"""Exercise the installed official Codex against an isolated local Responses fixture."""

import asyncio
from contextlib import AsyncExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from websockets.asyncio.client import unix_connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from model_guard.relay import Relay
from model_guard.check import probe
from model_guard.state import State


class ResponsesFixture:
    def __init__(self, model, reasoning=None, output_text="OK"):
        self.model, self.requests = model, []
        self.reasoning = reasoning or [0]
        self.output_text = output_text
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(request)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                if outer.model:
                    self.send_header("openai-model", outer.model)
                self.end_headers()
                for event in outer.events():
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)

    def events(self):
        index = len(self.requests) - 1
        tokens = self.reasoning[min(index, len(self.reasoning) - 1)]
        response_id = f"resp_test_{index}"
        item = {"id": "msg_test", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": self.output_text}]}
        return [
            {"type": "response.created", "response": {"id": response_id, "model": "gpt-4o"}},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": response_id, "status": "completed", "output": [item], "usage": {"input_tokens": 20, "output_tokens": tokens + 1, "output_tokens_details": {"reasoning_tokens": tokens}, "total_tokens": tokens + 21}}},
        ]

    async def websocket(self, ws):
        try:
            async for raw in ws:
                self.requests.append(json.loads(raw))
                if self.model:
                    await ws.send(json.dumps({"type": "response.metadata", "headers": {"X-OpenAI-Model": [self.model]}}))
                for event in self.events():
                    await ws.send(json.dumps(event))
        except ConnectionClosed:
            pass  # Codex can close its upstream socket without a close handshake.

    def __enter__(self):
        self.worker.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()


@unittest.skipUnless(os.environ.get("MODEL_GUARD_INTEGRATION") == "1", "set MODEL_GUARD_INTEGRATION=1 to exercise stock Codex")
class OfficialCodexTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, observed, websocket=False, probe_mode=False, reasoning=None, hidden_title=False):
        binary = os.environ.get("MODEL_GUARD_CODEX_BIN") or shutil.which("codex")
        with tempfile.TemporaryDirectory(prefix="mg-test-") as temp, ResponsesFixture(observed, reasoning) as api:
            base = Path(temp)
            codex_home = base / "codex"
            codex_home.mkdir()
            port = api.server.server_port
            stack = AsyncExitStack()
            if websocket:
                server = await stack.enter_async_context(serve(api.websocket, "127.0.0.1", 0))
                port = server.sockets[0].getsockname()[1]
            options = [
                "model='gpt-6-astra'", "model_provider='fixture'",
                "model_providers.fixture.name='Fixture'",
                f"model_providers.fixture.base_url='http://127.0.0.1:{port}/v1'",
                "model_providers.fixture.wire_api='responses'",
                "model_providers.fixture.requires_openai_auth=false",
                "model_providers.fixture.supports_websockets=" + str(websocket).lower(),
                "model_reasoning_effort='high'", "check_for_update_on_startup=false",
            ]
            cmd = [binary]
            for option in options:
                cmd += ["-c", option]
            cmd += ["app-server", "--stdio"]
            state = State()
            relay = Relay(cmd, state, temp)
            clean_env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "CODEX_"))}
            clean_env["CODEX_HOME"] = str(codex_home)
            with patch.dict(os.environ, clean_env, clear=True):
                if probe_mode:
                    try:
                        result = await probe(binary, model="gpt-6-astra", cwd=temp, options=cmd[1:-2])
                        self.assertEqual(result["exit_code"], 3 if observed is None else 2 if observed == "gpt-4o" else 0, str(result))
                        self.assertEqual(result["scope"], "separate_probe")
                        self.assertEqual(result["server_reported"], observed)
                        self.assertNotIn("account", result)
                    finally:
                        await stack.aclose()
                    return
                await relay.start()
            try:
                async with relay.serve(base / "rpc.sock"), unix_connect(str(base / "rpc.sock"), max_size=128 << 20) as ws:
                    await ws.send(json.dumps({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-tui", "version": "0.153.4"}, "capabilities": {"experimentalApi": True}}}))
                    await self.receive(ws, lambda msg: msg.get("id") == 1)
                    await ws.send(json.dumps({"method": "initialized"}))
                    await ws.send(json.dumps({"id": 2, "method": "thread/start", "params": {"model": "gpt-6-astra", "modelProvider": "fixture", "cwd": temp, "ephemeral": True, "approvalPolicy": "never", "sandbox": "read-only"}}))
                    response = await self.receive(ws, lambda msg: msg.get("id") == 2)
                    self.assertNotIn("error", response, str(response.get("error")))
                    tid = response["result"]["thread"]["id"]
                    for index in range(len(reasoning or [0])):
                        await ws.send(json.dumps({"id": 3 + index, "method": "turn/start", "params": {"threadId": tid, "input": [{"type": "text", "text": "Reply OK."}]}}))
                        await self.receive(ws, lambda msg: msg.get("method") == "turn/completed")
                    await asyncio.sleep(0.2)
                    snapshot = state.snapshot()
                    self.assertEqual(api.requests[-1]["model"], "gpt-6-astra")
                    if hidden_title:
                        await ws.send(json.dumps({"id": 100, "method": "thread/start", "params": {
                            "model": "gpt-5.6-luna", "modelProvider": "fixture", "cwd": temp,
                            "ephemeral": True, "threadSource": "system", "approvalPolicy": "never",
                            "sandbox": "read-only", "config": {"model_reasoning_effort": "low"}}}))
                        title = await self.receive(ws, lambda msg: msg.get("id") == 100)
                        self.assertNotIn("error", title)
                        hidden_id = title["result"]["thread"]["id"]
                        await ws.send(json.dumps({"id": 101, "method": "turn/start", "params": {
                            "threadId": hidden_id, "effort": "low", "input": [{"type": "text", "text": "Reply OK."}]}}))
                        await self.receive(ws, lambda msg: msg.get("method") == "turn/completed" and msg.get("params", {}).get("threadId") == hidden_id)
                        await asyncio.sleep(.2)
                        self.assertEqual(api.requests[-1]["model"], "gpt-5.6-luna")
                        self.assertEqual(state.snapshot()["thread"], snapshot["thread"])
                        self.assertEqual(state.selected, tid)
                    self.assertEqual(snapshot["thread"]["observed"], observed, str(snapshot))
                    self.assertIsNone(snapshot["account"])
                    self.assertEqual(snapshot["thread"]["mismatch"], observed if observed == "gpt-4o" else None)
                    if reasoning:
                        signal = snapshot["thread"]["reasoning"]
                        self.assertEqual(signal["samples"], len(reasoning))
                        self.assertEqual(signal["exact_516"], reasoning.count(516))
                        self.assertEqual(signal["last_tokens"], reasoning[-1])
                        self.assertEqual(signal["alert"], "suspect")
            finally:
                await relay.close()
                await stack.aclose()

    async def receive(self, ws, predicate):
        async with asyncio.timeout(40):
            async for raw in ws:
                msg = json.loads(raw)
                if predicate(msg):
                    return msg
        self.fail("Expected Codex response was not received")

    async def test_header_confirms_model(self):
        await self.exercise("gpt-6-astra")

    async def test_hidden_luna_title_does_not_replace_main_astra_thread(self):
        await self.exercise("gpt-6-astra", hidden_title=True)

    async def test_header_routes_to_gpt4o(self):
        await self.exercise("gpt-4o")

    async def test_response_model_without_header_is_unverified(self):
        await self.exercise(None)

    async def test_websocket_metadata_confirms_model(self):
        await self.exercise("gpt-6-astra", websocket=True)

    async def test_websocket_metadata_reports_reroute(self):
        await self.exercise("gpt-4o", websocket=True)

    async def test_websocket_without_metadata_is_unverified(self):
        await self.exercise(None, websocket=True)

    async def test_standalone_probe_checks_a_reported_match(self):
        await self.exercise("gpt-6-astra", probe_mode=True)

    async def test_standalone_probe_detects_gpt4o(self):
        await self.exercise("gpt-4o", websocket=True, probe_mode=True)

    async def test_standalone_probe_cannot_pass_without_evidence(self):
        await self.exercise(None, probe_mode=True)

    async def test_sse_reasoning_signal_without_model_disclosure(self):
        await self.exercise(None, reasoning=[516, 0, 516, 2000, 516])

    async def test_websocket_reasoning_signal_with_matching_model(self):
        await self.exercise("gpt-6-astra", websocket=True, reasoning=[516, 0, 516, 2000, 516])


if __name__ == "__main__":
    unittest.main()

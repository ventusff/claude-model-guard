"""Strict routing checks; only disclosed effective-model metadata can pass."""

import asyncio
import json
from pathlib import Path
import tempfile
import time

from websockets.asyncio.client import unix_connect
from websockets.exceptions import ConnectionClosed

from . import __version__
from .relay import MAX_MESSAGE, Relay, object_from_json
from .state import State, model_id
from .reasoning import Reasoning, alert_text, token_count, usage_text


EXIT_CODES = {"reported_match": 0, "reported_mismatch": 2, "unverified": 3, "unavailable": 4}


def verdict(snapshot, scope="current_session"):
    """Produce a shareable result without account identifiers or conversation data."""
    thread = snapshot.get("thread") or {}
    mismatch = model_id(thread.get("mismatch"))
    requested = model_id(thread.get("mismatch_requested")) if mismatch else model_id(thread.get("requested"))
    observed = mismatch or model_id(thread.get("observed"))
    source = thread.get("mismatch_source") if thread.get("mismatch") else thread.get("source")
    observed_at = thread.get("mismatch_at") if thread.get("mismatch") else thread.get("observed_at")
    health = snapshot.get("health")
    if health != "connected":
        status, reason = "unavailable", "observer_not_connected"
    elif not requested or not observed or source not in ("server-model-log", "model/rerouted"):
        status, reason = "unverified", "effective_model_not_disclosed"
    elif mismatch or requested.casefold() != observed.casefold():
        status, reason = "reported_mismatch", "server_reported_different_model"
    else:
        status, reason = "reported_match", "server_reported_matching_model"
    return {
        "status": status, "exit_code": EXIT_CODES[status], "reason": reason,
        "scope": scope, "requested": requested, "server_reported": observed,
        "current_requested": model_id(thread.get("requested")),
        "source": source if observed else None,
        "observed_at": observed_at if observed else None,
        "turn_running": thread.get("running") is True,
        "weights_verified": False,
        "reasoning": export_reasoning(thread.get("reasoning")),
    }


def export_reasoning(signal):
    if not isinstance(signal, dict):
        return None
    result = Reasoning().summary()
    for key, default in result.items():
        value = signal.get(key)
        if type(default) is int:
            result[key] = token_count(value) or 0
    result["last_tokens"] = token_count(signal.get("last_tokens"))
    result["alert"] = signal.get("alert") if signal.get("alert") in ("none", "watch", "suspect") else "none"
    effort = signal.get("effort")
    result["effort"] = effort if effort in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra") else None
    at = signal.get("observed_at")
    result["observed_at"] = at if type(at) in (float, int) and 0 <= at < 10**15 else None
    return result


class ProbeReader:
    """Correlate bidirectional RPC replies and early, thread-scoped completions."""

    def __init__(self, ws):
        self.ws = ws
        self.completed = {}

    async def response(self, rid):
        return await self.receive(lambda msg: "method" not in msg and msg.get("id") == rid)

    async def completion(self, thread, turn):
        key = (thread, turn)
        if key not in self.completed:
            await self.receive(lambda msg: key in self.completed)
        return self.completed.pop(key)

    async def receive(self, predicate):
        while True:
            msg = object_from_json(await self.ws.recv())
            if "method" in msg and "id" in msg:
                if msg["method"] in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                    response = {"id": msg["id"], "result": {"decision": "decline"}}
                else:
                    response = {"id": msg["id"], "error": {"code": -32601, "message": "Unavailable in a routing probe"}}
                await self.ws.send(json.dumps(response))
                continue  # Server request IDs live in a separate namespace.
            if msg.get("method") == "turn/completed":
                params = msg.get("params") or {}
                turn = params.get("turn") or {}
                key = (params.get("threadId"), turn.get("id"))
                if all(isinstance(value, str) and len(value) <= 120 for value in key):
                    if len(self.completed) >= 16:
                        self.completed.pop(next(iter(self.completed)))
                    self.completed[key] = {"status": turn.get("status")}
            if predicate(msg):
                if "error" in msg:
                    raise RuntimeError("probe_rpc_failed")
                return msg


async def probe(official, model=None, effort=None, timeout=120, cwd=None, options=()):
    """Run one ephemeral, read-only probe with the official CLI's own authentication.

    This is a separate request. It never certifies another session or changes its
    settings. Raw RPC traffic and stderr stay in memory and are not exported.
    """
    state = State(show_account=False)
    started = time.monotonic()
    result = None
    with tempfile.TemporaryDirectory(prefix="mg-probe-") as temp:
        root = Path(temp)
        relay = Relay([official, *options, "app-server", "--stdio"], state, cwd)

        try:
            async with asyncio.timeout(timeout):
                await relay.start()
                endpoint = root / "rpc.sock"
                async with relay.serve(endpoint), unix_connect(str(endpoint), max_size=MAX_MESSAGE) as ws:
                    reader = ProbeReader(ws)
                    await ws.send(json.dumps({"id": 1, "method": "initialize", "params": {
                        "clientInfo": {"name": "model-guard-probe", "version": __version__},
                        "capabilities": {"experimentalApi": True},
                    }}))
                    await reader.response(1)
                    await ws.send(json.dumps({"method": "initialized"}))
                    params = {"cwd": str(Path(cwd or Path.cwd()).absolute()), "ephemeral": True,
                              "approvalPolicy": "never", "sandbox": "read-only"}
                    if model:
                        params["model"] = model
                    await ws.send(json.dumps({"id": 2, "method": "thread/start", "params": params}))
                    start = await reader.response(2)
                    params = {"threadId": start["result"]["thread"]["id"], "input": [{
                        "type": "text", "text": "Reply exactly MODEL_GUARD_OK. Do not call any tools.",
                    }]}
                    if effort:
                        params["effort"] = effort
                    await ws.send(json.dumps({"id": 3, "method": "turn/start", "params": params}))
                    turn = await reader.response(3)
                    completion = await reader.completion(params["threadId"], turn["result"]["turn"]["id"])
                    if completion.get("status") != "completed":
                        raise RuntimeError("probe_turn_failed")
                    # Model logs and protocol messages travel through independent pipes.
                    await asyncio.sleep(.2)
                    result = verdict(state.snapshot(), "separate_probe")
        except TimeoutError:
            result = {**verdict({}, "separate_probe"), "reason": "probe_timeout"}
        except (OSError, RuntimeError, KeyError, ValueError, TypeError, ConnectionClosed):
            result = {**verdict({}, "separate_probe"), "reason": "probe_failed"}
        finally:
            await relay.close()
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return result


def format_result(result):
    model = result["server_reported"] or "not disclosed"
    signal = result.get("reasoning") or {}
    auxiliary = usage_text(signal)
    warning = alert_text(signal)
    if warning:
        auxiliary += " | " + warning + " (heuristic)"
    return (
        f"Routing: {result['status']}\n"
        f"Requested: {result['requested'] or 'unknown'}\n"
        f"Server reported: {model}\n"
        f"Evidence: {result['source'] or 'none'}\n"
        f"Scope: {result['scope']}\n"
        f"Reason: {result['reason']}\n"
        f"Reasoning: {auxiliary}\n"
        "Backend weights are not independently verified."
    )

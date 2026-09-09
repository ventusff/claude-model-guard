"""A local WebSocket/stdio adapter for the official app-server protocol."""

import asyncio
import json
import os
from pathlib import Path
import time
import uuid

from websockets.asyncio.server import unix_serve
from websockets.exceptions import ConnectionClosed

from .state import State


MAX_MESSAGE = 128 << 20  # Same ceiling as Codex's remote client.
LOG_FILTER = "off,codex_core::session=info,codex_core::session::turn=trace"


def object_from_json(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeError, RecursionError):
        return {}


class Relay:
    def __init__(self, command, state: State, cwd=None):
        self.command, self.state, self.cwd = command, state, cwd
        self.process = None
        self.websocket = None
        self.write_lock = asyncio.Lock()
        self.internal = {}
        self.account_pending = False
        self.last_account_request = 0
        self.last_limits_request = 0
        self.last_limits_epoch = None
        self.limits_pending = False
        self.initialized = False
        self.changed = asyncio.Event()
        self.id_prefix = "model-guard-" + uuid.uuid4().hex + "-"

    def observe(self, method, msg):
        try:
            getattr(self.state, method)(msg)
        except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
            # A changed metadata schema must not interrupt the user's TUI traffic.
            self.state.health = "unsupported metadata"

    async def start(self):
        env = dict(os.environ, RUST_LOG=LOG_FILTER, LOG_FORMAT="json")
        self.process = await asyncio.create_subprocess_exec(
            *self.command, cwd=self.cwd, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=MAX_MESSAGE + 1,
        )

    async def send(self, raw):
        async with self.write_lock:
            self.process.stdin.write(raw + b"\n")
            await self.process.stdin.drain()

    async def refresh_account(self):
        if self.account_pending or not self.initialized:
            return
        rid = self.id_prefix + uuid.uuid4().hex
        self.internal[rid] = ("account/read", self.state.auth_epoch, time.monotonic())
        self.account_pending = True
        self.last_account_request = time.monotonic()
        await self.send(json.dumps({"id": rid, "method": "account/read", "params": {"refreshToken": False}}).encode())

    async def refresh_limits(self):
        if self.limits_pending or not self.state.account or self.state.account.get("type") != "chatgpt":
            return
        if self.last_limits_epoch == self.state.auth_epoch and time.monotonic() - self.last_limits_request < 30:
            return
        self.last_limits_request = time.monotonic()
        self.last_limits_epoch = self.state.auth_epoch
        self.limits_pending = True
        rid = self.id_prefix + uuid.uuid4().hex
        self.internal[rid] = ("account/rateLimits/read", self.state.auth_epoch, time.monotonic())
        await self.send(json.dumps({"id": rid, "method": "account/rateLimits/read", "params": {}}).encode())

    async def from_client(self, ws):
        async for raw in ws:
            if isinstance(raw, str):
                raw = raw.encode()
            msg = object_from_json(raw)
            self.observe("client", msg)
            await self.send(raw)
            if msg.get("method") == "initialized":
                self.initialized = True
                await self.refresh_account()
            elif msg.get("method") == "turn/start":
                await self.refresh_account()
            self.changed.set()

    async def from_server(self, ws):
        while raw := await self.process.stdout.readline():
            msg = object_from_json(raw)
            rid = msg.get("id")
            if isinstance(rid, str) and rid.startswith(self.id_prefix):
                pending = self.internal.pop(rid, None)
                if not pending:
                    continue  # A timed-out internal response never reaches the TUI.
                method, epoch, _ = pending
                if method == "account/read":
                    self.account_pending = False
                    if epoch == self.state.auth_epoch and isinstance(msg.get("result"), dict):
                        self.state.set_account(msg["result"].get("account"))
                        await self.refresh_limits()
                    elif epoch != self.state.auth_epoch:
                        await self.refresh_account()
                else:
                    self.limits_pending = False
                    if epoch == self.state.auth_epoch and isinstance(msg.get("result"), dict):
                        self.state.set_limits(msg["result"].get("rateLimits"))
            else:
                self.observe("server", msg)
                await ws.send(raw.decode().rstrip("\r\n"))
            if msg.get("method") == "account/updated":
                await self.refresh_account()
            self.changed.set()

    async def logs(self):
        # stderr is consumed, never copied to a file. Model metadata is the only
        # log data retained; transport TRACE is deliberately disabled.
        while raw := await self.process.stderr.readline():
            self.observe("log", object_from_json(raw))
            self.changed.set()
        self.state.health = "model log ended"
        self.changed.set()

    async def poll(self):
        while True:
            await asyncio.sleep(15)
            self.expire_reads()
            if time.monotonic() - self.last_account_request > 14:
                await self.refresh_account()

    def expire_reads(self):
        for rid, (method, _, started) in list(self.internal.items()):
            if time.monotonic() - started < 30:
                continue
            del self.internal[rid]
            if method == "account/read":
                self.account_pending = False
                self.state.set_account(None)
            else:
                self.limits_pending = False
                self.state.limits = {}
            self.changed.set()

    async def handle(self, ws):
        if self.websocket is not None:
            await ws.close(1008, "One Codex TUI per guard session")
            return
        self.websocket = ws
        traffic = [asyncio.create_task(fn(ws)) for fn in (self.from_client, self.from_server)]
        jobs = traffic + [asyncio.create_task(self.logs()), asyncio.create_task(self.poll())]
        try:
            done, _ = await asyncio.wait(traffic, return_when=asyncio.FIRST_COMPLETED)
            for job in done:
                job.result()
        except (ConnectionClosed, BrokenPipeError, ConnectionError):
            pass
        except Exception:
            # Raw exceptions may include protocol payloads; report only a fixed state.
            self.state.health = "protocol error"
        finally:
            if self.state.health != "protocol error":
                self.state.health = "disconnected"
            self.changed.set()
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            await ws.close()

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()

    def serve(self, path: Path):
        return unix_serve(
            self.handle, str(path), origins=[None], compression=None,
            max_size=MAX_MESSAGE, max_queue=8, close_timeout=1,
        )

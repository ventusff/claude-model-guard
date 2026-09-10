"""A local WebSocket-to-stdio adapter around one official app-server process.

Only the explicit probe uses it. Protocol traffic passes through unchanged;
allowlisted metadata is observed on the way.
"""

import asyncio
import json
import os
from pathlib import Path

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

    def observe(self, method, msg):
        try:
            getattr(self.state, method)(msg)
        except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
            # A changed metadata schema must not interrupt the protocol traffic.
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

    async def from_client(self, ws):
        async for raw in ws:
            if isinstance(raw, str):
                raw = raw.encode()
            self.observe("client", object_from_json(raw))
            await self.send(raw)

    async def from_server(self, ws):
        while raw := await self.process.stdout.readline():
            self.observe("server", object_from_json(raw))
            await ws.send(raw.decode().rstrip("\r\n"))

    async def logs(self):
        # stderr is consumed, never copied to a file. Model metadata is the only
        # log data retained; transport TRACE is deliberately disabled.
        while raw := await self.process.stderr.readline():
            self.observe("log", object_from_json(raw))
        self.state.health = "model log ended"

    async def handle(self, ws):
        if self.websocket is not None:
            await ws.close(1008, "One client per relay")
            return
        self.websocket = ws
        traffic = [asyncio.create_task(fn(ws)) for fn in (self.from_client, self.from_server)]
        jobs = traffic + [asyncio.create_task(self.logs())]
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

import time
import unittest
from unittest.mock import AsyncMock

from model_guard.relay import Relay
from model_guard.state import State


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_limit_read_still_obeys_poll_interval(self):
        state = State()
        state.set_account({"type": "chatgpt", "email": "a@example.com", "planType": "pro"})
        relay = Relay([], state)
        relay.send = AsyncMock()
        await relay.refresh_limits()
        relay.limits_pending = False
        await relay.refresh_limits()
        self.assertEqual(relay.send.await_count, 1)
        state.set_account({"type": "chatgpt", "email": "b@example.com", "planType": "pro"})
        await relay.refresh_limits()
        self.assertEqual(relay.send.await_count, 2)

    async def test_timed_out_identity_read_clears_account(self):
        state = State()
        state.set_account({"type": "chatgpt", "email": "a@example.com", "planType": "pro"})
        relay = Relay([], state)
        relay.internal["request"] = ("account/read", state.auth_epoch, time.monotonic() - 31)
        relay.account_pending = True
        relay.expire_reads()
        self.assertIsNone(state.account)
        self.assertFalse(relay.account_pending)
        self.assertEqual(relay.internal, {})

    async def test_malformed_metadata_does_not_raise_into_transport(self):
        relay = Relay([], State())
        relay.state.client({"id": 1, "method": "thread/start"})
        relay.observe("server", {"id": 1, "result": {"thread": 123}})
        self.assertEqual(relay.state.health, "unsupported metadata")


if __name__ == "__main__":
    unittest.main()

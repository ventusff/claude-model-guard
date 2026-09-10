import unittest

from model_guard.relay import Relay
from model_guard.state import State


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_metadata_does_not_raise_into_transport(self):
        relay = Relay([], State())
        relay.state.client({"id": 1, "method": "thread/start"})
        relay.observe("server", {"id": 1, "result": {"thread": 123}})
        self.assertEqual(relay.state.health, "unsupported metadata")


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from model_guard.check import ProbeReader, format_result, verdict
from model_guard.state import State


class CheckTests(unittest.TestCase):
    def state(self):
        state = State(health="connected")
        thread = state.thread("t1")
        state.selected = thread.id
        thread.settings({"model": "gpt-6-astra", "modelProvider": "openai"})
        thread.begin_turn("turn1")
        return state, thread

    def test_missing_evidence_cannot_succeed(self):
        state, _ = self.state()
        self.assertEqual(verdict(state.snapshot())["exit_code"], 3)
        self.assertEqual(verdict({})["exit_code"], 4)

    def test_export_carries_routing_fields_only(self):
        state, thread = self.state()
        thread.observe("gpt-6-astra", "server-model-log")
        result = verdict(state.snapshot())
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["weights_verified"])
        self.assertFalse({"account", "email", "plan", "limits"} & set(result))

    def test_mismatch_keeps_its_provenance_after_new_sampling(self):
        state, thread = self.state()
        thread.observe("gpt-4o", "model/rerouted")
        state.log({"target": "codex_core::session::turn", "fields": {"message": "new"},
                   "span": {"name": "try_run_sampling_request", "turn_id": "turn1", "model": "gpt-6-astra"},
                   "spans": [{"thread_id": "t1"}]})
        result = verdict(state.snapshot())
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["source"], "model/rerouted")
        self.assertEqual(result["server_reported"], "gpt-4o")
        self.assertIsNotNone(result["observed_at"])
        thread.requested = "gpt-4o"
        result = verdict(state.snapshot())
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["requested"], "gpt-6-astra")
        self.assertEqual(result["current_requested"], "gpt-4o")
        thread.begin_turn("turn2")
        self.assertEqual(verdict(state.snapshot())["exit_code"], 3)

    def test_synthetic_or_body_identity_is_not_verified(self):
        state, thread = self.state()
        for source in ("response.model", "synthetic-demo", "model-self-identification"):
            thread.observe("gpt-6-astra", source)
            self.assertEqual(verdict(state.snapshot())["exit_code"], 3)

    def test_body_label_lines_in_the_text_report(self):
        state, thread = self.state()
        self.assertIn("Body label: none", format_result(verdict(state.snapshot())))
        thread.observe_label("gpt-6-astra-2026-09-01")
        self.assertIn("Body label: gpt-6-astra-2026-09-01 (consistent with the request)", format_result(verdict(state.snapshot())))
        thread.observe_label("gpt-4o")
        text = format_result(verdict(state.snapshot()))
        self.assertIn("Routing: label_mismatch", text)
        self.assertIn("Body label: gpt-4o (differs from the request)", text)


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def recv(self):
        return json.dumps(next(self.messages))

    async def send(self, raw):
        self.sent.append(json.loads(raw))


class ProbeReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_request_id_cannot_satisfy_client_response(self):
        socket = FakeSocket([
            {"id": 3, "method": "item/commandExecution/requestApproval", "params": {}},
            {"id": 3, "result": {"turn": {"id": "own-turn"}}},
        ])
        result = await ProbeReader(socket).response(3)
        self.assertEqual(result["result"]["turn"]["id"], "own-turn")
        self.assertEqual(socket.sent, [{"id": 3, "result": {"decision": "decline"}}])

    async def test_child_completion_cannot_finish_parent_probe(self):
        socket = FakeSocket([
            {"method": "turn/completed", "params": {"threadId": "child", "turn": {"id": "t2", "status": "completed"}}},
            {"method": "turn/completed", "params": {"threadId": "parent", "turn": {"id": "t1", "status": "failed"}}},
        ])
        self.assertEqual(await ProbeReader(socket).completion("parent", "t1"), {"status": "failed"})

    async def test_early_completion_is_retained_by_thread_and_turn(self):
        socket = FakeSocket([
            {"method": "turn/completed", "params": {"threadId": "parent", "turn": {"id": "old", "status": "failed"}}},
            {"method": "turn/completed", "params": {"threadId": "parent", "turn": {"id": "new", "status": "completed", "items": ["private text"]}}},
            {"id": 3, "result": {"turn": {"id": "new"}}},
        ])
        reader = ProbeReader(socket)
        await reader.response(3)
        self.assertNotIn("private text", str(reader.completed))
        self.assertEqual(await reader.completion("parent", "new"), {"status": "completed"})

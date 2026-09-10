import unittest

from model_guard.check import verdict
from model_guard.state import State, label_consistent


class StateTests(unittest.TestCase):
    def setUp(self):
        self.s = State(health="connected")
        self.s.client({"id": 1, "method": "thread/start"})
        self.s.server({"id": 1, "result": {"thread": {"id": "t1"}, "model": "gpt-6-astra", "modelProvider": "openai", "reasoningEffort": "high"}})
        self.event("turn/started", turn={"id": "turn1"})

    def event(self, method, **data):
        self.s.server({"method": method, "params": {"threadId": "t1", **data}})

    def log(self, actual="gpt-6-astra", tid="t1", turn="turn1"):
        self.s.log({"target": "codex_core::session", "fields": {"message": f"server reported model {actual} (matches requested model)"}, "spans": [{"thread_id": tid}, {"turn_id": turn, "model": "gpt-6-astra"}]})

    def routing(self, server=None, label=None, turn="turn1", requested="gpt-6-astra"):
        self.event("model/routing/updated", turnId=turn, requestedModel=requested, serverModel=server,
                   responseLabel=label, modelProvider="openai", reasoningEffort="max")

    def test_selected_model_is_not_evidence(self):
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])
        self.assertEqual(verdict(self.s.snapshot())["status"], "unverified")

    def test_real_report_matches(self):
        self.log()
        self.assertEqual(self.s.snapshot()["thread"]["observed"], "gpt-6-astra")
        self.assertEqual(verdict(self.s.snapshot())["status"], "reported_match")

    def test_gpt4o_reroute_is_reported(self):
        self.event("model/rerouted", turnId="turn1", fromModel="gpt-6-astra", toModel="gpt-4o", reason="highRiskCyberActivity")
        self.assertEqual(verdict(self.s.snapshot())["status"], "reported_mismatch")

    def test_latched_mismatch_retains_original_models_after_new_sampling(self):
        thread = self.s.threads["t1"]
        thread.observe("gpt-4o", "model/rerouted")
        thread.requested = "gpt-4o"
        thread.observed = None
        result = verdict(self.s.snapshot())
        self.assertEqual((result["requested"], result["server_reported"]), ("gpt-6-astra", "gpt-4o"))
        thread.requested = "gpt-6-astra"
        thread.observe("gpt-6-astra", "server-model-log")
        self.assertEqual(verdict(self.s.snapshot())["status"], "reported_mismatch")

    def test_native_routing_is_authoritative_over_delayed_legacy_logs(self):
        self.routing(server="gpt-6-astra")
        self.log("gpt-4o")
        result = verdict(self.s.snapshot())
        self.assertEqual((result["status"], result["source"]), ("reported_match", "model/routing/updated"))

    def test_body_label_is_a_second_tier_signal(self):
        self.routing(label="gpt-6-astra-2026-09-01")
        result = verdict(self.s.snapshot())
        self.assertEqual((result["status"], result["body_label"], result["body_label_consistent"]),
                         ("unverified", "gpt-6-astra-2026-09-01", True))
        self.routing(label="gpt-4o")
        result = verdict(self.s.snapshot())
        self.assertEqual((result["status"], result["exit_code"], result["body_label_consistent"]), ("label_mismatch", 5, False))
        self.assertIsNone(result["server_reported"])
        # A later request without a label keeps the latched difference through the turn,
        # and the export names the request the label differed from.
        self.routing(requested="gpt-4o")
        result = verdict(self.s.snapshot())
        self.assertEqual((result["status"], result["requested"], result["current_requested"]),
                         ("label_mismatch", "gpt-6-astra", "gpt-4o"))
        # A disclosed effective model decides the strict status, in either direction.
        self.routing(server="gpt-6-astra", label="gpt-4o")
        result = verdict(self.s.snapshot())
        self.assertEqual((result["status"], result["body_label_consistent"]), ("reported_match", False))
        self.routing(server="gpt-4o", label="gpt-4o")
        self.assertEqual(verdict(self.s.snapshot())["exit_code"], 2)
        self.event("turn/completed", turn={"id": "turn1"})
        self.event("turn/started", turn={"id": "turn2"})
        self.assertEqual(verdict(self.s.snapshot())["body_label"], None)

    def test_label_consistency_rule_matches_the_native_build(self):
        for requested, label, expected in [
            ("gpt-6-astra", "gpt-6-astra", True),
            ("GPT-6-Astra", "gpt-6-astra", True),
            ("gpt-6-astra", "gpt-6-astra-2026-09-01", True),
            ("gpt-6-astra", "gpt-6", True),
            ("gpt-5.6-sol", "gpt-5.6-sol-codex", True),
            ("gpt-6-astra", "gpt-4o", False),
            ("gpt-6-astra", "gpt-6-astra-mini", False),
            ("gpt-6-astra", "gpt-6-astrax", False),
            ("gpt-6-astra", "gpt-5.6-sol", False),
        ]:
            with self.subTest(requested=requested, label=label):
                self.assertEqual(label_consistent(requested, label), expected)

    def test_child_and_delayed_events_do_not_change_parent(self):
        self.log("gpt-4o", tid="agent")
        self.log("gpt-4o", turn="old")
        self.event("model/rerouted", turnId="old", toModel="gpt-4o")
        self.routing(label="gpt-4o", turn="old")
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])
        self.assertIsNone(self.s.snapshot()["thread"]["body_label"])

    def test_hidden_title_request_cannot_replace_visible_model_or_usage(self):
        original = self.s.snapshot()["thread"]
        for request_source, response_source in (("system", None), (None, "system"),
                                                ("system", "system")):
            self.s.client({"id": "title", "method": "thread/start", "params": {
                "model": "gpt-5.6-luna", "ephemeral": True, "threadSource": request_source}})
            self.s.server({"id": "title", "result": {
                "thread": {"id": "hidden", "threadSource": response_source},
                "model": "gpt-5.6-luna", "modelProvider": "openai", "reasoningEffort": "low"}})
            self.s.client({"id": "title-turn", "method": "turn/start", "params": {"threadId": "hidden"}})
            self.s.server({"method": "turn/started", "params": {"threadId": "hidden", "turn": {"id": "title-turn"}}})
            self.s.server({"method": "thread/tokenUsage/updated", "params": {
                "threadId": "hidden", "turnId": "title-turn", "tokenUsage": {
                    "last": {"totalTokens": 600, "reasoningOutputTokens": 516},
                    "total": {"totalTokens": 600, "reasoningOutputTokens": 516}}}})
            self.log("gpt-4o", tid="hidden", turn="title-turn")
            self.assertEqual(self.s.snapshot()["thread"], original)
            self.assertNotIn("hidden", self.s.threads)
            self.assertNotIn("title", self.s.pending)

    def test_visible_ephemeral_user_thread_is_still_monitored(self):
        self.s.client({"id": 2, "method": "thread/start", "params": {
            "ephemeral": True, "threadSource": "user"}})
        self.s.server({"id": 2, "result": {"thread": {"id": "visible", "threadSource": "user"},
                                             "model": "gpt-5.6-luna", "reasoningEffort": "low"}})
        self.assertEqual(self.s.snapshot()["thread"]["id"], "visible")
        self.assertEqual(self.s.snapshot()["thread"]["requested"], "gpt-5.6-luna")

    def test_new_turn_does_not_reuse_previous_confirmation(self):
        self.log()
        self.event("turn/completed", turn={"id": "turn1"})
        self.assertFalse(self.s.snapshot()["thread"]["running"])
        self.event("turn/started", turn={"id": "turn2"})
        self.assertEqual(verdict(self.s.snapshot())["status"], "unverified")

    def test_model_switch_invalidates_evidence(self):
        self.log()
        self.event("turn/completed", turn={"id": "turn1"})
        self.event("thread/settings/updated", threadSettings={"model": "gpt-5.6-sol"})
        self.assertEqual(verdict(self.s.snapshot())["status"], "unverified")

    def test_next_model_setting_does_not_relabel_inflight_request(self):
        self.log()
        self.event("thread/settings/updated", threadSettings={"model": "gpt-5.6-sol"})
        self.assertEqual(self.s.snapshot()["thread"]["requested"], "gpt-6-astra")
        self.event("turn/started", turn={"id": "turn2"})
        self.assertEqual(self.s.snapshot()["thread"]["requested"], "gpt-5.6-sol")
        self.assertEqual(verdict(self.s.snapshot())["status"], "unverified")

    def test_log_arrives_before_turn_notification(self):
        self.log(turn="turn2")
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])
        self.event("turn/started", turn={"id": "turn2"})
        self.assertEqual(self.s.snapshot()["thread"]["observed"], "gpt-6-astra")

    def test_nullable_reasoning_setting_does_not_keep_old_effort(self):
        self.event("turn/completed", turn={"id": "turn1"})
        self.event("thread/settings/updated", threadSettings={"effort": None})
        self.assertEqual(self.s.snapshot()["thread"]["effort"], "")

    def test_assistant_text_is_not_evidence(self):
        self.event("item/agentMessage/delta", delta="server reported model gpt-4o while requested model was gpt-6-astra")
        self.s.log({"target": "codex_api::sse", "fields": {"message": "server reported model gpt-4o (matches requested model)"}})
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])

    def test_snapshot_carries_no_account_or_credential_fields(self):
        self.event("account/updated", authMode="chatgpt")
        self.event("account/rateLimits/updated", rateLimits={"primary": {"usedPercent": 99}})
        snapshot = self.s.snapshot()
        self.assertEqual(set(snapshot), {"schema", "health", "updated_at", "thread"})


if __name__ == "__main__":
    unittest.main()

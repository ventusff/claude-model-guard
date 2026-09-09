import unittest

from model_guard.state import State, fit, render, tmux_band


class StateTests(unittest.TestCase):
    def setUp(self):
        self.s = State()
        self.s.client({"id": 1, "method": "thread/start"})
        self.s.server({"id": 1, "result": {"thread": {"id": "t1"}, "model": "gpt-6-astra", "modelProvider": "openai", "reasoningEffort": "high"}})
        self.event("turn/started", turn={"id": "turn1"})

    def event(self, method, **data):
        self.s.server({"method": method, "params": {"threadId": "t1", **data}})

    def log(self, actual="gpt-6-astra", tid="t1", turn="turn1"):
        self.s.log({"target": "codex_core::session", "fields": {"message": f"server reported model {actual} (matches requested model)"}, "spans": [{"thread_id": tid}, {"turn_id": turn, "model": "gpt-6-astra"}]})

    def test_selected_model_is_not_evidence(self):
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])
        self.assertEqual(render(self.s.snapshot())[0], "unknown")

    def test_real_report_matches(self):
        self.log()
        self.assertEqual(self.s.snapshot()["thread"]["observed"], "gpt-6-astra")
        self.assertEqual(render(self.s.snapshot())[0], "ok")

    def test_gpt4o_reroute_is_alarm(self):
        self.event("model/rerouted", turnId="turn1", fromModel="gpt-6-astra", toModel="gpt-4o", reason="highRiskCyberActivity")
        color, text = render(self.s.snapshot())
        self.assertEqual(color, "alarm")
        self.assertIn("gpt-6-astra → gpt-4o", text)

    def test_latched_mismatch_retains_original_models_in_band(self):
        thread = self.s.threads["t1"]
        thread.observe("gpt-4o", "model/rerouted")
        thread.requested = "gpt-4o"
        thread.observed = None
        color, text = render(self.s.snapshot())
        self.assertEqual(color, "alarm")
        self.assertIn("gpt-6-astra → gpt-4o", text)
        self.assertIn("current=?", text)
        band, _ = tmux_band(self.s.snapshot(), width=56)
        self.assertIn("gpt-4o | req gpt-6-astra", band)
        thread.requested = "gpt-6-astra"
        thread.observe("gpt-6-astra", "server-model-log")
        self.assertIn("gpt-6-astra → gpt-4o", render(self.s.snapshot())[1])

    def test_child_and_delayed_events_do_not_change_parent(self):
        self.log("gpt-4o", tid="agent")
        self.log("gpt-4o", turn="old")
        self.event("model/rerouted", turnId="old", toModel="gpt-4o")
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])

    def test_new_turn_does_not_reuse_previous_confirmation(self):
        self.log()
        self.event("turn/completed", turn={"id": "turn1"})
        self.assertIn("last turn", render(self.s.snapshot())[1])
        self.event("turn/started", turn={"id": "turn2"})
        self.assertEqual(render(self.s.snapshot())[0], "unknown")

    def test_model_switch_invalidates_evidence(self):
        self.log()
        self.event("turn/completed", turn={"id": "turn1"})
        self.event("thread/settings/updated", threadSettings={"model": "gpt-5.6-sol"})
        self.assertEqual(render(self.s.snapshot())[0], "unknown")

    def test_next_model_setting_does_not_relabel_inflight_request(self):
        self.log()
        self.event("thread/settings/updated", threadSettings={"model": "gpt-5.6-sol"})
        self.assertEqual(self.s.snapshot()["thread"]["requested"], "gpt-6-astra")
        self.event("turn/started", turn={"id": "turn2"})
        self.assertEqual(self.s.snapshot()["thread"]["requested"], "gpt-5.6-sol")
        self.assertEqual(render(self.s.snapshot())[0], "unknown")

    def test_log_arrives_before_turn_notification(self):
        self.log(turn="turn2")
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])
        self.event("turn/started", turn={"id": "turn2"})
        self.assertEqual(self.s.snapshot()["thread"]["observed"], "gpt-6-astra")

    def test_streaming_limits_cannot_reintroduce_previous_account_usage(self):
        self.s.set_account({"type": "chatgpt", "email": "new@example.com", "planType": "pro"})
        self.event("account/rateLimits/updated", rateLimits={"primary": {"usedPercent": 99, "windowDurationMins": 300}})
        self.assertEqual(self.s.snapshot()["limits"], {})

    def test_fresh_quota_snapshot_replaces_missing_windows(self):
        self.s.set_account({"type": "chatgpt", "email": "a@example.com", "planType": "pro"})
        self.s.set_limits({"primary": {"usedPercent": 92, "windowDurationMins": 300}})
        self.s.set_limits({"primary": None, "secondary": {"usedPercent": 10, "windowDurationMins": 10080}})
        self.assertEqual(set(self.s.snapshot()["limits"]), {"secondary"})

    def test_account_identity_change_invalidates_pending_reads_without_notification(self):
        self.s.set_account({"type": "chatgpt", "email": "a@example.com", "planType": "pro"})
        epoch = self.s.auth_epoch
        self.s.client({"id": 17, "method": "account/read"})
        self.s.set_account({"type": "chatgpt", "email": "b@example.com", "planType": "pro"})
        self.s.server({"id": 17, "result": {"account": {"type": "chatgpt", "email": "a@example.com", "planType": "pro"}}})
        self.assertGreater(self.s.auth_epoch, epoch)
        self.assertEqual(self.s.snapshot()["account"]["email"], "b@example.com")

    def test_nullable_reasoning_setting_does_not_keep_old_effort(self):
        self.event("turn/completed", turn={"id": "turn1"})
        self.event("thread/settings/updated", threadSettings={"effort": None})
        self.assertEqual(self.s.snapshot()["thread"]["effort"], "")

    def test_assistant_text_is_not_evidence(self):
        self.event("item/agentMessage/delta", delta="server reported model gpt-4o while requested model was gpt-6-astra")
        self.s.log({"target": "codex_api::sse", "fields": {"message": "server reported model gpt-4o (matches requested model)"}})
        self.assertIsNone(self.s.snapshot()["thread"]["observed"])

    def test_account_switch_clears_usage(self):
        self.s.set_account({"type": "chatgpt", "email": "a@example.com", "planType": "pro", "access_token": "secret"})
        self.s.set_limits({"primary": {"usedPercent": 92, "windowDurationMins": 300}})
        self.assertNotIn("secret", str(self.s.snapshot()))
        self.s.set_account({"type": "chatgpt", "email": "b@example.com", "planType": "pro"})
        self.assertEqual(self.s.snapshot()["limits"], {})
        self.event("account/updated", authMode="chatgpt")
        self.assertIsNone(self.s.snapshot()["account"])

    def test_custom_provider_cannot_claim_openai_account(self):
        self.s.set_account({"type": "chatgpt", "email": "a@example.com", "planType": "pro"})
        self.event("thread/settings/updated", threadSettings={"modelProvider": "custom"})
        self.event("turn/started", turn={"id": "turn2"})
        self.assertIsNone(self.s.snapshot()["account"])

    def test_metadata_cannot_execute_tmux_commands(self):
        self.s.set_account({"type": "chatgpt", "email": "#(touch /tmp/pwn)#[bg=green]\u001b]2;evil\u0007", "planType": "pro"})
        band, _ = tmux_band(self.s.snapshot(), row=1)
        self.assertNotIn("#(", band)
        self.assertNotIn("#[bg=green]", band)
        self.assertNotIn("\u001b", band)

    def test_narrow_terminal_keeps_route_first(self):
        self.event("model/rerouted", turnId="turn1", toModel="gpt-4o")
        band, _ = tmux_band(self.s.snapshot(), width=44)
        self.assertIn("gpt-4o", band)
        self.assertEqual(fit("路由x", 6), "路由x ")


if __name__ == "__main__":
    unittest.main()

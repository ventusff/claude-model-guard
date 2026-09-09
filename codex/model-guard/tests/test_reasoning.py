import unittest

from model_guard.check import verdict
from model_guard.reasoning import Reasoning
from model_guard.state import State


def usage(tokens, total, size=4000):
    return {"last": {"totalTokens": size, "outputTokens": 3000, "reasoningOutputTokens": tokens},
            "total": {"totalTokens": total}}


SCOPE = ("gpt-6-astra", "openai", "high", "")


class ReasoningTests(unittest.TestCase):
    def test_repeated_notifications_are_not_repeated_responses(self):
        signal = Reasoning()
        for _ in range(10):
            signal.observe(usage(516, 4000), SCOPE)
        self.assertEqual(signal.summary()["samples"], 1)
        self.assertEqual(signal.summary()["alert"], "watch")

    def test_identical_counts_from_distinct_responses_do_count(self):
        signal = Reasoning()
        for index in range(1, 6):
            signal.observe(usage(516, 4000 * index), SCOPE)
        result = signal.summary()
        self.assertEqual(result["samples"], 5)
        self.assertEqual(result["exact_516"], 5)
        self.assertEqual(result["alert"], "suspect")

    def test_higher_ladder_rungs_do_not_trigger_516_alert(self):
        signal = Reasoning()
        for index, tokens in enumerate([1034, 1552, 2070, 2588, 1034], 1):
            signal.observe(usage(tokens, 4000 * index), SCOPE)
        self.assertEqual(signal.summary()["ladder_hits"], 5)
        self.assertEqual(signal.summary()["alert"], "none")

    def test_low_effort_retains_observations_without_alarm(self):
        for effort in ("none", "minimal", "low", "medium", ""):
            with self.subTest(effort=effort):
                signal = Reasoning()
                for index in range(1, 6):
                    signal.observe(usage(516, index * 4000), ("gpt-6-astra", "openai", effort, ""))
                self.assertEqual(signal.summary()["exact_516"], 5)
                self.assertEqual(signal.summary()["alert"], "none")

    def test_missing_invalid_and_zero_are_distinct(self):
        for value in (None, "516", -516, 516.0, True, 10**15, 3001):
            with self.subTest(value=value):
                signal = Reasoning()
                signal.observe(usage(value, 4000), SCOPE)
                self.assertIsNone(signal.summary()["last_tokens"])
                self.assertEqual(signal.summary()["samples"], 0)
        signal = Reasoning()
        signal.observe(usage(0, 4000), SCOPE)
        self.assertEqual(signal.summary()["last_tokens"], 0)
        self.assertEqual(signal.summary()["samples"], 1)

    def test_replay_context_recomputation_and_rollback_are_not_completions(self):
        signal = Reasoning(total=None)
        signal.observe(usage(516, 16000), SCOPE)  # Attached history.
        self.assertEqual(signal.summary()["samples"], 0)
        signal.observe(usage(516, 20000), SCOPE)
        signal.observe(usage(0, 20000, size=7000), SCOPE)  # Context recomputation.
        self.assertEqual(signal.summary()["samples"], 1)
        signal.attach()  # Explicit accepted rollback, not an inferred decrease.
        signal.observe(usage(516, 8000), SCOPE)
        self.assertEqual(signal.summary()["samples"], 0)
        signal.observe(usage(0, 12000), SCOPE)
        self.assertEqual(signal.summary()["samples"], 1)

    def test_delayed_same_turn_snapshots_cannot_clear_history_or_recount(self):
        signal = Reasoning()
        for index in range(1, 6):
            signal.observe(usage(516, index * 4000), SCOPE)
        signal.observe(usage(516, 16000), SCOPE)
        signal.observe(usage(516, 20000), SCOPE)
        self.assertEqual(signal.summary()["samples"], 5)
        self.assertEqual(signal.summary()["alert"], "suspect")

    def test_scope_change_clears_samples_without_counting_replayed_usage(self):
        signal = Reasoning()
        signal.observe(usage(516, 4000), SCOPE)
        signal.activate(("gpt-6-astra", "openai", "low", ""))
        signal.observe(usage(516, 4000), signal.scope)
        self.assertEqual(signal.summary()["samples"], 0)
        signal.observe(usage(0, 8000), signal.scope)
        self.assertEqual(signal.summary()["samples"], 1)

    def test_rolling_window_and_turn_history_are_bounded(self):
        signal = Reasoning()
        for index in range(1, 31):
            signal.observe(usage(516 if index <= 5 else 0, index * 4000), SCOPE)
        self.assertEqual(signal.summary()["samples"], 20)
        self.assertEqual(signal.summary()["exact_516"], 0)
        self.assertEqual(signal.summary()["turn_516"], 5)
        self.assertEqual(signal.summary()["alert"], "watch")
        signal.begin_turn()
        self.assertEqual(signal.summary()["alert"], "none")
        self.assertEqual(signal.summary()["samples"], 20)


class ReasoningStateTests(unittest.TestCase):
    def setUp(self):
        self.state = State(health="connected")
        self.state.set_account({"type": "chatgpt", "email": "private@example.com", "planType": "pro"})
        self.thread = self.state.thread("t")
        self.state.selected = "t"
        self.thread.settings({"model": "gpt-6-astra", "modelProvider": "openai", "effort": "high"})
        self.thread.begin_turn("turn")

    def event(self, method, **params):
        self.state.server({"method": method, "params": {"threadId": "t", **params}})

    def count(self, tokens=516, index=1, **params):
        self.event("thread/tokenUsage/updated", turnId="turn", tokenUsage=usage(tokens, index * 4000), **params)

    def test_heuristic_is_visible_without_claiming_a_route(self):
        for index, tokens in enumerate([516, 0, 516, 2000, 516], 1):
            self.count(tokens, index)
        result = verdict(self.state.snapshot())
        self.assertEqual(result["exit_code"], 3)
        self.assertEqual(result["reasoning"]["alert"], "suspect")
        self.assertIsNone(result["server_reported"])
        self.assertNotIn("private", str(result))
        self.assertNotIn("scope", result["reasoning"])
        self.assertEqual((result["reasoning"]["recent_516"], result["reasoning"]["recent_samples"]), (3, 5))

    def test_old_turn_and_child_usage_cannot_contaminate_parent(self):
        self.state.server({"method": "thread/tokenUsage/updated", "params": {"threadId": "child", "turnId": "turn", "tokenUsage": usage(516, 4000)}})
        self.event("thread/tokenUsage/updated", turnId="old", tokenUsage=usage(516, 4000))
        self.assertEqual(self.thread.reasoning.summary()["samples"], 0)
        self.count()
        self.event("turn/completed", turn={"id": "turn"})
        self.count(index=2)
        self.assertEqual(self.thread.reasoning.summary()["samples"], 1)

    def test_mid_turn_hit_remains_visible_after_a_normal_final_response(self):
        self.count()
        self.count(2000, 2)
        self.event("turn/completed", turn={"id": "turn"})
        signal = self.thread.reasoning.summary()
        self.assertEqual(signal["last_tokens"], 2000)
        self.assertEqual(signal["turn_516"], 1)
        self.assertEqual(signal["alert"], "watch")

    def test_settings_for_next_turn_do_not_rebucket_running_response(self):
        self.count()
        self.event("thread/settings/updated", threadSettings={"model": "gpt-5.6-sol", "effort": "low", "serviceTier": "fast"})
        self.count(index=2)
        self.assertEqual(self.thread.reasoning.summary()["effort"], "high")
        self.assertEqual(self.thread.reasoning.summary()["samples"], 2)
        self.assertEqual(self.state.snapshot()["thread"]["effort"], "high")
        self.thread.begin_turn("next")
        self.assertEqual(self.thread.reasoning.summary()["samples"], 0)

    def test_future_provider_does_not_rebucket_running_response(self):
        self.count()
        self.event("thread/settings/updated", threadSettings={"modelProvider": "custom"})
        self.count(index=2)
        self.assertEqual(self.thread.reasoning.scope[1], "openai")
        self.assertEqual(self.thread.reasoning.summary()["samples"], 2)
        self.thread.begin_turn("next")
        self.assertEqual(self.thread.reasoning.summary()["samples"], 0)

    def test_future_openai_provider_cannot_expose_account_on_custom_turn(self):
        self.thread.settings({"modelProvider": "custom"})
        self.thread.begin_turn("custom-turn")
        self.event("thread/settings/updated", threadSettings={"modelProvider": "openai"})
        self.assertIsNone(self.state.snapshot()["account"])
        self.event("turn/completed", turn={"id": "custom-turn"})
        self.assertIsNone(self.state.snapshot()["account"])
        self.thread.begin_turn("openai-turn")
        self.assertIsNotNone(self.state.snapshot()["account"])

    def test_completed_turn_retains_measured_settings_until_idle_selection(self):
        for index in range(1, 6):
            self.count(index=index)
        self.event("thread/settings/updated", threadSettings={"effort": "low", "serviceTier": "fast"})
        self.event("turn/completed", turn={"id": "turn"})
        self.assertEqual(self.state.snapshot()["thread"]["effort"], "high")
        self.assertEqual(self.state.snapshot()["thread"]["effort"], "high")
        self.assertNotEqual(self.state.snapshot()["thread"]["tier"], "fast")
        self.event("thread/settings/updated", threadSettings={"effort": "low", "serviceTier": "fast"})
        self.assertEqual(self.state.snapshot()["thread"]["effort"], "low")
        self.assertEqual(self.thread.reasoning.summary()["samples"], 0)

    def test_single_response_history_after_attach_is_not_a_new_hit(self):
        for method in ("thread/resume", "thread/fork", "thread/rollback"):
            with self.subTest(method=method):
                self.state.client({"id": 42, "method": method, "params": {"threadId": "t"}})
                self.state.server({"id": 42, "result": {"thread": {"id": "t"}}})
                self.count()
                self.assertEqual(self.thread.reasoning.summary()["samples"], 0)
                self.count(index=2)
                self.assertEqual(self.thread.reasoning.summary()["samples"], 1)

    def test_login_change_quarantines_inflight_usage(self):
        self.count()
        self.state.set_account({"type": "chatgpt", "email": "new@example.com", "planType": "pro"})
        self.count(index=2)
        self.assertEqual(self.thread.reasoning.summary()["samples"], 0)
        self.thread.begin_turn("next")
        self.event("thread/tokenUsage/updated", turnId="next", tokenUsage=usage(0, 12000))
        self.event("thread/tokenUsage/updated", turnId="next", tokenUsage=usage(0, 16000))
        self.assertEqual(self.thread.reasoning.summary()["samples"], 1)
        self.assertEqual(self.thread.reasoning.summary()["exact_516"], 0)

    def test_disclosed_mismatch_keeps_strict_exit_code(self):
        self.count()
        self.thread.observe("gpt-4o", "model/rerouted")
        self.assertEqual(verdict(self.state.snapshot())["exit_code"], 2)

    def test_shared_export_filters_unknown_reasoning_fields(self):
        snapshot = self.state.snapshot()
        snapshot["thread"]["reasoning"].update(secret="private", source="private", effort=["private"], last_tokens="private")
        result = verdict(snapshot)
        self.assertNotIn("private", str(result))
        self.assertIsNone(result["reasoning"]["last_tokens"])


if __name__ == "__main__":
    unittest.main()

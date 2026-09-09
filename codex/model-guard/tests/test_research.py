import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("reasoning_counts", Path(__file__).resolve().parents[1] / "research/reasoning_counts.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ResearchTests(unittest.TestCase):
    def test_aggregate_deduplicates_forked_response_ids_and_omits_private_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "max", "cwd": "private-work"}}
            record = {"type": "token_usage_record", "payload": {"response_id": "private-id", "usage": {"reasoning_output_tokens": 516}}}
            text = "\n".join(json.dumps(row) for row in (context, record, record,
                {"type": "event_msg", "payload": {"type": "agent_message", "message": "private-text"}},
                {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"reasoning_output_tokens": 516}}}}))
            for name in ("one.jsonl", "fork.jsonl"):
                (root / name).write_text(text + "\n{incomplete")
            result = audit.aggregate([root])
            self.assertEqual(result["groups"][0]["responses"], 1)
            self.assertEqual(result["groups"][0]["exact_516"], 1)
            self.assertNotIn("private", json.dumps(result))

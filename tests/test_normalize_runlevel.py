import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import normalize_trajectories as nt  # noqa: E402

FIXTURES = TESTS / "fixtures"


class RunLevelEventsTests(unittest.TestCase):
    def test_run_level_events_do_not_become_conversations(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            lines = (FIXTURES / "mini_run" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            extra = [json.dumps({"sequence": 0, "event": "run_start", "run_id": "mini-run", "timestamp": "2026-09-18T04:58:59+00:00"}),
                     json.dumps({"sequence": 99, "event": "run_end", "run_id": "mini-run", "timestamp": "2026-09-18T05:00:00+00:00"})]
            (run / "events.jsonl").write_text("\n".join(extra[:1] + lines + extra[1:]) + "\n", encoding="utf-8")
            out = Path(tmp) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(nt.main(["normalize", str(run), "--out", str(out)]), 0)
            data = json.loads((out / "conversations.json").read_text(encoding="utf-8"))
            self.assertEqual([c["conversation_id"] for c in data["conversations"]], ["sim-mini-0001"])
            self.assertEqual(data["conversations"][0]["summary"]["outcome"], "abandoned")

    def test_outcome_from_reason(self):
        self.assertEqual(nt.outcome_from_reason("card_replacement_submitted"), "completed")
        self.assertEqual(nt.outcome_from_reason("transfer_to_human"), "transferred")
        self.assertEqual(nt.outcome_from_reason("turn_limit"), "abandoned")
        self.assertEqual(nt.outcome_from_reason(None), "unknown")

    def test_sessionless_capture_still_groups_by_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            rows = [{"sequence": 1, "event": "customer_message", "run_id": "r1", "turn": 1, "text": "hi", "timestamp": "2026-09-18T04:59:00+00:00"},
                    {"sequence": 2, "event": "agent_message", "run_id": "r1", "turn": 1, "text": "hello", "timestamp": "2026-09-18T04:59:01+00:00"}]
            (run / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            out = Path(tmp) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(nt.main(["normalize", str(run), "--out", str(out)]), 0)
            data = json.loads((out / "conversations.json").read_text(encoding="utf-8"))
            self.assertEqual(data["conversations"][0]["conversation_id"], "r1")


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

import normalize_trajectories as nt  # noqa: E402
from builders import BLOATED_TURNS, events_session  # noqa: E402
from halu_common.payload import status_of  # noqa: E402


class DietTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run = self.root / "run"
        self.run.mkdir()
        events_session(self.run, BLOATED_TURNS, session_id="sim-bloat-0001")
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def normalize(self, *flags):
        self.counter += 1
        out = self.root / ("out%d" % self.counter)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = nt.main(["normalize", str(self.run), "--out", str(out)] + list(flags))
        self.assertEqual(code, 0, captured.getvalue())
        data = json.loads((out / "conversations.json").read_text(encoding="utf-8"))
        report = (out / "normalize_report.md").read_text(encoding="utf-8")
        return out, data, report, captured.getvalue()

    def test_default_diet_shrinks_redacts_and_keeps_the_contract(self):
        out, data, report, printed = self.normalize()
        conv = data["conversations"][0]
        text = json.dumps(data)
        self.assertNotIn("eyJ", text)
        self.assertNotIn("4242424242424242", text)
        self.assertIn("[redacted:jwt", text)
        updates = [e for e in conv["events"] if e["kind"] == "state_update"]
        self.assertTrue(updates)
        self.assertTrue(all("state" not in e for e in updates))
        self.assertEqual(updates[0]["source"], "defaults")
        self.assertEqual(updates[0]["changes"]["democard_state.flow"]["new"], "damaged")
        zip_change = next(e for e in updates if "democard_state.user_zip" in e["changes"] and e["changes"]["democard_state.user_zip"]["new"])
        self.assertEqual(zip_change["changes"]["democard_state.user_zip"]["new"], "10001")
        self.assertEqual(zip_change["source"], "updatedVariables")
        old_lists = [c["old"] for e in updates for c in e["changes"].values() if isinstance(c.get("old"), list)]
        self.assertTrue(old_lists and all(len(v) == 1 and "_summary" in v[0] for v in old_lists))  # old values are summaries
        self.assertGreater(data["meta"]["diet"]["counts"]["old_summarized"], 0)
        payments = next(e for e in conv["events"] if e.get("tool") == "get_payments")
        self.assertEqual(status_of(payments["response"]), "SUCCESS")
        self.assertEqual(payments["response"]["tokens"][0]["device_name"], "iPhone 15 Pro")
        self.assertIn("_summary", json.dumps(payments["response"]))
        self.assertEqual(payments["args"]["account_id"], "acct-7f3a9c2e1b4d5e6f7a8b9c0d1e2f3a4b")
        token = next(e for e in conv["events"] if e.get("tool") == "get_token")
        self.assertTrue(token["response"]["access_token"].startswith("[redacted:jwt"))
        self.assertEqual(token["response"]["expires_in"], 3600)
        customer = [e["text"] for e in conv["events"] if e["kind"] == "customer_utterance"]
        self.assertIn("yes, and my card number is ****4242", customer)
        summary = conv["summary"]
        self.assertLess(summary["chars_after"], 0.4 * summary["chars_before"])
        diet = data["meta"]["diet"]
        self.assertEqual(diet["settings"]["state_snapshots"], "none")
        self.assertGreater(diet["counts"]["jwt"], 0)
        self.assertGreater(diet["counts"]["snapshots_dropped"], 0)
        self.assertIn("## Diet", report)
        self.assertIn("| jwt |", report)
        self.assertIn("| Chars before | Chars after |", report)
        self.assertIn("diet: redacted=", printed)

    def test_no_diet_keeps_everything(self):
        out, data, report, printed = self.normalize("--no-diet")
        text = json.dumps(data)
        self.assertIn("eyJ", text)
        conv = data["conversations"][0]
        updates = [e for e in conv["events"] if e["kind"] == "state_update"]
        self.assertTrue(all("state" in e for e in updates))
        payments = next(e for e in conv["events"] if e.get("tool") == "get_payments")
        self.assertEqual(len(payments["response"]["payments"]), 60)  # lists are intact without the diet
        self.assertEqual(payments["response"]["payments"][0]["card_number"], "4242424242424242")
        self.assertEqual(conv["summary"]["chars_after"], conv["summary"]["chars_before"])
        self.assertNotIn("jwt", data["meta"]["diet"]["counts"])
        out2, dieted, _, _ = self.normalize()
        self.assertLess(dieted["conversations"][0]["summary"]["chars_after"], 0.4 * conv["summary"]["chars_after"])

    def test_turn_policy_keeps_the_last_snapshot_of_each_turn_redacted(self):
        out, data, report, printed = self.normalize("--state-snapshots", "turn")
        events = data["conversations"][0]["events"]
        by_turn = {}
        for index, event in enumerate(events):
            if event["kind"] == "state_update":
                by_turn.setdefault(event["turn"], []).append(index)
        for turn, indexes in by_turn.items():
            self.assertTrue(all("state" not in events[i] for i in indexes[:-1]), turn)
            self.assertIn("state", events[indexes[-1]])
        self.assertNotIn("eyJ", json.dumps(data))

    def test_split_reports_oversized_conversations(self):
        out, data, report, printed = self.normalize()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = nt.main(["split", str(out / "conversations.json"), "--out", str(out / "batches"), "--max-chars", "2000"])
        self.assertEqual(code, 0)
        self.assertIn("oversized: sim-bloat-0001", captured.getvalue())
        index = json.loads((out / "batches" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["oversized"][0]["conversation_id"], "sim-bloat-0001")
        self.assertEqual(index["max_chars"], 2000)

    def test_show_locator_prints_the_record_redacted(self):
        out, data, report, printed = self.normalize()
        token = next(e for e in data["conversations"][0]["events"] if e.get("tool") == "get_token")
        locator = token.get("response_locator") or token["locator"]
        result = subprocess.run([sys.executable, str(TESTS.parent / "scripts" / "show_locator.py"), locator], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[redacted:", result.stdout)
        self.assertNotIn("eyJ", result.stdout)
        result = subprocess.run([sys.executable, str(TESTS.parent / "scripts" / "show_locator.py"), "events:/nope/events.jsonl#seq=1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()

import copy
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

import validate_findings  # noqa: E402
from builders import final_findings  # noqa: E402
from halu_common.jsonl import read_json, write_json  # noqa: E402

FIXTURES = TESTS / "fixtures"


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.batch = read_json(FIXTURES / "mini_findings_batch.json")

    def run_validate(self, data, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.json"
            write_json(path, data)
            return validate_findings.main([str(path)] + list(extra))

    def test_valid_final_file(self):
        self.assertEqual(self.run_validate(final_findings(self.batch["conversations"])), 0)

    def test_missing_evidence_fails(self):
        broken = copy.deepcopy(self.batch)
        broken["conversations"][0]["hallucinations"][0]["evidence"] = [
            {"kind": "pseudocode", "ref": "x", "provenance": "seen_in_code"}]
        self.assertEqual(self.run_validate(final_findings(broken["conversations"])), 1)

    def test_empty_rationale_fails(self):
        broken = copy.deepcopy(self.batch)
        broken["conversations"][0]["hallucinations"][0]["rationale"] = "  "
        self.assertEqual(self.run_validate(final_findings(broken["conversations"])), 1)

    def test_batch_mode_and_pre_audit(self):
        self.assertEqual(self.run_validate(self.batch, "--batch"), 0)
        stripped = copy.deepcopy(self.batch)
        stripped["conversations"][0]["hallucinations"][0].pop("verification")
        self.assertEqual(self.run_validate(stripped, "--batch"), 1)
        self.assertEqual(self.run_validate(stripped, "--batch", "--pre-audit"), 0)

    def test_unknown_type_fails_schema(self):
        broken = copy.deepcopy(self.batch)
        broken["conversations"][0]["hallucinations"][0]["type"] = "made_up"
        self.assertEqual(self.run_validate(final_findings(broken["conversations"])), 1)

    def test_conversations_cross_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            conversations = Path(tmp) / "conversations.json"
            write_json(conversations, {"meta": {}, "conversations": [{"conversation_id": "sim-mini-0001", "summary": {"turns": 3}}]})
            path = Path(tmp) / "f.json"
            write_json(path, final_findings(self.batch["conversations"]))
            self.assertEqual(validate_findings.main([str(path), "--conversations", str(conversations)]), 0)
            broken = copy.deepcopy(self.batch)
            broken["conversations"][0]["hallucinations"][0]["turn"] = 9
            write_json(path, final_findings(broken["conversations"]))
            self.assertEqual(validate_findings.main([str(path), "--conversations", str(conversations)]), 1)

    def test_resolve_locators_against_fixture(self):
        data = final_findings(copy.deepcopy(self.batch["conversations"]))
        absolute = str(FIXTURES / "mini_run" / "events.jsonl")
        for item in data["conversations"][0]["hallucinations"]:
            for ev in item["evidence"]:
                if ev.get("locator"):
                    ev["locator"] = ev["locator"].replace("tests/fixtures/mini_run/events.jsonl", absolute)
        self.assertEqual(self.run_validate(data, "--resolve-locators"), 0)


if __name__ == "__main__":
    unittest.main()

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import merge_findings  # noqa: E402
from halu_common.jsonl import read_json, write_json  # noqa: E402

FIXTURES = TESTS / "fixtures"


class MergeTests(unittest.TestCase):
    def test_merges_and_renumbers(self):
        batch = read_json(FIXTURES / "mini_findings_batch.json")
        second = copy.deepcopy(batch)
        second["batch"] = "002"
        second["conversations"][0]["conversation_id"] = "sim-mini-0002"
        with tempfile.TemporaryDirectory() as tmp:
            findings_dir = Path(tmp) / "findings"
            findings_dir.mkdir()
            write_json(findings_dir / "verified_batch_001.json", batch)
            write_json(findings_dir / "verified_batch_002.json", second)
            pseudocode = Path(tmp) / "workflow_pseudocode.md"
            pseudocode.write_text("# pseudocode\n", encoding="utf-8")
            out = Path(tmp) / "hallucination_findings.json"
            code = merge_findings.main(["--verified-dir", str(findings_dir), "--out", str(out), "--pseudocode", str(pseudocode),
                                        "--target", "DemoCard", "--model", "test-model"])
            self.assertEqual(code, 0)
            final = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(final["conversations"]), 2)
            ids = [h["id"] for c in final["conversations"] for h in c["hallucinations"]]
            self.assertEqual(ids, ["H-0001", "H-0002"])
            self.assertTrue(final["meta"]["evaluator"]["audited"])
            self.assertEqual(final["meta"]["evaluator"]["model"], "test-model")
            self.assertEqual(final["meta"]["target_agent"], "DemoCard")
            self.assertEqual(len(final["meta"]["pseudocode_sha256"]), 64)
            self.assertEqual(final["meta"]["counts"]["hallucinations"], 2)

    def test_unverified_batches_are_marked(self):
        batch = read_json(FIXTURES / "mini_findings_batch.json")
        batch["conversations"][0]["hallucinations"][0].pop("verification")
        with tempfile.TemporaryDirectory() as tmp:
            findings_dir = Path(tmp) / "findings"
            findings_dir.mkdir()
            write_json(findings_dir / "batch_001.json", batch)
            out = Path(tmp) / "final.json"
            self.assertEqual(merge_findings.main(["--verified-dir", str(findings_dir), "--out", str(out)]), 2)
            self.assertEqual(merge_findings.main(["--verified-dir", str(findings_dir), "--out", str(out), "--unverified"]), 0)
            final = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(final["meta"]["evaluator"]["audited"])
            self.assertEqual(final["conversations"][0]["hallucinations"][0]["verification"]["status"], "unaudited")


if __name__ == "__main__":
    unittest.main()

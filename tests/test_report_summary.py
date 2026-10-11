import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

import aggregate_findings as agg  # noqa: E402
import report_summary as rs  # noqa: E402
from builders import final_findings  # noqa: E402
from halu_common.jsonl import write_json  # noqa: E402


class ReportSummaryTests(unittest.TestCase):
    def test_summary_masks_digits_and_lists_findings(self):
        finding = {"id": "H-0001", "turn": 2, "point": "zip_collection.save_zip_code.args.zip_code", "author": "model",
                   "type": "unsupported_argument", "check_kind": "grounding", "severity": "medium", "confidence": "high",
                   "observed": "10001", "expected_or_allowed": "100011", "rationale": "customer said 100011 but the argument was 10001",
                   "evidence": [{"kind": "customer_utterance", "turn": 2, "quote": "my zip is 100011", "locator": "csv:f.csv:L2"},
                                {"kind": "pseudocode", "ref": "tool save_zip_code inputs.zip_code", "provenance": "seen_in_code"}],
                   "verification": {"status": "confirmed", "auditor_rationale": "ok", "revised_from": None}}
        data = final_findings([{"conversation_id": "c1", "workflow": "damaged", "turns": 3, "points_evaluated": 9, "outcome": "completed",
                                "hallucinations": [finding], "rejected": [], "pipeline_findings": [], "unverifiable": [{"point": "validate_zip_code.output", "turn": 3, "reason": "no ZIP on file"}],
                                "notes": ["asr_suspect turn 2"], "audit": {"sampled_supported": 3, "misses_found": 0}}])
        with tempfile.TemporaryDirectory() as tmp:
            findings = Path(tmp) / "f.json"
            write_json(findings, data)
            aggregate = Path(tmp) / "a.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(agg.main([str(findings), "--out", str(aggregate), "--mdd-view"]), 0)
                out = Path(tmp) / "summary.md"
                self.assertEqual(rs.main(["--findings", str(findings), "--aggregate", str(aggregate), "--out", str(out)]), 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("H-0001", text)
            self.assertIn("argument grounding (MDD B)", text)
            self.assertNotIn("100011", text)
            self.assertIn("10****", text)
            self.assertIn("no ZIP on file", text)
            self.assertIn("asr_suspect", text)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rs.main(["--findings", str(findings), "--aggregate", str(aggregate), "--out", str(out), "--unmask"]), 0)
            self.assertIn("100011", out.read_text(encoding="utf-8"))

    def test_unaudited_run_is_labelled(self):
        data = final_findings([{"conversation_id": "c1", "workflow": "damaged", "turns": 3, "points_evaluated": 9, "outcome": "completed",
                                "hallucinations": [], "rejected": [], "pipeline_findings": [], "unverifiable": [], "notes": [], "audit": None}])
        data["meta"]["evaluator"]["audited"] = False
        data["meta"]["evaluator"]["audit_model"] = None
        with tempfile.TemporaryDirectory() as tmp:
            findings = Path(tmp) / "f.json"
            write_json(findings, data)
            aggregate = Path(tmp) / "a.json"
            out = Path(tmp) / "summary.md"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(agg.main([str(findings), "--out", str(aggregate)]), 0)
                self.assertEqual(rs.main(["--findings", str(findings), "--aggregate", str(aggregate), "--out", str(out)]), 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Auditing model: none (P7 skipped)", text)
            self.assertIn("UNAUDITED (the P7 audit was not included)", text)


if __name__ == "__main__":
    unittest.main()

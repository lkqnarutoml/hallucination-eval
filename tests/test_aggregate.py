import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

import aggregate_findings as agg  # noqa: E402
from builders import final_findings  # noqa: E402
from halu_common.jsonl import write_json  # noqa: E402


def finding(fid, point, ftype, status, turn=2):
    return {"id": fid, "turn": turn, "point": point, "author": "model", "type": ftype, "check_kind": "grounding",
            "severity": "medium", "confidence": "high", "observed": "x", "expected_or_allowed": "y", "rationale": "r",
            "evidence": [{"kind": "customer_utterance", "turn": turn, "quote": "q", "locator": "csv:f.csv:L2"},
                         {"kind": "pseudocode", "ref": "p", "provenance": "seen_in_code"}],
            "verification": {"status": status, "auditor_rationale": "a", "revised_from": None}}


class AggregateTests(unittest.TestCase):
    def data(self):
        return final_findings([
            {"conversation_id": "c1", "workflow": "damaged", "turns": 4, "points_evaluated": 10, "outcome": "completed",
             "hallucinations": [finding("H-0001", "zip_collection.save_zip_code.args.zip_code", "unsupported_argument", "confirmed"),
                                finding("H-0002", "zip_confirmation.selection", "unsupported_tool_selection", "revised")],
             "rejected": [finding("R-0001", "card_replacement.selection", "omission", "rejected")],
             "pipeline_findings": [], "unverifiable": [{"point": "zip_confirmation.validate_zip_code.output", "turn": 3, "reason": "no ZIP on file"}],
             "notes": [], "audit": {"sampled_supported": 5, "misses_found": 1}},
            {"conversation_id": "c2", "workflow": "lost", "turns": 6, "points_evaluated": 12, "outcome": "transferred",
             "hallucinations": [], "rejected": [], "pipeline_findings": [{"id": "P-0001", "point": "callback.readback", "type": "spec_drift", "rationale": "r", "evidence": []}],
             "unverifiable": [], "notes": [], "audit": {"sampled_supported": 5, "misses_found": 0}},
        ])

    def test_counts_and_precision(self):
        result = agg.aggregate(self.data(), mdd_view=True)
        self.assertEqual(result["conversations"], 2)
        self.assertEqual(result["conversations_with_hallucination"], 1)
        self.assertEqual(result["hallucinations"], 2)
        self.assertEqual(result["points_evaluated"], 22)
        self.assertEqual(result["by_type"], {"unsupported_argument": 1, "unsupported_tool_selection": 1})
        self.assertEqual(result["by_workflow"], {"damaged": 2})
        self.assertEqual(result["audit"]["rejected"], 1)
        self.assertEqual(result["audit"]["evaluator_precision"], round(2 / 3, 4))
        self.assertEqual(result["audit"]["miss_rate"], 0.1)
        self.assertEqual(result["mdd_view"], {"argument grounding (MDD B)": 1, "tool selection (MDD C)": 1})
        self.assertEqual(result["pipeline_findings_by_type"], {"spec_drift": 1})
        self.assertEqual(result["unverifiable_by_reason"], {"no ZIP on file": 1})
        self.assertEqual(len(result["conversation_rate_wilson95"]), 2)

    def test_auditor_found_misses_do_not_change_evaluator_precision(self):
        data = self.data()
        baseline = agg.aggregate(data, mdd_view=False)
        miss = finding("H-0003", "zip_confirmation.selection", "unsupported_tool_selection", "confirmed", turn=3)
        miss["decided_by"] = "auditor"  # added by make_audit_payload.py apply; the evaluator never produced it
        data["conversations"][0]["hallucinations"].append(miss)
        data["conversations"][0]["audit"]["misses_found"] = 2
        result = agg.aggregate(data, mdd_view=False)
        self.assertEqual(result["audit"]["evaluator_precision"], baseline["audit"]["evaluator_precision"])
        self.assertEqual(result["audit"]["evaluator_precision"], round(2 / 3, 4))
        self.assertEqual(result["audit"]["kept"], 2)
        self.assertEqual(result["audit"]["rejected"], 1)
        self.assertEqual(result["hallucinations"], 3)  # the miss still counts as a hallucination
        self.assertEqual(result["by_verification"]["confirmed"], 2)
        self.assertEqual(result["audit"]["miss_rate"], 0.2)
        # a run whose only findings are auditor misses has no evaluator precision to report
        only_misses = final_findings([{"conversation_id": "c3", "workflow": "damaged", "turns": 4, "points_evaluated": 10,
                                       "outcome": "completed", "hallucinations": [miss], "rejected": [], "pipeline_findings": [],
                                       "unverifiable": [], "notes": [], "audit": {"sampled_supported": 5, "misses_found": 1}}])
        result = agg.aggregate(only_misses, mdd_view=False)
        self.assertIsNone(result["audit"]["evaluator_precision"])
        self.assertEqual(result["audit"]["kept"], 0)
        self.assertEqual(result["hallucinations"], 1)

    def test_cli_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "f.json"
            write_json(source, self.data())
            out = Path(tmp) / "aggregate.json"
            md = Path(tmp) / "tables.md"
            self.assertEqual(agg.main([str(source), "--out", str(out), "--md", str(md), "--mdd-view"]), 0)
            text = md.read_text(encoding="utf-8")
            self.assertIn("MDD view", text)
            self.assertIn("| c1 | damaged |", text)

    def test_wilson(self):
        self.assertIsNone(agg.wilson(0, 0))
        low, high = agg.wilson(0, 63)
        self.assertEqual(low, 0.0)
        self.assertLess(high, 0.06)


if __name__ == "__main__":
    unittest.main()

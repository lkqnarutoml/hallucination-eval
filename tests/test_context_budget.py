import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
sys.path.insert(0, str(SKILL / "scripts"))

import context_budget as cb  # noqa: E402


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name) / "run"
        for sub in ("normalized/batches", "checker/results", "audit", "runtime"):
            (self.run / sub).mkdir(parents=True)
        (self.run / "workflow_pseudocode.md").write_text("p" * 1000, encoding="utf-8")
        (self.run / "normalized" / "batches" / "batch_001.json").write_text("b" * 5000, encoding="utf-8")
        (self.run / "normalized" / "batches" / "index.json").write_text(json.dumps({"batches": [{"id": "001"}]}), encoding="utf-8")
        (self.run / "checker" / "results" / "batch_001.json").write_text("c" * 300, encoding="utf-8")
        (self.run / "runtime" / "prompt-evaluator-001.md").write_text("e" * 400, encoding="utf-8")
        files = {"pseudocode": str(self.run / "workflow_pseudocode.md"), "batches_dir": str(self.run / "normalized" / "batches"),
                 "checker_out_dir": str(self.run / "checker" / "results"), "audit_dir": str(self.run / "audit"), "runtime_dir": str(self.run / "runtime")}
        (self.run / "run_manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
        self.references = {role: sum(len((SKILL / rel).read_text(encoding="utf-8")) for rel in rels) for role, rels in cb.ROLE_REFERENCES.items()}

    def tearDown(self):
        self.tmp.cleanup()

    def run_budget(self, *args):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = cb.main([str(self.run)] + list(args))
        return code, captured.getvalue()

    def test_rows_and_limit(self):
        out = Path(self.tmp.name) / "budget.json"
        code, text = self.run_budget("--limit-chars", "1000000", "--json", str(out))
        self.assertEqual(code, 0, text)
        rows = json.loads(out.read_text(encoding="utf-8"))["rows"]
        evaluator = next(r for r in rows if r["role"] == "evaluator")
        self.assertEqual(evaluator["total"], 400 + 1000 + 5000 + 300 + self.references["evaluator"])
        self.assertTrue(evaluator["prompt_filled"])
        auditor = next(r for r in rows if r["role"] == "auditor")
        self.assertFalse(auditor["data_present"])
        self.assertEqual(auditor["prompt"], len((SKILL / "roles" / "auditor.md").read_text(encoding="utf-8")))
        self.assertIn("missing", text)
        code, text = self.run_budget("--limit-chars", "1000")
        self.assertEqual(code, 1)
        self.assertIn("OVER limit", text)
        code, text = self.run_budget("--role", "evaluator", "--batch", "1", "--limit-chars", "1000000")
        self.assertEqual(code, 0)
        self.assertIn("001    evaluator", text)
        self.assertNotIn("auditor", text)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import build_spec as bs  # noqa: E402
import manifest  # noqa: E402
from halu_common.jsonl import write_json  # noqa: E402

EXCERPT = TESTS.parent / "references" / "example_democard_excerpt.md"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = manifest.main(argv)
    return code, out.getvalue() + err.getvalue()


def manifest_of(run_dir: Path) -> dict:
    return json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "run"
        run(["init", str(self.run_dir), "--target", "DemoCard"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_prerequisites_and_gates_block_skipping_ahead(self):
        code, text = run(["set-phase", str(self.run_dir), "pseudocode", "done"])
        self.assertEqual(code, 1)
        self.assertIn("prerequisite phase inventory", text)
        code, text = run(["set-phase", str(self.run_dir), "inventory", "done"])
        self.assertEqual(code, 1)
        self.assertIn("missing", text)
        self.assertEqual(manifest_of(self.run_dir)["phases"]["inventory"]["status"], "pending")
        code, text = run(["set-phase", str(self.run_dir), "inventory", "done", "--force"])
        self.assertEqual(code, 2)
        code, text = run(["set-phase", str(self.run_dir), "inventory", "done", "--force", "--note", "smoke"])
        self.assertEqual(code, 0)
        data = manifest_of(self.run_dir)
        self.assertTrue(data["phases"]["inventory"]["note"].startswith("FORCED"))
        self.assertEqual(data["log"][-2]["event"], "forced")
        code, text = run(["set-phase", str(self.run_dir), "normalize_inspect", "skipped"])
        self.assertEqual(code, 2)
        code, _ = run(["set-phase", str(self.run_dir), "normalize_inspect", "skipped", "--note", "no tabular export"])
        self.assertEqual(code, 0)

    def test_pseudocode_gate_uses_compile_result(self):
        inv = self.run_dir / "inventory"
        write_json(inv / "materials_inventory.json", {"agents": {"root": {"tools": []}}})
        (inv / "materials_summary.md").write_text("x", encoding="utf-8")
        (inv / "materials_tree.md").write_text("x", encoding="utf-8")
        self.assertEqual(run(["set-phase", str(self.run_dir), "inventory", "done"])[0], 0)
        pseudocode = self.run_dir / "workflow_pseudocode.md"
        pseudocode.write_text(EXCERPT.read_text(encoding="utf-8"), encoding="utf-8")
        code, text = run(["gate", str(self.run_dir), "pseudocode"])
        self.assertEqual(code, 1)
        self.assertIn("missing spec_json", text)
        with contextlib.redirect_stdout(io.StringIO()):
            bs.main(["compile", str(pseudocode), "--out", str(self.run_dir / "spec" / "workflow_spec.json"), "--report", str(self.run_dir / "spec" / "spec_report.md")])
            bs.main(["render", str(self.run_dir / "spec" / "workflow_spec.json"), "--out", str(self.run_dir / "architecture.md")])
        code, text = run(["gate", str(self.run_dir), "pseudocode"])
        self.assertEqual(code, 0, text)
        self.assertEqual(run(["set-phase", str(self.run_dir), "pseudocode", "done"])[0], 0)
        review = self.run_dir / "spec" / "spec_review.md"
        review.write_text("issues...\nVERDICT: REVISE\n", encoding="utf-8")
        code, text = run(["set-phase", str(self.run_dir), "spec_review", "done"])
        self.assertEqual(code, 1)
        self.assertIn("REVISE", text)
        review.write_text("VERDICT: APPROVED_WITH_NOTES\n", encoding="utf-8")
        self.assertEqual(run(["set-phase", str(self.run_dir), "spec_review", "done"])[0], 0)

    def test_batches_are_registered_and_required(self):
        norm = self.run_dir / "normalized"
        write_json(norm / "conversations.json", {"conversations": []})
        write_json(norm / "batches" / "index.json", {"batches": [{"id": "001"}, {"id": "002"}]})
        run(["set-phase", str(self.run_dir), "normalize_inspect", "skipped", "--note", "n/a"])
        self.assertEqual(run(["set-phase", str(self.run_dir), "normalize", "done"])[0], 0)
        data = manifest_of(self.run_dir)
        self.assertEqual(data["batches"]["evaluate"], {"001": "pending", "002": "pending"})
        self.assertEqual(data["batches"]["audit"], {"001": "pending", "002": "pending"})
        code, text = run(["gate", str(self.run_dir), "evaluate"])
        self.assertEqual(code, 1)
        self.assertIn("batch 001 is pending", text)
        write_json(self.run_dir / "findings" / "batch_001.json", {"conversations": []})
        write_json(self.run_dir / "findings" / "batch_002.json", {"conversations": []})
        run(["set-batch", str(self.run_dir), "evaluate", "001", "done"])
        run(["set-batch", str(self.run_dir), "evaluate", "002", "done"])
        code, text = run(["gate", str(self.run_dir), "evaluate"])
        self.assertEqual(code, 1)
        self.assertIn("prerequisite phase spec_review", text)
        code, text = run(["register-batches", str(self.run_dir)])
        self.assertIn("2 batch(es)", text)

    def test_dispatch_lifecycle_and_attempt_limit(self):
        prompt = self.run_dir / "runtime" / "prompt-evaluator-001.md"
        prompt.write_text("Read RUN_DIR/normalized/batches/batch_001.json {{LEFTOVER}}", encoding="utf-8")
        code, text = run(["dispatch", str(self.run_dir), "evaluator", "--prompt", str(prompt), "--batch", "001"])
        self.assertEqual(code, 2)
        self.assertIn("PLACEHOLDER", text)
        prompt.write_text("Read the batch and follow the rules.", encoding="utf-8")
        code, text = run(["dispatch", str(self.run_dir), "evaluator", "--prompt", str(prompt), "--batch", "001"])
        self.assertEqual(code, 0)
        first = text.strip()
        self.assertEqual(first, "d-0001")
        code, text = run(["dispatch", str(self.run_dir), "evaluator", "--prompt", str(prompt), "--batch", "001"])
        self.assertEqual(code, 1)
        self.assertIn("already running", text)
        output = self.run_dir / "findings" / "batch_001.json"
        code, text = run(["finalize", str(self.run_dir), first, "--status", "done", "--outputs", str(output)])
        self.assertEqual(code, 1)
        self.assertIn("outputs missing", text)
        self.assertEqual(manifest_of(self.run_dir)["dispatches"][0]["status"], "failed")
        code, text = run(["dispatch", str(self.run_dir), "evaluator", "--prompt", str(prompt), "--batch", "001"])
        self.assertEqual(code, 0)
        second = text.strip()
        write_json(output, {"conversations": []})
        code, _ = run(["finalize", str(self.run_dir), second, "--status", "done", "--outputs", str(output)])
        self.assertEqual(code, 0)
        code, text = run(["dispatch", str(self.run_dir), "evaluator", "--prompt", str(prompt), "--batch", "001"])
        self.assertEqual(code, 1)
        self.assertIn("exceeds the limit", text)
        code, text = run(["dispatch", str(self.run_dir), "evaluator", "--prompt", str(prompt), "--batch", "001", "--force"])
        self.assertEqual(code, 0)
        code, text = run(["show", str(self.run_dir)])
        self.assertIn("dispatch d-0003 evaluator", text)
        code, text = run(["next", str(self.run_dir)])
        self.assertIn("running dispatches: d-0003", text)
        code, text = run(["dispatch", str(self.run_dir), "bogus", "--prompt", str(prompt)])
        self.assertEqual(code, 2)

    def test_init_records_both_models(self):
        other = Path(self.tmp.name) / "other"
        code, text = run(["init", str(other), "--target", "X", "--model", "GPT-5.5", "--audit-model", "Claude Opus 4.7"])
        self.assertEqual(code, 0, text)
        self.assertEqual(manifest_of(other)["evaluator"], {"mode": "multi-agent", "model": "GPT-5.5", "audit_model": "Claude Opus 4.7"})
        third = Path(self.tmp.name) / "third"
        code, text = run(["init", str(third), "--target", "X", "--model", "Some Other Model"])
        self.assertEqual(code, 0, text)
        self.assertIn("not one of", text)
        self.assertEqual(manifest_of(third)["evaluator"]["audit_model"], "Some Other Model")  # defaults to the P6 model
        code, text = run(["show", str(other)])
        self.assertIn("P6 evaluators=GPT-5.5  P7 auditors=Claude Opus 4.7", text)

    def test_audit_can_be_left_out_at_setup_and_toggled(self):
        run_dir = Path(self.tmp.name) / "noaudit"
        code, text = run(["init", str(run_dir), "--target", "X", "--model", "GPT-5.5", "--no-audit"])
        self.assertEqual(code, 0, text)
        data = manifest_of(run_dir)
        self.assertFalse(data["settings"]["audit"])
        self.assertEqual(data["phases"]["audit"]["status"], "skipped")
        self.assertIn("UNAUDITED", data["phases"]["audit"]["note"])
        self.assertIsNone(data["evaluator"]["audit_model"])
        code, text = run(["show", str(run_dir)])
        self.assertIn("audit: skipped", text)
        # batches: only evaluate entries are registered while the audit is off
        batches = run_dir / "normalized" / "batches"
        batches.mkdir(parents=True, exist_ok=True)
        write_json(batches / "index.json", {"batches": [{"id": "001", "file": str(batches / "batch_001.json"), "conversations": 1, "chars": 10}]})
        write_json(batches / "batch_001.json", {"batch": {"id": "001"}, "conversations": []})
        code, text = run(["register-batches", str(run_dir)])
        self.assertEqual(code, 0, text)
        data = manifest_of(run_dir)
        self.assertEqual(data["batches"]["evaluate"], {"001": "pending"})
        self.assertEqual(data["batches"]["audit"], {})
        # the audit phase does not block `next` or the report prerequisites
        for phase in ("inventory", "pseudocode", "spec_review", "normalize_inspect", "normalize", "checker_compile", "checker_run", "evaluate"):
            state = manifest_of(run_dir)
            state["phases"][phase]["status"] = "done"
            write_json(run_dir / "run_manifest.json", state)
        code, text = run(["next", str(run_dir)])
        self.assertIn("report", text)
        self.assertEqual(manifest.prerequisite_problems(manifest_of(run_dir), "report"), [])
        # turning the audit back on restores the phase and registers the audit batches
        self.assertEqual(run(["set-setting", str(run_dir), "audit", "true"])[0], 0)
        data = manifest_of(run_dir)
        self.assertEqual(data["phases"]["audit"]["status"], "pending")
        self.assertEqual(data["batches"]["audit"], {"001": "pending"})
        self.assertEqual(run(["set-setting", str(run_dir), "audit", "no"])[0], 0)
        data = manifest_of(run_dir)
        self.assertEqual(data["phases"]["audit"]["status"], "skipped")
        self.assertEqual(data["batches"]["audit"], {})
        self.assertEqual(run(["set-setting", str(run_dir), "audit", "maybe"])[0], 2)
        # the report gate refuses an unaudited final file only when the audit was included
        final = run_dir / "hallucination_findings.json"
        write_json(final, {"meta": {"evaluator": {"audited": False}}, "conversations": []})
        write_json(run_dir / "aggregate.json", {})
        (run_dir / "summary.md").write_text("# s\n", encoding="utf-8")
        self.assertEqual(manifest.gate_problems(manifest_of(run_dir), "report"), [])
        self.assertEqual(run(["set-setting", str(run_dir), "audit", "true"])[0], 0)
        problems = manifest.gate_problems(manifest_of(run_dir), "report")
        self.assertTrue(any("unaudited" in p for p in problems), problems)

    def test_set_setting_and_dispatch_model(self):
        self.assertEqual(run(["set-setting", str(self.run_dir), "model", "GPT-5.5"])[0], 0)
        self.assertEqual(run(["set-setting", str(self.run_dir), "audit_model", "Claude Sonnet 5.0"])[0], 0)
        self.assertEqual(run(["set-setting", str(self.run_dir), "batch_chars", "60000"])[0], 0)
        self.assertEqual(run(["set-setting", str(self.run_dir), "batch_chars", "lots"])[0], 2)
        self.assertEqual(run(["set-setting", str(self.run_dir), "nope", "1"])[0], 2)
        data = manifest_of(self.run_dir)
        self.assertEqual(data["evaluator"]["model"], "GPT-5.5")
        self.assertEqual(data["settings"]["batch_chars"], 60000)
        prompt = self.run_dir / "prompt.md"
        prompt.write_text("no placeholders here\n", encoding="utf-8")
        code, text = run(["dispatch", str(self.run_dir), "evaluator", "--prompt", str(prompt), "--batch", "001"])
        self.assertEqual(code, 0, text)
        code, text = run(["dispatch", str(self.run_dir), "auditor", "--prompt", str(prompt), "--batch", "001"])
        self.assertEqual(code, 0, text)
        code, text = run(["dispatch", str(self.run_dir), "auditor", "--prompt", str(prompt), "--batch", "002", "--model", "Claude Opus 4.8"])
        self.assertEqual(code, 0, text)
        records = manifest_of(self.run_dir)["dispatches"]
        self.assertEqual([r["model"] for r in records[-3:]], ["GPT-5.5", "Claude Sonnet 5.0", "Claude Opus 4.8"])
        code, text = run(["show", str(self.run_dir)])
        self.assertIn("model=GPT-5.5", text)
        self.assertIn("model=Claude Sonnet 5.0", text)
        self.assertIn("model=Claude Opus 4.8", text)


if __name__ == "__main__":
    unittest.main()

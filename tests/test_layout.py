import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import manifest  # noqa: E402

FIXTURES = TESTS / "fixtures"


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = manifest.main(argv)
    return code, out.getvalue()


def build_input(root: Path) -> Path:
    inp = root / "input"
    export = inp / "materials" / "exported_app_X" / "X"
    (export / "agents" / "a").mkdir(parents=True)
    (export / "tools" / "t").mkdir(parents=True)
    (export / "app.json").write_text("{}", encoding="utf-8")
    run_dir = inp / "trajectories" / "run1"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("events.jsonl").write_text((FIXTURES / "mini_run" / "events.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    (inp / "trajectories" / "prod.xlsx").write_bytes(b"PK")
    (inp / "ground_truth").mkdir()
    (inp / "ground_truth" / "zip.csv").write_text("session_id,zip_on_file\nsim-mini-0001,10001\n", encoding="utf-8")
    (inp / "docs").mkdir()
    (inp / "docs" / "intro.md").write_text("# intro\n", encoding="utf-8")
    (inp / "docs" / "old_pseudocode.md").write_text("# old\n", encoding="utf-8")
    (inp / "config").mkdir()
    (inp / "config" / "settings.json").write_text(json.dumps({"batch_conversations": 5, "model": "test-model", "mode": "single-agent"}), encoding="utf-8")
    return inp


class LayoutTests(unittest.TestCase):
    def test_scan_reports_kinds_and_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = build_input(Path(tmp))
            result = manifest.scan_input(inp)
            self.assertTrue(result["exists"])
            self.assertEqual(result["missing"], [])
            materials = result["kinds"]["materials"]["entries"]
            self.assertEqual(materials[0]["looks_like"], "ces_export")
            kinds = {Path(e["path"]).name: e.get("looks_like") for e in result["kinds"]["trajectories"]["entries"]}
            self.assertEqual(kinds, {"prod.xlsx": "tabular_export", "run1": "events_jsonl"})
            self.assertEqual([Path(p).name for p in result["existing_pseudocode"]], ["old_pseudocode.md"])
            self.assertEqual([Path(p).name for p in result["intro_docs"]], ["intro.md"])
            self.assertTrue(any("column_map.json" in h for h in result["hints"]))
            code, text = run(["scan", str(inp)])
            self.assertEqual(code, 0)
            self.assertIn("[ces_export]", text)
            code, text = run(["scan", str(Path(tmp) / "nope")])
            self.assertIn("MISSING", text)

    def test_init_from_convention_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = build_input(Path(tmp))
            out = Path(tmp) / "output"
            code, text = run(["init", "--target", "DemoCard Agent", "--input", str(inp), "--output", str(out), "--run-id", "run-A"])
            self.assertEqual(code, 0, text)
            run_dir = out / "run-A"
            data = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["run_id"], "run-A")
            self.assertEqual([Path(p).name for p in data["inputs"]["materials"]], ["exported_app_X"])
            self.assertEqual(sorted(Path(p).name for p in data["inputs"]["trajectories"]), ["prod.xlsx", "run1"])
            self.assertEqual([Path(p).name for p in data["inputs"]["ground_truth"]], ["zip.csv"])
            self.assertTrue(data["inputs"]["existing_pseudocode"].endswith("old_pseudocode.md"))
            self.assertEqual(data["settings"]["batch_conversations"], 5)
            self.assertEqual(data["settings"]["batch_chars"], 40000)
            self.assertEqual(data["evaluator"], {"mode": "single-agent", "model": "test-model", "audit_model": "test-model"})
            for sub in manifest.DIRS:
                self.assertTrue((run_dir / sub).is_dir(), sub)
            self.assertTrue((run_dir / "runtime" / "inputs.json").exists())
            self.assertTrue(data["files"]["conversations"].endswith(str(Path("normalized") / "conversations.json")))
            code, text = run(["paths", str(run_dir)])
            self.assertEqual(code, 0)
            self.assertIn("RUN_DIR=", text)
            self.assertIn("BATCHES_DIR=", text)
            self.assertIn(str(Path("normalized") / "batches"), text)
            code, text = run(["init", "--target", "DemoCard", "--output", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("-DemoCard", text)
            self.assertEqual(manifest.slug("DemoCard Agent (prod)"), "DemoCard-Agent-prod")

    def test_init_requires_a_destination(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = run(["init", "--target", "X"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()

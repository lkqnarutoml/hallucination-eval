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


def run(argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = manifest.main(argv)
    return code, buffer.getvalue()


class ManifestTests(unittest.TestCase):
    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = str(Path(tmp) / "run")
            code, _ = run(["init", run_dir, "--target", "DemoCard", "--materials", "/m", "--trajectories", "/t"])
            self.assertEqual(code, 0)
            data = json.loads((Path(run_dir) / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["phases"]["setup"]["status"], "done")
            self.assertEqual(data["inputs"]["materials"], ["/m"])
            self.assertTrue((Path(run_dir) / "normalized" / "batches").is_dir())
            code, out = run(["next", run_dir])
            self.assertEqual(out.strip(), "inventory")
            run(["set-phase", run_dir, "inventory", "done", "--force", "--note", "test"])
            run(["set-phase", run_dir, "pseudocode", "done", "--force", "--note", "2 rounds"])
            code, out = run(["next", run_dir])
            self.assertEqual(out.strip(), "spec_review")
            run(["set-batch", run_dir, "evaluate", "001", "pending"])
            run(["set-batch", run_dir, "evaluate", "002", "pending"])
            run(["set-batch", run_dir, "evaluate", "001", "done"])
            data = json.loads((Path(run_dir) / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["phases"]["evaluate"]["status"], "in_progress")
            run(["set-batch", run_dir, "evaluate", "002", "done"])
            data = json.loads((Path(run_dir) / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["phases"]["evaluate"]["status"], "done")
            run(["set-file", run_dir, "pseudocode", "/p/workflow_pseudocode.md"])
            run(["log", run_dir, "hello"])
            data = json.loads((Path(run_dir) / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["files"]["pseudocode"], "/p/workflow_pseudocode.md")
            self.assertEqual(data["log"][-1]["detail"], "hello")
            code, out = run(["show", run_dir])
            self.assertIn("evaluate", out)

    def test_init_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = str(Path(tmp) / "run")
            run(["init", run_dir, "--target", "X"])
            run(["set-phase", run_dir, "inventory", "done", "--force", "--note", "test"])
            code, out = run(["init", run_dir, "--target", "X"])
            self.assertIn("already exists", out)
            data = json.loads((Path(run_dir) / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["phases"]["inventory"]["status"], "done")

    def test_unknown_phase_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = str(Path(tmp) / "run")
            run(["init", run_dir, "--target", "X"])
            buffer = io.StringIO()
            with contextlib.redirect_stderr(buffer):
                code, _ = run(["set-phase", run_dir, "bogus", "done"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()

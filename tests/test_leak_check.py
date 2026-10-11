import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import leak_check as lc  # noqa: E402


def claude_line(name, arguments):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": arguments}]}})


class LeakCheckTests(unittest.TestCase):
    def test_detects_unlisted_and_forbidden_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "output" / "run" / "runtime").mkdir(parents=True)
            (root / "input" / "materials").mkdir(parents=True)
            batch = root / "output" / "run" / "normalized" / "batches" / "batch_001.json"
            batch.parent.mkdir(parents=True)
            batch.write_text("{}", encoding="utf-8")
            prompt = root / "output" / "run" / "runtime" / "prompt-evaluator-001.md"
            prompt.write_text("You may read %s and %s/references/evaluation_procedure.md. Write %s.\n" % (
                batch, root / "skill", root / "output" / "run" / "findings" / "batch_001.json"), encoding="utf-8")
            transcript = root / "agent.jsonl"
            transcript.write_text("\n".join([
                claude_line("Read", {"file_path": str(batch)}),
                claude_line("Read", {"file_path": str(root / "skill" / "references" / "evaluation_procedure.md")}),
                claude_line("Write", {"file_path": str(root / "output" / "run" / "findings" / "batch_001.json"), "content": "{}"}),
                claude_line("Read", {"file_path": str(root / "input" / "materials" / "tools" / "validate_zip_code.py")}),
                claude_line("Bash", {"command": "cat %s" % (root / "output" / "run" / "normalized" / "batches" / "batch_002.json")}),
            ]) + "\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = lc.main(["--prompt", str(prompt), "--transcript", str(transcript), "--forbid", str(root / "input" / "materials")])
            self.assertEqual(code, 1)
            text = out.getvalue()
            self.assertIn("VIOLATION Read", text)
            self.assertIn("validate_zip_code.py", text)
            self.assertIn("UNLISTED  Bash", text)
            self.assertIn("batch_002.json", text)
            self.assertIn("3 allowed", text)
            clean = root / "clean.json"
            clean.write_text(json.dumps([{"tool": "read_file", "input": {"path": str(batch)}}]), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lc.main(["--prompt", str(prompt), "--transcript", str(clean)]), 0)


if __name__ == "__main__":
    unittest.main()

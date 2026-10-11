import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import prompt_harness as ph  # noqa: E402

ROLES = TESTS.parent / "roles"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ph.main(argv)
    return code, out.getvalue(), err.getvalue()


class PromptHarnessTests(unittest.TestCase):
    def test_fill_and_missing(self):
        text, missing = ph.fill("a {{ONE}} b {{TWO}} {{ONE}}", {"ONE": "x"})
        self.assertEqual(text, "a x b {{TWO}} x")
        self.assertEqual(missing, ["TWO"])
        self.assertEqual(ph.placeholders_of("{{B}} {{A}} {{B}}"), ["B", "A"])

    def test_cli_fills_injects_and_refuses_unfilled(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "t.md"
            template.write_text("Run {{RUN_DIR}}\n{{NOTES}}\n", encoding="utf-8")
            notes = Path(tmp) / "notes.md"
            notes.write_text("review line\n", encoding="utf-8")
            out = Path(tmp) / "out" / "p.md"
            code, _, err = run(["--template", str(template), "--var", "RUN_DIR=C:\\runs\\x", "--output", str(out)])
            self.assertEqual(code, 1)
            self.assertIn("NOTES", err)
            code, _, _ = run(["--template", str(template), "--var", "RUN_DIR=C:\\runs\\x", "--inject-file", "NOTES=%s" % notes, "--output", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(out.read_text(encoding="utf-8"), "Run C:\\runs\\x\nreview line\n")

    def test_every_role_lists_its_placeholders(self):
        for role in sorted(ROLES.glob("*.md")):
            text = role.read_text(encoding="utf-8")
            used = set(ph.placeholders_of(text))
            self.assertTrue(used, role.name)
            for name in used:
                self.assertIn("| `{{%s}}` |" % name, text, "%s does not declare %s" % (role.name, name))


if __name__ == "__main__":
    unittest.main()

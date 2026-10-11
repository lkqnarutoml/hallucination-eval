import contextlib
import io
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import check_skill as cs  # noqa: E402


class CheckSkillTests(unittest.TestCase):
    def test_skill_passes_static_checks(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cs.main(["--skill-dir", str(TESTS.parent)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("check_skill: OK", out.getvalue())

    def test_frontmatter_parser(self):
        fields = cs.frontmatter('---\nname: x\ndescription: "a b"\nmetadata:\n  version: "1"\n---\nbody')
        self.assertEqual(fields["name"], "x")
        self.assertEqual(fields["description"], "a b")
        self.assertEqual(cs.frontmatter("no frontmatter"), {})


if __name__ == "__main__":
    unittest.main()

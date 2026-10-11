import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
sys.path.insert(0, str(SKILL / "scripts"))

import setup_skill  # noqa: E402

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
AGENT_COUNT = 7


class SetupSkillTests(unittest.TestCase):
    """Runs a copied setup_skill.py as a subprocess, the way a user does, so its own location decides what is installed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        # the situation after "Extract All": a workspace folder holding the skill folder, with the zip next to it
        self.workspace = self.root / "hallucination_eval"
        self.source = self.workspace / "hallucination-eval"
        shutil.copytree(SKILL, self.source, ignore=IGNORE)
        (self.source / "scripts" / "__pycache__").mkdir()
        (self.source / "scripts" / "__pycache__" / "junk.pyc").write_bytes(b"x")
        (self.workspace / "hallucination-eval-0.3.0.zip").write_bytes(b"PK")
        self.home = self.root / "home"
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_setup(self, *args, cwd=None, script=None):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        result = subprocess.run([sys.executable, str(script or self.source / "scripts" / "setup_skill.py")] + list(args),
                                cwd=str(cwd or self.workspace), capture_output=True, text=True, env=env)
        return result.returncode, result.stdout + result.stderr

    def test_installs_into_github_skills_and_verifies(self):
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        target = self.workspace / ".github" / "skills" / "hallucination-eval"
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((target / "scripts" / "check_skill.py").is_file())
        self.assertTrue((target / "tests" / "fixtures" / "mini_run" / "events.jsonl").is_file())
        self.assertFalse((target / "scripts" / "__pycache__" / "junk.pyc").exists())
        for kind in setup_skill.INPUT_KINDS:
            self.assertTrue((self.workspace / "input" / kind).is_dir(), kind)
        self.assertTrue((self.workspace / "output").is_dir())
        self.assertIn("check_skill: OK", out)
        self.assertIn("setup: OK", out)
        self.assertIn("scan input", out)
        self.assertTrue((self.workspace / "hallucination-eval-0.3.0.zip").exists())
        self.assertTrue((self.source / "SKILL.md").exists())
        # a second run has nothing to copy and still succeeds
        code, out = self.run_setup("--no-check")
        self.assertEqual(code, 0, out)
        self.assertIn("already installed", out)
        self.assertIn("already present", out)
        # --force replaces the installed copy
        (target / "marker.txt").write_text("x", encoding="utf-8")
        code, out = self.run_setup("--force", "--no-check")
        self.assertEqual(code, 0, out)
        self.assertIn("replacing", out)
        self.assertFalse((target / "marker.txt").exists())
        self.assertTrue((target / "SKILL.md").is_file())

    def test_workspace_defaults_to_the_folder_holding_the_skill_when_run_inside_it(self):
        code, out = self.run_setup("--no-check", cwd=self.source / "scripts")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.workspace / ".github" / "skills" / "hallucination-eval" / "SKILL.md").is_file())
        self.assertFalse((self.source / ".github").exists())
        self.assertFalse((self.source / "input").exists())

    def test_default_workspace_helper(self):
        self.assertEqual(setup_skill.default_workspace(self.source, cwd=self.source / "roles"), self.workspace)
        self.assertEqual(setup_skill.default_workspace(self.source, cwd=self.source), self.workspace)
        self.assertEqual(setup_skill.default_workspace(self.source, cwd=self.workspace), self.workspace)
        self.assertEqual(setup_skill.default_workspace(self.source, cwd=self.root), self.root)

    def test_dry_run_changes_nothing(self):
        code, out = self.run_setup("--dry-run", "--agents")
        self.assertEqual(code, 0, out)
        self.assertIn("would copy", out)
        self.assertIn("dry run complete", out)
        self.assertFalse((self.workspace / ".github").exists())
        self.assertFalse((self.workspace / "input").exists())
        self.assertFalse((self.workspace / "output").exists())

    def test_agents_other_hosts_and_user_install(self):
        code, out = self.run_setup("--agents", "--no-check")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(list((self.workspace / ".github" / "agents").glob("*.agent.md"))), AGENT_COUNT)
        code, out = self.run_setup("--agents", "--no-check")
        self.assertEqual(code, 0, out)
        self.assertIn("kept existing", out)
        code, out = self.run_setup("--host", "claude", "--agents", "--no-check")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.workspace / ".claude" / "skills" / "hallucination-eval" / "SKILL.md").is_file())
        self.assertEqual(len(list((self.workspace / ".claude" / "agents").glob("*.md"))), AGENT_COUNT)
        code, out = self.run_setup("--host", "codex", "--no-check")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.workspace / ".agents" / "skills" / "hallucination-eval" / "SKILL.md").is_file())
        code, out = self.run_setup("--user", "--no-check")  # HOME and USERPROFILE point at the temporary folder
        self.assertEqual(code, 0, out)
        self.assertTrue((self.home / ".copilot" / "skills" / "hallucination-eval" / "SKILL.md").is_file())
        code, out = self.run_setup("--host", "codex", "--user", "--no-check")
        self.assertEqual(code, 1)
        self.assertIn("not available", out)

    def test_evaluator_model_is_pinned_into_the_agent_files(self):
        code, out = self.run_setup("--evaluator-model", "GPT-5.5", "--no-check")
        self.assertEqual(code, 0, out)
        agents = self.workspace / ".github" / "agents"
        self.assertEqual(len(list(agents.glob("*.agent.md"))), AGENT_COUNT)  # --evaluator-model implies --agents
        for name in ("hallu-evaluator.agent.md", "hallu-auditor.agent.md"):
            text = (agents / name).read_text(encoding="utf-8")
            head = text[: text.find("\n---", 3)]
            self.assertIn("model: GPT-5.5", head, name)
        self.assertNotIn("model:", (agents / "hallu-normalizer.agent.md").read_text(encoding="utf-8"))
        self.assertIn("pinned", out)
        self.assertIn("evaluator=GPT-5.5", out)
        self.assertIn("auditor=GPT-5.5", out)
        code, out = self.run_setup("--evaluator-model", "Claude Opus 4.8", "--auditor-model", "Claude Sonnet 5.0", "--no-check")
        self.assertEqual(code, 0, out)
        text = (agents / "hallu-evaluator.agent.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("model:"), 1)  # replaced, never duplicated
        self.assertIn("model: Claude Opus 4.8", text)
        self.assertIn("model: Claude Sonnet 5.0", (agents / "hallu-auditor.agent.md").read_text(encoding="utf-8"))
        code, out = self.run_setup("--auditor-model", "GPT-5.5", "--no-check")  # the auditor alone
        self.assertEqual(code, 0, out)
        self.assertIn("model: Claude Opus 4.8", (agents / "hallu-evaluator.agent.md").read_text(encoding="utf-8"))
        self.assertIn("model: GPT-5.5", (agents / "hallu-auditor.agent.md").read_text(encoding="utf-8"))
        code, out = self.run_setup("--host", "claude", "--evaluator-model", "opus", "--no-check")
        self.assertEqual(code, 0, out)
        self.assertIn("model: opus", (self.workspace / ".claude" / "agents" / "hallu-auditor.md").read_text(encoding="utf-8"))

    def test_refuses_an_install_location_inside_the_skill(self):
        code, out = self.run_setup("--workspace", str(self.source), "--no-check")
        self.assertEqual(code, 1)
        self.assertIn("inside the skill folder", out)
        self.assertFalse((self.source / ".github").exists())
        self.assertFalse((self.source / "input").exists())

    def test_refuses_a_nested_extraction_inside_the_install_location(self):
        nested_workspace = self.root / "ws2"
        nested = nested_workspace / ".github" / "skills" / "hallucination-eval" / "hallucination-eval"
        shutil.copytree(SKILL, nested, ignore=IGNORE)
        code, out = self.run_setup("--workspace", str(nested_workspace), "--no-check", script=nested / "scripts" / "setup_skill.py")
        self.assertEqual(code, 1)
        self.assertIn("nested", out)
        self.assertTrue((nested / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()

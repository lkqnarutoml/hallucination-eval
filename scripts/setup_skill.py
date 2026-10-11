#!/usr/bin/env python3
"""Install the hallucination-eval skill folder where an Agent-Skills host looks for it, then verify the copy.

    python scripts/setup_skill.py [--workspace DIR] [--host vscode|claude|codex] [--user] [--agents] [--force]
                                  [--evaluator-model NAME] [--auditor-model NAME] [--no-input] [--tests] [--no-check] [--dry-run]

Run it from the extracted folder, wherever the zip was unpacked; nesting does not matter because the script finds
the skill folder it lives in. It copies that folder to the place the host reads skills from:

    vscode   <workspace>/.github/skills/hallucination-eval    --user: <home>/.copilot/skills/hallucination-eval
    claude   <workspace>/.claude/skills/hallucination-eval    --user: <home>/.claude/skills/hallucination-eval
    codex    <workspace>/.agents/skills/hallucination-eval

then creates the input/ and output/ folder convention in the workspace (--no-input skips it), optionally installs
the named-agent adapters (--agents: vscode -> .github/agents, claude -> .claude/agents; --evaluator-model NAME
writes `model: NAME` into the evaluator agent file and --auditor-model NAME into the auditor agent file, default the
same model, so P6 and P7 run on the models the user chose at setup, for example GPT-5.5 on Copilot) and runs
check_skill.py on
the installed copy (--tests adds the unit tests, --no-check skips the check). The workspace is the folder you open
in the editor: it defaults to the current directory, or to the folder that contains the skill when the current
directory is inside the skill. Nothing is overwritten unless --force, and --force only replaces an earlier installed
copy of this skill or the agent files. Exit 0 when installed and verified, 1 on a problem. Standard library only;
behaves the same on Windows (py -3), macOS and Linux.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_skill import frontmatter  # noqa: E402

SKILL_NAME = "hallucination-eval"
HOSTS: Dict[str, dict] = {
    "vscode": {"label": "VS Code GitHub Copilot",
               "skills": {"workspace": (".github", "skills"), "user": (".copilot", "skills")},
               "agents": {"source": ("adapters", "vscode-copilot"), "pattern": "*.agent.md",
                          "workspace": (".github", "agents"), "user": (".copilot", "agents")}},
    "claude": {"label": "Claude Code",
               "skills": {"workspace": (".claude", "skills"), "user": (".claude", "skills")},
               "agents": {"source": ("adapters", "claude-code", "agents"), "pattern": "*.md",
                          "workspace": (".claude", "agents"), "user": (".claude", "agents")}},
    "codex": {"label": "Codex or another Agent-Skills host",
              "skills": {"workspace": (".agents", "skills"), "user": None},
              "agents": None},
}
INPUT_KINDS = ("materials", "trajectories", "ground_truth", "docs", "config")
MODEL_PINNED_FILES = {"vscode": {"evaluator": "hallu-evaluator.agent.md", "auditor": "hallu-auditor.agent.md"},
                      "claude": {"evaluator": "hallu-evaluator.md", "auditor": "hallu-auditor.md"}}
IGNORED_NAMES = ("__pycache__", ".DS_Store", "Thumbs.db")
IGNORED = shutil.ignore_patterns("*.pyc", *IGNORED_NAMES)
VERSION_RE = re.compile(r"^\s+version:\s*[\"']?([^\"'\r\n]+)", re.M)


def python_command() -> str:
    return "py -3" if sys.platform == "win32" else "python3"


def skill_info(folder: Path) -> Optional[dict]:
    """Name and version from SKILL.md, or None when the folder is not a skill folder."""
    skill_md = folder / "SKILL.md"
    if not skill_md.is_file():
        return None
    text = skill_md.read_text(encoding="utf-8")
    fields = frontmatter(text)
    if not fields.get("name"):
        return None
    end = text.find("\n---", 3) if text.startswith("---") else -1
    match = VERSION_RE.search(text[:end]) if end > 0 else None
    return {"name": fields["name"], "version": match.group(1).strip() if match else "?"}


def is_this_skill(folder: Path) -> bool:
    info = skill_info(folder)
    return bool(info) and info["name"] == SKILL_NAME


def default_workspace(source: Path, cwd: Optional[Path] = None) -> Path:
    """The current directory, unless it is inside the skill folder: then the folder that contains the skill."""
    cwd = (cwd or Path.cwd()).resolve()
    if cwd == source or source in cwd.parents:
        return source.parent
    return cwd


def install_root(host: str, workspace: Path, user: bool) -> Optional[Path]:
    parts = HOSTS[host]["skills"]["user" if user else "workspace"]
    if parts is None:
        return None
    return (Path.home() if user else workspace).joinpath(*parts)


def agents_root(host: str, workspace: Path, user: bool) -> Optional[Path]:
    spec = HOSTS[host]["agents"]
    if spec is None:
        return None
    return (Path.home() if user else workspace).joinpath(*spec["user" if user else "workspace"])


def display(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def quoted(path: str) -> str:
    return '"%s"' % path if " " in path else path


def count_files(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.is_file() and p.suffix != ".pyc" and not any(n in p.parts for n in IGNORED_NAMES))


def environment() -> Tuple[List[str], List[str]]:
    lines = ["python       : %s (%s)" % (sys.version.split()[0], sys.executable)]
    problems: List[str] = []
    if sys.version_info < (3, 10):
        problems.append("Python 3.10 or newer is required; this is %s" % sys.version.split()[0])
    try:
        import openpyxl  # noqa: F401
        lines.append("openpyxl     : installed (xlsx trajectories supported)")
    except ImportError:
        lines.append("openpyxl     : not installed (only needed for xlsx trajectories: %s -m pip install openpyxl)" % python_command())
    return lines, problems


def install_skill(source: Path, target: Path, force: bool, dry_run: bool) -> List[str]:
    """Copy the skill folder to target; returns the problems found (empty when the copy is in place)."""
    if target == source:
        print("skill already at the install location; nothing to copy")
        return []
    if source in target.parents:
        return ["the install location is inside the skill folder; pass --workspace <the folder that contains %s>" % SKILL_NAME]
    if target in source.parents:
        return ["the skill folder is nested one level too deep inside %s; move the folder that holds SKILL.md up one level "
                "(so that SKILL.md sits directly in that location), then run again" % target]
    if target.exists():
        if not is_this_skill(target):
            return ["%s exists but is not a %s skill folder; move it away and run again" % (target, SKILL_NAME)]
        installed = skill_info(target)["version"]
        if not force:
            print("already installed at %s (version %s); use --force to replace it with this copy" % (target, installed))
            return []
        print("replacing the installed copy (version %s)" % installed)
        if not dry_run:
            shutil.rmtree(target)
    if dry_run:
        print("would copy %d file(s) -> %s" % (count_files(source), target))
        return []
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=IGNORED)
    print("copied %d file(s) -> %s" % (count_files(target), target))
    return []


def create_layout(workspace: Path, dry_run: bool) -> None:
    wanted = [workspace / "input" / kind for kind in INPUT_KINDS] + [workspace / "output"]
    created: List[str] = []
    for folder in wanted:
        if folder.is_dir():
            continue
        if not dry_run:
            folder.mkdir(parents=True, exist_ok=True)
        created.append(display(folder, workspace))
    if created:
        print("%s folders: %s" % ("would create" if dry_run else "created", ", ".join(created)))
    else:
        print("input/ and output/ folders already present")


def install_agents(source: Path, host: str, workspace: Path, user: bool, force: bool, dry_run: bool) -> List[str]:
    spec = HOSTS[host]["agents"]
    dest = agents_root(host, workspace, user)
    if spec is None or dest is None:
        print("no named-agent adapters for host %s (the skill works without them)" % host)
        return []
    adapters = source.joinpath(*spec["source"])
    files = sorted(adapters.glob(spec["pattern"]))
    if not files:
        return ["no adapter files found under %s" % adapters]
    copied: List[str] = []
    kept: List[str] = []
    for file in files:
        if (dest / file.name).exists() and not force:
            kept.append(file.name)
            continue
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest / file.name)
        copied.append(file.name)
    print("%s %d agent file(s) -> %s%s" % ("would copy" if dry_run else "copied", len(copied), dest,
                                           ("; kept existing: " + ", ".join(kept)) if kept else ""))
    return []


def pin_models(host: str, workspace: Path, user: bool, models: Dict[str, str], dry_run: bool) -> List[str]:
    """Write `model: <name>` into the frontmatter of the installed agent file of each role in `models`."""
    dest = agents_root(host, workspace, user)
    names = MODEL_PINNED_FILES.get(host)
    if dest is None or not names:
        return ["host %s has no named-agent files to pin a model in" % host]
    done: List[str] = []
    for role, model in models.items():
        name = names[role]
        path = dest / name
        if not path.is_file():
            return ["%s is missing; run with --agents first" % path]
        text = path.read_text(encoding="utf-8")
        end = text.find("\n---", 3) if text.startswith("---") else -1
        if end < 0:
            return ["%s has no frontmatter block" % path]
        head, tail = text[:end], text[end:]
        line = "model: %s" % model
        if re.search(r"^model:.*$", head, re.M):
            head = re.sub(r"^model:.*$", lambda _m: line, head, count=1, flags=re.M)
        else:
            head = head + "\n" + line
        if not dry_run:
            path.write_text(head + tail, encoding="utf-8")
        done.append("%s=%s (%s)" % (role, model, name))
    print("%s in %s: %s" % ("would pin" if dry_run else "pinned", dest, "; ".join(done)))
    return []


def run_check(target: Path, tests: bool) -> List[str]:
    command = [sys.executable, str(target / "scripts" / "check_skill.py")] + (["--tests"] if tests else [])
    result = subprocess.run(command, capture_output=True, text=True)
    for line in (result.stdout or "").splitlines():
        if line.startswith(("PROBLEM", "check_skill", "note: unit tests")):
            print(line)
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        return ["check_skill.py reported a problem with the installed copy" + ((": " + detail[-400:]) if detail else "")]
    return []


def next_steps(host: str, workspace: Path, target: Path) -> List[str]:
    manifest = quoted(display(target / "scripts" / "manifest.py", workspace))
    lines = ["Next steps:",
             "  1. Put the agent export under input/materials and the conversation logs under input/trajectories",
             "     (ground_truth, docs and config are optional; see references/folders.md in the skill).",
             "  2. Check what the skill sees:  %s %s scan input" % (python_command(), manifest)]
    if host == "vscode":
        lines += ["  3. In Copilot Chat switch to Agent mode and enable the run-subagent tool 'agent' under Configure Tools,",
                  "     then type / and pick hallucination-eval, or ask: Evaluate the trajectories in input/trajectories",
                  "     for hallucinations using the materials in input/materials."]
    elif host == "claude":
        lines += ["  3. In Claude Code run /hallucination-eval, or describe the task."]
    else:
        lines += ["  3. Ask the host to run the hallucination-eval skill (single-agent mode when it has no subagent tool)."]
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", help="the folder you open in the editor (default: the current directory, or the folder "
                                            "that contains the skill when run from inside it)")
    parser.add_argument("--host", choices=sorted(HOSTS), default="vscode", help="which host reads the skill (default: vscode)")
    parser.add_argument("--user", action="store_true", help="install under your home folder, for every workspace, instead of this workspace")
    parser.add_argument("--agents", action="store_true", help="also install the named-agent adapter files of the host")
    parser.add_argument("--force", action="store_true", help="replace an earlier installed copy and existing agent files")
    parser.add_argument("--evaluator-model", metavar="NAME", help="pin this model in the evaluator agent file, P6 (implies --agents)")
    parser.add_argument("--auditor-model", metavar="NAME", help="pin this model in the auditor agent file, P7 (default: the evaluator model)")
    parser.add_argument("--no-input", action="store_true", help="do not create the input/ and output/ folders")
    parser.add_argument("--tests", action="store_true", help="also run the unit tests of the installed copy")
    parser.add_argument("--no-check", action="store_true", help="skip check_skill.py on the installed copy")
    parser.add_argument("--dry-run", action="store_true", help="print what would be done and change nothing")
    args = parser.parse_args(argv)
    if args.evaluator_model or args.auditor_model:
        args.agents = True

    source = SCRIPT_DIR.parent
    info = skill_info(source)
    if not info or info["name"] != SKILL_NAME:
        print("PROBLEM: %s is not the %s skill folder (SKILL.md missing or named differently)" % (source, SKILL_NAME))
        return 1
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else default_workspace(source)
    root = install_root(args.host, workspace, args.user)
    if root is None:
        print("PROBLEM: --user is not available for host %s; install into a workspace instead" % args.host)
        return 1
    target = root / SKILL_NAME
    env_lines, problems = environment()
    print("%s setup%s" % (SKILL_NAME, " (dry run: nothing is changed)" if args.dry_run else ""))
    print("  skill source : %s (version %s)" % (source, info["version"]))
    print("  workspace    : %s" % workspace)
    print("  host         : %s (%s)" % (args.host, HOSTS[args.host]["label"]))
    print("  install to   : %s" % target)
    for line in env_lines:
        print("  " + line)
    print("")
    if not problems:
        problems += install_skill(source, target, args.force, args.dry_run)
    if not problems:
        if not args.no_input:
            create_layout(workspace, args.dry_run)
        if args.agents:
            problems += install_agents(source, args.host, workspace, args.user, args.force, args.dry_run)
        if not problems and (args.evaluator_model or args.auditor_model):
            models = {}
            if args.evaluator_model:
                models["evaluator"] = args.evaluator_model
            if args.auditor_model or args.evaluator_model:
                models["auditor"] = args.auditor_model or args.evaluator_model
            problems += pin_models(args.host, workspace, args.user, models, args.dry_run)
    if not problems and not args.no_check and not args.dry_run:
        problems += run_check(target, args.tests)
    print("")
    if problems:
        for problem in problems:
            print("PROBLEM: " + problem)
        print("setup: FAIL")
        return 1
    if args.dry_run:
        print("setup: dry run complete")
        return 0
    print("setup: OK")
    for line in next_steps(args.host, workspace, target):
        print(line)
    if target != source:
        print("The extracted folder %s and its zip are no longer needed; delete them when you like." % source)
    return 0


if __name__ == "__main__":
    sys.exit(main())

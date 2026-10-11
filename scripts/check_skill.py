#!/usr/bin/env python3
"""Static self-check of the hallucination-eval skill (for maintainers; not part of a run).

    python scripts/check_skill.py [--skill-dir PATH] [--tests]

Checks
    1. SKILL.md frontmatter: name matches the folder, name pattern, description length, required keys.
    2. Every {{PLACEHOLDER}} used by a role prompt is declared in that role's own "Placeholders" table and is
       provided by a harness command in references/cli-cheatsheet.md.
    3. Every relative path mentioned in SKILL.md, roles/ and references/ as `scripts/...`, `references/...`,
       `assets/...`, `roles/...` exists.
    4. Every script byte-compiles; no script uses os.system or shell=True; console output is ASCII.
    5. With --tests, runs the unit tests with unittest discovery.
Exit 1 on any failure. Standard library only.
"""
from __future__ import annotations

import argparse
import py_compile
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Set

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
PATH_RE = re.compile(r"(?<![\w/])((?:scripts|references|assets|roles|adapters|evals|tests)/[A-Za-z0-9_./-]+)")


def frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fields = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--tests", action="store_true")
    args = parser.parse_args(argv)
    skill = Path(args.skill_dir).resolve()
    problems: List[str] = []
    notes: List[str] = []

    skill_md = skill / "SKILL.md"
    if not skill_md.exists():
        problems.append("SKILL.md is missing")
        text = ""
    else:
        text = skill_md.read_text(encoding="utf-8")
        fields = frontmatter(text)
        name = fields.get("name", "")
        if not fields:
            problems.append("SKILL.md has no YAML frontmatter")
        if name != skill.name:
            problems.append("frontmatter name %r does not match folder %r" % (name, skill.name))
        if not NAME_RE.match(name or ""):
            problems.append("frontmatter name %r is not lowercase-hyphenated" % name)
        description = fields.get("description", "")
        if not description:
            problems.append("frontmatter description is empty")
        elif len(description) > 1024:
            problems.append("frontmatter description is %d characters (max 1024)" % len(description))
        body_lines = text.count("\n")
        notes.append("SKILL.md: %d lines, description %d chars" % (body_lines, len(description)))
        if body_lines > 500:
            problems.append("SKILL.md body exceeds 500 lines (%d)" % body_lines)

    cheatsheet = skill / "references" / "cli-cheatsheet.md"
    cheat_text = cheatsheet.read_text(encoding="utf-8") if cheatsheet.exists() else ""
    provided_by_cheatsheet: Set[str] = set(re.findall(r"--var\s+([A-Z][A-Z0-9_]*)=", cheat_text)) | set(re.findall(r"--inject-file\s+([A-Z][A-Z0-9_]*)=", cheat_text))
    roles_dir = skill / "roles"
    for role in sorted(roles_dir.glob("*.md")) if roles_dir.exists() else []:
        role_text = role.read_text(encoding="utf-8")
        used = set(PLACEHOLDER_RE.findall(role_text))
        declared = set(re.findall(r"^\|\s*`?\{\{([A-Z][A-Z0-9_]*)\}\}`?\s*\|", role_text, re.M))
        for name in sorted(used - declared):
            problems.append("%s uses {{%s}} but its Placeholders table does not declare it" % (role.name, name))
        for name in sorted(declared - used):
            problems.append("%s declares {{%s}} but never uses it" % (role.name, name))
        for name in sorted(used - provided_by_cheatsheet):
            problems.append("%s needs {{%s}} but no harness command in references/cli-cheatsheet.md provides it" % (role.name, name))
        notes.append("%s: %d placeholders" % (role.name, len(used)))

    for doc in [skill_md] + sorted((skill / "roles").glob("*.md")) + sorted((skill / "references").glob("*.md")) + [skill / "README.md"]:
        if not doc.exists():
            continue
        doc_text = doc.read_text(encoding="utf-8")
        for match in PATH_RE.findall(doc_text):
            candidate = match.rstrip(".,;:)")
            if "<" in candidate or "NNN" in candidate or "*" in candidate or candidate.endswith("/"):
                continue
            if not (skill / candidate).exists():
                problems.append("%s mentions %s which does not exist" % (doc.relative_to(skill), candidate))

    scripts = sorted((skill / "scripts").glob("*.py")) + sorted((skill / "scripts" / "halu_common").glob("*.py")) + sorted((skill / "assets").glob("*.py"))
    for script in scripts:
        try:
            py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as error:
            problems.append("%s does not compile: %s" % (script.relative_to(skill), error))
            continue
        source = script.read_text(encoding="utf-8")
        forbidden = ("os." + "system(", "shell" + "=True")
        if script.name != "check_skill.py" and any(token in source for token in forbidden):
            problems.append("%s uses os.system or shell=True" % script.relative_to(skill))
        for number, line in enumerate(source.splitlines(), start=1):
            if line.strip().startswith("print(") and any(ord(ch) > 127 for ch in line):
                problems.append("%s:%d prints non-ASCII text (Windows console safety)" % (script.relative_to(skill), number))
    notes.append("%d scripts compiled" % len(scripts))

    if args.tests:
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(skill / "tests"), "-p", "test_*.py"],
                                cwd=str(skill), capture_output=True, text=True)
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        notes.append("unit tests: " + " | ".join(tail))
        if result.returncode != 0:
            problems.append("unit tests failed")

    for note in notes:
        print("note: " + note)
    for problem in problems:
        print("PROBLEM: " + problem)
    print("check_skill: %s (%d problem(s))" % ("FAIL" if problems else "OK", len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

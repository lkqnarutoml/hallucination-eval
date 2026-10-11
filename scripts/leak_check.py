#!/usr/bin/env python3
"""Check a subagent's transcript for file accesses outside what its role prompt allowed.

    python scripts/leak_check.py --prompt RUN_DIR/runtime/prompt-evaluator-001.md --transcript TRANSCRIPT
           [--allow PATH ...] [--forbid PATH ...] [--json]

Isolation between roles is enforced by construction where a script decides what a role receives (one batch file,
a blind audit payload, placeholders that name only allowed files) and by instruction where the role could still
open other files with its tools. This script closes that gap after the fact: it lists every file the subagent
read, edited, listed or searched, and flags anything outside the paths its prompt named.

Allowed set = every path written in the prompt file (a file allows itself; a folder allows everything under it)
plus --allow paths. Forbidden set = --forbid paths (a folder forbids everything under it), checked first.
Transcript formats: Claude Code subagent transcripts (JSONL with assistant messages holding tool_use blocks:
Read, Glob, Grep, Edit, Write, NotebookEdit, Bash), or a JSON list / JSONL of {"tool": name, "input": {...}}
objects exported from another host. Bash commands are scanned for path-like tokens.
Exit 0 when clean, 1 when a forbidden or unlisted access was found, 2 on unreadable input. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/|\.\.?[\\/]|~[\\/])?(?:[\w.\-]+[\\/])+[\w.\-]*|[\w.\-]+\.(?:md|json|jsonl|py|txt|csv|xlsx|yaml|yml)")
FILE_TOOLS = {"Read", "Glob", "Grep", "Edit", "Write", "NotebookEdit", "MultiEdit", "read_file", "read", "list_dir", "search", "readFile", "editFiles"}
SHELL_TOOLS = {"Bash", "PowerShell", "run_in_terminal", "runCommands", "shell", "execute"}
PATH_KEYS = ("file_path", "path", "notebook_path", "filePath", "uri", "directory", "dir", "target")


def normalize(path: str, base: Optional[Path]) -> Path:
    text = path.strip().strip("'\"`")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute() and base is not None:
        candidate = base / candidate
    try:
        return candidate.resolve()
    except OSError:
        return candidate


def prompt_paths(prompt_text: str, base: Optional[Path]) -> Set[Path]:
    found: Set[Path] = set()
    for match in PATH_RE.finditer(prompt_text):
        token = match.group(0).rstrip(".,;:)")
        if len(token) < 4 or token.lower() in ("e.g.", "i.e."):
            continue
        if "/" not in token and "\\" not in token and not re.search(r"\.[a-z]+$", token):
            continue
        found.add(normalize(token, base))
    return found


def _tool_calls(transcript: Path) -> Iterable[Tuple[str, dict]]:
    text = transcript.read_text(encoding="utf-8", errors="replace")
    stripped = text.strip()
    records: List[Any] = []
    if stripped.startswith("["):
        try:
            records = json.loads(stripped)
        except ValueError:
            records = []
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    for record in records:
        if not isinstance(record, dict):
            continue
        if "tool" in record and isinstance(record.get("input") or record.get("arguments"), dict):
            yield str(record["tool"]), dict(record.get("input") or record.get("arguments") or {})
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else record
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield str(block.get("name")), dict(block.get("input") or {})


def accesses_of(transcript: Path, base: Optional[Path]) -> List[dict]:
    accesses: List[dict] = []
    for tool, arguments in _tool_calls(transcript):
        if tool in FILE_TOOLS:
            for key in PATH_KEYS:
                value = arguments.get(key)
                if isinstance(value, str) and value.strip():
                    accesses.append({"tool": tool, "path": str(normalize(value, base)), "raw": value})
            if tool in ("Glob", "Grep", "search") and isinstance(arguments.get("pattern"), str) and not any(k in arguments for k in PATH_KEYS):
                accesses.append({"tool": tool, "path": str(base or Path.cwd()), "raw": arguments["pattern"]})
        elif tool in SHELL_TOOLS:
            command = arguments.get("command") or arguments.get("cmd") or arguments.get("script") or ""
            if isinstance(command, str):
                for match in PATH_RE.finditer(command):
                    token = match.group(0).rstrip(".,;:)")
                    if ("/" in token or "\\" in token) and len(token) > 3:
                        accesses.append({"tool": tool, "path": str(normalize(token, base)), "raw": token})
    return accesses


def _under(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def classify(accesses: List[dict], allowed: Set[Path], forbidden: Set[Path]) -> Tuple[List[dict], List[dict], List[dict]]:
    ok, unlisted, violations = [], [], []
    for access in accesses:
        path = Path(access["path"])
        if any(path == f or _under(path, f) for f in forbidden):
            violations.append(access)
        elif any(path == a or _under(path, a) for a in allowed):
            ok.append(access)
        else:
            unlisted.append(access)
    return ok, unlisted, violations


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompt", required=True, help="the filled role prompt the subagent received")
    parser.add_argument("--transcript", required=True, help="the subagent transcript (JSONL or JSON list)")
    parser.add_argument("--allow", nargs="*", default=[], help="extra allowed files or folders")
    parser.add_argument("--forbid", nargs="*", default=[], help="folders or files the role must never touch (e.g. input/materials for an evaluator)")
    parser.add_argument("--base-dir", help="directory relative paths are resolved against (default: current directory)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    prompt = Path(args.prompt)
    transcript = Path(args.transcript)
    if not prompt.exists() or not transcript.exists():
        print("error: prompt or transcript does not exist", file=sys.stderr)
        return 2
    base = Path(args.base_dir).resolve() if args.base_dir else Path.cwd()
    allowed = prompt_paths(prompt.read_text(encoding="utf-8", errors="replace"), base) | {normalize(p, base) for p in args.allow}
    allowed.add(prompt.resolve())
    forbidden = {normalize(p, base) for p in args.forbid}
    accesses = accesses_of(transcript, base)
    ok, unlisted, violations = classify(accesses, allowed, forbidden)
    result = {"prompt": str(prompt), "transcript": str(transcript), "accesses": len(accesses), "allowed": len(ok),
              "unlisted": unlisted, "violations": violations}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("leak check: %d access(es), %d allowed, %d unlisted, %d violation(s)" % (len(accesses), len(ok), len(unlisted), len(violations)))
        for item in violations:
            print("VIOLATION %s %s" % (item["tool"], item["raw"]))
        for item in unlisted:
            print("UNLISTED  %s %s" % (item["tool"], item["raw"]))
    return 1 if (violations or unlisted) else 0


if __name__ == "__main__":
    sys.exit(main())

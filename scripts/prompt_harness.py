#!/usr/bin/env python3
"""Fill the {{PLACEHOLDER}} slots of a role prompt and write a ready-to-send prompt file.

    python scripts/prompt_harness.py --template roles/evaluator.md --var RUN_DIR=... --var BATCH_ID=003
           [--var-file vars.json] [--inject-file KEY=path] --output RUN_DIR/runtime/prompt-evaluator-003.md
           [--list]   # print the placeholders a template uses and exit

Rules
    * Every {{NAME}} in the template must be filled; a left-over placeholder is an error (exit 1) so that a
      subagent never receives a half-filled prompt.
    * --inject-file reads a file and substitutes its whole content (used for review notes or checker output).
    * Values are inserted verbatim. Paths are passed through unchanged, so use the path style of the host
      (backslashes on Windows are fine).
    * The output file is written with UTF-8 and a trailing newline. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def placeholders_of(text: str) -> List[str]:
    seen: List[str] = []
    for match in PLACEHOLDER_RE.finditer(text):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def fill(template: str, values: Dict[str, str]) -> Tuple[str, List[str]]:
    missing: List[str] = []

    def replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name in values:
            return values[name]
        if name not in missing:
            missing.append(name)
        return match.group(0)

    return PLACEHOLDER_RE.sub(replace, template), missing


def parse_pair(raw: str, flag: str) -> Tuple[str, str]:
    if "=" not in raw:
        print("error: %s expects KEY=VALUE, got %r" % (flag, raw), file=sys.stderr)
        sys.exit(2)
    key, _, value = raw.partition("=")
    key = key.strip()
    if not PLACEHOLDER_RE.fullmatch("{{%s}}" % key):
        print("error: %s key %r must be UPPER_SNAKE_CASE" % (flag, key), file=sys.stderr)
        sys.exit(2)
    return key, value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--template", required=True)
    parser.add_argument("--var", action="append", default=[], help="KEY=VALUE (repeatable)")
    parser.add_argument("--var-file", help="JSON object of KEY: VALUE pairs")
    parser.add_argument("--inject-file", action="append", default=[], help="KEY=path; the file content fills KEY")
    parser.add_argument("--output")
    parser.add_argument("--list", action="store_true", help="print the placeholders of the template and exit")
    args = parser.parse_args(argv)
    template_path = Path(args.template)
    if not template_path.exists():
        print("error: template %s does not exist" % template_path, file=sys.stderr)
        return 2
    template = template_path.read_text(encoding="utf-8")
    if args.list:
        for name in placeholders_of(template):
            print(name)
        return 0
    values: Dict[str, str] = {}
    if args.var_file:
        data = json.loads(Path(args.var_file).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            print("error: --var-file must hold a JSON object", file=sys.stderr)
            return 2
        for key, value in data.items():
            values[str(key)] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    for raw in args.var:
        key, value = parse_pair(raw, "--var")
        values[key] = value
    for raw in args.inject_file:
        key, path = parse_pair(raw, "--inject-file")
        source = Path(path)
        if not source.exists():
            print("error: inject file %s does not exist" % source, file=sys.stderr)
            return 2
        values[key] = source.read_text(encoding="utf-8").strip()
    filled, missing = fill(template, values)
    if missing:
        print("error: unfilled placeholders: %s" % ", ".join(missing), file=sys.stderr)
        return 1
    unused = sorted(set(values) - set(placeholders_of(template)))
    if unused:
        print("note: values not used by the template: %s" % ", ".join(unused))
    if not args.output:
        print("error: --output is required unless --list is given", file=sys.stderr)
        return 2
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(filled.rstrip("\n") + "\n", encoding="utf-8")
    print("prompt written to %s (%d placeholders filled)" % (out, len(placeholders_of(template))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

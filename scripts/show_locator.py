#!/usr/bin/env python3
"""Print the source record a locator points at, redacted the same way the normalizer redacts payloads.

    python scripts/show_locator.py LOCATOR [--base-dir DIR] [--max-chars 4000]

For an evaluator or auditor that meets a capped value in a batch ("...[+N chars]", "_summary", "_capped") and
needs the full payload to decide one point. The record is printed as JSON when it parses, otherwise as the raw
line; bearer tokens, JWTs, secret-named keys and card numbers are redacted on the way out, so nothing this
prints is more sensitive than the batch itself. Locators keep the trajectory paths as the normalizer saw them,
so run from the same working directory or pass --base-dir. Exit 0 on success, 1 when the locator cannot be
resolved. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.locators import parse_locator, resolve_locator  # noqa: E402
from halu_common.redact import redact_value  # noqa: E402


def show(locator: str, base_dir: Optional[str], max_chars: int) -> str:
    parse_locator(locator)
    raw = resolve_locator(locator, base_dir, max_chars=10 ** 9)
    try:
        node = json.loads(raw)
    except ValueError:
        text = redact_value(raw)
    else:
        text = json.dumps(redact_value(node), ensure_ascii=False, indent=1)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[+%d chars]" % (len(text) - max_chars)
    return text


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("locator")
    parser.add_argument("--base-dir", help="directory the locator paths are relative to (default: current directory)")
    parser.add_argument("--max-chars", type=int, default=4000)
    args = parser.parse_args(argv)
    try:
        print(show(args.locator, args.base_dir, args.max_chars))
    except Exception as error:  # noqa: BLE001
        print("error: cannot resolve %s (%s)" % (args.locator, error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

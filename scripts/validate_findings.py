#!/usr/bin/env python3
"""Validate a findings file (final or one batch) against the output contract.

    python scripts/validate_findings.py FINDINGS_JSON [--schema assets/findings.schema.json]
           [--conversations conversations.json] [--batch] [--pre-audit] [--resolve-locators] [--base-dir DIR]

Checks
    1. JSON Schema (assets/findings.schema.json) with the standard-library validator in halu_common.
    2. Every hallucination has a non-empty rationale, at least one trajectory evidence item with a locator and
       at least one pseudocode reference; ids are unique; verification is present unless --pre-audit.
    3. With --conversations: every finding's conversation id and turn exist in conversations.json.
    4. With --resolve-locators: every evidence locator can be reopened (slow; needs the source files). Locators hold
       the trajectory paths as they were given to the normalizer, so run from the same working directory (the
       workspace root that holds input/) or pass --base-dir with that directory.

--batch validates an evaluator or auditor batch file (no meta block). Exit 0 when clean, 1 when errors.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json  # noqa: E402
from halu_common.locators import parse_locator, resolve_locator  # noqa: E402
from halu_common.schema_check import validate  # noqa: E402

DEFAULT_SCHEMA = SCRIPT_DIR.parent / "assets" / "findings.schema.json"


def check_conversation(conv: dict, index: int, pre_audit: bool, seen_ids: set, conv_index: dict, resolve: bool,
                       base_dir: Optional[str] = None) -> List[str]:
    errors: List[str] = []
    cid = conv.get("conversation_id")
    where = "conversations[%d] (%s)" % (index, cid)
    known = conv_index.get(cid) if conv_index else None
    if conv_index and known is None:
        errors.append("%s: conversation id not present in conversations.json" % where)
    for group in ("hallucinations", "pipeline_findings", "rejected"):
        for item in conv.get(group, []) or []:
            fid = item.get("id")
            if fid in seen_ids:
                errors.append("%s: duplicate finding id %s" % (where, fid))
            seen_ids.add(fid)
            label = "%s %s %s" % (where, group, fid)
            if not str(item.get("rationale") or "").strip():
                errors.append("%s: empty rationale" % label)
            evidence = item.get("evidence") or []
            trajectory = [e for e in evidence if e.get("kind") != "pseudocode"]
            pseudo = [e for e in evidence if e.get("kind") == "pseudocode"]
            if group != "rejected":
                if not trajectory or not all(e.get("locator") for e in trajectory):
                    errors.append("%s: needs at least one trajectory evidence item with a locator" % label)
                if not pseudo:
                    errors.append("%s: needs at least one pseudocode reference" % label)
            if group == "hallucinations" and not pre_audit and not isinstance(item.get("verification"), dict):
                errors.append("%s: missing verification block (use --pre-audit for evaluator batches)" % label)
            if known is not None and item.get("turn") is not None and item["turn"] > known.get("turns", 10 ** 6):
                errors.append("%s: turn %s exceeds the conversation's %s turns" % (label, item["turn"], known.get("turns")))
            for ev in evidence:
                locator = ev.get("locator")
                if not locator:
                    continue
                try:
                    parse_locator(locator)
                except ValueError:
                    errors.append("%s: malformed locator %r" % (label, locator))
                    continue
                if resolve:
                    try:
                        resolve_locator(locator, base_dir)
                    except Exception as error:  # noqa: BLE001
                        errors.append("%s: locator %s cannot be resolved (%s)" % (label, locator, error))
    return errors


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("findings")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--conversations")
    parser.add_argument("--batch", action="store_true", help="the file is a batch (no meta block)")
    parser.add_argument("--pre-audit", action="store_true", help="verification blocks are not required yet")
    parser.add_argument("--resolve-locators", action="store_true")
    parser.add_argument("--base-dir", help="directory the locator paths are relative to (default: current directory)")
    args = parser.parse_args(argv)
    data = read_json(args.findings)
    schema = read_json(args.schema)
    errors: List[str] = []
    if args.batch:
        conversations = data.get("conversations", [])
        conv_schema = schema.get("$defs", {}).get("conversation")
        if conv_schema:
            for index, conv in enumerate(conversations):
                errors.extend(validate(conv, conv_schema, schema, "$.conversations[%d]" % index))
    else:
        errors.extend(validate(data, schema))
        conversations = data.get("conversations", [])
    conv_index = {}
    if args.conversations:
        source = read_json(args.conversations)
        conv_index = {c["conversation_id"]: c.get("summary", {}) for c in source.get("conversations", [])}
    seen_ids: set = set()
    for index, conv in enumerate(conversations):
        errors.extend(check_conversation(conv, index, args.pre_audit, seen_ids, conv_index, args.resolve_locators, args.base_dir))
    hallucinations = sum(len(c.get("hallucinations", []) or []) for c in conversations)
    if errors:
        for error in errors[:200]:
            print("ERROR " + error)
        if len(errors) > 200:
            print("... %d more" % (len(errors) - 200))
        print("INVALID: %d error(s) in %d conversation(s), %d hallucinations" % (len(errors), len(conversations), hallucinations))
        return 1
    print("VALID: %d conversation(s), %d hallucination(s)" % (len(conversations), hallucinations))
    return 0


if __name__ == "__main__":
    sys.exit(main())

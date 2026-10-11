#!/usr/bin/env python3
"""Measure what one evaluator or auditor subagent must read for a batch, before it is dispatched.

    python scripts/context_budget.py RUN_DIR [--batch 001 ...] [--role evaluator|auditor|both]
                                             [--limit-chars 300000] [--json OUT]

Sums the characters of every file the role prompt names: the filled prompt (runtime/prompt-<role>-<batch>.md
when it exists, else the role template), the pseudocode, the batch file (evaluator) or the audit payload
(auditor, once P7 has built it), the checker result for the batch (evaluator), and the reference documents the
role may read. One row per batch and role with the total and a token estimate (characters / 4). Exit 1 when any
row exceeds --limit-chars, so the orchestrator can re-split or shrink before spending a dispatch; set the limit
to what the chosen model handles comfortably. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, write_json  # noqa: E402

SHARED_REFERENCES = ["references/hallucination_taxonomy.md", "references/judgment_rubric.md", "references/grounding_sources.md",
                     "references/evidence_rules.md", "references/output_schema.md"]
ROLE_REFERENCES = {"evaluator": ["references/evaluation_procedure.md"] + SHARED_REFERENCES,
                   "auditor": ["references/audit_procedure.md"] + SHARED_REFERENCES}
CHARS_PER_TOKEN = 4.0


def size_of(path: Optional[Path]) -> int:
    if path is None or not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8", errors="replace"))


def batch_ids(files: Dict[str, str], wanted: Optional[List[str]]) -> List[str]:
    if wanted:
        return [b.zfill(3) if b.isdigit() else b for b in wanted]
    index = Path(files.get("batches_dir", "")) / "index.json"
    if index.is_file():
        return [str(b.get("id")) for b in (read_json(index).get("batches") or [])]
    return sorted(p.stem.split("_", 1)[1] for p in Path(files.get("batches_dir", "")).glob("batch_*.json"))


def measure(run_dir: Path, files: Dict[str, str], role: str, batch: str, skill_dir: Path) -> dict:
    runtime = Path(files.get("runtime_dir") or (run_dir / "runtime"))
    prompt = runtime / ("prompt-%s-%s.md" % (role, batch))
    prompt_chars = size_of(prompt) if prompt.is_file() else size_of(skill_dir / "roles" / ("%s.md" % role))
    contract = size_of(Path(files.get("pseudocode", "")))
    if role == "evaluator":
        data_path = Path(files.get("batches_dir", "")) / ("batch_%s.json" % batch)
        checker = size_of(Path(files.get("checker_out_dir", "")) / ("batch_%s.json" % batch))
    else:
        data_path = Path(files.get("audit_dir") or (run_dir / "audit")) / ("payload_batch_%s.json" % batch)
        checker = 0
    data = size_of(data_path)
    references = sum(size_of(skill_dir / rel) for rel in ROLE_REFERENCES[role])
    total = prompt_chars + contract + data + checker + references
    return {"batch": batch, "role": role, "prompt": prompt_chars, "prompt_filled": prompt.is_file(), "contract": contract,
            "data": data, "data_file": str(data_path), "data_present": data_path.is_file(), "checker": checker,
            "references": references, "total": total, "tokens_estimate": int(round(total / CHARS_PER_TOKEN))}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir")
    parser.add_argument("--batch", nargs="*", help="batch ids (default: every batch in the index)")
    parser.add_argument("--role", choices=["evaluator", "auditor", "both"], default="both")
    parser.add_argument("--limit-chars", type=int, default=300000, help="fail above this many characters per subagent (default 300000, about 75k tokens)")
    parser.add_argument("--skill-dir", default=str(SKILL_DIR))
    parser.add_argument("--json", help="also write the rows to this file")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.is_file():
        files = dict(read_json(manifest_path).get("files") or {})
    else:
        files = {"pseudocode": str(run_dir / "workflow_pseudocode.md"), "batches_dir": str(run_dir / "normalized" / "batches"),
                 "checker_out_dir": str(run_dir / "checker" / "results"), "audit_dir": str(run_dir / "audit"), "runtime_dir": str(run_dir / "runtime")}
    ids = batch_ids(files, args.batch)
    if not ids:
        print("error: no batches found under %s (run normalize + split first)" % files.get("batches_dir"), file=sys.stderr)
        return 2
    roles = ["evaluator", "auditor"] if args.role == "both" else [args.role]
    if manifest_path.is_file() and args.role == "both":
        settings = read_json(manifest_path).get("settings") or {}
        if str(settings.get("audit", True)).lower() in ("false", "0", "no"):
            roles = ["evaluator"]
            print("audit not included in this run (settings.audit=false): evaluator rows only")
    rows = [measure(run_dir, files, role, batch, Path(args.skill_dir)) for batch in ids for role in roles]
    print("%-6s %-9s %8s %9s %9s %8s %10s %9s %8s  %s" % ("batch", "role", "prompt", "contract", "data", "checker", "references", "total", "~tokens", "status"))
    worst = 0
    for row in rows:
        over = row["total"] > args.limit_chars
        worst = max(worst, row["total"])
        status = "OVER limit %d" % args.limit_chars if over else "ok"
        if not row["data_present"]:
            status += " (data file missing: %s)" % Path(row["data_file"]).name
        print("%-6s %-9s %8d %9d %9d %8d %10d %9d %8d  %s" % (row["batch"], row["role"], row["prompt"], row["contract"], row["data"],
                                                            row["checker"], row["references"], row["total"], row["tokens_estimate"], status))
    print("largest %d chars (about %d tokens at %.0f chars per token); limit %d" % (worst, int(worst / CHARS_PER_TOKEN), CHARS_PER_TOKEN, args.limit_chars))
    if args.json:
        write_json(args.json, {"limit_chars": args.limit_chars, "chars_per_token": CHARS_PER_TOKEN, "rows": rows})
    return 1 if worst > args.limit_chars else 0


if __name__ == "__main__":
    sys.exit(main())

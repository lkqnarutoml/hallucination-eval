#!/usr/bin/env python3
"""Merge verified findings batches into the final hallucination_findings.json.

    python scripts/merge_findings.py --verified-dir RUN_DIR/findings --out RUN_DIR/hallucination_findings.json
           [--manifest RUN_DIR/run_manifest.json] [--pseudocode RUN_DIR/workflow_pseudocode.md]
           [--conversations RUN_DIR/conversations.json] [--target NAME] [--model NAME] [--mode multi-agent]
           [--unverified]   # accept findings/batch_NNN.json when no verified files exist (marks audited=false)

Rules: conversation records are concatenated in batch order; hallucination ids are renumbered globally
(H-0001, ...), pipeline findings P-0001, ...; rejected findings are kept under conversations[].rejected;
meta is built from the manifest, the pseudocode hash and the conversations.json sources.
Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, sha256_of_file, write_json  # noqa: E402

SKILL_VERSION = "0.4.0"
REFERENCE_POINTS = ["customer utterances and history", "tool catalogue", "arguments passed", "tool results",
                    "session state", "workflow rules"]


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def collect_batches(verified_dir: Path, allow_unverified: bool):
    files = sorted(verified_dir.glob("verified_batch_*.json"))
    audited = True
    if not files and allow_unverified:
        files = sorted(verified_dir.glob("batch_*.json"))
        audited = False
    return files, audited


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verified-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--pseudocode")
    parser.add_argument("--conversations")
    parser.add_argument("--target")
    parser.add_argument("--model")
    parser.add_argument("--mode")
    parser.add_argument("--unverified", action="store_true")
    args = parser.parse_args(argv)
    verified_dir = Path(args.verified_dir)
    files, audited = collect_batches(verified_dir, args.unverified)
    if not files:
        print("error: no verified_batch_*.json files in %s (pass --unverified to merge unaudited batches)" % verified_dir, file=sys.stderr)
        return 2
    manifest = read_json(args.manifest) if args.manifest and Path(args.manifest).exists() else {}
    conversations_meta = {}
    if args.conversations and Path(args.conversations).exists():
        conversations_meta = read_json(args.conversations).get("meta", {})
    merged: List[dict] = []
    seen_ids = set()
    batches_meta = []
    hallucination_counter = 0
    pipeline_counter = 0
    rejected_counter = 0
    for file in files:
        batch = read_json(file)
        batches_meta.append({"file": str(file), "batch": batch.get("batch"), "conversations": len(batch.get("conversations", []))})
        for conversation in batch.get("conversations", []):
            cid = conversation.get("conversation_id")
            if cid in seen_ids:
                print("warning: conversation %s appears in more than one batch; keeping the first" % cid, file=sys.stderr)
                continue
            seen_ids.add(cid)
            for item in conversation.get("hallucinations", []) or []:
                hallucination_counter += 1
                item["id"] = "H-%04d" % hallucination_counter
                if not audited:
                    item.setdefault("verification", {"status": "unaudited", "auditor_rationale": None, "revised_from": None})
            for item in conversation.get("pipeline_findings", []) or []:
                pipeline_counter += 1
                item["id"] = "P-%04d" % pipeline_counter
            for item in conversation.get("rejected", []) or []:
                rejected_counter += 1
                item["id"] = "R-%04d" % rejected_counter
            conversation.setdefault("rejected", [])
            conversation.setdefault("pipeline_findings", [])
            conversation.setdefault("unverifiable", [])
            conversation.setdefault("notes", [])
            conversation.setdefault("hallucinations", [])
            merged.append(conversation)
    evaluator = dict(manifest.get("evaluator", {}))
    if args.model:
        evaluator["model"] = args.model
    if args.mode:
        evaluator["mode"] = args.mode
    evaluator.setdefault("mode", "multi-agent")
    evaluator.setdefault("model", "")
    checker = (manifest.get("files") or {}).get("checker")
    evaluator["checker_script"] = checker if checker and Path(checker).exists() else None
    evaluator["batches"] = len(files)
    evaluator["audited"] = audited
    models = sorted({d.get("model") for d in manifest.get("dispatches", []) if d.get("role") in ("evaluator", "auditor") and d.get("model")})
    if models:
        evaluator["models_used"] = models
    pseudocode = args.pseudocode or (manifest.get("files") or {}).get("pseudocode")
    meta = {
        "skill": "hallucination-eval",
        "skill_version": SKILL_VERSION,
        "generated_at": now_iso(),
        "target_agent": args.target or manifest.get("target_agent") or "",
        "pseudocode_file": str(pseudocode) if pseudocode else None,
        "pseudocode_sha256": sha256_of_file(pseudocode) if pseudocode and Path(pseudocode).exists() else None,
        "materials": (manifest.get("inputs") or {}).get("materials", []),
        "trajectory_sources": conversations_meta.get("sources", (manifest.get("inputs") or {}).get("trajectories", [])),
        "evaluator": evaluator,
        "sampling": (manifest.get("settings") or {}).get("sampling"),
        "normalization": conversations_meta.get("diet"),
        "reference_points": REFERENCE_POINTS,
        "batches": batches_meta,
        "counts": {"conversations": len(merged), "hallucinations": hallucination_counter,
                   "pipeline_findings": pipeline_counter, "rejected": rejected_counter},
    }
    write_json(args.out, {"meta": meta, "conversations": merged})
    print("merged %d conversations from %d batch(es): %d hallucinations, %d pipeline findings, %d rejected -> %s" % (
        len(merged), len(files), hallucination_counter, pipeline_counter, rejected_counter, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

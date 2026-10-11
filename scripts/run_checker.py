#!/usr/bin/env python3
"""Run a compiled deterministic checker over every batch of conversations.

    python scripts/run_checker.py --checker checker_democard.py --batches RUN_DIR/batches --out RUN_DIR/checker_out

The checker is a Python module written by the architect role from the deterministic and pattern points of the
pseudocode (start from assets/checker_template.py). It must expose

    check_conversation(conversation: dict) -> dict

returning {"conversation_id": ..., "findings": [...], "pipeline_findings": [...], "unverifiable": [...],
"points_evaluated": [...]} using the finding shape of references/output_schema.md (without verification).
Errors inside the checker are captured per conversation so one bad record does not stop the batch.
Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import sys
import traceback
from pathlib import Path
from typing import List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, write_json  # noqa: E402


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def load_checker(path: Path):
    spec = importlib.util.spec_from_file_location("compiled_checker", str(path))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load checker from %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["compiled_checker"] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "check_conversation"):
        raise ImportError("checker %s has no check_conversation(conversation) function" % path)
    return module


def run_batch(module, batch_file: Path, out_dir: Path) -> dict:
    batch = read_json(batch_file)
    results: List[dict] = []
    errors = 0
    for conversation in batch.get("conversations", []):
        try:
            result = module.check_conversation(conversation)
            if not isinstance(result, dict):
                raise TypeError("check_conversation returned %s" % type(result).__name__)
            result.setdefault("conversation_id", conversation.get("conversation_id"))
            result.setdefault("findings", [])
            result.setdefault("pipeline_findings", [])
            result.setdefault("unverifiable", [])
            result.setdefault("points_evaluated", [])
            results.append(result)
        except Exception:  # noqa: BLE001 - keep going, report the failure
            errors += 1
            results.append({"conversation_id": conversation.get("conversation_id"), "error": traceback.format_exc()[-2000:],
                            "findings": [], "pipeline_findings": [], "unverifiable": [], "points_evaluated": []})
    batch_id = (batch.get("batch") or {}).get("id") or batch_file.stem.replace("batch_", "")
    payload = {"batch": batch_id, "source": str(batch_file), "checked_at": now_iso(),
               "checker": getattr(module, "CHECKER_VERSION", "unversioned"), "conversations": len(results),
               "errors": errors, "results": results}
    out_file = out_dir / ("batch_%s.json" % batch_id)
    write_json(out_file, payload)
    return {"batch": batch_id, "file": str(out_file), "conversations": len(results), "errors": errors,
            "findings": sum(len(r["findings"]) for r in results)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checker", required=True)
    parser.add_argument("--batches", required=True, help="directory of batch_NNN.json files, or one batch file")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    checker_path = Path(args.checker)
    if not checker_path.exists():
        print("error: checker %s does not exist" % checker_path, file=sys.stderr)
        return 2
    try:
        module = load_checker(checker_path)
    except Exception as error:  # noqa: BLE001
        print("error: cannot load checker: %s" % error, file=sys.stderr)
        return 2
    batches_path = Path(args.batches)
    files = [batches_path] if batches_path.is_file() else sorted(batches_path.glob("batch_*.json"))
    if not files:
        print("error: no batch files under %s" % batches_path, file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = [run_batch(module, file, out_dir) for file in files]
    write_json(out_dir / "index.json", {"checked_at": now_iso(), "checker": str(checker_path), "batches": summary})
    total_findings = sum(s["findings"] for s in summary)
    total_errors = sum(s["errors"] for s in summary)
    print("checked %d batch(es): %d deterministic findings, %d conversation errors -> %s" % (len(summary), total_findings, total_errors, out_dir))
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())

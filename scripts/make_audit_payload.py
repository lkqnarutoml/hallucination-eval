#!/usr/bin/env python3
"""Build the blind payload an auditor reads, and apply the auditor's verdicts to a findings batch.

    python scripts/make_audit_payload.py payload --findings RUN_DIR/findings/batch_001.json
           --conversations RUN_DIR/conversations.json --out RUN_DIR/audit/payload_batch_001.json [--sample 5] [--seed 7]
    python scripts/make_audit_payload.py apply --findings RUN_DIR/findings/batch_001.json
           --verdicts RUN_DIR/audit/verdicts_batch_001.json --out RUN_DIR/findings/verified_batch_001.json [--allow-missing]

payload  copies each finding's point, turn, author, check kind, observed value and evidence, adds the slice of
         the conversation around it (the events of that turn and the utterances of the turn before), and
         WITHHOLDS the evaluator's type, rationale, severity, confidence and expected value, so the auditor must
         reach a verdict from the evidence and the pseudocode first. It also samples up to --sample model-authored
         tool calls per conversation that carry no finding, for the miss-rate estimate.
apply    merges verdicts_batch_NNN.json (written by the auditor) into the batch: confirmed / revised findings get
         their verification block, rejected ones move to conversations[].rejected, misses found on sampled points
         are added as auditor-decided findings (decided_by auditor, verification confirmed) under a provisional id
         that continues the batch's H-NNNN numbering (any id the auditor wrote is replaced), so the verified batch
         passes validate_findings.py --batch; merge_findings.py renumbers every id in the final file.
         conversations[].audit records the sample counts.

Verdicts file shape:
    {"batch": "001",
     "verdicts": [{"ref": "<conversation_id>#<index>", "status": "confirmed|revised|rejected",
                   "auditor_rationale": "...", "revised": {"type": "...", "severity": "...", "confidence": "..."}}],
     "samples": [{"ref": "<conversation_id>#sample<n>", "supported": true}, 
                 {"ref": "...", "supported": false, "finding": {<finding without id/verification>}}]}
Standard library only.
"""
from __future__ import annotations

import argparse
import copy
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, write_json  # noqa: E402

WITHHELD = ("type", "rationale", "severity", "confidence", "expected_or_allowed", "decided_by")
MAX_QUOTE = 400
H_ID_RE = re.compile(r"^H-(\d{4,})$")


def used_ids(batch: dict):
    """Every finding id already present in the batch (all groups, all conversations) and the highest H-NNNN number."""
    used = set()
    highest = 0
    for conversation in batch.get("conversations", []) or []:
        for group in ("hallucinations", "rejected", "pipeline_findings"):
            for item in conversation.get(group, []) or []:
                fid = item.get("id")
                if isinstance(fid, str):
                    used.add(fid)
                    match = H_ID_RE.match(fid)
                    if match:
                        highest = max(highest, int(match.group(1)))
    return used, highest


def _short(value: Any, limit: int = MAX_QUOTE) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, (dict, list)):
        text = str(value)
        return value if len(text) <= limit else text[:limit] + "..."
    return value


def compact_event(event: dict) -> dict:
    kind = event.get("kind")
    out = {"index": event.get("index"), "turn": event.get("turn"), "kind": kind, "locator": event.get("locator")}
    if kind in ("customer_utterance", "agent_utterance"):
        out["text"] = _short(event.get("text"))
        if kind == "agent_utterance":
            out["origin"] = event.get("origin")
            out["agent"] = event.get("agent")
    elif kind == "tool_call":
        out.update({"tool": event.get("tool"), "args": _short(event.get("args")), "response": _short(event.get("response")),
                    "origin": event.get("origin"), "agent": event.get("agent")})
    elif kind == "state_update":
        out["source"] = event.get("source")
        out["changes"] = {k: _short(v, 120) for k, v in list((event.get("changes") or {}).items())[:40]}
    elif kind == "transfer":
        out["target"] = event.get("target")
    elif kind == "session_end":
        out.update({"reason": event.get("reason"), "escalated": event.get("escalated")})
    return out


def slice_for(conversation: dict, turn: Optional[int]) -> dict:
    events = conversation.get("events", [])
    if turn is None:
        return {"turn_events": [compact_event(e) for e in events[-12:]], "previous_turn": []}
    current = [compact_event(e) for e in events if e.get("turn") == turn]
    previous = [compact_event(e) for e in events if e.get("turn") == turn - 1 and e.get("kind") in ("customer_utterance", "agent_utterance")]
    return {"turn_events": current, "previous_turn": previous}


def build_payload(batch: dict, conversations: Dict[str, dict], sample: int, seed: int) -> dict:
    rng = random.Random(seed)
    items: List[dict] = []
    samples: List[dict] = []
    for conversation in batch.get("conversations", []):
        cid = conversation.get("conversation_id")
        source = conversations.get(cid)
        if source is None:
            items.append({"ref": "%s#missing" % cid, "conversation_id": cid, "error": "conversation not found in conversations.json"})
            continue
        findings = conversation.get("hallucinations", []) or []
        for index, finding in enumerate(findings):
            visible = {k: v for k, v in finding.items() if k not in WITHHELD and k != "verification"}
            visible["evidence"] = [dict(e, quote=_short(e.get("quote"))) for e in (finding.get("evidence") or [])]
            visible.update({"ref": "%s#%d" % (cid, index), "conversation_id": cid, "workflow": conversation.get("workflow") or (source.get("metadata") or {}).get("flow"),
                            "context": slice_for(source, finding.get("turn"))})
            items.append(visible)
        flagged = {(f.get("turn"), (f.get("point") or "").split(".")[1] if "." in (f.get("point") or "") else None) for f in findings}
        candidates = [e for e in source.get("events", []) if e.get("kind") == "tool_call" and e.get("origin") in ("model", "unknown")
                      and (e.get("turn"), e.get("tool")) not in flagged and e.get("tool") not in ("get_token", "telephony_get_token", "_initialize_session_for_dev")]
        rng.shuffle(candidates)
        for number, event in enumerate(candidates[:sample], start=1):
            samples.append({"ref": "%s#sample%d" % (cid, number), "conversation_id": cid, "turn": event.get("turn"),
                            "event_index": event.get("index"), "tool": event.get("tool"), "args": _short(event.get("args")),
                            "response": _short(event.get("response")), "origin": event.get("origin"), "locator": event.get("locator"),
                            "context": slice_for(source, event.get("turn"))})
    return {"batch": (batch.get("batch") or {}).get("id") if isinstance(batch.get("batch"), dict) else batch.get("batch"),
            "withheld_from_auditor": list(WITHHELD), "items": items, "supported_samples": samples,
            "instructions": "Decide each item from its evidence and the pseudocode point BEFORE reading anything else. "
                            "For each sample, state whether the call is supported at that point; if not, describe the miss as a finding."}


def apply_verdicts(batch: dict, verdicts: dict, allow_missing: bool) -> Dict[str, Any]:
    by_ref = {v.get("ref"): v for v in verdicts.get("verdicts", []) or []}
    samples_by_conv: Dict[str, List[dict]] = {}
    for sample in verdicts.get("samples", []) or []:
        cid = str(sample.get("ref", "")).split("#")[0]
        samples_by_conv.setdefault(cid, []).append(sample)
    result = copy.deepcopy(batch)
    taken, highest = used_ids(result)
    missing: List[str] = []
    counts = {"confirmed": 0, "revised": 0, "rejected": 0, "unaudited": 0, "misses_added": 0}
    for conversation in result.get("conversations", []):
        cid = conversation.get("conversation_id")
        kept: List[dict] = []
        rejected: List[dict] = list(conversation.get("rejected", []) or [])
        for index, finding in enumerate(conversation.get("hallucinations", []) or []):
            ref = "%s#%d" % (cid, index)
            verdict = by_ref.get(ref)
            if verdict is None:
                missing.append(ref)
                finding["verification"] = {"status": "unaudited", "auditor_rationale": None, "revised_from": None}
                counts["unaudited"] += 1
                kept.append(finding)
                continue
            status = verdict.get("status")
            rationale = verdict.get("auditor_rationale")
            if status == "confirmed":
                finding["verification"] = {"status": "confirmed", "auditor_rationale": rationale, "revised_from": None}
                counts["confirmed"] += 1
                kept.append(finding)
            elif status == "revised":
                original = {k: finding.get(k) for k in ("type", "severity", "confidence", "point", "expected_or_allowed")}
                for key, value in (verdict.get("revised") or {}).items():
                    if key in ("type", "severity", "confidence", "point", "expected_or_allowed", "observed", "rationale"):
                        finding[key] = value
                finding["verification"] = {"status": "revised", "auditor_rationale": rationale, "revised_from": original}
                counts["revised"] += 1
                kept.append(finding)
            elif status == "rejected":
                finding["verification"] = {"status": "rejected", "auditor_rationale": rationale, "revised_from": None}
                counts["rejected"] += 1
                rejected.append(finding)
            else:
                missing.append(ref + " (bad status %r)" % status)
                finding["verification"] = {"status": "unaudited", "auditor_rationale": None, "revised_from": None}
                counts["unaudited"] += 1
                kept.append(finding)
        sampled = samples_by_conv.get(cid, [])
        misses = 0
        for sample in sampled:
            if sample.get("supported") is False and isinstance(sample.get("finding"), dict):
                miss = dict(sample["finding"])
                # Provisional id: the schema requires one and validate_findings.py needs it unique within the batch.
                # It continues the batch's H-NNNN numbering; merge_findings.py renumbers every id in the final file.
                highest += 1
                while "H-%04d" % highest in taken:
                    highest += 1
                miss["id"] = "H-%04d" % highest
                taken.add(miss["id"])
                miss["decided_by"] = "auditor"
                miss.setdefault("author", "model")
                miss["verification"] = {"status": "confirmed", "auditor_rationale": sample.get("auditor_rationale") or "found while sampling supported points", "revised_from": None}
                kept.append(miss)
                misses += 1
                counts["misses_added"] += 1
        conversation["hallucinations"] = kept
        conversation["rejected"] = rejected
        conversation["audit"] = {"sampled_supported": len(sampled), "misses_found": misses,
                                 "auditor_notes": verdicts.get("notes") if isinstance(verdicts.get("notes"), str) else None}
    if missing and not allow_missing:
        return {"error": "verdicts missing or malformed for: %s" % ", ".join(missing[:20]), "result": None, "counts": counts}
    result["audit_applied"] = {"batch": verdicts.get("batch"), "counts": counts, "missing": missing}
    return {"error": None, "result": result, "counts": counts}


def cmd_payload(args: argparse.Namespace) -> int:
    batch = read_json(args.findings)
    source = read_json(args.conversations)
    conversations = {c.get("conversation_id"): c for c in source.get("conversations", [])}
    payload = build_payload(batch, conversations, args.sample, args.seed)
    write_json(args.out, payload)
    print("audit payload: %d finding(s), %d sampled point(s) -> %s" % (len(payload["items"]), len(payload["supported_samples"]), args.out))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    batch = read_json(args.findings)
    verdicts = read_json(args.verdicts)
    outcome = apply_verdicts(batch, verdicts, args.allow_missing)
    if outcome["error"]:
        print("error: " + outcome["error"], file=sys.stderr)
        return 1
    write_json(args.out, outcome["result"])
    counts = outcome["counts"]
    print("applied verdicts: confirmed %d, revised %d, rejected %d, unaudited %d, misses added %d -> %s" % (
        counts["confirmed"], counts["revised"], counts["rejected"], counts["unaudited"], counts["misses_added"], args.out))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_payload = sub.add_parser("payload")
    p_payload.add_argument("--findings", required=True)
    p_payload.add_argument("--conversations", required=True)
    p_payload.add_argument("--out", required=True)
    p_payload.add_argument("--sample", type=int, default=5)
    p_payload.add_argument("--seed", type=int, default=7)
    p_payload.set_defaults(func=cmd_payload)
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--findings", required=True)
    p_apply.add_argument("--verdicts", required=True)
    p_apply.add_argument("--out", required=True)
    p_apply.add_argument("--allow-missing", action="store_true")
    p_apply.set_defaults(func=cmd_apply)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

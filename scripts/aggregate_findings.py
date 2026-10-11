#!/usr/bin/env python3
"""Aggregate hallucination_findings.json into counts, rates and an optional MDD-style view.

    python scripts/aggregate_findings.py FINDINGS_JSON --out aggregate.json [--md summary_tables.md] [--mdd-view]

Counts by type, point, workflow, author, severity, check kind and verification status; evaluator precision =
kept / (kept + rejected) over evaluator-decided findings only (confirmed and revised count as kept; findings with
decided_by == "auditor", the misses the auditor added while sampling, are excluded from both terms because the
evaluator never produced them and they already feed the miss rate); miss rate from audit samples
(conversations[].audit.sampled_supported / misses_found); per-conversation counts. --mdd-view groups points by the
naming convention in references/output_schema.md (<step>.<tool>.args.<param> -> argument grounding,
<step>.selection / <step>.omission -> tool selection, <step>.<tool>.output / .effects / .branch -> outputs,
*.device* -> device grounding, *.speech -> spoken facts, *.end_reason -> end reasons, *.silence -> silence).
Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, write_json  # noqa: E402

# The taxonomy views of the MDD hallucination section: A = hallucinated output (a spoken fact, a branch or a tool
# result that the deterministic rule does not support), B = hallucinated argument (a value passed to a tool, including
# an end reason, that no allowed source contains), C = hallucinated tool (a tool the workflow does not call for here,
# a missing required call, a tool outside the catalogue), D = device grounding (spoken device facts vs the token list).
MDD_VIEW_RULES = [
    (re.compile(r"device"), "device grounding (MDD D)"),
    (re.compile(r"\.args\.|\.end_reason$"), "argument grounding (MDD B)"),
    (re.compile(r"\.(selection|omission)$|hallucinated_tool"), "tool selection (MDD C)"),
    (re.compile(r"\.(output|effects|branch|speech|silence)$"), "outputs and branches (MDD A)"),
]


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def wilson(successes: int, total: int, z: float = 1.96):
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return [round((centre - margin) / denominator, 4), round((centre + margin) / denominator, 4)]


def mdd_view_of(point: str) -> str:
    for pattern, label in MDD_VIEW_RULES:
        if pattern.search(point or ""):
            return label
    return "other"


def aggregate(data: dict, mdd_view: bool) -> dict:
    conversations = data.get("conversations", [])
    by_type: Counter = Counter()
    by_point: Counter = Counter()
    by_workflow: Counter = Counter()
    by_author: Counter = Counter()
    by_severity: Counter = Counter()
    by_check_kind: Counter = Counter()
    by_verification: Counter = Counter()
    by_view: Counter = Counter()
    pipeline_by_type: Counter = Counter()
    unverifiable_by_reason: Counter = Counter()
    per_conversation: List[dict] = []
    points_evaluated = 0
    sampled = 0
    misses = 0
    kept = 0  # evaluator-decided findings the auditor confirmed or revised
    rejected_total = 0  # evaluator-decided findings the auditor rejected
    conversations_with_hallucination = 0
    for conv in conversations:
        hallucinations = conv.get("hallucinations", []) or []
        rejected = conv.get("rejected", []) or []
        rejected_total += sum(1 for item in rejected if item.get("decided_by") != "auditor")
        pipeline = conv.get("pipeline_findings", []) or []
        unverifiable = conv.get("unverifiable", []) or []
        points_evaluated += int(conv.get("points_evaluated") or 0)
        audit = conv.get("audit") or {}
        sampled += int(audit.get("sampled_supported") or 0)
        misses += int(audit.get("misses_found") or 0)
        workflow = conv.get("workflow") or "unknown"
        if hallucinations:
            conversations_with_hallucination += 1
        for item in hallucinations:
            by_type[item.get("type") or "unknown"] += 1
            by_point[item.get("point") or "unknown"] += 1
            by_workflow[workflow] += 1
            by_author[item.get("author") or "unknown"] += 1
            by_severity[item.get("severity") or "unknown"] += 1
            by_check_kind[item.get("check_kind") or "unknown"] += 1
            status = (item.get("verification") or {}).get("status") or "missing"
            by_verification[status] += 1
            if status in ("confirmed", "revised") and item.get("decided_by") != "auditor":
                kept += 1
            if mdd_view:
                by_view[mdd_view_of(item.get("point") or "")] += 1
        for item in pipeline:
            pipeline_by_type[item.get("type") or "unknown"] += 1
        for item in unverifiable:
            unverifiable_by_reason[item.get("reason") or "unknown"] += 1
        per_conversation.append({"conversation_id": conv.get("conversation_id"), "workflow": workflow,
                                 "turns": conv.get("turns"), "hallucinations": len(hallucinations),
                                 "rejected": len(rejected), "pipeline_findings": len(pipeline),
                                 "unverifiable": len(unverifiable), "outcome": conv.get("outcome")})
    precision = None
    if kept + rejected_total:
        precision = round(kept / float(kept + rejected_total), 4)
    total_hallucinations = sum(by_type.values())
    result = {
        "generated_at": now_iso(),
        "conversations": len(conversations),
        "conversations_with_hallucination": conversations_with_hallucination,
        "conversation_hallucination_rate": (round(conversations_with_hallucination / float(len(conversations)), 4) if conversations else None),
        "conversation_rate_wilson95": wilson(conversations_with_hallucination, len(conversations)),
        "points_evaluated": points_evaluated,
        "hallucinations": total_hallucinations,
        "hallucinations_per_100_points": (round(100.0 * total_hallucinations / points_evaluated, 3) if points_evaluated else None),
        "by_type": dict(by_type.most_common()),
        "by_point": dict(by_point.most_common()),
        "by_workflow": dict(by_workflow.most_common()),
        "by_author": dict(by_author.most_common()),
        "by_severity": dict(by_severity.most_common()),
        "by_check_kind": dict(by_check_kind.most_common()),
        "by_verification": dict(by_verification.most_common()),
        "pipeline_findings_by_type": dict(pipeline_by_type.most_common()),
        "unverifiable_by_reason": dict(unverifiable_by_reason.most_common()),
        "audit": {"rejected": rejected_total, "kept": kept, "evaluator_precision": precision,
                  "sampled_supported_points": sampled, "misses_found": misses,
                  "miss_rate": (round(misses / float(sampled), 4) if sampled else None)},
        "per_conversation": per_conversation,
    }
    if mdd_view:
        result["mdd_view"] = dict(by_view.most_common())
    return result


def render_markdown(result: dict) -> str:
    def table(title: str, mapping: Dict[str, int]) -> List[str]:
        lines = ["", "### %s" % title, "", "| Key | Count |", "|---|---|"]
        lines += ["| %s | %d |" % (k, v) for k, v in mapping.items()] or ["| (none) | 0 |"]
        return lines

    lines = ["# Aggregate", "", "Generated: %s" % result["generated_at"], "",
             "- Conversations: %d, with at least one hallucination: %d (rate %s, Wilson 95%% %s)" % (
                 result["conversations"], result["conversations_with_hallucination"],
                 result["conversation_hallucination_rate"], result["conversation_rate_wilson95"]),
             "- Points evaluated: %d, hallucinations: %d (%s per 100 points)" % (
                 result["points_evaluated"], result["hallucinations"], result["hallucinations_per_100_points"]),
             "- Audit: kept %d, rejected %d, evaluator precision %s; sampled supported points %d, misses %d (miss rate %s)" % (
                 result["audit"]["kept"], result["audit"]["rejected"], result["audit"]["evaluator_precision"],
                 result["audit"]["sampled_supported_points"], result["audit"]["misses_found"], result["audit"]["miss_rate"])]
    for title, key in (("By type", "by_type"), ("By point", "by_point"), ("By workflow", "by_workflow"), ("By author", "by_author"),
                       ("By severity", "by_severity"), ("By verification", "by_verification"),
                       ("Pipeline findings by type", "pipeline_findings_by_type"), ("Unverifiable by reason", "unverifiable_by_reason")):
        lines += table(title, result.get(key, {}))
    if "mdd_view" in result:
        lines += table("MDD view", result["mdd_view"])
    lines += ["", "### Per conversation", "", "| Conversation | Workflow | Turns | Hallucinations | Rejected | Pipeline | Unverifiable | Outcome |", "|---|---|---|---|---|---|---|---|"]
    for row in result["per_conversation"]:
        lines.append("| %s | %s | %s | %d | %d | %d | %d | %s |" % (row["conversation_id"], row["workflow"], row["turns"], row["hallucinations"],
                                                                   row["rejected"], row["pipeline_findings"], row["unverifiable"], row["outcome"]))
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("findings")
    parser.add_argument("--out", required=True)
    parser.add_argument("--md")
    parser.add_argument("--mdd-view", action="store_true")
    args = parser.parse_args(argv)
    result = aggregate(read_json(args.findings), args.mdd_view)
    write_json(args.out, result)
    if args.md:
        Path(args.md).write_text(render_markdown(result), encoding="utf-8")
    print("aggregate: %d conversations, %d hallucinations, precision %s -> %s" % (
        result["conversations"], result["hallucinations"], result["audit"]["evaluator_precision"], args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

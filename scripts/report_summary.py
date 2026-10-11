#!/usr/bin/env python3
"""Render summary.md, the human report of one run, from the machine outputs.

    python scripts/report_summary.py --findings RUN_DIR/hallucination_findings.json --aggregate RUN_DIR/aggregate.json
           --out RUN_DIR/summary.md [--spec RUN_DIR/workflow_spec.json] [--manifest RUN_DIR/run_manifest.json]
           [--max-findings 60] [--unmask]

Digit runs of four or more are masked in every quote unless --unmask is given, so the report can be pasted
into chat. The numbers come from aggregate.json; the report never recounts. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json  # noqa: E402
from halu_common.textnum import mask_digits  # noqa: E402


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _mask(value: Any, unmask: bool) -> str:
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    return text if unmask else mask_digits(text)


def _table(title: str, mapping: Dict[str, Any], key: str = "Key") -> List[str]:
    lines = ["", "### %s" % title, "", "| %s | Count |" % key, "|---|---|"]
    lines += ["| %s | %s |" % (k, v) for k, v in (mapping or {}).items()] or ["| (none) | 0 |"]
    return lines


def render(findings: dict, aggregate: dict, spec: Optional[dict], manifest: Optional[dict], max_findings: int, unmask: bool) -> str:
    meta = findings.get("meta", {})
    evaluator = meta.get("evaluator", {})
    audit = aggregate.get("audit", {})
    lines = ["# Hallucination evaluation summary: %s" % (meta.get("target_agent") or "?"), "",
             "Generated %s by hallucination-eval %s. Mode: %s. Evaluating model: %s. Auditing model: %s. Audited: %s. Checker: %s." % (
                 now_iso(), meta.get("skill_version", "?"), evaluator.get("mode", "?"), evaluator.get("model") or "not recorded",
                 "none (P7 skipped)" if evaluator.get("audited") is False else (evaluator.get("audit_model") or evaluator.get("model") or "not recorded"),
                 evaluator.get("audited"), evaluator.get("checker_script") or "none"),
             "Pseudocode: %s (sha256 %s)." % (meta.get("pseudocode_file") or "?", (meta.get("pseudocode_sha256") or "")[:12]),
             "Trajectory sources: %s." % ("; ".join("%s (%s, %s conversations)" % (s.get("path"), s.get("format"), s.get("conversations")) for s in meta.get("trajectory_sources") or []) or "not recorded"),
             ""]
    normalization = meta.get("normalization") or {}
    if normalization:
        counts = normalization.get("counts") or {}
        settings = normalization.get("settings") or {}
        redacted = sum(v for k, v in counts.items() if k not in ("chars_before", "chars_after", "truncated", "capped", "snapshots_dropped", "opaque_seen", "old_summarized"))
        lines.insert(len(lines) - 1, "Normalization: state snapshots %s, %d value(s) redacted, %d payload(s) capped, %s -> %s characters." % (
            settings.get("state_snapshots"), redacted, counts.get("capped", 0), counts.get("chars_before"), counts.get("chars_after")))
    if evaluator.get("models_used"):
        lines.insert(len(lines) - 1, "Models used by evaluators and auditors: %s." % ", ".join(evaluator["models_used"]))
    if evaluator.get("audited") is False:
        lines.append("> Caveat: findings are UNAUDITED (the P7 audit was not included). Evaluator precision and the miss rate are unknown; treat every count as an upper bound.")
    if evaluator.get("mode") == "single-agent":
        lines.append("> Caveat: single-agent mode. The same context derived the pseudocode and judged the trajectories, so consistent hallucinations may have been absorbed into the spec.")
    if meta.get("sampling"):
        lines.append("> Caveat: judgment points were sampled: %s" % meta["sampling"])
    lines += ["", "## Headline", "",
              "| Measure | Value |", "|---|---|",
              "| Conversations evaluated | %s |" % aggregate.get("conversations"),
              "| Conversations with at least one hallucination | %s (rate %s, Wilson 95%% %s) |" % (aggregate.get("conversations_with_hallucination"), aggregate.get("conversation_hallucination_rate"), aggregate.get("conversation_rate_wilson95")),
              "| Points evaluated | %s |" % aggregate.get("points_evaluated"),
              "| Hallucinations (model-authored, after audit) | %s (%s per 100 points) |" % (aggregate.get("hallucinations"), aggregate.get("hallucinations_per_100_points")),
              "| Evaluator precision (kept / kept+rejected) | %s (%s rejected) |" % (audit.get("evaluator_precision"), audit.get("rejected")),
              "| Miss rate on sampled supported points | %s (%s sampled, %s misses) |" % (audit.get("miss_rate"), audit.get("sampled_supported_points"), audit.get("misses_found")),
              "| Pipeline findings (code-authored, not hallucinations) | %s |" % sum((aggregate.get("pipeline_findings_by_type") or {}).values()),
              "| Unverifiable points | %s |" % sum((aggregate.get("unverifiable_by_reason") or {}).values())]
    lines += _table("Hallucinations by type", aggregate.get("by_type") or {}, "Type")
    if aggregate.get("mdd_view"):
        lines += _table("Taxonomy view (A outputs and branches, B arguments, C tool selection, D device grounding)", aggregate["mdd_view"], "View")
    lines += _table("By workflow point", aggregate.get("by_point") or {}, "Point")
    lines += _table("By workflow", aggregate.get("by_workflow") or {}, "Workflow")
    lines += _table("By severity", aggregate.get("by_severity") or {}, "Severity")
    lines += _table("Verification status", aggregate.get("by_verification") or {}, "Status")
    lines += _table("Pipeline findings by type", aggregate.get("pipeline_findings_by_type") or {}, "Type")
    lines += _table("Unverifiable points by reason", aggregate.get("unverifiable_by_reason") or {}, "Reason")

    lines += ["", "## Findings", "", "| Id | Conversation | Turn | Point | Type | Severity | Verification | Observed | Rationale |", "|---|---|---|---|---|---|---|---|---|"]
    shown = 0
    for conversation in findings.get("conversations", []):
        for item in conversation.get("hallucinations", []) or []:
            if shown >= max_findings:
                break
            shown += 1
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                item.get("id"), conversation.get("conversation_id"), item.get("turn"), item.get("point"), item.get("type"),
                item.get("severity"), (item.get("verification") or {}).get("status"), _mask(item.get("observed"), unmask)[:60].replace("|", "/"),
                _mask(item.get("rationale"), unmask)[:220].replace("|", "/")))
    total = aggregate.get("hallucinations") or 0
    if total > shown:
        lines.append("")
        lines.append("(%d of %d findings shown; the rest are in hallucination_findings.json)" % (shown, total))
    if shown == 0:
        lines.append("| (none) | | | | | | | | |")

    rejected = [(c.get("conversation_id"), r) for c in findings.get("conversations", []) for r in (c.get("rejected") or [])]
    if rejected:
        lines += ["", "## Rejected by the auditor (evaluator false positives)", "", "| Id | Conversation | Point | Evaluator type | Auditor rationale |", "|---|---|---|---|---|"]
        for cid, item in rejected[:max_findings]:
            lines.append("| %s | %s | %s | %s | %s |" % (item.get("id"), cid, item.get("point"), item.get("type"),
                                                         _mask((item.get("verification") or {}).get("auditor_rationale"), unmask)[:200].replace("|", "/")))
    pipeline = [(c.get("conversation_id"), p) for c in findings.get("conversations", []) for p in (c.get("pipeline_findings") or [])]
    if pipeline:
        lines += ["", "## Pipeline findings (code-authored; spec drift or deterministic mismatches)", "", "| Id | Conversation | Point | Type | Rationale |", "|---|---|---|---|---|"]
        for cid, item in pipeline[:max_findings]:
            lines.append("| %s | %s | %s | %s | %s |" % (item.get("id"), cid, item.get("point"), item.get("type"), _mask(item.get("rationale"), unmask)[:200].replace("|", "/")))
    notes = [(c.get("conversation_id"), n) for c in findings.get("conversations", []) for n in (c.get("notes") or [])]
    if notes:
        lines += ["", "## Evaluator notes", ""] + ["- %s: %s" % (cid, _mask(note, unmask)[:300]) for cid, note in notes[:max_findings]]
    if spec:
        questions = spec.get("open_questions") or []
        counts = (spec.get("meta") or {}).get("counts") or {}
        lines += ["", "## Pseudocode provenance", "",
                  "- Elements: %s steps, %s tools, %s callback rules, %s rules, %s points; %s inferred or unknown." % (
                      counts.get("steps"), counts.get("tools"), counts.get("callback_rules"), counts.get("rules"), counts.get("points"), counts.get("inferred_or_unknown"))]
        if questions:
            lines += ["- Open questions the materials did not settle:"] + ["  - " + q for q in questions[:30]]
    if manifest:
        phases = manifest.get("phases") or {}
        lines += ["", "## Run record", "", "- Run: %s in %s" % (manifest.get("run_id"), manifest.get("run_dir")),
                  "- Phases: " + ", ".join("%s=%s" % (name, (info or {}).get("status")) for name, info in phases.items())]
        skipped = [name for name, info in phases.items() if (info or {}).get("status") == "skipped"]
        if skipped:
            lines.append("- Skipped phases: %s" % ", ".join(skipped))
    lines += ["", "## How to read this", "",
              "- A hallucination is a model-authored artifact (tool choice, argument, spoken fact, branch, end reason) that none of the six reference points supports: the customer's words, the tool catalogue, earlier arguments, tool results, the session state, the workflow rules.",
              "- Code-authored mismatches are reported as pipeline findings, never as hallucinations; unverifiable points are counted separately and never enter a rate.",
              "- Every finding cites a locator into the source log; open hallucination_findings.json to see the evidence and the pseudocode element."]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--findings", required=True)
    parser.add_argument("--aggregate", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--manifest")
    parser.add_argument("--max-findings", type=int, default=60)
    parser.add_argument("--unmask", action="store_true")
    args = parser.parse_args(argv)
    findings = read_json(args.findings)
    aggregate = read_json(args.aggregate)
    spec = read_json(args.spec) if args.spec and Path(args.spec).exists() else None
    manifest = read_json(args.manifest) if args.manifest and Path(args.manifest).exists() else None
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(findings, aggregate, spec, manifest, args.max_findings, args.unmask), encoding="utf-8")
    print("summary written to %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

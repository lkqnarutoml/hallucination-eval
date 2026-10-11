#!/usr/bin/env python3
"""Template for a compiled deterministic checker. COPY this file to RUN_DIR/checker_<agent>.py and fill the
RULES section from the deterministic and pattern points of workflow_pseudocode.md. Do not edit the engine
below the RULES section unless a rule cannot be expressed with it.

The checker is run by scripts/run_checker.py over every batch:

    check_conversation(conversation) -> {"conversation_id", "findings", "pipeline_findings", "unverifiable", "points_evaluated"}

Findings use the shape of references/output_schema.md (no id, no verification; run_checker/merge add them).
Only deterministic and pattern points belong here. Judgment points (was the customer's reply affirmative?)
stay with the evaluator role. Keep everything standard-library so it runs on the Windows machine as is.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- locate the skill's shared helpers (edit SKILL_DIR if the checker lives outside the run folder tree) ---------
SKILL_DIR = Path(__file__).resolve().parent  # replaced by the architect with the absolute skill path if needed
for candidate in (SKILL_DIR / "scripts", SKILL_DIR.parent / "scripts", Path(__file__).resolve().parents[1] / "scripts"):
    if (candidate / "halu_common").exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
from halu_common.payload import find_key, normalize_digits, status_of  # noqa: E402
from halu_common.textnum import extract_digit_groups, relation  # noqa: E402

CHECKER_VERSION = "checker/<agent>/0.1"   # bump when RULES change; recorded in checker_out
PSEUDOCODE_REF = "workflow_pseudocode.md"  # file the pseudocode evidence refs point at

# =================================================================================================================
# RULES  (fill from the pseudocode; every entry cites the pseudocode element it came from)
# =================================================================================================================

# Tools the model may call, with the agents/flows they belong to.  name -> {"agents": [...], "flows": [...], "author": "model|code|both"}
TOOL_CATALOG: Dict[str, dict] = {
    # "save_zip_code": {"agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"], "author": "model"},
}

# Deterministic rules on tool OUTPUTS: given the arguments, prior state and external ground truth, what must the
# tool have returned?  Each rule returns (expected_status or None, branch_label, unverifiable_reason or None).
def rule_example_zip(args: dict, state: dict, truth: dict):
    """Example from DemoCard (delete if not applicable): validate_zip_code compares the first five characters."""
    arg = str(args.get("zip_code", ""))
    on_file = truth.get("zip_on_file")
    if not on_file:
        return None, "unknown", "no ZIP on file in ground truth"
    if arg in ("99991", "99992"):
        return "SYSTEM_ERROR", "error_trigger", None
    if str(on_file)[:5] == arg[:5]:
        return "SUCCESS", "match", None
    retries = int(state.get("zip_validation_retry_count") or 0) + 1
    return ("TRANSFER_REQUIRED" if retries >= 2 else "FAILURE"), "mismatch", None


OUTPUT_RULES: Dict[str, Any] = {
    # "validate_zip_code": rule_example_zip,
}

# Argument grounding rules: tool -> param -> {"source": "customer_current|state:<key>|agent_previous", "exact_len": 5}
ARGUMENT_RULES: Dict[str, Dict[str, dict]] = {
    # "save_zip_code": {"zip_code": {"source": "customer_current", "exact_len": 5}},
    # "validate_zip_code": {"zip_code": {"source": "state:user_zip"}},
}

# Canned utterance templates authored by CODE: name -> template with {placeholders} bound to state keys.
# A mismatch here is spec drift (pipeline finding), never a hallucination.
CANNED_TEMPLATES: Dict[str, dict] = {
    # "readback_zip": {"template": "Just to be sure, I heard {user_zip}. Is that the correct zip code?", "after_tool": "save_zip_code"},
}

# Silence rules: after these tool results the model must not speak (a model-authored utterance is a violation).
SILENCE_AFTER: Dict[str, List[str]] = {
    # "validate_zip_code": ["FAILURE", "TRANSFER_REQUIRED", "SYSTEM_ERROR"],
}

# Expected next action authored by CODE after a tool result: tool -> status -> next tool name (chained call).
CHAINED_CALLS: Dict[str, Dict[str, str]] = {
    # "validate_zip_code": {"SUCCESS": "indicate_ready_for_next_step"},
}

# =================================================================================================================
# ENGINE (generic; reads RULES)
# =================================================================================================================


def _template_regex(template: str) -> re.Pattern:
    parts = re.split(r"(\{[a-zA-Z_][a-zA-Z0-9_]*\})", template)
    pattern = ""
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            pattern += "(?P<%s>.+?)" % part[1:-1]
        else:
            pattern += re.escape(part).replace(r"\ ", r"\s+")
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


def _finding(point: str, turn: Optional[int], ftype: str, check_kind: str, observed: Any, expected: Any, rationale: str,
             evidence: List[dict], author: str = "model", severity: str = "medium") -> dict:
    return {"turn": turn, "point": point, "author": author, "type": ftype, "check_kind": check_kind, "severity": severity,
            "confidence": "high", "observed": observed, "expected_or_allowed": expected, "rationale": rationale,
            "evidence": evidence, "decided_by": "checker"}


def _ev(kind: str, event: dict, quote: Optional[str] = None) -> dict:
    return {"kind": kind, "turn": event.get("turn"), "quote": (quote if quote is not None else str(event.get("text") or event.get("args") or ""))[:300],
            "locator": event.get("locator")}


def _pseudo(ref: str) -> dict:
    return {"kind": "pseudocode", "ref": "%s: %s" % (PSEUDOCODE_REF, ref), "provenance": "seen_in_code"}


class Walk:
    """Tracks state and the last customer / agent utterances while iterating the events of one conversation."""

    def __init__(self, conversation: dict):
        self.conversation = conversation
        self.state: Dict[str, Any] = {}
        self.last_customer: Optional[dict] = None
        self.last_agent: Optional[dict] = None
        self.last_tool: Optional[dict] = None
        self.truth = dict((conversation.get("metadata") or {}).get("ground_truth") or {})

    def apply_state(self, event: dict) -> None:
        # `changes` is the contract (the normalizer's diet drops the `state` copy by default; a `source: defaults`
        # event carries the initial values). Redacted values arrive as "[redacted:...]" placeholders and masked
        # card numbers as "****1234": normalize_digits() turns them into empty or last-four digit strings.
        for path, change in (event.get("changes") or {}).items():
            self.state[path.split(".")[-1]] = change.get("new")
        for key, value in (event.get("state") or {}).items():
            if not isinstance(value, dict) or "_summary" not in value:
                self.state[key] = value


def check_conversation(conversation: dict) -> dict:
    walk = Walk(conversation)
    findings: List[dict] = []
    pipeline: List[dict] = []
    unverifiable: List[dict] = []
    points: List[str] = []
    events = conversation.get("events", [])
    flow = (conversation.get("metadata") or {}).get("flow")
    for index, event in enumerate(events):
        kind = event.get("kind")
        turn = event.get("turn")
        if kind == "state_update":
            walk.apply_state(event)
            continue
        if kind == "customer_utterance":
            walk.last_customer = event
            continue
        if kind == "agent_utterance":
            # silence rule: model text right after a tool result that requires silence
            last = walk.last_tool
            if last and event.get("origin") == "model" and last.get("tool") in SILENCE_AFTER \
                    and status_of(last.get("response")) in SILENCE_AFTER[last["tool"]]:
                point = "%s.silence" % last["tool"]
                points.append(point)
                findings.append(_finding(point, turn, "silence_violation", "pattern", event.get("text"), "no model text",
                                         "The pseudocode requires silence after %s returned %s; the model spoke." % (last["tool"], status_of(last.get("response"))),
                                         [_ev("agent_utterance", event), _ev("tool_response", last, str(last.get("response"))), _pseudo("silence after %s" % last["tool"])]))
            # canned templates authored by code: drift detection
            for name, spec in CANNED_TEMPLATES.items():
                if spec.get("after_tool") and (not last or last.get("tool") != spec["after_tool"]):
                    continue
                match = _template_regex(spec["template"]).search(event.get("text") or "")
                if match:
                    point = "callback.%s" % name
                    points.append(point)
                    for placeholder, captured in match.groupdict().items():
                        expected = walk.state.get(placeholder)
                        if expected is not None and normalize_digits(captured) != normalize_digits(expected) and str(captured).strip() != str(expected).strip():
                            pipeline.append({"turn": turn, "point": point, "type": "code_output_mismatch",
                                             "rationale": "Placeholder {%s} rendered as %r but state holds %r." % (placeholder, captured, expected),
                                             "evidence": [_ev("agent_utterance", event), _pseudo("template %s" % name)]})
                elif spec.get("after_tool") and last and last.get("tool") == spec["after_tool"] and event.get("origin") != "model":
                    pipeline.append({"turn": turn, "point": "callback.%s" % name, "type": "spec_drift",
                                     "rationale": "Utterance after %s does not match the canned template; update the pseudocode if production wording changed." % spec["after_tool"],
                                     "evidence": [_ev("agent_utterance", event), _pseudo("template %s" % name)]})
            walk.last_agent = event
            continue
        if kind != "tool_call":
            continue
        tool = event.get("tool") or ""
        args = event.get("args") or {}
        origin = event.get("origin") or "unknown"
        author = "code" if origin == "callback" else "model"
        # hallucinated tool: not in catalogue, or not allowed in this flow
        if TOOL_CATALOG:
            point = "%s.selection" % tool
            points.append(point)
            entry = TOOL_CATALOG.get(tool)
            if entry is None and origin != "callback":
                findings.append(_finding(point, turn, "hallucinated_tool", "deterministic", tool, sorted(TOOL_CATALOG),
                                         "Tool %s is not in the catalogue derived from the materials." % tool,
                                         [_ev("tool_call", event, "%s(%s)" % (tool, args)), _pseudo("tool catalogue")], author, "high"))
            elif entry and flow and entry.get("flows") and flow not in entry["flows"] and origin != "callback":
                findings.append(_finding(point, turn, "hallucinated_tool", "deterministic", tool, entry["flows"],
                                         "Tool %s belongs to flows %s but this conversation is the %s flow." % (tool, entry["flows"], flow),
                                         [_ev("tool_call", event, "%s(%s)" % (tool, args)), _pseudo("tool %s flows" % tool)], author, "high"))
        # argument grounding
        for param, rule in (ARGUMENT_RULES.get(tool) or {}).items():
            point = "%s.args.%s" % (tool, param)
            points.append(point)
            value = normalize_digits(args.get(param))
            if not value:
                continue
            source = rule.get("source", "")
            if source == "customer_current":
                if walk.last_customer is None:
                    unverifiable.append({"point": point, "turn": turn, "reason": "no customer utterance before the call"})
                    continue
                groups = extract_digit_groups(walk.last_customer.get("text") or "")
                candidates = [g.digits for g in groups]
                exact = rule.get("exact_len")
                if value in candidates:
                    continue
                relations = {c: relation(value, c) for c in candidates}
                detail = ", ".join("%s (%s)" % (c, r) for c, r in relations.items()) or "no digits in the utterance"
                findings.append(_finding(point, turn, "unsupported_argument", "grounding", value, candidates,
                                         "The argument %s does not equal any digit group the customer said: %s.%s" % (
                                             value, detail, (" The rule requires exactly %d digits as spoken." % exact) if exact else ""),
                                         [_ev("customer_utterance", walk.last_customer), _ev("tool_call", event, "%s(%s)" % (tool, args)),
                                          _pseudo("tool %s inputs.%s" % (tool, param))], author))
            elif source.startswith("state:"):
                key = source.split(":", 1)[1]
                expected = normalize_digits(walk.state.get(key))
                if expected and value != expected:
                    findings.append(_finding(point, turn, "wrong_source_argument", "grounding", value, expected,
                                             "The argument should carry state.%s (%s) but was %s." % (key, expected, value),
                                             [_ev("tool_call", event, "%s(%s)" % (tool, args)), _pseudo("tool %s inputs.%s" % (tool, param))], author))
                elif not expected:
                    unverifiable.append({"point": point, "turn": turn, "reason": "state.%s not available in the log" % key})
        # output rules (deterministic tool results)
        rule = OUTPUT_RULES.get(tool)
        if rule is not None:
            point = "%s.output" % tool
            points.append(point)
            expected, branch, why = rule(args, walk.state, walk.truth)
            actual = status_of(event.get("response"))
            if why:
                unverifiable.append({"point": point, "turn": turn, "reason": why})
            elif expected and actual and expected != actual:
                pipeline.append({"turn": turn, "point": point, "type": "code_output_mismatch",
                                 "rationale": "Rule expected %s on the %s branch but the tool returned %s." % (expected, branch, actual),
                                 "evidence": [_ev("tool_response", event, str(event.get("response"))), _pseudo("rule for %s" % tool)]})
        # chained calls authored by code
        chained = (CHAINED_CALLS.get(tool) or {}).get(status_of(event.get("response")) or "")
        if chained:
            point = "%s.effects" % tool
            points.append(point)
            following = [e for e in events[index + 1:index + 6] if e.get("kind") == "tool_call"]
            if not any(e.get("tool") == chained for e in following):
                pipeline.append({"turn": turn, "point": point, "type": "code_effect_mismatch",
                                 "rationale": "After %s returned %s the pseudocode chains %s, which was not observed." % (tool, status_of(event.get("response")), chained),
                                 "evidence": [_ev("tool_response", event, str(event.get("response"))), _pseudo("dispatch after %s" % tool)]})
        walk.last_tool = event
    return {"conversation_id": conversation.get("conversation_id"), "findings": findings, "pipeline_findings": pipeline,
            "unverifiable": unverifiable, "points_evaluated": points}


if __name__ == "__main__":
    import json

    for path in sys.argv[1:]:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        for conv in data.get("conversations", [data] if "events" in data else []):
            result = check_conversation(conv)
            print(json.dumps({"conversation_id": result["conversation_id"], "findings": len(result["findings"]),
                              "pipeline": len(result["pipeline_findings"]), "unverifiable": len(result["unverifiable"])}))

"""Minimal compiled checker used by the tests: flags a save_zip_code argument that is not among the digit
groups of the last customer utterance. Standard library only, no skill imports."""
import re

CHECKER_VERSION = "mini-checker/1"
POINT = "zip_collection.save_zip_code.args.zip_code"


def check_conversation(conversation):
    last_customer = None
    findings = []
    points = []
    for event in conversation.get("events", []):
        kind = event.get("kind")
        if kind == "customer_utterance":
            last_customer = event
        elif kind == "tool_call" and event.get("tool") == "save_zip_code":
            points.append(POINT)
            argument = str((event.get("args") or {}).get("zip_code", ""))
            said = re.findall(r"\d+", (last_customer or {}).get("text", "") or "")
            if argument and argument not in said:
                findings.append({
                    "turn": event.get("turn"), "point": POINT, "author": "model", "type": "unsupported_argument",
                    "check_kind": "grounding", "severity": "medium", "confidence": "high", "observed": argument,
                    "expected_or_allowed": said, "rationale": "argument not among the digits the customer said",
                    "evidence": [
                        {"kind": "customer_utterance", "turn": (last_customer or {}).get("turn"),
                         "quote": (last_customer or {}).get("text"), "locator": (last_customer or {}).get("locator")},
                        {"kind": "tool_call", "turn": event.get("turn"), "quote": "save_zip_code(%s)" % (event.get("args"),),
                         "locator": event.get("locator")},
                        {"kind": "pseudocode", "ref": "tool save_zip_code inputs.zip_code", "provenance": "seen_in_code"}],
                    "decided_by": "checker"})
    return {"conversation_id": conversation.get("conversation_id"), "findings": findings, "pipeline_findings": [],
            "unverifiable": [], "points_evaluated": points}

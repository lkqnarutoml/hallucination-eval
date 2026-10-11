"""In-memory builders shared by the tests: CES responses, events.jsonl sessions, CSV exports, findings.

Mirrors the runner's capture format: `agent_message` is logged BEFORE the execution spans of the same turn,
execution spans carry Google-side start times, and the CES response holds the ordered diagnosticInfo chunks.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Iterable, List, Optional

T0 = _dt.datetime(2026, 9, 18, 4, 59, 0, tzinfo=_dt.timezone.utc)


def ts(seconds: float, zulu: bool = True) -> str:
    moment = T0 + _dt.timedelta(seconds=seconds)
    if zulu:
        return moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return moment.isoformat()


def tool_resource(name: str) -> str:
    return "projects/p/locations/l/apps/a/tools/demo-" + name.replace("_", "-")


def ces_response(customer_text: str, agent_text: Optional[str] = None, tools: Iterable[tuple] = (),
                 transcript: bool = False, base: float = 0.0, defaults: Optional[dict] = None) -> dict:
    """tools: iterable of (name, args, response, effects). Chunks are emitted in production order:
    user text -> [defaultVariables] -> toolCall -> updatedVariables (effects) -> toolResponse -> ... -> model text."""
    key = "transcript" if transcript else "text"
    messages = [{"role": "user", "eventTime": ts(base), "chunks": [{key: customer_text}]}]
    chunks: List[dict] = []
    if defaults:
        chunks.append({"defaultVariables": defaults})
    for index, (name, args, response, effects) in enumerate(tools):
        call_id = "adk-%s-%d" % (name, index)
        chunks.append({"toolCall": {"id": call_id, "tool": tool_resource(name), "args": args, "displayName": name}})
        if effects:
            chunks.append({"updatedVariables": effects})
        chunks.append({"toolResponse": {"id": call_id, "tool": tool_resource(name), "response": {"result": response}}})
    if agent_text:
        chunks.append({key: agent_text})
    messages.append({"role": "model", "eventTime": ts(base + 1.0), "chunks": chunks})
    return {"outputs": [{"turnIndex": 0, "diagnosticInfo": {"messages": messages}}]}


def events_session(directory, turns: List[dict], session_id: str = "sim-test-0001", zip_answer: Optional[str] = "10001",
                   include_ces: bool = True) -> Path:
    """Write an events.jsonl file.

    turns: list of {"customer": str, "agent": str|None, "tools": [(name, args, response, effects, origin)], "transcript": bool}
    origin is "model" (spans: BeforeModel, model, AfterModel, Tool) or "callback" (spans: BeforeModel, Tool).
    """
    events: List[dict] = []
    counter = [0]

    def emit(event: str, **fields):
        counter[0] += 1
        row = {"sequence": counter[0], "event": event, "run_id": "run-test", "timestamp": ts(counter[0], zulu=False),
               "session_id": session_id, "scenario_id": "demo", "mode": "scripted"}
        row.update(fields)
        events.append(row)

    def span(kind: str, start: float, **attributes):
        return {"kind": kind, "name": {"callback": "Callback", "model": "LLM", "tool": "Tool"}[kind],
                "agent": "replace_debit_card_agent", "start": ts(start), "end": ts(start + 0.01), "attributes": attributes}

    record = {"id": "demo"}
    if zip_answer:
        record["zip_code_answer"] = zip_answer
    emit("session_start", turn=0, test_record=record)
    for turn_no, turn in enumerate(turns, start=1):
        base = turn_no * 10.0
        emit("customer_message", turn=turn_no, text=turn["customer"], input_modality="text")
        if turn.get("agent"):
            emit("agent_message", turn=turn_no, text=turn["agent"])
        offset = 0.1
        emit("execution_callback", turn=turn_no, span=span("callback", base + offset, stage="BeforeModel"))
        tools = turn.get("tools", [])
        for index, (name, args, response, effects, origin) in enumerate(tools):
            if origin == "model":
                offset += 0.1
                emit("execution_model", turn=turn_no, span=span("model", base + offset, model="test"))
                offset += 0.1
                emit("execution_callback", turn=turn_no, span=span("callback", base + offset, stage="AfterModel"))
            else:
                offset += 0.1
                emit("execution_callback", turn=turn_no, span=span("callback", base + offset, stage="BeforeModel"))
            offset += 0.1
            emit("execution_tool", turn=turn_no, span=span("tool", base + offset, name=name, type="PythonFunctionTool",
                                                            args=args, response={"result": response},
                                                            **{"tool call id": "adk-%s-%d" % (name, index)}))
        if tools:
            offset += 0.1
            emit("execution_callback", turn=turn_no, span=span("callback", base + offset, stage="BeforeModel"))
        if include_ces:
            emit("ces_response", turn=turn_no, transport="rest",
                 response=ces_response(turn["customer"], turn.get("agent"), [(n, a, r, e) for n, a, r, e, _ in tools],
                                       transcript=turn.get("transcript", False), base=base, defaults=turn.get("defaults")))
        state = {}
        for _, _, _, effects, _ in tools:
            if effects:
                for key, value in effects.items():
                    if isinstance(value, dict) and isinstance(state.get(key), dict):
                        state[key].update(value)
                    else:
                        state[key] = value
        if state:
            emit("state_snapshot", turn=turn_no, state=state)
    emit("session_end", turn=len(turns), end_reason="completed", tool_calls=[
        {"name": n, "args": a, "response": {"result": r}, "call_id": "adk-%s-%d" % (n, i), "agent": "replace_debit_card_agent"}
        for turn in turns for i, (n, a, r, _, _) in enumerate(turn.get("tools", []))])
    path = Path(directory) / "events.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


DEMO_TURNS = [
    {"customer": "hi", "agent": "For this demo, enter the five-digit ZIP 10001."},
    {"customer": "10001", "agent": "You entered 1 0 0 0 1. Is that correct?",
     "tools": [("save_zip_code", {"zip_code": "10001"}, {"status": "SUCCESS", "demo": True}, {"democard_state": {"user_zip": "10001"}}, "model")]},
    {"customer": "yes", "agent": "Would you like me to submit the card replacement request now?",
     "tools": [("validate_zip_code", {"zip_code": "10001"}, {"status": "SUCCESS", "demo": True, "verified": True},
                {"democard_state": {"user_zip": "10001", "is_zip_verified": True}}, "model"),
               ("indicate_ready_for_next_step", {}, {"status": "SUCCESS"}, None, "callback")]},
]

JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
       "eyJzdWIiOiJjYXJkaXgtc2ltIiwiaWF0IjoxNzI2NzkwNDAwLCJleHAiOjE3MjY3OTQwMDAsInNjb3BlIjoiY2FyZHMucmVhZCBjYXJkcy5yZXBsYWNlIn0."
       "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
TEST_PANS = ["4242424242424242", "5555555555554444", "4111111111111111"]
DEVICES = [{"device_name": "iPhone 15 Pro", "last4": "4242", "token_status": "active"},
           {"device_name": "Apple Watch", "last4": "4242", "token_status": "active"},
           {"device_name": "Pixel 8", "last4": "4444", "token_status": "suspended"}]


def payment_history(count: int = 60) -> list:
    return [{"payment_id": "pay-%04d" % i, "card_number": TEST_PANS[i % 3], "amount": round(10.0 + i * 1.25, 2),
             "posted_at": 1726790400000 + i * 86400000, "merchant": "Merchant %d" % i, "status": "POSTED",
             "memo": "x" * 120} for i in range(count)]


# A session shaped like production voice logs: a token callback whose response and state carry a JWT, a device
# token list, a 60-item payment history in a tool response and in state, and a customer reading a card number.
BLOATED_TURNS = [
    {"customer": "hi", "agent": "Welcome to DemoCard. For this demo, enter the five-digit ZIP 10001.",
     "defaults": {"democard_state": {"retry_count": 0, "flow": "damaged"}},
     "tools": [("get_token", {}, {"status": "SUCCESS", "access_token": JWT, "token_type": "Bearer", "expires_in": 3600},
                {"democard_state": {"got_bearer_token": True, "access_token": JWT, "authorization": "Bearer " + JWT}}, "callback")]},
    {"customer": "10001", "agent": "You entered 1 0 0 0 1. Is that correct?",
     "tools": [("save_zip_code", {"zip_code": "10001"}, {"status": "SUCCESS", "demo": True}, {"democard_state": {"user_zip": "10001"}}, "model")]},
    {"customer": "yes, and my card number is 4242 4242 4242 4242", "agent": "Would you like me to submit the card replacement request now?",
     "tools": [("validate_zip_code", {"zip_code": "10001"}, {"status": "SUCCESS", "demo": True, "verified": True},
                {"democard_state": {"user_zip": "10001", "is_zip_verified": True, "last4CardDigits": "4242"}}, "model"),
               ("get_payments", {"account_id": "acct-7f3a9c2e1b4d5e6f7a8b9c0d1e2f3a4b"},
                {"status": "SUCCESS", "payments": payment_history(), "tokens": DEVICES},
                {"democard_state": {"payments": payment_history(), "tokens": DEVICES}}, "model"),
               ("indicate_ready_for_next_step", {}, {"status": "SUCCESS"}, None, "callback")]},
    {"customer": "what were my last payments", "agent": "Your last five payments are listed.",
     "tools": [("get_payments", {"account_id": "acct-7f3a9c2e1b4d5e6f7a8b9c0d1e2f3a4b", "limit": 5},
                {"status": "SUCCESS", "payments": payment_history(5), "tokens": DEVICES},
                {"democard_state": {"user_zip": "10001", "is_zip_verified": True, "last4CardDigits": "4242", "payments": payment_history(5), "tokens": DEVICES}}, "model")]},
]

CSV_HEADER = ["conversation_id", "event_time", "event_type", "speaker", "utterance", "tool_name", "tool_input", "tool_response", "updated_variables"]
CSV_ROWS = [
    ["conv-0001-abcdef", "2026-09-18T05:00:01Z", "USER_UTTERANCE", "user", "my zip is 100011", "", "", "", ""],
    ["conv-0001-abcdef", "2026-09-18T05:00:02Z", "TOOL_CALL", "replace_debit_card_agent", "", "save_zip_code",
     "{'zip_code': '10001'}", '{"result": {"status": "SUCCESS"}}', "{'user_zip': '10001', 'is_zip_verified': False, 'x': None}"],
    ["conv-0001-abcdef", "2026-09-18T05:00:03Z", "AGENT_UTTERANCE", "replace_debit_card_agent",
     "Just to be sure, I heard 10001. Is that the correct zip code?", "", "", "", ""],
    ["conv-0001-abcdef", "2026-09-18T05:00:04Z", "USER_UTTERANCE", "user", "yes", "", "", "", ""],
    ["conv-0001-abcdef", "2026-09-18T05:00:05Z", "TOOL_CALL", "replace_debit_card_agent", "", "validate_zip_code",
     '{"zip_code": "10001"}', "", ""],
    ["conv-0001-abcdef", "2026-09-18T05:00:06Z", "TOOL_CALL", "replace_debit_card_agent", "", "validate_zip_code", "",
     '{"result": {"status": "FAILURE"}}', ""],
    ["conv-0001-abcdef", "2026-09-18T05:00:06Z", "TOOL_CALL", "replace_debit_card_agent", "", "validate_zip_code", "",
     '{"result": {"status": "FAILURE"}}', ""],
    ["conv-0002-abcdef", "2026-09-18T05:10:01Z", "USER_UTTERANCE", "user", "hello", "", "", "", ""],
    ["conv-0002-abcdef", "2026-09-18T05:10:02Z", "AGENT_UTTERANCE", "replace_debit_card_agent", "Can you confirm your ZIP code?", "", "", "", ""],
]


def write_csv(path, header=CSV_HEADER, rows=CSV_ROWS) -> Path:
    import csv

    target = Path(path)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return target


def column_map(sheet=None) -> dict:
    return {"version": 1, "sheet": sheet,
            "columns": {"session_id": "conversation_id", "timestamp": "event_time", "row_type": "event_type", "speaker": "speaker",
                        "text": "utterance", "tool_name": "tool_name", "tool_args": "tool_input", "tool_response": "tool_response",
                        "state": "updated_variables"},
            "ordering": "timestamp_then_row"}


def final_findings(conversations: List[dict], model: str = "test-model") -> dict:
    return {"meta": {"skill": "hallucination-eval", "skill_version": "0.1.0", "generated_at": "2026-09-20T00:00:00+00:00",
                     "target_agent": "DemoCard", "pseudocode_file": None, "pseudocode_sha256": None, "materials": [],
                     "trajectory_sources": [], "evaluator": {"mode": "multi-agent", "model": model, "checker_script": None,
                                                             "batches": 1, "audited": True},
                     "sampling": None,
                     "reference_points": ["customer utterances and history", "tool catalogue", "arguments passed",
                                          "tool results", "session state", "workflow rules"]},
            "conversations": conversations}

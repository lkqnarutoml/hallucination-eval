# Workflow pseudocode: DemoCard (worked excerpt, damaged-card ZIP stage)

<!-- This excerpt shows the architect what a finished workflow_pseudocode.md looks like. It covers the damaged flow of
     replace_debit_card_agent from the first ZIP prompt to the submission, plus the shared ending tool. The lost and stolen
     flows, the delivery-status agent and the bootstrap tools are deliberately left out (they would follow the same
     shape). It compiles with scripts/build_spec.py; tests/test_build_spec.py keeps it valid. -->

Build or version: DEV build from the console export (materials/democard), demo channel damaged_card
Materials read: materials/democard/tools/*.py, materials/democard/callbacks/cb_replace_*.py, materials/democard/instructions/replace_debit_card_agent.txt, materials/democard/package/DemoCard/agents/*, materials/democard/variables.json
Reconciled with: docs/democard_pseudocode_v1.md and docs/democard_workflow_intro.md

## 0. Conventions

- `S` is the session state. `CODE` marks decisions made by callbacks or tools; `MODEL` marks decisions made by Gemini.
- `say "..."` is customer-facing text; `CALL tool(args)` executes a tool; `last_tool` is the tool whose result the
  callback just saw.
- Input classes: digits5, digits_other, no_digits, affirmative, negative, repeat_request, agent_request, cancel_request,
  out_of_scope, no_input, other. `digits5` means the customer's utterance contains exactly one five-digit group and no
  other digit group (spoken, spaced or contiguous). `digits_other` means at least one digit group but none of exactly
  five digits.

## 1. Agents and routing

The root agent never speaks and never calls the model. Its before-model callback bootstraps tokens and the customer
record in three visits, then a forced handoff rule on `S.caller_intent` routes to one sub-agent. The excerpt follows
`replace_debit_card_agent` only.

```json
{"kind": "routing", "root_agent": "DemoCard steering agent",
 "rules": [
   {"when": "S.caller_intent == 'card.replace'", "to": "replace_debit_card_agent", "author": "code"},
   {"when": "S.caller_intent == 'delivery.status.inquiry'", "to": "card_delivery_status_agent", "author": "code"},
   {"when": "S.caller_intent not in ('card.replace', 'delivery.status.inquiry')", "to": "agent_transfer_no_ivr_intent", "author": "code"}],
 "agents": {
   "DemoCard steering agent": {"tools": ["get_token", "telephony_get_token", "_initialize_session_for_dev", "end_session"],
                             "sub_agents": ["replace_debit_card_agent", "card_delivery_status_agent", "agent_transfer_no_ivr_intent"], "prompt_file": null},
   "replace_debit_card_agent": {"tools": ["save_zip_code", "indicate_invalid_zipcode", "validate_zip_code", "indicate_wrong_zip",
                                          "indicate_ready_for_next_step", "replace_debit_card", "democard_end_conversation", "increment_retry_counter",
                                          "out_of_scope_handling", "handle_cancel_card_replacement_request", "end_session"],
                                "sub_agents": ["Transfer_to_human_agent"], "prompt_file": "materials/democard/instructions/replace_debit_card_agent.txt"},
   "card_delivery_status_agent": {"tools": ["get_delivery_status", "increment_retry_counter", "democard_end_conversation", "end_session"], "sub_agents": [],
                                  "prompt_file": "materials/democard/instructions/card_delivery_status_agent.txt"},
   "agent_transfer_no_ivr_intent": {"tools": ["democard_end_conversation", "end_session"], "sub_agents": [], "prompt_file": null},
   "Transfer_to_human_agent": {"tools": ["democard_end_conversation", "end_session"], "sub_agents": [], "prompt_file": null}},
 "provenance": "seen_in_code"}
```

## 2. Turn skeleton (replace_debit_card_agent)

```text
procedure TURN(user_text):
    before_agent_callback(S)            # CODE: pick the first step of FLOWS[S.issue_reason] whose gate is true -> S.instructions
    loop:
        r = before_model_callback(S)    # CODE: rules R1..R15 in order; first hit returns text and/or a tool call, model skipped
        if r is None: r = MODEL(prompt(S.instructions), history)     # the only model decision of the turn
        r = after_model_callback(S, r)  # CODE: insert the goodbye/transfer filler before democard_end_conversation; init_session_end -> end_session
        if r has tool calls: execute them (they write S); continue   # the callback runs again with last_tool set
        say r.text; break
```

```json
{"kind": "turn_skeleton", "agent": "replace_debit_card_agent",
 "before_model": ["R1_no_input", "R7_first_zip_prompt", "R10_consent_prompt", "R13_session_end", "R14_dispatch_on_last_tool"],
 "after_model": ["A1_filler_before_end_conversation", "A2_end_session_when_flagged"],
 "model_decides_only_when": "no before_model rule returned and S.instructions holds the active step",
 "provenance": "seen_in_code"}
```

## 3. Flows, gates and steps

```json
{"kind": "flows", "flows": {"damaged": ["zip_collection", "zip_confirmation", "card_replacement"]},
 "gates": {"zip_collection": "not S.user_zip", "zip_confirmation": "S.user_zip and not S.is_zip_verified",
           "card_replacement": "S.is_zip_verified and S.isReadyForTurn2"},
 "default_flow": "lost", "step_source": "instructions", "provenance": "seen_in_code"}
```

### Step: zip_collection

```text
GATE: not S.user_zip                                     # first turn: CODE R7 asks for the ZIP, model skipped
MODEL reads the customer's reply and counts digit groups:
  digits5      -> CALL save_zip_code(zip_code = the five digits as spoken)   # never pad, never truncate, never reuse an earlier ZIP
  digits_other -> CALL indicate_invalid_zipcode(); then ask again for a five-digit ZIP (model wording)
  no_digits    -> CALL indicate_invalid_zipcode(); ask again
  agent_request / cancel_request / out_of_scope -> global interrupt (see step interrupt)
CODE after save_zip_code: say "Just to be sure, I heard {user_zip}. Is that the correct zip code?"  -- the model must not repeat it
CODE after indicate_invalid_zipcode: confirmation_retry_count > 1 -> escalate "User entered incomplete zip or refused to give a zip too many times"; else count += 1 and let the model re-ask
```

```json
{"kind": "step", "name": "zip_collection", "flows": ["damaged"], "gate": "not S.user_zip", "author": "model",
 "context": {"customer_utterance": "current", "state": ["issue_reason", "confirmation_retry_count"], "history": "full"},
 "decide": {"digits5": {"call": "save_zip_code", "args": {"zip_code": "$customer.digits5"}},
            "digits_other": {"call": "indicate_invalid_zipcode"},
            "no_digits": {"call": "indicate_invalid_zipcode"},
            "agent_request": {"call": "democard_end_conversation", "args": {"reason": "User requested agent", "session_escalated": true}},
            "cancel_request": {"call": "handle_cancel_card_replacement_request", "args": {"stage": "Confirm cancellation intent"}},
            "out_of_scope": {"call": "out_of_scope_handling"},
            "other": {"call": "indicate_invalid_zipcode", "check": "judgment"}},
 "must_not": {"call": ["validate_zip_code", "replace_debit_card"], "speak_after": ["save_zip_code"], "speak_when": null},
 "then": {"save_zip_code": {"say": "Just to be sure, I heard {user_zip}. Is that the correct zip code?", "ground": {"user_zip": "state"},
                            "effects": {"user_zip": "$args.zip_code"}, "next_call": null},
          "indicate_invalid_zipcode": {"say": null, "ground": {}, "effects": {"confirmation_retry_count": "+1"}, "next_call": null}},
 "provenance": "seen_in_code"}
```

### Step: zip_confirmation

```text
GATE: S.user_zip and not S.is_zip_verified
MODEL was just asked (by CODE) to confirm the read-back:
  affirmative  -> CALL validate_zip_code(zip_code = S.user_zip); stay silent unless the result is SUCCESS
  negative     -> CALL indicate_wrong_zip(); say "Sorry, I couldn't catch the zipcode you provided, can you please say that again?"
  digits5 / digits_other (a new number) -> CALL indicate_wrong_zip()
  other        -> ambiguity handler (increment_retry_counter, re-ask)
CODE after validate_zip_code: see tool contract and rules R14b..R14e
```

```json
{"kind": "step", "name": "zip_confirmation", "flows": ["damaged"], "gate": "S.user_zip and not S.is_zip_verified", "author": "model",
 "context": {"customer_utterance": "current", "state": ["user_zip", "confirmation_retry_count"], "history": "full"},
 "decide": {"affirmative": {"call": "validate_zip_code", "args": {"zip_code": "$state.user_zip"}},
            "negative": {"call": "indicate_wrong_zip"},
            "digits5": {"call": "indicate_wrong_zip"},
            "digits_other": {"call": "indicate_wrong_zip"},
            "agent_request": {"call": "democard_end_conversation", "args": {"reason": "User requested agent", "session_escalated": true}},
            "cancel_request": {"call": "handle_cancel_card_replacement_request", "args": {"stage": "Confirm cancellation intent"}},
            "out_of_scope": {"call": "out_of_scope_handling"},
            "other": {"call": "increment_retry_counter", "check": "judgment"}},
 "must_not": {"call": ["save_zip_code", "replace_debit_card"], "speak_after": ["validate_zip_code"], "speak_when": "validate_zip_code returned anything but SUCCESS"},
 "then": {"validate_zip_code": {"say": null, "ground": {}, "effects": {}, "next_call": "indicate_ready_for_next_step"},
          "indicate_wrong_zip": {"say": null, "ground": {}, "effects": {"user_zip": null, "confirmation_retry_count": "+1"}, "next_call": null}},
 "provenance": "seen_in_code"}
```

### Step: card_replacement

```text
GATE: S.is_zip_verified and S.isReadyForTurn2           # CODE R10 already asked "Would you like me to submit ... ending in {last4CardDigits} now?"
MODEL (SILENCE CRITICAL: no spoken text in the same turn as a tool call):
  affirmative -> CALL replace_debit_card()
  negative    -> CALL democard_end_conversation(reason="User declined replacement transferring caller to a human agent", session_escalated=true)
  after replace_debit_card SUCCESS, CODE spoke the confirmation ending "Is there anything else I can help you with?":
     negative (nothing else) -> CALL democard_end_conversation(reason="Card submission successful")
     anything else            -> CALL democard_end_conversation(reason="User requested agent for follow-up inquiry post card submission", session_escalated=true)
```

```json
{"kind": "step", "name": "card_replacement", "flows": ["damaged"], "gate": "S.is_zip_verified and S.isReadyForTurn2", "author": "model",
 "context": {"customer_utterance": "current", "state": ["last4CardDigits", "card_replacement_submitted"], "history": "full"},
 "decide": {"affirmative": {"call": "replace_debit_card", "check": "judgment"},
            "negative": {"call": "democard_end_conversation", "args": {"reason": "User declined replacement transferring caller to a human agent", "session_escalated": true}, "check": "judgment"},
            "agent_request": {"call": "democard_end_conversation", "args": {"reason": "User requested agent", "session_escalated": true}},
            "cancel_request": {"call": "handle_cancel_card_replacement_request", "args": {"stage": "Confirm cancellation intent"}},
            "out_of_scope": {"call": "out_of_scope_handling"},
            "other": {"call": "increment_retry_counter", "check": "judgment"}},
 "must_not": {"call": ["save_zip_code", "validate_zip_code"], "speak_after": ["replace_debit_card", "democard_end_conversation"], "speak_when": "any tool is called in this turn"},
 "then": {"replace_debit_card": {"say": "Your card replacement request has been submitted successfully! ... Is there anything else I can help you with?",
                                 "ground": {}, "effects": {"card_replacement_submitted": true, "disclosure_read": true}, "next_call": null}},
 "provenance": "seen_in_code"}
```

### Step: interrupt

```text
Global interrupt handlers from the static instructions apply at every step (the model may fire them instead of the step's table):
  agent_request  -> CALL democard_end_conversation(reason="User requested agent", session_escalated=true)
  cancel_request -> CALL handle_cancel_card_replacement_request(stage="Confirm cancellation intent"); follow the tool's next_steps
  out_of_scope   -> CALL out_of_scope_handling(); say the scope message
  other (ambiguous / frustrated / non-English) -> CALL increment_retry_counter(); at count >= 2 escalate with the matching reason
```

```json
{"kind": "step", "name": "interrupt", "flows": ["damaged"], "gate": "any step (global handler, evaluated by the model)", "author": "model", "global": true,
 "context": {"customer_utterance": "current", "state": ["confirmation_retry_count", "card_replacement_submitted"], "history": "full"},
 "decide": {"agent_request": {"call": "democard_end_conversation", "args": {"reason": "User requested agent", "session_escalated": true}},
            "cancel_request": {"call": "handle_cancel_card_replacement_request", "args": {"stage": "Confirm cancellation intent"}},
            "out_of_scope": {"call": "out_of_scope_handling"},
            "other": {"call": "increment_retry_counter", "check": "judgment"}},
 "must_not": {"call": [], "speak_after": ["democard_end_conversation"], "speak_when": null},
 "then": {}, "provenance": "inferred"}
```

## 4. Tool contracts

### Tool: save_zip_code

```text
save_zip_code(zip_code: str) -> {"status": "SUCCESS"}      # MODEL calls it; writes S.user_zip = zip_code, nothing else
```

```json
{"kind": "tool", "name": "save_zip_code", "author": "model", "agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"],
 "inputs": {"zip_code": {"type": "digits", "ground_in": "customer_utterance.current", "rule": "exactly_5_digits_as_spoken", "enum": []}},
 "outputs": {"status": ["SUCCESS"]}, "effects": {"user_zip": "$args.zip_code"},
 "deterministic_rule": {"id": null, "needs": [], "description": "no computation"},
 "preconditions": {"step": "zip_collection", "state": "not S.user_zip"}, "provenance": "seen_in_code"}
```

### Tool: indicate_invalid_zipcode

```json
{"kind": "tool", "name": "indicate_invalid_zipcode", "author": "model", "agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"],
 "inputs": {}, "outputs": {"status": ["REPROMPT_USER"]}, "effects": {},
 "deterministic_rule": {"id": null, "needs": [], "description": "signal only; the callback counts confirmation_retry_count"},
 "preconditions": {"step": "zip_collection", "state": null}, "provenance": "seen_in_code"}
```

### Tool: validate_zip_code

```text
validate_zip_code(zip_code) -> status
    S.user_zip = zip_code
    if zip_code in {"99991", "99992"}: return SYSTEM_ERROR                       # test hooks
    zip_on_file = GetMailingAddress(cardNumber, customerNumber).zipcode   # external, not in the log
    if str(zip_on_file)[:5] == str(zip_code)[:5]: S.zip_validation_retry_count = 0; S.is_zip_verified = True; return SUCCESS
    S.zip_validation_retry_count += 1                                             # also on any API exception
    return TRANSFER_REQUIRED if S.zip_validation_retry_count >= 2 else FAILURE
```

```json
{"kind": "tool", "name": "validate_zip_code", "author": "model", "agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"],
 "inputs": {"zip_code": {"type": "digits", "ground_in": "state.user_zip", "rule": "equals the ZIP the callback read back", "enum": []}},
 "outputs": {"status": ["SUCCESS", "FAILURE", "TRANSFER_REQUIRED", "SYSTEM_ERROR"]},
 "effects": {"user_zip": "$args.zip_code", "is_zip_verified": "True on SUCCESS", "zip_validation_retry_count": "0 on SUCCESS, +1 otherwise"},
 "deterministic_rule": {"id": "ZIP_MATCH", "needs": ["zip_on_file"], "description": "first five characters of the argument equal the first five of the ZIP on file"},
 "preconditions": {"step": "zip_confirmation", "state": "S.user_zip and not S.is_zip_verified"}, "provenance": "seen_in_code"}
```

### Tool: indicate_wrong_zip

```json
{"kind": "tool", "name": "indicate_wrong_zip", "author": "model", "agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"],
 "inputs": {}, "outputs": {"status": ["SUCCESS"]}, "effects": {},
 "deterministic_rule": {"id": null, "needs": [], "description": "signal only; the callback clears user_zip and counts"},
 "preconditions": {"step": "zip_confirmation", "state": null}, "provenance": "seen_in_code"}
```

### Tool: indicate_ready_for_next_step

```json
{"kind": "tool", "name": "indicate_ready_for_next_step", "author": "code", "agents": ["replace_debit_card_agent"], "flows": ["damaged"],
 "inputs": {}, "outputs": {"status": ["SUCCESS"]}, "effects": {"isReadyForTurn2": true},
 "deterministic_rule": {"id": null, "needs": [], "description": "chained by callback rule R14c after a successful validation in the damaged flow"},
 "preconditions": {"step": null, "state": "S.is_zip_verified"}, "provenance": "seen_in_code"}
```

### Tool: replace_debit_card

```text
replace_debit_card() -> {"status": "SUCCESS" | "FAILURE"}
    if S.is_zip_verified is False: S.prerequisite_zipcode_failed = True; return {}     # code-level hard gate
    payload from S (customer identity, card, issue_reason -> replacementReason/cardStatus); submission API is MOCKED in the DEV build
    on SUBMITTED: S.card_replacement_submitted = True; damaged -> SUCCESS immediately
```

```json
{"kind": "tool", "name": "replace_debit_card", "author": "model", "agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"],
 "inputs": {}, "outputs": {"status": ["SUCCESS", "FAILURE"]},
 "effects": {"card_replacement_submitted": "True on SUBMITTED", "prerequisite_zipcode_failed": "True when called without a verified ZIP"},
 "deterministic_rule": {"id": "SUBMIT_MOCK", "needs": [], "description": "with is_zip_verified the mocked submission always returns SUCCESS; without it the tool returns {} and the callback escalates"},
 "preconditions": {"step": "card_replacement", "state": "S.is_zip_verified and S.isReadyForTurn2"}, "provenance": "seen_in_code"}
```

### Tool: democard_end_conversation

```json
{"kind": "tool", "name": "democard_end_conversation", "author": "both", "agents": ["replace_debit_card_agent", "card_delivery_status_agent", "agent_transfer_no_ivr_intent", "Transfer_to_human_agent"],
 "flows": ["damaged", "lost", "stolen", "delivery_status"],
 "inputs": {"reason": {"type": "enum", "ground_in": "enum", "rule": "one of the reason strings in end_reasons for the situation that occurred", "enum": []},
            "session_escalated": {"type": "bool", "ground_in": "enum", "rule": "true for every transfer, absent or false for a plain hang-up", "enum": [true, false]}},
 "outputs": {"status": ["Completed democard_end_conversation successfully", "Failed to end session: ..."]},
 "effects": {"end_session_reason": "$args.reason", "end_session_is_escalated": "$args.session_escalated", "init_session_end": true},
 "deterministic_rule": {"id": "END_ROUTING", "needs": [], "description": "escalated -> telephony transfer + transfer target; else telephony hangup; the next callback visit emits end_session"},
 "preconditions": {"step": null, "state": null}, "provenance": "seen_in_code"}
```

### Tool: increment_retry_counter

```json
{"kind": "tool", "name": "increment_retry_counter", "author": "both", "agents": ["replace_debit_card_agent", "card_delivery_status_agent"], "flows": ["damaged", "lost", "stolen", "delivery_status"],
 "inputs": {}, "outputs": {"new_retry_count": ["integer"]}, "effects": {"confirmation_retry_count": "+1"},
 "deterministic_rule": {"id": null, "needs": [], "description": "counter"}, "preconditions": {"step": null, "state": null}, "provenance": "seen_in_code"}
```

### Tool: out_of_scope_handling

```json
{"kind": "tool", "name": "out_of_scope_handling", "author": "model", "agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"],
 "inputs": {}, "outputs": {"status": ["SUCCESS"]}, "effects": {"out_of_scope_response": true},
 "deterministic_rule": {"id": null, "needs": [], "description": "signal only; the callback escalates at confirmation_retry_count >= 2 or after submission"},
 "preconditions": {"step": null, "state": null}, "provenance": "seen_in_code"}
```

### Tool: handle_cancel_card_replacement_request

```json
{"kind": "tool", "name": "handle_cancel_card_replacement_request", "author": "model", "agents": ["replace_debit_card_agent"], "flows": ["damaged", "lost", "stolen"],
 "inputs": {"stage": {"type": "enum", "ground_in": "enum", "rule": "first call: Confirm cancellation intent; second call after the customer confirms: Offer human agent", "enum": ["Confirm cancellation intent", "Offer human agent"]}},
 "outputs": {"status": ["SUCCESS", "FAILURE"]}, "effects": {"cancel_model_text": "the confirmation or offer sentence the callback will speak"},
 "deterministic_rule": {"id": null, "needs": [], "description": "returns next_steps text the model must follow"},
 "preconditions": {"step": null, "state": null}, "provenance": "seen_in_code"}
```

## 5. Callback rules (code-authored points), evaluation order

```json
{"kind": "callback_rule", "id": "R7_first_zip_prompt", "agent": "replace_debit_card_agent", "when": "S.needs_zip_prompt and S.issue_reason in ('lost', 'damaged')", "author": "code",
 "say": "To replace your {issue_reason} debit card, can you please confirm your ZIP code?", "ground": {"issue_reason": "state"},
 "effects": {"needs_zip_prompt": false}, "next_call": null, "escalate": null, "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R10_consent_prompt", "agent": "replace_debit_card_agent", "when": "S.needs_consent_prompt", "author": "code",
 "say": "Would you like me to submit the card replacement request for your card ending in {last4CardDigits} now?", "ground": {"last4CardDigits": "state"},
 "effects": {"needs_consent_prompt": false}, "next_call": null, "escalate": null, "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R13_session_end", "agent": "replace_debit_card_agent", "when": "S.init_session_end", "author": "code",
 "say": null, "ground": {}, "effects": {}, "next_call": "end_session", "escalate": null, "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R14a_readback", "agent": "replace_debit_card_agent", "when": "last_tool == save_zip_code", "author": "code",
 "say": "Just to be sure, I heard {user_zip}. Is that the correct zip code?", "ground": {"user_zip": "state"},
 "effects": {}, "next_call": null, "escalate": null, "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R14b_zip_failure", "agent": "replace_debit_card_agent", "when": "last_tool == validate_zip_code and status == FAILURE and S.zip_validation_retry_count < 2", "author": "code",
 "say": "Sorry, I could not catch the zipcode you provided, can you please say that again?", "ground": {},
 "effects": {"user_zip": null, "confirmation_retry_count": "+1"}, "next_call": "increment_retry_counter", "escalate": null, "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R14c_zip_success_damaged", "agent": "replace_debit_card_agent", "when": "last_tool == validate_zip_code and status == SUCCESS and S.issue_reason == 'damaged'", "author": "code",
 "say": null, "ground": {}, "effects": {"needs_consent_prompt": true}, "next_call": "indicate_ready_for_next_step", "escalate": null, "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R14d_zip_transfer", "agent": "replace_debit_card_agent", "when": "last_tool == validate_zip_code and (status == TRANSFER_REQUIRED or S.zip_validation_retry_count >= 2)", "author": "code",
 "say": "I am having trouble validating your zip code. I will transfer you to a representative who can assist you further.", "ground": {},
 "effects": {"confirmation_retry_count": "+1"}, "next_call": "democard_end_conversation", "escalate": "Max zip validation failures", "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R14e_zip_system_error", "agent": "replace_debit_card_agent", "when": "last_tool == validate_zip_code and status == SYSTEM_ERROR", "author": "code",
 "say": "Sorry, something went wrong on my side. Let me transfer you to a representative.", "ground": {},
 "effects": {}, "next_call": "democard_end_conversation", "escalate": "verify_zip system error", "provenance": "inferred"}
```

```json
{"kind": "callback_rule", "id": "R14f_wrong_zip", "agent": "replace_debit_card_agent", "when": "last_tool == indicate_wrong_zip", "author": "code",
 "say": null, "ground": {}, "effects": {"user_zip": null, "confirmation_retry_count": "+1"}, "next_call": null,
 "escalate": "Agent got users zipcode wrong too many times (second time only)", "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "R14g_submitted", "agent": "replace_debit_card_agent", "when": "last_tool == replace_debit_card and status == SUCCESS", "author": "code",
 "say": "Your card replacement request has been submitted successfully! ... Is there anything else I can help you with?", "ground": {},
 "effects": {"disclosure_read": true}, "next_call": null, "escalate": null, "provenance": "seen_in_code"}
```

```json
{"kind": "callback_rule", "id": "A1_filler_before_end_conversation", "agent": "replace_debit_card_agent", "when": "the model's response contains democard_end_conversation(reason)", "author": "code",
 "say": "FILLER[reason] (e.g. Card submission successful -> 'Thank you for calling Example Bank. Have a great day'; escalated default -> 'Please wait while I transfer your call to a representative.')",
 "ground": {}, "effects": {}, "next_call": null, "escalate": null, "provenance": "seen_in_code"}
```

## 6. Deterministic rules

```json
{"kind": "rule", "id": "ZIP_MATCH", "description": "str(zip_on_file)[:5] == str(zip_code)[:5]; match -> SUCCESS and is_zip_verified=True; mismatch or API error -> zip_validation_retry_count += 1, then TRANSFER_REQUIRED when the count reaches the threshold, else FAILURE; 99991 and 99992 -> SYSTEM_ERROR",
 "needs": ["zip_on_file"], "thresholds": {"zip_validation_retry_count": 2}, "provenance": "seen_in_code"}
```

```json
{"kind": "rule", "id": "SUBMIT_MOCK", "description": "replace_debit_card returns SUCCESS whenever is_zip_verified is true (the real API is commented out); {} when the ZIP was never verified",
 "needs": [], "thresholds": {}, "provenance": "seen_in_code"}
```

```json
{"kind": "rule", "id": "END_ROUTING", "description": "session_escalated -> update_telephony('transfer','false') and transfer target (IVR, +15555550100); otherwise update_telephony('Hangup','true') and HANGUP; then end_session on the next callback visit",
 "needs": [], "thresholds": {}, "provenance": "seen_in_code"}
```

## 7. End and transfer reasons

```json
{"kind": "end_reasons",
 "model_issued": [
   {"reason": "Card submission successful", "escalated": false, "when": "after replace_debit_card SUCCESS the customer needs nothing else"},
   {"reason": "User declined replacement transferring caller to a human agent", "escalated": true, "when": "customer says no to the consent question"},
   {"reason": "User requested agent for follow-up inquiry post card submission", "escalated": true, "when": "after submission the customer asks for anything else"},
   {"reason": "User requested agent", "escalated": true, "when": "customer asks for a human at any point (incl. DTMF 0)"},
   {"reason": "Max ambiguous confirmation retries reached", "escalated": true, "when": "confirmation_retry_count >= 2 in the ambiguity handler"},
   {"reason": "Safety/Abuse detected", "escalated": true, "when": "hostile or abusive input"},
   {"reason": "Fraud detected", "escalated": true, "when": "fraud keywords"},
   {"reason": "User accepted transfer due to frustration", "escalated": true, "when": "customer says yes to the frustration offer"},
   {"reason": "User remained frustrated after retry", "escalated": true, "when": "second frustration"},
   {"reason": "Max non-English attempts reached", "escalated": true, "when": "second non-English turn"},
   {"reason": "User confirmed cancel and requested agent", "escalated": true, "when": "cancel flow, wants a human"},
   {"reason": "User confirmed cancel and declined agent", "escalated": false, "when": "cancel flow, declines a human"}],
 "code_issued": [
   {"reason": "Max zip validation failures", "escalated": true, "rule": "R14d_zip_transfer"},
   {"reason": "verify_zip system error", "escalated": true, "rule": "R14e_zip_system_error"},
   {"reason": "Agent got users zipcode wrong too many times", "escalated": true, "rule": "R14f_wrong_zip"},
   {"reason": "User entered incomplete zip or refused to give a zip too many times", "escalated": true, "rule": "R14h_invalid_zip"},
   {"reason": "user zip code was not verified", "escalated": true, "rule": "R12_prerequisite_failed"},
   {"reason": "API failure during replacement", "escalated": true, "rule": "R14g_submitted"},
   {"reason": "User requested agent for out-of-scope inquiry", "escalated": true, "rule": "R14i_out_of_scope"},
   {"reason": "User cancelled post-submission", "escalated": true, "rule": "R14j_cancel"},
   {"reason": "Max inactivity timeouts reached", "escalated": false, "rule": "R1_no_input"}],
 "provenance": "seen_in_code"}
```

## 8. State variables (subset used by the excerpt)

```json
{"kind": "variables", "variables": {
   "issue_reason": {"default": "", "set_by": ["_initialize_session_for_dev"], "consumed_by": ["flow choice", "R7_first_zip_prompt", "prompt chip"]},
   "caller_intent": {"default": "", "set_by": ["_initialize_session_for_dev"], "consumed_by": ["routing"]},
   "needs_zip_prompt": {"default": true, "set_by": ["R7_first_zip_prompt"], "consumed_by": ["R7_first_zip_prompt"]},
   "user_zip": {"default": null, "set_by": ["save_zip_code", "validate_zip_code", "R14b_zip_failure", "R14f_wrong_zip"], "consumed_by": ["gate zip_collection", "gate zip_confirmation", "R14a_readback", "validate_zip_code"]},
   "is_zip_verified": {"default": false, "set_by": ["validate_zip_code"], "consumed_by": ["gate zip_confirmation", "gate card_replacement", "replace_debit_card"]},
   "zip_validation_retry_count": {"default": 0, "set_by": ["validate_zip_code"], "consumed_by": ["R14b_zip_failure", "R14d_zip_transfer"]},
   "confirmation_retry_count": {"default": 0, "set_by": ["increment_retry_counter", "R14b_zip_failure", "R14f_wrong_zip"], "consumed_by": ["interrupt handlers", "R14f_wrong_zip"]},
   "needs_consent_prompt": {"default": false, "set_by": ["R14c_zip_success_damaged"], "consumed_by": ["R10_consent_prompt"]},
   "isReadyForTurn2": {"default": false, "set_by": ["indicate_ready_for_next_step"], "consumed_by": ["gate card_replacement"]},
   "last4CardDigits": {"default": "", "set_by": ["_initialize_session_for_dev"], "consumed_by": ["R10_consent_prompt"]},
   "card_replacement_submitted": {"default": false, "set_by": ["replace_debit_card"], "consumed_by": ["cancel and out-of-scope handling"]},
   "prerequisite_zipcode_failed": {"default": false, "set_by": ["replace_debit_card"], "consumed_by": ["R12_prerequisite_failed"]},
   "disclosure_read": {"default": false, "set_by": ["R14g_submitted"], "consumed_by": []},
   "out_of_scope_response": {"default": false, "set_by": ["out_of_scope_handling"], "consumed_by": []},
   "cancel_model_text": {"default": null, "set_by": ["handle_cancel_card_replacement_request"], "consumed_by": ["callback after the cancel tool"]},
   "end_session_reason": {"default": null, "set_by": ["democard_end_conversation"], "consumed_by": ["R13_session_end"]},
   "end_session_is_escalated": {"default": null, "set_by": ["democard_end_conversation"], "consumed_by": ["R13_session_end"]},
   "init_session_end": {"default": false, "set_by": ["democard_end_conversation"], "consumed_by": ["R13_session_end"]}},
 "provenance": "seen_in_code"}
```

## 9. Canned utterance templates

```json
{"kind": "templates", "templates": {
   "first_zip_prompt": {"text": "To replace your {issue_reason} debit card, can you please confirm your ZIP code?", "after": "R7_first_zip_prompt", "ground": {"issue_reason": "state"}},
   "readback_zip": {"text": "Just to be sure, I heard {user_zip}. Is that the correct zip code?", "after": "save_zip_code", "ground": {"user_zip": "state"}},
   "zip_retry": {"text": "Sorry, I could not catch the zipcode you provided, can you please say that again?", "after": "validate_zip_code", "ground": {}},
   "consent_prompt": {"text": "Would you like me to submit the card replacement request for your card ending in {last4CardDigits} now?", "after": "indicate_ready_for_next_step", "ground": {"last4CardDigits": "state"}},
   "submitted_damaged": {"text": "Your card replacement request has been submitted successfully! {details} Is there anything else I can help you with?", "after": "replace_debit_card", "ground": {}},
   "goodbye": {"text": "Thank you for calling Example Bank. Have a great day", "after": "democard_end_conversation", "ground": {}}},
 "variants": {"readback_zip": ["You entered {user_zip}. Is that correct?"]}, "provenance": "seen_in_code"}
```

## 10. Point inventory

| Point id | Step | Artifact | Author | Check kind | Allowed sources | Pseudocode element |
|---|---|---|---|---|---|---|
| zip_collection.selection | zip_collection | tool selection | model | deterministic / judgment | customer utterance (digit count), workflow rules | step zip_collection |
| zip_collection.save_zip_code.args.zip_code | zip_collection | argument | model | grounding | customer_utterance.current, rule exactly_5_digits_as_spoken | tool save_zip_code inputs.zip_code |
| zip_collection.silence | zip_collection | model speech after save_zip_code | model | pattern | none (code speaks) | step zip_collection |
| zip_collection.omission | zip_collection | missing required call | model | deterministic | customer utterance | step zip_collection |
| save_zip_code.effects | zip_collection | state write user_zip | code | deterministic | arguments | tool save_zip_code |
| callback.readback_zip | zip_collection | canned utterance | code | pattern | state.user_zip | template readback_zip |
| zip_confirmation.selection | zip_confirmation | tool selection | model | judgment | customer utterance, workflow rules | step zip_confirmation |
| zip_confirmation.validate_zip_code.args.zip_code | zip_confirmation | argument | model | grounding | state.user_zip, agent_utterance.previous | tool validate_zip_code inputs.zip_code |
| zip_confirmation.silence | zip_confirmation | model speech after non-SUCCESS validation | model | pattern | none (code speaks) | step zip_confirmation |
| zip_confirmation.omission | zip_confirmation | missing required call | model | deterministic | customer utterance | step zip_confirmation |
| validate_zip_code.output | zip_confirmation | tool result | code | deterministic | arguments, external zip_on_file, state.zip_validation_retry_count | rule ZIP_MATCH |
| validate_zip_code.effects | zip_confirmation | chained call / state writes | code | deterministic | tool result | callback R14c_zip_success_damaged |
| callback.zip_retry | zip_confirmation | canned utterance | code | pattern | tool result | template zip_retry |
| callback.consent_prompt | card_replacement | canned utterance | code | pattern | state.last4CardDigits | template consent_prompt |
| card_replacement.selection | card_replacement | tool selection | model | judgment | customer utterance, workflow rules | step card_replacement |
| card_replacement.silence | card_replacement | model speech in a tool-call turn | model | pattern | none | step card_replacement |
| card_replacement.end_reason | card_replacement | reason and escalation flag | model | deterministic | end_reasons table, what happened | tool democard_end_conversation inputs.reason |
| card_replacement.omission | card_replacement | missing required call | model | deterministic | customer utterance | step card_replacement |
| replace_debit_card.output | card_replacement | tool result | code | deterministic | state.is_zip_verified | rule SUBMIT_MOCK |
| callback.submitted_damaged | card_replacement | canned utterance | code | pattern | tool result | template submitted_damaged |
| interrupt.selection | interrupt | global handler choice | model | judgment | customer utterance, workflow rules | step interrupt |
| interrupt.handle_cancel_card_replacement_request.args.stage | interrupt | argument | model | grounding | enum, tool next_steps history | tool handle_cancel_card_replacement_request inputs.stage |
| interrupt.end_reason | interrupt | reason and escalation flag | model | deterministic | end_reasons table | tool democard_end_conversation inputs.reason |

## 11. Open questions and inferred elements

- Step `interrupt` is inferred from the static instructions; the materials do not show how the platform resolves a conflict between an interrupt and the injected step in the same turn.
- Rule `R14e_zip_system_error`: the transfer sentence for SYSTEM_ERROR is inferred; the materials show only the reason string.
- `zip_on_file` is external (mailing address API). Without a ground-truth file every `validate_zip_code.output` point is unverifiable.
- The DEV build's `replace_debit_card` is mocked; in production the API may fail, so `replace_debit_card.output` must be re-derived from the production code before use.

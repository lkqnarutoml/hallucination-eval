# Workflow pseudocode: <AGENT NAME>

<!-- Written by the architect role from the materials only. Never from trajectories. -->
<!-- Every element: pseudocode text, then a fenced json contract. Provenance: seen_in_code | inferred | unknown. -->

Build or version: <what the materials describe, e.g. "DEV build from the console export, January">
Materials read: <list of files>
Reconciled with: <earlier pseudocode or docs, or "none">

## 0. Conventions

- `S` is the session state (variables shared by every agent and turn).
- `CODE` marks decisions made by callbacks or tools (deterministic). `MODEL` marks decisions made by the LLM.
- `say "..."` is customer-facing text. `CALL tool(args)` executes a tool.
- Input classes used in `decide` tables: digits5, digits_other, no_digits, affirmative, negative, repeat_request,
  agent_request, cancel_request, out_of_scope, no_input, other. Extend the list if the workflow needs more.

## 1. Agents and routing

<pseudocode: which agent starts, how control moves between agents (rules, variables, transfers)>

```json
{"kind": "routing", "root_agent": "<name>", "rules": [{"when": "<condition on S>", "to": "<agent>", "author": "code"}],
 "agents": {"<agent>": {"tools": ["<tool>", "..."], "sub_agents": [], "prompt_file": "<path>"}}, "provenance": "seen_in_code"}
```

## 2. Turn skeleton (per agent)

<pseudocode of one turn: callbacks before the model, the single model call, callbacks after, tool loop>

```json
{"kind": "turn_skeleton", "agent": "<agent>", "before_model": ["<rule id>", "..."], "after_model": ["..."],
 "model_decides_only_when": "<condition>", "provenance": "seen_in_code"}
```

## 3. Flows, gates and steps

<pseudocode: ordered steps per flow and the gate of each step>

```json
{"kind": "flows", "flows": {"<flow>": ["<step>", "..."]}, "gates": {"<step>": "<state predicate>"},
 "default_flow": "<flow or null>", "step_source": "<variable holding the injected step text, or null>", "provenance": "seen_in_code"}
```

### Step: <step id>

<pseudocode of what the model must do at this step given each input class, what it must not do, what code does after>

```json
{"kind": "step", "name": "<step>", "flows": ["<flow>"], "gate": "<predicate>", "author": "model",
 "context": {"customer_utterance": "current", "state": ["<var>"], "history": "full"},
 "decide": {"digits5": {"call": "<tool>", "args": {"<param>": "$customer.digits"}},
            "other": {"call": "<tool>", "check": "judgment"}},
 "must_not": {"call": ["<tool>"], "speak_after": ["<tool>"], "speak_when": "<condition or null>"},
 "then": {"<tool>": {"say": "<template with {placeholders}>", "ground": {"<placeholder>": "state"},
                     "effects": {"<var>": "<value or +1 or null>"}, "next_call": "<tool or null>"}},
 "provenance": "seen_in_code"}
```

## 4. Tool contracts

### Tool: <tool name>

<pseudocode of the tool body: inputs, external calls, state effects, return values>

```json
{"kind": "tool", "name": "<tool>", "author": "model", "agents": ["<agent>"], "flows": ["<flow>"],
 "inputs": {"<param>": {"type": "digits|string|enum|bool", "ground_in": "customer_utterance.current|state.<var>|agent_utterance.previous|enum",
                        "rule": "<e.g. exactly_5_digits_as_spoken>", "enum": []}},
 "outputs": {"status": ["SUCCESS", "..."]}, "effects": {"<var>": "<expr>"},
 "deterministic_rule": {"id": "<rule id or null>", "needs": ["<external data, e.g. zip_on_file>"], "description": "<rule>"},
 "preconditions": {"step": "<step or null>", "state": "<predicate or null>"}, "provenance": "seen_in_code"}
```

## 5. Callback rules (code-authored points)

<pseudocode of each rule in evaluation order: condition, customer text, state writes, chained calls>

```json
{"kind": "callback_rule", "id": "R<n>", "agent": "<agent>", "when": "<condition>", "author": "code",
 "say": "<template or null>", "ground": {"<placeholder>": "state"}, "effects": {}, "next_call": null, "escalate": null,
 "provenance": "seen_in_code"}
```

## 6. Deterministic rules

```json
{"kind": "rule", "id": "<rule id>", "description": "<exact comparison>", "needs": ["<external data>"],
 "thresholds": {"<name>": 2}, "provenance": "seen_in_code"}
```

## 7. End and transfer reasons

```json
{"kind": "end_reasons", "model_issued": [{"reason": "<text>", "escalated": true, "when": "<condition>"}],
 "code_issued": [{"reason": "<text>", "escalated": true, "rule": "R<n>"}], "provenance": "seen_in_code"}
```

## 8. State variables

```json
{"kind": "variables", "variables": {"<var>": {"default": null, "set_by": ["<tool or rule>"], "consumed_by": ["<gate or rule>"]}},
 "provenance": "seen_in_code"}
```

## 9. Canned utterance templates

```json
{"kind": "templates", "templates": {"<name>": {"text": "<template>", "after": "<tool or rule>", "ground": {"<placeholder>": "state"}}},
 "variants": {"<name>": ["<alternative wording seen in another build>"]}, "provenance": "seen_in_code"}
```

## 10. Point inventory

| Point id | Step | Artifact | Author | Check kind | Allowed sources | Pseudocode element |
|---|---|---|---|---|---|---|
| <step>.selection | <step> | tool selection | model | deterministic / judgment | customer utterance, state, workflow rules | step <step> |
| <step>.<tool>.args.<param> | <step> | argument | model | grounding | <sources> | tool <tool> |
| <tool>.output | - | tool result | code | deterministic | arguments, external data | rule <id> |
| callback.<name> | - | canned utterance | code | pattern | state | template <name> |

## 11. Open questions and inferred elements

- <every element tagged inferred or unknown, with what evidence would settle it>

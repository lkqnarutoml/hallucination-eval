# Pseudocode format

The architect writes one file, `workflow_pseudocode.md`, from the materials only. It is the contract every later
role reads. Start from `assets/pseudocode_template.md`.

## Shape of the file

Each element appears twice: once as pseudocode a person can read, once as a fenced `json` block a script can
read. The JSON blocks are the machine contract; the prose exists so a reviewer can tell at a glance whether the
contract is right.

    ### Step: zip_collection

    GATE: not S.user_zip
    The model reads the customer's last message and counts digits.
    5 digits  -> CALL save_zip_code(those digits)
    otherwise -> CALL indicate_invalid_zipcode()
    CODE then speaks the read-back; the model must stay silent.

    ```json
    {"kind": "step", "name": "zip_collection", ...}
    ```

Keep one JSON object per block, valid JSON (double quotes, no comments, no trailing commas). Anything the
format cannot express goes in prose beneath the block, and the element is tagged `"provenance": "inferred"`.

## Required sections

0. Header: build or version described by the materials, files read, what it was reconciled with.
1. Conventions: state symbol, CODE/MODEL marking, the input classes in use.
2. Agents and routing (`"kind": "routing"`).
3. Turn skeleton per agent (`"kind": "turn_skeleton"`).
4. Flows, gates and steps (`"kind": "flows"`, then one `"kind": "step"` per step).
5. Tool contracts (`"kind": "tool"`).
6. Callback rules (`"kind": "callback_rule"`), in evaluation order.
7. Deterministic rules (`"kind": "rule"`).
8. End and transfer reasons (`"kind": "end_reasons"`).
9. State variables (`"kind": "variables"`).
10. Canned utterance templates (`"kind": "templates"`).
11. Point inventory (a Markdown table, see below).
12. Open questions: every inferred or unknown element and what evidence would settle it.

## Two tags that decide how a finding is classified

`author`
: `model` when the LLM produced the artifact, `code` when a callback or tool did. Only model-authored artifacts
  can be hallucinations. Code-authored mismatches are pipeline findings. Getting this wrong is the single most
  expensive mistake in the file, so when a materials file shows a callback returning text or issuing a tool
  call, say so explicitly in the contract (`"author": "code"`).

`provenance`
: `seen_in_code` when a materials file states it; `inferred` when you concluded it from surrounding code;
  `unknown` when the materials do not show it (an API path, a threshold that lives elsewhere). Everything
  inferred or unknown is repeated in section 11 so the auditor can check it and the evaluator can discount it.

## Input classes

Use these names in `decide` tables so the evaluator and any compiled checker agree:
`digits5`, `digits_other`, `no_digits`, `affirmative`, `negative`, `repeat_request`, `agent_request`,
`cancel_request`, `out_of_scope`, `no_input`, `other`. Add a class only if the workflow needs it, and define it
in section 1.

## Grounding sources

Every tool input declares where its value may come from, with one of these `ground_in` values:
`customer_utterance.current`, `customer_utterance.any`, `agent_utterance.previous`, `state.<var>`,
`tool_result.<tool>.<field>`, `enum`, `external.<name>` (data not in the log, such as an address on file),
`none` (the tool takes no meaningful input). `references/grounding_sources.md` explains what each one licenses.

## The point inventory

A workflow point is one place where an artifact is produced. The table has one row per point:

| Point id | Step | Artifact | Author | Check kind | Allowed sources | Pseudocode element |

Point ids follow a naming convention so `aggregate_findings.py --mdd-view` can group them:

    <step>.selection                  which tool the model chose at that step
    <step>.omission                   a required tool the model did not call
    <step>.<tool>.args.<param>        one argument of one call
    <tool>.output                     the value a deterministic tool returned
    <tool>.effects                    state writes or chained calls after a tool result
    <step>.silence                    a rule forbidding model speech
    <step>.end_reason                 the reason and escalation flag of an ending call
    <step>.speech                     a fact the model stated to the customer
    callback.<name>                   a canned utterance authored by code

Check kinds: `deterministic` (an expected value follows from a rule), `pattern` (a template must match),
`grounding` (a value must appear in an allowed source), `judgment` (a person or the model must decide, for
example whether a reply was affirmative).

## Compile, validate, render

`python scripts/build_spec.py compile workflow_pseudocode.md --out workflow_spec.json --report spec_report.md --inventory materials_inventory.json`
parses every fenced json block, the point inventory and the open questions, checks cross-references (steps -> tools,
tools -> agents, rules, templates, variables, points -> elements, provenance and author on every element) and writes
the machine contract. `build_spec.py render` produces `architecture.md` (tree, turn skeletons, one Mermaid state
machine per flow, who decides what, state bus, point inventory); see `references/architecture_views.md`.
A step that is a global interrupt handler rather than a flow position carries `"global": true`.
`references/example_democard_excerpt.md` is a complete excerpt that compiles.

## What does not belong in this file

Observations from trajectories. The architect never opens a log. If a rule is unclear from the materials, mark
it `inferred` or `unknown` and write the open question; do not resolve it by looking at what the agent did,
because a consistent hallucination would then become part of the specification.

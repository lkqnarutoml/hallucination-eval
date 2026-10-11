# Role: checker compiler (deterministic points of the pseudocode -> a Python checker)

> CRITICAL: this file is your complete instruction set. Read only what is listed below. Do NOT read conversation
> content to derive rules; you may run the checker over batches and read its output. You cannot ask the user; put
> questions in the FINALIZE block.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `{{SKILL_DIR}}` | folder of the hallucination-eval skill |
| `{{RUN_DIR}}` | folder of this run |
| `{{PYTHON}}` | the Python command that works on this machine |
| `{{PSEUDOCODE_PATH}}` | `workflow_pseudocode.md` (approved by the spec auditor) |
| `{{SPEC_JSON}}` | compiled `workflow_spec.json` |
| `{{CHECKER_TEMPLATE}}` | `assets/checker_template.py` to copy and fill |
| `{{CHECKER_OUT}}` | where to write the checker module, e.g. `RUN_DIR/checker_<agent>.py` |
| `{{BATCHES_DIR}}` | the batch files to run the checker over |
| `{{CHECKER_RESULTS_DIR}}` | where `run_checker.py` writes `batch_NNN.json` results |
| `{{COMPILER_REPORT_OUT}}` | where to write your `checker_report.md` |

## You may read

`{{PSEUDOCODE_PATH}}`, `{{SPEC_JSON}}`, `{{CHECKER_TEMPLATE}}`, `{{SKILL_DIR}}/scripts/halu_common/*.py` (helpers you may
import), `{{SKILL_DIR}}/references/output_schema.md`, `{{SKILL_DIR}}/references/grounding_sources.md`, the checker
results you produce. Batch files only through the checker (and one batch to test-load if a rule crashes).

## Task

Copy `{{CHECKER_TEMPLATE}}` to `{{CHECKER_OUT}}` and fill its RULES section from the deterministic and pattern points
of the spec. Do not touch the engine below the RULES section unless a rule cannot be expressed with it; if you must,
document the change in the report.

## Procedure

1. Read `{{SPEC_JSON}}`. Fill, citing the element for each entry in a comment:
   - `TOOL_CATALOG`: every tool with the agents and flows that may use it, from `routing.agents` and `tools[*].flows`;
     `author` from the tool contract.
   - `ARGUMENT_RULES`: every model-authored input with `ground_in` `customer_utterance.current` (`source: customer_current`,
     `exact_len` from the rule) or `state.<var>` (`source: state:<var>`). Skip `enum`, `external`, `agent_utterance.previous`
     unless you add an engine branch for them (document it).
   - `OUTPUT_RULES`: one function per tool with a `deterministic_rule`, computing the expected status from args, state
     and `truth` (ground truth); return an unverifiable reason when the external data is missing.
   - `CANNED_TEMPLATES`: every template with its `after` tool.
   - `SILENCE_AFTER`: from steps' `must_not.speak_after` and `speak_when` (statuses after which the model must not speak).
   - `CHAINED_CALLS`: from callback rules with `next_call`, keyed by the tool and status that trigger them.
   - Set `SKILL_DIR` at the top so `halu_common` imports from `{{SKILL_DIR}}/scripts` (absolute path is fine here).
2. Load test: `{{PYTHON}} {{CHECKER_OUT}} {{BATCHES_DIR}}/batch_001.json` must print one line per conversation.
3. Run everything: `{{PYTHON}} {{SKILL_DIR}}/scripts/run_checker.py --checker {{CHECKER_OUT}} --batches {{BATCHES_DIR}} --out {{CHECKER_RESULTS_DIR}}`.
   Exit 1 means a conversation raised inside the checker: read the traceback in the result file, fix the rule, rerun.
4. Spot-check three findings from the results against the pseudocode (not against your sense of the data): each must
   name the element and carry locators from the events.
5. Write `{{COMPILER_REPORT_OUT}}`: the points the checker covers (point id -> RULES entry), the points left to the
   evaluators (judgment, speech, omissions, enum reasons), engine changes if any, run statistics from
   `{{CHECKER_RESULTS_DIR}}/index.json`, and known limitations (e.g. state emulated from tool effects).

## Rules

- Standard library plus `halu_common` only; no third-party imports; runs unchanged on Windows.
- The checker never decides judgment points. When a rule needs a customer-intent reading, leave it out.
- Bump `CHECKER_VERSION` when rules change; it is recorded in every result file.

## FINALIZE

```
--- FINALIZE ---
role: checker_compiler
status: done | failed
outputs:
  - {{CHECKER_OUT}}
  - {{CHECKER_RESULTS_DIR}}/index.json
  - {{COMPILER_REPORT_OUT}}
counts: points_covered=<n> batches=<n> deterministic_findings=<n> conversation_errors=<n>
warnings:
  - <one per line, or none>
questions_for_orchestrator:
  - <one per line, or none>
--- END ---
```

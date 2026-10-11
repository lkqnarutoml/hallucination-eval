# Role: architect (code -> pseudocode, tree and architecture views)

> CRITICAL: this file is your complete instruction set. Do not open `SKILL.md`, other role files, or anything not
> listed under "You may read". Do NOT open any trajectory, log, export or findings file: a spec derived from observed
> behaviour would absorb consistent hallucinations. You cannot ask the user; put questions in the FINALIZE block.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `{{SKILL_DIR}}` | folder of the hallucination-eval skill (scripts, references, assets) |
| `{{RUN_DIR}}` | folder of this evaluation run; every output goes here |
| `{{PYTHON}}` | the Python command that works on this machine (`python`, `py -3` or `python3`) |
| `{{TARGET_AGENT}}` | name of the agent under evaluation |
| `{{MATERIALS}}` | the material paths (code, callbacks, prompts, packaging, variables), one per line or semicolon-separated |
| `{{INTRO_DOCS}}` | documents that introduce the workflow and how the agents work together, or `none` |
| `{{EXISTING_PSEUDOCODE}}` | an earlier pseudocode or architecture write-up to reconcile with, or `none` |
| `{{INVENTORY_JSON}}` | `materials_inventory.json` produced by `scripts/inventory_materials.py` |
| `{{INVENTORY_SUMMARY}}` | `materials_summary.md`, the readable form of the inventory |
| `{{MATERIALS_TREE}}` | `materials_tree.md`, the agent-to-tool tree rendered from the inventory |
| `{{REVIEW_NOTES}}` | the spec auditor's review to address (second round), or `none` |
| `{{PSEUDOCODE_OUT}}` | where to write `workflow_pseudocode.md` |
| `{{SPEC_JSON_OUT}}` | where `build_spec.py compile` writes `workflow_spec.json` |
| `{{SPEC_REPORT_OUT}}` | where `build_spec.py compile` writes `spec_report.md` |
| `{{ARCHITECTURE_OUT}}` | where `build_spec.py render` writes `architecture.md` |
| `{{ARCHITECT_REPORT_OUT}}` | where to write your `architect_report.md` |

## You may read

- The materials: `{{MATERIALS}}`; the introduction documents: `{{INTRO_DOCS}}`; the earlier pseudocode: `{{EXISTING_PSEUDOCODE}}`.
- `{{INVENTORY_SUMMARY}}`, `{{MATERIALS_TREE}}`, `{{INVENTORY_JSON}}` (data about the materials; it never interprets behaviour).
- `{{SKILL_DIR}}/references/pseudocode_format.md` (the contract you must follow), `{{SKILL_DIR}}/references/architecture_views.md`,
  `{{SKILL_DIR}}/references/grounding_sources.md`, `{{SKILL_DIR}}/references/hallucination_taxonomy.md` (to know what the points are for),
  `{{SKILL_DIR}}/references/example_democard_excerpt.md` (a finished excerpt), `{{SKILL_DIR}}/assets/pseudocode_template.md`.
- Review notes to address: `{{REVIEW_NOTES}}`.

## You must not open

Any file under a runs, results, logs, trajectories or findings folder; any xlsx, csv, jsonl or events file; `SKILL.md`; other roles.

## Task

Turn the code and the architecture of `{{TARGET_AGENT}}` into `workflow_pseudocode.md`: literate pseudocode a
person can read, with one fenced JSON contract per element that scripts can read, plus the point inventory. Then
compile it and render the architecture views (tree, turn skeleton, flow state machines, who-decides-what, state bus).

## Procedure

1. Orient: read `{{INVENTORY_SUMMARY}}` and `{{MATERIALS_TREE}}`. Note every agent, its callbacks by stage, its tools,
   the functions no agent binds, the prompt files, the guardrails and the declared variables (from `app.json`
   `variableDeclarations` or `variables.json`). When the materials are a CX Agent Studio export, the agent definition
   files (`agents/<name>/<name>.json`) name the tools by resource id; the inventory has already resolved them to
   display names, so use the names in the summary. Read `{{INTRO_DOCS}}` for the intended
   workflow. If `{{EXISTING_PSEUDOCODE}}` is not `none`, read it as a map, but derive every element from the code.
2. Read `references/pseudocode_format.md` fully, then the excerpt. Copy `assets/pseudocode_template.md` to
   `{{PSEUDOCODE_OUT}}` and fill it section by section:
   - Section 1 routing: root agent, handoff rules (condition, target, author code), every agent with its tools,
     sub-agents and prompt file. Source: packaging yaml / snapshot / handoff-rule files.
   - Section 2 turn skeleton per agent: what the before-agent, before-model and after-model callbacks do, in order,
     and the exact condition under which the model is called at all. Source: the callback files.
   - Section 3 flows, gates, steps: from the flow engine (the callback that injects step instructions) and from the
     instruction blocks. For each step: gate predicate, `decide` table by input class (use the standard classes),
     `must_not` (calls, speak_after, speak_when), `then` (what code says or calls after each tool, with effects).
     Global interrupt handlers from the static instructions become a step with `"global": true`.
   - Section 4 tool contracts: one per tool the model can call and per tool code chains. Params with `ground_in`
     and `rule`, outputs (the status literals returned), effects (every `context.state[...] =` write), deterministic
     rule (the exact comparison, threshold, external data it needs), preconditions, and `author` (`model`, `code`,
     `both`).
   - Section 5 callback rules in evaluation order, `author` `code`: condition, canned text with placeholders, effects,
     chained call, escalation reason.
   - Sections 6 to 9: deterministic rules, end and transfer reasons (model-issued vs code-issued), variables with
     defaults / writers / readers, canned utterance templates (with variants seen in other builds).
   - Section 10 point inventory: one row per place an artifact is produced, naming convention from the format page.
   - Section 11 open questions: every `inferred` or `unknown` element and what evidence would settle it.
3. Tag every element with `provenance` (`seen_in_code` only when a file shows it) and the right `author`. When a
   callback returns text or a function call, that artifact is `code`. Getting `author` wrong is the most expensive
   mistake in this file.
4. Compile until clean:
   `{{PYTHON}} {{SKILL_DIR}}/scripts/build_spec.py compile {{PSEUDOCODE_OUT}} --out {{SPEC_JSON_OUT}} --report {{SPEC_REPORT_OUT}} --inventory {{INVENTORY_JSON}}`
   Fix every error. Fix warnings or explain each remaining one in your report.
5. Render the views:
   `{{PYTHON}} {{SKILL_DIR}}/scripts/build_spec.py render {{SPEC_JSON_OUT}} --out {{ARCHITECTURE_OUT}} --inventory {{INVENTORY_JSON}}`
   Read the result once: the tree must match the materials tree; every flow diagram must read like the code.
   Add other views (a demo-turn sequence diagram, a filler table) under a "Views" heading in the pseudocode file if
   they help; they never override the JSON.
6. If `{{REVIEW_NOTES}}` is not `none`: address every issue in it, recompile, re-render, and list each change.
7. Write `{{ARCHITECT_REPORT_OUT}}`: materials read; agents and flows covered fully / partially / not at all;
   elements tagged inferred or unknown and why; author-tag decisions that needed judgment; remaining warnings and
   why they are acceptable; changes made for the review; questions for the orchestrator.

## Rules

- Never invent a rule you cannot point at. If the materials do not show a threshold, an API path or a message, tag
  the element `unknown`, write the open question, and leave the value null.
- Quote the code in the prose (the exact comparison, the exact sentence); the JSON carries the same value.
- One JSON object per fenced block; valid JSON (double quotes, no comments, no trailing commas).
- Keep the file under about 60k characters; a large agent gets several flows but one file.

## Quality gate before FINALIZE

`build_spec.py compile` exits 0. `{{ARCHITECTURE_OUT}}` exists. Every step has a `.selection` point; every
model-authored input has an `.args` point; every deterministic tool has an `.output` point.

## FINALIZE

```
--- FINALIZE ---
role: architect
status: done | failed | blocked
outputs:
  - {{PSEUDOCODE_OUT}}
  - {{SPEC_JSON_OUT}}
  - {{SPEC_REPORT_OUT}}
  - {{ARCHITECTURE_OUT}}
  - {{ARCHITECT_REPORT_OUT}}
counts: steps=<n> tools=<n> callback_rules=<n> points=<n> inferred_or_unknown=<n> warnings=<n>
warnings:
  - <one per line, or none>
questions_for_orchestrator:
  - <one per line, or none>
--- END ---
```

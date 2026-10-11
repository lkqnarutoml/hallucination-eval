---
name: hallucination-eval
description: "Evaluates a tool-using conversational agent for hallucinations: first converts its code, prompts and agent-to-tool tree into literate pseudocode plus architecture views (tree, flow state machines, who-decides-what), then judges every trajectory point by point against that contract with isolated subagent roles (architect, normalizer, evaluators, auditors, reporter). Finds unsupported tool selections, arguments, outputs, branches, end reasons, silence violations and omissions; separates code-authored pipeline mismatches; outputs one JSON record per conversation with rationale and evidence locators plus an audited summary with MDD-style A/B/C/D views. Use when asked to check trajectories, conversation logs, tool-call logs, BigQuery exports or simulator runs for hallucination, grounding, unsupported arguments, DeepEval-style tool use, DemoCard ZIP checks, or to derive pseudocode and a tree from an agent's code. Not for fairness, toxicity, adversarial testing, writing model documentation or running simulators."
license: Apache-2.0
compatibility: "Python 3.10+ (openpyxl only for xlsx). Any Agent-Skills host: VS Code GitHub Copilot (Windows or other), Claude Code, Codex. A subagent tool enables multi-agent mode; without one the skill runs single-agent. No network access."
metadata:
  version: "0.4.0"
  author: model-validation
---

# hallucination-eval: orchestrator contract

You are the **orchestrator**. You never derive pseudocode, never judge a conversation, never write a finding and never
repair a role's output. You run scripts, dispatch the roles in `roles/` as isolated subagents, check gates, keep
`run_manifest.json`, and talk to the user. All commands are in `references/cli-cheatsheet.md`; treat scripts as
black boxes (no `--help`, no reading their source).

## What a hallucination is here

Anything the model said, any argument it passed, any tool it picked, any branch it took, that none of the six
reference points supports: the customer's words and history, the tool catalogue, earlier arguments, tool results,
session state, the workflow rules. Code-authored artifacts (callback text, tool results, state writes) can only be
pipeline findings. Missing evidence makes a point unverifiable, never a finding. Details:
`references/hallucination_taxonomy.md`.

## Roles and contamination rules

| Role (prompt) | Produces | May read | Must not open | Why separate |
|---|---|---|---|---|
| architect (`roles/architect.md`) | `workflow_pseudocode.md`, `workflow_spec.json`, `architecture.md`, `architect_report.md` | materials, inventory, tree, intro docs, earlier pseudocode | any trajectory or log | a spec built from logs absorbs consistent hallucinations |
| spec_auditor (`roles/spec_auditor.md`) | `spec_review.md` with a verdict | materials, pseudocode, spec, architecture | trajectories | checks author/provenance tags against source lines |
| normalizer (`roles/normalizer.md`) | `conversations.json`, batches, column-map proposal, `normalizer_report.md` | trajectories, column map, ground truth | pseudocode, materials, findings | data preparation without judgment |
| checker_compiler (`roles/checker_compiler.md`) | `checker_agent.py`, `checker_out/`, `checker_report.md` | pseudocode, spec, template | conversation content (except through the checker) | deterministic points without rule drift |
| evaluator (`roles/evaluator.md`, one per batch) | `findings/batch_NNN.json`, `notes/batch_NNN.md` | pseudocode, one batch, its checker output | source code, spec and architecture (duplicates), other batches, other findings | no ad-hoc rule re-derivation, no anchoring, smallest context |
| auditor (`roles/auditor.md`, one per batch) | `audit/verdicts_batch_NNN.json`, `audit/batch_NNN.md` | blind payload, pseudocode | evaluator rationale (withheld), spec, other batches | verdict from evidence first |
| reporter (`roles/reporter.md`) | `hallucination_findings.json`, `aggregate.json`, `summary_tables.md`, `summary.md`, `reporter_report.md` | verified batches, scripts, spec, manifest | raw trajectories | numbers come from scripts only |

You read only: the manifest, role reports, `materials_summary.md`, `materials_tree.md`, `spec_report.md`,
`spec_review.md`, `normalize_report.md`, `summary.md`, FINALIZE blocks. Never batches, findings bodies, materials or
logs: your context must stay small enough for hundreds of conversations and for the user.

## Step 0: environment perception (before anything else)

1. Find the Python command (`python`, `py -3`, `python3`; version 3.10+) and whether `openpyxl` imports.
2. Detect the subagent mechanism of this host and write `RUN_DIR/runtime/host.md` as described in
   `references/subagent_dispatch.md`; post the same text in chat under `## Subagent operations manual`, including the
   invocation template with the slots `{{SUBAGENT_NAME}}`, `{{PROMPT_PATH}}`, `{{MODEL}}` filled by example.
   VS Code Copilot: the run-subagent (`agent`) tool; Claude Code: the Agent tool; none: single-agent fallback.
3. Detect whether a structured question UI exists; use it for the setup questions when it does.
4. Fix `SKILL_DIR` (this folder), `INPUT_DIR` (`<workspace>/input`, one subfolder per kind: materials, trajectories,
   ground_truth, docs, config) and `OUTPUT_DIR` (`<workspace>/output`), unless the user names others. `RUN_DIR` is
   `OUTPUT_DIR/<RUN_ID>` with `RUN_ID = <UTC yyyymmddThhmmssZ>-<agent>`; the final deliverables sit at its top, the
   intermediate products in subfolders (`references/folders.md`). One RUN_ID per evaluation; resume reuses it.

## Step 1: scan the input folder, then ask once

Run `PY SKILL_DIR/scripts/manifest.py scan input` and show the result. If the folder is missing or a kind is
empty, ask the user to place the files by the convention (materials, trajectories, ground_truth, docs, config)
rather than collecting paths one by one. Then ask only what the scan and the prompt do not settle, from
`assets/questions.md`: target agent and scope, which build the materials and trajectories come from, external
ground truth, scale and sampling, privacy confirmation. Three questions are always asked, first, unless the
user's prompt already answers them: whether the P7 audit is included (yes: precision and miss rate are measured;
no: the run ends after P6 and the report is marked UNAUDITED), which model runs the P6 evaluators, and, only when
the audit is included, which model runs the P7 auditors; each model a single choice from GPT-5.5, Claude Opus 4.8,
Claude Opus 4.7, Claude Sonnet 5.0 (structured question UI when the host has one). Record them with `--model`,
`--audit-model` and `--no-audit`. Then:

```
PY SKILL_DIR/scripts/manifest.py init --target "<agent>" --input input --output output --model "<P6 model>" [--audit-model "<P7 model>" | --no-audit]
PY SKILL_DIR/scripts/manifest.py paths RUN_DIR
```

Copy the printed paths into every later command. If a run folder for this evaluation already exists under
`output/`, run `manifest.py next RUN_DIR` and resume there (`references/scaling.md`).

## The run is a state machine

`run_manifest.json` holds the state: eleven phases in a fixed order, each `pending`, `in_progress`, `done`,
`skipped` or `failed`; per-batch states under `evaluate` and `audit`; one dispatch record per subagent instance.
Transitions are guarded by `scripts/manifest.py`, not by your judgment:

- `set-phase PHASE done` is refused when a prerequisite phase is not done or skipped, or when the phase's artifacts
  are missing or invalid (the compiled spec has errors, the spec review says REVISE, a batch has no findings file,
  the final file lacks its meta). `gate PHASE` runs the same checks without changing anything. `--force` needs a
  `--note` reason and is written to the log; use it only on the user's explicit decision.
- `skipped` needs a `--note` reason (e.g. no tabular export, below the checker threshold).
- `set-phase normalize done` registers every batch of `batches/index.json` as pending for evaluate and audit;
  `evaluate` and `audit` cannot complete until every registered batch is `done`.
- `next` prints the first open phase and any subagent still running.

## Canonical plan (phases, subagents, gates)

Execute in this order; never skip ahead to "see what happens". Each phase: harness command from the cheatsheet ->
`manifest.py dispatch` -> RUN -> FINALIZE -> `manifest.py finalize` -> gate -> `manifest.py set-phase ... done`.
Never write a role's product yourself.

| Phase | Who | Gate (exit 0) | On gate failure |
|---|---|---|---|
| P1 inventory | orchestrator runs `inventory_materials.py` and `build_spec.py tree` | summary lists agents | ask user for `agents.json` |
| P2 pseudocode | architect | `build_spec.py compile` and `render` | re-dispatch architect with the compile report |
| P3 spec_review | spec_auditor | `VERDICT: APPROVED*` in `spec_review.md` | re-dispatch architect with `--inject-file REVIEW_NOTES=spec_review.md`, then P3 again; max two rounds |
| P4 normalize_inspect | normalizer (mode inspect; tabular exports only) | proposal file exists | ask the user to confirm the column map; save `column_map.json` |
| P4 normalize | normalizer (mode normalize) | `conversations.json` + `batches/index.json` exist | read `normalizer_report.md`; unusable inputs go back to the user |
| P5 checker_compile / checker_run | checker_compiler (only above `checker_threshold` conversations) | `run_checker.py` exits 0 | re-dispatch with the traceback |
| P6 evaluate | one evaluator per batch, parallel | before dispatch `context_budget.py RUN_DIR --role evaluator` exits 0; after, `validate_findings.py --batch --pre-audit` per batch | over budget: re-split or a stricter diet; failed: re-dispatch that batch |
| P7 audit (only when included at setup; otherwise `init --no-audit` marks it skipped and no audit batches exist) | `make_audit_payload.py payload`, `context_budget.py --role auditor`, one auditor per batch, parallel, then `apply` + validate | all exit 0 | re-dispatch that batch's auditor |
| P8 report | reporter | final validate + `summary.md` exists | re-dispatch reporter |

Mark batches with `manifest.py set-batch RUN_DIR evaluate <id> done` (and `audit`). `manifest.py next` tells you
where you are after any interruption.

## Subagent lifecycle (every instance, every host)

```
prompt generated -> dispatch recorded -> RUN sent -> FINALIZE received -> finalize recorded -> gate -> closed
     harness            manifest.py         host          subagent          manifest.py       script   (never reused)
```

1. Generate the prompt with `prompt_harness.py` (cheatsheet). It fails on an unfilled placeholder; never hand-edit
   prompts or send a role file with placeholders left.
2. `manifest.py dispatch RUN_DIR <role> --prompt <path> [--batch ID]` records the instance and prints its id. It
   refuses a prompt with leftover placeholders, a second running instance of the same role and batch, and a third
   attempt for the same role and batch (report to the user first; `--force` only on their decision).
3. Show the assembled subagent command in chat (name, prompt path, model), then start the subagent with the one-line
   RUN message: `Read the file <PROMPT_PATH> and follow it exactly. It is your complete instruction set. Return only the FINALIZE block it asks for.`
   If the host's subagent cannot read files, paste the prompt body instead.
   Model: evaluators run on `evaluator.model` and auditors, when the audit is included, on `evaluator.audit_model` (the Step 1 answers; change
   them with `manifest.py set-setting RUN_DIR model|audit_model "<name>"`). Subagents inherit the session model on
   VS Code Copilot, so when a chosen model differs from the session's, either pin both into the named agents
   (`setup_skill.py --agents --evaluator-model "<P6>" --auditor-model "<P7>"`, then dispatch by agent name) or ask
   the user to switch the model picker before the first P6 dispatch, again before the first P7 dispatch when the two
   differ, and back before P8. `dispatch` records the role's model by default; pass `--model` when the user switched
   to something else. The final file and `summary.md` list every model used.
4. Wait for the FINALIZE block (format in `references/subagent_dispatch.md`). Record it:
   `manifest.py finalize RUN_DIR <dispatch id> --status done|failed|blocked --outputs <paths...>`; a listed output that
   does not exist turns the record into `failed`. Then run the phase gate and `set-batch` / `set-phase`.
   Answer `questions_for_orchestrator` yourself from the manifest and reports, or ask the user, then re-dispatch with
   the answer injected.
5. Subagents are stateless and single-use: a re-dispatch is a new record with the same prompt file. Do not send
   follow-ups; do not reuse an instance for another batch.
6. Parallelism: dispatch all evaluators of the run together (host permitting), then all auditors. Everything else
   runs alone. Nested subagents stay off.

## Isolation: what is enforced and what is not

Enforced by construction: every subagent starts with an empty context (host property); its prompt names only the
files its role may use; an evaluator receives exactly one batch file; the auditor's payload is built by a script
that withholds the evaluator's type, rationale, severity and expected value; the architect's prompt carries no
trajectory path at all. Enforced by instruction only: a subagent with a file tool could still open other files.
Reduce that with the optional adapters (tool allowlists) and verify it after the fact with
`scripts/leak_check.py --prompt <filled prompt> --transcript <subagent transcript> --forbid input/materials`
(Claude Code keeps subagent transcripts under `~/.claude/projects/<project>/<session>/subagents/`; on hosts without
transcripts, review the subagent's tool calls in the chat). A confirmed leak invalidates that batch: re-dispatch it.

## Single-agent fallback

When no subagent mechanism exists or the user declines, perform each role yourself in phase order: open the role's
prompt file, then only the files it lists, produce its outputs, run its gate. Record
`evaluator.mode = single-agent` in the manifest (`manifest.py init ... --mode single-agent`) and pass
`--var EVALUATOR_MODE=single-agent` to the reporter. Say in the summary that the same
context wrote the spec and judged the logs.

## Scale rules

Batches: 12 conversations or 40k characters. Above 20 conversations compile the checker. Sampling of judgment points
only with the user's agreement and recorded in the manifest (`references/scaling.md`).

## Reporting to the user

After P8, relay `summary.md` in chat with digits masked (it already is), the run folder path under `output/` and
its four final files (`hallucination_findings.json`, `summary.md`, `workflow_pseudocode.md`, `architecture.md`), the mode, whether the
findings are audited, evaluator precision and miss rate, the top points, the unverifiable share and why, and the open
questions from the spec. If unverifiable points dominate (for example no ZIP on file), say what input would settle
them. Offer the next step (a second trajectory set, a production build of the pseudocode) without starting it.

## Guardrails

- Never edit anything under `input/`; never send trajectories or materials to any external service; outputs stay
  under `output/`.
- Never label ASR mishearing, customer self-correction, or a tool error as a hallucination; never let a consistent
  behaviour in the logs become part of the spec; drift is a pipeline finding with a proposed spec fix.
- Record which model evaluated and audited; report unaudited or single-agent results as such.
- If a role returns a product you find implausible, re-dispatch it or dispatch the auditor; do not fix it by hand.
- Ask the user before deleting or overwriting a run folder.
- The normalizer's diet is on by default (full-state copies dropped, secrets and card numbers redacted, payloads
  capped); `--no-diet` is for local debugging and its output must never reach a model. Evaluators and auditors read
  the pseudocode only, never the spec or the architecture views, and `context_budget.py` is the gate before P6 and P7.

## Files in this skill

`roles/` (7 prompts), `references/` (folders convention, taxonomy, evaluation procedure, judgment rubric, grounding
sources, evidence rules, audit procedure, output schema, pseudocode format, architecture views, trajectory formats,
scaling, subagent dispatch, CLI cheatsheet, DemoCard excerpt), `assets/` (pseudocode template, checker template, findings schema, manifest
template, column-map example, setup questions), `scripts/` (inventory, build_spec, normalize, prompt harness,
manifest with gates and dispatch records, run_checker, make_audit_payload, validate, merge, aggregate,
report_summary, leak_check, check_skill, setup_skill, context_budget, show_locator), `adapters/`
(optional named-agent files for VS Code Copilot and Claude Code), `tests/`, `evals/`.

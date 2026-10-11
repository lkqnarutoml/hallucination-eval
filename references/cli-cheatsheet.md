# CLI cheatsheet (every command the orchestrator runs, by phase)

`SKILL_DIR` is this skill's folder, `PY` the Python command from the operations manual (`python`, `py -3` or
`python3`), `RUN_DIR` the run folder under `output/`. Run scripts as black boxes: do not open them to learn their
flags; everything needed is on this page. Gate = the command whose exit code must be 0 before the phase is done.
Folder conventions and the canonical path keys are in `references/folders.md`.

## P0 Setup

```bash
PY SKILL_DIR/scripts/manifest.py scan input                                   # what the input folder holds, with hints
PY SKILL_DIR/scripts/manifest.py init --target "AGENT NAME" --input input --output output [--run-id ID] [--model "<P6 model>" --audit-model "<P7 model>"] [--no-audit] [--mode multi-agent|single-agent] [--batch-conversations 12] [--batch-chars 40000] [--checker-threshold 20]
PY SKILL_DIR/scripts/manifest.py paths RUN_DIR                                # KEY=path lines; use them below
PY SKILL_DIR/scripts/manifest.py show RUN_DIR
PY SKILL_DIR/scripts/manifest.py next RUN_DIR                                # first open phase + running subagents
PY SKILL_DIR/scripts/manifest.py gate RUN_DIR <phase>                        # prerequisites + artifacts, changes nothing
PY SKILL_DIR/scripts/manifest.py set-phase RUN_DIR <phase> done               # refused when the gate fails
PY SKILL_DIR/scripts/manifest.py set-phase RUN_DIR <phase> skipped --note "why"
PY SKILL_DIR/scripts/manifest.py set-phase RUN_DIR <phase> done --force --note "user decided: why"
PY SKILL_DIR/scripts/manifest.py register-batches RUN_DIR                    # after normalize (set-phase normalize done does it too)
PY SKILL_DIR/scripts/manifest.py set-batch RUN_DIR <evaluate|audit> <batch id> <pending|in_progress|done|failed>
PY SKILL_DIR/scripts/manifest.py dispatch RUN_DIR <role> --prompt RUN_DIR/runtime/prompt-<role>[-<batch>].md [--batch <id>]   # prints d-NNNN
PY SKILL_DIR/scripts/manifest.py finalize RUN_DIR d-NNNN --status done|failed|blocked --outputs <paths...> [--note "..."]
PY SKILL_DIR/scripts/manifest.py log RUN_DIR "message"
```

Roles for `dispatch`: architect, spec_auditor, normalizer, checker_compiler, evaluator, auditor, reporter. Every
subagent instance is dispatched and finalized through these two commands; the third attempt for one role and batch
is refused without `--force`.

Without the input convention: `manifest.py init RUN_DIR --target "AGENT NAME" --materials <paths...> --trajectories <paths...> [--ground-truth <files...>] [--intro-docs <files...>] [--existing-pseudocode <file>]`.
Phases: setup, inventory, pseudocode, spec_review, normalize_inspect, normalize, checker_compile, checker_run,
evaluate, audit, report. The paths below are the canonical ones; `paths` prints them absolute.

## P1 Inventory (orchestrator runs it; no subagent)

```bash
PY SKILL_DIR/scripts/inventory_materials.py input/materials --out RUN_DIR/inventory/materials_inventory.json --summary RUN_DIR/inventory/materials_summary.md [--agents-file input/config/agents.json]
PY SKILL_DIR/scripts/build_spec.py tree --inventory RUN_DIR/inventory/materials_inventory.json --out RUN_DIR/inventory/materials_tree.md
```

Gate: the summary lists at least one agent; otherwise ask the user for `input/config/agents.json`.

## P2 Architect

```bash
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/architect.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" --var TARGET_AGENT="AGENT NAME" \
  --var MATERIALS="input/materials/<entry>; ..." --var INTRO_DOCS="input/docs/<file>; ... or none" --var EXISTING_PSEUDOCODE="input/docs/<pseudocode file> or none" \
  --var INVENTORY_JSON=RUN_DIR/inventory/materials_inventory.json --var INVENTORY_SUMMARY=RUN_DIR/inventory/materials_summary.md \
  --var MATERIALS_TREE=RUN_DIR/inventory/materials_tree.md --var REVIEW_NOTES=none \
  --var PSEUDOCODE_OUT=RUN_DIR/workflow_pseudocode.md --var SPEC_JSON_OUT=RUN_DIR/spec/workflow_spec.json \
  --var SPEC_REPORT_OUT=RUN_DIR/spec/spec_report.md --var ARCHITECTURE_OUT=RUN_DIR/architecture.md \
  --var ARCHITECT_REPORT_OUT=RUN_DIR/spec/architect_report.md \
  --output RUN_DIR/runtime/prompt-architect.md
```

Second round after a `REVISE` verdict: same command with `--inject-file REVIEW_NOTES=RUN_DIR/spec/spec_review.md`
instead of `--var REVIEW_NOTES=none`, output `prompt-architect-r2.md`.

Gate:

```bash
PY SKILL_DIR/scripts/build_spec.py compile RUN_DIR/workflow_pseudocode.md --out RUN_DIR/spec/workflow_spec.json --report RUN_DIR/spec/spec_report.md --inventory RUN_DIR/inventory/materials_inventory.json
PY SKILL_DIR/scripts/build_spec.py render RUN_DIR/spec/workflow_spec.json --out RUN_DIR/architecture.md --inventory RUN_DIR/inventory/materials_inventory.json
```

## P3 Spec auditor

```bash
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/spec_auditor.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" --var MATERIALS="input/materials/<entry>; ..." \
  --var PSEUDOCODE_PATH=RUN_DIR/workflow_pseudocode.md --var SPEC_JSON=RUN_DIR/spec/workflow_spec.json \
  --var SPEC_REPORT=RUN_DIR/spec/spec_report.md --var ARCHITECTURE_PATH=RUN_DIR/architecture.md \
  --var INVENTORY_JSON=RUN_DIR/inventory/materials_inventory.json --var SPEC_REVIEW_OUT=RUN_DIR/spec/spec_review.md \
  --output RUN_DIR/runtime/prompt-spec-auditor.md
```

Gate: `RUN_DIR/spec/spec_review.md` exists and its `VERDICT:` line is `APPROVED` or `APPROVED_WITH_NOTES` (on
`REVISE`, re-run P2 round 2, then P3 again; at most two rounds, then ask the user).

## P4 Normalizer

Inspect (tabular exports only; skip when every trajectory entry is an events.jsonl or CES JSON folder):

```bash
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/normalizer.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" --var MODE=inspect \
  --var TRAJECTORIES="input/trajectories/<export.xlsx>; ..." --var FORMAT=auto --var SHEET=none --var COLUMN_MAP=none --var GROUND_TRUTH=none \
  --var NORMALIZE_OUT_DIR=RUN_DIR/normalized --var BATCHES_DIR=RUN_DIR/normalized/batches --var BATCH_CONVERSATIONS=12 --var BATCH_CHARS=40000 \
  --var NORMALIZER_REPORT_OUT=RUN_DIR/normalized/normalizer_inspect_report.md \
  --var NORMALIZE_EXTRA_FLAGS="" \
  --output RUN_DIR/runtime/prompt-normalizer-inspect.md
```

Then show the proposal to the user and save the confirmed map as `input/config/column_map.json` (copied to
`RUN_DIR/normalized/column_map.json`), and normalize:

```bash
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/normalizer.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" --var MODE=normalize \
  --var TRAJECTORIES="input/trajectories/<entry>; ..." --var FORMAT=auto --var SHEET=none \
  --var COLUMN_MAP="input/config/column_map.json or none" --var GROUND_TRUTH="input/ground_truth/<file> or none" \
  --var NORMALIZE_OUT_DIR=RUN_DIR/normalized --var BATCHES_DIR=RUN_DIR/normalized/batches --var BATCH_CONVERSATIONS=12 --var BATCH_CHARS=40000 \
  --var NORMALIZER_REPORT_OUT=RUN_DIR/normalized/normalizer_report.md \
  --var NORMALIZE_EXTRA_FLAGS="" \
  --output RUN_DIR/runtime/prompt-normalizer.md
```

Gate: `RUN_DIR/normalized/conversations.json` and `RUN_DIR/normalized/batches/index.json` exist. Direct commands
(fallback mode or a quick check):

```bash
PY SKILL_DIR/scripts/normalize_trajectories.py inspect input/trajectories/<export.xlsx> [--sheet NAME] --out RUN_DIR/normalized/column_map.proposed.json
PY SKILL_DIR/scripts/normalize_trajectories.py normalize input/trajectories/<entries...> --out RUN_DIR/normalized [--format auto|events_jsonl|ces_json|xlsx|csv] [--column-map input/config/column_map.json] [--sheet NAME] [--ground-truth input/ground_truth/<file>]
PY SKILL_DIR/scripts/normalize_trajectories.py split RUN_DIR/normalized/conversations.json --out RUN_DIR/normalized/batches --max-conversations 12 --max-chars 40000
```

## P5 Checker compiler (only above the checker threshold)

```bash
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/checker_compiler.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" \
  --var PSEUDOCODE_PATH=RUN_DIR/workflow_pseudocode.md --var SPEC_JSON=RUN_DIR/spec/workflow_spec.json \
  --var CHECKER_TEMPLATE=SKILL_DIR/assets/checker_template.py --var CHECKER_OUT=RUN_DIR/checker/checker_agent.py \
  --var BATCHES_DIR=RUN_DIR/normalized/batches --var CHECKER_RESULTS_DIR=RUN_DIR/checker/results --var COMPILER_REPORT_OUT=RUN_DIR/checker/checker_report.md \
  --output RUN_DIR/runtime/prompt-checker-compiler.md
```

Gate: `PY SKILL_DIR/scripts/run_checker.py --checker RUN_DIR/checker/checker_agent.py --batches RUN_DIR/normalized/batches --out RUN_DIR/checker/results` exits 0.

## P6 Evaluators (one per batch, in parallel)

```bash
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/evaluator.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" \
  --var PSEUDOCODE_PATH=RUN_DIR/workflow_pseudocode.md \
  --var BATCH_ID=001 --var BATCH_PATH=RUN_DIR/normalized/batches/batch_001.json --var CHECKER_RESULTS="RUN_DIR/checker/results/batch_001.json or none" \
  --var FINDINGS_OUT=RUN_DIR/findings/batch_001.json --var NOTES_OUT=RUN_DIR/notes/batch_001.md \
  --output RUN_DIR/runtime/prompt-evaluator-001.md
```

Before the first dispatch: `PY SKILL_DIR/scripts/context_budget.py RUN_DIR --role evaluator [--limit-chars 300000]` exits 0
(one row per batch: prompt + pseudocode + batch + checker + references; above the limit re-split with a smaller `--max-chars`
or normalize again with a stricter diet). Dispatch with `manifest.py dispatch RUN_DIR evaluator --prompt ... --batch 001 --model "<model>"`,
in waves of at most three on VS Code Copilot with Claude models.

Gate per batch: `PY SKILL_DIR/scripts/validate_findings.py RUN_DIR/findings/batch_001.json --batch --pre-audit --conversations RUN_DIR/normalized/batches/batch_001.json`

## P7 Auditors (one per evaluated batch, in parallel; only when the audit was included at setup)

Skip this whole phase when `manifest.py show` says `audit: skipped`: `init --no-audit` already marked it, `next` goes
from evaluate to report, and the reporter merges with `--unverified`. To change your mind mid-run:
`manifest.py set-setting RUN_DIR audit true|false`.

```bash
PY SKILL_DIR/scripts/make_audit_payload.py payload --findings RUN_DIR/findings/batch_001.json --conversations RUN_DIR/normalized/conversations.json --out RUN_DIR/audit/payload_batch_001.json [--sample 5] [--seed 7]
PY SKILL_DIR/scripts/context_budget.py RUN_DIR --role auditor --batch 001 [--limit-chars 300000]     # exits 0 before the auditor is dispatched
PY SKILL_DIR/scripts/manifest.py dispatch RUN_DIR auditor --prompt RUN_DIR/runtime/prompt-auditor-001.md --batch 001   # records evaluator.audit_model (the P7 choice)
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/auditor.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" \
  --var PSEUDOCODE_PATH=RUN_DIR/workflow_pseudocode.md --var BATCH_ID=001 \
  --var PAYLOAD_PATH=RUN_DIR/audit/payload_batch_001.json --var VERDICTS_OUT=RUN_DIR/audit/verdicts_batch_001.json \
  --var AUDIT_NOTES_OUT=RUN_DIR/audit/batch_001.md \
  --output RUN_DIR/runtime/prompt-auditor-001.md
```

After FINALIZE:

```bash
PY SKILL_DIR/scripts/make_audit_payload.py apply --findings RUN_DIR/findings/batch_001.json --verdicts RUN_DIR/audit/verdicts_batch_001.json --out RUN_DIR/findings/verified_batch_001.json
PY SKILL_DIR/scripts/validate_findings.py RUN_DIR/findings/verified_batch_001.json --batch --conversations RUN_DIR/normalized/batches/batch_001.json
```

Gate: both exit 0 (`apply` exits 1 when a verdict is missing: re-dispatch the auditor with the same prompt).

## P8 Reporter

```bash
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/reporter.md \
  --var SKILL_DIR=SKILL_DIR --var RUN_DIR=RUN_DIR --var PYTHON="PY" --var TARGET_AGENT="AGENT NAME" \
  --var EVALUATOR_MODEL="<P6 model>" --var EVALUATOR_MODE=multi-agent --var MERGE_FLAGS="" \
  --var FINDINGS_DIR=RUN_DIR/findings --var CONVERSATIONS_PATH=RUN_DIR/normalized/conversations.json \
  --var PSEUDOCODE_PATH=RUN_DIR/workflow_pseudocode.md --var SPEC_JSON=RUN_DIR/spec/workflow_spec.json --var MANIFEST_PATH=RUN_DIR/run_manifest.json \
  --var FINAL_OUT=RUN_DIR/hallucination_findings.json --var AGGREGATE_OUT=RUN_DIR/aggregate.json --var TABLES_OUT=RUN_DIR/summary_tables.md \
  --var SUMMARY_OUT=RUN_DIR/summary.md --var REPORTER_REPORT_OUT=RUN_DIR/report/reporter_report.md \
  --output RUN_DIR/runtime/prompt-reporter.md
```

`MERGE_FLAGS` is `--unverified` when `manifest.py show` says `audit: skipped` (P7 not included at setup), otherwise empty.

Gate: `PY SKILL_DIR/scripts/validate_findings.py RUN_DIR/hallucination_findings.json --conversations RUN_DIR/normalized/conversations.json --resolve-locators --base-dir <workspace root>` exits 0 and `RUN_DIR/summary.md` exists
(locators hold the trajectory paths as given to the normalizer, relative to the workspace root that holds `input/`).

## Utilities

```bash
PY SKILL_DIR/scripts/leak_check.py --prompt RUN_DIR/runtime/prompt-evaluator-001.md --transcript <subagent transcript> --forbid input/materials   # files a subagent touched outside its prompt
PY SKILL_DIR/scripts/prompt_harness.py --template SKILL_DIR/roles/<role>.md --list      # placeholders a role needs
PY SKILL_DIR/scripts/check_skill.py --tests                                           # maintainer self-check
PY SKILL_DIR/scripts/show_locator.py <locator> [--base-dir <workspace root>]          # the source record behind a capped value, redacted
PY SKILL_DIR/scripts/context_budget.py RUN_DIR [--role evaluator|auditor] [--batch 001] [--limit-chars N]   # what each subagent will read
PY SKILL_DIR/scripts/manifest.py set-setting RUN_DIR model "<P6 model>"               # the model evaluators run on (audit_model for auditors; also batch_chars, ...)
PY SKILL_DIR/scripts/manifest.py set-setting RUN_DIR audit false                       # drop or (true) restore the P7 audit mid-run
PY SKILL_DIR/scripts/setup_skill.py --agents --evaluator-model "<P6>" --auditor-model "<P7>"   # pin the chosen models into the named agents (Copilot)
PY -m unittest discover -s SKILL_DIR/tests -p "test_*.py"                             # unit tests
```

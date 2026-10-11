# Role: reporter (merge, validate, aggregate, summarize)

> CRITICAL: this file is your complete instruction set. Read only what is listed below. You work through scripts:
> never recount findings by hand, never read raw trajectories, never change a finding. You cannot ask the user; put
> questions in the FINALIZE block.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `{{SKILL_DIR}}` | folder of the hallucination-eval skill |
| `{{RUN_DIR}}` | folder of this run |
| `{{PYTHON}}` | the Python command that works on this machine |
| `{{TARGET_AGENT}}` | name of the agent under evaluation |
| `{{EVALUATOR_MODEL}}` | the model that ran the P6 evaluators (the P7 model comes from the manifest) |
| `{{EVALUATOR_MODE}}` | `multi-agent` or `single-agent` |
| `{{MERGE_FLAGS}}` | `--unverified` when the P7 audit was skipped at setup, otherwise empty |
| `{{FINDINGS_DIR}}` | folder with `verified_batch_NNN.json` (or unverified `batch_NNN.json` when P7 was skipped) |
| `{{CONVERSATIONS_PATH}}` | `conversations.json` |
| `{{PSEUDOCODE_PATH}}` | `workflow_pseudocode.md` |
| `{{SPEC_JSON}}` | `workflow_spec.json` |
| `{{MANIFEST_PATH}}` | `run_manifest.json` |
| `{{FINAL_OUT}}` | `hallucination_findings.json` |
| `{{AGGREGATE_OUT}}` | `aggregate.json` |
| `{{TABLES_OUT}}` | `summary_tables.md` |
| `{{SUMMARY_OUT}}` | `summary.md` |
| `{{REPORTER_REPORT_OUT}}` | `reporter_report.md` |

## You may read

The files above and `{{SKILL_DIR}}/references/output_schema.md`, `{{SKILL_DIR}}/references/evidence_rules.md`.

## Procedure

1. Merge: `{{PYTHON}} {{SKILL_DIR}}/scripts/merge_findings.py --verified-dir {{FINDINGS_DIR}} --out {{FINAL_OUT}} --manifest {{MANIFEST_PATH}} --pseudocode {{PSEUDOCODE_PATH}} --conversations {{CONVERSATIONS_PATH}} --target "{{TARGET_AGENT}}" --model "{{EVALUATOR_MODEL}}" --mode {{EVALUATOR_MODE}} {{MERGE_FLAGS}}`
   `{{MERGE_FLAGS}}` is `--unverified` only when the audit phase (P7) was skipped at setup: the file is then built
   from the evaluator batches and marked unaudited. If the command reports no verified files while the flag is
   empty, stop with `failed`: the audit phase did not finish. Never add `--unverified` on your own.
2. Validate: `{{PYTHON}} {{SKILL_DIR}}/scripts/validate_findings.py {{FINAL_OUT}} --conversations {{CONVERSATIONS_PATH}} --resolve-locators --base-dir <workspace root>`
   where the workspace root is the folder that holds `input/` (locators are relative to it); drop
   `--resolve-locators` only if the sources are not on this machine, and report it. Errors mean a batch is broken:
   do not patch the file; report which batch and stop with `failed`.
3. Aggregate: `{{PYTHON}} {{SKILL_DIR}}/scripts/aggregate_findings.py {{FINAL_OUT}} --out {{AGGREGATE_OUT}} --md {{TABLES_OUT}} --mdd-view`
4. Summarize: `{{PYTHON}} {{SKILL_DIR}}/scripts/report_summary.py --findings {{FINAL_OUT}} --aggregate {{AGGREGATE_OUT}} --spec {{SPEC_JSON}} --manifest {{MANIFEST_PATH}} --out {{SUMMARY_OUT}}`
5. Read `{{SUMMARY_OUT}}`. Append a section `## Analyst reading` with at most ten sentences: what the numbers mean
   for the agent, which points concentrate the findings, what is unverifiable and why, what the pipeline findings
   suggest about the spec or the build, and what to check next. Use only numbers that already appear in the summary.
6. Write `{{REPORTER_REPORT_OUT}}`: the commands run with their exit codes and printed lines, the batches merged,
   whether the file is audited, and any anomaly (a batch missing, a conversation in two batches).

## FINALIZE

```
--- FINALIZE ---
role: reporter
status: done | failed
outputs:
  - {{FINAL_OUT}}
  - {{AGGREGATE_OUT}}
  - {{TABLES_OUT}}
  - {{SUMMARY_OUT}}
  - {{REPORTER_REPORT_OUT}}
counts: conversations=<n> hallucinations=<n> rejected=<n> pipeline=<n> unverifiable=<n> precision=<x> miss_rate=<x>
warnings:
  - <one per line, or none>
questions_for_orchestrator:
  - <one per line, or none>
--- END ---
```

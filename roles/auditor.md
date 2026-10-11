# Role: auditor (blind re-verification of one findings batch)

> CRITICAL: this file is your complete instruction set. Read only what is listed below. Do NOT open the evaluator's
> findings file or notes, other batches, the source code or `SKILL.md`. The payload you receive withholds the
> evaluator's type, rationale, severity and expected value on purpose: decide from the evidence first. You cannot ask
> the user; put questions in the FINALIZE block.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `{{SKILL_DIR}}` | folder of the hallucination-eval skill |
| `{{RUN_DIR}}` | folder of this run |
| `{{PYTHON}}` | the Python command that works on this machine |
| `{{PSEUDOCODE_PATH}}` | `workflow_pseudocode.md` (the only contract file you read) |
| `{{BATCH_ID}}` | this batch id |
| `{{PAYLOAD_PATH}}` | `audit/payload_batch_{{BATCH_ID}}.json` built by `make_audit_payload.py payload` |
| `{{VERDICTS_OUT}}` | where to write `audit/verdicts_batch_{{BATCH_ID}}.json` |
| `{{AUDIT_NOTES_OUT}}` | where to write `audit/batch_{{BATCH_ID}}.md` |

## You may read

`{{PAYLOAD_PATH}}`, `{{PSEUDOCODE_PATH}}`, `{{SKILL_DIR}}/references/audit_procedure.md` (section B is your
procedure), `{{SKILL_DIR}}/references/hallucination_taxonomy.md`, `{{SKILL_DIR}}/references/judgment_rubric.md`,
`{{SKILL_DIR}}/references/grounding_sources.md`, `{{SKILL_DIR}}/references/evidence_rules.md`,
`{{SKILL_DIR}}/references/output_schema.md`. Read each file once; do not open `workflow_spec.json` (the pseudocode
carries the same content). Payload values may carry the normalizer's marks: `[redacted:... len=N]` (a secret, never
evidence for or against a finding), `****1234` (compare by last four), `...[+N chars]`, `_summary`, `_capped`. When a
verdict needs the full value, run `{{PYTHON}} {{SKILL_DIR}}/scripts/show_locator.py <locator>`.

## Procedure

1. For each item in `items`: read `point`, `observed`, the evidence quotes and locators, and the `context` slice.
   Open the pseudocode element the point names. Write your own verdict (supported / unsupported, and why) in
   `{{AUDIT_NOTES_OUT}}` BEFORE deciding the status.
2. Status per item: `confirmed`, `revised` (with the corrected `type` / `severity` / `confidence` / `point` in
   `revised`), or `rejected` (evidence supports the artifact; locator does not show the claim; code-authored;
   unverifiable; rule tagged unknown). Always give `auditor_rationale`.
3. For each entry in `supported_samples`: check the call against the active step's decide table and the argument
   contract. `supported: true`, or `supported: false` with a complete finding object (no id, no verification).
4. Write `{{VERDICTS_OUT}}` in the shape given in `references/audit_procedure.md` (`batch`, `notes`, `verdicts`,
   `samples`). Every item ref must appear exactly once.
5. Finish `{{AUDIT_NOTES_OUT}}`: consistency decisions, patterns the evaluator missed or over-reported, anything the
   orchestrator should raise with the user.

## Rules

- Same situation, same status. Revisit earlier items if a later one changes your reading.
- Do not soften a verdict because the evaluator "probably had a reason": you cannot see its reason by design.
- Never edit the findings batch; the orchestrator applies your verdicts with a script.

## FINALIZE

```
--- FINALIZE ---
role: auditor
batch: {{BATCH_ID}}
status: done | failed
outputs:
  - {{VERDICTS_OUT}}
  - {{AUDIT_NOTES_OUT}}
counts: items=<n> confirmed=<n> revised=<n> rejected=<n> samples=<n> misses=<n>
warnings:
  - <one per line, or none>
questions_for_orchestrator:
  - <one per line, or none>
--- END ---
```

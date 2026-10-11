# Role: spec auditor (review the pseudocode against the materials)

> CRITICAL: this file is your complete instruction set. Read only what is listed below. Do NOT open any trajectory,
> log or findings file. You cannot ask the user; put questions in the FINALIZE block.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `{{SKILL_DIR}}` | folder of the hallucination-eval skill |
| `{{RUN_DIR}}` | folder of this run |
| `{{PYTHON}}` | the Python command that works on this machine |
| `{{MATERIALS}}` | the material paths the architect read |
| `{{PSEUDOCODE_PATH}}` | `workflow_pseudocode.md` to review |
| `{{SPEC_JSON}}` | compiled `workflow_spec.json` |
| `{{SPEC_REPORT}}` | `spec_report.md` from the compiler |
| `{{ARCHITECTURE_PATH}}` | `architecture.md` rendered from the spec |
| `{{INVENTORY_JSON}}` | `materials_inventory.json` |
| `{{SPEC_REVIEW_OUT}}` | where to write `spec_review.md` |

## You may read

`{{MATERIALS}}`, `{{PSEUDOCODE_PATH}}`, `{{SPEC_JSON}}`, `{{SPEC_REPORT}}`, `{{ARCHITECTURE_PATH}}`, `{{INVENTORY_JSON}}`,
`{{SKILL_DIR}}/references/audit_procedure.md` (section A is your checklist), `{{SKILL_DIR}}/references/pseudocode_format.md`,
`{{SKILL_DIR}}/references/grounding_sources.md`.

## Task

Check that every element of the pseudocode is what the materials say, that author and provenance tags are right,
and that the point inventory covers every decision. Follow section A of `references/audit_procedure.md` in order.

## Procedure

1. Read `{{SPEC_REPORT}}`: errors are blocking; classify each warning.
2. For every step, tool, callback rule, rule and template, open the material file it was derived from and compare
   the exact comparison, threshold, status names, sentences and placeholders. Verify `author` and `provenance`.
3. Compare `{{ARCHITECTURE_PATH}}` (tree, flows) with the packaging files and the flow engine.
4. Check the open-questions section lists every inferred or unknown element.
5. Write `{{SPEC_REVIEW_OUT}}`: a table `| Severity (blocking/major/minor) | Element | Material says | Pseudocode says | Fix |`,
   a short list of things you verified and found correct (so the next round does not re-check them), and the verdict
   line `VERDICT: APPROVED` / `APPROVED_WITH_NOTES` / `REVISE`. `REVISE` when any blocking or major issue exists.

Do not rewrite the pseudocode yourself; the architect applies the fixes.

## FINALIZE

```
--- FINALIZE ---
role: spec_auditor
status: done | failed
outputs:
  - {{SPEC_REVIEW_OUT}}
counts: blocking=<n> major=<n> minor=<n> verified_ok=<n>
verdict: APPROVED | APPROVED_WITH_NOTES | REVISE
questions_for_orchestrator:
  - <one per line, or none>
--- END ---
```

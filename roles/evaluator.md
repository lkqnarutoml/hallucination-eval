# Role: evaluator (one batch of conversations, point by point against the pseudocode)

> CRITICAL: this file is your complete instruction set. Read only what is listed below. Do NOT open the agent's
> source code, other batches, other evaluators' findings, or `SKILL.md`. If the pseudocode looks wrong, record a
> possible spec drift in your notes and keep going; never re-derive rules from code or from what the agent "usually
> does". You cannot ask the user; put questions in the FINALIZE block.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `{{SKILL_DIR}}` | folder of the hallucination-eval skill |
| `{{RUN_DIR}}` | folder of this run |
| `{{PYTHON}}` | the Python command that works on this machine |
| `{{PSEUDOCODE_PATH}}` | `workflow_pseudocode.md`, the contract you evaluate against (the only contract file you read) |
| `{{BATCH_ID}}` | this batch id, e.g. `003` |
| `{{BATCH_PATH}}` | `batches/batch_{{BATCH_ID}}.json`, the only trajectory data you may read |
| `{{CHECKER_RESULTS}}` | `checker_out/batch_{{BATCH_ID}}.json` from the compiled checker, or `none` |
| `{{FINDINGS_OUT}}` | where to write `findings/batch_{{BATCH_ID}}.json` |
| `{{NOTES_OUT}}` | where to write `notes/batch_{{BATCH_ID}}.md` |

## You may read

`{{PSEUDOCODE_PATH}}`, `{{BATCH_PATH}}`, `{{CHECKER_RESULTS}}`,
`{{SKILL_DIR}}/references/evaluation_procedure.md` (your procedure), `{{SKILL_DIR}}/references/hallucination_taxonomy.md`,
`{{SKILL_DIR}}/references/judgment_rubric.md`, `{{SKILL_DIR}}/references/grounding_sources.md`,
`{{SKILL_DIR}}/references/evidence_rules.md`, `{{SKILL_DIR}}/references/output_schema.md`.
Read each file once. Do not open `workflow_spec.json`, `architecture.md` or the JSON schema: the pseudocode carries the
same decide tables, author tags and point inventory, and `validate_findings.py` enforces the schema for you.

## Task

For every conversation in the batch, walk the events in order, keep the state, know the active step, classify each
customer input, and at every point ask: is what the model produced supported by one of the six reference points
(customer words and history, tool catalogue, earlier arguments, tool results, session state, workflow rules)?
Record every hallucination with rationale and evidence; count every point you judged.

## Procedure

1. Read the pseudocode once, section by section: agents and routing (which tools each agent may call), the turn
   skeleton, the steps with their gates and decide tables, the tool contracts, the callback rules, the deterministic
   rules, the end reasons, the state variables, the canned templates, and the point inventory (the point ids you must
   use). Note the author of each artifact. Points authored by `code` produce pipeline findings, never hallucinations.
2. Read `references/evaluation_procedure.md` and `references/judgment_rubric.md`. Follow them literally.
3. Read `{{BATCH_PATH}}` once, in line ranges, one conversation at a time; never re-read the whole file. The
   normalizer has already shrunk it: a `state_update` with `source: defaults` carries the initial state and every
   later one carries only `changes` (apply them; there is no full-state copy). Values may carry these marks:
   `[redacted:... len=N]` (a secret; present, its content unverifiable, never a finding), `****1234` (a card or
   account number masked to its last four; compare by last four), `...[+N chars]` (a truncated string), `_summary`
   or `_capped` (a shortened container; the counts are in the summary text). When one point needs the full value, run
   `{{PYTHON}} {{SKILL_DIR}}/scripts/show_locator.py <locator>` for that event; it prints the record with the same redaction.
4. If `{{CHECKER_RESULTS}}` is not `none`: for each conversation, start from the checker's findings, re-verify each
   against the evidence, keep or drop (say why in the notes), set `decided_by: checker`, and add its
   `points_evaluated` to yours without double counting.
5. For each conversation write one record (shape in `references/output_schema.md`): `conversation_id`, `source`,
   `workflow`, `turns`, `points_evaluated`, `outcome`, `hallucinations` (ids `H-0001`... within this batch), `pipeline_findings`
   (`P-0001`...), `unverifiable`, `notes`. Every finding: `turn`, `point` (from the inventory naming), `author`, `type`,
   `check_kind`, `severity`, `confidence`, `observed`, `expected_or_allowed`, `rationale` (quote the customer's words or
   the state key), `evidence` (at least one trajectory item with the event's `locator`, plus one `pseudocode` item
   naming the element and its provenance), `decided_by: evaluator`, `batch: {{BATCH_ID}}`.
6. Save `{{FINDINGS_OUT}}` as `{"batch": "{{BATCH_ID}}", "conversations": [...]}` and validate:
   `{{PYTHON}} {{SKILL_DIR}}/scripts/validate_findings.py {{FINDINGS_OUT}} --batch --pre-audit --conversations {{BATCH_PATH}}`
   Fix every error until it prints `VALID`.
7. Write `{{NOTES_OUT}}`: per conversation, the active-step sequence you inferred and whether state was tracked or
   emulated; judgment calls and how you decided them (consistency inside the batch); `asr_suspect` cases; possible
   spec drift (element, what the log shows); checker findings you dropped and why; anything unverifiable and why.

## Rules

- Quote or do not claim. No finding without a locator and a pseudocode reference.
- One point, one finding. Count supported points too; `points_evaluated` is the denominator.
- Do not grade the workflow, the tools or the ASR; only the model's artifacts.
- Be consistent: the same situation in two conversations gets the same verdict.
- Digits stay exact in evidence; nothing leaves the run folder.

## FINALIZE

```
--- FINALIZE ---
role: evaluator
batch: {{BATCH_ID}}
status: done | failed | blocked
outputs:
  - {{FINDINGS_OUT}}
  - {{NOTES_OUT}}
counts: conversations=<n> points_evaluated=<n> hallucinations=<n> pipeline=<n> unverifiable=<n> checker_kept=<n> checker_dropped=<n>
warnings:
  - <one per line, or none>
questions_for_orchestrator:
  - <one per line, or none>
--- END ---
```

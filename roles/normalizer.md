# Role: normalizer (trajectories -> conversations.json and batches)

> CRITICAL: this file is your complete instruction set. Read only what is listed below. Do NOT open the pseudocode,
> the spec, the materials or any findings: your job is data preparation, not judgment. You cannot ask the user; put
> questions in the FINALIZE block.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `{{SKILL_DIR}}` | folder of the hallucination-eval skill |
| `{{RUN_DIR}}` | folder of this run |
| `{{PYTHON}}` | the Python command that works on this machine |
| `{{MODE}}` | `inspect` (propose a column map for a tabular export) or `normalize` (produce conversations and batches) |
| `{{TRAJECTORIES}}` | trajectory inputs: run folders with events.jsonl, CES JSON folders, xlsx or csv exports (one per line or semicolon-separated) |
| `{{FORMAT}}` | `auto`, `events_jsonl`, `ces_json`, `xlsx` or `csv` |
| `{{SHEET}}` | worksheet name for xlsx exports, or `none` |
| `{{COLUMN_MAP}}` | confirmed `column_map.json` for tabular exports, or `none` |
| `{{GROUND_TRUTH}}` | ground-truth file keyed by session id (e.g. ZIP on file), or `none` |
| `{{NORMALIZE_OUT_DIR}}` | where `conversations.json` and `normalize_report.md` go |
| `{{BATCHES_DIR}}` | where `batch_NNN.json` files go |
| `{{BATCH_CONVERSATIONS}}` | max conversations per batch |
| `{{BATCH_CHARS}}` | max characters per batch |
| `{{NORMALIZER_REPORT_OUT}}` | where to write your `normalizer_report.md` |
| `{{NORMALIZE_EXTRA_FLAGS}}` | extra flags for `normalize` (diet settings such as `--state-snapshots turn`), or empty |

## You may read

`{{TRAJECTORIES}}` (through the script; open a raw file only to diagnose a parse problem), `{{COLUMN_MAP}}`,
`{{GROUND_TRUTH}}`, `{{SKILL_DIR}}/references/trajectory_formats.md`, `{{SKILL_DIR}}/assets/column_map.example.json`,
the script outputs under `{{NORMALIZE_OUT_DIR}}` and `{{BATCHES_DIR}}`.

## Procedure, mode `inspect`

1. For each tabular file in `{{TRAJECTORIES}}`:
   `{{PYTHON}} {{SKILL_DIR}}/scripts/normalize_trajectories.py inspect <file> --out {{RUN_DIR}}/column_map.proposed.json`
   (add `--sheet {{SHEET}}` when it is not `none`).
2. Write `{{NORMALIZER_REPORT_OUT}}`: for each file the proposed mapping per field with confidence and the masked
   samples, the fields that need confirmation, and a ready-to-confirm `column_map.json` draft (copy the
   `suggested_column_map` and edit `values` so speakers and row types match what you saw). The orchestrator shows
   this to the user; do not normalize in this mode.

## Procedure, mode `normalize`

1. Run, with every input on one command line:
   `{{PYTHON}} {{SKILL_DIR}}/scripts/normalize_trajectories.py normalize <inputs> --out {{NORMALIZE_OUT_DIR}} --format {{FORMAT}}`
   adding `--column-map {{COLUMN_MAP}}` unless it is `none`, `--sheet {{SHEET}}` unless `none`,
   `--ground-truth {{GROUND_TRUTH}}` unless `none`, and then `{{NORMALIZE_EXTRA_FLAGS}}` verbatim (it may be empty).
   Exit code 3 means a tabular file needs a confirmed column map: stop and report `blocked`. The script's diet is on by
   default: it drops the full-state copies, redacts secrets and card numbers, and caps payloads; the `diet:` line it
   prints and the report's Diet section say what was removed. Never pass `--no-diet` for a real run.
2. Read `{{NORMALIZE_OUT_DIR}}/normalize_report.md`. Investigate every warning code: `fallback_used` (no CES chunks,
   intra-turn order comes from spans), `no_turns`, `ordering_conflict`, `duplicate_row`, `duplicate_conversation_id`,
   `flat_tool_calls_only`, `unreadable_json`. Open the raw source only where needed to say whether the data is usable.
3. Sanity-check `conversations.json` with a short script or by reading two conversations: customer and agent
   utterances alternate, tool calls carry parsed `args` and `response` dicts (`representation` not `unparseable`),
   `origin` is set where spans exist, `metadata.flow` and `ground_truth` are filled where the source provides them.
4. Split: `{{PYTHON}} {{SKILL_DIR}}/scripts/normalize_trajectories.py split {{NORMALIZE_OUT_DIR}}/conversations.json --out {{BATCHES_DIR}} --max-conversations {{BATCH_CONVERSATIONS}} --max-chars {{BATCH_CHARS}}`
5. Write `{{NORMALIZER_REPORT_OUT}}`: sources and counts, events by kind, payload representations seen, parse rate,
   warnings with your assessment (usable / partially usable / unusable and why), conversations without ground truth,
   conversations without a flow, the diet (settings, counts per rule, characters before and after, the largest
   conversations after the diet), the batch index (id, conversations, characters) with any `oversized:` conversation
   `split` printed, and anything the evaluators must know (e.g. "state is only available as snapshots at turn end",
   "audio sessions have ASR transcripts").

## Rules

- Never edit the input files. Never drop a conversation silently; unusable ones are listed with the reason.
- Never look at what the agent did to decide whether the data is "right"; you only judge structural completeness.

## FINALIZE

```
--- FINALIZE ---
role: normalizer
mode: {{MODE}}
status: done | failed | blocked
outputs:
  - <conversations.json, normalize_report.md, batch files, column_map.proposed.json, normalizer_report.md as applicable>
counts: conversations=<n> batches=<n> tool_calls=<n> parse_rate=<pct> warnings=<n> with_ground_truth=<n> redacted=<n> snapshots_dropped=<n> chars_before=<n> chars_after=<n>
warnings:
  - <one per line, or none>
questions_for_orchestrator:
  - <one per line, or none>
--- END ---
```

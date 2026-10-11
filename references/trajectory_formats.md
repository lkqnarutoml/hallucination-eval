# Trajectory formats

`scripts/normalize_trajectories.py` turns any of the formats below into one `conversations.json` whose events keep
the order in which things happened inside a turn (customer text, tool call, state write, agent text). Grounding
checks depend on that order: an argument is grounded in the customer utterance that precedes the call, not in the
read-back that follows it.

## Normalized record

```json
{"conversation_id": "sim-...", "source": {"path": "...", "format": "events_jsonl", "locator": "events:...#seq=4"},
 "metadata": {"scenario_id": "...", "mode": "ai", "input_modality": "text", "flow": "damaged",
              "ground_truth": {"zip_on_file": "10001"}, "ground_truth_source": "fixture"},
 "events": [
   {"index": 0, "turn": 1, "kind": "customer_utterance", "text": "My debit card is damaged.", "locator": "...", "text_source": "ces_text"},
   {"index": 1, "turn": 1, "kind": "state_update", "source": "updatedVariables", "changes": {"democard_state.got_bearer_token": {"old": null, "new": true}}, "locator": "..."},
   {"index": 2, "turn": 1, "kind": "tool_call", "tool": "get_token", "args": {}, "response": {"result": "..."}, "origin": "callback", "agent": "DemoCard steering agent", "call_id": "adk-...", "locator": "..."},
   {"index": 3, "turn": 1, "kind": "transfer", "target": "replace_debit_card_agent", "locator": "..."},
   {"index": 4, "turn": 1, "kind": "agent_utterance", "text": "To replace your damaged debit card, ...", "origin": "callback", "agent": "replace_debit_card_agent", "locator": "..."},
   {"index": 5, "turn": null, "kind": "session_end", "reason": "card_replacement_submitted", "escalated": null, "locator": "..."}],
 "warnings": [{"code": "fallback_used", "detail": "...", "locator": null}],
 "summary": {"turns": 4, "events": 31, "tool_calls": 7, "tools": ["..."], "outcome": "completed", "customer_utterances": 4, "agent_utterances": 4}}
```

### Diet (what `normalize` removes before a batch is written)

`state_update` events carry `source` (`defaults`, `updatedVariables`, `deletedVariables`, `state_snapshot`, `column`)
and `changes`; the full-state copy is dropped by default (`--state-snapshots none`; `turn` keeps the last one of
each turn, `all` keeps them all). Tool `args` and `response`, every changed value and kept snapshots are redacted
(`--no-redact` to disable; `--redact-opaque` also hides long opaque strings) and capped: strings beyond
`--max-string` (600) end with `...[+N chars]`, containers deeper than `--max-depth` (2) become `{"_summary": ...}`,
lists keep `--list-items` (8) entries plus a summary with the total, and a payload above `--max-payload` (2500)
characters is tightened further and marked `_capped`. Redaction placeholders: `[redacted:bearer_token len=N]`,
`[redacted:jwt len=N]`, `[redacted:<key> len=N]` for secret-named keys, `****1234` for 13-19 digit runs
(counted as `pan` when they pass the Luhn check). Utterances are redacted, never truncated. `conversations.json`
records the settings and counts under `meta.diet`, each conversation under `summary.chars_before/after`, and the
report has a Diet section. `scripts/show_locator.py <locator>` prints any source record in full, redacted the
same way. `--no-diet` keeps everything and is for local debugging only.

`origin` on tool calls and agent utterances is `model` (produced after a model execution span), `callback`
(produced by a before/after-model callback without a model call) or `unknown` (the export carries no execution
spans). Only `model` and `unknown` artifacts can be hallucinations; `callback` ones are code-authored.

## Format 1: events.jsonl run folders (the DemoCard runners and the customer simulator)

One line per event, `sequence` numbering, `session_id` on every session event, `turn` on turn events. Per turn the
normalizer prefers the CES `ces_response.response.outputs[*].diagnosticInfo.messages[*].chunks` because those chunks
are in execution order (`text`, `transcript`, `toolCall`, `toolResponse`, `agentTransfer`, `defaultVariables`,
`updatedVariables`, `deletedVariables`). `execution_model` / `execution_callback` / `execution_tool` spans give the
origin tags. Without chunks it falls back to `execution_tool` spans plus `customer_message` / `agent_message`
events (warning `fallback_used`). Run-level events without a session id (run_start, app_snapshot, run_end) are not
conversations. `session_start.test_record.zip_code_answer` or `scenario.facts.zip` becomes
`metadata.ground_truth.zip_on_file` (source `fixture`).

Pass the run root; every `events.jsonl` up to three levels down is read.

## Format 2: raw CES response JSON

A folder per session with `turn-NNN-response.json` files (the runner writes them next to `events.jsonl`). The same
chunk walk applies; origin is `unknown` because spans are not tied to chunks.

## Format 3: tabular exports (xlsx or csv) from BigQuery or the runner's trajectory.xlsx

Columns differ per export, so the normalizer never guesses silently:

1. `normalize_trajectories.py inspect FILE` proposes a column map (`column_map.proposed.json`) with a confidence per
   field and masked samples. Required fields: `session_id`, `text`, `tool_name`, `tool_args`, `tool_response`.
   Optional: `timestamp`, `turn`, `row_type`, `speaker`, `tool_call_id`, `state`, `ces_json`, `agent`, `flow`.
2. The orchestrator shows the proposal to the user and saves the confirmed map as `column_map.json` (start from
   `assets/column_map.example.json`; the `values` block tells the loader how row types and speakers are named).
3. `normalize ... --column-map column_map.json [--sheet NAME] [--ground-truth FILE]`.

Row handling: rows of one session are ordered by timestamp when at least 95 percent parse, else by file order
(warnings `ordering_conflict`, `ordering_file_order`); duplicate rows are dropped; a response-only row is joined to
the preceding call with the same call id or tool name; a `ces_json` cell holding `diagnosticInfo` is expanded into
chunks; `state` cells update the tracked state. The runner's `trajectory.xlsx` is a node-per-row export whose
`Full Node JSON` and `Full Content` sheet hold the raw payloads; for those files prefer the `events.jsonl` next to
them.

Payload cells may be JSON, double-encoded JSON, Python dict reprs (single quotes, True/None) or nested wrappers
(`{"toolCall": {"args": {...}}}`, `{"result": {...}}`); `halu_common/payload.py` decodes all of them and records the
representation seen, which the normalization report lists.

## Ground truth

`--ground-truth FILE` (csv, xlsx or json keyed by session id) attaches every non-empty column to
`metadata.ground_truth`. For DemoCard the ZIP-on-file column (`zip_on_file`) is what `validate_zip_code.output` needs;
without it that point is unverifiable in every conversation.

## Batches

`normalize_trajectories.py split conversations.json --out batches --max-conversations 12 --max-chars 40000` writes
`batch_NNN.json` (`meta`, `batch {id, index, of, conversation_ids}`, `conversations`) and `index.json`. Each
evaluator receives exactly one batch file and nothing else from the trajectories.

# Folder conventions: `input/` and `output/`

Everything the skill reads comes from one `input/` folder; everything it writes goes under one `output/` folder.
`scripts/manifest.py scan input` reports what is present, `manifest.py init --input input --output output` creates
the run folder from it, and `manifest.py paths RUN_DIR` prints every canonical path for the harness commands.

## Input

```text
input/
  materials/      the CX Agent Studio "Export agent" folder(s) as exported (e.g. exported_app_DemoCard/),
                  or loose tool code, callbacks, prompts and variables.json; several entries are allowed
  trajectories/   one entry per source: an events.jsonl run folder, a folder of CES turn-NNN-response.json files,
                  or an xlsx / csv export
  ground_truth/   csv, xlsx or json keyed by session id with the external facts deterministic checks need
                  (DemoCard: zip_on_file); optional but without it those points are unverifiable
  docs/           optional: workflow introduction, MDD sections, an earlier pseudocode to reconcile
                  (a file whose name contains "pseudocode" is treated as the existing pseudocode)
  config/         optional: column_map.json (confirmed map for tabular exports), agents.json (hand-written tree
                  when no packaging exists), settings.json
```

`settings.json` keys: `batch_conversations` (12), `batch_chars` (40000), `checker_threshold` (20), `audit` (true;
false skips the P7 audit and marks the report UNAUDITED), `model` (the P6 evaluator model), `audit_model` (the P7
auditor model, default the same), `mode` (`multi-agent` or `single-agent`), `sampling` (null unless agreed). The
audit and model questions are still asked at setup unless the prompt answers them.

Rules: never edit anything under `input/`; every trajectory entry must come from the same deployed build as the
materials; keep unrelated exports out of `materials/` (one app per run).

## Output

```text
output/<RUN_ID>/                      RUN_ID = <UTC timestamp>-<agent>, e.g. 20260920T153000Z-DemoCard
  hallucination_findings.json         FINAL: one record per conversation, findings with rationale and evidence
  summary.md                          FINAL: the human report, digits masked
  workflow_pseudocode.md              FINAL: the rule book derived from the materials
  architecture.md                     FINAL: agent tree, flow state machines, who decides what, state bus
  aggregate.json, summary_tables.md   counts, rates, precision, miss rate, taxonomy views
  run_manifest.json                   phases with gates, batches, dispatch records, inputs, canonical paths; resume point
  inventory/                          materials_inventory.json, materials_summary.md, materials_tree.md
  spec/                               workflow_spec.json, spec_report.md, architect_report.md, spec_review.md
  normalized/                         conversations.json, normalize_report.md, normalizer_report.md,
                                      column_map.proposed.json, column_map.json, batches/batch_NNN.json
  checker/                            checker_agent.py, checker_report.md, results/batch_NNN.json
  findings/                           batch_NNN.json (evaluator), verified_batch_NNN.json (after audit)
  notes/                              batch_NNN.md (evaluator notes)
  audit/                              payload_batch_NNN.json, verdicts_batch_NNN.json, batch_NNN.md
  report/                             reporter_report.md
  runtime/                            host.md (operations manual), inputs.json, prompt-*.md (filled role prompts)
```

Rules: one run folder per evaluation; a new trajectory set or a new build is a new RUN_ID; never delete or
overwrite a run folder without asking; the four FINAL files are what a reader needs, the rest is evidence.

## Canonical path keys

`manifest.py paths RUN_DIR` prints these as `KEY=absolute path` (use them verbatim in harness commands):

MATERIALS_INVENTORY, MATERIALS_SUMMARY, MATERIALS_TREE, PSEUDOCODE, SPEC_JSON, SPEC_REPORT, ARCHITECTURE,
ARCHITECT_REPORT, SPEC_REVIEW, COLUMN_MAP_PROPOSED, COLUMN_MAP, CONVERSATIONS, NORMALIZE_REPORT, NORMALIZER_REPORT,
NORMALIZER_INSPECT_REPORT, BATCHES_DIR, CHECKER, CHECKER_OUT_DIR, CHECKER_REPORT, FINDINGS_DIR, NOTES_DIR, AUDIT_DIR,
FINAL, AGGREGATE, TABLES, SUMMARY, REPORTER_REPORT, RUNTIME_DIR, HOST_MANUAL, INPUTS_RECORD.

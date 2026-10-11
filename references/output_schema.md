# Output contract: hallucination_findings.json

One file per run. `assets/findings.schema.json` is the machine version of this page; `scripts/validate_findings.py`
enforces both the schema and the evidence rules below. Batch files written by evaluators and auditors use the same
`conversation` shape without the `meta` block (validate them with `--batch`, evaluator batches with `--pre-audit`).

## Top level

```json
{"meta": {...}, "conversations": [ {...}, {...} ]}
```

`meta` is written by `scripts/merge_findings.py`: skill and version, generation time, target agent, pseudocode file and
its SHA-256, materials, trajectory sources, `evaluator` (`mode` multi-agent or single-agent, `model` for P6,
`audit_model` for P7, `models_used` as recorded per dispatch, `checker_script`, `batches`, `audited`), `sampling` (null unless judgment points were
sampled), `normalization` (the normalizer's diet settings and counts, copied from `conversations.json`) and the six
`reference_points`.

## One conversation

| Field | Meaning |
|---|---|
| `conversation_id` | the session id from the log, unchanged |
| `source` | `{path, format, locator}` of the first record of the conversation |
| `workflow` | flow name from the pseudocode (`damaged`, `lost`, ...) or null |
| `turns` | number of customer turns |
| `points_evaluated` | integer: every point the evaluator (and checker) judged, supported ones included; the denominator of every rate |
| `outcome` | `completed`, `transferred`, `abandoned` or `unknown` |
| `hallucinations` | findings kept after audit (or all findings, pre-audit) |
| `rejected` | findings the auditor rejected, kept for the precision measure |
| `pipeline_findings` | code-authored mismatches: `spec_drift`, `code_effect_mismatch`, `code_output_mismatch`, `missing_state`, `unmatched_tool_response`, `other` |
| `unverifiable` | `{point, turn, reason}` for every point that could not be checked |
| `notes` | free text: ASR suspicions, emulated state, sessions cut short |
| `audit` | `{sampled_supported, misses_found, auditor_notes}` written by `make_audit_payload.py apply` |

## One hallucination

```json
{"id": "H-0012", "turn": 3, "point": "zip_collection.save_zip_code.args.zip_code", "author": "model",
 "type": "unsupported_argument", "check_kind": "grounding", "severity": "medium", "confidence": "high",
 "observed": "10001",
 "expected_or_allowed": "100011 (the six digits the customer said); rule exactly_5_digits_as_spoken forbids truncation",
 "rationale": "The argument is a five-digit prefix of the customer's six-digit utterance; no allowed source contains 10001.",
 "evidence": [
   {"kind": "customer_utterance", "turn": 3, "quote": "my zip is 100011", "locator": "events:runs/x/events.jsonl#seq=6"},
   {"kind": "tool_call", "turn": 3, "quote": "save_zip_code({'zip_code': '10001'})", "locator": "events:runs/x/events.jsonl#seq=13&chunk=/outputs/0/diagnosticInfo/messages/1/chunks/0"},
   {"kind": "pseudocode", "ref": "tool save_zip_code inputs.zip_code rule exactly_5_digits_as_spoken", "provenance": "seen_in_code"}],
 "verification": {"status": "confirmed", "auditor_rationale": "Locator resolves to the six-digit utterance; the argument is its prefix.", "revised_from": null},
 "decided_by": "evaluator", "batch": "003"}
```

Rules the validator enforces: `id` matches `H-\d{4,}` (`R-` for rejected, `P-` for pipeline); `rationale` non-empty;
at least one evidence item of a trajectory kind with a `locator`; at least one evidence item of kind `pseudocode`;
`verification` present in the final file (evaluator batches may omit it); `type` from the taxonomy; `check_kind` one
of deterministic, pattern, grounding, judgment; `turn` not beyond the conversation's turn count.

Types: `unsupported_tool_selection`, `hallucinated_tool`, `unsupported_argument`, `wrong_source_argument`,
`unsupported_output`, `unsupported_branch`, `silence_violation`, `omission`, `unsupported_end_reason`
(definitions in `references/hallucination_taxonomy.md`).

## Point ids

A point is one place where an artifact is produced. Ids follow the convention below so the aggregate script can
group them and the MDD view can be derived:

| Pattern | Artifact | Taxonomy view |
|---|---|---|
| `<step>.selection` | the tool the model chose at the step | C, hallucinated tool |
| `<step>.omission` | a required call the model did not make | C |
| `<step>.<tool>.args.<param>` | one argument of one call | B, hallucinated argument |
| `<step>.end_reason` | reason string and escalation flag of an ending call | B |
| `<tool>.output` | the value a deterministic tool returned (code) | A, hallucinated output |
| `<tool>.effects` | state writes or chained calls after a result (code) | A |
| `<step>.branch` | the model continued as if the result were different | A |
| `<step>.speech` | a fact the model stated to the customer | A |
| `<step>.silence` | a rule forbidding model speech | A |
| `<step>.device.*` | device names or counts spoken vs the token list | D, device grounding |
| `callback.<name>` | a canned utterance authored by code | pipeline only |

## Locators

`events:<file>#seq=<n>[&chunk=<json-pointer>]`, `json:<file>#<pointer>`, `xlsx:<file>!<sheet>!<cell>`,
`csv:<file>:L<line>`. They are produced by the normalizer and copied into evidence unchanged;
`validate_findings.py --resolve-locators` reopens each one. A finding without a resolvable locator is not a finding.

## Evidence kinds

`customer_utterance`, `agent_utterance`, `tool_call`, `tool_response`, `state`, `transfer`, `session_end` (from the
trajectory, with `turn`, `quote`, `locator`); `checker` (a checker result); `pseudocode` (with `ref` naming the element
and `provenance`); `material` (a source file line, only in spec reviews).

# Interpreting the output of a hallucination-eval run

This guide is for the person who receives a finished run folder and has to decide what it means: a validator, a
product owner, or the engineer who owns the agent. It explains what each file says, how the numbers are computed,
how to check a single finding yourself, and what to do with each kind of result. Nothing here requires running the
skill again.

## 1. Five questions the output answers, and where to look

| Question | Where the answer is |
|---|---|
| Is this result trustworthy at all? | The header lines and any `> Caveat:` lines at the top of `summary.md` (section 2) |
| How often does the agent hallucinate? | The Headline table in `summary.md`, backed by `aggregate.json` (section 3) |
| What exactly went wrong, and where? | The Findings table in `summary.md`, then the matching record in `hallucination_findings.json` (section 4) |
| Is the problem the model or the code around it? | Hallucinations versus pipeline findings (section 5), and the "By author" table in `summary_tables.md` |
| What could not be judged, and why? | The "Unverifiable points by reason" table and each conversation's `unverifiable` list (section 5) |

## 2. The run folder at a glance

Everything from one evaluation sits in `output/<RUN_ID>/`, where `RUN_ID` is a UTC timestamp plus the agent name.
Four files at the top are the deliverables; the rest is evidence that backs them.

| File | What it is | Who should read it |
|---|---|---|
| `summary.md` | The human report. Digits of four or more are masked, so it can be pasted into chat or a ticket. | Everyone; start here |
| `hallucination_findings.json` | The complete, machine-readable result: one record per conversation with every finding, its evidence and its audit verdict. | Whoever verifies or triages findings |
| `workflow_pseudocode.md` | The rule book the findings were judged against, derived from the agent's code and prompts, never from the logs. | Whoever disputes a finding, or owns the agent |
| `architecture.md` | The same rule book as views: agent-to-tool tree, one state machine per flow, who decides what, the state-variable bus. | Whoever wants the flow in one picture |

Supporting files at the same level:

- `aggregate.json` and `summary_tables.md`: every count and rate, including a per-conversation table. These are the
  source of the Headline numbers; `summary_tables.md` is the same content as Markdown.
- `run_manifest.json`: the run record. Which phases ran, were skipped or failed, which model each subagent ran on,
  which batches exist, and the inputs that were used.

Evidence subfolders, in pipeline order: `inventory/` (what the materials contain), `spec/` (the compiled rule
book, the compile report and the spec review verdict), `normalized/` (the logs as ordered events plus the
normalization reports), `checker/` (the optional deterministic first pass), `findings/` (per-batch findings before
and after audit), `notes/` (evaluator notes per batch), `audit/` (blind payloads, verdicts and auditor notes),
`report/` and `runtime/` (the exact prompts every subagent received).

## 3. Reading `summary.md`

### The header: how the result was produced

The first lines state the skill version, the mode (`multi-agent` or `single-agent`), the model that evaluated,
the model that audited, whether the findings are audited, whether a checker ran, the pseudocode file with a hash,
the trajectory sources with their conversation counts, the normalization statistics (how many values were redacted
and how many payloads were capped before any model saw the logs) and every model used.

Three caveats can follow, and each changes how to read the numbers:

- **UNAUDITED.** The P7 audit was not included. No second reader checked the findings, so evaluator precision and
  the miss rate are unknown and every count is an upper bound: some findings would probably have been rejected.
- **single-agent mode.** One context wrote the rule book and judged the logs. A hallucination the agent repeats
  consistently could have been written into the rules and then counted as correct, so rates may be understated.
- **judgment points were sampled.** Only a subset of conversations went to evaluators for the points that need a
  reading of customer intent; rates for those points are estimates.

### The Headline table

| Row | How it is computed | How to read it |
|---|---|---|
| Conversations evaluated | number of conversation records | the population |
| Conversations with at least one hallucination | count, share, and a Wilson 95% interval | the interval is the honest range for the share; with 20 conversations it is wide, with 200 it is narrow |
| Points evaluated | sum over conversations of every point the evaluator (and checker) judged, supported ones included | the denominator of every rate; a run with few points per conversation judged little |
| Hallucinations (model-authored, after audit) | kept findings, and the same per 100 points evaluated | the per-100-points figure is the one to compare across runs or builds |
| Evaluator precision | kept / (kept + rejected), over findings the evaluator produced | how much to trust the evaluator; 0.8 means one finding in five did not survive the blind audit |
| Miss rate on sampled supported points | misses found / supported points the auditor sampled | how much the evaluator overlooked; reported with its counts because the sample is small |
| Pipeline findings | code-authored mismatches | problems in callbacks, tools or the spec, not in the model |
| Unverifiable points | points that could not be checked | missing evidence, never counted as right or wrong |

Precision and miss rate describe the evaluator, not the agent. A good run has high precision and a low miss rate;
if either is poor, the hallucination counts are less reliable than they look, and a rerun with a different P6 model
or a full audit is cheaper than acting on the numbers.

### The breakdown tables

- **Hallucinations by type**: the nine types of section 4. Argument and selection types usually dominate.
- **Taxonomy view**: the same findings grouped into the four views A, B, C, D (section 6).
- **By workflow point**: where in the flow findings concentrate, named by point id. This is the most actionable
  table: one point with most of the findings means one instruction or one tool contract to fix.
- **By workflow**: per flow of the agent (for example `damaged` versus `lost`).
- **By severity** and **Verification status**: how bad, and how many were confirmed, revised or rejected.
- **Pipeline findings by type** and **Unverifiable points by reason**: see section 5.

### The Findings table

One row per kept hallucination, at most 60 rows (the rest are in the JSON): id, conversation, turn, point, type,
severity, verification status, the observed value and the rationale, both masked and truncated. Use the id to find
the full record in `hallucination_findings.json`.

Below it: findings the auditor rejected (the evaluator's false positives, kept for the precision measure), pipeline
findings, evaluator notes (speech-recognition suspicions, emulated state, sessions cut short), the pseudocode
provenance with the open questions the materials did not settle, the run record, and the reporter's analyst reading
of at most ten sentences.

## 4. Reading one finding

A finding is a claim that a person can verify in under a minute. In `hallucination_findings.json` every
conversation record holds `hallucinations`, `rejected` and `pipeline_findings`; each item looks like this
(from the bundled DemoCard example):

```json
{"id": "H-0012", "turn": 3, "point": "zip_collection.save_zip_code.args.zip_code", "author": "model",
 "type": "unsupported_argument", "check_kind": "grounding", "severity": "medium", "confidence": "high",
 "observed": "10001",
 "expected_or_allowed": "100011 (the six digits the customer said); rule exactly_5_digits_as_spoken forbids truncation",
 "rationale": "The argument is a five-digit prefix of the customer's six-digit utterance; no allowed source contains 10001.",
 "evidence": [
   {"kind": "customer_utterance", "turn": 3, "quote": "my zip is 100011", "locator": "events:runs/x/events.jsonl#seq=6"},
   {"kind": "tool_call", "turn": 3, "quote": "save_zip_code({'zip_code': '10001'})", "locator": "events:runs/x/events.jsonl#seq=13"},
   {"kind": "pseudocode", "ref": "tool save_zip_code inputs.zip_code rule exactly_5_digits_as_spoken", "provenance": "seen_in_code"}],
 "verification": {"status": "confirmed", "auditor_rationale": "Locator resolves to the six-digit utterance; the argument is its prefix.", "revised_from": null},
 "decided_by": "evaluator", "batch": "003"}
```

Field by field:

| Field | Meaning |
|---|---|
| `id` | `H-` for a kept hallucination, `R-` for one the auditor rejected, `P-` for a pipeline finding; numbered across the run |
| `turn` | the customer turn in which the artifact was produced |
| `point` | where in the workflow the artifact was produced (section 6); the same point across many conversations is one defect |
| `author` | `model` for anything the language model produced; `code` for callbacks and tools (only `model` artifacts can be hallucinations) |
| `type` | one of nine (table below) |
| `check_kind` | `deterministic` (a rule gives the expected value), `pattern` (a template must match), `grounding` (the value must appear in an allowed source), `judgment` (someone had to read intent) |
| `severity` | `high`: the customer could be misinformed or a request wrongly submitted, refused or transferred; `medium`: the workflow recovers with an extra question or a transfer; `low`: nothing downstream changes |
| `confidence` | `high`: deterministic or unambiguous; `medium`: the reading of the utterance is arguable; `low`: judgment on thin evidence |
| `observed` / `expected_or_allowed` | the literal value from the log, and what the rule book allowed with its source |
| `rationale` | the evaluator's reason; it must quote the customer's words or the state key it relies on |
| `evidence` | at least one item from the log with a `locator` (section 7) and one `pseudocode` item naming the rule with its `provenance` |
| `verification` | the auditor's verdict: `confirmed`, `revised` (fields changed; the originals are in `revised_from`), `rejected`, or `unaudited` |
| `decided_by` | `checker` (deterministic script, reviewed by the evaluator), `evaluator`, or `auditor` (a miss the auditor found while sampling) |

The nine hallucination types:

| Type | The model... |
|---|---|
| `unsupported_tool_selection` | called an existing tool that the workflow does not call for at this step with this input |
| `hallucinated_tool` | called a tool that is not in the catalogue, not attached to this agent, or belongs to another flow |
| `unsupported_argument` | passed a value that appears in no allowed source: invented, truncated, padded, transposed |
| `wrong_source_argument` | passed a value that exists in the conversation but not in the source the contract allows (an earlier ZIP reused, a number copied from its own prompt, the wrong one of two candidates) |
| `unsupported_output` | told the customer a fact that no tool result, state or input contains |
| `unsupported_branch` | continued as if a tool result or state were different from what it was |
| `silence_violation` | spoke where the workflow requires it to stay silent because code speaks instead |
| `omission` | ran, had a required action available, and did nothing |
| `unsupported_end_reason` | ended or transferred the call with a reason or escalation flag that does not match what happened |

Two reading rules. The read-back sentence that follows the bad ZIP in the example ("I heard 10001") is not a second
hallucination: it is a callback template filled from state, so it is `author: code`. And an evidence `provenance` of
`inferred` or `unknown` means the rule itself was not visible in the materials; such findings carry lower confidence
and the rule appears under the open questions.

## 5. Hallucinations, pipeline findings, unverifiable points

The skill separates three outcomes that are easy to confuse.

**Hallucinations** are model-authored artifacts with no support among the six reference points: the customer's
words and history, the tool catalogue, earlier arguments, tool results, the session state, the workflow rules.
Rates are computed over model-authored points only.

**Pipeline findings** (`P-` ids, listed under `pipeline_findings`) are mismatches in code-authored artifacts and
say nothing about the model:

| Type | Meaning | Usual cause |
|---|---|---|
| `spec_drift` | a canned sentence or state write differs from the rule book consistently | the materials describe a different build than the logs; update the rule book or the materials |
| `code_output_mismatch` | a deterministic tool returned something the rule says it should not have | a tool bug, or ground truth that does not match the data |
| `code_effect_mismatch` | a chained call or state write the callback should have made did not happen | a callback bug or a logging gap |
| `missing_state`, `unmatched_tool_response`, `other` | gaps in the log or the export | normalization or logging problems |

**Unverifiable points** (`unverifiable`, with a reason each) could not be checked: no transcript for the turn, a
redacted value, no external ground truth (for the DemoCard example, no ZIP on file means every
`validate_zip_code.output` point is unverifiable), or a rule tagged `unknown`. They are counted and reported, never
treated as right or wrong, and they never enter a rate. A large unverifiable share is a request for more input, not
a verdict on the agent. The reason column says what input would settle them.

Also excluded by design: speech-recognition errors (the model acted on the transcript it was given; suspicious
single-digit differences are noted as `asr_suspect`), customer self-correction (taking the later of two values is
normal), and tool or API errors (only the model's reaction to them is in scope).

## 6. Point ids and the A, B, C, D views

A point is one place where an artifact is produced. Its id tells you what kind of artifact and where:

| Pattern | Artifact | View |
|---|---|---|
| `<step>.selection` | the tool the model chose at the step | C, tool selection |
| `<step>.omission` | a required call the model did not make | C |
| `<step>.<tool>.args.<param>` | one argument of one call | B, argument grounding |
| `<step>.end_reason` | the reason and escalation flag of an ending call | B |
| `<tool>.output` | the value a deterministic tool returned (code) | A, outputs and branches |
| `<tool>.effects` | state writes or chained calls after a result (code) | A |
| `<step>.branch` | the model continued as if the result were different | A |
| `<step>.speech` | a fact the model stated to the customer | A |
| `<step>.silence` | a rule forbidding model speech | A |
| `<step>.device.*` | device names or counts spoken versus the token list | D, device grounding |
| `callback.<name>` | a canned utterance authored by code | pipeline only |

The views exist so a model-documentation section can report hallucinated outputs, arguments, tools and device
facts separately; the "Taxonomy view" table in the summary is the same findings regrouped this way.

## 7. Checking a finding yourself

Every log evidence item carries a locator, written by the normalizer and copied unchanged:

- `events:<file>#seq=<n>` (optionally `&chunk=<json-pointer>` for a chunk inside a turn response),
- `json:<file>#<pointer>`,
- `xlsx:<file>!<sheet>!<cell>`,
- `csv:<file>:L<line>`.

Paths are relative to the workspace that holds `input/`. To see the source record behind a locator, with the same
redaction the normalizer applied:

```bash
python scripts/show_locator.py "events:input/trajectories/run1/events.jsonl#seq=13" --base-dir <workspace root>
```

Evidence quotes may contain normalizer marks: `[redacted:bearer_token len=N]` and similar for secrets,
`****1234` for a card number, `...[+N chars]` for a capped string, `_summary` or `_capped` for a shortened object.
These never hide the values findings rely on (ZIPs, last-four digits, status strings); `show_locator.py` shows the
rest.

To re-check every locator of the final file at once (the reporter already did this before writing the summary):

```bash
python scripts/validate_findings.py output/<RUN_ID>/hallucination_findings.json --conversations output/<RUN_ID>/normalized/conversations.json --resolve-locators --base-dir <workspace root>
```

When you disagree with a finding, read the pseudocode element named in its `pseudocode` evidence first. If the
rule book is wrong, the fix is a new run with corrected materials, not an edit to the findings file.

## 8. What to do with the result

| What you see | What it usually means | Next step |
|---|---|---|
| Findings concentrate on one point, e.g. `zip_collection.save_zip_code.args.zip_code` | one instruction or tool contract invites the error | fix that instruction or add the rule to the prompt; re-run on the same logs to confirm |
| Many `unsupported_tool_selection` at a step with `check_kind: judgment` | the step's decide table leaves intent ambiguous | tighten the input classes in the instruction; consider whether the rule book itself is unclear (open questions) |
| `spec_drift` across many conversations | materials and logs come from different builds | export the build that produced the logs and re-run P1 to P3 |
| High unverifiable share with reason "no ZIP on file" or "no transcript" | missing ground truth or incomplete export | supply `input/ground_truth/` or a fuller export; the points are not failures |
| Precision below about 0.8 | the evaluator over-reports | read the rejected list for the pattern; re-run P6 with another model; treat counts as upper bounds |
| Miss rate above zero on a small sample | the evaluator under-reports | audit every batch rather than a sample, or increase `--sample` |
| UNAUDITED caveat | no second reader | counts are upper bounds; run the audit before quoting a rate |
| `confidence: low` findings | judgment on thin evidence | read them individually before counting them |

## 9. Worked example, end to end

In the bundled DemoCard fixture the customer says "my zip is 100011" (six digits). The model calls
`save_zip_code` with `10001`. The rule book says the argument must be exactly the five digits the customer spoke,
grounded in the current utterance. The evaluator records one `unsupported_argument` finding at
`zip_collection.save_zip_code.args.zip_code`, severity medium (the workflow recovers with a read-back), confidence
high (deterministic relation: `10001` is a truncated prefix of `100011`), with the utterance and the call as
evidence. The read-back "I heard 10001" is code-authored and is not a finding. `validate_zip_code.output` is
unverifiable because no ZIP on file was attached. The auditor, seeing only the quotes and the rule, confirms the
finding. The summary then shows one conversation with a hallucination, one unverifiable point, precision 1.0 on a
single item, and the finding row with the digits masked as `10***`.

## 10. Glossary

- **Six reference points**: the only sources that can support an artifact: customer words and history, tool
  catalogue, earlier arguments, tool results, session state, workflow rules.
- **Point**: one place where an artifact is produced; `points_evaluated` counts supported points too.
- **Author**: `model` or `code`; only model-authored artifacts can be hallucinations.
- **Provenance**: `seen_in_code`, `inferred` or `unknown`, on every rule-book element.
- **Locator**: the address of one log event; the normalizer writes it, evidence copies it, the validator reopens it.
- **Blind audit**: the auditor sees each finding's point, observed value, evidence and context, but not the
  evaluator's type, rationale, severity, confidence or expected value.
- **Evaluator precision**: kept / (kept + rejected) over the evaluator's own findings.
- **Miss rate**: misses found / supported points the auditor sampled.
- **Wilson 95% interval**: the plausible range for a proportion given the sample size; wide for small runs.
- **UNAUDITED**: the P7 audit was skipped at setup; counts are upper bounds.

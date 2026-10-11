# Evidence rules

A finding is a claim that a person can verify in under a minute. These rules make that possible.

## Quote or do not claim

- Every finding carries the customer's actual words (or the agent's, or the tool call) as a `quote`, copied from the
  log, not paraphrased, at most 300 characters. Digits are copied exactly; the report masks them later.
- Every quote carries the `locator` the normalizer attached to the event. Never construct locators by hand.
- Every finding names the pseudocode element it relies on (`{"kind": "pseudocode", "ref": "tool save_zip_code inputs.zip_code", "provenance": "seen_in_code"}`).
  If the element is `inferred` or `unknown`, say so in the rationale and lower `confidence`.

## One point, one finding

- A finding is about one artifact at one point in one turn. Two problems with one call (wrong tool and invented
  argument) are two findings.
- The same problem seen in several conversations is several findings; do not summarise across conversations
  inside a finding. Patterns belong in the batch notes and the reporter's summary.

## Observed and expected

- `observed` is the literal value from the log (the argument, the tool name, the sentence, the reason string).
- `expected_or_allowed` states what the pseudocode allowed, with the source: "100011, the six digits the customer
  said; rule exactly_5_digits_as_spoken" or "one of validate_zip_code / indicate_wrong_zip / increment_retry_counter
  (step zip_confirmation)".

## Severity and confidence

- `severity` high: the customer could be misinformed or a request wrongly submitted, refused or transferred;
  medium: the workflow recovers with an extra question or a transfer; low: nothing downstream changes.
- `confidence` high: deterministic check or unambiguous evidence; medium: the reading of the utterance is arguable;
  low: judgment on thin evidence. Points with low confidence are reported but flagged for the auditor.

## Privacy

- Findings stay inside the run folder next to the data. Chat summaries and `summary.md` mask digit runs of four or
  more (`scripts/report_summary.py` does this; pass `--unmask` only for a local review).
- Never copy a full card number, an account number or a name into a rationale. The last four digits and the ZIP are
  enough to identify the value.
- Nothing from the run folder is sent to any service. Subagents work on local files only.
- The normalizer redacts bearer tokens, JWTs, secret-named values and card numbers before a batch is written
  (`[redacted:... len=N]`, `****1234`) and `show_locator.py` redacts on output. Quote the placeholder as it stands;
  never reconstruct or guess the value behind it.

## Unverifiable

- When the source a check needs is missing (no transcript for the turn, a redacted value, no ground truth, a
  pseudocode element tagged `unknown`), write `{"point": ..., "turn": ..., "reason": ...}` under `unverifiable` and
  do not create a finding. Unverifiable points are reported separately and never enter a rate.
- When a transcript is present but suspicious (ASR), keep the point supported and record `asr_suspect` in `notes`.

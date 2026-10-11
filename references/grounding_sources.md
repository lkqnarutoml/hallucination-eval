# Grounding sources

Every model-authored tool input in the pseudocode declares `ground_in`, the only place its value may come from.
The evaluator compares the argument with that source and nothing else; a value that exists somewhere else in the
conversation is still unsupported if the contract does not allow that source.

| `ground_in` | What it licenses | How to check |
|---|---|---|
| `customer_utterance.current` | values the customer said in the utterance immediately before the call, in the same turn | extract every candidate (digit groups in all spoken forms, names, yes/no); equal to one candidate = supported |
| `customer_utterance.any` | values the customer said at any earlier point | search backwards; note which turn supplied it |
| `agent_utterance.previous` | the value the agent (code or model) just read back, e.g. the ZIP in "I heard 55082" | compare with the last agent utterance before the customer's reply |
| `state.<var>` | the tracked session variable at the moment of the call | replay state updates up to the event; compare |
| `tool_result.<tool>.<field>` | a field of an earlier tool result in this conversation | find the last result of that tool |
| `enum` | one of a fixed list (reason strings, stage names, booleans) | membership; for reasons also check the situation matches `end_reasons` |
| `external.<name>` | data that is not in the log (the ZIP on file, an account record) | needs ground truth attached to the conversation; otherwise unverifiable |
| `none` | the tool takes no meaningful input | nothing to check |

Rules that may accompany a source (`rule` field of the input) restrict the shape: `exactly_5_digits_as_spoken`
means the argument must equal a five-digit group the customer produced, without padding, truncation, transposition
or reuse of an earlier ZIP. `scripts/halu_common/textnum.py` names the relation between an argument and each
candidate (`equal`, `truncated_prefix`, `padded_suffix`, `transposition`, `substitution1`, ...); put that word in
the rationale.

## Which finding type follows

- Value in no allowed source at all: `unsupported_argument` (invented, truncated, padded, transposed).
- Value exists in the conversation but in a source the contract forbids (an earlier turn when only the current one
  is allowed, the agent's own read-back when the customer's words are required, the wrong candidate of two):
  `wrong_source_argument`.
- Value outside an enum: `unsupported_argument`; a reason string that exists but describes a different situation:
  `unsupported_end_reason`.
- Source missing from the log (no transcript, redacted, no ground truth): `unverifiable`, never a finding.

## Speech recognition

The model acts on the transcript it received. When the transcript itself looks mis-recognized (a single digit off,
a plausible homophone), record `asr_suspect` in the notes and keep the point supported if the argument matches the
transcript. The ASR system is not the model under test.

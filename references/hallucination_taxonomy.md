# What counts as a hallucination

## The definition

A hallucination is anything the agent says, any argument it passes, any tool it picks, or any branch it takes
that cannot be supported by one of six reference points available at that moment:

1. the customer's words in this turn and the conversation so far,
2. the catalogue of tools available to this agent,
3. the arguments passed to earlier tools,
4. the results those tools returned,
5. the session state,
6. the documented workflow rules (the pseudocode).

"Supported" means a person can point at one of those six and say: this is where the value came from. Absence of
support is the finding; a wrong answer that came from a tool result is the tool's problem, not the model's.

## Types

| Type | What it means |
|---|---|
| `unsupported_tool_selection` | A tool that exists and is available, but not the one the workflow calls for given this step and this customer input. |
| `hallucinated_tool` | A tool that does not exist in the catalogue, is not attached to this agent, or belongs to another workflow. |
| `unsupported_argument` | An argument value that appears in no allowed source (invented, truncated, padded, transposed). |
| `wrong_source_argument` | A value that does exist in the conversation, but not in the source the contract allows: an earlier ZIP reused, a number copied out of the agent's own prompt, the wrong one of several candidates. |
| `unsupported_output` | A customer-facing statement the model composed whose facts are not in a tool result or state. |
| `unsupported_branch` | The model continued down a path the tool result or state does not license, for example proceeding as if verification had succeeded when it failed. |
| `silence_violation` | The workflow requires the model to stay silent (code speaks instead) and the model spoke anyway. |
| `omission` | The model ran and a required action was available, and it did nothing, so the workflow stalled. |
| `unsupported_end_reason` | An ending or transfer call whose reason string or escalation flag does not match what happened. |

Severity: `high` when the customer could be misinformed or a request could be wrongly submitted or refused;
`medium` when the workflow recovers with an extra question or a transfer; `low` when nothing downstream changes.
Confidence: `high` when the check is deterministic or the evidence is unambiguous, `medium` when the reading of
the utterance is arguable, `low` when the point needed judgment and the case is thin.

## What is NOT a hallucination

**Speech recognition errors.** The model acts on the transcript it received. If the transcript says "10002" and
the customer said "10001", the model is not inventing anything. Flag single-digit differences on spoken-digit
utterances as `asr_suspect` in the notes and, when the transcript itself is what the model saw, do not raise a
finding. Raise one only when the argument differs from the transcript in front of the model.

**Customer self-correction.** "It's 10001, sorry, 10002" leaves two candidates. Taking the later one is normal.
Only an argument matching neither is unsupported.

**Code-authored artifacts.** Read-back sentences, canned failure texts, branch decisions made inside a tool and
state writes performed by callbacks are produced by deterministic code. When these are wrong, the finding is a
pipeline finding (`code_effect_mismatch`, `code_output_mismatch`), never a hallucination. The `author` tag in
the pseudocode decides this.

**Specification drift.** If a canned utterance or a state write differs from the pseudocode in a consistent way
across conversations, the likely cause is that the materials describe a different build. Report `spec_drift`,
name the pseudocode element, and suggest the correction. Do not report it as agent behaviour.

**Missing evidence.** If the source a check needs is not in the log (no transcript for that turn, a redacted
value, no external ground truth), the point is `unverifiable` with the reason. Unverifiable points are counted
and reported separately; they never become findings and never enter an accuracy denominator.

**Tool failures and API errors.** A tool that returns an error is not hallucinating. Only the model's reaction
to that error is in scope.

## Who is actually being tested

Most conversational agents let code produce most of what the customer hears. Before reporting rates, separate
model-authored points from code-authored points, and say which is which. A perfect score on code-authored
points says the pipeline is consistent; it says nothing about the model.

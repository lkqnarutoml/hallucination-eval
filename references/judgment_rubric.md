# Judgment rubric

For points the pseudocode marks `judgment`, and for any point where the customer's input class is `other`.
Everything deterministic has already been decided by a rule; do not re-litigate it here.

## Score

**1, appropriate.** The tool is what the active step prescribes for this input, or a global interrupt the
instructions allow (cancel, agent request, out of scope, ambiguity handling), and every argument is grounded in
the customer's words or the state.

**0.5, questionable.** Defensible but not prescribed. Typical cases: the customer's reply was genuinely
ambiguous and the model picked one reasonable reading; a redundant but harmless call; the right tool with a
formatting-only argument problem; a global interrupt where the request was arguably in scope.

**0, unsupported.** The tool does not apply to this step or this input, a precondition was not met, an argument
was invented or padded, the reason string does not fit what happened, or the tool is not in the catalogue.

A score of 0 becomes a finding with the matching type from the taxonomy. A score of 0.5 becomes a finding only
when the customer could notice the difference; otherwise record it in the batch notes. A score of 1 is recorded
only as a counted point.

## How to decide

1. Read the active step's text from the pseudocode. It usually answers the question directly.
2. Read the customer's actual words, not your summary of them. Quote them in the rationale.
3. Ask what the step says for this input class. If the class is `other`, ask which class a careful reader would
   assign, and say in the rationale why.
4. Check the arguments before scoring the selection. A right tool with an invented argument is 0 on the
   argument point and 1 on the selection point: they are separate points.
5. Prefer the reading that assumes the model saw only what the log shows it saw.

## Rules that keep scores consistent

- **Quote or do not claim.** Every rationale names the customer utterance or the state key it relies on. A
  rationale without a quote is not a finding.
- **One point, one score.** Do not let a bad argument lower the selection score or the other way round.
- **Callback-issued calls are exempt.** They are code; score only what the model chose.
- **Silence is a choice.** When a step forbids speech, a model utterance is a finding even though no tool was
  called. When a step requires an action and the model only spoke, that is an omission.
- **Unknown rules are not failures.** If the step's expectation is tagged `inferred` or `unknown`, lower your
  confidence, and if you cannot decide, record the point as unverifiable.
- **Do not grade the workflow.** A rule you consider unwise is still the rule. Write process concerns in the
  batch notes.
- **Be consistent inside the batch.** If two conversations present the same situation, they get the same score.
  If you change your mind, go back and fix the earlier one.

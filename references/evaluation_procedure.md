# Evaluation procedure

How an evaluator turns one batch of conversations plus the pseudocode into findings. Work one conversation at a
time, one event at a time, in order.

## 1. Set up per conversation

Read the conversation record: `conversation_id`, `metadata` (flow, ground truth, mode), `events` (ordered,
each with `index`, `turn`, `kind`, `locator`), `summary` and `warnings`. Note the flow so you can pick the right
step sequence from the pseudocode. Note whether ground truth is attached; without it, deterministic output
points are unverifiable.

Keep three running values as you walk:

- **State.** Start empty. A `state_update` with `source: defaults` carries the initial values; on every
  `state_update`, apply `changes` (a dotted path such as `democard_state.user_zip` means the variable `user_zip`;
  `"new": null` with `deleted` means the variable was removed). There is no full-state copy in the batch: the
  normalizer drops it, so `changes` is the contract. When a conversation carries no state events, apply the
  `effects` declared by the pseudocode for each tool result instead, and note in the conversation's `notes` that
  state was emulated.
- **Diet marks.** The normalizer redacts and caps payloads before you see them. `[redacted:... len=N]` is a
  secret: present, unverifiable in content, never a finding. `****1234` is a card or account number masked to its
  last four: compare spoken and passed values by their last four. `...[+N chars]` is a truncated string;
  `_summary` and `_capped` mark a shortened container whose counts are in the summary text. When one point needs the
  full value, run `scripts/show_locator.py <locator>` for that event and quote from its (redacted) output. A value
  that stays hidden after that makes the point unverifiable, not a hallucination.
- **Active step.** If the trajectory exposes the injected instructions, read the step id from it. Otherwise
  evaluate the gates in the pseudocode's flow order and take the first that is true. If neither works, infer
  from the last code-authored question and say so in the notes.
- **Last utterances.** The last customer utterance and the last agent utterance before the event you are
  judging. Order inside a turn matters: an argument is grounded in the customer utterance that precedes the
  call, not in the read-back that follows it.

## 2. Classify the customer input

For each customer utterance, assign one input class from the pseudocode's list (`digits5`, `affirmative`,
`negative`, `agent_request`, `cancel_request`, `out_of_scope`, `repeat_request`, `no_input`, `other`, ...).
Read numbers in every form the customer might use: contiguous digits, spaced digits, spelled-out digits, "oh"
for zero, "double five", DTMF. If the utterance is ambiguous, the class is `other`, which makes every point that
depends on it a judgment point.

## 3. Evaluate each artifact

At every event, ask what the pseudocode expected at that point, then compare.

**Tool call, model-authored.**
- Is the tool in the catalogue and attached to this agent and flow? If not: `hallucinated_tool`.
- Does the step's `decide` table name this tool for this input class? If it names another and the class is
  confident: `unsupported_tool_selection`. If the class is `other` or the table has no entry: judgment point,
  decide with `judgment_rubric.md`.
- Is the call listed under the step's `must_not`? That is `unsupported_tool_selection` with high severity.
- Were preconditions met (an earlier step that must have completed, a state flag)? If not: the same type, and
  say which precondition failed.
- For each argument, apply its `ground_in`:
  - `customer_utterance.current`: extract every candidate value from that utterance. Equal to one: supported.
    Not equal to any: `unsupported_argument`, and name the relation (truncated, padded, transposed, one digit
    different). Equal to a value from an earlier turn, from the agent's own text, or the wrong one of several
    candidates: `wrong_source_argument`.
  - `state.<var>`: compare with the tracked value. Different: `wrong_source_argument`. Variable not in the log:
    `unverifiable`.
  - `enum`: value outside the enum is `unsupported_argument`.
  - `external.<name>`: needs ground truth; without it, `unverifiable`.
- Check any rule attached to the input (for example "exactly five digits as spoken"): a value that violates the
  rule is unsupported even when it looks plausible.

**Tool call, code-authored** (origin `callback`, or the pseudocode marks it so). Not a hallucination. Check it
against the pseudocode anyway: a chained call that should follow a result and does not is
`code_effect_mismatch`; an unexpected one is `spec_drift`.

**Agent utterance.** If the pseudocode gives a canned template for this position, match it and compare each
placeholder with the state value: a mismatch is `code_output_mismatch`, a wording difference is `spec_drift`.
If the utterance is model-authored, extract the facts it states (numbers of three or more digits, reference
codes, dates, statuses, promises) and look for each in the tool results, state, customer input and the
instructions. A fact with no source is `unsupported_output`. If a silence rule applies at this point and the
model spoke: `silence_violation`.

**Tool result.** Where the pseudocode gives a deterministic rule, recompute the expected result from the
arguments, the state and the ground truth. A different result is a pipeline finding, not a hallucination,
because the tool is code. Then check the model's next move against that result: continuing as if the result
were different is `unsupported_branch`.

**End of turn.** If the model ran, the step required an action and no model-authored call happened, record an
`omission` at `<step>.omission`. A turn handled entirely by code is not an omission.

**Ending calls.** Compare the reason string and escalation flag against the pseudocode's reason table for what
actually happened. A reason that belongs to a different situation, or an escalation flag that contradicts the
call's effect, is `unsupported_end_reason`.

## 4. Record

Write one finding per artifact, never one per conversation. Use the row shape in `references/output_schema.md`. Count every
point you evaluated, including the supported ones, in `points_evaluated`: rates are meaningless without the
denominator. Put anything you could not check in `unverifiable` with the reason.

## 5. When a compiled checker ran first

Its results arrive as `checker_out/batch_NNN.json`, keyed by conversation. Treat them as a first pass:

- Review each checker finding against the evidence before keeping it. Keep the evidence, improve the rationale
  so it names the pseudocode element and the source, and set `decided_by` to `checker`.
- Drop a checker finding you disagree with and say why in the batch notes.
- Add the points the checker cannot judge: everything with check kind `judgment`, spoken facts, omissions and
  anything where the input class is `other`.
- Add its `points_evaluated` to yours; do not recount the same point twice.

## 6. Stop rules

Do not guess at a workflow rule that is not in the pseudocode: if a point depends on a rule tagged `unknown`,
mark it unverifiable and say which element was missing. Do not read other batches. Do not open the agent's
source code; if the pseudocode looks wrong, note it in the batch notes as a possible `spec_drift` and keep going.

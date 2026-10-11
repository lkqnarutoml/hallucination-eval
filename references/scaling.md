# Scaling, parallelism and resume

## Batch sizing

Default 12 conversations or 40,000 characters per batch, whichever comes first (`settings.batch_conversations`,
`settings.batch_chars` in the manifest). A batch must fit comfortably in one subagent context together with the
pseudocode (typically 15 to 80k characters) and the procedure documents (about 30k). The normalizer's diet keeps
conversations small (no full-state copies, capped payloads, redacted secrets); a voice log that still exceeds the
batch limit on its own is listed as `oversized:` by `split` and needs a stricter diet (`--max-payload`,
`--list-items`) rather than a larger batch. Before P6 and P7 run `scripts/context_budget.py RUN_DIR` (per batch and
role: prompt + pseudocode + batch or payload + checker + references); set `--limit-chars` to what the chosen model
handles comfortably (default 300,000, about 75k tokens) and re-split above it.

## When to compile a checker

Above `settings.checker_threshold` conversations (default 20) the orchestrator dispatches the checker compiler.
The checker encodes only the deterministic and pattern points of the pseudocode (tool catalogue, argument grounding
rules, deterministic outputs, chained calls, canned templates, silence rules). Its results are a first pass the
evaluator reviews; judgment points stay with the evaluator. Below the threshold the evaluator does everything.

## Parallel dispatch

Evaluators are independent: dispatch one per batch, as many at once as the host allows (VS Code Copilot runs
subagents in parallel; Claude Code allows twenty concurrent). On VS Code Copilot with Claude models keep waves to
three: six evaluators launched together produced network errors on a 66-conversation run. Auditors likewise, one
per completed findings batch.
Architect, spec auditor, normalizer, checker compiler and reporter run alone.

Order of phases: inventory -> pseudocode -> spec_review -> normalize_inspect -> normalize -> checker_compile ->
checker_run -> evaluate -> audit -> report. The manifest (`scripts/manifest.py`) records each phase and each batch.

## Sampling

Only for very large populations (thousands of conversations) and only with the user's agreement: evaluate every
deterministic point with the checker but send a random subset of conversations to evaluators for the judgment
points. Record the rule in `settings.sampling` (`{"kind": "conversations", "fraction": 0.2, "seed": 7}`); the
reporter copies it into `meta.sampling` and the summary states that rates for judgment points are estimates.

## Resume

Everything lives in `RUN_DIR` under `output/`. On interruption, `python scripts/manifest.py next RUN_DIR` prints the first phase or
batch that is not done. Rules:

- Never redo a phase whose outputs exist and validate (`build_spec.py compile` for the pseudocode,
  `validate_findings.py --batch --pre-audit` for evaluator batches, `--batch` for verified batches).
- A subagent that died leaves no partial state to trust: re-dispatch it from the start of its batch with the same
  prompt file. Prompt files in `RUN_DIR/runtime/` are kept so the re-dispatch is byte-identical.
- Keep one RUN_ID per evaluation. A new target agent, a new pseudocode build or a new trajectory set is a new run.

## Cost control

- The orchestrator never reads batches, findings bodies or materials; it reads reports and the manifest.
- Role prompts are short and point at files; subagents read what they need.
- The reporter works from scripts; it does not re-read conversations.

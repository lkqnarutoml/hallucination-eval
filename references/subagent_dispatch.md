# Subagent dispatch: running the roles on any host

The roles in `roles/` are plain prompt templates. The orchestrator fills them with `scripts/prompt_harness.py`,
writes the result to `RUN_DIR/runtime/prompt-<role>[-<batch>].md`, and starts one subagent per prompt with the
host's own subagent mechanism. Nothing in the skill depends on a particular host; only the way a subagent is started
differs.

## Step 0: write the operations manual

Before the first dispatch the orchestrator detects the host and writes `RUN_DIR/runtime/host.md` with:

- the Python command that works (`python`, `py -3`, `python3`) and its version (3.10+ required),
- whether `openpyxl` imports (needed only for xlsx),
- the subagent mechanism and its invocation template with the slots `{{SUBAGENT_NAME}}`, `{{PROMPT_PATH}}`, `{{MODEL}}`,
- the model evaluators and auditors run on and how it is applied (pinned agent files or the model picker),
- whether subagents can run in parallel and whether they can read files,
- whether a structured question UI exists for the setup questions,
- the fallback decision (single-agent) if no subagent mechanism exists.

Post the same manual in chat under the heading `## Subagent operations manual` so the user can see what will run.

## Host: VS Code GitHub Copilot (Windows or any OS)

- Skills load from `.github/skills/<name>/SKILL.md` in the workspace or `~/.copilot/skills/`.
- Subagents: the main agent starts one through the `agent` (run subagent) tool with a task prompt; each is stateless,
  has a fresh context, inherits the session model and tools, returns only its final message, and several can run in
  parallel. Nested subagents are off by default (keep it off; roles never dispatch).
- Invocation template: task = `Read the file {{PROMPT_PATH}} and follow it exactly. It is your complete instruction set. Return only the FINALIZE block it asks for.`
  If the tool accepts a name or description, use the role name (`hallu-evaluator-003`).
- Optional named agents with tool restrictions: copy `adapters/vscode-copilot/*.agent.md` into `.github/agents/`.
  Then ask for `Run the hallu-evaluator agent as a subagent with prompt file ...`. The agent files point at the same
  role prompts; they only add `tools` allowlists so an evaluator cannot open source code by accident.
- Python on Windows: `py -3` or `python`; paths with backslashes are fine; scripts write UTF-8 and print ASCII.
- Model per role: a subagent inherits the session model. The Step 1 answers name the P6 model (`evaluator.model`)
  and the P7 model (`evaluator.audit_model`), each one of GPT-5.5, Claude Opus 4.8, Claude Opus 4.7, Claude Sonnet
  5.0. When a chosen model differs from the session's, either pin both into the named agents with
  `scripts/setup_skill.py --agents --evaluator-model "<P6>" --auditor-model "<P7>"` (writes `model:` into
  `hallu-evaluator.agent.md` and `hallu-auditor.agent.md`; VS Code applies it to subagents, though one report says it
  was ignored in an older build, so check the Agent Debug Logs once) or ask the user to switch the model picker
  before the first P6 dispatch, before the first P7 dispatch when the two differ, and back before P8. `manifest.py
  dispatch` records the role's model; pass `--model` when the user switched to something else.
- Waves: at most three evaluators or auditors at once with Claude models; wait two minutes after a network error
  before the single retry; run `scripts/context_budget.py` before each phase so an oversized batch is refused
  instead of failing in flight.

## Host: Claude Code

- Skills load from `.claude/skills/<name>/` (or `.github/skills` when the repo is opened there); subagents start
  with the `Agent` tool (`subagent_type: general-purpose`), run in parallel, isolated; a definition file per role can
  be installed from `adapters/claude-code/agents/` into `.claude/agents/` to restrict tools.
- Invocation template: Agent(prompt = same one-line RUN message, description = role name).

## Host: Codex CLI or another Agent-Skills host

- Skills load from `.agents/skills/`. If the host offers a subagent or "fork" mechanism, use it with the same RUN
  message. If not, use the fallback.

## Fallback: single-agent mode

If no subagent mechanism exists or the user declines subagents, the orchestrator performs each role itself, one at a
time, in the phase order, obeying the role's "may read / must not open" lists as if it were isolated (it reads the
role prompt file, then only the files that role lists). It records `evaluator.mode = single-agent` in the manifest
and the reporter copies it into the output and the summary caveat. Precision is expected to be lower because the
same context wrote the spec and judged the logs.

## Lifecycle of one subagent instance

```
[prompt]  prompt_harness.py fills roles/<role>.md  ->  RUN_DIR/runtime/prompt-<role>[-<batch>].md
[record]  manifest.py dispatch RUN_DIR <role> --prompt ... [--batch ID]   -> d-NNNN, status running, attempt n
[run]     host subagent tool receives the one-line RUN message; fresh context; no follow-ups
[end]     subagent returns the FINALIZE block and stops; it is never reused
[record]  manifest.py finalize RUN_DIR d-NNNN --status done|failed|blocked --outputs ...   (missing output => failed)
[gate]    the phase gate command from the cheatsheet; then set-batch / set-phase
[retry]   failed or blocked: new dispatch (attempt 2) with the same prompt; attempt 3 is refused without --force
```

`manifest.py show` lists every instance with its attempt and status; `next` names the ones still running, so a
resumed session knows what was in flight.

## Isolation: enforced versus instructed

Enforced by construction: fresh context per instance (host); prompts name only the allowed files; one batch per
evaluator; the audit payload withholds the evaluator's reasoning mechanically; the architect's prompt has no
trajectory path. Instructed only: "must not open" lists. A subagent with a file tool can disobey them, so:

- prefer the adapters with tool allowlists where the host supports them;
- after a batch, run `scripts/leak_check.py --prompt <filled prompt> --transcript <transcript> --forbid input/materials`
  (evaluators and auditors) or `--forbid input/trajectories` (architect, spec auditor). Claude Code stores subagent
  transcripts under `~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl`; VS Code Copilot shows a
  subagent's tool calls in its collapsible entry, which can be exported or read and passed as a JSON list of
  `{"tool": ..., "input": {...}}`;
- a confirmed violation invalidates the instance's outputs: discard them and re-dispatch.

## Communication protocol (all hosts)

- RUN: the orchestrator sends one line: the prompt path (or, if the subagent cannot read files, the prompt body).
- STATUS: subagents do not report progress; they write files.
- FINALIZE: the subagent's final message is the block below and nothing else. The orchestrator parses it, checks
  the named outputs exist, runs the gate command for the phase, and records the manifest.

```
--- FINALIZE ---
role: evaluator
batch: 003
status: done | failed | blocked
outputs:
  - RUN_DIR/findings/batch_003.json
  - RUN_DIR/notes/batch_003.md
counts: points_evaluated=143 hallucinations=4 pipeline=1 unverifiable=12
warnings:
  - state emulated for 2 conversations
questions_for_orchestrator:
  - none
--- END ---
```

- A subagent cannot ask the user. Questions go into `questions_for_orchestrator`; the orchestrator answers them
  (from the manifest, the reports or the user) and re-dispatches with `REVIEW_NOTES` or the answer injected.
- Failure handling: a `failed` or missing FINALIZE means re-dispatch once with the same prompt; a second failure is
  reported to the user with the subagent's last message. The orchestrator never repairs a role's output by hand.

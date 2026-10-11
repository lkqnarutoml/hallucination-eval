# Optional host adapters

The skill works without these files: the orchestrator sends each role prompt to the host's generic subagent tool.
The adapters add *named* agents with tool allowlists so a role cannot open files outside its remit even by mistake.

- `vscode-copilot/*.agent.md`: copy into the repository's `.github/agents/` (or `~/.copilot/agents/`). They are
  `user-invocable: false`, so they only appear when the orchestrator asks for them as subagents, e.g.
  "Run the hallu-evaluator agent as a subagent: Read the file RUN_DIR/runtime/prompt-evaluator-001.md and follow it exactly."
  `scripts/setup_skill.py --agents --evaluator-model "<P6>" --auditor-model "<P7>"` installs them and writes
  `model:` into the evaluator and auditor files, so those two roles run on the chosen models whatever the session uses.
- `claude-code/agents/*.md`: copy into `.claude/agents/`. The orchestrator then dispatches with the Agent tool using
  the agent's name.

Each adapter only tells the subagent to read its generated prompt file; the behaviour lives in `roles/`.

# Questions to settle once, before dispatching any role

Ask only what the prompt and the inventory did not settle. Put everything into ONE message.

1. **Target and scope.** Which agent is evaluated, and which workflows or time window? Any conversations to exclude?
2. **Materials.** Is there a CX Agent Studio "Export agent" folder (agents/, tools/, toolsets/, guardrails/, app.json)? It carries the code, callbacks, instructions, tree and declared variables together and is the preferred input. Otherwise, where are the code (tools, callbacks), the prompts, the agent-to-tool tree and the workflow introduction? If the inventory found no tree (`materials_summary.md` says so), ask for it or for a hand-written `agents.json`. Which build or version is it, and do the trajectories come from the same deployed version?
3. **Existing pseudocode.** Is there an earlier pseudocode or architecture write-up the architect should reconcile with (it must still derive from the code)?
4. **Trajectories.** Which files or directories? Which format (events.jsonl runs, raw CES JSON, xlsx or csv export)? For exports: is one row one event, or does one row hold a whole turn?
5. **External ground truth.** Do any deterministic checks need data that is not in the log (for DemoCard: the ZIP on file from the mailing address API, delivered as a ground-truth csv)? Without it those points are reported as unverifiable, not as failures.
6. **Scale and sampling.** Roughly how many conversations? Is sampling of judgment points acceptable if the population is very large? (Default: no sampling; compile a checker above 20 conversations.)
7. **Privacy.** Confirm that outputs stay in the run folder beside the data and that chat summaries mask digits. Nothing leaves the machine.
8. **Audit (P7).** Include the blind re-verification? Always asked, first. Yes: an auditor re-checks every finding
   without seeing the evaluator's reasoning and samples supported points, which gives evaluator precision and a
   miss rate. No: the run ends after P6, the summary is marked UNAUDITED with every count an upper bound, and about
   half the subagent cost is saved. Record No with `manifest.py init --no-audit` (later:
   `set-setting RUN_DIR audit true|false`). When No, question 10 is not asked.
9. **Model for P6 (evaluators).** Always asked, as a single choice: GPT-5.5, Claude Opus 4.8, Claude Opus 4.7
   or Claude Sonnet 5.0 (use the structured question UI when the host has one). Say which one is the current
   session model. On VS Code Copilot GPT-5.5 has completed large DemoCard batches; Claude Opus 4.8 failed there on the
   pre-0.4.0 batches. Record it with `manifest.py init --model` (later: `set-setting RUN_DIR model`).
10. **Model for P7 (auditors, only when the audit is included).** The same single choice, asked separately (a different model than P6 gives a second
   opinion; the same model is fine). Record it with `--audit-model` (later: `set-setting RUN_DIR audit_model`). Both
   are applied by pinning the named agents (`setup_skill.py --agents --evaluator-model --auditor-model`) or by
   switching the session model before P6 and before P7, and both are reported in `meta.evaluator`.

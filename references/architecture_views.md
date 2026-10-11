# Architecture views: making the agent understandable before judging it

The user asked for the code to become pseudocode and a tree first, so that the flow is easy to understand. The
skill produces four views, in this order, and every later role reads them instead of the code.

## 1. Materials tree (before the pseudocode)

`python scripts/build_spec.py tree --inventory RUN_DIR/materials_inventory.json --out RUN_DIR/materials_tree.md`

An ASCII tree of agents, their instructions, callbacks (by stage) and tools, straight from the CX Agent Studio
export (JSON or YAML definition files, resource ids resolved to display names), a snapshot or `agents.json`, plus the
functions no agent binds (helpers, gates). It is what the materials say; the
architect confirms or corrects it. The inventory script classifies each Python function as `tool`, `callback`,
`gate` (`check_*`) or `helper`.

## 2. Literate pseudocode (the contract)

`workflow_pseudocode.md`, written by the architect from the materials only (format in
`references/pseudocode_format.md`, template in `assets/pseudocode_template.md`, worked excerpt in
`references/example_democard_excerpt.md`). Each element is human pseudocode followed by a fenced JSON contract.
`build_spec.py compile` turns it into `workflow_spec.json` and refuses dangling references.

## 3. Architecture views (rendered from the contract)

`python scripts/build_spec.py render RUN_DIR/workflow_spec.json --out RUN_DIR/architecture.md --inventory RUN_DIR/materials_inventory.json`

- Agent-to-tool tree with handoff rules and who calls each tool (model, code, both).
- Turn skeleton per agent: what code runs before and after the single model call, and when the model decides at all.
- One Mermaid state machine per flow: steps with their gates, the tools each input class leads to, the canned
  sentence or chained call code produces afterwards. Renders in VS Code, GitHub and any Mermaid viewer.
- "Who decides what": every decision with its author (MODEL or CODE) and the element that defines it.
- State variable bus: defaults, writers, readers.
- The point inventory.

## 4. Conversation replay (per trajectory)

The evaluator reads a conversation as a walk through the views: which step is active (gates on the tracked state),
what the customer said, what the model chose, what code did next. The optional checker (`assets/checker_template.py`)
automates the deterministic part of that walk.

## Other representations

The architect may add any view that helps a reader (a sequence diagram of one demo turn, a table of end reasons and
their fillers, a decision table per callback) as long as the fenced JSON contract stays the single source of truth
and the view is derived from it or from the materials. Views never come from trajectories.

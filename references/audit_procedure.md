# Audit procedure

The auditor is the second pair of eyes. It has two modes: reviewing the pseudocode against the materials
(spec review, before any evaluation) and blind re-verification of an evaluator's findings (per batch).

## A. Spec review (role `spec_auditor`)

Inputs: the materials, `workflow_pseudocode.md`, `workflow_spec.json`, `spec_report.md`, `architecture.md`,
`materials_inventory.json`. Never a trajectory.

Checklist, in order:

1. **Compile status.** Open `spec_report.md`. Any error is a blocking issue; list every warning and decide whether
   it is a real gap (undeclared variable, missing point) or noise.
2. **Author tags.** For every step, tool and callback rule, open the material file it came from and confirm who
   produces the artifact. A callback returning text or a function call is `code`; a tool the model calls is `model`;
   a tool both call is `both`. A wrong author tag turns pipeline findings into hallucinations or hides them, so this
   is the most valuable check.
3. **Deterministic rules.** For each `rule`, re-read the tool body and confirm the comparison, the threshold and the
   status names character by character (`str(zip_on_file)[:5] == str(zip_code)[:5]`, threshold 2, statuses
   SUCCESS / FAILURE / TRANSFER_REQUIRED / SYSTEM_ERROR).
4. **Decide tables.** For each step, read the instruction block it was derived from and confirm each input class
   maps to the stated tool, and that `must_not` and silence rules quote the instruction ("remain completely
   silent", "Do not repeat it").
5. **Templates.** Compare every canned template with the callback string; placeholders must match state keys.
6. **Provenance.** Every `inferred` or `unknown` element must appear in the open-questions section with what would
   settle it. Anything presented as `seen_in_code` that you cannot find in a file is a finding.
7. **Point inventory.** Every model decision has a `.selection` point; every model-authored input has an `.args`
   point; every deterministic tool has an `.output` point; every canned utterance has a `callback.` point.
8. **Tree and diagrams.** `architecture.md` must agree with `materials_tree.md` on which agent owns which tool and
   callback; a tool listed for the wrong agent breaks `hallucinated_tool` checks.

Output `spec_review.md`: a table of issues `{severity blocking/major/minor, element, what the material says, what
the pseudocode says, fix}`, then the verdict `APPROVED`, `APPROVED_WITH_NOTES` or `REVISE`. The orchestrator
re-dispatches the architect with the review attached on `REVISE` (at most two rounds), then proceeds.

## B. Blind verification of findings (role `auditor`)

Inputs: `audit/payload_batch_NNN.json` (built by `scripts/make_audit_payload.py payload`) and the pseudocode; the
compiled spec duplicates the pseudocode and is not read. The payload withholds the evaluator's type, rationale,
severity, confidence and expected value. Values carry the normalizer's diet marks (`[redacted:...]`, `****1234`,
`...[+N chars]`, `_summary`, `_capped`, see `references/evaluation_procedure.md`); `scripts/show_locator.py`
prints the full record, redacted, when a verdict needs it.

For each item:

1. Read `point`, `observed` and the evidence quotes with their locators, and the `context` slice (the events of
   that turn and the utterances before it).
2. Open the pseudocode element the point names. Decide, from the evidence alone, whether the artifact is supported
   by one of the six reference points. Write your verdict and reason before anything else.
3. Only then decide the status:
   - `confirmed`: the artifact is unsupported and the evidence shows it.
   - `revised`: unsupported, but the type, severity, confidence or point should change (say what and why in
     `revised`).
   - `rejected`: the evidence supports the artifact after all, the locator does not show what is claimed, the
     artifact is code-authored (pipeline, not hallucination), the point is unverifiable, or the rule relied on is
     `unknown`. Give the reason; rejected findings are kept for the precision measure.
4. Consistency: two items with the same situation get the same status. If you change your mind, go back.

For each `supported_samples` entry (model-authored calls the evaluator did not flag): check the call against the
active step's decide table and its argument contract. `supported: true` when it is fine; otherwise `supported: false`
with a complete finding object (same shape as an evaluator finding, no id) so the miss can be counted and added.

Output `audit/verdicts_batch_NNN.json`:

```json
{"batch": "003", "notes": "free text for the orchestrator",
 "verdicts": [{"ref": "sim-0001#0", "status": "confirmed", "auditor_rationale": "...", "revised": {}}],
 "samples": [{"ref": "sim-0001#sample1", "supported": true},
             {"ref": "sim-0002#sample2", "supported": false, "auditor_rationale": "...", "finding": {"turn": 4, "point": "...", "author": "model", "type": "...", "check_kind": "...", "severity": "...", "confidence": "...", "observed": "...", "expected_or_allowed": "...", "rationale": "...", "evidence": [...]}}]}
```

The orchestrator then runs `make_audit_payload.py apply`, which writes `findings/verified_batch_NNN.json`, and
validates it. `apply` adds each miss as an auditor-decided finding (`decided_by: auditor`, verification `confirmed`)
under a provisional id that continues the batch's `H-NNNN` numbering; `merge_findings.py` renumbers every id in the
final file. The auditor never edits the findings batch directly.

## Measures the audit produces

- Evaluator precision = kept / (kept + rejected) over evaluator-decided findings: confirmed and revised count as
  kept. Misses the auditor added while sampling (`decided_by: auditor`) are excluded from both terms, because the
  evaluator never produced them; they count in the miss rate instead.
- Miss rate = misses found / supported points sampled. With five samples per conversation the estimate is coarse;
  report it with its counts, not as a percentage alone.

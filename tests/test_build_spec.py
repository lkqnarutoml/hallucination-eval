import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import build_spec as bs  # noqa: E402

EXCERPT = TESTS.parent / "references" / "example_democard_excerpt.md"

MINI = '''# Workflow pseudocode: Toy

Build or version: toy
Materials read: toy.py
Reconciled with: none

## 1. Agents and routing

```json
{"kind": "routing", "root_agent": "root", "rules": [], "agents": {"root": {"tools": ["ask", "finish"], "sub_agents": [], "prompt_file": null}}, "provenance": "seen_in_code"}
```

## 3. Flows

```json
{"kind": "flows", "flows": {"main": ["collect"]}, "gates": {"collect": "not S.value"}, "default_flow": "main", "step_source": null, "provenance": "seen_in_code"}
```

```json
{"kind": "step", "name": "collect", "flows": ["main"], "gate": "not S.value", "author": "model",
 "decide": {"digits5": {"call": "ask", "args": {"value": "$customer.digits5"}}, "other": {"call": "finish", "check": "judgment"}},
 "must_not": {"call": [], "speak_after": [], "speak_when": null}, "then": {}, "provenance": "seen_in_code"}
```

```json
{"kind": "tool", "name": "ask", "author": "model", "agents": ["root"], "flows": ["main"],
 "inputs": {"value": {"type": "digits", "ground_in": "customer_utterance.current", "rule": "exactly_5_digits_as_spoken", "enum": []}},
 "outputs": {"status": ["SUCCESS"]}, "effects": {"value": "$args.value"}, "deterministic_rule": {"id": null, "needs": [], "description": ""},
 "preconditions": {"step": "collect", "state": null}, "provenance": "seen_in_code"}
```

```json
{"kind": "variables", "variables": {"value": {"default": null, "set_by": ["ask"], "consumed_by": ["gate collect"]}}, "provenance": "seen_in_code"}
```

## 10. Point inventory

| Point id | Step | Artifact | Author | Check kind | Allowed sources | Pseudocode element |
|---|---|---|---|---|---|---|
| collect.selection | collect | tool selection | model | judgment | customer utterance | step collect |
| collect.ask.args.value | collect | argument | model | grounding | customer_utterance.current | tool ask inputs.value |

## 11. Open questions

- none
'''


class BuildSpecTests(unittest.TestCase):
    def test_excerpt_compiles_clean(self):
        compiled, diag = bs.compile_spec(EXCERPT.read_text(encoding="utf-8"), str(EXCERPT))
        self.assertEqual(diag.errors, [])
        self.assertEqual(diag.warnings, [])
        self.assertIn("zip_collection", compiled["steps"])
        self.assertIn("validate_zip_code", compiled["tools"])
        self.assertEqual(compiled["rules"]["ZIP_MATCH"]["thresholds"]["zip_validation_retry_count"], 2)
        self.assertTrue(any(p["id"] == "zip_collection.save_zip_code.args.zip_code" for p in compiled["points"]))
        self.assertEqual(compiled["meta"]["counts"]["open_questions"], 4)

    def test_mini_compiles_and_reports_dangling_references(self):
        compiled, diag = bs.compile_spec(MINI, "mini.md")
        self.assertEqual(diag.errors, [])
        broken = MINI.replace('"call": "finish", "check": "judgment"', '"call": "vanish", "check": "judgment"')
        broken = broken.replace(', "provenance": "seen_in_code"}\n```\n\n## 3. Flows', '}\n```\n\n## 3. Flows')
        _, diag2 = bs.compile_spec(broken, "broken.md")
        self.assertTrue(any("unknown tool 'vanish'" in e for e in diag2.errors))
        self.assertTrue(any("needs provenance" in e for e in diag2.errors))
        no_points = MINI.split("## 10. Point inventory")[0]
        _, diag3 = bs.compile_spec(no_points, "np.md")
        self.assertTrue(any("no point inventory" in e for e in diag3.errors))

    def test_gate_identifiers_ignore_prose(self):
        self.assertEqual(bs._gate_identifiers("S.user_zip and not S.is_zip_verified"), ["user_zip", "is_zip_verified"])
        self.assertEqual(bs._gate_identifiers("any step (global handler, evaluated by the model)"), [])
        self.assertEqual(bs._gate_identifiers("user_zip and not verified"), ["user_zip", "verified"])

    def test_cli_compile_render_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "wp.md"
            source.write_text(MINI, encoding="utf-8")
            spec = Path(tmp) / "spec.json"
            report = Path(tmp) / "report.md"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = bs.main(["compile", str(source), "--out", str(spec), "--report", str(report)])
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("VALID", out.getvalue())
            arch = Path(tmp) / "architecture.md"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bs.main(["render", str(spec), "--out", str(arch)]), 0)
            text = arch.read_text(encoding="utf-8")
            self.assertIn("```mermaid", text)
            self.assertIn("root  [root]", text)
            self.assertIn('s_collect -. "digits5" .-> t_collect_ask', text)
            inventory = Path(tmp) / "inv.json"
            inventory.write_text(json.dumps({"inputs": ["x"], "agents": {"root": {"tools": ["ask"], "sub_agents": ["child"]}, "child": {"tools": [], "sub_agents": []}},
                                             "tools": {"ask": {"kind": "python", "role": "tool", "docstring": "asks"}}, "callbacks": [{"agent": "root", "stage": "BeforeModel", "file": "cb.py", "functions": ["before_model_callback"]}],
                                             "unbound_tools": [], "prompts": []}), encoding="utf-8")
            tree = Path(tmp) / "tree.md"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bs.main(["tree", "--inventory", str(inventory), "--out", str(tree)]), 0)
            tree_text = tree.read_text(encoding="utf-8")
            self.assertIn("callback BeforeModel: cb.py", tree_text)
            self.assertIn("`-- child", tree_text)

    def test_strict_fails_on_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "wp.md"
            source.write_text(MINI.replace('"outputs": {"status": ["SUCCESS"]}, ', '"outputs": {}, '), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bs.main(["compile", str(source), "--out", str(Path(tmp) / "s.json"), "--strict"]), 1)


if __name__ == "__main__":
    unittest.main()

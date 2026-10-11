import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import inventory_materials as inv  # noqa: E402

SAVE_ZIP = '''from typing import Dict, Any

def save_zip_code(zip_code: str) -> Dict[str, Any]:
    """Saves the user-provided ZIP code to the session state.

    ONLY call this tool when the user has provided digits.
    """
    context.state['user_zip'] = zip_code
    retries = context.state.get('zip_validation_retry_count', 0)
    return {"status": "SUCCESS"}
'''

VALIDATE_ZIP = '''from typing import Dict, Any

ERROR_TRIGGERS = {"99991": {"status": "SYSTEM_ERROR"}}

def validate_zip_code(zip_code: str) -> Dict[str, Any]:
    """Validates the ZIP against the address on file."""
    context.state['user_zip'] = zip_code
    address = tools.GetMailingAddress_lookup({"cardNumber": context.state.get("cardNumber")}).json()
    if str(address.get("zipcode"))[:5] == str(zip_code)[:5]:
        context.state['is_zip_verified'] = True
        return {"status": "SUCCESS"}
    return {"status": "FAILURE"}
'''

AGENT_YAML = """displayName: replace_debit_card_agent
instruction: |
  You help customers replace cards.
  Follow the injected step.
tools:
  - projects/p/tools/save-zip-code
  - projects/p/tools/validate-zip-code
"""

TOOL_YAML = """displayName: save_zip_code
pythonFunction:
  name: save_zip_code
  description: "Saves the ZIP"
executionType: SYNCHRONOUS
"""


class InventoryTests(unittest.TestCase):
    def build(self, root: Path):
        (root / "tools").mkdir()
        (root / "tools" / "save_zip_code.py").write_text(SAVE_ZIP, encoding="utf-8")
        (root / "tools" / "validate_zip_code.py").write_text(VALIDATE_ZIP, encoding="utf-8")
        (root / "package" / "agents").mkdir(parents=True)
        (root / "package" / "agents" / "replace_debit_card_agent.yaml").write_text(AGENT_YAML, encoding="utf-8")
        (root / "package" / "tools").mkdir()
        (root / "package" / "tools" / "save_zip_code.yaml").write_text(TOOL_YAML, encoding="utf-8")
        (root / "instructions").mkdir()
        (root / "instructions" / "replace_debit_card_agent.txt").write_text("<role>\nYou are DemoCard.\n</role>\n", encoding="utf-8")
        (root / "variables.json").write_text(json.dumps([{"name": "user_zip"}, {"name": "is_zip_verified"}]), encoding="utf-8")
        return inv.build_inventory([root], None)

    def test_python_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self.build(Path(tmp))
            save = inventory["tools"]["save_zip_code"]
            self.assertIn("ONLY call this tool", save["docstring"])
            self.assertEqual(save["state_writes"], ["user_zip"])
            self.assertIn("zip_validation_retry_count", save["state_reads"])
            self.assertEqual(save["status_values"], ["SUCCESS"])
            self.assertEqual([p["name"] for p in save["params"]], ["zip_code"])
            validate = inventory["tools"]["validate_zip_code"]
            self.assertEqual(validate["external_calls"], ["GetMailingAddress_lookup"])
            self.assertEqual(sorted(validate["status_values"]), ["FAILURE", "SUCCESS"])
            self.assertTrue(any(c["name"] == "ERROR_TRIGGERS" for c in inventory["constants"]))

    def test_yaml_tree_and_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self.build(Path(tmp))
            agent = inventory["agents"]["replace_debit_card_agent"]
            self.assertEqual(agent["tools"], ["save_zip_code", "validate_zip_code"])
            self.assertIn("You help customers", agent["instruction_head"])
            self.assertEqual(inventory["tools"]["save_zip_code"].get("description"), "Saves the ZIP")
            self.assertEqual(len(inventory["prompts"]), 1)
            self.assertEqual(inventory["unbound_tools"], [])
            self.assertIn("variables.json", "".join(inventory["variables"].keys()))
            summary = inv.render_summary(inventory)
            self.assertIn("replace_debit_card_agent", summary)
            self.assertIn("save_zip_code", summary)

    def test_agents_json_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "code").mkdir()
            (root / "code" / "t.py").write_text(SAVE_ZIP, encoding="utf-8")
            (root / "agents.json").write_text(json.dumps({"agents": [{"name": "root", "tools": ["save_zip_code"], "sub_agents": []}]}), encoding="utf-8")
            out = root / "inventory.json"
            summary = root / "summary.md"
            code = inv.main([str(root / "code"), str(root / "agents.json"), "--out", str(out), "--summary", str(summary)])
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["agents"]["root"]["tools"], ["save_zip_code"])
            self.assertTrue(summary.exists())

    def test_simple_yaml_parser(self):
        parsed = inv.parse_simple_yaml("a: 1\nb:\n  - x\n  - y\nc:\n  d: \"q\"\n  e: |\n    line one\n    line two\n")
        self.assertEqual(parsed["a"], 1)
        self.assertEqual(parsed["b"], ["x", "y"])
        self.assertEqual(parsed["c"]["d"], "q")
        self.assertEqual(parsed["c"]["e"], "line one\nline two")


if __name__ == "__main__":
    unittest.main()

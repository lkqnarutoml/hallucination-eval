import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import inventory_materials as inv  # noqa: E402


class InventoryRoleTests(unittest.TestCase):
    def test_roles_and_callbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "callbacks").mkdir()
            (root / "tools" / "save_zip_code.py").write_text('def save_zip_code(zip_code: str):\n    """Saves."""\n    context.state["user_zip"] = zip_code\n    return {"status": "SUCCESS"}\n', encoding="utf-8")
            (root / "callbacks" / "cb_replace_before_agent.py").write_text('def check_zip_collection_needed(v):\n    return not v.get("user_zip")\n\ndef before_agent_callback(callback_context):\n    """Flow engine."""\n    return None\n', encoding="utf-8")
            (root / "agents.json").write_text('{"agents": [{"name": "replace_debit_card_agent", "tools": ["save_zip_code"], "sub_agents": []}]}', encoding="utf-8")
            inventory = inv.build_inventory([root], None)
            self.assertEqual(inventory["tools"]["save_zip_code"]["role"], "tool")
            self.assertEqual(inventory["tools"]["check_zip_collection_needed"]["role"], "gate")
            self.assertEqual(inventory["tools"]["before_agent_callback"]["role"], "callback")
            self.assertEqual(len(inventory["callbacks"]), 1)
            self.assertEqual(inventory["callbacks"][0]["stage"], "BeforeAgent")
            self.assertEqual(inventory["callbacks"][0]["agent"], "replace_debit_card_agent")
            summary = inv.render_summary(inventory)
            self.assertIn("## Callbacks", summary)
            self.assertIn("| save_zip_code | tool |", summary)


if __name__ == "__main__":
    unittest.main()

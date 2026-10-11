"""The CX Agent Studio "Export agent" package in its JSON flavour: definition files named after their folder,
resource ids instead of display names in references, sibling instruction.txt, callbacks declared on the agent."""
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
import inventory_materials as inv  # noqa: E402

APP = "projects/p/locations/us/apps/a"


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_export(root: Path) -> None:
    write(root / "app.json", {"name": APP, "displayName": "DemoCard", "rootAgent": APP + "/agents/agent-root",
                              "modelSettings": {"model": "gemini-3.1-flash-live"}, "guardrails": [APP + "/guardrails/Bank_Black_List"],
                              "variableDeclarations": [{"name": "needs_zip_prompt", "schema": {"type": "BOOLEAN"}, "default": True, "description": "first prompt flag"},
                                                       {"name": "user_zip", "schema": {"type": "STRING"}, "default": "", "description": ""}]})
    write(root / "environment.json", {"name": "prod"})
    write(root / "pythonEnvFiles" / "pythonEnvFiles.json", {"files": []})
    write(root / "agents" / "DemoCard_steering_agent" / "DemoCard_steering_agent.json",
          {"name": APP + "/agents/agent-root", "displayName": "DemoCard steering agent",
           "tools": [APP + "/tools/tool-7efc", APP + "/tools/system-end"], "childAgents": [APP + "/agents/agent-rdc"],
           "beforeModelCallbacks": [{"pythonCode": "agents/DemoCard_steering_agent/before_model_callbacks/cb_root_before_model.py", "description": "bootstrap", "disabled": False}]})
    write(root / "agents" / "DemoCard_steering_agent" / "before_model_callbacks" / "cb_root_before_model.py",
          'def before_model_callback(callback_context, llm_request):\n    """Bootstrap."""\n    return None\n')
    write(root / "agents" / "replace_debit_card_agent" / "replace_debit_card_agent.json",
          {"name": APP + "/agents/agent-rdc", "displayName": "replace_debit_card_agent",
           "tools": [{"tool": APP + "/tools/tool-save"}, APP + "/toolsets/ts-mailing"], "childAgents": [],
           "instruction": "agents/replace_debit_card_agent/instruction.txt",
           "beforeAgentCallbacks": [{"pythonCode": "def before_agent_callback(callback_context):\n    \"\"\"Flow engine.\"\"\"\n    callback_context.variables['instructions'] = 'x'\n    return None\n"}]})
    write(root / "agents" / "replace_debit_card_agent" / "instruction.txt", "<role>You replace cards.</role>\n<general_steps>...</general_steps>\n")
    write(root / "tools" / "_initialize_session_for_dev" / "_initialize_session_for_dev.json",
          {"name": APP + "/tools/tool-7efc", "displayName": "_initialize_session_for_dev",
           "pythonFunction": {"name": "_initialize_session_for_dev", "pythonCode": "tools/_initialize_session_for_dev/python_function/python_code.py", "description": "Bootstraps the session."},
           "executionType": "SYNCHRONOUS"})
    write(root / "tools" / "_initialize_session_for_dev" / "python_function" / "python_code.py",
          'def _initialize_session_for_dev():\n    """Bootstraps the session."""\n    context.state["caller_intent"] = "card.replace"\n    return "ok"\n')
    write(root / "tools" / "save_zip_code" / "save_zip_code.json",
          {"name": APP + "/tools/tool-save", "displayName": "save_zip_code",
           "pythonFunction": {"name": "save_zip_code", "description": "Saves the ZIP.",
                              "pythonCode": "def save_zip_code(zip_code: str):\n    \"\"\"Saves the ZIP.\"\"\"\n    context.state['user_zip'] = zip_code\n    return {'status': 'SUCCESS'}\n"}})
    write(root / "toolsets" / "GetMailingAddress" / "GetMailingAddress.json",
          {"name": APP + "/toolsets/ts-mailing", "displayName": "GetMailingAddress",
           "openApiToolset": {"openApiSchema": "toolsets/GetMailingAddress/open_api_toolset/open_api_schema.yaml"}})
    write(root / "guardrails" / "Bank_Black_List" / "Bank_Black_List.json", {"name": APP + "/guardrails/Bank_Black_List", "displayName": "Bank_Black_List", "blocklist": {"words": ["Chase"]}})


class ExportInventoryTests(unittest.TestCase):
    def test_json_export_resolves_ids_callbacks_and_variables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "DemoCard_export"
            build_export(root)
            inventory = inv.build_inventory([root], None)
            agents = inventory["agents"]
            self.assertEqual(sorted(agents), ["DemoCard steering agent", "replace_debit_card_agent"])
            self.assertEqual(agents["DemoCard steering agent"]["tools"], ["_initialize_session_for_dev", "system_end"])
            self.assertEqual(agents["DemoCard steering agent"]["sub_agents"], ["replace_debit_card_agent"])
            self.assertEqual(agents["replace_debit_card_agent"]["tools"], ["save_zip_code", "GetMailingAddress"])
            self.assertTrue(agents["replace_debit_card_agent"]["prompt_file"].endswith("instruction.txt"))
            self.assertGreater(agents["replace_debit_card_agent"]["instruction_chars"], 20)
            self.assertEqual(inventory["app"]["root_agent"], "DemoCard steering agent")
            self.assertEqual(inventory["app"]["guardrails"], ["Bank_Black_List"])
            self.assertEqual(inventory["tools"]["save_zip_code"]["state_writes"], ["user_zip"])
            self.assertEqual(inventory["tools"]["save_zip_code"]["kind"], "python")
            self.assertEqual(inventory["tools"]["_initialize_session_for_dev"]["state_writes"], ["caller_intent"])
            self.assertEqual(inventory["tools"]["GetMailingAddress"]["kind"], "openapi")
            stages = {(c["agent"], c["stage"]) for c in inventory["callbacks"]}
            self.assertIn(("DemoCard steering agent", "BeforeModel"), stages)
            self.assertIn(("replace_debit_card_agent", "BeforeAgent"), stages)
            self.assertEqual(sum(1 for c in inventory["callbacks"] if c["agent"] == "DemoCard steering agent"), 1)
            root_cb = next(c for c in inventory["callbacks"] if c["agent"] == "DemoCard steering agent")
            self.assertEqual(root_cb["functions"], ["before_model_callback"])
            variables = inventory["variables"]["app.json"]
            self.assertEqual([v["name"] for v in variables], ["needs_zip_prompt", "user_zip"])
            self.assertEqual(variables[0]["default"], True)
            self.assertEqual([g["display"] for g in inventory["guardrails"]], ["Bank_Black_List"])
            self.assertEqual(inventory["unbound_tools"], [])
            summary = inv.render_summary(inventory)
            self.assertIn("## App", summary)
            self.assertIn("Root agent: DemoCard steering agent", summary)
            tree = bs.render_materials_tree(inventory)
            self.assertIn("DemoCard steering agent  [root]", tree)
            self.assertIn("`-- replace_debit_card_agent", tree)
            self.assertIn("callback BeforeModel:", tree)
            self.assertIn("tool GetMailingAddress (openapi tool)", tree)

    def test_cli_on_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            build_export(root)
            out = Path(tmp) / "inv.json"
            summary = Path(tmp) / "summary.md"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = inv.main([str(root), "--out", str(out), "--summary", str(summary)])
            self.assertEqual(code, 0)
            self.assertIn("2 agents", buffer.getvalue())
            self.assertTrue(summary.exists())


if __name__ == "__main__":
    unittest.main()

import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

import normalize_trajectories as nt  # noqa: E402
from builders import CSV_HEADER, CSV_ROWS, column_map, write_csv  # noqa: E402

try:
    import openpyxl  # noqa: F401
    HAVE_OPENPYXL = True
except ImportError:
    HAVE_OPENPYXL = False


class ColumnMapTests(unittest.TestCase):
    def test_proposal_names_the_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp) / "export.csv")
            header, records, _, _ = nt.read_table(path)
            self.assertEqual(header, CSV_HEADER)
            self.assertEqual(len(records), len(CSV_ROWS))
            proposal = nt.propose_column_map(header, records)["proposal"]
            expected = {"session_id": "conversation_id", "timestamp": "event_time", "row_type": "event_type",
                        "speaker": "speaker", "text": "utterance", "tool_name": "tool_name", "tool_args": "tool_input",
                        "tool_response": "tool_response", "state": "updated_variables"}
            for field, column in expected.items():
                self.assertEqual(proposal[field]["column"], column, field)
            self.assertTrue(all("*" in s or not any(ch.isdigit() for ch in s) or len(s) < 4
                                for s in proposal["text"]["samples"]))

    def test_inspect_cli_writes_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp) / "export.csv")
            out = Path(tmp) / "proposal.json"
            self.assertEqual(nt.main(["inspect", str(path), "--out", str(out)]), 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["proposal"]["tool_args"]["column"], "tool_input")
            self.assertTrue(data["needs_confirmation"])


class LoadTabularTests(unittest.TestCase):
    def test_csv_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp) / "export.csv")
            conversations = nt.load_tabular(path, column_map(), None, "csv")
            self.assertEqual([c["conversation_id"] for c in conversations], ["conv-0001-abcdef", "conv-0002-abcdef"])
            conv = conversations[0]
            kinds = [e["kind"] for e in conv["events"]]
            self.assertEqual(kinds, ["customer_utterance", "tool_call", "state_update", "agent_utterance",
                                     "customer_utterance", "tool_call"])
            save = conv["events"][1]
            self.assertEqual(save["args"], {"zip_code": "10001"})
            self.assertEqual(save["representation"]["args"], "py_repr")
            self.assertEqual(save["response"], {"status": "SUCCESS"})
            self.assertEqual(conv["events"][2]["changes"]["user_zip"]["new"], "10001")
            self.assertEqual(conv["events"][3]["agent"], "replace_debit_card_agent")
            validate = conv["events"][5]
            self.assertEqual(validate["response"], {"status": "FAILURE"})
            self.assertTrue(any(w["code"] == "duplicate_row" for w in conv["warnings"]))
            self.assertEqual([e["turn"] for e in conv["events"]], [1, 1, 1, 1, 2, 2])
            self.assertTrue(save["locator"].startswith("csv:"))

    def test_normalize_cli_requires_column_map_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp) / "export.csv")
            out = Path(tmp) / "out"
            self.assertEqual(nt.main(["normalize", str(path), "--out", str(out)]), 3)
            map_path = Path(tmp) / "column_map.json"
            map_path.write_text(json.dumps(column_map()), encoding="utf-8")
            self.assertEqual(nt.main(["normalize", str(path), "--out", str(out), "--column-map", str(map_path)]), 0)
            data = json.loads((out / "conversations.json").read_text(encoding="utf-8"))
            self.assertEqual(data["meta"]["conversations"], 2)
            self.assertIn("py_repr", (out / "normalize_report.md").read_text(encoding="utf-8"))

    def test_ground_truth_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp) / "export.csv")
            truth = Path(tmp) / "gt.csv"
            truth.write_text("conversation_id,zip_on_file,issue_reason\nconv-0001-abcdef,10001,damaged\n", encoding="utf-8")
            conversations = nt.load_tabular(path, column_map(), None, "csv")
            attached = nt.attach_ground_truth(conversations, truth)
            self.assertEqual(attached, 1)
            self.assertEqual(conversations[0]["metadata"]["ground_truth"], {"zip_on_file": "10001", "issue_reason": "damaged"})
            self.assertIsNone(conversations[1]["metadata"]["ground_truth"])

    @unittest.skipUnless(HAVE_OPENPYXL, "openpyxl not installed")
    def test_xlsx_round_trip(self):
        import openpyxl

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.xlsx"
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.title = "prod"
            sheet.append(CSV_HEADER)
            for row in CSV_ROWS:
                sheet.append(row)
            book.save(str(path))
            header, records, locator, sheet_name = nt.read_table(path)
            self.assertEqual(header, CSV_HEADER)
            self.assertEqual(sheet_name, "prod")
            conversations = nt.load_tabular(path, column_map("prod"), None, "xlsx")
            self.assertEqual(len(conversations), 2)
            self.assertTrue(conversations[0]["events"][1]["locator"].startswith("xlsx:"))
            self.assertIn("!prod!", conversations[0]["events"][1]["locator"])


if __name__ == "__main__":
    unittest.main()

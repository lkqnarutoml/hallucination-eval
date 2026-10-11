import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import run_checker  # noqa: E402
from halu_common.jsonl import write_json  # noqa: E402

FIXTURES = TESTS / "fixtures"


def conversation(cid, customer_text, argument):
    return {"conversation_id": cid, "metadata": {}, "warnings": [], "events": [
        {"index": 0, "turn": 1, "kind": "customer_utterance", "text": customer_text, "locator": "csv:x.csv:L2"},
        {"index": 1, "turn": 1, "kind": "tool_call", "tool": "save_zip_code", "args": {"zip_code": argument},
         "response": {"status": "SUCCESS"}, "origin": "model", "locator": "csv:x.csv:L3"}]}


class RunCheckerTests(unittest.TestCase):
    def test_runs_fixture_checker_over_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            batches = Path(tmp) / "batches"
            batches.mkdir()
            write_json(batches / "batch_001.json", {"batch": {"id": "001"}, "conversations": [
                conversation("c1", "my zip is 100011", "10001"), conversation("c2", "10001", "10001")]})
            out = Path(tmp) / "checker_out"
            code = run_checker.main(["--checker", str(FIXTURES / "mini_checker.py"), "--batches", str(batches), "--out", str(out)])
            self.assertEqual(code, 0)
            result = json.loads((out / "batch_001.json").read_text(encoding="utf-8"))
            self.assertEqual(result["checker"], "mini-checker/1")
            self.assertEqual(len(result["results"][0]["findings"]), 1)
            self.assertEqual(result["results"][0]["findings"][0]["type"], "unsupported_argument")
            self.assertEqual(result["results"][1]["findings"], [])
            index = json.loads((out / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["batches"][0]["findings"], 1)

    def test_checker_errors_are_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad_checker.py"
            bad.write_text("def check_conversation(conversation):\n    raise ValueError('boom')\n", encoding="utf-8")
            batches = Path(tmp) / "batches"
            batches.mkdir()
            write_json(batches / "batch_001.json", {"batch": {"id": "001"}, "conversations": [conversation("c1", "x", "1")]})
            out = Path(tmp) / "checker_out"
            code = run_checker.main(["--checker", str(bad), "--batches", str(batches), "--out", str(out)])
            self.assertEqual(code, 1)
            result = json.loads((out / "batch_001.json").read_text(encoding="utf-8"))
            self.assertEqual(result["errors"], 1)
            self.assertIn("boom", result["results"][0]["error"])

    def test_missing_function_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "no_func.py"
            bad.write_text("X = 1\n", encoding="utf-8")
            batches = Path(tmp) / "batches"
            batches.mkdir()
            write_json(batches / "batch_001.json", {"conversations": []})
            self.assertEqual(run_checker.main(["--checker", str(bad), "--batches", str(batches), "--out", str(Path(tmp) / "o")]), 2)


if __name__ == "__main__":
    unittest.main()

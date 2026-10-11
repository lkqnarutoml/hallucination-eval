import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import normalize_trajectories as nt  # noqa: E402
from halu_common.jsonl import write_json  # noqa: E402


class SplitTests(unittest.TestCase):
    def test_split_by_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "conversations.json"
            conversations = [{"conversation_id": "c%d" % i, "metadata": {}, "events": [], "warnings": []} for i in range(5)]
            write_json(source, {"meta": {"conversations": 5}, "conversations": conversations})
            out = Path(tmp) / "batches"
            self.assertEqual(nt.main(["split", str(source), "--out", str(out), "--max-conversations", "2"]), 0)
            files = sorted(p.name for p in out.glob("batch_*.json"))
            self.assertEqual(files, ["batch_001.json", "batch_002.json", "batch_003.json"])
            first = json.loads((out / "batch_001.json").read_text(encoding="utf-8"))
            self.assertEqual(first["batch"], {"id": "001", "index": 1, "of": 3, "conversation_ids": ["c0", "c1"]})
            index = json.loads((out / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index["batches"]), 3)

    def test_split_by_chars(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "conversations.json"
            big = [{"conversation_id": "c%d" % i, "metadata": {}, "events": [{"kind": "customer_utterance", "text": "x" * 500}], "warnings": []} for i in range(4)]
            write_json(source, {"meta": {}, "conversations": big})
            out = Path(tmp) / "batches"
            nt.main(["split", str(source), "--out", str(out), "--max-conversations", "10", "--max-chars", "1200"])
            self.assertEqual(len(list(out.glob("batch_*.json"))), 4)


if __name__ == "__main__":
    unittest.main()

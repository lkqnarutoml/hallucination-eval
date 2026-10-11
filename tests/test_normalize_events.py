import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

import normalize_trajectories as nt  # noqa: E402
from builders import DEMO_TURNS, events_session  # noqa: E402

FIXTURES = TESTS / "fixtures"


class EventsJsonlTests(unittest.TestCase):
    def test_chunks_keep_intra_turn_order_and_origins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = events_session(tmp, DEMO_TURNS)
            conversations = nt.load_events_file(path)
            self.assertEqual(len(conversations), 1)
            conv = conversations[0]
            self.assertEqual(conv["metadata"]["ground_truth"], {"zip_on_file": "10001"})
            self.assertEqual(conv["metadata"]["ground_truth_source"], "fixture")
            turn2 = [e for e in conv["events"] if e["turn"] == 2]
            self.assertEqual([e["kind"] for e in turn2], ["customer_utterance", "tool_call", "state_update", "agent_utterance"])
            call = turn2[1]
            self.assertEqual(call["tool"], "save_zip_code")
            self.assertEqual(call["args"], {"zip_code": "10001"})
            self.assertEqual(call["response"], {"status": "SUCCESS", "demo": True})
            self.assertEqual(call["representation"], {"args": "dict", "response": "dict"})
            self.assertEqual(call["origin"], "model")
            self.assertIn("democard_state.user_zip", turn2[2]["changes"])
            self.assertEqual(turn2[2]["changes"]["democard_state.user_zip"]["new"], "10001")
            self.assertEqual(turn2[3]["origin"], "callback")
            turn3_calls = [e for e in conv["events"] if e["turn"] == 3 and e["kind"] == "tool_call"]
            self.assertEqual([c["tool"] for c in turn3_calls], ["validate_zip_code", "indicate_ready_for_next_step"])
            self.assertEqual([c["origin"] for c in turn3_calls], ["model", "callback"])
            self.assertEqual(conv["summary"]["tool_calls"], 3)
            self.assertFalse(any(w["code"] == "fallback_used" for w in conv["warnings"]))
            self.assertTrue(all(e.get("locator", "").startswith("events:") for e in conv["events"] if e["kind"] != "session_end"))

    def test_fallback_to_spans_without_ces_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = events_session(tmp, DEMO_TURNS, include_ces=False)
            conv = nt.load_events_file(path)[0]
            self.assertTrue(any(w["code"] == "fallback_used" for w in conv["warnings"]))
            turn2 = [e["kind"] for e in conv["events"] if e["turn"] == 2]
            self.assertEqual(turn2, ["customer_utterance", "tool_call", "state_update", "agent_utterance"])
            call = [e for e in conv["events"] if e["kind"] == "tool_call"][0]
            self.assertEqual(call["args"], {"zip_code": "10001"})
            self.assertEqual(call["origin"], "model")

    def test_transcript_chunks_merge(self):
        turns = [{"customer": "one zero zero zero one", "agent": "You entered 1 0 0 0 1. Is that correct?", "transcript": True,
                  "tools": [("save_zip_code", {"zip_code": "10001"}, {"status": "SUCCESS"}, None, "model")]}]
        with tempfile.TemporaryDirectory() as tmp:
            conv = nt.load_events_file(events_session(tmp, turns))[0]
            customer = [e for e in conv["events"] if e["kind"] == "customer_utterance"][0]
            self.assertEqual(customer["text"], "one zero zero zero one")
            self.assertEqual(customer["text_source"], "ces_transcript")

    def test_discover_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runs" / "a").mkdir(parents=True)
            (root / "runs" / "b").mkdir(parents=True)
            events_session(root / "runs" / "a", DEMO_TURNS, session_id="sim-a")
            events_session(root / "runs" / "b", DEMO_TURNS[:1], session_id="sim-b")
            self.assertEqual(len(nt.discover_events_files(root)), 2)
            out = root / "out"
            code = nt.main(["normalize", str(root / "runs"), "--out", str(out)])
            self.assertEqual(code, 0)
            data = json.loads((out / "conversations.json").read_text(encoding="utf-8"))
            self.assertEqual({c["conversation_id"] for c in data["conversations"]}, {"sim-a", "sim-b"})
            self.assertTrue((out / "normalize_report.md").exists())

    def test_mini_run_fixture(self):
        conv = nt.load_events_file(FIXTURES / "mini_run" / "events.jsonl")[0]
        self.assertEqual(conv["conversation_id"], "sim-mini-0001")
        customer = [e for e in conv["events"] if e["kind"] == "customer_utterance" and e["turn"] == 2][0]
        self.assertEqual(customer["text"], "my zip is 100011")
        save = [e for e in conv["events"] if e["kind"] == "tool_call" and e["tool"] == "save_zip_code"][0]
        self.assertEqual(save["args"], {"zip_code": "10001"})
        self.assertEqual(save["origin"], "model")
        readback = [e for e in conv["events"] if e["kind"] == "agent_utterance" and e["turn"] == 2][0]
        self.assertEqual(readback["origin"], "callback")
        self.assertEqual(conv["metadata"]["flow"], None)
        self.assertEqual(conv["summary"]["turns"], 3)


if __name__ == "__main__":
    unittest.main()

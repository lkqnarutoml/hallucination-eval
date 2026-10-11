import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

import make_audit_payload as ap  # noqa: E402
import merge_findings as mf  # noqa: E402
import normalize_trajectories as nt  # noqa: E402
import validate_findings as vf  # noqa: E402
from halu_common.jsonl import read_json, write_json  # noqa: E402

FIXTURES = TESTS / "fixtures"
ID_PATTERN = re.compile(r"^[HPR]-\d{4,}$")


def miss_finding(turn, locator):
    """A complete auditor finding for an unsupported sample, in the shape the auditor writes it (no id, no verification)."""
    return {"turn": turn, "point": "zip_confirmation.selection", "author": "model", "type": "unsupported_tool_selection",
            "check_kind": "judgment", "severity": "low", "confidence": "medium", "observed": "validate_zip_code",
            "expected_or_allowed": "x", "rationale": "r",
            "evidence": [{"kind": "tool_call", "turn": turn, "quote": "q", "locator": locator},
                         {"kind": "pseudocode", "ref": "step zip_confirmation", "provenance": "seen_in_code"}]}


class AuditPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            nt.main(["normalize", str(FIXTURES / "mini_run"), "--out", str(root)])
        self.conversations = root / "conversations.json"
        self.batch = FIXTURES / "mini_findings_batch.json"
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_payload_withholds_rationale_and_samples_supported_calls(self):
        payload = ap.build_payload(read_json(self.batch), {c["conversation_id"]: c for c in read_json(self.conversations)["conversations"]}, sample=5, seed=1)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        for key in ap.WITHHELD:
            self.assertNotIn(key, item)
        self.assertEqual(item["point"], "zip_collection.save_zip_code.args.zip_code")
        self.assertTrue(item["context"]["turn_events"])
        self.assertTrue(all(e["locator"] for e in item["evidence"] if e["kind"] != "pseudocode"))
        tools = {s["tool"] for s in payload["supported_samples"]}
        self.assertNotIn("save_zip_code", tools)
        self.assertIn("validate_zip_code", tools)

    def test_apply_confirm_reject_and_miss(self):
        batch = read_json(self.batch)
        cid = batch["conversations"][0]["conversation_id"]
        verdicts = {"batch": "001", "notes": "ok",
                    "verdicts": [{"ref": "%s#0" % cid, "status": "rejected", "auditor_rationale": "argument matches the transcript"}],
                    "samples": [{"ref": "%s#sample1" % cid, "supported": True},
                                {"ref": "%s#sample2" % cid, "supported": False, "auditor_rationale": "missed",
                                 "finding": {"turn": 3, "point": "zip_confirmation.selection", "author": "model", "type": "unsupported_tool_selection",
                                             "check_kind": "judgment", "severity": "low", "confidence": "medium", "observed": "validate_zip_code",
                                             "expected_or_allowed": "x", "rationale": "r",
                                             "evidence": [{"kind": "tool_call", "turn": 3, "quote": "q", "locator": "events:f#seq=20"},
                                                          {"kind": "pseudocode", "ref": "step zip_confirmation", "provenance": "seen_in_code"}]}}]}
        outcome = ap.apply_verdicts(batch, verdicts, allow_missing=False)
        self.assertIsNone(outcome["error"])
        conv = outcome["result"]["conversations"][0]
        self.assertEqual(len(conv["rejected"]), 1)
        self.assertEqual(conv["rejected"][0]["verification"]["status"], "rejected")
        self.assertEqual(len(conv["hallucinations"]), 1)
        self.assertEqual(conv["hallucinations"][0]["decided_by"], "auditor")
        self.assertEqual(conv["audit"], {"sampled_supported": 2, "misses_found": 1, "auditor_notes": "ok"})
        missing = ap.apply_verdicts(batch, {"verdicts": [], "samples": []}, allow_missing=False)
        self.assertIsNotNone(missing["error"])

    def test_cli_round_trip_validates(self):
        payload_path = self.root / "payload.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ap.main(["payload", "--findings", str(self.batch), "--conversations", str(self.conversations), "--out", str(payload_path)]), 0)
        payload = read_json(payload_path)
        cid = payload["items"][0]["conversation_id"]
        verdicts_path = self.root / "verdicts.json"
        write_json(verdicts_path, {"batch": "001", "verdicts": [{"ref": "%s#0" % cid, "status": "revised", "auditor_rationale": "severity higher",
                                                                 "revised": {"severity": "high"}}], "samples": []})
        verified = self.root / "verified_batch_001.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ap.main(["apply", "--findings", str(self.batch), "--verdicts", str(verdicts_path), "--out", str(verified)]), 0)
            self.assertEqual(vf.main([str(verified), "--batch", "--conversations", str(self.conversations)]), 0)
        item = read_json(verified)["conversations"][0]["hallucinations"][0]
        self.assertEqual(item["severity"], "high")
        self.assertEqual(item["verification"]["revised_from"]["severity"], "medium")

    def test_apply_gives_misses_unique_provisional_ids(self):
        batch = read_json(self.batch)
        second = copy.deepcopy(batch["conversations"][0])
        second["conversation_id"] = "sim-mini-0002"
        second["hallucinations"][0]["id"] = "H-0007"  # the batch's highest id, with a gap before it
        batch["conversations"].append(second)
        locator = "events:f#seq=20"
        verdicts = {"batch": "001",
                    "verdicts": [{"ref": "sim-mini-0001#0", "status": "confirmed", "auditor_rationale": "a"},
                                 {"ref": "sim-mini-0002#0", "status": "rejected", "auditor_rationale": "b"}],
                    "samples": [{"ref": "sim-mini-0001#sample1", "supported": False, "finding": miss_finding(3, locator)},
                                # an id the auditor wrote anyway must not survive: it would collide with the evaluator's
                                {"ref": "sim-mini-0001#sample2", "supported": False, "finding": dict(miss_finding(3, locator), id="H-0001")},
                                {"ref": "sim-mini-0002#sample1", "supported": True},
                                {"ref": "sim-mini-0002#sample2", "supported": False, "finding": miss_finding(3, locator)}]}
        outcome = ap.apply_verdicts(batch, verdicts, allow_missing=False)
        self.assertIsNone(outcome["error"])
        self.assertEqual(outcome["counts"]["misses_added"], 3)
        conversations = outcome["result"]["conversations"]
        kept_ids = [h["id"] for c in conversations for h in c["hallucinations"]]
        self.assertEqual(kept_ids, ["H-0001", "H-0008", "H-0009", "H-0010"])
        self.assertEqual([r["id"] for c in conversations for r in c["rejected"]], ["H-0007"])
        all_ids = kept_ids + ["H-0007"]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertTrue(all(ID_PATTERN.match(fid) for fid in all_ids))
        misses = [h for c in conversations for h in c["hallucinations"] if h["decided_by"] == "auditor"]
        self.assertEqual(len(misses), 3)
        self.assertTrue(all(m["verification"]["status"] == "confirmed" for m in misses))
        # the input batch is left untouched
        self.assertEqual([h["id"] for c in batch["conversations"] for h in c["hallucinations"]], ["H-0001", "H-0007"])

    def test_cli_apply_with_miss_passes_batch_gate_and_merges(self):
        batches = self.root / "batches"
        payload_path = self.root / "payload.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(nt.main(["split", str(self.conversations), "--out", str(batches)]), 0)
            self.assertEqual(ap.main(["payload", "--findings", str(self.batch), "--conversations", str(self.conversations),
                                      "--out", str(payload_path), "--sample", "2", "--seed", "7"]), 0)
        payload = read_json(payload_path)
        sample = payload["supported_samples"][0]
        verdicts_path = self.root / "verdicts.json"
        write_json(verdicts_path, {"batch": "001", "notes": "one miss",
                                   "verdicts": [{"ref": payload["items"][0]["ref"], "status": "confirmed", "auditor_rationale": "re-derived"}],
                                   "samples": [{"ref": sample["ref"], "supported": False, "auditor_rationale": "missed",
                                                "finding": miss_finding(sample["turn"], sample["locator"])}]})
        findings_dir = self.root / "findings"
        findings_dir.mkdir()
        verified = findings_dir / "verified_batch_001.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ap.main(["apply", "--findings", str(self.batch), "--verdicts", str(verdicts_path), "--out", str(verified)]), 0)
            # the documented P7 gate
            self.assertEqual(vf.main([str(verified), "--batch", "--conversations", str(batches / "batch_001.json")]), 0)
        hallucinations = read_json(verified)["conversations"][0]["hallucinations"]
        self.assertEqual([h["id"] for h in hallucinations], ["H-0001", "H-0002"])
        self.assertEqual(hallucinations[1]["decided_by"], "auditor")
        final = self.root / "hallucination_findings.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mf.main(["--verified-dir", str(findings_dir), "--out", str(final), "--target", "DemoCard"]), 0)
            self.assertEqual(vf.main([str(final)]), 0)
        merged = read_json(final)["conversations"][0]["hallucinations"]
        self.assertEqual([h["id"] for h in merged], ["H-0001", "H-0002"])
        self.assertEqual(merged[1]["decided_by"], "auditor")


if __name__ == "__main__":
    unittest.main()

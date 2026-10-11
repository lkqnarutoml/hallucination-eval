import json
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

from halu_common.payload import status_of  # noqa: E402
from halu_common.redact import cap_payload, luhn_ok, redact_text, redact_value, truncate_string  # noqa: E402

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"


class RedactTests(unittest.TestCase):
    def test_key_rule_touches_only_strings_and_whole_key_segments(self):
        counts = {}
        out = redact_value({"access_token": "abcdefgh12345678", "got_bearer_token": True, "token_type": "Bearer",
                            "expires_in": 3600, "tokens": ["iPhone 15 Pro", "Apple Watch"], "client_secret": "s3cr3t-value"}, counts=counts)
        self.assertTrue(out["access_token"].startswith("[redacted:access_token len=16]"))
        self.assertIs(out["got_bearer_token"], True)
        self.assertEqual(out["token_type"], "Bearer")  # shorter than 8 characters
        self.assertEqual(out["expires_in"], 3600)
        self.assertEqual(out["tokens"], ["iPhone 15 Pro", "Apple Watch"])  # "tokens" is not the segment "token"
        self.assertEqual(out["client_secret"], "[redacted:client_secret len=12]")
        self.assertEqual(counts, {"key:access_token": 1, "key:client_secret": 1})

    def test_bearer_and_jwt_rules(self):
        counts = {}
        out = redact_value({"value": JWT, "header": "Bearer " + JWT, "note": "token=" + JWT + " expires soon"}, counts=counts)
        self.assertEqual(out["value"], "[redacted:jwt len=%d]" % len(JWT))
        self.assertTrue(out["header"].startswith("[redacted:bearer_token len="))
        self.assertTrue(out["note"].startswith("token=[redacted:jwt len=") and out["note"].endswith(" expires soon"))
        self.assertNotIn("eyJ", json.dumps(out))
        self.assertEqual(counts["jwt"], 2)
        self.assertEqual(counts["bearer"], 1)

    def test_pan_rules(self):
        self.assertTrue(luhn_ok("4242424242424242"))
        self.assertFalse(luhn_ok("1234567890123"))
        counts = {}
        out = redact_value({"card_number": "4242 4242 4242 4242", "other": "12345678901234", "posted_at": "1726790400000",
                            "value": "1726790400000", "order_id": "1234567890123456", "last4": "4242", "zip_code": "10001",
                            "phone": "12125551212", "created": 1726790400000}, counts=counts)
        self.assertEqual(out["card_number"], "****4242")
        self.assertEqual(out["other"], "****1234")  # 14 digits, fails Luhn: still masked
        self.assertEqual(redact_value({"other": "1234567890123"})["other"], "1234567890123")  # 13 digits in the epoch range
        self.assertEqual(out["posted_at"], "1726790400000")  # time key
        self.assertEqual(out["value"], "1726790400000")  # bare 13 digits in the epoch-millisecond range
        self.assertEqual(out["order_id"], "1234567890123456")  # id key
        self.assertEqual(out["last4"], "4242")
        self.assertEqual(out["zip_code"], "10001")
        self.assertEqual(out["phone"], "12125551212")  # fewer than 13 digits
        self.assertEqual(out["created"], 1726790400000)  # not a string
        self.assertEqual(counts, {"pan": 1, "digits13_19": 1})
        self.assertEqual(redact_text("my card is 4242-4242-4242-4242 and zip 10001", {}), "my card is ****4242 and zip 10001")

    def test_opaque_strings_are_counted_not_redacted_unless_asked(self):
        blob = "SIM7f3a9c2e1b4d5e6f7a8b9c0d1e2f3a4bZZ9"
        counts = {}
        out = redact_value({"blob": blob, "session_id": blob, "hexid": "7f3a9c2e1b4d5e6f7a8b9c0d1e2f3a4b7f3a9c2e"}, counts=counts)
        self.assertEqual(out["blob"], blob)
        self.assertEqual(counts, {"opaque_seen": 1})  # the id key and the hex string do not count
        out = redact_value({"blob": blob, "session_id": blob}, counts={}, redact_opaque=True)
        self.assertTrue(out["blob"].startswith("[redacted:opaque"))
        self.assertEqual(out["session_id"], blob)

    def test_idempotent(self):
        once = redact_value({"access_token": JWT, "text": "card 4242424242424242", "n": [JWT]})
        self.assertEqual(redact_value(once), once)

    def test_cap_payload_keeps_status_first_items_and_marks_cuts(self):
        payload = {"status": "SUCCESS", "payments": [{"id": i, "memo": "m" * 50} for i in range(60)],
                   "deep": {"a": {"b": {"c": {"d": 1}}}}, "text": "x" * 700}
        counts = {}
        out = cap_payload(payload, max_string=600, max_depth=2, list_items=8, max_payload=0, counts=counts)
        self.assertEqual(status_of(out), "SUCCESS")
        self.assertEqual(len(out["payments"]), 9)
        self.assertEqual(out["payments"][0]["id"], 0)
        self.assertEqual(out["payments"][-1], {"_summary": "list with 60 items, first 8 kept"})
        self.assertEqual(out["deep"]["a"]["b"], {"_summary": "dict with 1 keys"})
        self.assertTrue(out["text"].endswith("...[+100 chars]"))
        self.assertEqual(counts["truncated"], 1)
        self.assertNotIn("_capped", out)

    def test_hard_cap_sheds_items_and_strings_before_depth(self):
        payload = {"status": "SUCCESS", "tokens": [{"device_name": "iPhone 15 Pro", "last4": "4242"}, {"device_name": "Pixel 8", "last4": "4444"}],
                   "payments": [{"id": i, "memo": "m" * 200, "status": "POSTED"} for i in range(60)]}
        counts = {}
        out = cap_payload(payload, max_string=600, max_depth=2, list_items=8, max_payload=1200, counts=counts)
        self.assertLessEqual(len(json.dumps(out)) - len(json.dumps(out["_capped"])) - 12, 1200)
        self.assertEqual(status_of(out), "SUCCESS")
        self.assertEqual(out["tokens"][0]["device_name"], "iPhone 15 Pro")  # scalars survive the cap
        self.assertEqual(out["payments"][0]["status"], "POSTED")
        self.assertIn("first", out["payments"][-1]["_summary"])
        self.assertEqual(counts["capped"], 1)
        self.assertEqual(truncate_string("[redacted:jwt len=9]", 5), "[redacted:jwt len=9]")  # placeholders are never cut


if __name__ == "__main__":
    unittest.main()

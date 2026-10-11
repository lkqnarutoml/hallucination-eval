import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

from halu_common.payload import canonical_tool_name, find_key, normalize_digits, parse_payload, status_of  # noqa: E402


class ParsePayloadTests(unittest.TestCase):
    def test_native_dict(self):
        parsed = parse_payload({"zip_code": "10001"})
        self.assertEqual(parsed.value, {"zip_code": "10001"})
        self.assertEqual(parsed.representation, "dict")

    def test_json_string(self):
        parsed = parse_payload('{"zip_code": "10001"}')
        self.assertEqual(parsed.value, {"zip_code": "10001"})
        self.assertEqual(parsed.representation, "json")

    def test_python_repr(self):
        parsed = parse_payload("{'zip_code': '10001', 'ok': True, 'x': None}")
        self.assertEqual(parsed.value, {"zip_code": "10001", "ok": True, "x": None})
        self.assertEqual(parsed.representation, "py_repr")

    def test_double_encoded_json(self):
        parsed = parse_payload('"{\\"zip_code\\": \\"10001\\"}"')
        self.assertEqual(parsed.value, {"zip_code": "10001"})
        self.assertEqual(parsed.representation, "json_double")

    def test_json_with_python_literals(self):
        parsed = parse_payload('{"ok": True, "missing": null}')
        self.assertEqual(parsed.value, {"ok": True, "missing": None})
        self.assertEqual(parsed.representation, "json_pyliterals")

    def test_tool_call_wrapper_lifts_meta(self):
        raw = {"toolCall": {"id": "adk-1", "tool": "projects/p/tools/demo-save-zip-code",
                            "args": {"zip_code": "10001"}, "displayName": "save_zip_code"}}
        parsed = parse_payload(raw)
        self.assertEqual(parsed.value, {"zip_code": "10001"})
        self.assertEqual(parsed.meta.get("displayName"), "save_zip_code")
        self.assertIn("unwrap:toolCall", parsed.layers)
        self.assertIn("unwrap:args", parsed.layers)

    def test_result_wrapper(self):
        parsed = parse_payload({"result": {"status": "SUCCESS", "demo": True}})
        self.assertEqual(parsed.value, {"status": "SUCCESS", "demo": True})

    def test_nested_string_inside_wrapper(self):
        parsed = parse_payload('{"args": "{\'zip_code\': \'1\'}"}')
        self.assertEqual(parsed.value, {"zip_code": "1"})

    def test_scalar_result_and_empty(self):
        self.assertEqual(parse_payload({"result": ""}).value, {"_value": ""})
        self.assertEqual(parse_payload(None).representation, "empty")
        self.assertEqual(parse_payload("   ").representation, "empty")
        digits = parse_payload("10001")
        self.assertEqual(digits.value, {"_value": "10001"})
        self.assertEqual(digits.representation, "scalar")

    def test_unparseable_string(self):
        parsed = parse_payload("SUCCESS")
        self.assertEqual(parsed.value, {"_value": "SUCCESS"})

    def test_does_not_mutate_input(self):
        raw = {"result": {"status": "SUCCESS"}}
        parse_payload(raw)
        self.assertEqual(raw, {"result": {"status": "SUCCESS"}})


class HelperTests(unittest.TestCase):
    def test_canonical_tool_name(self):
        self.assertEqual(canonical_tool_name("projects/p/locations/l/apps/a/tools/demo-validate-zip-code"), "validate_zip_code")
        self.assertEqual(canonical_tool_name("projects/p/tools/x", "save_zip_code"), "save_zip_code")
        self.assertEqual(canonical_tool_name("GetMailingAddress_lookup", aliases={"GetMailingAddress_lookup": "get_mailing_address"}),
                         "get_mailing_address")
        self.assertEqual(canonical_tool_name(None), "")

    def test_find_key(self):
        value, path = find_key({"a": {"zip_code": "1"}}, ("zip_code",))
        self.assertEqual((value, path), ("1", "a.zip_code"))
        self.assertEqual(find_key({"a": 1}, ("missing",)), (None, None))
        value, path = find_key({"items": [{"zipcode": "55082"}]}, ("zipCode",))
        self.assertEqual(value, "55082")

    def test_normalize_digits_and_status(self):
        self.assertEqual(normalize_digits("1 0 0 0 1"), "10001")
        self.assertEqual(normalize_digits(None), "")
        self.assertEqual(status_of({"result": {"status": "success"}}), "SUCCESS")
        self.assertEqual(status_of('{"status": "FAILURE"}'), "FAILURE")
        self.assertIsNone(status_of({"ok": True}))


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

from halu_common.textnum import digit_strings, extract_digit_groups, mask_digits, relation  # noqa: E402


class ExtractTests(unittest.TestCase):
    def forms(self, text):
        return [(g.digits, g.form) for g in extract_digit_groups(text)]

    def test_contiguous(self):
        self.assertEqual(self.forms("my zip is 10001"), [("10001", "contiguous")])

    def test_spaced(self):
        self.assertEqual(self.forms("You entered 1 0 0 0 1. Is that correct?"), [("10001", "spaced")])

    def test_words(self):
        self.assertEqual(self.forms("one zero zero zero one"), [("10001", "words")])

    def test_two_groups_split_by_words(self):
        self.assertEqual(self.forms("one two three four five and two three four five six"),
                         [("12345", "words"), ("23456", "words")])

    def test_double_and_oh(self):
        self.assertEqual(self.forms("double five oh eight two"), [("55082", "words")])

    def test_tens_compound(self):
        self.assertEqual(self.forms("fifty five oh eight two"), [("55082", "words")])

    def test_zip_plus4_and_dtmf(self):
        self.assertEqual(self.forms("12345-6789"), [("123456789", "zip_plus4")])
        self.assertEqual(self.forms("dtmf:12345"), [("12345", "dtmf")])

    def test_exclusions(self):
        self.assertEqual(self.forms("a $100 fee"), [])
        self.assertEqual(self.forms("50% off"), [])
        self.assertEqual(self.forms("on 2026-09-18"), [])
        self.assertEqual(self.forms("oh no"), [])

    def test_spans(self):
        group = extract_digit_groups("zip 55082 please")[0]
        self.assertEqual((group.start, group.end, group.text), (4, 9, "55082"))

    def test_digit_strings_min_len(self):
        self.assertEqual(digit_strings("call 1 or 2, zip 10001", min_len=3), ["10001"])


class RelationTests(unittest.TestCase):
    def test_relations(self):
        self.assertEqual(relation("10001", "10001"), "equal")
        self.assertEqual(relation("10001", "100011"), "truncated_prefix")
        self.assertEqual(relation("00011", "100011"), "truncated_suffix")
        self.assertEqual(relation("10000", "1000"), "padded_suffix")
        self.assertEqual(relation("01000", "1000"), "padded_prefix")
        self.assertEqual(relation("10010", "10001"), "transposition")
        self.assertEqual(relation("10002", "10001"), "substitution1")
        self.assertEqual(relation("99999", "10001"), "none")


class MaskTests(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(mask_digits("zip 10001 and 1 0 0 0 1"), "zip 10*** and 10***")
        self.assertEqual(mask_digits("turn 3"), "turn 3")


if __name__ == "__main__":
    unittest.main()

"""Digit extraction from voice transcripts and PII masking.

Customers read numbers in many forms: "10001", "1 0 0 0 1", "one zero zero zero one", "double five oh
eight two", DTMF strings, ZIP+4 with a hyphen. extract_digit_groups() returns every group with its
character span and form so grounding checks can compare a tool argument with what was actually said.

Standard library only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "naught": "0", "nought": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_OH_WORDS = {"oh", "o"}
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")
_SEPARATORS = {",", "-", ".", "/"}
_DATE_RES = (re.compile(r"^\d{4}-\d{2}-\d{2}$"), re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"), re.compile(r"^\d{4}/\d{2}/\d{2}$"))


@dataclass
class DigitGroup:
    digits: str
    start: int
    end: int
    form: str  # contiguous | spaced | words | mixed | dtmf | zip_plus4
    text: str

    @property
    def length(self) -> int:
        return len(self.digits)

    def first(self, n: int = 5) -> str:
        return self.digits[:n]


def _is_digitish(token: str) -> bool:
    low = token.lower()
    return token.isdigit() or low in DIGIT_WORDS or low in TEENS or low in TENS or low in ("double", "triple")


def extract_digit_groups(text: str) -> List[DigitGroup]:
    """Return every digit group in ``text`` in order of appearance."""
    source = text or ""
    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(source)]
    groups: List[DigitGroup] = []
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i][0]
        j = i
        dtmf = False
        if tok.lower() == "dtmf":
            dtmf = True
            j += 1
            while j < n and tokens[j][0] in {":", "=", "<", ">", "_"}:
                j += 1
        parts = []  # (digits, kind, start, end)
        while j < n:
            t, ts, te = tokens[j]
            low = t.lower()
            if t.isdigit():
                parts.append((t, "contiguous" if len(t) > 1 else "single", ts, te))
                j += 1
                continue
            if low in DIGIT_WORDS:
                parts.append((DIGIT_WORDS[low], "oh" if low in _OH_WORDS else "word", ts, te))
                j += 1
                continue
            if low in TEENS:
                parts.append((str(TEENS[low]), "word", ts, te))
                j += 1
                continue
            if low in TENS:
                value = TENS[low]
                if j + 1 < n:
                    nxt = tokens[j + 1][0].lower()
                    if nxt in DIGIT_WORDS and nxt not in _OH_WORDS and nxt != "zero":
                        value += int(DIGIT_WORDS[nxt])
                        parts.append((str(value), "word", ts, tokens[j + 1][2]))
                        j += 2
                        continue
                parts.append((str(value), "word", ts, te))
                j += 1
                continue
            if low in ("double", "triple") and j + 1 < n and tokens[j + 1][0].lower() in DIGIT_WORDS:
                digit = DIGIT_WORDS[tokens[j + 1][0].lower()]
                parts.append((digit * (2 if low == "double" else 3), "word", ts, tokens[j + 1][2]))
                j += 2
                continue
            if t in _SEPARATORS and parts and j + 1 < n and _is_digitish(tokens[j + 1][0]):
                j += 1
                continue
            break
        if not parts:
            i += 1
            continue
        i = max(j, i + 1)
        if all(kind == "oh" for _, kind, _, _ in parts):
            continue  # "oh no" is not a number
        start, end = parts[0][2], parts[-1][3]
        span_text = source[start:end]
        if start > 0 and source[start - 1] == "$":
            continue
        if end < len(source) and source[end] == "%":
            continue
        if any(rx.match(span_text) for rx in _DATE_RES):
            continue
        digits = "".join(p[0] for p in parts)
        kinds = {p[1] for p in parts}
        if dtmf:
            form = "dtmf"
        elif re.match(r"^\d{5}-\d{4}$", span_text):
            form = "zip_plus4"
        elif kinds == {"contiguous"} and len(parts) == 1:
            form = "contiguous"
        elif kinds <= {"single", "oh"}:
            form = "spaced"
        elif kinds <= {"word", "oh"}:
            form = "words"
        else:
            form = "mixed"
        groups.append(DigitGroup(digits=digits, start=start, end=end, form=form, text=span_text))
    return groups


def digit_strings(text: str, min_len: int = 1) -> List[str]:
    """Just the digit strings of every group with at least ``min_len`` digits."""
    return [g.digits for g in extract_digit_groups(text) if g.length >= min_len]


def relation(candidate: str, reference: str) -> str:
    """How ``candidate`` relates to ``reference`` (both digit strings).

    equal | truncated_prefix | truncated_suffix | truncated_inner | padded_prefix | padded_suffix |
    transposition | substitution1 | none
    """
    if candidate == reference:
        return "equal"
    if not candidate or not reference:
        return "none"
    if len(candidate) < len(reference):
        if reference.startswith(candidate):
            return "truncated_prefix"
        if reference.endswith(candidate):
            return "truncated_suffix"
        if candidate in reference:
            return "truncated_inner"
    if len(candidate) > len(reference):
        if candidate.startswith(reference):
            return "padded_suffix"
        if candidate.endswith(reference):
            return "padded_prefix"
    if len(candidate) == len(reference):
        diffs = [k for k in range(len(candidate)) if candidate[k] != reference[k]]
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1 and candidate[diffs[0]] == reference[diffs[1]] \
                and candidate[diffs[1]] == reference[diffs[0]]:
            return "transposition"
        if len(diffs) == 1:
            return "substitution1"
    return "none"


_MASK_RE = re.compile(r"\d{4,}")
_SPACED_RE = re.compile(r"(?<!\d)(?:\d[\s\-]){3,}\d(?!\d)")


def mask_digits(text: str, keep: int = 2) -> str:
    """Mask digit runs of four or more (and spaced digit sequences) for chat summaries and reports."""
    if not text:
        return text

    def _mask(match):
        value = match.group(0)
        digits_only = "".join(ch for ch in value if ch.isdigit())
        return digits_only[:keep] + "*" * (len(digits_only) - keep)

    masked = _SPACED_RE.sub(_mask, text)
    return _MASK_RE.sub(_mask, masked)

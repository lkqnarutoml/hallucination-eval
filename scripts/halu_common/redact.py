"""Redaction and capping of payload values before anything reaches a model (standard library only).

Rules, applied to string leaves only (booleans, numbers and nulls pass through untouched):

    bearer   the whole string is "Bearer <16+ non-space chars>"            -> [redacted:bearer_token len=N]
    jwt      three base64url segments joined by dots (first two 10+ chars) -> [redacted:jwt len=N], also inside
             longer strings
    key      the key name says secret (token, secret, password, passwd, pwd, api_key, authorization, auth, jwt,
             cookie, credential(s), session_key, access_key, private_key, client_secret, signature) as a whole
             segment delimited by _ . - or the ends, and the value is 8+ chars  -> [redacted:<key> len=N]
    pan      a run of 13 to 19 digits (single spaces or hyphens allowed between digits) becomes **** plus its
             last four; counted as "pan" when it passes the Luhn check, "digits13_19" otherwise. Skipped under
             keys that name time, ids or sequence numbers, and a bare 13-digit run in the epoch-millisecond
             range is treated as a timestamp unless the key names a card or account.
    opaque   32+ chars, letters and digits, no whitespace, not a path or URL, not hex only, not under an id-like
             key: COUNTED as "opaque_seen"; redacted only when redact_opaque is set (identifiers such as session
             ids look the same, and a redacted id breaks argument grounding).

Placeholders contain "[" and a space, so no rule matches them again (idempotent). Keys never redacted by the key
rule: last4 / last_four / zip / postal code / user_zip / zip_on_file, because those are evidence the evaluator
compares. cap_payload() keeps scalars to a depth, keeps the first items of long lists and marks what was cut, so
status fields survive for the checker and the evaluator while payment histories and token blobs do not.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

BEARER_RE = re.compile(r"^\s*bearer\s+\S{16,}\s*$", re.I)
BEARER_SUB_RE = re.compile(r"\bBearer\s+\S{16,}", re.I)
JWT_RE = re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*$")
JWT_SUB_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{7,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*")
SECRET_KEY_RE = re.compile(r"(?:^|[_.\-])(token|bearer|authorization|auth|secret|passwd|password|pwd|api_?key|jwt|cookie|"
                           r"credentials?|session_?key|access_?key|private_?key|client_?secret|signature)(?:$|[_.\-])", re.I)
NEVER_KEY_RE = re.compile(r"^(last4|last_?four|last4carddigits|zip|zip_?code|postal_?code|user_zip|zip_on_file)$", re.I)
PAN_RE = re.compile(r"(?<![\d])(?:\d[ -]?){12,18}\d(?![\d])")
PAN_SKIP_KEY_RE = re.compile(r"(time|date|epoch|^ts$|seq|sequence|_id$|^id$|expir|created|updated|issued|^start|^end|"
                             r"duration|timestamp|phone|zip|postal)", re.I)
CARD_KEY_RE = re.compile(r"(card|pan|account|acct)", re.I)
OPAQUE_RE = re.compile(r"^[A-Za-z0-9+=_.:-]{32,}$")
HEX_RE = re.compile(r"^[0-9a-fA-F-]+$")
ID_KEY_RE = re.compile(r"(?:^|[_.\-])(id|ids|uuid|guid|name|locator|path|url|uri|ref|reference|number|no)$", re.I)
EPOCH_MS_MIN = 1_000_000_000_000   # 2001-09-09
EPOCH_MS_MAX = 4_102_444_800_000   # 2100-01-01
PLACEHOLDER_PREFIX = "[redacted:"


def _count(counts: Optional[Dict[str, int]], key: str, n: int = 1) -> None:
    if counts is not None:
        counts[key] = counts.get(key, 0) + n


def luhn_ok(digits: str) -> bool:
    total = 0
    for index, ch in enumerate(reversed(digits)):
        d = int(ch)
        if index % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def last_segment(key: Optional[str]) -> str:
    return (key or "").split(".")[-1].strip().lower()


def mask_pans(text: str, key: Optional[str] = None, counts: Optional[Dict[str, int]] = None) -> str:
    """Replace 13-19 digit runs with **** + last four (substring pass)."""
    last = last_segment(key)
    if last and PAN_SKIP_KEY_RE.search(last) and not CARD_KEY_RE.search(last):
        return text

    def _mask(match: "re.Match[str]") -> str:
        raw = match.group(0)
        digits = re.sub(r"[ -]", "", raw)
        if not 13 <= len(digits) <= 19:
            return raw
        if len(digits) == 13 and raw == digits and EPOCH_MS_MIN <= int(digits) <= EPOCH_MS_MAX and not CARD_KEY_RE.search(last):
            return raw  # an epoch-millisecond timestamp, not a card
        _count(counts, "pan" if luhn_ok(digits) else "digits13_19")
        return "****" + digits[-4:]

    return PAN_RE.sub(_mask, text)


def redact_text(text: str, counts: Optional[Dict[str, int]] = None) -> str:
    """For utterances: JWT, bearer and PAN substring rules only, never truncation."""
    if not isinstance(text, str) or PLACEHOLDER_PREFIX in text:
        return text
    out = JWT_SUB_RE.sub(lambda m: _placeholder("jwt", len(m.group(0)), counts), text)
    out = BEARER_SUB_RE.sub(lambda m: _placeholder("bearer_token", len(m.group(0)), counts, "bearer"), out)
    return mask_pans(out, None, counts)


def _placeholder(label: str, length: int, counts: Optional[Dict[str, int]], counter: Optional[str] = None) -> str:
    _count(counts, counter or label)
    return "%s%s len=%d]" % (PLACEHOLDER_PREFIX, label, length)


def is_opaque(value: str, key: Optional[str] = None) -> bool:
    if len(value) < 32 or not OPAQUE_RE.match(value) or HEX_RE.match(value):
        return False
    if "/" in value or "://" in value or "\\" in value:
        return False
    if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
        return False
    return not ID_KEY_RE.search(last_segment(key)) if key else True


def redact_string(value: str, key: Optional[str] = None, counts: Optional[Dict[str, int]] = None,
                  redact_opaque: bool = False) -> str:
    if value.startswith(PLACEHOLDER_PREFIX):
        return value
    last = last_segment(key)
    if BEARER_RE.match(value):
        return _placeholder("bearer_token", len(value), counts, "bearer")
    if JWT_RE.match(value) and value.startswith("eyJ"):
        return _placeholder("jwt", len(value), counts)
    if last and not NEVER_KEY_RE.match(last) and SECRET_KEY_RE.search(last) and len(value) >= 8:
        _count(counts, "key:" + last)
        return "%s%s len=%d]" % (PLACEHOLDER_PREFIX, last, len(value))
    out = JWT_SUB_RE.sub(lambda m: _placeholder("jwt", len(m.group(0)), counts), value)
    out = BEARER_SUB_RE.sub(lambda m: _placeholder("bearer_token", len(m.group(0)), counts, "bearer"), out)
    if not (last and NEVER_KEY_RE.match(last)):
        out = mask_pans(out, key, counts)
    if out == value and is_opaque(value, key):
        _count(counts, "opaque_seen")
        if redact_opaque:
            return _placeholder("opaque", len(value), counts)
    return out


def redact_value(value: Any, key: Optional[str] = None, counts: Optional[Dict[str, int]] = None,
                 redact_opaque: bool = False) -> Any:
    """Recurse into dicts (child key names apply) and lists (the parent key applies); touch string leaves only."""
    if isinstance(value, dict):
        return {k: redact_value(v, k, counts, redact_opaque) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, key, counts, redact_opaque) for v in value]
    if isinstance(value, str):
        return redact_string(value, key, counts, redact_opaque)
    return value


def truncate_string(value: str, max_string: int, counts: Optional[Dict[str, int]] = None) -> str:
    if max_string and len(value) > max_string and not value.startswith(PLACEHOLDER_PREFIX):
        _count(counts, "truncated")
        return value[:max_string] + "...[+%d chars]" % (len(value) - max_string)
    return value


def _cap(value: Any, depth: int, max_string: int, max_depth: int, list_items: int, counts: Optional[Dict[str, int]]) -> Any:
    if isinstance(value, str):
        return truncate_string(value, max_string, counts)
    if isinstance(value, dict):
        if depth > max_depth:
            return {"_summary": "dict with %d keys" % len(value)}
        return {k: _cap(v, depth + 1, max_string, max_depth, list_items, counts) for k, v in value.items()}
    if isinstance(value, list):
        if depth > max_depth:
            return [{"_summary": "list with %d items" % len(value)}]
        kept = [_cap(v, depth + 1, max_string, max_depth, list_items, counts) for v in value[:list_items]] if list_items else []
        if len(value) > len(kept):
            kept.append({"_summary": "list with %d items, first %d kept" % (len(value), len(kept))})
        return kept
    return value


def cap_payload(value: Any, max_string: int = 600, max_depth: int = 2, list_items: int = 8, max_payload: int = 2500,
                counts: Optional[Dict[str, int]] = None) -> Any:
    """Shrink a parsed payload: scalars kept to max_depth, long lists cut to list_items, strings to max_string.

    When the result still exceeds max_payload characters the depth and list budget are tightened, and finally
    only top-level scalars and summaries remain; a dict then carries {"_capped": {"chars": <original>}}.
    """
    if not isinstance(value, (dict, list)):
        return truncate_string(value, max_string, counts) if isinstance(value, str) else value
    original = len(json.dumps(value, ensure_ascii=False, default=str))
    out = _cap(value, 0, max_string, max_depth, list_items, counts)
    if max_payload and len(json.dumps(out, ensure_ascii=False, default=str)) > max_payload:
        # Tighten in an order that keeps scalar fields (status, names, counts) as long as possible: fewer list
        # items and shorter strings first, nesting depth last.
        ladder = [(min(max_string or 200, 200), max_depth, max(1, list_items // 2)),
                  (min(max_string or 80, 80), max_depth, 1),
                  (min(max_string or 80, 80), 1, 1),
                  (min(max_string or 80, 80), 0, 0)]
        for step_string, step_depth, step_items in ladder:
            out = _cap(value, 0, step_string, step_depth, step_items, None)
            if len(json.dumps(out, ensure_ascii=False, default=str)) <= max_payload:
                break
        _count(counts, "capped")
        if isinstance(out, dict):
            out["_capped"] = {"chars": original}
        else:
            out.append({"_capped": {"chars": original}})
    return out

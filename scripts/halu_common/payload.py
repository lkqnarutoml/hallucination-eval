"""Payload parsing helpers shared by the hallucination-eval scripts.

Tool arguments and responses reach the evaluator in many encodings: native dicts, JSON strings,
double-encoded JSON strings, Python dict reprs (single quotes, True/False/None) and nested wrappers
such as {"toolCall": {"args": {...}}} or {"result": {...}}. parse_payload() turns any of them into a
plain dict and records which representation it saw, so reports can state what an export contained.

Standard library only.
"""
from __future__ import annotations

import ast
import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Tuple

WRAPPER_KEYS = (
    "toolCall", "tool_call", "functionCall", "function_call", "toolResponse", "tool_response",
    "functionResponse", "function_response", "args", "arguments", "input", "inputs", "payload",
    "parameters", "params", "request", "result", "response", "output", "outputs", "content", "data", "value",
)
META_KEYS = ("id", "name", "tool", "displayName", "display_name", "type")
# Keys that mark a leaf payload: once one of these is present we stop unwrapping.
DOMAIN_STOP_KEYS = (
    "status", "zip_code", "zipcode", "confirmed", "reason", "session_escalated", "tokens", "error", "message",
)
_PY_LITERALS = {"True": "true", "False": "false", "None": "null", "NaN": "null"}
_PY_LITERAL_RE = re.compile(r"\b(True|False|None|NaN)\b")
_NUMERIC_RE = re.compile(r"^[-+]?\d+(\.\d+)?$")


@dataclass
class Parsed:
    """Result of parse_payload()."""

    value: Any
    representation: str
    layers: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    raw: Any = None

    def as_dict(self) -> dict:
        if isinstance(self.value, dict):
            return self.value
        return {"_value": self.value}


def decode_text(text: str) -> Tuple[Any, Optional[str]]:
    """Decode one string layer. Returns (value, how) or (None, None) when the text is not structured.

    Purely numeric strings are left alone on purpose: a ZIP such as "10001" must stay a string.
    """
    stripped = (text or "").strip()
    if not stripped or _NUMERIC_RE.match(stripped):
        return None, None
    try:
        return json.loads(stripped), "json"
    except ValueError:
        pass
    if stripped[0] in "{[(\"'":
        try:
            value = ast.literal_eval(stripped)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            value = _SENTINEL
        if value is not _SENTINEL and (value is None or isinstance(value, (dict, list, tuple, str, int, float, bool))):
            return (list(value) if isinstance(value, tuple) else value), "py_repr"
    if _PY_LITERAL_RE.search(stripped):
        substituted = _PY_LITERAL_RE.sub(lambda m: _PY_LITERALS[m.group(1)], stripped)
        try:
            return json.loads(substituted), "json_pyliterals"
        except ValueError:
            pass
    return None, None


_SENTINEL = object()


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and value != value


def parse_payload(value: Any, max_decode: int = 3, max_unwrap: int = 4) -> Parsed:
    """Turn any payload representation into a dict (or list) and say what was seen.

    Order of work: empty -> bytes -> repeated string decoding -> structural unwrapping through
    single wrapper keys (lifting id/name/displayName into ``meta``) -> decoding of string leaves that
    still look like JSON. Scalars end up as {"_value": scalar}.
    """
    layers: list = []
    raw = value
    if value is None or _is_nan(value) or (isinstance(value, str) and not value.strip()):
        return Parsed({}, "empty", ["empty"], {}, raw)
    current: Any = value
    if isinstance(current, (bytes, bytearray)):
        current = bytes(current).decode("utf-8", "replace")
        layers.append("bytes->str")
    representation: Optional[str] = None
    decodes = 0
    while isinstance(current, str) and decodes < max_decode:
        decoded, how = decode_text(current)
        if how is None:
            break
        decodes += 1
        layers.append(how)
        if representation is None:
            representation = how
        elif how == "json" and representation == "json":
            representation = "json_double"
        current = decoded
    if isinstance(current, str):
        return Parsed({"_value": current}, representation or "scalar", layers or ["scalar"], {}, raw)
    if current is None or _is_nan(current):
        return Parsed({}, representation or "empty", layers or ["empty"], {}, raw)
    if representation is None:
        representation = "dict" if isinstance(current, dict) else ("list" if isinstance(current, list) else "scalar")
    if isinstance(current, (dict, list)):
        current = copy.deepcopy(current)
    meta: dict = {}
    unwraps = 0
    while isinstance(current, dict) and unwraps < max_unwrap:
        keys = list(current.keys())
        if any(k in DOMAIN_STOP_KEYS for k in keys):
            break
        wrappers = [k for k in keys if k in WRAPPER_KEYS]
        others = [k for k in keys if k not in WRAPPER_KEYS]
        if len(wrappers) == 1 and all(k in META_KEYS for k in others):
            for k in others:
                meta[k] = current[k]
            current = current[wrappers[0]]
            layers.append("unwrap:" + wrappers[0])
            unwraps += 1
            if isinstance(current, str):
                decoded, how = decode_text(current)
                if how is not None:
                    layers.append(how)
                    current = decoded
            continue
        break
    if isinstance(current, dict):
        for key, item in list(current.items()):
            if isinstance(item, str) and item.lstrip()[:1] in ("{", "["):
                decoded, how = decode_text(item)
                if how is not None and isinstance(decoded, (dict, list)):
                    current[key] = decoded
                    layers.append("leaf:%s:%s" % (key, how))
        return Parsed(current, representation, layers, meta, raw)
    if isinstance(current, list):
        return Parsed(current, "list" if representation == "dict" else representation, layers, meta, raw)
    return Parsed({"_value": current}, "scalar", layers or ["scalar"], meta, raw)


def canonical_tool_name(raw: Any, display: Any = None, aliases: Optional[dict] = None,
                        strip_prefixes: Iterable[str] = ("demo-",)) -> str:
    """Reduce a CES resource path or display name to a plain tool identifier.

    'projects/p/locations/l/apps/a/tools/demo-validate-zip-code' -> 'validate_zip_code'.
    """
    name = str(display or raw or "").strip()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    lowered = name.lower()
    for prefix in strip_prefixes:
        if lowered.startswith(prefix.lower()):
            name = name[len(prefix):]
            lowered = name.lower()
    name = name.replace("-", "_").strip()
    if aliases and name in aliases:
        return aliases[name]
    return name


def find_key(obj: Any, candidates: Iterable[str], max_depth: int = 3) -> Tuple[Any, Optional[str]]:
    """Breadth-first search for the first key (case-insensitive) among ``candidates``.

    Returns (value, dotted_path) or (None, None).
    """
    wanted = {str(c).lower() for c in candidates}
    queue = [(obj, "", 0)]
    while queue:
        current, path, depth = queue.pop(0)
        if isinstance(current, dict):
            for key, val in current.items():
                if str(key).lower() in wanted:
                    return val, (path + "." + str(key)) if path else str(key)
            if depth < max_depth:
                for key, val in current.items():
                    if isinstance(val, (dict, list)):
                        queue.append((val, (path + "." + str(key)) if path else str(key), depth + 1))
        elif isinstance(current, list) and depth < max_depth:
            for index, val in enumerate(current):
                if isinstance(val, (dict, list)):
                    queue.append((val, "%s[%d]" % (path, index), depth + 1))
    return None, None


def normalize_digits(value: Any) -> str:
    """Keep only the digits of ``value`` ('1 0 0 0 1' -> '10001'); '' for None."""
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def status_of(response: Any) -> Optional[str]:
    """Upper-cased 'status' of a parsed tool response, searching nested wrappers."""
    parsed = response if isinstance(response, (dict, list)) else parse_payload(response).value
    value, _ = find_key(parsed, ("status",))
    if value is None:
        return None
    return str(value).strip().upper()

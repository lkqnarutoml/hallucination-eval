"""Locators: strings that point from a finding back to the exact source line or cell.

Formats
    events:<file>#seq=<n>[&chunk=<json-pointer>]   one line of an events.jsonl file (by "sequence")
    json:<file>#<json-pointer>                      a node of a JSON file
    xlsx:<file>!<sheet>!<cell>                      one cell of a workbook
    csv:<file>:L<line>                              one line of a CSV file (1-based, header is line 1)

resolve_locator() reopens the source and returns a short snippet so a validator can confirm a finding
without the evaluator's help. Standard library only (openpyxl is imported lazily for xlsx).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_LOCATOR_RE = re.compile(r"^(?P<kind>events|json|xlsx|csv):(?P<rest>.+)$")


def events_locator(path: str, seq: int, chunk: Optional[str] = None) -> str:
    base = "events:%s#seq=%s" % (path, seq)
    return base + ("&chunk=%s" % chunk if chunk else "")


def json_locator(path: str, pointer: str) -> str:
    return "json:%s#%s" % (path, pointer)


def xlsx_locator(path: str, sheet: str, cell: str) -> str:
    return "xlsx:%s!%s!%s" % (path, sheet, cell)


def csv_locator(path: str, line: int) -> str:
    return "csv:%s:L%d" % (path, line)


def column_letter(index_1_based: int) -> str:
    letters = ""
    n = index_1_based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def parse_locator(locator: str) -> dict:
    match = _LOCATOR_RE.match(locator or "")
    if not match:
        raise ValueError("not a locator: %r" % (locator,))
    kind, rest = match.group("kind"), match.group("rest")
    if kind == "events":
        path, _, frag = rest.partition("#")
        params = dict(p.split("=", 1) for p in frag.split("&") if "=" in p)
        return {"kind": kind, "path": path, "seq": int(params.get("seq", "0")), "chunk": params.get("chunk")}
    if kind == "json":
        path, _, pointer = rest.partition("#")
        return {"kind": kind, "path": path, "pointer": pointer}
    if kind == "xlsx":
        path, sheet, cell = rest.rsplit("!", 2)
        return {"kind": kind, "path": path, "sheet": sheet, "cell": cell}
    path, _, line = rest.rpartition(":L")
    return {"kind": kind, "path": path, "line": int(line)}


def _pointer_get(node, pointer: str):
    for part in [p for p in pointer.strip("/").split("/") if p != ""]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def resolve_locator(locator: str, base_dir: Optional[str] = None, max_chars: int = 400) -> str:
    """Return a snippet of the source the locator points at. Raises on failure."""
    info = parse_locator(locator)
    path = Path(info["path"])
    if not path.is_absolute() and base_dir:
        path = Path(base_dir) / path
    if info["kind"] == "events":
        wanted = '"sequence": %d,' % info["seq"]
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if wanted in line[:64] or line.startswith('{"sequence": %d,' % info["seq"]):
                    if info.get("chunk"):
                        try:
                            event = json.loads(line)
                            node = _pointer_get(event.get("response", event), info["chunk"])
                            return json.dumps(node, ensure_ascii=False)[:max_chars]
                        except (KeyError, IndexError, ValueError, TypeError):
                            pass
                    return line.strip()[:max_chars]
        raise LookupError("sequence %d not found in %s" % (info["seq"], path))
    if info["kind"] == "json":
        with path.open("r", encoding="utf-8") as handle:
            node = _pointer_get(json.load(handle), info["pointer"])
        return json.dumps(node, ensure_ascii=False)[:max_chars]
    if info["kind"] == "xlsx":
        import openpyxl  # lazy: only xlsx sources need it

        book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        sheet = book[info["sheet"]] if info["sheet"] in book.sheetnames else book[book.sheetnames[0]]
        value = sheet[info["cell"]].value
        return str(value)[:max_chars]
    with path.open("r", encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, start=1):
            if number == info["line"]:
                return line.rstrip("\n")[:max_chars]
    raise LookupError("line %d not found in %s" % (info["line"], path))

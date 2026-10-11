"""Small JSON / JSONL file helpers with explicit UTF-8 handling (Windows-safe)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Tuple


def read_json(path) -> Any:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path, data: Any, indent: int = 2) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent, sort_keys=False)
        handle.write("\n")
    tmp.replace(target)
    return target


def iter_jsonl(path) -> Iterator[Tuple[int, Any]]:
    """Yield (line_number, object) for each non-empty line; a truncated last line is skipped with a warning object."""
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield number, json.loads(stripped)
            except ValueError:
                yield number, {"_parse_error": True, "_line": number}


def read_jsonl(path) -> List[Any]:
    return [obj for _, obj in iter_jsonl(path) if not (isinstance(obj, dict) and obj.get("_parse_error"))]


def write_jsonl(path, rows: Iterable[Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
    return target


def sha256_of_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

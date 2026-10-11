#!/usr/bin/env python3
"""Inventory the materials of a conversational agent: tools, docstrings, state effects, the agent-to-tool
tree, callbacks, prompts, guardrails and declared variables.

    python scripts/inventory_materials.py PATH [PATH ...] --out materials_inventory.json [--summary materials_summary.md]
           [--agents-file agents.json]

What it reads
    *.py                Python tool and callback sources (ast): top-level functions, docstrings, parameters, return
                        annotation, `return {"status": ...}` literals, context.state reads/writes, `tools.<x>` calls,
                        module-level constants. Functions are classified as tool, callback, gate or helper.
    CES export folder   The "Export agent" package of CX Agent Studio, in its JSON or YAML flavour:
                        app.json|yaml (rootAgent, variableDeclarations, guardrails), agents/<name>/<name>.json|yaml
                        (tools, childAgents, instruction or a sibling instruction.txt, before/after callbacks),
                        tools/<name>/<name>.json|yaml (+ python_function/python_code.py or inline pythonCode),
                        toolsets/<name>/<name>.json|yaml (OpenAPI), guardrails/<name>/<name>.json|yaml,
                        environment.json, pythonEnvFiles.json. Resource ids in tool and agent references are
                        resolved to display names.
    app_snapshot.json   A deployed-app snapshot (tools with pythonFunction.{name,description,pythonCode}; agents
                        with their tool bindings and instructions).
    agents.json         A hand-written tree {"agents": [{"name", "tools": [...], "sub_agents": [...], ...}]}.
    variables.json      Declared session variables.
    *.txt / *.md        Prompt and instruction files (path, size, headings, first line).

The output is data for the architect role. It never interprets behaviour. Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, write_json  # noqa: E402
from halu_common.payload import canonical_tool_name  # noqa: E402

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache", "_evidence", "site-packages"}
MAX_FILE_BYTES = 5 * 1024 * 1024
PROMPT_SUFFIXES = {".txt", ".md", ".prompt"}
CALLBACK_NAMES = {"before_agent_callback", "before_model_callback", "after_model_callback", "after_agent_callback",
                  "before_tool_callback", "after_tool_callback"}
CALLBACK_STAGES = (("before_agent", "BeforeAgent"), ("before_model", "BeforeModel"), ("after_model", "AfterModel"),
                   ("after_agent", "AfterAgent"), ("before_tool", "BeforeTool"), ("after_tool", "AfterTool"))
CALLBACK_KEYS = {"beforeAgentCallbacks": "BeforeAgent", "beforeModelCallbacks": "BeforeModel", "afterModelCallbacks": "AfterModel",
                 "afterAgentCallbacks": "AfterAgent", "beforeToolCallbacks": "BeforeTool", "afterToolCallbacks": "AfterTool",
                 "before_agent_callbacks": "BeforeAgent", "before_model_callbacks": "BeforeModel", "after_model_callbacks": "AfterModel"}
SPECIAL_JSON = {"app_snapshot.json", "agents.json", "variables.json"}


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


# ----------------------------------------------------------------------------------------------------------
# Python sources
# ----------------------------------------------------------------------------------------------------------
def _annotation(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - very old Python
        return None


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _is_context_state(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "state" and isinstance(node.value, ast.Name)
            and node.value.id == "context")


def _subscript_key(node: ast.Subscript) -> Optional[str]:
    key = node.slice
    if isinstance(key, ast.Constant):
        return str(key.value)
    return None


def analyze_python_source(source: str, rel_path: str) -> dict:
    out: dict = {"file": rel_path, "functions": [], "constants": [], "parse_error": None}
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        out["parse_error"] = "%s (line %s)" % (error.msg, error.lineno)
        return out
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _literal(node.value)
            if value is not None and len(json.dumps(value, default=str)) <= 2000:
                out["constants"].append({"name": node.targets[0].id, "value": value, "line": node.lineno})
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = {
                "name": node.name, "file": rel_path, "line": node.lineno,
                "docstring": ast.get_docstring(node) or "",
                "params": [], "returns": _annotation(node.returns),
                "return_literals": [], "state_reads": [], "state_writes": [], "external_calls": [],
            }
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
            for arg, default in zip(node.args.args, defaults):
                func["params"].append({"name": arg.arg, "type": _annotation(arg.annotation),
                                       "default": _literal(default) if default is not None else None,
                                       "required": default is None})
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    literal = _literal(sub.value)
                    if isinstance(literal, dict):
                        func["return_literals"].append(literal)
                if isinstance(sub, (ast.Assign, ast.AugAssign)):
                    targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                    for target in targets:
                        if isinstance(target, ast.Subscript) and _is_context_state(target.value):
                            key = _subscript_key(target)
                            if key and key not in func["state_writes"]:
                                func["state_writes"].append(key)
                if isinstance(sub, ast.Subscript) and _is_context_state(sub.value) and isinstance(sub.ctx, ast.Load):
                    key = _subscript_key(sub)
                    if key and key not in func["state_reads"]:
                        func["state_reads"].append(key)
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    callee = sub.func
                    if callee.attr == "get" and _is_context_state(callee.value) and sub.args and isinstance(sub.args[0], ast.Constant):
                        key = str(sub.args[0].value)
                        if key not in func["state_reads"]:
                            func["state_reads"].append(key)
                    if isinstance(callee.value, ast.Name) and callee.value.id == "tools":
                        if callee.attr not in func["external_calls"]:
                            func["external_calls"].append(callee.attr)
            statuses = sorted({str(lit.get("status")) for lit in func["return_literals"] if isinstance(lit, dict) and "status" in lit})
            func["status_values"] = statuses
            out["functions"].append(func)
    return out


def function_role(name: str, rel_path: str) -> str:
    """tool | callback | gate | helper, from the function name and where the file lives."""
    lowered = rel_path.lower().replace("\\", "/")
    if name in CALLBACK_NAMES:
        return "callback"
    if name.startswith("check_") or name.startswith("gate_"):
        return "gate"
    if "callback" in lowered or "/cb_" in lowered or lowered.startswith("cb_"):
        return "helper"
    if name.startswith("_") and name != "_initialize_session_for_dev":
        return "helper"
    return "tool"


def callback_stage(rel_path: str, function_names: List[str]) -> str:
    lowered = rel_path.lower().replace("\\", "/")
    for key, stage in CALLBACK_STAGES:
        if key in lowered or key.replace("_", "") in lowered.replace("_", ""):
            return stage
    for name in function_names:
        for key, stage in CALLBACK_STAGES:
            if name.startswith(key):
                return stage
    return "Callback"


def agent_of_path(rel_path: str) -> Optional[str]:
    parts = rel_path.replace("\\", "/").split("/")
    if "agents" in parts:
        index = parts.index("agents")
        if index + 1 < len(parts):
            return canonical_tool_name(parts[index + 1])
    stem = Path(rel_path).stem.lower()
    for prefix, agent in (("cb_root", "root"), ("cb_replace", "replace_debit_card_agent"), ("cb_delivery", "card_delivery_status_agent"),
                          ("cb_no_ivr", "agent_transfer_no_ivr_intent"), ("cb_transfer_to_human", "Transfer_to_human_agent")):
        if stem.startswith(prefix):
            return agent
    return None


# ----------------------------------------------------------------------------------------------------------
# a small YAML reader for CES packaging files (mappings, lists of scalars/mappings, block scalars)
# ----------------------------------------------------------------------------------------------------------
def _yaml_scalar(text: str) -> Any:
    value = text.strip()
    if value == "" or value == "~" or value == "null":
        return None
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if re.match(r"^-?\d+$", value):
        return int(value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_yaml_scalar(v) for v in inner.split(",")] if inner else []
    return value


def parse_simple_yaml(text: str) -> Any:
    lines = [line.rstrip("\n") for line in text.splitlines()]
    cleaned = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cleaned.append(line)
    position = [0]

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def parse_block(indent: int) -> Any:
        result: Any = None
        while position[0] < len(cleaned):
            line = cleaned[position[0]]
            current = indent_of(line)
            if current < indent:
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                if result is None:
                    result = []
                if not isinstance(result, list):
                    break
                item_text = stripped[2:]
                position[0] += 1
                if ":" in item_text and not item_text.startswith(('"', "'")):
                    key, _, rest = item_text.partition(":")
                    item: dict = {}
                    if rest.strip() in ("|", ">"):
                        item[key.strip()] = parse_block_scalar(current + 2)
                    elif rest.strip():
                        item[key.strip()] = _yaml_scalar(rest)
                    else:
                        item[key.strip()] = parse_block(current + 2)
                    nested = parse_block(current + 2)
                    if isinstance(nested, dict):
                        item.update(nested)
                    result.append(item)
                else:
                    result.append(_yaml_scalar(item_text))
                continue
            if ":" in stripped:
                if result is None:
                    result = {}
                if not isinstance(result, dict):
                    break
                key, _, rest = stripped.partition(":")
                position[0] += 1
                rest = rest.strip()
                if rest in ("|", ">", "|-", ">-"):
                    result[key.strip()] = parse_block_scalar(current + 1)
                elif rest:
                    result[key.strip()] = _yaml_scalar(rest)
                else:
                    result[key.strip()] = parse_block(current + 1)
                continue
            position[0] += 1
        return result

    def parse_block_scalar(min_indent: int) -> str:
        collected = []
        base = None
        while position[0] < len(cleaned):
            line = cleaned[position[0]]
            current = indent_of(line)
            if current < min_indent and line.strip():
                break
            if base is None:
                base = current
            collected.append(line[base:] if len(line) >= base else line.strip())
            position[0] += 1
        return "\n".join(collected)

    return parse_block(0)


def analyze_yaml(text: str, rel_path: str) -> dict:
    try:
        data = parse_simple_yaml(text)
    except Exception as error:  # noqa: BLE001 - any failure falls back to raw text
        return {"file": rel_path, "parsed": None, "error": str(error), "head": text[:1200]}
    return {"file": rel_path, "parsed": data, "error": None}


def _short(name: Any) -> str:
    return canonical_tool_name(name)


# ----------------------------------------------------------------------------------------------------------
# CES export definitions (JSON or YAML mappings with the same keys)
# ----------------------------------------------------------------------------------------------------------
def _last_segment(ref: Any) -> str:
    return str(ref or "").strip().rstrip("/").rsplit("/", 1)[-1]


def _string_ref(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("tool", "toolset", "agent", "name", "displayName", "display_name", "id"):
            if isinstance(item.get(key), str):
                return item[key]
    return ""


def _looks_like_code(text: Any) -> bool:
    return isinstance(text, str) and ("\n" in text or text.lstrip().startswith(("def ", "import ", "from ", "#")))


def classify_definition(data: Any, rel_path: str) -> Optional[Tuple[str, dict]]:
    """Recognise one CES export mapping: ('tool' | 'agent' | 'app' | 'guardrail', definition) or None."""
    if not isinstance(data, dict):
        return None
    parts = rel_path.replace("\\", "/").lower().split("/")
    stem = Path(rel_path).stem
    if "pythonFunction" in data or "openApiToolset" in data or "open_api_toolset" in data or "mcpToolset" in data:
        function = data.get("pythonFunction") or {}
        display = data.get("displayName") or data.get("display_name") or (function.get("name") if isinstance(function, dict) else None) or stem
        kind = "python" if function else ("openapi" if ("openApiToolset" in data or "open_api_toolset" in data) else "other")
        code = function.get("pythonCode") if isinstance(function, dict) else None
        return "tool", {"id": data.get("name"), "display": _short(display), "kind": kind, "file": rel_path,
                        "description": (function.get("description") if isinstance(function, dict) else None) or data.get("description") or "",
                        "inline_code": code if _looks_like_code(code) else None, "code_ref": None if _looks_like_code(code) else code}
    if "rootAgent" in data or "root_agent" in data or "variableDeclarations" in data or "variable_declarations" in data:
        variables = data.get("variableDeclarations") or data.get("variable_declarations") or []
        declared = []
        for item in variables if isinstance(variables, list) else []:
            if isinstance(item, dict):
                schema = item.get("schema") if isinstance(item.get("schema"), dict) else {}
                declared.append({"name": item.get("name"), "type": schema.get("type") or item.get("type"),
                                 "default": item.get("default", item.get("defaultValue")), "description": item.get("description", "")})
        return "app", {"display": data.get("displayName") or stem, "root_agent_raw": data.get("rootAgent") or data.get("root_agent"),
                       "model": (data.get("modelSettings") or {}).get("model") if isinstance(data.get("modelSettings"), dict) else None,
                       "guardrails_raw": data.get("guardrails") or [], "variables": declared, "file": rel_path}
    agent_keys = ("tools", "toolsets", "instruction", "instructions", "childAgents", "subAgents", "sub_agents", "child_agents")
    if any(key in data for key in agent_keys) or any(key in data for key in CALLBACK_KEYS):
        callbacks: List[dict] = []
        for key, stage in CALLBACK_KEYS.items():
            for entry in data.get(key) or []:
                if isinstance(entry, dict):
                    code = entry.get("pythonCode") or entry.get("python_code") or entry.get("code")
                    callbacks.append({"stage": stage, "code": code, "description": entry.get("description") or "", "disabled": bool(entry.get("disabled"))})
                elif isinstance(entry, str):
                    callbacks.append({"stage": stage, "code": entry, "description": "", "disabled": False})
        tools_raw = list(data.get("tools") or []) + list(data.get("toolsets") or [])
        return "agent", {"id": data.get("name"), "display": _short(data.get("displayName") or data.get("display_name") or stem),
                         "tools_raw": tools_raw, "sub_agents_raw": list(data.get("childAgents") or data.get("subAgents") or data.get("sub_agents") or data.get("child_agents") or []),
                         "instruction": data.get("instruction") or data.get("instructions") or "", "callbacks": callbacks,
                         "description": data.get("description") or "", "model": (data.get("modelSettings") or {}).get("model") if isinstance(data.get("modelSettings"), dict) else None,
                         "file": rel_path}
    if "guardrails" in parts:
        return "guardrail", {"display": data.get("displayName") or stem, "file": rel_path, "keys": sorted(str(k) for k in data.keys())[:12]}
    return None


def bindings_from_yaml(parsed: Any, rel_path: str) -> Tuple[List[dict], List[dict]]:
    """Backward-compatible view: (agents, tools) in the simple shape, display names only."""
    classified = classify_definition(parsed, rel_path)
    if classified is None:
        return [], []
    kind, definition = classified
    if kind == "tool":
        return [], [{"name": definition["display"], "description": definition["description"], "kind": definition["kind"], "file": rel_path}]
    if kind == "agent":
        return [{"name": definition["display"], "tools": [_short(_last_segment(_string_ref(t))) for t in definition["tools_raw"]],
                 "instruction_chars": len(str(definition["instruction"] or "")), "instruction_head": str(definition["instruction"] or "")[:400],
                 "sub_agents": [_short(_last_segment(_string_ref(a))) for a in definition["sub_agents_raw"]], "file": rel_path}], []
    return [], []


def analyze_snapshot(data: Any, rel_path: str) -> Tuple[List[dict], List[dict], dict]:
    version = data.get("version", {}) if isinstance(data, dict) else {}
    source = version.get("snapshot") if isinstance(version.get("snapshot"), dict) else (data if isinstance(data, dict) else {})
    app = source.get("app", {}) if isinstance(source.get("app"), dict) else {}
    agents_raw = source.get("agents", [])
    agents_raw = agents_raw.get("agents", []) if isinstance(agents_raw, dict) else agents_raw
    tools_raw = source.get("tools", [])
    tools_raw = tools_raw.get("tools", []) if isinstance(tools_raw, dict) else tools_raw
    tools: List[dict] = []
    python_analyses: List[dict] = []
    for tool in tools_raw or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("pythonFunction") or {}
        name = _short(tool.get("displayName") or function.get("name") or tool.get("name"))
        entry = {"name": name, "description": function.get("description") or tool.get("description") or "",
                 "kind": "python" if function else "other", "file": rel_path}
        code = function.get("pythonCode")
        if code:
            analysis = analyze_python_source(code, "%s#%s" % (rel_path, name))
            python_analyses.append(analysis)
            entry["functions"] = [f["name"] for f in analysis["functions"]]
        tools.append(entry)
    agents: List[dict] = []
    for agent in agents_raw or []:
        if not isinstance(agent, dict):
            continue
        agents.append({"name": _short(agent.get("displayName") or agent.get("name")),
                       "tools": [_short(t) for t in agent.get("tools", []) or []],
                       "instruction_chars": len(str(agent.get("instruction") or "")),
                       "instruction_head": str(agent.get("instruction") or "")[:400],
                       "sub_agents": [_short(a) for a in agent.get("subAgents", []) or agent.get("childAgents", []) or []],
                       "file": rel_path})
    info = {"app_display_name": app.get("displayName", ""), "root_agent": _short(app.get("rootAgent") or ""),
            "global_instruction_chars": len(str(app.get("globalInstruction") or ""))}
    return agents, tools, {"info": info, "python": python_analyses}


def analyze_prompt(text: str, rel_path: str) -> dict:
    lines = text.splitlines()
    headings = [line.strip() for line in lines if re.match(r"^\s*(#+\s|<[a-zA-Z_]+>)", line)]
    return {"file": rel_path, "chars": len(text), "lines": len(lines), "first_line": (lines[0].strip() if lines else "")[:160],
            "headings": headings[:60]}


# ----------------------------------------------------------------------------------------------------------
# walking
# ----------------------------------------------------------------------------------------------------------
def iter_files(paths: List[Path]):
    for root in paths:
        if root.is_file():
            yield root, root.parent
            continue
        for path in sorted(root.rglob("*")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path, root


def _merge_function(entry: dict, func: dict) -> None:
    if not entry.get("docstring"):
        entry["docstring"] = func["docstring"]
    for key in ("params", "returns", "status_values", "state_reads", "state_writes", "external_calls", "line"):
        if not entry.get(key):
            entry[key] = func[key]
    entry["return_literals"] = func["return_literals"][:12]


def build_inventory(paths: List[Path], agents_file: Optional[Path]) -> dict:
    inventory: dict = {"generated_at": now_iso(), "inputs": [str(p) for p in paths], "tools": {}, "agents": {},
                       "prompts": [], "variables": {}, "constants": [], "python_files": [], "yaml_files": [],
                       "snapshots": [], "callbacks": [], "guardrails": [], "app": None, "other_json": [],
                       "unparsed": [], "warnings": []}
    tool_defs: List[dict] = []
    agent_defs: List[dict] = []
    app_defs: List[dict] = []
    path_callbacks: List[dict] = []
    file_index: Dict[str, Path] = {}
    for path, root in iter_files(paths):
        rel = str(path.relative_to(root)) if root in path.parents else str(path)
        file_index[rel.replace("\\", "/")] = path
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            inventory["warnings"].append("skipped %s (%d bytes)" % (rel, size))
            continue
        suffix = path.suffix.lower()
        name = path.name.lower()
        try:
            if suffix == ".py":
                analysis = analyze_python_source(path.read_text(encoding="utf-8", errors="replace"), rel)
                inventory["python_files"].append({"file": rel, "functions": [f["name"] for f in analysis["functions"]],
                                                  "parse_error": analysis["parse_error"]})
                callback_functions = [f["name"] for f in analysis["functions"] if f["name"] in CALLBACK_NAMES]
                if callback_functions:
                    path_callbacks.append({"file": rel, "agent": agent_of_path(rel), "stage": callback_stage(rel, callback_functions),
                                           "functions": callback_functions})
                for func in analysis["functions"]:
                    entry = inventory["tools"].setdefault(func["name"], {"name": func["name"], "sources": []})
                    entry["sources"].append(rel)
                    role = function_role(func["name"], rel)
                    if entry.get("role") in (None, "helper") or role == "tool":
                        entry["role"] = role
                    _merge_function(entry, func)
                for constant in analysis["constants"]:
                    inventory["constants"].append(dict(constant, file=rel))
            elif suffix in (".yaml", ".yml"):
                result = analyze_yaml(path.read_text(encoding="utf-8", errors="replace"), rel)
                inventory["yaml_files"].append({"file": rel, "error": result["error"]})
                if result["error"]:
                    inventory["unparsed"].append({"file": rel, "reason": result["error"], "head": result.get("head", "")})
                else:
                    classified = classify_definition(result["parsed"], rel)
                    if classified:
                        _collect_definition(classified, tool_defs, agent_defs, app_defs, inventory)
            elif name == "app_snapshot.json" or (suffix == ".json" and name.endswith("snapshot.json")):
                agents, tools, extra = analyze_snapshot(read_json(path), rel)
                inventory["snapshots"].append(dict(extra["info"], file=rel, agents=len(agents), tools=len(tools)))
                for agent in agents:
                    inventory["agents"].setdefault(agent["name"], agent)
                for tool in tools:
                    entry = inventory["tools"].setdefault(tool["name"], {"name": tool["name"], "sources": []})
                    entry["sources"].append(rel)
                    if tool.get("description") and not entry.get("description"):
                        entry["description"] = tool["description"]
                for analysis in extra["python"]:
                    for func in analysis["functions"]:
                        entry = inventory["tools"].setdefault(func["name"], {"name": func["name"], "sources": []})
                        _merge_function(entry, func)
            elif name == "agents.json" or (agents_file and path.resolve() == agents_file.resolve()):
                data = read_json(path)
                for agent in data.get("agents", []) if isinstance(data, dict) else []:
                    inventory["agents"][agent.get("name")] = dict(agent, file=rel)
            elif name == "variables.json":
                inventory["variables"][rel] = read_json(path)
            elif suffix == ".json":
                data = read_json(path)
                classified = classify_definition(data, rel)
                if classified:
                    _collect_definition(classified, tool_defs, agent_defs, app_defs, inventory)
                elif isinstance(data, dict):
                    inventory["other_json"].append({"file": rel, "keys": sorted(str(k) for k in data.keys())[:20]})
            elif suffix in PROMPT_SUFFIXES:
                inventory["prompts"].append(analyze_prompt(path.read_text(encoding="utf-8", errors="replace"), rel))
        except (ValueError, OSError, UnicodeDecodeError) as error:
            inventory["unparsed"].append({"file": rel, "reason": str(error)})
    if agents_file and agents_file.exists():
        data = read_json(agents_file)
        for agent in data.get("agents", []) if isinstance(data, dict) else []:
            inventory["agents"][agent.get("name")] = dict(agent, file=str(agents_file))
    _resolve_definitions(inventory, tool_defs, agent_defs, app_defs, path_callbacks, file_index)
    bound = {t for a in inventory["agents"].values() for t in a.get("tools", [])}
    for name, tool in inventory["tools"].items():
        if name in bound:
            tool["role"] = "tool"
        elif not tool.get("role"):
            tool["role"] = "tool" if tool.get("kind") else "helper"
    inventory["unbound_tools"] = sorted(n for n, t in inventory["tools"].items() if n not in bound and t.get("role") == "tool")
    inventory["helper_functions"] = sorted(n for n, t in inventory["tools"].items() if n not in bound and t.get("role") != "tool")
    inventory["undocumented_tools"] = sorted(n for n, t in inventory["tools"].items() if t.get("role") == "tool" and not (t.get("docstring") or t.get("description")))
    return inventory


def _collect_definition(classified: Tuple[str, dict], tool_defs: List[dict], agent_defs: List[dict], app_defs: List[dict], inventory: dict) -> None:
    kind, definition = classified
    if kind == "tool":
        tool_defs.append(definition)
    elif kind == "agent":
        agent_defs.append(definition)
    elif kind == "app":
        app_defs.append(definition)
    elif kind == "guardrail":
        inventory["guardrails"].append(definition)


def _resolve_definitions(inventory: dict, tool_defs: List[dict], agent_defs: List[dict], app_defs: List[dict],
                         path_callbacks: List[dict], file_index: Dict[str, Path]) -> None:
    tool_by_id = {str(d["id"]): d["display"] for d in tool_defs if d.get("id")}
    tool_by_id.update({_last_segment(k): v for k, v in list(tool_by_id.items())})
    tool_displays = {d["display"] for d in tool_defs}
    agent_by_id = {str(d["id"]): d["display"] for d in agent_defs if d.get("id")}
    agent_by_id.update({_last_segment(k): v for k, v in list(agent_by_id.items())})
    agent_displays = {d["display"] for d in agent_defs}

    def resolve_tool(ref: Any) -> str:
        raw = _string_ref(ref)
        seg = _last_segment(raw)
        if raw in tool_by_id:
            return tool_by_id[raw]
        if seg in tool_by_id:
            return tool_by_id[seg]
        short = _short(seg)
        return short if short in tool_displays or seg in tool_displays else short

    def resolve_agent(ref: Any) -> str:
        raw = _string_ref(ref)
        seg = _last_segment(raw)
        if raw in agent_by_id:
            return agent_by_id[raw]
        if seg in agent_by_id:
            return agent_by_id[seg]
        short = _short(seg)
        return short if short in agent_displays or seg in agent_displays else short

    for definition in tool_defs:
        display = definition["display"]
        entry = inventory["tools"].setdefault(display, {"name": display, "sources": []})
        entry["sources"].append(definition["file"])
        entry["kind"] = definition["kind"]
        if definition.get("id"):
            entry["resource_id"] = definition["id"]
        if definition.get("description") and not entry.get("description"):
            entry["description"] = definition["description"]
        if definition.get("inline_code"):
            analysis = analyze_python_source(definition["inline_code"], "%s#%s" % (definition["file"], display))
            inventory["python_files"].append({"file": "%s#%s" % (definition["file"], display), "functions": [f["name"] for f in analysis["functions"]],
                                              "parse_error": analysis["parse_error"]})
            matching = [f for f in analysis["functions"] if f["name"] == display] or analysis["functions"][:1]
            for func in matching:
                _merge_function(entry, func)
            for constant in analysis["constants"]:
                inventory["constants"].append(dict(constant, file=definition["file"]))
        elif definition.get("code_ref"):
            entry["code_file"] = definition["code_ref"]

    seen_callbacks = set()
    for definition in agent_defs:
        display = definition["display"]
        folder = Path(definition["file"]).parent
        instruction = definition.get("instruction") or ""
        prompt_file = None
        chars = 0
        sibling = None
        for candidate in ("instruction.txt", "instructions.txt"):
            key = str(folder / candidate).replace("\\", "/")
            if key in file_index:
                sibling = key
                break
        if isinstance(instruction, str) and instruction and not _looks_like_code(instruction) and instruction.lower().endswith(".txt"):
            key = instruction.replace("\\", "/")
            sibling = key if key in file_index else sibling
        if sibling:
            prompt_file = sibling
            try:
                chars = len(file_index[sibling].read_text(encoding="utf-8", errors="replace"))
            except OSError:
                chars = 0
        elif isinstance(instruction, str):
            chars = len(instruction)
        inventory["agents"][display] = {
            "name": display, "resource_id": definition.get("id"), "tools": [resolve_tool(t) for t in definition["tools_raw"]],
            "sub_agents": [resolve_agent(a) for a in definition["sub_agents_raw"]], "instruction_chars": chars,
            "instruction_head": (instruction if isinstance(instruction, str) and not prompt_file else "")[:400],
            "prompt_file": prompt_file, "description": definition.get("description", ""), "model": definition.get("model"),
            "file": definition["file"],
        }
        for callback in definition.get("callbacks") or []:
            code = callback.get("code")
            if _looks_like_code(code):
                analysis = analyze_python_source(code, "%s#%s" % (definition["file"], callback["stage"]))
                functions = [f["name"] for f in analysis["functions"]]
                file_label = "%s#%s" % (definition["file"], callback["stage"])
                for func in analysis["functions"]:
                    entry = inventory["tools"].setdefault(func["name"], {"name": func["name"], "sources": []})
                    entry["sources"].append(file_label)
                    entry["role"] = "callback" if func["name"] in CALLBACK_NAMES else "helper"
                    _merge_function(entry, func)
            else:
                file_label = str(code or "").replace("\\", "/") or "%s#%s" % (definition["file"], callback["stage"])
                functions = []
            key = (display, callback["stage"], Path(file_label).name)
            if key in seen_callbacks:
                continue
            seen_callbacks.add(key)
            inventory["callbacks"].append({"file": file_label, "agent": display, "stage": callback["stage"], "functions": functions,
                                           "description": callback.get("description", ""), "disabled": callback.get("disabled", False)})

    app = app_defs[-1] if app_defs else None
    if app:
        root_display = resolve_agent(app.get("root_agent_raw")) if app.get("root_agent_raw") else None
        inventory["app"] = {"display": app.get("display"), "root_agent": root_display, "model": app.get("model"),
                            "guardrails": [_last_segment(_string_ref(g)) for g in app.get("guardrails_raw") or []], "file": app["file"]}
        if app.get("variables"):
            inventory["variables"][app["file"]] = app["variables"]
    root_alias = (inventory.get("app") or {}).get("root_agent")
    folder_to_display = {Path(d["file"]).parent.name: d["display"] for d in agent_defs}
    folder_to_display.update({_short(k): v for k, v in list(folder_to_display.items())})
    for callback in path_callbacks:
        agent = callback.get("agent")
        if agent == "root" and root_alias:
            agent = root_alias
        agent = folder_to_display.get(agent, agent)
        basename = Path(callback["file"]).name
        declared = [e for e in inventory["callbacks"] if e["stage"] == callback["stage"] and Path(e["file"]).name == basename
                    and (e["agent"] == agent or _short(e["agent"]) == _short(str(agent)))]
        if declared:
            for existing in declared:
                if not existing.get("functions"):
                    existing["functions"] = callback["functions"]
            continue
        key = (agent, callback["stage"], basename)
        if key in seen_callbacks:
            continue
        seen_callbacks.add(key)
        inventory["callbacks"].append(dict(callback, agent=agent))


def render_summary(inventory: dict) -> str:
    lines = ["# Materials inventory", "", "Generated: %s" % inventory["generated_at"], "",
             "Inputs: " + ", ".join(inventory["inputs"]), ""]
    app = inventory.get("app")
    if app:
        lines += ["## App", "", "- Display name: %s" % (app.get("display") or "?"), "- Root agent: %s" % (app.get("root_agent") or "?"),
                  "- Model: %s" % (app.get("model") or "not declared"), "- Guardrails: %s" % (", ".join(app.get("guardrails") or []) or "none"),
                  "- Source: %s" % app.get("file"), ""]
    lines += ["## Agents and their tools", ""]
    if inventory["agents"]:
        lines += ["| Agent | Tools | Sub-agents | Instruction chars | Source |", "|---|---|---|---|---|"]
        for name, agent in sorted(inventory["agents"].items()):
            lines.append("| %s | %s | %s | %s | %s |" % (name, ", ".join(agent.get("tools", [])) or "-",
                                                       ", ".join(agent.get("sub_agents", [])) or "-",
                                                       agent.get("instruction_chars", ""), agent.get("file", "")))
    else:
        lines.append("No agent tree found. Ask the user for the tree or provide agents.json.")
    if inventory.get("callbacks"):
        lines += ["", "## Callbacks", "", "| Agent | Stage | Functions | File |", "|---|---|---|---|"]
        for cb in inventory["callbacks"]:
            lines.append("| %s | %s | %s | %s |" % (cb.get("agent") or "?", cb.get("stage"), ", ".join(cb.get("functions", [])) or "-", cb.get("file")))
    lines += ["", "## Tools and other functions", "", "| Name | Role | Params | Status values | State writes | External calls | Docstring (first line) | Source |",
              "|---|---|---|---|---|---|---|---|"]
    for name, tool in sorted(inventory["tools"].items(), key=lambda kv: ({"tool": 0, "gate": 1, "callback": 2, "helper": 3}.get(kv[1].get("role"), 4), kv[0])):
        doc = (tool.get("docstring") or tool.get("description") or "").strip().splitlines()
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            name, tool.get("role") or "-", ", ".join(p["name"] for p in tool.get("params", [])) or "-", ", ".join(tool.get("status_values", [])) or "-",
            ", ".join(tool.get("state_writes", [])) or "-", ", ".join(tool.get("external_calls", [])) or "-",
            (doc[0][:90] if doc else "(none)"), ", ".join(tool.get("sources", []))[:80]))
    lines += ["", "Unbound tools (no agent lists them): %s" % (", ".join(inventory["unbound_tools"]) or "none"),
              "Callbacks, gates and helpers (not tools): %s" % (", ".join(inventory.get("helper_functions") or []) or "none"),
              "Undocumented tools: %s" % (", ".join(inventory["undocumented_tools"]) or "none"), "", "## Prompts", ""]
    for prompt in inventory["prompts"]:
        lines.append("- %s (%d lines): %s" % (prompt["file"], prompt["lines"], prompt["first_line"]))
    if inventory["variables"]:
        lines += ["", "## Variables", ""]
        for file, data in inventory["variables"].items():
            count = len(data) if isinstance(data, (list, dict)) else 0
            lines.append("- %s: %d entries" % (file, count))
    if inventory.get("guardrails"):
        lines += ["", "## Guardrails", ""] + ["- %s (%s)" % (g.get("display"), g.get("file")) for g in inventory["guardrails"]]
    if inventory["constants"]:
        lines += ["", "## Module constants", ""]
        for constant in inventory["constants"][:40]:
            lines.append("- %s = %s (%s:%s)" % (constant["name"], json.dumps(constant["value"], ensure_ascii=False)[:120], constant["file"], constant["line"]))
    if inventory.get("other_json"):
        lines += ["", "## Other JSON files (not interpreted)", ""] + ["- %s: keys %s" % (o["file"], ", ".join(o["keys"])) for o in inventory["other_json"]]
    if inventory["unparsed"]:
        lines += ["", "## Files the script could not parse (read them directly)", ""]
        for item in inventory["unparsed"]:
            lines.append("- %s: %s" % (item["file"], item["reason"]))
    if inventory["warnings"]:
        lines += ["", "## Warnings", ""] + ["- %s" % w for w in inventory["warnings"]]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="code folders, CES export folders, snapshot or prompt files")
    parser.add_argument("--out", required=True, help="materials_inventory.json")
    parser.add_argument("--summary", help="optional Markdown summary path")
    parser.add_argument("--agents-file", help="hand-written agents.json describing the agent-to-tool tree")
    args = parser.parse_args(argv)
    paths = [Path(p) for p in args.paths]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print("error: missing inputs: %s" % ", ".join(missing), file=sys.stderr)
        return 2
    inventory = build_inventory(paths, Path(args.agents_file) if args.agents_file else None)
    write_json(args.out, inventory)
    print("inventory: %d tools, %d agents, %d callbacks, %d prompts -> %s" % (len(inventory["tools"]), len(inventory["agents"]), len(inventory["callbacks"]), len(inventory["prompts"]), args.out))
    if args.summary:
        Path(args.summary).write_text(render_summary(inventory), encoding="utf-8")
        print("summary -> %s" % args.summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

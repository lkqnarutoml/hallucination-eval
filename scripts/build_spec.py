#!/usr/bin/env python3
"""Compile, validate and render the workflow pseudocode written by the architect role.

    python scripts/build_spec.py compile PSEUDOCODE_MD --out workflow_spec.json [--report spec_report.md]
                                         [--inventory materials_inventory.json] [--strict]
    python scripts/build_spec.py render  workflow_spec.json --out architecture.md [--inventory materials_inventory.json]
    python scripts/build_spec.py tree    --inventory materials_inventory.json --out materials_tree.md

compile  reads every fenced ```json block of workflow_pseudocode.md (one element per block, see
         references/pseudocode_format.md), the point-inventory table and the open-questions section, checks
         that every cross-reference resolves (steps -> tools, tools -> agents, rules, templates, variables,
         points -> elements), that every element carries author and provenance tags, and writes the machine
         contract the evaluator, checker compiler and reporter read. Errors -> exit 1; --strict also fails on
         warnings.
render   turns the compiled spec into the human views: the agent-to-tool tree, one Mermaid state machine per
         flow, the "who decides what" table, the state-variable bus and the point inventory.
tree     renders the agent-to-tool tree straight from materials_inventory.json, before any pseudocode exists,
         so the architect starts from a picture of the system.

Standard library only; ASCII output so it renders the same on Windows consoles.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, sha256_of_text, write_json  # noqa: E402

KINDS = ("routing", "turn_skeleton", "flows", "step", "tool", "callback_rule", "rule", "end_reasons", "variables", "templates")
PROVENANCE = ("seen_in_code", "inferred", "unknown")
AUTHORS = ("model", "code", "both")
GROUND_PREFIXES = ("customer_utterance.current", "customer_utterance.any", "agent_utterance.previous", "state.",
                   "tool_result.", "enum", "external.", "none")
INPUT_CLASSES = {"digits5", "digits_other", "no_digits", "affirmative", "negative", "repeat_request", "agent_request",
                 "cancel_request", "out_of_scope", "no_input", "other", "any"}
CHECK_KINDS = {"deterministic", "pattern", "grounding", "judgment"}
POINT_HEADER = "point id"
_GATE_WORDS = {"not", "and", "or", "true", "false", "none", "in", "is", "null", "if", "else", "len", "s"}
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


# ----------------------------------------------------------------------------------------------------------
# parsing the literate file
# ----------------------------------------------------------------------------------------------------------
def fenced_json_blocks(text: str) -> List[Tuple[int, str]]:
    """Return (start_line, body) for every ```json fenced block."""
    blocks: List[Tuple[int, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("```") and stripped[3:].strip().lower().startswith("json"):
            start = index + 1
            body: List[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != "```":
                body.append(lines[index])
                index += 1
            blocks.append((start, "\n".join(body)))
        index += 1
    return blocks


def header_fields(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in text.splitlines()[:60]:
        for key, label in (("build", "Build or version:"), ("materials", "Materials read:"), ("reconciled", "Reconciled with:")):
            if line.strip().startswith(label):
                fields[key] = line.split(":", 1)[1].strip()
    return fields


def markdown_tables(text: str) -> List[Tuple[int, List[List[str]]]]:
    """Return (start_line, rows) for every pipe table; rows exclude the separator line."""
    tables: List[Tuple[int, List[List[str]]]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip().startswith("|"):
            start = index
            rows: List[List[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [c.strip() for c in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in cells):
                    rows.append(cells)
                index += 1
            tables.append((start + 1, rows))
        else:
            index += 1
    return tables


def point_inventory(text: str) -> Tuple[List[dict], List[str]]:
    points: List[dict] = []
    warnings: List[str] = []
    for start, rows in markdown_tables(text):
        if not rows or rows[0][0].strip().lower() != POINT_HEADER:
            continue
        header = [h.strip().lower() for h in rows[0]]
        for offset, row in enumerate(rows[1:], start=1):
            if len(row) < 3:
                continue
            record = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
            point = record.get("point id", "")
            if "<" in point or point.startswith("..."):
                warnings.append("line %d: template row left in the point inventory (%s)" % (start + offset, point))
                continue
            points.append({
                "id": point, "step": record.get("step", ""), "artifact": record.get("artifact", ""),
                "author": record.get("author", ""), "check_kind": record.get("check kind", ""),
                "allowed_sources": record.get("allowed sources", ""), "element": record.get("pseudocode element", ""),
                "line": start + offset,
            })
    return points, warnings


def open_questions(text: str) -> List[str]:
    lines = text.splitlines()
    collected: List[str] = []
    active = False
    for line in lines:
        if line.startswith("#"):
            active = "open question" in line.lower()
            continue
        if active and line.strip().startswith(("-", "*", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
            collected.append(line.strip().lstrip("-*0123456789. ").strip())
    return collected


# ----------------------------------------------------------------------------------------------------------
# compile
# ----------------------------------------------------------------------------------------------------------
class Diagnostics:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, where: Any, message: str) -> None:
        self.errors.append("%s: %s" % (where, message))

    def warn(self, where: Any, message: str) -> None:
        self.warnings.append("%s: %s" % (where, message))


def _line(block: dict) -> str:
    return "line %s" % block.get("_line", "?")


def _gate_identifiers(gate: Any) -> List[str]:
    """Variable names a gate predicate reads. Prose gates (no S. prefix, many words) are not parsed."""
    if not isinstance(gate, str):
        return []
    names: List[str] = []
    if "S." in gate:
        for match in re.finditer(r"S\.([A-Za-z_][A-Za-z0-9_]*)", gate):
            if match.group(1) not in names:
                names.append(match.group(1))
        return names
    tokens = _IDENT_RE.findall(gate)
    if len(tokens) > 6:
        return []
    for token in tokens:
        if token.lower() in _GATE_WORDS or token in names:
            continue
        names.append(token)
    return names


def _ground_ok(value: Any) -> bool:
    return isinstance(value, str) and any(value == p or (p.endswith(".") and value.startswith(p)) for p in GROUND_PREFIXES)


def compile_spec(text: str, source: str, inventory: Optional[dict] = None) -> Tuple[dict, Diagnostics]:
    diag = Diagnostics()
    elements: List[dict] = []
    for start, body in fenced_json_blocks(text):
        try:
            data = json.loads(body)
        except ValueError as error:
            diag.error("line %d" % start, "invalid JSON in fenced block (%s)" % error)
            continue
        if not isinstance(data, dict):
            diag.error("line %d" % start, "fenced json block must hold one object")
            continue
        data["_line"] = start
        if data.get("kind") not in KINDS:
            diag.error("line %d" % start, "unknown or missing kind %r (expected one of %s)" % (data.get("kind"), ", ".join(KINDS)))
            continue
        if data.get("provenance") not in PROVENANCE:
            diag.error("line %d" % start, "%s element needs provenance in %s" % (data["kind"], "/".join(PROVENANCE)))
        elements.append(data)

    spec: Dict[str, Any] = {
        "routing": None, "turn_skeletons": [], "flows": None, "steps": OrderedDict(), "tools": OrderedDict(),
        "callback_rules": [], "rules": OrderedDict(), "end_reasons": None, "variables": OrderedDict(), "templates": OrderedDict(),
    }
    for element in elements:
        kind = element["kind"]
        if kind == "routing":
            if spec["routing"] is not None:
                diag.warn(_line(element), "more than one routing element; the last one wins")
            spec["routing"] = element
        elif kind == "turn_skeleton":
            spec["turn_skeletons"].append(element)
        elif kind == "flows":
            if spec["flows"] is not None:
                diag.warn(_line(element), "more than one flows element; the last one wins")
            spec["flows"] = element
        elif kind in ("step", "tool"):
            name = element.get("name")
            if not name:
                diag.error(_line(element), "%s element without a name" % kind)
                continue
            target = spec["steps"] if kind == "step" else spec["tools"]
            if name in target:
                diag.error(_line(element), "duplicate %s name %r" % (kind, name))
            target[name] = element
        elif kind == "callback_rule":
            if not element.get("id"):
                diag.error(_line(element), "callback_rule without an id")
            spec["callback_rules"].append(element)
        elif kind == "rule":
            rule_id = element.get("id")
            if not rule_id:
                diag.error(_line(element), "rule without an id")
                continue
            if rule_id in spec["rules"]:
                diag.error(_line(element), "duplicate rule id %r" % rule_id)
            spec["rules"][rule_id] = element
        elif kind == "end_reasons":
            spec["end_reasons"] = element
        elif kind == "variables":
            for name, meta in (element.get("variables") or {}).items():
                spec["variables"][name] = meta if isinstance(meta, dict) else {"default": meta}
        elif kind == "templates":
            for name, meta in (element.get("templates") or {}).items():
                spec["templates"][name] = meta

    routing = spec["routing"] or {}
    agents = (routing.get("agents") or {}) if isinstance(routing.get("agents"), dict) else {}
    agent_tools = {agent: set((meta or {}).get("tools") or []) for agent, meta in agents.items()}
    all_agent_tools = set().union(*agent_tools.values()) if agent_tools else set()
    known_tools = set(spec["tools"]) | all_agent_tools
    if inventory:
        known_tools |= set((inventory.get("tools") or {}).keys())
    variables = set(spec["variables"])

    if spec["routing"] is None:
        diag.error("file", "no routing element (kind: routing)")
    elif routing.get("root_agent") and routing["root_agent"] not in agents:
        diag.error(_line(routing), "root_agent %r is not in routing.agents" % routing["root_agent"])
    for rule in (routing.get("rules") or []):
        if isinstance(rule, dict) and rule.get("to") and rule["to"] not in agents:
            diag.error(_line(routing), "routing rule targets unknown agent %r" % rule["to"])
    for skeleton in spec["turn_skeletons"]:
        if skeleton.get("agent") and agents and skeleton["agent"] not in agents:
            diag.error(_line(skeleton), "turn_skeleton for unknown agent %r" % skeleton["agent"])

    flows = spec["flows"] or {}
    flow_steps = flows.get("flows") or {}
    if spec["flows"] is None:
        diag.error("file", "no flows element (kind: flows)")
    for flow, steps in flow_steps.items():
        for step in steps or []:
            if step not in spec["steps"]:
                diag.error(_line(flows), "flow %r lists step %r which has no step element" % (flow, step))
    for step, gate in (flows.get("gates") or {}).items():
        if step not in spec["steps"]:
            diag.warn(_line(flows), "gate for unknown step %r" % step)
        for name in _gate_identifiers(gate):
            if variables and name not in variables:
                diag.warn(_line(flows), "gate of %r references undeclared variable %r" % (step, name))

    for name, step in spec["steps"].items():
        if step.get("author") not in AUTHORS:
            diag.error(_line(step), "step %r needs author in %s" % (name, "/".join(AUTHORS)))
        listed = any(name in (steps or []) for steps in flow_steps.values())
        if flow_steps and not listed and not step.get("global"):
            diag.warn(_line(step), "step %r is not listed in any flow (set \"global\": true for interrupt handlers)" % name)
        for name_var in _gate_identifiers(step.get("gate")):
            if variables and name_var not in variables:
                diag.warn(_line(step), "step %r gate references undeclared variable %r" % (name, name_var))
        decide = step.get("decide") or {}
        if not isinstance(decide, dict) or not decide:
            diag.error(_line(step), "step %r has no decide table" % name)
        for input_class, action in decide.items() if isinstance(decide, dict) else []:
            if input_class not in INPUT_CLASSES:
                diag.warn(_line(step), "step %r uses input class %r not in the standard list (define it in section 0)" % (name, input_class))
            if not isinstance(action, dict):
                diag.error(_line(step), "step %r decide[%r] must be an object" % (name, input_class))
                continue
            call = action.get("call")
            if call and call not in known_tools:
                diag.error(_line(step), "step %r decide[%r] calls unknown tool %r" % (name, input_class, call))
            if call and call in spec["tools"]:
                flows_of_tool = spec["tools"][call].get("flows") or []
                step_flows = step.get("flows") or []
                if flows_of_tool and step_flows and not set(flows_of_tool) & set(step_flows):
                    diag.warn(_line(step), "step %r (flows %s) calls %r which lists flows %s" % (name, step_flows, call, flows_of_tool))
            if action.get("check") and action["check"] not in CHECK_KINDS:
                diag.error(_line(step), "step %r decide[%r] check %r is not a check kind" % (name, input_class, action["check"]))
        must_not = step.get("must_not") or {}
        for call in (must_not.get("call") or []):
            if call not in known_tools:
                diag.warn(_line(step), "step %r must_not names unknown tool %r" % (name, call))
        for tool, then in (step.get("then") or {}).items():
            if tool not in known_tools:
                diag.warn(_line(step), "step %r then[] names unknown tool %r" % (name, tool))
            if isinstance(then, dict) and then.get("next_call") and then["next_call"] not in known_tools:
                diag.error(_line(step), "step %r then[%r].next_call names unknown tool %r" % (name, tool, then["next_call"]))
            for var in ((then or {}).get("effects") or {}) if isinstance(then, dict) else {}:
                if variables and var not in variables:
                    diag.warn(_line(step), "step %r then[%r] writes undeclared variable %r" % (name, tool, var))

    for name, tool in spec["tools"].items():
        if tool.get("author") not in AUTHORS:
            diag.error(_line(tool), "tool %r needs author in %s" % (name, "/".join(AUTHORS)))
        for agent in tool.get("agents") or []:
            if agents and agent not in agents:
                diag.error(_line(tool), "tool %r names unknown agent %r" % (name, agent))
            elif agent in agent_tools and agent_tools[agent] and name not in agent_tools[agent]:
                diag.warn(_line(tool), "tool %r is not in routing.agents[%r].tools" % (name, agent))
        for param, meta in (tool.get("inputs") or {}).items():
            if not isinstance(meta, dict):
                diag.error(_line(tool), "tool %r input %r must be an object" % (name, param))
                continue
            if tool.get("author") in ("model", "both") and not _ground_ok(meta.get("ground_in")):
                diag.error(_line(tool), "tool %r input %r needs a valid ground_in (got %r)" % (name, param, meta.get("ground_in")))
            if isinstance(meta.get("ground_in"), str) and meta["ground_in"].startswith("state."):
                var = meta["ground_in"].split(".", 1)[1]
                if variables and var not in variables:
                    diag.warn(_line(tool), "tool %r input %r grounds in undeclared variable %r" % (name, param, var))
        rule = tool.get("deterministic_rule") or {}
        if isinstance(rule, dict) and rule.get("id") and rule["id"] not in spec["rules"]:
            diag.error(_line(tool), "tool %r references unknown rule %r" % (name, rule["id"]))
        for var in (tool.get("effects") or {}):
            if variables and var not in variables:
                diag.warn(_line(tool), "tool %r writes undeclared variable %r" % (name, var))
        if not tool.get("outputs"):
            diag.warn(_line(tool), "tool %r declares no outputs" % name)

    seen_rule_ids = set()
    for rule in spec["callback_rules"]:
        rule_id = rule.get("id")
        if rule_id in seen_rule_ids:
            diag.error(_line(rule), "duplicate callback_rule id %r" % rule_id)
        seen_rule_ids.add(rule_id)
        if rule.get("author") != "code":
            diag.error(_line(rule), "callback_rule %r must have author \"code\"" % rule_id)
        if rule.get("agent") and agents and rule["agent"] not in agents:
            diag.error(_line(rule), "callback_rule %r names unknown agent %r" % (rule_id, rule["agent"]))
        if rule.get("next_call") and rule["next_call"] not in known_tools:
            diag.error(_line(rule), "callback_rule %r next_call names unknown tool %r" % (rule_id, rule["next_call"]))
        for var in (rule.get("effects") or {}):
            if variables and var not in variables:
                diag.warn(_line(rule), "callback_rule %r writes undeclared variable %r" % (rule_id, var))

    if spec["end_reasons"] is None:
        diag.warn("file", "no end_reasons element; end-reason points will be unverifiable")
    else:
        reasons = Counter()
        for group in ("model_issued", "code_issued"):
            for item in spec["end_reasons"].get(group) or []:
                if isinstance(item, dict):
                    reasons[item.get("reason")] += 1
        for reason, count in reasons.items():
            if count > 1:
                diag.warn(_line(spec["end_reasons"]), "end reason %r listed %d times" % (reason, count))

    points, point_warnings = point_inventory(text)
    for message in point_warnings:
        diag.warn("inventory", message)
    if not points:
        diag.error("file", "no point inventory table (header must start with '| Point id |')")
    point_ids = Counter(p["id"] for p in points)
    for point in points:
        where = "line %d" % point["line"]
        if point_ids[point["id"]] > 1:
            diag.error(where, "duplicate point id %r" % point["id"])
        if point["author"] and point["author"] not in AUTHORS:
            diag.error(where, "point %r author %r not in %s" % (point["id"], point["author"], "/".join(AUTHORS)))
        kinds = {k.strip() for k in re.split(r"[/,]", point["check_kind"]) if k.strip()}
        if not kinds or not kinds <= CHECK_KINDS:
            diag.error(where, "point %r check kind %r must be one or more of %s" % (point["id"], point["check_kind"], "/".join(sorted(CHECK_KINDS))))
        if point["step"] not in ("", "-") and point["step"] not in spec["steps"]:
            diag.error(where, "point %r names unknown step %r" % (point["id"], point["step"]))
        element = point["element"].strip()
        if not _element_resolves(element, spec, known_tools):
            diag.error(where, "point %r references %r which does not resolve to a pseudocode element" % (point["id"], element))
    for name in spec["steps"]:
        if not any(p["id"] == "%s.selection" % name for p in points):
            diag.warn("inventory", "step %r has no <step>.selection point" % name)
    for name, tool in spec["tools"].items():
        if tool.get("author") in ("model", "both"):
            for param in (tool.get("inputs") or {}):
                covered = any(p["id"].endswith("%s.args.%s" % (name, param)) or ("tool %s inputs.%s" % (name, param)) in p["element"] for p in points)
                if not covered and param == "session_escalated" and any(p["id"].endswith(".end_reason") for p in points):
                    covered = True
                if not covered:
                    diag.warn("inventory", "no args point for model-authored input %s.%s" % (name, param))

    questions = open_questions(text)
    inferred = [e for e in elements if e.get("provenance") in ("inferred", "unknown")]
    if inferred and not questions:
        diag.error("file", "%d elements are inferred/unknown but the open-questions section is empty" % len(inferred))

    for element in elements:
        element.pop("_line", None)
    fields = header_fields(text)
    compiled = {
        "meta": {"source": source, "sha256": sha256_of_text(text), "generated_at": now_iso(), "build": fields.get("build", ""),
                 "materials": fields.get("materials", ""), "reconciled_with": fields.get("reconciled", ""),
                 "counts": {"agents": len(agents), "steps": len(spec["steps"]), "tools": len(spec["tools"]),
                            "callback_rules": len(spec["callback_rules"]), "rules": len(spec["rules"]),
                            "variables": len(spec["variables"]), "templates": len(spec["templates"]), "points": len(points),
                            "inferred_or_unknown": len(inferred), "open_questions": len(questions)},
                 "provenance": dict(Counter(e.get("provenance") for e in elements))},
        "routing": spec["routing"], "turn_skeletons": spec["turn_skeletons"], "flows": spec["flows"],
        "steps": spec["steps"], "tools": spec["tools"], "callback_rules": spec["callback_rules"], "rules": spec["rules"],
        "end_reasons": spec["end_reasons"], "variables": spec["variables"], "templates": spec["templates"],
        "points": points, "open_questions": questions,
        "diagnostics": {"errors": diag.errors, "warnings": diag.warnings},
    }
    return compiled, diag


def _element_resolves(element: str, spec: dict, known_tools: set) -> bool:
    if not element:
        return False
    tokens = element.replace(",", " ").split()
    head = tokens[0].lower().rstrip(":")
    name = tokens[1] if len(tokens) > 1 else ""
    name = name.strip("`'\"")
    if head in ("step",):
        return name in spec["steps"]
    if head in ("tool",):
        return name.split(".")[0] in known_tools
    if head in ("rule",):
        return name in spec["rules"]
    if head in ("template", "templates"):
        return name in spec["templates"] or name == ""
    if head in ("callback", "callback_rule"):
        return any(r.get("id") == name for r in spec["callback_rules"])
    if head in ("routing", "end_reasons", "variables", "flows", "turn_skeleton"):
        return True
    return False


def render_report(compiled: dict, diag: Diagnostics) -> str:
    meta = compiled["meta"]
    lines = ["# Spec compile report", "", "Source: %s" % meta["source"], "SHA-256: %s" % meta["sha256"],
             "Generated: %s" % meta["generated_at"], "", "## Counts", ""]
    for key, value in meta["counts"].items():
        lines.append("- %s: %s" % (key, value))
    lines += ["", "## Provenance of elements", ""] + ["- %s: %d" % kv for kv in sorted(meta["provenance"].items(), key=lambda kv: str(kv[0]))]
    by_kind = Counter()
    by_author = Counter()
    for point in compiled["points"]:
        by_kind[point["check_kind"]] += 1
        by_author[point["author"]] += 1
    lines += ["", "## Points", "", "- by check kind: %s" % (", ".join("%s=%d" % kv for kv in sorted(by_kind.items())) or "none"),
              "- by author: %s" % (", ".join("%s=%d" % kv for kv in sorted(by_author.items())) or "none")]
    lines += ["", "## Errors (%d)" % len(diag.errors), ""] + (["- " + e for e in diag.errors] or ["- none"])
    lines += ["", "## Warnings (%d)" % len(diag.warnings), ""] + (["- " + w for w in diag.warnings] or ["- none"])
    lines += ["", "## Open questions (%d)" % len(compiled["open_questions"]), ""] + (["- " + q for q in compiled["open_questions"]] or ["- none"])
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------------------
# render: human views of the compiled spec
# ----------------------------------------------------------------------------------------------------------
def _node_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def _label(text: str) -> str:
    return text.replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")


def tool_kind(name: str, spec: dict, inventory: Optional[dict]) -> str:
    tool = spec.get("tools", {}).get(name) if spec else None
    if tool and tool.get("author"):
        return {"model": "model-called", "code": "code-called", "both": "model+code"}.get(tool["author"], tool["author"])
    if inventory and name in (inventory.get("tools") or {}):
        return (inventory["tools"][name].get("kind") or "python") + " tool"
    if name in ("end_session",):
        return "system"
    return "tool"


def agent_tree_lines(agents: Dict[str, dict], root: Optional[str], routing_rules: List[dict], spec: Optional[dict],
                     inventory: Optional[dict], callbacks: Dict[str, List[dict]]) -> List[str]:
    lines: List[str] = []
    children_of: Dict[str, List[str]] = {name: list((meta or {}).get("sub_agents") or []) for name, meta in agents.items()}
    if root is None:
        referenced = {c for subs in children_of.values() for c in subs}
        roots = [a for a in agents if a not in referenced]
        root = roots[0] if roots else (next(iter(agents)) if agents else None)

    def walk(name: str, prefix: str, is_last: bool, depth: int) -> None:
        meta = agents.get(name) or {}
        branch = "" if depth == 0 else ("`-- " if is_last else "|-- ")
        lines.append("%s%s%s%s" % (prefix, branch, name, "  [root]" if depth == 0 else ""))
        child_prefix = prefix + ("" if depth == 0 else ("    " if is_last else "|   "))
        items: List[str] = []
        instruction = meta.get("prompt_file") or meta.get("instruction_head")
        if meta.get("instruction_chars") or instruction:
            items.append("instructions: %s" % (meta.get("prompt_file") or "%s chars" % meta.get("instruction_chars", "?")))
        else:
            items.append("instructions: none (code only)")
        for cb in callbacks.get(name, []):
            copies = " (+%d more copy)" % (cb["copies"] - 1) if cb.get("copies", 1) > 1 else ""
            items.append("callback %s: %s%s" % (cb.get("stage", "?"), cb.get("file", ""), copies))
        for tool in meta.get("tools") or []:
            items.append("tool %s (%s)" % (tool, tool_kind(tool, spec or {}, inventory)))
        for rule in routing_rules:
            if isinstance(rule, dict) and rule.get("to") and (rule.get("from", root) == name or depth == 0 and rule.get("to") in children_of.get(name, [])):
                items.append("handoff: when %s -> %s" % (rule.get("when", "?"), rule["to"]))
        subs = children_of.get(name, [])
        for index, item in enumerate(items):
            last_item = index == len(items) - 1 and not subs
            lines.append("%s%s%s" % (child_prefix, "`-- " if last_item else "|-- ", item))
        for index, sub in enumerate(subs):
            walk(sub, child_prefix, index == len(subs) - 1, depth + 1)

    if root:
        walk(root, "", True, 0)
    orphans = [a for a in agents if a != root and not any(a in subs for subs in children_of.values())]
    for orphan in orphans:
        lines.append("")
        lines.append("(not reachable from the root by sub_agents: %s)" % orphan)
        walk(orphan, "", True, 0)
    return lines


def callbacks_from_inventory(inventory: Optional[dict], root: Optional[str] = None) -> Dict[str, List[dict]]:
    """Callbacks per agent, one entry per stage (extra copies of the same stage are counted, not listed)."""
    result: Dict[str, List[dict]] = {}
    seen: Dict[Tuple[str, str], dict] = {}
    for entry in (inventory or {}).get("callbacks", []) or []:
        agent = entry.get("agent") or "?"
        if agent == "root" and root:
            agent = root
        key = (agent, entry.get("stage") or "?")
        if key in seen:
            seen[key]["copies"] = seen[key].get("copies", 1) + 1
            continue
        copy_entry = dict(entry, agent=agent)
        seen[key] = copy_entry
        result.setdefault(agent, []).append(copy_entry)
    return result


def mermaid_flow(flow: str, steps: List[str], spec: dict) -> List[str]:
    gates = (spec.get("flows") or {}).get("gates") or {}
    lines = ["```mermaid", "flowchart TD",
             "  classDef model fill:#FBE9CC,stroke:#C77D0A,color:#3F2A05",
             "  classDef code fill:#D6EEF0,stroke:#0E7C86,color:#0B3A3F",
             "  classDef tool fill:#E4E1FA,stroke:#5B4FCF,color:#241E5C",
             "  classDef end fill:#F6DAD7,stroke:#B4423A,color:#4A1612"]
    previous = None
    defined: set = set()
    for step_name in steps:
        step = spec["steps"].get(step_name, {})
        gate = step.get("gate") or gates.get(step_name) or "?"
        node = _node_id("s_" + step_name)
        lines.append('  %s["%s<br/>gate: %s<br/>decides: %s"]:::model' % (node, _label(step_name), _label(str(gate)), step.get("author", "?")))
        if previous:
            lines.append("  %s --> %s" % (previous, node))
        previous = node
        edges: Dict[str, List[str]] = OrderedDict()
        for input_class, action in (step.get("decide") or {}).items():
            if not isinstance(action, dict) or not action.get("call"):
                continue
            edges.setdefault(action["call"], []).append(input_class)
        for tool, classes in edges.items():
            tnode = _node_id("t_%s_%s" % (step_name, tool))
            style = "end" if "end" in tool or "transfer" in tool else "tool"
            if tnode not in defined:
                lines.append('  %s["%s()"]:::%s' % (tnode, _label(tool), style))
                defined.add(tnode)
            lines.append('  %s -. "%s" .-> %s' % (node, _label(" / ".join(classes)), tnode))
            then = (step.get("then") or {}).get(tool) or {}
            if isinstance(then, dict) and then.get("say"):
                snode = _node_id("say_%s_%s" % (step_name, tool))
                lines.append('  %s["CODE says: %s"]:::code' % (snode, _label(str(then["say"])[:70])))
                lines.append("  %s --> %s" % (tnode, snode))
            if isinstance(then, dict) and then.get("next_call"):
                nnode = _node_id("n_%s_%s" % (step_name, then["next_call"]))
                lines.append('  %s["CODE calls %s()"]:::code' % (nnode, _label(then["next_call"])))
                lines.append("  %s --> %s" % (tnode, nnode))
    lines.append("```")
    return lines


def render_architecture(spec: dict, inventory: Optional[dict]) -> str:
    routing = spec.get("routing") or {}
    agents = routing.get("agents") or {}
    meta = spec.get("meta", {})
    lines = ["# Architecture views", "", "Derived from `%s` (sha256 %s), build: %s" % (meta.get("source", "?"), (meta.get("sha256") or "")[:12], meta.get("build") or "?"),
             "", "Legend: MODEL = the language model decides; CODE = a callback or tool decides deterministically.", "",
             "## 1. Agent-to-tool tree", "", "```text"]
    lines += agent_tree_lines(agents, routing.get("root_agent"), routing.get("rules") or [], spec, inventory, callbacks_from_inventory(inventory, routing.get("root_agent")))
    lines += ["```", "", "## 2. Turn skeleton (what runs before and after the single model call)", ""]
    for skeleton in spec.get("turn_skeletons") or []:
        lines.append("- **%s**: before model: %s; after model: %s; the model decides only when: %s" % (
            skeleton.get("agent", "?"), ", ".join(skeleton.get("before_model") or []) or "nothing",
            ", ".join(skeleton.get("after_model") or []) or "nothing", skeleton.get("model_decides_only_when") or "?"))
    if not spec.get("turn_skeletons"):
        lines.append("- (no turn_skeleton elements)")
    lines += ["", "## 3. Flows as state machines", ""]
    flows = (spec.get("flows") or {}).get("flows") or {}
    for flow, steps in flows.items():
        lines += ["### Flow `%s`" % flow, "", "Steps in gate order: %s" % " -> ".join(steps or []), ""]
        lines += mermaid_flow(flow, steps or [], spec)
        lines.append("")
    lines += ["## 4. Who decides what", "", "| Decision | Made by | Element |", "|---|---|---|"]
    for name, step in (spec.get("steps") or {}).items():
        lines.append("| which tool to call at step %s given the customer's reply | %s | step %s |" % (name, (step.get("author") or "?").upper(), name))
    for rule in spec.get("callback_rules") or []:
        lines.append("| %s | CODE | callback %s |" % (_label(str(rule.get("when") or "?"))[:90], rule.get("id")))
    for name, tool in (spec.get("tools") or {}).items():
        det = tool.get("deterministic_rule") or {}
        if isinstance(det, dict) and det.get("id"):
            lines.append("| result of %s | CODE (rule %s) | tool %s |" % (name, det["id"], name))
    lines += ["", "## 5. State variable bus", "", "| Variable | Default | Set by | Consumed by |", "|---|---|---|---|"]
    for name, meta_var in (spec.get("variables") or {}).items():
        lines.append("| %s | %s | %s | %s |" % (name, json.dumps(meta_var.get("default"), ensure_ascii=False) if isinstance(meta_var, dict) else meta_var,
                                                 ", ".join((meta_var or {}).get("set_by") or []) if isinstance(meta_var, dict) else "",
                                                 ", ".join((meta_var or {}).get("consumed_by") or []) if isinstance(meta_var, dict) else ""))
    lines += ["", "## 6. Point inventory", "", "| Point id | Step | Artifact | Author | Check kind | Allowed sources | Element |", "|---|---|---|---|---|---|---|"]
    for point in spec.get("points") or []:
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (point["id"], point["step"], point["artifact"], point["author"], point["check_kind"], point["allowed_sources"], point["element"]))
    if spec.get("open_questions"):
        lines += ["", "## 7. Open questions", ""] + ["- " + q for q in spec["open_questions"]]
    return "\n".join(lines) + "\n"


def render_materials_tree(inventory: dict) -> str:
    agents = inventory.get("agents") or {}
    lines = ["# Materials tree", "", "Generated: %s from %s" % (now_iso(), ", ".join(inventory.get("inputs") or [])), "",
             "What the materials say about who owns which tool and callback. Written before the pseudocode; the architect",
             "confirms or corrects it in workflow_pseudocode.md.", "", "```text"]
    referenced = {c for meta in agents.values() for c in ((meta or {}).get("sub_agents") or [])}
    roots = [a for a in agents if a not in referenced]
    lines += agent_tree_lines(agents, None, [], None, inventory, callbacks_from_inventory(inventory, roots[0] if roots else None))
    lines += ["```", ""]
    def describe(name: str) -> str:
        tool = inventory["tools"].get(name, {})
        doc = (tool.get("docstring") or tool.get("description") or "").strip().splitlines()
        return "- %s (%s): %s" % (name, tool.get("role") or "unbound", doc[0][:100] if doc else "no docstring")

    unbound = inventory.get("unbound_tools") or []
    lines += ["Tools defined in the materials that no agent binds (check whether the tree is incomplete):", ""]
    lines += [describe(name) for name in unbound] or ["- none"]
    helpers = inventory.get("helper_functions") or []
    lines += ["", "Callbacks, gates and helper functions (code, never called by the model):", ""]
    lines += [describe(name) for name in helpers] or ["- none"]
    lines += ["", "Prompts / instruction files:", ""] + ["- %s (%d lines)" % (p["file"], p["lines"]) for p in inventory.get("prompts") or []] or []
    if inventory.get("variables"):
        lines += ["", "Declared variables:", ""] + ["- %s: %d entries" % (f, len(d) if isinstance(d, (list, dict)) else 0) for f, d in inventory["variables"].items()]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------------------------------------------
def cmd_compile(args: argparse.Namespace) -> int:
    path = Path(args.pseudocode)
    if not path.exists():
        print("error: %s does not exist" % path, file=sys.stderr)
        return 2
    inventory = read_json(args.inventory) if args.inventory else None
    text = path.read_text(encoding="utf-8")
    compiled, diag = compile_spec(text, str(path), inventory)
    write_json(args.out, compiled)
    if args.report:
        Path(args.report).write_text(render_report(compiled, diag), encoding="utf-8")
    counts = compiled["meta"]["counts"]
    print("compiled %d steps, %d tools, %d callback rules, %d points -> %s" % (counts["steps"], counts["tools"], counts["callback_rules"], counts["points"], args.out))
    for error in diag.errors:
        print("ERROR " + error)
    for warning in diag.warnings:
        print("WARN  " + warning)
    if diag.errors:
        print("INVALID: %d error(s), %d warning(s)" % (len(diag.errors), len(diag.warnings)))
        return 1
    if args.strict and diag.warnings:
        print("INVALID (strict): %d warning(s)" % len(diag.warnings))
        return 1
    print("VALID: 0 errors, %d warning(s), %d open question(s)" % (len(diag.warnings), counts["open_questions"]))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    spec = read_json(args.spec)
    inventory = read_json(args.inventory) if args.inventory else None
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_architecture(spec, inventory), encoding="utf-8")
    print("architecture views written to %s" % out)
    return 0


def cmd_tree(args: argparse.Namespace) -> int:
    inventory = read_json(args.inventory)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_materials_tree(inventory), encoding="utf-8")
    print("materials tree written to %s (%d agents)" % (out, len(inventory.get("agents") or {})))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_compile = sub.add_parser("compile")
    p_compile.add_argument("pseudocode")
    p_compile.add_argument("--out", required=True)
    p_compile.add_argument("--report")
    p_compile.add_argument("--inventory")
    p_compile.add_argument("--strict", action="store_true")
    p_compile.set_defaults(func=cmd_compile)
    p_render = sub.add_parser("render")
    p_render.add_argument("spec")
    p_render.add_argument("--out", required=True)
    p_render.add_argument("--inventory")
    p_render.set_defaults(func=cmd_render)
    p_tree = sub.add_parser("tree")
    p_tree.add_argument("--inventory", required=True)
    p_tree.add_argument("--out", required=True)
    p_tree.set_defaults(func=cmd_tree)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

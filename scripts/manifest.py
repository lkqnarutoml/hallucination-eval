#!/usr/bin/env python3
"""Folder conventions, input scan and run_manifest.json (the shared state of one evaluation run).

    python scripts/manifest.py scan  INPUT_DIR [--json]
    python scripts/manifest.py init  --target NAME --input INPUT_DIR --output OUTPUT_DIR [--run-id ID]
                                     [--materials P ...] [--trajectories P ...] [--ground-truth P ...] [--intro-docs P ...]
                                     [--existing-pseudocode P] [--batch-conversations 12] [--batch-chars 40000]
                                     [--checker-threshold 20] [--model NAME] [--mode multi-agent|single-agent] [--force]
    python scripts/manifest.py init  RUN_DIR --target NAME [same flags]        # explicit run folder, no convention
    python scripts/manifest.py paths RUN_DIR                                   # KEY=absolute path, one per line
    python scripts/manifest.py show  RUN_DIR
    python scripts/manifest.py next  RUN_DIR                                   # first phase that is not done
    python scripts/manifest.py gate  RUN_DIR PHASE                             # check prerequisites + artifacts, change nothing
    python scripts/manifest.py set-phase RUN_DIR PHASE STATUS [--note TEXT] [--force]   # `done` is refused when the gate fails
    python scripts/manifest.py register-batches RUN_DIR                        # batches/index.json -> pending evaluate/audit batches
    python scripts/manifest.py set-batch RUN_DIR PHASE BATCH STATUS
    python scripts/manifest.py dispatch RUN_DIR ROLE --prompt PATH [--batch ID] [--force]   # prints the dispatch id
    python scripts/manifest.py finalize RUN_DIR DISPATCH_ID --status done|failed|blocked [--outputs P ...] [--note TEXT]
    python scripts/manifest.py set-setting RUN_DIR KEY VALUE      # batch_conversations, batch_chars, checker_threshold, sampling,
                                                                  # model (P6 evaluators), audit_model (P7 auditors), audit (true|false: P7 included)
    python scripts/manifest.py set-file  RUN_DIR KEY PATH
    python scripts/manifest.py log RUN_DIR MESSAGE

The run is a state machine: PREREQS says which phases must be done (or skipped) before a phase may complete, and
GATES says which artifacts must exist and validate before `set-phase PHASE done` is accepted. `--force` overrides
a failed gate but requires --note and is logged. Every subagent instance is a dispatch record with an attempt
number; a third attempt for the same role and batch is refused without --force.

Input convention (one folder, one subfolder per kind of material):
    input/materials/      the CX Agent Studio export folder(s), or loose code, callbacks, prompts, variables
    input/trajectories/   events.jsonl run folders, CES JSON folders, xlsx or csv exports
    input/ground_truth/   csv, xlsx or json keyed by session id (for DemoCard: zip_on_file)
    input/docs/           workflow introduction, MDD sections, an existing pseudocode to reconcile (name contains "pseudocode")
    input/config/         column_map.json, agents.json (hand-written tree), settings.json (batch sizes, threshold, model, mode)

Output convention: one run lives in OUTPUT_DIR/<RUN_ID>/. The final deliverables sit at the top of the run folder
(hallucination_findings.json, summary.md, workflow_pseudocode.md, architecture.md, aggregate.json,
summary_tables.md, run_manifest.json); intermediate products sit in inventory/, spec/, normalized/, checker/,
findings/, notes/, audit/, report/ and runtime/. `paths` prints every canonical location. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from halu_common.jsonl import read_json, write_json  # noqa: E402

SKILL_VERSION = "0.4.0"
PHASES = ["setup", "inventory", "pseudocode", "spec_review", "normalize_inspect", "normalize", "checker_compile",
          "checker_run", "evaluate", "audit", "report"]
STATUSES = ["pending", "in_progress", "done", "skipped", "failed"]

LAYOUT: "OrderedDict[str, str]" = OrderedDict([
    ("materials_inventory", "inventory/materials_inventory.json"),
    ("materials_summary", "inventory/materials_summary.md"),
    ("materials_tree", "inventory/materials_tree.md"),
    ("pseudocode", "workflow_pseudocode.md"),
    ("spec_json", "spec/workflow_spec.json"),
    ("spec_report", "spec/spec_report.md"),
    ("architecture", "architecture.md"),
    ("architect_report", "spec/architect_report.md"),
    ("spec_review", "spec/spec_review.md"),
    ("column_map_proposed", "normalized/column_map.proposed.json"),
    ("column_map", "normalized/column_map.json"),
    ("conversations", "normalized/conversations.json"),
    ("normalize_report", "normalized/normalize_report.md"),
    ("normalizer_report", "normalized/normalizer_report.md"),
    ("normalizer_inspect_report", "normalized/normalizer_inspect_report.md"),
    ("batches_dir", "normalized/batches"),
    ("checker", "checker/checker_agent.py"),
    ("checker_out_dir", "checker/results"),
    ("checker_report", "checker/checker_report.md"),
    ("findings_dir", "findings"),
    ("notes_dir", "notes"),
    ("audit_dir", "audit"),
    ("final", "hallucination_findings.json"),
    ("aggregate", "aggregate.json"),
    ("tables", "summary_tables.md"),
    ("summary", "summary.md"),
    ("reporter_report", "report/reporter_report.md"),
    ("runtime_dir", "runtime"),
    ("host_manual", "runtime/host.md"),
    ("inputs_record", "runtime/inputs.json"),
])
DIRS = ["inventory", "spec", "normalized", "normalized/batches", "checker", "checker/results", "findings", "notes", "audit", "report", "runtime"]
FILE_KEYS = list(LAYOUT.keys())
INPUT_KINDS: "OrderedDict[str, str]" = OrderedDict([
    ("materials", "the CX Agent Studio export folder(s), or loose code, callbacks, prompts and variables"),
    ("trajectories", "events.jsonl run folders, CES JSON folders, xlsx or csv exports"),
    ("ground_truth", "csv, xlsx or json keyed by session id (e.g. zip_on_file)"),
    ("docs", "workflow introduction, MDD sections, an existing pseudocode to reconcile"),
    ("config", "column_map.json, agents.json, settings.json"),
])
CONFIG_FILES = {"column_map": "column_map.json", "agents_file": "agents.json", "settings": "settings.json"}
SETTING_KEYS = ("batch_conversations", "batch_chars", "checker_threshold", "sampling", "audit")
# The models the orchestrator offers for P6 (evaluators) and P7 (auditors) at setup; any other name is accepted with a note.
MODEL_CHOICES = ("GPT-5.5", "Claude Opus 4.8", "Claude Opus 4.7", "Claude Sonnet 5.0")
PREREQS: Dict[str, List[str]] = {
    "setup": [], "inventory": ["setup"], "pseudocode": ["inventory"], "spec_review": ["pseudocode"],
    "normalize_inspect": ["setup"], "normalize": ["normalize_inspect"], "checker_compile": ["spec_review", "normalize"],
    "checker_run": ["checker_compile"], "evaluate": ["spec_review", "normalize", "checker_run"], "audit": ["evaluate"],
    "report": ["audit"],
}
ROLES = ["architect", "spec_auditor", "normalizer", "checker_compiler", "evaluator", "auditor", "reporter"]
MAX_ATTEMPTS = 2
TABULAR_SUFFIXES = (".xlsx", ".xlsm", ".csv", ".tsv")


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-") or "agent"


def default_run_id(target: str) -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + slug(target)


def manifest_path(run_dir: str) -> Path:
    return Path(run_dir) / "run_manifest.json"


# ----------------------------------------------------------------------------------------------------------
# input folder
# ----------------------------------------------------------------------------------------------------------
def _looks_like_export(folder: Path, depth: int = 0) -> bool:
    if (folder / "agents").is_dir() or (folder / "tools").is_dir():
        return True
    if depth >= 2:
        return False
    return any(_looks_like_export(child, depth + 1) for child in folder.iterdir() if child.is_dir() and not child.name.startswith("."))


def scan_input(input_dir: Path) -> dict:
    result: Dict[str, Any] = {"input_dir": str(input_dir), "exists": input_dir.is_dir(), "kinds": OrderedDict(), "missing": [],
                              "config": {}, "existing_pseudocode": [], "intro_docs": [], "hints": []}
    for kind, description in INPUT_KINDS.items():
        folder = input_dir / kind
        entries: List[dict] = []
        if folder.is_dir():
            for child in sorted(folder.iterdir()):
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    entry = {"path": str(child), "type": "dir", "files": sum(1 for p in child.rglob("*") if p.is_file())}
                    if kind == "materials" and _looks_like_export(child):
                        entry["looks_like"] = "ces_export"
                    if kind == "trajectories":
                        if any(child.rglob("events.jsonl")):
                            entry["looks_like"] = "events_jsonl"
                        elif any("response" in p.name.lower() for p in child.rglob("*.json")):
                            entry["looks_like"] = "ces_json"
                    entries.append(entry)
                else:
                    entry = {"path": str(child), "type": "file", "bytes": child.stat().st_size}
                    if kind == "trajectories" and child.suffix.lower() in (".xlsx", ".xlsm", ".csv", ".tsv"):
                        entry["looks_like"] = "tabular_export"
                    entries.append(entry)
        else:
            result["missing"].append(kind)
        result["kinds"][kind] = {"description": description, "entries": entries}
    config_dir = input_dir / "config"
    for key, name in CONFIG_FILES.items():
        candidate = config_dir / name
        result["config"][key] = str(candidate) if candidate.is_file() else None
    for entry in result["kinds"]["docs"]["entries"]:
        if entry["type"] == "file":
            (result["existing_pseudocode"] if "pseudocode" in Path(entry["path"]).name.lower() else result["intro_docs"]).append(entry["path"])
    if not result["exists"]:
        result["hints"].append("input folder does not exist; create input/materials, input/trajectories, input/ground_truth, input/docs, input/config")
    if not result["kinds"]["materials"]["entries"]:
        result["hints"].append("materials/ is empty: put the CX Agent Studio export folder (or the code, callbacks and prompts) there")
    if not result["kinds"]["trajectories"]["entries"]:
        result["hints"].append("trajectories/ is empty: put the events.jsonl run folders or the xlsx/csv export there")
    if not result["kinds"]["ground_truth"]["entries"]:
        result["hints"].append("ground_truth/ is empty: deterministic tool outputs (e.g. validate_zip_code) will be reported as unverifiable")
    if any(e.get("looks_like") == "tabular_export" for e in result["kinds"]["trajectories"]["entries"]) and not result["config"]["column_map"]:
        result["hints"].append("a tabular export needs config/column_map.json; run the normalizer in inspect mode first and confirm the proposal with the user")
    return result


def render_scan(result: dict) -> str:
    lines = ["Input folder: %s (%s)" % (result["input_dir"], "found" if result["exists"] else "MISSING")]
    for kind, info in result["kinds"].items():
        lines.append("  %s/  %s" % (kind, info["description"]))
        if not info["entries"]:
            lines.append("    (empty)" if kind not in result["missing"] else "    (folder missing)")
        for entry in info["entries"]:
            extra = " [%s]" % entry["looks_like"] if entry.get("looks_like") else ""
            size = "%d files" % entry["files"] if entry["type"] == "dir" else "%d bytes" % entry["bytes"]
            lines.append("    - %s (%s, %s)%s" % (Path(entry["path"]).name, entry["type"], size, extra))
    lines.append("  config: " + ", ".join("%s=%s" % (k, "yes" if v else "no") for k, v in result["config"].items()))
    if result["existing_pseudocode"]:
        lines.append("  existing pseudocode: " + ", ".join(Path(p).name for p in result["existing_pseudocode"]))
    for hint in result["hints"]:
        lines.append("  hint: " + hint)
    return "\n".join(lines)


def cmd_scan(args: argparse.Namespace) -> int:
    result = scan_input(Path(args.input_dir))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render_scan(result))
    return 0


# ----------------------------------------------------------------------------------------------------------
# manifest
# ----------------------------------------------------------------------------------------------------------
def load(run_dir: str) -> dict:
    path = manifest_path(run_dir)
    if not path.exists():
        print("error: %s does not exist (run `manifest.py init` first)" % path, file=sys.stderr)
        sys.exit(2)
    return read_json(path)


def save(run_dir: str, manifest: dict) -> None:
    manifest["updated_at"] = now_iso()
    write_json(manifest_path(run_dir), manifest)


def _read_settings(path: Optional[str]) -> dict:
    if not path or not Path(path).is_file():
        return {}
    try:
        data = read_json(path)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def cmd_init(args: argparse.Namespace) -> int:
    scanned: Optional[dict] = None
    if args.input:
        input_dir = Path(args.input)
        if not input_dir.is_dir():
            print("error: input folder %s does not exist" % input_dir, file=sys.stderr)
            return 2
        scanned = scan_input(input_dir)
    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.output:
        run_dir = Path(args.output) / (args.run_id or default_run_id(args.target))
    else:
        print("error: give RUN_DIR or --output OUTPUT_DIR", file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path(str(run_dir))
    if path.exists() and not args.force:
        print("manifest already exists at %s; use `next` to resume or --force to recreate" % path)
        return 0
    settings_file = _read_settings((scanned or {}).get("config", {}).get("settings"))
    settings = {"batch_conversations": 12, "batch_chars": 40000, "checker_threshold": 20, "sampling": None, "audit": True}
    for key in SETTING_KEYS:
        if key in settings_file:
            settings[key] = settings_file[key]
    settings["audit"] = False if args.no_audit else _as_bool(settings.get("audit", True), True)
    for key in ("batch_conversations", "batch_chars", "checker_threshold"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value
    model = args.model or settings_file.get("model") or ""
    audit_model = (args.audit_model or settings_file.get("audit_model") or model) if settings["audit"] else None
    for label, name in (("--model", model), ("--audit-model", audit_model or "")):
        if name and name not in MODEL_CHOICES:
            print("note: %s %r is not one of %s; recorded as given" % (label, name, ", ".join(MODEL_CHOICES)))
    mode = args.mode or settings_file.get("mode") or "multi-agent"
    inputs: Dict[str, Any] = {"materials": [], "trajectories": [], "ground_truth": [], "intro_docs": [], "existing_pseudocode": None,
                              "config": {"column_map": None, "agents_file": None, "settings": None}}
    if scanned:
        inputs["materials"] = [e["path"] for e in scanned["kinds"]["materials"]["entries"]]
        inputs["trajectories"] = [e["path"] for e in scanned["kinds"]["trajectories"]["entries"]]
        inputs["ground_truth"] = [e["path"] for e in scanned["kinds"]["ground_truth"]["entries"]]
        inputs["intro_docs"] = list(scanned["intro_docs"])
        inputs["existing_pseudocode"] = scanned["existing_pseudocode"][0] if scanned["existing_pseudocode"] else None
        inputs["config"] = dict(scanned["config"])
    if args.materials:
        inputs["materials"] = list(args.materials)
    if args.trajectories:
        inputs["trajectories"] = list(args.trajectories)
    if args.ground_truth:
        inputs["ground_truth"] = list(args.ground_truth)
    if args.intro_docs:
        inputs["intro_docs"] = list(args.intro_docs)
    if args.existing_pseudocode:
        inputs["existing_pseudocode"] = args.existing_pseudocode
    manifest = {
        "skill": "hallucination-eval", "skill_version": SKILL_VERSION, "run_id": run_dir.name,
        "created_at": now_iso(), "updated_at": now_iso(), "target_agent": args.target, "run_dir": str(run_dir.resolve()),
        "input_dir": str(Path(args.input).resolve()) if args.input else None, "inputs": inputs, "settings": settings,
        "evaluator": {"mode": mode, "model": model, "audit_model": audit_model},
        "phases": {name: {"status": "pending", "at": None, "note": None} for name in PHASES},
        "batches": {"evaluate": {}, "audit": {}},
        "layout": dict(LAYOUT), "files": {key: str((run_dir / rel).resolve()) for key, rel in LAYOUT.items()},
        "dispatches": [],
        "log": [{"at": now_iso(), "event": "init", "detail": "manifest created"}],
    }
    _apply_audit_setting(manifest)
    for sub in DIRS:
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    manifest["phases"]["setup"] = {"status": "done", "at": now_iso(), "note": None}
    write_json(run_dir / LAYOUT["inputs_record"], {"scanned": scanned, "resolved": inputs, "settings": settings, "evaluator": manifest["evaluator"]})
    save(str(run_dir), manifest)
    print("manifest written to %s" % path)
    print("run folder: %s" % run_dir.resolve())
    if scanned:
        print(render_scan(scanned))
    return 0


def cmd_paths(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    print("RUN_DIR=%s" % manifest["run_dir"])
    for key in FILE_KEYS:
        print("%s=%s" % (key.upper(), manifest["files"].get(key) or str(Path(manifest["run_dir"]) / LAYOUT[key])))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    print("run %s for %s (mode %s)" % (manifest["run_id"], manifest.get("target_agent"), manifest["evaluator"].get("mode")))
    audited = _audit_enabled(manifest)
    print("  models P6 evaluators=%s  P7 auditors=%s  audit: %s" % (manifest["evaluator"].get("model") or "not set",
                                                                   (manifest["evaluator"].get("audit_model") or manifest["evaluator"].get("model") or "not set") if audited else "-",
                                                                   "included" if audited else "skipped (P7 off, report marked UNAUDITED)"))
    if manifest.get("input_dir"):
        print("  input  %s" % manifest["input_dir"])
    print("  output %s" % manifest["run_dir"])
    for name in PHASES:
        phase = manifest["phases"].get(name, {})
        extra = ""
        if name in ("evaluate", "audit"):
            batches = manifest["batches"].get(name, {})
            done = sum(1 for s in batches.values() if s == "done")
            extra = " (%d/%d batches done)" % (done, len(batches)) if batches else ""
        print("  %-18s %-12s %s%s" % (name, phase.get("status"), phase.get("note") or "", extra))
    for key, value in manifest["files"].items():
        if value and Path(value).exists():
            print("  file %-26s %s" % (key, value))
    for record in manifest.get("dispatches", []):
        print("  dispatch %s %-17s batch=%-5s attempt=%d %s%s" % (record["id"], record["role"], record.get("batch") or "-", record["attempt"], record["status"],
                                                                  (" model=%s" % record["model"]) if record.get("model") else ""))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    running = [d for d in manifest.get("dispatches", []) if d["status"] == "running"]
    if running:
        print("running dispatches: " + ", ".join("%s %s%s" % (d["id"], d["role"], (" batch " + d["batch"]) if d.get("batch") else "") for d in running))
    for name in PHASES:
        status = manifest["phases"].get(name, {}).get("status")
        if status in ("done", "skipped"):
            continue
        pending = []
        if name in ("evaluate", "audit"):
            pending = [b for b, s in manifest["batches"].get(name, {}).items() if s != "done"]
        print(name + ((" pending batches: " + ", ".join(pending)) if pending else ""))
        return 0
    print("complete")
    return 0


# ----------------------------------------------------------------------------------------------------------
# state machine: prerequisites and gates
# ----------------------------------------------------------------------------------------------------------
def _file(manifest: dict, key: str) -> Path:
    return Path(manifest["files"].get(key) or (Path(manifest["run_dir"]) / LAYOUT[key]))


def _json_or_none(path: Path) -> Any:
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def _batch_ids(manifest: dict) -> List[str]:
    index = _json_or_none(_file(manifest, "batches_dir") / "index.json")
    if isinstance(index, dict):
        return [str(b.get("id")) for b in index.get("batches", []) if b.get("id")]
    return []


def _has_tabular_trajectories(manifest: dict) -> bool:
    return any(str(p).lower().endswith(TABULAR_SUFFIXES) for p in (manifest.get("inputs") or {}).get("trajectories") or [])


def prerequisite_problems(manifest: dict, phase: str) -> List[str]:
    problems = []
    for required in PREREQS.get(phase, []):
        status = (manifest["phases"].get(required) or {}).get("status")
        if status not in ("done", "skipped"):
            problems.append("prerequisite phase %s is %s (must be done or skipped)" % (required, status))
    return problems


def gate_problems(manifest: dict, phase: str) -> List[str]:
    """Artifacts a phase must have produced before it may be marked done."""
    problems: List[str] = []

    def need(key: str, what: str = "") -> Optional[Path]:
        path = _file(manifest, key)
        if not path.exists():
            problems.append("missing %s (%s)" % (what or key, path))
            return None
        return path

    if phase == "inventory":
        inventory = need("materials_inventory")
        need("materials_summary")
        need("materials_tree")
        if inventory:
            data = _json_or_none(inventory)
            if not isinstance(data, dict) or not data.get("agents"):
                problems.append("materials_inventory.json lists no agents (ask for agents.json)")
    elif phase == "pseudocode":
        need("pseudocode")
        spec = need("spec_json")
        need("spec_report")
        need("architecture")
        if spec:
            data = _json_or_none(spec)
            errors = ((data or {}).get("diagnostics") or {}).get("errors") if isinstance(data, dict) else None
            if errors is None:
                problems.append("workflow_spec.json has no diagnostics block (recompile)")
            elif errors:
                problems.append("workflow_spec.json has %d compile error(s)" % len(errors))
            elif isinstance(data, dict) and not data.get("points"):
                problems.append("workflow_spec.json has no point inventory")
    elif phase == "spec_review":
        review = need("spec_review")
        if review:
            text = review.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"VERDICT:\s*(APPROVED_WITH_NOTES|APPROVED|REVISE)", text)
            if not match:
                problems.append("spec_review.md has no VERDICT line")
            elif match.group(1) == "REVISE":
                problems.append("spec_review.md verdict is REVISE (re-dispatch the architect)")
    elif phase == "normalize_inspect":
        if _has_tabular_trajectories(manifest):
            need("column_map_proposed", "column map proposal")
            need("column_map", "confirmed column map (copy the user-confirmed input/config/column_map.json here)")
    elif phase == "normalize":
        need("conversations")
        index = need("batches_dir")
        if index and not (index / "index.json").exists():
            problems.append("missing batches index (%s)" % (index / "index.json"))
        elif index and not _batch_ids(manifest):
            problems.append("batches index lists no batches")
    elif phase == "checker_compile":
        checker = need("checker")
        if checker:
            try:
                compile(checker.read_text(encoding="utf-8"), str(checker), "exec")
            except SyntaxError as error:
                problems.append("checker does not compile: %s" % error)
    elif phase == "checker_run":
        out = need("checker_out_dir")
        if out:
            if not (out / "index.json").exists():
                problems.append("missing checker results index (%s)" % (out / "index.json"))
            for batch_id in _batch_ids(manifest):
                if not (out / ("batch_%s.json" % batch_id)).exists():
                    problems.append("no checker result for batch %s" % batch_id)
    elif phase in ("evaluate", "audit"):
        registered = manifest["batches"].get(phase) or {}
        ids = _batch_ids(manifest)
        if not registered:
            problems.append("no %s batches registered (run register-batches after normalize)" % phase)
        for batch_id in ids:
            if registered.get(batch_id) != "done":
                problems.append("%s batch %s is %s" % (phase, batch_id, registered.get(batch_id, "not registered")))
            name = ("batch_%s.json" if phase == "evaluate" else "verified_batch_%s.json") % batch_id
            path = _file(manifest, "findings_dir") / name
            if not path.exists():
                problems.append("missing %s" % path)
            elif not isinstance(_json_or_none(path), dict):
                problems.append("%s is not valid JSON" % path)
    elif phase == "report":
        final = need("final")
        need("aggregate")
        need("summary")
        if final:
            data = _json_or_none(final)
            if not isinstance(data, dict) or "meta" not in data or "conversations" not in data:
                problems.append("hallucination_findings.json lacks meta or conversations")
            elif _audit_enabled(manifest) and ((data.get("meta") or {}).get("evaluator") or {}).get("audited") is False:
                problems.append("hallucination_findings.json is unaudited but the audit phase was included (merge the verified batches)")
    return problems


def cmd_gate(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    if args.phase not in PHASES:
        print("error: unknown phase %s" % args.phase, file=sys.stderr)
        return 2
    problems = prerequisite_problems(manifest, args.phase) + gate_problems(manifest, args.phase)
    for problem in problems:
        print("GATE %s: %s" % (args.phase, problem))
    print("gate %s: %s" % (args.phase, "PASS" if not problems else "FAIL (%d problem(s))" % len(problems)))
    return 0 if not problems else 1


def cmd_set_phase(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    if args.phase not in PHASES:
        print("error: unknown phase %s (choose from %s)" % (args.phase, ", ".join(PHASES)), file=sys.stderr)
        return 2
    if args.status not in STATUSES:
        print("error: unknown status %s" % args.status, file=sys.stderr)
        return 2
    note = args.note
    if args.status == "done":
        problems = prerequisite_problems(manifest, args.phase) + gate_problems(manifest, args.phase)
        if problems and not args.force:
            for problem in problems:
                print("GATE %s: %s" % (args.phase, problem))
            print("refused: %s cannot be marked done (%d problem(s)); fix them or use --force --note REASON" % (args.phase, len(problems)))
            return 1
        if problems and args.force:
            if not note:
                print("error: --force requires --note with the reason", file=sys.stderr)
                return 2
            note = "FORCED past %d gate problem(s): %s" % (len(problems), note)
            manifest["log"].append({"at": now_iso(), "event": "forced", "detail": "%s done despite: %s" % (args.phase, "; ".join(problems))})
    if args.status == "skipped" and not note:
        print("error: skipping a phase requires --note with the reason", file=sys.stderr)
        return 2
    if args.status == "done" and args.phase == "normalize":
        added = _register_batches(manifest)
        if added:
            manifest["log"].append({"at": now_iso(), "event": "batches", "detail": "registered %d batch(es)" % added})
    manifest["phases"][args.phase] = {"status": args.status, "at": now_iso(), "note": note}
    manifest["log"].append({"at": now_iso(), "event": "phase", "detail": "%s -> %s" % (args.phase, args.status)})
    save(args.run_dir, manifest)
    print("%s = %s" % (args.phase, args.status))
    return 0


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("true", "yes", "1", "on", "included", "include"):
        return True
    if text in ("false", "no", "0", "off", "skipped", "skip"):
        return False
    raise ValueError(value)


def _audit_enabled(manifest: dict) -> bool:
    return _as_bool((manifest.get("settings") or {}).get("audit", True), True)


def _apply_audit_setting(manifest: dict) -> None:
    """Keep the audit phase and its batch map consistent with settings.audit (P7 included or skipped)."""
    phase = manifest["phases"].setdefault("audit", {"status": "pending", "at": None, "note": None})
    if not _audit_enabled(manifest):
        if phase.get("status") != "done":
            manifest["phases"]["audit"] = {"status": "skipped", "at": now_iso(), "note": "audit not included at setup (P7 skipped; the report is marked UNAUDITED)"}
        manifest["batches"]["audit"] = {}
    else:
        if phase.get("status") == "skipped":
            manifest["phases"]["audit"] = {"status": "pending", "at": None, "note": None}
        _register_batches(manifest)


def _register_batches(manifest: dict) -> int:
    added = 0
    phases = ("evaluate", "audit") if _audit_enabled(manifest) else ("evaluate",)
    for batch_id in _batch_ids(manifest):
        for phase in phases:
            if batch_id not in manifest["batches"].setdefault(phase, {}):
                manifest["batches"][phase][batch_id] = "pending"
                added += 1
    return added


def cmd_register_batches(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    ids = _batch_ids(manifest)
    if not ids:
        print("error: no batches index under %s" % _file(manifest, "batches_dir"), file=sys.stderr)
        return 1
    added = _register_batches(manifest)
    save(args.run_dir, manifest)
    print("registered %d batch(es): %s (%d new)" % (len(ids), ", ".join(ids), added))
    return 0


# ----------------------------------------------------------------------------------------------------------
# subagent lifecycle: dispatch and finalize records
# ----------------------------------------------------------------------------------------------------------
INT_SETTINGS = ("batch_conversations", "batch_chars", "checker_threshold")


def cmd_set_setting(args: argparse.Namespace) -> int:
    """Change one setting mid-run (logged). `model` sets evaluator.model, the model evaluators and auditors run on."""
    manifest = load(args.run_dir)
    key = args.key
    value: Any = args.value
    if key in ("model", "audit_model"):
        if value not in MODEL_CHOICES:
            print("note: %r is not one of %s; recorded as given" % (value, ", ".join(MODEL_CHOICES)))
        manifest.setdefault("evaluator", {})[key] = value
    elif key in SETTING_KEYS:
        if key in INT_SETTINGS:
            try:
                value = int(value)
            except ValueError:
                print("error: %s expects an integer, got %r" % (key, args.value), file=sys.stderr)
                return 2
        elif key == "sampling":
            try:
                value = json.loads(value)
            except ValueError:
                print("error: sampling expects JSON (null or an object), got %r" % args.value, file=sys.stderr)
                return 2
        elif key == "audit":
            try:
                value = _as_bool(value, True)
            except ValueError:
                print("error: audit expects true or false, got %r" % args.value, file=sys.stderr)
                return 2
        manifest.setdefault("settings", {})[key] = value
        if key == "audit":
            _apply_audit_setting(manifest)
    else:
        print("error: unknown setting %s (choose from %s, model, audit_model)" % (key, ", ".join(SETTING_KEYS)), file=sys.stderr)
        return 2
    manifest["log"].append({"at": now_iso(), "event": "setting", "detail": "%s = %s" % (key, args.value)})
    save(args.run_dir, manifest)
    print("%s = %s" % (key, args.value))
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    if args.role not in ROLES:
        print("error: unknown role %s (choose from %s)" % (args.role, ", ".join(ROLES)), file=sys.stderr)
        return 2
    prompt = Path(args.prompt)
    if not prompt.exists():
        print("error: prompt file %s does not exist (run prompt_harness.py first)" % prompt, file=sys.stderr)
        return 2
    if re.search(r"\{\{[A-Z][A-Z0-9_]*\}\}", prompt.read_text(encoding="utf-8", errors="replace")):
        print("error: prompt file %s still contains {{PLACEHOLDER}} slots" % prompt, file=sys.stderr)
        return 2
    dispatches = manifest.setdefault("dispatches", [])
    same = [d for d in dispatches if d["role"] == args.role and d.get("batch") == args.batch]
    running = [d for d in same if d["status"] == "running"]
    if running and not args.force:
        print("refused: %s is already running for this batch (%s); finalize it first or use --force" % (args.role, running[-1]["id"]))
        return 1
    attempt = len(same) + 1
    if attempt > MAX_ATTEMPTS and not args.force:
        print("refused: attempt %d for %s%s exceeds the limit of %d; report to the user, then --force if they decide to retry" % (
            attempt, args.role, (" batch " + args.batch) if args.batch else "", MAX_ATTEMPTS))
        return 1
    dispatch_id = "d-%04d" % (len(dispatches) + 1)
    chosen = manifest.get("evaluator") or {}
    default_model = chosen.get("audit_model") if args.role == "auditor" else chosen.get("model")
    model = args.model or default_model or chosen.get("model") or None
    dispatches.append({"id": dispatch_id, "role": args.role, "batch": args.batch, "prompt": str(prompt.resolve()), "attempt": attempt,
                       "status": "running", "started_at": now_iso(), "finished_at": None, "outputs": [], "note": None, "model": model})
    manifest["log"].append({"at": now_iso(), "event": "dispatch", "detail": "%s %s%s attempt %d" % (dispatch_id, args.role, (" batch " + args.batch) if args.batch else "", attempt)})
    save(args.run_dir, manifest)
    print(dispatch_id)
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    record = next((d for d in manifest.get("dispatches", []) if d["id"] == args.dispatch_id), None)
    if record is None:
        print("error: no dispatch %s" % args.dispatch_id, file=sys.stderr)
        return 2
    missing = [p for p in (args.outputs or []) if not Path(p).exists()]
    status = args.status
    note = args.note
    if missing and status == "done":
        status = "failed"
        note = ("%s; " % note if note else "") + "outputs missing: " + ", ".join(missing)
    record.update({"status": status, "finished_at": now_iso(), "outputs": list(args.outputs or []), "note": note})
    manifest["log"].append({"at": now_iso(), "event": "finalize", "detail": "%s %s -> %s" % (record["id"], record["role"], status)})
    save(args.run_dir, manifest)
    print("%s %s = %s%s" % (record["id"], record["role"], status, (" (" + note + ")") if note else ""))
    return 0 if status == "done" else 1


def cmd_set_batch(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    if args.phase not in ("evaluate", "audit"):
        print("error: batches exist only for evaluate and audit", file=sys.stderr)
        return 2
    manifest["batches"].setdefault(args.phase, {})[args.batch] = args.status
    statuses = set(manifest["batches"][args.phase].values())
    if statuses and statuses <= {"done"}:
        manifest["phases"][args.phase] = {"status": "done", "at": now_iso(), "note": "all batches done"}
    else:
        manifest["phases"][args.phase] = {"status": "in_progress", "at": now_iso(), "note": None}
    manifest["log"].append({"at": now_iso(), "event": "batch", "detail": "%s %s -> %s" % (args.phase, args.batch, args.status)})
    save(args.run_dir, manifest)
    print("%s batch %s = %s" % (args.phase, args.batch, args.status))
    return 0


def cmd_set_file(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    manifest["files"][args.key] = args.path
    manifest["log"].append({"at": now_iso(), "event": "file", "detail": "%s = %s" % (args.key, args.path)})
    save(args.run_dir, manifest)
    print("%s = %s" % (args.key, args.path))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    manifest = load(args.run_dir)
    manifest["log"].append({"at": now_iso(), "event": "note", "detail": args.message})
    save(args.run_dir, manifest)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("input_dir")
    p_scan.add_argument("--json", action="store_true")
    p_scan.set_defaults(func=cmd_scan)
    p_init = sub.add_parser("init")
    p_init.add_argument("run_dir", nargs="?")
    p_init.add_argument("--target", required=True)
    p_init.add_argument("--input")
    p_init.add_argument("--output")
    p_init.add_argument("--run-id")
    p_init.add_argument("--materials", nargs="*")
    p_init.add_argument("--trajectories", nargs="*")
    p_init.add_argument("--ground-truth", nargs="*")
    p_init.add_argument("--intro-docs", nargs="*")
    p_init.add_argument("--existing-pseudocode")
    p_init.add_argument("--batch-conversations", type=int)
    p_init.add_argument("--batch-chars", type=int)
    p_init.add_argument("--checker-threshold", type=int)
    p_init.add_argument("--model", help="model that runs the P6 evaluators (one of: %s)" % ", ".join(MODEL_CHOICES))
    p_init.add_argument("--audit-model", help="model that runs the P7 auditors (default: the same as --model)")
    p_init.add_argument("--no-audit", action="store_true", help="skip the P7 audit: the run ends after P6 and the report is marked UNAUDITED")
    p_init.add_argument("--mode", choices=["multi-agent", "single-agent"])
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)
    p_paths = sub.add_parser("paths")
    p_paths.add_argument("run_dir")
    p_paths.set_defaults(func=cmd_paths)
    p_show = sub.add_parser("show")
    p_show.add_argument("run_dir")
    p_show.set_defaults(func=cmd_show)
    p_next = sub.add_parser("next")
    p_next.add_argument("run_dir")
    p_next.set_defaults(func=cmd_next)
    p_gate = sub.add_parser("gate")
    p_gate.add_argument("run_dir")
    p_gate.add_argument("phase")
    p_gate.set_defaults(func=cmd_gate)
    p_phase = sub.add_parser("set-phase")
    p_phase.add_argument("run_dir")
    p_phase.add_argument("phase")
    p_phase.add_argument("status")
    p_phase.add_argument("--note")
    p_phase.add_argument("--force", action="store_true")
    p_phase.set_defaults(func=cmd_set_phase)
    p_register = sub.add_parser("register-batches")
    p_register.add_argument("run_dir")
    p_register.set_defaults(func=cmd_register_batches)
    p_setting = sub.add_parser("set-setting", help="change one setting mid-run")
    p_setting.add_argument("run_dir")
    p_setting.add_argument("key")
    p_setting.add_argument("value")
    p_setting.set_defaults(func=cmd_set_setting)
    p_dispatch = sub.add_parser("dispatch")
    p_dispatch.add_argument("run_dir")
    p_dispatch.add_argument("role")
    p_dispatch.add_argument("--prompt", required=True)
    p_dispatch.add_argument("--batch")
    p_dispatch.add_argument("--force", action="store_true")
    p_dispatch.add_argument("--model", help="model this subagent runs on (default: evaluator.model for evaluators, evaluator.audit_model for auditors)")
    p_dispatch.set_defaults(func=cmd_dispatch)
    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("run_dir")
    p_finalize.add_argument("dispatch_id")
    p_finalize.add_argument("--status", required=True, choices=["done", "failed", "blocked"])
    p_finalize.add_argument("--outputs", nargs="*")
    p_finalize.add_argument("--note")
    p_finalize.set_defaults(func=cmd_finalize)
    p_batch = sub.add_parser("set-batch")
    p_batch.add_argument("run_dir")
    p_batch.add_argument("phase")
    p_batch.add_argument("batch")
    p_batch.add_argument("status")
    p_batch.set_defaults(func=cmd_set_batch)
    p_file = sub.add_parser("set-file")
    p_file.add_argument("run_dir")
    p_file.add_argument("key", choices=FILE_KEYS)
    p_file.add_argument("path")
    p_file.set_defaults(func=cmd_set_file)
    p_log = sub.add_parser("log")
    p_log.add_argument("run_dir")
    p_log.add_argument("message")
    p_log.set_defaults(func=cmd_log)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import csv
import copy
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .agent_edit import run_agent_edit
from .agent_validate import validate_agentic
from .config import Settings
from .io_utils import read_json, write_json, write_text
from .pipeline import PipelineError, run_pipeline
from .plantuml import ir_to_plantuml
from .roundtrip import run_roundtrip


@dataclass(frozen=True)
class HITLCase:
    case_id: str
    edit_type: str
    scenario_text: str
    agent_request: str
    apply_manual_edit: Callable[[Dict[str, Any]], Tuple[Dict[str, Any], str, List[str]]]
    evaluate: Callable[[Dict[str, Any]], Tuple[bool, bool, List[str]]]


def _sm(ir: Dict[str, Any]) -> Dict[str, Any]:
    sm = ir.get("stateMachine")
    if not isinstance(sm, dict):
        raise PipelineError("IR missing stateMachine object")
    return sm


def _transitions(ir: Dict[str, Any]) -> List[Dict[str, Any]]:
    ts = _sm(ir).get("transitions")
    if not isinstance(ts, list):
        raise PipelineError("IR missing stateMachine.transitions[] list")
    return [t for t in ts if isinstance(t, dict)]


def _actions(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    acts = t.get("actions")
    return [a for a in acts if isinstance(a, dict)] if isinstance(acts, list) else []


def _triggers(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    trigs = t.get("triggers")
    return [tg for tg in trigs if isinstance(tg, dict)] if isinstance(trigs, list) else []


def _is_command(a: Dict[str, Any], device: str, command: str) -> bool:
    return a.get("type") == "command" and a.get("device") == device and a.get("command") == command


def _has_command(ir: Dict[str, Any], device: str, command: str) -> bool:
    return any(_is_command(a, device, command) for t in _transitions(ir) for a in _actions(t))


def _has_notify(ir: Dict[str, Any], contains: Optional[str] = None) -> bool:
    for t in _transitions(ir):
        for a in _actions(t):
            if a.get("type") == "notify":
                if contains is None or contains in str(a.get("message", "")):
                    return True
    return False


def _after_values(ir: Dict[str, Any]) -> List[int]:
    vals: List[int] = []
    for t in _transitions(ir):
        for tg in _triggers(t):
            if tg.get("type") == "after" and isinstance(tg.get("seconds"), int):
                vals.append(int(tg["seconds"]))
        for a in _actions(t):
            if a.get("type") == "delay" and isinstance(a.get("seconds"), int):
                vals.append(int(a["seconds"]))
    return vals


def _literal_value(obj: Any) -> Any:
    if not isinstance(obj, dict):
        return None
    if "string" in obj:
        return obj.get("string")
    if "number" in obj:
        return obj.get("number")
    if "bool" in obj:
        return obj.get("bool")
    return None


def _expr_contains_ref_lit(expr: Any, device: str, path: str, value: Any) -> bool:
    if not isinstance(expr, dict):
        return False
    if expr.get("op") in {"eq", "neq", "lt", "lte", "gt", "gte"}:
        args = expr.get("args") if isinstance(expr.get("args"), list) else []
        if len(args) >= 2:
            left, right = args[0], args[1]
            if isinstance(left, dict) and isinstance(left.get("ref"), dict):
                ref = left["ref"]
                if ref.get("device") == device and ref.get("path") == path and _literal_value(right.get("lit") if isinstance(right, dict) else None) == value:
                    return True
    for child in expr.get("args", []) if isinstance(expr.get("args"), list) else []:
        if _expr_contains_ref_lit(child, device, path, value):
            return True
    return False


def _replace_expr_lit(expr: Any, device: str, path: str, old_value: Any, new_value: Any) -> bool:
    """Mutates expr in place; returns True if a matching literal was replaced."""
    if not isinstance(expr, dict):
        return False
    changed = False
    if expr.get("op") in {"eq", "neq", "lt", "lte", "gt", "gte"}:
        args = expr.get("args") if isinstance(expr.get("args"), list) else []
        if len(args) >= 2:
            left, right = args[0], args[1]
            if isinstance(left, dict) and isinstance(left.get("ref"), dict) and isinstance(right, dict) and isinstance(right.get("lit"), dict):
                ref = left["ref"]
                if ref.get("device") == device and ref.get("path") == path and _literal_value(right["lit"]) == old_value:
                    right["lit"] = {"string": new_value} if isinstance(new_value, str) else {"number": new_value}
                    changed = True
    for child in expr.get("args", []) if isinstance(expr.get("args"), list) else []:
        changed = _replace_expr_lit(child, device, path, old_value, new_value) or changed
    return changed


def _find_first_transition(ir: Dict[str, Any], predicate: Callable[[Dict[str, Any]], bool]) -> Optional[Dict[str, Any]]:
    for t in _transitions(ir):
        if predicate(t):
            return t
    return None


def _change_delay(ir: Dict[str, Any], old_seconds: int, new_seconds: int) -> Tuple[Dict[str, Any], str, List[str]]:
    edited = copy.deepcopy(ir)
    changed = False
    notes: List[str] = []
    for t in _transitions(edited):
        for tg in _triggers(t):
            if tg.get("type") == "after" and int(tg.get("seconds", -1)) == old_seconds:
                tg["seconds"] = new_seconds
                changed = True
        for a in _actions(t):
            if a.get("type") == "delay" and int(a.get("seconds", -1)) == old_seconds:
                a["seconds"] = new_seconds
                changed = True
    if not changed:
        notes.append(f"No {old_seconds}s timer/delay found to change.")
    return edited, f"Changed duration from {old_seconds}s to {new_seconds}s.", notes


def _change_presence_guard(ir: Dict[str, Any]) -> Tuple[Dict[str, Any], str, List[str]]:
    edited = copy.deepcopy(ir)
    changed = False
    for t in _transitions(edited):
        g = t.get("guard")
        if isinstance(g, dict):
            changed = _replace_expr_lit(g, "presence_user", "presence", "not present", "present") or changed
    notes = [] if changed else ["No presence_user.presence == 'not present' guard found to change."]
    return edited, "Changed presence guard from not present to present.", notes


def _remove_notify(ir: Dict[str, Any]) -> Tuple[Dict[str, Any], str, List[str]]:
    edited = copy.deepcopy(ir)
    removed = False
    for t in _transitions(edited):
        acts = t.get("actions")
        if isinstance(acts, list):
            new_acts = [a for a in acts if not (isinstance(a, dict) and a.get("type") == "notify")]
            if len(new_acts) != len(acts):
                removed = True
                t["actions"] = new_acts
    notes = [] if removed else ["No notify action found to remove."]
    return edited, "Removed notify action while preserving other actions.", notes


def _add_away_notify(ir: Dict[str, Any]) -> Tuple[Dict[str, Any], str, List[str]]:
    edited = copy.deepcopy(ir)
    target = _find_first_transition(
        edited,
        lambda t: any(_is_command(a, "light_hall", "off") for a in _actions(t))
        and any(_is_command(a, "lock_front", "lock") for a in _actions(t)),
    )
    notes: List[str] = []
    if target is None:
        notes.append("No transition with light_hall.off() and lock_front.lock() found.")
    else:
        target.setdefault("actions", []).append({"type": "notify", "message": "House set to away mode."})
    return edited, "Added away-mode notification action.", notes


def _change_notify_message(ir: Dict[str, Any]) -> Tuple[Dict[str, Any], str, List[str]]:
    edited = copy.deepcopy(ir)
    changed = False
    for t in _transitions(edited):
        for a in _actions(t):
            if a.get("type") == "notify":
                a["message"] = "Warning: front door unlocked after 9 PM."
                changed = True
    notes = [] if changed else ["No notify action found to change."]
    return edited, "Changed notification message.", notes


def _eval_delay_600(ir: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    vals = _after_values(ir)
    edit_ok = 600 in vals and 300 not in vals
    protected_ok = _has_command(ir, "light_hall", "on") or _has_command(ir, "light_hall", "off")
    notes = []
    if not edit_ok:
        notes.append(f"Expected 600s timer/delay and no 300s timer/delay; saw {vals}.")
    if not protected_ok:
        notes.append("Expected hallway light behavior to remain present.")
    return edit_ok, protected_ok, notes


def _eval_presence_present(ir: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    edit_ok = any(_expr_contains_ref_lit(t.get("guard"), "presence_user", "presence", "present") for t in _transitions(ir))
    old_present = any(_expr_contains_ref_lit(t.get("guard"), "presence_user", "presence", "not present") for t in _transitions(ir))
    protected_ok = _has_command(ir, "light_hall", "on")
    notes: List[str] = []
    if not edit_ok or old_present:
        notes.append("Expected presence guard to be present, not not-present.")
    if not protected_ok:
        notes.append("Expected hallway light on action to remain present.")
    return edit_ok and not old_present, protected_ok, notes


def _eval_remove_notify_keep_siren(ir: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    edit_ok = not _has_notify(ir)
    protected_ok = _has_command(ir, "alarm_main", "siren")
    notes: List[str] = []
    if not edit_ok:
        notes.append("Expected notify action to be removed.")
    if not protected_ok:
        notes.append("Expected alarm_main.siren() action to remain present.")
    return edit_ok, protected_ok, notes


def _eval_add_notify_keep_actions(ir: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    edit_ok = _has_notify(ir, "House set to away mode")
    protected_ok = _has_command(ir, "light_hall", "off") and _has_command(ir, "lock_front", "lock")
    notes: List[str] = []
    if not edit_ok:
        notes.append("Expected away-mode notify action to be present.")
    if not protected_ok:
        notes.append("Expected light_hall.off() and lock_front.lock() to remain present.")
    return edit_ok, protected_ok, notes


def _eval_notify_message(ir: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    edit_ok = _has_notify(ir, "Warning: front door unlocked after 9 PM")
    protected_ok = _has_command(ir, "light_hall", "on")
    notes: List[str] = []
    if not edit_ok:
        notes.append("Expected edited notification message to be present.")
    if not protected_ok:
        notes.append("Expected light_hall.on() action to remain present.")
    return edit_ok, protected_ok, notes


DEFAULT_HITL_CASES: Tuple[HITLCase, ...] = (
    HITLCase(
        case_id="S10_DelayEdit",
        edit_type="delay_change",
        scenario_text="If motion is detected by the Hallway Motion Sensor and the Front Door Lock is unlocked, then turn on the Hallway Light for 5 minutes.",
        agent_request="Change the hallway light timeout from 5 minutes to 10 minutes. Keep the same trigger, guard, and devices.",
        apply_manual_edit=lambda ir: _change_delay(ir, 300, 600),
        evaluate=_eval_delay_600,
    ),
    HITLCase(
        case_id="S13_GuardEdit",
        edit_type="guard_change",
        scenario_text="If the Front Door Contact Sensor opens and User Presence is not present, then turn on the Hallway Light.",
        agent_request="Change the condition so the hallway light turns on only when User Presence is present, instead of not present. Keep the front door opening trigger.",
        apply_manual_edit=_change_presence_guard,
        evaluate=_eval_presence_present,
    ),
    HITLCase(
        case_id="S16_RemoveNotify",
        edit_type="remove_action",
        scenario_text="If the Front Door Contact Sensor opens while Location Mode is Away, then turn on the Main Alarm Siren and send a notification.",
        agent_request="Remove the notification action from this automation. Keep the Main Alarm Siren action and keep the Location Mode Away condition.",
        apply_manual_edit=_remove_notify,
        evaluate=_eval_remove_notify_keep_siren,
    ),
    HITLCase(
        case_id="S17_AddNotify",
        edit_type="add_action",
        scenario_text="If User Presence becomes not present and Location Mode is set to Away, then turn off the Hallway Light and lock the Front Door Lock.",
        agent_request="Add a notification action that says \"House set to away mode.\" Keep the existing actions that turn off the hallway light and lock the front door.",
        apply_manual_edit=_add_away_notify,
        evaluate=_eval_add_notify_keep_actions,
    ),
    HITLCase(
        case_id="S20_NotificationEdit",
        edit_type="notification_message_change",
        scenario_text="If the Front Door Lock becomes unlocked after 9:00 PM, then turn on the Hallway Light and send a notification.",
        agent_request="Change the notification message to \"Warning: front door unlocked after 9 PM.\" Keep the lock trigger, time condition, and hallway light action unchanged.",
        apply_manual_edit=_change_notify_message,
        evaluate=_eval_notify_message,
    ),
    HITLCase(
        case_id="S12_DurationEdit",
        edit_type="duration_change",
        scenario_text="If the Front Door Contact Sensor stays open for more than 5 minutes, then turn off the Hallway Light.",
        agent_request="Change the duration condition from more than 5 minutes to more than 10 minutes. Keep the front door contact sensor trigger and the hallway light off action.",
        apply_manual_edit=lambda ir: _change_delay(ir, 300, 600),
        evaluate=_eval_delay_600,
    ),
)


def _safe_name(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in s).strip("_")


def _count_det_report(report: Dict[str, Any]) -> Tuple[int, int]:
    diags = report.get("diagnostics") if isinstance(report.get("diagnostics"), list) else []
    errors = [d for d in diags if isinstance(d, dict) and d.get("severity") == "error"]
    warnings = [d for d in diags if isinstance(d, dict) and d.get("severity") == "warning"]
    return len(errors), len(warnings)


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: List[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _pct(n: int, d: int) -> str:
    return "n/a" if d == 0 else f"{(100.0 * n / d):.2f}%"


def _read_if_exists(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path and path.exists():
        try:
            return read_json(path)
        except Exception:
            return None
    return None


def _post_validate(ir: Dict[str, Any], artifact_dir: Path) -> Tuple[bool, Path]:
    _issues, report = validate_agentic(ir)
    path = artifact_dir / "hitl.l5.validation_agent.json"
    write_json(path, report)
    return bool(report.get("ok", False)), path


def _infer_failure_stage(row: Dict[str, Any]) -> str:
    """Return the first pipeline stage that explains a non-successful HITL row."""
    if row.get("hitl_success"):
        return "success"
    if not row.get("baseline_completed"):
        return "baseline_generation"
    if not row.get("baseline_det_valid"):
        return "baseline_validation"
    if not row.get("edit_applied"):
        return "agent_patch" if row.get("mode") == "agentic_nl_edit" else "manual_edit"
    if not row.get("roundtrip_or_agent_completed"):
        return "agent_edit" if row.get("mode") == "agentic_nl_edit" else "manual_roundtrip"
    if not row.get("regenerated_puml"):
        return "plantuml_regeneration"
    if not row.get("post_det_valid"):
        return "post_edit_validation"
    if not row.get("post_agentic_valid"):
        return "layer5_validation"
    if not row.get("edit_preserved"):
        return "edit_preservation"
    if not row.get("protected_behavior_preserved"):
        return "protected_behavior"
    return "unknown"


def _failure_stage_counts(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        stage = str(row.get("failure_stage") or _infer_failure_stage(row))
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def _result_row_base(case: HITLCase, mode: str, bundle_name: str, bundle_root: Path) -> Dict[str, Any]:
    return {
        "test_id": f"{mode}_{case.case_id}",
        "case_id": case.case_id,
        "mode": mode,
        "edit_type": case.edit_type,
        "bundle_name": bundle_name,
        "bundle_root": str(bundle_root),
        "scenario_text": case.scenario_text,
        "agent_request": case.agent_request if mode == "agentic_nl_edit" else "",
        "baseline_completed": False,
        "baseline_det_valid": False,
        "edit_applied": False,
        "roundtrip_or_agent_completed": False,
        "post_det_valid": False,
        "post_agentic_valid": False,
        "post_overall_valid": False,
        "regenerated_puml": False,
        "edit_preserved": False,
        "protected_behavior_preserved": False,
        "unintended_changes_detected": "",
        "hitl_success": False,
        "failure_stage": "",
        "det_errors_after": "",
        "det_warnings_after": "",
        "revision_dir": "",
        "puml_path": "",
        "ir_path": "",
        "validation_path": "",
        "layer5_path": "",
        "notes": "",
    }


def _run_manual_case(
    *,
    case: HITLCase,
    runs_dir: Path,
    settings: Settings,
    use_mock: bool,
    baseline_max_repairs: int,
) -> Dict[str, Any]:
    bundle_name = _safe_name(f"HITL_Manual_{case.case_id}")
    bundle_root = runs_dir / bundle_name
    row = _result_row_base(case, "manual_puml", bundle_name, bundle_root)
    notes: List[str] = []
    stage = "baseline_generation"
    try:
        base_paths = run_pipeline(
            text=case.scenario_text,
            bundle_name=bundle_name,
            settings=settings,
            out_dir=runs_dir,
            use_mock=use_mock,
            max_repairs=baseline_max_repairs,
        )
        row["baseline_completed"] = True
        stage = "baseline_validation"
        base_report = read_json(base_paths["validation"])
        row["baseline_det_valid"] = bool(base_report.get("ok", False))
        stage = "manual_edit"
        base_ir = read_json(base_paths["ir"])

        edited_ir, edit_summary, edit_notes = case.apply_manual_edit(base_ir)
        notes.append(edit_summary)
        notes.extend(edit_notes)
        row["edit_applied"] = len(edit_notes) == 0
        stage = "manual_roundtrip"

        edited_puml_path = Path(base_paths["bundle_root"]) / "hitl_edited.puml"
        write_text(edited_puml_path, ir_to_plantuml(edited_ir, title=bundle_name))

        out_paths, summary_lines = run_roundtrip(
            puml_path=edited_puml_path,
            out_bundle_dir=Path(base_paths["bundle_root"]),
            settings=settings,
            baseline_ir_path=Path(base_paths["ir"]),
        )
        notes.extend(summary_lines)
        row["roundtrip_or_agent_completed"] = True
        row["revision_dir"] = str(out_paths.get("revision_dir", ""))
        row["puml_path"] = str(out_paths.get("puml", ""))
        row["ir_path"] = str(out_paths.get("ir", ""))
        row["validation_path"] = str(out_paths.get("validation", ""))
        row["regenerated_puml"] = Path(out_paths["puml"]).exists()
        stage = "post_edit_validation"

        final_ir = read_json(out_paths["ir"])
        final_report = read_json(out_paths["validation"])
        det_errors, det_warnings = _count_det_report(final_report)
        row["det_errors_after"] = det_errors
        row["det_warnings_after"] = det_warnings
        row["post_det_valid"] = bool(final_report.get("ok", False))
        stage = "layer5_validation"
        l5_ok, l5_path = _post_validate(final_ir, Path(out_paths["revision_dir"]))
        row["post_agentic_valid"] = l5_ok
        row["layer5_path"] = str(l5_path)
        stage = "edit_preservation"
        edit_ok, protected_ok, eval_notes = case.evaluate(final_ir)
        notes.extend(eval_notes)
        row["edit_preserved"] = edit_ok
        row["protected_behavior_preserved"] = protected_ok
        row["post_overall_valid"] = bool(row["post_det_valid"] and row["post_agentic_valid"])
        row["unintended_changes_detected"] = not protected_ok
        row["hitl_success"] = bool(row["edit_applied"] and row["post_overall_valid"] and row["regenerated_puml"] and edit_ok and protected_ok)
    except Exception as e:
        row["failure_stage"] = stage
        notes.append(f"ERROR: {e}")
    if not row.get("failure_stage"):
        row["failure_stage"] = _infer_failure_stage(row)
    row["notes"] = " | ".join(str(n) for n in notes if str(n).strip())
    return row


def _run_agent_case(
    *,
    case: HITLCase,
    runs_dir: Path,
    settings: Settings,
    use_mock: bool,
    baseline_max_repairs: int,
    agent_max_repairs: int,
) -> Dict[str, Any]:
    bundle_name = _safe_name(f"HITL_Agent_{case.case_id}")
    bundle_root = runs_dir / bundle_name
    row = _result_row_base(case, "agentic_nl_edit", bundle_name, bundle_root)
    notes: List[str] = []
    stage = "baseline_generation"
    try:
        base_paths = run_pipeline(
            text=case.scenario_text,
            bundle_name=bundle_name,
            settings=settings,
            out_dir=runs_dir,
            use_mock=use_mock,
            max_repairs=baseline_max_repairs,
        )
        row["baseline_completed"] = True
        stage = "baseline_validation"
        base_report = read_json(base_paths["validation"])
        row["baseline_det_valid"] = bool(base_report.get("ok", False))
        stage = "agent_patch"

        out_paths, summary_lines = run_agent_edit(
            bundle_name=bundle_name,
            out_dir=runs_dir,
            request_text=case.agent_request,
            settings=settings,
            use_mock=use_mock,
            max_repairs=agent_max_repairs,
        )
        notes.extend(summary_lines)
        row["roundtrip_or_agent_completed"] = "ir" in out_paths and Path(out_paths["ir"]).exists()
        row["edit_applied"] = "patch" in out_paths and Path(out_paths["patch"]).exists()
        row["revision_dir"] = str(out_paths.get("revision_dir", ""))
        row["puml_path"] = str(out_paths.get("puml", ""))
        row["ir_path"] = str(out_paths.get("ir", ""))
        row["validation_path"] = str(out_paths.get("validation", ""))
        row["regenerated_puml"] = bool("puml" in out_paths and Path(out_paths["puml"]).exists())
        stage = "post_edit_validation"

        final_ir = _read_if_exists(Path(out_paths["ir"]) if "ir" in out_paths else None)
        final_report = _read_if_exists(Path(out_paths["validation"]) if "validation" in out_paths else None)
        if final_report is not None:
            det_errors, det_warnings = _count_det_report(final_report)
            row["det_errors_after"] = det_errors
            row["det_warnings_after"] = det_warnings
            row["post_det_valid"] = bool(final_report.get("ok", False))
        if final_ir is not None and "revision_dir" in out_paths:
            stage = "layer5_validation"
            l5_ok, l5_path = _post_validate(final_ir, Path(out_paths["revision_dir"]))
            row["post_agentic_valid"] = l5_ok
            row["layer5_path"] = str(l5_path)
            stage = "edit_preservation"
            edit_ok, protected_ok, eval_notes = case.evaluate(final_ir)
            notes.extend(eval_notes)
            row["edit_preserved"] = edit_ok
            row["protected_behavior_preserved"] = protected_ok
            row["unintended_changes_detected"] = not protected_ok
        row["post_overall_valid"] = bool(row["post_det_valid"] and row["post_agentic_valid"])
        row["hitl_success"] = bool(row["edit_applied"] and row["post_overall_valid"] and row["regenerated_puml"] and row["edit_preserved"] and row["protected_behavior_preserved"])
    except Exception as e:
        row["failure_stage"] = stage
        notes.append(f"ERROR: {e}")
    if not row.get("failure_stage"):
        row["failure_stage"] = _infer_failure_stage(row)
    row["notes"] = " | ".join(str(n) for n in notes if str(n).strip())
    return row


def _summary_for_mode(rows: List[Dict[str, Any]], mode: str) -> Dict[str, Any]:
    selected = [r for r in rows if r.get("mode") == mode]
    n = len(selected)
    def count(key: str) -> int:
        return sum(1 for r in selected if bool(r.get(key)))
    return {
        "tests": n,
        "baseline_completed": count("baseline_completed"),
        "edit_applied": count("edit_applied"),
        "post_det_valid": count("post_det_valid"),
        "post_agentic_valid": count("post_agentic_valid"),
        "post_overall_valid": count("post_overall_valid"),
        "regenerated_puml": count("regenerated_puml"),
        "edit_preserved": count("edit_preserved"),
        "protected_behavior_preserved": count("protected_behavior_preserved"),
        "unintended_changes_detected": sum(1 for r in selected if r.get("unintended_changes_detected") is True),
        "hitl_success": count("hitl_success"),
        "hitl_success_rate": None if n == 0 else round(count("hitl_success") / n, 4),
        "failure_stages": _failure_stage_counts(selected),
    }


def _summary_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for section, payload in summary.items():
        if not isinstance(payload, dict):
            continue
        for k, v in payload.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                rows.append({"section": section, "metric": k, "value": v})
    return rows


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(out)


def _write_report(path: Path, rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    manual = summary["manual_puml"]
    agent = summary["agentic_nl_edit"]
    overall = summary["overall"]
    lines = [
        "# HITL Edit Metrics Report",
        "",
        "This report evaluates two human-in-the-loop edit modes:",
        "",
        "1. **Manual PlantUML edit path**: a deterministic scripted edit is rendered as an edited `.puml` artifact and passed through the existing round-trip parser/validator/regenerator.",
        "2. **Agentic NL edit path**: a natural-language change request is sent through the existing edit-agent pipeline.",
        "",
        "A test is counted as a HITL success only when the edit is applied, the final artifact is deterministic-valid and Layer-5-valid, regenerated PlantUML exists, the requested edit is preserved, and protected baseline behavior remains present.",
        "",
        "## Summary",
        "",
        _markdown_table(
            ["Metric", "Manual PlantUML", "Agentic NL Edit", "Overall"],
            [
                ["Tests", manual["tests"], agent["tests"], overall["tests"]],
                ["Post-edit overall valid", f'{manual["post_overall_valid"]}/{manual["tests"]}', f'{agent["post_overall_valid"]}/{agent["tests"]}', f'{overall["post_overall_valid"]}/{overall["tests"]}'],
                ["Regenerated PlantUML", f'{manual["regenerated_puml"]}/{manual["tests"]}', f'{agent["regenerated_puml"]}/{agent["tests"]}', f'{overall["regenerated_puml"]}/{overall["tests"]}'],
                ["Intended edit preserved", f'{manual["edit_preserved"]}/{manual["tests"]}', f'{agent["edit_preserved"]}/{agent["tests"]}', f'{overall["edit_preserved"]}/{overall["tests"]}'],
                ["Protected behavior preserved", f'{manual["protected_behavior_preserved"]}/{manual["tests"]}', f'{agent["protected_behavior_preserved"]}/{agent["tests"]}', f'{overall["protected_behavior_preserved"]}/{overall["tests"]}'],
                ["Unintended changes detected", manual["unintended_changes_detected"], agent["unintended_changes_detected"], overall["unintended_changes_detected"]],
                ["HITL success rate", _pct(manual["hitl_success"], manual["tests"]), _pct(agent["hitl_success"], agent["tests"]), _pct(overall["hitl_success"], overall["tests"])],
            ],
        ),
        "",
        "## Failure stage counts",
        "",
        _markdown_table(
            ["Stage", "Manual PlantUML", "Agentic NL Edit", "Overall"],
            [
                [
                    stage,
                    manual.get("failure_stages", {}).get(stage, 0),
                    agent.get("failure_stages", {}).get(stage, 0),
                    overall.get("failure_stages", {}).get(stage, 0),
                ]
                for stage in sorted(set(manual.get("failure_stages", {})) | set(agent.get("failure_stages", {})) | set(overall.get("failure_stages", {})))
            ],
        ),
        "",
        "## Per-test results",
        "",
        _markdown_table(
            ["Test", "Mode", "Edit Type", "Failure Stage", "Overall Valid", "Edit Preserved", "Protected Behavior", "Success", "Notes"],
            [
                [
                    r.get("case_id", ""),
                    r.get("mode", ""),
                    r.get("edit_type", ""),
                    r.get("failure_stage", ""),
                    r.get("post_overall_valid", ""),
                    r.get("edit_preserved", ""),
                    r.get("protected_behavior_preserved", ""),
                    r.get("hitl_success", ""),
                    str(r.get("notes", ""))[:160].replace("|", "/"),
                ]
                for r in rows
            ],
        ),
        "",
    ]
    write_text(path, "\n".join(lines))


def run_hitl_metrics(
    *,
    out_dir: Path,
    settings: Settings,
    use_mock: bool = False,
    baseline_max_repairs: int = 1,
    agent_max_repairs: int = 1,
    limit: Optional[int] = None,
    include_manual: bool = True,
    include_agent: bool = True,
    clean: bool = False,
) -> Dict[str, Path]:
    """Run paired HITL edit tests over direct PlantUML and agentic NL edit paths."""
    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    cases = list(DEFAULT_HITL_CASES)
    if limit is not None:
        cases = cases[: max(0, int(limit))]

    rows: List[Dict[str, Any]] = []
    for case in cases:
        if include_manual:
            rows.append(
                _run_manual_case(
                    case=case,
                    runs_dir=runs_dir,
                    settings=settings,
                    use_mock=use_mock,
                    baseline_max_repairs=baseline_max_repairs,
                )
            )
        if include_agent:
            rows.append(
                _run_agent_case(
                    case=case,
                    runs_dir=runs_dir,
                    settings=settings,
                    use_mock=use_mock,
                    baseline_max_repairs=baseline_max_repairs,
                    agent_max_repairs=agent_max_repairs,
                )
            )

    manual_summary = _summary_for_mode(rows, "manual_puml")
    agent_summary = _summary_for_mode(rows, "agentic_nl_edit")
    overall_rows = rows
    def count_all(key: str) -> int:
        return sum(1 for r in overall_rows if bool(r.get(key)))
    n_total = len(overall_rows)
    overall = {
        "tests": n_total,
        "baseline_completed": count_all("baseline_completed"),
        "edit_applied": count_all("edit_applied"),
        "post_det_valid": count_all("post_det_valid"),
        "post_agentic_valid": count_all("post_agentic_valid"),
        "post_overall_valid": count_all("post_overall_valid"),
        "regenerated_puml": count_all("regenerated_puml"),
        "edit_preserved": count_all("edit_preserved"),
        "protected_behavior_preserved": count_all("protected_behavior_preserved"),
        "unintended_changes_detected": sum(1 for r in overall_rows if r.get("unintended_changes_detected") is True),
        "hitl_success": count_all("hitl_success"),
        "hitl_success_rate": None if n_total == 0 else round(count_all("hitl_success") / n_total, 4),
        "failure_stages": _failure_stage_counts(overall_rows),
    }
    summary: Dict[str, Any] = {
        "config": {
            "cases": len(cases),
            "include_manual": include_manual,
            "include_agent": include_agent,
            "use_mock": use_mock,
            "baseline_max_repairs": baseline_max_repairs,
            "agent_max_repairs": agent_max_repairs,
        },
        "manual_puml": manual_summary,
        "agentic_nl_edit": agent_summary,
        "overall": overall,
    }

    results_csv = out_dir / "hitl_results.csv"
    summary_csv = out_dir / "hitl_summary.csv"
    summary_json = out_dir / "hitl_summary.json"
    report_md = out_dir / "report.md"
    _write_csv(results_csv, rows)
    _write_csv(summary_csv, _summary_rows(summary))
    write_json(summary_json, summary)
    _write_report(report_md, rows, summary)

    return {
        "results_csv": results_csv,
        "summary_csv": summary_csv,
        "summary_json": summary_json,
        "report_md": report_md,
        "runs_dir": runs_dir,
    }

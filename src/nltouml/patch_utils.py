from __future__ import annotations

from typing import Any, Dict, List

ALLOWED_PATCH_OPS = {
    "set_state_label",
    "set_initial",
    "add_state",
    "remove_state",
    "add_transition",
    "remove_transition",
    "update_transition",
}


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_expr_shape(expr: Any, path: str, issues: List[str]) -> None:
    if not isinstance(expr, dict):
        issues.append(f"{path} must be an expression object, got {type(expr).__name__}.")
        return
    if "ref" in expr:
        ref = expr.get("ref")
        if not isinstance(ref, dict):
            issues.append(f"{path}.ref must be an object.")
            return
        if not _is_non_empty_str(ref.get("device")):
            issues.append(f"{path}.ref.device must be a non-empty string.")
        if not _is_non_empty_str(ref.get("path")):
            issues.append(f"{path}.ref.path must be a non-empty string.")
        return
    if "lit" in expr:
        lit = expr.get("lit")
        if not isinstance(lit, dict):
            issues.append(f"{path}.lit must be an object.")
            return
        if not any(k in lit for k in ("string", "number", "bool")):
            issues.append(f"{path}.lit must contain one of string, number, or bool.")
        return

    op = expr.get("op")
    args = expr.get("args")
    if not _is_non_empty_str(op):
        issues.append(f"{path}.op must be a non-empty string.")
        return
    if not isinstance(args, list):
        issues.append(f"{path}.args must be a list.")
        return
    for idx, arg in enumerate(args):
        _validate_expr_shape(arg, f"{path}.args[{idx}]", issues)


def _validate_trigger_shape(trigger: Any, path: str, issues: List[str]) -> None:
    if not isinstance(trigger, dict):
        issues.append(f"{path} must be an object, got {type(trigger).__name__}.")
        return
    t = trigger.get("type")
    if _is_non_empty_str(t):
        t = str(t).strip()
    else:
        t = None

    if t in {"becomes", "changes"}:
        ref = trigger.get("ref")
        if isinstance(ref, dict):
            if not _is_non_empty_str(ref.get("device")):
                issues.append(f"{path}.ref.device must be a non-empty string.")
            if not _is_non_empty_str(ref.get("path")):
                issues.append(f"{path}.ref.path must be a non-empty string.")
        else:
            dev = trigger.get("device") or trigger.get("deviceId") or trigger.get("device_id")
            attr = trigger.get("path") or trigger.get("attribute") or trigger.get("attr") or trigger.get("property")
            if not _is_non_empty_str(dev):
                issues.append(f"{path} must include ref.device or device/deviceId for {t} trigger.")
            if not _is_non_empty_str(attr):
                issues.append(f"{path} must include ref.path or attribute/property for {t} trigger.")
        return

    if t == "schedule":
        if not any(_is_non_empty_str(trigger.get(k)) for k in ("cron", "schedule", "time", "at")):
            issues.append(f"{path} schedule trigger must include cron/time-like string.")
        return

    if t == "after":
        if not isinstance(trigger.get("seconds"), int) and not isinstance(trigger.get("duration"), (int, float)):
            issues.append(f"{path} after trigger must include integer seconds or numeric duration.")
        return

    if t is None and any(k in trigger for k in ("seconds", "duration")):
        return

    issues.append(f"{path} has unsupported trigger type '{trigger.get('type')}'.")


def _validate_action_shape(action: Any, path: str, issues: List[str]) -> None:
    if not isinstance(action, dict):
        issues.append(f"{path} must be an object, got {type(action).__name__}.")
        return
    t = action.get("type")
    if _is_non_empty_str(t):
        t = str(t).strip()
    else:
        t = None

    device = action.get("device") or action.get("deviceId") or action.get("device_id")
    command = action.get("command")
    if t == "command" or (t is None and _is_non_empty_str(device) and _is_non_empty_str(command)):
        if not _is_non_empty_str(device):
            issues.append(f"{path} command action must include device or deviceId.")
        if not _is_non_empty_str(command):
            issues.append(f"{path} command action must include a non-empty command string.")
        args = action.get("args")
        if args is not None and not isinstance(args, list):
            issues.append(f"{path}.args must be a list when provided.")
        return

    if t == "delay":
        if not isinstance(action.get("seconds"), int) and not isinstance(action.get("duration"), (int, float)):
            issues.append(f"{path} delay action must include integer seconds or numeric duration.")
        return

    if t == "notify":
        if not any(_is_non_empty_str(action.get(k)) for k in ("message", "text", "msg")):
            issues.append(f"{path} notify action must include a message/text string.")
        return

    issues.append(f"{path} has unsupported action type '{action.get('type')}'.")


def _validate_transition_payload(edit: Dict[str, Any], idx: int, issues: List[str]) -> None:
    if "guard" in edit:
        _validate_expr_shape(edit.get("guard"), f"Edit #{idx}.guard", issues)
    if "triggers" in edit:
        triggers = edit.get("triggers")
        if not isinstance(triggers, list):
            issues.append(f"Edit #{idx}.triggers must be a list when provided.")
        else:
            for j, trig in enumerate(triggers):
                _validate_trigger_shape(trig, f"Edit #{idx}.triggers[{j}]", issues)
    if "actions" in edit:
        actions = edit.get("actions")
        if not isinstance(actions, list):
            issues.append(f"Edit #{idx}.actions must be a list when provided.")
        else:
            for j, action in enumerate(actions):
                _validate_action_shape(action, f"Edit #{idx}.actions[{j}]", issues)


def validate_patch_structure(patch: Any) -> Dict[str, Any]:
    """Validate the high-level structure of an LLM patch before apply-time.

    The validator stays permissive about near-miss canonical shapes that normalize later
    (for example deviceId vs device), but it rejects the brittle cases that caused refine
    failures: missing ops, unsupported ops, non-object guard payloads, and malformed nested
    trigger/action payloads.
    """
    issues: List[str] = []
    sanitized_patch: Dict[str, Any] = {"summary": "", "edits": []}

    if not isinstance(patch, dict):
        issues.append(f"Patch root must be an object, got {type(patch).__name__}.")
        return {
            "ok": False,
            "issues": issues,
            "allowed_ops": sorted(ALLOWED_PATCH_OPS),
            "sanitized_patch": sanitized_patch,
            "edit_count": 0,
            "valid_edit_count": 0,
        }

    summary = patch.get("summary", "")
    if summary is None:
        summary = ""
    elif not isinstance(summary, str):
        summary = str(summary)
    sanitized_patch["summary"] = summary

    edits = patch.get("edits", [])
    if edits is None:
        edits = []
    if not isinstance(edits, list):
        issues.append("Patch field 'edits' must be a list.")
        edits = []

    for idx, raw_edit in enumerate(edits):
        if not isinstance(raw_edit, dict):
            issues.append(f"Edit #{idx} must be an object, got {type(raw_edit).__name__}.")
            continue

        edit = dict(raw_edit)
        op = edit.get("op")
        if isinstance(op, str):
            op = op.strip()
            edit["op"] = op

        if not _is_non_empty_str(op):
            issues.append(f"Edit #{idx} is missing a valid non-empty string 'op'.")
            continue

        if op not in ALLOWED_PATCH_OPS:
            issues.append(f"Edit #{idx} has unsupported op '{op}'. Allowed ops: {sorted(ALLOWED_PATCH_OPS)}")
            continue

        if op == "set_state_label":
            if not _is_non_empty_str(edit.get("state_id")):
                issues.append(f"Edit #{idx} set_state_label requires non-empty string state_id.")
            if not isinstance(edit.get("label"), str):
                issues.append(f"Edit #{idx} set_state_label requires string label.")
        elif op in {"set_initial", "add_state", "remove_state"}:
            if not _is_non_empty_str(edit.get("state_id")):
                issues.append(f"Edit #{idx} {op} requires non-empty string state_id.")
        elif op in {"add_transition", "remove_transition", "update_transition"}:
            if not _is_non_empty_str(edit.get("from")):
                issues.append(f"Edit #{idx} {op} requires non-empty string from.")
            if not _is_non_empty_str(edit.get("to")):
                issues.append(f"Edit #{idx} {op} requires non-empty string to.")
            if "index" in edit and not isinstance(edit.get("index"), int):
                issues.append(f"Edit #{idx} {op} index must be an integer when provided.")
            _validate_transition_payload(edit, idx, issues)

        sanitized_patch["edits"].append(edit)

    return {
        "ok": not issues,
        "issues": issues,
        "allowed_ops": sorted(ALLOWED_PATCH_OPS),
        "sanitized_patch": sanitized_patch,
        "edit_count": len(edits),
        "valid_edit_count": len(sanitized_patch["edits"]),
    }


def patch_validation_error_message(report: Dict[str, Any]) -> str:
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    if not issues:
        return "Patch validation failed for an unknown reason."
    return "; ".join(str(issue) for issue in issues)

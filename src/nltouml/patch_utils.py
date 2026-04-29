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


def _coerce_literal_payload(value: Any) -> Dict[str, Any]:
    """Coerce near-miss literal payloads into canonical patch literal shape."""
    if isinstance(value, dict):
        if "string" in value:
            return {"string": "" if value.get("string") is None else str(value.get("string"))}
        if "number" in value:
            n = value.get("number")
            if isinstance(n, (int, float)) and not isinstance(n, bool):
                return {"number": n}
            if isinstance(n, str):
                try:
                    return {"number": float(n) if "." in n else int(n)}
                except ValueError:
                    pass
            return {"string": "" if n is None else str(n)}
        if "bool" in value:
            return {"bool": bool(value.get("bool"))}
        for key in ("int", "integer", "float", "double"):
            if key in value:
                n = value.get(key)
                if isinstance(n, (int, float)) and not isinstance(n, bool):
                    return {"number": int(n) if key in {"int", "integer"} else float(n)}
                return {"string": "" if n is None else str(n)}
        if "value" in value and len(value) == 1:
            return _coerce_literal_payload(value.get("value"))
        if "lit" in value and len(value) == 1:
            return _coerce_literal_payload(value.get("lit"))
        return {"string": str(value)}
    if isinstance(value, bool):
        return {"bool": value}
    if isinstance(value, (int, float)):
        return {"number": value}
    return {"string": "" if value is None else str(value)}


def _coerce_expr_shape(expr: Any) -> Any:
    """Normalize guard expression near-misses before patch validation.

    This accepts common LLM patch variants such as raw primitive literals,
    {"int": 21}, and older boolean shapes like {"all": [...]}.
    """
    if not isinstance(expr, dict):
        return expr

    if "ref" in expr:
        ref = expr.get("ref")
        if isinstance(ref, dict):
            dev = ref.get("device") or ref.get("deviceId") or ref.get("device_id")
            path = ref.get("path") or ref.get("attribute") or ref.get("attr") or ref.get("property") or ref.get("prop")
            if _is_non_empty_str(dev) and _is_non_empty_str(path):
                return {"ref": {"device": dev, "path": path}}
        return expr

    if "lit" in expr:
        return {"lit": _coerce_literal_payload(expr.get("lit"))}

    if "literal" in expr and len(expr) == 1:
        return {"lit": _coerce_literal_payload(expr.get("literal"))}

    for key, op in (("all", "and"), ("and", "and"), ("any", "or"), ("or", "or")):
        if key in expr and isinstance(expr.get(key), list):
            return {"op": op, "args": [_coerce_expr_shape(a) for a in expr.get(key, [])]}

    if "not" in expr:
        return {"op": "not", "args": [_coerce_expr_shape(expr.get("not"))]}

    # Condition shortcut produced by some edit-agent outputs.
    dev = expr.get("device") or expr.get("deviceId") or expr.get("device_id")
    path = expr.get("path") or expr.get("attribute") or expr.get("attr") or expr.get("property") or expr.get("prop")
    if _is_non_empty_str(dev) and _is_non_empty_str(path):
        raw_value = expr.get("value")
        if raw_value is None:
            raw_value = expr.get("equals") or expr.get("state") or expr.get("expected")
        if raw_value is not None:
            op_raw = expr.get("op") or expr.get("operator") or expr.get("comparison") or "eq"
            op_map = {"==": "eq", "equals": "eq", "is": "eq", "eq": "eq", "!=": "neq", "not_equals": "neq", "is_not": "neq", "neq": "neq", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
            op = op_map.get(str(op_raw).strip().lower(), "eq")
            return {"op": op, "args": [{"ref": {"device": dev, "path": path}}, {"lit": _coerce_literal_payload(raw_value)}]}

    if "op" in expr:
        op = expr.get("op")
        op_map = {"&&": "and", "||": "or", "==": "eq", "!=": "neq", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte", "equals": "eq", "not_equals": "neq"}
        if isinstance(op, str):
            op = op_map.get(op.strip().lower(), op.strip().lower())
        args = expr.get("args") if isinstance(expr.get("args"), list) else []
        return {"op": op, "args": [_coerce_expr_shape(a) for a in args]}

    return expr


def _validate_expr_shape(expr: Any, path: str, issues: List[str]) -> None:
    if isinstance(expr, dict):
        coerced = _coerce_expr_shape(expr)
        if isinstance(coerced, dict) and coerced is not expr:
            expr.clear()
            expr.update(coerced)
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
        coerced_guard = _coerce_expr_shape(edit.get("guard"))
        if isinstance(coerced_guard, dict):
            edit["guard"] = coerced_guard
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

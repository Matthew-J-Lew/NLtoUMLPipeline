from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .io_utils import write_json
from .normalize import coerce_ir_shape, normalize_ir
from .patch_utils import validate_patch_structure


def _check_schedule_normalization() -> Dict[str, Any]:
    device_catalog = {"devices": [], "globals": []}
    ir = {
        "version": "0.1",
        "devices": [],
        "stateMachine": {
            "initial": "Idle",
            "states": [{"id": "Idle"}, {"id": "Night"}],
            "transitions": [
                {
                    "from": "Idle",
                    "to": "Night",
                    "triggers": [{"type": "schedule", "time": "22:00"}],
                    "actions": [],
                }
            ],
        },
    }
    out = normalize_ir(coerce_ir_shape(ir, device_catalog))
    trig = out["stateMachine"]["transitions"][0]["triggers"][0]
    passed = trig.get("type") == "schedule" and trig.get("cron") == "0 22 * * *"
    return {
        "name": "schedule_time_to_cron",
        "passed": passed,
        "details": trig,
    }


def _check_condition_action_rescue() -> Dict[str, Any]:
    device_catalog = {
        "devices": [{"id": "presence_user", "kind": "presenceSensor"}],
        "globals": [],
    }
    ir = {
        "version": "0.1",
        "devices": [{"id": "presence_user", "kind": "presenceSensor"}],
        "stateMachine": {
            "initial": "Idle",
            "states": [{"id": "Idle"}, {"id": "Armed"}],
            "transitions": [
                {
                    "from": "Idle",
                    "to": "Armed",
                    "triggers": [],
                    "actions": [
                        {
                            "type": "command",
                            "device": "presence_user",
                            "property": "presence",
                            "value": "not present",
                            "operator": "equals",
                        }
                    ],
                }
            ],
        },
    }
    out = normalize_ir(coerce_ir_shape(ir, device_catalog))
    tr = out["stateMachine"]["transitions"][0]
    guard = tr.get("guard")
    passed = isinstance(guard, dict) and tr.get("actions") == []
    return {
        "name": "condition_like_action_to_guard",
        "passed": passed,
        "details": {"guard": guard, "actions": tr.get("actions")},
    }


def _check_guard_string_rescue() -> Dict[str, Any]:
    device_catalog = {
        "devices": [
            {"id": "lock_front", "kind": "lock"},
            {"id": "door_front", "kind": "contactSensor"},
        ],
        "globals": [{"id": "location", "kind": "location"}],
    }
    ir = {
        "version": "0.1",
        "devices": [
            {"id": "lock_front", "kind": "lock"},
            {"id": "door_front", "kind": "contactSensor"},
            {"id": "location", "kind": "location"},
        ],
        "stateMachine": {
            "initial": "Idle",
            "states": [{"id": "Idle"}, {"id": "Active"}],
            "transitions": [
                {
                    "from": "Idle",
                    "to": "Active",
                    "guard": "door_front.contact == 'closed' && lock_front.lock == 'locked'",
                    "actions": [],
                }
            ],
        },
    }
    out = normalize_ir(coerce_ir_shape(ir, device_catalog))
    guard = out["stateMachine"]["transitions"][0].get("guard")
    passed = isinstance(guard, dict) and guard.get("op") == "and"
    return {
        "name": "guard_string_to_expr",
        "passed": passed,
        "details": guard,
    }


def _check_deviceid_action_rescue() -> Dict[str, Any]:
    device_catalog = {
        "devices": [{"id": "light_hall", "kind": "switch"}],
        "globals": [],
    }
    ir = {
        "version": "0.1",
        "devices": [{"id": "light_hall", "kind": "switch"}],
        "stateMachine": {
            "initial": "Idle",
            "states": [{"id": "Idle"}, {"id": "Lit"}],
            "transitions": [
                {
                    "from": "Idle",
                    "to": "Lit",
                    "triggers": [],
                    "actions": [{"deviceId": "light_hall", "command": "on"}],
                }
            ],
        },
    }
    out = normalize_ir(coerce_ir_shape(ir, device_catalog))
    action = out["stateMachine"]["transitions"][0]["actions"][0]
    passed = action.get("type") == "command" and action.get("device") == "light_hall"
    return {
        "name": "deviceid_command_action_to_canonical",
        "passed": passed,
        "details": action,
    }




def _check_time_guard_to_schedule_trigger() -> Dict[str, Any]:
    device_catalog = {
        "devices": [
            {"id": "door_front", "kind": "contactSensor"},
            {"id": "lock_front", "kind": "lock"},
        ],
        "globals": [],
    }
    ir = {
        "version": "0.1",
        "devices": device_catalog["devices"],
        "stateMachine": {
            "initial": "Idle",
            "states": [{"id": "Idle"}, {"id": "Secure"}],
            "transitions": [
                {
                    "from": "Idle",
                    "to": "Secure",
                    "triggers": [
                        {
                            "type": "becomes",
                            "ref": {"device": "door_front", "path": "contact"},
                            "value": {"string": "closed"},
                        }
                    ],
                    "guard": "time >= 22 || time < 6",
                    "actions": [{"type": "command", "device": "lock_front", "command": "lock"}],
                }
            ],
        },
    }
    out = normalize_ir(coerce_ir_shape(ir, device_catalog))
    tr = out["stateMachine"]["transitions"][0]
    schedule_triggers = [tg for tg in tr.get("triggers", []) if isinstance(tg, dict) and tg.get("type") == "schedule"]
    passed = "guard" not in tr and any(tg.get("cron") == "0 22 * * *" for tg in schedule_triggers)
    return {
        "name": "time_guard_to_schedule_trigger",
        "passed": passed,
        "details": tr,
    }

def _check_patch_validation() -> Dict[str, Any]:
    report = validate_patch_structure({"summary": "bad", "edits": [{"state_id": "Idle"}]})
    return {
        "name": "patch_validation_rejects_missing_op",
        "passed": not bool(report.get("ok", False)),
        "details": report,
    }


def _check_patch_validation_rejects_bad_guard_payload() -> Dict[str, Any]:
    patch = {
        "summary": "bad guard payload",
        "edits": [
            {
                "op": "update_transition",
                "from": "Idle",
                "to": "Lit",
                "guard": {"op": "and", "args": [True, {"ref": {"device": "lock_front", "path": "lock"}}]},
            }
        ],
    }
    report = validate_patch_structure(patch)
    return {
        "name": "patch_validation_rejects_nonexpr_guard_args",
        "passed": not bool(report.get("ok", False)),
        "details": report,
    }


def run_regression_checks(out_path: Optional[Path] = None) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = [
        _check_schedule_normalization(),
        _check_condition_action_rescue(),
        _check_guard_string_rescue(),
        _check_deviceid_action_rescue(),
        _check_time_guard_to_schedule_trigger(),
        _check_patch_validation(),
        _check_patch_validation_rejects_bad_guard_payload(),
    ]
    summary = {
        "ok": all(bool(c.get("passed", False)) for c in checks),
        "total": len(checks),
        "passed": sum(1 for c in checks if c.get("passed")),
        "checks": checks,
    }
    if out_path is not None:
        write_json(out_path, summary)
    return summary

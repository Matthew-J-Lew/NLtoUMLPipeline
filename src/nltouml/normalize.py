from __future__ import annotations

from typing import Any, Dict


def _to_literal(v: Any) -> Dict[str, Any]:
    """Convert a primitive into an IR literal object."""
    if isinstance(v, bool):
        return {"bool": v}
    if isinstance(v, (int, float)):
        return {"number": float(v) if isinstance(v, float) else v}
    return {"string": "" if v is None else str(v)}


def _unit_seconds(duration: Any, unit: Any) -> Any:
    """Convert duration+unit into seconds if possible."""
    if not isinstance(duration, (int, float)):
        return None
    if not isinstance(unit, str):
        return int(duration)
    u = unit.strip().lower()
    if u in ("s", "sec", "secs", "second", "seconds"):
        return int(duration)
    if u in ("m", "min", "mins", "minute", "minutes"):
        return int(duration * 60)
    if u in ("h", "hr", "hrs", "hour", "hours"):
        return int(duration * 3600)
    return int(duration)


def coerce_ir_shape(ir: Dict[str, Any], device_catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce common "almost-IR" shapes into the canonical IR schema.

    LLMs often produce plausible JSON with slightly wrong key names (deviceId vs device,
    states.name vs states.id, notify.text vs notify.message, etc.).

    This function performs *lossless* renames/mappings so validation + PlantUML generation
    can succeed more often without needing an LLM repair round-trip.
    """

    # Build quick lookup: id -> kind
    id_to_kind: Dict[str, str] = {}
    for d in device_catalog.get("devices", []) or []:
        if isinstance(d, dict) and "id" in d and "kind" in d:
            id_to_kind[str(d["id"])] = str(d["kind"])
    for d in device_catalog.get("globals", []) or []:
        if isinstance(d, dict) and "id" in d and "kind" in d:
            id_to_kind[str(d["id"])] = str(d["kind"])

    # --- devices ---
    devs = ir.get("devices")
    if isinstance(devs, list):
        # If devices are just strings, expand to objects
        if devs and all(isinstance(x, str) for x in devs):
            ir["devices"] = [
                {"id": x, "kind": id_to_kind.get(x, "unknown")}
                for x in devs
            ]
        # If devices are objects missing 'id', try to repair
        elif devs and all(isinstance(x, dict) for x in devs):
            for d in devs:
                if "id" not in d and "name" in d:
                    d["id"] = d.pop("name")
                if "kind" not in d and isinstance(d.get("id"), str):
                    d["kind"] = id_to_kind.get(d["id"], d.get("kind", "unknown"))

    sm = ir.get("stateMachine")
    if not isinstance(sm, dict):
        return ir

    # --- states ---
    states = sm.get("states")
    if isinstance(states, list):
        for st in states:
            if not isinstance(st, dict):
                continue
            if "id" not in st and "name" in st:
                st["id"] = st.pop("name")
            # Some models include both id+name; keep id as canonical
            if "name" in st and "id" in st and st["name"] == st["id"]:
                st.pop("name", None)

    # --- transitions (triggers/actions) ---
    transitions = sm.get("transitions")
    if isinstance(transitions, list):
        for tr in transitions:
            if not isinstance(tr, dict):
                continue

            # triggers
            triggers = tr.get("triggers")
            if isinstance(triggers, list):
                for t in triggers:
                    if not isinstance(t, dict):
                        continue

                    # Canonical trigger schema:
                    #   { type: 'becomes'|'changes'|'schedule', ref:{device,path}, value?:literal, cron?:string }
                    # We coerce common LLM variants into this form.
                    #
                    # Common variants observed:
                    #   {device, attribute, becomes:'active'}
                    #   {deviceId, attribute, event:'becomes', value:'active'}
                    #   {deviceId, attribute, type:'becomes', value:{string:'active'}}

                    dev = t.get("device") or t.get("deviceId") or t.get("device_id")
                    attr = t.get("path") or t.get("attribute") or t.get("attr")
                    typ = t.get("type") or t.get("condition") or t.get("event")

                    # Support timer/after triggers in a few common shapes:
                    #   {type:'after', seconds:30}
                    #   {type:'timer', duration:30, unit:'seconds'}
                    #   {seconds:30} (rare)
                    #   {type:'schedule', seconds:30} (LLM confusion; treat as after)
                    raw_typ = typ.strip().lower() if isinstance(typ, str) else None
                    if raw_typ in ("after", "timer", "delay") or (
                        raw_typ == "schedule" and "cron" not in t and "seconds" in t
                    ) or (
                        raw_typ is None and ("seconds" in t or "duration" in t)
                    ):
                        secs = None
                        if isinstance(t.get("seconds"), (int, float)):
                            secs = int(t["seconds"])
                        elif "duration" in t:
                            secs = _unit_seconds(t.get("duration"), t.get("unit"))
                        if secs is not None:
                            t.clear()
                            t.update({"type": "after", "seconds": int(secs)})
                            continue

                    # Special case: {device, attribute, becomes: 'active'}
                    if typ is None and "becomes" in t:
                        typ = "becomes"

                    # Special case: schedule-ish
                    if typ is None and any(k in t for k in ("cron", "schedule", "time")):
                        typ = "schedule"

                    if isinstance(typ, str):
                        typ = typ.strip()

                    if isinstance(dev, str) and isinstance(attr, str) and isinstance(typ, str):
                        new_t: Dict[str, Any] = {
                            "type": typ,
                            "ref": {"device": dev, "path": attr},
                        }

                        if typ == "becomes":
                            # value may be under 'value' or under 'becomes'
                            v = t.get("value")
                            if v is None and "becomes" in t:
                                v = t.get("becomes")
                            if isinstance(v, dict) and any(k in v for k in ("string", "number", "bool")):
                                new_t["value"] = v
                            else:
                                new_t["value"] = _to_literal(v)

                        elif typ == "schedule":
                            cron = t.get("cron") or t.get("schedule") or t.get("time")
                            if isinstance(cron, str):
                                new_t["cron"] = cron
                            else:
                                # If the model produced "schedule" without a cron, but did include a duration,
                                # treat it as an "after" timer trigger.
                                secs = None
                                if isinstance(t.get("seconds"), (int, float)):
                                    secs = int(t["seconds"])
                                elif "duration" in t:
                                    secs = _unit_seconds(t.get("duration"), t.get("unit"))
                                if secs is not None:
                                    new_t = {"type": "after", "seconds": int(secs)}

                        # Replace in-place
                        t.clear()
                        t.update(new_t)

            # actions
            actions = tr.get("actions")
            if isinstance(actions, list):
                for a in actions:
                    if not isinstance(a, dict):
                        continue

                    # Canonical action schema:
                    #   command: {type:'command', device, command, args?:literal[]}
                    #   delay:   {type:'delay', seconds:int}
                    #   notify:  {type:'notify', message:str}

                    # Variant: {device:'x', command:'on'} (missing type)
                    if "type" not in a and isinstance(a.get("device"), str) and isinstance(a.get("command"), str):
                        a["type"] = "command"

                    # Variant: {action:'delay', seconds:120}
                    if "type" not in a and a.get("action") == "delay":
                        a["type"] = "delay"

                    # Variant: {type:'delay', duration:30, unit:'seconds'}
                    if a.get("type") == "delay" and "seconds" not in a:
                        secs = None
                        if "duration" in a:
                            secs = _unit_seconds(a.get("duration"), a.get("unit"))
                        if secs is None and "seconds" in a:
                            secs = a.get("seconds")
                        if secs is not None:
                            a.pop("duration", None)
                            a.pop("unit", None)
                            a["seconds"] = int(secs)

                    # Normalize delay payload: move seconds to top-level and drop 'action'
                    if a.get("type") == "delay":
                        if "seconds" not in a and isinstance(a.get("seconds"), (int, float)):
                            a["seconds"] = int(a["seconds"])
                        a.pop("action", None)

                    # Coerce command action fields
                    if a.get("type") == "command":
                        if "device" not in a:
                            a["device"] = a.pop("deviceId", None) or a.get("device")
                        # some models use 'device' but put an object - coerce to string id if possible
                        if isinstance(a.get("device"), dict) and "id" in a["device"]:
                            a["device"] = a["device"]["id"]

                        # Variant: {parameters:{mode:'Away'}} for setMode
                        if "args" not in a and isinstance(a.get("parameters"), dict):
                            params = a.get("parameters") or {}
                            if isinstance(params, dict) and params:
                                if "mode" in params:
                                    a["args"] = [{"string": str(params["mode"])}]
                                elif len(params) == 1:
                                    (_, pv) = next(iter(params.items()))
                                    a["args"] = [_to_literal(pv)]
                            a.pop("parameters", None)

                        # If args are primitives, convert to literal objects
                        if isinstance(a.get("args"), list):
                            new_args = []
                            for av in a["args"]:
                                if isinstance(av, dict) and any(k in av for k in ("string", "number", "bool")):
                                    new_args.append(av)
                                else:
                                    new_args.append(_to_literal(av))
                            a["args"] = new_args

                        # Device-specific command aliases (reduce common NL mismatch)
                        dev_id = a.get("device")
                        cmd = a.get("command")
                        if isinstance(dev_id, str) and isinstance(cmd, str):
                            kind = id_to_kind.get(dev_id)
                            c = cmd.strip().lower()
                            # People say "turn on the alarm"; our alarm kind uses siren/strobe/both/off.
                            if kind == "alarm" and c == "on":
                                a["command"] = "siren"
                            # Some models output 'deactivate' etc.
                            if kind == "alarm" and c in ("deactivate", "disable"):
                                a["command"] = "off"
                    if a.get("type") == "notify":
                        if "message" not in a:
                            if "text" in a:
                                a["message"] = a.pop("text")
                            elif "msg" in a:
                                a["message"] = a.pop("msg")
                            else:
                                # Guarantee schema-required field.
                                a["message"] = ""

    return ir


# Simple synonym normalization to reduce LLM errors.
# This runs on IR JSON before strict validation.
VALUE_SYNONYMS: Dict[str, str] = {
    # motion
    "detected": "active",
    "motion": "active",
    "movement": "active",
    "no motion": "inactive",
    "no_motion": "inactive",

    # contact
    "opened": "open",
    "shut": "closed",

    # presence
    "home": "present",
    "away": "not present",
    "not_home": "not present",

    # switch
    "true": "on",
    "false": "off",
}


def _normalize_literal(lit: Dict[str, Any]) -> Dict[str, Any]:
    if "string" in lit:
        s = str(lit["string"]).strip()
        s_lower = s.lower()
        if s_lower in VALUE_SYNONYMS:
            return {"string": VALUE_SYNONYMS[s_lower]}
        return {"string": s}
    return lit


def normalize_ir(ir: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow-normalized copy of IR (in-place modifications for simplicity)."""
    def walk_expr(expr: Any) -> None:
        if isinstance(expr, dict):
            if "lit" in expr and isinstance(expr["lit"], dict):
                expr["lit"] = _normalize_literal(expr["lit"])
            if "op" in expr and "args" in expr:
                for a in expr.get("args", []):
                    walk_expr(a)

    def walk_triggers(triggers: Any) -> None:
        if not isinstance(triggers, list):
            return
        for t in triggers:
            if isinstance(t, dict) and t.get("type") == "becomes" and isinstance(t.get("value"), dict):
                t["value"] = _normalize_literal(t["value"])

    def walk_actions(actions: Any) -> None:
        if not isinstance(actions, list):
            return
        for a in actions:
            if not isinstance(a, dict):
                continue
            if a.get("type") == "command":
                # normalize common command aliases
                cmd = a.get("command")
                if isinstance(cmd, str):
                    c = cmd.strip().lower()
                    if c in ("turn_on", "turnon", "on"):
                        a["command"] = "on"
                    elif c in ("turn_off", "turnoff", "off"):
                        a["command"] = "off"

    sm = ir.get("stateMachine", {})
    for tr in sm.get("transitions", []) if isinstance(sm, dict) else []:
        if isinstance(tr, dict):
            walk_triggers(tr.get("triggers"))
            if "guard" in tr:
                walk_expr(tr["guard"])
            walk_actions(tr.get("actions"))

    # also normalize invariants
    for st in sm.get("states", []) if isinstance(sm, dict) else []:
        if isinstance(st, dict):
            inv = st.get("invariants")
            if isinstance(inv, list):
                for e in inv:
                    walk_expr(e)

    return ir

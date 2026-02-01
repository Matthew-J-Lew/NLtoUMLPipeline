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
    # Some LLM outputs omit the top-level devices list entirely, or only reference devices
    # inside triggers/actions. We infer a minimal devices[] list from any references we can find.
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

    # If devices are missing or empty, infer them from references.
    if not isinstance(ir.get("devices"), list) or not ir.get("devices"):
        inferred: Dict[str, str] = {}
        sm0 = ir.get("stateMachine")
        if isinstance(sm0, dict):
            trans0 = sm0.get("transitions")
            if isinstance(trans0, list):
                for tr0 in trans0:
                    if not isinstance(tr0, dict):
                        continue
                    # triggers may appear as 'trigger' (singular) or 'triggers' (list)
                    trig_any = tr0.get("triggers")
                    if isinstance(trig_any, dict):
                        trig_any = [trig_any]
                    if not isinstance(trig_any, list) and isinstance(tr0.get("trigger"), dict):
                        trig_any = [tr0.get("trigger")]
                    if isinstance(trig_any, list):
                        for t0 in trig_any:
                            if isinstance(t0, dict):
                                dev_id = t0.get("device") or t0.get("deviceId") or t0.get("device_id")
                                if isinstance(dev_id, str):
                                    inferred[dev_id] = id_to_kind.get(dev_id, "unknown")

                    act_any = tr0.get("actions")
                    if isinstance(act_any, dict):
                        act_any = [act_any]
                    if not isinstance(act_any, list) and isinstance(tr0.get("action"), dict):
                        act_any = [tr0.get("action")]
                    if isinstance(act_any, list):
                        for a0 in act_any:
                            if isinstance(a0, dict):
                                dev_id = a0.get("device") or a0.get("deviceId") or a0.get("device_id")
                                if isinstance(dev_id, str):
                                    inferred[dev_id] = id_to_kind.get(dev_id, "unknown")

        # Only set devices if we found at least one reference.
        if inferred:
            ir["devices"] = [{"id": did, "kind": kind} for did, kind in sorted(inferred.items())]

    sm = ir.get("stateMachine")
    if not isinstance(sm, dict):
        return ir

    # --- states ---
    states = sm.get("states")
    if isinstance(states, list):
        # Common "almost-IR" variant: states as string names
        if states and all(isinstance(s, str) for s in states):
            sm["states"] = [{"id": s} for s in states]
            states = sm["states"]

        for st in states:
            if not isinstance(st, dict):
                continue
            if "id" not in st and "name" in st:
                st["id"] = st.pop("name")
            # Some models include both id+name; keep id as canonical
            if "name" in st and "id" in st and st["name"] == st["id"]:
                st.pop("name", None)

    # --- initial ---
    # If initial is missing, infer from first state, otherwise use a safe default.
    if "initial" not in sm or not isinstance(sm.get("initial"), str) or not sm.get("initial"):
        first_state_id = None
        sts = sm.get("states")
        if isinstance(sts, list) and sts:
            s0 = sts[0]
            if isinstance(s0, dict) and isinstance(s0.get("id"), str):
                first_state_id = s0.get("id")
        sm["initial"] = first_state_id or "Idle"

    # --- transitions (shape coercion + triggers/actions) ---
    transitions = sm.get("transitions")
    if isinstance(transitions, list):
        # Collect known state ids for light inference.
        state_ids = []
        sts = sm.get("states")
        if isinstance(sts, list):
            for s in sts:
                if isinstance(s, dict) and isinstance(s.get("id"), str):
                    state_ids.append(s["id"])

        for tr in transitions:
            if not isinstance(tr, dict):
                continue

            # Canonical transition keys required by schema: from, to, triggers, actions
            # Common variants: source/target, state/next, trigger/actions singular, etc.
            if "to" not in tr and "target" in tr:
                tr["to"] = tr.pop("target")
            if "to" not in tr and "next" in tr:
                tr["to"] = tr.pop("next")
            if "from" not in tr and "source" in tr:
                tr["from"] = tr.pop("source")
            if "from" not in tr and "state" in tr:
                tr["from"] = tr.pop("state")

            # Wrap singular trigger/action into lists under canonical keys.
            if "triggers" not in tr and isinstance(tr.get("trigger"), dict):
                tr["triggers"] = [tr.pop("trigger")]
            if "actions" not in tr and isinstance(tr.get("action"), dict):
                tr["actions"] = [tr.pop("action")]

            # If triggers/actions are dicts (not lists), wrap them.
            if isinstance(tr.get("triggers"), dict):
                tr["triggers"] = [tr["triggers"]]
            if isinstance(tr.get("actions"), dict):
                tr["actions"] = [tr["actions"]]

            # If from/to missing, try minimal inference to satisfy schema.
            if "from" not in tr or not isinstance(tr.get("from"), str) or not tr.get("from"):
                tr["from"] = sm.get("initial") if isinstance(sm.get("initial"), str) else (state_ids[0] if state_ids else "Idle")
            if "to" not in tr or not isinstance(tr.get("to"), str) or not tr.get("to"):
                # Pick a different state if possible
                fallback_to = None
                for sid in state_ids:
                    if sid != tr.get("from"):
                        fallback_to = sid
                        break
                tr["to"] = fallback_to or tr.get("from")

            # Ensure actions/triggers exist as lists for schema; if missing, create empty lists
            if "triggers" not in tr or not isinstance(tr.get("triggers"), list):
                tr["triggers"] = []
            if "actions" not in tr or not isinstance(tr.get("actions"), list):
                tr["actions"] = []

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

                    # Device/attribute reference can appear in multiple common shapes.
                    # Canonical is: ref:{device:<id>, path:<attr>}
                    ref = t.get("ref")
                    dev = t.get("device") or t.get("deviceId") or t.get("device_id")
                    attr = (
                        t.get("path")
                        or t.get("attribute")
                        or t.get("attr")
                        or t.get("property")
                        or t.get("prop")
                    )
                    if isinstance(ref, dict):
                        dev = dev or ref.get("device") or ref.get("deviceId") or ref.get("device_id")
                        attr = (
                            attr
                            or ref.get("path")
                            or ref.get("attribute")
                            or ref.get("attr")
                            or ref.get("property")
                            or ref.get("prop")
                        )

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

                    # If a type is missing but we have a ref-like payload, infer conservatively.
                    if typ is None and isinstance(dev, str) and isinstance(attr, str):
                        if any(k in t for k in ("value", "equals", "state", "becomes", "val")):
                            typ = "becomes"
                        else:
                            typ = "changes"

                    # Special case: schedule-ish
                    if typ is None and any(k in t for k in ("cron", "schedule", "time")):
                        typ = "schedule"

                    if isinstance(typ, str):
                        typ = typ.strip()

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
                            if v is None:
                                v = t.get("equals") or t.get("state") or t.get("val")
                            if isinstance(v, dict) and any(k in v for k in ("string", "number", "bool")):
                                new_t["value"] = v
                            else:
                                new_t["value"] = _to_literal(v)

                        elif typ == "schedule":
                            cron = t.get("cron") or t.get("schedule") or t.get("time") or t.get("at") or t.get("event")
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
                coerced_actions = []
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
                            # Drop placeholder/no-op commands that otherwise fail catalog validation.
                            c0 = cmd.strip().lower()
                            if c0 in ("none", "noop", "no-op", "do_nothing", "do nothing", "nothing"):
                                continue

                            kind = id_to_kind.get(dev_id)
                            c = c0
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

                    coerced_actions.append(a)

                # Replace list in-place to avoid leaving invalid/no-op actions behind.
                tr["actions"] = coerced_actions

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

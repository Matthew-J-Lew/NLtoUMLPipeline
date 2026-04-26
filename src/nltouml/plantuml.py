from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set


def _escape_puml_string(s: str) -> str:
    # PlantUML strings are quoted with ". Keep escaping minimal and predictable.
    return s.replace("\\", r"\\").replace('"', r'\"')


def _split_identifier_parts(raw: str) -> List[str]:
    if not isinstance(raw, str):
        return []
    text = raw.strip()
    if not text:
        return []
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.replace("-", " ").replace("_", " ")
    return [p for p in text.split() if p]


def _titleize_words(parts: Iterable[str]) -> str:
    return " ".join(str(p).replace("/", " ").title() for p in parts if str(p).strip())


_DEVICE_NOUNS = {
    "light",
    "lock",
    "door",
    "motion",
    "alarm",
    "presence",
    "sensor",
    "switch",
    "thermostat",
    "camera",
    "window",
    "fan",
    "speaker",
    "contact",
}

_MODE_WORDS = {
    "on",
    "off",
    "open",
    "closed",
    "close",
    "locked",
    "unlocked",
    "armed",
    "disarmed",
    "active",
    "inactive",
    "triggered",
    "notify",
    "notification",
    "waiting",
    "ready",
}


def _humanize_device_id(raw: Optional[str]) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return "Unknown Device"
    parts = [p.lower() for p in _split_identifier_parts(raw)]
    if len(parts) == 2 and parts[0] in _DEVICE_NOUNS:
        return _titleize_words([parts[1], parts[0]])
    return _titleize_words(parts)


def _humanize_state_mode(sid: str) -> str:
    words = [w.lower() for w in _split_identifier_parts(sid)]
    if not words:
        return "State"
    if words and words[0] in {"idle", "ready", "monitoring"}:
        return "Ready"
    if words == ["notify"]:
        return "Notification"
    return _titleize_words(words)


def _drop_duplicate_suffix_word(device_name: str, phrase: str) -> str:
    device_parts = [p.lower() for p in _split_identifier_parts(device_name)]
    phrase_parts = [p.lower() for p in _split_identifier_parts(phrase)]
    if device_parts and phrase_parts and phrase_parts[0] == device_parts[-1]:
        phrase_parts = phrase_parts[1:]
    if not phrase_parts:
        return device_name
    return f"{device_name} {_titleize_words(phrase_parts)}"


def _lit_to_str(lit: Dict[str, Any]) -> str:
    if "string" in lit:
        return f"\"{_escape_puml_string(str(lit['string']))}\""
    if "number" in lit:
        return str(lit["number"])
    if "bool" in lit:
        return "true" if lit["bool"] else "false"
    return "?"


def _trigger_to_line(tg: Dict[str, Any]) -> str:
    t = tg.get("type")
    if t == "becomes":
        ref = tg.get("ref", {})
        dev = ref.get("device")
        path = ref.get("path")
        val = tg.get("value", {})
        return f"{dev}.{path} becomes {_lit_to_str(val)}"
    if t == "changes":
        ref = tg.get("ref", {})
        dev = ref.get("device")
        path = ref.get("path")
        return f"{dev}.{path} changes"
    if t == "schedule":
        return f"schedule {tg.get('cron')}"
    if t == "after":
        return f"after {tg.get('seconds')}s"
    return "unknown_trigger"


def _expr_to_str(expr: Dict[str, Any]) -> str:
    if "ref" in expr:
        r = expr["ref"]
        return f"{r.get('device')}.{r.get('path')}"
    if "lit" in expr:
        return _lit_to_str(expr["lit"])
    op = expr.get("op")
    args = expr.get("args", [])
    if not isinstance(args, list):
        args = []

    if op == "not" and len(args) == 1:
        return f"not ({_expr_to_str(args[0])})"

    infix = {
        "eq": "==",
        "neq": "!=",
        "lt": "<",
        "lte": "<=",
        "gt": ">",
        "gte": ">=",
        "and": "and",
        "or": "or",
    }.get(op)

    if infix and len(args) >= 2:
        joined = f" {infix} ".join(_expr_to_str(a) for a in args)
        return f"({joined})"

    return "expr?"


def _action_to_lines(act: Dict[str, Any]) -> List[str]:
    t = act.get("type")
    if t == "command":
        dev = act.get("device")
        cmd = act.get("command")
        args = act.get("args", [])
        if args:
            arg_str = ", ".join(_lit_to_str(a) for a in args)
            return [f"{dev}.{cmd}({arg_str})"]
        return [f"{dev}.{cmd}()"]
    if t == "delay":
        return [f"delay {act.get('seconds')}s"]
    if t == "notify":
        return [f"notify {_lit_to_str({'string': act.get('message','')})}"]
    return ["unknown_action"]


def _collect_state_context(transitions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    ctx: Dict[str, Dict[str, Any]] = {}

    def ensure(state_id: str) -> Dict[str, Any]:
        return ctx.setdefault(
            state_id,
            {
                "incoming": [],
                "outgoing": [],
                "trigger_devices": set(),
                "action_devices": set(),
                "commands": set(),
            },
        )

    for tr in transitions:
        if not isinstance(tr, dict):
            continue
        frm = tr.get("from")
        to = tr.get("to")
        if isinstance(frm, str):
            ensure(frm)["outgoing"].append(tr)
        if isinstance(to, str):
            ensure(to)["incoming"].append(tr)

        trigger_devices: Set[str] = set()
        for tg in tr.get("triggers", []) if isinstance(tr.get("triggers"), list) else []:
            if not isinstance(tg, dict):
                continue
            ref = tg.get("ref") if isinstance(tg.get("ref"), dict) else None
            dev = ref.get("device") if ref else None
            if isinstance(dev, str) and dev:
                trigger_devices.add(dev)

        action_devices: Set[str] = set()
        commands: Set[str] = set()
        for act in tr.get("actions", []) if isinstance(tr.get("actions"), list) else []:
            if not isinstance(act, dict):
                continue
            dev = act.get("device")
            if isinstance(dev, str) and dev:
                action_devices.add(dev)
            cmd = act.get("command")
            if isinstance(cmd, str) and cmd:
                commands.add(cmd.lower())

        for state_id in {frm, to}:
            if not isinstance(state_id, str):
                continue
            slot = ensure(state_id)
            slot["trigger_devices"].update(trigger_devices)
            slot["action_devices"].update(action_devices)
            slot["commands"].update(commands)

    return ctx


def _is_idle_like_state(state_id: str) -> bool:
    return state_id.strip().lower() in {"idle", "ready", "monitoring", "initial"}


def _best_device_for_state(state_id: str, context: Dict[str, Dict[str, Any]]) -> Optional[str]:
    slot = context.get(state_id, {})
    incoming = slot.get("incoming", []) if isinstance(slot.get("incoming"), list) else []
    for tr in incoming:
        if not isinstance(tr, dict):
            continue
        for act in tr.get("actions", []) if isinstance(tr.get("actions"), list) else []:
            if isinstance(act, dict) and isinstance(act.get("device"), str):
                return act["device"]
    action_devices = slot.get("action_devices") if isinstance(slot.get("action_devices"), set) else set()
    if action_devices:
        return sorted(action_devices)[0]
    trigger_devices = slot.get("trigger_devices") if isinstance(slot.get("trigger_devices"), set) else set()
    if trigger_devices:
        return sorted(trigger_devices)[0]
    return None


def _derive_state_label(
    st: Dict[str, Any],
    *,
    initial: Optional[str],
    states: List[Dict[str, Any]],
    context: Dict[str, Dict[str, Any]],
) -> str:
    explicit_label = st.get("label")
    if isinstance(explicit_label, str) and explicit_label.strip():
        return explicit_label

    sid = st.get("id")
    if not isinstance(sid, str) or not sid:
        return "State"

    if _is_idle_like_state(sid):
        trigger_devices = sorted(context.get(sid, {}).get("trigger_devices", set()))
        if len(states) == 1:
            if trigger_devices:
                friendly = ", ".join(_humanize_device_id(dev) for dev in trigger_devices[:2])
                suffix = " + more" if len(trigger_devices) > 2 else ""
                return f"Monitoring {friendly}{suffix}"
            return "Monitoring"
        if sid == initial:
            return "Ready / Monitoring"
        return "Monitoring"

    words = _humanize_state_mode(sid)
    words_lower = {w.lower() for w in _split_identifier_parts(sid)}
    device_id = _best_device_for_state(sid, context)
    if device_id and words_lower & _MODE_WORDS:
        device_name = _humanize_device_id(device_id)
        if device_name.lower() not in words.lower():
            return _drop_duplicate_suffix_word(device_name, words)
    return words


def ir_to_plantuml(ir: Dict[str, Any], title: str = "Automation") -> str:
    sm = ir.get("stateMachine", {})
    states = sm.get("states", [])
    transitions = sm.get("transitions", [])
    initial = sm.get("initial")
    context = _collect_state_context(transitions if isinstance(transitions, list) else [])

    lines: List[str] = []
    lines.append("@startuml")
    lines.append(f"title {title}")
    lines.append("hide empty description")
    lines.append("skinparam shadowing false")
    lines.append("skinparam state {")
    lines.append("  RoundCorner 12")
    lines.append("}")
    lines.append("")

    # Human-editing cheat sheet (kept as comments so it won't affect rendering).
    lines.extend(
        [
            "' === Human-editable guide ===",
            "' This diagram is the canonical IR rendered as PlantUML.",
            "' Display labels and styling are presentation-only; aliases/transitions remain authoritative.",
            "' You may edit this diagram and round-trip it back into IR:",
            "'   # 1) Copy baseline to an editable file (example):",
            "'   #    cp outputs/<Bundle>/baseline/final.puml outputs/<Bundle>/edited.puml",
            "'   # 2) Edit outputs/<Bundle>/edited.puml",
            "'   # 3) Round-trip (outputs go to outputs/<Bundle>/edits/edit_###/*):",
            "'   #    nlpipeline roundtrip --puml outputs/<Bundle>/edited.puml --out-bundle outputs/<Bundle>",
            "'",
            "' Supported label lines (one per line, joined with \\n in PlantUML):",
            "'   TRIGGER: <dev>.<attr> becomes \"value\" AND <dev>.<attr> changes AND after 30s AND schedule <cron>",
            "'   GUARD:   (<dev>.<attr> == \"value\") and not (<dev>.<attr> != \"value\")",
            "'   ACTION:  <dev>.<command>(\"arg\", 1) | delay 30s | notify \"message\"",
            "'",
            "' Tip: Prefer renaming the *display label* in a state declaration:",
            "'   state \"Hallway Light On\" as LightOn",
            "' Keep the alias (LightOn) stable so transitions remain parseable.",
            "' =============================",
            "",
        ]
    )

    # Declare states explicitly so users can rename display labels without breaking IDs.
    # If a state contains a 'label' field, we use it; otherwise we derive a human-readable label.
    for st in states if isinstance(states, list) else []:
        if not isinstance(st, dict):
            continue
        sid = st.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        label = _derive_state_label(st, initial=initial, states=states, context=context)
        lines.append(f'state "{_escape_puml_string(label)}" as {sid}')

    lines.append("")
    if initial:
        lines.append(f"[*] --> {initial}")
        lines.append("")

    # Preserve explicit invariants as semantic notes, but do not add presentation-only notes.
    for st in states if isinstance(states, list) else []:
        if not isinstance(st, dict):
            continue
        sid = st.get("id")
        inv = st.get("invariants")
        if sid and isinstance(inv, list) and inv:
            inv_lines = [f"- {_expr_to_str(e)}" for e in inv if isinstance(e, dict)]
            if inv_lines:
                lines.append(f"note right of {sid}")
                lines.extend(inv_lines)
                lines.append("end note")
                lines.append("")

    for tr in transitions if isinstance(transitions, list) else []:
        if not isinstance(tr, dict):
            continue
        frm = tr.get("from")
        to = tr.get("to")
        triggers = tr.get("triggers", [])
        guard = tr.get("guard")
        actions = tr.get("actions", [])

        label_parts: List[str] = []
        if isinstance(triggers, list) and triggers:
            trig_lines = [_trigger_to_line(tg) for tg in triggers if isinstance(tg, dict)]
            if trig_lines:
                label_parts.append("TRIGGER: " + " AND ".join(trig_lines))

        if isinstance(guard, dict):
            label_parts.append("GUARD: " + _expr_to_str(guard))

        act_lines: List[str] = []
        if isinstance(actions, list):
            for act in actions:
                if isinstance(act, dict):
                    act_lines.extend(_action_to_lines(act))
        for al in act_lines:
            label_parts.append("ACTION: " + al)

        # PlantUML state transition label uses \n for new line.
        label = "\\n".join(label_parts) if label_parts else ""
        if label:
            lines.append(f"{frm} --> {to} : {label}")
        else:
            lines.append(f"{frm} --> {to}")

    lines.append("@enduml")
    lines.append("")
    return "\n".join(lines)

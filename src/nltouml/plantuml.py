from __future__ import annotations

from typing import Any, Dict, List


def _escape_puml_string(s: str) -> str:
    # PlantUML strings are quoted with ". Keep escaping minimal and predictable.
    return s.replace("\\", r"\\").replace('"', r'\"')


def _lit_to_str(lit: Dict[str, Any]) -> str:
    if "string" in lit:
        return f"\"{_escape_puml_string(str(lit['string']))}\""
    if "number" in lit:
        return str(lit['number'])
    if "bool" in lit:
        return "true" if lit['bool'] else "false"
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


def ir_to_plantuml(ir: Dict[str, Any], title: str = "Automation") -> str:
    sm = ir.get("stateMachine", {})
    states = sm.get("states", [])
    transitions = sm.get("transitions", [])
    initial = sm.get("initial")

    lines: List[str] = []
    lines.append("@startuml")
    lines.append(f"title {title}")
    lines.append("")

    # Human-editing cheat sheet (kept as comments so it won't affect rendering).
    lines.extend(
        [
            "' === Human-editable guide ===",
            "' You may edit this diagram and round-trip it back into IR:",
            "'   nlpipeline roundtrip --puml outputs/<Bundle>/edited.puml",
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
    # If a state contains a 'label' field, we use it; otherwise we default to its id.
    for st in states:
        if not isinstance(st, dict):
            continue
        sid = st.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        label = st.get("label") if isinstance(st.get("label"), str) else sid
        lines.append(f'state "{_escape_puml_string(label)}" as {sid}')

    lines.append("")
    lines.append(f"[*] --> {initial}")
    lines.append("")

    # Optionally render invariants as notes
    for st in states:
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

    for tr in transitions:
        if not isinstance(tr, dict):
            continue
        frm = tr.get("from")
        to = tr.get("to")
        triggers = tr.get("triggers", [])
        guard = tr.get("guard")
        actions = tr.get("actions", [])

        label_parts: List[str] = []
        if isinstance(triggers, list) and triggers:
            trig_lines = [ _trigger_to_line(tg) for tg in triggers if isinstance(tg, dict) ]
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

        # PlantUML state transition label uses \n for new line
        label = "\\n".join(label_parts) if label_parts else ""
        if label:
            lines.append(f"{frm} --> {to} : {label}")
        else:
            lines.append(f"{frm} --> {to}")

    lines.append("@enduml")
    lines.append("")
    return "\n".join(lines)

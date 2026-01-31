from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator


@dataclass
class Diagnostic:
    severity: str  # 'error' or 'warning'
    code: str
    path: str
    message: str
    suggestions: Optional[List[str]] = None


@dataclass
class Patch:
    op: str
    path: str
    value: Any
    reason: str


def _json_pointer(path_items: List[Any]) -> str:
    # Convert jsonschema error path (deque) to JSON Pointer-ish string
    if not path_items:
        return "$"
    out = "$"
    for p in path_items:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            out += f".{p}"
    return out


def validate_json_schema(ir: Dict[str, Any], ir_schema: Dict[str, Any]) -> List[Diagnostic]:
    v = Draft202012Validator(ir_schema)
    diags: List[Diagnostic] = []
    for err in sorted(v.iter_errors(ir), key=str):
        diags.append(Diagnostic(
            severity="error",
            code="E100",
            path=_json_pointer(list(err.path)),
            message=err.message,
        ))
    return diags


def _device_kind_map(device_catalog: Dict[str, Any]) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for d in device_catalog.get("devices", []):
        if isinstance(d, dict) and "id" in d and "kind" in d:
            m[str(d["id"])] = str(d["kind"])
    for g in device_catalog.get("globals", []):
        if isinstance(g, dict) and "id" in g and "kind" in g:
            m[str(g["id"])] = str(g["kind"])
    return m


def _allowed_attr_and_values(cap_catalog: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    kinds = cap_catalog.get("kinds", {}) if isinstance(cap_catalog.get("kinds", {}), dict) else {}
    value_sets = cap_catalog.get("valueSets", {}) if isinstance(cap_catalog.get("valueSets", {}), dict) else {}
    return kinds, value_sets


def _get_attr_spec(kind_spec: Dict[str, Any], attr: str) -> Optional[Dict[str, Any]]:
    attrs = kind_spec.get("attributes", {}) if isinstance(kind_spec.get("attributes", {}), dict) else {}
    spec = attrs.get(attr)
    return spec if isinstance(spec, dict) else None


def _allowed_enum_values(attr_spec: Dict[str, Any], value_sets: Dict[str, List[str]]) -> Optional[List[str]]:
    if attr_spec.get("type") == "enum":
        vs = attr_spec.get("valuesFrom")
        if isinstance(vs, str) and vs in value_sets:
            vals = value_sets[vs]
            if isinstance(vals, list) and all(isinstance(x, str) for x in vals):
                return vals
    return None


def validate_semantics(
    ir: Dict[str, Any],
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
) -> Tuple[List[Diagnostic], List[Patch]]:
    diags: List[Diagnostic] = []
    patches: List[Patch] = []

    device_to_kind = _device_kind_map(device_catalog)
    kind_specs, value_sets = _allowed_attr_and_values(capability_catalog)

    # Device existence helper
    def ensure_device_exists(device_id: str, path: str) -> Optional[str]:
        if device_id not in device_to_kind:
            diags.append(Diagnostic(
                severity="error",
                code="E110",
                path=path,
                message=f"Unknown device '{device_id}'. Must be one of: {sorted(device_to_kind.keys())}",
                suggestions=sorted(device_to_kind.keys()),
            ))
            return None
        return device_to_kind[device_id]

    # Attribute checker (ref-only)
    def check_ref_only(device_id: str, attr: str, path: str) -> None:
        kind = ensure_device_exists(device_id, path)
        if not kind:
            return
        kind_spec = kind_specs.get(kind)
        if not isinstance(kind_spec, dict):
            diags.append(Diagnostic(
                severity="error",
                code="E205",
                path=path,
                message=f"No capability spec found for kind '{kind}'",
            ))
            return

        attr_spec = _get_attr_spec(kind_spec, attr)
        if not attr_spec:
            allowed = sorted((kind_spec.get("attributes") or {}).keys()) if isinstance(kind_spec.get("attributes"), dict) else []
            diags.append(Diagnostic(
                severity="error",
                code="E200",
                path=path,
                message=f"Unknown attribute '{attr}' for kind '{kind}'. Allowed: {allowed}",
                suggestions=allowed,
            ))
            return

    # Attribute/value checker
    def check_ref_and_value(device_id: str, attr: str, lit: Dict[str, Any], path: str) -> None:
        # First ensure the ref is valid.
        kind = ensure_device_exists(device_id, path)
        if not kind:
            return
        kind_spec = kind_specs.get(kind)
        if not isinstance(kind_spec, dict):
            diags.append(Diagnostic(
                severity="error",
                code="E205",
                path=path,
                message=f"No capability spec found for kind '{kind}'",
            ))
            return

        attr_spec = _get_attr_spec(kind_spec, attr)
        if not attr_spec:
            allowed = sorted((kind_spec.get("attributes") or {}).keys()) if isinstance(kind_spec.get("attributes"), dict) else []
            diags.append(Diagnostic(
                severity="error",
                code="E200",
                path=path,
                message=f"Unknown attribute '{attr}' for kind '{kind}'. Allowed: {allowed}",
                suggestions=allowed,
            ))
            return

        enum_vals = _allowed_enum_values(attr_spec, value_sets)
        if enum_vals is not None:
            # must be string literal
            if "string" not in lit:
                diags.append(Diagnostic(
                    severity="error",
                    code="E210",
                    path=path,
                    message=f"Expected string literal for enum '{kind}.{attr}'. Allowed: {enum_vals}",
                    suggestions=enum_vals,
                ))
                return
            v = str(lit.get("string"))
            if v not in enum_vals:
                diags.append(Diagnostic(
                    severity="error",
                    code="E220",
                    path=path,
                    message=f"Invalid value '{v}' for {kind}.{attr}. Allowed: {enum_vals}",
                    suggestions=enum_vals,
                ))

    # Command checker
    def check_command(device_id: str, cmd: str, path: str) -> None:
        kind = ensure_device_exists(device_id, path)
        if not kind:
            return
        kind_spec = kind_specs.get(kind)
        if not isinstance(kind_spec, dict):
            return
        commands = kind_spec.get("commands", {}) if isinstance(kind_spec.get("commands", {}), dict) else {}
        if cmd not in commands:
            suggestions = sorted(commands.keys())
            diags.append(Diagnostic(
                severity="error",
                code="E300",
                path=path,
                message=f"Unknown command '{cmd}' for kind '{kind}'. Allowed: {suggestions}",
                suggestions=suggestions,
            ))

    # Walk transitions
    sm = ir.get("stateMachine") if isinstance(ir.get("stateMachine"), dict) else {}
    states = sm.get("states", []) if isinstance(sm.get("states", []), list) else []
    state_ids = {s.get("id") for s in states if isinstance(s, dict) and isinstance(s.get("id"), str)}

    # state refs
    initial = sm.get("initial")
    if isinstance(initial, str) and initial not in state_ids:
        diags.append(Diagnostic(
            severity="error",
            code="E111",
            path="$.stateMachine.initial",
            message=f"Initial state '{initial}' not found in states.",
            suggestions=sorted(list(state_ids)),
        ))

    transitions = sm.get("transitions", []) if isinstance(sm.get("transitions", []), list) else []
    for i, tr in enumerate(transitions):
        if not isinstance(tr, dict):
            continue
        frm = tr.get("from")
        to = tr.get("to")
        if isinstance(frm, str) and frm not in state_ids:
            diags.append(Diagnostic("error", "E111", f"$.stateMachine.transitions[{i}].from", f"Unknown state '{frm}'"))
        if isinstance(to, str) and to not in state_ids:
            diags.append(Diagnostic("error", "E111", f"$.stateMachine.transitions[{i}].to", f"Unknown state '{to}'"))

        # triggers
        triggers = tr.get("triggers", []) if isinstance(tr.get("triggers", []), list) else []
        for j, tg in enumerate(triggers):
            if not isinstance(tg, dict):
                continue
            ttype = tg.get("type")
            if ttype in ("becomes", "changes"):
                ref = tg.get("ref")
                if isinstance(ref, dict):
                    dev = ref.get("device")
                    attr = ref.get("path")
                    if isinstance(dev, str) and isinstance(attr, str):
                        if ttype == "becomes":
                            val = tg.get("value")
                            if isinstance(val, dict):
                                check_ref_and_value(dev, attr, val, f"$.stateMachine.transitions[{i}].triggers[{j}]")
                        else:
                            # just validate ref exists and attr is valid
                            check_ref_only(dev, attr, f"$.stateMachine.transitions[{i}].triggers[{j}]")

        # guard expressions: only validate refs + enum literals for eq/neq in MVP
        def walk_expr(expr: Any, base_path: str) -> None:
            if not isinstance(expr, dict):
                return
            if "ref" in expr and isinstance(expr["ref"], dict):
                r = expr["ref"]
                dev = r.get("device")
                attr = r.get("path")
                if isinstance(dev, str) and isinstance(attr, str):
                    # validate ref exists and attr is valid (no value checking)
                    check_ref_only(dev, attr, base_path)
            if "lit" in expr and isinstance(expr["lit"], dict):
                # literal alone is okay
                return
            op = expr.get("op")
            args = expr.get("args")
            if isinstance(op, str) and isinstance(args, list):
                # arity rules (basic)
                if op == "not" and len(args) != 1:
                    diags.append(Diagnostic("error", "E400", base_path, "'not' must have 1 argument"))
                if op in ("eq", "neq", "lt", "lte", "gt", "gte") and len(args) != 2:
                    diags.append(Diagnostic("error", "E400", base_path, f"'{op}' must have 2 arguments"))
                if op in ("and", "or") and len(args) < 2:
                    diags.append(Diagnostic("error", "E400", base_path, f"'{op}' must have 2+ arguments"))

                for k, a in enumerate(args):
                    walk_expr(a, f"{base_path}.args[{k}]")

                # enum literal check for eq/neq when one side is ref and other is lit
                if op in ("eq", "neq") and len(args) == 2:
                    left, right = args[0], args[1]
                    if isinstance(left, dict) and isinstance(right, dict):
                        if "ref" in left and "lit" in right:
                            r = left["ref"]
                            lit = right["lit"]
                        elif "ref" in right and "lit" in left:
                            r = right["ref"]
                            lit = left["lit"]
                        else:
                            return
                        if isinstance(r, dict) and isinstance(lit, dict):
                            dev = r.get("device")
                            attr = r.get("path")
                            if isinstance(dev, str) and isinstance(attr, str):
                                check_ref_and_value(dev, attr, lit, base_path)

        if "guard" in tr:
            walk_expr(tr.get("guard"), f"$.stateMachine.transitions[{i}].guard")

        # actions
        actions = tr.get("actions", []) if isinstance(tr.get("actions", []), list) else []
        # conflict check within a transition
        seen_device_cmds: Dict[str, set] = {}
        for j, act in enumerate(actions):
            if not isinstance(act, dict):
                continue
            if act.get("type") == "command":
                dev = act.get("device")
                cmd = act.get("command")
                if isinstance(dev, str) and isinstance(cmd, str):
                    check_command(dev, cmd, f"$.stateMachine.transitions[{i}].actions[{j}]")
                    seen_device_cmds.setdefault(dev, set()).add(cmd)

        for dev, cmds in seen_device_cmds.items():
            # simple contradiction rule for on/off, lock/unlock
            contradictions = [({"on", "off"}, "on/off"), ({"lock", "unlock"}, "lock/unlock")]
            for s, label in contradictions:
                if len(s.intersection(cmds)) == 2:
                    diags.append(Diagnostic(
                        severity="error",
                        code="E530",
                        path=f"$.stateMachine.transitions[{i}].actions",
                        message=f"Conflicting actions for device '{dev}' ({label}) in same transition.",
                    ))

    # simple reachability warnings (optional)
    # Build adjacency
    adj: Dict[str, List[str]] = {sid: [] for sid in state_ids}
    for tr in transitions:
        if isinstance(tr, dict) and isinstance(tr.get("from"), str) and isinstance(tr.get("to"), str):
            if tr["from"] in adj:
                adj[tr["from"]].append(tr["to"])

    if isinstance(initial, str) and initial in adj:
        visited = set()
        stack = [initial]
        while stack:
            s = stack.pop()
            if s in visited:
                continue
            visited.add(s)
            for nxt in adj.get(s, []):
                if nxt not in visited:
                    stack.append(nxt)

        for sid in sorted(state_ids):
            if sid not in visited:
                diags.append(Diagnostic(
                    severity="warning",
                    code="W500",
                    path="$.stateMachine.states",
                    message=f"Unreachable state '{sid}' from initial state '{initial}'.",
                ))

    return diags, patches


def validate_all(
    ir: Dict[str, Any],
    ir_schema: Dict[str, Any],
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
) -> Tuple[List[Diagnostic], List[Patch]]:
    diags = validate_json_schema(ir, ir_schema)
    if any(d.severity == "error" for d in diags):
        return diags, []
    sem_diags, patches = validate_semantics(ir, device_catalog, capability_catalog)
    return diags + sem_diags, patches

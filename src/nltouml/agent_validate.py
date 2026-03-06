from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import json


@dataclass
class Issue:
    severity: str  # 'error' or 'warning'
    code: str
    path: str
    message: str
    suggestions: Optional[List[str]] = None


def _stable_json(obj: Any) -> str:
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(obj)


def _state_machine(ir: Dict[str, Any]) -> Dict[str, Any]:
    sm = ir.get("stateMachine")
    return sm if isinstance(sm, dict) else {}


def validate_agentic(ir: Dict[str, Any]) -> Tuple[List[Issue], Dict[str, Any]]:
    """Layer 5: higher-level state-machine checks (graph/logical coherency).

    This is intentionally conservative and mostly deterministic:
      - unreachable states (error)
      - ambiguous transitions (same from + same triggers but different targets) (error)
      - duplicate transitions (same from + same triggers + same target) (warning)
      - dead-end states (warning)
    """
    issues: List[Issue] = []
    sm = _state_machine(ir)

    states = sm.get("states", []) if isinstance(sm.get("states"), list) else []
    state_ids = [s.get("id") for s in states if isinstance(s, dict) and isinstance(s.get("id"), str)]
    state_set = set(state_ids)

    initial = sm.get("initial")
    if not isinstance(initial, str) or not initial:
        issues.append(Issue(
            severity="error",
            code="S100",
            path="$.stateMachine.initial",
            message="Missing or invalid initial state.",
            suggestions=state_ids[:10] if state_ids else None,
        ))
        # Continue; other checks may still be useful.
        initial = None

    transitions = sm.get("transitions", []) if isinstance(sm.get("transitions"), list) else []
    # Build adjacency for reachability
    adj: Dict[str, List[str]] = {}
    outgoing_count: Dict[str, int] = {sid: 0 for sid in state_set}
    for i, t in enumerate(transitions):
        if not isinstance(t, dict):
            continue
        frm = t.get("from")
        to = t.get("to")
        if isinstance(frm, str) and isinstance(to, str):
            adj.setdefault(frm, []).append(to)
            if frm in outgoing_count:
                outgoing_count[frm] += 1

    # Reachability from initial
    reachable: set[str] = set()
    if isinstance(initial, str) and initial in state_set:
        stack = [initial]
        while stack:
            s = stack.pop()
            if s in reachable:
                continue
            reachable.add(s)
            for nxt in adj.get(s, []):
                if nxt in state_set and nxt not in reachable:
                    stack.append(nxt)

        for sid in state_ids:
            if sid not in reachable:
                issues.append(Issue(
                    severity="error",
                    code="S401",
                    path="$.stateMachine.states",
                    message=f"Unreachable state '{sid}' (not reachable from initial '{initial}').",
                    suggestions=[initial] if isinstance(initial, str) else None,
                ))

    # Dead-end states (no outgoing transitions)
    for sid in state_ids:
        if outgoing_count.get(sid, 0) == 0:
            issues.append(Issue(
                severity="warning",
                code="S420",
                path="$.stateMachine.states",
                message=f"State '{sid}' has no outgoing transitions (may be a terminal/dead-end state).",
            ))

    # Ambiguous / duplicate transitions: same from + same triggers signature
    groups: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}
    for i, t in enumerate(transitions):
        if not isinstance(t, dict):
            continue
        frm = t.get("from")
        to = t.get("to")
        if not (isinstance(frm, str) and isinstance(to, str)):
            continue
        triggers = t.get("triggers", [])
        sig = _stable_json(triggers)
        groups.setdefault((frm, sig), []).append((i, to))

    for (frm, _sig), entries in groups.items():
        if len(entries) <= 1:
            continue
        tos = {to for _i, to in entries}
        idxs = [i for i, _to in entries]
        if len(tos) > 1:
            issues.append(Issue(
                severity="error",
                code="S450",
                path="$.stateMachine.transitions",
                message=(
                    f"Ambiguous transitions from '{frm}': multiple transitions share the same triggers but lead to "
                    f"different targets {sorted(tos)} (transition indices {idxs})."
                ),
            ))
        else:
            issues.append(Issue(
                severity="warning",
                code="S451",
                path="$.stateMachine.transitions",
                message=(
                    f"Duplicate transitions from '{frm}': {len(entries)} transitions share the same triggers and target "
                    f"'{next(iter(tos))}' (transition indices {idxs})."
                ),
            ))

    report = {
        "ok": not any(i.severity == "error" for i in issues),
        "issues": [i.__dict__ for i in issues],
    }
    return issues, report

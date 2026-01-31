from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _ensure_state(states: List[Dict[str, Any]], state_id: str) -> None:
    if any(isinstance(s, dict) and s.get("id") == state_id for s in states):
        return
    states.append({"id": state_id})


def _make_after_trigger(seconds: int) -> Dict[str, Any]:
    return {"type": "after", "seconds": int(seconds)}


def _first_delay(actions: List[Any]) -> Tuple[int, int] | None:
    """Return (index, seconds) of the first delay action, else None."""
    for i, a in enumerate(actions):
        if isinstance(a, dict) and a.get("type") == "delay":
            secs = a.get("seconds")
            if isinstance(secs, (int, float)):
                return i, int(secs)
    return None


def desugar_delays_to_timer_states(ir: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite inline delay actions into explicit timer states.

    Why:
      - LLMs frequently produce action lists like: [command on, delay 30s, command off]
      - A true state-machine representation is clearer if this becomes:
          StateA --(trigger)--> TimedState (do command on)
          TimedState --(after 30s)--> StateA (do command off)

    This transform is conservative and ONLY rewrites transitions that contain a delay
    action *followed by at least one more action*.
    """

    sm = ir.get("stateMachine")
    if not isinstance(sm, dict):
        return ir

    states = sm.get("states")
    transitions = sm.get("transitions")
    if not isinstance(states, list) or not isinstance(transitions, list):
        return ir

    # Build a stable set of existing state ids.
    existing_ids = {
        s.get("id")
        for s in states
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }

    new_transitions: List[Dict[str, Any]] = []
    counter = 0

    for tr in transitions:
        if not isinstance(tr, dict):
            continue

        actions = tr.get("actions")
        if not isinstance(actions, list):
            new_transitions.append(tr)
            continue

        # We may need to split multiple delays in one transition; do it iteratively.
        cur_tr = tr
        cur_actions = actions
        did_any = False

        while True:
            hit = _first_delay(cur_actions)
            if hit is None:
                break
            idx, secs = hit
            if idx >= len(cur_actions) - 1:
                # delay at end has no observable effect in our IR; keep as-is.
                break

            before = cur_actions[:idx]
            after = cur_actions[idx + 1 :]

            frm = str(cur_tr.get("from"))
            to = str(cur_tr.get("to"))

            # Create a unique intermediate state id.
            counter += 1
            wait_state = f"Wait_{secs}s_{counter}"
            # Ensure valid identifier-ish state id.
            wait_state = wait_state.replace("-", "_").replace(" ", "_")
            if wait_state in existing_ids:
                # extremely unlikely, but keep stable
                wait_state = f"{wait_state}_{counter}"
            existing_ids.add(wait_state)
            _ensure_state(states, wait_state)

            # Part A: original triggers/guard, run actions before delay
            tr_a: Dict[str, Any] = {
                "from": frm,
                "to": wait_state,
                "triggers": cur_tr.get("triggers", []),
                "actions": before,
            }
            if "guard" in cur_tr:
                tr_a["guard"] = cur_tr.get("guard")
            if "id" in cur_tr and isinstance(cur_tr.get("id"), str):
                tr_a["id"] = f"{cur_tr['id']}_a{counter}"

            # Part B: after(secs) trigger, run actions after delay
            tr_b: Dict[str, Any] = {
                "from": wait_state,
                "to": to,
                "triggers": [_make_after_trigger(secs)],
                "actions": after,
            }
            if "id" in cur_tr and isinstance(cur_tr.get("id"), str):
                tr_b["id"] = f"{cur_tr['id']}_b{counter}"

            # Emit A now; keep splitting B if it contains more delays.
            new_transitions.append(tr_a)
            cur_tr = tr_b
            cur_actions = after
            did_any = True

        if did_any:
            # Append the final (possibly transformed) transition.
            new_transitions.append(cur_tr)
        else:
            new_transitions.append(tr)

    sm["transitions"] = new_transitions
    return ir

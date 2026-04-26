from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .io_utils import try_extract_json


@dataclass
class LLMResult:
    text: str
    raw: Any


def _build_system_prompt(device_catalog: Dict[str, Any], capability_catalog: Dict[str, Any], ir_schema: Dict[str, Any]) -> str:
    # Keep it short and strict to reduce formatting mistakes.
    allowed_devices = [d["id"] for d in device_catalog.get("devices", []) if isinstance(d, dict) and "id" in d]
    globals_ = [g["id"] for g in device_catalog.get("globals", []) if isinstance(g, dict) and "id" in g]
    all_ids = sorted(set(allowed_devices + globals_))

    # Build a compact kind→(attrs, commands) map
    kind_specs = capability_catalog.get("kinds", {}) if isinstance(capability_catalog.get("kinds"), dict) else {}
    compact_kinds: Dict[str, Dict[str, List[str]]] = {}
    for k, spec in kind_specs.items():
        if not isinstance(spec, dict):
            continue
        attrs = list((spec.get("attributes") or {}).keys()) if isinstance(spec.get("attributes"), dict) else []
        cmds = list((spec.get("commands") or {}).keys()) if isinstance(spec.get("commands"), dict) else []
        compact_kinds[str(k)] = {"attributes": sorted(attrs), "commands": sorted(cmds)}

    return (
        "You convert a natural-language smart-home requirement into a STRICT JSON object that conforms to the provided IR schema.\n"
        "Output ONLY JSON. No markdown. No code fences.\n\n"
        "IR constraints:\n"
        f"- version must be '0.1'\n"
        f"- You may ONLY reference these device ids: {all_ids}\n"
        "- The output MUST include: version, devices[], and stateMachine.{initial,states[],transitions[]}\n"
        "- Use EXACT field names and shapes. Follow this minimal skeleton (fill values; keep keys):\n"
        "  {\n"
        "    'version':'0.1',\n"
        "    'devices':[{'id':'motion_hall','kind':'motionSensor'}],\n"
        "    'stateMachine':{\n"
        "      'initial':'Idle',\n"
        "      'states':[{'id':'Idle'}],\n"
        "      'transitions':[{'from':'Idle','to':'Active','triggers':[...],'actions':[...]}]\n"
        "    }\n"
        "  }\n"
        "- triggers must be one of: becomes|changes|schedule|after.\n"
        "- actions must be one of: command|delay|notify.\n"
        "- Clock-based schedule triggers MUST use {type:'schedule', cron:'...'} in the final JSON. Never use time or at fields in the final IR.\n"
        "- Relative waiting uses {type:'after', seconds:N}, not a schedule trigger.\n"
        "- Conditions/comparisons belong in guard expressions or trigger logic, never inside actions[].\n"
        "- A command action MUST include a real device command; do not encode property/value/operator checks as actions.\n\n"
        "Device kinds and their attributes/commands (for checking):\n"
        f"{compact_kinds}\n\n"
        "Guidelines:\n"
        "- Prefer 2–4 states max for simple automations.\n"
        "- Use enum values exactly (e.g., motion: active/inactive; switch: on/off; presence: present/'not present'; lock: locked/unlocked).\n"
        "- Prefer modeling time with an explicit timer transition: create an intermediate state and use a trigger {type:'after', seconds:N}.\n"
        "  (Example: motion->TimedLight (turn on), then TimedLight --after 30s--> Idle (turn off))\n"
        "- If you do use an ACTION delay, ensure it is followed by at least one action.\n"
        "- When the requirement contains both an event and a persistent condition, put the event-like part in triggers and the persistent condition in guard.\n"
    )


def openai_generate_json(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> LLMResult:
    """Calls OpenAI using whichever API surface is available (responses or chat.completions)."""
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError("OpenAI dependency not installed. Run: pip install -e '.[openai]' ") from e

    client = OpenAI(api_key=api_key)

    # Prefer Responses API if present
    if hasattr(client, "responses"):
        try:
            resp = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                # JSON mode: guarantees valid JSON (but not schema adherence).
                # This greatly reduces flaky parsing failures.
                text={"format": {"type": "json_object"}},
                # Make runs repeatable for metrics (reduces variance across runs).
                temperature=0,
            )
            text = getattr(resp, "output_text", None)
            if text is None:
                # fallback: try to extract from output structure
                text = str(resp)
            return LLMResult(text=text, raw=resp)
        except Exception:
            # fall through to chat.completions
            pass

    # Chat Completions fallback
    # Chat Completions fallback. Try JSON mode if supported, otherwise plain.
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
    text = resp.choices[0].message.content or ""
    return LLMResult(text=text, raw=resp)




def _write_llm_debug_text(debug_dir: Optional[Path], name: str, text: str) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(text, encoding="utf-8")


def _generate_and_parse_json_with_retries(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_attempts: int,
    debug_dir: Optional[Path],
    artifact_prefix: str,
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    attempt_prompt = user_prompt
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        res = openai_generate_json(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            user_prompt=attempt_prompt,
        )
        _write_llm_debug_text(debug_dir, f"{artifact_prefix}.attempt_{attempt:02d}.raw.txt", res.text or "")
        try:
            obj = try_extract_json(res.text)
            if debug_dir is not None:
                from .io_utils import write_json
                write_json(debug_dir / f"{artifact_prefix}.attempt_{attempt:02d}.parsed.json", obj)
            return obj
        except Exception as e:
            last_error = e
            _write_llm_debug_text(debug_dir, f"{artifact_prefix}.attempt_{attempt:02d}.parse_error.txt", str(e))
            attempt_prompt = (
                user_prompt
                + "\n\nIMPORTANT: Your previous response was not a single valid JSON object parseable by the pipeline. "
                + f"Parse error: {e}. Return ONLY one JSON object with double-quoted keys and no prose."
            )
    debug_hint = f" See {debug_dir.as_posix()} for raw responses." if debug_dir is not None else ""
    raise ValueError(f"JSON generation failed after {max(1, int(max_attempts))} attempts: {last_error}.{debug_hint}")


def generate_ir_with_llm(
    text: str,
    *,
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    debug_dir: Optional[Path] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    sys_prompt = _build_system_prompt(device_catalog, capability_catalog, ir_schema)
    user_prompt = (
        "Convert this requirement into IR JSON.\n"
        "Return ONLY one JSON object.\n"
        f"REQUIREMENT: {text}\n"
    )
    return _generate_and_parse_json_with_retries(
        api_key=api_key,
        model=model,
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        max_attempts=max_attempts,
        debug_dir=debug_dir,
        artifact_prefix="generate_ir",
    )


def repair_ir_with_llm(
    ir: Dict[str, Any],
    diagnostics: List[Dict[str, Any]],
    *,
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    debug_dir: Optional[Path] = None,
    max_attempts: int = 2,
    artifact_prefix: str = "repair_ir",
) -> Dict[str, Any]:
    sys_prompt = _build_system_prompt(device_catalog, capability_catalog, ir_schema)
    user_prompt = (
        "Fix the following IR JSON so it passes validation.\n"
        "Return ONLY corrected JSON.\n"
        "Keep schedule triggers canonical: use cron for clock schedules and after for relative waits.\n"
        "Move condition-like checks into guard instead of actions when needed.\n\n"
        f"DIAGNOSTICS: {diagnostics}\n\n"
        f"IR: {ir}\n"
    )
    return _generate_and_parse_json_with_retries(
        api_key=api_key,
        model=model,
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        max_attempts=max_attempts,
        debug_dir=debug_dir,
        artifact_prefix=artifact_prefix,
    )


def mock_generate_ir(text: str) -> Dict[str, Any]:
    """A tiny deterministic generator for demo/testing without an LLM.

    It only understands a couple of patterns (motion→switch) but is enough to test end-to-end.
    """
    t = text.lower()
    # default: motion controls hallway light
    delay_s = 0
    if "minute" in t:
        # naive parse: find first number before 'minute'
        import re
        m = re.search(r"(\d+)\s*(minute|minutes)", t)
        if m:
            delay_s = int(m.group(1)) * 60
    elif "second" in t:
        import re
        m = re.search(r"(\d+)\s*(second|seconds)", t)
        if m:
            delay_s = int(m.group(1))

    if delay_s <= 0:
        delay_s = 300  # default 5 min

    return {
        "version": "0.1",
        "devices": [
            {"id": "motion_hall", "kind": "motionSensor", "capabilities": ["motion"]},
            {"id": "light_hall", "kind": "switch", "capabilities": ["switch"]},
        ],
        "stateMachine": {
            "initial": "Idle",
            "states": [
                {"id": "Idle"},
                {"id": "Lit"}
            ],
            "transitions": [
                {
                    "id": "t_on",
                    "from": "Idle",
                    "to": "Lit",
                    "triggers": [
                        {
                            "type": "becomes",
                            "ref": {"device": "motion_hall", "path": "motion"},
                            "value": {"string": "active"}
                        }
                    ],
                    "actions": [
                        {"type": "command", "device": "light_hall", "command": "on"}
                    ]
                },
                {
                    "id": "t_off",
                    "from": "Lit",
                    "to": "Idle",
                    "triggers": [
                        {
                            "type": "becomes",
                            "ref": {"device": "motion_hall", "path": "motion"},
                            "value": {"string": "inactive"}
                        }
                    ],
                    "actions": [
                        {"type": "delay", "seconds": delay_s},
                        {"type": "command", "device": "light_hall", "command": "off"}
                    ]
                }
            ]
        }
    }

def _build_edit_patch_system_prompt(
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    current_ir: Dict[str, Any],
) -> str:
    allowed_devices = [d["id"] for d in device_catalog.get("devices", []) if isinstance(d, dict) and "id" in d]
    globals_ = [g["id"] for g in device_catalog.get("globals", []) if isinstance(g, dict) and "id" in g]
    all_ids = sorted(set(allowed_devices + globals_))

    sm = current_ir.get("stateMachine", {}) if isinstance(current_ir.get("stateMachine"), dict) else {}
    states = [s.get("id") for s in sm.get("states", []) if isinstance(s, dict) and isinstance(s.get("id"), str)]
    transitions = []
    for t in sm.get("transitions", []) if isinstance(sm.get("transitions"), list) else []:
        if isinstance(t, dict):
            transitions.append({"from": t.get("from"), "to": t.get("to")})

    kind_specs = capability_catalog.get("kinds", {}) if isinstance(capability_catalog.get("kinds"), dict) else {}
    compact_kinds: Dict[str, Dict[str, List[str]]] = {}
    for k, spec in kind_specs.items():
        if not isinstance(spec, dict):
            continue
        attrs = list((spec.get("attributes") or {}).keys()) if isinstance(spec.get("attributes"), dict) else []
        cmds = list((spec.get("commands") or {}).keys()) if isinstance(spec.get("commands"), dict) else []
        compact_kinds[str(k)] = {"attributes": sorted(attrs), "commands": sorted(cmds)}

    return (
        "You are an edit agent for a smart-home state-machine IR.\n"
        "You will receive:\n"
        "  - CURRENT_IR (JSON)\n"
        "  - CHANGE_REQUEST (natural language)\n\n"
        "You must return ONLY a JSON object with this shape:\n"
        "{\n"
        "  \"summary\": \"one or two sentences describing what you changed\",\n"
        "  \"edits\": [\n"
        "     {\"op\":\"set_state_label\", \"state_id\":\"Idle\", \"label\":\"LightOff\"},\n"
        "     {\"op\":\"update_transition\", \"from\":\"WaitOff\", \"to\":\"Idle\", \"triggers\":[...], \"actions\":[...]},\n"
        "     ...\n"
        "  ]\n"
        "}\n\n"
        "Allowed ops (ONLY these):\n"
        "- set_state_label(state_id,label)\n"
        "- set_initial(state_id)\n"
        "- add_state(state_id,label?)\n"
        "- remove_state(state_id)\n"
        "- add_transition(from,to,triggers?,guard?,actions?)\n"
        "- remove_transition(from,to,index?)\n"
        "- update_transition(from,to,index?,new_from?,new_to?,triggers?,guard?,actions?)\n\n"
        "CRITICAL constraints:\n"
        "- Do NOT rename existing state IDs unless the user explicitly requests it.\n"
        "- Prefer changing human-readable naming via set_state_label.\n"
        "- If you include \"index\", it refers to the Nth transition (0-based) among transitions matching the same from/to pair.\n"
        "- Any triggers/actions you include MUST be valid IR objects per schema (types: becomes|changes|schedule|after, and command|delay|notify).\n"
        "- Every edit object MUST include a non-empty string op from the allowed list. Never use null/None for op.\n"
        "- If you are unsure, return an empty edits list rather than a malformed edit object.\n"
        "- For schedule triggers, use cron in the final patch payload, not time/at fields.\n"
        "- Do not encode conditions or comparisons inside actions[]. Use guard for conditions.\n"
        "- You may ONLY reference these device ids: "
        + str(all_ids)
        + "\n\n"
        "Current state IDs:\n"
        + str(states)
        + "\n"
        "Current transition endpoints:\n"
        + str(transitions)
        + "\n\n"
        "Device kinds and their attributes/commands (for checking):\n"
        + str(compact_kinds)
        + "\n"
    )


def generate_edit_patch_with_llm(
    *,
    request_text: str,
    current_ir: Dict[str, Any],
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    debug_dir: Optional[Path] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    sys_prompt = _build_edit_patch_system_prompt(device_catalog, capability_catalog, ir_schema, current_ir)
    user_prompt = (
        "CHANGE_REQUEST:\n"
        f"{request_text}\n\n"
        "CURRENT_IR:\n"
        f"{current_ir}\n"
    )
    return _generate_and_parse_json_with_retries(
        api_key=api_key,
        model=model,
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        max_attempts=max_attempts,
        debug_dir=debug_dir,
        artifact_prefix="generate_edit_patch",
    )


def repair_edit_patch_with_llm(
    *,
    request_text: str,
    current_ir: Dict[str, Any],
    prior_patch: Dict[str, Any],
    diagnostics: List[Dict[str, Any]],
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    debug_dir: Optional[Path] = None,
    max_attempts: int = 2,
) -> Dict[str, Any]:
    sys_prompt = _build_edit_patch_system_prompt(device_catalog, capability_catalog, ir_schema, current_ir)
    user_prompt = (
        "The prior patch produced validation errors after being applied.\n"
        "Return a corrected patch JSON using ONLY allowed ops.\n"
        "Every edit must include a valid string op. If unsure, return edits:[].\n\n"
        f"CHANGE_REQUEST:\n{request_text}\n\n"
        f"CURRENT_IR:\n{current_ir}\n\n"
        f"PRIOR_PATCH:\n{prior_patch}\n\n"
        f"DIAGNOSTICS:\n{diagnostics}\n"
    )
    return _generate_and_parse_json_with_retries(
        api_key=api_key,
        model=model,
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        max_attempts=max_attempts,
        debug_dir=debug_dir,
        artifact_prefix="repair_edit_patch",
    )


def mock_generate_edit_patch(request_text: str, current_ir: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic patch generator for demo/testing without an LLM.

    This is intentionally heuristic. It supports the common HITL edit requests used by
    `nlpipeline hitl-metrics` so the suite can be smoke-tested without an API key.
    Real runs should omit --mock and use the edit agent.
    """
    import copy
    import re

    t = request_text.lower()
    sm = current_ir.get("stateMachine") if isinstance(current_ir.get("stateMachine"), dict) else {}
    transitions = sm.get("transitions", []) if isinstance(sm.get("transitions"), list) else []

    def actions(tr: Dict[str, Any]) -> List[Dict[str, Any]]:
        acts = tr.get("actions")
        return [a for a in acts if isinstance(a, dict)] if isinstance(acts, list) else []

    def triggers(tr: Dict[str, Any]) -> List[Dict[str, Any]]:
        trigs = tr.get("triggers")
        return [tg for tg in trigs if isinstance(tg, dict)] if isinstance(trigs, list) else []

    def is_cmd(a: Dict[str, Any], device: str, command: str) -> bool:
        return a.get("type") == "command" and a.get("device") == device and a.get("command") == command

    def locator_for(tr: Dict[str, Any]) -> Dict[str, Any]:
        frm = str(tr.get("from", ""))
        to = str(tr.get("to", ""))
        idx = 0
        for prior in transitions:
            if prior is tr:
                break
            if isinstance(prior, dict) and prior.get("from") == frm and prior.get("to") == to:
                idx += 1
        out = {"from": frm, "to": to}
        if idx:
            out["index"] = idx
        return out

    def first_transition(pred) -> Optional[Dict[str, Any]]:
        for tr in transitions:
            if isinstance(tr, dict) and pred(tr):
                return tr
        return None

    def replace_expr_lit(expr: Any, device: str, path: str, old: str, new: str) -> bool:
        if not isinstance(expr, dict):
            return False
        changed = False
        if expr.get("op") in {"eq", "neq", "lt", "lte", "gt", "gte"}:
            args = expr.get("args") if isinstance(expr.get("args"), list) else []
            if len(args) >= 2:
                left, right = args[0], args[1]
                if isinstance(left, dict) and isinstance(left.get("ref"), dict) and isinstance(right, dict) and isinstance(right.get("lit"), dict):
                    ref = left["ref"]
                    lit = right["lit"]
                    if ref.get("device") == device and ref.get("path") == path and lit.get("string") == old:
                        right["lit"] = {"string": new}
                        changed = True
        for child in expr.get("args", []) if isinstance(expr.get("args"), list) else []:
            changed = replace_expr_lit(child, device, path, old, new) or changed
        return changed

    edits: List[Dict[str, Any]] = []

    # Change timeout/duration to N minutes/seconds.
    m = re.search(r"(\d+)\s*(minute|minutes)", t)
    m2 = re.search(r"(\d+)\s*(second|seconds|s)\b", t)
    secs: Optional[int] = None
    if m:
        secs = int(m.group(1)) * 60
    elif m2:
        secs = int(m2.group(1))
    if secs is not None and any(word in t for word in ["timeout", "duration", "minute", "second"]):
        tr = first_transition(lambda x: any(tg.get("type") == "after" for tg in triggers(x)))
        if tr is not None:
            new_trigs = copy.deepcopy(triggers(tr))
            for tg in new_trigs:
                if tg.get("type") == "after":
                    tg["seconds"] = secs
            edits.append({"op": "update_transition", **locator_for(tr), "triggers": new_trigs})
        else:
            tr = first_transition(lambda x: any(a.get("type") == "delay" for a in actions(x)))
            if tr is not None:
                new_acts = copy.deepcopy(actions(tr))
                for a in new_acts:
                    if a.get("type") == "delay":
                        a["seconds"] = secs
                edits.append({"op": "update_transition", **locator_for(tr), "actions": new_acts})

    # Change presence guard from not present to present.
    if "presence" in t and "present" in t and "not present" in t:
        tr = first_transition(lambda x: isinstance(x.get("guard"), dict))
        if tr is not None:
            g = copy.deepcopy(tr.get("guard"))
            if replace_expr_lit(g, "presence_user", "presence", "not present", "present"):
                edits.append({"op": "update_transition", **locator_for(tr), "guard": g})

    # Remove notify action while preserving other actions.
    if "remove" in t and "notification" in t:
        tr = first_transition(lambda x: any(a.get("type") == "notify" for a in actions(x)))
        if tr is not None:
            new_acts = [copy.deepcopy(a) for a in actions(tr) if a.get("type") != "notify"]
            edits.append({"op": "update_transition", **locator_for(tr), "actions": new_acts})

    # Add notification action.
    if "add" in t and "notification" in t:
        msg_match = re.search(r'"([^"]+)"', request_text)
        msg = msg_match.group(1) if msg_match else "Motion detected"
        tr = first_transition(lambda x: any(is_cmd(a, "light_hall", "off") for a in actions(x)) and any(is_cmd(a, "lock_front", "lock") for a in actions(x)))
        if tr is None:
            tr = first_transition(lambda x: actions(x))
        if tr is not None:
            new_acts = copy.deepcopy(actions(tr))
            new_acts.append({"type": "notify", "message": msg})
            edits.append({"op": "update_transition", **locator_for(tr), "actions": new_acts})

    # Change notification message.
    if "change" in t and "notification" in t and "message" in t:
        msg_match = re.search(r'"([^"]+)"', request_text)
        msg = msg_match.group(1) if msg_match else "Updated notification"
        tr = first_transition(lambda x: any(a.get("type") == "notify" for a in actions(x)))
        if tr is not None:
            new_acts = copy.deepcopy(actions(tr))
            for a in new_acts:
                if a.get("type") == "notify":
                    a["message"] = msg
            edits.append({"op": "update_transition", **locator_for(tr), "actions": new_acts})

    # Backwards-compatible simple demo edits.
    if not edits and "lightoff" in t:
        edits.append({"op": "set_state_label", "state_id": "Idle", "label": "LightOff"})

    if not edits:
        # Safe no-op so demos do not crash.
        initial = sm.get("initial") if isinstance(sm.get("initial"), str) else "Idle"
        edits.append({"op": "set_state_label", "state_id": initial, "label": initial})

    return {
        "summary": "Applied requested changes (mock).",
        "edits": edits,
    }

def _build_repair_patch_system_prompt(
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    current_ir: Dict[str, Any],
) -> str:
    """System prompt for Layer 6 repair agent (patch-based repairs)."""
    allowed_devices = [d["id"] for d in device_catalog.get("devices", []) if isinstance(d, dict) and "id" in d]
    globals_ = [g["id"] for g in device_catalog.get("globals", []) if isinstance(g, dict) and "id" in g]
    all_ids = sorted(set(allowed_devices + globals_))

    sm = current_ir.get("stateMachine", {}) if isinstance(current_ir.get("stateMachine"), dict) else {}
    states = [s.get("id") for s in sm.get("states", []) if isinstance(s, dict) and isinstance(s.get("id"), str)]
    transitions = []
    for t in sm.get("transitions", []) if isinstance(sm.get("transitions"), list) else []:
        if isinstance(t, dict):
            transitions.append({"from": t.get("from"), "to": t.get("to")})

    kind_specs = capability_catalog.get("kinds", {}) if isinstance(capability_catalog.get("kinds"), dict) else {}
    compact_kinds: Dict[str, Dict[str, List[str]]] = {}
    for k, spec in kind_specs.items():
        if not isinstance(spec, dict):
            continue
        attrs = list((spec.get("attributes") or {}).keys()) if isinstance(spec.get("attributes"), dict) else []
        cmds = list((spec.get("commands") or {}).keys()) if isinstance(spec.get("commands"), dict) else []
        compact_kinds[str(k)] = {"attributes": sorted(attrs), "commands": sorted(cmds)}

    return (
        "You are a REPAIR agent for a smart-home state-machine IR.\n"
        "Goal: produce a MINIMAL patch that fixes the reported errors.\n"
        "Output ONLY a JSON object (no markdown) with this exact shape:\n"
        "{\n"
        "  \"summary\": \"one or two sentences describing the fix\",\n"
        "  \"edits\": [ {\"op\":\"...\", ...}, ... ]\n"
        "}\n\n"
        "Allowed ops (ONLY these):\n"
        "- set_state_label(state_id,label)\n"
        "- set_initial(state_id)\n"
        "- add_state(state_id,label?)\n"
        "- remove_state(state_id)\n"
        "- add_transition(from,to,triggers?,guard?,actions?)\n"
        "- remove_transition(from,to,index?)\n"
        "- update_transition(from,to,index?,new_from?,new_to?,triggers?,guard?,actions?)\n\n"
        "Constraints:\n"
        "- Prefer the smallest change that resolves the error(s).\n"
        "- Do NOT invent new device ids; you may ONLY reference: " + str(all_ids) + "\n"
        "- Avoid renaming state IDs; prefer set_state_label.\n"
        "- If you include \"index\", it refers to the Nth transition (0-based) among transitions matching the same from/to pair.\n"
        "- Any triggers/actions you include MUST be valid IR objects per schema (types: becomes|changes|schedule|after, and command|delay|notify).\n"
        "- Every edit object MUST include a non-empty string op from the allowed list. Never use null/None for op.\n"
        "- If unsure, return an empty edits list rather than malformed edits.\n"
        "- For schedule triggers, use cron in the final patch payload, not time/at fields.\n"
        "- Do not encode conditions or comparisons inside actions[]. Use guard for conditions.\n\n"
        "Current state IDs:\n" + str(states) + "\n"
        "Current transition endpoints:\n" + str(transitions) + "\n\n"
        "Device kinds and their attributes/commands (for checking):\n" + str(compact_kinds) + "\n"
    )


def generate_repair_patch_with_llm(
    *,
    current_ir: Dict[str, Any],
    agentic_issues: List[Dict[str, Any]],
    deterministic_diagnostics: List[Dict[str, Any]],
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    debug_dir: Optional[Path] = None,
    max_attempts: int = 3,
    artifact_prefix: str = "generate_repair_patch",
) -> Dict[str, Any]:
    sys_prompt = _build_repair_patch_system_prompt(device_catalog, capability_catalog, ir_schema, current_ir)
    user_prompt = (
        "Fix the IR by returning a patch.\n"
        "Prioritize ERRORs over WARNINGs.\n"
        "Every edit must include a valid string op. If unsure, return edits:[].\n\n"
        f"AGENTIC_ISSUES: {agentic_issues}\n\n"
        f"DETERMINISTIC_DIAGNOSTICS: {deterministic_diagnostics}\n\n"
        f"CURRENT_IR: {current_ir}\n"
    )
    return _generate_and_parse_json_with_retries(
        api_key=api_key,
        model=model,
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        max_attempts=max_attempts,
        debug_dir=debug_dir,
        artifact_prefix=artifact_prefix,
    )


def repair_repair_patch_with_llm(
    *,
    current_ir: Dict[str, Any],
    agentic_issues: List[Dict[str, Any]],
    deterministic_diagnostics: List[Dict[str, Any]],
    prior_patch: Dict[str, Any],
    patch_error: str,
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
    debug_dir: Optional[Path] = None,
    max_attempts: int = 2,
    artifact_prefix: str = "repair_repair_patch",
) -> Dict[str, Any]:
    sys_prompt = _build_repair_patch_system_prompt(device_catalog, capability_catalog, ir_schema, current_ir)
    user_prompt = (
        "The prior patch failed to apply or produced invalid IR. Return a corrected patch JSON using ONLY allowed ops.\n"
        "Every edit must include a valid string op. If unsure, return edits:[].\n\n"
        f"AGENTIC_ISSUES: {agentic_issues}\n\n"
        f"DETERMINISTIC_DIAGNOSTICS: {deterministic_diagnostics}\n\n"
        f"CURRENT_IR: {current_ir}\n\n"
        f"PRIOR_PATCH: {prior_patch}\n\n"
        f"PATCH_ERROR: {patch_error}\n"
    )
    return _generate_and_parse_json_with_retries(
        api_key=api_key,
        model=model,
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        max_attempts=max_attempts,
        debug_dir=debug_dir,
        artifact_prefix=artifact_prefix,
    )


def mock_generate_repair_patch(
    *,
    current_ir: Dict[str, Any],
) -> Dict[str, Any]:
    """Deterministic fallback patch for demo/testing (Layer 6).

    Heuristics:
      - remove unreachable states (except initial)
      - remove duplicate/ambiguous transitions (keep first)
    """
    sm = current_ir.get("stateMachine") if isinstance(current_ir.get("stateMachine"), dict) else {}
    states = sm.get("states", []) if isinstance(sm.get("states"), list) else []
    transitions = sm.get("transitions", []) if isinstance(sm.get("transitions"), list) else []
    state_ids = [s.get("id") for s in states if isinstance(s, dict) and isinstance(s.get("id"), str)]
    state_set = set(state_ids)
    initial = sm.get("initial") if isinstance(sm.get("initial"), str) else None

    # Reachability
    adj: Dict[str, List[str]] = {}
    for t in transitions:
        if not isinstance(t, dict):
            continue
        frm, to = t.get("from"), t.get("to")
        if isinstance(frm, str) and isinstance(to, str):
            adj.setdefault(frm, []).append(to)

    reachable: set[str] = set()
    if initial and initial in state_set:
        stack = [initial]
        while stack:
            s = stack.pop()
            if s in reachable:
                continue
            reachable.add(s)
            for nxt in adj.get(s, []):
                if nxt in state_set and nxt not in reachable:
                    stack.append(nxt)

    edits: List[Dict[str, Any]] = []
    for sid in state_ids:
        if sid != initial and initial and sid not in reachable:
            edits.append({"op": "remove_state", "state_id": sid})

    # Ambiguous/duplicate transitions
    import json as _json
    def _sig(obj: Any) -> str:
        try:
            return _json.dumps(obj, sort_keys=True, ensure_ascii=False)
        except Exception:
            return str(obj)

    seen = set()
    for t in transitions:
        if not isinstance(t, dict):
            continue
        frm, to = t.get("from"), t.get("to")
        if not (isinstance(frm, str) and isinstance(to, str)):
            continue
        sig = (frm, _sig(t.get("triggers", [])), to)
        if sig in seen:
            edits.append({"op": "remove_transition", "from": frm, "to": to})
        else:
            seen.add(sig)

    if not edits:
        edits.append({"op": "set_state_label", "state_id": state_ids[0] if state_ids else "Idle", "label": state_ids[0] if state_ids else "Idle"})

    return {"summary": "Applied automatic repairs (mock).", "edits": edits}

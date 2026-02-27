from __future__ import annotations

from dataclasses import dataclass
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
        "- actions must be one of: command|delay|notify.\n\n"
        "Device kinds and their attributes/commands (for checking):\n"
        f"{compact_kinds}\n\n"
        "Guidelines:\n"
        "- Prefer 2–4 states max for simple automations.\n"
        "- Use enum values exactly (e.g., motion: active/inactive; switch: on/off; presence: present/'not present'; lock: locked/unlocked).\n"
        "- Prefer modeling time with an explicit timer transition: create an intermediate state and use a trigger {type:'after', seconds:N}.\n"
        "  (Example: motion->TimedLight (turn on), then TimedLight --after 30s--> Idle (turn off))\n"
        "- If you do use an ACTION delay, ensure it is followed by at least one action.\n"
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


def generate_ir_with_llm(
    text: str,
    *,
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
) -> Dict[str, Any]:
    sys_prompt = _build_system_prompt(device_catalog, capability_catalog, ir_schema)
    user_prompt = (
        "Convert this requirement into IR JSON:\n"
        f"REQUIREMENT: {text}\n"
    )

    res = openai_generate_json(api_key=api_key, model=model, system_prompt=sys_prompt, user_prompt=user_prompt)
    return try_extract_json(res.text)


def repair_ir_with_llm(
    ir: Dict[str, Any],
    diagnostics: List[Dict[str, Any]],
    *,
    api_key: str,
    model: str,
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
    ir_schema: Dict[str, Any],
) -> Dict[str, Any]:
    sys_prompt = _build_system_prompt(device_catalog, capability_catalog, ir_schema)
    user_prompt = (
        "Fix the following IR JSON so it passes validation.\n"
        "Return ONLY corrected JSON.\n\n"
        f"DIAGNOSTICS: {diagnostics}\n\n"
        f"IR: {ir}\n"
    )
    res = openai_generate_json(api_key=api_key, model=model, system_prompt=sys_prompt, user_prompt=user_prompt)
    return try_extract_json(res.text)


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
) -> Dict[str, Any]:
    sys_prompt = _build_edit_patch_system_prompt(device_catalog, capability_catalog, ir_schema, current_ir)
    user_prompt = (
        "CHANGE_REQUEST:\n"
        f"{request_text}\n\n"
        "CURRENT_IR:\n"
        f"{current_ir}\n"
    )
    res = openai_generate_json(api_key=api_key, model=model, system_prompt=sys_prompt, user_prompt=user_prompt)
    return try_extract_json(res.text)


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
) -> Dict[str, Any]:
    sys_prompt = _build_edit_patch_system_prompt(device_catalog, capability_catalog, ir_schema, current_ir)
    user_prompt = (
        "The prior patch produced validation errors after being applied.\n"
        "Return a corrected patch JSON using ONLY allowed ops.\n\n"
        f"CHANGE_REQUEST:\n{request_text}\n\n"
        f"CURRENT_IR:\n{current_ir}\n\n"
        f"PRIOR_PATCH:\n{prior_patch}\n\n"
        f"DIAGNOSTICS:\n{diagnostics}\n"
    )
    res = openai_generate_json(api_key=api_key, model=model, system_prompt=sys_prompt, user_prompt=user_prompt)
    return try_extract_json(res.text)


def mock_generate_edit_patch(request_text: str, current_ir: Dict[str, Any]) -> Dict[str, Any]:
    """Very small deterministic patch generator for demo/testing without an LLM."""
    t = request_text.lower()
    edits: List[Dict[str, Any]] = []

    # common demo edits
    if "lightoff" in t:
        edits.append({"op": "set_state_label", "state_id": "Idle", "label": "LightOff"})

    # timer: "2 minutes" or "120s"
    import re
    m = re.search(r"(\d+)\s*(minute|minutes)", t)
    if m:
        secs = int(m.group(1)) * 60
        edits.append({
            "op": "update_transition",
            "from": "WaitOff",
            "to": "Idle",
            "triggers": [{"type": "after", "seconds": secs}],
        })
    m2 = re.search(r"(\d+)\s*(second|seconds|s)\b", t)
    if m2:
        secs = int(m2.group(1))
        edits.append({
            "op": "update_transition",
            "from": "WaitOff",
            "to": "Idle",
            "triggers": [{"type": "after", "seconds": secs}],
        })

    if "notify" in t:
        edits.append({
            "op": "update_transition",
            "from": "Idle",
            "to": "LightOn",
            "actions": [
                {"type": "command", "ref": {"device": "light_hall"}, "command": "on", "args": []},
                {"type": "notify", "message": "Motion detected"},
            ],
        })

    if not edits:
        edits.append({"op": "set_state_label", "state_id": "Idle", "label": "Idle"})  # no-op

    return {
        "summary": "Applied requested changes (mock).",
        "edits": edits,
    }
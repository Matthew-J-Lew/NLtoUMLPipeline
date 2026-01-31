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
        "- Use a stateMachine with an initial state, states[], and transitions[].\n"
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
        )
    except Exception:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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

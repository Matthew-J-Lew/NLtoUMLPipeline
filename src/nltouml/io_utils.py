from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def try_extract_json(text: str) -> Any:
    """Extract JSON from a model output that may include code fences or extra text."""
    text = text.strip()

    # 1) Remove common markdown fences first.
    if "```" in text:
        parts = text.split("```")
        candidates: list[str] = []
        for p in parts:
            p = p.strip()
            # ```json
            if p.lower().startswith("json"):
                p = p[4:].strip()
            if "{" in p and "}" in p:
                candidates.append(p)
        if candidates:
            candidates.sort(key=len, reverse=True)
            text = candidates[0].strip()

    # 2) Robustly parse the FIRST JSON object we can find.
    # This avoids JSONDecodeError("Extra data") when the model returns:
    #   { ...valid json... }\n\nSure! Here's the JSON... (etc)
    start = text.find("{")
    if start == -1:
        raise ValueError("Could not extract JSON (no '{' found)")

    decoder = json.JSONDecoder()
    obj, idx = decoder.raw_decode(text[start:])
    # idx is relative to text[start:]
    tail = text[start + idx :].strip()
    # If there is trailing non-whitespace, we ignore it on purpose.
    # (This is the main fix for the user's intermittent 'Extra data' crash.)
    return obj

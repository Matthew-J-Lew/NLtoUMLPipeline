from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import copy

from .config import Settings
from .io_utils import read_json, write_json, write_text
from .layout import (
    allocate_edit_dir,
    ensure_bundle_dirs,
    update_current,
    write_manifest,
    build_revision_record,
)
from .normalize import coerce_ir_shape, normalize_ir
from .transform import desugar_delays_to_timer_states
from .plantuml import ir_to_plantuml
from .validate import validate_all, Diagnostic
from .pipeline import PipelineError, load_templates
from .llm import (
    generate_edit_patch_with_llm,
    repair_edit_patch_with_llm,
    mock_generate_edit_patch,
)

# Reuse the lightweight IR diff used by roundtrip (good enough for stakeholders)
from .roundtrip import _simple_ir_diff  # type: ignore


def _bundle_paths(out_dir: Path, bundle_name: str) -> Dict[str, Path]:
    bundle_root = out_dir / bundle_name
    layout = ensure_bundle_dirs(bundle_root)
    return {
        "bundle_root": bundle_root,
        "baseline_dir": layout.baseline_dir,
        "current_dir": layout.current_dir,
    }


def _load_parent_ir(bundle_root: Path) -> Tuple[Dict[str, Any], Path]:
    """Read the current canonical IR (preferred), otherwise fall back to baseline."""
    cur = bundle_root / "current" / "final.ir.json"
    if cur.exists():
        return read_json(cur), cur
    base = bundle_root / "baseline" / "final.ir.json"
    if base.exists():
        return read_json(base), base
    raise PipelineError(
        f"Could not find a parent IR to edit. Expected one of:\n"
        f"  - {cur}\n"
        f"  - {base}\n"
        f"Run: nlpipeline run --bundle-name {bundle_root.name} --text \"...\""
    )


def _find_state(sm: Dict[str, Any], state_id: str) -> Optional[Dict[str, Any]]:
    for s in sm.get("states", []) or []:
        if isinstance(s, dict) and s.get("id") == state_id:
            return s
    return None


def _ensure_state(sm: Dict[str, Any], state_id: str) -> Dict[str, Any]:
    s = _find_state(sm, state_id)
    if s is not None:
        return s
    new_s = {"id": state_id}
    sm.setdefault("states", []).append(new_s)
    return new_s


def _match_transition(
    sm: Dict[str, Any],
    *,
    from_id: str,
    to_id: str,
    index: Optional[int] = None,
) -> Dict[str, Any]:
    """Match a transition by endpoints.

    If index is provided, it refers to the Nth match (0-based) among transitions
    that have the same (from_id, to_id) pair (NOT the global transitions[] index).
    """
    ts = sm.get("transitions", [])
    if not isinstance(ts, list):
        raise PipelineError("IR is missing stateMachine.transitions[] list")

    matches = [
        t for t in ts
        if isinstance(t, dict) and t.get("from") == from_id and t.get("to") == to_id
    ]

    if not matches:
        raise PipelineError(f"No transition found from '{from_id}' to '{to_id}'")

    if index is None:
        if len(matches) > 1:
            raise PipelineError(
                f"Multiple transitions found from '{from_id}' to '{to_id}'. "
                f"Specify an explicit transition index (0..{len(matches)-1}) among matches."
            )
        return matches[0]

    if index < 0 or index >= len(matches):
        raise PipelineError(f"transition index out of range for {from_id}->{to_id}: {index}")
    return matches[index]


    if index is not None:
        if index < 0 or index >= len(ts):
            raise PipelineError(f"transition index out of range: {index}")
        t = ts[index]
        if not isinstance(t, dict):
            raise PipelineError(f"transition at index {index} is not an object")
        return t

    matches = []
    for t in ts:
        if not isinstance(t, dict):
            continue
        if t.get("from") == from_id and t.get("to") == to_id:
            matches.append(t)

    if not matches:
        raise PipelineError(f"No transition found from '{from_id}' to '{to_id}'")
    if len(matches) > 1:
        raise PipelineError(
            f"Multiple transitions found from '{from_id}' to '{to_id}'. "
            f"Specify an explicit transition index in the patch."
        )
    return matches[0]


def _remove_transition(
    sm: Dict[str, Any],
    *,
    from_id: str,
    to_id: str,
    index: Optional[int] = None,
) -> None:
    """Remove a transition by endpoints.

    If index is provided, it refers to the Nth match (0-based) among transitions
    that have the same (from_id, to_id) pair (NOT the global transitions[] index).
    """
    ts = sm.get("transitions", [])
    if not isinstance(ts, list):
        return

    match_idxs = [
        i for i, t in enumerate(ts)
        if isinstance(t, dict) and t.get("from") == from_id and t.get("to") == to_id
    ]
    if not match_idxs:
        return

    if index is None:
        ts.pop(match_idxs[0])
        return

    if index < 0 or index >= len(match_idxs):
        raise PipelineError(f"transition index out of range for {from_id}->{to_id}: {index}")
    ts.pop(match_idxs[index])


    # remove first match
    for i, t in enumerate(ts):
        if isinstance(t, dict) and t.get("from") == from_id and t.get("to") == to_id:
            ts.pop(i)
            return


def apply_ir_patch(parent_ir: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a constrained patch (from the edit agent) to a parent IR.

    Patch format:
      { "summary": "...", "edits": [ { "op": "...", ... }, ... ] }
    """
    ir = copy.deepcopy(parent_ir)
    sm = ir.get("stateMachine")
    if not isinstance(sm, dict):
        raise PipelineError("IR missing stateMachine object")

    edits = patch.get("edits", [])
    if not isinstance(edits, list):
        raise PipelineError("Patch must contain edits[] list")

    for e in edits:
        if not isinstance(e, dict):
            continue
        op = e.get("op")

        if op == "set_state_label":
            sid = str(e.get("state_id", ""))
            lbl = e.get("label")
            if not sid or not isinstance(lbl, str):
                raise PipelineError("set_state_label requires state_id (str) and label (str)")
            s = _ensure_state(sm, sid)
            s["label"] = lbl
            continue

        if op == "set_initial":
            sid = str(e.get("state_id", ""))
            if not sid:
                raise PipelineError("set_initial requires state_id")
            _ensure_state(sm, sid)
            sm["initial"] = sid
            continue

        if op == "add_state":
            sid = str(e.get("state_id", ""))
            if not sid:
                raise PipelineError("add_state requires state_id")
            s = _ensure_state(sm, sid)
            lbl = e.get("label")
            if isinstance(lbl, str) and lbl:
                s["label"] = lbl
            continue

        if op == "remove_state":
            sid = str(e.get("state_id", ""))
            if not sid:
                raise PipelineError("remove_state requires state_id")
            # remove state
            states = sm.get("states", [])
            if isinstance(states, list):
                sm["states"] = [s for s in states if not (isinstance(s, dict) and s.get("id") == sid)]
            # remove transitions touching it
            ts = sm.get("transitions", [])
            if isinstance(ts, list):
                sm["transitions"] = [
                    t for t in ts
                    if not (isinstance(t, dict) and (t.get("from") == sid or t.get("to") == sid))
                ]
            # if initial points to it, leave as-is (validator can catch)
            continue

        if op == "remove_transition":
            from_id = str(e.get("from", ""))
            to_id = str(e.get("to", ""))
            idx = e.get("index")
            index = int(idx) if isinstance(idx, int) else None
            if not from_id or not to_id:
                raise PipelineError("remove_transition requires from and to")
            _remove_transition(sm, from_id=from_id, to_id=to_id, index=index)
            continue

        if op == "add_transition":
            from_id = str(e.get("from", ""))
            to_id = str(e.get("to", ""))
            if not from_id or not to_id:
                raise PipelineError("add_transition requires from and to")
            _ensure_state(sm, from_id)
            _ensure_state(sm, to_id)

            t: Dict[str, Any] = {"from": from_id, "to": to_id}
            if "triggers" in e:
                t["triggers"] = e["triggers"]
            if "guard" in e:
                t["guard"] = e["guard"]
            if "actions" in e:
                t["actions"] = e["actions"]

            sm.setdefault("transitions", []).append(t)
            continue

        if op == "update_transition":
            from_id = str(e.get("from", ""))
            to_id = str(e.get("to", ""))
            idx = e.get("index")
            index = int(idx) if isinstance(idx, int) else None
            if not from_id or not to_id:
                raise PipelineError("update_transition requires from and to (and optional index)")
            t = _match_transition(sm, from_id=from_id, to_id=to_id, index=index)

            # allow updating triggers/actions/guard and also changing endpoints
            if "new_from" in e and isinstance(e["new_from"], str) and e["new_from"]:
                nf = e["new_from"]
                _ensure_state(sm, nf)
                t["from"] = nf
            if "new_to" in e and isinstance(e["new_to"], str) and e["new_to"]:
                nt = e["new_to"]
                _ensure_state(sm, nt)
                t["to"] = nt

            if "triggers" in e:
                t["triggers"] = e["triggers"]
            if "guard" in e:
                t["guard"] = e["guard"]
            if "actions" in e:
                t["actions"] = e["actions"]
            continue

        raise PipelineError(f"Unsupported patch op: {op}")

    return ir


def _diff_summary(diff: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if diff.get("initial", {}).get("baseline") != diff.get("initial", {}).get("edited"):
        lines.append(
            f"- initial: {diff['initial'].get('baseline')} → {diff['initial'].get('edited')}"
        )
    states_added = diff.get("states_added") or []
    states_removed = diff.get("states_removed") or []
    if states_added:
        lines.append(f"- states added ({len(states_added)}): {states_added}")
    if states_removed:
        lines.append(f"- states removed ({len(states_removed)}): {states_removed}")
    ta = diff.get("transitions_added") or []
    tr = diff.get("transitions_removed") or []
    if ta:
        lines.append(f"- transitions added ({len(ta)})")
    if tr:
        lines.append(f"- transitions removed ({len(tr)})")
    return lines


def run_agent_edit(
    *,
    bundle_name: str,
    out_dir: Path,
    request_text: str,
    settings: Settings,
    use_mock: bool = False,
    max_repairs: int = 1,
) -> Tuple[Dict[str, Path], List[str]]:
    """Agent-driven edit: NL change request -> patch IR -> validate -> regenerate PUML -> new edit_### revision."""
    paths = _bundle_paths(out_dir, bundle_name)
    bundle_root = paths["bundle_root"]

    if not bundle_root.exists():
        raise PipelineError(f"Bundle does not exist: {bundle_root}. Run `nlpipeline run --bundle-name {bundle_name}` first.")

    ir_schema, device_catalog, capability_catalog = load_templates(settings.templates_dir)

    parent_ir, parent_ir_path = _load_parent_ir(bundle_root)

    # Allocate a new edit revision folder
    revision_dir = allocate_edit_dir(bundle_root)

    # Write the source request
    req_path = revision_dir / "source.request.txt"
    write_text(req_path, request_text)

    # Generate patch (and repair once if needed)
    if use_mock:
        patch = mock_generate_edit_patch(request_text, parent_ir)
    else:
        if not settings.openai_api_key:
            raise PipelineError("OPENAI_API_KEY not set. Either set it, or run with --mock.")
        patch = generate_edit_patch_with_llm(
            request_text=request_text,
            current_ir=parent_ir,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            device_catalog=device_catalog,
            capability_catalog=capability_catalog,
            ir_schema=ir_schema,
        )

    # Apply patch -> IR (raw)
    try:
        raw_ir = apply_ir_patch(parent_ir, patch)
    except Exception as e:
        # Write what we can and return an error report
        write_json(revision_dir / "agent.patch.json", patch)
        report = {
            "ok": False,
            "diagnostics": [{
                "severity": "error",
                "code": "E900",
                "path": "$",
                "message": f"Failed to apply patch: {e}",
            }],
            "patches": [],
        }
        write_json(revision_dir / "validation_report.json", report)
        summary_lines = [
            "Agent edit FAILED (patch could not be applied).",
            f"Revision: {revision_dir}",
            f"Reason: {e}",
        ]
        out_paths = {
            "bundle_root": bundle_root,
            "revision_dir": revision_dir,
            "request": req_path,
            "patch": revision_dir / "agent.patch.json",
            "validation": revision_dir / "validation_report.json",
        }
        # Do not update current
        write_manifest(
            bundle_root,
            {
                "current": {"points_to": "unchanged"},
                "append_revision": {
                    **build_revision_record(kind="agent_edit_failed", revision_dir=revision_dir, diff_against=parent_ir_path),
                    "request": str(req_path.as_posix()),
                },
            },
        )
        return out_paths, summary_lines

    write_json(revision_dir / "agent.patch.json", patch)
    write_json(revision_dir / "raw.ir.json", raw_ir)

    # Normalize + validate + regenerate
    def compile_and_validate(ir0: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        ir1 = coerce_ir_shape(ir0, device_catalog)
        ir1 = normalize_ir(ir1)
        ir1 = desugar_delays_to_timer_states(ir1)
        diags, patches = validate_all(ir1, ir_schema, device_catalog, capability_catalog)
        report = {
            "ok": not any(d.severity == "error" for d in diags),
            "diagnostics": [asdict(d) for d in diags],
            "patches": [asdict(p) for p in patches],
        }
        return ir1, report

    final_ir, report = compile_and_validate(raw_ir)

    # Optional repair loop: ask the agent to fix the PATCH (not rewrite IR)
    repairs = 0
    while (not use_mock) and repairs < max_repairs and (not report.get("ok", False)):
        repairs += 1
        diag_payload = report.get("diagnostics", [])
        patch = repair_edit_patch_with_llm(
            request_text=request_text,
            current_ir=parent_ir,
            prior_patch=patch,
            diagnostics=diag_payload,
            api_key=settings.openai_api_key or "",
            model=settings.openai_model,
            device_catalog=device_catalog,
            capability_catalog=capability_catalog,
            ir_schema=ir_schema,
        )
        raw_ir = apply_ir_patch(parent_ir, patch)
        write_json(revision_dir / "agent.patch.json", patch)
        write_json(revision_dir / "raw.ir.json", raw_ir)
        final_ir, report = compile_and_validate(raw_ir)

    write_json(revision_dir / "final.ir.json", final_ir)
    write_json(revision_dir / "validation_report.json", report)

    puml = ir_to_plantuml(final_ir, title=bundle_name)
    write_text(revision_dir / "final.puml", puml)

    diff = _simple_ir_diff(parent_ir, final_ir)
    write_json(revision_dir / "diff.json", diff)

    # Write a human-facing summary inside the revision
    agent_summary = patch.get("summary") if isinstance(patch, dict) else None
    if not isinstance(agent_summary, str) or not agent_summary.strip():
        agent_summary = "Applied requested changes."

    diff_lines = _diff_summary(diff)
    ok = bool(report.get("ok", False))
    summary_md = "\n".join([
        "# Agent Edit Summary",
        "",
        f"**Request:** {request_text}",
        "",
        f"**Agent summary:** {agent_summary}",
        "",
        "## Diff summary",
        *(diff_lines or ["- (no structural changes detected)"]),
        "",
        f"## Validation status",
        f"- {'✅ OK' if ok else '❌ FAILED'}",
        "",
    ])
    write_text(revision_dir / "summary.md", summary_md)

    # Update manifest + (optionally) current pointer
    points_to = f"edits/{revision_dir.name}"
    write_manifest(
        bundle_root,
        {
            "current": {"points_to": points_to if ok else "unchanged"},
            "append_revision": {
                **build_revision_record(kind="agent_edit", revision_dir=revision_dir, diff_against=parent_ir_path),
                "request": str(req_path.as_posix()),
                "ok": ok,
            },
        },
    )
    if ok:
        update_current(bundle_root, revision_dir)

    # CLI summary lines
    summary_lines = [
        f"Agent summary: {agent_summary}",
        "Diff summary:",
        *(diff_lines or ["- (no structural changes detected)"]),
        f"Validation: {'OK' if ok else 'FAILED'}",
        f"Revision written: {revision_dir}",
        f"Regenerated diagram: {revision_dir / 'final.puml'}",
        f"Updated current: {'YES' if ok else 'NO'}",
    ]

    out_paths = {
        "bundle_root": bundle_root,
        "revision_dir": revision_dir,
        "request": req_path,
        "patch": revision_dir / "agent.patch.json",
        "raw_ir": revision_dir / "raw.ir.json",
        "ir": revision_dir / "final.ir.json",
        "puml": revision_dir / "final.puml",
        "validation": revision_dir / "validation_report.json",
        "diff": revision_dir / "diff.json",
        "summary": revision_dir / "summary.md",
    }
    return out_paths, summary_lines
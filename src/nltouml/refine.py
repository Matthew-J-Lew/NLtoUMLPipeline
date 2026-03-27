from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import copy
import hashlib
import json

from .config import Settings
from .io_utils import read_json, write_json, write_text
from .layout import allocate_edit_dir, ensure_bundle_dirs, update_current, write_manifest, build_revision_record
from .normalize import coerce_ir_shape, normalize_ir
from .transform import desugar_delays_to_timer_states
from .plantuml import ir_to_plantuml
from .validate import validate_all
from .pipeline import PipelineError, load_templates
from .agent_edit import apply_ir_patch
from .agent_validate import validate_agentic
from .llm import (
    generate_repair_patch_with_llm,
    repair_repair_patch_with_llm,
    mock_generate_repair_patch,
)
from .patch_utils import patch_validation_error_message, validate_patch_structure

# Reuse lightweight diff used elsewhere
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
        f"Could not find a parent IR to refine. Expected one of:\n"
        f"  - {cur}\n"
        f"  - {base}\n"
        f"Run: nlpipeline run --bundle-name {bundle_root.name} --text \"...\""
    )


def _hash_ir(ir: Dict[str, Any]) -> str:
    try:
        blob = json.dumps(ir, sort_keys=True, ensure_ascii=False).encode("utf-8")
    except Exception:
        blob = repr(ir).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _compile_and_validate(
    ir0: Dict[str, Any],
    *,
    ir_schema: Dict[str, Any],
    device_catalog: Dict[str, Any],
    capability_catalog: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Layer 4 (+ canonicalization): coerce -> normalize -> desugar -> deterministic validate -> L5 agentic validate."""
    ir1 = coerce_ir_shape(ir0, device_catalog)
    ir1 = normalize_ir(ir1)
    ir1 = desugar_delays_to_timer_states(ir1)

    diags, patches = validate_all(ir1, ir_schema, device_catalog, capability_catalog)
    det_report = {
        "ok": not any(d.severity == "error" for d in diags),
        "diagnostics": [asdict(d) for d in diags],
        "patches": [asdict(p) for p in patches],
    }

    _issues, agent_report = validate_agentic(ir1)
    return ir1, det_report, agent_report


def _write_failure_summary(
    *,
    revision_dir: Path,
    bundle_name: str,
    parent_ir_path: Path,
    iterations_run: int,
    stage: str,
    reason: str,
    current_ir: Dict[str, Any],
) -> None:
    summary_obj = {
        "bundle_name": bundle_name,
        "start_ir_path": parent_ir_path.as_posix(),
        "iterations_run": iterations_run,
        "stop_reason": f"{stage}: {reason}",
        "deterministic_ok": False,
        "layer5_ok": False,
        "overall_ok": False,
        "failure_stage": stage,
        "failure_reason": reason,
    }
    write_json(revision_dir / "failure.current_ir.json", current_ir)
    write_json(revision_dir / "summary.json", summary_obj)
    summary_lines_md = [
        "# Agentic Refine Summary",
        "",
        f"- **Bundle:** {bundle_name}",
        f"- **Start IR:** {parent_ir_path.as_posix()}",
        f"- **Iterations run:** {iterations_run}",
        f"- **Stop reason:** {stage}: {reason}",
        "",
        "## Final status",
        "- Deterministic validation: ❌ FAILED",
        "- Layer 5 (agentic) checks: ❌ FAILED",
        "- Overall: ❌ FAILED",
        "",
    ]
    write_text(revision_dir / "summary.md", "\n".join(summary_lines_md) + "\n")


def run_refine(
    *,
    bundle_name: str,
    out_dir: Path,
    settings: Settings,
    use_mock: bool = False,
    max_iters: int = 5,
    max_patch_repairs: int = 2,
) -> Tuple[Dict[str, Path], List[str]]:
    """Layers 5–7: agentic validate+repair loop over the CURRENT IR.

    Writes a single new outputs/<bundle>/edits/edit_### revision containing:
      - iterations/iter_###/* (per-loop artifacts)
      - final.ir.json, final.puml, validation_report.json (deterministic Layer 4 report)
      - layer5_report.json (agentic report)
      - diff.json, summary.md
    Updates outputs/<bundle>/current/* ONLY if the final artifacts are OK.
    """
    paths = _bundle_paths(out_dir, bundle_name)
    bundle_root = paths["bundle_root"]

    if not bundle_root.exists():
        raise PipelineError(f"Bundle does not exist: {bundle_root}. Run `nlpipeline run --bundle-name {bundle_name}` first.")

    ir_schema, device_catalog, capability_catalog = load_templates(settings.templates_dir)
    parent_ir, parent_ir_path = _load_parent_ir(bundle_root)

    # Allocate new revision directory
    revision_dir = allocate_edit_dir(bundle_root)
    (revision_dir / "iterations").mkdir(parents=True, exist_ok=True)

    write_json(revision_dir / "source.parent_ir.json", parent_ir)
    write_text(revision_dir / "source.parent_ir_path.txt", str(parent_ir_path.as_posix()))

    # Start from parent IR
    cur_ir = copy.deepcopy(parent_ir)
    seen_hashes: set[str] = set()

    # Baseline validation report for the parent
    compiled, det_report, layer5_report = _compile_and_validate(
        cur_ir,
        ir_schema=ir_schema,
        device_catalog=device_catalog,
        capability_catalog=capability_catalog,
    )
    cur_ir = compiled
    write_json(revision_dir / "source.validation_report.json", det_report)
    write_json(revision_dir / "source.l5.validation_agent.json", layer5_report)

    ok_det = bool(det_report.get("ok", False))
    ok_l5 = bool(layer5_report.get("ok", False))

    iterations_run = 0
    stop_reason = ""
    last_patch: Optional[Dict[str, Any]] = None
    last_patch_summary = ""

    try:
        for it in range(1, max(1, int(max_iters)) + 1):
            iterations_run = it
            h = _hash_ir(cur_ir)
            if h in seen_hashes:
                stop_reason = "Detected oscillation (IR repeated)."
                break
            seen_hashes.add(h)

            iter_dir = revision_dir / "iterations" / f"iter_{it:03d}"
            iter_dir.mkdir(parents=True, exist_ok=False)
            llm_debug_dir = iter_dir / "llm"

            # Record current state
            write_json(iter_dir / "input.ir.json", cur_ir)
            write_json(iter_dir / "validation_report.json", det_report)
            write_json(iter_dir / "l5.validation_agent.json", layer5_report)

            ok_det = bool(det_report.get("ok", False))
            ok_l5 = bool(layer5_report.get("ok", False))
            if ok_det and ok_l5:
                stop_reason = "Converged (deterministic + agentic OK)."
                break

            # Layer 6: produce a PATCH (not a rewritten IR)
            agentic_issues = layer5_report.get("issues", []) if isinstance(layer5_report.get("issues"), list) else []
            deterministic_diags = det_report.get("diagnostics", []) if isinstance(det_report.get("diagnostics"), list) else []

            if use_mock:
                patch = mock_generate_repair_patch(current_ir=cur_ir)
            else:
                if not settings.openai_api_key:
                    raise PipelineError("OPENAI_API_KEY not set. Either set it, or run with --mock.")
                patch = generate_repair_patch_with_llm(
                    current_ir=cur_ir,
                    agentic_issues=agentic_issues,
                    deterministic_diagnostics=deterministic_diags,
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    device_catalog=device_catalog,
                    capability_catalog=capability_catalog,
                    ir_schema=ir_schema,
                    debug_dir=llm_debug_dir,
                    max_attempts=3,
                    artifact_prefix="generate_repair_patch",
                )

            raw_ir: Optional[Dict[str, Any]] = None
            patch_attempt = 0
            max_patch_attempts = 1 + max(0, int(max_patch_repairs))
            last_patch_error = ""

            while patch_attempt < max_patch_attempts:
                patch_attempt += 1
                patch_path = iter_dir / f"l6.repair_agent.patch.attempt_{patch_attempt:02d}.json"
                patch_validation_path = iter_dir / f"l6.repair_agent.patch.attempt_{patch_attempt:02d}.validation.json"
                patch_error_path = iter_dir / f"l6.repair_agent.patch.attempt_{patch_attempt:02d}.error.txt"
                write_json(patch_path, patch)

                patch_validation = validate_patch_structure(patch)
                write_json(patch_validation_path, patch_validation)
                if not patch_validation.get("ok", False):
                    last_patch_error = patch_validation_error_message(patch_validation)
                    write_text(patch_error_path, last_patch_error)
                    if use_mock or patch_attempt >= max_patch_attempts:
                        break
                    patch = repair_repair_patch_with_llm(
                        current_ir=cur_ir,
                        agentic_issues=agentic_issues,
                        deterministic_diagnostics=deterministic_diags,
                        prior_patch=patch,
                        patch_error=last_patch_error,
                        api_key=settings.openai_api_key or "",
                        model=settings.openai_model,
                        device_catalog=device_catalog,
                        capability_catalog=capability_catalog,
                        ir_schema=ir_schema,
                        debug_dir=llm_debug_dir,
                        max_attempts=2,
                        artifact_prefix=f"repair_repair_patch_attempt_{patch_attempt:02d}",
                    )
                    continue

                sanitized_patch = patch_validation.get("sanitized_patch", patch)
                try:
                    raw_ir = apply_ir_patch(cur_ir, sanitized_patch)
                    patch = sanitized_patch
                    write_json(iter_dir / "l6.repair_agent.patch.json", patch)
                    write_json(iter_dir / "l6.repair_agent.patch.validation.json", patch_validation)
                    break
                except Exception as e:
                    last_patch_error = f"Patch apply failure: {e}"
                    write_text(patch_error_path, last_patch_error)
                    if use_mock or patch_attempt >= max_patch_attempts:
                        break
                    patch = repair_repair_patch_with_llm(
                        current_ir=cur_ir,
                        agentic_issues=agentic_issues,
                        deterministic_diagnostics=deterministic_diags,
                        prior_patch=patch,
                        patch_error=last_patch_error,
                        api_key=settings.openai_api_key or "",
                        model=settings.openai_model,
                        device_catalog=device_catalog,
                        capability_catalog=capability_catalog,
                        ir_schema=ir_schema,
                        debug_dir=llm_debug_dir,
                        max_attempts=2,
                        artifact_prefix=f"repair_repair_patch_attempt_{patch_attempt:02d}",
                    )

            if raw_ir is None:
                failure_reason = last_patch_error or "Unknown repair patch failure."
                _write_failure_summary(
                    revision_dir=revision_dir,
                    bundle_name=bundle_name,
                    parent_ir_path=parent_ir_path,
                    iterations_run=iterations_run,
                    stage="Patch repair failed",
                    reason=failure_reason,
                    current_ir=cur_ir,
                )
                raise PipelineError(
                    f"Failed to produce/apply a valid repair patch after {max_patch_attempts} attempt(s): {failure_reason}. "
                    f"See {revision_dir.as_posix()} for patch validation and raw LLM artifacts."
                )

            last_patch = patch
            if isinstance(last_patch, dict):
                ps = last_patch.get("summary")
                if isinstance(ps, str):
                    last_patch_summary = ps.strip()
            write_json(iter_dir / "raw.ir.json", raw_ir)

            # Re-compile and validate after applying patch
            compiled, det_report, layer5_report = _compile_and_validate(
                raw_ir,
                ir_schema=ir_schema,
                device_catalog=device_catalog,
                capability_catalog=capability_catalog,
            )
            cur_ir = compiled

            write_json(iter_dir / "final.ir.json", cur_ir)
            write_json(iter_dir / "validation_report.after.json", det_report)
            write_json(iter_dir / "l5.validation_agent.after.json", layer5_report)

            puml = ir_to_plantuml(cur_ir, title=bundle_name)
            write_text(iter_dir / "final.puml", puml)
    except Exception:
        # Partial artifacts have already been written above.
        raise

    # Final artifacts at revision root (Layer 7 canonical output boundary)
    final_ir, final_det_report, final_layer5_report = _compile_and_validate(
        cur_ir,
        ir_schema=ir_schema,
        device_catalog=device_catalog,
        capability_catalog=capability_catalog,
    )
    cur_ir = final_ir

    write_json(revision_dir / "final.ir.json", cur_ir)
    write_json(revision_dir / "validation_report.json", final_det_report)
    write_json(revision_dir / "l5.validation_agent.json", final_layer5_report)

    puml = ir_to_plantuml(cur_ir, title=bundle_name)
    write_text(revision_dir / "final.puml", puml)

    diff = _simple_ir_diff(parent_ir, cur_ir)
    write_json(revision_dir / "diff.json", diff)

    ok_det = bool(final_det_report.get("ok", False))
    ok_l5 = bool(final_layer5_report.get("ok", False))
    ok = ok_det and ok_l5

    # Summary.md
    summary_lines_md: List[str] = [
        "# Agentic Refine Summary",
        "",
        f"- **Bundle:** {bundle_name}",
        f"- **Start IR:** {parent_ir_path.as_posix()}",
        f"- **Iterations run:** {iterations_run}",
        f"- **Stop reason:** {stop_reason or 'Reached max iterations.'}",
        "",
        "## Final status",
        f"- Deterministic validation: {'✅ OK' if ok_det else '❌ FAILED'}",
        f"- Layer 5 (agentic) checks: {'✅ OK' if ok_l5 else '❌ FAILED'}",
        f"- Overall: {'✅ OK' if ok else '❌ FAILED'}",
        "",
    ]
    if last_patch_summary:
        summary_lines_md += ["## Last repair patch summary", last_patch_summary, ""]

    write_text(revision_dir / "summary.md", "\n".join(summary_lines_md) + "\n")

    summary_obj = {
        "bundle_name": bundle_name,
        "start_ir_path": parent_ir_path.as_posix(),
        "iterations_run": iterations_run,
        "stop_reason": stop_reason or "Reached max iterations.",
        "deterministic_ok": ok_det,
        "layer5_ok": ok_l5,
        "overall_ok": ok,
        "last_patch_summary": last_patch_summary,
    }
    write_json(revision_dir / "summary.json", summary_obj)

    # Manifest + current pointer
    points_to = f"edits/{revision_dir.name}"
    write_manifest(
        bundle_root,
        {
            "current": {"points_to": points_to if ok else "unchanged"},
            "append_revision": {
                **build_revision_record(kind="agent_refine", revision_dir=revision_dir, diff_against=parent_ir_path),
                "ok": ok,
                "iterations": iterations_run,
                "stop_reason": stop_reason or "Reached max iterations.",
            },
        },
    )
    if ok:
        update_current(bundle_root, revision_dir)

    # CLI summary
    summary_lines = [
        f"Iterations: {iterations_run}",
        f"Stop reason: {stop_reason or 'Reached max iterations.'}",
        f"Validation (deterministic): {'OK' if ok_det else 'FAILED'}",
        f"Layer5 (agentic): {'OK' if ok_l5 else 'FAILED'}",
        f"Updated current: {'YES' if ok else 'NO'}",
    ]

    out_paths = {
        "bundle_root": bundle_root,
        "revision_dir": revision_dir,
        "ir": revision_dir / "final.ir.json",
        "puml": revision_dir / "final.puml",
        "validation": revision_dir / "validation_report.json",
        "layer5": revision_dir / "l5.validation_agent.json",
        "diff": revision_dir / "diff.json",
        "summary": revision_dir / "summary.md",
        "summary_json": revision_dir / "summary.json",
    }
    return out_paths, summary_lines

from __future__ import annotations

from dataclasses import asdict
import json
from importlib import resources
from pathlib import Path
from typing import Any, Dict

from .config import Settings
from .io_utils import read_json, write_json, write_text
from .layout import build_revision_record, ensure_bundle_dirs, update_current, write_manifest
from .llm import generate_ir_with_llm, mock_generate_ir, repair_ir_with_llm
from .normalize import coerce_ir_shape, normalize_ir
from .transform import desugar_delays_to_timer_states
from .plantuml import ir_to_plantuml
from .validate import validate_all


class PipelineError(RuntimeError):
    pass


def _read_packaged_template(name: str) -> Dict[str, Any]:
    """Read a JSON template shipped inside the nltouml package.

    This makes `pip install .` work even when templates are not present on disk
    next to the installed site-packages directory.
    """
    txt = resources.files("nltouml").joinpath("templates", name).read_text(encoding="utf-8")
    return json.loads(txt)


def load_templates(templates_dir: Path) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Load required template JSON files.

    Resolution order:
    1) If `templates_dir` exists and contains the files, load from there.
    2) Otherwise, load the packaged templates from `nltouml/templates/*.json`.
    """
    names = ("ir_schema.json", "device_catalog.json", "capability_catalog.json")
    if templates_dir and templates_dir.exists():
        try:
            ir_schema = read_json(templates_dir / names[0])
            device_catalog = read_json(templates_dir / names[1])
            capability_catalog = read_json(templates_dir / names[2])
            return ir_schema, device_catalog, capability_catalog
        except FileNotFoundError:
            # Fall back to packaged templates.
            pass

    ir_schema = _read_packaged_template(names[0])
    device_catalog = _read_packaged_template(names[1])
    capability_catalog = _read_packaged_template(names[2])
    return ir_schema, device_catalog, capability_catalog


def run_pipeline(
    *,
    text: str,
    bundle_name: str,
    settings: Settings,
    out_dir: Path,
    use_mock: bool = False,
    max_repairs: int = 1,
) -> Dict[str, Path]:
    """Run NL->IR->validate->(repair)->PlantUML.

    Output layout (recommended, and now the default):
      outputs/<bundle>/baseline/*   - initial NL->IR->PUML artifacts
      outputs/<bundle>/current/*    - convenience pointer to latest canonical artifacts

    Returns paths to the *baseline* artifacts.
    """

    ir_schema, device_catalog, capability_catalog = load_templates(settings.templates_dir)

    # 1) NL -> IR
    if use_mock:
        ir = mock_generate_ir(text)
    else:
        if not settings.openai_api_key:
            raise PipelineError("OPENAI_API_KEY not set. Either set it, or run with --mock.")
        ir = generate_ir_with_llm(
            text,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            device_catalog=device_catalog,
            capability_catalog=capability_catalog,
            ir_schema=ir_schema,
        )

    # Output bundle layout
    bundle_root = out_dir / bundle_name
    layout = ensure_bundle_dirs(bundle_root)
    baseline_dir = layout.baseline_dir

    out_paths = {
        "ir": baseline_dir / "final.ir.json",
        "puml": baseline_dir / "final.puml",
        "validation": baseline_dir / "validation_report.json",
        # Debug artifacts (helpful when the LLM produces near-miss JSON).
        "raw_ir": baseline_dir / "raw.ir.json",
        "coerced_ir": baseline_dir / "coerced.ir.json",
        "bundle_root": bundle_root,
        "baseline_dir": baseline_dir,
        "current_dir": layout.current_dir,
    }

    # Write raw IR (pre-coercion) for debugging.
    write_json(out_paths["raw_ir"], ir)

    # 2) Coerce common LLM key variants -> normalize -> validate
    ir = coerce_ir_shape(ir, device_catalog)
    ir = normalize_ir(ir)
    # Convert inline delays into explicit timer states (more "state-machine like" diagrams).
    ir = desugar_delays_to_timer_states(ir)
    write_json(out_paths["coerced_ir"], ir)
    diags, patches = validate_all(ir, ir_schema, device_catalog, capability_catalog)

    # 3) Repair loop (optional)
    repairs = 0
    while (not use_mock) and repairs < max_repairs and any(d.severity == "error" for d in diags):
        repairs += 1
        diag_payload = [asdict(d) for d in diags]
        ir = repair_ir_with_llm(
            ir,
            diag_payload,
            api_key=settings.openai_api_key or "",
            model=settings.openai_model,
            device_catalog=device_catalog,
            capability_catalog=capability_catalog,
            ir_schema=ir_schema,
        )
        ir = coerce_ir_shape(ir, device_catalog)
        ir = normalize_ir(ir)
        ir = desugar_delays_to_timer_states(ir)
        diags, patches = validate_all(ir, ir_schema, device_catalog, capability_catalog)

    # 4) Generate PlantUML
    title = f"{bundle_name}"
    puml = ir_to_plantuml(ir, title=title)

    # 5) Write baseline outputs
    write_json(out_paths["ir"], ir)

    report = {
        "ok": not any(d.severity == "error" for d in diags),
        "diagnostics": [asdict(d) for d in diags],
        "patches": [asdict(p) for p in patches],
    }
    write_json(out_paths["validation"], report)
    write_text(out_paths["puml"], puml)

    # 6) Update current pointer + manifest
    update_current(bundle_root, baseline_dir)
    write_manifest(
        bundle_root,
        {
            "baseline": {"dir": "baseline", "updated_at": datetime_utc_iso()},
            "current": {"points_to": "baseline"},
            "append_revision": build_revision_record(kind="baseline", revision_dir=baseline_dir),
        },
    )

    return out_paths


def datetime_utc_iso() -> str:
    """UTC timestamp for manifest metadata (kept here to avoid extra imports in hot paths)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

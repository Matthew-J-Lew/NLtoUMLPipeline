from __future__ import annotations

from dataclasses import asdict
import json
from importlib import resources
from pathlib import Path
from typing import Any, Dict

from .config import Settings
from .io_utils import read_json, write_json, write_text
from .llm import generate_ir_with_llm, mock_generate_ir, repair_ir_with_llm
from .normalize import coerce_ir_shape, normalize_ir
from .transform import desugar_delays_to_timer_states
from .plantuml import ir_to_plantuml
from .validate import Diagnostic, validate_all


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

    Returns paths to written artifacts.
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

    # Prepare output paths early so we can write debug artifacts.
    out_bundle = out_dir / bundle_name
    out_paths = {
        "ir": out_bundle / "final.ir.json",
        "puml": out_bundle / "final.puml",
        "validation": out_bundle / "validation_report.json",
        # Debug artifacts (helpful when the LLM produces near-miss JSON).
        "raw_ir": out_bundle / "raw.ir.json",
        "coerced_ir": out_bundle / "coerced.ir.json",
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
        # convert diags to plain dict for the model
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

    # 5) Write outputs
    write_json(out_paths["ir"], ir)

    report = {
        "ok": not any(d.severity == "error" for d in diags),
        "diagnostics": [asdict(d) for d in diags],
        "patches": [asdict(p) for p in patches],
    }
    write_json(out_paths["validation"], report)
    write_text(out_paths["puml"], puml)

    return out_paths

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent_edit import run_agent_edit
from .config import Settings, load_settings, repo_root
from .diagram_render import (
    PlantUMLRenderError,
    PlantUMLRendererUnavailable,
    get_renderer_status,
    render_plantuml_svg,
)
from .io_utils import read_json
from .pipeline import PipelineError, run_pipeline
from .refine import run_refine
from .roundtrip import run_roundtrip


SAFE_BUNDLE_RE = re.compile(r"[^A-Za-z0-9_-]+")


class RunRequest(BaseModel):
    text: str = Field(min_length=1)
    bundle_name: str = Field(default="StudioRun")
    use_mock: bool = False
    max_repairs: int = Field(default=1, ge=0, le=5)


class AgentEditRequest(BaseModel):
    request: str = Field(min_length=1)
    use_mock: bool = False
    max_repairs: int = Field(default=1, ge=0, le=5)


class RoundTripRequest(BaseModel):
    puml: str = Field(min_length=1)


class RefineRequest(BaseModel):
    use_mock: bool = False
    max_iters: int = Field(default=5, ge=1, le=10)
    max_patch_repairs: int = Field(default=2, ge=0, le=5)


class RenderPlantUMLRequest(BaseModel):
    puml: str = Field(min_length=1)


class StudioContext(BaseModel):
    out_dir: Path
    settings: Settings

    class Config:
        arbitrary_types_allowed = True


class ProjectSummary(BaseModel):
    bundle_name: str
    updated_at: Optional[str] = None
    revision_count: int = 0
    ok: Optional[bool] = None
    states: int = 0
    transitions: int = 0


class ProjectSnapshot(BaseModel):
    bundle_name: str
    exists: bool
    paths: Dict[str, str]
    summary: Dict[str, Any]
    current: Dict[str, Any]
    baseline: Dict[str, Any]
    revisions: List[Dict[str, Any]]
    manifest: Dict[str, Any]


def _slug_bundle_name(name: str) -> str:
    cleaned = SAFE_BUNDLE_RE.sub("_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "StudioRun"


def _safe_read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _counts_from_ir(ir: Optional[Dict[str, Any]]) -> tuple[int, int]:
    if not isinstance(ir, dict):
        return 0, 0
    sm = ir.get("stateMachine") or {}
    return len(sm.get("states") or []), len(sm.get("transitions") or [])


def _diagnostic_counts(report: Optional[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    if not isinstance(report, dict):
        return counts
    for diag in report.get("diagnostics") or []:
        sev = str(diag.get("severity", "info")).lower()
        if sev in counts:
            counts[sev] += 1
    return counts


def _resolve_revision_dir(bundle_root: Path, manifest: Dict[str, Any]) -> Optional[Path]:
    current = manifest.get("current") or {}
    points_to = current.get("points_to")
    if isinstance(points_to, str) and points_to:
        return bundle_root / points_to
    fallback = bundle_root / "current"
    return fallback if fallback.exists() else None


def _project_summary(bundle_root: Path) -> ProjectSummary:
    manifest = _safe_read_json(bundle_root / "manifest.json") or {}
    current_ir = _safe_read_json(bundle_root / "current" / "final.ir.json") or {}
    current_validation = _safe_read_json(bundle_root / "current" / "validation_report.json") or {}
    states, transitions = _counts_from_ir(current_ir)
    revisions = manifest.get("revisions") or []
    return ProjectSummary(
        bundle_name=bundle_root.name,
        updated_at=manifest.get("updated_at"),
        revision_count=len(revisions),
        ok=current_validation.get("ok") if isinstance(current_validation, dict) else None,
        states=states,
        transitions=transitions,
    )


def _load_snapshot(ctx: StudioContext, bundle_name: str) -> ProjectSnapshot:
    bundle_name = _slug_bundle_name(bundle_name)
    bundle_root = ctx.out_dir / bundle_name
    if not bundle_root.exists():
        return ProjectSnapshot(
            bundle_name=bundle_name,
            exists=False,
            paths={"bundle_root": str(bundle_root)},
            summary={},
            current={},
            baseline={},
            revisions=[],
            manifest={},
        )

    manifest = _safe_read_json(bundle_root / "manifest.json") or {}
    current_dir = bundle_root / "current"
    baseline_dir = bundle_root / "baseline"
    revision_dir = _resolve_revision_dir(bundle_root, manifest)

    current_ir = _safe_read_json(current_dir / "final.ir.json")
    current_validation = _safe_read_json(current_dir / "validation_report.json")
    current_puml = _safe_read_text(current_dir / "final.puml")
    baseline_ir = _safe_read_json(baseline_dir / "final.ir.json")
    baseline_validation = _safe_read_json(baseline_dir / "validation_report.json")
    baseline_puml = _safe_read_text(baseline_dir / "final.puml")

    diff = _safe_read_json(revision_dir / "diff.json") if revision_dir else None
    states, transitions = _counts_from_ir(current_ir)
    diag_counts = _diagnostic_counts(current_validation)

    revisions = list(manifest.get("revisions") or [])
    revisions.reverse()

    summary: Dict[str, Any] = {
        "updated_at": manifest.get("updated_at"),
        "revision_count": len(manifest.get("revisions") or []),
        "current_pointer": (manifest.get("current") or {}).get("points_to", "baseline"),
        "states": states,
        "transitions": transitions,
        "ok": current_validation.get("ok") if isinstance(current_validation, dict) else None,
        "diagnostic_counts": diag_counts,
    }

    return ProjectSnapshot(
        bundle_name=bundle_name,
        exists=True,
        paths={
            "bundle_root": str(bundle_root),
            "baseline_dir": str(baseline_dir),
            "current_dir": str(current_dir),
            "active_revision_dir": str(revision_dir) if revision_dir else "",
        },
        summary=summary,
        current={
            "ir": current_ir,
            "validation": current_validation,
            "puml": current_puml,
            "diff": diff,
        },
        baseline={
            "ir": baseline_ir,
            "validation": baseline_validation,
            "puml": baseline_puml,
        },
        revisions=revisions,
        manifest=manifest,
    )


def create_app() -> FastAPI:
    out_dir = Path(os.getenv("NLTOUML_STUDIO_OUT_DIR", str(repo_root() / "outputs"))).resolve()
    templates_dir = os.getenv("NLTOUML_STUDIO_TEMPLATES_DIR")
    settings = load_settings(templates_dir=templates_dir) if templates_dir else load_settings()

    app = FastAPI(
        title="NL→UML Studio API",
        version="0.1.0",
        description="Verification-first backend for the NL→IR→UML MVP studio.",
    )
    app.state.ctx = StudioContext(out_dir=out_dir, settings=settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        ctx: StudioContext = app.state.ctx
        renderer_status = get_renderer_status()
        return {
            "ok": True,
            "out_dir": str(ctx.out_dir),
            "templates_dir": str(ctx.settings.templates_dir),
            "openai_configured": bool(ctx.settings.openai_api_key),
            "plantuml_renderer": renderer_status.model_dump() if hasattr(renderer_status, "model_dump") else {
                "available": renderer_status.available,
                "renderer": renderer_status.renderer,
                "detail": renderer_status.detail,
            },
        }

    @app.get("/api/projects")
    def list_projects() -> Dict[str, Any]:
        ctx: StudioContext = app.state.ctx
        ctx.out_dir.mkdir(parents=True, exist_ok=True)
        bundles = [p for p in ctx.out_dir.iterdir() if p.is_dir()]
        projects = sorted(
            (_project_summary(bundle) for bundle in bundles),
            key=lambda item: item.updated_at or "",
            reverse=True,
        )
        return {"projects": [project.model_dump() for project in projects]}

    @app.get("/api/projects/{bundle_name}")
    def get_project(bundle_name: str) -> Dict[str, Any]:
        ctx: StudioContext = app.state.ctx
        snapshot = _load_snapshot(ctx, bundle_name)
        return {"project": snapshot.model_dump()}


    @app.post("/api/render/plantuml")
    def render_plantuml(req: RenderPlantUMLRequest) -> Dict[str, Any]:
        try:
            result = render_plantuml_svg(req.puml)
        except PlantUMLRendererUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PlantUMLRenderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"svg": result.svg, "renderer": result.renderer}

    @app.post("/api/projects/run")
    def create_project(req: RunRequest) -> Dict[str, Any]:
        ctx: StudioContext = app.state.ctx
        bundle_name = _slug_bundle_name(req.bundle_name)
        try:
            run_pipeline(
                text=req.text,
                bundle_name=bundle_name,
                settings=ctx.settings,
                out_dir=ctx.out_dir,
                use_mock=req.use_mock,
                max_repairs=req.max_repairs,
            )
        except PipelineError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = _load_snapshot(ctx, bundle_name)
        return {"project": snapshot.model_dump(), "message": f"Created or updated {bundle_name}."}

    @app.post("/api/projects/{bundle_name}/agent-edit")
    def agent_edit(bundle_name: str, req: AgentEditRequest) -> Dict[str, Any]:
        ctx: StudioContext = app.state.ctx
        bundle_name = _slug_bundle_name(bundle_name)
        try:
            _, summary = run_agent_edit(
                bundle_name=bundle_name,
                out_dir=ctx.out_dir,
                request_text=req.request,
                settings=ctx.settings,
                use_mock=req.use_mock,
                max_repairs=req.max_repairs,
            )
        except PipelineError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = _load_snapshot(ctx, bundle_name)
        return {"project": snapshot.model_dump(), "summary": summary}

    @app.post("/api/projects/{bundle_name}/roundtrip")
    def roundtrip(bundle_name: str, req: RoundTripRequest) -> Dict[str, Any]:
        ctx: StudioContext = app.state.ctx
        bundle_name = _slug_bundle_name(bundle_name)
        bundle_root = ctx.out_dir / bundle_name
        if not bundle_root.exists():
            raise HTTPException(status_code=404, detail=f"Bundle '{bundle_name}' does not exist.")

        edited_path = bundle_root / "edited.puml"
        edited_path.write_text(req.puml, encoding="utf-8")
        baseline_ir = bundle_root / "baseline" / "final.ir.json"
        try:
            _, summary = run_roundtrip(
                puml_path=edited_path,
                out_bundle_dir=bundle_root,
                settings=ctx.settings,
                baseline_ir_path=baseline_ir if baseline_ir.exists() else None,
            )
        except PipelineError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = _load_snapshot(ctx, bundle_name)
        return {"project": snapshot.model_dump(), "summary": summary}

    @app.post("/api/projects/{bundle_name}/refine")
    def refine(bundle_name: str, req: RefineRequest) -> Dict[str, Any]:
        ctx: StudioContext = app.state.ctx
        bundle_name = _slug_bundle_name(bundle_name)
        try:
            _, summary = run_refine(
                bundle_name=bundle_name,
                out_dir=ctx.out_dir,
                settings=ctx.settings,
                use_mock=req.use_mock,
                max_iters=req.max_iters,
                max_patch_repairs=req.max_patch_repairs,
            )
        except PipelineError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = _load_snapshot(ctx, bundle_name)
        return {"project": snapshot.model_dump(), "summary": summary}

    return app


app = create_app()

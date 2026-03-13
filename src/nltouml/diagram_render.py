from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import repo_root


class PlantUMLRendererUnavailable(RuntimeError):
    """Raised when no local PlantUML renderer can be found."""


class PlantUMLRenderError(RuntimeError):
    """Raised when PlantUML fails to render the requested diagram."""


@dataclass(frozen=True)
class PlantUMLRenderer:
    kind: str
    argv: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class PlantUMLRenderResult:
    svg: str
    renderer: str


@dataclass(frozen=True)
class PlantUMLRendererStatus:
    available: bool
    renderer: Optional[str]
    detail: str


def _default_jar_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_jar = os.getenv("PLANTUML_JAR")
    if env_jar:
        candidates.append(Path(env_jar).expanduser())
    repo_jar = repo_root() / "tools" / "plantuml.jar"
    if repo_jar.exists():
        candidates.append(repo_jar)
    return candidates


def _graphviz_args() -> list[str]:
    dot_path = os.getenv("GRAPHVIZ_DOT")
    if dot_path:
        return ["-graphvizdot", dot_path]
    return []


def _discover_renderer() -> tuple[Optional[PlantUMLRenderer], str]:
    env_cmd = os.getenv("PLANTUML_CMD")
    if env_cmd:
        argv = tuple(shlex.split(env_cmd))
        if argv:
            return PlantUMLRenderer(kind="command", argv=argv, label="PLANTUML_CMD"), "Using renderer from PLANTUML_CMD."

    plantuml_exe = shutil.which("plantuml")
    if plantuml_exe:
        return PlantUMLRenderer(kind="command", argv=(plantuml_exe,), label="plantuml executable"), "Using plantuml executable on PATH."

    java_exe = shutil.which("java")
    for jar_path in _default_jar_candidates():
        if jar_path.exists() and java_exe:
            return (
                PlantUMLRenderer(
                    kind="jar",
                    argv=(java_exe, "-jar", str(jar_path.resolve())),
                    label=f"plantuml.jar ({jar_path.resolve()})",
                ),
                f"Using plantuml.jar at {jar_path.resolve()}.",
            )

    if any(path.exists() for path in _default_jar_candidates()) and not java_exe:
        return None, "Found plantuml.jar, but Java is not available on PATH."

    return None, (
        "No local PlantUML renderer was detected. Install a plantuml executable on PATH, or add "
        "plantuml.jar under <repo>/tools/plantuml.jar (or set PLANTUML_JAR) and ensure Java is on PATH. "
        "Graphviz may also be required for state-diagram rendering."
    )


def get_renderer_status() -> PlantUMLRendererStatus:
    renderer, detail = _discover_renderer()
    return PlantUMLRendererStatus(
        available=renderer is not None,
        renderer=(renderer.label if renderer else None),
        detail=detail,
    )


def _extract_svg(text: str) -> Optional[str]:
    start = text.find("<svg")
    end = text.rfind("</svg>")
    if start == -1 or end == -1:
        return None
    return text[start : end + len("</svg>")]


def render_plantuml_svg(puml_text: str, *, timeout_seconds: int = 25) -> PlantUMLRenderResult:
    renderer, detail = _discover_renderer()
    if renderer is None:
        raise PlantUMLRendererUnavailable(detail)

    cmd = [*renderer.argv, "-tsvg", "-pipe", "-charset", "UTF-8", *_graphviz_args()]

    try:
        completed = subprocess.run(
            cmd,
            input=puml_text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise PlantUMLRendererUnavailable(
            f"The configured PlantUML renderer could not be started: {exc}."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PlantUMLRenderError(
            "Timed out while rendering PlantUML. Check that Java/PlantUML is installed correctly and try again."
        ) from exc

    stdout_text = completed.stdout.decode("utf-8", errors="replace")
    stderr_text = completed.stderr.decode("utf-8", errors="replace")
    svg = _extract_svg(stdout_text) or _extract_svg(stderr_text)

    if completed.returncode != 0:
        detail_text = stderr_text.strip() or stdout_text.strip() or "PlantUML returned a non-zero exit status."
        raise PlantUMLRenderError(detail_text)

    if not svg:
        detail_text = stderr_text.strip() or stdout_text.strip() or "PlantUML did not return SVG output."
        raise PlantUMLRenderError(detail_text)

    return PlantUMLRenderResult(svg=svg, renderer=renderer.label)

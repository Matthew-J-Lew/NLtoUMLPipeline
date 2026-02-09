from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


_EDIT_RE = re.compile(r"^edit_(\d{3})$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_copy(src: Path, dst: Path) -> None:
    """Copy a file, ensuring destination folder exists."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))


@dataclass(frozen=True)
class BundleLayout:
    bundle_root: Path
    baseline_dir: Path
    edits_dir: Path
    current_dir: Path
    manifest_path: Path


def get_layout(bundle_root: Path) -> BundleLayout:
    return BundleLayout(
        bundle_root=bundle_root,
        baseline_dir=bundle_root / "baseline",
        edits_dir=bundle_root / "edits",
        current_dir=bundle_root / "current",
        manifest_path=bundle_root / "manifest.json",
    )


def ensure_bundle_dirs(bundle_root: Path) -> BundleLayout:
    """Create baseline/edits/current folders if missing."""
    layout = get_layout(bundle_root)
    layout.baseline_dir.mkdir(parents=True, exist_ok=True)
    layout.edits_dir.mkdir(parents=True, exist_ok=True)
    layout.current_dir.mkdir(parents=True, exist_ok=True)
    return layout


def find_bundle_root(puml_path: Path, out_bundle_override: Optional[Path] = None) -> Path:
    """Infer the bundle root given a .puml path.

    If out_bundle_override is provided, it wins.

    Otherwise, we walk up a few levels looking for a recognizable bundle root
    marker (manifest.json or baseline/edits/current directories). If none are
    found, we treat the .puml's parent directory as the bundle root.
    """

    if out_bundle_override is not None:
        return out_bundle_override

    cur = puml_path.parent
    for _ in range(4):
        if (cur / "manifest.json").exists():
            return cur
        if (cur / "baseline").exists() or (cur / "edits").exists() or (cur / "current").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent

    return puml_path.parent


def _next_edit_id(edits_dir: Path) -> str:
    max_n = 0
    if edits_dir.exists():
        for child in edits_dir.iterdir():
            if not child.is_dir():
                continue
            m = _EDIT_RE.match(child.name)
            if not m:
                continue
            try:
                n = int(m.group(1))
                max_n = max(max_n, n)
            except Exception:
                continue
    return f"edit_{max_n + 1:03d}"


def allocate_edit_dir(bundle_root: Path) -> Path:
    layout = ensure_bundle_dirs(bundle_root)
    edit_id = _next_edit_id(layout.edits_dir)
    edit_dir = layout.edits_dir / edit_id
    edit_dir.mkdir(parents=True, exist_ok=False)
    return edit_dir


def update_current(bundle_root: Path, revision_dir: Path) -> None:
    """Update outputs/<bundle>/current/* to point at the latest canonical artifacts."""
    layout = ensure_bundle_dirs(bundle_root)
    for name in ("final.ir.json", "final.puml", "validation_report.json"):
        src = revision_dir / name
        if src.exists():
            safe_copy(src, layout.current_dir / name)


def _read_manifest(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def write_manifest(bundle_root: Path, update: Dict[str, Any]) -> None:
    """Upsert manifest.json at the bundle root.

    Supported keys in `update`:
      - append_revision: { ... }  -> appended to revisions[]
      - current: { ... }          -> sets the current pointer metadata
      - baseline: { ... }         -> sets baseline metadata
      - ... any other top-level keys will be overwritten
    """

    layout = ensure_bundle_dirs(bundle_root)
    m = _read_manifest(layout.manifest_path)

    m.setdefault("schema_version", "1")
    m.setdefault("bundle", bundle_root.name)
    if not isinstance(m.get("revisions"), list):
        m["revisions"] = []

    for k, v in update.items():
        if k == "append_revision" and isinstance(v, dict):
            m["revisions"].append(v)
        else:
            m[k] = v

    m["updated_at"] = _now_iso()
    layout.manifest_path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_revision_record(
    *,
    kind: str,
    revision_dir: Path,
    source_puml: Optional[Path] = None,
    diff_against: Optional[Path] = None,
) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "kind": kind,
        "dir": str(revision_dir.as_posix()),
        "created_at": _now_iso(),
    }
    if source_puml is not None:
        rec["source_puml"] = str(source_puml.as_posix())
    if diff_against is not None:
        rec["diff_against"] = str(diff_against.as_posix())
    return rec

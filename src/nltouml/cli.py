from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import load_settings
from .pipeline import PipelineError, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nltouml", description="NL -> IR -> PlantUML state machine")
    p.add_argument("--text", required=True, help="Natural language requirement")
    p.add_argument("--bundle-name", default="Bundle1", help="Output bundle folder name")
    p.add_argument("--out-dir", default="outputs", help="Output directory")
    p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )
    p.add_argument("--mock", action="store_true", help="Run without an LLM (deterministic demo)")
    p.add_argument("--max-repairs", type=int, default=1, help="Max LLM repair attempts when validation fails")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # read .env if present
    args = build_parser().parse_args(argv)

    settings = load_settings(templates_dir=args.templates_dir)
    try:
        out_paths = run_pipeline(
            text=args.text,
            bundle_name=args.bundle_name,
            settings=settings,
            out_dir=Path(args.out_dir),
            use_mock=args.mock,
            max_repairs=args.max_repairs,
        )
    except PipelineError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"Wrote IR:   {out_paths['ir']}")
    print(f"Wrote PUML: {out_paths['puml']}")
    print(f"Wrote report: {out_paths['validation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

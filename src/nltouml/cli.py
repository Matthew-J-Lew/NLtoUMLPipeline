from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import load_settings
from .metrics import run_metrics
from .pipeline import PipelineError, run_pipeline


def build_run_parser(prog: str = "nltouml") -> argparse.ArgumentParser:
    """Backward-compatible parser for `nltouml --text ...` and `nlpipeline --text ...`."""
    p = argparse.ArgumentParser(prog=prog, description="NL -> IR -> PlantUML state machine")
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


def build_metrics_parser(prog: str = "nltouml") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=f"{prog} metrics",
        description="Run metrics over a scenarios.csv file",
    )
    p.add_argument("--scenarios", required=True, help="Path to scenarios.csv")
    p.add_argument("--out-dir", default="metrics_out", help="Where to write metrics outputs")
    p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )
    p.add_argument("--mock", action="store_true", help="Run without an LLM (deterministic demo)")

    # Metric 1: completion (by default allow 1 repair, but user can set 0).
    p.add_argument(
        "--metric1-max-repairs",
        type=int,
        default=1,
        help="Max LLM repair attempts for Metric 1 runs",
    )
    # Metric 2/3: initial output (no repairs by default).
    p.add_argument(
        "--metric2-max-repairs",
        type=int,
        default=0,
        help="Max LLM repair attempts for Metric 2/3 runs (0 = first try)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of scenarios to run",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # read .env if present
    argv = list(argv) if argv is not None else None

    # Backward compatible: `nlpipeline --text ...` keeps working.
    # New: `nlpipeline metrics --scenarios scenarios.csv`
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) > 0 and argv[0] == "metrics":
        margs = build_metrics_parser(prog="nltouml").parse_args(argv[1:])
        settings = load_settings(templates_dir=margs.templates_dir)
        try:
            outputs = run_metrics(
                scenarios_path=Path(margs.scenarios),
                out_dir=Path(margs.out_dir),
                settings=settings,
                use_mock=margs.mock,
                metric1_max_repairs=margs.metric1_max_repairs,
                metric2_max_repairs=margs.metric2_max_repairs,
                limit=margs.limit,
            )
        except PipelineError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        print(f"Wrote per-scenario results: {outputs['per_scenario_csv']}")
        print(f"Wrote metrics summary:      {outputs['summary_csv']}")
        print(f"Run artifacts under:        {outputs['runs_dir']}")
        return 0

    args = build_run_parser(prog="nltouml").parse_args(argv)

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

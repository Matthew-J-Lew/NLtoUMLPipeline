from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import load_settings
from .pipeline import PipelineError, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Build a CLI with subcommands.

    Backwards-compatible with the original single-command interface:
      nlpipeline --text "..." [--bundle-name ...] [--max-repairs ...]

    New preferred interface:
      nlpipeline run --text "..."
      nlpipeline metrics --scenarios scenarios.csv
      nlpipeline roundtrip --puml outputs/Bundle1/edited.puml
    """

    p = argparse.ArgumentParser(prog="nltouml", description="NL -> IR -> PlantUML state machine")
    sub = p.add_subparsers(dest="command", required=True)

    # ----- run -----
    run_p = sub.add_parser("run", help="Run the pipeline once for a single NL prompt")
    run_p.add_argument("--text", required=True, help="Natural language requirement")
    run_p.add_argument("--bundle-name", default="Bundle1", help="Output bundle folder name")
    run_p.add_argument("--out-dir", default="outputs", help="Output directory")
    run_p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )
    run_p.add_argument("--mock", action="store_true", help="Run without an LLM (deterministic demo)")
    run_p.add_argument("--max-repairs", type=int, default=1, help="Max LLM repair attempts when validation fails")

    # ----- metrics -----
    metrics_p = sub.add_parser("metrics", help="Run evaluation metrics over scenarios.csv")
    metrics_p.add_argument("--scenarios", required=True, help="Path to scenarios.csv")
    metrics_p.add_argument("--out-dir", default="metrics_out", help="Directory to write metrics outputs")
    metrics_p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )
    metrics_p.add_argument("--mock", action="store_true", help="Run without an LLM (deterministic demo)")
    metrics_p.add_argument("--metric1-max-repairs", type=int, default=1, help="Max repairs for Metric 1 runs")
    metrics_p.add_argument("--metric2-max-repairs", type=int, default=0, help="Max repairs for Metric 2 runs")
    metrics_p.add_argument("--limit", type=int, default=None, help="Limit number of scenarios (debug)")

    # ----- roundtrip -----
    rt_p = sub.add_parser("roundtrip", help="Parse an edited PlantUML diagram back into IR + validation")
    rt_p.add_argument(
        "--puml",
        required=True,
        help=(
            "Path to the edited PlantUML file (e.g., outputs/Bundle1/edited.puml). "
            "By default, artifacts are written next to this file."
        ),
    )
    rt_p.add_argument(
        "--out-bundle",
        default=None,
        help=(
            "Optional directory to write artifacts into (overrides default of puml's parent folder). "
            "Example: outputs/Bundle1"
        ),
    )
    rt_p.add_argument(
        "--baseline-ir",
        default=None,
        help=(
            "Optional path to a baseline IR (e.g., outputs/Bundle1/final.ir.json) to produce a simple diff."
        ),
    )
    rt_p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )

    return p


def _normalize_legacy_argv(argv: list[str]) -> list[str]:
    """Support the legacy CLI that required --text at top-level.

    If the first argument is not a subcommand, assume the user meant `run`.
    This keeps existing docs/commands working:
      nlpipeline --text "..." --max-repairs 0
    """
    if not argv:
        return argv
    if argv[0] in {"run", "metrics", "roundtrip"}:
        return argv
    # If user started with flags ("--text" etc.), treat as legacy `run`.
    if argv[0].startswith("-"):
        return ["run", *argv]
    # Otherwise, leave as-is (argparse will show a helpful error).
    return argv


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # read .env if present

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    raw_argv = _normalize_legacy_argv(raw_argv)
    args = build_parser().parse_args(raw_argv)

    if args.command == "metrics":
        # Import here to keep base startup light.
        from .metrics import run_metrics

        settings = load_settings(templates_dir=args.templates_dir)
        try:
            out_paths = run_metrics(
                scenarios_path=Path(args.scenarios),
                out_dir=Path(args.out_dir),
                settings=settings,
                use_mock=bool(args.mock),
                metric1_max_repairs=int(args.metric1_max_repairs),
                metric2_max_repairs=int(args.metric2_max_repairs),
                limit=args.limit,
            )
        except PipelineError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        print(f"Wrote per-scenario CSV: {out_paths['per_scenario_csv']}")
        print(f"Wrote summary CSV:      {out_paths['summary_csv']}")
        print(f"Wrote run artifacts:    {out_paths['runs_dir']}")
        return 0

    if args.command == "roundtrip":
        from .roundtrip import run_roundtrip

        settings = load_settings(templates_dir=args.templates_dir)
        try:
            out_paths, summary = run_roundtrip(
                puml_path=Path(args.puml),
                out_bundle_dir=(Path(args.out_bundle) if args.out_bundle else None),
                settings=settings,
                baseline_ir_path=(Path(args.baseline_ir) if args.baseline_ir else None),
            )
        except PipelineError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        # Small compiler-style summary
        if summary:
            for line in summary:
                print(line)

        print(f"Wrote parsed IR (raw): {out_paths['raw_ir']}")
        print(f"Wrote parsed IR:       {out_paths['ir']}")
        print(f"Wrote report:          {out_paths['validation']}")
        print(f"Wrote regenerated PUML:{out_paths['regenerated_puml']}")
        if 'diff' in out_paths:
            print(f"Wrote diff:            {out_paths['diff']}")
        return 0

    # args.command == "run"
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

    print(f"Wrote IR:      {out_paths['ir']}")
    print(f"Wrote PUML:    {out_paths['puml']}")
    print(f"Wrote report:  {out_paths['validation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

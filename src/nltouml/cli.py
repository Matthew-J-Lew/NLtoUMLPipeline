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
      nlpipeline agent-edit --bundle-name Bundle1 --request "..."
      nlpipeline regression-checks
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

    # ----- metrics-full -----
    mf_p = sub.add_parser("metrics-full", help="Run the full end-to-end evaluation suite")
    mf_p.add_argument("--scenarios", required=True, help="Path to scenarios.csv")
    mf_p.add_argument("--out-dir", default="metrics_full_out", help="Directory to write evaluation outputs")
    mf_p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )
    mf_p.add_argument("--mock", action="store_true", help="Run without an LLM (deterministic demo)")
    mf_p.add_argument("--pre-max-repairs", type=int, default=0, help="Max repairs allowed during the pre-refine baseline run")
    mf_p.add_argument("--refine-max-iters", type=int, default=5, help="Max refine loop iterations")
    mf_p.add_argument("--refine-max-patch-repairs", type=int, default=2, help="Max attempts to repair an invalid patch during refine")
    mf_p.add_argument("--limit", type=int, default=None, help="Limit number of scenarios (debug)")
    mf_p.add_argument("--skip-paraphrases", action="store_true", help="Skip paraphrase robustness evaluation")
    mf_p.add_argument("--skip-adversarial", action="store_true", help="Skip adversarial bundle evaluation")
    mf_p.add_argument("--adversarial-source-dir", default="outputs", help="Directory containing handcrafted adversarial bundles")
    mf_p.add_argument(
        "--adversarial-bundles",
        nargs="*",
        default=None,
        help="Optional list of adversarial bundle names to evaluate. Defaults to the built-in bundle set.",
    )

    # ----- roundtrip -----
    rt_p = sub.add_parser("roundtrip", help="Parse an edited PlantUML diagram back into IR + validation")
    rt_p.add_argument(
        "--puml",
        required=True,
        help=(
            "Path to the edited PlantUML file (e.g., outputs/Bundle1/edited.puml). "
            "Artifacts are written into a new outputs/<bundle>/edits/edit_### revision (next to baseline/current)."
        ),
    )
    rt_p.add_argument(
        "--out-bundle",
        default=None,
        help=(
            "Optional bundle root directory. If provided, the new edit revision will be created under: <bundle>/edits/edit_###. "
            "Example: outputs/Bundle1"
        ),
    )
    rt_p.add_argument(
        "--baseline-ir",
        default=None,
        help=(
            "Optional path to a baseline IR (e.g., outputs/Bundle1/baseline/final.ir.json) to produce a simple diff."
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

    # ----- agent-edit -----
    ae_p = sub.add_parser("agent-edit", help="Use an edit agent to apply NL change requests to the CURRENT IR")
    ae_p.add_argument("--bundle-name", required=True, help="Existing bundle name under --out-dir (must have baseline/current)")
    ae_p.add_argument("--out-dir", default="outputs", help="Outputs directory containing the bundle")
    ae_p.add_argument("--request", required=True, help="Natural language change request (what to change)")
    ae_p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )
    ae_p.add_argument("--mock", action="store_true", help="Run without LLM (simple heuristic patch generator)")
    ae_p.add_argument("--max-repairs", type=int, default=1, help="Max agent patch repair attempts if validation fails")

    # ----- refine (Layers 5–7) -----
    rf_p = sub.add_parser("refine", help="Run agentic validate+repair loop (Layers 5–7) on the CURRENT IR")
    rf_p.add_argument("--bundle-name", required=True, help="Existing bundle name under --out-dir (must have baseline/current)")
    rf_p.add_argument("--out-dir", default="outputs", help="Outputs directory containing the bundle")
    rf_p.add_argument("--mock", action="store_true", help="Run without LLM (deterministic demo repairs)")
    rf_p.add_argument("--max-iters", type=int, default=5, help="Max refine loop iterations")
    rf_p.add_argument("--max-patch-repairs", type=int, default=2, help="Max attempts to repair an invalid patch per iteration")
    rf_p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )

    # ----- regression-checks -----
    rc_p = sub.add_parser("regression-checks", help="Run lightweight robustness checks for recent failure modes")
    rc_p.add_argument("--out", default=None, help="Optional JSON output path for the regression check report")

    # ----- studio -----
    st_p = sub.add_parser("studio", help="Launch the FastAPI backend used by the MVP studio UI")
    st_p.add_argument("--host", default="127.0.0.1", help="Host interface for the studio API")
    st_p.add_argument("--port", type=int, default=8000, help="Port for the studio API")
    st_p.add_argument("--out-dir", default="outputs", help="Directory containing output bundles")
    st_p.add_argument(
        "--templates-dir",
        default=None,
        help=(
            "Path to templates dir. If omitted, uses repo_root/templates when running from source, "
            "otherwise uses packaged templates shipped with the library."
        ),
    )
    st_p.add_argument("--reload", action="store_true", help="Enable uvicorn reload for local backend development")

    return p


def _normalize_legacy_argv(argv: list[str]) -> list[str]:
    """Support the legacy CLI that required --text at top-level.

    If the first argument is not a subcommand, assume the user meant `run`.
    This keeps existing docs/commands working:
      nlpipeline --text "..." --max-repairs 0
    """
    if not argv:
        return argv
    if argv[0] in {"run", "metrics", "metrics-full", "roundtrip", "agent-edit", "refine", "regression-checks", "studio"}:
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

    if args.command == "regression-checks":
        from .regression_checks import run_regression_checks

        out_path = Path(args.out) if args.out else None
        summary = run_regression_checks(out_path=out_path)
        print(f"Passed {summary['passed']}/{summary['total']} regression checks")
        for check in summary.get("checks", []):
            status = "PASS" if check.get("passed") else "FAIL"
            print(f"- [{status}] {check.get('name')}")
        if out_path is not None:
            print(f"Wrote regression report: {out_path}")
        return 0 if summary.get("ok") else 1

    if args.command == "metrics-full":
        from .metrics_full import run_full_metrics

        settings = load_settings(templates_dir=args.templates_dir)
        try:
            out_paths = run_full_metrics(
                scenarios_path=Path(args.scenarios),
                out_dir=Path(args.out_dir),
                settings=settings,
                use_mock=bool(args.mock),
                pre_max_repairs=int(args.pre_max_repairs),
                refine_max_iters=int(args.refine_max_iters),
                refine_max_patch_repairs=int(args.refine_max_patch_repairs),
                limit=args.limit,
                include_paraphrases=not bool(args.skip_paraphrases),
                include_adversarial=not bool(args.skip_adversarial),
                adversarial_source_dir=Path(args.adversarial_source_dir),
                adversarial_bundles=args.adversarial_bundles,
            )
        except PipelineError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        print(f"Wrote scenario CSV:    {out_paths['scenario_results_csv']}")
        print(f"Wrote paraphrase CSV:  {out_paths['paraphrase_results_csv']}")
        print(f"Wrote adversarial CSV: {out_paths['adversarial_results_csv']}")
        print(f"Wrote summary CSV:     {out_paths['summary_csv']}")
        print(f"Wrote summary JSON:    {out_paths['summary_json']}")
        print(f"Wrote markdown report: {out_paths['report_md']}")
        print(f"Wrote run artifacts:   {out_paths['runs_dir']}")
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

        print(f"Wrote revision dir:    {out_paths['revision_dir']}")
        print(f"Wrote source PUML:     {out_paths['source_puml']}")
        print(f"Wrote parsed IR (raw): {out_paths['raw_ir']}")
        print(f"Wrote parsed IR:       {out_paths['ir']}")
        print(f"Wrote report:          {out_paths['validation']}")
        print(f"Wrote regenerated PUML:{out_paths['puml']}")
        if 'diff' in out_paths:
            print(f"Wrote diff:            {out_paths['diff']}")
        print(f"Updated current dir:   {Path(out_paths['bundle_root']) / 'current'}")
        return 0

    if args.command == "agent-edit":
        from .agent_edit import run_agent_edit

        settings = load_settings(templates_dir=args.templates_dir)
        try:
            out_paths, summary = run_agent_edit(
                bundle_name=args.bundle_name,
                out_dir=Path(args.out_dir),
                request_text=args.request,
                settings=settings,
                use_mock=bool(args.mock),
                max_repairs=int(args.max_repairs),
            )
        except PipelineError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        for line in summary:
            print(line)

        print(f"Wrote revision dir:    {out_paths['revision_dir']}")
        if "puml" in out_paths:
            print(f"Wrote diagram:         {out_paths['puml']}")
        if "validation" in out_paths:
            print(f"Wrote report:          {out_paths['validation']}")
        return 0


    if args.command == "refine":
        from .refine import run_refine

        settings = load_settings(templates_dir=args.templates_dir)
        try:
            out_paths, summary = run_refine(
                bundle_name=args.bundle_name,
                out_dir=Path(args.out_dir),
                settings=settings,
                use_mock=bool(args.mock),
                max_iters=int(args.max_iters),
                max_patch_repairs=int(args.max_patch_repairs),
            )
        except PipelineError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        for line in summary:
            print(line)

        print(f"Wrote revision dir:    {out_paths['revision_dir']}")
        print(f"Wrote IR:              {out_paths['ir']}")
        print(f"Wrote diagram:         {out_paths['puml']}")
        print(f"Wrote report:          {out_paths['validation']}")
        print(f"Wrote layer5 report:   {out_paths['layer5']}")
        print(f"Updated current if OK: {Path(out_paths['bundle_root']) / 'current'}")
        return 0

    if args.command == "studio":
        try:
            import os
            import uvicorn
        except Exception:
            print(
                "ERROR: Studio dependencies are not installed. Run: pip install -e '.[studio]'",
                file=sys.stderr,
            )
            return 2

        os.environ["NLTOUML_STUDIO_OUT_DIR"] = str(Path(args.out_dir).resolve())
        if args.templates_dir:
            os.environ["NLTOUML_STUDIO_TEMPLATES_DIR"] = str(Path(args.templates_dir).resolve())

        if args.reload:
            uvicorn.run(
                "nltouml.studio_api:app",
                host=args.host,
                port=int(args.port),
                reload=True,
            )
        else:
            from .studio_api import create_app

            uvicorn.run(create_app(), host=args.host, port=int(args.port))
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

    print(f"Wrote baseline dir: {out_paths['baseline_dir']}")
    print(f"Wrote current dir:  {out_paths['current_dir']}")
    print(f"Wrote IR:           {out_paths['ir']}")
    print(f"Wrote PUML:         {out_paths['puml']}")
    print(f"Wrote report:       {out_paths['validation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
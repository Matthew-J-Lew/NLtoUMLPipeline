from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .agent_validate import validate_agentic
from .config import Settings
from .io_utils import read_json, write_json, write_text
from .metrics import (
    Scenario,
    _count_diags,
    _coverage,
    _read_validation_report,
    extract_present_tokens,
    load_scenarios_csv,
)
from .pipeline import PipelineError, run_pipeline
from .refine import run_refine
from .roundtrip import run_roundtrip


DEFAULT_ADVERSARIAL_BUNDLES: Tuple[str, ...] = (
    "UnreachableState",
    "DuplicateTransitions",
    "DeadEndState",
    "DisconnectedSubgraph",
    "MultiIssueRepair",
    "MaxItersStop",
)


def _normalize_text(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _bool(v: Any) -> bool:
    return bool(v)


def _state_machine_counts(ir: Dict[str, Any]) -> Dict[str, int]:
    sm = ir.get("stateMachine") if isinstance(ir.get("stateMachine"), dict) else {}
    states = sm.get("states", []) if isinstance(sm.get("states"), list) else []
    transitions = sm.get("transitions", []) if isinstance(sm.get("transitions"), list) else []
    return {
        "state_count": len(states),
        "transition_count": len(transitions),
    }


def _count_agentic(report: Dict[str, Any]) -> Dict[str, Any]:
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    errors = [i for i in issues if isinstance(i, dict) and i.get("severity") == "error"]
    warnings = [i for i in issues if isinstance(i, dict) and i.get("severity") == "warning"]
    codes = sorted({str(i.get("code")) for i in issues if isinstance(i, dict) and i.get("code")})
    return {
        "issue_count": len(issues),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "codes": codes,
        "codes_str": "|".join(codes),
    }


def _coverage_for_scenario(sc: Optional[Scenario], present: Dict[str, Set[str]]) -> Dict[str, Any]:
    if sc is None:
        return {
            "devices_required": 0,
            "devices_present": 0,
            "devices_coverage": 1.0,
            "missing_devices": "",
            "triggers_required": 0,
            "triggers_present": 0,
            "triggers_coverage": 1.0,
            "missing_triggers": "",
            "actions_required": 0,
            "actions_present": 0,
            "actions_coverage": 1.0,
            "missing_actions": "",
            "overall_coverage": 1.0,
        }

    dev_found, dev_req, dev_cov, _, dev_missing = _coverage(sc.req_devices, present["devices"])
    trg_found, trg_req, trg_cov, _, trg_missing = _coverage(sc.req_triggers, present["triggers"])
    act_found, act_req, act_cov, _, act_missing = _coverage(sc.req_actions, present["actions"])
    total_req = dev_req + trg_req + act_req
    total_found = dev_found + trg_found + act_found
    overall_cov = 1.0 if total_req == 0 else (total_found / total_req)
    return {
        "devices_required": dev_req,
        "devices_present": dev_found,
        "devices_coverage": round(dev_cov, 4),
        "missing_devices": "|".join(dev_missing),
        "triggers_required": trg_req,
        "triggers_present": trg_found,
        "triggers_coverage": round(trg_cov, 4),
        "missing_triggers": "|".join(trg_missing),
        "actions_required": act_req,
        "actions_present": act_found,
        "actions_coverage": round(act_cov, 4),
        "missing_actions": "|".join(act_missing),
        "overall_coverage": round(overall_cov, 4),
    }


def _downstream_ready(*, det_ok: bool, layer5_ok: bool, ir: Dict[str, Any], puml_path: Path) -> bool:
    if not det_ok or not layer5_ok:
        return False
    if not puml_path.exists():
        return False
    if not isinstance(ir, dict):
        return False
    devices = ir.get("devices")
    sm = ir.get("stateMachine")
    if not isinstance(devices, list) or not isinstance(sm, dict):
        return False
    if not isinstance(sm.get("states"), list) or not isinstance(sm.get("transitions"), list):
        return False
    return True


def _prefixed(prefix: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {f"{prefix}{k}": v for k, v in data.items() if not k.startswith("_")}


def _filter_public_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    public_rows = _filter_public_rows(rows)
    if not public_rows:
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write("")
        return
    fieldnames: List[str] = []
    seen: Set[str] = set()
    for row in public_rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in public_rows:
            w.writerow(row)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not headers:
        return ""
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        vals = [str(v) if v is not None else "" for v in row]
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)


def _summary_csv_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for section, payload in summary.items():
        if isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    rows.append({"section": section, "metric": key, "value": value})
    return rows


def _run_single_case(
    *,
    text: str,
    bundle_name: str,
    run_root: Path,
    settings: Settings,
    use_mock: bool,
    pre_max_repairs: int,
    refine_max_iters: int,
    refine_max_patch_repairs: int,
    scenario: Optional[Scenario],
) -> Dict[str, Any]:
    baseline: Dict[str, Any]
    post: Dict[str, Any]

    try:
        base_paths = run_pipeline(
            text=text,
            bundle_name=bundle_name,
            settings=settings,
            out_dir=run_root,
            use_mock=use_mock,
            max_repairs=pre_max_repairs,
        )
        base_report = _read_validation_report(base_paths["validation"])
        base_ir = read_json(base_paths["ir"])
        _issues, base_layer5_report = validate_agentic(base_ir)
        write_json(base_paths["baseline_dir"] / "l5.validation_agent.json", base_layer5_report)
        base_counts = _count_diags(base_report)
        base_agent_counts = _count_agentic(base_layer5_report)
        base_present = extract_present_tokens(base_ir)
        base_struct = _state_machine_counts(base_ir)
        base_det_ok = bool(base_report.get("ok", False))
        base_l5_ok = bool(base_layer5_report.get("ok", False))
        baseline = {
            "completed": True,
            "exception": "",
            "bundle_name": bundle_name,
            "bundle_root": str(base_paths["bundle_root"]),
            "ir_path": str(base_paths["ir"]),
            "puml_path": str(base_paths["puml"]),
            "validation_path": str(base_paths["validation"]),
            "layer5_path": str(base_paths["baseline_dir"] / "l5.validation_agent.json"),
            "det_ok": base_det_ok,
            "layer5_ok": base_l5_ok,
            "overall_valid": base_det_ok and base_l5_ok,
            "structural_valid": base_det_ok and Path(base_paths["puml"]).exists(),
            "downstream_ready": _downstream_ready(
                det_ok=base_det_ok,
                layer5_ok=base_l5_ok,
                ir=base_ir,
                puml_path=Path(base_paths["puml"]),
            ),
            "det_error_count": base_counts["error_count"],
            "det_warning_count": base_counts["warning_count"],
            "det_schema_error_count": base_counts["schema_error_count"],
            "layer5_issue_count": base_agent_counts["issue_count"],
            "layer5_error_count": base_agent_counts["error_count"],
            "layer5_warning_count": base_agent_counts["warning_count"],
            "layer5_codes": base_agent_counts["codes_str"],
            "total_issue_count": base_counts["error_count"] + base_counts["warning_count"] + base_agent_counts["issue_count"],
            "total_error_count": base_counts["error_count"] + base_agent_counts["error_count"],
            **base_struct,
            **_coverage_for_scenario(scenario, base_present),
            "_present_tokens": base_present,
        }
    except Exception as e:
        baseline = {
            "completed": False,
            "exception": str(e),
            "bundle_name": bundle_name,
            "bundle_root": str(run_root / bundle_name),
            "ir_path": "",
            "puml_path": "",
            "validation_path": "",
            "layer5_path": "",
            "det_ok": False,
            "layer5_ok": False,
            "overall_valid": False,
            "structural_valid": False,
            "downstream_ready": False,
            "det_error_count": 0,
            "det_warning_count": 0,
            "det_schema_error_count": 0,
            "layer5_issue_count": 0,
            "layer5_error_count": 0,
            "layer5_warning_count": 0,
            "layer5_codes": "",
            "total_issue_count": 0,
            "total_error_count": 0,
            "state_count": 0,
            "transition_count": 0,
            **_coverage_for_scenario(scenario, {"devices": set(), "triggers": set(), "actions": set()}),
            "_present_tokens": {"devices": set(), "triggers": set(), "actions": set()},
        }

    if not baseline["completed"]:
        post = {
            "completed": False,
            "exception": "Skipped because the baseline run failed.",
            "bundle_name": bundle_name,
            "bundle_root": baseline["bundle_root"],
            "revision_dir": "",
            "ir_path": "",
            "puml_path": "",
            "validation_path": "",
            "layer5_path": "",
            "summary_json_path": "",
            "det_ok": False,
            "layer5_ok": False,
            "overall_valid": False,
            "structural_valid": False,
            "downstream_ready": False,
            "det_error_count": 0,
            "det_warning_count": 0,
            "det_schema_error_count": 0,
            "layer5_issue_count": 0,
            "layer5_error_count": 0,
            "layer5_warning_count": 0,
            "layer5_codes": "",
            "total_issue_count": 0,
            "total_error_count": 0,
            "state_count": 0,
            "transition_count": 0,
            **_coverage_for_scenario(scenario, {"devices": set(), "triggers": set(), "actions": set()}),
            "iterations_run": 0,
            "stop_reason": "Baseline failed",
            "_present_tokens": {"devices": set(), "triggers": set(), "actions": set()},
        }
        return {"baseline": baseline, "post": post}

    try:
        refine_paths, _summary = run_refine(
            bundle_name=bundle_name,
            out_dir=run_root,
            settings=settings,
            use_mock=use_mock,
            max_iters=refine_max_iters,
            max_patch_repairs=refine_max_patch_repairs,
        )
        post_report = _read_validation_report(refine_paths["validation"])
        post_layer5_report = read_json(refine_paths["layer5"])
        post_summary = read_json(refine_paths["summary_json"]) if Path(refine_paths["summary_json"]).exists() else {}
        post_ir = read_json(refine_paths["ir"])
        post_counts = _count_diags(post_report)
        post_agent_counts = _count_agentic(post_layer5_report)
        post_present = extract_present_tokens(post_ir)
        post_struct = _state_machine_counts(post_ir)
        post_det_ok = bool(post_report.get("ok", False))
        post_l5_ok = bool(post_layer5_report.get("ok", False))
        post = {
            "completed": True,
            "exception": "",
            "bundle_name": bundle_name,
            "bundle_root": str(refine_paths["bundle_root"]),
            "revision_dir": str(refine_paths["revision_dir"]),
            "ir_path": str(refine_paths["ir"]),
            "puml_path": str(refine_paths["puml"]),
            "validation_path": str(refine_paths["validation"]),
            "layer5_path": str(refine_paths["layer5"]),
            "summary_json_path": str(refine_paths["summary_json"]),
            "det_ok": post_det_ok,
            "layer5_ok": post_l5_ok,
            "overall_valid": post_det_ok and post_l5_ok,
            "structural_valid": post_det_ok and Path(refine_paths["puml"]).exists(),
            "downstream_ready": _downstream_ready(
                det_ok=post_det_ok,
                layer5_ok=post_l5_ok,
                ir=post_ir,
                puml_path=Path(refine_paths["puml"]),
            ),
            "det_error_count": post_counts["error_count"],
            "det_warning_count": post_counts["warning_count"],
            "det_schema_error_count": post_counts["schema_error_count"],
            "layer5_issue_count": post_agent_counts["issue_count"],
            "layer5_error_count": post_agent_counts["error_count"],
            "layer5_warning_count": post_agent_counts["warning_count"],
            "layer5_codes": post_agent_counts["codes_str"],
            "total_issue_count": post_counts["error_count"] + post_counts["warning_count"] + post_agent_counts["issue_count"],
            "total_error_count": post_counts["error_count"] + post_agent_counts["error_count"],
            **post_struct,
            **_coverage_for_scenario(scenario, post_present),
            "iterations_run": int(post_summary.get("iterations_run", 0) or 0),
            "stop_reason": str(post_summary.get("stop_reason", "")),
            "_present_tokens": post_present,
        }
    except Exception as e:
        post = {
            "completed": False,
            "exception": str(e),
            "bundle_name": bundle_name,
            "bundle_root": baseline["bundle_root"],
            "revision_dir": "",
            "ir_path": "",
            "puml_path": "",
            "validation_path": "",
            "layer5_path": "",
            "summary_json_path": "",
            "det_ok": False,
            "layer5_ok": False,
            "overall_valid": False,
            "structural_valid": False,
            "downstream_ready": False,
            "det_error_count": 0,
            "det_warning_count": 0,
            "det_schema_error_count": 0,
            "layer5_issue_count": 0,
            "layer5_error_count": 0,
            "layer5_warning_count": 0,
            "layer5_codes": "",
            "total_issue_count": 0,
            "total_error_count": 0,
            "state_count": 0,
            "transition_count": 0,
            **_coverage_for_scenario(scenario, {"devices": set(), "triggers": set(), "actions": set()}),
            "iterations_run": 0,
            "stop_reason": "Refine failed",
            "_present_tokens": {"devices": set(), "triggers": set(), "actions": set()},
        }

    return {"baseline": baseline, "post": post}


def _pair_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    a_tokens = a.get("_present_tokens", {"devices": set(), "triggers": set(), "actions": set()})
    b_tokens = b.get("_present_tokens", {"devices": set(), "triggers": set(), "actions": set()})
    same_devices = a_tokens.get("devices", set()) == b_tokens.get("devices", set())
    same_triggers = a_tokens.get("triggers", set()) == b_tokens.get("triggers", set())
    same_actions = a_tokens.get("actions", set()) == b_tokens.get("actions", set())
    same_topology = (
        int(a.get("state_count", 0)) == int(b.get("state_count", 0))
        and int(a.get("transition_count", 0)) == int(b.get("transition_count", 0))
    )
    score = mean([same_devices, same_triggers, same_actions, same_topology])
    return {
        "same_devices": same_devices,
        "same_triggers": same_triggers,
        "same_actions": same_actions,
        "same_topology": same_topology,
        "similarity_score": round(float(score), 4),
    }


def _safe_remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _collect_roundtrip_snapshot(
    *,
    ir_path: Path,
    validation_path: Path,
    puml_path: Path,
    layer5_path: Path,
) -> Dict[str, Any]:
    report = _read_validation_report(validation_path)
    ir = read_json(ir_path)
    _issues, layer5_report = validate_agentic(ir)
    write_json(layer5_path, layer5_report)
    det_counts = _count_diags(report)
    layer5_counts = _count_agentic(layer5_report)
    present = extract_present_tokens(ir)
    struct = _state_machine_counts(ir)
    det_ok = bool(report.get("ok", False))
    l5_ok = bool(layer5_report.get("ok", False))
    return {
        "completed": True,
        "exception": "",
        "ir_path": str(ir_path),
        "puml_path": str(puml_path),
        "validation_path": str(validation_path),
        "layer5_path": str(layer5_path),
        "det_ok": det_ok,
        "layer5_ok": l5_ok,
        "overall_valid": det_ok and l5_ok,
        "structural_valid": det_ok and puml_path.exists(),
        "downstream_ready": _downstream_ready(det_ok=det_ok, layer5_ok=l5_ok, ir=ir, puml_path=puml_path),
        "det_error_count": det_counts["error_count"],
        "det_warning_count": det_counts["warning_count"],
        "det_schema_error_count": det_counts["schema_error_count"],
        "layer5_issue_count": layer5_counts["issue_count"],
        "layer5_error_count": layer5_counts["error_count"],
        "layer5_warning_count": layer5_counts["warning_count"],
        "layer5_codes": layer5_counts["codes_str"],
        "total_issue_count": det_counts["error_count"] + det_counts["warning_count"] + layer5_counts["issue_count"],
        "total_error_count": det_counts["error_count"] + layer5_counts["error_count"],
        **struct,
        "_present_tokens": present,
    }


def _run_adversarial_suite(
    *,
    out_dir: Path,
    settings: Settings,
    use_mock: bool,
    refine_max_iters: int,
    refine_max_patch_repairs: int,
    source_dir: Path,
    bundle_names: Sequence[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    runs_root = out_dir / "runs" / "adversarial"
    rows: List[Dict[str, Any]] = []

    for bundle_name in bundle_names:
        src_root = source_dir / bundle_name
        row: Dict[str, Any] = {
            "bundle_name": bundle_name,
            "source_bundle_root": str(src_root),
            "source_edited_puml": str(src_root / "edited.puml"),
            "source_baseline_ir": str(src_root / "baseline" / "final.ir.json"),
        }
        edited_puml = src_root / "edited.puml"
        baseline_ir = src_root / "baseline" / "final.ir.json"
        if not edited_puml.exists() or not baseline_ir.exists():
            row.update(
                {
                    "completed": False,
                    "exception": "Missing edited.puml or baseline/final.ir.json in source bundle.",
                    "repair_effective": False,
                    "issues_removed": 0,
                    "errors_removed": 0,
                }
            )
            rows.append(row)
            continue

        dest_bundle_root = runs_root / bundle_name
        _safe_remove_tree(dest_bundle_root)
        try:
            rt_paths, rt_summary = run_roundtrip(
                puml_path=edited_puml,
                out_bundle_dir=dest_bundle_root,
                settings=settings,
                baseline_ir_path=baseline_ir,
            )
            pre = _collect_roundtrip_snapshot(
                ir_path=Path(rt_paths["ir"]),
                validation_path=Path(rt_paths["validation"]),
                puml_path=Path(rt_paths["puml"]),
                layer5_path=Path(rt_paths["revision_dir"]) / "l5.validation_agent.json",
            )
            refine_paths, _ = run_refine(
                bundle_name=bundle_name,
                out_dir=runs_root,
                settings=settings,
                use_mock=use_mock,
                max_iters=refine_max_iters,
                max_patch_repairs=refine_max_patch_repairs,
            )
            post_report = _read_validation_report(Path(refine_paths["validation"]))
            post_layer5 = read_json(Path(refine_paths["layer5"]))
            post_summary = read_json(Path(refine_paths["summary_json"])) if Path(refine_paths["summary_json"]).exists() else {}
            post_ir = read_json(Path(refine_paths["ir"]))
            post_counts = _count_diags(post_report)
            post_layer5_counts = _count_agentic(post_layer5)
            post_present = extract_present_tokens(post_ir)
            post_struct = _state_machine_counts(post_ir)
            post_det_ok = bool(post_report.get("ok", False))
            post_l5_ok = bool(post_layer5.get("ok", False))
            post = {
                "completed": True,
                "exception": "",
                "revision_dir": str(refine_paths["revision_dir"]),
                "ir_path": str(refine_paths["ir"]),
                "puml_path": str(refine_paths["puml"]),
                "validation_path": str(refine_paths["validation"]),
                "layer5_path": str(refine_paths["layer5"]),
                "summary_json_path": str(refine_paths["summary_json"]),
                "det_ok": post_det_ok,
                "layer5_ok": post_l5_ok,
                "overall_valid": post_det_ok and post_l5_ok,
                "structural_valid": post_det_ok and Path(refine_paths["puml"]).exists(),
                "downstream_ready": _downstream_ready(det_ok=post_det_ok, layer5_ok=post_l5_ok, ir=post_ir, puml_path=Path(refine_paths["puml"])),
                "det_error_count": post_counts["error_count"],
                "det_warning_count": post_counts["warning_count"],
                "det_schema_error_count": post_counts["schema_error_count"],
                "layer5_issue_count": post_layer5_counts["issue_count"],
                "layer5_error_count": post_layer5_counts["error_count"],
                "layer5_warning_count": post_layer5_counts["warning_count"],
                "layer5_codes": post_layer5_counts["codes_str"],
                "total_issue_count": post_counts["error_count"] + post_counts["warning_count"] + post_layer5_counts["issue_count"],
                "total_error_count": post_counts["error_count"] + post_layer5_counts["error_count"],
                **post_struct,
                "iterations_run": int(post_summary.get("iterations_run", 0) or 0),
                "stop_reason": str(post_summary.get("stop_reason", "")),
                "_present_tokens": post_present,
            }
            row.update(
                {
                    "completed": True,
                    **_prefixed("pre_", pre),
                    **_prefixed("post_", post),
                    "repair_effective": (not pre["overall_valid"]) and post["overall_valid"],
                    "issues_removed": pre["total_issue_count"] - post["total_issue_count"],
                    "errors_removed": pre["total_error_count"] - post["total_error_count"],
                }
            )
        except Exception as e:
            row.update(
                {
                    "completed": False,
                    "exception": str(e),
                    "repair_effective": False,
                    "issues_removed": 0,
                    "errors_removed": 0,
                }
            )
        rows.append(row)

    completed_rows = [r for r in rows if r.get("completed")]
    initially_invalid = [r for r in completed_rows if not _bool(r.get("pre_overall_valid"))]
    repaired = [r for r in initially_invalid if _bool(r.get("repair_effective"))]
    summary = {
        "bundles_requested": len(bundle_names),
        "bundles_completed": len(completed_rows),
        "initially_invalid": len(initially_invalid),
        "repair_effective_count": len(repaired),
        "repair_effective_rate": round((len(repaired) / len(initially_invalid)), 4) if initially_invalid else 0.0,
        "final_valid_count": sum(1 for r in completed_rows if _bool(r.get("post_overall_valid"))),
        "final_valid_rate": round((sum(1 for r in completed_rows if _bool(r.get("post_overall_valid"))) / len(completed_rows)), 4) if completed_rows else 0.0,
        "avg_issues_removed": round(mean([float(r.get("issues_removed", 0)) for r in completed_rows]), 4) if completed_rows else 0.0,
        "avg_iterations": round(mean([float(r.get("post_iterations_run", 0)) for r in completed_rows]), 4) if completed_rows else 0.0,
    }
    return rows, summary


def _build_report(
    *,
    out_dir: Path,
    summary: Dict[str, Any],
    scenario_rows: List[Dict[str, Any]],
    paraphrase_rows: List[Dict[str, Any]],
    adversarial_rows: List[Dict[str, Any]],
) -> str:
    scenario_failures = [r for r in scenario_rows if not _bool(r.get("post_completed")) or not _bool(r.get("post_overall_valid"))]
    scenario_failures = sorted(
        scenario_failures,
        key=lambda r: (not _bool(r.get("post_completed")), int(r.get("post_total_issue_count", 0)) * -1),
    )[:10]

    stop_reason_counts: Dict[str, int] = {}
    for r in scenario_rows:
        reason = str(r.get("post_stop_reason", "") or "")
        if not reason:
            continue
        stop_reason_counts[reason] = stop_reason_counts.get(reason, 0) + 1

    lines: List[str] = [
        "# Full Pipeline Evaluation Report",
        "",
        f"Output directory: `{out_dir.as_posix()}`",
        "",
        "## Primary scenario benchmark",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Scenarios requested", summary["scenario_benchmark"]["scenarios_requested"]],
                ["Scenarios completed", summary["scenario_benchmark"]["scenarios_completed"]],
                ["Pre structural validity rate", summary["scenario_benchmark"]["pre_structural_valid_rate"]],
                ["Pre overall validity rate", summary["scenario_benchmark"]["pre_overall_valid_rate"]],
                ["Post structural validity rate", summary["scenario_benchmark"]["post_structural_valid_rate"]],
                ["Post overall validity rate", summary["scenario_benchmark"]["post_overall_valid_rate"]],
                ["Repair effectiveness rate", summary["scenario_benchmark"]["repair_effective_rate"]],
                ["Pre downstream readiness rate", summary["scenario_benchmark"]["pre_downstream_ready_rate"]],
                ["Post downstream readiness rate", summary["scenario_benchmark"]["post_downstream_ready_rate"]],
                ["Avg issues before", summary["scenario_benchmark"]["avg_pre_total_issues"]],
                ["Avg issues after", summary["scenario_benchmark"]["avg_post_total_issues"]],
                ["Avg issues removed", summary["scenario_benchmark"]["avg_issues_removed"]],
                ["Avg iterations", summary["scenario_benchmark"]["avg_iterations"]],
                ["Avg pre coverage", summary["scenario_benchmark"]["avg_pre_overall_coverage"]],
                ["Avg post coverage", summary["scenario_benchmark"]["avg_post_overall_coverage"]],
            ],
        ),
        "",
        "## Refine stop reasons",
        "",
        _markdown_table(["Stop reason", "Count"], [[k, v] for k, v in sorted(stop_reason_counts.items())]) if stop_reason_counts else "No stop reasons recorded.",
        "",
        "## Scenario failures / unresolved cases",
        "",
        _markdown_table(
            ["Scenario", "Pre valid", "Post valid", "Pre issues", "Post issues", "Iterations", "Stop reason"],
            [
                [
                    r.get("scenario_id", ""),
                    r.get("pre_overall_valid", ""),
                    r.get("post_overall_valid", ""),
                    r.get("pre_total_issue_count", ""),
                    r.get("post_total_issue_count", ""),
                    r.get("post_iterations_run", ""),
                    r.get("post_stop_reason", ""),
                ]
                for r in scenario_failures
            ],
        ) if scenario_failures else "All completed scenario runs finished valid after refinement.",
        "",
        "## Paraphrase robustness",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Paraphrase pairs evaluated", summary["paraphrase_benchmark"]["pairs_evaluated"]],
                ["Primary variant pre-valid rate", summary["paraphrase_benchmark"]["primary_pre_valid_rate"]],
                ["Paraphrase variant pre-valid rate", summary["paraphrase_benchmark"]["paraphrase_pre_valid_rate"]],
                ["Primary variant post-valid rate", summary["paraphrase_benchmark"]["primary_post_valid_rate"]],
                ["Paraphrase variant post-valid rate", summary["paraphrase_benchmark"]["paraphrase_post_valid_rate"]],
                ["Pre validity consistency rate", summary["paraphrase_benchmark"]["pre_validity_consistency_rate"]],
                ["Post validity consistency rate", summary["paraphrase_benchmark"]["post_validity_consistency_rate"]],
                ["Post exact token/topology consistency rate", summary["paraphrase_benchmark"]["post_exact_consistency_rate"]],
                ["Mean post similarity score", summary["paraphrase_benchmark"]["mean_post_similarity_score"]],
            ],
        ),
        "",
        "## Adversarial repair suite",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Bundles requested", summary["adversarial_suite"]["bundles_requested"]],
                ["Bundles completed", summary["adversarial_suite"]["bundles_completed"]],
                ["Initially invalid bundles", summary["adversarial_suite"]["initially_invalid"]],
                ["Repair effectiveness rate", summary["adversarial_suite"]["repair_effective_rate"]],
                ["Final valid rate", summary["adversarial_suite"]["final_valid_rate"]],
                ["Avg issues removed", summary["adversarial_suite"]["avg_issues_removed"]],
                ["Avg iterations", summary["adversarial_suite"]["avg_iterations"]],
            ],
        ),
        "",
        _markdown_table(
            ["Bundle", "Pre valid", "Post valid", "Issues removed", "Iterations", "Stop reason"],
            [
                [
                    r.get("bundle_name", ""),
                    r.get("pre_overall_valid", ""),
                    r.get("post_overall_valid", ""),
                    r.get("issues_removed", ""),
                    r.get("post_iterations_run", ""),
                    r.get("post_stop_reason", ""),
                ]
                for r in adversarial_rows
            ],
        ) if adversarial_rows else "No adversarial bundles were evaluated.",
        "",
        "## Artifacts",
        "",
        _markdown_table(
            ["Artifact", "Path"],
            [
                ["Per-scenario CSV", summary["artifacts"]["scenario_results_csv"]],
                ["Paraphrase CSV", summary["artifacts"]["paraphrase_results_csv"]],
                ["Adversarial CSV", summary["artifacts"]["adversarial_results_csv"]],
                ["Summary CSV", summary["artifacts"]["summary_csv"]],
                ["Summary JSON", summary["artifacts"]["summary_json"]],
            ],
        ),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def run_full_metrics(
    *,
    scenarios_path: Path,
    out_dir: Path,
    settings: Settings,
    use_mock: bool = False,
    pre_max_repairs: int = 0,
    refine_max_iters: int = 5,
    refine_max_patch_repairs: int = 2,
    limit: Optional[int] = None,
    include_paraphrases: bool = True,
    include_adversarial: bool = True,
    adversarial_source_dir: Optional[Path] = None,
    adversarial_bundles: Optional[Sequence[str]] = None,
) -> Dict[str, Path]:
    scenarios = load_scenarios_csv(scenarios_path, limit=limit)
    out_dir.mkdir(parents=True, exist_ok=True)

    primary_root = out_dir / "runs" / "primary"
    paraphrase_root = out_dir / "runs" / "paraphrases"

    scenario_rows: List[Dict[str, Any]] = []
    primary_cases: Dict[str, Dict[str, Any]] = {}

    for sc in scenarios:
        result = _run_single_case(
            text=sc.nl_prompt,
            bundle_name=f"{sc.scenario_id}__primary",
            run_root=primary_root,
            settings=settings,
            use_mock=use_mock,
            pre_max_repairs=pre_max_repairs,
            refine_max_iters=refine_max_iters,
            refine_max_patch_repairs=refine_max_patch_repairs,
            scenario=sc,
        )
        pre = result["baseline"]
        post = result["post"]
        primary_cases[sc.scenario_id] = result
        scenario_rows.append(
            {
                "scenario_id": sc.scenario_id,
                "nl_prompt": sc.nl_prompt,
                "original_prompt": sc.original_prompt,
                "req_devices": "|".join(sc.req_devices),
                "req_triggers": "|".join(sc.req_triggers),
                "req_actions": "|".join(sc.req_actions),
                "req_conditions": "|".join(sc.req_conditions),
                **_prefixed("pre_", pre),
                **_prefixed("post_", post),
                "repair_effective": (not pre["overall_valid"]) and post["overall_valid"],
                "issues_removed": pre["total_issue_count"] - post["total_issue_count"] if post["completed"] else 0,
                "errors_removed": pre["total_error_count"] - post["total_error_count"] if post["completed"] else 0,
                "coverage_delta": round(float(post.get("overall_coverage", 0.0)) - float(pre.get("overall_coverage", 0.0)), 4) if post["completed"] else 0.0,
            }
        )

    completed_primary = [r for r in scenario_rows if _bool(r.get("pre_completed")) and _bool(r.get("post_completed"))]
    initially_invalid_primary = [r for r in completed_primary if not _bool(r.get("pre_overall_valid"))]
    repair_effective_primary = [r for r in initially_invalid_primary if _bool(r.get("repair_effective"))]
    scenario_summary = {
        "scenarios_requested": len(scenarios),
        "scenarios_completed": len(completed_primary),
        "pre_structural_valid_rate": round((sum(1 for r in completed_primary if _bool(r.get("pre_structural_valid"))) / len(completed_primary)), 4) if completed_primary else 0.0,
        "pre_overall_valid_rate": round((sum(1 for r in completed_primary if _bool(r.get("pre_overall_valid"))) / len(completed_primary)), 4) if completed_primary else 0.0,
        "post_structural_valid_rate": round((sum(1 for r in completed_primary if _bool(r.get("post_structural_valid"))) / len(completed_primary)), 4) if completed_primary else 0.0,
        "post_overall_valid_rate": round((sum(1 for r in completed_primary if _bool(r.get("post_overall_valid"))) / len(completed_primary)), 4) if completed_primary else 0.0,
        "pre_downstream_ready_rate": round((sum(1 for r in completed_primary if _bool(r.get("pre_downstream_ready"))) / len(completed_primary)), 4) if completed_primary else 0.0,
        "post_downstream_ready_rate": round((sum(1 for r in completed_primary if _bool(r.get("post_downstream_ready"))) / len(completed_primary)), 4) if completed_primary else 0.0,
        "repair_effective_count": len(repair_effective_primary),
        "repair_effective_rate": round((len(repair_effective_primary) / len(initially_invalid_primary)), 4) if initially_invalid_primary else 0.0,
        "avg_pre_total_issues": round(mean([float(r.get("pre_total_issue_count", 0)) for r in completed_primary]), 4) if completed_primary else 0.0,
        "avg_post_total_issues": round(mean([float(r.get("post_total_issue_count", 0)) for r in completed_primary]), 4) if completed_primary else 0.0,
        "avg_issues_removed": round(mean([float(r.get("issues_removed", 0)) for r in completed_primary]), 4) if completed_primary else 0.0,
        "avg_iterations": round(mean([float(r.get("post_iterations_run", 0)) for r in completed_primary]), 4) if completed_primary else 0.0,
        "avg_pre_overall_coverage": round(mean([float(r.get("pre_overall_coverage", 0.0)) for r in completed_primary]), 4) if completed_primary else 0.0,
        "avg_post_overall_coverage": round(mean([float(r.get("post_overall_coverage", 0.0)) for r in completed_primary]), 4) if completed_primary else 0.0,
    }

    paraphrase_rows: List[Dict[str, Any]] = []
    if include_paraphrases:
        for sc in scenarios:
            original = sc.original_prompt.strip()
            if not original or _normalize_text(original) == _normalize_text(sc.nl_prompt):
                continue
            alt = _run_single_case(
                text=original,
                bundle_name=f"{sc.scenario_id}__paraphrase",
                run_root=paraphrase_root,
                settings=settings,
                use_mock=use_mock,
                pre_max_repairs=pre_max_repairs,
                refine_max_iters=refine_max_iters,
                refine_max_patch_repairs=refine_max_patch_repairs,
                scenario=sc,
            )
            primary = primary_cases[sc.scenario_id]
            pre_sim = _pair_similarity(primary["baseline"], alt["baseline"])
            post_sim = _pair_similarity(primary["post"], alt["post"])
            paraphrase_rows.append(
                {
                    "scenario_id": sc.scenario_id,
                    "primary_prompt": sc.nl_prompt,
                    "paraphrase_prompt": original,
                    "primary_pre_valid": primary["baseline"]["overall_valid"],
                    "paraphrase_pre_valid": alt["baseline"]["overall_valid"],
                    "primary_post_valid": primary["post"]["overall_valid"],
                    "paraphrase_post_valid": alt["post"]["overall_valid"],
                    "primary_pre_downstream_ready": primary["baseline"]["downstream_ready"],
                    "paraphrase_pre_downstream_ready": alt["baseline"]["downstream_ready"],
                    "primary_post_downstream_ready": primary["post"]["downstream_ready"],
                    "paraphrase_post_downstream_ready": alt["post"]["downstream_ready"],
                    "pre_validity_consistent": primary["baseline"]["overall_valid"] == alt["baseline"]["overall_valid"],
                    "post_validity_consistent": primary["post"]["overall_valid"] == alt["post"]["overall_valid"],
                    "pre_same_devices": pre_sim["same_devices"],
                    "pre_same_triggers": pre_sim["same_triggers"],
                    "pre_same_actions": pre_sim["same_actions"],
                    "pre_same_topology": pre_sim["same_topology"],
                    "pre_similarity_score": pre_sim["similarity_score"],
                    "post_same_devices": post_sim["same_devices"],
                    "post_same_triggers": post_sim["same_triggers"],
                    "post_same_actions": post_sim["same_actions"],
                    "post_same_topology": post_sim["same_topology"],
                    "post_similarity_score": post_sim["similarity_score"],
                    "post_exact_consistency": all([
                        post_sim["same_devices"],
                        post_sim["same_triggers"],
                        post_sim["same_actions"],
                        post_sim["same_topology"],
                    ]),
                }
            )

    paraphrase_summary = {
        "pairs_evaluated": len(paraphrase_rows),
        "primary_pre_valid_rate": round((sum(1 for r in paraphrase_rows if _bool(r.get("primary_pre_valid"))) / len(paraphrase_rows)), 4) if paraphrase_rows else 0.0,
        "paraphrase_pre_valid_rate": round((sum(1 for r in paraphrase_rows if _bool(r.get("paraphrase_pre_valid"))) / len(paraphrase_rows)), 4) if paraphrase_rows else 0.0,
        "primary_post_valid_rate": round((sum(1 for r in paraphrase_rows if _bool(r.get("primary_post_valid"))) / len(paraphrase_rows)), 4) if paraphrase_rows else 0.0,
        "paraphrase_post_valid_rate": round((sum(1 for r in paraphrase_rows if _bool(r.get("paraphrase_post_valid"))) / len(paraphrase_rows)), 4) if paraphrase_rows else 0.0,
        "pre_validity_consistency_rate": round((sum(1 for r in paraphrase_rows if _bool(r.get("pre_validity_consistent"))) / len(paraphrase_rows)), 4) if paraphrase_rows else 0.0,
        "post_validity_consistency_rate": round((sum(1 for r in paraphrase_rows if _bool(r.get("post_validity_consistent"))) / len(paraphrase_rows)), 4) if paraphrase_rows else 0.0,
        "post_exact_consistency_rate": round((sum(1 for r in paraphrase_rows if _bool(r.get("post_exact_consistency"))) / len(paraphrase_rows)), 4) if paraphrase_rows else 0.0,
        "mean_post_similarity_score": round(mean([float(r.get("post_similarity_score", 0.0)) for r in paraphrase_rows]), 4) if paraphrase_rows else 0.0,
    }

    adv_rows: List[Dict[str, Any]] = []
    adversarial_summary = {
        "bundles_requested": 0,
        "bundles_completed": 0,
        "initially_invalid": 0,
        "repair_effective_count": 0,
        "repair_effective_rate": 0.0,
        "final_valid_count": 0,
        "final_valid_rate": 0.0,
        "avg_issues_removed": 0.0,
        "avg_iterations": 0.0,
    }
    if include_adversarial:
        src_dir = adversarial_source_dir or (Path("outputs"))
        bundle_names = tuple(adversarial_bundles or DEFAULT_ADVERSARIAL_BUNDLES)
        existing = [b for b in bundle_names if (src_dir / b).exists()]
        adv_rows, adversarial_summary = _run_adversarial_suite(
            out_dir=out_dir,
            settings=settings,
            use_mock=use_mock,
            refine_max_iters=refine_max_iters,
            refine_max_patch_repairs=refine_max_patch_repairs,
            source_dir=src_dir,
            bundle_names=existing,
        )
        adversarial_summary["bundles_requested"] = len(bundle_names)

    scenario_csv = out_dir / "scenario_results.csv"
    paraphrase_csv = out_dir / "paraphrase_results.csv"
    adversarial_csv = out_dir / "adversarial_results.csv"
    summary_csv = out_dir / "summary.csv"
    summary_json = out_dir / "summary.json"
    report_md = out_dir / "report.md"

    _write_csv(scenario_csv, scenario_rows)
    _write_csv(paraphrase_csv, paraphrase_rows)
    _write_csv(adversarial_csv, adv_rows)

    summary = {
        "config": {
            "scenarios_path": str(scenarios_path),
            "out_dir": str(out_dir),
            "use_mock": bool(use_mock),
            "pre_max_repairs": int(pre_max_repairs),
            "refine_max_iters": int(refine_max_iters),
            "refine_max_patch_repairs": int(refine_max_patch_repairs),
            "include_paraphrases": bool(include_paraphrases),
            "include_adversarial": bool(include_adversarial),
        },
        "scenario_benchmark": scenario_summary,
        "paraphrase_benchmark": paraphrase_summary,
        "adversarial_suite": adversarial_summary,
        "artifacts": {
            "scenario_results_csv": str(scenario_csv),
            "paraphrase_results_csv": str(paraphrase_csv),
            "adversarial_results_csv": str(adversarial_csv),
            "summary_csv": str(summary_csv),
            "summary_json": str(summary_json),
            "report_md": str(report_md),
        },
    }

    write_json(summary_json, summary)
    _write_csv(summary_csv, _summary_csv_rows(summary))
    write_text(
        report_md,
        _build_report(
            out_dir=out_dir,
            summary=summary,
            scenario_rows=scenario_rows,
            paraphrase_rows=paraphrase_rows,
            adversarial_rows=adv_rows,
        ),
    )

    return {
        "scenario_results_csv": scenario_csv,
        "paraphrase_results_csv": paraphrase_csv,
        "adversarial_results_csv": adversarial_csv,
        "summary_csv": summary_csv,
        "summary_json": summary_json,
        "report_md": report_md,
        "runs_dir": out_dir / "runs",
    }

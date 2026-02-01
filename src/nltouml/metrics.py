from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .config import Settings
from .io_utils import read_json, write_json
from .pipeline import PipelineError, run_pipeline


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    nl_prompt: str
    original_prompt: str
    req_devices: Tuple[str, ...]
    req_triggers: Tuple[str, ...]
    req_actions: Tuple[str, ...]
    req_conditions: Tuple[str, ...]


def _split_pipe(cell: Optional[str]) -> Tuple[str, ...]:
    if cell is None:
        return ()
    s = str(cell).strip()
    if s == "" or s.lower() == "nan":
        return ()
    parts = [p.strip() for p in s.split("|") if p.strip()]
    return tuple(parts)


def load_scenarios_csv(path: Path, limit: Optional[int] = None) -> List[Scenario]:
    if not path.exists():
        raise PipelineError(f"scenarios file not found: {path}")

    out: List[Scenario] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        required_cols = {"scenario_id", "nl_prompt", "original_prompt"}
        missing = required_cols.difference(set(r.fieldnames or []))
        if missing:
            raise PipelineError(f"scenarios.csv missing columns: {sorted(missing)}")

        for row in r:
            sid = (row.get("scenario_id") or "").strip()
            if not sid:
                continue
            out.append(
                Scenario(
                    scenario_id=sid,
                    nl_prompt=(row.get("nl_prompt") or "").strip(),
                    original_prompt=(row.get("original_prompt") or "").strip(),
                    req_devices=_split_pipe(row.get("req_devices")),
                    req_triggers=_split_pipe(row.get("req_triggers")),
                    req_actions=_split_pipe(row.get("req_actions")),
                    req_conditions=_split_pipe(row.get("req_conditions")),
                )
            )
            if limit is not None and len(out) >= limit:
                break
    return out


def _lit_to_str(lit: Dict[str, Any]) -> str:
    if "string" in lit:
        return str(lit["string"])
    if "number" in lit:
        # keep integers clean
        n = lit["number"]
        if isinstance(n, (int, float)) and float(n).is_integer():
            return str(int(n))
        return str(n)
    if "bool" in lit:
        return "true" if bool(lit["bool"]) else "false"
    return ""


def extract_present_tokens(ir: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Extract comparable token sets from an IR for coverage scoring.

    The tokens are intentionally simple and aligned with the scenarios.csv format:
    - devices: device ids
    - triggers: becomes(device.attr,value), changes(device.attr), after(seconds), schedule(cron)
    - actions: command(device,cmd), delay(seconds), notify()

    Conditions are not tokenized here (guards can be arbitrarily complex). If you later
    want guard coverage, add a guard normalizer + tokenizer.
    """

    devices: Set[str] = set()
    triggers: Set[str] = set()
    actions: Set[str] = set()

    for d in ir.get("devices", []) if isinstance(ir.get("devices", []), list) else []:
        if isinstance(d, dict) and isinstance(d.get("id"), str):
            devices.add(d["id"])

    sm = ir.get("stateMachine") if isinstance(ir.get("stateMachine"), dict) else {}
    transitions = sm.get("transitions", []) if isinstance(sm.get("transitions", []), list) else []
    for tr in transitions:
        if not isinstance(tr, dict):
            continue

        # triggers
        for tg in tr.get("triggers", []) if isinstance(tr.get("triggers", []), list) else []:
            if not isinstance(tg, dict):
                continue
            ttype = tg.get("type")
            if ttype in ("becomes", "changes"):
                ref = tg.get("ref")
                if isinstance(ref, dict) and isinstance(ref.get("device"), str) and isinstance(ref.get("path"), str):
                    dev = ref["device"]
                    path = ref["path"]
                    if ttype == "changes":
                        triggers.add(f"changes({dev}.{path})")
                    else:
                        val = tg.get("value")
                        if isinstance(val, dict):
                            v = _lit_to_str(val)
                            triggers.add(f"becomes({dev}.{path},{v})")
            elif ttype == "after":
                sec = tg.get("seconds")
                if isinstance(sec, int):
                    triggers.add(f"after({sec})")
            elif ttype == "schedule":
                cron = tg.get("cron")
                if isinstance(cron, str):
                    triggers.add(f"schedule({cron})")

        # actions
        for act in tr.get("actions", []) if isinstance(tr.get("actions", []), list) else []:
            if not isinstance(act, dict):
                continue
            atype = act.get("type")
            if atype == "command":
                dev = act.get("device")
                cmd = act.get("command")
                if isinstance(dev, str) and isinstance(cmd, str):
                    actions.add(f"command({dev},{cmd})")
            elif atype == "delay":
                sec = act.get("seconds")
                if isinstance(sec, int):
                    actions.add(f"delay({sec})")
            elif atype == "notify":
                # ignore message content for scoring
                actions.add("notify()")

    return {"devices": devices, "triggers": triggers, "actions": actions}


def _coverage(required: Iterable[str], present: Set[str]) -> Tuple[int, int, float, List[str], List[str]]:
    req = [r.strip() for r in required if r and str(r).strip()]
    if not req:
        return 0, 0, 1.0, [], []
    missing = [r for r in req if r not in present]
    found = [r for r in req if r in present]
    return len(found), len(req), (len(found) / len(req)), found, missing


def _read_validation_report(path: Path) -> Dict[str, Any]:
    try:
        return read_json(path)
    except Exception:
        return {"ok": False, "diagnostics": []}


def _count_diags(report: Dict[str, Any]) -> Dict[str, int]:
    diags = report.get("diagnostics", []) if isinstance(report.get("diagnostics", []), list) else []
    errors = [d for d in diags if isinstance(d, dict) and d.get("severity") == "error"]
    warnings = [d for d in diags if isinstance(d, dict) and d.get("severity") == "warning"]
    schema_errors = [d for d in errors if d.get("code") == "E100"]
    return {
        "error_count": len(errors),
        "warning_count": len(warnings),
        "schema_error_count": len(schema_errors),
    }


def run_metrics(
    *,
    scenarios_path: Path,
    out_dir: Path,
    settings: Settings,
    use_mock: bool = False,
    metric1_max_repairs: int = 1,
    metric2_max_repairs: int = 0,
    limit: Optional[int] = None,
) -> Dict[str, Path]:
    """Run metrics 1–3 over scenarios.csv.

    Metric 1: pipeline completion rate for NL->IR->PUML->Schema/Type check
    Metric 2: schema validity rate on first try (metric2_max_repairs defaults to 0)
    Metric 3: constraint coverage (% required devices/triggers/actions present)
    """

    scenarios = load_scenarios_csv(scenarios_path, limit=limit)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs_dir = out_dir / "runs"
    m1_dir = runs_dir / "metric1"
    m2_dir = runs_dir / "metric2"
    m1_dir.mkdir(parents=True, exist_ok=True)
    m2_dir.mkdir(parents=True, exist_ok=True)

    per_rows: List[Dict[str, Any]] = []

    # Optimization: if metric1 and metric2 settings are identical, run once and reuse.
    reuse_one_run = (metric1_max_repairs == metric2_max_repairs)

    for sc in scenarios:
        row: Dict[str, Any] = {
            "scenario_id": sc.scenario_id,
            "nl_prompt": sc.nl_prompt,
            "original_prompt": sc.original_prompt,
            "req_devices": "|".join(sc.req_devices),
            "req_triggers": "|".join(sc.req_triggers),
            "req_actions": "|".join(sc.req_actions),
            "req_conditions": "|".join(sc.req_conditions),
        }

        # ---------- Metric 2 (initial output) ----------
        m2_completed = False
        m2_ok = False
        m2_counts = {"error_count": 0, "warning_count": 0, "schema_error_count": 0}
        m2_present = {"devices": set(), "triggers": set(), "actions": set()}
        m2_ir: Optional[Dict[str, Any]] = None
        m2_paths: Dict[str, Path] = {}
        m2_error_msg: Optional[str] = None

        try:
            m2_paths = run_pipeline(
                text=sc.nl_prompt,
                bundle_name=sc.scenario_id,
                settings=settings,
                out_dir=m2_dir,
                use_mock=use_mock,
                max_repairs=metric2_max_repairs,
            )
            m2_completed = True
            report = _read_validation_report(m2_paths["validation"])
            m2_ok = bool(report.get("ok"))
            m2_counts = _count_diags(report)
            m2_ir = read_json(m2_paths["ir"])
            m2_present = extract_present_tokens(m2_ir)
        except Exception as e:
            m2_error_msg = str(e)

        row.update(
            {
                "m2_completed": m2_completed,
                "m2_ok": m2_ok,
                "m2_error_count": m2_counts["error_count"],
                "m2_warning_count": m2_counts["warning_count"],
                "m2_schema_error_count": m2_counts["schema_error_count"],
                "m2_ir_path": str(m2_paths.get("ir", "")),
                "m2_puml_path": str(m2_paths.get("puml", "")),
                "m2_report_path": str(m2_paths.get("validation", "")),
                "m2_exception": m2_error_msg or "",
            }
        )

        # ---------- Metric 3 (coverage) computed on Metric 2 IR ----------
        dev_found, dev_req, dev_cov, _, dev_missing = _coverage(sc.req_devices, m2_present["devices"])
        trg_found, trg_req, trg_cov, _, trg_missing = _coverage(sc.req_triggers, m2_present["triggers"])
        act_found, act_req, act_cov, _, act_missing = _coverage(sc.req_actions, m2_present["actions"])

        total_req = dev_req + trg_req + act_req
        total_found = dev_found + trg_found + act_found
        overall_cov = 1.0 if total_req == 0 else (total_found / total_req)

        row.update(
            {
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
        )

        # ---------- Metric 1 (completion) ----------
        if reuse_one_run:
            # Metric 1 run is identical to metric 2.
            row.update(
                {
                    "m1_completed": m2_completed,
                    "m1_ok": m2_ok,
                    "m1_error_count": m2_counts["error_count"],
                    "m1_ir_path": row["m2_ir_path"],
                    "m1_puml_path": row["m2_puml_path"],
                    "m1_report_path": row["m2_report_path"],
                    "m1_exception": row["m2_exception"],
                }
            )
        else:
            m1_completed = False
            m1_ok = False
            m1_err_count = 0
            m1_paths: Dict[str, Path] = {}
            m1_error_msg: Optional[str] = None
            try:
                m1_paths = run_pipeline(
                    text=sc.nl_prompt,
                    bundle_name=sc.scenario_id,
                    settings=settings,
                    out_dir=m1_dir,
                    use_mock=use_mock,
                    max_repairs=metric1_max_repairs,
                )
                m1_completed = True
                report = _read_validation_report(m1_paths["validation"])
                m1_ok = bool(report.get("ok"))
                m1_err_count = _count_diags(report)["error_count"]
            except Exception as e:
                m1_error_msg = str(e)

            row.update(
                {
                    "m1_completed": m1_completed,
                    "m1_ok": m1_ok,
                    "m1_error_count": m1_err_count,
                    "m1_ir_path": str(m1_paths.get("ir", "")),
                    "m1_puml_path": str(m1_paths.get("puml", "")),
                    "m1_report_path": str(m1_paths.get("validation", "")),
                    "m1_exception": m1_error_msg or "",
                }
            )

        per_rows.append(row)

    # ---------- Write per-scenario CSV ----------
    per_csv = out_dir / "per_scenario_results.csv"
    if per_rows:
        with per_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(per_rows[0].keys()))
            w.writeheader()
            for r in per_rows:
                w.writerow(r)

    # ---------- Summary metrics ----------
    total = len(per_rows)
    m1_completed = sum(1 for r in per_rows if r.get("m1_completed"))
    m2_completed = sum(1 for r in per_rows if r.get("m2_completed"))

    # Metric 1 completion rate
    m1_completion_rate = 0.0 if total == 0 else (m1_completed / total)

    # Metric 2 schema validity rate (E100 == 0) and full validation ok rate
    schema_valid = sum(1 for r in per_rows if r.get("m2_completed") and int(r.get("m2_schema_error_count", 0)) == 0)
    validation_ok = sum(1 for r in per_rows if r.get("m2_completed") and bool(r.get("m2_ok")))
    schema_valid_rate = 0.0 if m2_completed == 0 else (schema_valid / m2_completed)
    validation_ok_rate = 0.0 if m2_completed == 0 else (validation_ok / m2_completed)

    failed_schema_err_counts = [int(r.get("m2_schema_error_count", 0)) for r in per_rows if r.get("m2_completed") and int(r.get("m2_schema_error_count", 0)) > 0]
    avg_schema_errors_failed = mean(failed_schema_err_counts) if failed_schema_err_counts else 0.0

    # Coverage summary (computed over completed metric2 runs)
    covs = [float(r.get("overall_coverage", 0.0)) for r in per_rows if r.get("m2_completed")]
    avg_coverage = mean(covs) if covs else 0.0

    summary_row = {
        "total_scenarios": total,
        "metric1_completed": m1_completed,
        "metric1_completion_rate": round(m1_completion_rate, 4),
        "metric2_completed": m2_completed,
        "schema_valid_irs": schema_valid,
        "schema_valid_rate": round(schema_valid_rate, 4),
        "validation_ok_irs": validation_ok,
        "validation_ok_rate": round(validation_ok_rate, 4),
        "avg_schema_errors_per_schema_failed_ir": round(avg_schema_errors_failed, 4),
        "avg_constraint_coverage": round(avg_coverage, 4),
        "metric1_max_repairs": metric1_max_repairs,
        "metric2_max_repairs": metric2_max_repairs,
        "use_mock": bool(use_mock),
    }

    summary_csv = out_dir / "metrics_summary.csv"
    with summary_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_row.keys()))
        w.writeheader()
        w.writerow(summary_row)

    # Also store a JSON snapshot for convenience.
    write_json(out_dir / "metrics_summary.json", summary_row)

    return {
        "per_scenario_csv": per_csv,
        "summary_csv": summary_csv,
        "runs_dir": runs_dir,
    }

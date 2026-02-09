from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .io_utils import read_json, write_json, write_text
from .layout import (
    allocate_edit_dir,
    find_bundle_root,
    safe_copy,
    update_current,
    write_manifest,
    build_revision_record,
)
from .normalize import normalize_ir
from .pipeline import PipelineError, load_templates
from .plantuml import ir_to_plantuml
from .transform import desugar_delays_to_timer_states
from .validate import Diagnostic, validate_all


# -----------------------------
# Tokenization + parsing helpers
# -----------------------------


_RE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_ident(s: str) -> bool:
    return bool(_RE_IDENT.match(s))


def _sanitize_ident(s: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_]", "_", s.strip())
    if not out:
        return "State"
    if out[0].isdigit():
        out = "S_" + out
    if not _is_ident(out):
        out = re.sub(r"^[^A-Za-z_]+", "S_", out)
        out = re.sub(r"[^A-Za-z0-9_]", "_", out)
    return out


def _split_escaped_newlines(label: str) -> List[str]:
    # PlantUML multiline label uses the literal sequence "\n" in the .puml file.
    return [p.strip() for p in label.split(r"\n") if p.strip()]


def _parse_literal(tok: str) -> Optional[Dict[str, Any]]:
    t = tok.strip()
    if t.lower() in {"true", "false"}:
        return {"bool": t.lower() == "true"}
    # number
    if re.fullmatch(r"-?\d+", t):
        return {"number": int(t)}
    if re.fullmatch(r"-?\d+\.\d+", t):
        return {"number": float(t)}
    # string
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        inner = t[1:-1]
        # handle simple escapes
        inner = inner.replace(r"\"", '"').replace(r"\\", "\\")
        return {"string": inner}
    return None


class _ExprTokenizer:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def _peek(self) -> str:
        return self.s[self.i : self.i + 1]

    def _eat_ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def next(self) -> Tuple[str, str]:
        self._eat_ws()
        if self.i >= len(self.s):
            return ("EOF", "")

        ch = self._peek()
        if ch in "()":
            self.i += 1
            return (ch, ch)

        # two-char operators
        if self.s.startswith("==", self.i) or self.s.startswith("!=", self.i) or self.s.startswith("<=", self.i) or self.s.startswith(">=", self.i):
            op = self.s[self.i : self.i + 2]
            self.i += 2
            return ("OP", op)
        if ch in "<>":
            self.i += 1
            return ("OP", ch)

        # string literal
        if ch == '"':
            j = self.i + 1
            esc = False
            out = ['"']
            while j < len(self.s):
                c = self.s[j]
                out.append(c)
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    break
                j += 1
            if j >= len(self.s) or self.s[j] != '"':
                # unterminated
                self.i = len(self.s)
                return ("BAD", "".join(out))
            self.i = j + 1
            return ("LIT", "".join(out))

        # number
        m = re.match(r"-?\d+(?:\.\d+)?", self.s[self.i :])
        if m:
            tok = m.group(0)
            self.i += len(tok)
            return ("LIT", tok)

        # keyword / identifier chain
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", self.s[self.i :])
        if m:
            tok = m.group(0)
            self.i += len(tok)
            low = tok.lower()
            if low in {"and", "or", "not"}:
                return ("KW", low)
            if low in {"true", "false"}:
                return ("LIT", low)
            return ("REF", tok)

        # unknown char
        self.i += 1
        return ("BAD", ch)


class _ExprParser:
    def __init__(self, s: str):
        self.tok = _ExprTokenizer(s)
        self.cur = self.tok.next()

    def _eat(self, kind: str, value: Optional[str] = None) -> bool:
        if self.cur[0] != kind:
            return False
        if value is not None and self.cur[1] != value:
            return False
        self.cur = self.tok.next()
        return True

    def parse(self) -> Optional[Dict[str, Any]]:
        expr = self._parse_or()
        if expr is None:
            return None
        if self.cur[0] != "EOF":
            return None
        return expr

    def _parse_or(self) -> Optional[Dict[str, Any]]:
        left = self._parse_and()
        if left is None:
            return None
        args = [left]
        while self.cur == ("KW", "or"):
            self._eat("KW", "or")
            rhs = self._parse_and()
            if rhs is None:
                return None
            args.append(rhs)
        if len(args) == 1:
            return args[0]
        return {"op": "or", "args": args}

    def _parse_and(self) -> Optional[Dict[str, Any]]:
        left = self._parse_cmp()
        if left is None:
            return None
        args = [left]
        while self.cur == ("KW", "and"):
            self._eat("KW", "and")
            rhs = self._parse_cmp()
            if rhs is None:
                return None
            args.append(rhs)
        if len(args) == 1:
            return args[0]
        return {"op": "and", "args": args}

    def _parse_cmp(self) -> Optional[Dict[str, Any]]:
        left = self._parse_unary()
        if left is None:
            return None
        if self.cur[0] == "OP":
            op = self.cur[1]
            self._eat("OP")
            right = self._parse_unary()
            if right is None:
                return None
            op_map = {
                "==": "eq",
                "!=": "neq",
                "<": "lt",
                "<=": "lte",
                ">": "gt",
                ">=": "gte",
            }
            if op not in op_map:
                return None
            return {"op": op_map[op], "args": [left, right]}
        return left

    def _parse_unary(self) -> Optional[Dict[str, Any]]:
        if self.cur == ("KW", "not"):
            self._eat("KW", "not")
            sub = self._parse_unary()
            if sub is None:
                return None
            return {"op": "not", "args": [sub]}
        return self._parse_primary()

    def _parse_primary(self) -> Optional[Dict[str, Any]]:
        if self._eat("("):
            inner = self._parse_or()
            if inner is None:
                return None
            if not self._eat(")"):
                return None
            return inner

        if self.cur[0] == "REF":
            raw = self.cur[1]
            self._eat("REF")
            parts = raw.split(".")
            dev = parts[0]
            path = ".".join(parts[1:]) if len(parts) > 1 else ""
            if not dev or not path:
                return None
            return {"ref": {"device": dev, "path": path}}

        if self.cur[0] == "LIT":
            raw = self.cur[1]
            self._eat("LIT")
            lit = _parse_literal(raw)
            if lit is None:
                return None
            return {"lit": lit}

        return None


def _parse_expr(s: str) -> Optional[Dict[str, Any]]:
    return _ExprParser(s.strip()).parse()


def _parse_trigger(s: str) -> Optional[Dict[str, Any]]:
    t = s.strip()
    if t.lower().startswith("schedule "):
        cron = t[len("schedule ") :].strip()
        if cron:
            return {"type": "schedule", "cron": cron}
        return None

    m = re.fullmatch(r"after\s+(\d+)\s*s", t, flags=re.IGNORECASE)
    if m:
        return {"type": "after", "seconds": int(m.group(1))}

    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s+changes", t)
    if m:
        chain = m.group(1)
        parts = chain.split(".")
        return {"type": "changes", "ref": {"device": parts[0], "path": ".".join(parts[1:])}}

    m = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s+becomes\s+(.+)",
        t,
    )
    if m:
        chain = m.group(1)
        val_s = m.group(2).strip()
        lit = _parse_literal(val_s)
        if lit is None:
            return None
        parts = chain.split(".")
        return {"type": "becomes", "ref": {"device": parts[0], "path": ".".join(parts[1:])}, "value": lit}

    return None


def _parse_action(s: str) -> Optional[Dict[str, Any]]:
    t = s.strip()
    m = re.fullmatch(r"delay\s+(\d+)\s*s", t, flags=re.IGNORECASE)
    if m:
        return {"type": "delay", "seconds": int(m.group(1))}

    if t.lower().startswith("notify "):
        rest = t[len("notify ") :].strip()
        lit = _parse_literal(rest)
        if isinstance(lit, dict) and "string" in lit:
            return {"type": "notify", "message": lit["string"]}
        # allow bare text notify
        return {"type": "notify", "message": rest.strip('"')}

    # command: dev.cmd(args)
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\((.*)\)", t)
    if m:
        dev = m.group(1)
        cmd = m.group(2)
        arg_s = m.group(3).strip()

        args: List[Dict[str, Any]] = []
        if arg_s:
            parts: List[str] = []
            cur = []
            in_q = False
            esc = False
            for ch in arg_s:
                if esc:
                    cur.append(ch)
                    esc = False
                    continue
                if ch == "\\":
                    cur.append(ch)
                    esc = True
                    continue
                if ch == '"':
                    cur.append(ch)
                    in_q = not in_q
                    continue
                if ch == "," and not in_q:
                    parts.append("".join(cur).strip())
                    cur = []
                    continue
                cur.append(ch)
            if cur:
                parts.append("".join(cur).strip())

            for p in parts:
                lit = _parse_literal(p)
                if lit is None:
                    return None
                args.append(lit)

        out: Dict[str, Any] = {"type": "command", "device": dev, "command": cmd}
        if args:
            out["args"] = args
        return out

    # allow dev.cmd without parentheses
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", t)
    if m:
        return {"type": "command", "device": m.group(1), "command": m.group(2)}

    return None


def parse_plantuml(text: str) -> Tuple[Dict[str, Any], List[Diagnostic]]:
    """Parse a restricted subset of PlantUML produced by `ir_to_plantuml`.

    Returns:
      (ir, diagnostics)

    Parsing is best-effort: we emit diagnostics and continue where possible.
    """

    diags: List[Diagnostic] = []
    lines = text.splitlines()

    # State alias declarations: alias -> label
    state_labels: Dict[str, str] = {}
    # label -> alias (for quoted endpoints)
    label_to_alias: Dict[str, str] = {}

    # Invariants: state_id -> expr list
    invariants: Dict[str, List[Dict[str, Any]]] = {}

    initial_state: Optional[str] = None
    states_seen: set[str] = set()
    transitions_out: List[Dict[str, Any]] = []

    # note parsing
    in_note = False
    note_state: Optional[str] = None

    def err(line_no: int, code: str, msg: str) -> None:
        diags.append(Diagnostic(severity="error", code=code, path=f"puml:L{line_no}", message=msg))

    def warn(line_no: int, code: str, msg: str) -> None:
        diags.append(Diagnostic(severity="warning", code=code, path=f"puml:L{line_no}", message=msg))

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        # comments
        if line.startswith("'"):
            continue
        if line.startswith("//"):
            continue

        if in_note:
            if line.lower() == "end note":
                in_note = False
                note_state = None
                continue
            if note_state and line.startswith("-"):
                expr_s = line.lstrip("-").strip()
                expr = _parse_expr(expr_s)
                if expr is None:
                    err(idx, "E430", f"Could not parse invariant expression: {expr_s}")
                else:
                    invariants.setdefault(note_state, []).append(expr)
            else:
                # ignore other note lines
                continue
            continue

        # state declaration: state "Label" as Alias
        m = re.fullmatch(r"state\s+\"(.+?)\"\s+as\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            label = m.group(1)
            alias = m.group(2)
            state_labels[alias] = label
            label_to_alias[label] = alias
            states_seen.add(alias)
            continue

        # invariants note
        m = re.fullmatch(r"note\s+right\s+of\s+([A-Za-z_][A-Za-z0-9_]*)", line, flags=re.IGNORECASE)
        if m:
            in_note = True
            note_state = m.group(1)
            continue

        # initial marker
        m = re.fullmatch(r"\[\*\]\s*-->\s*(.+)", line)
        if m:
            st = m.group(1).strip()
            # handle quoted state name
            if len(st) >= 2 and st[0] == '"' and st[-1] == '"':
                lbl = st[1:-1]
                st = label_to_alias.get(lbl, _sanitize_ident(lbl))
            initial_state = st
            states_seen.add(st)
            continue

        # transitions
        m = re.fullmatch(r"(.+?)\s*-->\s*(.+?)(?:\s*:\s*(.+))?", line)
        if m:
            frm_raw = m.group(1).strip()
            to_raw = m.group(2).strip()
            label_raw = m.group(3)

            def resolve_state(tok: str) -> str:
                t = tok.strip()
                # quoted label
                if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
                    lbl = t[1:-1]
                    if lbl in label_to_alias:
                        return label_to_alias[lbl]
                    warn(idx, "W401", f"Unknown quoted state label '{lbl}'. Sanitizing to identifier.")
                    return _sanitize_ident(lbl)
                # raw identifier
                if _is_ident(t):
                    return t
                # allow using a declared label without quotes (rare)
                if t in label_to_alias:
                    return label_to_alias[t]
                warn(idx, "W402", f"Non-identifier state token '{t}'. Sanitizing to identifier.")
                return _sanitize_ident(t)

            frm = resolve_state(frm_raw)
            to = resolve_state(to_raw)
            if frm == "[*]" or to == "[*]":
                # ignore finals for now
                continue

            states_seen.add(frm)
            states_seen.add(to)

            triggers: List[Dict[str, Any]] = []
            actions: List[Dict[str, Any]] = []
            guard: Optional[Dict[str, Any]] = None

            if label_raw:
                parts = _split_escaped_newlines(label_raw)
                for part in parts:
                    if part.startswith("TRIGGER:"):
                        trig_s = part[len("TRIGGER:") :].strip()
                        # triggers are joined by " AND " (uppercase) in our generator
                        for chunk in [c.strip() for c in trig_s.split(" AND ") if c.strip()]:
                            tg = _parse_trigger(chunk)
                            if tg is None:
                                err(idx, "E410", f"Could not parse trigger: {chunk}")
                            else:
                                triggers.append(tg)
                    elif part.startswith("GUARD:"):
                        expr_s = part[len("GUARD:") :].strip()
                        g = _parse_expr(expr_s)
                        if g is None:
                            err(idx, "E420", f"Could not parse guard expression: {expr_s}")
                        else:
                            guard = g
                    elif part.startswith("ACTION:"):
                        act_s = part[len("ACTION:") :].strip()
                        a = _parse_action(act_s)
                        if a is None:
                            err(idx, "E440", f"Could not parse action: {act_s}")
                        else:
                            actions.append(a)
                    else:
                        warn(idx, "W410", f"Ignoring unknown label line: {part}")
            else:
                warn(idx, "W400", f"Transition '{frm} --> {to}' has no label; triggers/actions will be empty.")

            tr_obj: Dict[str, Any] = {
                "from": frm,
                "to": to,
                "triggers": triggers,
                "actions": actions,
            }
            if guard is not None:
                tr_obj["guard"] = guard
            transitions_out.append(tr_obj)
            continue

        # ignore everything else (title, @startuml, @enduml, etc.)
        continue

    if initial_state is None:
        err(1, "E400", "Missing initial state line: [*] --> <State>")
        # best-effort
        initial_state = sorted(states_seen)[0] if states_seen else "Idle"

    # Build states list
    states_list: List[Dict[str, Any]] = []
    for sid in sorted(states_seen):
        st: Dict[str, Any] = {"id": sid}
        lbl = state_labels.get(sid)
        if isinstance(lbl, str) and lbl and lbl != sid:
            st["label"] = lbl
        inv = invariants.get(sid)
        if inv:
            st["invariants"] = inv
        states_list.append(st)

    ir: Dict[str, Any] = {
        "version": "0.1",
        "devices": [],
        "stateMachine": {
            "initial": initial_state,
            "states": states_list,
            "transitions": transitions_out,
        },
    }

    # Infer devices from triggers/actions
    devices: Dict[str, str] = {}
    for tr in transitions_out:
        for tg in tr.get("triggers", []) if isinstance(tr.get("triggers", []), list) else []:
            if not isinstance(tg, dict):
                continue
            ref = tg.get("ref")
            if isinstance(ref, dict) and isinstance(ref.get("device"), str):
                devices[ref["device"]] = "unknown"
        for act in tr.get("actions", []) if isinstance(tr.get("actions", []), list) else []:
            if isinstance(act, dict) and act.get("type") == "command" and isinstance(act.get("device"), str):
                devices[act["device"]] = "unknown"

    ir["devices"] = [{"id": did, "kind": "unknown"} for did in sorted(devices.keys())]

    return ir, diags


def _simple_ir_diff(baseline: Dict[str, Any], edited: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a small, human-friendly diff between two IRs.

    This is intentionally lightweight (no external deps) and focused on the parts
    users most commonly edit: states + transitions.
    """

    def norm_state(s: Dict[str, Any]) -> str:
        sid = s.get("id")
        lbl = s.get("label")
        return f"{sid}|{lbl}" if isinstance(lbl, str) and lbl else str(sid)

    def _strip_noise(tr: Dict[str, Any]) -> Dict[str, Any]:
        # Transition IDs are not represented in PlantUML; drop them for a more meaningful diff.
        out = dict(tr)
        out.pop("id", None)
        acts = out.get("actions")
        if isinstance(acts, list):
            new_acts = []
            for a in acts:
                if not isinstance(a, dict):
                    continue
                aa = dict(a)
                # Empty args are common and not semantically important.
                if aa.get("type") == "command" and ("args" in aa) and (not aa.get("args")):
                    aa.pop("args", None)
                new_acts.append(aa)
            out["actions"] = new_acts
        return out

    def canon(obj: Any) -> str:
        if isinstance(obj, dict):
            obj = _strip_noise(obj)
        return json.dumps(obj, sort_keys=True, ensure_ascii=False)

    b_sm = baseline.get("stateMachine", {}) if isinstance(baseline.get("stateMachine"), dict) else {}
    e_sm = edited.get("stateMachine", {}) if isinstance(edited.get("stateMachine"), dict) else {}

    b_states = {norm_state(s) for s in b_sm.get("states", []) if isinstance(s, dict)}
    e_states = {norm_state(s) for s in e_sm.get("states", []) if isinstance(s, dict)}

    b_trans = {canon(t) for t in b_sm.get("transitions", []) if isinstance(t, dict)}
    e_trans = {canon(t) for t in e_sm.get("transitions", []) if isinstance(t, dict)}

    return {
        "initial": {"baseline": b_sm.get("initial"), "edited": e_sm.get("initial")},
        "states_added": sorted(list(e_states - b_states)),
        "states_removed": sorted(list(b_states - e_states)),
        "transitions_added": [json.loads(x) for x in sorted(list(e_trans - b_trans))],
        "transitions_removed": [json.loads(x) for x in sorted(list(b_trans - e_trans))],
    }



def run_roundtrip(
    *,
    puml_path: Path,
    out_bundle_dir: Optional[Path],
    settings: Settings,
    baseline_ir_path: Optional[Path] = None,
) -> Tuple[Dict[str, Path], List[str]]:
    """Parse an edited PlantUML -> IR -> validate -> regenerate PlantUML.

    Output layout (preferred):
      outputs/<bundle>/edits/edit_###/*   - revision created from this round-trip
      outputs/<bundle>/current/*          - convenience pointer to the latest canonical artifacts

    The input .puml can live anywhere. If it lives under a recognized bundle, we will
    place outputs under that bundle. Otherwise, we treat puml_path.parent as the bundle root.

    Returns:
      (out_paths, summary_lines)
    """
    if not puml_path.exists():
        raise PipelineError(f"PlantUML file not found: {puml_path}")

    ir_schema, device_catalog, capability_catalog = load_templates(settings.templates_dir)

    # Determine bundle root + allocate new edit revision dir
    bundle_root = find_bundle_root(puml_path, out_bundle_override=out_bundle_dir)
    edit_dir = allocate_edit_dir(bundle_root)

    # Copy the user's edited source into the revision folder for provenance.
    source_puml = edit_dir / "source.puml"
    safe_copy(puml_path, source_puml)

    out_paths: Dict[str, Path] = {
        "source_puml": source_puml,
        "raw_ir": edit_dir / "raw.ir.json",
        "ir": edit_dir / "final.ir.json",
        "validation": edit_dir / "validation_report.json",
        "puml": edit_dir / "final.puml",
        "revision_dir": edit_dir,
        "bundle_root": bundle_root,
    }

    txt = source_puml.read_text(encoding="utf-8")
    ir_raw, parse_diags = parse_plantuml(txt)

    # Fill device kinds from catalog where possible.
    id_to_kind: Dict[str, str] = {}
    for d in device_catalog.get("devices", []) or []:
        if isinstance(d, dict) and isinstance(d.get("id"), str) and isinstance(d.get("kind"), str):
            id_to_kind[d["id"]] = d["kind"]
    for g in device_catalog.get("globals", []) or []:
        if isinstance(g, dict) and isinstance(g.get("id"), str) and isinstance(g.get("kind"), str):
            id_to_kind[g["id"]] = g["kind"]
    devs = ir_raw.get("devices", []) if isinstance(ir_raw.get("devices", []), list) else []
    for d in devs:
        if isinstance(d, dict) and isinstance(d.get("id"), str):
            d["kind"] = id_to_kind.get(d["id"], d.get("kind", "unknown"))

    write_json(out_paths["raw_ir"], ir_raw)

    # Normalize + desugar into canonical IR
    ir = normalize_ir(ir_raw)
    ir = desugar_delays_to_timer_states(ir)

    diags, patches = validate_all(ir, ir_schema, device_catalog, capability_catalog)
    diags_all = parse_diags + diags

    ok = not any(d.severity == "error" for d in diags_all)
    report = {
        "ok": ok,
        "diagnostics": [asdict(d) for d in diags_all],
        "patches": [asdict(p) for p in patches],
    }

    write_json(out_paths["ir"], ir)
    write_json(out_paths["validation"], report)

    # Regenerate PlantUML from canonical IR (trust anchor)
    title = bundle_root.name or "Automation"
    regenerated = ir_to_plantuml(ir, title=title)
    write_text(out_paths["puml"], regenerated)

    # Optional diff
    diff_against: Optional[Path] = None
    if baseline_ir_path and baseline_ir_path.exists():
        diff_against = baseline_ir_path
    else:
        # Default: diff against the current pointer if present, otherwise baseline.
        cand_current = bundle_root / "current" / "final.ir.json"
        cand_baseline = bundle_root / "baseline" / "final.ir.json"
        if cand_current.exists():
            diff_against = cand_current
        elif cand_baseline.exists():
            diff_against = cand_baseline

    if diff_against is not None and diff_against.exists():
        baseline = read_json(diff_against)
        diff = _simple_ir_diff(baseline, ir)
        out_paths["diff"] = edit_dir / "diff.json"
        write_json(out_paths["diff"], diff)

    # Update current pointer + manifest
    update_current(bundle_root, edit_dir)
    rel = str(edit_dir.relative_to(bundle_root).as_posix()) if edit_dir.is_relative_to(bundle_root) else str(edit_dir)
    write_manifest(
        bundle_root,
        {
            "current": {"points_to": rel},
            "append_revision": build_revision_record(
                kind="edit",
                revision_dir=edit_dir,
                source_puml=source_puml,
                diff_against=diff_against,
            ),
        },
    )

    # CLI summary (first few errors)
    summary: List[str] = []
    errors = [d for d in diags_all if d.severity == "error"]
    if errors:
        summary.append(f"Round-trip failed with {len(errors)} error(s). Fix the .puml and rerun.")
        for d in errors[:8]:
            summary.append(f"  {d.path}: {d.code} {d.message}")
        if len(errors) > 8:
            summary.append(f"  ... and {len(errors) - 8} more")
    else:
        summary.append("Round-trip OK (no errors).")

    return out_paths, summary

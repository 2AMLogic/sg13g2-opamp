#!/usr/bin/env python3
"""Per-spec-row characterization report from committed evidence (T1 item 8).

Reads the explicit record selection in `selection.json` (beside this file),
the committed `sim/*/records/*.csv` (+ `.md`) records it names, the ratified
spec text and the item 9 testbench inventory, and renders one aggregated
report: for every claimed row, its units, load and conditions, ratified bound
and decision record, measured extremum and binding point, source record and
hash, expected-versus-observed grid coverage, and verdict.

Stdlib only. Needs no ngspice, no PDK and no network: it re-reads committed
evidence, it never re-simulates. (Re-running the simulations is a different,
much more expensive operation -- each bench's README, "Cold-start
invocation", and signoff/evidence/testbenches.txt.)

  python3 signoff/characterization/generate.py            # print the report, write nothing
  python3 signoff/characterization/generate.py --format json
  python3 signoff/characterization/generate.py --mint     # append a new record under reports/
  python3 signoff/characterization/generate.py --check    # newest committed record reproduces

Exit codes: 0 report rendered, overall PASS (or --check/--mint succeeded);
3 report rendered but overall FAIL or INCOMPLETE (mirrors `klt signoff`);
1 the selected evidence is in error (or --check/--mint failed); 2 usage.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import math
import re
import subprocess
import sys
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = HERE.parent.parent
SELECTION_REL = "signoff/characterization/selection.json"
REPORTS_REL = "signoff/characterization/reports"
ENVELOPE_REL = "signoff/evidence/characterization.json"
GENERATOR_REL = "signoff/characterization/generate.py"

SELECTION_SCHEMA = "sg13g2-opamp/characterization-selection/1"
REPORT_SCHEMA = "sg13g2-opamp/characterization-report/2"
RECORD_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-z]{4,40}$")
NGSPICE_RE = re.compile(r"\bngspice-(\d+)\b")

# Matches the provenance block every existing generic envelope under
# signoff/evidence/ carries (they are hand-rolled, not produced by klt).
ENVELOPE_KLT_VERSION = "0.6.0"

ROW_CLASSES = ("ratified", "superseded", "measured", "pending")
EXTREMA = ("min", "max", "absmax")
BOUND_OPS = (">=", "<=")
VALID_OPS = ("==", ">=", "==col")

COMPARISON_RULE = (
    "Each ratified bound is compared literally: every valid grid point's raw "
    "measured value, scaled to the bound's unit, must satisfy the bound exactly "
    "as written in spec/target-spec.md (e.g. >= 37.8 means 37.7999 fails). No "
    "rounding, tolerance or precision convention is applied: no ratification "
    "record defines one, and choosing one is a spec decision, not the "
    "report's. The worst value rounded to the bound's written decimals is "
    "shown for information only and never gates a verdict. A point that fails "
    "its record's validity flags never contributes an extremum: it is counted "
    "as missing coverage, so a failed simulation point can only make a row "
    "INCOMPLETE, never PASS."
)

NOT_CLAIMED = [
    "Not item 5 or item 6 evidence: it is a generic, offline aggregation of "
    "harness-native records, not a `klt sim` or `klt yield` envelope, and the "
    "signoff manifest cites it for item 8 only.",
    "Not a re-run: regenerating this report re-reads committed records; it "
    "does not re-simulate anything. Re-running the benches is the separate "
    "cold-start procedure in each sim/ bench README.",
    "Not a claim that every T1 item is satisfied; post-layout (PEX) "
    "re-simulation does not exist yet, so every number here is pre-layout.",
]


# --------------------------------------------------------------------------
# small helpers


class SelectionError(Exception):
    """The selection file itself is malformed (not an evidence problem)."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def fmt(value: Decimal | None) -> str | None:
    """Plain (non-exponent) decimal string, trailing zeros kept as computed."""
    if value is None:
        return None
    if value != 0 and abs(value) < Decimal("1e-6"):
        return format(value.normalize(), "E")  # e.g. a negative control's ~0 sigma
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def parse_decimal(text: str | None) -> tuple[Decimal | None, str | None]:
    """(value, None) for a finite number, (None, why) otherwise."""
    if text is None:
        return None, "empty cell"
    stripped = text.strip()
    if not stripped:
        return None, "empty cell"
    try:
        value = Decimal(stripped)
    except InvalidOperation:
        return None, f"not a number ({stripped!r})"
    if not value.is_finite():
        return None, f"non-finite value ({stripped!r})"
    return value, None


def decimals_of(literal: str) -> int:
    exponent = Decimal(literal).as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def normalized_netlist_hash(path: Path) -> str:
    """Hash of a SPICE netlist with comment (`*`) and blank lines dropped.

    The netlist snapshots each bench committed differ from the current
    design netlist only in header comments/blank lines when the circuit is
    the same, so this is the identity that matters for "same design".
    """
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        lines.append(line.rstrip())
    return sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def load_selection(path: Path) -> dict:
    try:
        selection = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SelectionError(f"cannot read selection {path}: {exc}") from exc
    except ValueError as exc:
        raise SelectionError(f"selection {path} is not valid JSON: {exc}") from exc
    if not isinstance(selection, dict) or selection.get("schema") != SELECTION_SCHEMA:
        raise SelectionError(f"selection {path}: `schema` must be {SELECTION_SCHEMA!r}")
    for key in ("block", "spec", "inventory", "pdk_pin", "design_netlist"):
        if not isinstance(selection.get(key), str):
            raise SelectionError(f"selection: `{key}` must be a string")
    for key in ("grids", "records"):
        if not isinstance(selection.get(key), dict):
            raise SelectionError(f"selection: `{key}` must be an object")
    if not isinstance(selection.get("rows"), list) or not selection["rows"]:
        raise SelectionError("selection: `rows` must be a non-empty list")
    seen = set()
    for row in selection["rows"]:
        rid = row.get("id")
        if not isinstance(rid, str) or rid in seen:
            raise SelectionError(f"selection: row id {rid!r} missing or duplicated")
        seen.add(rid)
        if row.get("class") not in ROW_CLASSES:
            raise SelectionError(f"selection: row {rid}: `class` must be one of {ROW_CLASSES}")
        if row["class"] == "pending":
            continue
        if row.get("record") not in selection["records"]:
            raise SelectionError(f"selection: row {rid} names unknown record {row.get('record')!r}")
        if row.get("extremum") not in EXTREMA:
            raise SelectionError(f"selection: row {rid}: `extremum` must be one of {EXTREMA}")
        try:
            Decimal(row.get("scale", ""))
        except InvalidOperation as exc:
            raise SelectionError(f"selection: row {rid}: bad `scale`") from exc
        bound = row.get("bound")
        if row["class"] in ("ratified", "superseded"):
            if not isinstance(bound, dict) or bound.get("op") not in BOUND_OPS:
                raise SelectionError(f"selection: row {rid}: a {row['class']} row needs a bound")
            try:
                Decimal(bound.get("value", ""))
            except InvalidOperation as exc:
                raise SelectionError(f"selection: row {rid}: bound value is not a number") from exc
        elif bound is not None:
            raise SelectionError(f"selection: row {rid}: a measured (unratified) row carries no bound")
    for key, rec in selection["records"].items():
        if rec.get("grid") not in selection["grids"]:
            raise SelectionError(f"selection: record {key} names unknown grid {rec.get('grid')!r}")
        for cond in rec.get("valid_when", []):
            if not (isinstance(cond, list) and len(cond) == 3 and cond[1] in VALID_OPS):
                raise SelectionError(f"selection: record {key}: bad valid_when entry {cond!r}")
        for name in rec.get("definition_checks", []):
            if name not in DEFINITION_CHECKS:
                raise SelectionError(f"selection: record {key}: unknown definition check {name!r}")
    return selection


# --------------------------------------------------------------------------
# definition checks: per-point identities a record's derived column must obey


def _check_cmrr_linear(point: dict) -> str | None:
    """DR-0004's definition: Av0 - 20log10(mean + 3 sigma), LINEAR domain."""
    try:
        av0 = float(point["av0_db"])
        mean = float(point["acm_lin_mean"])
        sigma = float(point["acm_lin_sigma"])
        stated = float(point["cmrr_3sigma_db"])
    except (KeyError, ValueError) as exc:
        return f"cannot evaluate ({exc})"
    plus3 = mean + 3.0 * sigma
    if not plus3 > 0:
        return "mean + 3 sigma of Acm is not positive"
    derived = av0 - 20.0 * math.log10(plus3)
    if not math.isfinite(derived) or abs(derived - stated) > 1e-3:
        return (
            f"cmrr_3sigma_db {stated} != Av0 - 20log10(mean + 3 sigma) = {derived:.6f} "
            "(the linear-domain definition DR-0004 ratifies)"
        )
    return None


def _check_slew_worse_edge(point: dict) -> str | None:
    rise, _ = parse_decimal(point.get("sr_rise_v_per_us"))
    fall, _ = parse_decimal(point.get("sr_fall_v_per_us"))
    worst, _ = parse_decimal(point.get("sr_worst_v_per_us"))
    if None in (rise, fall, worst):
        return "cannot evaluate (missing edge column)"
    if worst != min(rise, fall):
        return f"sr_worst_v_per_us {worst} is not the worse of rise {rise} / fall {fall}"
    return None


def _check_offset_magnitude(point: dict) -> str | None:
    signed, _ = parse_decimal(point.get("vos_null_v"))
    magnitude, _ = parse_decimal(point.get("vos_abs_v"))
    if None in (signed, magnitude):
        return "cannot evaluate (missing vos_null_v / vos_abs_v)"
    if magnitude != abs(signed):
        return f"vos_abs_v {magnitude} != |vos_null_v| {abs(signed)}"
    return None


DEFINITION_CHECKS = {
    "cmrr_linear_3sigma": _check_cmrr_linear,
    "slew_worse_edge": _check_slew_worse_edge,
    "offset_magnitude": _check_offset_magnitude,
}


# --------------------------------------------------------------------------
# records


def expected_points(grid: dict) -> list[tuple[str, dict]]:
    axes = grid["axes"]
    points = []
    for corner in axes["corner"]:
        for temp in axes["temp"]:
            for vdd in axes["vdd"]:
                values = {"corner": corner, "temp": temp, "vdd": vdd}
                points.append((grid["point_id"].format(**values), values))
    return points


def read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines) + "\n"))
    header = list(reader.fieldnames or [])
    return header, list(reader)


def point_is_valid(point: dict, conditions: list) -> str | None:
    """None when every validity flag holds, else why the point failed."""
    for column, op, operand in conditions:
        cell = (point.get(column) or "").strip()
        if op == "==":
            if cell != operand:
                return f"{column}={cell!r} (needs {operand!r})"
        elif op == "==col":
            if cell != (point.get(operand) or "").strip():
                return f"{column}={cell!r} != {operand}={point.get(operand)!r}"
        elif op == ">=":
            value, why = parse_decimal(cell)
            if value is None or value < Decimal(operand):
                return f"{column}={cell!r} (needs >= {operand})" + (f", {why}" if why else "")
    return None


def load_record(repo: Path, key: str, spec: dict, grid: dict, env: dict) -> dict:
    """Read and audit one selected record. Never raises on bad evidence."""
    state = {
        "key": key,
        "errors": [],
        "points": {},
        "valid_ids": [],
        "invalid": {},
        "missing": [],
        "unexpected": [],
        "controls": {},
        "source": {
            "csv": spec.get("csv"),
            "csv_sha256": None,
            "md": spec.get("md"),
            "md_sha256": None,
            "netlist_snapshot": spec.get("netlist_snapshot"),
            "netlist_snapshot_sha256": None,
            "ngspice": None,
            "grid": spec.get("grid"),
            "filter": spec.get("filter"),
            "valid_when": spec.get("valid_when", []),
            "definition_checks": spec.get("definition_checks", []),
        },
    }
    errors = state["errors"]
    src = state["source"]

    # 1. presence and pins
    for field in ("csv", "md", "netlist_snapshot"):
        rel = spec.get(field)
        if not isinstance(rel, str):
            errors.append(f"record {key}: selection names no `{field}`")
            continue
        path = repo / rel
        if not path.is_file():
            errors.append(f"record {key}: missing record file {rel}")
            continue
        actual = sha256_file(path)
        src[f"{field}_sha256"] = actual
        pinned = spec.get(f"{field}_sha256")
        if field != "netlist_snapshot" and actual != pinned:
            errors.append(
                f"record {key}: {rel} does not match its selection pin "
                f"(pinned {pinned}, actual {actual}) -- re-select deliberately, "
                "never re-read silently"
            )
    if errors:
        return state

    # 2. environment: same ngspice as the pin, same circuit as design/
    md_text = (repo / spec["md"]).read_text(encoding="utf-8")
    versions = sorted(set(NGSPICE_RE.findall(md_text)))
    if len(versions) != 1:
        errors.append(
            f"record {key}: {spec['md']} names {len(versions)} ngspice versions "
            f"({', '.join('ngspice-' + v for v in versions) or 'none'}) -- the "
            "simulation environment is not identifiable"
        )
    else:
        src["ngspice"] = f"ngspice-{versions[0]}"
        if env.get("ngspice") and src["ngspice"] != env["ngspice"]:
            errors.append(
                f"record {key}: ran on {src['ngspice']}, but sim/pdk.json pins "
                f"{env['ngspice']} -- mixed simulation environments are not "
                "combined silently"
            )
    snapshot_norm = normalized_netlist_hash(repo / spec["netlist_snapshot"])
    if env.get("netlist_normalized_sha256") and snapshot_norm != env["netlist_normalized_sha256"]:
        errors.append(
            f"record {key}: simulated netlist {spec['netlist_snapshot']} is not "
            f"the committed design netlist (ignoring comments/blank lines) -- "
            "this record characterizes a different circuit"
        )

    # 3. rows: parse, de-duplicate, check identity against the grid
    try:
        header, rows = read_csv_rows(repo / spec["csv"])
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        errors.append(f"record {key}: cannot parse {spec['csv']} ({exc})")
        return state
    if "point_id" not in header:
        errors.append(f"record {key}: {spec['csv']} has no point_id column")
        return state
    state["header"] = header

    all_ids: dict[str, int] = {}
    for row in rows:
        pid = (row.get("point_id") or "").strip()
        all_ids[pid] = all_ids.get(pid, 0) + 1
    for pid, count in sorted(all_ids.items()):
        if count > 1:
            errors.append(f"record {key}: duplicate point_id {pid!r} ({count} rows)")

    flt = spec.get("filter")
    controls = set(spec.get("controls", []))
    selected = []
    for row in rows:
        pid = (row.get("point_id") or "").strip()
        if pid in controls:
            state["controls"][pid] = row
            continue
        if flt and (row.get(flt["column"]) or "").strip() != flt["equals"]:
            continue
        selected.append(row)

    expected = expected_points(grid)
    expected_ids = {pid for pid, _ in expected}
    columns = grid["columns"]
    for row in selected:
        pid = row["point_id"].strip()
        if pid not in expected_ids:
            state["unexpected"].append(pid)
            continue
        state["points"][pid] = row
    for pid, values in expected:
        row = state["points"].get(pid)
        if row is None:
            state["missing"].append(pid)
            continue
        for axis, column in columns.items():
            cell = (row.get(column) or "").strip()
            if cell != values[axis]:
                errors.append(
                    f"record {key}: point {pid} says {column}={cell!r}, but its "
                    f"point_id means {axis}={values[axis]!r}"
                )
    for pid in sorted(state["unexpected"]):
        errors.append(f"record {key}: point {pid!r} is outside the expected {spec['grid']} grid")
    for pid in sorted(controls - set(state["controls"])):
        state["missing"].append(pid)

    # 4. validity flags and definitions, per point
    conditions = spec.get("valid_when", [])
    for pid, _ in expected:
        row = state["points"].get(pid)
        if row is None:
            continue
        why = point_is_valid(row, conditions)
        if why:
            state["invalid"][pid] = why
            continue
        for name in spec.get("definition_checks", []):
            problem = DEFINITION_CHECKS[name](row)
            if problem:
                errors.append(f"record {key}: point {pid} fails definition check {name}: {problem}")
        state["valid_ids"].append(pid)
    for pid, row in sorted(state["controls"].items()):
        why = point_is_valid(row, conditions)
        if why:
            state["invalid"][pid] = why

    src["expected_points"] = len(expected) + len(controls)
    src["observed_points"] = len(state["points"]) + len(state["controls"])
    src["valid_points"] = len(state["valid_ids"]) + sum(
        1 for pid in state["controls"] if pid not in state["invalid"]
    )
    src["missing_points"] = sorted(state["missing"])
    src["invalid_points"] = {pid: state["invalid"][pid] for pid in sorted(state["invalid"])}
    return state


# --------------------------------------------------------------------------
# rows


def spec_line(spec_lines: list[str], prefix: str) -> tuple[str | None, str | None]:
    hits = [line for line in spec_lines if line.startswith(prefix)]
    if len(hits) != 1:
        return None, f"{len(hits)} spec/target-spec.md lines start with {prefix!r} (need exactly 1)"
    return hits[0], None


def parse_inventory(path: Path) -> dict[str, str]:
    """`label -> committed record` from signoff/evidence/testbenches.txt."""
    mapping = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) == 4:
            mapping[fields[0]] = fields[3]
    return mapping


def column_values(state: dict, column: str, scale: Decimal, ids: list[str], errors: list):
    values = []
    for pid in ids:
        row = state["points"].get(pid) or state["controls"].get(pid)
        if column not in row:
            errors.append(f"record {state['key']}: no column {column!r}")
            return []
        value, why = parse_decimal(row.get(column))
        if value is None:
            errors.append(f"record {state['key']}: point {pid} column {column}: {why}")
            continue
        values.append((pid, value * scale))
    return values


def pick(values, extremum: str, worst: bool = True):
    """(point_id, value) at the worst (or best) end; ties -> smallest point_id."""
    if not values:
        return None
    if extremum == "absmax":
        keyed = [(abs(v), pid, v) for pid, v in values]
        target = max(k for k, _, _ in keyed) if worst else min(k for k, _, _ in keyed)
    else:
        want_max = (extremum == "max") == worst
        keyed = [(v, pid, v) for pid, v in values]
        target = max(k for k, _, _ in keyed) if want_max else min(k for k, _, _ in keyed)
    pid, value = sorted((pid, v) for k, pid, v in keyed if k == target)[0]
    return pid, value


def meets(value: Decimal, op: str, bound: Decimal) -> bool:
    return value >= bound if op == ">=" else value <= bound


def evaluate_row(row: dict, records: dict, spec_lines: list[str], inventory: dict, selection: dict) -> dict:
    out = {
        "id": row["id"],
        "spec_row": row.get("spec_row"),
        "class": row["class"],
        "decision_record": row.get("decision_record"),
        "tag": row.get("tag"),
        "load": row.get("load"),
        "conditions": row.get("conditions"),
        "errors": [],
    }
    errors = out["errors"]

    check = row.get("spec_check") or {}
    line, problem = spec_line(spec_lines, check.get("row_prefix", "\0"))
    if problem:
        errors.append(problem)
    elif check.get("text") not in line:
        errors.append(
            f"spec/target-spec.md row {check.get('row_prefix')!r} no longer contains "
            f"{check.get('text')!r} -- the selection disagrees with the ratified spec"
        )
    bound = row.get("bound")
    if bound and bound["value"] not in (check.get("text") or ""):
        errors.append(
            f"bound {bound['value']} does not appear in the spec text this row checks "
            f"({check.get('text')!r}) -- bounds are copied from the spec, never typed in"
        )

    if row["class"] == "pending":
        out["pending_reason"] = row.get("pending_reason")
        out["verdict"] = "ERROR" if errors else "PENDING"
        return out

    label = row.get("inventory_label")
    rec_spec = selection["records"][row["record"]]
    if label not in inventory:
        errors.append(f"signoff/evidence/testbenches.txt has no row {label!r}")
    elif inventory[label] != rec_spec.get("csv"):
        errors.append(
            f"testbenches.txt cites {inventory[label]} for {label!r}, but this row "
            f"selects {rec_spec.get('csv')} -- the item 8 report and the item 9 "
            "inventory must name the same record"
        )

    state = records[row["record"]]
    errors.extend(state["errors"])
    scale = Decimal(row["scale"])
    out["unit"] = row.get("unit")
    out["source"] = {
        "record": row["record"],
        "csv": rec_spec.get("csv"),
        "csv_sha256": state["source"]["csv_sha256"],
        "column": row["column"],
        "scale_to_unit": row["scale"],
    }
    out["coverage"] = {
        "grid": rec_spec.get("grid"),
        "expected": state["source"].get("expected_points"),
        "observed": state["source"].get("observed_points"),
        "valid": state["source"].get("valid_points"),
        "missing": state["source"].get("missing_points", []),
        "invalid": state["source"].get("invalid_points", {}),
    }
    complete = not out["coverage"]["missing"] and not out["coverage"]["invalid"]
    out["coverage"]["complete"] = complete

    values = column_values(state, row["column"], scale, state["valid_ids"], errors) if not state["errors"] else []
    worst = pick(values, row["extremum"], worst=True)
    best = pick(values, row["extremum"], worst=False)
    out["extremum"] = row["extremum"]
    out["measured_worst"] = {"value": fmt(worst[1]), "point": worst[0]} if worst else None
    out["measured_best"] = {"value": fmt(best[1]), "point": best[0]} if best else None

    context = []
    for item in row.get("context", []):
        entry = {"label": item["label"]}
        if "count_equal" in item:
            ids = state["valid_ids"]
            entry["count"] = sum(
                1 for pid in ids if (state["points"][pid].get(item["column"]) or "").strip() == item["count_equal"]
            ) if ids and item["column"] in state["points"][ids[0]] else None
            entry["of"] = len(ids)
            if entry["count"] is None and not state["errors"]:
                errors.append(f"record {row['record']}: no column {item['column']!r}")
        elif "point" in item:
            pid = item["point"]
            if pid in state["invalid"] or (pid not in state["controls"] and pid not in state["points"]):
                entry["value"], entry["point"] = None, pid
            else:
                got = column_values(state, item["column"], Decimal(item["scale"]), [pid], errors)
                entry["value"], entry["point"] = (fmt(got[0][1]) if got else None), pid
            entry["unit"] = item.get("unit")
        else:
            got = column_values(state, item["column"], Decimal(item["scale"]), state["valid_ids"], errors) if not state["errors"] else []
            hit = pick(got, item["extremum"], worst=True)
            entry["value"], entry["point"] = (fmt(hit[1]), hit[0]) if hit else (None, None)
            entry["unit"] = item.get("unit")
        context.append(entry)
    if context:
        out["context"] = context

    if row["class"] in ("ratified", "superseded"):
        bound_value = Decimal(bound["value"])
        decimals = decimals_of(bound["value"])
        quantum = Decimal(1).scaleb(-decimals)
        violators = []
        for pid, value in values:
            magnitude = abs(value) if row["extremum"] == "absmax" else value
            # The gate: the RAW value against the literal ratified bound.
            if not meets(magnitude, bound["op"], bound_value):
                violators.append(pid)
        out["bound"] = {"op": bound["op"], "value": bound["value"], "unit": row.get("unit"), "written_decimals": decimals}
        out["violating_points"] = sorted(violators)
        if worst:
            magnitude = abs(worst[1]) if row["extremum"] == "absmax" else worst[1]
            margin = magnitude - bound_value if bound["op"] == ">=" else bound_value - magnitude
            out["measured_worst"]["raw_margin"] = fmt(margin)
            # Informational only -- never consulted by the verdict above.
            rounded = magnitude.quantize(quantum, rounding=ROUND_HALF_EVEN)
            out["measured_worst"]["rounded_to_bound_decimals"] = fmt(rounded)
            out["fails_only_beyond_written_decimals"] = bool(violators) and meets(rounded, bound["op"], bound_value)
        else:
            out["fails_only_beyond_written_decimals"] = None
        out["meets_bound"] = (not violators) if values else None
        if errors:
            out["verdict"] = "ERROR"
        elif violators:
            out["verdict"] = "FAIL"
        elif not complete or not values:
            out["verdict"] = "INCOMPLETE"
        else:
            out["verdict"] = "PASS"
        out["binding"] = row["class"] == "ratified"
    else:
        if errors:
            out["verdict"] = "ERROR"
        elif not complete or not values:
            out["verdict"] = "INCOMPLETE"
        else:
            out["verdict"] = "MEASURED"
        out["binding"] = False
    if not complete and out["verdict"] in ("FAIL",):
        out["incomplete_too"] = True
    return out


# --------------------------------------------------------------------------
# report


def build_content(repo: Path, selection_path: Path) -> dict:
    repo = repo.resolve()
    selection = load_selection(selection_path)
    global_errors: list[str] = []

    def need(rel: str) -> Path | None:
        path = repo / rel
        if not path.is_file():
            global_errors.append(f"missing input {rel}")
            return None
        return path

    env: dict = {}
    pdk_path = need(selection["pdk_pin"])
    if pdk_path:
        try:
            pdk = json.loads(pdk_path.read_text(encoding="utf-8"))
            env["ngspice"] = pdk["osdi_toolchain"]["ngspice_actually_used"]
            env["pdk"] = f"{pdk['source']} {pdk['release_tag']}"
        except (ValueError, KeyError, TypeError) as exc:
            global_errors.append(f"{selection['pdk_pin']}: cannot read the ngspice/PDK pin ({exc})")
    netlist = need(selection["design_netlist"])
    if netlist:
        env["netlist_normalized_sha256"] = normalized_netlist_hash(netlist)
    spec_path = need(selection["spec"])
    spec_lines = spec_path.read_text(encoding="utf-8").splitlines() if spec_path else []
    inventory_path = need(selection["inventory"])
    inventory = parse_inventory(inventory_path) if inventory_path else {}

    records = {
        key: load_record(repo, key, spec, selection["grids"][spec["grid"]], env)
        for key, spec in sorted(selection["records"].items())
    }
    rows = [evaluate_row(row, records, spec_lines, inventory, selection) for row in selection["rows"]]

    # Coverage of the spec and of the item 9 inventory: no ratified row may be
    # silently absent from the selection.
    prefixes = [row["spec_check"]["row_prefix"] for row in selection["rows"]]
    spec_rows = []
    in_section = False
    for line in spec_lines:
        if line.startswith("## "):
            in_section = line.startswith("## 2.")
            continue
        if in_section and line.startswith("| ") and not line.startswith("| Parameter") and not line.startswith("|---"):
            name = line[2:].split(" | ", 1)[0].strip()
            covered = any(line.startswith(prefix) for prefix in prefixes)
            spec_rows.append({"row": name, "covered": covered})
            if not covered:
                global_errors.append(f"spec/target-spec.md section 2 row {name!r} has no row in the selection")
    if spec_path and not spec_rows:
        global_errors.append("spec/target-spec.md: found no section 2 table rows")
    labels = {row.get("inventory_label") for row in selection["rows"]}
    inventory_rows = []
    for label in sorted(inventory):
        if label in selection.get("inventory_ignore", []):
            continue
        inventory_rows.append({"row": label, "covered": label in labels})
        if label not in labels:
            global_errors.append(f"testbenches.txt row {label!r} has no row in the selection")

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    considered = [row for row in rows if row["class"] != "pending"]
    if global_errors or any(row["verdict"] == "ERROR" for row in rows):
        overall = "ERROR"
    elif any(row["verdict"] == "FAIL" and row["binding"] for row in considered):
        overall = "FAIL"
    elif any(row["verdict"] == "INCOMPLETE" for row in considered):
        overall = "INCOMPLETE"
    else:
        overall = "PASS"
    ratified = [row for row in rows if row["class"] == "ratified"]
    # Disclosure, not a gate: binding rows that FAIL literally although their
    # worst value rounds onto the bound at the decimals the bound is written
    # to. Whether such a row should pass is a spec decision for the keys.
    beyond_decimals = sorted(
        row["id"] for row in ratified if row["verdict"] == "FAIL" and row.get("fails_only_beyond_written_decimals")
    )

    return {
        "schema": REPORT_SCHEMA,
        "block": selection["block"],
        "selection": {
            "path": str(selection_path.resolve().relative_to(repo)) if selection_path.resolve().is_relative_to(repo) else selection_path.name,
            "sha256": sha256_file(selection_path),
        },
        "comparison_rule": COMPARISON_RULE,
        "environment": {
            "ngspice_pin": env.get("ngspice"),
            "pdk_pin": env.get("pdk"),
            "pdk_pin_file": selection["pdk_pin"],
            "design_netlist": selection["design_netlist"],
            "design_netlist_normalized_sha256": env.get("netlist_normalized_sha256"),
            "note": "every selected record must name this ngspice and must have simulated this netlist (comment/blank lines ignored); a mismatch is an error, never a silent mix",
        },
        "sources": {key: state["source"] for key, state in records.items()},
        "rows": rows,
        "spec_coverage": spec_rows,
        "inventory_coverage": inventory_rows,
        "caveats": selection.get("caveats", []),
        "not_claimed": NOT_CLAIMED,
        "errors": sorted(global_errors),
        "overall": {
            "verdict": overall,
            "ratified_rows": len(ratified),
            "ratified_pass": sum(1 for row in ratified if row["verdict"] == "PASS"),
            "fail_only_beyond_written_decimals": beyond_decimals,
            "verdict_counts": dict(sorted(counts.items())),
            "rule": "ERROR if any input is in error; else FAIL if any ratified (binding) row fails its bound; else INCOMPLETE if any non-pending row lacks full valid grid coverage; else PASS. Superseded rows are context and never FAIL the report; measured rows carry no bound; Area is PENDING.",
        },
    }


def content_hash(content: dict) -> str:
    return sha256_bytes(canonical_json(content).encode("utf-8"))


def git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"], cwd=str(repo), capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def make_report(content: dict, record_id: str | None, repo: Path) -> dict:
    head = git_head(repo)
    generator = repo / GENERATOR_REL
    return {
        "record_metadata": {
            "_note": "The ONLY fields excluded from reproduction: --check compares `content` (and content_sha256) and nothing here.",
            "record_id": record_id,
            "generated_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_head": head,
            "generator": GENERATOR_REL,
            "generator_sha256": sha256_file(generator) if generator.is_file() else None,
        },
        "content_sha256": content_hash(content),
        "content": content,
    }


# --------------------------------------------------------------------------
# markdown


def _v(value, unit=None) -> str:
    if value is None:
        return "—"
    return f"{value} {unit}" if unit else str(value)


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _short(hash_text: str | None) -> str:
    return hash_text.split(":", 1)[-1][:12] if hash_text else "—"


def _coverage(cov: dict) -> str:
    text = f"{cov['valid']}/{cov['expected']} valid"
    if cov["missing"]:
        text += f"; missing {len(cov['missing'])}"
    if cov["invalid"]:
        text += f"; failed {len(cov['invalid'])}"
    return text


def render_markdown(report: dict) -> str:
    meta = report["record_metadata"]
    content = report["content"]
    overall = content["overall"]
    out = io.StringIO()
    w = out.write

    w(f"# Characterization report — {content['block']}\n\n")
    w("T1 item 8 (\"Characterization report\"): every claimed spec row, its\n")
    w("evidence record and its verdict, aggregated from committed `sim/`\n")
    w("records. Generated by `signoff/characterization/generate.py` from the\n")
    w("explicit record selection `" + content["selection"]["path"] + "`; nothing\n")
    w("here was re-simulated.\n\n")

    w("## Record metadata (excluded from reproduction)\n\n")
    w("| Field | Value |\n|---|---|\n")
    for key in ("record_id", "generated_utc", "git_head", "generator_sha256"):
        value = meta.get(key)
        w(f"| `{key}` | {'`' + str(value) + '`' if value is not None else '— (not minted)'} |\n")
    w("\nEverything below this section is a pure function of the selected\n")
    w("records, the selection file, the spec text and the inventory:\n")
    w(f"`content_sha256` = `{report['content_sha256']}`.\n\n")

    w("## Reproduce (no ngspice, no PDK)\n\n")
    w("```bash\n")
    w("python3 signoff/characterization/generate.py           # re-render, write nothing\n")
    w("python3 signoff/characterization/generate.py --check   # newest record reproduces\n")
    w("```\n\n")
    w("That re-reads committed evidence only. Re-running the *simulations*\n")
    w("behind it is a different operation (PDK + ngspice, hours of grids):\n")
    w("see `signoff/evidence/testbenches.txt` and each bench's README.\n\n")

    w(f"## Overall: **{overall['verdict']}**\n\n")
    w(f"{overall['ratified_pass']} of {overall['ratified_rows']} ratified (binding) bounds PASS. ")
    w("Verdict counts: " + ", ".join(f"{k} {v}" for k, v in overall["verdict_counts"].items()) + ".\n\n")
    if overall.get("fail_only_beyond_written_decimals"):
        w(
            "**Bound precision:** "
            + ", ".join(f"`{rid}`" for rid in overall["fail_only_beyond_written_decimals"])
            + " FAIL their ratified bound as written, although the raw worst case rounds onto the "
            "bound at the decimals the bound is written to (see each row's raw margin). No "
            "ratification record defines a rounding convention, so this report compares literally "
            "and does not pass them; whether those bounds or the comparison convention should be "
            "restated is a spec decision for the keys (see the caveats below).\n\n"
        )
    w(f"Rule: {overall['rule']}\n\n")
    w(f"Comparison rule: {content['comparison_rule']}\n\n")
    if content["errors"]:
        w("### Errors\n\n")
        for err in content["errors"]:
            w(f"- {err}\n")
        w("\n")

    def table(rows, with_bound: bool):
        if with_bound:
            w("| Row | Bound | Decision record | Load / conditions | Worst measured (binding point) | Raw margin to bound (worst rounded to bound decimals, informational) | Best measured | Grid coverage | Source record (sha256) | Verdict |\n")
            w("|---|---|---|---|---|---|---|---|---|---|\n")
        else:
            w("| Row | Status / tag | Load / conditions | Worst measured (point) | Best measured | Grid coverage | Source record (sha256) | Verdict |\n")
            w("|---|---|---|---|---|---|---|---|\n")
        for row in rows:
            worst = row.get("measured_worst") or {}
            best = row.get("measured_best") or {}
            unit = row.get("unit")
            src = row["source"]
            worst_txt = f"{_v(worst.get('value'), unit)} at `{worst.get('point')}`" if worst else "—"
            best_txt = f"{_v(best.get('value'), unit)} at `{best.get('point')}`" if best else "—"
            source_txt = f"`{src['csv']}` col `{src['column']}` (`{_short(src['csv_sha256'])}`)"
            cond = f"{row['load']}; {row['conditions']}"
            if with_bound:
                bound = row["bound"]
                bound_txt = f"{'≥' if bound['op'] == '>=' else '≤'} {bound['value']} {unit}"
                margin = worst.get("raw_margin")
                comp_txt = "—" if margin is None else (
                    f"{margin} {unit} (rounded: {worst.get('rounded_to_bound_decimals')} {unit})"
                )
                w(
                    f"| {_cell(row['spec_row'])} | {_cell(bound_txt)} | `{row['decision_record']}` [{row['tag']}] "
                    f"| {_cell(cond)} | {_cell(worst_txt)} | {_cell(comp_txt)} | {_cell(best_txt)} "
                    f"| {_coverage(row['coverage'])} | {_cell(source_txt)} | **{row['verdict']}** |\n"
                )
            else:
                w(
                    f"| {_cell(row['spec_row'])} | [{_cell(row['tag'])}] | {_cell(cond)} | {_cell(worst_txt)} "
                    f"| {_cell(best_txt)} | {_coverage(row['coverage'])} | {_cell(source_txt)} | **{row['verdict']}** |\n"
                )
        w("\n")

    def details(rows):
        for row in rows:
            lines = []
            for item in row.get("context", []):
                if "count" in item:
                    lines.append(f"{item['label']}: {item['count']} of {item['of']}")
                else:
                    lines.append(f"{item['label']}: {_v(item['value'], item.get('unit'))} at `{item['point']}`")
            cov = row["coverage"]
            if cov["missing"]:
                lines.append("missing points: " + ", ".join(f"`{p}`" for p in cov["missing"]))
            if cov["invalid"]:
                lines.append("failed points (excluded from the extremum): " + "; ".join(f"`{p}` ({why})" for p, why in cov["invalid"].items()))
            if row.get("violating_points"):
                lines.append("points violating the bound: " + ", ".join(f"`{p}`" for p in row["violating_points"]))
            for err in row["errors"]:
                lines.append(f"ERROR: {err}")
            if lines:
                w(f"- **{row['spec_row']}**\n")
                for line in lines:
                    w(f"  - {line}\n")
        w("\n")

    groups = [
        ("Ratified rows (binding)", "ratified", True),
        ("Superseded ratified bound (context, not binding)", "superseded", True),
        ("Measured, NOT ratified (no pass/fail verdict)", "measured", False),
    ]
    for title, cls, with_bound in groups:
        rows = [row for row in content["rows"] if row["class"] == cls]
        if not rows:
            continue
        w(f"## {title}\n\n")
        table(rows, with_bound)
        details(rows)

    pending = [row for row in content["rows"] if row["class"] == "pending"]
    if pending:
        w("## Pending (no evidence by construction)\n\n")
        for row in pending:
            w(f"- **{row['spec_row']}** [{row['tag']}] — {row['verdict']}: {row.get('pending_reason')}\n")
            for err in row["errors"]:
                w(f"  - ERROR: {err}\n")
        w("\n")

    w("## Caveats that travel with these numbers\n\n")
    for caveat in content["caveats"]:
        w(f"- {caveat}\n")
    w("\n## What this report is not\n\n")
    for item in content["not_claimed"]:
        w(f"- {item}\n")

    env = content["environment"]
    w("\n## Sources and environment\n\n")
    w(f"Simulator pin: `{env['ngspice_pin']}`; PDK pin: {env['pdk_pin']} (`{env['pdk_pin_file']}`); ")
    w(f"design netlist `{env['design_netlist']}` (normalized `{_short(env['design_netlist_normalized_sha256'])}`). {env['note']}.\n\n")
    w("| Record | CSV (sha256) | MD (sha256) | ngspice | Grid | Expected | Observed | Valid |\n")
    w("|---|---|---|---|---|---|---|---|\n")
    for key, src in content["sources"].items():
        w(
            f"| {key} | `{src['csv']}` (`{_short(src['csv_sha256'])}`) | `{src['md']}` (`{_short(src['md_sha256'])}`) "
            f"| {src.get('ngspice') or '—'} | {src['grid']} | {src.get('expected_points', '—')} "
            f"| {src.get('observed_points', '—')} | {src.get('valid_points', '—')} |\n"
        )
    w("\nSpec section 2 rows covered: ")
    w(", ".join(f"{r['row']}{'' if r['covered'] else ' (NOT COVERED)'}" for r in content["spec_coverage"]) + ".\n")
    w("Item 9 inventory rows covered: ")
    w(", ".join(f"{r['row']}{'' if r['covered'] else ' (NOT COVERED)'}" for r in content["inventory_coverage"]) + ".\n")
    return out.getvalue()


# --------------------------------------------------------------------------
# minting, envelope, check


def latest_report(reports_dir: Path) -> Path | None:
    """Newest record BY NAME (the record id sorts by UTC time), never by mtime."""
    candidates = sorted(p for p in reports_dir.glob("*.json") if RECORD_ID_RE.match(p.stem))
    return candidates[-1] if candidates else None


def envelope_for(report_rel: str, report_hash: str, content: dict) -> dict:
    overall = content["overall"]
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass" if overall["verdict"] == "PASS" else "fail",
        "t1_item": 8,
        "summary": (
            f"characterization report: overall {overall['verdict']}, "
            f"{overall['ratified_pass']}/{overall['ratified_rows']} ratified spec-row bounds PASS (raw values "
            "compared against the literal ratified bound) with full "
            "expected-grid coverage; per-row units, load, bound, decision record, binding point and "
            "source-record hash; aggregated offline from committed sim/ records (no re-simulation); "
            "not item 5/6 evidence"
        ),
        "source": report_rel[: -len(".json")] + ".md",
        "provenance": {
            "klt_version": ENVELOPE_KLT_VERSION,
            "klayout_version": None,
            "pdk": None,
            "deck": None,
            "input": {
                "path": {"path": report_rel, "scope": "repo"},
                "content_hash": report_hash,
            },
        },
    }


def mint(repo: Path, selection_path: Path) -> int:
    content = build_content(repo, selection_path)
    if content["overall"]["verdict"] == "ERROR":
        print(render_markdown(make_report(content, None, repo)))
        print("refusing to mint a report whose inputs are in error", file=sys.stderr)
        return 1
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    record_id = f"{stamp}-{git_head(repo) or 'nogit'}"
    reports = repo / REPORTS_REL
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / f"{record_id}.json"
    md_path = reports / f"{record_id}.md"
    if json_path.exists() or md_path.exists():
        print(f"refusing to overwrite existing record {record_id}", file=sys.stderr)
        return 1
    report = make_report(content, record_id, repo)
    json_path.write_text(canonical_json(report), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    report_rel = f"{REPORTS_REL}/{record_id}.json"
    report_hash = sha256_file(json_path)
    envelope = repo / ENVELOPE_REL
    envelope.write_text(canonical_json(envelope_for(report_rel, report_hash, content)), encoding="utf-8")
    print(f"wrote {REPORTS_REL}/{record_id}.json and .md (overall {content['overall']['verdict']})")
    print(f"wrote {ENVELOPE_REL} (status {'pass' if content['overall']['verdict'] == 'PASS' else 'fail'})")
    print("next: pin it -- signoff/block-manifest.json evidence[\"8\"].content_hash and")
    print(f"      signoff/pinned-inputs.json inputs[\"8\"] = {report_rel!r}, both at")
    print(f"      {report_hash}; then bash signoff/regenerate.sh and")
    print("      python3 signoff/check_signoff.py --run-klt")
    return 0


def check(repo: Path, selection_path: Path, report_path: Path | None) -> int:
    problems: list[str] = []
    reports = repo / REPORTS_REL
    if report_path is None:
        report_path = latest_report(reports)
        if report_path is None:
            print(f"FAIL: no minted report under {REPORTS_REL}")
            return 1
    print(f"  record: {report_path.relative_to(repo) if report_path.is_relative_to(repo) else report_path}")
    try:
        committed = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FAIL: cannot read {report_path} ({exc})")
        return 1
    if not RECORD_ID_RE.match(report_path.stem) or committed.get("record_metadata", {}).get("record_id") != report_path.stem:
        problems.append("record id in the file name and in record_metadata disagree (or is malformed)")
    fresh = build_content(repo, selection_path)
    if committed.get("content") != fresh:
        old, new = committed.get("content") or {}, fresh
        for key in sorted(set(old) | set(new)):
            if old.get(key) != new.get(key):
                problems.append(f"content.{key} no longer reproduces from the selected evidence")
    if committed.get("content_sha256") != content_hash(committed.get("content") or {}):
        problems.append("content_sha256 does not match the committed content")
    md_path = report_path.with_suffix(".md")
    if not md_path.is_file():
        problems.append(f"no Markdown twin {md_path.name}")
    elif md_path.read_text(encoding="utf-8") != render_markdown(committed):
        problems.append(f"{md_path.name} is not the rendering of its JSON twin")

    envelope_path = repo / ENVELOPE_REL
    if envelope_path.is_file():
        latest = latest_report(reports)
        try:
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{ENVELOPE_REL} is not valid JSON ({exc})")
            envelope = None
        if envelope is not None and latest is not None:
            latest_rel = str(latest.relative_to(repo))
            expected = envelope_for(latest_rel, sha256_file(latest), json.loads(latest.read_text(encoding="utf-8"))["content"])
            if envelope != expected:
                problems.append(
                    f"{ENVELOPE_REL} does not wrap the newest report {latest_rel} at its current hash "
                    "with a status matching its overall verdict -- re-mint or re-wrap"
                )
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        return 1
    print(f"  ok  report reproduces (content_sha256 {committed['content_sha256']}), overall {fresh['overall']['verdict']}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--selection", type=Path, default=None, help=f"default: <repo>/{SELECTION_REL}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mint", action="store_true", help="append a new report record and re-wrap the item 8 envelope")
    mode.add_argument("--check", nargs="?", const="", default=None, metavar="REPORT", help="verify a minted record (default: newest by record id) reproduces")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    selection = (args.selection or repo / SELECTION_REL).resolve()
    try:
        if args.mint:
            return mint(repo, selection)
        if args.check is not None:
            return check(repo, selection, Path(args.check).resolve() if args.check else None)
        content = build_content(repo, selection)
    except SelectionError as exc:
        print(f"selection error: {exc}", file=sys.stderr)
        return 2
    report = make_report(content, None, repo)
    sys.stdout.write(canonical_json(report) if args.format == "json" else render_markdown(report))
    verdict = content["overall"]["verdict"]
    return 0 if verdict == "PASS" else (1 if verdict == "ERROR" else 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Spec rows: bound/clause parsing, load conditions and row grading.

Split out of generate.py (issue #355). Turns a ratified spec clause plus a
record's measured population into one graded report row.

Depends on `common` only.

Stdlib only; pure functions.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from common import decimals_of, fmt, parse_decimal

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


# The spec states each ratified bound as `<op> <number> <unit>` inside a cited
# clause. Only this narrow grammar is understood; anything else is an ERROR
# rather than a guess. A leading `+` (the offset row's "+21.9 mV") is a
# magnitude cap, graded as `<=` against the absolute value.
_CLAUSE_OPS = {"\u2265": ">=", "\u2264": "<=", "+": "<="}
_CLAUSE_UNITS = r"(?:V/\u00b5s|\u00b5Vrms|MHz|dB|mV|uA|\u00b5A|\u00b0|V)"
_CLAUSE_RE = re.compile(
    r"(?P<op>[\u2265\u2264+])\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>" + _CLAUSE_UNITS + r")(?![\w/\u00b5])"
)
_UNIT_CANON = {"uA": "\u00b5A", "\u00b0": "deg"}


def parse_bound_clause(text: str) -> tuple[tuple[str, str, str] | None, str | None]:
    """(op, numeric token as written, unit) from a cited clause, or an error."""
    hits = list(_CLAUSE_RE.finditer(text))
    if len(hits) != 1:
        return None, (
            f"cited spec clause {text!r} holds {len(hits)} `<op> <number> <unit>` bounds "
            "(need exactly 1; narrow the cited text to the clause being graded)"
        )
    hit = hits[0]
    return (_CLAUSE_OPS[hit["op"]], hit["num"], _UNIT_CANON.get(hit["unit"], hit["unit"])), None


def check_bound_against_clause(bound: dict, unit: str | None, text: str) -> list[str]:
    """Validate the whole selected comparison (op, number, unit) against the clause."""
    parsed, problem = parse_bound_clause(text)
    if problem:
        return [problem]
    op, num, clause_unit = parsed
    errs = []
    if bound.get("op") != op:
        errs.append(f"bound operator {bound.get('op')!r} disagrees with the spec clause {text!r} (reads {op!r})")
    if bound.get("value") != num:
        errs.append(
            f"bound value {bound.get('value')!r} is not the whole numeric token {num!r} of the spec "
            f"clause {text!r} -- bounds are copied from the spec, never typed in"
        )
    if _UNIT_CANON.get(unit or "", unit) != clause_unit:
        errs.append(f"selected unit {unit!r} disagrees with the spec clause unit {clause_unit!r} in {text!r}")
    return errs


CAP_UNITS = {"F": Decimal(1), "mF": Decimal("1e-3"), "uF": Decimal("1e-6"), "µF": Decimal("1e-6"),
             "nF": Decimal("1e-9"), "pF": Decimal("1e-12"), "fF": Decimal("1e-15")}
CAP_RE = r"([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*(F|mF|uF|µF|nF|pF|fF)\b"
LOAD_APPLICABILITY = ("applies", "dc_ignored")
SPEC_CL_RE = re.compile(r"^\|\s*Load capacitance, CL\s*\|\s*\*\*\s*" + CAP_RE)
SOURCE_CL_RE = re.compile(r"\bCL\s*=\s*`?\s*" + CAP_RE)


def parse_capacitance(text: str | None) -> tuple[Decimal | None, str | None]:
    """'2 pF' / '2e-12 F' -> farads (Decimal), so equal loads compare equal."""
    match = re.fullmatch(CAP_RE, (text or "").strip())
    if not match:
        return None, f"{text!r} is not a capacitance (expected e.g. '2 pF' or '2e-12 F')"
    return Decimal(match.group(1)) * CAP_UNITS[match.group(2)], None


def source_cl_statements(md_text: str) -> list[str]:
    """Every explicit `CL = <value> <unit>` the record's own prose states."""
    return sorted({f"{m.group(1)} {m.group(2)}" for m in SOURCE_CL_RE.finditer(md_text)})


def check_load_condition(row: dict, state: dict, spec_lines: list[str]) -> tuple[str, list[str], dict]:
    """Validate the row's structured load against the ratified spec and the
    selected record's own stated CL. Returns (displayed load, errors, detail).

    The displayed load is DERIVED from the validated numbers, never copied from
    a free-text label. Only the capacitive load is validated; every other
    condition string stays explicitly descriptive."""
    errors: list[str] = []
    cond = row.get("load_condition")
    detail: dict = {"status": "unverified"}
    if not isinstance(cond, dict):
        return "load not stated", [f"row {row['id']}: no structured `load_condition`"], detail
    note = cond.get("note") or ""
    applicability = cond.get("applicability")
    if applicability not in LOAD_APPLICABILITY:
        errors.append(f"row {row['id']}: load_condition.applicability must be one of {LOAD_APPLICABILITY}")
    selected, problem = parse_capacitance(cond.get("cl"))
    if problem:
        errors.append(f"row {row['id']}: load_condition.cl {problem}")
    ratified = None
    for line in spec_lines:
        match = SPEC_CL_RE.match(line)
        if match:
            ratified = Decimal(match.group(1)) * CAP_UNITS[match.group(2)]
            detail["ratified_cl"] = f"{match.group(1)} {match.group(2)}"
            break
    if ratified is None:
        errors.append("spec/target-spec.md section 1 has no parseable 'Load capacitance, CL' row")
    stated = [parse_capacitance(s)[0] for s in state.get("stated_cl", [])]
    detail["selected_cl"] = cond.get("cl")
    detail["source_states"] = list(state.get("stated_cl", []))
    detail["applicability"] = applicability
    if selected is not None and ratified is not None and selected != ratified:
        errors.append(
            f"row {row['id']}: reported load {cond.get('cl')} contradicts the ratified "
            f"CL of {detail['ratified_cl']} (spec/target-spec.md section 1) -- a load "
            "label is not evidence"
        )
    contradicting = sorted(s for s, v in zip(state.get("stated_cl", []), stated) if selected is not None and v != selected)
    if contradicting:
        errors.append(
            f"row {row['id']}: reported load {cond.get('cl')} contradicts the selected "
            f"record {row['record']}, which states CL = {', '.join(contradicting)}"
        )
    if errors:
        detail["status"] = "contradicted"
        return f"CL = {cond.get('cl')} (CONTRADICTED, see errors)", errors, detail
    if applicability == "dc_ignored":
        detail["status"] = "not_applicable"
        text = (f"CL = {cond['cl']} [DR-1] attached; a DC analysis is independent of it "
                "(applicability: DC, not a load claim)")
    elif state.get("stated_cl"):
        detail["status"] = "verified"
        text = (f"CL = {cond['cl']} [DR-1] (verified: ratified spec section 1 and the selected "
                f"record both state it; record says {', '.join(state['stated_cl'])})")
    else:
        detail["status"] = "unverified"
        text = (f"CL = {cond['cl']} [DR-1] (UNVERIFIED against the source: the selected "
                "record states no CL; matches the ratified spec only)")
    if note:
        text += f"; {note}"
    return text, errors, detail



def evaluate_row(row: dict, records: dict, spec_lines: list[str], inventory: dict, selection: dict) -> dict:
    out = {
        "id": row["id"],
        "spec_row": row.get("spec_row"),
        "class": row["class"],
        "decision_record": row.get("decision_record"),
        "tag": row.get("tag"),
        "load": None,
        "load_check": None,
        "conditions": row.get("conditions"),
        "conditions_provenance": "descriptive: selection text, not validated against the source record",
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
    if bound:
        errors.extend(check_bound_against_clause(bound, row.get("unit"), check.get("text") or ""))

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
    out["load"], load_errors, out["load_check"] = check_load_condition(row, state, spec_lines)
    errors.extend(load_errors)
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

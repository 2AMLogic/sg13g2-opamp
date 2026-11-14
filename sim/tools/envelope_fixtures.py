#!/usr/bin/env python3
"""Shared synthetic-envelope fixture kit for the sim/*/klt/test_compare.py suites.

Stdlib only, offline: reads committed files and runs no simulator. This is the
*test-side* counterpart of klt_envelope.py, which issue #142 extracted from the
per-bench compare.py files. The fixture plumbing beside those comparators was
left behind and had drifted into three byte-identical copies (issue #358):
`_harness_rows`, `_status`, `_request_limits`, the `schema_version: 3` envelope
skeleton, `_regrade` and `Base.find`. Those live here now.

What lives here:

* harness_rows  -- the csv.DictReader read of a committed harness record;
* grade         -- the min/max limits grader the fixtures use to stamp status;
* request_limits-- {measurement name: limits} lifted off a klt request;
* build_envelope-- the per-corner dict and the schema_version 3 wrapper;
* regrade       -- restamp one corner (and the envelope rollup) after a test
                   perturbs a value;
* find          -- the (corner, measurement) lookup by grid point and name.

What stays per bench: the `vals` dict naming that bench's measurements (passed
in as `vals_fn`), its WORST/MID corners, and every negative-control test body.

**No production grading logic is imported here, on purpose.** These suites are
negative-control suites whose envelopes are built FROM the committed harness
record; if the fixture builder graded via the code under test, the controls
would go circular and could no longer fail. So `grade` is a local
reimplementation of klt sim's limits semantics rather than a re-export, and
`make_key` is a *parameter* of build_envelope/find -- each bench passes its own
`C.make_key` exactly as the per-bench copies did, so this module keeps no
dependency on the comparators it builds fixtures for. (sim/output-swing's
test_compare.py delegates its `_status` to the comparator under test; that
direction is deliberately not spread here.)

test_envelope_fixtures.py, beside this file, pins the output shape.
"""

from __future__ import annotations

import csv
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


def harness_rows(csv_path: str) -> List[Dict[str, str]]:
    """The committed harness record, as raw string rows in file order."""
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def grade(value: float, limits: Optional[Mapping[str, float]]) -> str:
    """klt sim's limits semantics: inclusive min/max, no limits means pass.

    A local reimplementation, NOT a re-export of any comparator's grader -- see
    the module docstring on why the fixtures must not grade via the code under
    test.
    """
    if not limits:
        return "pass"
    lo, hi = limits.get("min"), limits.get("max")
    return "pass" if (lo is None or value >= lo) and (hi is None or value <= hi) else "fail"


def request_limits(request_path: str) -> Dict[str, Any]:
    """{measurement name: its `limits` dict (or None)} from a klt request file."""
    with open(request_path) as f:
        request = json.load(f)
    return {m["name"]: m.get("limits") for m in request["measurements"]}


def build_envelope(
    rows: Sequence[Mapping[str, str]],
    vals_fn: Callable[[Mapping[str, str]], Dict[str, float]],
    make_key: Callable[[Any, Any, Any], Tuple[str, int, float]],
    limits: Mapping[str, Any],
    status_fn: Callable[[float, Optional[Mapping[str, float]]], str] = grade,
    supply_key: str = "vinp",
) -> Dict[str, Any]:
    """A synthetic klt-sim-shaped envelope carrying the harness's own numbers.

    One corner per harness row, in row order; `vals_fn(row)` supplies that
    bench's {measurement name: value} dict. The mid-supply bias rail is named
    `supply_key` and sits at vdd/2, as every bench here biases it.
    """
    corners = []
    for r in rows:
        k = make_key(r["corner"], r["temp_c"], r["vdd_v"])
        vdd = float(r["vdd_v"])
        vals = vals_fn(r)
        ms = [{"name": n, "value": v, "status": status_fn(v, limits[n])} for n, v in vals.items()]
        corners.append({
            "corner_id": f"{k[0]}/vdd={vdd:.3f}_{supply_key}={vdd / 2:.3f}V/{k[1]}C",
            "process": k[0], "temperature_c": k[1],
            "supply_v": {"vdd": vdd, supply_key: vdd / 2},
            "status": "fail" if any(m["status"] == "fail" for m in ms) else "pass",
            "measurements": ms,
        })
    return {
        "schema_version": 3,
        "status": "fail" if any(c["status"] == "fail" for c in corners) else "pass",
        "corner_count": len(corners),
        "coverage": {"nothing_checked": False, "skipped": []},
        "corners": corners,
    }


def regrade(
    env: Mapping[str, Any],
    corner: Mapping[str, Any],
    limits: Mapping[str, Any],
    status_fn: Callable[[float, Optional[Mapping[str, float]]], str] = grade,
) -> None:
    """Restamp `corner`'s measurement statuses, then its status and the rollup.

    A measurement whose value a test set to None keeps the status it had: a
    null value is an input error for the comparator to name, not something the
    fixture silently re-grades.
    """
    for m in corner["measurements"]:
        if m["value"] is not None:
            m["status"] = status_fn(m["value"], limits[m["name"]])
    corner["status"] = "fail" if any(m["status"] == "fail" for m in corner["measurements"]) else "pass"
    env["status"] = "fail" if any(c["status"] == "fail" for c in env["corners"]) else "pass"


def find(
    env: Mapping[str, Any],
    point: Tuple[Any, Any, Any],
    name: str,
    make_key: Callable[[Any, Any, Any], Tuple[str, int, float]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The (corner, measurement) pair at grid `point` named `name`.

    Raises KeyError((point, name)) when the envelope has no such measurement --
    a test asking for a point it just deleted is a broken test, not a finding.
    """
    k = make_key(*point)
    for c in env["corners"]:
        if make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == k:
            for m in c["measurements"]:
                if m["name"] == name:
                    return c, m
    raise KeyError((point, name))

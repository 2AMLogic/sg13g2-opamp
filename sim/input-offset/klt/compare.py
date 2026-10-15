#!/usr/bin/env python3
"""Compare the input-offset bench's `klt sim` envelope against the harness record.

Usage:

    compare.py validate <envelope.json>
    compare.py compare --envelope <offset.sim.json> --harness-csv <records/<id>.csv> \
        [--json-out <report.json>] [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator.

`validate` is the gate sim/input-offset/klt/run.sh applies to the envelope
before it is allowed into records/: exactly the 45-point ratified grid, one
corner per (process, temperature, VDD) point, Vcm = VDD/2 at every corner,
every declared measurement present and finite at every corner, no corner
`error` / `inconclusive`, and `coverage.nothing_checked` false with nothing
skipped. An envelope that fails any of these is an incomplete run, not
evidence. A ratified-bound MISS is not a gate failure: it is a result.

`compare` joins the envelope and the harness record
(sim/input-offset/records/20260918-203858-90844d2.csv) on the full
(process, temperature, VDD) key, refuses anything but the same 45 unique
points on both sides, and reports per corner and per metric the difference
against a stated tolerance (TOLERANCES below). Exit status:

    0  every comparison within tolerance and every verdict agrees
    1  at least one comparison outside tolerance, or a bound verdict that
       disagrees without being explained by the tolerance (report still
       written -- an out-of-tolerance point is reported, never hidden)
    2  inputs unusable: missing/duplicate/extra points, missing or
       non-finite measurements, malformed envelope

Comparison tolerances never touch a pass/fail limit. The ratified bound
(OFFSET_BOUND_V) is graded by `klt sim` itself; this script only reports
whether the two measurement paths agree, and whether they agree about the
bound.

Which harness number is compared: the record's `vos_null_v` column, the
PRIMARY (open-loop null sweep) method of sim/input-offset/. The request is
that same method; the harness's closed-loop cross-check (`vos_closed_loop_v`)
is a second method that needs a separately measured AC gain and is not part
of this request.
"""

from __future__ import annotations

import functools
import math
import os
import sys
from typing import Dict, List, Optional

# The grid, the key helpers, InputError and the envelope gate are shared by
# every sim/*/klt/compare.py: sim/tools/klt_envelope.py (issue #142).
_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import klt_envelope as E  # noqa: E402
from klt_envelope import (  # noqa: E402,F401  (re-exported: tests and callers use C.<name>)
    PROCESSES, TEMPERATURES, SUPPLIES, Key, InputError, expected_keys, make_key, key_str,
)

# ----------------------------------------------------------- measurements
# Everything offset.request.json reports.
MEASUREMENTS = (
    "vos_null_v", "vos_crossings_n", "gain_local_vv",
    "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v",
    "op_vd1_rail_frac", "op_vd2_rail_frac", "op_vtail_rail_frac",
)
# The harness's per-point op_pass sanity rule: every node inside the rails,
# local gain >= 10 V/V, exactly one crossing (the harness aborts a point with
# any other crossing count), null inside the window.
OP_SANITY = ("vos_crossings_n", "gain_local_vv",
             "op_vd1_rail_frac", "op_vd2_rail_frac", "op_vtail_rail_frac")

# The ratified row (spec/target-spec.md section 2, [DR-2]): systematic
# (deterministic, corner-only) input-referred offset, |Vos| <= 21.9 mV
# worst-case. Copied here only to check that the two paths AGREE about the
# bound; the verdict of record is the envelope's. No rounding or slack.
OFFSET_BOUND_V = 0.0219

# ------------------------------------------------------------- tolerances
# Per-metric comparison tolerance: |tool - harness| <= abs + rel * |harness|.
#
# Basis (README.md "Comparison tolerance" carries the full argument):
#
# * Same circuit, same drive (Vcm exactly, Vid split symmetrically about it),
#   same ngspice default solver tolerance (DR-0005: no reltol/abstol/vntol
#   override anywhere in sim/). The harness record was produced on
#   macOS/aarch64 ngspice-46; the envelope is produced wherever `klt sim`
#   runs it. DR-0005 measured a 9.9e-4 relative drain-current difference
#   between that host and Linux/x86_64 default-tolerance records of this
#   PDK: that is the ceiling the allowance may not exceed, and an offset (a
#   small difference of large quantities) is the metric most exposed to it.
#   The first committed envelope (README.md "Comparison tolerance") moved by
#   at most 5.1e-8 relative (0.58 nV), four orders under that ceiling, so
#   the allowance below is set at 1e-4 relative: still 10x above the
#   largest cross-host movement actually seen, and 10x under DR-0005's
#   figure, so a real regression (a changed bias, a changed model card)
#   cannot hide inside it.
# * Measurement method: both paths linearly interpolate the Vout = Vcm
#   crossing between adjacent samples of a 4 uV Vid grid (the harness's fine
#   pass; the request's whole sweep). The two grids are not aligned, so the
#   interpolation residue of the S-curve is far below 1 uV; the absolute
#   allowance is 1 uV, a quarter of a grid step. The harness's own
#   coarse-vs-fine delta (<= 2.4 uV, column vos_coarse_fine_delta_v) is
#   reported per point as context.
# * Local gain: harness = least-squares slope over +-0.2 mV of Vid around the
#   null; request = two-point slope across the sweep interval bracketing the
#   null. Different estimators of the same slope: 0.02 dB (observed max
#   0.004 dB).
# * DC node voltages: harness = ngspice's own solution at the swept sample
#   nearest the null (<= 2 uV of Vid away); request = interpolated at the
#   null. 1e-4 relative + 50 uV (the sample offset times the first-stage
#   gain, observed max 23 uV on Vd2).
TOLERANCES = {
    "vos_null_v": {"abs": 1e-6, "rel": 1e-4, "unit": "V"},
    "gain_local_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "vd1_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vd2_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vtail_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vibias_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
}


# --------------------------------------------------------------- envelopes
def index_envelope(env: dict, label: str = "envelope") -> Dict[Key, Dict[str, object]]:
    """The shared envelope gate (klt_envelope.index_envelope); no bench-specific
    per-corner checks beyond every MEASUREMENTS entry present and finite."""
    return E.index_envelope(env, label, MEASUREMENTS)


# ----------------------------------------------------------------- harness
HARNESS_COLUMNS = ("vcm_v", "vos_null_v", "vos_abs_v", "vos_coarse_fine_delta_v", "av_local_db",
                   "vd1_sample_v", "vd2_sample_v", "vtail_sample_v", "vibias_sample_v")
HARNESS_FLAGS = ("op_pass",)


def load_harness_csv(path: str) -> Dict[Key, Dict[str, object]]:
    return E.load_harness_csv_rows(path, HARNESS_COLUMNS, "harness CSV", flag_columns=HARNESS_FLAGS)


# ----------------------------------------------------------------- compare
_tol = functools.partial(E.tol, TOLERANCES)

# tool metric -> harness column
JOIN = {
    "vos_null_v": "vos_null_v",
    "gain_local_db": "av_local_db",
    "vd1_dc_v": "vd1_sample_v",
    "vd2_dc_v": "vd2_sample_v",
    "vtail_dc_v": "vtail_sample_v",
    "vibias_dc_v": "vibias_sample_v",
}


def compare(tool: Dict[Key, Dict[str, object]], harness: Dict[Key, Dict[str, object]],
            env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for label, d in (("envelope", tool), ("harness CSV", harness)):
        E.check_grid(d.keys(), label, problems)
    if problems:
        raise InputError("; ".join(problems))

    points = []
    out_of_tol: List[str] = []
    verdict_disagreements: List[dict] = []
    for k in expected_keys():
        h = harness[k]
        t = tool[k]
        if t["gain_local_vv"] <= 0:
            raise InputError(f"{key_str(k)}: gain_local_vv {t['gain_local_vv']} is not positive")
        tv_all = {
            "vos_null_v": t["vos_null_v"],
            "gain_local_db": 20 * math.log10(t["gain_local_vv"]),
            "vd1_dc_v": t["vd1_dc_v"], "vd2_dc_v": t["vd2_dc_v"], "vtail_dc_v": t["vtail_dc_v"],
            "vibias_dc_v": t["vibias_dc_v"],
        }
        metrics = {}
        for m, tv in tv_all.items():
            hv = float(h[JOIN[m]])
            tol = _tol(m, hv)
            delta = tv - hv
            entry = {"harness": hv, "tool": tv, "delta": delta,
                     "rel_delta": delta / hv if hv else None, "tolerance": tol,
                     "unit": TOLERANCES[m]["unit"], "within": abs(delta) <= tol}
            if not entry["within"]:
                out_of_tol.append(f"{key_str(k)} {m}: tool {tv:.9g} vs harness {hv:.9g} "
                                  f"(delta {delta:.3g} {TOLERANCES[m]['unit']}, tolerance {tol:.3g})")
            metrics[m] = entry

        tool_op = all(t.get(n + "__status") == "pass" for n in OP_SANITY)
        flag = {"harness_pass": h["op_pass"], "tool_pass": tool_op, "agree": h["op_pass"] == tool_op}
        if not flag["agree"]:
            out_of_tol.append(f"{key_str(k)} op_sanity: harness pass={h['op_pass']} vs tool pass={tool_op}")

        # Ratified row: tool verdict = the envelope's own status on vos_null_v.
        tool_pass = t.get("vos_null_v__status") == "pass"
        hv_vos = float(h["vos_null_v"])
        harness_pass = abs(hv_vos) <= OFFSET_BOUND_V
        near = abs(abs(hv_vos) - OFFSET_BOUND_V) <= _tol("vos_null_v", hv_vos)
        row = {"tool_status": t.get("vos_null_v__status"), "tool_pass": tool_pass, "harness_pass": harness_pass,
               "agree": tool_pass == harness_pass, "harness_within_tolerance_of_bound": near,
               "harness_margin_v": OFFSET_BOUND_V - abs(hv_vos),
               "tool_margin_v": OFFSET_BOUND_V - abs(t["vos_null_v"])}
        if tool_pass != harness_pass:
            verdict_disagreements.append({"point": key_str(k), "row": "input_offset_systematic", "harness": hv_vos,
                                          "tool": t["vos_null_v"], "bound": OFFSET_BOUND_V,
                                          "explained_by_tolerance": near})
        points.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                       "metrics": metrics, "harness_coarse_fine_delta_v": float(h["vos_coarse_fine_delta_v"]),
                       "integrity_checks": {"op_sanity": flag}, "row": row})

    unexplained = [d for d in verdict_disagreements if not d["explained_by_tolerance"]]
    hw = max((abs(float(harness[k]["vos_null_v"])), k) for k in expected_keys())
    summary = {"bound": {"max_abs_v": OFFSET_BOUND_V},
               "harness_worst": {"point": key_str(hw[1]), "value": hw[0],
                                 "verdict": "pass" if hw[0] <= OFFSET_BOUND_V else "fail"},
               "harness_points_over_bound": [key_str(k) for k in expected_keys()
                                             if abs(float(harness[k]["vos_null_v"])) > OFFSET_BOUND_V]}
    if env is not None:
        summary["tool"] = {}
        for m in env.get("measurements") or []:
            if m.get("name") == "vos_null_v":
                summary["tool"][m["name"]] = {"status": m.get("status"), "limits": m.get("limits"),
                                              "worst_case": m.get("worst_case")}
    return {
        "schema": "sg13g2-opamp/input-offset/klt-compare/1",
        "points_compared": len(points),
        "tolerances": TOLERANCES,
        "out_of_tolerance": out_of_tol,
        "bound_verdict_disagreements": verdict_disagreements,
        "unexplained_bound_verdict_disagreements": len(unexplained),
        "row": summary,
        "points": points,
        "status": "agree" if not out_of_tol and not unexplained else "disagree",
    }


def _text_summary(rep: dict) -> str:
    r = rep["row"]
    hw = r["harness_worst"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}",
             f"  offset bound |Vos| <= {r['bound']['max_abs_v']}: harness worst {hw['point']} = {hw['value']:.6g} ({hw['verdict']})"]
    for n, e in (r.get("tool") or {}).items():
        wc = e.get("worst_case") or {}
        lines.append(f"    tool {n}: {e.get('status')} (worst {wc.get('corner_id')} = {wc.get('value')}, margin {wc.get('margin')})")
    return "\n".join(E.summary_tail(lines, rep))


def _run(a, tool: Dict[Key, Dict[str, object]], env: dict) -> dict:
    return compare(tool, load_harness_csv(a.harness_csv), env)


def main(argv: Optional[List[str]] = None) -> int:
    return E.run_cli(
        argv, description=__doc__.split("\n\n")[0], compare_help="join the envelope with the harness record",
        harness_args=(("--harness-csv", {"required": True}),),
        index_fn=index_envelope,
        run=_run,
        inputs=(("harness_csv", "harness_csv", True),),
        summary=_text_summary)


if __name__ == "__main__":
    sys.exit(main())

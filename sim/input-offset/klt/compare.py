#!/usr/bin/env python3
"""Compare the input-offset bench's `klt sim` envelopes against the harness record.

Usage:

    compare.py validate --kind {null,cl} <envelope.json>
    compare.py compare --envelope <offset.sim.json> --cl <offset.cl.sim.json> \
        --harness-csv <records/<id>.csv> --av0-csv <open-loop-ac records/<id>.csv> \
        [--json-out <report.json>] [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator.

`validate` is the gate sim/input-offset/klt/run.sh applies to each envelope
before it is allowed into records/: exactly the 45-point ratified grid, one
corner per (process, temperature, VDD) point, Vcm = VDD/2 at every corner,
every declared measurement present and finite at every corner, no corner
`error` / `inconclusive`, and `coverage.nothing_checked` false with nothing
skipped. An envelope that fails any of these is an incomplete run, not
evidence. A ratified-bound MISS is not a gate failure: it is a result.

`compare` joins the null envelope, the closed-loop envelope and the harness
record (sim/input-offset/records/20260918-203858-90844d2.csv) on the full
(process, temperature, VDD) key -- with each corner's Av0 joined from the
named sim/open-loop-ac record CSV (`--av0-csv`, read by offset_post.read_av0_csv,
which binds every Av0 row to its own corner through the record's own
corner/temp_c/vdd_v columns) -- refuses anything but the same 45 unique
points on all sides, and reports per corner and per metric the difference
against a stated tolerance (TOLERANCES below). The tool side of the
validity/agreement cells is DERIVED from the envelopes by offset_post.derive
(the harness's own op_pass / xcheck_pass rules), never read off the envelope's
grading alone. Exit status:

    0  every comparison within tolerance and every verdict agrees
    1  at least one comparison outside tolerance, or a bound verdict that
       disagrees without being explained by the tolerance (report still
       written -- an out-of-tolerance point is reported, never hidden)
    2  inputs unusable: missing/duplicate/extra points, missing or
       non-finite measurements, malformed envelope, Av0 bound to a foreign
       corner

Comparison tolerances never touch a pass/fail limit. The ratified bound
(OFFSET_BOUND_V) is graded by `klt sim` itself; this script only reports
whether the two measurement paths agree, and whether they agree about the
bound.

Which harness number is compared: the record's `vos_null_v` column, the
PRIMARY (open-loop null sweep) method of sim/input-offset/, and the
closed-loop cross-check columns (`vout_cl_v`, `vos_closed_loop_v`,
`vos_method_delta_v`, `xcheck_pass`) of its SECOND method. The requests are
those same two methods; the harness computed vos_cl with the then-latest
open-loop record's Av0, while the tool joins the currently selected record
-- the grounded-inn correction shifts vos_cl by at most ~3e-3 relative
(TOLERANCES carries the derivation), never a method change.
"""

from __future__ import annotations

import functools
import math
import os
import sys
from typing import Dict, List, Optional

# The grid, the key helpers, InputError and the envelope gate are shared by
# every sim/*/klt/compare.py: sim/tools/klt_envelope.py (issue #142). The
# per-point derivation (op_pass / xcheck_pass, the closed-loop referral) is
# shared by this bench's writer, this comparator and the signoff audit:
# offset_post.py beside this file (issue #504).
_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import klt_envelope as E  # noqa: E402
import offset_post as P  # noqa: E402
from klt_envelope import (  # noqa: E402,F401  (re-exported: tests and callers use C.<name>)
    PROCESSES, TEMPERATURES, SUPPLIES, Key, InputError, expected_keys, make_key, key_str,
)

# ----------------------------------------------------------- measurements
# Everything offset.request.json reports (the null sweep)...
MEASUREMENTS = (
    "vos_null_v", "vos_crossings_n", "gain_local_vv",
    "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vout_null_dc_v", "vibias_dc_v",
    "op_vd1_rail_frac", "op_vd2_rail_frac", "op_vtail_rail_frac",
)
# ...and everything offset_cl.request.json reports (the closed-loop method).
CL_MEASUREMENTS = tuple(P.CL_MEASUREMENTS)
KIND_MEASUREMENTS = {"null": MEASUREMENTS, "cl": CL_MEASUREMENTS}
# The harness's per-point op_pass sanity rule, re-derived from raw values by
# offset_post.derive: every rail-window node inside [0.02, 0.98]*VDD at the
# null, local gain >= 10 V/V, exactly one crossing (a null that left the
# sweep window shows 0). The envelope's own grading of the same rules is
# checked against the derivation per corner below.
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
# * Closed-loop output vout_cl_v: a plain DC node of an `op` solve of the
#   same circuit class, so the DC-node basis applies directly (1e-4 relative
#   + 50 uV; both paths solve the same closed-loop topology at ngspice's
#   default tolerance, and the first committed envelope pair moved by under
#   1e-7 relative -- README.md "Comparison tolerance").
# * vos_closed_loop_v and vos_method_delta_v additionally carry the Av0 JOIN
#   SOURCE swap, which is a documented difference, not an error: the harness
#   record (20260918) referred its output error back through the
#   then-latest open-loop record (20260910-221601, inn AC-floating), while
#   the tool joins the selected corrected record (inn AC-grounded). The
#   referral factor (1 + Av)/Av moves by d ln((1+Av)/Av) = -dAv/(Av(1+Av));
#   the two records' av0_db columns differ by at most 1.785 dB
#   (= 22.6% relative Av, measured across all 45 points), and Av >= 37.8 dB
#   [DR-2] (>= 77.6 V/V), so the swap moves vos_cl by at most
#   0.226/(1 + 77.6) = 2.9e-3 relative -- 5e-3 relative is allowed on
#   vos_closed_loop_v (1.7x that bound), and vos_method_delta_v (a small
#   difference of two ~|Vos| quantities, so a relative allowance is
#   meaningless) gets 1e-4 absolute = 2.4x the swap's worst 42 uV shift.
TOLERANCES = {
    "vos_null_v": {"abs": 1e-6, "rel": 1e-4, "unit": "V"},
    "gain_local_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "vd1_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vd2_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vtail_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vibias_dc_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vout_cl_v": {"abs": 5e-5, "rel": 1e-4, "unit": "V"},
    "vos_closed_loop_v": {"abs": 5e-6, "rel": 5e-3, "unit": "V"},
    "vos_method_delta_v": {"abs": 1e-4, "rel": 0.0, "unit": "V"},
}


# --------------------------------------------------------------- envelopes
def index_envelope(env: dict, label: str = "envelope", *,
                   kind: str) -> Dict[Key, Dict[str, object]]:
    """Gate one `klt sim` envelope and index its corners by grid key.

    `kind` is keyword-only so the signature matches E.load_envelope's
    `index_fn(env, path, **kw)` call, which is how run_cli forwards --kind.
    """
    return E.index_envelope(env, label, KIND_MEASUREMENTS[kind])


# ----------------------------------------------------------------- harness
HARNESS_COLUMNS = ("vcm_v", "vos_null_v", "vos_abs_v", "vos_coarse_fine_delta_v", "av_local_db",
                   "vd1_sample_v", "vd2_sample_v", "vtail_sample_v", "vibias_sample_v",
                   "vout_cl_v", "vos_closed_loop_v", "vos_method_delta_v")
HARNESS_FLAGS = ("op_pass", "xcheck_pass")


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
    "vout_cl_v": "vout_cl_v",
    "vos_closed_loop_v": "vos_closed_loop_v",
    "vos_method_delta_v": "vos_method_delta_v",
}


def compare(tool: Dict[Key, Dict[str, object]], cl: Dict[Key, Dict[str, object]],
            harness: Dict[Key, Dict[str, object]], av0: Dict[Key, float],
            env: Optional[dict] = None, cl_env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for label, d in (("envelope", tool), ("cl envelope", cl), ("harness CSV", harness)):
        E.check_grid(d.keys(), label, problems)
    if problems:
        raise InputError("; ".join(problems))

    points = []
    out_of_tol: List[str] = []
    verdict_disagreements: List[dict] = []
    for k in expected_keys():
        h = harness[k]
        t = tool[k]
        c = cl[k]
        if t["gain_local_vv"] <= 0:
            raise InputError(f"{key_str(k)}: gain_local_vv {t['gain_local_vv']} is not positive")
        d = P.derive_point(t, c["vout_cl_v"], k[2], av0[k])
        tv_all = {
            "vos_null_v": t["vos_null_v"],
            "gain_local_db": 20 * math.log10(t["gain_local_vv"]),
            "vd1_dc_v": t["vd1_dc_v"], "vd2_dc_v": t["vd2_dc_v"], "vtail_dc_v": t["vtail_dc_v"],
            "vibias_dc_v": t["vibias_dc_v"],
            "vout_cl_v": c["vout_cl_v"],
            "vos_closed_loop_v": d["vos_closed_loop_v"],
            "vos_method_delta_v": d["vos_method_delta_v"],
        }
        metrics = {}
        for m, tv in tv_all.items():
            metrics[m] = E.metric_entry(TOLERANCES, m, tv, float(h[JOIN[m]]), out_of_tol, key_str(k))

        # The harness's op_pass rule, re-derived from the raw envelope values
        # (offset_post.derive), against the harness's own flag -- and against
        # the envelope's own grading of the same rules.
        tool_op = d["op_pass"]
        graded_op = all(t.get(n + "__status") == "pass" for n in OP_SANITY)
        flags = {
            "op_sanity": {"harness_pass": h["op_pass"], "tool_pass": tool_op, "agree": h["op_pass"] == tool_op,
                          "tool_reasons": d["op_reasons"], "envelope_grading_agrees": graded_op == tool_op},
            "xcheck": {"harness_pass": h["xcheck_pass"], "tool_pass": d["xcheck_pass"],
                       "agree": h["xcheck_pass"] == d["xcheck_pass"],
                       "tool_why": d["xcheck_why"], "tolerance_v": P.xcheck_tolerance(t["vos_null_v"])},
        }
        if not flags["op_sanity"]["agree"]:
            out_of_tol.append(f"{key_str(k)} op_sanity: harness pass={h['op_pass']} vs tool pass={tool_op}"
                              + (f" ({'; '.join(d['op_reasons'])})" if d["op_reasons"] else ""))
        if not flags["xcheck"]["agree"]:
            out_of_tol.append(f"{key_str(k)} xcheck: harness pass={h['xcheck_pass']} vs tool pass={d['xcheck_pass']}"
                              + (f" ({d['xcheck_why']})" if d["xcheck_why"] else ""))
        if not flags["op_sanity"]["envelope_grading_agrees"]:
            out_of_tol.append(f"{key_str(k)} op_sanity: the derived rule (pass={tool_op}) disagrees with the "
                              "envelope's own grading of the same limits "
                              f"(pass={graded_op}) -- the request's limits and offset_post's rule have drifted apart")

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
                       "integrity_checks": flags, "derived": {
                           "vos_closed_loop_v": d["vos_closed_loop_v"],
                           "vos_method_delta_v": d["vos_method_delta_v"],
                           "av0_db_joined": av0[k],
                       }, "row": row})

    unexplained = [d for d in verdict_disagreements if not d["explained_by_tolerance"]]
    hw = max((abs(float(harness[k]["vos_null_v"])), k) for k in expected_keys())
    hd = max((abs(float(harness[k]["vos_method_delta_v"])), k) for k in expected_keys())
    summary = {"bound": {"max_abs_v": OFFSET_BOUND_V},
               "harness_worst": {"point": key_str(hw[1]), "value": hw[0],
                                 "verdict": "pass" if hw[0] <= OFFSET_BOUND_V else "fail"},
               "harness_points_over_bound": [key_str(k) for k in expected_keys()
                                             if abs(float(harness[k]["vos_null_v"])) > OFFSET_BOUND_V],
               "harness_worst_method_delta": {"point": key_str(hd[1]), "value": hd[0]}}
    if env is not None:
        summary["tool"] = E.tool_summary(env, ("vos_null_v",))
    return {
        "schema": "sg13g2-opamp/input-offset/klt-compare/2",
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
    hd = r["harness_worst_method_delta"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}",
             f"  offset bound |Vos| <= {r['bound']['max_abs_v']}: harness worst {hw['point']} = {hw['value']:.6g} ({hw['verdict']})",
             f"  two-method agreement: harness worst |method delta| {hd['point']} = {hd['value']:.6g}"]
    lines.extend(E.tool_summary_lines(rep))
    return "\n".join(E.summary_tail(lines, rep))


def _run(a, tool: Dict[Key, Dict[str, object]], env: dict) -> dict:
    """compare's body: the null envelope is already gated; load the closed-loop
    envelope and the Av0 join, then compare."""
    cl_env, cl = E.load_envelope(a.cl, index_envelope, kind="cl")
    harness = load_harness_csv(a.harness_csv)
    try:
        av0 = P.read_av0_csv(a.av0_csv)
    except P.OffsetPostError as exc:
        raise InputError(str(exc)) from exc
    return compare(tool, cl, harness, av0, env, cl_env)


def main(argv: Optional[List[str]] = None) -> int:
    return E.run_cli(
        argv, description=__doc__.split("\n\n")[0], compare_help="join both envelopes with the harness record",
        harness_args=(("--cl", {"required": True, "help": "the closed-loop cross-check envelope (.cl.sim.json)"}),
                      ("--av0-csv", {"required": True, "help": "the joined same-DUT open-loop-ac record CSV (per-corner Av0)"}),
                      ("--harness-csv", {"required": True})),
        validate_args=(("--kind", {"choices": ("null", "cl"), "required": True, "help":
                      "which measurement set `validate` gates"}),),
        compare_index_kw={"kind": "null"},
        index_fn=index_envelope,
        run=_run,
        inputs=(("cl_envelope", "cl", True), ("av0_csv", "av0_csv", True),
                ("harness_csv", "harness_csv", True)),
        summary=_text_summary)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Compare the input-cmr (ICMR) bench's `klt sim` envelope against the harness record.

Usage:

    compare.py validate <envelope.json> [--points grid|nominal]
    compare.py compare --envelope <icmr.sim.json> --harness-csv <records/<id>.csv> \
        [--points grid|nominal] [--json-out <report.json>] [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator. The
ICMR row is Measured, not ratified (spec/target-spec.md section 2), so there is
no ratified bound here and this script never computes a pass/fail verdict on
the amplifier. The bounds, the replica-measured saturation requirements and the
state at each bound are measured by `klt sim`; this script (a) refuses
envelopes that are not complete, gradable evidence, (b) derives the per-point
mechanism labels and the "does VDD/2 lie inside the range" flag from the
measured values by the harness's own rule, and (c) reports whether the harness
path and the tool path agree, listing every difference.

`--points` names the set of (process, temperature, VDD) keys the envelope must
contain EXACTLY: `grid` (the ratified 45 points, default) or `nominal` (the
single mos_tt / 27 C / 1.20 V point).

`validate` is the gate sim/input-cmr/klt/run.sh applies before an envelope may
enter records/. It rejects an unreadable / error envelope; a key set that is not
exactly the requested one; `coverage.nothing_checked` not false or anything
skipped; an aggregate or per-corner status other than pass/fail (errored,
inconclusive); a declared measurement that is absent, duplicated, non-finite or
reports the wrong unit; a measurement whose `limits` differ from the pinned
integrity bounds in make_requests.py (a request that relaxed or removed one is
not evidence); an integrity measurement that failed (a bound located zero or
several times, a bias replica that does not match the DUT, a knee outside the
plausible band: the bounds would be artifacts); and Vcm != VDD/2.

`compare` joins the envelope and the harness record on the full (process,
temperature, VDD) key and reports, per point and per metric, the harness value,
the tool value, the delta, the tolerance and whether it is within. Exit status:

    0  every comparison within tolerance and every derived label agrees
    1  at least one comparison outside tolerance, or a derived label that
       disagrees without being explained by the tolerance (report still
       written -- an out-of-tolerance point is reported, never hidden)
    2  inputs unusable (see `validate`; or a malformed harness CSV)
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.normpath(os.path.join(_HERE, "..", "..", "tools"))
for _p in (_TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import klt_envelope as E  # noqa: E402
import make_requests as REQ  # noqa: E402
from klt_envelope import InputError, Key, expected_keys, key_str, make_key  # noqa: E402,F401

# ------------------------------------------------------------ point sets
NOMINAL_KEY: Key = make_key("mos_tt", 27, 1.20)
POINT_SETS = {
    "grid": tuple(expected_keys()),
    "nominal": (NOMINAL_KEY,),
}

# ----------------------------------------------------------- measurements
# Single source of truth: the request generator. The unit is part of the
# contract; the integrity limits are pinned LITERALLY from the generator, so an
# envelope from a request that relaxed or dropped one is rejected.
_DECLARED = REQ.build_measurements()
MEASUREMENT_UNITS = {m["name"]: m["unit"] for m in _DECLARED}
MEASUREMENTS = tuple(MEASUREMENT_UNITS)
INTEGRITY_LIMITS = {m["name"]: m["limits"] for m in _DECLARED if "limits" in m}
INTEGRITY = tuple(INTEGRITY_LIMITS)

# ------------------------------------------------------------- tolerances
# Comparison tolerance |tool - harness| <= base + REL_CROSS_HOST*|harness| +
# ABS_FLOOR, NOT a pass/fail limit. Each base is analytic, from a stated
# difference between the two paths (README.md "Comparison tolerance"), not
# fitted to the record:
#
# * Vdsat5 quantisation. The harness reads the M5 knee off a 2.5 mV Vds grid and
#   reports the first SAMPLE v[k+1] whose forward secant slope has fallen to 10%
#   of the maximum; the request reads it off a 250 uV grid. The harness value is
#   therefore late by up to one harness step (2.5 mV) plus half a step of
#   secant-vs-point offset (1.25 mV): VDSAT5_QUANT_V = 3.75 mV, harness >= tool.
# * The lower bound inherits that offset divided by the tail's local slope
#   dv(tail)/dVcm at the bound: LO_BOUND_TOL_V = VDSAT5_QUANT_V / 0.6. 0.6 is a
#   floor on that slope for this circuit (README.md shows the observed range),
#   so it is a bound on the shift, not the typical shift.
# * The upper bound has no such quantisation: the harness converges its
#   body-bias fixed point to within 2 fine steps (0.5 mV, verified at that
#   level) and extracts Vth on a 5 mV gate grid with log-interpolation, and the
#   request's Vth servo has ~0.06 mV finite-gain error: HI_BOUND_TOL_V = 1 mV.
# * State read at the in-range-adjacent SAMPLE of a bound (vtail_*, vgs1_hi,
#   vds*_hi): both paths use a 250 uV Vcm grid, but the grids are offset, so the
#   two adjacent samples can differ by one step; the quantity moves at most
#   ~1 V/V with Vcm there: SAMPLE_STEP_V = 0.25 mV is added.
# * Cross-host numerics: DR-0005 measured 9.9e-4 relative drain-current
#   difference between the macOS/aarch64 ngspice-46 that produced the harness
#   record and Linux/x86_64 default-tolerance runs of this PDK; 1e-3 relative
#   is allowed on every value, plus an absolute floor (vntol 1 uV; 1 nA for
#   currents).
VDSAT5_QUANT_V = 3.75e-3
TAIL_SLOPE_FLOOR = 0.6
LO_BOUND_TOL_V = VDSAT5_QUANT_V / TAIL_SLOPE_FLOOR
HI_BOUND_TOL_V = 1e-3
SAMPLE_STEP_V = 250e-6
REL_CROSS_HOST = 1e-3
ABS_FLOOR_V = 1e-6
ABS_FLOOR_A = 1e-9

# tool name -> (harness column, base tolerance, unit)
COMPARED = {
    "icmr_lo_v": ("icmr_lo_v", LO_BOUND_TOL_V, "V"),
    "icmr_hi_v": ("icmr_hi_v", HI_BOUND_TOL_V, "V"),
    "vdsat5_v": ("vdsat5_meas_v", VDSAT5_QUANT_V, "V"),
    "vth_pair_cc_v": ("vth_pair_cc_v", HI_BOUND_TOL_V, "V"),
    "vtail_lo_v": ("vtail_lo_v", VDSAT5_QUANT_V + SAMPLE_STEP_V, "V"),
    "vtail_hi_v": ("vtail_hi_v", HI_BOUND_TOL_V + SAMPLE_STEP_V, "V"),
    "vgs1_hi_v": ("vgs1_hi_v", HI_BOUND_TOL_V + SAMPLE_STEP_V, "V"),
    "vds1_hi_v": ("vds1_hi_v", HI_BOUND_TOL_V + SAMPLE_STEP_V, "V"),
    "vds2_hi_v": ("vds2_hi_v", HI_BOUND_TOL_V + SAMPLE_STEP_V, "V"),
    "op_vout_v": ("op_vout_v", 0.0, "V"),
    "op_vtail_v": ("op_vtail_v", 0.0, "V"),
    "op_vd1_v": ("op_vd1_v", 0.0, "V"),
    "op_vd2_v": ("op_vd2_v", 0.0, "V"),
    "op_vibias_v": ("op_vibias_v", 0.0, "V"),
    "op_ivdd_a": ("op_ivdd_a", 0.0, "A"),
}
# Reported in the envelope but not compared point by point: ivdd at the bounds
# (it moves steeply with the bound position inside the harness's own tolerance
# band), the lo-side Vds values (same reason) and the integrity bookkeeping.
HARNESS_COLUMNS = (
    ("vcm_v", "icmr_span_v", "margin_m5_hi_v", "margin_pair_lo_v")
    + tuple(c for c, _, _ in COMPARED.values())
)
HARNESS_FLAGS = ("contains_vcm", "op_pass")
MARGIN_TOL_V = LO_BOUND_TOL_V      # a margin is a difference of two compared quantities


def tolerance(metric: str, harness_value: float) -> float:
    _, base, unit = COMPARED[metric]
    floor = ABS_FLOOR_A if unit == "A" else ABS_FLOOR_V
    return base + REL_CROSS_HOST * abs(harness_value) + floor


# ---------------------------------------------------------- derived labels
def mech_lo(vds1_lo: float, vds2_lo: float, vgs1_hi: float, vth_cc: float) -> str:
    """The harness rule (run_cmr_sweep.sh): the lower bound is the M5 headroom
    alone unless the pair is also past its saturation requirement there."""
    margin_pair_lo = min(vds1_lo, vds2_lo) - (vgs1_hi - vth_cc)
    return "m5_headroom" if margin_pair_lo > 0 else "m5_headroom+pair_saturation"


def mech_hi(vtail_hi: float, vdsat5: float) -> str:
    return "pair_saturation" if vtail_hi - vdsat5 > 0 else "pair_saturation+m5_headroom"


def margin_pair_lo(t: Dict[str, object]) -> float:
    return min(t["vds1_lo_v"], t["vds2_lo_v"]) - (t["vgs1_hi_v"] - t["vth_pair_cc_v"])


# --------------------------------------------------------------- envelopes
def _check_envelope(env: dict, label: str, problems: List[str]) -> None:
    """Envelope-level rules beyond the shared gate: nothing errored or
    inconclusive, and every integrity row carries exactly the pinned bounds."""
    for field in ("errored", "inconclusive"):
        if env.get(field) not in (0, None):
            raise InputError(f"{label}: {field} = {env.get(field)!r}, expected 0")
    top = {m.get("name"): m for m in env.get("measurements") or [] if isinstance(m, dict)}
    for n, lim in INTEGRITY_LIMITS.items():
        got = (top.get(n) or {}).get("limits")
        if got != lim:
            problems.append(f"{n}: envelope limits {got!r} != literal integrity bound {lim!r}")


def _literal_verdict(value: float, limits: Dict[str, float]) -> str:
    lo, hi = limits.get("min"), limits.get("max")
    return "pass" if (lo is None or value >= lo) and (hi is None or value <= hi) else "fail"


def _check_measurement(k: Key, n: str, m: dict, v: float, problems: List[str]) -> bool:
    if m.get("unit") != MEASUREMENT_UNITS[n]:
        problems.append(f"{key_str(k)}: measurement {n} unit {m.get('unit')!r} != {MEASUREMENT_UNITS[n]!r}")
        return False
    if n in INTEGRITY_LIMITS:
        if m["status"] != _literal_verdict(v, INTEGRITY_LIMITS[n]):
            problems.append(f"{key_str(k)}: measurement {n} status {m['status']!r} contradicts value {v!r} "
                            f"against the literal bound {INTEGRITY_LIMITS[n]!r}")
            return False
        if m["status"] != "pass":
            problems.append(f"{key_str(k)}: integrity measurement {n} = {v!r} failed -- the bounds are an "
                            "artifact at this point, not evidence")
            return False
    return True


def index_envelope(env: dict, label: str = "envelope",
                   points: Sequence[Key] = POINT_SETS["grid"]) -> Dict[Key, Dict[str, object]]:
    """The shared envelope gate (klt_envelope.index_envelope) on the vcm supply
    key and the requested point set, plus the two hooks above."""
    return E.index_envelope(env, label, MEASUREMENTS, accept_statuses=("pass", "fail"), supply_key="vcm",
                            points=points, envelope_check=_check_envelope,
                            measurement_check=_check_measurement)


# ----------------------------------------------------------- harness CSV
def load_harness_csv(path: str, points: Sequence[Key] = POINT_SETS["grid"]) -> Dict[Key, Dict[str, object]]:
    return E.load_harness_csv_rows(path, HARNESS_COLUMNS, "harness CSV", points=points,
                                   flag_columns=HARNESS_FLAGS)


# ------------------------------------------------------------- comparison
def compare(tool: Dict[Key, Dict[str, object]], harness: Dict[Key, Dict[str, object]],
            points: Sequence[Key] = POINT_SETS["grid"], env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for k in points:
        if k not in tool:
            problems.append(f"{key_str(k)}: missing from envelope")
        if k not in harness:
            problems.append(f"{key_str(k)}: missing from harness CSV")
    if problems:
        raise InputError("; ".join(problems))

    out_of_tol: List[str] = []
    disagreements: List[dict] = []
    point_reports = []
    for k in points:
        h, t = harness[k], tool[k]
        vcm = k[2] / 2
        metrics = {}
        for m, (col, _, unit) in COMPARED.items():
            hv, tv = h[col], float(t[m])
            tol = tolerance(m, hv)
            delta = tv - hv
            within = abs(delta) <= tol
            metrics[m] = {"harness": hv, "tool": tv, "delta": delta, "tolerance": tol,
                          "within": within, "unit": unit}
            if not within:
                out_of_tol.append(f"{key_str(k)} {m}: tool {tv:.9g} vs harness {hv:.9g} "
                                  f"(delta {delta:.3g} {unit}, tolerance {tol:.3g} {unit})")
        span_t = float(t["icmr_hi_v"]) - float(t["icmr_lo_v"])
        metrics["icmr_span_v"] = {"harness": h["icmr_span_v"], "tool": span_t,
                                  "delta": span_t - h["icmr_span_v"],
                                  "tolerance": LO_BOUND_TOL_V + HI_BOUND_TOL_V + 2 * ABS_FLOOR_V
                                  + REL_CROSS_HOST * abs(h["icmr_span_v"]), "unit": "V"}
        e = metrics["icmr_span_v"]
        e["within"] = abs(e["delta"]) <= e["tolerance"]
        if not e["within"]:
            out_of_tol.append(f"{key_str(k)} icmr_span_v: tool {span_t:.9g} vs harness {h['icmr_span_v']:.9g} "
                              f"(delta {e['delta']:.3g} V, tolerance {e['tolerance']:.3g} V)")

        # Labels derived from the measured values by the harness's own rule.
        # Tolerance only says whether a disagreement is EXPLAINED (the harness's
        # own margin / distance lies within tolerance of the decision edge); it
        # never changes a label.
        m_lo = mech_lo(t["vds1_lo_v"], t["vds2_lo_v"], t["vgs1_hi_v"], t["vth_pair_cc_v"])
        m_hi = mech_hi(t["vtail_hi_v"], t["vdsat5_v"])
        h_m_lo = "m5_headroom" if h["margin_pair_lo_v"] > 0 else "m5_headroom+pair_saturation"
        h_m_hi = "pair_saturation" if h["margin_m5_hi_v"] > 0 else "pair_saturation+m5_headroom"
        tool_contains = float(t["icmr_lo_v"]) <= vcm <= float(t["icmr_hi_v"])
        labels = {
            "mech_lo": {"harness": h_m_lo, "tool": m_lo, "agree": h_m_lo == m_lo,
                        "tool_margin_v": margin_pair_lo(t), "harness_margin_v": h["margin_pair_lo_v"],
                        "explained": abs(h["margin_pair_lo_v"]) <= MARGIN_TOL_V},
            "mech_hi": {"harness": h_m_hi, "tool": m_hi, "agree": h_m_hi == m_hi,
                        "tool_margin_v": float(t["vtail_hi_v"]) - float(t["vdsat5_v"]),
                        "harness_margin_v": h["margin_m5_hi_v"],
                        "explained": abs(h["margin_m5_hi_v"]) <= MARGIN_TOL_V},
            "contains_vcm": {"harness": h["contains_vcm"], "tool": tool_contains,
                             "agree": h["contains_vcm"] == tool_contains,
                             "harness_distance_to_edge_v": min(abs(vcm - h["icmr_lo_v"]), abs(h["icmr_hi_v"] - vcm)),
                             "explained": min(abs(vcm - h["icmr_lo_v"]), abs(h["icmr_hi_v"] - vcm))
                             <= LO_BOUND_TOL_V},
        }
        for name, d in labels.items():
            if not d["agree"]:
                disagreements.append({"point": key_str(k), "label": name, **d})
        point_reports.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                              "metrics": metrics, "labels": labels})

    unexplained = [d for d in disagreements if not d["explained"]]
    return {
        "schema": "sg13g2-opamp/input-cmr/klt-compare/1",
        "points_compared": len(point_reports),
        "point_set": [key_str(k) for k in points],
        "tolerance_basis": {"vdsat5_quant_v": VDSAT5_QUANT_V, "tail_slope_floor": TAIL_SLOPE_FLOOR,
                            "lo_bound_tol_v": LO_BOUND_TOL_V, "hi_bound_tol_v": HI_BOUND_TOL_V, "sample_step_v": SAMPLE_STEP_V,
                            "rel_cross_host": REL_CROSS_HOST, "abs_floor_v": ABS_FLOOR_V,
                            "abs_floor_a": ABS_FLOOR_A},
        "out_of_tolerance": out_of_tol,
        "bound_verdict_disagreements": disagreements,
        "unexplained_bound_verdict_disagreements": len(unexplained),
        "points": point_reports,
        "status": "agree" if not out_of_tol and not unexplained else "disagree",
    }


def _text_summary(rep: dict) -> str:
    lines = [f"compare: {rep['points_compared']} point(s), status {rep['status']}"]
    for p in rep["points"]:
        for m, e in p["metrics"].items():
            lines.append(f"  {p['point_id']} {m}: harness {e['harness']:.9g} tool {e['tool']:.9g} "
                         f"delta {e['delta']:+.3g} (tol {e['tolerance']:.3g}) {'ok' if e['within'] else 'OUT'}")
        for name, d in p["labels"].items():
            lines.append(f"  {p['point_id']} {name}: harness {d['harness']}, tool {d['tool']}"
                         f"{'' if d['agree'] else '  DISAGREE' + (' (explained)' if d['explained'] else '')}")
    return "\n".join(E.summary_tail(lines, rep))


def main(argv: Optional[List[str]] = None) -> int:
    def run(a, tool_idx, env):
        points = POINT_SETS[a.points]
        return compare(tool_idx, load_harness_csv(a.harness_csv, points), points, env)

    return E.run_cli(
        argv, description=__doc__.split("\n\n")[0],
        compare_help="join the envelope with the harness record",
        harness_args=[("--harness-csv", {"required": True})],
        common_args=[("--points", {"choices": sorted(POINT_SETS), "default": "grid"})],
        index_fn=lambda env, label, points: index_envelope(env, label, POINT_SETS[points]),
        run=run, inputs=[("harness_csv", "harness_csv", True)],
        summary=_text_summary, validate_noun="corner(s)")


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Compare the output-swing bench's `klt sim` envelope against the harness record.

Usage:

    compare.py validate <envelope.json> [--points grid|nominal]
    compare.py compare --envelope <swing.sim.json> --harness-csv <records/<id>.csv> \
        [--points grid|nominal] [--json-out <report.json>] [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator, and it
NEVER computes a swing verdict of its own. The three ratified numbers
(headroom_hi_v, headroom_lo_v, swing_span_v) are measured and graded by `klt
sim`; this script only (a) refuses envelopes that are not complete, gradable
evidence and (b) reports whether the harness path and the tool path agree.

`--points` names the set of (process, temperature, VDD) keys the envelope must
contain EXACTLY:

    grid     the ratified 45-point grid (default; the deferred full-envelope work)
    nominal  the single mos_tt / 27 C / 1.20 V prototype point

`validate` is the gate sim/output-swing/klt/run.sh applies before an envelope
may enter records/. It rejects: an unreadable / error envelope; a key set that
is not exactly the requested one (missing, duplicate, unexpected points);
`coverage.nothing_checked` not false or anything skipped; an aggregate or
per-corner status other than pass/fail (errored, inconclusive, not_checked);
a declared measurement that is absent, duplicated, non-finite, carries a
status other than pass/fail, or reports the wrong unit; a ratified
measurement whose `limits` differ from the literal ratified bounds
(RATIFIED_LIMITS -- a request that relaxed a bound is not evidence); a
verdict that contradicts the literal bound applied to the reported value; an
integrity measurement (window-edge, monotonic, plausible-gain) that failed
(its tracking bounds would then be window artifacts); and Vcm != VDD/2.
A complete run in which a ratified row FAILS its literal bound (for example a
span just below 0.571 V) is VALID evidence: validate accepts it, because a
bound miss is a result, not a data fault.

`compare` joins the envelope and the harness record on the full (process,
temperature, VDD) key and reports, per point and per metric, the harness value,
the tool value, the delta, the comparison tolerance (TOLERANCE_* below) and
whether it is within. Comparison tolerances are NEVER applied to a ratified
limit: the literal bounds live in RATIFIED_LIMITS and are only used to (i)
check the tool's own verdict is consistent with its value and (ii) derive the
harness's literal verdict for the per-row agreement check. Exit status:

    0  every comparison within tolerance and every row verdict agrees
    1  at least one comparison outside tolerance, or a row verdict that
       disagrees without being explained by the tolerance (report still
       written -- an out-of-tolerance point is reported, never hidden)
    2  inputs unusable (see `validate`; or a malformed harness CSV)
"""

from __future__ import annotations

import csv
import math
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import klt_envelope as E  # noqa: E402
from klt_envelope import InputError, Key, expected_keys, finite, key_str, make_key  # noqa: E402,F401

# ------------------------------------------------------------ point sets
NOMINAL_KEY: Key = make_key("mos_tt", 27, 1.20)
POINT_SETS = {
    "grid": tuple(expected_keys()),
    "nominal": (NOMINAL_KEY,),
}

# ------------------------------------------------- literal ratified limits
# spec/target-spec.md section 2, [DR-2]: headroom >= 251 mV from VDD and
# >= 141 mV from VSS worst-case, tracking span >= 0.571 V worst-case, at the
# -6 dB incremental-gain criterion, CL = 2 pF, unloaded. LITERAL: never
# widened by any comparison tolerance below. (The harness record's worst span
# is 0.570957773 V -- a literal miss of this bound; see README.md.)
RATIFIED_LIMITS = {
    "headroom_hi_v": {"min": 0.251},
    "headroom_lo_v": {"min": 0.141},
    "swing_span_v": {"min": 0.571},
}

# ----------------------------------------------------------- measurements
# name -> unit. The unit is part of the contract (a V value reported in mV is
# a 1000x error that no finiteness check would see).
MEASUREMENT_UNITS = {
    "gpk_vv": "V/V",
    "mono_min_dv_v": "V",
    "pk_idx": "index",
    "lo_idx": "index",
    "hi_idx": "index",
    "vmax_track_v": "V",
    "vmin_track_v": "V",
    "headroom_hi_v": "V",
    "headroom_lo_v": "V",
    "swing_span_v": "V",
}
MEASUREMENTS = tuple(MEASUREMENT_UNITS)
RATIFIED = tuple(RATIFIED_LIMITS)
# Integrity measurements: graded by the tool against the harness's own sanity
# rules. A FAIL here means the ratified numbers are window/curve artifacts, so
# the envelope is not evidence (unlike a ratified-row FAIL).
INTEGRITY = ("gpk_vv", "mono_min_dv_v", "lo_idx", "hi_idx")

# ------------------------------------------------------------- tolerances
# Comparison tolerance (|tool - harness| <= abs + rel*|harness| + extra), NOT a
# pass/fail limit. Basis (README.md "Comparison tolerance" has the full text):
#
# * Estimator difference, bounded analytically per point. Both paths use the
#   same sampled definition (contiguous segments >= 0.5*peak, endpoint
#   samples), at the same 10 uV Vid step, but the harness centres its +-25 mV
#   fine window on the coarse Vout = Vcm crossing while the request sweeps a
#   FIXED window, so the two sample grids are offset by a fraction of one step.
#   A boundary sample can therefore land one step (VID_STEP_V) away, and
#   |dVout| over one step is at most the PEAK incremental gain times the step:
#   boundary_tol = VID_STEP_V * peak_inc_gain_v_v (harness column, per point).
#   A span has two boundaries: 2 * that.
# * Cross-host numerics: DR-0005 measured 9.9e-4 relative drain-current
#   difference between the macOS/aarch64 ngspice-46 that produced the harness
#   record and Linux/x86_64 default-tolerance runs of this PDK; 1e-3 relative
#   is allowed on every value, plus 1 uV (vntol).
# The bound is analytic, not fitted: the one-point prototype observes deltas of
# well under a third of it (README.md); the 45-point run must confirm it per
# point and explain any exceedance.
VID_STEP_V = 10e-6
REL_CROSS_HOST = 1e-3
ABS_FLOOR_V = 1e-6
# metric -> number of window boundaries its value depends on
METRIC_BOUNDARIES = {
    "vmax_track_v": 1, "vmin_track_v": 1,
    "headroom_hi_v": 1, "headroom_lo_v": 1,
    "swing_span_v": 2,
}
COMPARED = tuple(METRIC_BOUNDARIES)
HARNESS_COLUMN = {
    "vmax_track_v": "vout_max_track_v", "vmin_track_v": "vout_min_track_v",
    "headroom_hi_v": "headroom_hi_v", "headroom_lo_v": "headroom_lo_v",
    "swing_span_v": "swing_span_v",
}
HARNESS_COLUMNS = ("vcm_v", "op_pass", "peak_inc_gain_v_v") + tuple(HARNESS_COLUMN.values())


def tolerance(metric: str, harness_value: float, harness_peak_gain: float) -> float:
    return (METRIC_BOUNDARIES[metric] * VID_STEP_V * harness_peak_gain
            + REL_CROSS_HOST * abs(harness_value) + ABS_FLOOR_V)


# ------------------------------------------------------- literal verdicts
def literal_verdict(value: float, limits: Dict[str, float]) -> str:
    """pass/fail of `value` against LITERAL limits (no tolerance anywhere)."""
    lo, hi = limits.get("min"), limits.get("max")
    return "pass" if (lo is None or value >= lo) and (hi is None or value <= hi) else "fail"


# --------------------------------------------------------------- envelopes
def _check_envelope(env: dict, label: str, problems: List[str]) -> None:
    """Envelope-level rules beyond the shared gate: nothing errored or
    inconclusive, and the ratified rows carry exactly the literal bounds."""
    for field in ("errored", "inconclusive"):
        if env.get(field) not in (0, None):
            raise InputError(f"{label}: {field} = {env.get(field)!r}, expected 0")
    top = {m.get("name"): m for m in env.get("measurements") or [] if isinstance(m, dict)}
    for n, lim in RATIFIED_LIMITS.items():
        got = (top.get(n) or {}).get("limits")
        if got != lim:
            problems.append(f"{n}: envelope limits {got!r} != literal ratified bound {lim!r}")


def _check_measurement(k: Key, n: str, m: dict, v: float, problems: List[str]) -> bool:
    """Per-measurement rules beyond the shared gate: the unit, a ratified
    row's verdict against its literal bound, and an integrity measurement's
    pass. Returns whether the value may be kept."""
    if m.get("unit") != MEASUREMENT_UNITS[n]:
        problems.append(f"{key_str(k)}: measurement {n} unit {m.get('unit')!r} != {MEASUREMENT_UNITS[n]!r}")
        return False
    if n in RATIFIED_LIMITS and m["status"] != literal_verdict(v, RATIFIED_LIMITS[n]):
        problems.append(f"{key_str(k)}: measurement {n} status {m['status']!r} contradicts value {v!r} "
                        f"against the literal bound {RATIFIED_LIMITS[n]!r}")
        return False
    if n in INTEGRITY and m["status"] != "pass":
        problems.append(f"{key_str(k)}: integrity measurement {n} = {v!r} failed -- the tracking bounds "
                        "are a window/curve artifact at this point, not evidence")
        return False
    return True


def index_envelope(env: dict, label: str = "envelope",
                   points: Sequence[Key] = POINT_SETS["grid"]) -> Dict[Key, Dict[str, object]]:
    """The shared envelope gate (klt_envelope.index_envelope) on the vcm
    supply key and the requested point set, plus _check_envelope and
    _check_measurement. See the module docstring for the rules."""
    return E.index_envelope(env, label, MEASUREMENTS, accept_statuses=("pass", "fail"), supply_key="vcm",
                            points=points, envelope_check=_check_envelope,
                            measurement_check=_check_measurement)


# ----------------------------------------------------------- harness CSV
def load_harness_csv(path: str, points: Sequence[Key] = POINT_SETS["grid"]) -> Dict[Key, Dict[str, object]]:
    """Read the harness record's rows needed by the join; refuse duplicates,
    non-finite numbers, and a key set other than `points` PLUS (for the grid)
    nothing else. A one-point join still requires the harness row for that
    point and ignores the other 44 (they are not under comparison)."""
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        raise InputError(f"{path}: unreadable harness CSV ({e})")
    problems: List[str] = []
    out: Dict[Key, Dict[str, object]] = {}
    for r in rows:
        try:
            k = make_key(r["corner"], r["temp_c"], r["vdd_v"])
        except (KeyError, ValueError, TypeError):
            problems.append(f"malformed row {r!r}")
            continue
        if k in out:
            problems.append(f"{key_str(k)}: duplicate harness row")
            continue
        if r.get("point_id") != key_str(k):
            problems.append(f"{key_str(k)}: point_id {r.get('point_id')!r} disagrees with its corner/temp/vdd")
        vals: Dict[str, object] = {}
        for c in HARNESS_COLUMNS:
            try:
                x = float(r[c])
            except (KeyError, ValueError, TypeError):
                problems.append(f"{key_str(k)}: column {c} missing or not a number ({r.get(c)!r})")
                continue
            if not math.isfinite(x):
                problems.append(f"{key_str(k)}: column {c} is non-finite ({r.get(c)!r})")
                continue
            vals[c] = x
        out[k] = vals
    for k in sorted(set(points) - set(out)):
        problems.append(f"{key_str(k)}: missing from harness CSV")
    if set(points) == set(POINT_SETS["grid"]):
        for k in sorted(set(out) - set(points)):
            problems.append(f"{key_str(k)}: unexpected point in harness CSV")
    if problems:
        raise InputError(f"{path}: " + "; ".join(problems))
    return out


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
        gpk = h["peak_inc_gain_v_v"]
        metrics = {}
        for m in COMPARED:
            hv = h[HARNESS_COLUMN[m]]
            tv = float(t[m])
            tol = tolerance(m, hv, gpk)
            delta = tv - hv
            within = abs(delta) <= tol
            metrics[m] = {"harness": hv, "tool": tv, "delta": delta, "tolerance": tol,
                          "within": within, "unit": "V"}
            if not within:
                out_of_tol.append(f"{key_str(k)} {m}: tool {tv:.9g} vs harness {hv:.9g} "
                                  f"(delta {delta:.3g} V, tolerance {tol:.3g} V)")
        # Row verdicts: the tool's is the envelope's own; the harness's is the
        # LITERAL bound applied to the harness value. Tolerance is used only
        # to say whether a disagreement is explained (the harness value lies
        # within tolerance of the bound), never to relax the bound.
        rows = {}
        for m, lim in RATIFIED_LIMITS.items():
            hv = h[HARNESS_COLUMN[m]]
            tool_v = t[m + "__status"]
            harness_v = literal_verdict(hv, lim)
            bound = lim["min"]
            near = abs(hv - bound) <= tolerance(m, hv, gpk)
            rows[m] = {"bound_min": bound, "tool_verdict": tool_v, "harness_verdict": harness_v,
                       "agree": tool_v == harness_v, "harness_within_tolerance_of_bound": near}
            if tool_v != harness_v:
                disagreements.append({"point": key_str(k), "row": m, "harness": hv, "tool": float(t[m]),
                                      "bound_min": bound, "tool_verdict": tool_v, "harness_verdict": harness_v,
                                      "explained_by_tolerance": near})
        point_reports.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                              "harness_peak_gain_v_v": gpk, "metrics": metrics, "rows": rows})

    unexplained = [d for d in disagreements if not d["explained_by_tolerance"]]
    summary: Dict[str, object] = {"ratified_limits": RATIFIED_LIMITS}
    if env is not None:
        summary["tool"] = {}
        for m in env.get("measurements") or []:
            if m.get("name") in RATIFIED_LIMITS:
                summary["tool"][m["name"]] = {"status": m.get("status"), "limits": m.get("limits"),
                                              "worst_case": m.get("worst_case")}
    return {
        "schema": "sg13g2-opamp/output-swing/klt-compare/1",
        "points_compared": len(point_reports),
        "point_set": [key_str(k) for k in points],
        "tolerance_basis": {"vid_step_v": VID_STEP_V, "rel_cross_host": REL_CROSS_HOST,
                            "abs_floor_v": ABS_FLOOR_V, "boundaries": METRIC_BOUNDARIES},
        "out_of_tolerance": out_of_tol,
        "bound_verdict_disagreements": disagreements,
        "unexplained_bound_verdict_disagreements": len(unexplained),
        "row": summary,
        "points": point_reports,
        "status": "agree" if not out_of_tol and not unexplained else "disagree",
    }


def _text_summary(rep: dict) -> str:
    lines = [f"compare: {rep['points_compared']} point(s), status {rep['status']}"]
    for p in rep["points"]:
        for m, e in p["metrics"].items():
            lines.append(f"  {p['point_id']} {m}: harness {e['harness']:.9g} tool {e['tool']:.9g} "
                         f"delta {e['delta']:+.3g} (tol {e['tolerance']:.3g}) {'ok' if e['within'] else 'OUT'}")
        for m, r in p["rows"].items():
            lines.append(f"  {p['point_id']} row {m} >= {r['bound_min']}: tool {r['tool_verdict']}, "
                         f"harness {r['harness_verdict']}")
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

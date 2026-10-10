#!/usr/bin/env python3
"""Compare the slew-rate bench's `klt sim` envelope against the harness record.

Usage:

    compare.py validate <envelope.json>
    compare.py compare --envelope <slew.sim.json> --harness-csv <records/<id>.csv> \
        --harness-tran-dir <corners/<id>/> [--json-out <report.json>] \
        [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator.

`validate` is the gate sim/slew-rate/klt/run.sh applies to the envelope before
it is allowed into records/: exactly the 45-point ratified grid, one corner per
(process, temperature, VDD) point, Vcm = VDD/2 at every corner, every declared
measurement present and finite at every corner, no corner `error` /
`inconclusive`, and `coverage.nothing_checked` false with nothing skipped. An
envelope that fails any of these is an incomplete run, not evidence.

`compare` joins the envelope and the harness record
(sim/slew-rate/records/20260918-210216-90844d2.csv) on the full
(process, temperature, VDD) key, refuses anything but the same 45 unique points
on both sides, and reports per corner and per metric the difference against a
stated tolerance (TOLERANCES below). Exit status:

    0  every comparison within tolerance and every verdict agrees
    1  at least one comparison outside tolerance, or a bound verdict that
       disagrees without being explained by the tolerance (report still
       written -- an out-of-tolerance point is reported, never hidden)
    2  inputs unusable: missing/duplicate/extra points, missing or
       non-finite measurements, malformed envelope

Comparison tolerances never touch a pass/fail limit. The ratified bound
(SLEW_BOUND_V_PER_US) is graded by `klt sim` itself, once per edge; this script
only reports whether the two measurement paths agree, and whether they agree
about the bound.
"""

from __future__ import annotations

import functools
import os
import sys
from typing import Dict, Iterable, List, Optional, Tuple

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
# Everything slew-rate/klt/slew.request.json reports. The tool's per-edge slew
# measurements carry the ratified bound; the rest are either integrity checks
# (graded by the tool, compared against the harness's own check flags) or
# unlimited values joined against the harness CSV.
MEASUREMENTS = (
    "t_rise_outer_s", "t_fall_outer_s", "t_rise_inner_s", "t_fall_inner_s",
    "sr_rise_v_per_us", "sr_fall_v_per_us",
    "sr_rise_inner_v_per_us", "sr_fall_inner_v_per_us",
    "lin_rise_ratio", "lin_fall_ratio",
    "pre_rise_orel_v", "pre_fall_orel_v",
    "vinn_max_v", "vinn_min_v", "vout_dc_v", "drive_pp_v", "drive_centre_err_v",
    "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v",
    "op_vout_offset_frac", "op_vout_rail_frac", "op_vd1_rail_frac",
    "op_vd2_rail_frac", "op_vtail_rail_frac",
)
OP_SANITY = tuple(m for m in MEASUREMENTS if m.startswith("op_"))
LINEARITY = ("lin_rise_ratio", "lin_fall_ratio")
TRAVERSE = ("pre_rise_orel_v", "pre_fall_orel_v")
DRIVE = ("drive_pp_v", "drive_centre_err_v")
EDGE_MEASUREMENTS = ("sr_rise_v_per_us", "sr_fall_v_per_us")

# The ratified row (spec/target-spec.md section 2, [DR-2]): slew rate into
# CL = 2 pF >= 7.51 V/us, the WORSE of the rising and falling edge at each
# point. Copied here only to check that the two paths AGREE about the bound;
# the verdict of record is the envelope's. `min(rise, fall) >= B` is
# `rise >= B and fall >= B`, so the row passes at a corner iff both edge
# measurements (each carrying the same bound) pass there.
SLEW_BOUND_V_PER_US = 7.51

# ------------------------------------------------------------- tolerances
# Per-metric comparison tolerance: |tool - harness| <= abs + rel * |harness|.
#
# Basis (README.md "Comparison tolerance" carries the full argument):
#
# * Same circuit, same drive, same ngspice default solver tolerance (DR-0005:
#   no reltol/abstol/vntol override anywhere in sim/). The harness record was
#   produced on macOS/aarch64 ngspice-46; the envelope is produced wherever
#   `klt sim` runs it. DR-0005 measured a 9.9e-4 relative drain-current
#   difference between that host and Linux/x86_64 default-tolerance records of
#   this PDK; slew ~ Itail/Cc moves with the tail current, so ~1e-3 relative is
#   the cross-host allowance, and 2e-3 is allowed. (Same-host, default vs a
#   1e-6 reltol, DR-0005 found the slew columns move by <= 3.4e-6: the
#   transient number is converged; the allowance is for host-dependent paths.)
# * Measurement method: the harness reads the committed 1 ns wrdata waveform
#   (`.options interp`) with a linear-interpolated crossing of Vcm +/- h inside
#   the [T2,T3] / [T3,T_STOP] window; the request reads the same interpolated
#   samples with `.meas trig/targ ... td=`. compare.py re-derives the `.meas`
#   algorithm on the harness's own committed waveform for every point
#   (method_check below) and requires it to equal the CSV value to
#   METHOD_CHECK_REL; the observed max is 3.3e-6, the CSV's %.6g quantisation.
# * DC node voltages: 1e-3 relative + 1 uV (reltol, vntol), as in sim/open-loop-ac.
TOLERANCES = {
    "sr_rise_v_per_us": {"abs": 0.0, "rel": 2e-3, "unit": "V/us"},
    "sr_fall_v_per_us": {"abs": 0.0, "rel": 2e-3, "unit": "V/us"},
    "sr_worst_v_per_us": {"abs": 0.0, "rel": 2e-3, "unit": "V/us"},
    "sr_rise_inner_v_per_us": {"abs": 0.0, "rel": 2e-3, "unit": "V/us"},
    "sr_fall_inner_v_per_us": {"abs": 0.0, "rel": 2e-3, "unit": "V/us"},
    "vout_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vd1_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vd2_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vtail_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vibias_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
}
# The `.meas` algorithm on the harness's own waveform vs the harness CSV.
METHOD_CHECK_REL = 1e-5

# The harness's step schedule (run_slew_sweep.sh): the edge under test starts
# at T2 (rising) / T3 (falling); `td` in the request is 50 ns before each.
T_RISE_TD_S = 250e-9
T_FALL_TD_S = 500e-9
WIN_OUTER = 0.15
WIN_INNER = 0.075


# --------------------------------------------------------------- envelopes
def index_envelope(env: dict, label: str = "envelope") -> Dict[Key, Dict[str, object]]:
    """The shared envelope gate (klt_envelope.index_envelope); no bench-specific
    per-corner checks beyond every MEASUREMENTS entry present and finite."""
    return E.index_envelope(env, label, MEASUREMENTS)


# ----------------------------------------------------------------- harness
HARNESS_COLUMNS = ("vcm_v", "sr_rise_v_per_us", "sr_fall_v_per_us", "sr_worst_v_per_us",
                   "sr_rise_inner_v_per_us", "sr_fall_inner_v_per_us", "vout_dc_v",
                   "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v")
HARNESS_FLAGS = ("op_pass", "linearity_pass", "traverse_pass", "drive_pass")


def load_harness_csv(path: str) -> Dict[Key, Dict[str, object]]:
    return E.load_harness_csv_rows(path, HARNESS_COLUMNS, "harness CSV", flag_columns=HARNESS_FLAGS)


def load_waveform(path: str) -> Tuple[List[float], List[float]]:
    """The harness's committed wrdata waveform: (time, v(out)) per line."""
    t: List[float] = []
    v: List[float] = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    t.append(float(parts[0]))
                    v.append(float(parts[1]))
    except (OSError, ValueError) as e:
        raise InputError(f"{path}: unreadable waveform ({e})")
    if len(t) < 3:
        raise InputError(f"{path}: waveform has {len(t)} samples")
    return t, v


def meas_crossing(t: List[float], v: List[float], td: float, level: float, rising: bool) -> Optional[float]:
    """First linearly interpolated crossing of `level` after `td`, the way
    ngspice's `.meas ... val=<level> rise|fall=1 td=<td>` finds it."""
    for i in range(1, len(t)):
        if t[i] <= td:
            continue
        a, b = v[i - 1], v[i]
        if (rising and a <= level < b) or ((not rising) and a >= level > b):
            return t[i - 1] + (level - a) / (b - a) * (t[i] - t[i - 1])
    return None


def meas_style_slew(t: List[float], v: List[float], vcm: float, half: float, rising: bool) -> float:
    """The request's slew (2*half / dt, V/us) computed on a waveform."""
    td = T_RISE_TD_S if rising else T_FALL_TD_S
    first = vcm - half if rising else vcm + half
    second = vcm + half if rising else vcm - half
    ta = meas_crossing(t, v, td, first, rising)
    tb = meas_crossing(t, v, td, second, rising)
    if ta is None or tb is None or tb == ta:
        return float("nan")
    return 2 * half / abs(tb - ta) / 1e6


def method_check(tran_csv: str, vcm: float) -> Dict[str, float]:
    """`.meas` algorithm on the harness's own waveform, per slew column."""
    t, v = load_waveform(tran_csv)
    return {
        "sr_rise_v_per_us": meas_style_slew(t, v, vcm, WIN_OUTER, True),
        "sr_fall_v_per_us": meas_style_slew(t, v, vcm, WIN_OUTER, False),
        "sr_rise_inner_v_per_us": meas_style_slew(t, v, vcm, WIN_INNER, True),
        "sr_fall_inner_v_per_us": meas_style_slew(t, v, vcm, WIN_INNER, False),
    }


# ----------------------------------------------------------------- compare
_tol = functools.partial(E.tol, TOLERANCES)


def _all_pass(vals: Dict[str, object], names: Iterable[str]) -> bool:
    return all(vals.get(n + "__status") == "pass" for n in names)


def compare(tool: Dict[Key, Dict[str, object]], harness: Dict[Key, Dict[str, object]],
            methods: Optional[Dict[Key, Dict[str, float]]] = None,
            env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for label, d in (("envelope", tool), ("harness CSV", harness)):
        E.check_grid(d.keys(), label, problems)
    if problems:
        raise InputError("; ".join(problems))

    points = []
    out_of_tol: List[str] = []
    verdict_disagreements: List[dict] = []
    method_failures: List[str] = []
    for k in expected_keys():
        h = harness[k]
        t = tool[k]
        tv_all = {
            "sr_rise_v_per_us": t["sr_rise_v_per_us"],
            "sr_fall_v_per_us": t["sr_fall_v_per_us"],
            "sr_worst_v_per_us": min(t["sr_rise_v_per_us"], t["sr_fall_v_per_us"]),
            "sr_rise_inner_v_per_us": t["sr_rise_inner_v_per_us"],
            "sr_fall_inner_v_per_us": t["sr_fall_inner_v_per_us"],
            "vout_dc_v": t["vout_dc_v"], "vd1_dc_v": t["vd1_dc_v"], "vd2_dc_v": t["vd2_dc_v"],
            "vtail_dc_v": t["vtail_dc_v"], "vibias_dc_v": t["vibias_dc_v"],
        }
        metrics = {}
        for m, tv in tv_all.items():
            hv = float(h[m])
            tol = _tol(m, hv)
            delta = tv - hv
            entry = {"harness": hv, "tool": tv, "delta": delta,
                     "rel_delta": delta / hv if hv else None, "tolerance": tol,
                     "unit": TOLERANCES[m]["unit"], "within": abs(delta) <= tol}
            if methods is not None and m in methods[k]:
                mc = methods[k][m]
                entry["method_check"] = {"meas_style_on_harness_waveform": mc,
                                         "rel_delta_vs_csv": (mc - hv) / hv if hv else None}
                if not (abs(mc - hv) <= METHOD_CHECK_REL * abs(hv)):
                    method_failures.append(f"{key_str(k)} {m}: .meas-style {mc:.9g} vs CSV {hv:.9g}")
            if not entry["within"]:
                out_of_tol.append(f"{key_str(k)} {m}: tool {tv:.9g} vs harness {hv:.9g} "
                                  f"(delta {delta:.3g} {TOLERANCES[m]['unit']}, tolerance {tol:.3g})")
            metrics[m] = entry

        flags = {
            "op_sanity": (h["op_pass"], _all_pass(t, OP_SANITY)),
            "ramp_linearity": (h["linearity_pass"], _all_pass(t, LINEARITY)),
            "full_swing_traverse": (h["traverse_pass"], _all_pass(t, TRAVERSE)),
            "drive_integrity": (h["drive_pass"], _all_pass(t, DRIVE)),
        }
        flag_out = {}
        for name, (hf, tf) in flags.items():
            flag_out[name] = {"harness_pass": hf, "tool_pass": tf, "agree": hf == tf}
            if hf != tf:
                out_of_tol.append(f"{key_str(k)} {name}: harness pass={hf} vs tool pass={tf}")

        # Ratified row: tool verdict = conjunction of the per-edge verdicts.
        edge_status = {n: t.get(n + "__status") for n in EDGE_MEASUREMENTS}
        tool_pass = all(s == "pass" for s in edge_status.values())
        hv_worst = float(h["sr_worst_v_per_us"])
        harness_pass = hv_worst >= SLEW_BOUND_V_PER_US
        near = abs(hv_worst - SLEW_BOUND_V_PER_US) <= _tol("sr_worst_v_per_us", hv_worst)
        row = {"tool_edge_status": edge_status, "tool_pass": tool_pass, "harness_pass": harness_pass,
               "agree": tool_pass == harness_pass, "harness_within_tolerance_of_bound": near}
        if tool_pass != harness_pass:
            verdict_disagreements.append({"point": key_str(k), "row": "slew_rate", "harness": hv_worst,
                                          "tool_edge_status": edge_status, "bound": SLEW_BOUND_V_PER_US,
                                          "explained_by_tolerance": near})
        points.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                       "metrics": metrics, "integrity_checks": flag_out, "row": row})

    unexplained = [d for d in verdict_disagreements if not d["explained_by_tolerance"]]
    hvals = [(float(harness[k]["sr_worst_v_per_us"]), k) for k in expected_keys()]
    hw = min(hvals)
    summary = {"bound": {"min": SLEW_BOUND_V_PER_US},
               "harness_worst": {"point": key_str(hw[1]), "value": hw[0],
                                 "verdict": "pass" if hw[0] >= SLEW_BOUND_V_PER_US else "fail"}}
    if env is not None:
        summary["tool"] = {}
        for m in env.get("measurements") or []:
            if m.get("name") in EDGE_MEASUREMENTS:
                summary["tool"][m["name"]] = {"status": m.get("status"), "limits": m.get("limits"),
                                              "worst_case": m.get("worst_case")}
    return {
        "schema": "sg13g2-opamp/slew-rate/klt-compare/1",
        "points_compared": len(points),
        "tolerances": TOLERANCES,
        "method_check_rel": METHOD_CHECK_REL,
        "method_check_failures": method_failures,
        "out_of_tolerance": out_of_tol,
        "bound_verdict_disagreements": verdict_disagreements,
        "unexplained_bound_verdict_disagreements": len(unexplained),
        "row": summary,
        "points": points,
        "status": "agree" if not out_of_tol and not unexplained and not method_failures else "disagree",
    }


def _text_summary(rep: dict) -> str:
    r = rep["row"]
    hw = r["harness_worst"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}",
             f"  slew_rate bound {r['bound']}: harness worst {hw['point']} = {hw['value']:.6g} ({hw['verdict']})"]
    for n, e in (r.get("tool") or {}).items():
        wc = e.get("worst_case") or {}
        lines.append(f"    tool {n}: {e.get('status')} (worst {wc.get('corner_id')} = {wc.get('value')}, margin {wc.get('margin')})")
    for line in rep["method_check_failures"]:
        lines.append(f"  METHOD CHECK FAILS: {line}")
    return "\n".join(E.summary_tail(lines, rep))


def _run(a, tool: Dict[Key, Dict[str, object]], env: dict) -> dict:
    harness = load_harness_csv(a.harness_csv)
    methods = {k: method_check(os.path.join(a.harness_tran_dir, f"{key_str(k)}_tran.csv"),
                               float(harness[k]["vcm_v"])) for k in expected_keys()}
    return compare(tool, harness, methods, env)

def main(argv: Optional[List[str]] = None) -> int:
    return E.run_cli(
        argv, description=__doc__.split("\n\n")[0], compare_help="join the envelope with the harness record",
        harness_args=(("--harness-csv", {"required": True}),
                      ("--harness-tran-dir", {"required": True,
                                              "help": "the harness record's corners/<id>/ directory (raw *_tran.csv waveforms)"})),
        index_fn=index_envelope,
        run=_run,
        inputs=(("harness_csv", "harness_csv", True), ("harness_tran_dir", "harness_tran_dir", False)),
        summary=_text_summary)


if __name__ == "__main__":
    sys.exit(main())

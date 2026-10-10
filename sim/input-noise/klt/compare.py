#!/usr/bin/env python3
"""Compare the input-noise bench's `klt sim` envelope against the harness record.

Usage:

    compare.py validate <envelope.json>
    compare.py compare --envelope <noise.sim.json> --harness-csv <records/<id>.csv> \
        [--json-out <report.json>] [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator.

`validate` is the gate sim/input-noise/klt/run.sh applies to the envelope
before it is allowed into records/: exactly the 45-point ratified grid, one
corner per (process, temperature, VDD) point, Vcm = VDD/2 at every corner,
every declared measurement present and finite at every corner, the band
integrity measurements (81 points, 100 Hz .. 1 MHz, spot frequencies) at their
expected values, no corner `error` / `inconclusive`, and
`coverage.nothing_checked` false with nothing skipped. An envelope that fails
any of these is an incomplete run, not evidence.

`compare` joins the envelope and the harness record
(sim/input-noise/records/20260918-203850-90844d2.csv) on the full
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
(NOISE_BOUND_VRMS) is graded by `klt sim` itself; this script only reports
whether the two measurement paths agree, and whether they agree about the bound.

The tolerances here are PROVISIONAL: they are derived from DR-0005's
cross-host figure, not from a measured envelope (none exists yet). They must be
re-justified from the first real comparison before it is cited.
"""

from __future__ import annotations

import functools
import os
import sys
from typing import Dict, List, Optional, Tuple

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
# Everything noise.request.json reports. The integrated figure carries the
# ratified bound; the spot densities are unlimited values joined against the
# harness CSV; the band_* / spot_f_* measurements are tool-graded integrity
# checks (the harness asserts the same facts in run_noise_sweep.sh).
INTEGRATED = "inoise_int_vrms"
SPOTS = {  # envelope measurement -> harness CSV column
    "inoise_100hz_v_rthz": "vni_100hz_v_rthz",
    "inoise_1khz_v_rthz": "vni_1khz_v_rthz",
    "inoise_10khz_v_rthz": "vni_10khz_v_rthz",
    "inoise_100khz_v_rthz": "vni_100khz_v_rthz",
    "inoise_1mhz_v_rthz": "vni_1mhz_v_rthz",
}
BAND_CHECKS = ("band_points", "band_f_first_hz", "band_f_last_hz",
               "spot_f_1khz_hz", "spot_f_10khz_hz", "spot_f_100khz_hz")
# Expected values of the integrity measurements (the band is part of the number).
BAND_EXPECTED = {
    "band_points": 81.0, "band_f_first_hz": 100.0, "band_f_last_hz": 1e6,
    "spot_f_1khz_hz": 1e3, "spot_f_10khz_hz": 1e4, "spot_f_100khz_hz": 1e5,
}
BAND_REL_TOL = 1e-6
MEASUREMENTS = (INTEGRATED,) + tuple(SPOTS) + BAND_CHECKS

# The ratified row (spec/target-spec.md section 2, [DR-2]): input-referred
# noise <= 108.9 uVrms worst-case, integrated over 100 Hz - 1 MHz, CL = 2 pF.
# Copied here only to check that the two paths AGREE about the bound; the
# verdict of record is the envelope's.
NOISE_BOUND_VRMS = 108.9e-6
BAND_LO_HZ = 100.0
BAND_HI_HZ = 1e6

# ------------------------------------------------------------- tolerances
# Per-metric comparison tolerance: |tool - harness| <= abs + rel * |harness|.
#
# PROVISIONAL (no measured envelope yet; README.md "Comparison tolerance"):
#
# * Same circuit, same analysis, same ngspice default solver tolerance
#   (DR-0005). The harness record was produced on macOS/aarch64 ngspice-46;
#   the envelope is produced wherever `klt sim` runs it. DR-0005 measured a
#   9.9e-4 relative drain-current difference between that host and
#   Linux/x86_64 default-tolerance records of this PDK. Noise power follows
#   device bias currents/gm, so ~1e-3 relative is the cross-host allowance
#   carried over; 2e-3 is allowed (the figure doubled, as in sim/slew-rate/klt).
# * Measurement method: both paths read ngspice's own noise2.inoise_total and
#   noise1.inoise_spectrum[k] at identical frequencies (dec 20 from exactly
#   100 Hz); there is no waveform post-processing to differ. The harness CSV
#   prints 6 significant digits (<= 5e-6 relative quantisation).
# * These numbers are to be replaced by a measured justification once a real
#   envelope exists; until then a pass here is not evidence of agreement.
TOL_REL = 2e-3
TOLERANCES = {INTEGRATED: {"abs": 0.0, "rel": TOL_REL, "unit": "Vrms"}}
for _m in SPOTS:
    TOLERANCES[_m] = {"abs": 0.0, "rel": TOL_REL, "unit": "V/rtHz"}


# --------------------------------------------------------------- envelopes
def _check_band(k: Key, vals: Dict[str, object], problems: List[str]) -> None:
    """Per-corner hook: the band/spot integrity values and a positive integral."""
    for n, want in BAND_EXPECTED.items():
        if n in vals and abs(vals[n] - want) > BAND_REL_TOL * want:
            problems.append(f"{key_str(k)}: {n} = {vals[n]!r}, expected {want!r} (the band/spot grid is part of the number)")
    if INTEGRATED in vals and not vals[INTEGRATED] > 0:
        problems.append(f"{key_str(k)}: {INTEGRATED} = {vals[INTEGRATED]!r} is not positive")


def index_envelope(env: dict, label: str = "envelope") -> Dict[Key, Dict[str, object]]:
    """The shared envelope gate (klt_envelope.index_envelope) plus _check_band."""
    return E.index_envelope(env, label, MEASUREMENTS, corner_check=_check_band)


# ----------------------------------------------------------------- harness
HARNESS_COLUMNS = ("vcm_v", "vni_int_vrms") + tuple(SPOTS.values())


def load_harness_csv(path: str) -> Dict[Key, Dict[str, object]]:
    return E.load_harness_csv_rows(path, HARNESS_COLUMNS, "harness CSV")


# ----------------------------------------------------------------- compare
_tol = functools.partial(E.tol, TOLERANCES)


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
        pairs = {INTEGRATED: (t[INTEGRATED], float(h["vni_int_vrms"]))}
        for m, col in SPOTS.items():
            pairs[m] = (t[m], float(h[col]))
        metrics = {}
        for m, (tv, hv) in pairs.items():
            tol = _tol(m, hv)
            delta = tv - hv
            entry = {"harness": hv, "tool": tv, "delta": delta,
                     "rel_delta": delta / hv if hv else None, "tolerance": tol,
                     "unit": TOLERANCES[m]["unit"], "within": abs(delta) <= tol}
            if not entry["within"]:
                out_of_tol.append(f"{key_str(k)} {m}: tool {tv:.9g} vs harness {hv:.9g} "
                                  f"(delta {delta:.3g} {TOLERANCES[m]['unit']}, tolerance {tol:.3g})")
            metrics[m] = entry

        # Ratified row: the tool's own verdict on the integrated figure vs the
        # bound applied to the harness value. A bound miss stays a miss.
        tool_pass = t.get(INTEGRATED + "__status") == "pass"
        hv_int = float(h["vni_int_vrms"])
        harness_pass = hv_int <= NOISE_BOUND_VRMS
        near = abs(hv_int - NOISE_BOUND_VRMS) <= _tol(INTEGRATED, hv_int)
        row = {"tool_status": t.get(INTEGRATED + "__status"), "tool_pass": tool_pass,
               "harness_pass": harness_pass, "agree": tool_pass == harness_pass,
               "harness_within_tolerance_of_bound": near}
        if tool_pass != harness_pass:
            verdict_disagreements.append({"point": key_str(k), "row": "input_referred_noise", "harness": hv_int,
                                          "tool_status": t.get(INTEGRATED + "__status"),
                                          "bound": NOISE_BOUND_VRMS, "explained_by_tolerance": near})
        points.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                       "metrics": metrics, "row": row})

    unexplained = [d for d in verdict_disagreements if not d["explained_by_tolerance"]]
    hw = max((float(harness[k]["vni_int_vrms"]), k) for k in expected_keys())
    summary = {"bound": {"max": NOISE_BOUND_VRMS, "band_hz": [BAND_LO_HZ, BAND_HI_HZ]},
               "harness_worst": {"point": key_str(hw[1]), "value": hw[0],
                                 "verdict": "pass" if hw[0] <= NOISE_BOUND_VRMS else "fail"}}
    if env is not None:
        summary["tool"] = {}
        for m in env.get("measurements") or []:
            if m.get("name") == INTEGRATED:
                summary["tool"][m["name"]] = {"status": m.get("status"), "limits": m.get("limits"),
                                              "worst_case": m.get("worst_case")}
    return {
        "schema": "sg13g2-opamp/input-noise/klt-compare/1",
        "points_compared": len(points),
        "tolerances": TOLERANCES,
        "tolerances_provisional": True,
        "not_compared": ["op_pass / clgain_* (need a second analysis per corner; klt sim runs one)",
                         "flicker/thermal split and crosscheck columns (derived by the harness from the written spectrum)"],
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
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']} (tolerances provisional)",
             f"  input_referred_noise bound {r['bound']}: harness worst {hw['point']} = {hw['value']:.6g} ({hw['verdict']})"]
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

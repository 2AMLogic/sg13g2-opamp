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

import argparse
import csv
import hashlib
import json
import math
import sys
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------- the grid
# spec/target-spec.md section 1 [DR-1]/[DR-2]: cornerMOSlv.lib's five
# sections x {-40, 27, 125} C x {1.08, 1.20, 1.32} V.
PROCESSES = ("mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs")
TEMPERATURES = (-40, 27, 125)
SUPPLIES = (1.08, 1.20, 1.32)

Key = Tuple[str, int, float]


def expected_keys() -> List[Key]:
    return [(p, t, v) for p in PROCESSES for t in TEMPERATURES for v in SUPPLIES]


def make_key(process: str, temp, vdd) -> Key:
    return (str(process), int(round(float(temp))), round(float(vdd), 3))


def key_str(k: Key) -> str:
    """The harness's own point_id spelling, e.g. mos_fs_125C_1.08V."""
    return f"{k[0]}_{k[1]}C_{k[2]:.2f}V"


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


class InputError(Exception):
    """Inputs cannot be compared at all (exit 2)."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# --------------------------------------------------------------- envelopes
def load_envelope(path: str) -> Tuple[dict, Dict[Key, Dict[str, object]]]:
    """Validate the `klt sim` envelope and index its corners by grid key."""
    try:
        with open(path) as f:
            env = json.load(f)
    except (OSError, ValueError) as e:
        raise InputError(f"{path}: unreadable envelope ({e})")
    return env, index_envelope(env, path)


def index_envelope(env: dict, label: str = "envelope") -> Dict[Key, Dict[str, object]]:
    if not isinstance(env, dict):
        raise InputError(f"{label}: not a JSON object")
    if "error" in env:
        raise InputError(f"{label}: klt error envelope: {env['error']}")
    corners = env.get("corners")
    if not isinstance(corners, list):
        raise InputError(f"{label}: no corners[] array")
    if env.get("corner_count") != len(corners):
        raise InputError(f"{label}: corner_count {env.get('corner_count')} != len(corners) {len(corners)}")
    cov = env.get("coverage")
    if not isinstance(cov, dict):
        raise InputError(f"{label}: no coverage block")
    if cov.get("nothing_checked") is not False:
        raise InputError(f"{label}: coverage.nothing_checked is {cov.get('nothing_checked')!r}, expected false")
    if cov.get("skipped"):
        raise InputError(f"{label}: coverage.skipped is non-empty ({len(cov['skipped'])} item(s)), e.g. {cov['skipped'][0]}")
    if env.get("status") not in ("pass", "fail"):
        raise InputError(f"{label}: aggregate status {env.get('status')!r} -- only a complete pass/fail run is evidence")

    out: Dict[Key, Dict[str, object]] = {}
    problems: List[str] = []
    for c in corners:
        cid = c.get("corner_id")
        supply = c.get("supply_v") or {}
        if "vdd" not in supply or "vinp" not in supply or c.get("process") is None:
            problems.append(f"{cid}: missing process or supply_v.vdd/vinp")
            continue
        k = make_key(c["process"], c.get("temperature_c"), supply["vdd"])
        if k in out:
            problems.append(f"{key_str(k)}: duplicate corner")
            continue
        if not math.isclose(float(supply["vinp"]), float(supply["vdd"]) / 2, rel_tol=0, abs_tol=1e-9):
            problems.append(f"{key_str(k)}: vinp {supply['vinp']} != vdd/2 ({supply['vdd']}/2)")
        if c.get("status") not in ("pass", "fail"):
            problems.append(f"{key_str(k)}: corner status {c.get('status')!r}")
        vals: Dict[str, object] = {}
        by_name = {}
        for m in c.get("measurements") or []:
            if m.get("name") in by_name:
                problems.append(f"{key_str(k)}: measurement {m.get('name')} reported twice")
            by_name[m.get("name")] = m
        for n in MEASUREMENTS:
            m = by_name.get(n)
            if m is None:
                problems.append(f"{key_str(k)}: measurement {n} missing")
                continue
            if not _finite(m.get("value")):
                problems.append(f"{key_str(k)}: measurement {n} value {m.get('value')!r} is missing or non-finite")
                continue
            vals[n] = float(m["value"])
            vals[n + "__status"] = m.get("status")
        for n, want in BAND_EXPECTED.items():
            if n in vals and abs(vals[n] - want) > BAND_REL_TOL * want:
                problems.append(f"{key_str(k)}: {n} = {vals[n]!r}, expected {want!r} (the band/spot grid is part of the number)")
        if INTEGRATED in vals and not vals[INTEGRATED] > 0:
            problems.append(f"{key_str(k)}: {INTEGRATED} = {vals[INTEGRATED]!r} is not positive")
        out[k] = vals
    _check_grid(out.keys(), label, problems)
    if problems:
        raise InputError(f"{label}: " + "; ".join(problems))
    return out


def _check_grid(keys: Iterable[Key], label: str, problems: List[str]) -> None:
    got = set(keys)
    want = set(expected_keys())
    for k in sorted(want - got):
        problems.append(f"{key_str(k)}: missing from {label}")
    for k in sorted(got - want):
        problems.append(f"{key_str(k)}: not a point of the ratified grid")


# ----------------------------------------------------------------- harness
HARNESS_COLUMNS = ("vcm_v", "vni_int_vrms") + tuple(SPOTS.values())


def load_harness_csv(path: str) -> Dict[Key, Dict[str, object]]:
    out: Dict[Key, Dict[str, object]] = {}
    problems: List[str] = []
    try:
        f = open(path, newline="")
    except OSError as e:
        raise InputError(f"{path}: {e}")
    with f:
        for r in csv.DictReader(f):
            k = make_key(r["corner"], r["temp_c"], r["vdd_v"])
            if k in out:
                problems.append(f"{key_str(k)}: duplicate row")
                continue
            if r.get("point_id") != key_str(k):
                problems.append(f"{r.get('point_id')}: point_id disagrees with its corner/temp/vdd columns")
            row: Dict[str, object] = {}
            for col in HARNESS_COLUMNS:
                raw = r.get(col)
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    v = float("nan")
                if not math.isfinite(v):
                    problems.append(f"{key_str(k)}: harness {col} {raw!r} is missing or non-finite")
                row[col] = v
            out[k] = row
    _check_grid(out.keys(), "harness CSV", problems)
    if problems:
        raise InputError(f"{path}: " + "; ".join(problems))
    return out


# ----------------------------------------------------------------- compare
def _tol(metric: str, ref: float) -> float:
    t = TOLERANCES[metric]
    return t["abs"] + t["rel"] * abs(ref)


def compare(tool: Dict[Key, Dict[str, object]], harness: Dict[Key, Dict[str, object]],
            env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for label, d in (("envelope", tool), ("harness CSV", harness)):
        _check_grid(d.keys(), label, problems)
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


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _text_summary(rep: dict) -> str:
    r = rep["row"]
    hw = r["harness_worst"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']} (tolerances provisional)",
             f"  input_referred_noise bound {r['bound']}: harness worst {hw['point']} = {hw['value']:.6g} ({hw['verdict']})"]
    for n, e in (r.get("tool") or {}).items():
        wc = e.get("worst_case") or {}
        lines.append(f"    tool {n}: {e.get('status')} (worst {wc.get('corner_id')} = {wc.get('value')}, margin {wc.get('margin')})")
    for line in rep["out_of_tolerance"]:
        lines.append(f"  OUT OF TOLERANCE: {line}")
    for d in rep["bound_verdict_disagreements"]:
        lines.append(f"  VERDICT DISAGREES: {d}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="gate the envelope before it may enter records/")
    v.add_argument("envelope")
    c = sub.add_parser("compare", help="join the envelope with the harness record")
    c.add_argument("--envelope", required=True)
    c.add_argument("--harness-csv", required=True)
    c.add_argument("--json-out")
    c.add_argument("--provenance", action="append", default=[], metavar="KEY=VALUE")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "validate":
            env, idx = load_envelope(a.envelope)
            print(f"validate: {a.envelope}: {len(idx)} corners, status {env.get('status')}, ok")
            return 0
        env, tool = load_envelope(a.envelope)
        harness = load_harness_csv(a.harness_csv)
        rep = compare(tool, harness, env)
    except InputError as e:
        print(f"compare.py: {e}", file=sys.stderr)
        return 2

    rep["inputs"] = {"envelope": {"path": a.envelope, "sha256": _sha256(a.envelope)},
                     "harness_csv": {"path": a.harness_csv, "sha256": _sha256(a.harness_csv)}}
    rep["provenance"] = dict(kv.split("=", 1) for kv in a.provenance)
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(rep, f, indent=2)
            f.write("\n")
    print(_text_summary(rep))
    return 0 if rep["status"] == "agree" else 1


if __name__ == "__main__":
    sys.exit(main())

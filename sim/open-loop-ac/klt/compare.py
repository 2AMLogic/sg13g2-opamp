#!/usr/bin/env python3
"""Compare the open-loop AC bench's `klt sim` envelopes against the harness record.

Usage:

    compare.py validate --kind {ac,op} <envelope.json>
    compare.py compare --ac <ac.sim.json> --op <op.sim.json> \
        --harness-csv <records/<id>.csv> --harness-ac-dir <corners/<id>/> \
        [--json-out <report.json>] [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator.

`validate` is the gate sim/open-loop-ac/klt/run.sh applies to each envelope
before it is allowed into records/: exactly the 45-point ratified grid, one
corner per (process, temperature, VDD) point, Vcm = VDD/2 at every corner,
every declared measurement present and finite at every corner, no corner
`error`/`inconclusive`, and `coverage.nothing_checked` false with nothing
skipped. An envelope that fails any of these is an incomplete run, not
evidence.

`compare` joins the AC envelope, the OP envelope and the harness record
(sim/open-loop-ac/records/20260910-221601-22feaba.csv) on the full
(process, temperature, VDD) key, refuses anything but the same 45 unique
points on all three sides, and reports per corner and per metric the
difference against a stated tolerance (TOLERANCES below). Exit status:

    0  every comparison within tolerance and every bound verdict agrees
    1  at least one comparison outside tolerance, or a bound verdict that
       disagrees without being explained by the tolerance (report still
       written -- an out-of-tolerance point is reported, never hidden)
    2  inputs unusable: missing/duplicate/extra points, missing or
       non-finite measurements, malformed envelope

Comparison tolerances never touch a pass/fail limit. The ratified bounds
(BOUNDS) are graded by `klt sim` itself; this script only reports whether
the two measurement paths agree, and whether they agree about each bound.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
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
AC_MEASUREMENTS = ("av0_db", "gbw_hz", "phase_at_ugf_rad")
OP_MEASUREMENTS = (
    "ivdd_total_a",
    "vout_dc_v",
    "vd1_dc_v",
    "vd2_dc_v",
    "vtail_dc_v",
    "vibias_dc_v",
    "op_vcm_frac",
    "op_vout_offset_frac",
    "op_vout_rail_frac",
    "op_vd1_rail_frac",
    "op_vd2_rail_frac",
    "op_vtail_rail_frac",
)
OP_SANITY = tuple(m for m in OP_MEASUREMENTS if m.startswith("op_"))
KIND_MEASUREMENTS = {"ac": AC_MEASUREMENTS, "op": OP_MEASUREMENTS}

# The four ratified rows this bench carries (spec/target-spec.md section 2,
# [DR-2]). Copied here only to check that the two paths AGREE about each
# bound; the verdict of record is the envelope's own.
#   row name -> (harness CSV column, comparison metric, "min"/"max", bound)
BOUNDS = {
    "open_loop_dc_gain": ("av0_db", "av0_db", "min", 37.8),
    "gbw": ("gbw_hz", "gbw_hz", "min", 4.74e6),
    "phase_margin": ("pm_deg", "pm_deg", "min", 60.0),
    "quiescent_current": ("ivdd_total_a", "ivdd_total_a", "max", 119.7e-6),
}

# Envelope measurement that carries each row's tool verdict.
ROW_TOOL_MEASUREMENT = {
    "open_loop_dc_gain": ("ac", "av0_db"),
    "gbw": ("ac", "gbw_hz"),
    "phase_margin": ("ac", "phase_at_ugf_rad"),
    "quiescent_current": ("op", "ivdd_total_a"),
}

# ------------------------------------------------------------- tolerances
# Per-metric comparison tolerance: |tool - harness| <= abs + rel * |harness|.
#
# Basis (README.md "Comparison tolerance" carries the full argument):
#
# * Both paths solve the same circuit at ngspice's DEFAULT solver tolerance
#   (DR-0005: no reltol/abstol/vntol override anywhere in sim/). The solver
#   accepts a DC solution once successive iterates agree to reltol = 1e-3
#   relative (vntol = 1 uV absolute on node voltages), so two hosts' default
#   solves of one circuit may legitimately differ by up to ~1e-3 relative in
#   any DC quantity. DR-0005 measured exactly that magnitude cross-host on
#   this PDK: drain current 9.9e-04 relative between the macOS/aarch64 and
#   Linux/x86_64 default-tolerance gm/ID records. The harness record was
#   produced on macOS/aarch64 ngspice-46; the envelope is produced wherever
#   `klt sim` runs it.
# * The harness CSV prints 6 significant figures (%.6g); ngspice prints the
#   DC node voltages it echoes to 6-7. Quantisation is <= 5e-6 relative, two
#   decades below the solver term, so it is absorbed by it.
# * Propagation to the small-signal rows: Av0 is a product of two stage
#   gains, each a gm/gds ratio of DC-biased devices, so a 1e-3 relative
#   current error moves it by at most ~2e-3 relative -> 20*log10(1.002) =
#   0.017 dB, rounded up to 0.02 dB. GBW (~gm1/Cc) moves ~1e-3; 2e-3 is
#   allowed. Phase margin is set by the ratio of the second pole to GBW; a
#   2e-3 relative shift in that ratio moves PM by ~0.03 deg at this design's
#   ~77 deg; 0.1 deg is allowed.
# * GBW ALSO differs by measurement method, and that part is not a
#   tolerance: ngspice's `.meas ... WHEN vdb(out)=0` interpolates the
#   crossing linearly in FREQUENCY between the two bracketing sweep points;
#   run_pvt_sweep.sh interpolates linearly in log10(frequency) with the same
#   bracketing fraction. The tool value is therefore larger by a one-signed
#   factor that depends only on that fraction (0 <= bias <= 1.657e-3 at 20
#   points/decade). compare.py recomputes that factor per corner from the
#   harness's own committed raw AC sweep (corners/<id>/<point>_ac.csv) and
#   compares against the method-corrected harness value, so the 2e-3 GBW
#   tolerance covers only the solver term. The uncorrected difference is
#   reported alongside it.
# * Phase at the crossing uses the same bracketing fraction in both paths
#   (linear interpolation in the sweep index), so PM has no method term.
TOLERANCES = {
    "av0_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "gbw_hz": {"abs": 0.0, "rel": 2e-3, "unit": "Hz"},
    "pm_deg": {"abs": 0.1, "rel": 0.0, "unit": "deg"},
    "ivdd_total_a": {"abs": 0.0, "rel": 1e-3, "unit": "A"},
    "vout_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vd1_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vd2_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vtail_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
    "vibias_dc_v": {"abs": 1e-6, "rel": 1e-3, "unit": "V"},
}

GBW_METHOD_BIAS_MAX = (1 + 10 ** (1 / 20)) / 2 / math.sqrt(10 ** (1 / 20)) - 1


class InputError(Exception):
    """Inputs cannot be compared at all (exit 2)."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# --------------------------------------------------------------- envelopes
def load_envelope(path: str, kind: str) -> Tuple[dict, Dict[Key, Dict[str, float]]]:
    """Validate one `klt sim` envelope and index its corners by grid key."""
    try:
        with open(path) as f:
            env = json.load(f)
    except (OSError, ValueError) as e:
        raise InputError(f"{path}: unreadable envelope ({e})")
    return env, index_envelope(env, kind, path)


def index_envelope(env: dict, kind: str, label: str = "envelope") -> Dict[Key, Dict[str, float]]:
    names = KIND_MEASUREMENTS[kind]
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

    out: Dict[Key, Dict[str, float]] = {}
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
        vals: Dict[str, float] = {}
        by_name = {}
        for m in c.get("measurements") or []:
            if m.get("name") in by_name:
                problems.append(f"{key_str(k)}: measurement {m.get('name')} reported twice")
            by_name[m.get("name")] = m
        for n in names:
            m = by_name.get(n)
            if m is None:
                problems.append(f"{key_str(k)}: measurement {n} missing")
                continue
            if not _finite(m.get("value")):
                problems.append(f"{key_str(k)}: measurement {n} value {m.get('value')!r} is missing or non-finite")
                continue
            vals[n] = float(m["value"])
            vals[n + "__status"] = m.get("status")
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
HARNESS_COLUMNS = ("av0_db", "gbw_hz", "pm_deg", "ivdd_total_a", "vout_dc_v",
                   "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v", "op_pass")


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
                if col == "op_pass":
                    row[col] = raw
                    continue
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


def gbw_method_bias(ac_csv: str) -> float:
    """tool/harness GBW ratio minus 1 for one point, from the raw AC sweep.

    Reproduces run_pvt_sweep.sh's bracketing exactly (first point pair with
    dB[i-1] >= 0 > dB[i]); returns f_lin/f_log - 1 at that fraction.
    """
    freqs: List[float] = []
    dbs: List[float] = []
    with open(ac_csv) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 4:
                continue
            freqs.append(float(parts[0]))
            dbs.append(float(parts[1]))
    for i in range(1, len(dbs)):
        if dbs[i - 1] >= 0.0 > dbs[i]:
            frac = dbs[i - 1] / (dbs[i - 1] - dbs[i])
            f0, f1 = freqs[i - 1], freqs[i]
            f_lin = f0 + frac * (f1 - f0)
            f_log = 10 ** (math.log10(f0) + frac * (math.log10(f1) - math.log10(f0)))
            return f_lin / f_log - 1.0
    raise InputError(f"{ac_csv}: no 0 dB crossing in the raw sweep")


# ----------------------------------------------------------------- compare
def _tol(metric: str, ref: float) -> float:
    t = TOLERANCES[metric]
    return t["abs"] + t["rel"] * abs(ref)


def _passes(value: float, kind: str, bound: float) -> bool:
    return value >= bound if kind == "min" else value <= bound


def compare(ac: Dict[Key, Dict[str, float]], op: Dict[Key, Dict[str, float]],
            harness: Dict[Key, Dict[str, object]],
            gbw_bias: Optional[Dict[Key, float]] = None,
            ac_env: Optional[dict] = None, op_env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for label, d in (("ac envelope", ac), ("op envelope", op), ("harness CSV", harness)):
        _check_grid(d.keys(), label, problems)
    if problems:
        raise InputError("; ".join(problems))

    points = []
    out_of_tol: List[str] = []
    verdict_disagreements: List[dict] = []
    for k in expected_keys():
        h = harness[k]
        tool = {
            "av0_db": ac[k]["av0_db"],
            "gbw_hz": ac[k]["gbw_hz"],
            "pm_deg": 180.0 + math.degrees(ac[k]["phase_at_ugf_rad"]),
            "ivdd_total_a": op[k]["ivdd_total_a"],
            "vout_dc_v": op[k]["vout_dc_v"],
            "vd1_dc_v": op[k]["vd1_dc_v"],
            "vd2_dc_v": op[k]["vd2_dc_v"],
            "vtail_dc_v": op[k]["vtail_dc_v"],
            "vibias_dc_v": op[k]["vibias_dc_v"],
        }
        metrics = {}
        for m, tv in tool.items():
            hv = float(h[m])
            ref = hv
            entry = {"harness": hv, "tool": tv}
            if m == "gbw_hz" and gbw_bias is not None:
                b = gbw_bias[k]
                ref = hv * (1.0 + b)
                entry["method_bias"] = b
                entry["harness_method_corrected"] = ref
                entry["delta_uncorrected"] = tv - hv
                entry["rel_delta_uncorrected"] = (tv - hv) / hv
            tol = _tol(m, ref)
            delta = tv - ref
            entry.update({
                "delta": delta,
                "rel_delta": delta / ref if ref else None,
                "tolerance": tol,
                "unit": TOLERANCES[m]["unit"],
                "within": abs(delta) <= tol,
            })
            if not entry["within"]:
                out_of_tol.append(f"{key_str(k)} {m}: tool {tv:.9g} vs harness {ref:.9g} "
                                  f"(delta {delta:.3g} {TOLERANCES[m]['unit']}, tolerance {tol:.3g})")
            metrics[m] = entry

        tool_op_pass = all(op[k].get(n + "__status") == "pass" for n in OP_SANITY)
        harness_op_pass = str(h["op_pass"]).strip() == "1"
        op_sanity = {"harness_op_pass": harness_op_pass, "tool_op_sanity_pass": tool_op_pass,
                     "agree": harness_op_pass == tool_op_pass}
        if not op_sanity["agree"]:
            out_of_tol.append(f"{key_str(k)} op sanity: harness op_pass={h['op_pass']} vs tool sanity "
                              f"{'pass' if tool_op_pass else 'fail'}")

        rows = {}
        for row, (hcol, metric, kind, bound) in BOUNDS.items():
            env_kind, env_name = ROW_TOOL_MEASUREMENT[row]
            src = ac if env_kind == "ac" else op
            tool_status = src[k].get(env_name + "__status")
            hv = float(h[hcol])
            harness_pass = _passes(hv, kind, bound)
            tool_pass = tool_status == "pass"
            near = abs(hv - bound) <= _tol(metric, hv) + (abs(hv) * GBW_METHOD_BIAS_MAX if metric == "gbw_hz" else 0)
            rows[row] = {"tool_status": tool_status, "harness_pass": harness_pass,
                         "agree": harness_pass == tool_pass, "harness_within_tolerance_of_bound": near}
            if harness_pass != tool_pass:
                verdict_disagreements.append({"point": key_str(k), "row": row, "harness": hv,
                                              "tool_status": tool_status, "bound": bound,
                                              "explained_by_tolerance": near})
        points.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                       "metrics": metrics, "op_sanity": op_sanity, "rows": rows})

    unexplained = [d for d in verdict_disagreements if not d["explained_by_tolerance"]]
    summary_rows = {}
    for row, (hcol, metric, kind, bound) in BOUNDS.items():
        env_kind, env_name = ROW_TOOL_MEASUREMENT[row]
        hvals = [(float(harness[k][hcol]), k) for k in expected_keys()]
        hw = min(hvals) if kind == "min" else max(hvals)
        entry = {"bound": {kind: bound}, "harness_worst": {"point": key_str(hw[1]), "value": hw[0],
                                                           "verdict": "pass" if _passes(hw[0], kind, bound) else "fail"}}
        env = ac_env if env_kind == "ac" else op_env
        if env is not None:
            for m in env.get("measurements") or []:
                if m.get("name") == env_name:
                    entry["tool"] = {"measurement": env_name, "status": m.get("status"),
                                     "limits": m.get("limits"), "worst_case": m.get("worst_case")}
        summary_rows[row] = entry

    return {
        "schema": "sg13g2-opamp/open-loop-ac/klt-compare/1",
        "points_compared": len(points),
        "tolerances": TOLERANCES,
        "gbw_method_bias_bound": GBW_METHOD_BIAS_MAX,
        "out_of_tolerance": out_of_tol,
        "bound_verdict_disagreements": verdict_disagreements,
        "unexplained_bound_verdict_disagreements": len(unexplained),
        "rows": summary_rows,
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
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}"]
    for row, e in rep["rows"].items():
        hw = e["harness_worst"]
        t = e.get("tool", {})
        wc = t.get("worst_case") or {}
        lines.append(f"  {row:18s} bound {e['bound']}: tool {t.get('status')} "
                     f"(worst {wc.get('corner_id')} = {wc.get('value')}, margin {wc.get('margin')}); "
                     f"harness worst {hw['point']} = {hw['value']:.6g} ({hw['verdict']})")
    for line in rep["out_of_tolerance"]:
        lines.append(f"  OUT OF TOLERANCE: {line}")
    for d in rep["bound_verdict_disagreements"]:
        lines.append(f"  VERDICT DISAGREES: {d}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="gate one envelope before it may enter records/")
    v.add_argument("--kind", choices=("ac", "op"), required=True)
    v.add_argument("envelope")
    c = sub.add_parser("compare", help="join both envelopes with the harness record")
    c.add_argument("--ac", required=True)
    c.add_argument("--op", required=True)
    c.add_argument("--harness-csv", required=True)
    c.add_argument("--harness-ac-dir", required=True,
                   help="the harness record's corners/<id>/ directory (raw *_ac.csv sweeps)")
    c.add_argument("--json-out")
    c.add_argument("--provenance", action="append", default=[], metavar="KEY=VALUE")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "validate":
            env, idx = load_envelope(a.envelope, a.kind)
            print(f"validate: {a.envelope}: {len(idx)} corners, status {env.get('status')}, ok")
            return 0
        ac_env, ac = load_envelope(a.ac, "ac")
        op_env, op = load_envelope(a.op, "op")
        harness = load_harness_csv(a.harness_csv)
        bias = {k: gbw_method_bias(os.path.join(a.harness_ac_dir, f"{key_str(k)}_ac.csv"))
                for k in expected_keys()}
        rep = compare(ac, op, harness, bias, ac_env, op_env)
    except InputError as e:
        print(f"compare.py: {e}", file=sys.stderr)
        return 2

    if a.cmd == "compare":
        rep["inputs"] = {name: {"path": p, "sha256": _sha256(p)} for name, p in
                         (("ac_envelope", a.ac), ("op_envelope", a.op), ("harness_csv", a.harness_csv))}
        rep["inputs"]["harness_ac_dir"] = {"path": a.harness_ac_dir}
        rep["provenance"] = dict(kv.split("=", 1) for kv in a.provenance)
        if a.json_out:
            with open(a.json_out, "w") as f:
                json.dump(rep, f, indent=2)
                f.write("\n")
        print(_text_summary(rep))
    return 0 if rep["status"] == "agree" else 1


if __name__ == "__main__":
    sys.exit(main())

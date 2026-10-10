#!/usr/bin/env python3
"""Compare the PSRR supply-gain `klt sim` envelope against the harness record.

Usage:

    compare.py validate <envelope.json>
    compare.py compare --envelope <psrr.sim.json> --harness-csv <cmrr-psrr record.csv> \
        --openloop-csv <open-loop-ac record.csv> [--json-out <report.json>] \
        [--provenance key=value ...]

Offline and stdlib-only: it reads committed files and runs no simulator.

What the envelope is, and is not. psrr.request.json measures ONE excitation: the
supply-to-output gain Avs (Vdd carries `ac 1`). PSRR = Av0 - Avs0 (dB) also
needs the differential gain Av0 of the same point, a different excitation that
one AC solve cannot carry. `compare` therefore joins the same-point Av0 from the
committed open-loop HARNESS record (not a `klt sim` Av0 envelope) on the full
(process, temperature, VDD) key and applies the ratified bound offline. That
PSRR verdict is this script's, not `klt sim`'s: the only limit the tool grades
is the harness's flat-shelf plateau guard.

`validate` is the gate sim/cmrr-psrr/klt/run.sh applies before an envelope may
enter records/: exactly the 45-point ratified grid, one corner per (process,
temperature, VDD), Vcm = VDD/2 at every corner, every declared measurement
present and finite once, no corner `error` / `inconclusive`, and
`coverage.nothing_checked` false with nothing skipped. A bound miss is NOT a
validation failure: a miss is a result.

`compare` refuses anything but the same 45 unique points on all three inputs,
fails closed if the same-point Av0 or Avs is absent or non-finite, and reports
per point and metric the difference against a stated tolerance (TOLERANCES).
Exit status:

    0  every comparison within tolerance and every verdict agrees
    1  at least one comparison outside tolerance, or a verdict that disagrees
       without being explained by the tolerance (report still written)
    2  inputs unusable: missing/duplicate/extra points, missing or non-finite
       values, malformed envelope
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from typing import Dict, Iterable, List, Optional, Tuple

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


# Everything psrr.request.json reports.
MEASUREMENTS = ("avs0_db", "avs_plateau_db", "avs_plateau_delta_db", "avs_1khz_db")

# Ratified row (spec/target-spec.md section 2, [DR-2]): PSRR+ >= 1.87 dB
# worst-case, DC shelf. Copied only so this script can apply it to the joined
# value; the spec is the source of truth.
PSRR_BOUND_DB = 1.87
# The harness's flat-shelf guard, which the request carries as its one limit.
PLATEAU_LIMIT_DB = 0.05

# Per-metric tolerance: |tool - harness| <= abs + rel * |harness|.
#
# Basis (README.md "The `klt sim` path" has the argument):
# * Same circuit, same sweep, same ngspice default tolerance (DR-0005). DR-0005
#   measured a 9.9e-4 relative drain-current difference between the harness
#   host (macOS/aarch64 ngspice-46) and Linux/x86_64. A gain moves at most about
#   2x that relative amount: 20*log10(1 + 2e-3) = 0.017 dB, rounded up to 0.02 dB.
# * Measurement method: both paths read vdb(out) at 10 mHz / 0.1 Hz / 1 kHz of the
#   same `ac dec 20 10m 1g` sweep (ngspice `.meas find ... at=` interpolates in
#   the swept grid; the harness reads the wrdata sample). The one-corner
#   prototype on this host agreed with the CSV to its 6 significant digits.
#   MEASURED (records/20261010-094256-469573d.compare.json, real 45-point
#   fleet envelope): the largest |tool - harness| is 4.96e-5 dB on avs0_db/psrr_db,
#   4.93e-5 dB on avs_1khz_db and 8.8e-8 dB on the plateau delta, i.e. the harness
#   CSV's own print precision. The tolerances below are kept at their argued,
#   conservative values (about 400x the measured spread); they never touch a
#   pass/fail limit.
# * The plateau delta is a difference of two nearly equal numbers: 0.005 dB abs.
# * psrr_db = av0 - avs0 where av0 is the SAME committed number on both sides, so
#   it carries the avs0 tolerance exactly.
TOLERANCES = {
    "avs0_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "avs_1khz_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "avs_plateau_delta_db": {"abs": 0.005, "rel": 0.0, "unit": "dB"},
    "psrr_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "psrr_1khz_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
}


class InputError(Exception):
    """Inputs cannot be compared at all (exit 2)."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# --------------------------------------------------------------- envelopes
def load_envelope(path: str) -> Tuple[dict, Dict[Key, Dict[str, object]]]:
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
        by_name: Dict[object, dict] = {}
        for m in c.get("measurements") or []:
            if m.get("name") in by_name:
                problems.append(f"{key_str(k)}: measurement {m.get('name')} reported twice")
            by_name[m.get("name")] = m
        for n in MEASUREMENTS:
            m = by_name.get(n)
            if m is None:
                problems.append(f"{key_str(k)}: measurement {n} missing")
                continue
            if m.get("status") in ("skipped", "error", "inconclusive", "not_checked"):
                problems.append(f"{key_str(k)}: measurement {n} status {m.get('status')!r}")
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


# ------------------------------------------------------------- CSV records
def _load_csv(path: str, columns: Iterable[str], label: str) -> Dict[Key, Dict[str, float]]:
    out: Dict[Key, Dict[str, float]] = {}
    problems: List[str] = []
    try:
        f = open(path, newline="")
    except OSError as e:
        raise InputError(f"{path}: {e}")
    with f:
        for r in csv.DictReader(f):
            try:
                k = make_key(r["corner"], r["temp_c"], r["vdd_v"])
            except (KeyError, TypeError, ValueError):
                problems.append(f"unparsable row {r!r}")
                continue
            if k in out:
                problems.append(f"{key_str(k)}: duplicate row")
                continue
            if r.get("point_id") != key_str(k):
                problems.append(f"{r.get('point_id')}: point_id disagrees with its corner/temp/vdd columns")
            row: Dict[str, float] = {}
            for col in columns:
                raw = r.get(col)
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    v = float("nan")
                if not math.isfinite(v):
                    problems.append(f"{key_str(k)}: {label} {col} {raw!r} is missing or non-finite")
                row[col] = v
            out[k] = row
    _check_grid(out.keys(), label, problems)
    if problems:
        raise InputError(f"{path}: " + "; ".join(problems))
    return out


def load_harness_csv(path: str) -> Dict[Key, Dict[str, float]]:
    """sim/cmrr-psrr/records/<id>.csv (the PSRR columns)."""
    return _load_csv(path, ("av0_db", "avs0_db", "avs_1khz_db", "psrr_db", "psrr_1khz_db",
                            "psrr_plateau_delta_db"), "harness CSV")


def load_openloop_csv(path: str) -> Dict[Key, Dict[str, float]]:
    """sim/open-loop-ac/records/<id>.csv (the same-point Av0)."""
    return _load_csv(path, ("av0_db",), "open-loop CSV")


# ----------------------------------------------------------------- compare
def _tol(metric: str, ref: float) -> float:
    t = TOLERANCES[metric]
    return t["abs"] + t["rel"] * abs(ref)


def compare(tool: Dict[Key, Dict[str, object]], harness: Dict[Key, Dict[str, float]],
            openloop: Dict[Key, Dict[str, float]], env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for label, d in (("envelope", tool), ("harness CSV", harness), ("open-loop CSV", openloop)):
        _check_grid(d.keys(), label, problems)
    for k in expected_keys():
        if k in tool:
            for n in ("avs0_db", "avs_1khz_db", "avs_plateau_delta_db"):
                if not _finite(tool[k].get(n)):
                    problems.append(f"{key_str(k)}: tool {n} absent or non-finite")
        if k in openloop and not _finite(openloop[k].get("av0_db")):
            problems.append(f"{key_str(k)}: same-point Av0 absent or non-finite")
    if problems:
        raise InputError("; ".join(problems))

    points = []
    out_of_tol: List[str] = []
    verdict_disagreements: List[dict] = []
    joins_inconsistent: List[str] = []
    for k in expected_keys():
        h, t, ol = harness[k], tool[k], openloop[k]
        av0 = float(ol["av0_db"])
        # The harness divided this very Av0 out; a different value would mean the
        # two records are not from the same open-loop run.
        if not math.isclose(av0, h["av0_db"], rel_tol=0, abs_tol=1e-9):
            joins_inconsistent.append(f"{key_str(k)}: open-loop av0_db {av0} != harness-recorded av0_db {h['av0_db']}")
        tv_all = {
            "avs0_db": t["avs0_db"],
            "avs_1khz_db": t["avs_1khz_db"],
            "avs_plateau_delta_db": t["avs_plateau_delta_db"],
            "psrr_db": av0 - float(t["avs0_db"]),
            "psrr_1khz_db": av0 - float(t["avs_1khz_db"]),
        }
        hv_all = {
            "avs0_db": h["avs0_db"], "avs_1khz_db": h["avs_1khz_db"],
            "avs_plateau_delta_db": h["psrr_plateau_delta_db"],
            "psrr_db": h["psrr_db"], "psrr_1khz_db": h["psrr_1khz_db"],
        }
        metrics = {}
        for m, tv in tv_all.items():
            hv = float(hv_all[m])
            tol = _tol(m, hv)
            delta = float(tv) - hv
            within = abs(delta) <= tol
            metrics[m] = {"harness": hv, "tool": float(tv), "delta": delta, "tolerance": tol,
                          "unit": TOLERANCES[m]["unit"], "within": within}
            if not within:
                out_of_tol.append(f"{key_str(k)} {m}: tool {float(tv):.9g} vs harness {hv:.9g} "
                                  f"(delta {delta:.3g} dB, tolerance {tol:.3g})")

        # Ratified row, offline: PSRR(DC shelf) >= 1.87 dB at this point.
        tool_psrr = tv_all["psrr_db"]
        harness_psrr = float(h["psrr_db"])
        tool_pass = tool_psrr >= PSRR_BOUND_DB
        harness_pass = harness_psrr >= PSRR_BOUND_DB
        near = abs(harness_psrr - PSRR_BOUND_DB) <= _tol("psrr_db", harness_psrr)
        row = {"tool_psrr_db": tool_psrr, "harness_psrr_db": harness_psrr, "tool_pass": tool_pass,
               "harness_pass": harness_pass, "agree": tool_pass == harness_pass,
               "harness_within_tolerance_of_bound": near,
               "verdict_source": "offline join with the open-loop harness record (not a klt verdict)"}
        if tool_pass != harness_pass:
            verdict_disagreements.append({"point": key_str(k), "row": "psrr_dc_shelf", "harness": harness_psrr,
                                          "tool": tool_psrr, "bound": PSRR_BOUND_DB,
                                          "explained_by_tolerance": near})

        # Plateau guard: the tool's graded limit vs the harness's own delta.
        harness_plateau_ok = float(h["psrr_plateau_delta_db"]) <= PLATEAU_LIMIT_DB
        tool_plateau_ok = t.get("avs_plateau_delta_db__status") == "pass"
        plateau = {"harness_pass": harness_plateau_ok, "tool_pass": tool_plateau_ok,
                   "agree": harness_plateau_ok == tool_plateau_ok}
        if not plateau["agree"]:
            out_of_tol.append(f"{key_str(k)} plateau_guard: harness pass={harness_plateau_ok} vs tool pass={tool_plateau_ok}")
        points.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                       "av0_db_joined": av0, "metrics": metrics, "plateau_guard": plateau, "row": row})

    unexplained = [d for d in verdict_disagreements if not d["explained_by_tolerance"]]
    worst_tool = min(((p["row"]["tool_psrr_db"], p["point_id"]) for p in points))
    worst_harness = min(((p["row"]["harness_psrr_db"], p["point_id"]) for p in points))
    summary = {
        "bound": {"min": PSRR_BOUND_DB, "unit": "dB"},
        "tool_worst": {"point": worst_tool[1], "value": worst_tool[0],
                       "verdict": "pass" if worst_tool[0] >= PSRR_BOUND_DB else "fail"},
        "harness_worst": {"point": worst_harness[1], "value": worst_harness[0],
                          "verdict": "pass" if worst_harness[0] >= PSRR_BOUND_DB else "fail"},
        "verdict_source": "offline join of the tool's Avs with the harness open-loop Av0; not a klt verdict",
    }
    if env is not None:
        summary["tool_plateau_guard"] = {}
        for m in env.get("measurements") or []:
            if m.get("name") == "avs_plateau_delta_db":
                summary["tool_plateau_guard"] = {"status": m.get("status"), "limits": m.get("limits"),
                                                 "worst_case": m.get("worst_case")}
    return {
        "schema": "sg13g2-opamp/cmrr-psrr/klt-compare/1",
        "points_compared": len(points),
        "tolerances": TOLERANCES,
        "out_of_tolerance": out_of_tol,
        "join_inconsistencies": joins_inconsistent,
        "bound_verdict_disagreements": verdict_disagreements,
        "unexplained_bound_verdict_disagreements": len(unexplained),
        "row": summary,
        "points": points,
        "status": "agree" if not (out_of_tol or unexplained or joins_inconsistent) else "disagree",
    }


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _text_summary(rep: dict) -> str:
    r = rep["row"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}",
             f"  PSRR bound >= {r['bound']['min']} dB (offline join): tool worst {r['tool_worst']['point']} = "
             f"{r['tool_worst']['value']:.6g} ({r['tool_worst']['verdict']}); harness worst "
             f"{r['harness_worst']['point']} = {r['harness_worst']['value']:.6g} ({r['harness_worst']['verdict']})"]
    for line in rep["join_inconsistencies"]:
        lines.append(f"  JOIN INCONSISTENT: {line}")
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
    c = sub.add_parser("compare", help="join the envelope with the harness records")
    c.add_argument("--envelope", required=True)
    c.add_argument("--harness-csv", required=True)
    c.add_argument("--openloop-csv", required=True)
    c.add_argument("--json-out")
    c.add_argument("--provenance", action="append", default=[], metavar="KEY=VALUE")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "validate":
            env, idx = load_envelope(a.envelope)
            print(f"validate: {a.envelope}: {len(idx)} corners, status {env.get('status')}, ok")
            return 0
        env, tool = load_envelope(a.envelope)
        rep = compare(tool, load_harness_csv(a.harness_csv), load_openloop_csv(a.openloop_csv), env)
    except InputError as e:
        print(f"compare.py: {e}", file=sys.stderr)
        return 2

    rep["inputs"] = {"envelope": {"path": a.envelope, "sha256": _sha256(a.envelope)},
                     "harness_csv": {"path": a.harness_csv, "sha256": _sha256(a.harness_csv)},
                     "openloop_csv": {"path": a.openloop_csv, "sha256": _sha256(a.openloop_csv)}}
    rep["provenance"] = dict(kv.split("=", 1) for kv in a.provenance)
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(rep, f, indent=2)
            f.write("\n")
    print(_text_summary(rep))
    return 0 if rep["status"] == "agree" else 1


if __name__ == "__main__":
    sys.exit(main())

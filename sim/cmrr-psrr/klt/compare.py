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

import csv
import functools
import math
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
#   The tolerance is PROVISIONAL until a real 45-point envelope quantifies the
#   per-point spread; it never touches a pass/fail limit.
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


# --------------------------------------------------------------- envelopes
# Measurement statuses whose value is unusable whatever its number.
REJECT_STATUSES = ("skipped", "error", "inconclusive", "not_checked")


def index_envelope(env: dict, label: str = "envelope") -> Dict[Key, Dict[str, object]]:
    """The shared envelope gate (klt_envelope.index_envelope), additionally
    refusing a measurement whose status is in REJECT_STATUSES."""
    return E.index_envelope(env, label, MEASUREMENTS, reject_statuses=REJECT_STATUSES)


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
    E.check_grid(out.keys(), label, problems)
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
_tol = functools.partial(E.tol, TOLERANCES)


def compare(tool: Dict[Key, Dict[str, object]], harness: Dict[Key, Dict[str, float]],
            openloop: Dict[Key, Dict[str, float]], env: Optional[dict] = None) -> dict:
    problems: List[str] = []
    for label, d in (("envelope", tool), ("harness CSV", harness), ("open-loop CSV", openloop)):
        E.check_grid(d.keys(), label, problems)
    for k in expected_keys():
        if k in tool:
            for n in ("avs0_db", "avs_1khz_db", "avs_plateau_delta_db"):
                if not E.finite(tool[k].get(n)):
                    problems.append(f"{key_str(k)}: tool {n} absent or non-finite")
        if k in openloop and not E.finite(openloop[k].get("av0_db")):
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


def _text_summary(rep: dict) -> str:
    r = rep["row"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}",
             f"  PSRR bound >= {r['bound']['min']} dB (offline join): tool worst {r['tool_worst']['point']} = "
             f"{r['tool_worst']['value']:.6g} ({r['tool_worst']['verdict']}); harness worst "
             f"{r['harness_worst']['point']} = {r['harness_worst']['value']:.6g} ({r['harness_worst']['verdict']})"]
    for line in rep["join_inconsistencies"]:
        lines.append(f"  JOIN INCONSISTENT: {line}")
    return "\n".join(E.summary_tail(lines, rep))


def _run(a, tool: Dict[Key, Dict[str, object]], env: dict) -> dict:
    return compare(tool, load_harness_csv(a.harness_csv), load_openloop_csv(a.openloop_csv), env)

def main(argv: Optional[List[str]] = None) -> int:
    return E.run_cli(
        argv, description=__doc__.split("\n\n")[0], compare_help="join the envelope with the harness records",
        harness_args=(("--harness-csv", {"required": True}), ("--openloop-csv", {"required": True})),
        index_fn=index_envelope,
        run=_run,
        inputs=(("harness_csv", "harness_csv", True), ("openloop_csv", "openloop_csv", True)),
        summary=_text_summary)


if __name__ == "__main__":
    sys.exit(main())

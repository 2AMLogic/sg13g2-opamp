#!/usr/bin/env python3
"""Cross-check the direct PSRR `klt sim` envelope against the two-envelope join (issue #307).

Usage:

    compare_direct.py validate <direct.sim.json>
    compare_direct.py compare --envelope <direct.sim.json> --join-record <records/*.compare.json> \
        [--json-out <report.json>] [--provenance key=value ...]

Offline and stdlib-only. psrr_direct.request.json measures PSRR = Av0 - Avs0
as ONE derived measurement (two DUT copies in one deck) and grades the
ratified bound itself. `compare` checks it, at all 45 points, against the
committed join of the two single-excitation envelopes (compare.py's
`.compare.json`: `points[].row.tool_psrr_db`, the joined Av0 and the Avs0 tool
value), and checks that both agree on the bound verdict. A disagreement is
reported (exit 1, report still written), never hidden.

Exit status: 0 agree; 1 outside tolerance / verdict disagrees; 2 inputs unusable.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import klt_envelope as E  # noqa: E402
from klt_envelope import InputError, Key, make_key, key_str  # noqa: E402

MEASUREMENTS = ("av0_db", "avs0_db", "psrr_db", "psrr_plateau_delta_db")
PSRR_BOUND_DB = 1.87
REJECT_STATUSES = ("skipped", "error", "inconclusive", "not_checked")

# |direct - join| <= abs, in dB. Basis: the same two circuits and the same
# ngspice default tolerance (DR-0005) solved in one deck instead of two, so the
# only difference is solver-host noise (DR-0005's 9.9e-4 relative current
# difference moves a gain by under 0.017 dB; rounded to 0.02 dB, the tolerance
# every other cross-check in this directory uses). A one-corner local probe
# agreed with the join to 5e-8 dB.
TOLERANCES = {
    "psrr_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "av0_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
    "avs0_db": {"abs": 0.02, "rel": 0.0, "unit": "dB"},
}


def index_envelope(env: dict, label: str = "envelope") -> Dict[Key, Dict[str, object]]:
    return E.index_envelope(env, label, MEASUREMENTS, reject_statuses=REJECT_STATUSES)


def load_join(path: str) -> Dict[Key, Dict[str, float]]:
    with open(path) as f:
        rec = json.load(f)
    out: Dict[Key, Dict[str, float]] = {}
    for p in rec.get("points") or []:
        k = make_key(p["process"], p["temperature_c"], p["vdd_v"])
        if k in out:
            raise InputError(f"{path}: duplicate point {key_str(k)}")
        try:
            out[k] = {"psrr_db": float(p["row"]["tool_psrr_db"]), "av0_db": float(p["av0_db_joined"]),
                      "avs0_db": float(p["metrics"]["avs0_db"]["tool"])}
        except (KeyError, TypeError, ValueError) as e:
            raise InputError(f"{path}: point {key_str(k)} lacks a joined value ({e!r})")
    missing = set(E.expected_keys()) - set(out)
    if missing or len(out) != 45:
        raise InputError(f"{path}: join record is not the 45-point grid ({len(out)} points, {len(missing)} missing)")
    return out


def compare(tool: Dict[Key, Dict[str, object]], join: Dict[Key, Dict[str, float]]) -> dict:
    points: List[dict] = []
    oot: List[str] = []
    disagree: List[str] = []
    for k in E.expected_keys():
        t, j = tool[k], join[k]
        metrics = {}
        for m, tb in TOLERANCES.items():
            d = float(t[m]) - j[m]
            ok = abs(d) <= E.tol(TOLERANCES, m, j[m])
            metrics[m] = {"join": j[m], "direct": t[m], "delta": d, "tolerance": tb["abs"], "unit": "dB", "within": ok}
            if not ok:
                oot.append(f"{key_str(k)} {m}: direct {t[m]:.6g} vs join {j[m]:.6g} (delta {d:.3g} dB)")
        dp, jp = float(t["psrr_db"]) >= PSRR_BOUND_DB, j["psrr_db"] >= PSRR_BOUND_DB
        near = abs(j["psrr_db"] - PSRR_BOUND_DB) <= TOLERANCES["psrr_db"]["abs"]
        if dp != jp and not near:
            disagree.append(f"{key_str(k)}: direct {'pass' if dp else 'fail'} vs join {'pass' if jp else 'fail'}")
        points.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                       "metrics": metrics, "direct_pass": dp, "join_pass": jp})

    def worst(src):
        pt = min(points, key=lambda p: p["metrics"]["psrr_db"][src])
        return {"point": pt["point_id"], "value": pt["metrics"]["psrr_db"][src], "verdict": "pass" if pt["metrics"]["psrr_db"][src] >= PSRR_BOUND_DB else "fail"}

    maxd = max(points, key=lambda p: abs(p["metrics"]["psrr_db"]["delta"]))
    return {"points_compared": len(points), "tolerances": TOLERANCES,
            "out_of_tolerance": oot, "bound_verdict_disagreements": disagree,
            "row": {"bound": {"min": PSRR_BOUND_DB, "unit": "dB"}, "direct_worst": worst("direct"), "join_worst": worst("join"),
                    "max_abs_psrr_delta_db": abs(maxd["metrics"]["psrr_db"]["delta"]), "max_abs_psrr_delta_point": maxd["point_id"],
                    "plateau_delta_worst_db": max(float(tool[k]["psrr_plateau_delta_db"]) for k in tool),
                    "verdict_source": "klt sim limits.min on the derived psrr_db measurement"},
            "points": points, "status": "agree" if not (oot or disagree) else "disagree"}


def _summary(rep: dict) -> str:
    r = rep["row"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}",
             f"  PSRR >= {r['bound']['min']} dB: direct worst {r['direct_worst']['point']} = {r['direct_worst']['value']:.6g} "
             f"({r['direct_worst']['verdict']}); join worst {r['join_worst']['point']} = {r['join_worst']['value']:.6g} ({r['join_worst']['verdict']})",
             f"  max |direct - join| {r['max_abs_psrr_delta_db']:.3g} dB at {r['max_abs_psrr_delta_point']}; worst plateau delta {r['plateau_delta_worst_db']:.3g} dB"]
    return "\n".join(E.summary_tail(lines, rep))


def _run(a, tool, env) -> dict:
    return compare(tool, load_join(a.join_record))


def main(argv: Optional[List[str]] = None) -> int:
    return E.run_cli(argv, description=__doc__.split("\n\n")[0], compare_help="cross-check against the two-envelope join",
                     harness_args=(("--join-record", {"required": True}),), index_fn=index_envelope, run=_run,
                     inputs=(("join_record", "join_record", True),), summary=_summary)


if __name__ == "__main__":
    sys.exit(main())

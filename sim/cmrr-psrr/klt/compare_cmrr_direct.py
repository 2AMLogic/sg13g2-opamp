#!/usr/bin/env python3
"""Cross-check the direct CMRR `klt sim` envelope (issue #505).

Usage:

    compare_cmrr_direct.py validate <cmrr.sim.json>
    compare_cmrr_direct.py compare --envelope <cmrr.sim.json> --psrr-envelope <direct.sim.json> \
        --harness-csv <records/*.csv> [--cmrr-body F] [--psrr-body F] [--json-out <report.json>] \
        [--provenance key=value ...]

Offline and stdlib-only. cmrr_direct.request.json measures Av0, Acm0 and
CMRR = Av0 - Acm0 in ONE deck (two DUT copies). `compare` checks, at all 45
points:

  * the joined run conditions: both envelopes (this one and the PSRR direct
    one) ran the same engine and version, model deck, DUT netlist hash and
    corner grid; a different DUT hash or engine is refused, not compared;
  * each envelope's bench body hash equals the committed body, and the bodies
    carry the intended stimulus (CMRR: differential on copy A, in-phase
    common-mode on copy B, supply quiet; PSRR: differential on A, supply on B)
    -- a swapped stimulus is refused;
  * Av0 of the CMRR deck equals Av0 of the PSRR direct deck at every point
    (same DUT, corner, temperature, VDD and options, so a stale or misjoined
    Av0 point shows as a named out-of-tolerance point);
  * cmrr_db == av0_db - acm0_db (internal consistency);
  * Acm0 against the superseded fixed-harness record (regression control).

The harness record's Av0 (hence its CMRR) is NOT a regression control: its Av0
is the floating-`inn` open-loop gain, which differs from the AC-grounded
batch Av0 by +0.2199..+1.785 dB (the shift sim/open-loop-ac/records/
20261015-103057-895d555.md records). That shift is reported, never hidden.
A plateau-guard miss is a result (envelope `fail`), listed in the report.

Exit status: 0 agree; 1 outside tolerance; 2 inputs unusable.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.normpath(os.path.join(HERE, "..", "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import klt_envelope as E  # noqa: E402
from klt_envelope import InputError, Key, key_str  # noqa: E402

MEASUREMENTS = ("av0_db", "acm0_db", "cmrr_db", "cmrr_plateau_delta_db")
PSRR_MEASUREMENTS = ("av0_db", "avs0_db", "psrr_db", "psrr_plateau_delta_db")
REJECT_STATUSES = ("skipped", "error", "inconclusive", "not_checked")
CMRR_SYSTEMATIC_BOUND_DB = 30.75  # superseded DR-2 row, context only
PLATEAU_MAX_DB = 0.05
DEFAULT_CMRR_BODY = os.path.join(HERE, "tb_cmrr_direct.body.spice")
DEFAULT_PSRR_BODY = os.path.join(HERE, "tb_psrr_direct.body.spice")
DUT = "design/netlist/opamp_core.spice"

# Basis: same circuit solved in one deck instead of two single-excitation runs
# (psrr/cmrr direct decks share the Av0 copy verbatim), so Av0 agrees to solver
# noise: observed 6e-9 dB across ngspice 46/47; 1e-4 dB leaves headroom without
# admitting a wrong corner (adjacent corners differ by >0.1 dB).
AV0_JOIN_ABS_DB = 1e-4
CONSISTENCY_ABS_DB = 1e-6
# Acm0 vs the harness record: the same common-mode circuit; the harness CSV
# prints 6 significant digits. Observed max 4.3e-5 dB.
ACM0_HARNESS_ABS_DB = 1e-3


def index_envelope(env: dict, label: str = "envelope", measurements=MEASUREMENTS) -> Dict[Key, Dict[str, object]]:
    if isinstance(env, dict) and "corners" not in env and "error" not in env:
        raise InputError(f"{label}: not a klt sim envelope (no corners[]); a harness record is not batch evidence")
    idx = E.index_envelope(env, label, measurements, reject_statuses=REJECT_STATUSES)
    remote = ((env.get("environment") or {}).get("remote") or {})
    if not (remote.get("job_id") or remote.get("fleet")):
        raise InputError(f"{label}: no environment.remote batch job (a local or harness run is not batch evidence)")
    return idx


def _closure(env: dict) -> Dict[str, str]:
    return {c["path"]: c["sha256"] for c in (env.get("environment") or {}).get("netlist_closure") or []}


def _body_path(env: dict) -> str:
    n = env.get("netlist")
    return n.get("path") if isinstance(n, dict) else str(n)


def check_conditions(cmrr: dict, psrr: dict) -> None:
    """The two envelopes must be the same run conditions, or they are not joined."""
    problems: List[str] = []
    ec, ep = cmrr.get("environment") or {}, psrr.get("environment") or {}
    for f in ("engine", "engine_version", "models_lib_sha256"):
        if ec.get(f) != ep.get(f):
            problems.append(f"{f} differs (CMRR {ec.get(f)!r} vs PSRR {ep.get(f)!r})")
    cc, cp = _closure(cmrr), _closure(psrr)
    if DUT not in cc or DUT not in cp:
        problems.append(f"{DUT} missing from a netlist closure")
    elif cc[DUT] != cp[DUT]:
        problems.append(f"DUT netlist hash differs (CMRR {cc[DUT][:12]} vs PSRR {cp[DUT][:12]}): Av0 is from a different DUT")
    if problems:
        raise InputError("misjoined envelopes: " + "; ".join(problems))


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_body_hash(env: dict, body_path: str, label: str) -> None:
    got = _closure(env).get("sim/cmrr-psrr/klt/" + os.path.basename(body_path))
    if got is None:
        raise InputError(f"{label}: envelope closure does not name {os.path.basename(body_path)}")
    if got != _sha(body_path):
        raise InputError(f"{label}: simulated bench body hash {got[:12]} is not the committed {os.path.basename(body_path)} ({_sha(body_path)[:12]}): stale or different body")


_AC_SRC = re.compile(r"^([VI]\w*)\s+.*\bac\s+[0-9.eE+-]+", re.MULTILINE | re.IGNORECASE)


def check_stimulus(cmrr_body: str, psrr_body: str) -> None:
    """Refuse a swapped common-mode/supply stimulus."""
    problems = []
    cm_srcs = sorted(m.group(1).lower() for m in _AC_SRC.finditer(cmrr_body))
    if cm_srcs != ["vcmb", "vinp"]:
        problems.append(f"CMRR body AC sources are {cm_srcs}, need exactly ['vcmb', 'vinp']")
    if not re.search(r"^Vcmb\s+inpb\s+midb\s+dc\s+0\s+ac\s+1\s*$", cmrr_body, re.M | re.I):
        problems.append("CMRR body: common-mode source must be `Vcmb inpb midb dc 0 ac 1` (input of copy B)")
    if not re.search(r"^Ccmb\s+innb\s+inpb\s+1\s*$", cmrr_body, re.M | re.I):
        problems.append("CMRR body: inn of copy B must follow inp through `Ccmb innb inpb 1`")
    if re.search(r"^Vsrip\b", cmrr_body, re.M | re.I):
        problems.append("CMRR body carries a supply AC source (Vsrip): swapped stimulus")
    ps_srcs = sorted(m.group(1).lower() for m in _AC_SRC.finditer(psrr_body))
    if ps_srcs != ["vinp", "vsrip"]:
        problems.append(f"PSRR body AC sources are {ps_srcs}, need exactly ['vinp', 'vsrip']")
    if re.search(r"^Vcmb\b", psrr_body, re.M | re.I):
        problems.append("PSRR body carries a common-mode AC source (Vcmb): swapped stimulus")
    if problems:
        raise InputError("stimulus check: " + "; ".join(problems))


def load_harness(path: str) -> Dict[Key, Dict[str, object]]:
    return E.load_harness_csv_rows(path, ("av0_db", "acm0_db", "cmrr_db"), "harness CSV")  # type: ignore[return-value]


def compare(cmrr_idx, psrr_idx, harness, cmrr_env: dict, psrr_env: dict, cmrr_body: str, psrr_body: str) -> dict:
    check_conditions(cmrr_env, psrr_env)
    check_stimulus(cmrr_body, psrr_body)
    oot: List[str] = []
    plateau_fail: List[str] = []
    points: List[dict] = []
    for k in E.expected_keys():
        t, p, h = cmrr_idx[k], psrr_idx[k], harness[k]
        d_av = float(t["av0_db"]) - float(p["av0_db"])
        if abs(d_av) > AV0_JOIN_ABS_DB:
            oot.append(f"{key_str(k)} av0_db: CMRR deck {t['av0_db']:.9g} vs PSRR deck {p['av0_db']:.9g} (delta {d_av:.3g} dB): stale or misjoined Av0")
        d_cons = float(t["cmrr_db"]) - (float(t["av0_db"]) - float(t["acm0_db"]))
        if abs(d_cons) > CONSISTENCY_ABS_DB:
            oot.append(f"{key_str(k)} cmrr_db: {t['cmrr_db']:.9g} != av0_db - acm0_db (delta {d_cons:.3g} dB)")
        d_acm = float(t["acm0_db"]) - float(h["acm0_db"])
        if abs(d_acm) > ACM0_HARNESS_ABS_DB:
            oot.append(f"{key_str(k)} acm0_db: batch {t['acm0_db']:.9g} vs harness {h['acm0_db']:.9g} (delta {d_acm:.3g} dB): wrong common-mode stimulus?")
        pl = float(t["cmrr_plateau_delta_db"])
        if t.get("cmrr_plateau_delta_db__status") == "fail" or pl > PLATEAU_MAX_DB:
            plateau_fail.append(f"{key_str(k)}: |CMRR(0.1 Hz) - CMRR(10 mHz)| = {pl:.4g} dB > {PLATEAU_MAX_DB}")
        points.append({"point_id": key_str(k), "process": k[0], "temperature_c": k[1], "vdd_v": k[2],
                       "av0_db": t["av0_db"], "acm0_db": t["acm0_db"], "cmrr_db": t["cmrr_db"],
                       "cmrr_plateau_delta_db": pl,
                       "av0_vs_psrr_deck_delta_db": d_av, "acm0_vs_harness_delta_db": d_acm,
                       "av0_vs_harness_shift_db": float(t["av0_db"]) - float(h["av0_db"]),
                       "cmrr_vs_harness_shift_db": float(t["cmrr_db"]) - float(h["cmrr_db"]),
                       "meets_systematic_floor": float(t["cmrr_db"]) >= CMRR_SYSTEMATIC_BOUND_DB})
    worst = min(points, key=lambda q: q["cmrr_db"])
    shifts = [q["cmrr_vs_harness_shift_db"] for q in points]
    avs = [q["av0_vs_harness_shift_db"] for q in points]
    return {"points_compared": len(points),
            "tolerances": {"av0_vs_psrr_deck_abs_db": AV0_JOIN_ABS_DB, "consistency_abs_db": CONSISTENCY_ABS_DB,
                           "acm0_vs_harness_abs_db": ACM0_HARNESS_ABS_DB},
            "out_of_tolerance": oot, "bound_verdict_disagreements": [],
            "plateau_guard_failures": plateau_fail,
            "conditions": {"engine": cmrr_env["environment"].get("engine"), "engine_version": cmrr_env["environment"].get("engine_version"),
                           "dut_netlist_sha256": _closure(cmrr_env)[DUT], "models_lib_sha256": cmrr_env["environment"].get("models_lib_sha256")},
            "row": {"context_bound": {"min": CMRR_SYSTEMATIC_BOUND_DB, "unit": "dB", "note": "superseded DR-2 systematic floor, context only"},
                    "worst": {"point": worst["point_id"], "value": worst["cmrr_db"], "verdict": "pass" if worst["meets_systematic_floor"] else "fail"},
                    "points_below_floor": [q["point_id"] for q in points if not q["meets_systematic_floor"]],
                    "harness_shift_db": {"cmrr_min": min(shifts), "cmrr_max": max(shifts), "av0_min": min(avs), "av0_max": max(avs),
                                         "basis": "harness Av0 is the superseded floating-inn open-loop gain; not a regression control for Av0/CMRR"}},
            "points": points, "status": "agree" if not oot else "disagree"}


def _summary(rep: dict) -> str:
    r = rep["row"]
    lines = [f"compare: {rep['points_compared']} points, status {rep['status']}, engine ngspice-{rep['conditions']['engine_version']}",
             f"  CMRR (systematic, context floor {r['context_bound']['min']} dB): worst {r['worst']['point']} = {r['worst']['value']:.6g} ({r['worst']['verdict']})",
             f"  Av0/CMRR shift vs superseded floating-inn harness record: Av0 {r['harness_shift_db']['av0_min']:+.4g}..{r['harness_shift_db']['av0_max']:+.4g} dB",
             f"  plateau-guard failures: {len(rep['plateau_guard_failures'])}"]
    return "\n".join(E.summary_tail(lines, rep))


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError as e:
        raise InputError(f"{path}: unreadable ({e})")


def _run(a, tool, env) -> dict:
    psrr_env = E.read_envelope(a.psrr_envelope)
    psrr_idx = E.index_envelope(psrr_env, "PSRR direct envelope", PSRR_MEASUREMENTS, reject_statuses=REJECT_STATUSES)
    check_body_hash(env, a.cmrr_body, "CMRR envelope")
    check_body_hash(psrr_env, a.psrr_body, "PSRR direct envelope")
    return compare(tool, psrr_idx, load_harness(a.harness_csv), env, psrr_env, _read(a.cmrr_body), _read(a.psrr_body))


def main(argv: Optional[List[str]] = None) -> int:
    return E.run_cli(argv, description=__doc__.split("\n\n")[0], compare_help="cross-check against the PSRR direct deck and the harness record",
                     harness_args=(("--psrr-envelope", {"required": True}), ("--harness-csv", {"required": True}),
                                   ("--cmrr-body", {"default": DEFAULT_CMRR_BODY}), ("--psrr-body", {"default": DEFAULT_PSRR_BODY})),
                     index_fn=index_envelope, run=_run,
                     inputs=(("psrr_envelope", "psrr_envelope", True), ("harness_csv", "harness_csv", True)), summary=_summary)


if __name__ == "__main__":
    sys.exit(main())

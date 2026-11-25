#!/usr/bin/env python3
"""The input-offset batch record: derive every published cell from the two
`klt sim` envelopes plus the Av0 join (issue #504).

This is the SAME derivation sim/input-offset/run_offset_sweep.sh applies to
its three harness passes, re-expressed once as a module so that

* klt/run.sh mints the batch record `records/<id>.csv` (+ `.md`) from the
  null envelope (tb_offset.body.spice, `dc Vid 0.004 0.034 4u`), the
  closed-loop envelope (tb_offset_cl.body.spice, `op` with
  `Lbreak inn out 1e18`) and the selected same-DUT sim/open-loop-ac record's
  per-corner Av0;
* klt/compare.py derives the tool side of its join against the harness CSV;
* signoff/characterization (definition check `offset_klt_audit`) re-derives
  every committed cell from the pinned envelopes offline.

The harness's per-point rules, transcribed exactly (run_offset_sweep.sh and
README.md "Per-point sanity checks"):

* op_pass: the rail window of sim/tools/op_sanity.py `rail_ok` over
  (Vd1, Vd2, Vtail, Vout-at-the-null), the local gain >= 10 V/V, and exactly
  one Vout = Vcm crossing. The harness's coarse-window rule
  (|vos| < 0.9*0.1 V) maps to the batch's exactly-one-crossing rule over the
  4..34 mV sweep window: a null that left the window shows 0 crossings. The
  harness's mid-rail gap term is vacuous at a Vout = Vcm crossing by
  definition (issue #380). The batch reads Vout AT the interpolated null
  (`.meas ... find v(out) when v(orel)=0`), where the harness reads it at
  the swept sample nearest the null (<= 2 uV of Vid away).
* the closed-loop cross-check: vout_cl_err = vout_cl - Vcm;
  vos_cl = -vout_cl_err * (1 + Av0)/Av0 with Av0 the SAME-grid-point Av0 of
  the joined open-loop record; the two methods agree when
  |vos_null - vos_cl| <= max(200 uV, 5% |vos_null|). A non-finite joined
  Av0 makes vos_cl and the delta nan and the cross-check fail, exactly as
  the harness's missing-lookup case.

Serialization is the harness's own printf %.9g (nine significant digits),
`nan` spelled out, flags 0/1 -- so a committed cell and its offline
re-derivation compare as exact strings.

Stdlib only; reads committed files, never re-simulates.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, Optional

# sim/tools (op_sanity, klt_envelope) relative to this file, exactly the way
# compare.py beside it hops there.
_TOOLS = str(Path(__file__).resolve().parent.parent.parent / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import klt_envelope as E  # noqa: E402
from op_sanity import rail_ok  # noqa: E402

# Everything offset.request.json reports (the null sweep).
NULL_MEASUREMENTS = (
    "vos_null_v", "vos_crossings_n", "gain_local_vv",
    "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vout_null_dc_v", "vibias_dc_v",
    "op_vd1_rail_frac", "op_vd2_rail_frac", "op_vtail_rail_frac",
)
# Everything offset_cl.request.json reports (the closed-loop cross-check).
CL_MEASUREMENTS = ("vout_cl_v",)

# The derived cells of the batch record, in column order.
RECORD_COLUMNS = (
    "point_id", "corner", "temp_c", "vdd_v", "vcm_v", "op_pass", "xcheck_pass",
    "vos_null_v", "vos_abs_v", "gain_local_db", "vout_null_dc_v",
    "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v",
    "av0_db_av_record", "vout_cl_v", "vout_cl_err_v",
    "vos_closed_loop_v", "vos_method_delta_v",
)

# The harness's xcheck tolerance: the two methods must agree to the
# CMRR-order difference between their input common-mode conditions
# (README.md "Two methods"), never merely the same order of magnitude.
XCHECK_ABS_V = 200e-6
XCHECK_REL = 0.05

# The harness's amplifying-point rule: a flat/railed "null" shows up as a
# near-zero local slope (>= 20 dB sanity rule).
GAIN_MIN_VV = 10.0


class OffsetPostError(Exception):
    """The inputs cannot yield a record (unreadable, off-grid, ambiguous)."""


def serialize(x: float) -> str:
    """The bench's printf %.9g; nan spelled out (flags serialize via int())."""
    return "nan" if x != x else f"{x:.9g}"


def xcheck_tolerance(vos_null: float) -> float:
    return max(XCHECK_ABS_V, XCHECK_REL * abs(vos_null))


def derive(null: Dict[str, float], vout_cl: float, vdd: float,
            av0_db: float) -> dict:
    """One grid point's derived cells from the two envelopes and the Av0 join.

    `null` is the null envelope's measurements for the point (NULL_MEASUREMENTS
    keys as floats), `vout_cl` the closed-loop envelope's v(out), `vdd` the
    corner supply, `av0_db` the joined open-loop record's Av0 (nan when the
    join has no finite value for the point -- the harness's missing lookup).
    """
    vos = null["vos_null_v"]
    vcm = vdd / 2.0
    reasons = []
    if not rail_ok(vdd, (null["vd1_dc_v"], null["vd2_dc_v"], null["vtail_dc_v"], null["vout_null_dc_v"])):
        reasons.append("a rail-window node is outside [0.02, 0.98]*VDD at the null")
    gain = null["gain_local_vv"]
    if not (gain == gain and gain >= GAIN_MIN_VV):
        reasons.append(f"local gain {serialize(gain)} V/V is below {GAIN_MIN_VV:g}")
    crossings = null["vos_crossings_n"]
    if not 0.5 < crossings < 1.5:
        reasons.append(f"{serialize(crossings)} Vout=Vcm crossings (expected exactly 1)")
    op_pass = not reasons

    vout_cl_err = vout_cl - vcm
    if av0_db == av0_db:
        av_ac = 10.0 ** (av0_db / 20.0)
        vos_cl = -vout_cl_err * (1.0 + av_ac) / av_ac
        method_delta = vos - vos_cl
        tol = xcheck_tolerance(vos)
        xcheck_pass = abs(method_delta) <= tol
        xcheck_why = (None if xcheck_pass else
                      f"|vos_null - vos_cl| = {serialize(abs(method_delta))} V exceeds the "
                      f"max({XCHECK_ABS_V:g}, {XCHECK_REL:g}*|vos|) = {serialize(tol)} V tolerance")
    else:
        vos_cl = float("nan")
        method_delta = float("nan")
        xcheck_pass = False
        xcheck_why = "no finite Av0 in the joined open-loop record for this point"
    return {
        "op_pass": op_pass, "op_reasons": reasons,
        "xcheck_pass": xcheck_pass, "xcheck_why": xcheck_why,
        "vos_null_v": vos, "vos_abs_v": abs(vos),
        "gain_local_db": 20.0 * math.log10(gain) if gain == gain and gain > 0 else float("nan"),
        "vcm_v": vcm, "vout_cl_v": vout_cl, "vout_cl_err_v": vout_cl_err,
        "vos_closed_loop_v": vos_cl, "vos_method_delta_v": method_delta,
        "av0_db": av0_db,
    }


def derive_point(null_vals: Dict[str, float], vout_cl: float, vdd: float,
                 av0_db: float) -> dict:
    """derive() over a NULL_MEASUREMENTS-keyed dict (envelope values)."""
    return derive(null_vals, vout_cl, vdd, av0_db)


# ------------------------------------------------------------------ the join
def read_av0_csv(path: str) -> Dict[E.Key, float]:
    """{grid key: Av0 in dB} from an open-loop-ac record CSV.

    The joined record's own corner/temp_c/vdd_v columns must spell each row's
    point_id (a swapped temperature/VDD key is a different point -- catching
    it here is what binds each Av0 to ITS corner), point ids must be unique
    and on the ratified grid, and the av0_db column must be present. A row
    whose av0_db cell is missing or non-finite yields nan for its point (the
    harness's own missing-lookup behaviour); everything else is an
    OffsetPostError naming the row.
    """
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        raise OffsetPostError(f"{path}: unreadable Av0 record ({exc})") from exc
    if not rows or "av0_db" not in rows[0]:
        raise OffsetPostError(f"{path}: no av0_db column")
    out: Dict[E.Key, float] = {}
    for r in rows:
        try:
            k = E.make_key(r["corner"], r["temp_c"], r["vdd_v"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise OffsetPostError(f"{path}: unparsable row {r!r}") from exc
        pid = (r.get("point_id") or "").strip()
        if pid != E.key_str(k):
            raise OffsetPostError(
                f"{path}: {pid!r}: point_id disagrees with its corner/temp_c/vdd_v columns "
                f"(they spell {E.key_str(k)!r}) -- an Av0 bound to the wrong corner")
        if k in out:
            raise OffsetPostError(f"{path}: duplicate point {pid}")
        if k not in set(E.expected_keys()):
            raise OffsetPostError(f"{path}: {pid} is not a point of the ratified grid")
        try:
            out[k] = float(r["av0_db"])
        except (TypeError, ValueError):
            out[k] = float("nan")
    for k in E.expected_keys():
        out.setdefault(k, float("nan"))
    return out


# --------------------------------------------------------------- envelopes
def envelope_points(env: dict, measurements, label: str) -> Dict[E.Key, Dict[str, float]]:
    """{grid key: {measurement: value}} from one `klt sim` envelope, gated by
    the shared envelope gate (klt_envelope.index_envelope)."""
    return E.index_envelope(env, label, tuple(measurements))


def record_rows(null_env: dict, cl_env: dict, av0_csv: str,
                label_null: str = "null envelope", label_cl: str = "cl envelope"
                ) -> list[dict]:
    """The 45 derived rows of the batch record, sorted by point id.

    Both envelopes must gate clean (the shared gate refuses a missing,
    duplicate, off-grid, errored or non-finite corner); the Av0 join is read
    with read_av0_csv's corner-binding rules. Every row carries the derived
    cells plus the grid columns the harness record spells.
    """
    null = envelope_points(null_env, NULL_MEASUREMENTS, label_null)
    cl = envelope_points(cl_env, CL_MEASUREMENTS, label_cl)
    av0 = read_av0_csv(av0_csv)
    rows = []
    for k in E.expected_keys():
        d = derive_point(null[k], cl[k]["vout_cl_v"], k[2], av0[k])
        rows.append({
            "point_id": E.key_str(k), "corner": k[0], "temperature_c": k[1], "vdd_v": k[2],
            **d,
            "null": null[k], "av0_joined": av0[k],
        })
    return rows


# ---------------------------------------------------------------- the record
def csv_text(rows: list[dict]) -> str:
    lines = [",".join(RECORD_COLUMNS)]
    for r in sorted(rows, key=lambda r: r["point_id"]):
        cells = {
            "point_id": r["point_id"], "corner": r["corner"],
            "temp_c": str(r["temperature_c"]), "vdd_v": f"{r['vdd_v']:.2f}",
            "vcm_v": serialize(r["vcm_v"]),
            "op_pass": str(int(r["op_pass"])), "xcheck_pass": str(int(r["xcheck_pass"])),
            "vos_null_v": serialize(r["vos_null_v"]), "vos_abs_v": serialize(r["vos_abs_v"]),
            "gain_local_db": serialize(r["gain_local_db"]),
            "vout_null_dc_v": serialize(r["null"]["vout_null_dc_v"]),
            "vd1_dc_v": serialize(r["null"]["vd1_dc_v"]),
            "vd2_dc_v": serialize(r["null"]["vd2_dc_v"]),
            "vtail_dc_v": serialize(r["null"]["vtail_dc_v"]),
            "vibias_dc_v": serialize(r["null"]["vibias_dc_v"]),
            "av0_db_av_record": serialize(r["av0_joined"]),
            "vout_cl_v": serialize(r["vout_cl_v"]), "vout_cl_err_v": serialize(r["vout_cl_err_v"]),
            "vos_closed_loop_v": serialize(r["vos_closed_loop_v"]),
            "vos_method_delta_v": serialize(r["vos_method_delta_v"]),
        }
        lines.append(",".join(cells[c] for c in RECORD_COLUMNS))
    return "\n".join(lines) + "\n"


def md_text(rid: str, rows: list[dict], null_env: dict, cl_env: dict,
            av0_csv: str, snapshot_rel: str) -> str:
    def job(env):
        remote = (env.get("environment") or {}).get("remote") or {}
        return f"`{remote.get('job_id')}` ({remote.get('state')})"

    worst_vos = max(rows, key=lambda r: abs(r["vos_null_v"]))
    worst_delta = max(rows, key=lambda r: abs(r["vos_method_delta_v"]))
    op_fail = [r["point_id"] for r in rows if not r["op_pass"]]
    xcheck_fail = [r["point_id"] for r in rows if not r["xcheck_pass"]]
    lines = [
        f"# input-offset batch record {rid} (null + closed-loop cross-check)",
        "",
        "Generated by `sim/input-offset/klt/run.sh` (issue #504) against "
        "`design/netlist/opamp_core.spice` (snapshot: `" + snapshot_rel + "`) through "
        "`klt sim` on the batch fleet. Two envelopes per corner: the open-loop null sweep "
        "(`klt/records/" + rid + ".sim.json`, `tb_offset.body.spice`, one 7501-point dc sweep "
        "of Vid) and the closed-loop cross-check (`klt/records/" + rid + ".cl.sim.json`, "
        "`tb_offset_cl.body.spice`, one `op` with `Lbreak = 1e18 H` closing the unity-gain "
        "buffer at DC). Grid: cornerMOSlv.lib `mos_tt/ss/ff/sf/fs` [DR-1] x `{-40, 27, 125} C` "
        "x `{1.08, 1.20, 1.32} V` = 45 points, into `CL = 2e-12 F` [DR-1].",
        "",
        f"Batch jobs: null {job(null_env)}, cl {job(cl_env)}.",
        "",
        f"Av0 join: `{av0_csv}` (the selected same-DUT sim/open-loop-ac record), read per "
        "corner by its own point_id; `vos_closed_loop_v = -(vout_cl_v - Vcm)*(1 + Av0)/Av0`. "
        "The null sweep and this join re-derive every cell offline "
        "(`sim/input-offset/klt/offset_post.py`), the same derivation "
        "signoff/characterization's `offset_klt_audit` re-applies to the pinned envelopes.",
        "",
        "Engine: both envelopes agree on the simulator and name its version in their "
        "environment blocks -- that is the pin the selection audits (against the "
        "sim/pdk.json toolchain floor), not this prose.",
        "",
        "## Derived summary (45 corners)",
        "",
        "| quantity | worst | at corner |", "|---|---|---|",
        f"| \\|vos_null_v\\| (ratified bound 21.9 mV [DR-2]) | {serialize(abs(worst_vos['vos_null_v']))} | {worst_vos['point_id']} |",
        f"| \\|vos_method_delta_v\\| (two-method agreement) | {serialize(abs(worst_delta['vos_method_delta_v']))} | {worst_delta['point_id']} |",
        f"| op_pass failures | {len(op_fail)} of 45 | {'; '.join(op_fail) or 'none'} |",
        f"| xcheck_pass failures | {len(xcheck_fail)} of 45 | {'; '.join(xcheck_fail) or 'none'} |",
        "",
        "A ratified-bound miss or a validity failure is a result, recorded as such; the "
        "validity flags (`op_pass`, `xcheck_pass`) gate which points may contribute to a "
        "spec-row extremum, exactly as the harness record's flags do.",
        "",
        f"Per-point data: `sim/input-offset/records/{rid}.csv`. Raw envelopes: "
        f"`sim/input-offset/klt/records/{rid}.sim.json`, `sim/input-offset/klt/records/{rid}.cl.sim.json`.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------- CLI
def main(argv: Optional[list] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write-record", help="mint the batch CSV + Markdown record")
    w.add_argument("--rid", required=True)
    w.add_argument("--null", required=True, help="the null sweep envelope (.sim.json)")
    w.add_argument("--cl", required=True, help="the closed-loop envelope (.cl.sim.json)")
    w.add_argument("--av0-csv", required=True, help="the joined open-loop-ac record CSV")
    w.add_argument("--snapshot", required=True, help="the record's DUT netlist snapshot, repo-relative")
    w.add_argument("--out-csv", required=True)
    w.add_argument("--out-md", required=True)
    a = ap.parse_args(argv)

    def load(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError) as exc:
            raise OffsetPostError(f"{path}: unreadable envelope ({exc})") from exc

    try:
        null_env = load(a.null)
        cl_env = load(a.cl)
        rows = record_rows(null_env, cl_env, a.av0_csv)
    except (OffsetPostError, E.InputError) as exc:
        print(f"offset_post.py: {exc}", file=sys.stderr)
        return 2
    Path(a.out_csv).write_text(csv_text(rows), encoding="utf-8")
    Path(a.out_md).write_text(md_text(a.rid, rows, null_env, cl_env, a.av0_csv, a.snapshot), encoding="utf-8")
    print(f"offset_post.py: wrote {a.out_csv} and {a.out_md} ({len(rows)} points)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Stage and summarize the schematic open-loop AC+OP `klt sim` record (#241, #500).

  summarize_klt.py stage <dut-snapshot.spice> <corners-dir>
  summarize_klt.py <record-id> <corners-dir> [<superseded.csv>] <out.csv> <out.md>

`stage` prepares <corners-dir> from sim/open-loop-ac/klt/ for a flat schematic
DUT snapshot, preserving the internal-node operating-point measurements
(vd1_dc_v, vd2_dc_v, vtail_dc_v, vibias_dc_v and their rail fractions) alongside
the port quantities. Extracted `.SUBCKT` netlists hide internal nodes and must
use sim/post-layout/measure_openloop_ac.sh instead.

Summarization reads {ac,op}.envelope.json directly from <corners-dir> (and
writes measurement.json when absent), derives the 45-corner OP sanity verdict
via sim/tools/op_sanity.py and the four ratified rows (av0_db, gbw_hz, pm_deg,
iq_a), and writes <out.csv> and <out.md> with no dependency on the historical
floating-inn CSV unless <superseded.csv> is explicitly supplied for comparison.

Grades each row against the ratified bounds (spec/target-spec.md Sec 2, all
DR-2 worst-case into CL = 2 pF [DR-1]) and lists every failing corner. A miss
is a result and is reported; the exit status stays 0. Loud on a missing or
malformed input (exit 1, nothing written).
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KLT_DIR = HERE / "klt"
sys.path.insert(0, str(HERE.parent / "tools"))
import op_sanity  # noqa: E402

PROCESSES = ("mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs")
TEMPERATURES = (-40, 27, 125)
SUPPLIES = (1.08, 1.20, 1.32)
EXPECTED_POINTS = {
    f"{p}_{t}C_{v:.2f}V": (p, t, v)
    for p in PROCESSES
    for t in TEMPERATURES
    for v in SUPPLIES
}

AC_NAMES = ("av0_db", "gbw_hz", "phase_at_ugf_rad")
OP_NODE_NAMES = ("ivdd_total_a", "vout_dc_v", "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v")
OP_FRAC_NAMES = (
    "op_vcm_frac",
    "op_vout_offset_frac",
    "op_vout_rail_frac",
    "op_vd1_rail_frac",
    "op_vd2_rail_frac",
    "op_vtail_rail_frac",
)
OP_NAMES = OP_NODE_NAMES + OP_FRAC_NAMES

BOUNDS = {  # row: (op, limit, unit)
    "av0_db": (">=", 37.8, "dB"),
    "gbw_hz": (">=", 4.74e6, "Hz"),
    "pm_deg": (">=", 60.0, "deg"),
    "iq_a": ("<=", 119.7e-6, "A"),
}
ROWS = tuple(BOUNDS)
CSV_COLUMNS = (
    "point_id",
    "corner",
    "temp_c",
    "vdd_v",
    "vcm_v",
    "op_pass",
    "vout_dc_v",
    "vd1_dc_v",
    "vd2_dc_v",
    "vtail_dc_v",
    "vibias_dc_v",
    "av0_db",
    "gbw_hz",
    "pm_deg",
    "iq_a",
)
_BANNER_RE = re.compile(r"\bngspice-(\d+)\b")


def old_key(row: dict) -> str:
    t = int(float(row["temp_c"]))
    return f"{row['corner']}_{t}C_{float(row['vdd_v']):.2f}V"


def stage(dut_path: str, corners_dir: str) -> None:
    dut = Path(dut_path).resolve()
    if not dut.is_file() or dut.stat().st_size == 0:
        sys.exit(f"summarize_klt: DUT netlist not found or empty: {dut}")
    dut_text = dut.read_text(encoding="utf-8")
    if re.search(r"^\s*\.subckt\s+", dut_text, re.IGNORECASE | re.MULTILINE):
        sys.exit(
            f"summarize_klt: {dut} is a .SUBCKT netlist without exposed internal nodes; "
            "use sim/post-layout/measure_openloop_ac.sh for extracted-subcircuit runs"
        )
    cdir = Path(corners_dir).resolve()
    cdir.mkdir(parents=True, exist_ok=True)
    rel_dut = Path(os.path.relpath(dut, cdir)).as_posix()
    body_template = (KLT_DIR / "tb_openloop_ac.body.spice").read_text(encoding="utf-8")
    new_body, count = re.subn(
        r"^\.include\s+\S*opamp_core\.spice\s*$",
        f'.include "{rel_dut}"',
        body_template,
        flags=re.MULTILINE,
    )
    if count != 1:
        sys.exit("summarize_klt: bench body template has no single opamp_core.spice .include line")
    (cdir / "tb_openloop_ac.body.spice").write_text(new_body, encoding="utf-8")

    backend_override = os.environ.get("OPENLOOP_KLT_BACKEND") or None
    for fname in ("openloop_ac.request.json", "openloop_op.request.json"):
        req = json.loads((KLT_DIR / fname).read_text(encoding="utf-8"))
        req.pop("_comment", None)
        req["netlist"] = "tb_openloop_ac.body.spice"
        if backend_override:
            req["backend"] = backend_override
        (cdir / fname).write_text(json.dumps(req, indent=2) + "\n", encoding="utf-8")


def _load_envelope(cdir: Path, kind: str, wanted: tuple[str, ...]) -> tuple[dict, dict[str, dict[str, float]]]:
    path = cdir / f"{kind}.envelope.json"
    if not path.is_file():
        sys.exit(f"summarize_klt: missing {path}")
    env = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(env, dict) or "error" in env:
        msg = (env.get("error") or {}).get("message") if isinstance(env, dict) else "not an object"
        sys.exit(f"summarize_klt: {kind}.envelope.json is an error envelope ({msg})")
    for field in ("errored", "inconclusive"):
        if env.get(field) != 0:
            sys.exit(f"summarize_klt: {kind}.envelope.json has {field}={env.get(field)!r}")
    if (env.get("diagnostic_counts") or {}).get("corners_with_diagnostics") != 0:
        sys.exit(f"summarize_klt: {kind}.envelope.json has corners with diagnostics")
    corners = env.get("corners")
    if not isinstance(corners, list) or env.get("corner_count") != len(corners):
        sys.exit(f"summarize_klt: {kind}.envelope.json has malformed corners[]")
    n_pass = sum(1 for c in corners if c.get("status") == "pass")
    n_fail = sum(1 for c in corners if c.get("status") == "fail")
    if (
        n_pass + n_fail != len(corners)
        or env.get("passed") != n_pass
        or env.get("failed") != n_fail
        or env.get("status") != ("pass" if n_fail == 0 else "fail")
    ):
        sys.exit(f"summarize_klt: {kind}.envelope.json aggregate status/counts disagree with corners")

    req_path = cdir / f"openloop_{kind}.request.json"
    expect_batch = True
    if req_path.is_file():
        req = json.loads(req_path.read_text(encoding="utf-8"))
        expect_batch = req.get("backend", "batch") == "batch"
    remote = (env.get("environment") or {}).get("remote") or {}
    if expect_batch and not remote.get("job_id"):
        sys.exit(f"summarize_klt: {kind}.envelope.json has no environment.remote.job_id (not a batch run)")

    indexed: dict[str, dict[str, float]] = {}
    for c in corners:
        if c.get("diagnostics"):
            sys.exit(f"summarize_klt: {kind} corner {c.get('corner_id')} carries diagnostics")
        sup = c.get("supply_v") or {}
        try:
            proc = str(c["process"])
            temp = int(round(float(c["temperature_c"])))
            vdd = float(sup["vdd"])
            vinp = float(sup["vinp"])
        except (KeyError, TypeError, ValueError):
            sys.exit(f"summarize_klt: {kind} corner {c.get('corner_id')} has unreadable grid coordinates")
        pid = f"{proc}_{temp}C_{vdd:.2f}V"
        if pid in indexed:
            sys.exit(f"summarize_klt: {kind}.envelope.json has duplicate corner {pid}")
        vals: dict[str, float] = {"__vdd": vdd, "__vinp": vinp}
        got = {m.get("name"): m for m in c.get("measurements") or []}
        for name in wanted:
            m = got.get(name)
            v = m.get("value") if isinstance(m, dict) else None
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                sys.exit(f"summarize_klt: {kind} corner {pid}: missing or non-finite {name}")
            vals[name] = float(v)
        indexed[pid] = vals
    if set(indexed) != set(EXPECTED_POINTS):
        sys.exit(f"summarize_klt: {kind}.envelope.json has {len(indexed)} corners, expected the 45-point grid")
    return env, indexed


def main(rid: str, cdir: str, old_csv: str | None, out_csv: str, out_md: str) -> None:
    cdir_p = Path(cdir)
    ac_env, ac_pts = _load_envelope(cdir_p, "ac", AC_NAMES)
    op_env, op_pts = _load_envelope(cdir_p, "op", OP_NAMES)

    ea, eo = ac_env.get("environment") or {}, op_env.get("environment") or {}
    if ea.get("engine") != "ngspice" or eo.get("engine") != "ngspice" or ea.get("engine_version") != eo.get("engine_version"):
        sys.exit(
            f"summarize_klt: AC and OP envelopes disagree on simulator "
            f"({ea.get('engine')} {ea.get('engine_version')} vs {eo.get('engine')} {eo.get('engine_version')})"
        )
    version = str(ea.get("engine_version") or "")
    if not re.fullmatch(r"\d+", version):
        sys.exit(f"summarize_klt: unreadable simulator engine_version {version!r}")
    for kind, env in (("ac", ac_env), ("op", op_env)):
        e = env.get("environment") or {}
        for b_label, banner in (
            ("worker banner", ((e.get("remote") or {}).get("worker_environment") or {}).get("simulator", {}).get("version_banner")),
            ("engine_build banner", (e.get("engine_build") or {}).get("version_banner")),
        ):
            if banner is not None and sorted(set(_BANNER_RE.findall(banner))) != [version]:
                sys.exit(f"summarize_klt: {kind}.envelope.json {b_label} disagrees with ngspice-{version}")

    pts: dict[str, dict] = {}
    meas_corners = []
    for pid in sorted(EXPECTED_POINTS):
        proc, temp, vdd = EXPECTED_POINTS[pid]
        a, o = ac_pts[pid], op_pts[pid]
        if a["__vdd"] != o["__vdd"] or a["__vinp"] != o["__vinp"]:
            sys.exit(f"summarize_klt: {pid}: AC and OP supplies disagree")
        vinp = o["__vinp"]
        vcm = vdd / 2.0
        vout = o["vout_dc_v"]
        vd1, vd2, vtail, vibias = o["vd1_dc_v"], o["vd2_dc_v"], o["vtail_dc_v"], o["vibias_dc_v"]
        expected_fracs = {
            "op_vcm_frac": vinp / vdd,
            "op_vout_offset_frac": abs(vout - vcm) / vdd,
            "op_vout_rail_frac": vout / vdd,
            "op_vd1_rail_frac": vd1 / vdd,
            "op_vd2_rail_frac": vd2 / vdd,
            "op_vtail_rail_frac": vtail / vdd,
        }
        for fname, fval in expected_fracs.items():
            if abs(o[fname] - fval) > 1e-9:
                sys.exit(f"summarize_klt: {pid}: {fname}={o[fname]!r} disagrees with raw DC nodes ({fval!r})")
        if a["phase_at_ugf_rad"] > 0.0:
            sys.exit(f"summarize_klt: {pid}: positive phase_at_ugf_rad {a['phase_at_ugf_rad']!r} (wrapped)")
        pm = 180.0 + math.degrees(a["phase_at_ugf_rad"])
        op_ok = int(
            abs(expected_fracs["op_vcm_frac"] - 0.5) <= 1e-4
            and op_sanity.op_sane(vdd, vcm, vout, vd1, vd2, vtail)
        )
        pts[pid] = {
            "corner": proc,
            "temp_c": temp,
            "vdd_v": vdd,
            "vcm_v": vcm,
            "op_pass": op_ok,
            "vout_dc_v": vout,
            "vd1_dc_v": vd1,
            "vd2_dc_v": vd2,
            "vtail_dc_v": vtail,
            "vibias_dc_v": vibias,
            "av0_db": a["av0_db"],
            "gbw_hz": a["gbw_hz"],
            "pm_deg": pm,
            "iq_a": o["ivdd_total_a"],
        }
        meas_corners.append({
            "corner_id": f"{proc}/{vdd:.2f}V/{temp}C",
            "measurements": [
                {"name": "av0_db", "value": a["av0_db"]},
                {"name": "gbw_hz", "value": a["gbw_hz"]},
                {"name": "pm_deg", "value": pm},
                {"name": "iq_a", "value": o["ivdd_total_a"]},
            ],
        })

    meas_path = cdir_p / "measurement.json"
    meas_doc = {"corners": sorted(meas_corners, key=lambda c: c["corner_id"])}
    if meas_path.is_file():
        existing = json.loads(meas_path.read_text(encoding="utf-8"))
        by_cid = {
            c["corner_id"]: {m["name"]: m["value"] for m in c["measurements"]}
            for c in existing.get("corners") or []
        }
        if len(by_cid) != 45:
            sys.exit(f"summarize_klt: existing measurement.json has {len(by_cid)} corners, expected 45")
        for mc in meas_doc["corners"]:
            got = by_cid.get(mc["corner_id"]) or {}
            for m in mc["measurements"]:
                v = got.get(m["name"])
                if not isinstance(v, (int, float)) or abs(v - m["value"]) > 1e-9 * max(1.0, abs(m["value"])):
                    sys.exit(f"summarize_klt: measurement.json disagrees with envelopes at {mc['corner_id']} {m['name']}")
    else:
        meas_path.write_text(json.dumps(meas_doc, indent=1) + "\n", encoding="utf-8")

    old = None
    if old_csv:
        with open(old_csv, newline="", encoding="utf-8") as fh:
            old = {old_key(r): r for r in csv.DictReader(fh)}
        if set(old) != set(pts):
            sys.exit(f"summarize_klt: superseded CSV {old_csv} does not cover the 45-point grid")

    jobs = []
    for kind, env in (("ac", ac_env), ("op", op_env)):
        r = (env.get("environment") or {}).get("remote") or {}
        if r.get("job_id"):
            jobs.append((kind, r["job_id"], r.get("state")))

    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for pid in sorted(pts):
            p = pts[pid]
            w.writerow([
                pid,
                p["corner"],
                p["temp_c"],
                f"{p['vdd_v']:.2f}",
                f"{p['vcm_v']:.6g}",
                p["op_pass"],
                *(f"{p[c]:.6g}" for c in ("vout_dc_v", "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v", "av0_db", "gbw_hz", "pm_deg", "iq_a")),
            ])

    op_bad = [pid for pid in sorted(pts) if pts[pid]["op_pass"] != 1]
    job_line = (
        "Batch jobs: " + ", ".join(f"{k} `{j}` ({s})" for k, j, s in jobs) + "."
        if jobs
        else "Backend: local probe."
    )
    lines = [
        f"# open-loop-ac record {rid} (inn AC-grounded)",
        "",
        f"Generated by `sim/open-loop-ac/run_klt_record.sh` against "
        f"`design/netlist/opamp_core.spice` (snapshot: `netlist-snapshots/{rid}/opamp_core.spice`) "
        f"through `klt sim` (`ngspice-{version}`), with the bench's `Cinn_acgnd inn vss 1` "
        "(1 F AC ground on `inn`) next to `Lbreak = 1e18 H`. Grid: cornerMOSlv.lib "
        "`mos_tt/ss/ff/sf/fs` [DR-1] x `{-40, 27, 125} C` x `{1.08, 1.20, 1.32} V` = 45 points, "
        "into `CL = 2e-12 F` [DR-1].",
        "",
        job_line,
        f"Schematic operating-point sanity (`vd1`, `vd2`, `vtail`, `vout`, `vibias` measured directly): "
        f"{45 - len(op_bad)} of 45 corners pass.",
    ]
    if op_bad:
        lines.append("Operating-point failures: " + ", ".join(op_bad) + ".")
    if old is not None and old_csv:
        lines += [
            "",
            f"**Supersedes** (does not edit) `records/{Path(old_csv).stem}.*`, which measured with "
            "`inn` AC-floating (`Lbreak` only). Do not cite that record's GBW or PM.",
        ]
    lines += [
        "",
        "## Rows against the ratified bounds (45 corners)",
        "",
        "| row | bound | worst | at corner | corners failing | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r, (op, lim, unit) in BOUNDS.items():
        vals = sorted((pts[p][r], p) for p in pts)
        worst = vals[0] if op == ">=" else vals[-1]
        bad = [p for v, p in vals if (v < lim if op == ">=" else v > lim)]
        lines.append(
            f"| {r} | {op} {lim:g} {unit} | {worst[0]:.6g} | {worst[1]} | {len(bad)} of 45 | "
            f"{'PASS' if not bad else 'FAIL'} |"
        )
    for r, (op, lim, _unit) in BOUNDS.items():
        bad = [p for p in sorted(pts) if (pts[p][r] < lim if op == ">=" else pts[p][r] > lim)]
        if bad:
            lines += ["", f"Failing corners for `{r}`: " + ", ".join(f"{p} ({pts[p][r]:.6g})" for p in bad)]
    if old is not None:
        lines += [
            "",
            "## Shift against the superseded floating-inn record",
            "",
            "| row | min change | max change | unit |",
            "|---|---|---|---|",
        ]
        for r, scale, unit in (("av0_db", 1, "dB"), ("gbw_hz", 1e-6, "MHz"), ("pm_deg", 1, "deg"), ("iq_a", 1e6, "uA")):
            col = "iq_a" if r == "iq_a" and "iq_a" in next(iter(old.values())) else {"av0_db": "av0_db", "gbw_hz": "gbw_hz", "pm_deg": "pm_deg", "iq_a": "ivdd_total_a"}[r]
            d = [(pts[p][r] - float(old[p][col])) * scale for p in pts]
            lines.append(f"| {r} | {min(d):+.4g} | {max(d):+.4g} | {unit} |")
    lines += ["", f"Per-point data: `records/{rid}.csv`. Raw envelopes and requests: `corners/{rid}/`.", ""]
    Path(out_md).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "stage":
        stage(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 5:
        main(sys.argv[1], sys.argv[2], None, sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 6:
        main(sys.argv[1], sys.argv[2], sys.argv[3] or None, sys.argv[4], sys.argv[5])
    else:
        sys.exit(__doc__)

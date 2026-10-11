#!/usr/bin/env python3
"""Admission check for cross-record AC joins (issue #224).

Stdlib only; a pure function of files on disk, so it needs no PDK, simulator
or network. A consumer bench (sim/cmrr-psrr, sim/input-offset,
sim/output-swing) imports per-grid-point values (av0_db, ...) measured by an
EARLIER sim/open-loop-ac record. Matching the PVT key alone does not make
that join valid: the source may have been measured on another DUT or under
another model install. Before the consumer's first solver this check
requires, for the selected source record <id> (default newest OR explicit
AC_RECORD_CSV -- same validation either way):

  1. a verified run-time identity sidecar records/<id>.env.json (schema and
     provenance via env_identity.verify). A LEGACY source without one is
     preserved as historical evidence but refused for a new join; nothing
     is guessed or retrofitted into the append-only record.
  2. the source's identity (model closure bytes + OSDI build manifest, via
     identity_sha256, plus release marker, configured pin and simulator)
     equals the consumer's begin capture. Identities are compared, never
     record ids or host install paths.
  3. netlist-snapshots/<id>/opamp_core.spice is byte-identical to the
     consumer's DUT snapshot.
  4. operating conditions match: the load Cload in every source per-point
     rendered netlist equals the consumer's CL, and each row's vcm_v equals
     vcm_frac * vdd_v (common-mode configuration).
  5. for every requested (corner, temp, vdd) point exactly ONE source row,
     consistent point_id, successful source OP (op_pass == 1), and finite
     values in every required column.

On success a provenance document binding the sha256 of the accepted source
CSV, sidecar and DUT snapshot (plus the compatibility basis) is written for
the consumer to publish next to its record. All problems are reported
together. Exit 0 admitted, 1 rejected, 2 usage/IO.

  ac_join_admission.py admit --source-csv F --consumer-env F
      --consumer-snapshot F --consumer-record-id ID --pin sim/pdk.json
      --cl-f 2e-12 --vcm-frac 0.5 --corners A B ... --temps T ... --vdds V ...
      --require-col av0_db ... --out F
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import env_identity as ei  # noqa: E402

SCHEMA = "sg13g2-opamp/ac-join/1"
PROVENANCE_SUFFIX = ".ac-join.json"
_CLOAD_RE = re.compile(r"^\s*Cload\s+\S+\s+\S+\s+(\S+)", re.IGNORECASE | re.MULTILINE)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _num(text):
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _point_key(corner, temp, vdd):
    return (str(corner), round(float(temp), 6), round(float(vdd), 6))


def _identity_diffs(src: dict, cons: dict) -> list[str]:
    """Why two env-identity sidecars describe different environments."""
    errs: list[str] = []
    for key in ("source", "release_tag", "variant"):
        a, b = ei._cfg(src, key), ei._cfg(cons, key)
        if a != b:
            errs.append(f"configured {key} differs (source {a!r}, consumer {b!r})")
    for key, label in (("release_marker", "installed PDK release"), ("ngspice", "simulator")):
        a, b = ei._obs(src, key), ei._obs(cons, key)
        if a != b:
            errs.append(f"{label} differs (source {a!r}, consumer {b!r})")
    fa, fb = ei._closure(src), ei._closure(cons)
    for p in sorted(set(fa) - set(fb)):
        errs.append(f"model file only in the source's closure: {p}")
    for p in sorted(set(fb) - set(fa)):
        errs.append(f"model file only in the consumer's closure: {p}")
    for p in sorted(set(fa) & set(fb)):
        if fa[p] != fb[p]:
            errs.append(f"model file {p} has different bytes (source sha256 {fa[p]}, consumer {fb[p]})")
    a, b = ei._osdi(src, "manifest_sha256"), ei._osdi(cons, "manifest_sha256")
    if a != b:
        errs.append(f"OSDI build manifest differs (source {a}, consumer {b})")
    if src.get("identity_sha256") != cons.get("identity_sha256") and not errs:
        errs.append(f"identity_sha256 differs (source {src.get('identity_sha256')}, consumer {cons.get('identity_sha256')})")
    return errs


def admit(source_csv: Path, consumer_env: dict, consumer_snapshot: Path, consumer_record_id: str,
          pin: dict, cl_f: float, vcm_frac: float, corners, temps, vdds, require_cols) -> tuple[list[str], dict | None]:
    """Return (errors, provenance). provenance is None iff errors is non-empty."""
    errs: list[str] = []
    source_csv = Path(source_csv)
    exp = source_csv.parent.parent
    sid = source_csv.stem
    sidecar_path = source_csv.parent / f"{sid}{ei.SIDECAR_SUFFIX}"
    snap_dir = exp / "netlist-snapshots" / sid
    src_dut = snap_dir / "opamp_core.spice"

    if not source_csv.is_file() or source_csv.stat().st_size == 0:
        return [f"source record {source_csv} is missing or empty"], None

    # 1. identity sidecar (legacy sources are refused, never guessed)
    sidecar = None
    if not sidecar_path.is_file():
        errs.append(
            f"source record {sid} is LEGACY: it has no run-time identity sidecar ({sidecar_path.name}), so its DUT/model "
            "compatibility with this run cannot be established. It stays valid historical evidence but cannot back a "
            "new compatibility-asserted join; regenerate it (see sim/README.md, 'Cross-record AC joins')")
    else:
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errs.append(f"source identity sidecar {sidecar_path.name} is unreadable ({exc})")
        if sidecar is not None:
            v = ei.verify(sidecar, pin, sid, (consumer_env.get("observed") or {}).get("ngspice"))
            errs += [f"source identity sidecar: {e}" for e in v]
            if not v:
                errs += [f"incompatible model environment: {e}" for e in _identity_diffs(sidecar, consumer_env)]

    # 2. DUT bytes
    if not src_dut.is_file():
        errs.append(f"source DUT snapshot {src_dut} is missing, so its circuit bytes cannot be compared")
    elif sha256_file(src_dut) != sha256_file(consumer_snapshot):
        errs.append(
            f"incompatible DUT: source snapshot {src_dut.parent.name}/opamp_core.spice differs from this run's DUT "
            f"(sha256 {sha256_file(src_dut)} vs {sha256_file(consumer_snapshot)})")

    # 3/4. grid rows and operating conditions
    with source_csv.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
        header = rows and list(rows[0].keys())
    need = ["point_id", "corner", "temp_c", "vdd_v", "vcm_v", "op_pass", *require_cols]
    missing = [c for c in need if rows and c not in header]
    if not rows:
        errs.append("source record has no data rows")
    elif missing:
        errs.append(f"source record lacks required column(s): {', '.join(missing)}")
    else:
        index: dict = {}
        for r in rows:
            try:
                k = _point_key(r["corner"], r["temp_c"], r["vdd_v"])
            except ValueError:
                errs.append(f"source row {r.get('point_id')!r} has a non-numeric temp_c/vdd_v")
                continue
            index.setdefault(k, []).append(r)
        for corner in corners:
            for t in temps:
                for v in vdds:
                    pid = f"{corner}_{t}C_{v}V"
                    got = index.get(_point_key(corner, t, v), [])
                    if not got:
                        errs.append(f"grid point {pid}: no source row")
                        continue
                    if len(got) > 1:
                        errs.append(f"grid point {pid}: {len(got)} source rows (must be unique)")
                        continue
                    r = got[0]
                    if r["point_id"] != pid:
                        errs.append(f"grid point {pid}: source point_id is {r['point_id']!r}")
                    if (r["op_pass"] or "").strip() != "1":
                        errs.append(f"grid point {pid}: source operating point failed (op_pass={r['op_pass']!r})")
                    for c in require_cols:
                        if _num(r[c]) is None:
                            errs.append(f"grid point {pid}: source {c} is not finite ({r[c]!r})")
                    vcm, vdd = _num(r["vcm_v"]), float(v)
                    if vcm is None or abs(vcm - vcm_frac * vdd) > 1e-9:
                        errs.append(f"grid point {pid}: common-mode config differs (source vcm_v {r['vcm_v']!r}, "
                                    f"this run {vcm_frac * vdd:.6g} = {vcm_frac} x VDD)")
                    pnet = snap_dir / f"{pid}.spice"
                    if not pnet.is_file():
                        errs.append(f"grid point {pid}: source rendered netlist {pnet.name} is missing, load cannot be checked")
                    else:
                        m = _CLOAD_RE.search(pnet.read_text(encoding="utf-8", errors="replace"))
                        cl = _num(m.group(1)) if m else None
                        if cl is None:
                            errs.append(f"grid point {pid}: no readable Cload in source netlist {pnet.name}")
                        elif not math.isclose(cl, cl_f, rel_tol=1e-9):
                            errs.append(f"grid point {pid}: load differs (source CL {cl:g} F, this run {cl_f:g} F)")
        known = {_point_key(c, t, v) for c in corners for t in temps for v in vdds}
        extra = sorted(k for k in index if k not in known)
        if extra:
            errs.append(f"source has {len(extra)} grid point(s) outside the requested grid (e.g. {extra[0]}); "
                        "grids must match exactly")

    if errs:
        return errs, None
    return [], {
        "schema": SCHEMA,
        "consumer_record_id": consumer_record_id,
        "source": {
            "record_id": sid,
            "csv_sha256": sha256_file(source_csv),
            "env_sidecar_sha256": sha256_file(sidecar_path),
            "dut_snapshot_sha256": sha256_file(src_dut),
            "identity_sha256": sidecar["identity_sha256"],
        },
        "consumer": {
            "dut_snapshot_sha256": sha256_file(consumer_snapshot),
            "identity_sha256": consumer_env["identity_sha256"],
        },
        "basis": {
            "dut_bytes": "identical",
            "model_environment": "identity_sha256, release marker, configured pin, simulator all equal",
            "cl_f": cl_f,
            "vcm_frac_of_vdd": vcm_frac,
            "points": len(corners) * len(temps) * len(vdds),
            "required_columns": list(require_cols),
            "rows": "unique per requested point, op_pass=1, required columns finite",
        },
    }


REMEDIATION = (
    "ac_join_admission: rejected before any solver ran. To regenerate a compatible source, run "
    "sim/open-loop-ac/run_pvt_sweep.sh under the same DUT and model install as this run, then re-run "
    "this bench (it picks the newest record) or select it with AC_RECORD_CSV=<that record's .csv>. "
    "See sim/README.md, 'Cross-record AC joins'."
)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("admit")
    a.add_argument("--source-csv", type=Path, required=True)
    a.add_argument("--consumer-env", type=Path, required=True)
    a.add_argument("--consumer-snapshot", type=Path, required=True)
    a.add_argument("--consumer-record-id", required=True)
    a.add_argument("--pin", type=Path, required=True)
    a.add_argument("--cl-f", type=float, required=True)
    a.add_argument("--vcm-frac", type=float, default=0.5)
    a.add_argument("--corners", nargs="+", required=True)
    a.add_argument("--temps", nargs="+", required=True)
    a.add_argument("--vdds", nargs="+", required=True)
    a.add_argument("--require-col", nargs="+", default=["av0_db"])
    a.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args(argv)
    try:
        pin = json.loads(ns.pin.read_text(encoding="utf-8"))
        env = json.loads(ns.consumer_env.read_text(encoding="utf-8"))
        errs, prov = admit(ns.source_csv, env, ns.consumer_snapshot, ns.consumer_record_id, pin, ns.cl_f,
                           ns.vcm_frac, ns.corners, ns.temps, ns.vdds, ns.require_col)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ac_join_admission: {exc}", file=sys.stderr)
        return 2
    if errs:
        print(f"ac_join_admission: AC source {ns.source_csv} REJECTED:", file=sys.stderr)
        for e in errs:
            print(f"ac_join_admission:   {e}", file=sys.stderr)
        print(REMEDIATION, file=sys.stderr)
        return 1
    if ns.out.exists():
        print(f"ac_join_admission: refusing to overwrite {ns.out}", file=sys.stderr)
        return 2
    ns.out.write_text(ei.canonical_json(prov), encoding="utf-8")
    print(f"ac_join_admission: admitted {prov['source']['record_id']} (csv {prov['source']['csv_sha256'][:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

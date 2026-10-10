#!/usr/bin/env bash
# Per-draw CMRR table (issue #107): a NO-SIMULATION post-processor.
#
#   sim/cmrr-mismatch/make_draws_csv.sh --record-csv records/<id>.csv \
#       [--samples-dir corners/<id>] [--out records/<id>-draws.csv] \
#       [--seed-base 260000]
#
# Reads the raw ngspice echo files <point_id>_mc_samples.txt (lines
# `OP <k> ...` and `AC <k> acm10m acm01 acm1k`) that the bench already
# commits, plus the per-point summary record (av0_db, vcm_v), and writes one
# row per draw:
#
#   point_id,corner,temp_c,vdd_v,draw_index,draw_seed,status,fail_reason,
#   acm10m_db,acm1k_db,av0_db,cmrr_db
#
# status is PASS or EXCLUDED; fail_reason is op_fail or plateau_fail, using
# the SAME per-draw gates as stat_point() in run_cmrr_mismatch_mc.sh
# (OP_RAIL_FRAC / OP_MID_FRAC / PLATEAU_TOL_DB, same defaults), so excluded
# draws stay visible instead of being dropped. draw_seed is the point's
# setseed (MC_SEED_BASE + grid index): the bench seeds once per point and
# resets per sample, so every draw of a point shares it; draw_index is the
# sample index. av0_db is the joined SYSTEMATIC Av0 of the grid point
# (README: deliberately not re-measured per draw), repeated per row.
# cmrr_db = av0_db - acm10m_db, as in stat_point.
#
# Round-trip gate: before the file is published, per-point mc_n, mc_n_ok,
# mc_n_excluded, op_fail, plateau_fail, acm_lin_mean, acm_lin_sigma,
# cmrr_3sigma_db, cmrr_db_min are recomputed FROM THE DRAWS and compared with
# the record CSV at its printed precision (%.6g); any mismatch exits 1 and
# nothing is written. run_cmrr_mismatch_mc.sh Phase 5 calls this same script,
# so the post-processor and the harness cannot diverge. Never overwrites an
# existing --out (append-only evidence): exits 3. Output is deterministic.
#
# This is NOT a per-draw pass/fail statistic: the ratified DR-0004 bound is
# an aggregate (+3 sigma of Acm). The draws file does not discharge it and
# asserts no per-draw limit or target_yield.
set -euo pipefail

record_csv=""; samples_dir=""; out=""; seed_base="${MC_SEED_BASE:-260000}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --record-csv) record_csv="$2"; shift 2 ;;
    --samples-dir) samples_dir="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --seed-base) seed_base="$2"; shift 2 ;;
    *) echo "make_draws_csv.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "${record_csv}" || ! -s "${record_csv}" ]]; then
  echo "make_draws_csv.sh: --record-csv <records/<id>.csv> is required and must exist" >&2; exit 2
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rid="$(basename "${record_csv}" .csv)"
rec_dir="$(cd "$(dirname "${record_csv}")" && pwd)"
[[ -n "${samples_dir}" ]] || samples_dir="${here}/corners/${rid}"
[[ -n "${out}" ]] || out="${rec_dir}/${rid}-draws.csv"
if [[ -e "${out}" ]]; then
  echo "make_draws_csv.sh: ${out} exists; evidence is append-only, refusing to overwrite" >&2; exit 3
fi
[[ -d "${samples_dir}" ]] || { echo "make_draws_csv.sh: no samples dir ${samples_dir}" >&2; exit 2; }

tmp="${out}.tmp.$$"; trap 'rm -f "${tmp}"' EXIT
python3 -I - "${record_csv}" "${samples_dir}" "${tmp}" "${seed_base}" \
  "${OP_RAIL_FRAC:-0.02}" "${OP_MID_FRAC:-0.15}" "${PLATEAU_TOL_DB:-0.05}" "${here}" <<'PYEOF'
import csv, math, os, sys

rec, sdir, out, seed_base, rail_frac, mid_frac, plateau_tol, lib_dir = sys.argv[1:9]
sys.path.insert(0, lib_dir)
import mc_samples  # strict shared parser (issue #174), also used by run_cmrr_mismatch_mc.sh
seed_base = int(seed_base)
rail_frac, mid_frac, plateau_tol = float(rail_frac), float(mid_frac), float(plateau_tol)

def g6(x):
    return f"{x:.6g}"

def read_samples(path):
    try:
        n, ops, acs, toks = mc_samples.read_samples_raw(path)
    except (mc_samples.SampleError, OSError) as e:
        raise SystemExit(f"make_draws_csv.sh: INVALID SAMPLES {e}")
    return n, ops, acs, toks

errors = []
rows_out = []
header = ["point_id", "corner", "temp_c", "vdd_v", "draw_index", "draw_seed",
          "status", "fail_reason", "acm10m_db", "acm1k_db", "av0_db", "cmrr_db"]

for pidx, r in enumerate(csv.DictReader(open(rec))):
    pid = r["point_id"]
    vdd = float(r["vdd_v"]); vcm = float(r["vcm_v"]); av0_db = float(r["av0_db"])
    n, ops, acs, toks = read_samples(os.path.join(sdir, f"{pid}_mc_samples.txt"))
    rail_lo, rail_hi = rail_frac * vdd, vdd - rail_frac * vdd
    lin, cm = [], []
    op_fail = plateau_fail = 0
    for k in range(n):
        vout, vd1, vd2, vtail = ops[k][:4]
        a10, a01, a1k = acs[k]
        ok = abs(vout - vcm) <= mid_frac * vdd
        for node in (vout, vd1, vd2, vtail):
            if not (rail_lo <= node <= rail_hi):
                ok = False
        reason = ""
        if not ok:
            op_fail += 1; reason = "op_fail"
        elif abs(a10 - a01) > plateau_tol:
            plateau_fail += 1; reason = "plateau_fail"
        cmrr = av0_db - a10
        if not reason:
            lin.append(10 ** (a10 / 20.0)); cm.append(cmrr)
        rows_out.append([pid, r["corner"], r["temp_c"], r["vdd_v"], k, seed_base + pidx,
                         "EXCLUDED" if reason else "PASS", reason,
                         toks[k][0], toks[k][2], r["av0_db"], g6(cmrr)])
    n_ok = len(lin)
    if n_ok < 2:
        errors.append(f"{pid}: fewer than 2 passing draws"); continue
    mu = sum(lin) / n_ok
    sd = math.sqrt(sum((x - mu) ** 2 for x in lin) / (n_ok - 1))
    got = {
        "mc_n": str(n), "mc_n_ok": str(n_ok), "mc_n_excluded": str(n - n_ok),
        "op_fail": str(op_fail), "plateau_fail": str(plateau_fail),
        "acm_lin_mean": g6(mu), "acm_lin_sigma": g6(sd),
        "cmrr_3sigma_db": g6(av0_db - 20 * math.log10(mu + 3 * sd)),
        "cmrr_db_min": g6(min(cm)),
    }
    for key, val in got.items():
        if val != r[key]:
            errors.append(f"{pid}: {key} from draws = {val}, record = {r[key]}")

if errors:
    for e in errors[:20]:
        print("make_draws_csv.sh: ROUND-TRIP MISMATCH " + e, file=sys.stderr)
    sys.exit(1)

with open(out, "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows_out)
worst = min(rows_out, key=lambda x: float(x[11]) if x[6] == "PASS" else math.inf)
print(f"make_draws_csv.sh: {len(rows_out)} draws, round-trip OK; worst single draw "
      f"{worst[11]} dB at {worst[0]} (draw {worst[4]})")
PYEOF
mv "${tmp}" "${out}"
echo "make_draws_csv.sh: wrote ${out}"

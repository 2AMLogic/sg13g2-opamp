#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/input-offset/run_offset_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH plus the
# OSDI device models sim/tools/build-osdi.sh builds; does not require xschem
# or klt at run time (design/netlist/opamp_core.spice is committed,
# pre-netlisted -- see design/README.md for the xschem command that
# regenerates it from design/opamp_core.sch). Full methodology, what this
# bench measures and does not, and the pinned PDK revision are documented in
# README.md and sim/pdk.json -- read those first if a result here looks
# surprising.
#
# Deterministic (corner-only, NO Monte Carlo / NO mismatch draw) DC
# input-referred offset characterization of design/opamp_core.spice across
# the full cornerMOSlv.lib process x temperature x supply grid (mos_tt/ss/
# ff/sf/fs x -40/27/125 C x 1.08/1.20/1.32 V = 45 points), by two
# independent methods per point:
#
#   1. PRIMARY -- open-loop differential-input null sweep
#      (testbench/tb_offset_null.spice.tmpl): sweep Vid = V(inp) - V(inn)
#      with the input common mode pinned at Vcm = VDD/2, and report the Vid
#      at which Vout crosses Vcm. Two passes: a coarse locate sweep, then a
#      fine sweep centered on the coarse crossing, so the reported number is
#      demonstrably converged rather than an artifact of one step size.
#   2. CROSS-CHECK -- closed-loop DC error referred back through the DC gain
#      sim/open-loop-ac/ measured at the SAME grid point
#      (testbench/tb_offset_cl.spice.tmpl).
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- same
# fleet convention as sim/open-loop-ac/run_pvt_sweep.sh and
# sim/gm-id-characterization/run_gmid_sweep.sh in this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_offset_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_offset_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_offset_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_offset_sweep.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  echo "run_offset_sweep.sh:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
  exit 3
fi

# --- Open-loop AC record cross-reference ---------------------------------
# The closed-loop cross-check method refers its measured output DC error
# back through the DC gain measured for the SAME grid point by
# sim/open-loop-ac/ (issue #11's own wording: "the measured DC gain
# (sim/open-loop-ac/records/*.csv's Av0 column, same corner)"). Default to
# the newest committed record there; override with AC_RECORD_CSV=<path>.
if [[ -z "${AC_RECORD_CSV:-}" ]]; then
  AC_RECORD_CSV=""
  while IFS= read -r _f; do AC_RECORD_CSV="${_f}"; done < <(
    find "${SIM_DIR}/open-loop-ac/records" -maxdepth 1 -name '*.csv' 2>/dev/null | sort
  )
fi
if [[ -z "${AC_RECORD_CSV}" || ! -s "${AC_RECORD_CSV}" ]]; then
  echo "run_offset_sweep.sh: no sim/open-loop-ac/records/*.csv found -- the closed-loop" >&2
  echo "run_offset_sweep.sh: cross-check needs that experiment's per-point Av0 column." >&2
  exit 3
fi
AC_RECORD_ID="$(basename "${AC_RECORD_CSV}" .csv)"

OSDI_DIR="${SG13G2_OSDI_DIR}"
REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

DUT_NETLIST_SNAPSHOT="${SNAPSHOTS_OUT}/opamp_core.spice"
cp "${DUT_NETLIST_SRC}" "${DUT_NETLIST_SNAPSHOT}"

# --- Sweep grid ----------------------------------------------------------
# Process corner grid: cornerMOSlv.lib's five sections [DR-1]; temperature x
# supply grid from spec/target-spec.md Sec 1. Identical 45-point grid to
# sim/open-loop-ac/, by construction -- the two benches' records are meant
# to be joined point-by-point on point_id.
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

# Coarse locate pass: +-100 mV of differential input is far wider than any
# plausible systematic offset of this topology, and wide enough that the
# output is hard-railed at both ends (which is what makes the single
# Vout = Vcm crossing unambiguous). Records v(out) only -- see the
# template's "RECORDED VECTORS" note.
COARSE_START="-0.1"
COARSE_STOP="0.1"
COARSE_STEP="500e-6"
COARSE_VECTORS="v(out)"
# Fine pass: re-sweep a +-0.5 mV window around the coarse crossing at 4 uV,
# so the reported null is read from a curve sampled 125x finer than the
# locate pass. Agreement between the two passes is reported per point
# (vos_coarse_fine_delta_v) as a convergence check -- and in practice the
# coarse pass already lands within a few hundred nanovolts, so the half-span
# is three orders of magnitude of headroom, not a tight fit. Records the
# full node set, so the operating point at the null is committed evidence;
# the span/step pair is also what sets this experiment's corners/ footprint
# (~50 kB per point), which is why it is no wider than it needs to be.
FINE_HALFSPAN="5e-4"
FINE_STEP="4e-6"
FINE_VECTORS="v(out) v(d1) v(d2) v(tail) v(ibias) i(vdd)"

echo "point_id,corner,temp_c,vdd_v,vcm_v,op_pass,xcheck_pass,vos_null_v,vos_abs_v,vos_coarse_fine_delta_v,av_local_db,vid_sample_v,vout_sample_v,vd1_sample_v,vd2_sample_v,vtail_sample_v,vibias_sample_v,ivdd_sample_a,vout_cl_v,vout_cl_err_v,av0_db_ac_record,vos_closed_loop_v,vos_method_delta_v" > "${CSV_OUT}.raw"

total=0
passed=0
op_fail_points=()
xcheck_fail_points=()
sim_fail_points=()

render() {
  # render <template> <out> <corner> <temp> <vdd> <vcm> <extra sed args...>
  local tmpl="$1" out="$2" corner="$3" temp="$4" vdd="$5" vcm="$6"
  shift 6
  sed \
    -e "s|@@PDK_ROOT@@|${PDK_ROOT}|g" \
    -e "s|@@PDK@@|${PDK}|g" \
    -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
    -e "s|@@MOS_SECTION@@|${corner}|g" \
    -e "s|@@TEMP_C@@|${temp}|g" \
    -e "s|@@VDD_V@@|${vdd}|g" \
    -e "s|@@VCM_V@@|${vcm}|g" \
    -e "s|@@CL_F@@|${CL_F}|g" \
    -e "s|@@DUT_NETLIST@@|${DUT_NETLIST_SNAPSHOT}|g" \
    "$@" \
    "${tmpl}" > "${out}"
}

sim_broken() {
  # sim_broken <rc> <log> <required-output-file>
  local rc="$1" log="$2" outfile="$3"
  [[ ${rc} -ne 0 ]] && return 0
  [[ -s "${outfile}" ]] || return 0
  grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence" "${log}" && return 0
  return 1
}

for corner in "${CORNERS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      total=$((total + 1))
      point_id="${corner}_${temp}C_${vdd}V"
      vcm="$(python3 -c "print(${vdd}/2)")"

      coarse_net="${SNAPSHOTS_OUT}/${point_id}_null_coarse.spice"
      coarse_log="${CORNERS_OUT}/${point_id}_null_coarse.log"
      coarse_csv="${CORNERS_OUT}/${point_id}_null_coarse.csv"
      fine_net="${SNAPSHOTS_OUT}/${point_id}_null_fine.spice"
      fine_log="${CORNERS_OUT}/${point_id}_null_fine.log"
      fine_csv="${CORNERS_OUT}/${point_id}_null_fine.csv"
      cl_net="${SNAPSHOTS_OUT}/${point_id}_closedloop.spice"
      cl_log="${CORNERS_OUT}/${point_id}_closedloop.log"

      # --- pass 1: coarse locate sweep ---------------------------------
      render "${EXPERIMENT_DIR}/testbench/tb_offset_null.spice.tmpl" "${coarse_net}" \
        "${corner}" "${temp}" "${vdd}" "${vcm}" \
        -e "s|@@PASS_LABEL@@|coarse|g" \
        -e "s|@@VID_START@@|${COARSE_START}|g" \
        -e "s|@@VID_STOP@@|${COARSE_STOP}|g" \
        -e "s|@@VID_STEP@@|${COARSE_STEP}|g" \
        -e "s|@@WRDATA_VECTORS@@|${COARSE_VECTORS}|g" \
        -e "s|@@SWEEP_CSV@@|${coarse_csv}|g"

      rc=0
      ngspice -b "${coarse_net}" > "${coarse_log}" 2>&1 || rc=$?
      if sim_broken "${rc}" "${coarse_log}" "${coarse_csv}"; then
        echo "run_offset_sweep.sh: SIM FAILED ${point_id} coarse pass (rc=${rc}) -- see ${coarse_log}" >&2
        sim_fail_points+=("${point_id}:coarse")
        continue
      fi

      vos_coarse="$(python3 - "${coarse_csv}" "${vcm}" <<'PYEOF'
import sys
# wrdata column layout: one (scale,value) pair per requested vector, in the
# order requested by the testbench's own wrdata line. The coarse pass
# requests v(out) alone, so col0 = Vid (v(out)'s own scale) and
# col1 = v(out). See sim/gm-id-characterization/README.md "wrdata column
# layout" for this gotcha documented once for the whole tree.
path, target = sys.argv[1], float(sys.argv[2])
vid, vout = [], []
for line in open(path):
    p = line.split()
    if len(p) < 2:
        continue
    vid.append(float(p[0]))
    vout.append(float(p[1]))
crossings = []
for i in range(1, len(vid)):
    a, b = vout[i - 1] - target, vout[i] - target
    if (a <= 0 < b) or (a >= 0 > b):
        frac = (target - vout[i - 1]) / (vout[i] - vout[i - 1])
        crossings.append(vid[i - 1] + frac * (vid[i] - vid[i - 1]))
if len(crossings) != 1:
    print(f"nan {len(crossings)}")
else:
    print(f"{crossings[0]:.9g} 1")
PYEOF
)"
      n_cross_coarse="${vos_coarse##* }"
      vos_coarse="${vos_coarse%% *}"
      if [[ "${vos_coarse}" == "nan" ]]; then
        echo "run_offset_sweep.sh: ANALYSIS FAILED ${point_id} -- coarse sweep has ${n_cross_coarse} Vout=Vcm crossings (expected exactly 1), see ${coarse_csv}" >&2
        sim_fail_points+=("${point_id}:coarse_crossings=${n_cross_coarse}")
        continue
      fi

      # --- pass 2: fine sweep centered on the coarse crossing -----------
      fine_start="$(python3 -c "print(${vos_coarse} - ${FINE_HALFSPAN})")"
      fine_stop="$(python3 -c "print(${vos_coarse} + ${FINE_HALFSPAN})")"
      render "${EXPERIMENT_DIR}/testbench/tb_offset_null.spice.tmpl" "${fine_net}" \
        "${corner}" "${temp}" "${vdd}" "${vcm}" \
        -e "s|@@PASS_LABEL@@|fine|g" \
        -e "s|@@VID_START@@|${fine_start}|g" \
        -e "s|@@VID_STOP@@|${fine_stop}|g" \
        -e "s|@@VID_STEP@@|${FINE_STEP}|g" \
        -e "s|@@WRDATA_VECTORS@@|${FINE_VECTORS}|g" \
        -e "s|@@SWEEP_CSV@@|${fine_csv}|g"

      rc=0
      ngspice -b "${fine_net}" > "${fine_log}" 2>&1 || rc=$?
      if sim_broken "${rc}" "${fine_log}" "${fine_csv}"; then
        echo "run_offset_sweep.sh: SIM FAILED ${point_id} fine pass (rc=${rc}) -- see ${fine_log}" >&2
        sim_fail_points+=("${point_id}:fine")
        continue
      fi

      # --- pass 3: closed-loop cross-check ------------------------------
      render "${EXPERIMENT_DIR}/testbench/tb_offset_cl.spice.tmpl" "${cl_net}" \
        "${corner}" "${temp}" "${vdd}" "${vcm}"
      rc=0
      ngspice -b "${cl_net}" > "${cl_log}" 2>&1 || rc=$?
      if [[ ${rc} -ne 0 ]] || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence" "${cl_log}"; then
        echo "run_offset_sweep.sh: SIM FAILED ${point_id} closed-loop pass (rc=${rc}) -- see ${cl_log}" >&2
        sim_fail_points+=("${point_id}:closedloop")
        continue
      fi
      vout_cl="$(grep '^CL_VOUT ' "${cl_log}" | awk '{print $2}')"
      if [[ -z "${vout_cl}" ]]; then
        echo "run_offset_sweep.sh: SIM FAILED ${point_id} -- missing CL_VOUT line, see ${cl_log}" >&2
        sim_fail_points+=("${point_id}:closedloop_noop")
        continue
      fi

      # Column looked up by HEADER NAME, not by a hardcoded index, so this
      # keeps working if sim/open-loop-ac/ ever adds a column.
      av0_db_ac="$(awk -F, -v pid="${point_id}" '
        NR==1 { for (i = 1; i <= NF; i++) if ($i == "av0_db") col = i; next }
        col && $1 == pid { print $col }' "${AC_RECORD_CSV}")"
      [[ -n "${av0_db_ac}" ]] || av0_db_ac="nan"

      # --- per-point post-processing ------------------------------------
      # Reads the fine sweep, interpolates the null, reports the simulated
      # operating point at the swept sample nearest that null, fits the
      # local small-signal gain, applies the per-point sanity rule
      # (README.md "Per-point sanity checks"), and computes the closed-loop
      # cross-check value.
      row="$(python3 - "${fine_csv}" "${vcm}" "${vdd}" "${vos_coarse}" "${vout_cl}" "${av0_db_ac}" <<'PYEOF'
import math, sys

fine_path = sys.argv[1]
vcm = float(sys.argv[2])
vdd = float(sys.argv[3])
vos_coarse = float(sys.argv[4])
vout_cl = float(sys.argv[5])
av0_db_ac = float(sys.argv[6]) if sys.argv[6] != "nan" else float("nan")

# wrdata column layout (see the coarse-pass note above): 6 vectors ->
# 12 columns, each a (scale, value) pair in wrdata argument order:
# v(out), v(d1), v(d2), v(tail), v(ibias), i(vdd).
VCOL = {"out": 1, "d1": 3, "d2": 5, "tail": 7, "ibias": 9, "ivdd": 11}
vid = []
cols = {k: [] for k in VCOL}
for line in open(fine_path):
    p = line.split()
    if len(p) < 12:
        continue
    vid.append(float(p[0]))
    for k, c in VCOL.items():
        cols[k].append(float(p[c]))

vout = cols["out"]
idx = None
for i in range(1, len(vid)):
    a, b = vout[i - 1] - vcm, vout[i] - vcm
    if (a <= 0 < b) or (a >= 0 > b):
        idx = i
        break

def fail(reason):
    # Field order/count must match the success print at the bottom of this
    # block exactly (19 whitespace-separated fields, status last), because
    # the caller `read`s them positionally.
    av0_txt = "nan" if av0_db_ac != av0_db_ac else f"{av0_db_ac:.9g}"
    fields = ["0", "0"] + ["nan"] * 11 + [f"{vout_cl:.9g}", "nan", av0_txt,
                                          "nan", "nan", reason]
    print(" ".join(fields))
    raise SystemExit(0)

if idx is None:
    fail("fine_sweep_no_crossing")
# The crossing must sit strictly inside the fine window, not on its edge --
# an edge crossing would mean the coarse locate pass was wrong by more than
# the fine half-span and the fine read is not trustworthy.
if idx <= 1 or idx >= len(vid) - 1:
    fail("fine_sweep_crossing_at_edge")

frac = (vcm - vout[idx - 1]) / (vout[idx] - vout[idx - 1])
vos = vid[idx - 1] + frac * (vid[idx] - vid[idx - 1])

# Operating point AT the null. Rather than interpolating every node, report
# the simulator's own solution at the swept sample nearest the null (at most
# half a fine step, 2 uV of Vid, away from it) -- these columns are then
# unmodified ngspice output, not a derived quantity. v(out) at that sample
# lands within ~(half step x gain) of Vcm, which is itself a visible
# confirmation that the interpolated null is where the record says it is.
s = idx - 1 if abs(vid[idx - 1] - vos) <= abs(vid[idx] - vos) else idx
vid_sample = vid[s]
vout_sample = cols["out"][s]
vd1 = cols["d1"][s]
vd2 = cols["d2"][s]
vtail = cols["tail"][s]
vibias = cols["ibias"][s]
ivdd = -cols["ivdd"][s]        # i(vdd) is into the source; report current drawn

# Local small-signal DC gain: least-squares slope of Vout vs Vid over the
# samples within +-0.2 mV of the null (about 100 fine-sweep points), which
# is both the gain used for nothing downstream and an honest sanity number
# -- a railed/degenerate "null" shows up here as a near-zero slope.
win = 0.2e-3
xs, ys = [], []
for x, y in zip(vid, vout):
    if abs(x - vos) <= win:
        xs.append(x)
        ys.append(y)
n = len(xs)
if n >= 3:
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    av_local = sxy / sxx if sxx > 0 else float("nan")
else:
    av_local = (vout[idx] - vout[idx - 1]) / (vid[idx] - vid[idx - 1])
av_local_db = 20 * math.log10(av_local) if av_local == av_local and av_local > 0 else float("nan")

# --- per-point sanity rule (README.md "Per-point sanity checks") --------
rail_lo, rail_hi = 0.02 * vdd, 0.98 * vdd
op_pass = 1
for node in (vd1, vd2, vtail, vout_sample):
    if not (rail_lo <= node <= rail_hi):
        op_pass = 0
# The null must be a real amplifying point, not a flat/railed region.
if not (av_local == av_local and av_local >= 10.0):
    op_pass = 0
# ... and it must be well inside the coarse locate window.
if abs(vos) >= 0.9 * 0.1:
    op_pass = 0

# --- closed-loop cross-check -------------------------------------------
vout_cl_err = vout_cl - vcm
if av0_db_ac == av0_db_ac:
    av_ac = 10 ** (av0_db_ac / 20.0)
    vos_cl = -vout_cl_err * (1.0 + av_ac) / av_ac
    method_delta = vos - vos_cl
    # The two methods are independent measurements of the same quantity;
    # they must agree to the CMRR-order difference between their input
    # common-mode conditions, not merely be the same order of magnitude.
    tol = max(200e-6, 0.05 * abs(vos))
    xcheck_pass = 1 if abs(method_delta) <= tol else 0
else:
    vos_cl = float("nan")
    method_delta = float("nan")
    xcheck_pass = 0

def f(x):
    return "nan" if x != x else f"{x:.9g}"

print(" ".join([
    str(op_pass), str(xcheck_pass), f(vos), f(abs(vos)), f(vos - vos_coarse),
    f(av_local_db), f(vid_sample), f(vout_sample), f(vd1), f(vd2), f(vtail),
    f(vibias), f(ivdd),
    f(vout_cl), f(vout_cl_err), f(av0_db_ac), f(vos_cl), f(method_delta), "ok",
]))
PYEOF
)"

      read -r op_pass xcheck_pass vos_null vos_abs vos_cf_delta av_local_db \
        vid_sample vout_sample vd1s vd2s vtails vibiass ivdds \
        vout_cl_out vout_cl_err av0_db_out vos_cl vos_method_delta status <<<"${row}"

      if [[ "${status}" != "ok" ]]; then
        echo "run_offset_sweep.sh: ANALYSIS FAILED ${point_id} -- ${status}, see ${fine_csv}" >&2
        sim_fail_points+=("${point_id}:${status}")
        continue
      fi

      echo "${point_id},${corner},${temp},${vdd},${vcm},${op_pass},${xcheck_pass},${vos_null},${vos_abs},${vos_cf_delta},${av_local_db},${vid_sample},${vout_sample},${vd1s},${vd2s},${vtails},${vibiass},${ivdds},${vout_cl_out},${vout_cl_err},${av0_db_out},${vos_cl},${vos_method_delta}" >> "${CSV_OUT}.raw"

      [[ "${op_pass}" == "1" ]] || op_fail_points+=("${point_id}")
      [[ "${xcheck_pass}" == "1" ]] || xcheck_fail_points+=("${point_id}")
      passed=$((passed + 1))
    done
  done
done

if [[ ${passed} -eq 0 ]]; then
  echo "run_offset_sweep.sh: no points passed -- refusing to write a summary." >&2
  exit 1
fi

mv "${CSV_OUT}.raw" "${CSV_OUT}"

{
  echo "op_pass_count,${passed} of ${total}, op_sane failures: ${#op_fail_points[@]} (${op_fail_points[*]:-none})"
  echo "xcheck_failures,${#xcheck_fail_points[@]} (${xcheck_fail_points[*]:-none})"
  echo "sim_fail_count,${#sim_fail_points[@]} (${sim_fail_points[*]:-none})"
  echo "ac_record_cross_referenced,${AC_RECORD_ID}"
} > "${CORNERS_OUT}/sanity_checks.txt"

n_rows=$(($(wc -l < "${CSV_OUT}") - 1))
expected=$(( ${#CORNERS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} ))
if [[ "${n_rows}" -ne "${expected}" ]]; then
  echo "run_offset_sweep.sh: WARNING -- ${n_rows} rows written, expected ${expected} (${#sim_fail_points[@]} failures)" >&2
fi

SUMMARY="$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys

rows = list(csv.DictReader(open(sys.argv[1])))

def num(r, k):
    try:
        v = float(r[k])
    except (ValueError, KeyError):
        return None
    return v if v == v else None

vals = [(num(r, "vos_null_v"), r) for r in rows if num(r, "vos_null_v") is not None]
worst = max(vals, key=lambda t: abs(t[0]))
best = min(vals, key=lambda t: abs(t[0]))
print(f"worst_abs_vos_v: {abs(worst[0]):.6g} ({worst[0]:+.6g}) at {worst[1]['point_id']}")
print(f"best_abs_vos_v: {abs(best[0]):.6g} ({best[0]:+.6g}) at {best[1]['point_id']}")
print(f"vos_range_v: {min(v for v, _ in vals):+.6g} .. {max(v for v, _ in vals):+.6g}")

deltas = [(num(r, "vos_method_delta_v"), r) for r in rows if num(r, "vos_method_delta_v") is not None]
if deltas:
    wd = max(deltas, key=lambda t: abs(t[0]))
    print(f"worst_method_delta_v: {wd[0]:+.6g} at {wd[1]['point_id']} "
          f"(open-loop null minus closed-loop cross-check)")
cf = [(num(r, "vos_coarse_fine_delta_v"), r) for r in rows if num(r, "vos_coarse_fine_delta_v") is not None]
if cf:
    wcf = max(cf, key=lambda t: abs(t[0]))
    print(f"worst_coarse_fine_delta_v: {wcf[0]:+.6g} at {wcf[1]['point_id']} "
          f"(fine-pass null minus coarse-pass null)")

# Per-process-corner worst |Vos|, so the binding-corner claim in the record
# is readable directly rather than inferred from 45 rows.
by_corner = {}
for v, r in vals:
    by_corner.setdefault(r["corner"], []).append((abs(v), r["point_id"], v))
for c in ("mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs"):
    if c in by_corner:
        a, pid, sv = max(by_corner[c])
        print(f"worst_abs_vos_{c}: {a:.6g} ({sv:+.6g}) at {pid}")
PYEOF
)"

cat > "${MD_OUT}" <<EOF
# input-offset record ${RECORD_ID}

Generated by \`sim/input-offset/run_offset_sweep.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`).

Deterministic, corner-only DC input-referred offset: **no Monte Carlo, no
mismatch deck, no random draw**. Every matched device pair in the DUT
netlist is instantiated identically, so this record measures the
**systematic** offset of the topology at each PVT point and nothing else.

Grid: cornerMOSlv.lib \`mos_tt/ss/ff/sf/fs\` [DR-1] x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${expected} points
(the same grid, and the same \`point_id\` keys, as
\`sim/open-loop-ac/records/${AC_RECORD_ID}.csv\`, whose \`av0_db\` column
this record's closed-loop cross-check refers its output error back
through). ${passed} of ${total} points measured successfully;
${#sim_fail_points[@]} failure(s) (${sim_fail_points[*]:-none});
${#op_fail_points[@]} point(s) failed the per-point sanity check
(${op_fail_points[*]:-none}); ${#xcheck_fail_points[@]} point(s) failed the
two-method agreement check (${xcheck_fail_points[*]:-none}).

## Summary

\`\`\`
${SUMMARY}
\`\`\`

Sign convention: \`Vos = V(inp) - V(inn)\` required to bring \`Vout\` to
mid-rail (\`VDD/2\`), with \`inp\` the non-inverting input — a **positive**
\`Vos\` means \`inp\` must be held above \`inn\`.

Full per-point data (both methods, the simulated operating point at the
null, local DC gain at the null, and the cross-referenced \`Av0\`) is in
\`records/${RECORD_ID}.csv\`. Raw per-point ngspice logs and the full
coarse/fine \`Vid\` sweep curves are in \`corners/${RECORD_ID}/\`.
EOF

echo "run_offset_sweep.sh: wrote ${CSV_OUT} and ${MD_OUT} (${passed}/${total} points, ${#op_fail_points[@]} op-sanity failures, ${#xcheck_fail_points[@]} cross-check failures)"

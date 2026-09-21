#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/output-swing/run_swing_sweep.sh
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
# DC output-swing characterization of design/opamp_core.spice across the
# full cornerMOSlv.lib process x temperature x supply grid (mos_tt/ss/ff/
# sf/fs x -40/27/125 C x 1.08/1.20/1.32 V = 45 points), from the
# open-loop differential DC transfer curve (testbench/tb_swing.spice.tmpl):
# sweep Vid = V(inp) - V(inn) with the input common mode pinned at
# Vcm = VDD/2, and report the linear region's rail-ward bounds -- the
# maximum/minimum DC output voltage at which the amplifier still tracks
# its input to the -6 dB incremental-gain criterion (README.md "The swing
# criterion") -- as headroom from VDD and VSS, so the figure is directly
# comparable across the supply grid. Two passes per grid point: a coarse
# locate sweep (Vid +- 100 mV, 500 uV step) that also reads both
# hard-clipped plateau levels, then a fine sweep (Vid +- 25 mV around the
# coarse crossing, 10 uV step) that resolves both -6 dB boundaries. The
# fine pass's peak incremental gain, mid-swing supply current and
# Vout = Vcm crossing input are cross-checked per point against the
# already-merged sim/open-loop-ac/ (Av0, Iq) and sim/input-offset/ (Vos)
# records at the same point_id -- logged, not gated (README.md
# "Cross-checks").
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- same
# fleet convention as sim/open-loop-ac/run_pvt_sweep.sh and
# sim/input-offset/run_offset_sweep.sh in this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_swing_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_swing_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_swing_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_swing_sweep.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  echo "run_swing_sweep.sh:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
  exit 3
fi

# --- Committed sibling-record cross-references ---------------------------
# The record's peak incremental gain, mid-swing Iq and Vid-crossing columns
# are cross-checked against the per-point av0_db / ivdd_total_a columns of
# the newest committed sim/open-loop-ac/ record and the vos_null_v column
# of the newest committed sim/input-offset/ record -- joined on point_id,
# the same 45-point grid every bench in this tree shares. The AC record is
# REQUIRED (this bench's numbers describe the same grid points; a checkout
# that has the AC bench but not its record is not the tree the evidence
# describes). The offset record is used when present. Override either with
# AC_RECORD_CSV=... / OFFSET_RECORD_CSV=....
latest_csv_in() {
  local _found=""
  while IFS= read -r _f; do _found="${_f}"; done < <(
    find "$1" -maxdepth 1 -name '*.csv' 2>/dev/null | sort
  )
  printf '%s' "${_found}"
}
if [[ -z "${AC_RECORD_CSV:-}" ]]; then
  AC_RECORD_CSV="$(latest_csv_in "${SIM_DIR}/open-loop-ac/records")"
fi
if [[ -z "${AC_RECORD_CSV}" || ! -s "${AC_RECORD_CSV}" ]]; then
  echo "run_swing_sweep.sh: no sim/open-loop-ac/records/*.csv found -- the peak-gain" >&2
  echo "run_swing_sweep.sh: cross-check column needs that experiment's per-point Av0 column." >&2
  exit 3
fi
if [[ -z "${OFFSET_RECORD_CSV:-}" ]]; then
  OFFSET_RECORD_CSV="$(latest_csv_in "${SIM_DIR}/input-offset/records")"
fi
if [[ -z "${OFFSET_RECORD_CSV}" || ! -s "${OFFSET_RECORD_CSV}" ]]; then
  OFFSET_RECORD_CSV=""
fi

csv_lookup() {
  # csv_lookup <file> <header> <point_id> -- column looked up by HEADER
  # NAME, not a hardcoded index, so this keeps working if the source record
  # ever adds a column. Empty output if not found.
  awk -F, -v hdr="$2" -v pid="$3" '
    NR==1 { for (i = 1; i <= NF; i++) if ($i == hdr) col = i; next }
    col && $1 == pid { print $col }' "$1" 2>/dev/null || true
}

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
# sim/open-loop-ac/ and sim/input-offset/, by construction -- the benches'
# records are meant to be joined point-by-point on point_id.
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

# Coarse locate pass: +-100 mV of differential input is the same window
# sim/input-offset/ uses to prove the Vout = Vcm crossing unique, and wide
# enough that the output is hard-clipped at both ends -- which is what
# makes both plateau levels readable and the crossing unambiguous.
# Records v(out) only (see the template's "RECORDED VECTORS" note).
COARSE_START="-0.1"
COARSE_STOP="0.1"
COARSE_STEP="500e-6"
COARSE_VECTORS="v(out)"

# Fine pass: +-25 mV of differential input around the coarse crossing.
# The linear region spans ~(output span)/Av0) of Vid -- measured Av0 is
# 77.6-181 V/V across this grid (sim/open-loop-ac/), so the region is well
# under 12 mV of Vid even at the lowest-gain corner; +-25 mV brackets
# both -6 dB boundaries with >4x margin, while the 10 uV step keeps each
# boundary read to ~1-2 mV of output volts at the worst gain. Records
# v(out) and i(vdd) (supply current at the mid-swing bias).
FINE_HALFSPAN="25e-3"
FINE_STEP="10e-6"
FINE_VECTORS="v(out) i(vdd)"

# -6 dB incremental-gain criterion: the linear region is the contiguous
# run of sweep segments around the peak-gain segment whose two-point
# incremental gain dVout/dVid stays >= this fraction of the peak -- the
# boundary passed in as an env knob only so a reviewer can re-run with a
# stricter/looser criterion and mint a NEW (append-only) record; the
# shipped number this record's README describes is 0.5 (-6 dB).
CRITERION_FRAC="0.5"

echo "point_id,corner,temp_c,vdd_v,vcm_v,op_pass,vout_max_track_v,vout_min_track_v,headroom_hi_v,headroom_lo_v,swing_span_v,vout_clip_high_v,vout_clip_low_v,vos_crossing_v,vos_offset_record_v,vos_delta_v,peak_inc_gain_v_v,av0_ac_record_db,av0_ratio,ivdd_center_a,ivdd_ac_record_a,ivdd_ratio" > "${CSV_OUT}.raw"

total=0
passed=0
op_fail_points=()
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

      coarse_net="${SNAPSHOTS_OUT}/${point_id}_coarse.spice"
      coarse_log="${CORNERS_OUT}/${point_id}_coarse.log"
      coarse_csv="${CORNERS_OUT}/${point_id}_coarse.csv"
      fine_net="${SNAPSHOTS_OUT}/${point_id}_fine.spice"
      fine_log="${CORNERS_OUT}/${point_id}_fine.log"
      fine_csv="${CORNERS_OUT}/${point_id}_fine.csv"

      # --- pass 1: coarse locate sweep ---------------------------------
      render "${EXPERIMENT_DIR}/testbench/tb_swing.spice.tmpl" "${coarse_net}" \
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
        echo "run_swing_sweep.sh: SIM FAILED ${point_id} coarse pass (rc=${rc}) -- see ${coarse_log}" >&2
        sim_fail_points+=("${point_id}:coarse")
        continue
      fi

      # --- pass 2: fine sweep centered on the coarse crossing -----------
      # Coarse post-processing in one python read: the unique Vout = Vcm
      # crossing (same uniqueness rule as sim/input-offset/'s coarse pass)
      # and both hard-clipped plateau levels.
      read -r vos_coarse n_cross_coarse clip_high clip_low plateau_ok < <(python3 - "${coarse_csv}" "${vcm}" <<'PYEOF'
import sys
# wrdata column layout: one (scale,value) pair per requested vector, in the
# order requested by the testbench's own wrdata line. The coarse pass
# requests v(out) alone, so col0 = Vid (v(out)'s own scale) and
# col1 = v(out). See sim/gm-id-characterization/README.md "wrdata column
# layout" for this gotcha documented once for the whole tree.
path, target = sys.argv[1], float(sys.argv[2])
clip_high = clip_low = "nan"
plateau_ok = 0
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
# Clipped plateau levels = the extremes the output actually reached at the
# far ends of the (hard-railed) coarse window; plateau_ok additionally
# requires both window ends to sit on a CLIPPED, not amplifying, part of
# the curve, judged by slope ratio rather than absolute flatness: the
# incremental slope over the outermost stretch of each end must be <= 1%
# of the curve's own peak segment slope (a mid-curve point -- the linear
# region is 500+ segments wide -- so the comparison is self-calibrating
# per corner). An absolute mV-flatness rule was tried first and is WRONG
# at hot corners: at 125 C the "railed" output still creeps ~0.3 mV per
# mV of Vid (leakage-fed), which is ~1e-6 of the peak gain -- clearly
# clipped -- but breaches any absolute millivolt threshold.
def seg_gain(i):
    dv = vout[i] - vout[i - 1]
    di = vid[i] - vid[i - 1]
    return dv / di if di != 0 else 0.0
if vout:
    clip_high = max(vout)
    clip_low = min(vout)
    flat_n = max(2, len(vid) // 50)
    peak = abs(max((seg_gain(i) for i in range(1, len(vid))), key=abs)) if len(vid) > 2 else 0.0
    if peak > 0:
        slope_lo = abs(vout[flat_n] - vout[0]) / abs(vid[flat_n] - vid[0])
        slope_hi = abs(vout[-1] - vout[-1 - flat_n]) / abs(vid[-1] - vid[-1 - flat_n])
        plateau_ok = 1 if (slope_lo <= 0.01 * peak and slope_hi <= 0.01 * peak) else 0
if len(crossings) != 1:
    print(f"nan {len(crossings)} {clip_high:.9g} {clip_low:.9g} {plateau_ok}")
else:
    print(f"{crossings[0]:.9g} 1 {clip_high:.9g} {clip_low:.9g} {plateau_ok}")
PYEOF
)
      if [[ "${n_cross_coarse}" != "1" || "${vos_coarse}" == "nan" ]]; then
        echo "run_swing_sweep.sh: ANALYSIS FAILED ${point_id} -- coarse sweep has ${n_cross_coarse} Vout=Vcm crossings (expected exactly 1), see ${coarse_csv}" >&2
        sim_fail_points+=("${point_id}:coarse_crossings=${n_cross_coarse}")
        continue
      fi

      fine_start="$(python3 -c "print(${vos_coarse} - ${FINE_HALFSPAN})")"
      fine_stop="$(python3 -c "print(${vos_coarse} + ${FINE_HALFSPAN})")"
      render "${EXPERIMENT_DIR}/testbench/tb_swing.spice.tmpl" "${fine_net}" \
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
        echo "run_swing_sweep.sh: SIM FAILED ${point_id} fine pass (rc=${rc}) -- see ${fine_log}" >&2
        sim_fail_points+=("${point_id}:fine")
        continue
      fi

      # --- sibling-record cross-reference inputs ------------------------
      av0_db_ac="$(csv_lookup "${AC_RECORD_CSV}" av0_db "${point_id}")"
      [[ -n "${av0_db_ac}" ]] || av0_db_ac="nan"
      ivdd_ac="$(csv_lookup "${AC_RECORD_CSV}" ivdd_total_a "${point_id}")"
      [[ -n "${ivdd_ac}" ]] || ivdd_ac="nan"
      vos_off="nan"
      if [[ -n "${OFFSET_RECORD_CSV}" ]]; then
        vos_off="$(csv_lookup "${OFFSET_RECORD_CSV}" vos_null_v "${point_id}")"
        [[ -n "${vos_off}" ]] || vos_off="nan"
      fi

      # --- per-point post-processing ------------------------------------
      # Reads the fine sweep, applies the -6 dB incremental-gain criterion
      # to both rail-ward boundaries of the linear region, reads the
      # mid-swing operating point, and applies the per-point sanity rule
      # (README.md "Per-point sanity checks").
      row="$(python3 - "${fine_csv}" "${vdd}" "${vcm}" "${clip_high}" "${clip_low}" "${plateau_ok}" "${vos_coarse}" "${av0_db_ac}" "${ivdd_ac}" "${vos_off}" "${CRITERION_FRAC}" <<'PYEOF'
import math, sys

fine_path = sys.argv[1]
vdd = float(sys.argv[2])
vcm = float(sys.argv[3])
clip_high = float(sys.argv[4])
clip_low = float(sys.argv[5])
plateau_ok = int(sys.argv[6])
vos_coarse = float(sys.argv[7])
av0_db_ac = float(sys.argv[8]) if sys.argv[8] != "nan" else float("nan")
ivdd_ac = float(sys.argv[9]) if sys.argv[9] != "nan" else float("nan")
vos_off = float(sys.argv[10]) if sys.argv[10] != "nan" else float("nan")
criterion = float(sys.argv[11])

# wrdata column layout (see the coarse-pass note above): 2 vectors ->
# 4 columns, each a (scale, value) pair in wrdata argument order:
# v(out), i(vdd).
vid, vout, ivdd = [], [], []
for line in open(fine_path):
    p = line.split()
    if len(p) < 4:
        continue
    vid.append(float(p[0]))
    vout.append(float(p[1]))
    ivdd.append(float(p[3]))

def fmt(x):
    return "nan" if x != x else f"{x:.9g}"

def fail(reason):
    # Emit exactly the same 17 whitespace-separated fields as the success
    # print below (the caller `read`s them positionally), with op_pass=0
    # and every not-yet-derived quantity as nan; the human-readable reason
    # goes to stderr so the bash caller's own log names it.
    print(reason, file=sys.stderr)
    fields = ["0",
              "nan", "nan", "nan", "nan", "nan",
              f"{clip_high:.9g}", f"{clip_low:.9g}",
              fmt(vos_coarse), fmt(vos_off), "nan", "nan",
              fmt(av0_db_ac), "nan", "nan", fmt(ivdd_ac), "nan"]
    print(" ".join(fields))
    raise SystemExit(0)

n = len(vid)
if n < 10:
    fail("fine_sweep_too_short")

idx = None
for i in range(1, n):
    a, b = vout[i - 1] - vcm, vout[i] - vcm
    if (a <= 0 < b) or (a >= 0 > b):
        idx = i
        break
if idx is None:
    fail("fine_sweep_no_crossing")
# The crossing must sit strictly inside the fine window, not on its edge --
# an edge crossing would mean the coarse locate pass was wrong by more than
# the fine half-span and the fine read is not trustworthy (same rule as
# sim/input-offset/).
if idx <= 1 or idx >= n - 1:
    fail("fine_sweep_crossing_at_edge")

# Monotonic S-curve check: v(out) must never decrease (beyond fp wiggle) --
# a non-monotonic transfer curve would make "the linear region" ambiguous.
for i in range(1, n):
    if vout[i] < vout[i - 1] - 1e-9:
        fail("fine_sweep_non_monotonic")

# Incremental gain per segment; peak segment and the contiguous block of
# segments around it still above the criterion fraction of the peak (the
# -6 dB rule -- README.md "The swing criterion").
g = [(vout[i] - vout[i - 1]) / (vid[i] - vid[i - 1]) for i in range(1, n)]
peak_i = max(range(len(g)), key=lambda i: g[i])
g_pk = g[peak_i]
if not (g_pk == g_pk and g_pk >= 10.0):
    fail("peak_gain_implausible")
lo = peak_i
while lo > 0 and g[lo - 1] >= criterion * g_pk:
    lo -= 1
hi = peak_i
while hi < len(g) - 1 and g[hi + 1] >= criterion * g_pk:
    hi += 1
# The -6 dB region must be strictly inside the fine window: an edge-touching
# region means the fine window truncated the boundary and the reported
# swing bound is an artifact of the window, not the amplifier.
if lo <= 0 or hi >= len(g) - 1:
    fail("linear_region_touches_window_edge")

# Samples inside the linear region: segment i spans samples i..i+1.
vout_region = vout[lo:hi + 2]
vout_max_track = max(vout_region)
vout_min_track = min(vout_region)
headroom_hi = vdd - vout_max_track
headroom_lo = vout_min_track
span = vout_max_track - vout_min_track

# Mid-swing operating point: the simulator's own solution at the swept
# sample nearest the Vout = Vcm crossing (at most half a fine step, 5 uV
# of Vid, away) -- unmodified ngspice output, not a derived quantity,
# same convention as sim/input-offset/'s `*_sample_*` columns. The supply
# current there cross-checks sim/open-loop-ac/'s per-point Iq (same bias,
# same grid point).
s = idx - 1 if abs(vid[idx - 1] - vos_coarse) <= abs(vid[idx] - vos_coarse) else idx
ivdd_center = -ivdd[s]              # i(vdd) is into the source; report drawn

# Crossing (interpolated in the fine pass) vs the offset record's own
# null for this point -- an independent bench's measurement of the same
# quantity (README.md "Cross-checks"). Logged, never gated.
frac = (vcm - vout[idx - 1]) / (vout[idx] - vout[idx - 1])
vos_crossing = vid[idx - 1] + frac * (vid[idx] - vid[idx - 1])
vos_delta = abs(vos_crossing - vos_off) if vos_off == vos_off else float("nan")

# Cross-check ratios (logged, never gated): peak incremental DC gain vs
# the AC bench's 1 Hz Av0 at this point; mid-swing Iq vs the AC bench's
# total Iq at this point.
if av0_db_ac == av0_db_ac:
    av_ac = 10 ** (av0_db_ac / 20.0)
    av0_ratio = g_pk / av_ac
else:
    av0_ratio = float("nan")
ivdd_ratio = ivdd_center / ivdd_ac if ivdd_ac == ivdd_ac and ivdd_ac != 0 else float("nan")

# --- per-point sanity rule (README.md "Per-point sanity checks") --------
op_pass = 1
# Coarse window must actually have clipped on both ends for the plateau
# levels to mean anything.
if plateau_ok != 1:
    op_pass = 0
# Plateaus must straddle mid-rail and contain the tracking bounds.
if not (clip_low < vcm < clip_high):
    op_pass = 0
if not (clip_low < vout_min_track <= vout_max_track < clip_high):
    op_pass = 0
# Headrooms must be physical: strictly positive and strictly inside the
# supply span (a bound outside the rails is an extraction artifact).
if not (0.0 < headroom_hi < vdd and 0.0 < headroom_lo < vdd):
    op_pass = 0
# The tracking bounds must sit a real distance inside the hard-clip
# plateaus -- the -6 dB boundary by construction lies before the plateau.
if not (vout_max_track < clip_high - 1e-6 and vout_min_track > clip_low + 1e-6):
    op_pass = 0
# Peak incremental gain must be a real amplifying point (same floor as
# sim/input-offset/'s rule).
if not (g_pk == g_pk and g_pk >= 10.0):
    op_pass = 0

fields = [str(op_pass),
          f"{vout_max_track:.9g}", f"{vout_min_track:.9g}",
          f"{headroom_hi:.9g}", f"{headroom_lo:.9g}", f"{span:.9g}",
          f"{clip_high:.9g}", f"{clip_low:.9g}",
          f"{vos_crossing:.9g}", fmt(vos_off), fmt(vos_delta),
          f"{g_pk:.9g}", fmt(av0_db_ac), fmt(av0_ratio),
          f"{ivdd_center:.9g}", fmt(ivdd_ac), fmt(ivdd_ratio)]
print(" ".join(fields))
PYEOF
)"

      # Split the python block's whitespace-separated fields positionally.
      read -r op_pass vout_max_track vout_min_track headroom_hi headroom_lo swing_span \
        vout_clip_high vout_clip_low vos_crossing vos_off_v vos_delta \
        peak_inc_gain av0_db_ac_v av0_ratio ivdd_center ivdd_ac_v ivdd_ratio <<<"${row}"

      echo "${point_id},${corner},${temp},${vdd},${vcm},${op_pass},${vout_max_track},${vout_min_track},${headroom_hi},${headroom_lo},${swing_span},${vout_clip_high},${vout_clip_low},${vos_crossing},${vos_off_v},${vos_delta},${peak_inc_gain},${av0_db_ac_v},${av0_ratio},${ivdd_center},${ivdd_ac_v},${ivdd_ratio}" >> "${CSV_OUT}.raw"

      if [[ "${op_pass}" != "1" ]]; then
        echo "run_swing_sweep.sh: SANITY FAILED ${point_id} -- reason printed above; see ${fine_csv} and ${CORNERS_OUT}/${point_id}_coarse.csv" >&2
        op_fail_points+=("${point_id}")
      fi

      passed=$((passed + 1))
    done
  done
done

if [[ ${passed} -eq 0 ]]; then
  echo "run_swing_sweep.sh: no points passed -- refusing to write a summary." >&2
  exit 1
fi

mv "${CSV_OUT}.raw" "${CSV_OUT}"

{
  echo "op_pass_count,${passed} of ${total}, op_sane failures: ${#op_fail_points[@]} (${op_fail_points[*]:-none})"
  echo "sim_fail_count,${#sim_fail_points[@]} (${sim_fail_points[*]:-none})"
} > "${CORNERS_OUT}/sanity_checks.txt"

# --- Completeness: all 45 (corner, temp, vdd) cells must have run. -------
n_rows=$(($(wc -l < "${CSV_OUT}") - 1))
expected=$(( ${#CORNERS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} ))
if [[ "${n_rows}" -ne "${expected}" ]]; then
  echo "run_swing_sweep.sh: WARNING -- ${n_rows} rows written, expected ${expected} (${#sim_fail_points[@]} sim failures)" >&2
fi

# --- Worst-corner summary (per metric) for the record's README-style table.
WORST="$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys

rows = list(csv.DictReader(open(sys.argv[1])))
def numeric(rows, key):
    out = []
    for r in rows:
        try:
            v = float(r[key])
        except ValueError:
            continue
        if v == v:  # not NaN
            out.append((v, r))
    return out

hh = numeric(rows, "headroom_hi_v")
hl = numeric(rows, "headroom_lo_v")
span = numeric(rows, "swing_span_v")

def line(label, t, agg):
    if t is None:
        print(f"{label}: n/a")
        return
    v, r = t
    print(f"{label}: {v:.4g} at {r['point_id']}{agg}")

line("worst_headroom_hi_v", min(hh, key=lambda t: t[0]) if hh else None, "")
line("worst_headroom_lo_v", min(hl, key=lambda t: t[0]) if hl else None, "")
line("worst_swing_span_v", min(span, key=lambda t: t[0]) if span else None, "")
line("best_swing_span_v", max(span, key=lambda t: t[0]) if span else None, "")
if hh and hl and span:
    w_hi = min(hh, key=lambda t: t[0])[1]["point_id"]
    w_lo = min(hl, key=lambda t: t[0])[1]["point_id"]
    w_sp = min(span, key=lambda t: t[0])[1]["point_id"]
    print(f"binding_point_overlap, hi={w_hi} lo={w_lo} span={w_sp}")
PYEOF
)"

cat > "${MD_OUT}" <<EOF
# output-swing record ${RECORD_ID}

Generated by \`sim/output-swing/run_swing_sweep.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`).

Grid: cornerMOSlv.lib \`mos_tt/ss/ff/sf/fs\` [DR-1] x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${expected} points,
into \`CL = 2 pF\` [DR-1]. Method: open-loop differential DC transfer curve
(input common mode pinned at \`Vcm = VDD/2\`), the linear region's rail-ward
bounds read at the **-6 dB incremental-gain** criterion (README.md "The
swing criterion"). ${passed} of ${total} points simulated successfully;
${#sim_fail_points[@]} simulation failure(s) (${sim_fail_points[*]:-none});
${#op_fail_points[@]} point(s) failed the per-point sanity check
(${op_fail_points[*]:-none}) -- see README.md "Per-point sanity checks"
for what that check does and does not verify.

## Worst-corner summary

\`\`\`
${WORST}
\`\`\`

Full per-point data (tracking bounds per rail, headroom from VDD/VSS,
swing span, hard-clipped plateau reach, mid-swing operating point, peak
incremental DC gain, and the per-point cross-checks against
\`sim/open-loop-ac/\` and \`sim/input-offset/\` at the same point_id) is in
\`records/${RECORD_ID}.csv\`. Raw per-point ngspice logs and the coarse +
fine transfer-curve data each swing number was measured from are in
\`corners/${RECORD_ID}/\`.
EOF

echo "run_swing_sweep.sh: wrote ${CSV_OUT} and ${MD_OUT} (${passed}/${total} points, ${#op_fail_points[@]} op-sanity failures)"

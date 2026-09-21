#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/input-cmr/run_cmr_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH plus the
# OSDI device models sim/tools/build-osdi.sh builds; does not require
# xschem or klt at run time (design/netlist/opamp_core.spice is committed,
# pre-netlisted -- see design/README.md for the xschem command that
# regenerates it from design/opamp_core.sch). Full methodology, what this
# bench measures and does not, and the pinned PDK revision are documented
# in README.md and sim/pdk.json -- read those first if a result here looks
# surprising.
#
# Input common-mode range (ICMR) characterization of
# design/netlist/opamp_core.spice across the full cornerMOSlv.lib process x
# temperature x supply grid (mos_tt/ss/ff/sf/fs x -40/27/125 C x
# 1.08/1.20/1.32 V = 45 points): sweep the input common mode with the
# differential input pinned at exactly zero (both inputs tied via a 0 V
# source), record the input stage's internal DC state per sample
# (v(tail) = Vds of the tail device M5, v(d1)/v(d2) = the pair drain
# nodes, v(ibias) = M5's gate bias, total Vdd current), and report per
# corner the maximal Vcm interval around VDD/2 in which every
# input-stage-relevant device provably stays saturated:
#   lower bound -- the Vcm where v(tail) falls through the MEASURED
#     saturation voltage of M5 (its gate bias Vgs5 = v(ibias) is Vcm
#     invariant, so one same-bias replica probe per grid point fixes the
#     requirement; the knee of the Id5(Vds) curve is read at the first Vds
#     whose incremental slope has fallen to SLOPE_FRAC=10% of the curve's
#     maximum triode slope -- README.md "The saturation-edge probes");
#   upper bound -- the Vcm where the pair's Vds compresses to its own
#     saturation requirement Vgs - Vth, with Vth measured per this repo's
#     gm/ID constant-current convention at the pair's true body bias at
#     the bound. Because Vth depends on the body bias (v(tail), which
#     itself moves ~1:1 with the bound), the requirement is resolved by a
#     bounded fixed-point loop: a probe's Vth re-locates the coarse
#     crossing, whose tail bias re-seeds the next probe's body bias,
#     until the crossing moves < 2 mV (contraction is ~0.1x per round, so
#     two rounds after the centre seed typically suffice; hard cap four
#     rounds), then the fine pass resolves the bound and a final probe
#     AT the recorded bound verifies the loop closed (hi_converged -- the
#     residual shift is recorded per point). The condition Vds >= Vgs -
#     Vth rearranges on DUT observables to v(d1) - Vcm >= -Vth, which is
#     what the crossing search applies.
# Both bounds are located with a coarse full-span pass (5 mV step) then
# resolved with a fine pass (250 uV step) per side, mirroring
# sim/output-swing/'s coarse-then-fine convention. Why open-loop, not a
# closed-loop buffer sweep, and why measured replica probes instead of
# model op-point parameters: README.md "What this bench measures" and the
# testbench templates' method blocks. The lo/hi bound values join the
# committed sim/output-swing/ record per point_id to state the
# closed-loop-buffer usable interval (the intersection with the output
# stage's own reach), and the centre operating point joins
# sim/open-loop-ac/ per point_id -- logged, not gated (README.md
# "Cross-checks").
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- same
# fleet convention as sim/open-loop-ac/run_pvt_sweep.sh and siblings.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_cmr_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_cmr_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_cmr_sweep.sh: ngspice not on PATH." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_cmr_sweep.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_cmr_sweep.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  echo "run_cmr_sweep.sh:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
  exit 3
fi

# --- Committed sibling-record cross-references ---------------------------
# The bound values join the output-swing record's per-point tracking
# bounds (for the closed-loop usable interval), and the centre op point
# joins the open-loop-ac record's per-point DC operating point. Both are
# REQUIRED: this bench's rows describe the same 45 point_ids, and a
# checkout with a bench but without its record is not the tree the
# evidence describes.
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
  echo "run_cmr_sweep.sh: no sim/open-loop-ac/records/*.csv found -- the op-point cross-check" >&2
  echo "run_cmr_sweep.sh: columns need that experiment's per-point vtail/vd1/vd2/vibias columns." >&2
  exit 3
fi
if [[ -z "${SWING_RECORD_CSV:-}" ]]; then
  SWING_RECORD_CSV="$(latest_csv_in "${SIM_DIR}/output-swing/records")"
fi
if [[ -z "${SWING_RECORD_CSV}" || ! -s "${SWING_RECORD_CSV}" ]]; then
  echo "run_cmr_sweep.sh: no sim/output-swing/records/*.csv found -- the buffer-usable-interval" >&2
  echo "run_cmr_sweep.sh: columns need that experiment's per-point vout_max_track/lo columns." >&2
  exit 3
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

# --- Replica-geometry lockstep guard ------------------------------------
# tb_cmr_mech.spice.tmpl replicates the DUT's XM1/XM2 (w=3.2u l=0.13u), M5
# and Mbias (both w=2.2u l=0.52u) exactly; if the DUT netlist is ever
# re-sized, the replicas must be re-checked against this file first.
geometry_guard() {
  local net="$1" ok=1
  grep -qE '^XM1 d1 inn tail vss sg13_lv_nmos w=3\.2u l=0\.13u ' "${net}" || ok=0
  grep -qE '^XM2 d2 inp tail vss sg13_lv_nmos w=3\.2u l=0\.13u ' "${net}" || ok=0
  grep -qE '^XM5 tail ibias vss vss sg13_lv_nmos w=2\.2u l=0\.52u ' "${net}" || ok=0
  grep -qE '^XMbias ibias ibias vss vss sg13_lv_nmos w=2\.2u l=0\.52u ' "${net}" || ok=0
  [[ ${ok} -eq 1 ]]
}
if ! geometry_guard "${DUT_NETLIST_SNAPSHOT}"; then
  echo "run_cmr_sweep.sh: ${DUT_NETLIST_SNAPSHOT} no longer carries the geometries" >&2
  echo "run_cmr_sweep.sh: tb_cmr_mech.spice.tmpl replicates (XM1/XM2 3.2u/0.13u, XM5/XMbias 2.2u/0.52u)." >&2
  echo "run_cmr_sweep.sh: Re-check the replica template against the resized DUT before re-running." >&2
  exit 3
fi

# --- Sweep grid ----------------------------------------------------------
# Process corner grid: cornerMOSlv.lib's five sections [DR-1]; temperature x
# supply grid from spec/target-spec.md Sec 1. Identical 45-point grid to
# sim/open-loop-ac/ and every sibling bench, by construction -- the
# benches' records are joined point-by-point on point_id.
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

# Coarse pass: the full usable supply span (VDD approached within 50 mV on
# each side, so both hard degenerate ends are provably inside the window
# and every relevant crossing is bracketed) at 5 mV. Fine passes resolve
# each bound at 250 uV, well below the value's own reproducibility
# (README.md "Two passes (coarse locate, then fine read)").
COARSE_EDGE="50e-3"
COARSE_STEP="5e-3"
FINE_HALFSPAN="12e-3"
FINE_STEP="250e-6"

# Tail-replica Id5(Vds) sweep resolution.
MECH_VDS_STEP="2.5e-3"
# M5 saturation-knee rule: the first Vds whose incremental slope has
# fallen to SLOPE_FRAC of the curve's maximum (triodeRon) slope. An env
# knob only so a reviewer can re-run with a stricter/looser criterion and
# mint a NEW (append-only) record; the shipped number this record's
# README describes is 0.10.
SLOPE_FRAC="0.10"

# Pair-replica constant-current threshold, this repo's gm/ID convention:
# Id = 100 nA * (W/L) at the replica's own geometry (w=3.2u l=0.13u),
# log-Id linear interpolation of the bracketing (vgs, id) pair -- exactly
# sim/gm-id-characterization/run_gmid_sweep.sh's Vth definition, re-run
# here at the DUT's own body bias, corner and temperature.
PAIR_W_L="3.2/0.13"
VTH_CC_CURRENT_A="$(python3 -c "print(100e-9 * (${PAIR_W_L}))")"
MECH_VG_STEP="5e-3"

echo "point_id,corner,temp_c,vdd_v,vcm_v,op_pass,icmr_lo_v,icmr_hi_v,icmr_span_v,buffer_use_lo_v,buffer_use_hi_v,buffer_use_span_v,contains_vcm,centre_gap_lo_v,mech_lo,mech_hi,hi_round_shift_v,hi_converged,vdsat5_meas_v,vth_pair_cc_v,vthreq_pair_v,vtail_lo_v,vds1_lo_v,vds2_lo_v,margin_m5_lo_v,margin_pair_lo_v,vtail_hi_v,vgs1_hi_v,vsb1_hi_v,vds1_hi_v,vds2_hi_v,margin_m5_hi_v,margin_pair_hi_v,ivdd_lo_a,ivdd_hi_a,ratio_ivdd_lo_c_a,op_vout_v,op_vtail_v,op_vd1_v,op_vd2_v,op_vibias_v,op_ivdd_a,x_vtail_ac_delta_v,x_vd1_ac_delta_v,x_vd2_ac_delta_v,x_vibias_ac_delta_v,swing_vout_max_track_v,swing_vout_min_track_v" > "${CSV_OUT}.raw"

total=0
sim_fail_points=()
op_fail_points=()

render() {
  # render <template> <out> <corner> <temp> <vdd> <extra sed args...>
  local tmpl="$1" out="$2" corner="$3" temp="$4" vdd="$5"
  shift 5
  sed \
    -e "s|@@PDK_ROOT@@|${PDK_ROOT}|g" \
    -e "s|@@PDK@@|${PDK}|g" \
    -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
    -e "s|@@MOS_SECTION@@|${corner}|g" \
    -e "s|@@TEMP_C@@|${temp}|g" \
    -e "s|@@VDD_V@@|${vdd}|g" \
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
  grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence|DC solution failed" "${log}" && return 0
  return 1
}

op_line() {
  # op_line <log> <OP_NAME> -- the echo'd per-point line from the .control
  local v
  v="$(grep -m1 "^$2 " "$1" | awk '{print $2}')"
  printf '%s' "${v:-nan}"
}

# py_vdsat_knee <mech5_csv> <slope_frac> -- the M5 replica's saturation
# knee: first Vds whose incremental slope has fallen to <slope_frac> of
# the curve's maximum slope. Prints "<vdsat> <max_slope_a_per_v>".
py_vdsat_knee() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
path, frac = sys.argv[1], float(sys.argv[2])
v, i = [], []
for line in open(path):
    p = line.split()
    if len(p) < 4:
        continue
    v.append(float(p[0]))
    i.append(float(p[3]))
if len(v) < 20:
    print("nan nan"); raise SystemExit(0)
slopes = [(i[k + 1] - i[k]) / (v[k + 1] - v[k]) for k in range(len(v) - 1)]
hmax = max(slopes)
if not (hmax > 0):
    print("nan nan"); raise SystemExit(0)
vdsat = None
for k in range(len(slopes)):
    if slopes[k] <= frac * hmax:
        vdsat = v[k + 1]
        break
# The knee must sit in the lower half of the sweep; a late "knee" means
# the curve never really saturated and the fraction rule has latched onto
# noise or a DIBL tail instead of a transition.
if vdsat is None or vdsat > 0.5 * v[-1] or vdsat <= 0:
    print("nan nan"); raise SystemExit(0)
print(f"{vdsat:.9g} {hmax:.9g}")
PYEOF
}

# py_vth_cc <mechp_csv> <src_abs_v> <i_crit_a> -- the pair replica's
# constant-current Vth (this repo's gm/ID convention): log-Id linear
# interpolation of the Vgs axis at Id = i_crit, on the Vgs = v(gate) -
# v(source) axis. Prints "<vth_cc> <id_at_last_point_a>".
py_vth_cc() {
  python3 - "$1" "$2" "$3" <<'PYEOF'
import math, sys
path, src, i_crit = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
vgs, ids = [], []
for line in open(path):
    p = line.split()
    if len(p) < 4:
        continue
    vgs.append(float(p[0]) - src)
    ids.append(float(p[3]))
if len(vgs) < 10:
    print("nan nan"); raise SystemExit(0)
vth = None
for k in range(len(ids) - 1):
    lo, hi = (k, k + 1) if ids[k] <= ids[k + 1] else (k + 1, k)
    if ids[lo] <= i_crit <= ids[hi] and ids[hi] > ids[lo]:
        log_lo = math.log(max(ids[lo], 1e-15))
        log_hi = math.log(max(ids[hi], 1e-15))
        if log_hi != log_lo:
            frac = (math.log(i_crit) - log_lo) / (log_hi - log_lo)
            vth = vgs[lo] + frac * (vgs[hi] - vgs[lo])
            break
if vth is None:
    print("nan nan"); raise SystemExit(0)
print(f"{vth:.9g} {ids[-1]:.9g}")
PYEOF
}

run_probe() {
  # run_probe <net> <log> <p_csv> <m5_csv> <corner> <temp> <vdd> <src> <label>
  # Renders and runs the mech probe at body bias <src>. The M5 replica's
  # curve is identical in every round (its bias, Vgs5 = v(ibias), does not
  # depend on the pair probe's body bias), so every round rewrites the one
  # per-point M5 curve file -- idempotent, and the committed evidence
  # keeps exactly one M5 curve per grid point.
  local net="$1" log="$2" p_csv="$3" m5_csv="$4" corner="$5" temp="$6" vdd="$7" src="$8" label="$9"
  local gate_lo gate_hi drn
  gate_lo="$(python3 -c "print(${src} + 0.05)")"
  gate_hi="$(python3 -c "print(${src} + 0.75)")"
  drn="$(python3 -c "print(min(${src} + 0.6, ${vdd} - 0.02))")"
  render "${EXPERIMENT_DIR}/testbench/tb_cmr_mech.spice.tmpl" "${net}" \
    "${corner}" "${temp}" "${vdd}" \
    -e "s|@@PROBE_LABEL@@|${label}|g" \
    -e "s|@@PAIR_SRC_V@@|${src}|g" \
    -e "s|@@PAIR_DRN_V@@|${drn}|g" \
    -e "s|@@VGATE_LO@@|${gate_lo}|g" \
    -e "s|@@VGATE_HI@@|${gate_hi}|g" \
    -e "s|@@VGATE_STEP@@|${MECH_VG_STEP}|g" \
    -e "s|@@VDS_STEP@@|${MECH_VDS_STEP}|g" \
    -e "s|@@MECH5_CSV@@|${m5_csv}|g" \
    -e "s|@@MECHP_CSV@@|${p_csv}|g"
  local rc=0
  ngspice -b "${net}" > "${log}" 2>&1 || rc=$?
  if sim_broken "${rc}" "${log}" "${p_csv}"; then
    return 1
  fi
  return 0
}

for corner in "${CORNERS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      total=$((total + 1))
      point_id="${corner}_${temp}C_${vdd}V"
      vcm="$(python3 -c "print(${vdd}/2)")"
      coarse_start="$(python3 -c "print(${COARSE_EDGE})")"
      coarse_stop="$(python3 -c "print(${vdd} - ${COARSE_EDGE})")"

      coarse_net="${SNAPSHOTS_OUT}/${point_id}_coarse.spice"
      coarse_log="${CORNERS_OUT}/${point_id}_coarse.log"
      coarse_csv="${CORNERS_OUT}/${point_id}_coarse.csv"
      finelo_net="${SNAPSHOTS_OUT}/${point_id}_finelo.spice"
      finelo_log="${CORNERS_OUT}/${point_id}_finelo.log"
      finelo_csv="${CORNERS_OUT}/${point_id}_finelo.csv"
      finehi_net="${SNAPSHOTS_OUT}/${point_id}_finehi.spice"
      finehi_log="${CORNERS_OUT}/${point_id}_finehi.log"
      finehi_csv="${CORNERS_OUT}/${point_id}_finehi.csv"
      mech_m5_csv="${CORNERS_OUT}/${point_id}_mech_m5.csv"
      mech1_p_csv="${CORNERS_OUT}/${point_id}_mech_p_centre.csv"
      mech3_p_csv="${CORNERS_OUT}/${point_id}_mech_p_verify.csv"
      mech1_net="${SNAPSHOTS_OUT}/${point_id}_mech1.spice"
      mech3_net="${SNAPSHOTS_OUT}/${point_id}_mech3.spice"
      mech1_log="${CORNERS_OUT}/${point_id}_mech1.log"
      mech3_log="${CORNERS_OUT}/${point_id}_mech3.log"

      # --- pass 1: coarse full-span sweep --------------------------------
      render "${EXPERIMENT_DIR}/testbench/tb_cmr.spice.tmpl" "${coarse_net}" \
        "${corner}" "${temp}" "${vdd}" \
        -e "s|@@PASS_LABEL@@|coarse|g" \
        -e "s|@@VCM_V@@|${vcm}|g" \
        -e "s|@@VCM_START@@|${coarse_start}|g" \
        -e "s|@@VCM_STOP@@|${coarse_stop}|g" \
        -e "s|@@VCM_STEP@@|${COARSE_STEP}|g" \
        -e "s|@@SWEEP_CSV@@|${coarse_csv}|g"

      rc=0
      ngspice -b "${coarse_net}" > "${coarse_log}" 2>&1 || rc=$?
      if sim_broken "${rc}" "${coarse_log}" "${coarse_csv}"; then
        echo "run_cmr_sweep.sh: SIM FAILED ${point_id} coarse pass (rc=${rc}) -- see ${coarse_log}" >&2
        sim_fail_points+=("${point_id}:coarse")
        continue
      fi

      op_vout="$(op_line "${coarse_log}" OP_VOUT)"
      op_vtail="$(op_line "${coarse_log}" OP_TAIL)"
      op_vd1="$(op_line "${coarse_log}" OP_VD1)"
      op_vd2="$(op_line "${coarse_log}" OP_VD2)"
      op_vibias="$(op_line "${coarse_log}" OP_VIBIAS)"
      op_ivdd="$(op_line "${coarse_log}" OP_IVDD)"

      # --- central-sample state (feeds the round-1 pair probe bias) ------
      read -r vibias_spread c_vtail < <(python3 - "${coarse_csv}" "${vcm}" <<'PYEOF'
import sys
path, target = sys.argv[1], float(sys.argv[2])
vibias = []
best = None
for line in open(path):
    p = line.split()
    if len(p) < 12:
        continue
    vcm = float(p[0])
    vibias.append(float(p[9]))
    if best is None or abs(vcm - target) < abs(best[0] - target):
        best = (vcm, float(p[3]))
if not vibias:
    print("nan nan"); raise SystemExit(0)
spread = max(vibias) - min(vibias)
print(f"{spread:.9g} {best[1]:.9g}")
PYEOF
)

      # --- pass 2a: mech probe at the centre bias ------------------------
      if ! run_probe "${mech1_net}" "${mech1_log}" "${mech1_p_csv}" "${mech_m5_csv}" \
        "${corner}" "${temp}" "${vdd}" "${c_vtail}" "pair-bias round 1 (centre)"; then
        echo "run_cmr_sweep.sh: SIM FAILED ${point_id} mech round 1 -- see ${mech1_log}" >&2
        sim_fail_points+=("${point_id}:mech1")
        continue
      fi
      mech_vibias_repl="$(op_line "${mech1_log}" PROBE_VIBIAS_REPL)"
      read -r vdsat5 m5_max_slope < <(py_vdsat_knee "${mech_m5_csv}" "${SLOPE_FRAC}")
      read -r vth_cc_c pair_c_last_id < <(py_vth_cc "${mech1_p_csv}" "${c_vtail}" "${VTH_CC_CURRENT_A}")

      # --- locate both bounds on the coarse curve (centre-bias first
      # pass), and read the tail bias at the provisional hi bound (the
      # fixed-point seed for the bound-setting probe). --------------------
      #   lo: vtail(vcm) falls through vdsat5 as Vcm drops.
      #   hi: the pair condition rearranges to vd1 - Xcm >= -Vth, so the
      #       crossing of (vd1 - vcm) through -Vth as Vcm rises.
      read -r lo_prelim hi_prelim hi_vsb_seed lo_unique hi_unique < <(python3 - "${coarse_csv}" "${vdsat5}" "${vth_cc_c}" <<'PYEOF'
import sys
path, level5, vth1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
if sys.argv[2] == "nan" or sys.argv[3] == "nan":
    print("nan nan nan 0 0"); raise SystemExit(0)
vcm_v, vtail_v, vds1_v = [], [], []
for line in open(path):
    p = line.split()
    if len(p) < 12:
        continue
    vcm_v.append(float(p[0]))
    vtail_v.append(float(p[3]))
    vds1_v.append(float(p[5]))

def crossing(xs, ys, level, side):
    # interpolated x where ys crosses `level`, scanning outward from the
    # window centre; `side` is -1 (toward lo) or +1 (toward hi). The
    # scan stops at its first crossing -- the innermost one -- so a
    # degenerate re-entry closer to the rail cannot widen the bound.
    idx = range(len(xs) - 1, 0, -1) if side < 0 else range(1, len(xs))
    for i in idx:
        a, b = ys[i - 1] - level, ys[i] - level
        if (a > 0 >= b) or (a < 0 <= b):
            frac = a / (a - b)
            return xs[i - 1] + frac * (xs[i] - xs[i - 1]), i
    return None, None

lo_x, lo_i = crossing(vcm_v, vtail_v, level5, -1)
y_hi = [vds1_v[k] - vcm_v[k] for k in range(len(vcm_v))]
hi_x, hi_i = crossing(vcm_v, y_hi, -vth1, +1)

def fmt(x):
    return "%g" % x if x is not None else "nan"
# hi_vsb_seed: v(tail) at the in-range-adjacent coarse sample of the
# provisional hi crossing (the sample pair's in-range side), the fixed
# point's body-bias seed.
vsb = vtail_v[hi_i] if hi_i is not None else float("nan")
print(f"{fmt(lo_x)} {fmt(hi_x)} {vsb:.9g} {1 if lo_x else 0} {1 if hi_x else 0}")
PYEOF
)

      # --- pass 2b: bounded fixed-point loop for the hi bound's pair ------
      # requirement. Round 1's centre-bias Vth located a provisional hi
      # crossing above; each round now probes the body bias at the last
      # crossing and re-locates with the returned Vth, until the crossing
      # moves <= HI_FP_TOL. The loop's contraction is ~10x per round
      # (dvth/dvtail is small), so two rounds typically suffice after the
      # centre seed; the hard cap bounds pathological cases, and the
      # post-fine verification probe (pass 4) is the actual convergence
      # gate. fp_failed skips the whole grid point without losing the
      # already-collected coarse evidence.
      HI_FP_TOL="2e-3"
      hi_prev="${hi_prelim}"
      vsb_iter="${hi_vsb_seed}"
      vth_pair_cc="${vth_cc_c}"
      hi_prelim2="${hi_prelim}"
      hi_unique2="${hi_unique}"
      fp_round=1
      fp_failed=0
      while [[ ${fp_round} -lt 4 ]]; do
        fp_round=$((fp_round + 1))
        mech_net="${SNAPSHOTS_OUT}/${point_id}_mech${fp_round}.spice"
        mech_log="${CORNERS_OUT}/${point_id}_mech${fp_round}.log"
        mech_p_csv="${CORNERS_OUT}/${point_id}_mech_p_r${fp_round}.csv"
        if ! run_probe "${mech_net}" "${mech_log}" "${mech_p_csv}" "${mech_m5_csv}" \
          "${corner}" "${temp}" "${vdd}" "${vsb_iter}" "pair-bias fixed-point round ${fp_round}"; then
          echo "run_cmr_sweep.sh: SIM FAILED ${point_id} mech round ${fp_round} -- see ${mech_log}" >&2
          sim_fail_points+=("${point_id}:mech${fp_round}")
          fp_failed=1
          break
        fi
        read -r vth_r pair_last_id < <(py_vth_cc "${mech_p_csv}" "${vsb_iter}" "${VTH_CC_CURRENT_A}")
        if [[ "${vth_r}" == "nan" ]]; then
          echo "run_cmr_sweep.sh: ANALYSIS FAILED ${point_id} -- round ${fp_round} Vth extraction failed, see ${mech_p_csv}" >&2
          sim_fail_points+=("${point_id}:mech${fp_round}")
          fp_failed=1
          break
        fi
        # Re-locate with this round's Vth; also read the crossing's own
        # tail bias (the next round's seed).
        read -r hi_x vsb_x uniq_x < <(python3 - "${coarse_csv}" "${vth_r}" <<'PYEOF'
import sys
path, vth1 = sys.argv[1], float(sys.argv[2])
if sys.argv[2] == "nan":
    print("nan nan 0"); raise SystemExit(0)
vcm_v, vds1_v, vtail_v = [], [], []
for line in open(path):
    p = line.split()
    if len(p) < 12:
        continue
    vcm_v.append(float(p[0]))
    vtail_v.append(float(p[3]))
    vds1_v.append(float(p[5]))
for i in range(1, len(vcm_v)):
    a, b = vds1_v[i - 1] - vcm_v[i - 1] + vth1, vds1_v[i] - vcm_v[i] + vth1
    if (a > 0 >= b) or (a < 0 <= b):
        frac = a / (a - b)
        print(f"{vcm_v[i - 1] + frac * (vcm_v[i] - vcm_v[i - 1]):.9g} {vtail_v[i - 1]:.9g} 1")
        raise SystemExit(0)
print("nan nan 0")
PYEOF
)
        if [[ "${hi_x}" == "nan" ]]; then
          echo "run_cmr_sweep.sh: ANALYSIS FAILED ${point_id} -- round ${fp_round} re-locate failed on the coarse curve" >&2
          sim_fail_points+=("${point_id}:fp-relocate")
          fp_failed=1
          break
        fi
        vth_pair_cc="${vth_r}"
        hi_prelim2="${hi_x}"
        hi_unique2="${uniq_x}"
        fp_shift="$(python3 -c "print(abs(${hi_x} - ${hi_prev}))")"
        hi_prev="${hi_x}"
        vsb_iter="${vsb_x}"
        if python3 -c "import sys; sys.exit(0 if ${fp_shift} <= ${HI_FP_TOL} else 1)"; then
          break
        fi
      done
      if [[ ${fp_failed} -ne 0 ]]; then
        continue
      fi

      # --- pass 3: fine sweep at each bound -------------------------------
      finelo_start="$(python3 -c "print(${lo_prelim} - ${FINE_HALFSPAN})")"
      finelo_stop="$(python3 -c "print(${lo_prelim} + ${FINE_HALFSPAN})")"
      render "${EXPERIMENT_DIR}/testbench/tb_cmr.spice.tmpl" "${finelo_net}" \
        "${corner}" "${temp}" "${vdd}" \
        -e "s|@@PASS_LABEL@@|fine-lo|g" \
        -e "s|@@VCM_V@@|${vcm}|g" \
        -e "s|@@VCM_START@@|${finelo_start}|g" \
        -e "s|@@VCM_STOP@@|${finelo_stop}|g" \
        -e "s|@@VCM_STEP@@|${FINE_STEP}|g" \
        -e "s|@@SWEEP_CSV@@|${finelo_csv}|g"

      rc=0
      ngspice -b "${finelo_net}" > "${finelo_log}" 2>&1 || rc=$?
      if sim_broken "${rc}" "${finelo_log}" "${finelo_csv}"; then
        echo "run_cmr_sweep.sh: SIM FAILED ${point_id} fine-lo pass (rc=${rc}) -- see ${finelo_log}" >&2
        sim_fail_points+=("${point_id}:fine-lo")
        continue
      fi

      finehi_start="$(python3 -c "print(${hi_prelim2} - ${FINE_HALFSPAN})")"
      finehi_stop="$(python3 -c "print(${hi_prelim2} + ${FINE_HALFSPAN})")"
      render "${EXPERIMENT_DIR}/testbench/tb_cmr.spice.tmpl" "${finehi_net}" \
        "${corner}" "${temp}" "${vdd}" \
        -e "s|@@PASS_LABEL@@|fine-hi|g" \
        -e "s|@@VCM_V@@|${vcm}|g" \
        -e "s|@@VCM_START@@|${finehi_start}|g" \
        -e "s|@@VCM_STOP@@|${finehi_stop}|g" \
        -e "s|@@VCM_STEP@@|${FINE_STEP}|g" \
        -e "s|@@SWEEP_CSV@@|${finehi_csv}|g"

      rc=0
      ngspice -b "${finehi_net}" > "${finehi_log}" 2>&1 || rc=$?
      if sim_broken "${rc}" "${finehi_log}" "${finehi_csv}"; then
        echo "run_cmr_sweep.sh: SIM FAILED ${point_id} fine-hi pass (rc=${rc}) -- see ${finehi_log}" >&2
        sim_fail_points+=("${point_id}:fine-hi")
        continue
      fi

      # --- resolve the lo bound on the fine curve -------------------------
      read -r icmr_lo vtail_lo vds1_lo vds2_lo ivdd_lo lo_in_window < <(python3 - "${finelo_csv}" "${vdsat5}" <<'PYEOF'
import sys
path, level = sys.argv[1], float(sys.argv[2])
if sys.argv[2] == "nan":
    print("nan nan nan nan nan 0"); raise SystemExit(0)
vcm_v, vtail_v, vd1_v, vd2_v, ivdd_v = [], [], [], [], []
for line in open(path):
    p = line.split()
    if len(p) < 12:
        continue
    vcm_v.append(float(p[0]))
    vtail_v.append(float(p[3]))
    vd1_v.append(float(p[5]))
    vd2_v.append(float(p[7]))
    ivdd_v.append(float(p[11]))
# The curve is stored in ascending Vcm; scan from the window's hi end
# (the in-range side) DOWN so a degenerate re-entry cannot widen the
# bound. vtail falls through the saturation level only once on this side.
bound = None
for i in range(len(vcm_v) - 1, 0, -1):
    a, b = vtail_v[i] - level, vtail_v[i - 1] - level
    if (a >= 0 > b):
        frac = a / (a - b)
        bound = vcm_v[i] + frac * (vcm_v[i - 1] - vcm_v[i])
        s = i
        break
if bound is None:
    print("nan nan nan nan nan 0"); raise SystemExit(0)
in_window = 1 if (vcm_v[0] < bound < vcm_v[-1]) else 0
# State at the in-range-adjacent sample (index s: the last sample at or
# above the saturation edge -- unmodified ngspice output, same convention
# as sim/input-offset/'s *_sample_* columns).
print(f"{bound:.9g} {vtail_v[s]:.9g} {vd1_v[s] - vtail_v[s]:.9g} {vd2_v[s] - vtail_v[s]:.9g} {ivdd_v[s]:.9g} {in_window}")
PYEOF
)

      # --- resolve the hi bound on the fine curve (bound-setting probe) --
      read -r icmr_hi vtail_hi vgs1_hi vsb1_hi vds1_hi vds2_hi ivdd_hi hi_in_window < <(python3 - "${finehi_csv}" "${vth_pair_cc}" <<'PYEOF'
import sys
path, vth1 = sys.argv[1], float(sys.argv[2])
if sys.argv[2] == "nan":
    print("nan nan nan nan nan nan nan 0"); raise SystemExit(0)
vcm_v, vtail_v, vd1_v, vd2_v, ivdd_v = [], [], [], [], []
for line in open(path):
    p = line.split()
    if len(p) < 12:
        continue
    vcm_v.append(float(p[0]))
    vtail_v.append(float(p[3]))
    vd1_v.append(float(p[5]))
    vd2_v.append(float(p[7]))
    ivdd_v.append(float(p[11]))
# y = vd1 - vcm falls through -vth1 as vcm rises; scan ascending (from
# the in-range/lo side) so a degenerate re-entry cannot widen the bound.
bound = None
for i in range(0, len(vcm_v) - 1):
    a = vd1_v[i] - vcm_v[i] + vth1
    b = vd1_v[i + 1] - vcm_v[i + 1] + vth1
    if (a >= 0 > b):
        frac = a / (a - b)
        bound = vcm_v[i] + frac * (vcm_v[i + 1] - vcm_v[i])
        s = i
        break
if bound is None:
    print("nan nan nan nan nan nan nan 0"); raise SystemExit(0)
in_window = 1 if (vcm_v[0] < bound < vcm_v[-1]) else 0
# State at the in-range-adjacent sample (index s).
print(f"{bound:.9g} {vtail_v[s]:.9g} {vcm_v[s] - vtail_v[s]:.9g} {vtail_v[s]:.9g} {vd1_v[s] - vtail_v[s]:.9g} {vd2_v[s] - vtail_v[s]:.9g} {ivdd_v[s]:.9g} {in_window}")
PYEOF
)

      # --- pass 4: verification probe at the recorded bound's body bias --
      if ! run_probe "${mech3_net}" "${mech3_log}" "${mech3_p_csv}" "${mech_m5_csv}" \
        "${corner}" "${temp}" "${vdd}" "${vsb1_hi}" "pair verification (fine-bound body bias)"; then
        echo "run_cmr_sweep.sh: SIM FAILED ${point_id} mech round 3 -- see ${mech3_log}" >&2
        sim_fail_points+=("${point_id}:mech3")
        continue
      fi
      read -r vth_cc_verify pair3_last_id < <(py_vth_cc "${mech3_p_csv}" "${vsb1_hi}" "${VTH_CC_CURRENT_A}")

      # --- fixed-point verification: re-read the bound with the verifying
      # Vth on the SAME fine curve; the shift must close within resolution.
      read -r hi_bound_verify hi_converged hi_shift < <(python3 - "${finehi_csv}" "${vth_cc_verify}" "${icmr_hi}" "${FINE_STEP}" <<'PYEOF'
import sys
path, vth1, rec_bound, step = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
if sys.argv[2] == "nan" or sys.argv[3] == "nan":
    print("nan 0 nan"); raise SystemExit(0)
vcm_v, vd1_v = [], []
for line in open(path):
    p = line.split()
    if len(p) < 12:
        continue
    vcm_v.append(float(p[0]))
    vd1_v.append(float(p[5]))
bound = None
for i in range(0, len(vcm_v) - 1):
    a = vd1_v[i] - vcm_v[i] + vth1
    b = vd1_v[i + 1] - vcm_v[i + 1] + vth1
    if (a >= 0 > b):
        frac = a / (a - b)
        bound = vcm_v[i] + frac * (vcm_v[i + 1] - vcm_v[i])
        break
if bound is None:
    print("nan 0 nan"); raise SystemExit(0)
shift = abs(bound - rec_bound)
converged = 1 if shift <= 2 * step else 0
print(f"{bound:.9g} {converged} {shift:.9g}")
PYEOF
)

      # --- sibling-record cross-reference inputs -------------------------
      ac_vtail="$(csv_lookup "${AC_RECORD_CSV}" vtail_dc_v "${point_id}")"
      [[ -n "${ac_vtail}" ]] || ac_vtail="nan"
      ac_vd1="$(csv_lookup "${AC_RECORD_CSV}" vd1_dc_v "${point_id}")"
      [[ -n "${ac_vd1}" ]] || ac_vd1="nan"
      ac_vd2="$(csv_lookup "${AC_RECORD_CSV}" vd2_dc_v "${point_id}")"
      [[ -n "${ac_vd2}" ]] || ac_vd2="nan"
      ac_vibias="$(csv_lookup "${AC_RECORD_CSV}" vibias_dc_v "${point_id}")"
      [[ -n "${ac_vibias}" ]] || ac_vibias="nan"
      swing_hi="$(csv_lookup "${SWING_RECORD_CSV}" vout_max_track_v "${point_id}")"
      [[ -n "${swing_hi}" ]] || swing_hi="nan"
      swing_lo="$(csv_lookup "${SWING_RECORD_CSV}" vout_min_track_v "${point_id}")"
      [[ -n "${swing_lo}" ]] || swing_lo="nan"

      # --- per-point sanity checks + row assembly ------------------------
      row="$(python3 - "${point_id}" "${corner}" "${temp}" "${vdd}" "${vcm}" \
        "${vibias_spread}" "${op_vout}" "${op_vtail}" "${op_vd1}" "${op_vd2}" "${op_vibias}" "${op_ivdd}" \
        "${mech_vibias_repl}" "${vdsat5}" "${vth_pair_cc}" "${vth_cc_verify}" "${vth_cc_c}" \
        "${icmr_lo}" "${lo_unique}" "${lo_in_window}" \
        "${icmr_hi}" "${hi_unique}" "${hi_unique2}" "${hi_in_window}" "${hi_converged}" "${hi_shift}" \
        "${vtail_lo}" "${vds1_lo}" "${vds2_lo}" "${ivdd_lo}" \
        "${vtail_hi}" "${vgs1_hi}" "${vsb1_hi}" "${vds1_hi}" "${vds2_hi}" "${ivdd_hi}" \
        "${ac_vtail}" "${ac_vd1}" "${ac_vd2}" "${ac_vibias}" "${swing_hi}" "${swing_lo}" <<'PYEOF'
import sys

(args, ok) = (sys.argv[1:], True)

(point_id, corner, temp, vdd_s, vcm_s) = args[0:5]
(vib_spread_s, vout_s, vtail_s, vd1_s, vd2_s, vibias_s, ivdd_s) = args[5:12]
(repl_s, vdsat5_s, vth_b_s, vth_v_s, vth_c_s) = args[12:17]
(lo_s, lo_uniq_s, lo_in_s) = args[17:20]
(hi_s, hi_uniq_s, hi_uniq2_s, hi_in_s, hi_conv_s, hi_shift_s) = args[20:26]
(vtail_lo_s, vds1_lo_s, vds2_lo_s, ivdd_lo_s) = args[26:30]
(vtail_hi_s, vgs1_hi_s, vsb1_hi_s, vds1_hi_s, vds2_hi_s, ivdd_hi_s) = args[30:36]
(ac_vtail_s, ac_vd1_s, ac_vd2_s, ac_vibias_s, swing_hi_s, swing_lo_s) = args[36:42]

def f(x):
    try:
        return float(x)
    except ValueError:
        return float("nan")

vdd, vcm = f(vdd_s), f(vcm_s)
vib_spread = f(vib_spread_s)
op = {k: f(v) for k, v in zip(("vout", "vtail", "vd1", "vd2", "vibias", "ivdd"),
                              (vout_s, vtail_s, vd1_s, vd2_s, vibias_s, ivdd_s))}
repl_vibias = f(repl_s)
vdsat5 = f(vdsat5_s)
vth_b = f(vth_b_s)
vth_v = f(vth_v_s)
vth_c = f(vth_c_s)
icmr_lo, icmr_hi = f(lo_s), f(hi_s)
lo_in, hi_in = int(f(lo_in_s)), int(f(hi_in_s))
lo_uniq, hi_uniq, hi_uniq2 = int(f(lo_uniq_s)), int(f(hi_uniq_s)), int(f(hi_uniq2_s))
hi_conv = int(f(hi_conv_s))
vtail_lo, vds1_lo, vds2_lo = f(vtail_lo_s), f(vds1_lo_s), f(vds2_lo_s)
vtail_hi, vgs1_hi, vsb1_hi, vds1_hi, vds2_hi = (f(vtail_hi_s), f(vgs1_hi_s),
                                                f(vsb1_hi_s), f(vds1_hi_s), f(vds2_hi_s))

# Each check appends its name to `fails` on failure; the names are printed
# to stderr so the corners log states exactly why a point failed (same
# diagnostic discipline as sim/gm-id-characterization/'s sanity pass).
fails = []

def ck(cond, name):
    global ok
    if not cond:
        fails.append(name)
        ok = False

# 1. v(ibias) must be a constant across the whole sweep: it is a diode
#    voltage set by the external 10 uA alone; any movement means the bias
#    leg or the sweep itself misbehaved.
ck(vib_spread == vib_spread and vib_spread <= 1e-3, "vibias_not_constant")
# 2. The replica-reproduced bias must match the DUT's own v(ibias); the
#    probe's whole authority rests on this equality.
ck(repl_vibias == repl_vibias and op["vibias"] == op["vibias"]
   and abs(repl_vibias - op["vibias"]) <= 1e-3, "probe_bias_mismatch")
# 3. All three probes must have resolved real requirements in their
#    plausible bands.
ck(vdsat5 == vdsat5 and vdsat5 > 0 and vdsat5 < 0.5 * vdd, "vdsat5_implausible")
ck(vth_b == vth_b and 0.05 < vth_b < 0.8, "vth_bound_implausible")
ck(vth_v == vth_v and 0.05 < vth_v < 0.8, "vth_verify_implausible")
ck(vth_c == vth_c and 0.05 < vth_c < 0.8, "vth_centre_implausible")
# 4. Each bound was located on its side and sits strictly inside its
#    fine window (an edge-touching bound is a window artifact, not the
#    amplifier -- same rule as sim/output-swing/). The hi bound must have
#    been located by BOTH the coarse passes (centre-bias seed and
#    bound-bias re-locate).
ck(lo_uniq == 1 and hi_uniq == 1 and hi_uniq2 == 1 and lo_in == 1 and hi_in == 1,
   "bound_not_located_unique_or_in_window")
# 5. Bounds form a coherent, physically separated interval and the pair
#    fixed-point loop closed: the verification probe at the recorded
#    bound's own body bias must reproduce the bound within two fine steps
#    (0.5 mV). Whether the nominal VDD/2 operating point itself lies
#    INSIDE the interval is recorded per point (contains_vcm,
#    centre_gap_lo_v) rather than gated: at the low rail several corners
#    genuinely sit below the measured lower bound -- the tail-starvation
#    sensitivity issue #12's dev-time study observed, quantified here --
#    and that is a characterization result, not a bench failure.
ck(icmr_lo == icmr_lo and icmr_hi == icmr_hi and icmr_lo < icmr_hi
   and (icmr_hi - icmr_lo) > 0.05 and hi_conv == 1, "bounds_disordered_span_or_fp_unconverged")
contains_vcm = 1 if (icmr_lo <= vcm <= icmr_hi) else 0
centre_gap_lo = icmr_lo - vcm
# 6. The centre op point must sit in its plausible band (front-end nodes
#    not railed; the OUTPUT is expected to be railed here -- this is the
#    open-loop configuration, README.md "What this bench measures").
ck(0.0 < op["vtail"] < 0.45 * vdd and 0.0 < op["vd1"] < vdd
   and 0.0 < op["vd2"] < vdd and 0.2 < op["vibias"] < 0.8 and op["ivdd"] > 0,
   "op_point_implausible")
# 7. The recorded bound-setting probe and the verification probe must
#    have been seeded at (nearly) the same body bias: their two Vth
#    values may differ only by the residual coarse-vs-fine seed gap,
#    materialized as the bound's own shift tolerance.
ck(vth_b == vth_b and vth_v == vth_v and abs(vth_b - vth_v) <= 5e-3,
   "vth_bound_vs_verify_diverged")

if fails:
    print(f"row sanity: {point_id} failed: {', '.join(fails)}", file=sys.stderr)

# --- saturation requirements + margins ---------------------------------
# Pair requirement at the recorded bound: vgs - vth, evaluated with the
# bound's own vgs so the number recorded is the requirement the bound
# tested. (margin_pair_lo uses the same probe at a slightly different
# body bias -- the lo-side tail sits lower -- so it is a logged
# diagnostic for the mechanism table, not a gated quantity; README.md
# notes this.)
vthreq_pair = vgs1_hi - vth_b
margin_m5_lo = vtail_lo - vdsat5
margin_pair_lo = min(vds1_lo, vds2_lo) - vthreq_pair
margin_m5_hi = vtail_hi - vdsat5
margin_pair_hi = min(vds1_hi, vds2_hi) - vthreq_pair

mech_lo = "m5_headroom" if margin_pair_lo > 0 else "m5_headroom+pair_saturation"
mech_hi = "pair_saturation" if margin_m5_hi > 0 else "pair_saturation+m5_headroom"

# Supply-current evidence at the bounds: the lo bound's mechanism is
# independently corroborated by the front-end starvation showing up in
# the total supply current (ivdd at the lo bound vs the centre op). Ratio
# logged, not gated.
ivdd_lo_ratio = f(ivdd_lo_s) / op["ivdd"] if op["ivdd"] > 0 else float("nan")

# --- closed-loop-buffer usable interval --------------------------------
# A unity-gain buffer at input Vcm needs the output to reach Vcm too, so
# the usable interval is the intersection with the output stage's own
# measured reach (the output-swing record's -6 dB tracking bounds at this
# same point_id). Logged, not gated -- README.md "Cross-checks".
buf_lo = max(icmr_lo, f(swing_lo_s)) if f(swing_lo_s) == f(swing_lo_s) else icmr_lo
# A buffer never needs the output to cross below (for the hi bound) or
# above (for the lo bound) its input, so only the same-side reach applies.
buf_hi = min(icmr_hi, f(swing_hi_s)) if f(swing_hi_s) == f(swing_hi_s) else icmr_hi
buf_span = buf_hi - buf_lo if (buf_hi == buf_hi and buf_lo == buf_lo) else float("nan")

# --- centre-op joins (logged, never gated) ------------------------------
x_vtail = op["vtail"] - f(ac_vtail_s) if f(ac_vtail_s) == f(ac_vtail_s) else float("nan")
x_vd1 = op["vd1"] - f(ac_vd1_s) if f(ac_vd1_s) == f(ac_vd1_s) else float("nan")
x_vd2 = op["vd2"] - f(ac_vd2_s) if f(ac_vd2_s) == f(ac_vd2_s) else float("nan")
x_vibias = op["vibias"] - f(ac_vibias_s) if f(ac_vibias_s) == f(ac_vibias_s) else float("nan")

def fmt(x):
    return "nan" if x != x else f"{x:.9g}"

fields = ["1" if ok else "0",
          fmt(icmr_lo), fmt(icmr_hi), fmt(icmr_hi - icmr_lo),
          fmt(buf_lo), fmt(buf_hi), fmt(buf_span),
          str(contains_vcm), fmt(centre_gap_lo),
          mech_lo, mech_hi,
          fmt(f(hi_shift_s)), str(hi_conv),
          fmt(vdsat5), fmt(vth_b), fmt(vthreq_pair),
          fmt(vtail_lo), fmt(vds1_lo), fmt(vds2_lo),
          fmt(margin_m5_lo), fmt(margin_pair_lo),
          fmt(vtail_hi), fmt(vgs1_hi), fmt(vsb1_hi),
          fmt(vds1_hi), fmt(vds2_hi),
          fmt(margin_m5_hi), fmt(margin_pair_hi),
          fmt(f(ivdd_lo_s)), fmt(f(ivdd_hi_s)),
          fmt(ivdd_lo_ratio),
          fmt(op["vout"]), fmt(op["vtail"]), fmt(op["vd1"]), fmt(op["vd2"]),
          fmt(op["vibias"]), fmt(op["ivdd"]),
          fmt(x_vtail), fmt(x_vd1), fmt(x_vd2), fmt(x_vibias),
          fmt(f(swing_hi_s)), fmt(f(swing_lo_s))]
print(" ".join(fields))
PYEOF
)"
      read -r op_pass icmr_lo icmr_hi icmr_span buf_lo buf_hi buf_span \
        contains_vcm centre_gap_lo \
        mech_lo mech_hi hi_round_shift hi_converged \
        vdsat5_meas vth_pair_cc vthreq_pair \
        vtail_lo_v vds1_lo_v vds2_lo_v margin_m5_lo margin_pair_lo \
        vtail_hi_v vgs1_hi_v vsb1_hi_v vds1_hi_v vds2_hi_v margin_m5_hi margin_pair_hi \
        ivdd_lo ivdd_hi ratio_ivdd_lo_c \
        op_vout op_vtail op_vd1 op_vd2 op_vibias op_ivdd \
        x_vtail x_vd1 x_vd2 x_vibias swing_hi swing_lo <<<"${row}"

      echo "${point_id},${corner},${temp},${vdd},${vcm},${op_pass},${icmr_lo},${icmr_hi},${icmr_span},${buf_lo},${buf_hi},${buf_span},${contains_vcm},${centre_gap_lo},${mech_lo},${mech_hi},${hi_round_shift},${hi_converged},${vdsat5_meas},${vth_pair_cc},${vthreq_pair},${vtail_lo_v},${vds1_lo_v},${vds2_lo_v},${margin_m5_lo},${margin_pair_lo},${vtail_hi_v},${vgs1_hi_v},${vsb1_hi_v},${vds1_hi_v},${vds2_hi_v},${margin_m5_hi},${margin_pair_hi},${ivdd_lo},${ivdd_hi},${ratio_ivdd_lo_c},${op_vout},${op_vtail},${op_vd1},${op_vd2},${op_vibias},${op_ivdd},${x_vtail},${x_vd1},${x_vd2},${x_vibias},${swing_hi},${swing_lo}" >> "${CSV_OUT}.raw"

      if [[ "${op_pass}" != "1" ]]; then
        echo "run_cmr_sweep.sh: SANITY FAILED ${point_id} -- per-point checks above; see ${CORNERS_OUT}/${point_id}*.{csv,log}" >&2
        op_fail_points+=("${point_id}")
      fi

    done
  done
done

passed=$(( total - ${#sim_fail_points[@]} - ${#op_fail_points[@]} ))

if [[ ${passed} -le 0 ]]; then
  echo "run_cmr_sweep.sh: no points passed -- refusing to write a summary." >&2
  exit 1
fi

mv "${CSV_OUT}.raw" "${CSV_OUT}"

{
  echo "op_pass_count,${passed} of ${total}, op-sane failures: ${#op_fail_points[@]} (${op_fail_points[*]:-none})"
  echo "sim_fail_count,${#sim_fail_points[@]} (${sim_fail_points[*]:-none})"
} > "${CORNERS_OUT}/sanity_checks.txt"

# --- Completeness: all 45 (corner, temp, vdd) cells must have run. -------
n_rows=$(($(wc -l < "${CSV_OUT}") - 1))
expected=$(( ${#CORNERS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} ))
if [[ "${n_rows}" -ne "${expected}" ]]; then
  echo "run_cmr_sweep.sh: WARNING -- ${n_rows} rows written, expected ${expected} (${#sim_fail_points[@]} sim failures)" >&2
fi

# --- Worst-corner summary (per metric) for the record's .md -------------
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
        if v == v:
            out.append((v, r))
    return out

span = numeric(rows, "icmr_span_v")
lo = numeric(rows, "icmr_lo_v")
hi = numeric(rows, "icmr_hi_v")
buf = numeric(rows, "buffer_use_span_v")

def line(label, t):
    if t is None:
        print(f"{label}: n/a")
        return
    v, r = t
    print(f"{label}: {v:.4g} at {r['point_id']}")

line("worst_icmr_span_v", min(span, key=lambda t: t[0]) if span else None)
line("best_icmr_span_v", max(span, key=lambda t: t[0]) if span else None)
line("worst_icmr_lo_v", max(lo, key=lambda t: t[0]) if lo else None)
line("worst_icmr_hi_v", min(hi, key=lambda t: t[0]) if hi else None)
line("worst_buffer_use_span_v", min(buf, key=lambda t: t[0]) if buf else None)
if lo and hi and span:
    w_lo = max(lo, key=lambda t: t[0])[1]["point_id"]
    w_hi = min(hi, key=lambda t: t[0])[1]["point_id"]
    w_sp = min(span, key=lambda t: t[0])[1]["point_id"]
    print(f"binding_point_overlap, lo={w_lo} hi={w_hi} span={w_sp}")
# Corners whose nominal VDD/2 bias point sits BELOW the measured lower
# bound: the low-rail tail-starvation finding (README.md "The low-rail
# finding").
outside = [r for r in rows if r.get("contains_vcm") == "0"]
print(f"centre_below_lo_points,{len(outside)} ({' '.join(r['point_id'] for r in outside) or 'none'})")
mechs = {}
for r in rows:
    mechs.setdefault(r["mech_lo"] + "/" + r["mech_hi"], []).append(r["point_id"])
for k in sorted(mechs):
    print(f"mech_combo {k}: {len(mechs[k])}")
PYEOF
)"

cat > "${MD_OUT}" <<EOF
# input-cmr record ${RECORD_ID}

Generated by \`sim/input-cmr/run_cmr_sweep.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`).

Grid: cornerMOSlv.lib \`mos_tt/ss/ff/sf/fs\` [DR-1] x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${expected} points,
into \`CL = 2 pF\` [DR-1]. Method: open-loop input common-mode sweep with
the differential input pinned at zero; the lower bound is the
\`v(tail) = Vdsat(M5)\` crossing with Vdsat5 measured by the same-device
replica probe at its 10%-of-max-slope saturation knee, the upper bound is
the pair saturation condition \`Vds >= Vgs - Vth\` with Vth measured by the
replica probe at the bound's own body bias per the gm/ID constant-current
convention (a three-round seeded fixed point: centre-bias seed, bound-bias
setting, bound verification), both located coarse (5 mV) then resolved
fine (250 uV) -- README.md "What this bench measures" and "The
saturation-edge probes". ${passed} of ${total} points simulated
successfully; ${#sim_fail_points[@]} simulation failure(s)
(${sim_fail_points[*]:-none}); ${#op_fail_points[@]} point(s) failed the
per-point sanity check (${op_fail_points[*]:-none}) -- see README.md
"Per-point sanity checks" for what each check does and does not verify.

## Worst-corner summary

\`\`\`
${WORST}
\`\`\`

Full per-point data (ICMR bounds and span, closed-loop-buffer usable
interval, whether the nominal VDD/2 operating point lies inside the
measured interval (contains_vcm / centre_gap_lo_v -- at the 1.08 V rail
several corners sit below the measured lower bound: the low-rail
tail-starvation finding, README.md "The low-rail finding"), mechanism
attribution with margin evidence, the measured
saturation requirements both bounds are judged against (Vdsat5 knee,
Vth(CC) and Vgs-Vth of the pair), per-bound internal operating point and
Vdd current, the centre operating point, and the per-point cross-checks
against \`sim/open-loop-ac\` and \`sim/output-swing\` at the same point_id)
is in \`records/${RECORD_ID}.csv\`. Raw per-point ngspice logs, the coarse
and fine scan curves each bound was read from, and the replica-probe
saturation curves each requirement was read from are in
\`corners/${RECORD_ID}/\`.
EOF

echo "run_cmr_sweep.sh: wrote ${CSV_OUT} and ${MD_OUT} (${passed}/${total} points, ${#op_fail_points[@]} op-sanity failures)"

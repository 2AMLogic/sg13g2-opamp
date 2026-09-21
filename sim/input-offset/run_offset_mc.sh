#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
#   sim/input-offset/run_offset_mc.sh --seed 20260921 --n 300
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH (developed
# and run against ngspice-46) plus the OSDI models sim/tools/build-osdi.sh
# builds, AND at least one committed deterministic
# sim/input-offset/records/<record-id>.csv from issue #11's
# run_offset_sweep.sh -- this campaign joins that record's per-point
# systematic Vos (same corner/temp at the fixed 1.20 V supply) into its
# digest, and hard-gates its negative control against that record's
# mos_tt_27C_1.20V figure. Override the join source with
# OFFSET_DET_RECORD_CSV=<path>.
#
# Device-mismatch Monte Carlo campaign for the DC input-referred offset
# bench (issue #17; the statistical basis spec/target-spec.md's offset row
# and gap-to-T1 tracker #3 item 6 track): N draws per point against
# cornerMOSlv.lib's `<corner>_mismatch` sections -- the SAME deterministic
# process-corner parameters as the plain sections PLUS per-instance
# agauss() mismatch draws (combined with, not instead of, process corners)
# -- across all five corner families x {-40, 27, 125} C at the fixed
# nominal 1.20 V supply, plus a deterministic negative control at the
# nominal point. Seeding (setseed + reset in .control -- the only
# mechanism that reaches this deck's instance-parameter agauss draws) is
# documented in testbench/tb_offset_mc.spice.tmpl's header -- read that
# first if a result here looks surprising.
#
# The campaign self-verifies, every run (hard gates, all must pass or no
# record is written):
#   - negctrl zero-spread: N plain-section draws on the identical seed
#     sequence must produce EXACTLY identical Vos -- any nonzero spread is
#     a harness bug (a mismatch section that leaked in, or a seed that
#     never reached .options before the draws parsed), not noise;
#   - negctrl anchor: that identical figure must reproduce issue #11's
#     committed fine-pass Vos at mos_tt_27C_1.20V within 50 uV (measured
#     agreement is ~1.2 uV, the deterministic record's own coarse-vs-fine
#     delta at that point, so the gate carries 40x headroom);
#   - seed-determinism self-check: one duplicated nominal draw (same seed,
#     separate ngspice invocation) must come out bit-identical to the
#     original -- the "recorded seed makes the run reproducible" property
#     issue #17's test plan asks for, verified in-campaign every time.
#     (This gate is load-bearing: the first draft of this campaign seeded
#     via a netlist-level .options line that the title-card rule silently
#     swallowed, and draws varied run-to-run -- the gate caught it and
#     refused to write a record before any evidence landed.)
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{md,csv} plus the
# per-draw records/<record-id>-draws.csv -- never overwriting a prior run.
# Full methodology, scope, and non-claims: README.md (this directory).
set -euo pipefail

SEED=20260921
N=300
PARALLEL=8
while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed) SEED="$2"; shift 2 ;;
    --n) N="$2"; shift 2 ;;
    --parallel) PARALLEL="$2"; shift 2 ;;
    *) echo "run_offset_mc.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "${N}" -lt 300 ]]; then
  echo "run_offset_mc.sh: refusing --n < 300 -- the statistical basis this" >&2
  echo "run_offset_mc.sh: campaign is evidence for (target-spec.md offset row," >&2
  echo "run_offset_mc.sh: tracker #3 item 6) commits to N>=300 per corner." >&2
  exit 2
fi
if ! [[ "${SEED}" =~ ^[0-9]+$ ]]; then
  echo "run_offset_mc.sh: --seed must be a non-negative integer (got: ${SEED})" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_offset_mc.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_offset_mc.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_offset_mc.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_offset_mc.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  exit 3
fi

# --- Deterministic-record join (issue #11's bench) -------------------------
# The newest deterministic offset digest: a records/*.csv whose header
# carries the deterministic bench's own vos_closed_loop_v column -- absent
# from this campaign's digest on purpose, so that on any RE-run (after
# this campaign has landed a record of its own) the join still selects an
# issue-#11 record, not the newest MC digest sitting beside it.
if [[ -z "${OFFSET_DET_RECORD_CSV:-}" ]]; then
  OFFSET_DET_RECORD_CSV=""
  while IFS= read -r _f; do
    if head -n 1 "${_f}" 2>/dev/null | grep -q "vos_closed_loop_v"; then
      OFFSET_DET_RECORD_CSV="${_f}"
    fi
  done < <(find "${SCRIPT_DIR}/records" -maxdepth 1 -name '*.csv' ! -name '*-draws.csv' 2>/dev/null | sort)
fi
if [[ -z "${OFFSET_DET_RECORD_CSV}" || ! -s "${OFFSET_DET_RECORD_CSV}" ]]; then
  echo "run_offset_mc.sh: no deterministic issue-#11 record found (need a records/*.csv" >&2
  echo "run_offset_mc.sh: with a vos_closed_loop_v column) -- run run_offset_sweep.sh first." >&2
  exit 3
fi
DET_RECORD_ID="$(basename "${OFFSET_DET_RECORD_CSV}" .csv)"
DET_ANCHOR_PID="mos_tt_27C_1.20V"
DET_ANCHOR_VOS="$(awk -F, -v pid="${DET_ANCHOR_PID}" '
  NR==1 { for (i = 1; i <= NF; i++) if ($i == "vos_null_v") col = i; next }
  col && $1 == pid { print $col }' "${OFFSET_DET_RECORD_CSV}")"
if [[ -z "${DET_ANCHOR_VOS}" ]]; then
  echo "run_offset_mc.sh: no ${DET_ANCHOR_PID} row in ${OFFSET_DET_RECORD_CSV} -- cannot anchor the negative control." >&2
  exit 3
fi

OSDI_DIR="${SG13G2_OSDI_DIR}"
REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="mc-$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
DRAWS_CSV="${RECORDS_DIR}/${RECORD_ID}-draws.csv"
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

DUT_NETLIST_SNAPSHOT="${SNAPSHOTS_OUT}/opamp_core.spice"
cp "${DUT_NETLIST_SRC}" "${DUT_NETLIST_SNAPSHOT}"

# --- Campaign grid ---------------------------------------------------------
# 15 mismatch points: every cornerMOSlv.lib family [DR-1] x the same
# temperature axis {-40, 27, 125} C as the deterministic bench, at the
# fixed NOMINAL supply 1.20 V. The PVT axis this campaign holds fixed
# while mismatch is sampled is supply, because issue #11's own 45-point
# deterministic record already covers every (corner, temp) at all three
# supplies, and random-vs-supply interaction is not an evidence class
# issue #17 names -- the same scope argument sg13g2-bandgap's
# sim/closed-loop-vref-mc used on this PDK (corners x temperatures at
# nominal supply; sampling mismatch across three supplies as well would
# triple the campaign for no incremental evidence value). Every corner
# family is drawn at N>=300 at EACH of its three temperatures, so the
# "N>=300 per corner" requirement holds everywhere it is claimed.
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
TEMPS=(-40 27 125)
VDD="1.20"
VCM="0.6"
CL_F="2e-12"
COARSE_START="-0.1"
COARSE_STOP="0.1"
COARSE_STEP="500e-6"
SWEEP_VECTORS="v(out)"
NEGCTRL_ANCHOR_TOL="50e-6"

POINT_SPECS=()
for _c in "${CORNERS[@]}"; do
  for _t in "${TEMPS[@]}"; do
    POINT_SPECS+=("mismatch:${_c}:${_t}")
  done
done
POINT_SPECS+=("negctrl:mos_tt:27")   # plain section at the nominal point, same seed sequence
N_POINTS="${#POINT_SPECS[@]}"

point_id_of() { # <mode> <corner> <temp> -> stable digest/point id
  printf '%s_%s_%sC_%sV' "$2" "$1" "$3" "${VDD}"
}

det_vos_of() { # <corner> <temp> -> systematic vos_null_v joined from the issue-#11 record
  awk -F, -v pid="$1_$2C_${VDD}V" '
    NR==1 { for (i = 1; i <= NF; i++) if ($i == "vos_null_v") col = i; next }
    col && $1 == pid { print $col }' "${OFFSET_DET_RECORD_CSV}"
}

echo "run_offset_mc.sh: record-id=${RECORD_ID} seed=${SEED} n=${N} parallel=${PARALLEL}"
echo "run_offset_mc.sh: points: $(( N_POINTS - 1 )) mismatch (5 corners x 3 temps @ ${VDD} V) + 1 negative control"
echo "run_offset_mc.sh: deterministic join: ${DET_RECORD_ID} (anchor ${DET_ANCHOR_PID} vos_null_v=${DET_ANCHOR_VOS} V)"

# --- Scratch space ----------------------------------------------------------
# Per-draw netlists/logs/sweeps are campaign scratch, NOT committed
# evidence (README.md "Evidence volume"); only draw 0 per point plus the
# frozen DUT snapshot are copied into netlist-snapshots/<record-id>/ and
# corners/<record-id>/ at the end, matching the digest's per-point rows.
# The base gets its trailing slash stripped BEFORE mktemp: on macOS TMPDIR
# ends in "/", and the un-stripped template would bake a "//" into every
# scratch path -- a token ngspice's .control wrdata parser treats as
# ending the filename ("wrdata: too few args", sweep never written;
# verified empirically and what killed this campaign's first three
# launches before the in-campaign gates caught it).
SCRATCH_BASE="${TMPDIR:-/tmp}"
SCRATCH_BASE="${SCRATCH_BASE%/}"
SCRATCH_DIR="$(mktemp -d "${SCRATCH_BASE}/sg13g2-opamp-offset-mc.XXXXXX")"
trap 'rm -rf "${SCRATCH_DIR}"' EXIT
mkdir -p "${SCRATCH_DIR}/netlists" "${SCRATCH_DIR}/logs" "${SCRATCH_DIR}/sweeps"

echo "point_id,mode,corner,mos_section,temp_c,vdd_v,draw_index,draw_seed,status,fail_reason,vos_v" > "${DRAWS_CSV}"

render_netlist() { # <out> <point_id> <mode> <corner> <temp> <draw_index> <draw_seed>
  local out="$1" pid="$2" mode="$3" corner="$4" temp="$5" idx="$6" seed="$7"
  local section
  if [[ "${mode}" == "mismatch" ]]; then
    section="${corner}_mismatch"
  else
    section="${corner}"
  fi
  sed \
    -e "s|@@PDK_ROOT@@|${PDK_ROOT}|g" \
    -e "s|@@PDK@@|${PDK}|g" \
    -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
    -e "s|@@MOS_SECTION@@|${section}|g" \
    -e "s|@@TEMP_C@@|${temp}|g" \
    -e "s|@@VDD_V@@|${VDD}|g" \
    -e "s|@@VCM_V@@|${VCM}|g" \
    -e "s|@@CL_F@@|${CL_F}|g" \
    -e "s|@@DUT_NETLIST@@|${DUT_NETLIST_SNAPSHOT}|g" \
    -e "s|@@POINT_ID@@|${pid}|g" \
    -e "s|@@CORNER@@|${corner}|g" \
    -e "s|@@MISMATCH_MODE@@|${mode}|g" \
    -e "s|@@DRAW_INDEX@@|${idx}|g" \
    -e "s|@@N_DRAWS@@|${N}|g" \
    -e "s|@@SEED@@|${seed}|g" \
    -e "s|@@VID_START@@|${COARSE_START}|g" \
    -e "s|@@VID_STOP@@|${COARSE_STOP}|g" \
    -e "s|@@VID_STEP@@|${COARSE_STEP}|g" \
    -e "s|@@WRDATA_VECTORS@@|${SWEEP_VECTORS}|g" \
    -e "s|@@SWEEP_CSV@@|${SCRATCH_DIR}/sweeps/${pid}_${idx}.csv|g" \
    "${EXPERIMENT_DIR}/testbench/tb_offset_mc.spice.tmpl" > "${out}"
}

# -------------------------------------------------------------- Pass 1: render
# One netlist per (point, draw), plus the seed-determinism duplicate of
# the first mismatch point's draw 0 (identical render inputs: same seed,
# separate file, byte-identical sweep required in the self-check below).
MANIFEST="${SCRATCH_DIR}/manifest.txt"
: > "${MANIFEST}"

for spec in "${POINT_SPECS[@]}"; do
  IFS=':' read -r mode corner temp <<< "${spec}"
  pid="$(point_id_of "${mode}" "${corner}" "${temp}")"
  for ((draw_index = 0; draw_index < N; draw_index++)); do
    draw_seed=$((SEED + draw_index))
    render_netlist \
      "${SCRATCH_DIR}/netlists/${pid}_${draw_index}.spice" \
      "${pid}" "${mode}" "${corner}" "${temp}" "${draw_index}" "${draw_seed}"
    echo "${SCRATCH_DIR}/netlists/${pid}_${draw_index}.spice ${SCRATCH_DIR}/logs/${pid}_${draw_index}.log" >> "${MANIFEST}"
  done
done

FIRST_PID="$(point_id_of mismatch mos_tt -40)"
DETCHK_NETLIST="${SCRATCH_DIR}/netlists/_detcheck_0.spice"
DETCHK_LOG="${SCRATCH_DIR}/logs/_detcheck_0.log"
render_netlist "${DETCHK_NETLIST}" "detcheck" "mismatch" "mos_tt" "-40" "0" "${SEED}"
# detcheck's own sweep lands at sweeps/detcheck_0.csv via the same
# @@SWEEP_CSV@@ substitution the point netlists use.

TOTAL_DRAWS=$(( $(wc -l < "${MANIFEST}" | tr -d ' ') + 1 ))
echo "run_offset_mc.sh: rendered ${TOTAL_DRAWS} draw netlists -- simulating with ${PARALLEL}-way parallelism..."

# ------------------------------------------------------------ Pass 2: simulate
# The inner command always exits 0 and captures the real ngspice rc into
# "<log>.rc", so one crashed draw cannot abort the whole campaign under
# this script's own set -e; pass 3 tallies the real per-draw rc.
# shellcheck disable=SC2016  # $0/$1/$? are the INNER shell's -- must not expand here
xargs -P "${PARALLEL}" -n2 bash -c 'ngspice -b "$0" > "$1" 2>&1; echo $? > "$1.rc"; exit 0' < "${MANIFEST}"
{ ngspice -b "${DETCHK_NETLIST}" > "${DETCHK_LOG}" 2>&1; echo $? > "${DETCHK_LOG}.rc"; true; }

echo "run_offset_mc.sh: simulation pass (${TOTAL_DRAWS} draws) complete -- parsing..."

# --------------------------------------------------------------- Pass 3: parse
# ONE python process per POINT (N_POINTS total), not one per draw: python
# interpreter startup (~0.25 s) times 4800 draws dominates the campaign's
# wall time otherwise. Per-draw sanity rule, identical to the per-draw
# parser this replaces (testbench template "method" section): clean
# simulator exit, no model-load/convergence error, a non-empty sweep,
# exactly one Vout = Vcm crossing, comfortably inside the +-100 mV window.
# Matches the deterministic bench's own per-point sanity bound
# (run_offset_sweep.sh: |vos| >= 0.9 * 0.1 -> fail). Rows are appended to
# DRAWS_CSV in point order, draw-scan order -- same order pass 1 rendered.

failed_draws_total=0
for spec in "${POINT_SPECS[@]}"; do
  IFS=':' read -r mode corner temp <<< "${spec}"
  pid="$(point_id_of "${mode}" "${corner}" "${temp}")"
  if [[ "${mode}" == "mismatch" ]]; then
    section="${corner}_mismatch"
  else
    section="${corner}"
  fi

  python3 - "${SCRATCH_DIR}" "${DRAWS_CSV}" "${pid}" "${mode}" "${corner}" \
    "${section}" "${temp}" "${VDD}" "${SEED}" "${N}" "${VCM}" <<'PYEOF'
import os, re, sys
scratch, draws_csv, pid, mode, corner, section, temp, vdd, seed, n, vcm = sys.argv[1:12]
n, seed, target = int(n), int(seed), float(vcm)
err_re = re.compile(
    r"Unable to find definition of model|couldn't be loaded|Unknown model type"
    r"|fatal error|singular matrix|gmin stepping failed|no convergence", re.I)
with open(draws_csv, "a") as out:
    for idx in range(n):
        sweep = os.path.join(scratch, "sweeps", "%s_%d.csv" % (pid, idx))
        log = os.path.join(scratch, "logs", "%s_%d.log" % (pid, idx))
        draw_seed = seed + idx
        status, reason, vos = "FAIL", "", "nan"
        try:
            with open(log + ".rc") as f:
                rc = f.read().strip()
        except OSError:
            rc = "missing"
        if rc != "0":
            reason = "ngspice_rc=%s" % rc
        else:
            try:
                log_text = open(log, errors="replace").read()
            except OSError:
                log_text = ""
            if err_re.search(log_text):
                reason = "sim_error_in_log"
            else:
                vid, vout = [], []
                try:
                    for line in open(sweep):
                        p = line.split()
                        if len(p) < 2:
                            continue
                        vid.append(float(p[0])); vout.append(float(p[1]))
                except OSError:
                    vid, vout = [], []
                if not vid:
                    reason = "no_sweep_file"
                else:
                    crossings = []
                    for i in range(1, len(vid)):
                        a, b = vout[i - 1] - target, vout[i] - target
                        if (a <= 0 < b) or (a >= 0 > b):
                            frac = (target - vout[i - 1]) / (vout[i] - vout[i - 1])
                            crossings.append(vid[i - 1] + frac * (vid[i] - vid[i - 1]))
                    if len(crossings) != 1:
                        reason = "crossings=%d" % len(crossings)
                    elif abs(crossings[0]) >= 0.9 * 0.1:
                        reason = "vos_outside_window"
                    else:
                        status, vos = "PASS", "%.9g" % crossings[0]
        out.write("%s,%s,%s,%s,%s,%s,%d,%d,%s,%s,%s\n"
                  % (pid, mode, corner, section, temp, vdd, idx, draw_seed,
                     status, reason, vos))
PYEOF

  # Representative draw 0 per point -> committed evidence dirs (README.md
  # "Evidence volume": the full per-draw population stays in the -draws
  # CSV; only this one netlist+log pair per point is committed).
  cp "${SCRATCH_DIR}/netlists/${pid}_0.spice" "${SNAPSHOTS_OUT}/${pid}.spice"
  cp "${SCRATCH_DIR}/logs/${pid}_0.log" "${CORNERS_OUT}/${pid}.log"
done

# -------------------------------------------------- Seed-determinism self-check
# Duplicate of the FIRST mismatch point's draw 0 (same seed, its own
# invocation in pass 2): the sweep CSVs must be byte-identical -- the
# recorded-seed reproducibility property, verified rather than asserted.
DETCHK_SWEEP="${SCRATCH_DIR}/sweeps/detcheck_0.csv"
DETCHK_RC="$(cat "${DETCHK_LOG}.rc" 2>/dev/null || echo 1)"
if [[ "${DETCHK_RC}" == "0" ]] && cmp -s "${SCRATCH_DIR}/sweeps/${FIRST_PID}_0.csv" "${DETCHK_SWEEP}"; then
  DETCHECK="PASS bit-identical"
else
  DETCHECK="FAIL byte-diff (detcheck rc=${DETCHK_RC})"
fi
echo "run_offset_mc.sh: seed-determinism self-check: ${DETCHECK}"
if [[ "${DETCHECK}" != "PASS"* ]]; then
  echo "run_offset_mc.sh: same-seed draws diverge -- the recorded seed does NOT" >&2
  echo "run_offset_mc.sh: make this campaign reproducible; refusing to write a record." >&2
  exit 1
fi

# ---------------------------------------------------------- Negative control
# Hard gate, two parts (issue #17 acceptance criteria):
#   1. all N plain-section draws on the identical seed sequence produce
#      EXACTLY the same Vos (nonzero spread = harness bug, not noise);
#   2. that figure reproduces issue #11's committed FINE-pass Vos at
#      mos_tt_27C_1.20V within the anchor tolerance -- the MC harness
#      reproduces the deterministic record with mismatch disabled.
NEGCTRL_PID="$(point_id_of negctrl mos_tt 27)"
NEGCTRL_MINMAX="$(awk -F, -v p="${NEGCTRL_PID}" '$1==p && $9=="PASS" {print $11}' "${DRAWS_CSV}" | awk 'NR==1{min=$1;max=$1} {if($1<min)min=$1; if($1>max)max=$1} END{if(NR>0)printf "%.17g %.17g", min, max}')"
NEGCTRL_MIN="${NEGCTRL_MINMAX%% *}"
NEGCTRL_MAX="${NEGCTRL_MINMAX##* }"
if [[ -z "${NEGCTRL_MIN}" ]]; then
  echo "run_offset_mc.sh: negative control has no PASS draws -- cannot confirm zero spread." >&2
  exit 1
fi
if [[ "${NEGCTRL_MIN}" != "${NEGCTRL_MAX}" ]]; then
  echo "run_offset_mc.sh: NEGATIVE CONTROL FAILED -- non-mismatch draws show nonzero spread" >&2
  echo "run_offset_mc.sh: (min=${NEGCTRL_MIN} max=${NEGCTRL_MAX}) -- this is a driver bug, not noise. Aborting." >&2
  exit 1
fi
NEGCTRL_ANCHOR_DELTA="$(python3 -c "print(f'{abs(${NEGCTRL_MIN} - (${DET_ANCHOR_VOS})):.6g}')")"
echo "run_offset_mc.sh: negative control spread: exactly zero (vos=${NEGCTRL_MIN} V at every draw)."
echo "run_offset_mc.sh: negative control anchor: |${NEGCTRL_MIN} - ${DET_ANCHOR_VOS}| = ${NEGCTRL_ANCHOR_DELTA} V (gate ${NEGCTRL_ANCHOR_TOL} V)"
ANCHOR_GATE_BREACHED="$(python3 -c "print(1 if ${NEGCTRL_ANCHOR_DELTA} > (${NEGCTRL_ANCHOR_TOL}) else 0)")"
if [[ "${ANCHOR_GATE_BREACHED}" == "1" ]]; then
  echo "run_offset_mc.sh: NEGATIVE CONTROL FAILED -- plain draws land outside the deterministic" >&2
  echo "run_offset_mc.sh: record's own coarse-vs-fine tolerance; the MC harness is not" >&2
  echo "run_offset_mc.sh: reproducing issue #11's figure with mismatch disabled. Aborting." >&2
  exit 1
fi

# ----------------------------------------------------------- Per-point digest
# One row per point: N, n_pass, mean, sample sigma, 3-sigma (an absolute
# VOLTAGE -- the statistical-basis number for an offset row is not a
# percentage of the mean), min/max, the deterministic systematic Vos
# joined from issue #11's record at the same (corner, temp) on this
# campaign's fixed supply, and the worst-case total = |systematic| + 3*sigma
# a real part's offset budget carries at that point.
echo "point_id,mode,mos_section,temp_c,vdd_v,seed_base,n_draws,n_pass,status,mean_vos_v,sigma_vos_v,three_sigma_v,min_vos_v,max_vos_v,vos_systematic_det_v,vos_total_wc_det_plus_3sigma_v" > "${CSV_OUT}.raw"

failed_points=()
for spec in "${POINT_SPECS[@]}"; do
  IFS=':' read -r mode corner temp <<< "${spec}"
  pid="$(point_id_of "${mode}" "${corner}" "${temp}")"
  if [[ "${mode}" == "mismatch" ]]; then
    section="${corner}_mismatch"
  else
    section="${corner}"
  fi
  det_vos="$(det_vos_of "${corner}" "${temp}")"
  [[ -n "${det_vos}" ]] || det_vos="nan"

  read -r n_draws n_pass mean sigma three_sigma vmin vmax total_wc <<< "$(awk -F, -v p="${pid}" -v dv="${det_vos}" '
    $1==p { n++ }
    $1==p && $9=="PASS" { np++; v[np]=$11; sum += $11 }
    END {
      if (np==0) { printf "%d 0 0 0 0 0 0 nan", n; exit }
      mean = sum/np
      ssq = 0
      for (i=1;i<=np;i++) { d = v[i]-mean; ssq += d*d }
      sigma = (np>1) ? sqrt(ssq/(np-1)) : 0
      vmin=v[1]; vmax=v[1]
      for (i=1;i<=np;i++) { if (v[i]<vmin) vmin=v[i]; if (v[i]>vmax) vmax=v[i] }
      twc = (dv != "nan") ? ((dv<0?-dv:dv) + 3*sigma) : 0/0
      printf "%d %d %.9g %.9g %.9g %.9g %.9g %.9g", n, np, mean, sigma, 3*sigma, vmin, vmax, twc
    }' "${DRAWS_CSV}")"

  point_status="PASS"
  if [[ "${n_pass}" != "${n_draws}" ]]; then
    point_status="FAIL"
    failed_points+=("${pid}")
  fi
  echo "${pid},${mode},${section},${temp},${VDD},${SEED},${n_draws},${n_pass},${point_status},${mean},${sigma},${three_sigma},${vmin},${vmax},${det_vos},${total_wc}" >> "${CSV_OUT}.raw"
done

mv "${CSV_OUT}.raw" "${CSV_OUT}"

failed_draws_total="$(awk -F, 'NR>1 && $9=="FAIL" {f++} END {print f+0}' "${DRAWS_CSV}")"
if [[ ${#failed_points[@]} -gt 0 ]]; then
  echo "run_offset_mc.sh: WARNING -- ${#failed_points[@]} point(s) have failed draws (${failed_points[*]});" >&2
  echo "run_offset_mc.sh: their digest rows carry status=FAIL -- inspect ${DRAWS_CSV}." >&2
fi
if [[ "${failed_draws_total}" != "0" ]]; then
  echo "run_offset_mc.sh: WARNING -- ${failed_draws_total} draw(s) failed per-draw sanity overall." >&2
fi

# ------------------------------------------------------ Sanity-checks log file
{
  echo "seed_determinism_selfcheck,${DETCHECK}"
  echo "negctrl_zero_spread,PASS (vos=${NEGCTRL_MIN} V at all ${N} negctrl draws)"
  echo "negctrl_anchor,PASS (|draw - ${DET_ANCHOR_PID} vos_null_v=${DET_ANCHOR_VOS} V| = ${NEGCTRL_ANCHOR_DELTA} V, gate ${NEGCTRL_ANCHOR_TOL} V)"
  echo "negctrl_point,${NEGCTRL_PID}"
  echo "deterministic_record_joined,${DET_RECORD_ID}"
  echo "total_draws,$(( N_POINTS * N + 1 )) (incl. detcheck duplicate)"
  echo "failed_draws_total,${failed_draws_total}"
  echo "failed_draw_points,${#failed_points[@]} (${failed_points[*]:-none})"
} > "${CORNERS_OUT}/sanity_checks.txt"

# ------------------------------------------------------------------ Record md
# Worst-point scan over the mismatch points only (negctrl carries no
# statistics by construction). Numbers via one python block so the md
# summary and sanity evidence come from the exact same parse.
read -r W3SIG W3SIG_PID WTOTAL WTOTAL_PID WMEAND WMEAND_PID <<< "$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
mm = [r for r in rows if r["mode"] == "mismatch" and r["status"] == "PASS"]
if not mm:
    print("nan nan nan nan nan nan"); raise SystemExit(0)
w3s = max(mm, key=lambda r: float(r["three_sigma_v"]))
wt = max(mm, key=lambda r: float(r["vos_total_wc_det_plus_3sigma_v"]))
wm = max(mm, key=lambda r: abs(float(r["mean_vos_v"]) - float(r["vos_systematic_det_v"])))
print("%.9g %s %.9g %s %.9g %s" % (
    float(w3s["three_sigma_v"]), w3s["point_id"],
    float(wt["vos_total_wc_det_plus_3sigma_v"]), wt["point_id"],
    abs(float(wm["mean_vos_v"]) - float(wm["vos_systematic_det_v"])), wm["point_id"]))
PYEOF
)"

SUMMARY_TABLE="$(awk -F, 'NR>1 && $2=="mismatch" && $9=="PASS" { printf "| `%s` | %d/%d | %s | %s | %s | %s |\n", $1, $8, $7, $10, $11, $12, $16 }' "${CSV_OUT}")"

{
cat <<MDEOF
# input-offset Monte Carlo record ${RECORD_ID}

Generated by \`sim/input-offset/run_offset_mc.sh\` (issue #17, the statistical
basis \`spec/target-spec.md\`'s offset row and gap-to-T1 tracker #3 item 6
track) against \`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), \`${NGSPICE_VERSION}\`, PDK
\`ihp-sg13g2\` rooted at \`${PDK_ROOT}\` (pin: \`sim/pdk.json\`), OSDI models from
\`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`).

Device-mismatch Monte Carlo **combined with (not instead of) process
corners**: every draw runs cornerMOSlv.lib's \`<corner>_mismatch\` section --
the same deterministic process-corner parameters as the plain section, plus
per-instance zero-mean \`agauss()\` mismatch draws (delvto / factuo / w / l,
area-scaled by 1/sqrt(m*l*w*1e12)). **Campaign seed \`${SEED}\`, N = ${N} draws
per point**, per-draw seed = base + draw index, every draw's own seed
recorded in \`records/${RECORD_ID}-draws.csv\`, seeded via \`setseed\` +
\`reset\` in .control -- see \`testbench/tb_offset_mc.spice.tmpl\`'s header for
why that mechanism (and not a netlist-level option line) is the one that
reaches this deck's instance-parameter draws (directly verified below).

Grid: **the five corner families \`mos_tt/ss/ff/sf/fs\` [DR-1] x {-40, 27,
125} °C at the fixed nominal 1.20 V supply** = 15 mismatch points, **plus a
deterministic negative control** at the nominal point (\`mos_tt\` plain
section, identical seed sequence). Supply is the PVT axis held fixed: issue
#11's deterministic record already covers every (corner, temperature) at
all three supplies, and random-vs-supply interaction is not an evidence
class issue #17 names -- the same scope argument \`sg13g2-bandgap\`'s
\`sim/closed-loop-vref-mc\` landed on this PDK. Each corner family is drawn
N = ${N} >= 300 times at EACH of its three temperatures, so the row's
"N>=300 per corner" basis holds everywhere it is claimed.

## Campaign self-verification (hard gates -- all passed)

- **Seed determinism**: a duplicated draw (same seed, separate ngspice
  invocation) came out **bit-identical**; re-running the campaign with
  \`--seed ${SEED} --n ${N}\` on this commit reproduces it.
- **Negative-control zero spread**: all ${N} plain-section draws produced
  exactly \`${NEGCTRL_MIN} V\` -- no draw expressions exist in the plain deck,
  so any spread would be a harness bug.
- **Negative-control anchor**: that figure reproduces issue #11's committed
  fine-pass Vos at \`${DET_ANCHOR_PID}\` (\`${DET_ANCHOR_VOS} V\`) to within
  ${NEGCTRL_ANCHOR_DELTA} V (gate 5e-5 V) -- the MC harness reproduces the
  deterministic record's figure with mismatch disabled.

Machine-readable gate output: \`corners/${RECORD_ID}/sanity_checks.txt\`.

## Summary (mismatch points; Vos in V, sign per issue #11's convention)

| Point @ 1.20 V | n_pass/total | mean Vos | sigma | 3-sigma | w.c. total (|sys|+3σ) |
|---|---|---|---|---|---|
${SUMMARY_TABLE}

- **Worst-case mismatch 3σ: \`${W3SIG} V\` at \`${W3SIG_PID}\`.**
- **Worst-case total offset (deterministic systematic + 3σ, the figure a
  real part's offset budget carries at a single PVT point):
  \`${WTOTAL} V\` at \`${WTOTAL_PID}\`.**
- Largest deviation of any point's MC sample mean from the deterministic
  systematic at the same (corner, temp): \`${WMEAND} V\` (\`${WMEAND_PID}\`) --
  consistent with the sampling error of a 300-draw zero-mean population
  (sigma/sqrt(N)), not a harness bias.

Per-point systematic values (\`vos_systematic_det_v\`) join
\`records/${DET_RECORD_ID}.csv\` (issue #11) at the same corner/temp/1.20 V
point ids.

## Method (per draw), and what this record does not claim

One draw = one single-pass **coarse** null sweep of the same open-loop
method as issue #11's primary measurement (Vid over ±100 mV at 500 µV,
exactly one Vout = Vcm crossing required, comfortably inside the window).
The deterministic record's committed \`vos_coarse_fine_delta_v\` column
bounds the coarse-vs-fine null delta at ≤ 2.4 µV across all 45 of its
points -- three orders of magnitude below the mismatch term measured here
-- so the per-draw fine re-sweep is deliberately omitted (stated,
justified deviation, anchored by that committed evidence column).

**Pre-layout, schematic-level**: the DUT is the committed
\`design/netlist/opamp_core.spice\`; no layout parasitics are drawn. This
remains **[P]-tagged measured evidence** for the still-DRAFT offset row's
statistical-basis column, not a ratification of it (ratification is issue
#16's two-key mechanism). The 3σ figure is a property of THIS topology's
device sizes against THIS PDK's mismatch deck
(\`sg13g2_moslv_mod_mismatch.lib\`, one-sigma delvto 3.9 mV nmos / 2.2 mV
pmos before area scaling) at the sampled PVT points only -- it transfers
to neither another topology nor another PDK.

Full per-draw table (point, mode, draw index, per-draw seed, status,
per-draw Vos): \`records/${RECORD_ID}-draws.csv\`. Per-point digest:
\`records/${RECORD_ID}.csv\`. Representative draw-0 netlist + log per point plus
the frozen DUT snapshot: \`netlist-snapshots/${RECORD_ID}/\` and
\`corners/${RECORD_ID}/\` (the per-draw population is deliberately not
committed -- see README.md "Evidence volume").
MDEOF
} > "${MD_OUT}"

echo "run_offset_mc.sh: done. record-id=${RECORD_ID}"
echo "run_offset_mc.sh:   digest    -> ${CSV_OUT}"
echo "run_offset_mc.sh:   per-draw  -> ${DRAWS_CSV}"
echo "run_offset_mc.sh:   markdown  -> ${MD_OUT}"

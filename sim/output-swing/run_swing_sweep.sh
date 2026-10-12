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
# shellcheck disable=SC2034  # consumed by sim/preflight.sh once sourced below
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/preflight.sh"
sg13g2_preflight_require_netlist

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
if [[ -z "${AC_RECORD_CSV:-}" ]]; then
  AC_RECORD_CSV="$(sg13g2_latest_record_csv "${SIM_DIR}/open-loop-ac/records")"
fi
if [[ -z "${AC_RECORD_CSV}" || ! -s "${AC_RECORD_CSV}" ]]; then
  echo "run_swing_sweep.sh: no sim/open-loop-ac/records/*.csv found -- the peak-gain" >&2
  echo "run_swing_sweep.sh: cross-check column needs that experiment's per-point Av0 column." >&2
  exit 3
fi
if [[ -z "${OFFSET_RECORD_CSV:-}" ]]; then
  OFFSET_RECORD_CSV="$(sg13g2_latest_record_csv "${SIM_DIR}/input-offset/records")"
fi
if [[ -z "${OFFSET_RECORD_CSV}" || ! -s "${OFFSET_RECORD_CSV}" ]]; then
  OFFSET_RECORD_CSV=""
fi

OSDI_DIR="${SG13G2_OSDI_DIR}"
sg13g2_preflight_record_paths

# Run-time PDK/model identity, BEFORE the first solver (issue #209): captured
# into private scratch outside records/, rechecked and published at finalize.
# Also the consumer side of the AC-source admission check below (issue #224).
ENV_SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/output-swing-${RECORD_ID}.XXXXXX")"
ENV_BEGIN="${ENV_SCRATCH}/${RECORD_ID}.env.json"
AC_JOIN_PROV="${ENV_SCRATCH}/${RECORD_ID}.ac-join.json"
sg13g2_env_identity_begin "${RECORD_ID}" "${ENV_BEGIN}"

DUT_NETLIST_SNAPSHOT="${SNAPSHOTS_OUT}/opamp_core.spice"
cp "${DUT_NETLIST_SRC}" "${DUT_NETLIST_SNAPSHOT}"

# --- Sweep grid ----------------------------------------------------------
# Process corner grid: cornerMOSlv.lib's five sections [DR-1]; temperature x
# supply grid from spec/target-spec.md Sec 1. Identical 45-point grid to
# sim/open-loop-ac/ and sim/input-offset/, by construction -- the benches'
# records are meant to be joined point-by-point on point_id.
CORNERS=("${SG13G2_MOS_CORNERS[@]}")
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
# shellcheck disable=SC2034  # consumed by sg13g2_render_netlist (sim/preflight.sh) after this point
CL_F="2e-12"

# --- AC-source admission (issue #224) ------------------------------------
# Default-selected and explicit AC_RECORD_CSV sources get the SAME check,
# before the first solver: the source must carry a verified identity sidecar
# equal to this run's captured environment, a byte-identical DUT snapshot,
# the same load / common-mode configuration, and one successful finite row
# per requested grid point. On rejection: exit 3, nothing simulated.
sg13g2_ac_join_admit "${AC_RECORD_CSV}" "${ENV_BEGIN}" "${DUT_NETLIST_SNAPSHOT}" "${RECORD_ID}" \
  "${AC_JOIN_PROV}" "${CL_F}" "${CORNERS[*]}" "${TEMPS[*]}" "${VDDS[*]}" av0_db ivdd_total_a

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
      sg13g2_render_netlist --vcm "${vcm}" "${EXPERIMENT_DIR}/testbench/tb_swing.spice.tmpl" "${coarse_net}" \
        "${corner}" "${temp}" "${vdd}" \
        -e "s|@@PASS_LABEL@@|coarse|g" \
        -e "s|@@VID_START@@|${COARSE_START}|g" \
        -e "s|@@VID_STOP@@|${COARSE_STOP}|g" \
        -e "s|@@VID_STEP@@|${COARSE_STEP}|g" \
        -e "s|@@WRDATA_VECTORS@@|${COARSE_VECTORS}|g" \
        -e "s|@@SWEEP_CSV@@|${coarse_csv}|g"

      rc=0
      ngspice -b "${coarse_net}" > "${coarse_log}" 2>&1 || rc=$?
      if sg13g2_sim_broken "${rc}" "${coarse_log}" "${coarse_csv}"; then
        echo "run_swing_sweep.sh: SIM FAILED ${point_id} coarse pass (rc=${rc}) -- see ${coarse_log}" >&2
        sim_fail_points+=("${point_id}:coarse")
        continue
      fi

      # --- pass 2: fine sweep centered on the coarse crossing -----------
      # Coarse post-processing in one python read: the unique Vout = Vcm
      # crossing (same uniqueness rule as sim/input-offset/'s coarse pass)
      # and both hard-clipped plateau levels.
      # and both hard-clipped plateau levels. The definition lives in
      # swing_post.py (stdlib only), shared with the offline raw-evidence
      # audit in signoff/characterization/generate.py (issue #230); the
      # audit refuses any other COARSE_*/FINE_* configuration.
      read -r vos_coarse n_cross_coarse clip_high clip_low plateau_ok < <(python3 "${SCRIPT_DIR}/swing_post.py" coarse "${coarse_csv}" "${vcm}" || true)
      if [[ "${n_cross_coarse}" != "1" || "${vos_coarse}" == "nan" ]]; then
        echo "run_swing_sweep.sh: ANALYSIS FAILED ${point_id} -- coarse sweep has ${n_cross_coarse} Vout=Vcm crossings (expected exactly 1), see ${coarse_csv}" >&2
        sim_fail_points+=("${point_id}:coarse_crossings=${n_cross_coarse}")
        continue
      fi

      fine_start="$(python3 -c "print(${vos_coarse} - ${FINE_HALFSPAN})")"
      fine_stop="$(python3 -c "print(${vos_coarse} + ${FINE_HALFSPAN})")"
      sg13g2_render_netlist --vcm "${vcm}" "${EXPERIMENT_DIR}/testbench/tb_swing.spice.tmpl" "${fine_net}" \
        "${corner}" "${temp}" "${vdd}" \
        -e "s|@@PASS_LABEL@@|fine|g" \
        -e "s|@@VID_START@@|${fine_start}|g" \
        -e "s|@@VID_STOP@@|${fine_stop}|g" \
        -e "s|@@VID_STEP@@|${FINE_STEP}|g" \
        -e "s|@@WRDATA_VECTORS@@|${FINE_VECTORS}|g" \
        -e "s|@@SWEEP_CSV@@|${fine_csv}|g"

      rc=0
      ngspice -b "${fine_net}" > "${fine_log}" 2>&1 || rc=$?
      if sg13g2_sim_broken "${rc}" "${fine_log}" "${fine_csv}"; then
        echo "run_swing_sweep.sh: SIM FAILED ${point_id} fine pass (rc=${rc}) -- see ${fine_log}" >&2
        sim_fail_points+=("${point_id}:fine")
        continue
      fi

      # --- sibling-record cross-reference inputs ------------------------
      av0_db_ac="$(sg13g2_ac_lookup av0_db "${point_id}")"
      [[ -n "${av0_db_ac}" ]] || av0_db_ac="nan"
      ivdd_ac="$(sg13g2_ac_lookup ivdd_total_a "${point_id}")"
      [[ -n "${ivdd_ac}" ]] || ivdd_ac="nan"
      vos_off="nan"
      if [[ -n "${OFFSET_RECORD_CSV}" ]]; then
        vos_off="$(sg13g2_csv_lookup "${OFFSET_RECORD_CSV}" vos_null_v "${point_id}")"
        [[ -n "${vos_off}" ]] || vos_off="nan"
      fi

      # --- per-point post-processing ------------------------------------
      # Reads the fine sweep, applies the -6 dB incremental-gain criterion
      # to both rail-ward boundaries of the linear region, reads the
      # mid-swing operating point, and applies the per-point sanity rule
      # (README.md "Per-point sanity checks").
      # Reads the fine sweep via the shared swing_post.py module (issue
      # #230): applies the -6 dB incremental-gain criterion to both
      # rail-ward boundaries of the linear region, reads the mid-swing
      # operating point, and applies the per-point sanity rule (README.md
      # "Per-point sanity checks"). An analysis that cannot be made still
      # prints the 17-field row, with op_pass=0 and the reason on stderr.
      row="$(python3 "${SCRIPT_DIR}/swing_post.py" fine "${fine_csv}" "${vdd}" "${vcm}" \
        "${clip_high}" "${clip_low}" "${plateau_ok}" "${vos_coarse}" \
        "${av0_db_ac}" "${ivdd_ac}" "${vos_off}" "${CRITERION_FRAC}")"

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

# Model-identity recheck (issue #209) and AC-join provenance (issue #224),
# right after the last solver and before any record file is finalized: on
# drift this exits 4 with only the incomplete .csv.raw/corners/ left. On a
# match it publishes the BEGIN capture as records/<id>.env.json and the
# accepted source's hashes/compatibility basis as records/<id>.ac-join.json.
sg13g2_env_identity_finalize "${RECORD_ID}" "${ENV_BEGIN}" "${RECORDS_DIR}/${RECORD_ID}.env.json"
sg13g2_ac_join_publish "${AC_JOIN_PROV}" "${RECORDS_DIR}/${RECORD_ID}.ac-join.json"
rm -f "${ENV_SCRATCH}/${RECORD_ID}.env.json" "${ENV_SCRATCH}/${RECORD_ID}.ac-join.json" "${ENV_SCRATCH}/${RECORD_ID}.ac-source.csv"
rmdir "${ENV_SCRATCH}" 2>/dev/null || true

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

Imported AC values come from the admitted source record \`${AC_RECORD_ID}\`;
its CSV/sidecar/DUT-snapshot hashes and the compatibility basis (identical
DUT bytes, equal model-environment identity, same load and common-mode
configuration, unique successful finite rows for every grid point) are bound
in \`records/${RECORD_ID}.ac-join.json\`; this run's own PDK/model identity
is \`records/${RECORD_ID}.env.json\`.

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

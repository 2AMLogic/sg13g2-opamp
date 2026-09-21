#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/cmrr-psrr/run_cmrr_psrr_sweep.sh
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
# CMRR and PSRR characterization of design/opamp_core.spice across the full
# cornerMOSlv.lib process x temperature x supply grid (mos_tt/ss/ff/sf/fs x
# -40/27/125 C x 1.08/1.20/1.32 V = 45 points), two ngspice runs per point
# (one per harness, 90 total):
#
#   1. CMRR harness (testbench/tb_cmrr.spice.tmpl) -- common-mode AC
#      injected in phase on both inputs around the same self-biased DC
#      operating point as sim/open-loop-ac/; measures Acm(f), the
#      common-mode gain. CMRR = Av0/Acm.
#   2. PSRR harness (testbench/tb_psrr.spice.tmpl) -- supply AC injected on
#      VDD with the signal input quiet; measures Avs(f), the supply-to-output
#      gain. PSRR+ = Av0/Avs.
#
# The differential open-loop gain Av0 in every ratio is NOT re-measured here:
# it comes from the SAME grid point's av0_db column of the committed
# sim/open-loop-ac/ records (per issue #14's own wording). Default is the
# newest committed record there; override with AC_RECORD_CSV=<path>. The
# transfer's validity depends on both benches sharing one DC operating
# point, which this script cross-checks two ways per point (see
# op_xcheck_psrr_delta_v and ol_vout_delta_v in the CSV, and "Per-point
# sanity checks" in README.md).
#
# Both harnesses sweep 10 mHz - 1 GHz so the DC figure is read from a
# machine-verified flat low-frequency shelf (the PSRR transfer has a real
# zero near 1.5 Hz -- see tb_psrr.spice.tmpl's header); a per-point plateau
# guard (acm/avs at 10 mHz vs 0.1 Hz, within 0.05 dB) is recorded as
# *_plateau_delta_db and summarized in sanity_checks.txt.
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- same
# fleet convention as sim/open-loop-ac/run_pvt_sweep.sh,
# sim/input-offset/run_offset_sweep.sh and sim/gm-id-characterization/
# in this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_cmrr_psrr_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_cmrr_psrr_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_cmrr_psrr_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_cmrr_psrr_sweep.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  echo "run_cmrr_psrr_sweep.sh:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
  exit 3
fi

# --- Open-loop AC record cross-reference ---------------------------------
# Both ratios this experiment reports divide the SAME grid point's Av0 out
# of sim/open-loop-ac/ (issue #14's own wording: "differential open-loop
# gain (from sim/open-loop-ac/'s existing Av0 record, same corner)").
# Default to the newest committed record there; override with
# AC_RECORD_CSV=<path>.
if [[ -z "${AC_RECORD_CSV:-}" ]]; then
  AC_RECORD_CSV=""
  while IFS= read -r _f; do AC_RECORD_CSV="${_f}"; done < <(
    find "${SIM_DIR}/open-loop-ac/records" -maxdepth 1 -name '*.csv' 2>/dev/null | sort
  )
fi
if [[ -z "${AC_RECORD_CSV}" || ! -s "${AC_RECORD_CSV}" ]]; then
  echo "run_cmrr_psrr_sweep.sh: no sim/open-loop-ac/records/*.csv found -- this experiment's" >&2
  echo "run_cmrr_psrr_sweep.sh: CMRR/PSRR ratios need that experiment's per-point Av0 column." >&2
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
# Same grid as sim/open-loop-ac/: cornerMOSlv.lib's five sections [DR-1],
# crossed at testbench time with spec/target-spec.md Sec 1's temperature
# and supply axes.
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

echo "point_id,corner,temp_c,vdd_v,vcm_v,op_pass,vout_dc_v,vd1_dc_v,vd2_dc_v,vtail_dc_v,vibias_dc_v,ivdd_total_a,av0_db,acm0_db,acm_1khz_db,cmrr_db,cmrr_1khz_db,cmrr_plateau_delta_db,avs0_db,avs_1khz_db,psrr_db,psrr_1khz_db,psrr_plateau_delta_db,op_xcheck_psrr_delta_v,ol_vout_dc_v,ol_vout_delta_v" > "${CSV_OUT}.raw"

total=0
passed=0
op_fail_points=()
sim_fail_points=()
plateau_fail_points=()
psrr_xcheck_fail_points=()
ol_xcheck_fail_points=()

read_ac_shelf() {
  # Parse a wrdata AC CSV (freq, db, freq, ph columns); print:
  #   <db at lowest swept frequency> <db at 10x that frequency>
  #   <db at 1 kHz> <delta(lowest, 10x-lowest)>
  python3 - "$1" <<'PYEOF'
import sys, math

rows = []
with open(sys.argv[1]) as f:
    for line in f:
        parts = line.split()
        if len(parts) < 4:
            continue
        # wrdata column layout: (scale,value) pair per requested vector --
        # col1=freq, col2=vout_db, col3=freq (dup), col4=vout_ph. Same
        # gotcha sim/open-loop-ac/ documents from gm-id-characterization.
        rows.append((float(parts[0]), float(parts[1])))

if not rows:
    print("nan nan nan nan")
else:
    db0 = rows[0][1]
    f0 = rows[0][0]
    # nearest row to 10x the lowest frequency (exact row exists: dec 20)
    f10 = 10.0 * f0
    db10 = min(rows, key=lambda r: abs(math.log10(r[0] / f10)))[1]
    # nearest row to 1 kHz
    db1k = min(rows, key=lambda r: abs(math.log10(r[0] / 1e3)))[1]
    delta = abs(db0 - db10)
    print(f"{db0:.6g} {db10:.6g} {db1k:.6g} {delta:.6g}")
PYEOF
}

for corner in "${CORNERS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      total=$((total + 1))
      point_id="${corner}_${temp}C_${vdd}V"
      vcm="$(python3 -c "print(${vdd}/2)")"

      # --- Av0 + open-loop op point for this grid point (joined, not
      # re-measured; see header).
      read -r ol_av0_db ol_vout_dc < <(python3 - "${AC_RECORD_CSV}" "${corner}" "${temp}" "${vdd}" <<'PYEOF'
import csv, sys

want = (sys.argv[2], sys.argv[3], sys.argv[4])
for r in csv.DictReader(open(sys.argv[1])):
    if (r["corner"], r["temp_c"], r["vdd_v"]) == want:
        print(f"{r['av0_db']} {r['vout_dc_v']}")
        break
else:
    print("MISSING MISSING")
PYEOF
)
      if [[ "${ol_av0_db}" == "MISSING" ]]; then
        echo "run_cmrr_psrr_sweep.sh: SIM FAILED ${point_id} -- no av0_db row in ${AC_RECORD_CSV} (${AC_RECORD_ID})." >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      for harness in cmrr psrr; do
        netlist="${SNAPSHOTS_OUT}/${point_id}_${harness}.spice"
        log="${CORNERS_OUT}/${point_id}_${harness}.log"
        ac_csv="${CORNERS_OUT}/${point_id}_${harness}_ac.csv"

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
          -e "s|@@AC_CSV@@|${ac_csv}|g" \
          "${EXPERIMENT_DIR}/testbench/tb_${harness}.spice.tmpl" > "${netlist}"

        rc=0
        ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

        if [[ ${rc} -ne 0 ]] || ! [[ -s "${ac_csv}" ]] || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence" "${log}"; then
          echo "run_cmrr_psrr_sweep.sh: SIM FAILED ${point_id} ${harness} (rc=${rc}) -- see ${log}" >&2
          sim_fail_points+=("${point_id}")
          continue 2
        fi
      done

      # OP_* lines: the two harnesses are DC-identical by construction;
      # the CMRR harness's op is the point of record, the PSRR harness's
      # is a structural-equivalence cross-check.
      vout="$(grep '^OP_VOUT ' "${CORNERS_OUT}/${point_id}_cmrr.log" | awk '{print $2}')"
      vd1="$(grep '^OP_VD1 ' "${CORNERS_OUT}/${point_id}_cmrr.log" | awk '{print $2}')"
      vd2="$(grep '^OP_VD2 ' "${CORNERS_OUT}/${point_id}_cmrr.log" | awk '{print $2}')"
      vtail="$(grep '^OP_VTAIL ' "${CORNERS_OUT}/${point_id}_cmrr.log" | awk '{print $2}')"
      vibias="$(grep '^OP_VIBIAS ' "${CORNERS_OUT}/${point_id}_cmrr.log" | awk '{print $2}')"
      ivdd="$(grep '^OP_IVDD ' "${CORNERS_OUT}/${point_id}_cmrr.log" | awk '{print $2}')"
      vout_psrr="$(grep '^OP_VOUT ' "${CORNERS_OUT}/${point_id}_psrr.log" | awk '{print $2}')"

      if [[ -z "${vout}" || -z "${vd1}" || -z "${vd2}" || -z "${vtail}" || -z "${ivdd}" || -z "${vout_psrr}" ]]; then
        echo "run_cmrr_psrr_sweep.sh: SIM FAILED ${point_id} -- missing OP_* line(s), see ${CORNERS_OUT}/${point_id}_{cmrr,psrr}.log" >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      # --- Per-point DC sanity check, same rule as sim/open-loop-ac/:
      # output within 15% of VDD of mid-rail, and no internal node fully
      # railed -- a non-regulating point must not read as a plausible
      # rejection ratio. Same necessary-not-sufficient scope as open-loop's
      # check (see README.md "Per-point sanity checks").
      op_pass="$(python3 -c "
vdd=${vdd}; vcm=${vcm}
vout=${vout}; vd1=${vd1}; vd2=${vd2}; vtail=${vtail}
tol=0.15*vdd
rail_lo=0.02*vdd
rail_hi=vdd-0.02*vdd
ok = (abs(vout-vcm) <= tol)
for node in (vd1, vd2, vtail, vout):
    if not (rail_lo <= node <= rail_hi):
        ok = False
print('1' if ok else '0')
")"

      read -r acm0_db _acm10x_db acm_1k_db acm_delta < <(read_ac_shelf "${CORNERS_OUT}/${point_id}_cmrr_ac.csv")
      read -r avs0_db _avs10x_db avs_1k_db avs_delta < <(read_ac_shelf "${CORNERS_OUT}/${point_id}_psrr_ac.csv")

      # Derived figures for this point, one pass: the two ratios at the DC
      # shelf and at 1 kHz, plus the two shared-operating-point cross-check
      # deltas (CMRR-harness vout vs PSRR-harness vout: the two templates
      # are DC-identical by construction, so any delta is a template-drift
      # alarm; this bench's vout vs the joined open-loop record's vout_dc_v:
      # the ratio's validity rests on both benches sharing one op point).
      read -r cmrr_db cmrr_1k_db psrr_db psrr_1k_db op_xcheck_psrr_delta_v ol_vout_delta_v < <(python3 -c "
def g(x):
    v = float(x)
    return v
ol_av0 = g('${ol_av0_db}')
acm0 = g('${acm0_db}'); acm1k = g('${acm_1k_db}')
avs0 = g('${avs0_db}'); avs1k = g('${avs_1k_db}')
cmrr_db = ol_av0 - acm0
cmrr_1k = ol_av0 - acm1k
psrr_db = ol_av0 - avs0
psrr_1k = ol_av0 - avs1k
ops_x = abs(g('${vout}') - g('${vout_psrr}'))
ol_d = abs(g('${vout}') - g('${ol_vout_dc}'))
print(f'{cmrr_db:.6g} {cmrr_1k:.6g} {psrr_db:.6g} {psrr_1k:.6g} {ops_x:.6g} {ol_d:.6g}')")

      if [[ "$(python3 -c "print(1 if float('${acm_delta}') > 0.05 or float('${avs_delta}') > 0.05 else 0)")" == "1" ]]; then
        plateau_fail_points+=("${point_id}")
      fi
      if [[ "$(python3 -c "print(1 if float('${op_xcheck_psrr_delta_v}') > 1e-3 else 0)")" == "1" ]]; then
        psrr_xcheck_fail_points+=("${point_id}")
      fi
      if [[ "$(python3 -c "print(1 if float('${ol_vout_delta_v}') > 1e-3 else 0)")" == "1" ]]; then
        ol_xcheck_fail_points+=("${point_id}")
      fi

      echo "${point_id},${corner},${temp},${vdd},${vcm},${op_pass},${vout},${vd1},${vd2},${vtail},${vibias},${ivdd},${ol_av0_db},${acm0_db},${acm_1k_db},${cmrr_db},${cmrr_1k_db},${acm_delta},${avs0_db},${avs_1k_db},${psrr_db},${psrr_1k_db},${avs_delta},${op_xcheck_psrr_delta_v},${ol_vout_dc},${ol_vout_delta_v}" >> "${CSV_OUT}.raw"

      if [[ "${op_pass}" != "1" ]]; then
        op_fail_points+=("${point_id}")
      fi
      passed=$((passed + 1))
    done
  done
done

if [[ ${passed} -eq 0 ]]; then
  echo "run_cmrr_psrr_sweep.sh: no points passed -- refusing to write a summary." >&2
  exit 1
fi

mv "${CSV_OUT}.raw" "${CSV_OUT}"

{
  echo "op_pass_count,${passed} of ${total}, op_sane failures: ${#op_fail_points[@]} (${op_fail_points[*]:-none})"
  echo "sim_fail_count,${#sim_fail_points[@]} (${sim_fail_points[*]:-none})"
  echo "plateau_guard_failures (>0.05 dB),${#plateau_fail_points[@]} (${plateau_fail_points[*]:-none})"
  echo "psrr_xcheck_failures (>1e-3 V),${#psrr_xcheck_fail_points[@]} (${psrr_xcheck_fail_points[*]:-none})"
  echo "ol_vout_xcheck_failures (>1e-3 V),${#ol_xcheck_fail_points[@]} (${ol_xcheck_fail_points[*]:-none})"
} > "${CORNERS_OUT}/sanity_checks.txt"

# --- Completeness: all 45 (corner, temp, vdd) cells must have run. -------
n_rows=$(($(wc -l < "${CSV_OUT}") - 1))
expected=$(( ${#CORNERS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} ))
if [[ "${n_rows}" -ne "${expected}" ]]; then
  echo "run_cmrr_psrr_sweep.sh: WARNING -- ${n_rows} rows written, expected ${expected} (${#sim_fail_points[@]} sim failures)" >&2
fi

# --- Worst-corner summary (per metric) for the record's README-style table.
WORST="$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys

rows = list(csv.DictReader(open(sys.argv[1])))
def numeric(rows, key, pick):
    out = []
    for r in rows:
        try:
            v = float(r[key])
        except ValueError:
            continue
        if v == v:  # not NaN
            out.append((v, r))
    return pick(out, key=lambda t: t[0]) if out else None

def line(label, t):
    if t is None:
        print(f"{label}: n/a")
        return
    v, r = t
    print(f"{label}: {v:.4g} at {r['point_id']}")

line("worst_cmrr_db", numeric(rows, "cmrr_db", min))
line("best_cmrr_db", numeric(rows, "cmrr_db", max))
line("worst_cmrr_1khz_db", numeric(rows, "cmrr_1khz_db", min))
line("best_cmrr_1khz_db", numeric(rows, "cmrr_1khz_db", max))
line("worst_psrr_db", numeric(rows, "psrr_db", min))
line("best_psrr_db", numeric(rows, "psrr_db", max))
line("worst_psrr_1khz_db", numeric(rows, "psrr_1khz_db", min))
line("best_psrr_1khz_db", numeric(rows, "psrr_1khz_db", max))
PYEOF
)"

cat > "${MD_OUT}" <<EOF
# cmrr-psrr record ${RECORD_ID}

Generated by \`sim/cmrr-psrr/run_cmrr_psrr_sweep.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`). Both
ratios divide the per-point \`av0_db\` of the open-loop record
\`sim/open-loop-ac/records/${AC_RECORD_ID}.csv\` (joined by grid point, not
re-measured; the transfer's shared-operating-point assumption is
cross-checked per point -- see \`op_xcheck_psrr_delta_v\` and
\`ol_vout_delta_v\` columns).

Grid: cornerMOSlv.lib \`mos_tt/ss/ff/sf/fs\` [DR-1] x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${expected} points,
two harnesses per point (CMRR, PSRR+), into \`CL = ${CL_F} F\` [DR-1].
Both harnesses sweep 10 mHz - 1 GHz; Acm0/Avs0 are read at the 10 mHz
flat low-frequency shelf and re-verified flat by the per-point plateau
guard (delta vs 0.1 Hz, tolerance 0.05 dB). ${passed} of ${total} points
simulated successfully; ${#sim_fail_points[@]} simulation failure(s)
(${sim_fail_points[*]:-none}); ${#op_fail_points[@]} point(s) failed the
per-point DC sanity check (${op_fail_points[*]:-none});
${#plateau_fail_points[@]} plateau-guard failure(s)
(${plateau_fail_points[*]:-none}); ${#psrr_xcheck_fail_points[@]}
CMRR-vs-PSRR harness op-point cross-check failure(s)
(${psrr_xcheck_fail_points[*]:-none}); ${#ol_xcheck_fail_points[@]}
open-loop op-point cross-check failure(s) (${ol_xcheck_fail_points[*]:-none})
-- see README.md "Per-point sanity checks" for what each check does and
does not verify.

## Worst/best-corner summary (DC shelf and 1 kHz)

\`\`\`
${WORST}
\`\`\`

Full per-point data (joined Av0, Acm0/Avs0 and the derived CMRR/PSRR+ at
the DC shelf and at 1 kHz, DC operating point, plateau-guard and
shared-op-point cross-check deltas) is in \`records/${RECORD_ID}.csv\`.
Raw per-point ngspice logs and AC sweep data (10 mHz - 1 GHz, both
harnesses) are in \`corners/${RECORD_ID}/\`.
EOF

echo "run_cmrr_psrr_sweep.sh: wrote ${CSV_OUT} and ${MD_OUT} (${passed}/${total} points, ${#op_fail_points[@]} op-sanity failures, ${#plateau_fail_points[@]} plateau-guard failures)"

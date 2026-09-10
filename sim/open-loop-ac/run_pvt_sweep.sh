#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/open-loop-ac/run_pvt_sweep.sh
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
# Standalone open-loop AC characterization of design/opamp_core.spice: DC
# bias established by an ideal-inductor DC-feedback trick (see
# testbench/tb_openloop_ac.spice.tmpl's own header), AC test signal
# injected at the non-inverting input, swept 1 Hz - 1 GHz, across the full
# cornerMOSlv.lib process x temperature x supply grid (mos_tt/ss/ff/sf/fs x
# -40/27/125 C x 1.08/1.20/1.32 V = 45 points), measuring Av0, unity-gain
# frequency (GBW into CL = 2 pF [DR-1]), phase margin, gain margin and Iq
# per point. Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- same
# fleet convention as sim/gm-id-characterization/run_gmid_sweep.sh in this
# repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_pvt_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_pvt_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_pvt_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_pvt_sweep.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  echo "run_pvt_sweep.sh:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
  exit 3
fi

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
# Process corner grid: cornerMOSlv.lib's five sections [DR-1].
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
# Temperature x supply grid: spec/target-spec.md Sec 1 ("Operating
# temperature", "Supply voltage, VDD") -- crossed with the corner grid "at
# testbench time", which is exactly what this bench is.
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

echo "point_id,corner,temp_c,vdd_v,vcm_v,op_pass,vout_dc_v,vd1_dc_v,vd2_dc_v,vtail_dc_v,vibias_dc_v,ivdd_total_a,ivdd_signal_path_a,av0_db,gbw_hz,pm_deg,gm_status,gm_db,gm_freq_hz" > "${CSV_OUT}.raw"

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
      netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
      log="${CORNERS_OUT}/${point_id}.log"
      ac_csv="${CORNERS_OUT}/${point_id}_ac.csv"

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
        "${EXPERIMENT_DIR}/testbench/tb_openloop_ac.spice.tmpl" > "${netlist}"

      rc=0
      ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

      if [[ ${rc} -ne 0 ]] || ! [[ -s "${ac_csv}" ]] || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence" "${log}"; then
        echo "run_pvt_sweep.sh: SIM FAILED ${point_id} (rc=${rc}) -- see ${log}" >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      vout="$(grep '^OP_VOUT ' "${log}" | awk '{print $2}')"
      vd1="$(grep '^OP_VD1 ' "${log}" | awk '{print $2}')"
      vd2="$(grep '^OP_VD2 ' "${log}" | awk '{print $2}')"
      vtail="$(grep '^OP_VTAIL ' "${log}" | awk '{print $2}')"
      vibias="$(grep '^OP_VIBIAS ' "${log}" | awk '{print $2}')"
      ivdd="$(grep '^OP_IVDD ' "${log}" | awk '{print $2}')"

      if [[ -z "${vout}" || -z "${vd1}" || -z "${vd2}" || -z "${vtail}" || -z "${ivdd}" ]]; then
        echo "run_pvt_sweep.sh: SIM FAILED ${point_id} -- missing OP_* line(s), see ${log}" >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      # --- Per-point DC sanity check (issue #9 Test Plan "Edge cases"):
      # output within 15% of VDD of mid-rail, and no internal node fully
      # railed to a supply -- a non-regulating point must not read as a
      # plausible margin. See README.md "Per-point sanity checks" for the
      # exact rule and its honest scope (a necessary, not sufficient,
      # saturation proxy -- this OSDI/PSP103 build exposes no per-device
      # queryable operating-point parameters, same limitation
      # sim/gm-id-characterization/README.md documents).
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

      # --- AC post-processing: Av0 (at the lowest swept frequency, 1 Hz --
      # see testbench header for why the L=1e18H loop-break choice keeps
      # this a clean plateau read, not corrupted by the loop-break itself),
      # unity-gain crossover (GBW), phase margin at that crossover, and
      # gain margin at the first -180 deg phase crossing above it (if any).
      read -r av0_db gbw_hz pm_deg gm_status gm_db gm_freq_hz < <(python3 - "${ac_csv}" <<'PYEOF'
import sys, math

path = sys.argv[1]
freqs, dbs, phs = [], [], []
with open(path) as f:
    for line in f:
        parts = line.split()
        if len(parts) < 4:
            continue
        # wrdata column layout: (scale,value) pair per requested vector --
        # col1=freq (vout_db's own scale), col2=vout_db, col3=freq (dup,
        # vout_ph's own scale), col4=vout_ph. See
        # sim/gm-id-characterization/README.md "wrdata column layout" for
        # the same gotcha documented once, reused here.
        freqs.append(float(parts[0]))
        dbs.append(float(parts[1]))
        phs.append(float(parts[3]))

av0_db = dbs[0]

gbw_hz = float('nan')
pm_deg = float('nan')
for i in range(1, len(dbs)):
    if dbs[i - 1] >= 0.0 > dbs[i]:
        # linear interpolation in log10(freq) vs dB between the bracketing points
        lf0, lf1 = math.log10(freqs[i - 1]), math.log10(freqs[i])
        frac = dbs[i - 1] / (dbs[i - 1] - dbs[i])
        lf_cross = lf0 + frac * (lf1 - lf0)
        gbw_hz = 10 ** lf_cross
        ph_cross = phs[i - 1] + frac * (phs[i] - phs[i - 1])
        pm_deg = 180.0 + ph_cross
        gbw_index = i
        break
else:
    gbw_index = None

gm_status = "not_reached"
gm_db = float('nan')
gm_freq_hz = float('nan')
if gbw_index is not None:
    for i in range(gbw_index, len(phs)):
        if phs[i - 1] >= -180.0 > phs[i]:
            lf0, lf1 = math.log10(freqs[i - 1]), math.log10(freqs[i])
            frac = (phs[i - 1] - (-180.0)) / (phs[i - 1] - phs[i])
            lf_cross = lf0 + frac * (lf1 - lf0)
            gm_freq_hz = 10 ** lf_cross
            db_cross = dbs[i - 1] + frac * (dbs[i] - dbs[i - 1])
            gm_db = -db_cross
            gm_status = "measured"
            break

def fmt(x):
    return "nan" if x != x else f"{x:.6g}"

print(f"{fmt(av0_db)} {fmt(gbw_hz)} {fmt(pm_deg)} {gm_status} {fmt(gm_db)} {fmt(gm_freq_hz)}")
PYEOF
)

      ivdd_signal_path="$(python3 -c "print(${ivdd} - 10e-6)")"

      echo "${point_id},${corner},${temp},${vdd},${vcm},${op_pass},${vout},${vd1},${vd2},${vtail},${vibias},${ivdd},${ivdd_signal_path},${av0_db},${gbw_hz},${pm_deg},${gm_status},${gm_db},${gm_freq_hz}" >> "${CSV_OUT}.raw"

      if [[ "${op_pass}" != "1" ]]; then
        op_fail_points+=("${point_id}")
      fi

      passed=$((passed + 1))
    done
  done
done

if [[ ${passed} -eq 0 ]]; then
  echo "run_pvt_sweep.sh: no points passed -- refusing to write a summary." >&2
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
  echo "run_pvt_sweep.sh: WARNING -- ${n_rows} rows written, expected ${expected} (${#sim_fail_points[@]} sim failures)" >&2
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

av0 = numeric(rows, "av0_db")
gbw = numeric(rows, "gbw_hz")
pm = numeric(rows, "pm_deg")
iq = numeric(rows, "ivdd_total_a")

worst_av0 = min(av0, key=lambda t: t[0]) if av0 else None
worst_gbw = min(gbw, key=lambda t: t[0]) if gbw else None
worst_pm = min(pm, key=lambda t: t[0]) if pm else None
worst_iq = max(iq, key=lambda t: t[0]) if iq else None

def line(label, t):
    if t is None:
        print(f"{label}: n/a")
        return
    v, r = t
    print(f"{label}: {v:.4g} at {r['point_id']}")

line("worst_av0_db", worst_av0)
line("worst_gbw_hz", worst_gbw)
line("worst_pm_deg", worst_pm)
line("worst_iq_a", worst_iq)
PYEOF
)"

cat > "${MD_OUT}" <<EOF
# open-loop-ac record ${RECORD_ID}

Generated by \`sim/open-loop-ac/run_pvt_sweep.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`).

Grid: cornerMOSlv.lib \`mos_tt/ss/ff/sf/fs\` [DR-1] x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${expected} points,
into \`CL = ${CL_F} F\` [DR-1]. ${passed} of ${total} points simulated
successfully; ${#sim_fail_points[@]} simulation failure(s)
(${sim_fail_points[*]:-none}); ${#op_fail_points[@]} point(s) failed the
per-point DC sanity check (${op_fail_points[*]:-none}) -- see
"Per-point sanity checks" in README.md for what that check does and does
not verify.

## Worst-corner summary

\`\`\`
${WORST}
\`\`\`

Full per-point data (Av0, unity-gain frequency/GBW, phase margin, gain
margin, DC operating point, Iq) is in
\`records/${RECORD_ID}.csv\`. Raw per-point ngspice logs and AC sweep data
are in \`corners/${RECORD_ID}/\`.
EOF

echo "run_pvt_sweep.sh: wrote ${CSV_OUT} and ${MD_OUT} (${passed}/${total} points, ${#op_fail_points[@]} op-sanity failures)"

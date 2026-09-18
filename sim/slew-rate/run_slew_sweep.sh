#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/slew-rate/run_slew_sweep.sh
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
# Large-signal step (slew-rate) characterization of
# design/opamp_core.spice: DC bias established by the same ideal-inductor
# DC-feedback trick sim/open-loop-ac/ uses, then an antiphase large-signal
# step driven into both inputs (constant input common mode Vcm = VDD/2) so
# the output slews rail-to-rail, across the full cornerMOSlv.lib process x
# temperature x supply grid (mos_tt/ss/ff/sf/fs x -40/27/125 C x
# 1.08/1.20/1.32 V = 45 points), measuring rising and falling slew rate
# into CL = 2 pF [DR-1] plus the DC operating point and Iq per point.
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- same
# fleet convention as sim/open-loop-ac/run_pvt_sweep.sh in this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_slew_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_slew_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_slew_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_slew_sweep.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  echo "run_slew_sweep.sh:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
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
# testbench time", the same 45-point grid sim/open-loop-ac/ uses.
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

# --- Drive and measurement conditions ------------------------------------
# VSTEP_V: per-input antiphase step half-amplitude, so the differential
# input is +/- 2*VSTEP_V while the input common mode stays at VDD/2. 0.3 V
# lands within ~2% of the large-drive asymptote of the measured slew rate
# while keeping both input pins inside the rails at the 1.08 V corner
# (0.24 V / 0.84 V) -- see README.md "Choosing the drive amplitude" for the
# amplitude sweep this value was chosen from.
VSTEP_V="0.3"
# Slew is read over a fixed window centred on mid-rail: VDD/2 +/- WIN_OUTER
# for the recorded number, VDD/2 +/- WIN_INNER as a ramp-linearity check
# (the two must agree, else the "ramp" was really a settling tail).
WIN_OUTER="0.15"
WIN_INNER="0.075"
# Step schedule (ns). T1 parks the output at the low rail, T2 is the
# measured rising edge, T3 the measured falling edge; each window is wide
# enough for the slowest corner's full-swing traversal with margin.
T1_NS=50
T2_NS=300
T3_NS=550
TSTOP_NS=800
EDGE_NS="0.1"     # step transition time: << the ~150 ns slewing interval
TPRINT_NS=1       # committed waveform grid (.options interp)
TMAX_NS="0.05"    # internal max timestep

t1="${T1_NS}n"; t2="${T2_NS}n"; t3="${T3_NS}n"; tstop="${TSTOP_NS}n"
t1e="$(python3 -c "print(${T1_NS}+${EDGE_NS})")n"
t2e="$(python3 -c "print(${T2_NS}+${EDGE_NS})")n"
t3e="$(python3 -c "print(${T3_NS}+${EDGE_NS})")n"

echo "point_id,corner,temp_c,vdd_v,vcm_v,vstep_v,op_pass,vout_dc_v,vd1_dc_v,vd2_dc_v,vtail_dc_v,vibias_dc_v,ivdd_total_a,ivdd_signal_path_a,sr_rise_v_per_us,sr_fall_v_per_us,sr_worst_v_per_us,sr_rise_inner_v_per_us,sr_fall_inner_v_per_us,linearity_pass,traverse_pass,drive_pass,vout_min_v,vout_max_v,window_lo_v,window_hi_v" > "${CSV_OUT}.raw"

total=0
passed=0
op_fail_points=()
check_fail_points=()
sim_fail_points=()

for corner in "${CORNERS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      total=$((total + 1))
      point_id="${corner}_${temp}C_${vdd}V"
      vcm="$(python3 -c "print('%.6g' % (${vdd}/2))")"
      vp_hi="$(python3 -c "print('%.6g' % (${vcm}+${VSTEP_V}))")"
      vp_lo="$(python3 -c "print('%.6g' % (${vcm}-${VSTEP_V}))")"
      vn_hi="$(python3 -c "print('%.6g' % (${VSTEP_V}))")"
      vn_lo="$(python3 -c "print('%.6g' % (-${VSTEP_V}))")"
      netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
      log="${CORNERS_OUT}/${point_id}.log"
      tran_csv="${CORNERS_OUT}/${point_id}_tran.csv"

      sed \
        -e "s|@@PDK_ROOT@@|${PDK_ROOT}|g" \
        -e "s|@@PDK@@|${PDK}|g" \
        -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
        -e "s|@@MOS_SECTION@@|${corner}|g" \
        -e "s|@@TEMP_C@@|${temp}|g" \
        -e "s|@@VDD_V@@|${vdd}|g" \
        -e "s|@@VCM_V@@|${vcm}|g" \
        -e "s|@@VSTEP_V@@|${VSTEP_V}|g" \
        -e "s|@@VP_HI@@|${vp_hi}|g" \
        -e "s|@@VP_LO@@|${vp_lo}|g" \
        -e "s|@@VN_HI@@|${vn_hi}|g" \
        -e "s|@@VN_LO@@|${vn_lo}|g" \
        -e "s|@@T1E@@|${t1e}|g" \
        -e "s|@@T2E@@|${t2e}|g" \
        -e "s|@@T3E@@|${t3e}|g" \
        -e "s|@@T1@@|${t1}|g" \
        -e "s|@@T2@@|${t2}|g" \
        -e "s|@@T3@@|${t3}|g" \
        -e "s|@@T_STOP@@|${tstop}|g" \
        -e "s|@@T_PRINT@@|${TPRINT_NS}n|g" \
        -e "s|@@T_MAX@@|${TMAX_NS}n|g" \
        -e "s|@@CL_F@@|${CL_F}|g" \
        -e "s|@@DUT_NETLIST@@|${DUT_NETLIST_SNAPSHOT}|g" \
        -e "s|@@TRAN_CSV@@|${tran_csv}|g" \
        "${EXPERIMENT_DIR}/testbench/tb_slew.spice.tmpl" > "${netlist}"

      rc=0
      ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

      if [[ ${rc} -ne 0 ]] || ! [[ -s "${tran_csv}" ]] || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence|Transient solution failed" "${log}"; then
        echo "run_slew_sweep.sh: SIM FAILED ${point_id} (rc=${rc}) -- see ${log}" >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      vout="$(grep '^OP_VOUT ' "${log}" | awk '{print $2}')"
      vd1="$(grep '^OP_VD1 ' "${log}" | awk '{print $2}')"
      vd2="$(grep '^OP_VD2 ' "${log}" | awk '{print $2}')"
      vtail="$(grep '^OP_VTAIL ' "${log}" | awk '{print $2}')"
      vibias="$(grep '^OP_VIBIAS ' "${log}" | awk '{print $2}')"
      ivdd="$(grep '^OP_IVDD ' "${log}" | awk '{print $2}')"
      vinn_max="$(grep '^TR_VINN_MAX ' "${log}" | awk '{print $2}')"
      vinn_min="$(grep '^TR_VINN_MIN ' "${log}" | awk '{print $2}')"

      if [[ -z "${vout}" || -z "${vd1}" || -z "${vd2}" || -z "${vtail}" || -z "${ivdd}" || -z "${vinn_max}" || -z "${vinn_min}" ]]; then
        echo "run_slew_sweep.sh: SIM FAILED ${point_id} -- missing OP_*/TR_* line(s), see ${log}" >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      # --- Per-point DC sanity check: identical rule to
      # sim/open-loop-ac/run_pvt_sweep.sh (output within 15% of VDD of
      # mid-rail, no internal node fully railed) -- a non-regulating DC
      # start point must not read as a plausible slew number. See
      # README.md "Per-point sanity checks" for the honest scope of what
      # this does and does not verify.
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

      # --- Drive-integrity check: the antiphase drive has to have arrived
      # at inn through Cinj undistorted -- inn's excursion must be
      # 2*VSTEP_V peak-to-peak, centred on its own DC bias (= vout_dc, the
      # Lbreak servo's own result). A failure here means the AC-coupled
      # drive, not the amplifier, shaped the waveform.
      drive_pass="$(python3 -c "
vmax=${vinn_max}; vmin=${vinn_min}; vstep=${VSTEP_V}; vdc=${vout}
pp = vmax - vmin
centre = 0.5*(vmax + vmin)
ok = abs(pp - 2*vstep) <= 0.02*2*vstep and abs(centre - vdc) <= 0.01
print('1' if ok else '0')
")"

      # --- Slew post-processing, read from the committed waveform CSV.
      read -r sr_rise sr_fall sr_rise_in sr_fall_in lin_pass trav_pass vout_min vout_max win_lo win_hi < <(python3 - "${tran_csv}" "${vcm}" "${WIN_OUTER}" "${WIN_INNER}" "${T2_NS}" "${T3_NS}" "${TSTOP_NS}" <<'PYEOF'
import sys

path = sys.argv[1]
vcm = float(sys.argv[2])
w_out = float(sys.argv[3])
w_in = float(sys.argv[4])
t2 = float(sys.argv[5]) * 1e-9
t3 = float(sys.argv[6]) * 1e-9
tstop = float(sys.argv[7]) * 1e-9

# wrdata column layout: (scale,value) pair per requested vector -- col1 =
# time (v(out)'s own scale), col2 = v(out). Same gotcha
# sim/gm-id-characterization/README.md documents once for this fleet.
t, v = [], []
with open(path) as f:
    for line in f:
        parts = line.split()
        if len(parts) < 2:
            continue
        t.append(float(parts[0]))
        v.append(float(parts[1]))


def cross(t_lo, t_hi, level, rising):
    """First interpolated crossing of `level` inside [t_lo, t_hi]."""
    for i in range(1, len(t)):
        if not (t_lo <= t[i] <= t_hi):
            continue
        a, b = v[i - 1], v[i]
        if (rising and a <= level < b) or ((not rising) and a >= level > b):
            return t[i - 1] + (level - a) / (b - a) * (t[i] - t[i - 1])
    return None


def slew(t_lo, t_hi, half, rising):
    """V/us over the +/-half window centred on mid-rail."""
    first = vcm - half if rising else vcm + half
    second = vcm + half if rising else vcm - half
    ta = cross(t_lo, t_hi, first, rising)
    tb = cross(t_lo, t_hi, second, rising)
    if ta is None or tb is None or tb == ta:
        return float('nan')
    return 2 * half / abs(tb - ta) / 1e6


def value_at(ts):
    for i in range(len(t)):
        if t[i] >= ts:
            return v[i]
    return v[-1]


sr_rise = slew(t2, t3, w_out, True)
sr_fall = slew(t3, tstop, w_out, False)
sr_rise_in = slew(t2, t3, w_in, True)
sr_fall_in = slew(t3, tstop, w_in, False)

# Ramp linearity: the inner and outer windows must agree to 2%, i.e. the
# output really was on a constant-slope ramp across the measured window
# rather than on a settling tail.
def close(a, b):
    return a == a and b == b and abs(a - b) <= 0.02 * abs(b)


lin_pass = 1 if (close(sr_rise_in, sr_rise) and close(sr_fall_in, sr_fall)) else 0

# Traverse check: the output must have parked BELOW the window before the
# rising edge and ABOVE it before the falling edge, so each measured
# window is fully inside a single full-swing transition.
trav_pass = 1 if (value_at(t2 - 1e-9) < vcm - w_out and value_at(t3 - 1e-9) > vcm + w_out) else 0


def fmt(x):
    return "nan" if x != x else f"{x:.6g}"


print(f"{fmt(sr_rise)} {fmt(sr_fall)} {fmt(sr_rise_in)} {fmt(sr_fall_in)} "
      f"{lin_pass} {trav_pass} {fmt(min(v))} {fmt(max(v))} "
      f"{fmt(vcm - w_out)} {fmt(vcm + w_out)}")
PYEOF
)

      sr_worst="$(python3 -c "
import math
a=float('${sr_rise}'); b=float('${sr_fall}')
vals=[x for x in (a,b) if x==x]
print('nan' if not vals else '%.6g' % min(vals))
")"
      ivdd_signal_path="$(python3 -c "print(${ivdd} - 10e-6)")"

      echo "${point_id},${corner},${temp},${vdd},${vcm},${VSTEP_V},${op_pass},${vout},${vd1},${vd2},${vtail},${vibias},${ivdd},${ivdd_signal_path},${sr_rise},${sr_fall},${sr_worst},${sr_rise_in},${sr_fall_in},${lin_pass},${trav_pass},${drive_pass},${vout_min},${vout_max},${win_lo},${win_hi}" >> "${CSV_OUT}.raw"

      if [[ "${op_pass}" != "1" ]]; then
        op_fail_points+=("${point_id}")
      fi
      if [[ "${lin_pass}" != "1" || "${trav_pass}" != "1" || "${drive_pass}" != "1" || "${sr_worst}" == "nan" ]]; then
        check_fail_points+=("${point_id}")
      fi

      passed=$((passed + 1))
    done
  done
done

if [[ ${passed} -eq 0 ]]; then
  echo "run_slew_sweep.sh: no points passed -- refusing to write a summary." >&2
  exit 1
fi

mv "${CSV_OUT}.raw" "${CSV_OUT}"

{
  echo "op_pass_count,${passed} of ${total}, op_sane failures: ${#op_fail_points[@]} (${op_fail_points[*]:-none})"
  echo "measurement_check_failures,${#check_fail_points[@]} (${check_fail_points[*]:-none})"
  echo "sim_fail_count,${#sim_fail_points[@]} (${sim_fail_points[*]:-none})"
} > "${CORNERS_OUT}/sanity_checks.txt"

# --- Completeness: all 45 (corner, temp, vdd) cells must have run. -------
n_rows=$(($(wc -l < "${CSV_OUT}") - 1))
expected=$(( ${#CORNERS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} ))
if [[ "${n_rows}" -ne "${expected}" ]]; then
  echo "run_slew_sweep.sh: WARNING -- ${n_rows} rows written, expected ${expected} (${#sim_fail_points[@]} sim failures)" >&2
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


def line(label, t, worst=min):
    if not t:
        print(f"{label}: n/a")
        return
    v, r = worst(t, key=lambda x: x[0])
    print(f"{label}: {v:.4g} at {r['point_id']}")


line("worst_sr_rise_v_per_us", numeric(rows, "sr_rise_v_per_us"))
line("worst_sr_fall_v_per_us", numeric(rows, "sr_fall_v_per_us"))
line("worst_sr_either_edge_v_per_us", numeric(rows, "sr_worst_v_per_us"))
line("best_sr_either_edge_v_per_us", numeric(rows, "sr_worst_v_per_us"), worst=max)
line("worst_iq_a", numeric(rows, "ivdd_total_a"), worst=max)
PYEOF
)"

cat > "${MD_OUT}" <<EOF
# slew-rate record ${RECORD_ID}

Generated by \`sim/slew-rate/run_slew_sweep.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`).

Grid: cornerMOSlv.lib \`mos_tt/ss/ff/sf/fs\` [DR-1] x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${expected} points,
into \`CL = ${CL_F} F\` [DR-1]. Drive: antiphase \`+/-${VSTEP_V} V\` per
input (differential \`+/-$(python3 -c "print(2*${VSTEP_V})") V\`) at a fixed
input common mode \`Vcm = VDD/2\`; slew read over the \`Vcm +/- ${WIN_OUTER} V\`
window (\`Vcm +/- ${WIN_INNER} V\` as the ramp-linearity cross-check).

${passed} of ${total} points simulated successfully; ${#sim_fail_points[@]}
simulation failure(s) (${sim_fail_points[*]:-none}); ${#op_fail_points[@]}
point(s) failed the per-point DC sanity check (${op_fail_points[*]:-none});
${#check_fail_points[@]} point(s) failed a measurement-integrity check
(ramp linearity / full-swing traverse / drive integrity)
(${check_fail_points[*]:-none}) -- see README.md "Per-point sanity checks"
for what each check does and does not verify.

## Worst-corner summary

\`\`\`
${WORST}
\`\`\`

Full per-point data (rising/falling slew rate, inner-window cross-check,
DC operating point, Iq, per-point check flags) is in
\`records/${RECORD_ID}.csv\`. Raw per-point ngspice logs and the output
waveform each slew number was measured from are in
\`corners/${RECORD_ID}/\`.
EOF

echo "run_slew_sweep.sh: wrote ${CSV_OUT} and ${MD_OUT} (${passed}/${total} points, ${#op_fail_points[@]} op-sanity failures, ${#check_fail_points[@]} measurement-check failures)"

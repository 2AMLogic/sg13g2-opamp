#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/input-noise/run_noise_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH plus the
# OSDI device models sim/tools/build-osdi.sh builds; does not require
# xschem or klt at run time (design/netlist/opamp_core.spice is committed,
# pre-netlisted -- see design/README.md for the xschem command that
# regenerates it from design/opamp_core.sch). Full methodology, the chosen
# measurement band and why, and the pinned PDK revision are documented in
# README.md and sim/pdk.json -- read those first if a result here looks
# surprising.
#
# Input-referred noise characterization of design/opamp_core.spice in a
# unity-gain (voltage-follower) closed-loop configuration -- see
# testbench/tb_noise.spice.tmpl's own header for why closed loop and not
# sim/open-loop-ac/'s Lbreak trick. Runs an ngspice `.noise` analysis over
# the chosen band (100 Hz - 1 MHz, integrated + five spot densities)
# across the full cornerMOSlv.lib process x temperature x supply grid
# (mos_tt/ss/ff/sf/fs x -40/27/125 C x 1.08/1.20/1.32 V = 45 points),
# into CL = 2 pF [DR-1]. Writes append-only evidence under
# corners/<record-id>/, netlist-snapshots/<record-id>/ and
# records/<record-id>.{csv,md} -- same fleet convention as
# sim/open-loop-ac/run_pvt_sweep.sh in this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_noise_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_noise_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_noise_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_noise_sweep.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  echo "run_noise_sweep.sh:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
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

# --- Measurement band ----------------------------------------------------
# Chosen in this experiment's README.md ("Choosing the band"): integrated
# 100 Hz - 1 MHz, plus spot densities at 100 Hz / 1 kHz / 10 kHz / 100 kHz
# / 1 MHz. These constants exist here only so the record/summary text can
# state them; the swept range itself is written into the testbench
# template (a `noise ... dec 20 100 1meg` line), and the post-processing
# below re-derives each spot frequency from the written CSV and asserts it
# rather than trusting index arithmetic.
BAND_LO_HZ="100"
BAND_HI_HZ="1e6"

# --- Units check ---------------------------------------------------------
# Pin ngspice's `noise` output units against a closed-form 4kTR reference
# BEFORE simulating any DUT point -- see
# testbench/tb_noise_units_check.spice for the derivation of the expected
# numbers. A version of ngspice reporting V^2/Hz densities or mean-square
# totals would otherwise silently rescale every recorded number.
UNITS_LOG="${CORNERS_OUT}/units_check.log"
ngspice -b "${EXPERIMENT_DIR}/testbench/tb_noise_units_check.spice" > "${UNITS_LOG}" 2>&1 || {
  echo "run_noise_sweep.sh: units-check deck failed to run -- see ${UNITS_LOG}" >&2
  exit 1
}
units_in_spectrum="$(grep '^UNITS_INOISE_SPECTRUM ' "${UNITS_LOG}" | awk '{print $2}')"
units_out_spectrum="$(grep '^UNITS_ONOISE_SPECTRUM ' "${UNITS_LOG}" | awk '{print $2}')"
units_in_total="$(grep '^UNITS_INOISE_TOTAL ' "${UNITS_LOG}" | awk '{print $2}')"
if ! python3 - "${units_in_spectrum}" "${units_out_spectrum}" "${units_in_total}" > "${CORNERS_OUT}/units_check.txt" <<'PYEOF'
import math, sys

sp_in, sp_out, tot_in = (float(x) for x in sys.argv[1:4])
k, T, R, gain = 1.380649e-23, 300.0, 1e3, 100.0
en = math.sqrt(4 * k * T * R)              # V/sqrt(Hz)
expect = {
    "inoise_spectrum_v_per_rthz": (sp_in, en),
    "onoise_spectrum_v_per_rthz": (sp_out, en * gain),
    "inoise_total_vrms": (tot_in, en * math.sqrt(10e3 - 1e3)),
}
ok = True
for name, (got, want) in expect.items():
    rel = abs(got - want) / want
    status = "OK" if rel <= 5e-3 else "FAIL"
    if status == "FAIL":
        ok = False
    print(f"{name},{got:.6g},{want:.6g},{rel:.3g},{status}")
sys.exit(0 if ok else 1)
PYEOF
then
  echo "run_noise_sweep.sh: ngspice noise-analysis UNITS CHECK FAILED -- refusing to record numbers whose units are not the ones this bench's math assumes:" >&2
  cat "${CORNERS_OUT}/units_check.txt" >&2
  exit 1
fi

# --- Sweep grid ----------------------------------------------------------
# Process corner grid: cornerMOSlv.lib's five sections [DR-1].
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
# Temperature x supply grid: spec/target-spec.md Sec 1 ("Operating
# temperature", "Supply voltage, VDD") -- the same 45-point grid
# sim/open-loop-ac/run_pvt_sweep.sh runs.
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

echo "point_id,corner,temp_c,vdd_v,vcm_v,op_pass,vout_dc_v,vd1_dc_v,vd2_dc_v,vtail_dc_v,vibias_dc_v,ivdd_total_a,clgain_100hz,clgain_1mhz,vni_int_vrms,vni_int_crosscheck_ratio,vni_100hz_v_rthz,vni_1khz_v_rthz,vni_10khz_v_rthz,vni_100khz_v_rthz,vni_1mhz_v_rthz,flicker_coeff_v2,thermal_floor_v_rthz,flicker_corner_hz,flicker_frac_of_msq" > "${CSV_OUT}.raw"

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
      noise_csv="${CORNERS_OUT}/${point_id}_noise.csv"
      noise_wide_csv="${CORNERS_OUT}/${point_id}_noise_wide.csv"

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
        -e "s|@@NOISE_CSV@@|${noise_csv}|g" \
        -e "s|@@NOISE_WIDE_CSV@@|${noise_wide_csv}|g" \
        "${EXPERIMENT_DIR}/testbench/tb_noise.spice.tmpl" > "${netlist}"

      rc=0
      ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

      if [[ ${rc} -ne 0 ]] || ! [[ -s "${noise_csv}" ]] || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence" "${log}"; then
        echo "run_noise_sweep.sh: SIM FAILED ${point_id} (rc=${rc}) -- see ${log}" >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      vout="$(grep '^OP_VOUT ' "${log}" | awk '{print $2}')"
      vd1="$(grep '^OP_VD1 ' "${log}" | awk '{print $2}')"
      vd2="$(grep '^OP_VD2 ' "${log}" | awk '{print $2}')"
      vtail="$(grep '^OP_VTAIL ' "${log}" | awk '{print $2}')"
      vibias="$(grep '^OP_VIBIAS ' "${log}" | awk '{print $2}')"
      ivdd="$(grep '^OP_IVDD ' "${log}" | awk '{print $2}')"
      vni_int="$(grep '^NOISE_INOISE_TOTAL ' "${log}" | awk '{print $2}')"
      clgain_lo="$(grep '^AC_CLGAIN_100HZ ' "${log}" | awk '{print $2}')"
      clgain_hi="$(grep '^AC_CLGAIN_1MHZ ' "${log}" | awk '{print $2}')"

      if [[ -z "${vout}" || -z "${vd1}" || -z "${vd2}" || -z "${vtail}" || -z "${ivdd}" \
            || -z "${vni_int}" || -z "${clgain_lo}" || -z "${clgain_hi}" ]]; then
        echo "run_noise_sweep.sh: SIM FAILED ${point_id} -- missing OP_*/NOISE_*/AC_* line(s), see ${log}" >&2
        sim_fail_points+=("${point_id}")
        continue
      fi

      # --- Per-point sanity check. Two parts, both documented in
      # README.md "Per-point sanity checks":
      #   (a) the same DC-operating-point rule sim/open-loop-ac/ applies
      #       (output near mid-rail, no internal node railed), so a
      #       non-regulating point cannot read as a plausible noise figure;
      #   (b) a noise-gain guard specific to this bench -- the closed-loop
      #       gain must still be ~1 at BOTH band edges, otherwise the
      #       input-referral at the band top is dividing by a collapsed
      #       gain and the reported density is inflated rather than
      #       measured.
      op_pass="$(python3 -c "
vdd=${vdd}; vcm=${vcm}
vout=${vout}; vd1=${vd1}; vd2=${vd2}; vtail=${vtail}
glo=${clgain_lo}; ghi=${clgain_hi}
tol=0.15*vdd
rail_lo=0.02*vdd
rail_hi=vdd-0.02*vdd
ok = (abs(vout-vcm) <= tol)
for node in (vd1, vd2, vtail, vout):
    if not (rail_lo <= node <= rail_hi):
        ok = False
for g in (glo, ghi):
    if not (0.9 <= g <= 1.1):
        ok = False
print('1' if ok else '0')
")"

      # --- Noise post-processing: spot densities at the five stated
      # frequencies (each re-derived from the CSV and asserted, never
      # implied by index arithmetic), a weighted least-squares split of
      # the in-band spectrum into a flicker (A/f) and a thermal (B) term,
      # the resulting flicker corner, and a trapezoidal cross-check of
      # ngspice's own integrated figure.
      read -r cs_ratio s100 s1k s10k s100k s1m acoef bfloor fcorner ffrac < <(python3 - "${noise_csv}" "${vni_int}" <<'PYEOF'
import math, sys

path, vni_int = sys.argv[1], float(sys.argv[2])
freqs, dens = [], []
with open(path) as f:
    for line in f:
        parts = line.split()
        if len(parts) < 4:
            continue
        # wrdata column layout: (scale,value) pair per requested vector --
        # col1=freq (inoise_spectrum's own scale), col2=inoise_spectrum,
        # col3=freq (dup), col4=onoise_spectrum. Same gotcha
        # sim/gm-id-characterization/README.md documents once for the
        # whole repo.
        freqs.append(float(parts[0]))
        dens.append(float(parts[1]))       # V/sqrt(Hz), input-referred

if len(freqs) != 81:
    raise SystemExit(f"expected 81 swept points, got {len(freqs)}")

# Spot frequencies: assert, do not imply (dec 20 from exactly 100 Hz).
spots = []
for idx, want in ((0, 1e2), (20, 1e3), (40, 1e4), (60, 1e5), (80, 1e6)):
    got = freqs[idx]
    if abs(got - want) / want > 1e-6:
        raise SystemExit(f"spot index {idx} is {got} Hz, expected {want} Hz")
    spots.append(dens[idx])

# Weighted least-squares fit of S(f) = A/f + B to the measured POWER
# density S = dens^2 (V^2/Hz). Relative (1/S^2) weighting so the fit is
# not dominated by the flicker-heavy low-frequency decade.
S = [d * d for d in dens]
sa = sb = sab = ra = rb = 0.0
for fq, s in zip(freqs, S):
    x1, x2, w = 1.0 / fq, 1.0, 1.0 / (s * s)
    sa += w * x1 * x1
    sab += w * x1 * x2
    sb += w * x2 * x2
    ra += w * x1 * s
    rb += w * x2 * s
det = sa * sb - sab * sab
A = (ra * sb - rb * sab) / det
B = (rb * sa - ra * sab) / det

flo, fhi = freqs[0], freqs[-1]
msq_flicker = A * math.log(fhi / flo) if A > 0 else 0.0
msq_thermal = B * (fhi - flo) if B > 0 else 0.0
ffrac = msq_flicker / (msq_flicker + msq_thermal) if (msq_flicker + msq_thermal) > 0 else float("nan")
fcorner = A / B if (A > 0 and B > 0) else float("nan")
thermal_floor = math.sqrt(B) if B > 0 else float("nan")

# Trapezoidal cross-check of ngspice's own inoise_total: integrate the
# measured power density over the band and compare RMS values.
msq = 0.0
for i in range(1, len(freqs)):
    msq += 0.5 * (S[i - 1] + S[i]) * (freqs[i] - freqs[i - 1])
cross_ratio = math.sqrt(msq) / vni_int if vni_int > 0 else float("nan")

def fmt(x):
    return "nan" if x != x else f"{x:.6g}"

print(" ".join(fmt(v) for v in (
    cross_ratio, spots[0], spots[1], spots[2], spots[3], spots[4],
    A, thermal_floor, fcorner, ffrac)))
PYEOF
)

      echo "${point_id},${corner},${temp},${vdd},${vcm},${op_pass},${vout},${vd1},${vd2},${vtail},${vibias},${ivdd},${clgain_lo},${clgain_hi},${vni_int},${cs_ratio},${s100},${s1k},${s10k},${s100k},${s1m},${acoef},${bfloor},${fcorner},${ffrac}" >> "${CSV_OUT}.raw"

      if [[ "${op_pass}" != "1" ]]; then
        op_fail_points+=("${point_id}")
      fi

      passed=$((passed + 1))
    done
  done
done

if [[ ${passed} -eq 0 ]]; then
  echo "run_noise_sweep.sh: no points passed -- refusing to write a summary." >&2
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
  echo "run_noise_sweep.sh: WARNING -- ${n_rows} rows written, expected ${expected} (${#sim_fail_points[@]} sim failures)" >&2
fi

# --- Worst-corner summary (per metric) for the record's README-style table.
WORST="$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys

rows = list(csv.DictReader(open(sys.argv[1])))

def numeric(key):
    out = []
    for r in rows:
        try:
            v = float(r[key])
        except ValueError:
            continue
        if v == v:
            out.append((v, r))
    return out

def line(label, pairs, worst):
    if not pairs:
        print(f"{label}: n/a")
        return
    v, r = worst(pairs, key=lambda t: t[0])
    print(f"{label}: {v:.4g} at {r['point_id']}")

line("worst_vni_int_vrms", numeric("vni_int_vrms"), max)
line("best_vni_int_vrms", numeric("vni_int_vrms"), min)
line("worst_vni_100hz_v_rthz", numeric("vni_100hz_v_rthz"), max)
line("worst_vni_1khz_v_rthz", numeric("vni_1khz_v_rthz"), max)
line("worst_vni_1mhz_v_rthz", numeric("vni_1mhz_v_rthz"), max)
line("worst_thermal_floor_v_rthz", numeric("thermal_floor_v_rthz"), max)
line("highest_flicker_corner_hz", numeric("flicker_corner_hz"), max)
line("lowest_flicker_corner_hz", numeric("flicker_corner_hz"), min)
line("lowest_flicker_frac_of_msq", numeric("flicker_frac_of_msq"), min)
line("worst_int_crosscheck_ratio_dev",
     [(abs(v - 1.0), r) for v, r in numeric("vni_int_crosscheck_ratio")], max)
PYEOF
)"

cat > "${MD_OUT}" <<EOF
# input-noise record ${RECORD_ID}

Generated by \`sim/input-noise/run_noise_sweep.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\` (built by \`sim/tools/build-osdi.sh\`).

Configuration: unity-gain (voltage-follower) closed loop, \`CL = ${CL_F} F\`
[DR-1], 10 uA external \`ibias\` -- see \`README.md\` "Why closed loop".

Band: input-referred noise integrated over **${BAND_LO_HZ} Hz - ${BAND_HI_HZ} Hz**
(\`vni_int_vrms\`, RMS volts), plus spot densities (V/sqrt(Hz)) at
100 Hz / 1 kHz / 10 kHz / 100 kHz / 1 MHz -- see \`README.md\`
"Choosing the band".

Grid: cornerMOSlv.lib \`mos_tt/ss/ff/sf/fs\` [DR-1] x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${expected} points.
${passed} of ${total} points simulated successfully;
${#sim_fail_points[@]} simulation failure(s) (${sim_fail_points[*]:-none});
${#op_fail_points[@]} point(s) failed the per-point sanity check
(${op_fail_points[*]:-none}) -- see "Per-point sanity checks" in
\`README.md\` for what that check does and does not verify.

ngspice \`noise\` units were re-verified against the closed-form 4kTR
reference in \`testbench/tb_noise_units_check.spice\` before this sweep ran
(\`corners/${RECORD_ID}/units_check.txt\`).

## Worst-corner summary

\`\`\`
${WORST}
\`\`\`

Full per-point data (integrated noise, five spot densities, flicker/thermal
split and flicker corner, closed-loop gain guard at both band edges, DC
operating point, Iq) is in \`records/${RECORD_ID}.csv\`. Raw per-point
ngspice logs, in-band noise spectra and the reference-only wide
(1 Hz - 100 MHz) spectra are in \`corners/${RECORD_ID}/\`.
EOF

echo "run_noise_sweep.sh: wrote ${CSV_OUT} and ${MD_OUT} (${passed}/${total} points, ${#op_fail_points[@]} sanity failures)"

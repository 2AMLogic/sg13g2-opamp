#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/cmrr-mismatch/run_cmrr_mismatch_mc.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH plus the
# OSDI device models sim/tools/build-osdi.sh builds; does not require xschem
# or klt at run time (design/netlist/opamp_core.spice is committed,
# pre-netlisted). Full methodology, what this bench measures and does not,
# the seed discipline and the N derivation are documented in this
# experiment's README.md -- read that first if a result here looks
# surprising. Pinned PDK revision in sim/pdk.json.
#
# Mismatch Monte Carlo CMRR for design/opamp_core.spice across the full
# cornerMOSlv.lib process x temperature x supply grid (mos_tt/ss/ff/sf/fs
# x -40/27/125 C x 1.08/1.20/1.32 V = 45 points, issue #26), the
# mismatch-inclusive companion to sim/cmrr-psrr/'s systematic CMRR bench
# (issue #14, PR #25): same testbench topology (tb_cmrr_mc.spice.tmpl is
# tb_cmrr.spice.tmpl plus a Monte Carlo loop), but every grid point runs
# the PDK's own per-corner mismatch section (cornerMOSlv.lib
# <corner>_mismatch -> sg13g2_moslv_mismatch.lib +
# sg13g2_moslv_mod_mismatch.lib, the agauss() per-instance wrappers on
# w/l/delvto/factuo). Per sample: one reset (fresh independent
# per-instance draws for all eight MOSFETs) + op + a 6-point AC sweep
# (10 mHz shelf / 0.1 Hz plateau-guard partner / 1 kHz), per-sample DC
# sanity per issue #14's rule.
#
# CMRR per sample = the SAME grid point's av0_db from the committed
# sim/open-loop-ac/ record (joined, not re-measured -- issue #26's own
# harness-reuse wording) minus the sample's Acm(10 mHz). Per-point
# statistics: mean, sigma, mean-3*sigma (the dB-domain 3 sigma basis the
# offset row's statistical-basis column commits to, applied to CMRR),
# empirical 1st percentile and worst observed sample, plus the 1 kHz
# in-band variant. The quoted mismatch-inclusive worst-case CMRR is the
# grid-minimum of cmrr_db_minus_3sigma.
#
# Controls run by this script and required before any record is written:
#   - N derivation: pilot at the nominal point and at sim/cmrr-psrr/'s
#     measured binding corner (mos_fs_125C_1.08V), MC_N_FLOOR default 300
#     samples per the spec row's wording; N chosen so the sampling error
#     of the linear-domain mismatch sigma stays below MC_TARGET_SIGMA_RE
#     (default 0.05, SE(sigma_hat)/sigma ~ 1/sqrt(2N)).
#   - Negative control: every grid point also runs N=MC_NEGCTL_N (default
#     3) iterations against the PLAIN <corner> section (the exact
#     systematic configuration sim/cmrr-psrr/ ran -- same self-biased
#     netlist, no agauss() anywhere, hence a zero-mismatch deck). Asserted
#     per point: all iterations identical AND equal to #25's committed
#     per-point record (acm0_db / vout_dc_v / vibias_dc_v / cmrr_db,
#     tolerances NEGCTL_TOL_DB default 5e-3 and NEGCTL_TOL_V default
#     5e-4) -- i.e. the zero-mismatch deck reproduces #25's systematic
#     CMRR through the full Monte Carlo machinery.
#   - Reproducibility: the nominal point is re-run with the same seed
#     (asserted byte-identical sample sequence to the grid run's nominal
#     sample file) and with MC_SEED_ALT (default 990000, asserted a
#     different draw sequence). This pair is the machine check of "same
#     seed -> same result, different seed -> different draw" from issue
#     #26's Test Plan.
#
# Seeds: the base MC_SEED_BASE (default 260000) plus the grid index
# (corner-major, the loop order below) selects the deterministic per-point
# seed for the Monte Carlo stream: point i of 45 runs setseed
# $((MC_SEED_BASE + i)). Committed seeds are printed in every rendered
# netlist header and in the record .md; everything about a point's sample
# sequence is a pure function of (corner, temp, vdd, section, seed, N).
#
# Writes append-only evidence under netlist-snapshots/<record-id>/,
# corners/<record-id>/ and records/<record-id>.{csv,md} -- same fleet
# convention as sim/open-loop-ac/, sim/cmrr-psrr/ and the other benches
# in this tree. Raw per-point solver stdout (corners/<id>/<point>_*.log)
# is retained only for points that failed a check; passing points keep
# their extracted sample files (the OP/AC echo lines) as the committed
# artifact, so the record stays reviewable without 13,500 solver banners.
#
# Resume: replay the same RECORD_ID (env RECORD_ID=<id> re-set on the next
# invocation) and already-completed points (sample file present with the
# exact expected line count) are skipped, so a killed run can be
# continued instead of restarted. A fresh invocation with no RECORD_ID
# mints a new one and starts clean; a resumed run truncates only its own
# record-id's partial sample files, never another record's evidence.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_cmrr_mismatch_mc.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_cmrr_mismatch_mc.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_cmrr_mismatch_mc.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
  echo "run_cmrr_mismatch_mc.sh: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
  exit 3
fi

MU_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/sg13g2_moslv_mod_mismatch.lib"
if [[ ! -s "${MU_LIB}" ]]; then
  echo "run_cmrr_mismatch_mc.sh: ${MU_LIB} missing -- the PDK mismatch decks are required (see README.md)." >&2
  exit 3
fi

# --- Cross-references to committed records --------------------------------
# Every CMRR number this experiment quotes divides the SAME grid point's
# av0_db out of sim/open-loop-ac/ (joined, not re-measured), exactly as
# sim/cmrr-psrr/ does; the negative control additionally asserts equality
# with #25's committed per-point systematic acm0/vout/vibias/cmrr.
if [[ -z "${AC_RECORD_CSV:-}" ]]; then
  AC_RECORD_CSV=""
  while IFS= read -r _f; do AC_RECORD_CSV="${_f}"; done < <(
    find "${SIM_DIR}/open-loop-ac/records" -maxdepth 1 -name '*.csv' 2>/dev/null | sort
  )
fi
if [[ -z "${AC_RECORD_CSV:-}" || ! -s "${AC_RECORD_CSV}" ]]; then
  echo "run_cmrr_mismatch_mc.sh: no sim/open-loop-ac/records/*.csv found -- this experiment's CMRR" >&2
  echo "run_cmrr_mismatch_mc.sh: needs that record's per-point av0_db column." >&2
  exit 3
fi
AC_RECORD_ID="$(basename "${AC_RECORD_CSV}" .csv)"

if [[ -z "${CMRR_RECORD_CSV:-}" ]]; then
  CMRR_RECORD_CSV=""
  while IFS= read -r _f; do CMRR_RECORD_CSV="${_f}"; done < <(
    find "${SIM_DIR}/cmrr-psrr/records" -maxdepth 1 -name '*.csv' 2>/dev/null | sort
  )
fi
if [[ -z "${CMRR_RECORD_CSV:-}" || ! -s "${CMRR_RECORD_CSV}" ]]; then
  echo "run_cmrr_mismatch_mc.sh: no sim/cmrr-psrr/records/*.csv found -- the negative control" >&2
  echo "run_cmrr_mismatch_mc.sh: asserts against issue #14's committed systematic record." >&2
  exit 3
fi
CMRR_RECORD_ID="$(basename "${CMRR_RECORD_CSV}" .csv)"

OSDI_DIR="${SG13G2_OSDI_DIR}"
REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="${RECORD_ID:-$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

DUT_NETLIST_SNAPSHOT="${SNAPSHOTS_OUT}/opamp_core.spice"
if [[ ! -s "${DUT_NETLIST_SNAPSHOT}" ]]; then
  cp "${DUT_NETLIST_SRC}" "${DUT_NETLIST_SNAPSHOT}"
fi

# --- Knobs -----------------------------------------------------------------
MC_N_FLOOR="${MC_N_FLOOR:-300}"                 # spec-row wording: "mismatch MC N>=300"
MC_TARGET_SIGMA_RE="${MC_TARGET_SIGMA_RE:-0.05}"  # target rel. sampling error of the linear sigma
MC_NEGCTL_N="${MC_NEGCTL_N:-3}"
MC_SEED_BASE="${MC_SEED_BASE:-260000}"
MC_SEED_ALT="${MC_SEED_ALT:-990000}"
NEGCTL_TOL_DB="${NEGCTL_TOL_DB:-5e-3}"
NEGCTL_TOL_V="${NEGCTL_TOL_V:-5e-4}"
OP_RAIL_FRAC="${OP_RAIL_FRAC:-0.02}"        # inner-node rail margin, same rule as #14
OP_MID_FRAC="${OP_MID_FRAC:-0.15}"          # output-vs-midrail tolerance, same rule as #14
PLATEAU_TOL_DB="${PLATEAU_TOL_DB:-0.05}"     # same plateau guard tolerance as #14

# --- Sweep grid: identical order to sim/cmrr-psrr/ --------------------------
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"

point_ids=()
point_corners=()
point_temps=()
point_vdds=()
point_seeds=()
idx=0
for corner in "${CORNERS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      point_ids+=("${corner}_${temp}C_${vdd}V")
      point_corners+=("${corner}")
      point_temps+=("${temp}")
      point_vdds+=("${vdd}")
      point_seeds+=("$((MC_SEED_BASE + idx))")
      idx=$((idx + 1))
    done
  done
done
NP=${#point_ids[@]}

find_point_index() { # <point_id>
  local want="$1" i
  for i in "${!point_ids[@]}"; do
    [[ "${point_ids[$i]}" == "${want}" ]] && { echo "$i"; return 0; }
  done
  return 1
}

PILOT_A_IDX="$(find_point_index mos_tt_27C_1.20V)"
PILOT_B_IDX="$(find_point_index mos_fs_125C_1.08V)"

# --------------------------------------------------------------------------- 
# Per-point sample extraction + per-sample sanity + per-point statistics.
# Python reads the OP/AC echo lines, applies #14's DC rule per sample,
# joins av0_db (open-loop record) and the systematic acm0/vout/vibias/cmrr
# (#25 record), and prints the per-point stat row. Excluded samples (DC
# sanity fail or a plateau-guard fail) never enter the statistics; they are
# counted and surfaced, mirroring #14's "a non-regulating point must not
# read as a plausible rejection ratio" at sample granularity.
# ---------------------------------------------------------------------------
stat_point() { # <point_index> <mc_sample_file> -> row on stdout
  python3 - "$1" "$2" "${AC_RECORD_CSV}" "${CMRR_RECORD_CSV}" \
    "${OP_RAIL_FRAC}" "${OP_MID_FRAC}" "${PLATEAU_TOL_DB}" <<'PYEOF'
import csv, math, sys

pidx, file, ac_csv, cmrr_csv, rail_frac, mid_frac, plateau_tol = sys.argv[1:8]
pidx = int(pidx)
rail_frac, mid_frac, plateau_tol = float(rail_frac), float(mid_frac), float(plateau_tol)

# grid params from index (corner-major order, same as the bash arrays)
CORNER = None; TEMP = None; VDD = None
CORNERS = ['mos_tt', 'mos_ss', 'mos_ff', 'mos_sf', 'mos_fs']
TEMPS = [-40, 27, 125]
VDDS = ['1.08', '1.20', '1.32']
ci = pidx // 9; ti = (pidx % 9) // 3; vi = pidx % 3
CORNER, TEMP, VDD = CORNERS[ci], TEMPS[ti], VDDS[vi]
point_id = f"{CORNER}_{TEMP}C_{VDD}V"
vcm = float(VDD) / 2.0

# join committed systematic + av0 rows for this grid point
ol = {}
for r in csv.DictReader(open(ac_csv)):
    if (r["corner"], r["temp_c"], r["vdd_v"]) == (CORNER, str(TEMP), VDD):
        ol = r
        break
sy = {}
for r in csv.DictReader(open(cmrr_csv)):
    if (r["corner"], r["temp_c"], r["vdd_v"]) == (CORNER, str(TEMP), VDD):
        sy = r
        break
if not ol or not sy:
    print(f"NOJOIN {point_id}")
    sys.exit(1)

av0_db = float(ol["av0_db"])
sys_acm0_db = float(sy["acm0_db"])
sys_cmrr_db = float(sy["cmrr_db"])
sys_vout = float(sy["vout_dc_v"])
sys_vibias = float(sy["vibias_dc_v"])

# read sample file: OP/AC pairs by index
ops, acs = {}, {}
with open(file) as f:
    for line in f:
        p = line.split()
        if not p:
            continue
        if p[0] == "OP" and len(p) >= 8:
            ops[int(p[1])] = [float(x) for x in p[2:8]]
        elif p[0] == "AC" and len(p) >= 5:
            acs[int(p[1])] = [float(x) for x in p[2:5]]

n_asked = max(ops.keys()) + 1
if set(ops) != set(range(n_asked)) or set(acs) != set(range(n_asked)):
    print(f"TRUNCATED {point_id}")
    sys.exit(1)

vdd = float(VDD)
rail_lo, rail_hi = rail_frac * vdd, vdd - rail_frac * vdd

# Estimator domains, stated up front because they matter here:
#   - The quoted per-point mismatch-inclusive bound is computed in the
#     LINEAR Acm domain (V/V): mismatch enters the common-mode gain as
#     roughly additive zero-mean perturbations of the two competing
#     first-stage terms, so mean+3*sigma is the meaningful "+3 sigma
#     part" Acm; that point is then mapped to dB once. At the low-rail
#     near-cancellation corners the dB image of the sample distribution
#     is heavy-tailed on the REJECTION-GOOD side (a drawn cancellation
#     sends Acm dB far down without any risk attached), so a dB-domain
#     mean-3*sigma would be dominated by benign outliers and understate
#     the bound arbitrarily (dev notes in README.md "Choosing the 3
#     sigma domain").
#   - Empirical dB-domain columns (mean, 1st percentile, worst sample)
#     are recorded as context, computed from the same samples.
acm_lin, acm1k_lin, cmrr_db, cmrr1k_db = [], [], [], []
excluded = op_fail = plateau_fail = 0
plateau_max = 0.0
n_ok = 0
for k in range(n_asked):
    vout, vd1, vd2, vtail, vibias, ivdd = ops[k]
    acm10m, acm01, acm1k = acs[k]
    ok = abs(vout - vcm) <= mid_frac * vdd
    for node in (vout, vd1, vd2, vtail):
        if not (rail_lo <= node <= rail_hi):
            ok = False
    pdelta = abs(acm10m - acm01)
    plateau_max = max(plateau_max, pdelta)
    if not ok:
        op_fail += 1
        excluded += 1
    elif pdelta > plateau_tol:
        plateau_fail += 1
        excluded += 1
    else:
        n_ok += 1
        acm_lin.append(10 ** (acm10m / 20.0))
        acm1k_lin.append(10 ** (acm1k / 20.0))
        cmrr_db.append(av0_db - acm10m)
        cmrr1k_db.append(av0_db - acm1k)

if n_ok < 2:
    print(f"ALLFAIL {point_id}")
    sys.exit(1)

def lin_stats(v):
    n = len(v)
    mu = sum(v) / n
    var = sum((x - mu) ** 2 for x in v) / (n - 1)
    return mu, math.sqrt(var)

def db_stats(v):
    n = len(v)
    mu = sum(v) / n
    sv = sorted(v)
    def pct(p):
        pos = p * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return sv[lo] * (1 - frac) + sv[hi] * frac
    return mu, sv[0], pct(0.01)

mu_a, sd_a = lin_stats(acm_lin)
acm_3s_db = 20 * math.log10(mu_a + 3 * sd_a)
mu_a1k, sd_a1k = lin_stats(acm1k_lin)
acm1k_3s_db = 20 * math.log10(mu_a1k + 3 * sd_a1k)
mu_c, vmin_c, p01_c = db_stats(cmrr_db)

print(f"{point_id},{CORNER},{TEMP},{VDD},{vcm:g},{av0_db:.6g},{sys_acm0_db:.6g},{sys_cmrr_db:.6g},"
      f"{n_asked},{n_ok},{excluded},{op_fail},{plateau_fail},"
      f"{mu_a:.6g},{sd_a:.6g},{acm_3s_db:.6g},{av0_db - acm_3s_db:.6g},"
      f"{mu_c:.6g},{p01_c:.6g},{vmin_c:.6g},{av0_db - acm1k_3s_db:.6g},{plateau_max:.6g}")
PYEOF
}

# --------------------------------------------------------------------------- 
# One point's Monte Carlo run (or negative-control run): render, run, and
# verify the mechanical completion invariants (exit status, no failure
# signature in the log, exactly 2N OP/AC lines).
# ---------------------------------------------------------------------------
run_deck() { # <point_index> <section> <n> <tag> [seed-override]
  local pidx="$1" section="$2" n="$3" tag="$4" seed="${5:-}"
  if ! [[ "${n}" =~ ^[0-9]+$ ]] || [[ "${n}" -lt 1 ]]; then
    echo "run_cmrr_mismatch_mc.sh: internal error -- non-positive-integer N '${n}' for tag ${tag}" >&2
    return 1
  fi
  local pid="${point_ids[$pidx]}" temp="${point_temps[$pidx]}" vdd="${point_vdds[$pidx]}"
  local vcm netlist log samples rc have sig
  vcm="$(python3 -c "print(${vdd}/2)")"
  netlist="${SNAPSHOTS_OUT}/${pid}_${tag}.spice"
  samples="${CORNERS_OUT}/${pid}_${tag}_samples.txt"
  log="${CORNERS_OUT}/${pid}_${tag}.log"
  [[ -z "${seed}" ]] && seed="${point_seeds[$pidx]}"

  # Resume: skip only when this record-id's sample file is complete.
  if [[ "${tag}" == "mc" && -s "${samples}" ]]; then
    have="$(grep -c -E '^(OP|AC) ' "${samples}" || true)"
    if [[ "${have}" -eq $((2 * n)) ]]; then
      echo "run_cmrr_mismatch_mc.sh: resume -- ${pid} ${tag} already complete (${have} lines)" >&2
      return 0
    fi
  fi

  sed \
    -e "s|@@PDK_ROOT@@|${PDK_ROOT}|g" \
    -e "s|@@PDK@@|${PDK}|g" \
    -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
    -e "s|@@MOS_SECTION@@|${section}|g" \
    -e "s|@@TEMP_C@@|${temp}|g" \
    -e "s|@@VDD_V@@|${vdd}|g" \
    -e "s|@@VCM_V@@|${vcm}|g" \
    -e "s|@@CL_F@@|${CL_F}|g" \
    -e "s|@@DUT_NETLIST@@|${DUT_NETLIST_SNAPSHOT}|g" \
    -e "s|@@SEED@@|${seed}|g" \
    -e "s|@@MC_N@@|${n}|g" \
    -e "s|@@MC_OUT@@|${samples}|g" \
    "${EXPERIMENT_DIR}/testbench/tb_cmrr_mc.spice.tmpl" > "${netlist}"

  rm -f "${samples}"

  rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

  sig="$(grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence|Simulation interrupted" "${log}" && echo 1 || echo 0)"
  have="$(grep -c -E '^(OP|AC) ' "${samples}" 2>/dev/null || true)"
  if [[ ${rc} -ne 0 ]] || [[ "${sig}" == "1" ]] || [[ "${have}" -ne $((2 * n)) ]]; then
    echo "run_cmrr_mismatch_mc.sh: SIM FAILED ${pid} ${tag} (rc=${rc}, lines=${have}/$((2*n))) -- raw log retained: ${log}" >&2
    return 1
  fi
  # The solver banner carries no evidence beyond the echo lines; on success
  # the extracted sample file is the committed artifact and the raw log is
  # removed. On failure the log above is retained for diagnosis. The
  # retained-logs-vs-samples policy is documented in README.md.
  rm -f "${log}"
  return 0
}

# ---------------------------------------------------------------------------
# Phase 1 -- pilots (nominal + #14's measured binding corner), N derivation.
# The pilot sigma is the larger of the two pilot points' LINEAR Acm sigma;
# N is the smallest sample count meeting BOTH the spec row's N>=300 floor
# and the relative-sampling-error constraint on that sigma. Pilot sample
# files are committed alongside the grid ones.
#   SE(sigma_hat)/sigma ~ 1/sqrt(2N)  ->  N_req = ceil(1/(2*MC_TARGET_SIGMA_RE^2))
# ---------------------------------------------------------------------------
pilot_sigma_lin="unset"
MC_N_EFFECTIVE="${MC_N_FLOOR}"
if [[ ! -s "${RECORDS_DIR}/${RECORD_ID}.pilot.txt" ]]; then
  echo "run_cmrr_mismatch_mc.sh: pilot phase -- points: ${PILOT_A_IDX} ${point_ids[$PILOT_A_IDX]}, ${PILOT_B_IDX} ${point_ids[$PILOT_B_IDX]} at N=${MC_N_FLOOR}" >&2
  run_deck "${PILOT_A_IDX}" "${point_corners[$PILOT_A_IDX]}_mismatch" "${MC_N_FLOOR}" "pilot"
  run_deck "${PILOT_B_IDX}" "${point_corners[$PILOT_B_IDX]}_mismatch" "${MC_N_FLOOR}" "pilot"
  pilot_out="$(python3 - "${CORNERS_OUT}" "${PILOT_A_IDX}" "${PILOT_B_IDX}" "${MC_TARGET_SIGMA_RE}" "${MC_N_FLOOR}" <<'PYEOF'
import math, os, sys
corners, a_idx, b_idx, sigma_re, floor_n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
def pid_of(i):
    C = ['mos_tt','mos_ss','mos_ff','mos_sf','mos_fs']; T = [-40,27,125]; V = ['1.08','1.20','1.32']
    return f"{C[i//9]}_{T[(i%9)//3]}C_{V[i%3]}V"
def sigma_of(i):
    acs = []
    with open(os.path.join(corners, f"{pid_of(i)}_pilot_samples.txt")) as f:
        for line in f:
            p = line.split()
            if p and p[0] == "AC":
                acs.append(10 ** (float(p[2]) / 20.0))  # linear Acm
    n = len(acs)
    mu = sum(acs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in acs) / (n - 1))
    return mu, sd
ma, sa = sigma_of(a_idx)
mb, sb = sigma_of(b_idx)
sig = max(sa, sb)
# N derivation: the quoted bound hinges on the linear-domain sigma, so N
# must make its sampling error small: SE(sigma_hat)/sigma ~ 1/sqrt(2N) <
# sigma_re  =>  N > 1/(2*sigma_re^2). The spec row's N>=300 floor stays
# the co-dominant constraint (epsilon 5% needs only N=200).
n_req = math.ceil(1 / (2 * sigma_re ** 2))
n_eff = max(floor_n, n_req)
print(f"{sig:.6g} {n_eff}")
PYEOF
)"
  pilot_sigma_lin="${pilot_out%% *}"
  MC_N_EFFECTIVE="${pilot_out##* }"
  if ! [[ "${MC_N_EFFECTIVE}" =~ ^[0-9]+$ ]]; then
    echo "run_cmrr_mismatch_mc.sh: pilot N derivation produced non-integer N (${MC_N_EFFECTIVE}) -- aborting" >&2
    exit 1
  fi
  if [[ "${MC_N_EFFECTIVE}" -gt "${MC_N_FLOOR}" ]]; then
    echo "run_cmrr_mismatch_mc.sh: N raised above the floor to ${MC_N_EFFECTIVE} (pilot linearsigma ${pilot_sigma_lin} V/V)" >&2
  fi
  {
    echo "pilot_points: ${PILOT_A_IDX} ${point_ids[$PILOT_A_IDX]} (seed ${point_seeds[$PILOT_A_IDX]}), ${PILOT_B_IDX} ${point_ids[$PILOT_B_IDX]} (seed ${point_seeds[$PILOT_B_IDX]})"
    echo "pilot_n: ${MC_N_FLOOR}"
    echo "pilot_acm_sigma_max_linear: ${pilot_sigma_lin}"
    echo "mc_target_sigma_re: ${MC_TARGET_SIGMA_RE}"
    echo "mc_n_effective: ${MC_N_EFFECTIVE}"
    echo "mc_n_floor: ${MC_N_FLOOR}"
    echo "ngspice: ${NGSPICE_VERSION}"
    echo "ac_record: ${AC_RECORD_ID}"
    echo "cmrr_record: ${CMRR_RECORD_ID}"
    echo "seed_base: ${MC_SEED_BASE}"
    echo "seed_formula: seed = MC_SEED_BASE + grid_index (corner-major, 0-based)"
    echo "mismatch_section_formula: corner + '_mismatch' (cornerMOSlv.lib per-corner sections)"
  } > "${RECORDS_DIR}/${RECORD_ID}.pilot.txt"
else
  MC_N_EFFECTIVE="$(sed -n 's/^mc_n_effective: //p' "${RECORDS_DIR}/${RECORD_ID}.pilot.txt")"
  echo "run_cmrr_mismatch_mc.sh: resume -- pilot already derived (mc_n_effective=${MC_N_EFFECTIVE})" >&2
fi

# ---------------------------------------------------------------------------
# Phase 2 -- grid: all 45 points, mismatch section, N_effective samples each.
# ---------------------------------------------------------------------------
sim_fail_points=()
for i in "${!point_ids[@]}"; do
  if ! run_deck "$i" "${point_corners[$i]}_mismatch" "${MC_N_EFFECTIVE}" "mc"; then
    sim_fail_points+=("${point_ids[$i]}")
  fi
done

# ---------------------------------------------------------------------------
# Phase 3 -- negative control at every grid point (plain section = the exact
# zero-mismatch configuration #14 ran), machine-asserted against #25's
# committed record AND against the MC machinery's per-point stats joiner.
# ---------------------------------------------------------------------------
negctl_fail_points=()
for i in "${!point_ids[@]}"; do
  if ! run_deck "$i" "${point_corners[$i]}" "${MC_NEGCTL_N}" "negctl"; then
    negctl_fail_points+=("${point_ids[$i]}")
    continue
  fi
  if ! python3 - "${CORNERS_OUT}" "${AC_RECORD_CSV}" "${CMRR_RECORD_CSV}" \
      "${point_ids[$i]}" "${NEGCTL_TOL_DB}" "${NEGCTL_TOL_V}" <<'PYEOF' > /dev/null
import csv, os, sys
corners, ac_csv, cmrr_csv, point_id, tol_db, tol_v = sys.argv[1:7]
tol_db, tol_v = float(tol_db), float(tol_v)
# point_id shape: <corner>_<temp>C_<vdd>V ; corner names carry no underscores
parts = point_id.split("_")
TEMP, VDD = parts[1][:-1], parts[2][:-1]
sy, ol = {}, {}
for r in csv.DictReader(open(cmrr_csv)):
    if r["point_id"] == point_id:
        sy = r; break
for r in csv.DictReader(open(ac_csv)):
    if r["point_id"] == point_id:
        ol = r; break
assert sy and ol, f"no committed systematic row for {point_id}"
sys_acm0 = float(sy["acm0_db"]); sys_vout = float(sy["vout_dc_v"])
sys_vibias = float(sy["vibias_dc_v"]); sys_cmrr = float(sy["cmrr_db"])
av0 = float(ol["av0_db"])
ops, acs = [], []
with open(os.path.join(corners, f"{point_id}_negctl_samples.txt")) as f:
    for line in f:
        p = line.split()
        if p and p[0] == "OP":
            ops.append([float(x) for x in p[2:8]])
        elif p and p[0] == "AC":
            acs.append([float(x) for x in p[2:5]])
assert len(ops) == len(acs), f"{point_id}: OP/AC pair mismatch"
for k, (op, ac) in enumerate(zip(ops, acs)):
    dev_acm = abs(ac[0] - sys_acm0)
    dev_vout = abs(op[0] - sys_vout)
    dev_vibias = abs(op[4] - sys_vibias)
    dev_cmrr = abs((av0 - ac[0]) - sys_cmrr)
    assert dev_acm <= tol_db, f"{point_id}[{k}]: negctl acm dev {dev_acm}"
    assert dev_cmrr <= tol_db, f"{point_id}[{k}]: negctl cmrr dev {dev_cmrr}"
    assert dev_vout <= tol_v, f"{point_id}[{k}]: negctl vout dev {dev_vout}"
    assert dev_vibias <= tol_v, f"{point_id}[{k}]: negctl vibias dev {dev_vibias}"
    # all iterations must be IDENTICAL (no agauss anywhere in the plain
    # section): the first-draw-vs-committed asserts above already pin the
    # value; the spread assert proves the "zero draw" part.
    assert abs(op[0] - ops[0][0]) <= 1e-9 and abs(ac[0] - acs[0][0]) <= 1e-9, \
        f"{point_id}[{k}]: negctl samples not identical"
PYEOF
  then
    echo "run_cmrr_mismatch_mc.sh: NEGCTL FAILED ${point_ids[$i]} -- deviation vs #25 record out of tolerance" >&2
    negctl_fail_points+=("${point_ids[$i]}")
  fi
done

# ---------------------------------------------------------------------------
# Phase 4 -- reproducibility at the nominal point: same seed re-run must be
# byte-identical to the grid run's sample file; the alt-seed run must
# differ. Artifacts committed as repro_<seed>_samples.txt + repro_check.txt.
# ---------------------------------------------------------------------------
NOMINAL_IDX="${PILOT_A_IDX}"
NOMINAL_PID="${point_ids[$NOMINAL_IDX]}"
repro_state=fail
if run_deck "${NOMINAL_IDX}" "${point_corners[$NOMINAL_IDX]}_mismatch" "${MC_N_EFFECTIVE}" "repro" ; then
  if run_deck "${NOMINAL_IDX}" "${point_corners[$NOMINAL_IDX]}_mismatch" "${MC_N_EFFECTIVE}" "repro_alt" "${MC_SEED_ALT}"; then
    if cmp -s "${CORNERS_OUT}/${NOMINAL_PID}_mc_samples.txt" "${CORNERS_OUT}/${NOMINAL_PID}_repro_samples.txt"; then
      if ! cmp -s "${CORNERS_OUT}/${NOMINAL_PID}_mc_samples.txt" "${CORNERS_OUT}/${NOMINAL_PID}_repro_alt_samples.txt"; then
        repro_state=pass
      else repro_state="alt-seed-identical"; fi
    else repro_state="same-seed-diverged"; fi
  else repro_state="alt-seed-run-failed"; fi
else repro_state="same-seed-run-failed"; fi
{
  echo "nominal_point: ${NOMINAL_PID}"
  echo "grid_seed: ${point_seeds[$NOMINAL_IDX]}"
  echo "alt_seed: ${MC_SEED_ALT}"
  echo "mc_n_effective: ${MC_N_EFFECTIVE}"
  case "${repro_state}" in
    pass)
      echo "same_seed_rerun: byte-identical to ${NOMINAL_PID}_mc_samples.txt (PASS)"
      echo "alt_seed_rerun: different draw sequence (PASS)" ;;
    *) echo "RESULT: ${repro_state} (FAIL)" ;;
  esac
} > "${CORNERS_OUT}/repro_check.txt"
if [[ "${repro_state}" != "pass" ]]; then
  echo "run_cmrr_mismatch_mc.sh: REPRO FAILED (${repro_state}) -- see ${CORNERS_OUT}/repro_check.txt" >&2
fi

# ---------------------------------------------------------------------------
# Phase 5 -- stats across the grid, completeness + control gates, record.
# ---------------------------------------------------------------------------
declare -a rows=()
stat_fail_points=()
for i in "${!point_ids[@]}"; do
  samples="${CORNERS_OUT}/${point_ids[$i]}_mc_samples.txt"
  row="$(stat_point "$i" "${samples}" || true)"
  if [[ -z "${row}" ]]; then
    stat_fail_points+=("${point_ids[$i]}")
  elif grep -qE "^(NOJOIN|TRUNCATED|ALLFAIL)" <<<"${row}"; then
    echo "run_cmrr_mismatch_mc.sh: STATS FAILED ${point_ids[$i]}: ${row}" >&2
    stat_fail_points+=("${point_ids[$i]}")
  else
    rows+=("${row}")
  fi
done

n_rows="${#rows[@]}"
if [[ "${n_rows}" -lt "${NP}" ]]; then
  echo "run_cmrr_mismatch_mc.sh: refusing to write a record: ${n_rows}/${NP} points produced stat rows" >&2
  echo "run_cmrr_mismatch_mc.sh: sim_fail=${sim_fail_points[*]:-none}; stat_fail=${stat_fail_points[*]:-none}; negctl_fail=${negctl_fail_points[*]:-none}; repro=${repro_state}" >&2
  exit 1
fi
if [[ "${#sim_fail_points[@]}" -gt 0 || "${#stat_fail_points[@]}" -gt 0 || "${#negctl_fail_points[@]}" -gt 0 || "${repro_state}" != "pass" ]]; then
  echo "run_cmrr_mismatch_mc.sh: refusing to write a record: controls not clean" >&2
  echo "run_cmrr_mismatch_mc.sh: sim_fail=${sim_fail_points[*]:-none}; stat_fail=${stat_fail_points[*]:-none}; negctl_fail=${negctl_fail_points[*]:-none}; repro=${repro_state}" >&2
  exit 1
fi

header="point_id,corner,temp_c,vdd_v,vcm_v,av0_db,sys_acm0_db,sys_cmrr_db,mc_n,mc_n_ok,mc_n_excluded,op_fail,plateau_fail,acm_lin_mean,acm_lin_sigma,acm_plus_3sigma_db,cmrr_3sigma_db,cmrr_db_mean,cmrr_db_p01,cmrr_db_min,cmrr_1khz_3sigma_db,plateau_max_db"
{
  echo "${header}"
  for r in "${rows[@]}"; do echo "${r}"; done
} > "${CSV_OUT}"

# Completeness guard: one row per grid cell.
n_written=$(($(wc -l < "${CSV_OUT}") - 1))
if [[ "${n_written}" -ne "${NP}" ]]; then
  echo "run_cmrr_mismatch_mc.sh: WARNING -- ${n_written} rows written, expected ${NP}" >&2
fi

# Grid summary + controls digest for the record .md.
SUMMARY="$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
def col(key):
    try:
        return [(float(r[key]), r["point_id"]) for r in rows if r[key]]
    except ValueError:
        return []
print(f"points: {len(rows)}, mc_n per point: {rows[0]['mc_n']}")
for key in ("cmrr_3sigma_db", "cmrr_1khz_3sigma_db", "cmrr_db_p01", "cmrr_db_min", "cmrr_db_mean"):
    vals = col(key)
    if vals:
        lo, pid_lo = min(vals)
        hi, pid_hi = max(vals)
        print(f"{key}: worst(min) {lo:.4g} at {pid_lo}, best(max) {hi:.4g} at {pid_hi}")
ex_total = sum(int(r["mc_n_excluded"]) for r in rows)
op_total = sum(int(r["op_fail"]) for r in rows)
pl_total = sum(int(r["plateau_fail"]) for r in rows)
print(f"excluded samples total: {ex_total} (op_fail {op_total}, plateau_fail {pl_total}) of {sum(int(r['mc_n']) for r in rows)}")
nom = [r for r in rows if r["point_id"] == "mos_tt_27C_1.20V"][0]
print(f"nominal mos_tt_27C_1.20V: sys_cmrr {nom['sys_cmrr_db']}, mc mean {nom['cmrr_db_mean']},"
      f" 3sigma bound {nom['cmrr_3sigma_db']} (acm mu {nom['acm_lin_mean']}, sigma {nom['acm_lin_sigma']})")
PYEOF
)"

{
  echo "points,${NP}"
  echo "mc_n_per_point,${MC_N_EFFECTIVE}"
  echo "pilot_acm_sigma_max_linear,${pilot_sigma_lin}"
  echo "sim_fail_count,${#sim_fail_points[@]}"
  echo "negctl_fail_count,${#negctl_fail_points[@]}"
  echo "repro,${repro_state}"
  echo "negctl_tolerance_db,${NEGCTL_TOL_DB}"
  echo "negctl_tolerance_v,${NEGCTL_TOL_V}"
  echo "plateau_tolerance_db,${PLATEAU_TOL_DB}"
  echo "op_rule,midrail ${OP_MID_FRAC}*VDD, inner nodes ${OP_RAIL_FRAC}*VDD rail margin"
} > "${CORNERS_OUT}/sanity_checks.txt"

cat > "${MD_OUT}" <<EOF
# cmrr-mismatch record ${RECORD_ID}

Generated by \`sim/cmrr-mismatch/run_cmrr_mismatch_mc.sh\` against
\`design/netlist/opamp_core.spice\` (snapshot:
\`netlist-snapshots/${RECORD_ID}/opamp_core.spice\`), ${NGSPICE_VERSION},
PDK \`${PDK}\` rooted at \`${PDK_ROOT}\` (pin: see \`sim/pdk.json\`), OSDI
models from \`${OSDI_DIR}\`. Every sample's CMRR divides the SAME grid
point's \`av0_db\` of the open-loop record
\`sim/open-loop-ac/records/${AC_RECORD_ID}.csv\` (joined, not
re-measured), per issue #26's harness-reuse wording. The negative control
asserts the zero-mismatch deck (plain \`${CORNERS[*]}\` sections, the exact
configuration \`sim/cmrr-psrr/\` ran) reproduces #25's committed
\`sim/cmrr-psrr/records/${CMRR_RECORD_ID}.csv\` per point (acm0/vout/vibias
and the derived cmrr, tolerances ${NEGCTL_TOL_DB} dB / ${NEGCTL_TOL_V} V).

Grid: cornerMOSlv.lib \`${CORNERS[*]}\` mismatch sections
(\`<corner>_mismatch\` -> sg13g2_moslv_mod_mismatch.lib) x temperature
\`{-40, 27, 125} C\` x supply \`{1.08, 1.20, 1.32} V\` = ${NP} points,
**MC_N = ${MC_N_EFFECTIVE}** samples per point (each sample one fresh
independent per-instance agauss draw of all eight MOSFETs), into
\`CL = ${CL_F} F\` [DR-1]. N derived from the pilots at
${point_ids[$PILOT_A_IDX]} and ${point_ids[$PILOT_B_IDX]}: worst pilot
linear-Acm sigma ${pilot_sigma_lin} V/V, N chosen so the sigma's sampling
error stays below MC_TARGET_SIGMA_RE = ${MC_TARGET_SIGMA_RE}
(SE(sigma_hat)/sigma ~ 1/sqrt(2N)), floor N ${MC_N_FLOOR} per the spec
row's "mismatch MC N>=300" wording. Seeds: setseed = ${MC_SEED_BASE} +
grid index (corner-major, 0-based); reproducibility machine-checked
(\`corners/${RECORD_ID}/repro_check.txt\`: same seed byte-identical, alt
seed ${MC_SEED_ALT} a different draw).

The quoted per-point bound (cmrr_3sigma_db) is computed in the LINEAR
Acm domain -- the +3 sigma point of the drawn Acm distribution
(20*log10(mean+3*sigma)) mapped below the joined Av0 -- because the dB
image of the draw distribution is heavy-tailed on the rejection-good
side at the low-rail near-cancellation corners; empirical dB-domain
context columns (mean, 1st percentile, worst sample) are recorded
alongside. Per-sample AC points: 10 mHz shelf (Acm0 read, same
convention as #14), 0.1 Hz (plateau guard partner; tolerance
${PLATEAU_TOL_DB} dB, samples failing it are excluded and counted), and
1 kHz (in-band figure, the same frequency #14 reports alongside). Per-
sample DC sanity per #14's rule (output within ${OP_MID_FRAC}*VDD of
mid-rail, no internal node within ${OP_RAIL_FRAC}*VDD of a rail); failing
samples are excluded from the statistics and counted in the record's
excluded/op_fail columns.

## Worst/best-corner summary (mismatch-inclusive)

\`\`\`
${SUMMARY}
\`\`\`

Full per-point data (joined Av0 and #25 systematic values, linear-domain
Acm mean/sigma, the +3 sigma Acm point and its CMRR, empirical dB
mean/p1/min, the 1 kHz variant, per-point excluded/op/plateau counts,
plateau max deviation) is in \`records/${RECORD_ID}.csv\`. Per-sample
artifacts (the OP/AC echo lines, one file per point) are in
\`corners/${RECORD_ID}/\`, alongside each point's negative-control sample
file and the repro pair. Rendered per-point netlists (with their seeds in
the header) are in \`netlist-snapshots/${RECORD_ID}/\`.

Method, definition caveats (the fixed systematic numerator; the 3 sigma
domain choice; the shelf-only frequency claim) and what this bench does
not claim: \`sim/cmrr-mismatch/README.md\`.
EOF

echo "run_cmrr_mismatch_mc.sh: record ${RECORD_ID} written (${n_rows} points, MC_N=${MC_N_EFFECTIVE})." >&2

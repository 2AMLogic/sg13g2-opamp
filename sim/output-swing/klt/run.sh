#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/output-swing/klt/run.sh
#
# The output-swing bench (sim/output-swing/) as a `klt sim` request (issue
# #100) -- ONE-POINT NATIVE-CAPABILITY PROTOTYPE: runs swing.nominal.request.json
# (mos_tt / 27 C / 1.20 V only) on the LOCAL backend, gates the envelope with
# compare.py's `validate --points nominal`, and only then writes it,
# unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.nominal.sim.json
#
# followed by compare.py's join against the harness record of the same bench,
#
#   records/<id>.nominal.compare.json
#
# Grid mode submits two Spot batch jobs. Both passes, the original worker
# waveforms, derived summary, report-reader pins and baseline comparison
# are retained together in sim/.evidence-scratch/swing-<id>/.
#
# KLT selects the klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt".
#
# Exit 0 means the archived comparison agrees. Exit 3 identifies a
# preflight failure and 4 an incomplete capture or evidence validation
# failure. Exit 5 retains the measurements and reports a disagreement
# or an unavailable same-DUT baseline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=sim/preflight.sh
source "${SIM_DIR}/preflight.sh"
# shellcheck source=sim/tools/klt_run_common.sh
source "${SIM_DIR}/tools/klt_run_common.sh"

klt_check_client

MODE="${1:-nominal}"
case "${MODE}" in
  nominal|grid) ;;
  *) echo "usage: run.sh [nominal|grid [RUN_ID]]   (default nominal; grid = 45 points on the batch backend)" >&2; exit 3 ;;
esac

if [[ "${MODE}" != grid || -z "${2:-}" ]]; then
  # shellcheck disable=SC2119 # the optional --no-hint flag belongs to this helper
  sg13g2_preflight_require_netlist
fi

if [[ "${MODE}" == nominal ]]; then
  HARNESS_CSV="sim/output-swing/records/20260921-151759-707b34c.csv"
  klt_begin_record swing .nominal
  req="${SCRIPT_DIR}/swing.nominal.request.json"
  out="${SCRATCH}/swing.nominal.sim.json"
  # --backend local: one operating point (see header).
  klt_run_request "${req}" "${out}" "${SCRATCH}/swing.nominal.stderr" --backend local
  klt_validate_envelope "${out}" --points nominal
  klt_require_complete
  klt_write_envelope "${out}"
  KLT_OK_NOTE="within tolerance"
  KLT_PROVENANCE_EXTRA=(
    "command=${KLT_CMD[*]} sim swing.nominal.request.json --backend local --format json"
    "request_sha256=$(sha256sum "${req}" | cut -d' ' -f1)")
  klt_compare_and_finish --points nominal --harness-csv "${HARNESS_CSV}"
  exit 0
fi

# Preserve the exact submit directory and before-run identity across interruptions.
bundle_root="${SIM_DIR}/.evidence-scratch"
if [[ -n "${2:-}" ]]; then
  RECORD_ID="$2"
  if [[ ! "${RECORD_ID}" =~ ^[0-9]{8}-[0-9]{6}-[[:alnum:]]+$ ]]; then
    echo "run.sh: expected the original grid run ID" >&2; exit 3
  fi
  bundle="${bundle_root}/swing-${RECORD_ID}"
  cd "${REPO_ROOT}"
  KLT_RESERVATION="${SCRIPT_DIR}/records/.reserve-${RECORD_ID}"
  sg13g2_exclusive_mkdir "${KLT_RESERVATION}" || exit 3
  trap klt_release_reservation EXIT
  if [[ ! -s "${bundle}/environment.begin.json" || -e "${bundle}/selection.json" ]]; then
    echo "run.sh: need an interrupted bundle at ${bundle}" >&2; exit 3
  fi
  SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/swing-klt-${RECORD_ID}.XXXXXX")"
else
  if [[ -n "${SWING_KLT_ATTACH:-}${SWING_KLT_FINE_ATTACH:-}" ]]; then
    echo "run.sh: attach requires the original bundle: run.sh grid RUN_ID" >&2; exit 3
  fi
  klt_begin_record swing
  bundle="${bundle_root}/swing-${RECORD_ID}"
  mkdir -p "${bundle_root}"
  sg13g2_exclusive_mkdir "${bundle}" || exit 3
  mv "${SCRATCH}/${RECORD_ID}.env.json" "${bundle}/environment.begin.json"
  python3 "${SCRIPT_DIR}/grid.py" coarse-request "${bundle}" || exit 4
fi

echo "run.sh: retaining swing evidence in ${bundle}; klt artifacts in ${SCRATCH}" >&2
for phase in coarse fine; do
  expected="${SWING_KLT_ATTACH:-}"
  if [[ "${phase}" == fine ]]; then
    if [[ ! -f "${bundle}/fine.request.json" ]]; then
      python3 "${SCRIPT_DIR}/grid.py" fine-request "${bundle}" "${SCRATCH}/coarse" || exit 4
    fi
    expected="${SWING_KLT_FINE_ATTACH:-}"
  fi
  req="${bundle}/${phase}.request.json"
  submission="${bundle}/${phase}"
  if [[ ! -d "${submission}" && -z "${expected}" && ( "${phase}" == fine || -z "${2:-}" ) ]]; then
    mkdir "${submission}"
    klt_run_request "${req}" "${SCRATCH}/${phase}.submit.json" "${SCRATCH}/${phase}.submit.stderr" \
      --backend batch --submit-only --outdir "${submission}"
    klt_require_complete
  fi
  # Refuse an unreceipted job even if klt would allow an attach from scratch.
  job=$(python3 "${SCRIPT_DIR}/grid.py" submission-job "${bundle}" "${phase}" ${expected:+"${expected}"}) || exit 4
  if [[ "${phase}" == coarse && -f "${bundle}/fine.request.json" ]]; then
    # fine-request already retained the coarse curves. finish revalidates them.
    continue
  fi
  mkdir "${SCRATCH}/${phase}"
  cp "${submission}/batch-receipt.json" "${SCRATCH}/${phase}/"
  klt_run_request "${req}" "${SCRATCH}/${phase}.sim.json" "${SCRATCH}/${phase}.stderr" \
    --backend batch --outdir "${SCRATCH}/${phase}" --attach "${job}"
  klt_require_complete
  mv "${SCRATCH}/${phase}.sim.json" "${bundle}/${phase}.sim.json"
done
sg13g2_env_identity_finalize "${RECORD_ID}" "${bundle}/environment.begin.json" "${bundle}/environment.json"
rc=0
python3 "${SCRIPT_DIR}/grid.py" finish "${bundle}" "${SCRATCH}/fine" || rc=$?
case "${rc}" in
  0|5) rm -rf "${SCRATCH}"; exit "${rc}" ;;
  *) exit 4 ;;
esac

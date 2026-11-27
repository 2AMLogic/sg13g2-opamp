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
# shellcheck disable=SC2119 # the optional --no-hint flag belongs to this helper
sg13g2_preflight_require_netlist
# shellcheck source=sim/tools/klt_run_common.sh
source "${SIM_DIR}/tools/klt_run_common.sh"

klt_check_client

MODE="${1:-nominal}"
case "${MODE}" in
  nominal|grid) ;;
  *) echo "usage: run.sh [nominal|grid]   (default nominal; grid = 45 points on the batch backend)" >&2; exit 3 ;;
esac

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

# Each run owns a fresh bundle. selection.json is written last, after both
# envelopes, the model-identity recheck and the per-corner audit succeed.
klt_begin_record swing
bundle="${SIM_DIR}/.evidence-scratch/swing-${RECORD_ID}"
mkdir -p "${SIM_DIR}/.evidence-scratch"
sg13g2_exclusive_mkdir "${bundle}" || exit 3
echo "run.sh: retaining swing evidence in ${bundle}; klt artifacts in ${SCRATCH}" >&2
python3 "${SCRIPT_DIR}/grid.py" coarse-request "${bundle}" || exit 4
for phase in coarse fine; do
  attach="${SWING_KLT_ATTACH:-}"
  if [[ "${phase}" == fine ]]; then
    python3 "${SCRIPT_DIR}/grid.py" fine-request "${bundle}" "${SCRATCH}/coarse" || exit 4
    attach="${SWING_KLT_FINE_ATTACH:-}"
  fi
  args=(--backend batch --outdir "${SCRATCH}/${phase}")
  [[ -z "${attach}" ]] || args+=(--attach "${attach}")
  klt_run_request "${bundle}/${phase}.request.json" "${bundle}/${phase}.sim.json" \
    "${SCRATCH}/${phase}.stderr" "${args[@]}"
  klt_require_complete
done
sg13g2_env_identity_finalize "${RECORD_ID}" "${SCRATCH}/${RECORD_ID}.env.json" "${bundle}/environment.json"
rc=0
python3 "${SCRIPT_DIR}/grid.py" finish "${bundle}" "${SCRATCH}/fine" || rc=$?
case "${rc}" in
  0|5) rm -rf "${SCRATCH}"; exit "${rc}" ;;
  *) exit 4 ;;
esac

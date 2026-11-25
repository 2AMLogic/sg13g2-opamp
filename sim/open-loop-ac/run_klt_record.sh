#!/usr/bin/env bash
#
# Issue #241 / #500: the schematic open-loop AC+OP bench with inn AC-grounded
# (Cinn_acgnd, 1 F), measured over the ratified 45-point grid through `klt sim`.
#
#   bash sim/open-loop-ac/run_klt_record.sh
#
# Measures design/netlist/opamp_core.spice directly with the committed
# schematic klt requests (sim/open-loop-ac/klt/openloop_{ac,op}.request.json:
# one AC and one OP request, 45 corners each, CL = 2 pF [DR-1], preserving the
# internal-node operating-point measurements vd1, vd2, vtail and vibias) and
# writes
#
#   netlist-snapshots/<id>/opamp_core.spice    the schematic DUT simulated
#   corners/<id>/                              both klt sim envelopes
#                                              (environment.remote = batch
#                                              job id), requests, bench body,
#                                              stderr, measurement.json
#   records/<id>.{csv,md}                      the record (summarize_klt.py)
#
# Extracted `.SUBCKT` netlists hide internal nodes and use the post-layout
# port-only runner sim/post-layout/measure_openloop_ac.sh instead.
#
# GRID: never run locally on a shared dispatch host. The requests declare
# "backend": "batch", batch submissions pass --wait-for-capacity 600, and a
# failed batch submit exits 1 leaving the partial corners/<id>/ for inspection;
# it never falls back to a local grid. Set OPENLOOP_SUPERSEDES=<record-id> only
# when deliberately comparing two configurations on the same DUT.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
_sg13g2_preflight_self="$(basename "$0")"
# shellcheck source=/dev/null
source "${REPO_ROOT}/sim/env.sh" >&2
# shellcheck source=/dev/null
source "${REPO_ROOT}/sim/record-paths.sh"

read -r -a KLT_CMD <<< "${KLT:-klt}"
command -v "${KLT_CMD[0]}" >/dev/null 2>&1 || {
  echo "${_sg13g2_preflight_self}: klt not found (${KLT_CMD[*]})" >&2
  exit 1
}

DUT_SRC="${OPENLOOP_DUT_NETLIST:-${REPO_ROOT}/design/netlist/opamp_core.spice}"
SUPERSEDES="${OPENLOOP_SUPERSEDES:-}"

sg13g2_preflight_record_paths
echo "record ${RECORD_ID}" >&2

mkdir -p "${SNAPSHOTS_OUT}"
cp "${DUT_SRC}" "${SNAPSHOTS_OUT}/opamp_core.spice"
python3 -I "${SCRIPT_DIR}/summarize_klt.py" stage "${SNAPSHOTS_OUT}/opamp_core.spice" "${CORNERS_OUT}"

SIMOUT="$(mktemp -d "${TMPDIR:-/tmp}/openloop-klt-sim.XXXXXX")"
trap 'rm -rf "${SIMOUT}"' EXIT

EFFECTIVE_BACKEND="${OPENLOOP_KLT_BACKEND:-batch}"
WAIT_ARGS=()
if [[ "${EFFECTIVE_BACKEND}" == "batch" ]]; then
  WAIT_ARGS=(--wait-for-capacity "${KLT_CAPACITY_WAIT_S:-600}")
fi
BACKEND_ARGS=()
if [[ -n "${OPENLOOP_KLT_BACKEND:-}" ]]; then
  BACKEND_ARGS=(--backend "${OPENLOOP_KLT_BACKEND}")
fi

(
  cd "${REPO_ROOT}"
  for kind in ac op; do
    rc=0
    "${KLT_CMD[@]}" sim "${CORNERS_OUT}/openloop_${kind}.request.json" \
      -o "${SIMOUT}/${kind}" --format json "${BACKEND_ARGS[@]}" "${WAIT_ARGS[@]}" \
      > "${CORNERS_OUT}/${kind}.envelope.json" 2> "${CORNERS_OUT}/${kind}.stderr" || rc=$?
    # klt sim: 0 = pass, 3 = ran and a limit failed -- both gradable.
    if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]]; then
      echo "${_sg13g2_preflight_self}: klt sim (${kind}) exited ${rc} -- record aborted." >&2
      sed 's/^/  stderr: /' "${CORNERS_OUT}/${kind}.stderr" >&2 || true
      exit 1
    fi
  done
)

if [[ -n "${SUPERSEDES}" ]]; then
  python3 -I "${SCRIPT_DIR}/summarize_klt.py" "${RECORD_ID}" "${CORNERS_OUT}" \
    "${SCRIPT_DIR}/records/${SUPERSEDES}.csv" "${CSV_OUT}" "${MD_OUT}"
else
  python3 -I "${SCRIPT_DIR}/summarize_klt.py" "${RECORD_ID}" "${CORNERS_OUT}" \
    "${CSV_OUT}" "${MD_OUT}"
fi
echo "wrote ${CSV_OUT} and ${MD_OUT}" >&2

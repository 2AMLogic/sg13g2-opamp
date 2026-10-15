#!/usr/bin/env bash
#
# Issue #241: the open-loop AC bench with inn AC-grounded (Cinn_acgnd, 1 F),
# measured over the ratified 45-point grid through `klt sim`.
#
#   bash sim/open-loop-ac/run_klt_record.sh
#
# Measures design/netlist/opamp_core.spice with the committed klt form of the
# bench (sim/post-layout/klt/, via sim/post-layout/measure_openloop_ac.sh:
# one AC and one OP request, 45 corners each, CL = 2 pF [DR-1]) and writes
#
#   netlist-snapshots/<id>/opamp_core.spice    the DUT simulated
#   corners/<id>/                              both klt sim envelopes
#                                              (environment.remote = batch
#                                              job id), requests, stderr,
#                                              measurement.json
#   records/<id>.{csv,md}                      the record (summarize_klt.py)
#
# GRID: never run locally. The requests declare "backend": "batch" and the
# dispatch workers export KLT_SIM_BACKEND=batch. A failed batch submit exits 1
# and leaves the partial corners/<id>/ for inspection; it does not fall back
# to a local grid. SUPERSEDES (does not edit) the floating-inn record
# records/20260910-221601-22feaba.*.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
_sg13g2_preflight_self="$(basename "$0")"
# shellcheck source=/dev/null
source "${REPO_ROOT}/sim/record-paths.sh"

SUPERSEDES="${OPENLOOP_SUPERSEDES:-20260910-221601-22feaba}"

sg13g2_preflight_record_paths
echo "record ${RECORD_ID}" >&2

mkdir -p "${SNAPSHOTS_OUT}"
cp "${REPO_ROOT}/design/netlist/opamp_core.spice" "${SNAPSHOTS_OUT}/opamp_core.spice"

rc=0
KLT_MEASURE_EXPECTED_CORNERS=45 KLT_PEX_ARTIFACTS_DIR="${CORNERS_OUT}" KLT_PEX_SIDE=schematic \
  bash "${REPO_ROOT}/sim/post-layout/measure_openloop_ac.sh" "${SNAPSHOTS_OUT}/opamp_core.spice" \
  > "${CORNERS_OUT}/measurement.json" 2> "${CORNERS_OUT}/measure.stderr" || rc=$?
if [[ "${rc}" -ne 0 || ! -s "${CORNERS_OUT}/measurement.json" ]]; then
  echo "measurement failed (exit ${rc}); see ${CORNERS_OUT}/measure.stderr" >&2
  sed 's/^/  /' "${CORNERS_OUT}/measure.stderr" >&2 || true
  exit 1
fi

python3 -I "${SCRIPT_DIR}/summarize_klt.py" "${RECORD_ID}" "${CORNERS_OUT}" \
  "${SCRIPT_DIR}/records/${SUPERSEDES}.csv" "${CSV_OUT}" "${MD_OUT}"
echo "wrote ${CSV_OUT} and ${MD_OUT}" >&2

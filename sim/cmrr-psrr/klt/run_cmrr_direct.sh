#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/cmrr-psrr/klt/run_cmrr_direct.sh
#
# Systematic CMRR as ONE `klt sim` measurement (issue #505): submits
# cmrr_direct.request.json (two DUT copies in one deck, cmrr_db = Av0 - Acm0)
# over the 45-point grid on the batch fleet, gates the envelope with
# compare_cmrr_direct.py's `validate`, and only then writes it, unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.cmrr.sim.json
#
# followed by compare_cmrr_direct.py's cross-check against the PSRR direct
# envelope (same engine, model deck, DUT hash; Av0 must agree) and the
# superseded harness record (Acm0 only; see the comparator's docstring),
#
#   records/<id>.cmrr.compare.json
#
# Backend: the request declares `"backend": "batch"`: 45 AC corners is a grid,
# and grids do not run on shared dispatch hosts. If the submit fails, report
# the error; do NOT fall back to the full grid locally. KLT selects the klt
# executable (default: `klt` on PATH). The submit waits for fleet capacity
# (--wait-for-capacity, KLT_CAPACITY_WAIT_S, default 600).
#
# CMRR_PSRR_DIRECT_ENVELOPE overrides the PSRR direct envelope joined to this
# run (default: the newest records/*.direct.sim.json); CMRR_HARNESS_CSV
# overrides the harness record.
# On success, write the checked envelope's absolute path to a new KLT_ENVELOPE_PATH_FILE
# when requested by run_klt_record.sh.
#
# Exit status: 0 records written and in agreement; 3 preflight failed; 4 no
# gradable envelope (nothing written); 5 records written but the cross-check
# found a point outside tolerance (reported, never hidden). A plateau-guard
# miss is a result (reported in the compare record), not a failure of this
# script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# The batch fleet simulates; the host needs only the PDK path klt resolves
# model references through (as open-loop-ac/klt/run.sh does).
# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh" >&2
# shellcheck source=/dev/null
source "${SIM_DIR}/tools/klt_run_common.sh"

NGSPICE_VERSION="n/a (simulated on the batch fleet)"

klt_check_client
# No run-time model-identity sidecar: on the batch backend the local host is not
# the machine that ran the simulation (same stance as open-loop-ac/klt/run.sh).
KLT_IDENTITY=0
KLT_COMPARE_PY=compare_cmrr_direct.py
KLT_OK_NOTE="direct CMRR joins the PSRR direct envelope at all 45 points"
PSRR_ENV="${CMRR_PSRR_DIRECT_ENVELOPE:-$(find "${SCRIPT_DIR}/records" -name '*.direct.sim.json' | sort | tail -1)}"
HARNESS_CSV="${CMRR_HARNESS_CSV:-sim/cmrr-psrr/records/20260921-151815-707b34c.csv}"

klt_begin_record cmrr-direct .cmrr
out="${SCRATCH}/cmrr_direct.sim.json"
klt_run_request "${SCRIPT_DIR}/cmrr_direct.request.json" "${out}" "${SCRATCH}/cmrr_direct.stderr"
klt_validate_envelope "${out}"
klt_require_complete
klt_write_envelope "${out}"

KLT_PROVENANCE_EXTRA=("submit_mode=single")
klt_compare_and_finish --psrr-envelope "${PSRR_ENV}" --harness-csv "${HARNESS_CSV}"
if [[ -n "${KLT_ENVELOPE_PATH_FILE:-}" ]]; then
  set -o noclobber
  printf '%s\n' "${RECORDS_DIR}/${RECORD_ID}${RECORD_SUFFIX}.sim.json" > "${KLT_ENVELOPE_PATH_FILE}"
fi

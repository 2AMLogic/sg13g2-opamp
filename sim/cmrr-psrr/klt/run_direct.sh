#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/cmrr-psrr/klt/run_direct.sh
#
# The PSRR row as ONE `klt sim` measurement (issue #307): submits
# psrr_direct.request.json (two DUT copies in one deck, psrr_db = Av0 - Avs0
# graded against the ratified 1.87 dB bound by the tool) over the 45-point grid
# on the batch fleet, gates the envelope with compare_direct.py's `validate`,
# and only then writes it, unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.direct.sim.json
#
# followed by compare_direct.py's cross-check against the two-envelope join,
#
#   records/<id>.direct.compare.json
#
# Backend: the request declares `"backend": "batch"`: 45 AC corners is a grid,
# and grids do not run on shared dispatch hosts. If the submit fails, report
# the error; do NOT fall back to the full grid locally. KLT selects the klt
# executable (default: `klt` on PATH).
#
# PSRR_JOIN_RECORD overrides the join record the envelope is checked against.
#
# Exit status: 0 records written and in agreement; 3 preflight failed; 4 no
# gradable envelope (nothing written); 5 records written but the cross-check
# found a point outside tolerance or a verdict disagreement (reported, never
# hidden). A missed PSRR limit is a result, not a failure of this script.
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
KLT_COMPARE_PY=compare_direct.py
KLT_OK_NOTE="direct PSRR agrees with the two-envelope join at all 45 points"
JOIN_RECORD="${PSRR_JOIN_RECORD:-sim/cmrr-psrr/klt/records/20261016-171154-ff5ee9a.compare.json}"

klt_begin_record psrr-direct .direct
out="${SCRATCH}/psrr_direct.sim.json"
klt_run_request "${SCRIPT_DIR}/psrr_direct.request.json" "${out}" "${SCRATCH}/psrr_direct.stderr"
klt_validate_envelope "${out}"
klt_require_complete
klt_write_envelope "${out}"

KLT_PROVENANCE_EXTRA=("submit_mode=single")
klt_compare_and_finish --join-record "${JOIN_RECORD}"

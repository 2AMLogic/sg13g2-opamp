#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/slew-rate/klt/run.sh
#
# The slew-rate bench (sim/slew-rate/) expressed as a `klt sim` request
# (issue #95): runs slew.request.json over the ratified 45-point grid, gates
# the envelope with compare.py's `validate`, and only then writes it,
# unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.sim.json
#
# followed by compare.py's join against the harness record of the same bench,
#
#   records/<id>.compare.json
#
# One envelope (the whole bench is one transient analysis, unlike
# sim/open-loop-ac/klt/'s AC + OP pair).
#
# Backend: the request declares `"backend": "batch"` (2am's EDA batch fleet):
# 45 transient corners is a grid, and grids do not run on shared dispatch
# hosts. Set SLEW_KLT_BACKEND=local (or local-parallel) on a machine where
# running the grid locally is appropriate; it is passed to klt as --backend.
# KLT selects the klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt" to match a fleet runner.
#
# Exit status: 0 records written; 3 preflight failed (PDK/OSDI/ngspice/klt
# missing -- nothing written); 4 the run produced no gradable envelope
# (klt error, errored/inconclusive corner, incomplete coverage -- nothing
# written to records/, the raw output is kept in a scratch dir named on
# stderr); 5 records written but compare.py found a point outside
# tolerance or an unexplained bound-verdict disagreement (see the
# compare.json it wrote -- reported, never hidden). The envelope's own
# pass/fail verdict does not change the exit status: a ratified bound missed
# at some corner is a result, recorded as such.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/preflight.sh"
sg13g2_preflight_require_netlist
# shellcheck source=/dev/null
source "${SIM_DIR}/tools/klt_run_common.sh"

klt_check_client

HARNESS_ID="20260918-210216-90844d2"
HARNESS_CSV="sim/slew-rate/records/${HARNESS_ID}.csv"
HARNESS_TRAN_DIR="sim/slew-rate/corners/${HARNESS_ID}"

klt_begin_record slew
BACKEND_ARGS=()
[[ -n "${SLEW_KLT_BACKEND:-}" ]] && BACKEND_ARGS=(--backend "${SLEW_KLT_BACKEND}")

req="${SCRIPT_DIR}/slew.request.json"
out="${SCRATCH}/slew.sim.json"
klt_run_request "${req}" "${out}" "${SCRATCH}/slew.stderr" "${BACKEND_ARGS[@]}"
klt_validate_envelope "${out}"
klt_require_complete
klt_write_envelope "${out}"

KLT_PROVENANCE_EXTRA=("backend_override=${SLEW_KLT_BACKEND:-none (request field: batch)}")
klt_compare_and_finish \
  --harness-csv "${HARNESS_CSV}" \
  --harness-tran-dir "${HARNESS_TRAN_DIR}"

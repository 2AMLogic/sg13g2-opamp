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
# This is NOT the 45-point envelope and is not evidence for T1 item 5
# (signoff/README.md); that work is deferred (README.md "Prototype vs accepted
# evidence"). This runner never declares or submits the 45-point grid, and it
# refuses to run any backend but local: a grid does not run on a shared
# dispatch host, and a batch submit is out of scope for the prototype.
#
# KLT selects the klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt".
#
# Exit status: 0 records written and the join agrees; 3 preflight failed
# (PDK/OSDI/ngspice/klt missing -- nothing written); 4 the run produced no
# gradable envelope (klt error, errored/inconclusive, incomplete coverage,
# failed validation -- nothing written to records/, the raw output is kept in
# a scratch dir named on stderr); 5 records written but compare.py found a
# point outside tolerance or an unexplained verdict disagreement (see the
# compare.json it wrote -- reported, never hidden). The envelope's own
# pass/fail verdict does not change the exit status: a ratified bound missed
# is a result, recorded as such.
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

HARNESS_ID="20260921-151759-707b34c"
HARNESS_CSV="sim/output-swing/records/${HARNESS_ID}.csv"

klt_begin_record swing .nominal

req="${SCRIPT_DIR}/swing.nominal.request.json"
out="${SCRATCH}/swing.nominal.sim.json"
# Always --backend local: one operating point (see header).
klt_run_request "${req}" "${out}" "${SCRATCH}/swing.nominal.stderr" --backend local
klt_validate_envelope "${out}" --points nominal
klt_require_complete
klt_write_envelope "${out}"

KLT_OK_NOTE="within tolerance"
KLT_PROVENANCE_EXTRA=(
  "command=${KLT_CMD[*]} sim swing.nominal.request.json --backend local --format json"
  "request_sha256=$(sha256sum "${req}" | cut -d' ' -f1)")
klt_compare_and_finish --points nominal --harness-csv "${HARNESS_CSV}"

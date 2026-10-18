#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/open-loop-ac/klt/run.sh
#
# The open-loop AC bench (sim/open-loop-ac/) expressed as `klt sim` requests
# (issue #85): runs openloop_ac.request.json (Av0, GBW, phase at the unity-gain
# crossing) and openloop_op.request.json (Iq plus the per-point DC sanity
# checks) over the ratified 45-point grid, gates each envelope with
# compare.py's `validate`, and only then writes the pair, unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.ac.sim.json
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.op.sim.json
#
# followed by compare.py's join against the grounded-inn klt record of the
# same bench (records/20261015-103057-895d555.csv, issue #241),
#
#   records/<id>.compare.json
#
# Two envelopes, not one: `klt sim` runs one analysis per corner, and Iq/the
# DC sanity checks are operating-point quantities while Av0/GBW/PM come from
# an AC sweep -- see README.md "Why two requests".
#
# Backend: the requests declare `"backend": "batch"` (2am's EDA batch fleet):
# 45 corners x 2 analyses is a grid, and grids do not run on shared dispatch
# hosts. Set OPENLOOP_KLT_BACKEND=local (or local-parallel) on a machine
# where running the grid locally is appropriate; it is passed to klt as
# --backend. KLT selects the klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt" to match a fleet runner.
#
# Exit status: 0 records written; 3 preflight failed (PDK/OSDI/ngspice/klt
# missing -- nothing written); 4 a run produced no gradable envelope
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

# The batch backend (the default) simulates on the fleet, so the host needs
# neither the pinned ngspice nor built OSDI models -- only the PDK path klt
# resolves model references through (what measure_openloop_ac.sh does). The
# full local preflight (PDK + OSDI + ngspice) applies only when the grid is
# deliberately sent to a local backend.
case "${OPENLOOP_KLT_BACKEND:-batch}" in
  batch)
    # shellcheck source=/dev/null
    source "${SIM_DIR}/env.sh" >&2
    NGSPICE_VERSION="n/a (simulated on the batch fleet)"
    ;;
  *)
    # shellcheck source=/dev/null
    source "${SIM_DIR}/preflight.sh"
    sg13g2_preflight_require_netlist
    ;;
esac

# shellcheck source=/dev/null
source "${SIM_DIR}/tools/klt_run_common.sh"

klt_check_client

# The baseline is the grounded-inn klt record (issue #241). The floating-inn
# harness record 20260910-221601-22feaba is superseded: its Av0/GBW/PM were
# measured on a bench whose inn was AC-floating and cannot be compared with
# this bench's numbers.
BASELINE_ID="20261015-103057-895d555"
BASELINE_CSV="sim/open-loop-ac/records/${BASELINE_ID}.csv"

# Two envelopes and a comparison share one record id: reserve the id once and
# refuse if any of them exists (issue #274).
KLT_RECORD_EXTS=(.ac.sim.json .op.sim.json .compare.json)
# No run-time PDK/model identity sidecar (<id>.env.json) for this bench yet:
# with the default batch backend the local host is not the machine that ran
# the simulation, so what to record there is an open operator question that
# must be answered for every klt bench at once (issue #274). Until then this
# bench keeps its existing behaviour -- no capture, no sidecar.
KLT_IDENTITY=0
klt_begin_record openloop
BACKEND_ARGS=()
[[ -n "${OPENLOOP_KLT_BACKEND:-}" ]] && BACKEND_ARGS=(--backend "${OPENLOOP_KLT_BACKEND}")

for kind in ac op; do
  klt_run_request "${SCRIPT_DIR}/openloop_${kind}.request.json" \
    "${SCRATCH}/${kind}.sim.json" "${SCRATCH}/${kind}.stderr" "${BACKEND_ARGS[@]}"
  klt_validate_envelope "${SCRATCH}/${kind}.sim.json" --kind "${kind}"
done
klt_require_complete

for kind in ac op; do
  klt_write_envelope "${SCRATCH}/${kind}.sim.json" ".${kind}.sim.json"
done

rel="${SCRIPT_DIR#"${REPO_ROOT}"/}"
KLT_COMPARE_ENVELOPE_ARGS=(
  --ac "${rel}/records/${RECORD_ID}.ac.sim.json"
  --op "${rel}/records/${RECORD_ID}.op.sim.json"
)
KLT_PROVENANCE_EXTRA=(
  "baseline_record=${BASELINE_ID}"
  "backend_override=${OPENLOOP_KLT_BACKEND:-none (request field: batch)}"
)
klt_compare_and_finish --harness-csv "${BASELINE_CSV}"

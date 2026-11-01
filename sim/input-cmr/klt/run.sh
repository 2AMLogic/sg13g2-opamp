#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/input-cmr/klt/run.sh grid           # 45 points, batch backend
#
# The input-cmr (ICMR) bench (sim/input-cmr/) as a `klt sim` request (issue
# #325). `run.sh nominal` (the default) runs icmr.nominal.request.json (mos_tt /
# 27 C / 1.20 V, ONE operating point) on the LOCAL backend; `run.sh grid`
# submits icmr.request.json (the 45-point grid) on the BATCH backend, as the
# host rules require (a dispatch worker never hand-launches a grid). Either
# way the envelope is gated by compare.py's `validate` and only then written,
# unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>[.nominal].sim.json
#
# followed by compare.py's join against the committed local-harness record,
#
#   records/<id>[.nominal].compare.json
#
# Records are append-only: an existing id is refused, never overwritten.
#
# KLT selects the klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt". ICMR_KLT_ATTACH=<job id>
# re-attaches to an already-submitted batch job (e.g. after the client was
# interrupted) instead of submitting a new grid. A failed batch submit is
# reported and exits non-zero; there is NO local fallback for the grid.
#
# Exit status: 0 records written and the join agrees; 3 preflight failed
# (PDK/OSDI/ngspice/klt missing -- nothing written); 4 the run produced no
# gradable envelope (PDK/model identity drifted during the run, issue #209;
# klt error, errored/inconclusive, incomplete coverage, failed validation --
# nothing written to records/, the raw output is kept in a scratch dir named on
# stderr); 5 records written but compare.py found a point outside tolerance or
# an unexplained label disagreement (see the compare.json it wrote -- reported,
# never hidden).
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

HARNESS_ID="20260921-174405-65f5fb4"
HARNESS_CSV="sim/input-cmr/records/${HARNESS_ID}.csv"

MODE="${1:-nominal}"
case "${MODE}" in
  nominal|grid) ;;
  *) echo "usage: run.sh [nominal|grid]   (default nominal; grid = 45 points on the batch backend)" >&2; exit 3 ;;
esac

if [[ "${MODE}" == nominal ]]; then
  klt_begin_record icmr .nominal
  req="${SCRIPT_DIR}/icmr.nominal.request.json"
  out="${SCRATCH}/icmr.nominal.sim.json"
  # --backend local: one operating point (see header).
  klt_run_request "${req}" "${out}" "${SCRATCH}/icmr.nominal.stderr" --backend local
  klt_validate_envelope "${out}" --points nominal
  klt_require_complete
  klt_write_envelope "${out}"
  KLT_OK_NOTE="within tolerance"
  KLT_PROVENANCE_EXTRA=(
    "command=${KLT_CMD[*]} sim icmr.nominal.request.json --backend local --format json"
    "request_sha256=$(sha256sum "${req}" | cut -d' ' -f1)")
  klt_compare_and_finish --points nominal --harness-csv "${HARNESS_CSV}"
  exit 0
fi

# Grid: 45 points, batch backend only.
klt_begin_record icmr
req="${SCRIPT_DIR}/icmr.request.json"
out="${SCRATCH}/icmr.sim.json"
ATTACH_ARGS=()
[[ -n "${ICMR_KLT_ATTACH:-}" ]] && ATTACH_ARGS=(--attach "${ICMR_KLT_ATTACH}")
klt_run_request "${req}" "${out}" "${SCRATCH}/icmr.stderr" --backend batch "${ATTACH_ARGS[@]}"
klt_validate_envelope "${out}" --points grid
klt_require_complete
klt_write_envelope "${out}"
KLT_OK_NOTE="within tolerance"
KLT_PROVENANCE_EXTRA=(
  "command=${KLT_CMD[*]} sim icmr.request.json --backend batch --format json"
  "request_sha256=$(sha256sum "${req}" | cut -d' ' -f1)"
  "remote=$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])).get("environment",{}).get("remote")))' "${out}")")
klt_compare_and_finish --points grid --harness-csv "${HARNESS_CSV}"

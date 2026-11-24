#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/cmrr-psrr/klt/run.sh
#
# The PSRR supply-gain bench (sim/cmrr-psrr/) expressed as a `klt sim` request
# (issue #99): runs psrr.request.json over the ratified 45-point grid, gates
# the envelope with compare.py's `validate`, and only then writes it,
# unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.sim.json
#
# followed by compare.py's join against the harness records,
#
#   records/<id>.compare.json
#
# One envelope: it carries the supply-to-output gain Avs only. PSRR also needs
# the same-point open-loop gain Av0, which compare.py joins offline from the
# committed open-loop `klt sim` AC envelope (sim/open-loop-ac/klt/records/
# *.ac.sim.json, measurement av0_db; PSRR_OPENLOOP_ENVELOPE), cross-checked
# against the open-loop harness CSV. Both operands are `klt sim` outputs, but the
# PSRR verdict in compare.json is still an offline verdict (a two-envelope
# join), not the tool's.
#
# Backend: the request declares `"backend": "batch"` (2am's EDA batch fleet):
# 45 AC corners is a grid, and grids do not run on shared dispatch hosts. If a
# batch submit fails, report the error; do NOT fall back to the full grid
# locally. PSRR_KLT_BACKEND=local is for a machine where running the grid
# locally is appropriate (it is passed to klt as --backend). KLT selects the
# klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt" to match a fleet runner.
#
# One request: psrr.request.json is the whole 45-point grid in ONE fleet job
# (submit_mode=single; operator ruling 2026-11-23, issue #444, confirmed on
# the current runner image -- see README.md). The five-job shard bridge this
# runner used to select via PSRR_KLT_MODE (the klt 0.5.0 runner era,
# 2AMLogic/2am#2193) is retired; shard.py and its records remain for
# historical replay of records/20261010-094256-469573d only.
#
# Exit status: 0 records written; 3 preflight failed (PDK/OSDI/ngspice/klt
# missing -- nothing written); 4 the run produced no gradable envelope
# (PDK/model identity drifted during the run, issue #209; klt error, errored/inconclusive corner, incomplete coverage -- nothing
# written to records/, the raw output is kept in a scratch dir named on
# stderr); 5 records written but compare.py found a point outside
# tolerance or an unexplained bound-verdict disagreement (see the
# compare.json it wrote -- reported, never hidden). The envelope's own
# pass/fail verdict does not change the exit status: a missed limit at some
# corner is a result, recorded as such.
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

HARNESS_ID="20260921-151815-707b34c"
HARNESS_CSV="sim/cmrr-psrr/records/${HARNESS_ID}.csv"
# Same-point Av0: the inn-AC-grounded open-loop record (issue #241). It
# supersedes 20260910-221601-22feaba (inn AC-floating), which the harness
# record above divided by, so compare.py reports the join as inconsistent and
# the tool values as outside the old harness record's tolerance: expected, and
# the point of the re-derivation. Override with PSRR_OPENLOOP_CSV.
OPENLOOP_CSV="${PSRR_OPENLOOP_CSV:-sim/open-loop-ac/records/20261015-103057-895d555.csv}"
# Av0 source of the PSRR join (issue #99): the open-loop klt sim AC envelope of
# the same grounded-inn bench; OPENLOOP_CSV above is then only the cross-check.
OPENLOOP_ENVELOPE="${PSRR_OPENLOOP_ENVELOPE:-sim/open-loop-ac/klt/records/20261016-161057-8caa272.ac.sim.json}"

klt_begin_record psrr
BACKEND_ARGS=()
[[ -n "${PSRR_KLT_BACKEND:-}" ]] && BACKEND_ARGS=(--backend "${PSRR_KLT_BACKEND}")

out="${SCRATCH}/psrr.sim.json"
# One 45-point request (submit_mode=single): needs a runner whose klt can
# carry per-section corner libraries, osdi_preload and staged includes (a
# bumped image, 2AMLogic/2am#2193) and a client whose version equals the
# runner's. Confirmed on the current runner image (issue #444; job id in
# README.md).
klt_run_request "${SCRIPT_DIR}/psrr.request.json" "${out}" "${SCRATCH}/psrr.stderr" "${BACKEND_ARGS[@]}"
klt_validate_envelope "${out}"
klt_require_complete
klt_write_envelope "${out}"

KLT_PROVENANCE_EXTRA=("backend_override=${PSRR_KLT_BACKEND:-none (request field: batch)}"
                      "submit_mode=single")
klt_compare_and_finish \
  --harness-csv "${HARNESS_CSV}" \
  --openloop-envelope "${OPENLOOP_ENVELOPE}" \
  --openloop-csv "${OPENLOOP_CSV}"

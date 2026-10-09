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
# followed by compare.py's join against the harness record of the same bench,
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

# shellcheck source=/dev/null
source "${SIM_DIR}/preflight.sh"
sg13g2_preflight_require_netlist

read -r -a KLT_CMD <<< "${KLT:-klt}"
if ! command -v "${KLT_CMD[0]}" >/dev/null 2>&1; then
  echo "run.sh: klt not found (${KLT_CMD[*]}) -- install klayout-tools or set KLT." >&2
  exit 3
fi
if ! KLT_VERSION="$("${KLT_CMD[@]}" --version 2>&1)"; then
  echo "run.sh: '${KLT_CMD[*]} --version' failed: ${KLT_VERSION}" >&2
  exit 3
fi

HARNESS_ID="20260910-221601-22feaba"
HARNESS_CSV="sim/open-loop-ac/records/${HARNESS_ID}.csv"
HARNESS_AC_DIR="sim/open-loop-ac/corners/${HARNESS_ID}"

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"
RECORDS_DIR="${SCRIPT_DIR}/records"
mkdir -p "${RECORDS_DIR}"
for kind in ac op; do
  if [[ -e "${RECORDS_DIR}/${RECORD_ID}.${kind}.sim.json" ]]; then
    echo "run.sh: ${RECORDS_DIR}/${RECORD_ID}.${kind}.sim.json already exists -- records are append-only." >&2
    exit 3
  fi
done

# klt reports netlist/model paths relative to the invoking repo; run from its root.
cd "${REPO_ROOT}"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/openloop-klt-${RECORD_ID}.XXXXXX")"
BACKEND_ARGS=()
[[ -n "${OPENLOOP_KLT_BACKEND:-}" ]] && BACKEND_ARGS=(--backend "${OPENLOOP_KLT_BACKEND}")

incomplete=0
for kind in ac op; do
  req="${SCRIPT_DIR}/openloop_${kind}.request.json"
  out="${SCRATCH}/${kind}.sim.json"
  err="${SCRATCH}/${kind}.stderr"
  echo "run.sh: ${KLT_CMD[*]} sim $(basename "${req}") ${BACKEND_ARGS[*]} --format json"
  rc=0
  "${KLT_CMD[@]}" sim "${req}" "${BACKEND_ARGS[@]}" --format json > "${out}" 2> "${err}" || rc=$?
  # klt sim: 0 = pass, 3 = ran and some limit failed -- both are complete,
  # gradable runs. 1/2 = did not run; 4 = errored/inconclusive/not_checked.
  if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]]; then
    echo "run.sh: klt sim (${kind}) exited ${rc} -- not a gradable envelope; nothing written to records/." >&2
    sed 's/^/run.sh:   /' "${err}" >&2 || true
    incomplete=1
    continue
  fi
  if ! python3 "${SCRIPT_DIR}/compare.py" validate --kind "${kind}" "${out}"; then
    echo "run.sh: ${kind} envelope failed validation -- nothing written to records/." >&2
    incomplete=1
  fi
done

if [[ "${incomplete}" -ne 0 ]]; then
  echo "run.sh: incomplete run; raw klt output kept in ${SCRATCH}" >&2
  exit 4
fi

for kind in ac op; do
  cp "${SCRATCH}/${kind}.sim.json" "${RECORDS_DIR}/${RECORD_ID}.${kind}.sim.json"
done
echo "run.sh: wrote records/${RECORD_ID}.ac.sim.json and records/${RECORD_ID}.op.sim.json"

cmp_rc=0
(
  cd "${REPO_ROOT}"
  python3 sim/open-loop-ac/klt/compare.py compare \
    --ac "sim/open-loop-ac/klt/records/${RECORD_ID}.ac.sim.json" \
    --op "sim/open-loop-ac/klt/records/${RECORD_ID}.op.sim.json" \
    --harness-csv "${HARNESS_CSV}" \
    --harness-ac-dir "${HARNESS_AC_DIR}" \
    --json-out "sim/open-loop-ac/klt/records/${RECORD_ID}.compare.json" \
    --provenance "record_id=${RECORD_ID}" \
    --provenance "repo_git_sha=${REPO_GIT_SHA}" \
    --provenance "klt_client_version=${KLT_VERSION}" \
    --provenance "host_ngspice=${NGSPICE_VERSION}" \
    --provenance "backend_override=${OPENLOOP_KLT_BACKEND:-none (request field: batch)}" \
    --provenance "pdk=${PDK} $(cat "${PDK_ROOT}/${PDK}/.fetched-version" 2>/dev/null || echo unknown-version)"
) || cmp_rc=$?

rm -rf "${SCRATCH}"
case "${cmp_rc}" in
  0) echo "run.sh: wrote records/${RECORD_ID}.compare.json (all points within tolerance)" ;;
  1) echo "run.sh: wrote records/${RECORD_ID}.compare.json -- OUT OF TOLERANCE points listed above; explain them in README.md before citing." >&2
     exit 5 ;;
  *) echo "run.sh: compare.py could not join the records (exit ${cmp_rc}); envelopes are written, comparison is not." >&2
     exit 5 ;;
esac

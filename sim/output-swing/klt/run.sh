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

read -r -a KLT_CMD <<< "${KLT:-klt}"
if ! command -v "${KLT_CMD[0]}" >/dev/null 2>&1; then
  echo "run.sh: klt not found (${KLT_CMD[*]}) -- install klayout-tools or set KLT." >&2
  exit 3
fi
if ! KLT_VERSION="$("${KLT_CMD[@]}" --version 2>&1)"; then
  echo "run.sh: '${KLT_CMD[*]} --version' failed: ${KLT_VERSION}" >&2
  exit 3
fi

HARNESS_ID="20260921-151759-707b34c"
HARNESS_CSV="sim/output-swing/records/${HARNESS_ID}.csv"

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"
RECORDS_DIR="${SCRIPT_DIR}/records"
mkdir -p "${RECORDS_DIR}"
if [[ -e "${RECORDS_DIR}/${RECORD_ID}.nominal.sim.json" ]]; then
  echo "run.sh: ${RECORDS_DIR}/${RECORD_ID}.nominal.sim.json already exists -- records are append-only." >&2
  exit 3
fi

# klt reports netlist/model paths relative to the invoking repo; run from its root.
cd "${REPO_ROOT}"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/swing-klt-${RECORD_ID}.XXXXXX")"
req="${SCRIPT_DIR}/swing.nominal.request.json"
out="${SCRATCH}/swing.nominal.sim.json"
err="${SCRATCH}/swing.nominal.stderr"
# Always --backend local: one operating point (see header).
echo "run.sh: ${KLT_CMD[*]} sim $(basename "${req}") --backend local --format json"
rc=0
"${KLT_CMD[@]}" sim "${req}" --backend local --format json > "${out}" 2> "${err}" || rc=$?
# klt sim: 0 = pass, 3 = ran and some limit failed -- both are complete,
# gradable runs. 1/2 = did not run; 4 = errored/inconclusive/not_checked.
incomplete=0
if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]]; then
  echo "run.sh: klt sim exited ${rc} -- not a gradable envelope; nothing written to records/." >&2
  sed 's/^/run.sh:   /' "${err}" >&2 || true
  incomplete=1
elif ! python3 "${SCRIPT_DIR}/compare.py" validate "${out}" --points nominal; then
  echo "run.sh: envelope failed validation -- nothing written to records/." >&2
  incomplete=1
fi

if [[ "${incomplete}" -ne 0 ]]; then
  echo "run.sh: incomplete run; raw klt output kept in ${SCRATCH}" >&2
  exit 4
fi

cp "${out}" "${RECORDS_DIR}/${RECORD_ID}.nominal.sim.json"
echo "run.sh: wrote records/${RECORD_ID}.nominal.sim.json"

cmp_rc=0
python3 sim/output-swing/klt/compare.py compare --points nominal \
  --envelope "sim/output-swing/klt/records/${RECORD_ID}.nominal.sim.json" \
  --harness-csv "${HARNESS_CSV}" \
  --json-out "sim/output-swing/klt/records/${RECORD_ID}.nominal.compare.json" \
  --provenance "record_id=${RECORD_ID}" \
  --provenance "repo_git_sha=${REPO_GIT_SHA}" \
  --provenance "klt_client_version=${KLT_VERSION}" \
  --provenance "host_ngspice=${NGSPICE_VERSION}" \
  --provenance "command=${KLT_CMD[*]} sim swing.nominal.request.json --backend local --format json" \
  --provenance "request_sha256=$(sha256sum "${req}" | cut -d' ' -f1)" \
  --provenance "pdk=${PDK} $(cat "${PDK_ROOT}/${PDK}/.fetched-version" 2>/dev/null || echo unknown-version)" \
  || cmp_rc=$?

rm -rf "${SCRATCH}"
case "${cmp_rc}" in
  0) echo "run.sh: wrote records/${RECORD_ID}.nominal.compare.json (within tolerance)" ;;
  1) echo "run.sh: wrote records/${RECORD_ID}.nominal.compare.json -- OUT OF TOLERANCE points listed above; explain them in README.md before citing." >&2
     exit 5 ;;
  *) echo "run.sh: compare.py could not join the records (exit ${cmp_rc}); the envelope is written, the comparison is not." >&2
     exit 5 ;;
esac

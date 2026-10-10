# shellcheck shell=bash
# Source me:  source "${SIM_DIR}/tools/klt_run_common.sh"
#
# Shared wrapper steps for every sim/<bench>/klt/run.sh (issue #151): the klt
# client check, record-id allocation (append-only), scratch dir, the
# `klt sim` invocation with its exit-code gate, the validate-before-write
# gate, writing the envelope into records/, and the offline compare with its
# exit-status mapping. Each bench's run.sh keeps only what is its own: header
# docs, request file, backend variable, harness record ids/paths, and any
# submit mode (cmrr-psrr's shard merge).
#
# The caller computes SCRIPT_DIR / SIM_DIR / REPO_ROOT, sources
# sim/preflight.sh and calls sg13g2_preflight_require_netlist BEFORE this
# file (sourcing preflight inside a function here would scope its variables
# locally), then calls, in order:
#
#   klt_check_client                       -> KLT_CMD, KLT_VERSION (exit 3)
#   klt_begin_record <scratch-prefix> [<record-suffix>]
#                                          -> REPO_GIT_SHA, RECORD_ID,
#                                             RECORDS_DIR, SCRATCH; cds to
#                                             REPO_ROOT (exit 3 if the record
#                                             id already exists)
#   klt_run_request <req> <out> <err> [<klt sim args>...]
#                                          -> runs `klt sim`; sets `incomplete`
#   klt_validate_envelope <out> [<validate args>...]
#   klt_require_complete                   -> exit 4 if `incomplete` is set
#   klt_write_envelope <out>               -> copies into records/
#   KLT_PROVENANCE_EXTRA=(key=value ...)   -> optional, placed before pdk=
#   klt_compare_and_finish <compare args>...
#                                          -> compare; exit 0 / 5
#
# <record-suffix> (default empty) goes between the record id and `.sim.json` /
# `.compare.json`, e.g. ".nominal". KLT_OK_NOTE overrides the exit-0 message
# parenthetical. Exit statuses are those documented in each run.sh header:
# 3 preflight, 4 no gradable envelope, 5 compare disagreed or could not join.

incomplete=0
RECORD_SUFFIX=""
KLT_OK_NOTE="all points within tolerance"
KLT_PROVENANCE_EXTRA=()

klt_check_client() {
  read -r -a KLT_CMD <<< "${KLT:-klt}"
  if ! command -v "${KLT_CMD[0]}" >/dev/null 2>&1; then
    echo "run.sh: klt not found (${KLT_CMD[*]}) -- install klayout-tools or set KLT." >&2
    exit 3
  fi
  if ! KLT_VERSION="$("${KLT_CMD[@]}" --version 2>&1)"; then
    echo "run.sh: '${KLT_CMD[*]} --version' failed: ${KLT_VERSION}" >&2
    exit 3
  fi
}

klt_begin_record() {
  local scratch_prefix="$1"
  RECORD_SUFFIX="${2:-}"
  REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"
  RECORDS_DIR="${SCRIPT_DIR}/records"
  mkdir -p "${RECORDS_DIR}"
  if [[ -e "${RECORDS_DIR}/${RECORD_ID}${RECORD_SUFFIX}.sim.json" ]]; then
    echo "run.sh: ${RECORDS_DIR}/${RECORD_ID}${RECORD_SUFFIX}.sim.json already exists -- records are append-only." >&2
    exit 3
  fi
  # klt reports netlist/model paths relative to the invoking repo; run from its root.
  cd "${REPO_ROOT}" || exit
  SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/${scratch_prefix}-klt-${RECORD_ID}.XXXXXX")"
}

klt_run_request() {
  local req="$1" out="$2" err="$3"
  shift 3
  echo "run.sh: ${KLT_CMD[*]} sim $(basename "${req}") $* --format json"
  local rc=0
  "${KLT_CMD[@]}" sim "${req}" "$@" --format json > "${out}" 2> "${err}" || rc=$?
  # klt sim: 0 = pass, 3 = ran and some limit failed -- both are complete,
  # gradable runs. 1/2 = did not run; 4 = errored/inconclusive/not_checked.
  if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]]; then
    echo "run.sh: klt sim exited ${rc} -- not a gradable envelope; nothing written to records/." >&2
    sed 's/^/run.sh:   /' "${err}" >&2 || true
    incomplete=1
  fi
}

klt_validate_envelope() {
  local out="$1"
  shift
  if [[ "${incomplete}" -eq 0 ]] && ! python3 "${SCRIPT_DIR}/compare.py" validate "${out}" "$@"; then
    echo "run.sh: envelope failed validation -- nothing written to records/." >&2
    incomplete=1
  fi
}

klt_require_complete() {
  if [[ "${incomplete}" -ne 0 ]]; then
    echo "run.sh: incomplete run; raw klt output kept in ${SCRATCH}" >&2
    exit 4
  fi
}

klt_write_envelope() {
  cp "$1" "${RECORDS_DIR}/${RECORD_ID}${RECORD_SUFFIX}.sim.json"
}

klt_compare_and_finish() {
  echo "run.sh: wrote records/${RECORD_ID}${RECORD_SUFFIX}.sim.json"
  local rel="${SCRIPT_DIR#"${REPO_ROOT}"/}"
  local rec="${RECORD_ID}${RECORD_SUFFIX}"
  local cmp_rc=0
  python3 "${rel}/compare.py" compare "$@" \
    --envelope "${rel}/records/${rec}.sim.json" \
    --json-out "${rel}/records/${rec}.compare.json" \
    --provenance "record_id=${RECORD_ID}" \
    --provenance "repo_git_sha=${REPO_GIT_SHA}" \
    --provenance "klt_client_version=${KLT_VERSION}" \
    --provenance "host_ngspice=${NGSPICE_VERSION}" \
    "${KLT_PROVENANCE_EXTRA[@]/#/--provenance=}" \
    --provenance "pdk=${PDK} $(cat "${PDK_ROOT}/${PDK}/.fetched-version" 2>/dev/null || echo unknown-version)" \
    || cmp_rc=$?

  rm -rf "${SCRATCH}"
  case "${cmp_rc}" in
    0) echo "run.sh: wrote records/${rec}.compare.json (${KLT_OK_NOTE})" ;;
    1) echo "run.sh: wrote records/${rec}.compare.json -- OUT OF TOLERANCE points listed above; explain them in README.md before citing." >&2
       exit 5 ;;
    *) echo "run.sh: compare.py could not join the records (exit ${cmp_rc}); the envelope is written, the comparison is not." >&2
       exit 5 ;;
  esac
}

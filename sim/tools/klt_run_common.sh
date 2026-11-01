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
#                                             id already exists). Also
#                                             captures the before-run PDK/
#                                             model identity into SCRATCH
#                                             via sg13g2_env_identity_begin
#                                             (issue #209; exit 3 if that
#                                             capture fails, before any
#                                             solver runs)
#   klt_run_request <req> <out> <err> [<klt sim args>...]
#                                          -> runs `klt sim`; sets `incomplete`
#   klt_validate_envelope <out> [<validate args>...]
#   klt_require_complete                   -> exit 4 if `incomplete` is set
#   klt_write_envelope <out> [<ext>]       -> rechecks the model identity
#                                             against the begin capture
#                                             (issue #209; drift exits 4
#                                             before anything is
#                                             published), then copies into
#                                             records/<id><suffix><ext>
#                                             (<ext> default .sim.json) (+
#                                             the <id>.env.json PDK identity
#                                             sidecar, #191)
#   KLT_PROVENANCE_EXTRA=(key=value ...)   -> optional, placed before pdk=
#   KLT_RECORD_EXTS=(.ac.sim.json ...)     -> optional, set before
#                                             klt_begin_record: the destination
#                                             extensions it refuses on
#                                             (default .sim.json .compare.json
#                                             .shards). A bench that publishes
#                                             several envelopes per record id
#                                             (open-loop-ac: .ac/.op) lists
#                                             them all, plus .compare.json.
#   KLT_COMPARE_ENVELOPE_ARGS=(--ac f ...) -> optional, used by
#                                             klt_compare_and_finish in place
#                                             of the default
#                                             `--envelope records/<id>.sim.json`
#   KLT_IDENTITY=0                         -> optional, set before
#                                             klt_begin_record: skip the PDK/
#                                             model identity capture and
#                                             sidecar (default 1). Only for a
#                                             bench whose run.sh does not
#                                             source sim/preflight.sh.
#   KLT_COMPARE_PY=compare_direct.py       -> optional, the comparator script in
#                                             the bench dir that validate and
#                                             compare call (default compare.py)
#   klt_compare_and_finish <compare args>...
#                                          -> compare; exit 0 / 5
#
# Reservation (issue #171). klt_begin_record claims the record destinations
# BEFORE klt is invoked, with the same primitive as sim/record-paths.sh
# (#140): an un-`-p` mkdir, which is atomic and fails on an existing path, so
# of any number of overlapping starts with the same <id><suffix> exactly one
# owns it. The reservation is the empty hidden directory
#
#   records/.reserve-<id><suffix>/
#
# (empty, so never tracked by git). The owner then refuses -- releasing the
# reservation and exiting 3, before any klt call -- if records/<id><suffix>
# .sim.json, .compare.json or .shards already exists, so a comparison-only
# leftover is protected too. Files are published by sg13g2_publish_noclobber
# (sim/record-paths.sh, sourced below; copy to a hidden temp in records/,
# then `ln`, which fails on an existing destination, then unlink the temp):
# a destination is never truncated or replaced. compare.py writes its report
# to scratch and it is published the same way. The model-identity sidecar is
# published through the same primitive by sg13g2_env_identity_finalize --
# only after a fresh capture matched the begin capture (#209), and before
# the sim envelope is published, so a drifted run publishes nothing.
#
# Cleanup/retention: an EXIT trap rmdirs the reservation on every normal exit
# (0, 3, 4, 5). A failed or incomplete run therefore leaves no reservation,
# only its raw output in ${SCRATCH} (exit 4); nothing was published, so a
# fresh invocation may reuse the id. Published evidence is never removed.
# Only a hard kill (SIGKILL, power loss) can strand the reservation; it is
# empty and harmless to other ids, and a later start with that same
# second+commit refuses naming it. Recover by confirming no run is live and
# `rmdir`-ing that directory (rmdir refuses a non-empty dir).
#
# <record-suffix> (default empty) goes between the record id and `.sim.json` /
# `.compare.json`, e.g. ".nominal". KLT_OK_NOTE overrides the exit-0 message
# parenthetical. Exit statuses are those documented in each run.sh header:
# 3 preflight (including a failed before-run identity capture, #209),
# 4 no gradable envelope or drifted model identity (nothing published),
# 5 compare disagreed or could not join.

incomplete=0
KLT_RESERVATION=""
RECORD_SUFFIX=""
KLT_OK_NOTE="all points within tolerance"
KLT_PROVENANCE_EXTRA=()
KLT_RECORD_EXTS=()
KLT_COMPARE_ENVELOPE_ARGS=()
KLT_IDENTITY=1
KLT_COMPARE_PY="${KLT_COMPARE_PY:-compare.py}"

# Publication primitive: sg13g2_publish_noclobber lives in
# sim/record-paths.sh -- the offline-sourceable split of sim/preflight.sh
# that every caller has already sourced before this file. Sourcing it again
# here (idempotent: only definitions), located relative to THIS file, keeps
# this file standalone for its offline tests. The identity lifecycle
# (sg13g2_env_identity_begin/_finalize, sim/env-identity.sh) is NOT sourced
# here: it comes from sim/preflight.sh, and offline tests provide it
# explicitly (stubbed, or the real file against a fake PDK install).
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/../record-paths.sh"

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
  local rec="${RECORD_ID}${RECORD_SUFFIX}"
  KLT_RESERVATION="${RECORDS_DIR}/.reserve-${rec}"
  if ! mkdir "${KLT_RESERVATION}" 2>/dev/null; then
    echo "run.sh: record ${rec} is reserved by another run (${KLT_RESERVATION}) -- nothing written." >&2
    echo "run.sh: if no run is live (killed earlier), rmdir that empty directory; otherwise re-run to mint a new id." >&2
    KLT_RESERVATION=""
    exit 3
  fi
  trap klt_release_reservation EXIT
  local taken=() f
  local exts=("${KLT_RECORD_EXTS[@]}")
  [[ "${#exts[@]}" -gt 0 ]] || exts=(.sim.json .compare.json .shards)
  for f in "${exts[@]/#/${RECORDS_DIR}/${rec}}"; do
    [[ -e "${f}" || -L "${f}" ]] && taken+=("${f}")
  done
  if [[ "${#taken[@]}" -gt 0 ]]; then
    echo "run.sh: refusing record ${rec} -- records are append-only; already exists:" >&2
    printf 'run.sh:   %s\n' "${taken[@]}" >&2
    exit 3
  fi
  # klt reports netlist/model paths relative to the invoking repo; run from its root.
  cd "${REPO_ROOT}" || exit
  SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/${scratch_prefix}-klt-${RECORD_ID}.XXXXXX")"
  # Run-time PDK/model identity, BEFORE any solver can run (issue #209):
  # captured into this run's private scratch; klt_write_envelope rechecks it
  # against a fresh capture before publishing anything. A capture failure is
  # a preflight failure (exit 3, reservation released by the EXIT trap): the
  # record would claim provenance it cannot vouch for, so nothing simulates.
  if [[ "${KLT_IDENTITY}" -ne 0 ]]; then
    sg13g2_env_identity_begin "${RECORD_ID}" "${SCRATCH}/${RECORD_ID}.env.json"
  fi
}

klt_release_reservation() {
  if [[ -n "${KLT_RESERVATION:-}" ]]; then
    rmdir "${KLT_RESERVATION}" 2>/dev/null || true
    KLT_RESERVATION=""
  fi
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
  if [[ "${incomplete}" -eq 0 ]] && ! python3 "${SCRIPT_DIR}/${KLT_COMPARE_PY}" validate "${out}" "$@"; then
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
  # Run-time PDK/model identity sidecar (issues #191, #209): one per record
  # id, bound to it. Recheck the begin capture against the live install
  # BEFORE the envelope is published, so a drifted run leaves no
  # finalized-looking records/<id>.sim.json (exit 4; the raw envelope and
  # begin capture stay in SCRATCH). A later suffixed envelope of the same
  # id reuses the first sidecar, which must equal this run's begin capture.
  if [[ "${KLT_IDENTITY}" -ne 0 ]]; then
    sg13g2_env_identity_finalize "${RECORD_ID}" "${SCRATCH}/${RECORD_ID}.env.json" \
      "${RECORDS_DIR}/${RECORD_ID}.env.json"
  fi
  local dest="${RECORD_ID}${RECORD_SUFFIX}${2:-.sim.json}"
  sg13g2_publish_noclobber "$1" "${RECORDS_DIR}/${dest}" || exit 4
  echo "run.sh: wrote records/${dest}"
}

klt_compare_and_finish() {
  local rel="${SCRIPT_DIR#"${REPO_ROOT}"/}"
  local rec="${RECORD_ID}${RECORD_SUFFIX}"
  local cmp_rc=0
  local env_args=("${KLT_COMPARE_ENVELOPE_ARGS[@]}")
  [[ "${#env_args[@]}" -gt 0 ]] || env_args=(--envelope "${rel}/records/${rec}.sim.json")
  python3 "${rel}/${KLT_COMPARE_PY}" compare "$@" \
    "${env_args[@]}" \
    --json-out "${SCRATCH}/${rec}.compare.json" \
    --provenance "record_id=${RECORD_ID}" \
    --provenance "repo_git_sha=${REPO_GIT_SHA}" \
    --provenance "klt_client_version=${KLT_VERSION}" \
    --provenance "host_ngspice=${NGSPICE_VERSION}" \
    "${KLT_PROVENANCE_EXTRA[@]/#/--provenance=}" \
    --provenance "pdk=${PDK} $(cat "${PDK_ROOT}/${PDK}/.fetched-version" 2>/dev/null || echo unknown-version)" \
    || cmp_rc=$?

  # compare.py wrote into scratch; publish without replacing (issue #171).
  if [[ -e "${SCRATCH}/${rec}.compare.json" ]] &&
     ! sg13g2_publish_noclobber "${SCRATCH}/${rec}.compare.json" "${RECORDS_DIR}/${rec}.compare.json"; then
    echo "run.sh: comparison not written; raw copy kept in ${SCRATCH}" >&2
    exit 5
  fi
  rm -rf "${SCRATCH}"
  case "${cmp_rc}" in
    0) echo "run.sh: wrote records/${rec}.compare.json (${KLT_OK_NOTE})" ;;
    1) echo "run.sh: wrote records/${rec}.compare.json -- OUT OF TOLERANCE points listed above; explain them in README.md before citing." >&2
       exit 5 ;;
    *) echo "run.sh: compare.py could not join the records (exit ${cmp_rc}); the envelope is written, the comparison is not." >&2
       exit 5 ;;
  esac
}

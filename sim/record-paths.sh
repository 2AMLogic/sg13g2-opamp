# Source me (via sim/preflight.sh, or directly from an offline test):
#   source "${SIM_DIR}/record-paths.sh"
#
# sg13g2_preflight_record_paths, split out of sim/preflight.sh so it can be
# exercised offline: unlike preflight.sh this file sources nothing, checks no
# PDK/OSDI/ngspice, and runs no simulator. It needs only SCRIPT_DIR and
# REPO_ROOT set by the caller (see sim/preflight.sh's own header).
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

_sg13g2_preflight_self="${_sg13g2_preflight_self:-$(basename "$0")}"

# sg13g2_preflight_record_paths [--prefix <p>] [--resumable]
#   Mint this run's record id, RESERVE it atomically (issue #140), and
#   derive the append-only output paths every sim/*/run_*.sh harness writes
#   into, then create the three output directories. Sets, for the caller to
#   use afterward:
#
#     REPO_GIT_SHA    short HEAD of this repo, or "unknown" outside a checkout
#     RECORD_ID       <prefix>YYYYmmdd-HHMMSS-<REPO_GIT_SHA> (UTC)
#     EXPERIMENT_DIR  the calling harness's own directory (= SCRIPT_DIR)
#     SNAPSHOTS_OUT   ${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}
#     CORNERS_OUT     ${EXPERIMENT_DIR}/corners/${RECORD_ID}
#     RECORDS_DIR     ${EXPERIMENT_DIR}/records
#     CSV_OUT         ${RECORDS_DIR}/${RECORD_ID}.csv
#     MD_OUT          ${RECORDS_DIR}/${RECORD_ID}.md
#     RECORD_RESUMED  1 when an EXISTING incomplete campaign is being
#                     continued (--resumable, RECORD_ID set, corners/<id>/
#                     already present), else 0. run_cmrr_mismatch_mc.sh keys
#                     its campaign-manifest check on it (issue #163).
#
#   Callers needing a further record-id-derived path (run_offset_mc.sh's
#   DRAWS_CSV) derive it locally from RECORDS_DIR/RECORD_ID after this call
#   rather than growing this function a knob per bench.
#
#   Two of the ten callers vary the RECORD_ID line, and both variants are
#   load-bearing rather than incidental:
#
#   --prefix <p>  prepend <p> to the minted id. run_offset_mc.sh passes
#                 "mc-" so its Monte Carlo records sort and read distinctly
#                 from the deterministic sweep's records in the same
#                 experiment directory.
#   --resumable   honor a RECORD_ID already set in the environment instead
#                 of minting a new one. run_cmrr_mismatch_mc.sh's resume
#                 feature (see its own header) replays the same RECORD_ID to
#                 continue a killed campaign; without this flag the resumed
#                 run would mint a fresh id and restart from zero. `date` is
#                 not evaluated on a resumed run.
#
#   Reservation (issue #140). The id is minted at one-second resolution, so
#   two starts in the same second at the same commit mint the SAME id, and
#   every writer downstream truncates (`> "${MD_OUT}"`) or replaces
#   (`mv "${CSV_OUT}.raw" "${CSV_OUT}"`) its outputs. The git-level gate
#   (sim/tools/check_append_only_evidence.py) only sees committed trees and
#   cannot recover an uncommitted record lost that way, so the id is claimed
#   here, before the caller writes anything:
#
#     * Fresh run (no --resumable, or --resumable with RECORD_ID unset):
#       `mkdir` WITHOUT -p of corners/<id>/ is the reservation. mkdir(2) is
#       atomic and fails on an existing path, so of any number of concurrent
#       starts with the same id exactly one owns it; there is no
#       check-then-create window. The owner then refuses (and releases the
#       still-empty corners/<id>/) if any other run-owned output of that id
#       already exists -- netlist-snapshots/<id>/, records/<id>, or any
#       records/<id>.* / <id>-* / <id>_* sibling (CSV, MD, pilot, draws,
#       plots) -- which covers a committed record whose corners/<id>/ is
#       absent from the checkout. Any refusal exits 3 before the caller has
#       written a byte, so the earlier record is left exactly as it was.
#
#     * Resumed run (--resumable with RECORD_ID set): continuing an
#       INCOMPLETE campaign is the documented use and is allowed; its
#       existing corners/, netlist-snapshots/ and pilot file are reused.
#       A record is FINALIZED once records/<id>.csv or records/<id>.md
#       exists -- run_cmrr_mismatch_mc.sh writes both only after every
#       control has passed, as its last act -- and resuming a finalized
#       record refuses, since the resumed run would rewrite both files.
#       Resuming an id with nothing on disk yet reserves it like a fresh run.
#
#   The id syntax itself is unchanged; a RECORD_ID taken from the
#   environment must be a single path component ([A-Za-z0-9._-], not
#   starting with "."), because it is spliced into output paths.
# shellcheck disable=SC2034  # CSV_OUT/MD_OUT/RECORD_RESUMED are consumed by callers after this returns
sg13g2_preflight_record_paths() {
  local prefix="" resumable=0 resume=0
  RECORD_RESUMED=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prefix)
        if [[ $# -lt 2 ]]; then
          echo "${_sg13g2_preflight_self}: sg13g2_preflight_record_paths: --prefix needs a value" >&2
          exit 3
        fi
        prefix="$2"
        shift 2
        ;;
      --resumable)
        resumable=1
        shift
        ;;
      *)
        echo "${_sg13g2_preflight_self}: sg13g2_preflight_record_paths: unknown argument '$1'" >&2
        exit 3
        ;;
    esac
  done

  REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if [[ "${resumable}" -eq 1 && -n "${RECORD_ID:-}" ]]; then
    resume=1
    if [[ ! "${RECORD_ID}" =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]]; then
      echo "${_sg13g2_preflight_self}: RECORD_ID='${RECORD_ID}' is not a valid record id (expected a single path component such as <prefix>YYYYmmdd-HHMMSS-<sha>)." >&2
      exit 3
    fi
  else
    RECORD_ID="${prefix}$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"
  fi

  EXPERIMENT_DIR="${SCRIPT_DIR}"
  SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
  CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
  RECORDS_DIR="${EXPERIMENT_DIR}/records"
  CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
  MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
  mkdir -p "${EXPERIMENT_DIR}/netlist-snapshots" "${EXPERIMENT_DIR}/corners" "${RECORDS_DIR}"

  if [[ "${resume}" -eq 1 ]]; then
    local final=() f
    for f in "${CSV_OUT}" "${MD_OUT}"; do
      [[ -e "${f}" ]] && final+=("${f}")
    done
    if [[ "${#final[@]}" -gt 0 ]]; then
      {
        echo "${_sg13g2_preflight_self}: refusing to resume record ${RECORD_ID}: it is already finalized:"
        printf '%s:   %s\n' "${_sg13g2_preflight_self}" "${final[@]}"
        echo "${_sg13g2_preflight_self}: a resumed run would rewrite that CSV/Markdown evidence, which is append-only."
        echo "${_sg13g2_preflight_self}: Unset RECORD_ID to start a new campaign under a freshly minted id."
      } >&2
      exit 3
    fi
    if mkdir "${CORNERS_OUT}" 2>/dev/null; then
      _sg13g2_record_refuse_if_taken
    else
      RECORD_RESUMED=1
      echo "${_sg13g2_preflight_self}: resuming incomplete record ${RECORD_ID}." >&2
    fi
    mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}"
    return 0
  fi

  if ! mkdir "${CORNERS_OUT}" 2>/dev/null; then
    _sg13g2_record_refuse "${CORNERS_OUT}"
  fi
  _sg13g2_record_refuse_if_taken
  if ! mkdir "${SNAPSHOTS_OUT}" 2>/dev/null; then
    rmdir "${CORNERS_OUT}" 2>/dev/null || true
    _sg13g2_record_refuse "${SNAPSHOTS_OUT}"
  fi
}

# _sg13g2_record_refuse_if_taken
#   Called only by the owner of a freshly created (hence empty) CORNERS_OUT:
#   refuse, releasing that reservation, if any other run-owned output of
#   RECORD_ID already exists.
_sg13g2_record_refuse_if_taken() {
  local taken=() p
  [[ -e "${SNAPSHOTS_OUT}" ]] && taken+=("${SNAPSHOTS_OUT}")
  [[ -e "${RECORDS_DIR}/${RECORD_ID}" ]] && taken+=("${RECORDS_DIR}/${RECORD_ID}")
  while IFS= read -r p; do
    [[ -n "${p}" ]] && taken+=("${p}")
  done < <(compgen -G "${RECORDS_DIR}/${RECORD_ID}[._-]*" || true)
  if [[ "${#taken[@]}" -gt 0 ]]; then
    rmdir "${CORNERS_OUT}" 2>/dev/null || true
    _sg13g2_record_refuse "${taken[@]}"
  fi
}

# _sg13g2_record_refuse <existing-path>...
_sg13g2_record_refuse() {
  {
    echo "${_sg13g2_preflight_self}: refusing to reuse record id ${RECORD_ID}: run-owned output already exists:"
    printf '%s:   %s\n' "${_sg13g2_preflight_self}" "$@"
    echo "${_sg13g2_preflight_self}: record ids are minted per second from UTC time and HEAD (${REPO_GIT_SHA}), so another"
    echo "${_sg13g2_preflight_self}: run started in the same second at the same commit, or this id's evidence already exists."
    echo "${_sg13g2_preflight_self}: Nothing was written; the existing record is append-only and was left untouched."
    echo "${_sg13g2_preflight_self}: Re-run to mint a new id (and do not run two copies of one bench at once)."
  } >&2
  exit 3
}

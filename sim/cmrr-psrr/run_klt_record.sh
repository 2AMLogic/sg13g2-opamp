#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/cmrr-psrr/run_klt_record.sh
#
# The batch CMRR/PSRR record the characterization report selects (issue #514).
# Runs the two direct decks on the batch fleet through their own runners
# (klt/run_direct.sh: PSRR, klt/run_cmrr_direct.sh: CMRR; each gates its
# envelope and waits for fleet capacity, and neither falls back to a local
# grid), then summarizes the newest pair of envelopes into
#
#   records/<cmrr-envelope-id>.csv and records/<cmrr-envelope-id>.md
#
# with klt/summarize_batch.py. Append-only: an existing record id is never
# overwritten. The characterization report re-derives every cell from the
# pinned envelopes (definition check cmrr_psrr_klt_audit); selecting the new
# record there is a deliberate edit of signoff/characterization/selection.json.
#
# Set SKIP_RUN=1 to summarize the already committed newest envelopes without
# submitting anything. To publish a revised summary of the same envelopes,
# set RECORD_ID to a fresh record ID; the default is the CMRR envelope ID.
#
# Exit status: 0 record written; 1 summarize failed (nothing written);
# 2 an envelope is missing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KLT_RECORDS="${SCRIPT_DIR}/klt/records"

if [[ "${SKIP_RUN:-0}" != "1" ]]; then
  "${SCRIPT_DIR}/klt/run_direct.sh"
  "${SCRIPT_DIR}/klt/run_cmrr_direct.sh"
fi

CMRR_ENV="$(find "${KLT_RECORDS}" -name '*.cmrr.sim.json' | sort | tail -1)"
PSRR_ENV="$(find "${KLT_RECORDS}" -name '*.direct.sim.json' | sort | tail -1)"
if [[ -z "${CMRR_ENV}" || -z "${PSRR_ENV}" ]]; then
  echo "error: no CMRR and/or PSRR direct envelope under ${KLT_RECORDS}" >&2
  exit 2
fi
RECORD_ID="${RECORD_ID:-$(basename "${CMRR_ENV}" .cmrr.sim.json)}"
if [[ ! "${RECORD_ID}" =~ ^[[:alnum:]_-][[:alnum:]_.-]*$ ]]; then
  echo "error: invalid record id: ${RECORD_ID}" >&2
  exit 1
fi
# shellcheck source=../record-paths.sh
source "${SCRIPT_DIR}/../record-paths.sh"
RECORDS_DIR="${SCRIPT_DIR}/records"
OUT="${RECORDS_DIR}/${RECORD_ID}"
RESERVATION="${RECORDS_DIR}/.reserve-${RECORD_ID}"
mkdir -p "${RECORDS_DIR}"
if ! sg13g2_exclusive_mkdir "${RESERVATION}"; then
  echo "error: record ${RECORD_ID} is reserved by another writer" >&2
  exit 1
fi
SCRATCH=""
cleanup() {
  if [[ -n "${SCRATCH}" ]]; then rm -rf -- "${SCRATCH}"; fi
  rmdir -- "${RESERVATION}"
}
trap cleanup EXIT
trap 'exit 1' INT TERM
if [[ -e "${OUT}.csv" || -L "${OUT}.csv" || -e "${OUT}.md" || -L "${OUT}.md" ]]; then
  echo "error: record ${RECORD_ID} already exists; records are append-only" >&2
  exit 1
fi
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/cmrr-psrr-record.XXXXXXXX")"
python3 "${SCRIPT_DIR}/klt/summarize_batch.py" "${CMRR_ENV}" "${PSRR_ENV}" "${SCRATCH}/record.csv" "${SCRATCH}/record.md"
# Finish the two short link operations (or their rollback) if interrupted.
trap '' INT TERM
sg13g2_publish_noclobber "${SCRATCH}/record.csv" "${OUT}.csv"
if ! sg13g2_publish_noclobber "${SCRATCH}/record.md" "${OUT}.md"; then
  unlink "${OUT}.csv"
  exit 1
fi
echo "wrote ${OUT}.csv and ${OUT}.md"

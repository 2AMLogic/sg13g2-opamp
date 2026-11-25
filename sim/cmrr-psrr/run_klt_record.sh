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
# submitting anything.
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
ID="$(basename "${CMRR_ENV}" .cmrr.sim.json)"
OUT="${SCRIPT_DIR}/records/${ID}"
if [[ -e "${OUT}.csv" || -e "${OUT}.md" ]]; then
  echo "error: record ${ID} already exists; records are append-only" >&2
  exit 1
fi
python3 "${SCRIPT_DIR}/klt/summarize_batch.py" "${CMRR_ENV}" "${PSRR_ENV}" "${OUT}.csv" "${OUT}.md"
echo "wrote ${OUT}.csv and ${OUT}.md"

#!/usr/bin/env bash
#
# Run the committed LVS compare and write its JSON report.
#
#   bash layout/opamp_core/run_lvs.sh          # regenerate layout/opamp_core/lvs_report.json
#
# Reads layout/opamp_core/lvs_request.json (paths inside it resolve relative
# to that file's own directory), runs `klt lvs --format json`, and writes the
# envelope to lvs_report.json next to it -- verdict intact, whatever it is:
# an honestly-recorded failing compare is a legitimate landing state for
# item 4 (#57), and this script never tunes anything to flip one.
#
# Requires `klt` (klayout-tools) with the curated sg13g2 deck and the pip
# `klayout` engine module -- see layout/README.md's "Regenerating" section.
# `klt lvs --check layout/opamp_core/lvs_report.json` re-verifies a written
# report against its own recorded input hashes, no klt layout run needed.
#
# Exit codes mirror `klt lvs` itself: 0 match, 3 mismatch, 4 inconclusive,
# 1 application error. The report is written for every verdict except 1.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT="${HERE}/lvs_report.json"
REQUEST="${HERE}/lvs_request.json"

if ! command -v klt >/dev/null 2>&1; then
  echo "klt not found -- install klayout-tools (see layout/README.md)" >&2
  exit 1
fi

# `klt lvs` prints its JSON envelope to stdout and its verdict to the exit
# code (0 match / 3 mismatch / 4 inconclusive); anything else is an
# application error that wrote no envelope.
set +e
klt lvs "${REQUEST}" --format json >"${REPORT}.tmp" 2>"${HERE}/.lvs_stderr.tmp"
rc=$?
set -e

if [ "${rc}" -eq 1 ] || [ ! -s "${REPORT}.tmp" ]; then
  echo "klt lvs failed (exit ${rc}):" >&2
  cat "${HERE}/.lvs_stderr.tmp" >&2
  rm -f "${REPORT}.tmp" "${HERE}/.lvs_stderr.tmp"
  exit 1
fi
mv "${REPORT}.tmp" "${REPORT}"
rm -f "${HERE}/.lvs_stderr.tmp"

status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "${REPORT}")"
echo "wrote ${REPORT}  status=${status}"
exit "${rc}"

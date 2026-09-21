#!/usr/bin/env bash
#
# Re-grade this block's T1 evidence and mint a new verdict of record.
#
#   bash signoff/regenerate.sh            # write signoff/reports/<record-id>.signoff.json
#   bash signoff/regenerate.sh --dry-run  # print the text report, write nothing
#
# Runs `klt signoff --manifest signoff/block-manifest.json` at the revision
# pinned in signoff/klt-pin.txt -- via `uvx`, in a throwaway environment, so
# whatever `klt` happens to be on PATH is irrelevant and the graded checklist
# is the pinned one. Needs network on first run (uvx caches afterwards); needs
# no PDK, no ngspice and no klayout install of its own.
#
# Records are append-only evidence, exactly like sim/*/records: this script
# adds a file, never rewrites one. The record id is
# <UTC yyyymmdd>-<UTC HHMMSS>-<short sha of HEAD>, so the record says which
# commit's artifacts it graded.
#
# Exit codes: 0 report written (or printed), 1 klt failed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

DRY_RUN=0
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: ${arg}" >&2; exit 1 ;;
  esac
done

PIN="$(grep -v '^[[:space:]]*#' signoff/klt-pin.txt | grep -v '^[[:space:]]*$' | head -1)"
if [ -z "${PIN}" ]; then
  echo "signoff/klt-pin.txt names no revision" >&2
  exit 1
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "uvx not found -- install uv (https://docs.astral.sh/uv/) or set" >&2
  echo "KLT_SIGNOFF_CMD and run signoff/check_signoff.py --run-klt directly" >&2
  exit 1
fi

KLT=(uvx --from "git+https://github.com/2AMLogic/klayout-tools@${PIN}" klt)

# `klt signoff --manifest` exits 3 when the block is not yet T1 (at least one
# item `unmet`) and 0 only at full T1 -- both mean "the report rendered".
# Anything else (1 unreadable manifest/tier doc, 2 usage) is a real failure.
# Treating 3 as failure here would make this script unrunnable on exactly the
# blocks it exists to measure.
run_klt() {
  local rc=0
  "${KLT[@]}" "$@" || rc=$?
  if [ "${rc}" -ne 0 ] && [ "${rc}" -ne 3 ]; then
    echo "klt signoff failed (exit ${rc})" >&2
    exit 1
  fi
}

echo "== klt signoff (klayout-tools @ ${PIN:0:12}) =="
run_klt signoff --manifest signoff/block-manifest.json

if [ "${DRY_RUN}" -eq 1 ]; then
  echo
  echo "--dry-run: no record written"
  exit 0
fi

RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-$(git rev-parse --short=7 HEAD)"
OUT="signoff/reports/${RECORD_ID}.signoff.json"
mkdir -p signoff/reports
if [ -e "${OUT}" ]; then
  echo "refusing to overwrite existing record ${OUT}" >&2
  exit 1
fi

run_klt signoff --manifest signoff/block-manifest.json --format json >"${OUT}"
echo
echo "wrote ${OUT}"
echo "next: python3 signoff/check_signoff.py --run-klt"

#!/usr/bin/env bash
#
# Run the committed ERC supply check (T1 item 11) and write its JSON report.
#
#   bash layout/opamp_core/run_erc.sh   # regenerate layout/opamp_core/erc_report.json
#
# Reads layout/opamp_core/erc_supply_spec.json -- the item-11 supply spec --
# and runs `klt erc` over the committed layout/opamp_core/opamp_core.gds,
# writing the envelope to erc_report.json next to it. Verdict intact,
# whatever it is: this script never tunes the spec to flip a finding. A
# supply that resolves to more than one island is a real finding and gets
# filed as its own issue.
#
# WHY THIS RUNS FROM THE REPO ROOT, and why that is not cosmetic: `klt erc`
# echoes the spec path it was given verbatim into the envelope's `spec`
# field, and `klt signoff` re-opens that path -- resolved against ITS own
# process cwd, which for signoff/regenerate.sh is the repo root. A run
# launched from layout/opamp_core/ would record `erc_supply_spec.json`, which
# signoff could not find, and item 11 would render `supply_spec_incomplete`
# for a purely clerical reason. So both paths below are repo-relative and the
# script cds to the repo root first.
#
# Requires `klt` (klayout-tools) with the curated sg13g2 deck and the pip
# `klayout` engine module -- see layout/README.md's "Regenerating" section.
#
# Exit codes: `klt erc`'s own exit code answers the ANTENNA question, and on
# SG13G2 there is no antenna-ratio limit table in klt at all, so a clean run
# here exits 4 (`status: "not_checked"`) however clean the design is. The
# structural verdict item 11 is about is `erc_status` in the payload. This
# script therefore gates on `erc_status` and reports it, exiting:
#   0  erc_status "clean"
#   3  erc_status anything else (violations, or clean_partial -- work skipped)
#   1  klt erc failed to run at all (no envelope written)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
cd "${REPO_ROOT}"

LAYOUT="layout/opamp_core/opamp_core.gds"
SPEC="layout/opamp_core/erc_supply_spec.json"
REPORT="${HERE}/erc_report.json"

if ! command -v klt >/dev/null 2>&1; then
  echo "klt not found -- install klayout-tools (see layout/README.md)" >&2
  exit 1
fi

# --deck sg13g2 does two things worth having and nothing this report depends
# on being wrong about: it carves the curated deck's own device bodies (the
# cap_cmim MiM top plate and its Vmim cut) out of any role they would
# otherwise be read as wire on, and it narrows
# erc_coverage.layers_in_stream_without_declaration to the deck's conducting
# layers, so that field means "an undeclared ROUTING level" rather than
# "an implant or a documentation layer".
#
# --pdk is deliberately NOT passed: klt ships an antenna-ratio limit table
# for sky130 only, and naming a PDK it has no table for is an error, not a
# check. Antenna is out of item 11's scope either way (klayout-tools#1994).
set +e
klt erc "${LAYOUT}" "${SPEC}" --deck sg13g2 --format json \
  >"${REPORT}.tmp" 2>"${HERE}/.erc_stderr.tmp"
rc=$?
set -e

if [ "${rc}" -eq 1 ] || [ "${rc}" -eq 2 ] || [ ! -s "${REPORT}.tmp" ]; then
  echo "klt erc failed (exit ${rc}):" >&2
  cat "${HERE}/.erc_stderr.tmp" >&2
  rm -f "${REPORT}.tmp" "${HERE}/.erc_stderr.tmp"
  exit 1
fi
mv "${REPORT}.tmp" "${REPORT}"
if [ -s "${HERE}/.erc_stderr.tmp" ]; then
  echo "klt erc stderr:" >&2
  cat "${HERE}/.erc_stderr.tmp" >&2
fi
rm -f "${HERE}/.erc_stderr.tmp"

read -r erc_status findings <<EOF
$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["erc_status"], d["erc_finding_count"])' "${REPORT}")
EOF

echo "wrote ${REPORT}  erc_status=${erc_status}  erc_findings=${findings}  (klt erc exit ${rc}, antenna: not_checked on sg13g2)"
[ "${erc_status}" = "clean" ] || exit 3
exit 0

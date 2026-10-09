#!/usr/bin/env bash
#
# Run the post-layout (T1 item 7) schematic-vs-extracted comparison and write
# its JSON report plus the extracted netlist.
#
#   bash layout/opamp_core/run_pex.sh             # regenerate pex_report.json
#   bash layout/opamp_core/run_pex.sh --dry-run   # print the klt pex command only
#
# Extracts parasitics from layout/opamp_core/opamp_core.gds (deck sg13g2,
# bound to this PDK's real device models via --pdk so the extracted netlist is
# simulatable), then measures BOTH the schematic
# (design/netlist/opamp_core.spice) and the extracted netlist with
# sim/post-layout/measure_openloop_ac.sh -- the committed open-loop AC bench
# over the ratified 45-point PVT grid -- and lets `klt pex` compute every
# delta[] row. Writes, next to this script:
#
#   pex_report.json     the klt pex envelope, verdict intact whatever it is
#   opamp_core_pex.spice  the extracted, parasitic-annotated netlist
#
# Verdict intact: this script never tunes anything to flip a result. Whether
# each extracted row still meets the ratified bound is a separate question,
# answered by `python3 sim/post-layout/check_bounds.py layout/opamp_core/pex_report.json`.
#
# GRID: the measure command expresses each leg's 45-point PVT grid as `klt sim`
# requests (AC + OP) and never launches ngspice itself, so on a shared dispatch
# worker (KLT_SIM_BACKEND=batch) the corners go to the Spot batch fleet. If the
# batch submit fails the run fails loudly (exit 1, no report); it does not fall
# back to a local grid.
#
# Needs `klt` >= the revision in signoff/klt-pin.txt (--measure-command), a
# reachable batch fleet whose runner matches the client klt version, and the
# ihp-sg13g2 PDK (found via $PDK_ROOT, else the sim/env.sh candidate list).
#
# Exit codes mirror `klt pex`: 0 pass, 3 fail, 4 error rows; 1 application
# error (no report written).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
cd "${REPO_ROOT}"

DRY_RUN=0
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n "2,35p" "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: ${arg}" >&2; exit 1 ;;
  esac
done

# shellcheck source=/dev/null
source sim/env.sh >&2   # PDK / PDK_ROOT resolution only

REPORT="layout/opamp_core/pex_report.json"
NETLIST="layout/opamp_core/opamp_core_pex.spice"
OUTDIR="$(mktemp -d)"
trap 'rm -rf "${OUTDIR}"' EXIT

cmd=(klt pex layout/opamp_core/opamp_core.gds
  --deck sg13g2 --pdk "${PDK}" --pdk-root "${PDK_ROOT}"
  --measure-command "bash sim/post-layout/measure_openloop_ac.sh"
  --reference-netlist design/netlist/opamp_core.spice
  --measure-timeout-s 7200
  -o "${NETLIST}" --outdir "${OUTDIR}" --format json)

if [ "${DRY_RUN}" -eq 1 ]; then
  printf '%q ' "${cmd[@]}"; echo
  exit 0
fi

command -v klt >/dev/null 2>&1 || { echo "klt not found -- install klayout-tools (see layout/README.md)" >&2; exit 1; }

set +e
"${cmd[@]}" >"${REPORT}.tmp" 2>"${HERE}/.pex_stderr.tmp"
rc=$?
set -e

if [ "${rc}" -eq 1 ] || [ ! -s "${REPORT}.tmp" ]; then
  echo "klt pex failed (exit ${rc}):" >&2
  cat "${HERE}/.pex_stderr.tmp" >&2
  rm -f "${REPORT}.tmp" "${HERE}/.pex_stderr.tmp"
  exit 1
fi
mv "${REPORT}.tmp" "${REPORT}"
rm -f "${HERE}/.pex_stderr.tmp"

status="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], len(d["delta"]))' "${REPORT}")"
echo "wrote ${REPORT} and ${NETLIST}  status/delta_rows=${status}"
exit "${rc}"

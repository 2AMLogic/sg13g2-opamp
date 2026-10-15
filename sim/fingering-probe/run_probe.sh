#!/usr/bin/env bash
#
# Issue #237 device-representation probe: does the schematic-vs-extracted
# delta of the first post-layout run come from parasitics, or from the
# schematic leg simulating lumped devices the layout does not draw?
#
#   bash sim/fingering-probe/run_probe.sh
#
# Writes five DUT netlists (build_probe_netlists.py: lumped, drawn, expanded,
# extracted_nopar, extracted) into netlist-snapshots/<record-id>/ and measures
# each with the committed post-layout open-loop AC bench
# (sim/post-layout/measure_openloop_ac.sh -- the same bench, requests and
# measurement definitions run_pex.sh hands `klt pex`) on a reduced grid:
# all five MOS process corners at 27 C, VDD = 1.20 V, CL = 2 pF [DR-1].
# Then summarize.py joins the five measurement documents into
# records/<record-id>.json and records/<record-id>.md.
#
# GRID: never run locally. Each variant is two `klt sim` requests whose
# corners go to the backend the requests declare ("batch": the Spot fleet;
# KLT_SIM_BACKEND=batch on the dispatch workers). The variants are measured
# one after another (no background jobs). A failed batch submit fails the
# run (exit 1) and leaves the partial corners/<record-id>/ for inspection; it
# never falls back to a local grid.
#
# Kept per variant under corners/<record-id>/<variant>/: the generated bench
# body and requests, both `klt sim` envelopes (environment.remote carries the
# batch job id), their stderr, and the measurement document.
#
# PROBE_SET=innac measures the four <variant>_innac netlists instead: the
# same DUTs with inn AC-grounded by 1 F (build_probe_netlists.inn_acgnd), a
# diagnostic of the bench's floating-inn loop break.
#
# Environment (optional): PROBE_POINTS overrides the grid (SG13G2_PEX_POINTS
# syntax, e.g. "mos_tt:27:1.20"; axes are crossed, see klt_measure.py).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
_sg13g2_preflight_self="$(basename "$0")"
# shellcheck source=/dev/null
source "${REPO_ROOT}/sim/record-paths.sh"

POINTS="${PROBE_POINTS:-mos_tt:27:1.20 mos_ss:27:1.20 mos_ff:27:1.20 mos_sf:27:1.20 mos_fs:27:1.20}"
PROBE_SET="${PROBE_SET:-base}"
case "${PROBE_SET}" in
  base)  VARIANTS=(lumped drawn expanded extracted_nopar extracted) ;;
  innac) VARIANTS=(lumped_innac drawn_innac extracted_nopar_innac extracted_innac) ;;
  *) echo "PROBE_SET must be base or innac (got '${PROBE_SET}')" >&2; exit 2 ;;
esac

sg13g2_preflight_record_paths
echo "record ${RECORD_ID}" >&2

python3 "${SCRIPT_DIR}/build_probe_netlists.py" "${SNAPSHOTS_OUT}" >&2

n_corners="$(python3 -I - "${POINTS}" <<'PY'
import sys
pts = [t.split(":") for t in sys.argv[1].split()]
print(len({p[0] for p in pts}) * len({p[1] for p in pts}) * len({p[2] for p in pts}))
PY
)"

for v in "${VARIANTS[@]}"; do
  art="${CORNERS_OUT}/${v}"
  mkdir -p "${art}"
  echo "measuring ${v} (${n_corners} corners via klt sim) ..." >&2
  rc=0
  SG13G2_PEX_POINTS="${POINTS}" KLT_MEASURE_EXPECTED_CORNERS="${n_corners}" \
    KLT_PEX_ARTIFACTS_DIR="${art}" KLT_PEX_SIDE="${v}" \
    bash "${REPO_ROOT}/sim/post-layout/measure_openloop_ac.sh" "${SNAPSHOTS_OUT}/${v}.spice" \
    > "${art}/measurement.json" 2> "${art}/measure.stderr" || rc=$?
  if [[ "${rc}" -ne 0 || ! -s "${art}/measurement.json" ]]; then
    echo "${v}: measurement failed (exit ${rc}); see ${art}/measure.stderr" >&2
    sed 's/^/  /' "${art}/measure.stderr" >&2 || true
    exit 1
  fi
done

PROBE_SET="${PROBE_SET}" python3 -I "${SCRIPT_DIR}/summarize.py" "${RECORD_ID}" "${POINTS}" \
  "${CORNERS_OUT}" "${RECORDS_DIR}/${RECORD_ID}.json" "${MD_OUT}"
echo "wrote ${RECORDS_DIR}/${RECORD_ID}.json and ${MD_OUT}" >&2

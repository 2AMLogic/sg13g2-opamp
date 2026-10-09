#!/usr/bin/env bash
#
# `klt pex --measure-command` target: the open-loop AC bench (T1 item 7).
#
#   sim/post-layout/measure_openloop_ac.sh <dut-netlist>
#
# Measures the given device-under-test netlist with the committed open-loop AC
# bench (sim/post-layout/klt/, the `klt sim` form of
# sim/open-loop-ac/testbench/tb_openloop_ac.spice.tmpl) over the ratified
# 45-point grid (cornerMOSlv.lib mos_tt/ss/ff/sf/fs x -40/27/125 C x
# 1.08/1.20/1.32 V, CL = 2 pF [DR-1]) and prints, on stdout and nowhere else,
# the measurement document `klt pex` expects:
#
#   {"corners": [{"corner_id": "mos_tt/1.20V/27C",
#                 "measurements": [{"name": "av0_db", "value": ..}, ...]}]}
#
# Four rows per corner -- av0_db, gbw_hz, pm_deg, iq_a (total Vdd current,
# incl. the external 10 uA ibias reference) -- i.e. the spec/target-spec.md
# Sec 2 rows DC gain, GBW, phase margin and quiescent power. klt pex computes
# every schematic-vs-extracted delta itself; the bounds are checked by
# sim/post-layout/check_bounds.py.
#
# The grid is NOT looped here. It is two `klt sim` requests (an AC analysis and
# an OP analysis -- klt sim runs one analysis per corner) whose corners go to
# whatever backend the request declares ("batch": the Spot fleet). This script
# never launches ngspice itself, so there is no local-grid path to refuse.
# Override with KLT_PEX_SIM_BACKEND=local|local-parallel on a box where a local
# grid is appropriate; SG13G2_PEX_POINTS="mos_tt:27:1.20" restricts the grid to
# one point (a debug probe). KLT selects the klt executable (default `klt`).
#
# Loud, never partial: any corner that is not graded pass/fail, a missing
# value, a corner-count mismatch, a failed batch submit, or a non-regulating DC
# point exits 1 with NO document on stdout -- an unmeasured leg must not read as
# a measured one. Bench definition (and its known GBW-interpolation bias):
# sim/post-layout/README.md.
#
# Environment (all optional): KLT_PEX_ARTIFACTS_DIR (kept requests/envelopes;
# default a temp dir), KLT_PEX_SIDE (label only).

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <dut-netlist>" >&2
  exit 2
fi
NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# PDK / PDK_ROOT resolution only (klt sim resolves the models through them).
# shellcheck source=/dev/null
source "${REPO_ROOT}/sim/env.sh" >&2

read -r -a KLT_CMD <<< "${KLT:-klt}"
command -v "${KLT_CMD[0]}" >/dev/null 2>&1 || { echo "${NAME}: klt not found (${KLT_CMD[*]})" >&2; exit 1; }

ART="${KLT_PEX_ARTIFACTS_DIR:-$(mktemp -d)}"
mkdir -p "${ART}"
python3 -I "${SCRIPT_DIR}/klt_measure.py" build "$1" "${ART}"

# klt resolves repo-relative netlist/model paths from the invoking directory.
cd "${REPO_ROOT}"
for kind in ac op; do
  rc=0
  "${KLT_CMD[@]}" sim "${ART}/openloop_${kind}.request.json" --format json \
    > "${ART}/${kind}.envelope.json" 2> "${ART}/${kind}.stderr" || rc=$?
  # klt sim: 0 = pass, 3 = ran and a limit failed -- both gradable. Anything
  # else did not produce a gradable envelope.
  if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]]; then
    echo "${NAME}: klt sim (${kind}) exited ${rc} -- no measurement document." >&2
    sed 's/^/  stderr: /' "${ART}/${kind}.stderr" >&2 || true
    python3 -I - "${ART}/${kind}.envelope.json" >&2 <<'PY' || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit()
if "error" in d:
    print("  error:", d["error"].get("message"))
for c in (d.get("corners") or [])[:1]:
    for x in c.get("diagnostics", []):
        print("  diagnostic:", x.get("code"), x.get("runner_code", ""), "-", x.get("message", "")[:400])
PY
    exit 1
  fi
done

python3 -I "${SCRIPT_DIR}/klt_measure.py" convert "${ART}/ac.envelope.json" "${ART}/op.envelope.json"

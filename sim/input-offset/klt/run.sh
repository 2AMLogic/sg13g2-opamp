#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/input-offset/klt/run.sh
#
# The input-offset bench (sim/input-offset/, systematic half) expressed as
# `klt sim` requests (issue #97; closed-loop cross-check added by issue #504):
# runs BOTH requests over the ratified 45-point grid --
#
#   offset.request.json      the open-loop null sweep (dc Vid 0.004 0.034 4u)
#   offset_cl.request.json   the closed-loop cross-check (op, Lbreak 1e18 H)
#
# -- gates each envelope with compare.py's `validate --kind`, and only then
# writes the pair, unmodified, as
#
#   klt/records/<UTC YYYYmmdd-HHMMSS>-<short sha>.sim.json
#   klt/records/<UTC YYYYmmdd-HHMMSS>-<short sha>.cl.sim.json
#
# then derives the batch record from the two envelopes joined with the
# selected same-DUT open-loop-ac record's per-corner Av0 (offset_post.py,
# the same module signoff/characterization's offset_klt_audit re-applies),
# publishing
#
#   records/<id>.csv, records/<id>.md        (sim/input-offset/records/)
#   netlist-snapshots/<id>/opamp_core.spice
#
# followed by compare.py's join of both envelopes against the harness record
# of the same bench,
#
#   klt/records/<id>.compare.json
#
# Two envelopes, not one: `klt sim` runs one analysis per corner, and the two
# methods need different topologies (the null sweep drives inn from a
# differential B-source; the closed-loop method ties inn to out through
# Lbreak) -- the same shape as sim/open-loop-ac/klt/run.sh.
#
# The harness CSV stays what it always was: a same-DUT regression control for
# compare.py's join. It is NOT a gate for a new DUT -- after a netlist change
# the join disagrees (exit 5, reported never hidden) while the batch record
# and its envelopes remain the re-mintable evidence (issue #497).
#
# Backend: the requests declare `"backend": "batch"` (2am's EDA batch fleet):
# 90 corners is a grid, and grids do not run on shared dispatch hosts. Set
# OFFSET_KLT_BACKEND=local (or local-parallel) on a machine where running the
# grid locally is appropriate; it is passed to klt as --backend. KLT selects
# the klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt" to match a fleet runner.
#
# Av0 join: AV0_RECORD_CSV (default: the open-loop record selection.json
# selects today, sim/open-loop-ac/records/20261015-103057-895d555.csv) -- the
# closed-loop referral needs that experiment's per-corner av0_db column, read
# with offset_post.read_av0_csv's corner-binding rules.
#
# Exit status: 0 records written; 3 preflight failed (PDK/OSDI/ngspice/klt
# missing -- nothing written); 4 a run produced no gradable envelope
# (PDK/model identity drifted during the run, issue #209; klt error, errored/inconclusive corner, incomplete coverage -- nothing
# written to records/, the raw output is kept in a scratch dir named on
# stderr); 5 records written but compare.py found a point outside
# tolerance or an unexplained bound-verdict disagreement (see the
# compare.json it wrote -- reported, never hidden). The envelope's own
# pass/fail verdict does not change the exit status: a ratified bound missed
# at some corner is a result, recorded as such.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# SIM_DIR is sim/ (where env.sh/preflight.sh/record-paths.sh live); the BENCH
# dir -- whose records/ and netlist-snapshots/ hold this bench's append-only
# evidence -- is one level above this klt/ script dir.
SIM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BENCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# The batch backend (the default) simulates on the fleet, so the host needs
# neither the pinned ngspice nor built OSDI models -- only the PDK path klt
# resolves model references through (what sim/env.sh finds). The full local
# preflight (PDK + OSDI + ngspice) applies only when the grid is deliberately
# sent to a local backend.
case "${OFFSET_KLT_BACKEND:-batch}" in
  batch)
    # shellcheck source=/dev/null
    source "${SIM_DIR}/env.sh" >&2
    NGSPICE_VERSION="n/a (simulated on the batch fleet)"
    ;;
  *)
    # shellcheck source=/dev/null
    source "${SIM_DIR}/preflight.sh"
    sg13g2_preflight_require_netlist
    ;;
esac

# shellcheck source=/dev/null
source "${SIM_DIR}/tools/klt_run_common.sh"
# Set AFTER sourcing klt_run_common.sh (its defaults reset the flag): with the
# batch backend the local host is not the machine that ran the simulation, so
# there is no local PDK/model identity to capture (#274, as open-loop-ac).
KLT_IDENTITY=0

klt_check_client

HARNESS_ID="20260918-203858-90844d2"
HARNESS_CSV="sim/input-offset/records/${HARNESS_ID}.csv"

# The Av0 join source: the open-loop record the characterization selection
# pins (its netlist snapshot must be the same DUT this bench simulates; the
# signoff-side audit re-checks that binding on the selection's own pins).
AV0_DEFAULT_ID="20261015-103057-895d555"
if [[ -z "${AV0_RECORD_CSV:-}" ]]; then
  AV0_RECORD_CSV="sim/open-loop-ac/records/${AV0_DEFAULT_ID}.csv"
fi
if [[ ! -s "${REPO_ROOT}/${AV0_RECORD_CSV}" ]]; then
  echo "run.sh: Av0 join record ${AV0_RECORD_CSV} not found -- set AV0_RECORD_CSV to the selected same-DUT open-loop-ac record." >&2
  exit 3
fi

# Two envelopes, one derived record and one comparison share one record id:
# reserve every destination up front (issue #274). The reservation covers the
# klt/records/ extensions; the derived CSV/MD and the DUT snapshot under
# sim/input-offset/ are published no-clobber below.
KLT_RECORD_EXTS=(.sim.json .cl.sim.json .compare.json)
klt_begin_record offset
BACKEND_ARGS=()
[[ -n "${OFFSET_KLT_BACKEND:-}" ]] && BACKEND_ARGS=(--backend "${OFFSET_KLT_BACKEND}")

for kind in null cl; do
  suffix=""
  if [[ "${kind}" == "cl" ]]; then suffix="_cl"; fi
  req="${SCRIPT_DIR}/offset${suffix}.request.json"
  klt_run_request "${req}" "${SCRATCH}/${kind}.sim.json" "${SCRATCH}/${kind}.stderr" "${BACKEND_ARGS[@]}"
  klt_validate_envelope "${SCRATCH}/${kind}.sim.json" --kind "${kind}"
done
klt_require_complete

# The DUT snapshot the derived record and the signoff selection pin: the
# committed netlist this run simulated (the envelopes' netlist_closure hash
# it; klt_write_envelope publishes the envelopes only after this copy).
SNAPSHOT_REL="sim/input-offset/netlist-snapshots/${RECORD_ID}/opamp_core.spice"
mkdir -p "${REPO_ROOT}/$(dirname "${SNAPSHOT_REL}")"
if [[ -e "${REPO_ROOT}/${SNAPSHOT_REL}" ]]; then
  echo "run.sh: refusing to overwrite ${SNAPSHOT_REL} -- records are append-only." >&2
  exit 3
fi
cp "${REPO_ROOT}/design/netlist/opamp_core.spice" "${REPO_ROOT}/${SNAPSHOT_REL}"

klt_write_envelope "${SCRATCH}/null.sim.json" ".sim.json"
klt_write_envelope "${SCRATCH}/cl.sim.json" ".cl.sim.json"

# The derived record: every cell recomputed offline from the two envelopes +
# the Av0 join (offset_post.py), staged in scratch, published no-clobber.
python3 "${SCRIPT_DIR}/offset_post.py" write-record \
  --rid "${RECORD_ID}" \
  --null "${REPO_ROOT}/sim/input-offset/klt/records/${RECORD_ID}.sim.json" \
  --cl "${REPO_ROOT}/sim/input-offset/klt/records/${RECORD_ID}.cl.sim.json" \
  --av0-csv "${AV0_RECORD_CSV}" \
  --snapshot "${SNAPSHOT_REL}" \
  --out-csv "${SCRATCH}/${RECORD_ID}.csv" \
  --out-md "${SCRATCH}/${RECORD_ID}.md"
for f in "${RECORD_ID}.csv" "${RECORD_ID}.md"; do
  sg13g2_publish_noclobber "${SCRATCH}/${f}" "${BENCH_DIR}/records/${f}" || exit 4
  echo "run.sh: wrote records/${f}"
done

rel="${SCRIPT_DIR#"${REPO_ROOT}"/}"
rec="${RECORD_ID}${RECORD_SUFFIX}"
KLT_COMPARE_ENVELOPE_ARGS=(
  --envelope "${rel}/records/${rec}.sim.json"
  --cl "${rel}/records/${rec}.cl.sim.json"
  --av0-csv "${AV0_RECORD_CSV}"
)
KLT_PROVENANCE_EXTRA=(
  "av0_join_record=$(basename "${AV0_RECORD_CSV}" .csv)"
  "backend_override=${OFFSET_KLT_BACKEND:-none (request field: batch)}"
)
klt_compare_and_finish \
  --harness-csv "${HARNESS_CSV}"

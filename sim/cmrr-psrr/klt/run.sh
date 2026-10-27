#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/cmrr-psrr/klt/run.sh
#
# The PSRR supply-gain bench (sim/cmrr-psrr/) expressed as a `klt sim` request
# (issue #99): runs psrr.request.json over the ratified 45-point grid, gates
# the envelope with compare.py's `validate`, and only then writes it,
# unmodified, as
#
#   records/<UTC YYYYmmdd-HHMMSS>-<short sha>.sim.json
#
# followed by compare.py's join against the harness records,
#
#   records/<id>.compare.json
#
# One envelope: it carries the supply-to-output gain Avs only. PSRR also needs
# the same-point open-loop gain Av0, which compare.py joins offline from the
# committed open-loop `klt sim` AC envelope (sim/open-loop-ac/klt/records/
# *.ac.sim.json, measurement av0_db; PSRR_OPENLOOP_ENVELOPE), cross-checked
# against the open-loop harness CSV. Both operands are `klt sim` outputs, but the
# PSRR verdict in compare.json is still an offline verdict (a two-envelope
# join), not the tool's.
#
# Backend: the request declares `"backend": "batch"` (2am's EDA batch fleet):
# 45 AC corners is a grid, and grids do not run on shared dispatch hosts. If a
# batch submit fails, report the error; do NOT fall back to the full grid
# locally. PSRR_KLT_BACKEND=local is for a machine where running the grid
# locally is appropriate (it is passed to klt as --backend). KLT selects the
# klt executable (default: `klt` on PATH), e.g.
# KLT="uvx --from klayout-tools==X.Y.Z klt" to match a fleet runner.
#
# PSRR_KLT_MODE selects how the grid is submitted. `shard` (default): five
# per-process requests built by shard.py, each one fleet job, merged by
# shard.py's validation-gated merge -- the bridge for the fleet runner image
# that still pinned klt 0.5.0 (2AMLogic/2am#2193). The runner now carries
# klt 0.8.0, so use KLT="uvx --from klayout-tools==0.8.0 klt" (0.5.0 has no
# batch backend). `single`: the one 45-point psrr.request.json,
# for a runner image new enough to carry it.
#
# Exit status: 0 records written; 3 preflight failed (PDK/OSDI/ngspice/klt
# missing -- nothing written); 4 the run produced no gradable envelope
# (PDK/model identity drifted during the run, issue #209; klt error, errored/inconclusive corner, incomplete coverage -- nothing
# written to records/, the raw output is kept in a scratch dir named on
# stderr); 5 records written but compare.py found a point outside
# tolerance or an unexplained bound-verdict disagreement (see the
# compare.json it wrote -- reported, never hidden). The envelope's own
# pass/fail verdict does not change the exit status: a missed limit at some
# corner is a result, recorded as such.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/preflight.sh"
sg13g2_preflight_require_netlist
# shellcheck source=/dev/null
source "${SIM_DIR}/tools/klt_run_common.sh"

klt_check_client

HARNESS_ID="20260921-151815-707b34c"
HARNESS_CSV="sim/cmrr-psrr/records/${HARNESS_ID}.csv"
# Same-point Av0: the inn-AC-grounded open-loop record (issue #241). It
# supersedes 20260910-221601-22feaba (inn AC-floating), which the harness
# record above divided by, so compare.py reports the join as inconsistent and
# the tool values as outside the old harness record's tolerance: expected, and
# the point of the re-derivation. Override with PSRR_OPENLOOP_CSV.
OPENLOOP_CSV="${PSRR_OPENLOOP_CSV:-sim/open-loop-ac/records/20261015-103057-895d555.csv}"
# Av0 source of the PSRR join (issue #99): the open-loop klt sim AC envelope of
# the same grounded-inn bench; OPENLOOP_CSV above is then only the cross-check.
OPENLOOP_ENVELOPE="${PSRR_OPENLOOP_ENVELOPE:-sim/open-loop-ac/klt/records/20261016-161057-8caa272.ac.sim.json}"

klt_begin_record psrr
BACKEND_ARGS=()
[[ -n "${PSRR_KLT_BACKEND:-}" ]] && BACKEND_ARGS=(--backend "${PSRR_KLT_BACKEND}")

out="${SCRATCH}/psrr.sim.json"
MODE="${PSRR_KLT_MODE:-shard}"
case "${MODE}" in
  single)
    # One 45-point request: needs a runner whose klt can carry per-section
    # corner libraries, osdi_preload and staged includes (a bumped image,
    # 2AMLogic/2am#2193) and a client whose version equals the runner's.
    klt_run_request "${SCRIPT_DIR}/psrr.request.json" "${out}" "${SCRATCH}/psrr.stderr" "${BACKEND_ARGS[@]}"
    ;;
  shard)
    # Five per-process requests (shard.py), the bridge written for a fleet runner
    # image that pinned klt 0.5.0. Each is one fleet job; the submitting client
    # must carry the batch backend and be accepted by the runner (the runner
    # now carries 0.8.0: KLT="uvx --from klayout-tools==0.8.0 klt"). Never local: the shards ARE
    # the grid.
    if [[ "${PSRR_KLT_BACKEND:-batch}" != "batch" ]]; then
      echo "run.sh: shard mode submits to the batch fleet only; PSRR_KLT_BACKEND=${PSRR_KLT_BACKEND} refused." >&2
      exit 3
    fi
    python3 "${SCRIPT_DIR}/shard.py" gen --workdir "${SCRATCH}"
    merge_args=()
    for proc in mos_tt mos_ss mos_ff mos_sf mos_fs; do
      rep="${SCRATCH}/report-${proc}.json"
      # Resume: reuse a prior shard report only if its request is byte-identical
      # to the one just generated and the report is a complete gradable run.
      if [[ -n "${PSRR_KLT_RESUME_DIR:-}" && -s "${PSRR_KLT_RESUME_DIR}/report-${proc}.json" ]] \
         && cmp -s "${PSRR_KLT_RESUME_DIR}/request-${proc}.json" "${SCRATCH}/request-${proc}.json" \
         && python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if r.get("status") in ("pass","fail") and r.get("corner_count")==9 else 1)' "${PSRR_KLT_RESUME_DIR}/report-${proc}.json"; then
        echo "run.sh: shard ${proc}: reusing ${PSRR_KLT_RESUME_DIR}/report-${proc}.json (request byte-identical)"
        cp "${PSRR_KLT_RESUME_DIR}/report-${proc}.json" "${rep}"
        merge_args+=("${proc}=${rep}")
        continue
      fi
      # A capacity refusal ("no capacity in any of the 30 pools", or the fleet-wide
      # BATCH_MAX_CONCURRENT_INSTANCES cap) is final per
      # klt submit (0.6.0 has no capacity wait): re-submit a bounded number of
      # times, sleeping between. Any other failure stops at once. Never local.
      tries="${PSRR_KLT_SUBMIT_TRIES:-3}"
      attempt=1
      while :; do
        echo "run.sh: ${KLT_CMD[*]} sim request-${proc}.json --backend batch --format json (attempt ${attempt}/${tries})"
        rc=0
        ( cd "${SCRATCH}" && "${KLT_CMD[@]}" sim "request-${proc}.json" --backend batch --format json \
            > "report-${proc}.json" 2> "stderr-${proc}.txt" ) || rc=$?
        if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]] \
           && grep -q -E "no capacity in any|exceeds BATCH_MAX_CONCURRENT_INSTANCES" "${SCRATCH}/stderr-${proc}.txt" "${rep}" 2>/dev/null \
           && [[ "${attempt}" -lt "${tries}" ]]; then
          attempt=$((attempt + 1))
          sleep "${PSRR_KLT_RETRY_SLEEP_S:-120}"
          continue
        fi
        break
      done
      if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]]; then
        echo "run.sh: shard ${proc}: klt sim exited ${rc} -- not a gradable report; nothing written to records/." >&2
        { head -c 4000 "${SCRATCH}/stderr-${proc}.txt"; head -c 4000 "${rep}"; } | sed 's/^/run.sh:   /' >&2 || true
        incomplete=1
        break
      fi
      merge_args+=("${proc}=${rep}")
    done
    if [[ "${incomplete}" -eq 0 ]]; then
      python3 "${SCRIPT_DIR}/shard.py" merge --manifest "${SCRATCH}/shards.json" -o "${out}" "${merge_args[@]}" || incomplete=1
    fi
    ;;
  *)
    echo "run.sh: PSRR_KLT_MODE must be shard or single, got '${MODE}'." >&2
    exit 3
    ;;
esac
klt_validate_envelope "${out}"
klt_require_complete
klt_write_envelope "${out}"
if [[ "${MODE}" == "shard" ]]; then
  # Keep the raw per-shard evidence the merged envelope was built from.
  SHARD_DIR="${RECORDS_DIR}/${RECORD_ID}.shards"
  mkdir -p "${SHARD_DIR}"
  cp "${SCRATCH}"/shards.json "${SCRATCH}"/request-mos_*.json "${SCRATCH}"/body-mos_*.spice \
     "${SCRATCH}"/report-mos_*.json "${SHARD_DIR}/"
fi

KLT_PROVENANCE_EXTRA=("backend_override=${PSRR_KLT_BACKEND:-none (request field: batch)}"
                      "submit_mode=${MODE}")
klt_compare_and_finish \
  --harness-csv "${HARNESS_CSV}" \
  --openloop-envelope "${OPENLOOP_ENVELOPE}" \
  --openloop-csv "${OPENLOOP_CSV}"

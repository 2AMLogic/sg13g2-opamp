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
# committed open-loop HARNESS record (not a `klt sim` envelope), so the PSRR
# verdict in compare.json is an offline verdict, not the tool's.
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
# that still pins klt 0.5.0 (2AMLogic/2am#2193). Use
# KLT="uvx --from klayout-tools==0.6.0 klt" (0.5.0 has no batch backend; 0.7.0
# is refused by the runner). `single`: the one 45-point psrr.request.json,
# for a runner image new enough to carry it.
#
# Exit status: 0 records written; 3 preflight failed (PDK/OSDI/ngspice/klt
# missing -- nothing written); 4 the run produced no gradable envelope
# (klt error, errored/inconclusive corner, incomplete coverage -- nothing
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

read -r -a KLT_CMD <<< "${KLT:-klt}"
if ! command -v "${KLT_CMD[0]}" >/dev/null 2>&1; then
  echo "run.sh: klt not found (${KLT_CMD[*]}) -- install klayout-tools or set KLT." >&2
  exit 3
fi
if ! KLT_VERSION="$("${KLT_CMD[@]}" --version 2>&1)"; then
  echo "run.sh: '${KLT_CMD[*]} --version' failed: ${KLT_VERSION}" >&2
  exit 3
fi

HARNESS_ID="20260921-151815-707b34c"
HARNESS_CSV="sim/cmrr-psrr/records/${HARNESS_ID}.csv"
OPENLOOP_CSV="sim/open-loop-ac/records/20260910-221601-22feaba.csv"

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"
RECORDS_DIR="${SCRIPT_DIR}/records"
mkdir -p "${RECORDS_DIR}"
if [[ -e "${RECORDS_DIR}/${RECORD_ID}.sim.json" ]]; then
  echo "run.sh: ${RECORDS_DIR}/${RECORD_ID}.sim.json already exists -- records are append-only." >&2
  exit 3
fi

# klt reports netlist/model paths relative to the invoking repo; run from its root.
cd "${REPO_ROOT}"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/psrr-klt-${RECORD_ID}.XXXXXX")"
BACKEND_ARGS=()
[[ -n "${PSRR_KLT_BACKEND:-}" ]] && BACKEND_ARGS=(--backend "${PSRR_KLT_BACKEND}")

out="${SCRATCH}/psrr.sim.json"
incomplete=0
MODE="${PSRR_KLT_MODE:-shard}"
case "${MODE}" in
  single)
    # One 45-point request: needs a runner whose klt can carry per-section
    # corner libraries, osdi_preload and staged includes (a bumped image,
    # 2AMLogic/2am#2193) and a client whose version equals the runner's.
    req="${SCRIPT_DIR}/psrr.request.json"
    err="${SCRATCH}/psrr.stderr"
    echo "run.sh: ${KLT_CMD[*]} sim $(basename "${req}") ${BACKEND_ARGS[*]} --format json"
    rc=0
    "${KLT_CMD[@]}" sim "${req}" "${BACKEND_ARGS[@]}" --format json > "${out}" 2> "${err}" || rc=$?
    # klt sim: 0 = pass, 3 = ran and some limit failed -- both are complete,
    # gradable runs. 1/2 = did not run; 4 = errored/inconclusive/not_checked.
    if [[ "${rc}" -ne 0 && "${rc}" -ne 3 ]]; then
      echo "run.sh: klt sim exited ${rc} -- not a gradable envelope; nothing written to records/." >&2
      sed 's/^/run.sh:   /' "${err}" >&2 || true
      incomplete=1
    fi
    ;;
  shard)
    # Five per-process requests (shard.py), because the fleet runner image pins
    # klt 0.5.0. Each is one fleet job; the submitting client must carry the
    # batch backend and be accepted by the runner (PyPI klayout-tools==0.6.0:
    # KLT="uvx --from klayout-tools==0.6.0 klt"). Never local: the shards ARE
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
if [[ "${incomplete}" -eq 0 ]] && ! python3 "${SCRIPT_DIR}/compare.py" validate "${out}"; then
  echo "run.sh: envelope failed validation -- nothing written to records/." >&2
  incomplete=1
fi

if [[ "${incomplete}" -ne 0 ]]; then
  echo "run.sh: incomplete run; raw klt output kept in ${SCRATCH}" >&2
  exit 4
fi

cp "${out}" "${RECORDS_DIR}/${RECORD_ID}.sim.json"
if [[ "${MODE}" == "shard" ]]; then
  # Keep the raw per-shard evidence the merged envelope was built from.
  SHARD_DIR="${RECORDS_DIR}/${RECORD_ID}.shards"
  mkdir -p "${SHARD_DIR}"
  cp "${SCRATCH}"/shards.json "${SCRATCH}"/request-mos_*.json "${SCRATCH}"/body-mos_*.spice \
     "${SCRATCH}"/report-mos_*.json "${SHARD_DIR}/"
fi
echo "run.sh: wrote records/${RECORD_ID}.sim.json"

cmp_rc=0
python3 sim/cmrr-psrr/klt/compare.py compare \
  --envelope "sim/cmrr-psrr/klt/records/${RECORD_ID}.sim.json" \
  --harness-csv "${HARNESS_CSV}" \
  --openloop-csv "${OPENLOOP_CSV}" \
  --json-out "sim/cmrr-psrr/klt/records/${RECORD_ID}.compare.json" \
  --provenance "record_id=${RECORD_ID}" \
  --provenance "repo_git_sha=${REPO_GIT_SHA}" \
  --provenance "klt_client_version=${KLT_VERSION}" \
  --provenance "host_ngspice=${NGSPICE_VERSION}" \
  --provenance "backend_override=${PSRR_KLT_BACKEND:-none (request field: batch)}" \
  --provenance "submit_mode=${MODE}" \
  --provenance "pdk=${PDK} $(cat "${PDK_ROOT}/${PDK}/.fetched-version" 2>/dev/null || echo unknown-version)" \
  || cmp_rc=$?

rm -rf "${SCRATCH}"
case "${cmp_rc}" in
  0) echo "run.sh: wrote records/${RECORD_ID}.compare.json (all points within tolerance)" ;;
  1) echo "run.sh: wrote records/${RECORD_ID}.compare.json -- OUT OF TOLERANCE points listed above; explain them in README.md before citing." >&2
     exit 5 ;;
  *) echo "run.sh: compare.py could not join the records (exit ${cmp_rc}); the envelope is written, the comparison is not." >&2
     exit 5 ;;
esac

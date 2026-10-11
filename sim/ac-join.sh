# Source me (via sim/preflight.sh, or directly from an offline test):
#   source "${SIM_DIR}/ac-join.sh"
#
# Shared admission check for cross-record AC joins (issue #224). Sources
# nothing, runs no simulator; needs SIM_DIR, python3, and the arguments below.
# Contract and checks: sim/tools/ac_join_admission.py.
# shellcheck shell=bash

_sg13g2_preflight_self="${_sg13g2_preflight_self:-$(basename "$0")}"

# sg13g2_ac_join_admit <source-csv> <consumer-env-begin> <consumer-dut-snapshot>
#                      <record-id> <provenance-out> <cl-f> <corners> <temps> <vdds> [col...]
#   <corners>/<temps>/<vdds> are space-separated lists. Call AFTER
#   sg13g2_env_identity_begin and the DUT snapshot copy, BEFORE the first
#   solver, for the default-selected and AC_RECORD_CSV-selected source alike.
#   Admission also freezes the source (issue #226): the bytes it validated and
#   hashed are written to a private read-only snapshot beside <provenance-out>
#   (<id>.ac-source.csv) and exported as AC_SNAPSHOT_CSV / AC_SNAPSHOT_SHA256.
#   Consumers MUST read per-point values only via sg13g2_ac_lookup /
#   AC_SNAPSHOT_CSV, never the original path (AC_RECORD_CSV), which may change.
#   On rejection prints every reason plus the regeneration steps and exits 3,
#   having simulated nothing. On success writes <provenance-out>, which the
#   runner publishes at finalize with sg13g2_ac_join_publish.
sg13g2_ac_join_admit() {
  local src="$1" env="$2" snap="$3" rid="$4" out="$5" cl="$6" corners="$7" temps="$8" vdds="$9"
  shift 9
  local -a cols=("$@")
  [[ ${#cols[@]} -gt 0 ]] || cols=(av0_db)
  local -a cn tn vn
  local snapcsv="${out%.ac-join.json}.ac-source.csv"
  read -r -a cn <<< "${corners}"; read -r -a tn <<< "${temps}"; read -r -a vn <<< "${vdds}"
  if ! python3 "${SIM_DIR}/tools/ac_join_admission.py" admit \
      --source-csv "${src}" --consumer-env "${env}" --consumer-snapshot "${snap}" \
      --consumer-record-id "${rid}" --pin "${SIM_DIR}/pdk.json" --cl-f "${cl}" --vcm-frac 0.5 \
      --corners "${cn[@]}" --temps "${tn[@]}" --vdds "${vn[@]}" --require-col "${cols[@]}" --snapshot-out "${snapcsv}" --out "${out}"; then
    # Nothing was measured: drop the DUT snapshot and the (empty) output
    # dirs this run just created so a rejected start leaves no stray record.
    unlink "${snap}" 2>/dev/null || true
    rmdir "$(dirname "${snap}")" "${CORNERS_OUT:-/nonexistent}" 2>/dev/null || true
    echo "${_sg13g2_preflight_self}: AC source ${src} is not admissible for a new join -- refusing to start; nothing was simulated." >&2
    exit 3
  fi
  AC_SNAPSHOT_CSV="${snapcsv}"
  AC_SNAPSHOT_SHA256="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source"]["snapshot_sha256"])' "${out}")" || {
    echo "${_sg13g2_preflight_self}: cannot read the admitted snapshot hash from ${out}; nothing was simulated." >&2
    exit 3
  }
  export AC_SNAPSHOT_CSV AC_SNAPSHOT_SHA256
}

# sg13g2_ac_lookup <header> <point_id>
#   Print <header> of <point_id>'s row from the frozen admitted snapshot
#   (sg13g2_csv_lookup semantics). The snapshot's sha256 is re-verified
#   against the admitted hash on EVERY call; a missing or altered snapshot
#   fails (status 4) and is never replaced by a re-read of the original path.
sg13g2_ac_lookup() {
  sg13g2_ac_snapshot_verify || return 4
  if [[ $# -ne 2 ]]; then
    echo "${_sg13g2_preflight_self}: sg13g2_ac_lookup: expected <header> <point_id>, got $# argument(s)" >&2
    return 3
  fi
  # Same by-header-name join as sg13g2_csv_lookup, on the snapshot only.
  awk -F, -v hdr="$1" -v pid="$2" '
    NR==1 { for (i = 1; i <= NF; i++) if ($i == hdr) col = i; next }
    col && $1 == pid { print $col }' "${AC_SNAPSHOT_CSV}"
}

# sg13g2_ac_snapshot_verify -- status 0 iff the snapshot exists and matches the
#   admitted hash; otherwise a diagnostic and status 4.
sg13g2_ac_snapshot_verify() {
  local got
  if [[ -z "${AC_SNAPSHOT_CSV:-}" || -z "${AC_SNAPSHOT_SHA256:-}" ]]; then
    echo "${_sg13g2_preflight_self}: no admitted AC snapshot (sg13g2_ac_join_admit not run); refusing to read the original AC source." >&2
    return 4
  fi
  if [[ ! -f "${AC_SNAPSHOT_CSV}" ]] || ! got="$(sha256sum "${AC_SNAPSHOT_CSV}" 2>/dev/null | cut -d' ' -f1)"; then
    echo "${_sg13g2_preflight_self}: admitted AC snapshot ${AC_SNAPSHOT_CSV} is missing or unreadable; refusing to fall back to the original source." >&2
    return 4
  fi
  if [[ "${got}" != "${AC_SNAPSHOT_SHA256}" ]]; then
    echo "${_sg13g2_preflight_self}: admitted AC snapshot ${AC_SNAPSHOT_CSV} is corrupted (sha256 ${got}, admitted ${AC_SNAPSHOT_SHA256}); refusing to fall back to the original source." >&2
    return 4
  fi
}

# sg13g2_ac_join_publish <provenance-file> <dest>
#   Publish the accepted-source provenance (records/<id>.ac-join.json)
#   no-clobber, at finalize after sg13g2_env_identity_finalize.
sg13g2_ac_join_publish() {
  if ! sg13g2_publish_noclobber "$1" "$2" 2>/dev/null && ! cmp -s "$1" "$2"; then
    echo "${_sg13g2_preflight_self}: could not publish AC-join provenance $2 (exists with different content); record not finalized." >&2
    exit 4
  fi
}

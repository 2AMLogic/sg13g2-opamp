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
#   On rejection prints every reason plus the regeneration steps and exits 3,
#   having simulated nothing. On success writes <provenance-out>, which the
#   runner publishes at finalize with sg13g2_ac_join_publish.
sg13g2_ac_join_admit() {
  local src="$1" env="$2" snap="$3" rid="$4" out="$5" cl="$6" corners="$7" temps="$8" vdds="$9"
  shift 9
  local -a cols=("$@")
  [[ ${#cols[@]} -gt 0 ]] || cols=(av0_db)
  local -a cn tn vn
  read -r -a cn <<< "${corners}"; read -r -a tn <<< "${temps}"; read -r -a vn <<< "${vdds}"
  if ! python3 "${SIM_DIR}/tools/ac_join_admission.py" admit \
      --source-csv "${src}" --consumer-env "${env}" --consumer-snapshot "${snap}" \
      --consumer-record-id "${rid}" --pin "${SIM_DIR}/pdk.json" --cl-f "${cl}" --vcm-frac 0.5 \
      --corners "${cn[@]}" --temps "${tn[@]}" --vdds "${vn[@]}" --require-col "${cols[@]}" --out "${out}"; then
    # Nothing was measured: drop the DUT snapshot and the (empty) output
    # dirs this run just created so a rejected start leaves no stray record.
    unlink "${snap}" 2>/dev/null || true
    rmdir "$(dirname "${snap}")" "${CORNERS_OUT:-/nonexistent}" 2>/dev/null || true
    echo "${_sg13g2_preflight_self}: AC source ${src} is not admissible for a new join -- refusing to start; nothing was simulated." >&2
    exit 3
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

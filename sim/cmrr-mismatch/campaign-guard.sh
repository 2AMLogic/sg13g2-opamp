# Source me (from run_cmrr_mismatch_mc.sh, or directly from an offline test):
#   source "${SCRIPT_DIR}/campaign-guard.sh"
#
# Binds a resumable cmrr-mismatch campaign to its original inputs (issue
# #163). Split out of the runner so it can be exercised offline: this file
# sources nothing, checks no PDK/OSDI install and runs no simulator. The
# canonical manifest itself is rendered/compared by campaign_manifest.py.
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

_cmrr_mc_guard_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_cmrr_mc_self="${_cmrr_mc_self:-$(basename "$0")}"
CMRR_MC_MANIFEST_TOOL="${_cmrr_mc_guard_dir}/campaign_manifest.py"

# cmrr_mc_render_manifest
#   Print the canonical manifest of the CURRENT invocation's inputs: every
#   input that decides a sample's bytes or the record's verdict. Reads the
#   runner's variables (see cmrr_mc_campaign_guard). Paths inside the
#   checkout are recorded repo-relative and PDK files by content only, so a
#   relocated checkout or PDK install is the same experiment.
#
#   Deliberately NOT bound: the OSDI binaries (a rebuild of the pinned
#   compiler need not be byte-identical; sim/tools/build-osdi.sh --check
#   gates them) and the runner's own bytes (a resume after a fix to an
#   unrelated part of the runner is legitimate; every input the runner feeds
#   the solver or the statistics is bound here instead).
cmrr_mc_render_manifest() {
  local models="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models"
  local fetched="unknown"
  if [[ -r "${PDK_ROOT}/${PDK}/.fetched-version" ]]; then
    fetched="$(head -n 1 "${PDK_ROOT}/${PDK}/.fetched-version" | tr -d '\r\n')"
  fi
  python3 -I "${CMRR_MC_MANIFEST_TOOL}" render --repo-root "${REPO_ROOT}" \
    --field record_id="${RECORD_ID}" \
    --file dut_netlist_src="${DUT_NETLIST_SRC}" \
    --blob dut_netlist_snapshot="${DUT_NETLIST_SNAPSHOT}" \
    --file testbench_template="${EXPERIMENT_DIR}/testbench/tb_cmrr_mc.spice.tmpl" \
    --file ac_record_csv="${AC_RECORD_CSV}" \
    --file cmrr_record_csv="${CMRR_RECORD_CSV}" \
    --field grid_corners="${CORNERS[*]}" \
    --field grid_temps_c="${TEMPS[*]}" \
    --field grid_vdds_v="${VDDS[*]}" \
    --field cl_f="${CL_F}" \
    --field mc_seed_base="${MC_SEED_BASE}" \
    --field mc_seed_alt="${MC_SEED_ALT}" \
    --field mc_n_floor="${MC_N_FLOOR}" \
    --field mc_target_sigma_re="${MC_TARGET_SIGMA_RE}" \
    --field mc_negctl_n="${MC_NEGCTL_N}" \
    --field negctl_tol_db="${NEGCTL_TOL_DB}" \
    --field negctl_tol_v="${NEGCTL_TOL_V}" \
    --field op_rail_frac="${OP_RAIL_FRAC}" \
    --field op_mid_frac="${OP_MID_FRAC}" \
    --field plateau_tol_db="${PLATEAU_TOL_DB}" \
    --field ngspice_version="${NGSPICE_VERSION}" \
    --field pdk="${PDK}" \
    --field pdk_fetched_version="${fetched}" \
    --libdir pdk_ngspice_model_libs="${models}"
}

# _cmrr_mc_refuse <headline> [detail-line...]
#   Print the refusal and exit 3 (called in the current shell, never in a
#   pipeline, so the exit ends the run).
_cmrr_mc_refuse() {
  local headline="$1" line l
  shift
  {
    echo "${_cmrr_mc_self}: refusing to resume record ${RECORD_ID}: ${headline}"
    for line in "$@"; do
      while IFS= read -r l; do echo "${_cmrr_mc_self}: ${l}"; done <<<"${line}"
    done
    echo "${_cmrr_mc_self}: Nothing was modified: this record's samples, snapshot and pilot are exactly as they were."
    echo "${_cmrr_mc_self}: A campaign's samples are only combinable under identical inputs. To run with the"
    echo "${_cmrr_mc_self}: current inputs, unset RECORD_ID (a fresh run mints a new id)."
    if [[ -f "${CAMPAIGN_MANIFEST:-}" ]]; then
      echo "${_cmrr_mc_self}: To continue this campaign instead, restore the stored inputs listed above and"
      echo "${_cmrr_mc_self}: replay RECORD_ID=${RECORD_ID}."
    fi
  } >&2
  exit 3
}

# _cmrr_mc_stored_path <manifest-key>
#   The joined CSV a resume uses when the caller did not name one: the path
#   the manifest recorded (repo-relative unless it lay outside the checkout),
#   never "the newest record" -- a record committed after the campaign began
#   must not silently change the join.
_cmrr_mc_stored_path() {
  local p
  p="$(python3 -I "${CMRR_MC_MANIFEST_TOOL}" get "${CAMPAIGN_MANIFEST}" "$1")" || return 1
  if [[ "${p}" == /* ]]; then
    printf '%s' "${p}"
  else
    printf '%s' "${REPO_ROOT}/${p}"
  fi
}

# cmrr_mc_restore_pilot <pilot-file>
#   Restore the saved pilot's derived values (mc_n_effective AND the pilot
#   sigma, so a resumed record reports the original pilot statistics instead
#   of "unset") after checking the pilot was produced under the current
#   inputs. Sets pilot_sigma_lin, MC_N_EFFECTIVE, PILOT_RESTORED=1.
cmrr_mc_restore_pilot() {
  local pf="$1" k want got bad=()
  local -A expect=(
    [seed_base]="${MC_SEED_BASE}"
    [mc_n_floor]="${MC_N_FLOOR}"
    [mc_target_sigma_re]="${MC_TARGET_SIGMA_RE}"
    [ac_record]="${AC_RECORD_ID}"
    [cmrr_record]="${CMRR_RECORD_ID}"
    [ngspice]="${NGSPICE_VERSION}"
  )
  for k in seed_base mc_n_floor mc_target_sigma_re ac_record cmrr_record ngspice; do
    want="${expect[$k]}"
    got="$(sed -n "s/^${k}: //p" "${pf}" | head -n 1)"
    [[ "${got}" == "${want}" ]] || bad+=("  pilot ${k}: stored=${got:-(absent)} current=${want}")
  done
  local sigma n_eff
  sigma="$(sed -n 's/^pilot_acm_sigma_max_linear: //p' "${pf}" | head -n 1)"
  n_eff="$(sed -n 's/^mc_n_effective: //p' "${pf}" | head -n 1)"
  [[ "${sigma}" =~ ^[0-9][0-9.eE+-]*$ ]] || bad+=("  pilot pilot_acm_sigma_max_linear: unparseable '${sigma}'")
  [[ "${n_eff}" =~ ^[1-9][0-9]*$ ]] || bad+=("  pilot mc_n_effective: unparseable '${n_eff}'")
  if [[ "${#bad[@]}" -gt 0 ]]; then
    _cmrr_mc_refuse "saved pilot does not match the campaign inputs" \
      "the saved pilot (${pf}) disagrees with this invocation:" "${bad[@]}"
  fi
  # shellcheck disable=SC2034  # consumed by the runner after this returns
  {
    pilot_sigma_lin="${sigma}"
    MC_N_EFFECTIVE="${n_eff}"
    PILOT_RESTORED=1
  }
}

# cmrr_mc_campaign_guard
#   Run once, right after sg13g2_preflight_record_paths --resumable and
#   BEFORE the runner touches any campaign artifact.
#
#   Fresh campaign (RECORD_RESUMED=0): snapshot the DUT, then publish the
#   immutable manifest corners/<id>/campaign.manifest -- before the first
#   simulation.
#
#   Resumed campaign (RECORD_RESUMED=1):
#     * no manifest (a legacy or never-started campaign) -> refuse, exit 3;
#     * joined CSVs default to the manifest's recorded paths (an explicit
#       AC_RECORD_CSV / CMRR_RECORD_CSV is honored, and then compared);
#     * any differing manifest key -> refuse, exit 3, naming each key with
#       its stored and current value;
#     * a saved pilot is checked and restored (cmrr_mc_restore_pilot).
#   Every refusal happens before a sample, the snapshot or the pilot is
#   modified.
#
#   Reads: REPO_ROOT EXPERIMENT_DIR RECORD_ID RECORD_RESUMED CORNERS_OUT
#   RECORDS_DIR DUT_NETLIST_SRC DUT_NETLIST_SNAPSHOT AC_RECORD_CSV AC_LATEST_CSV
#   CMRR_RECORD_CSV CMRR_LATEST_CSV CORNERS TEMPS VDDS CL_F MC_* NEGCTL_TOL_* OP_*_FRAC
#   PLATEAU_TOL_DB NGSPICE_VERSION PDK_ROOT PDK.
#   Sets: CAMPAIGN_MANIFEST AC_RECORD_CSV CMRR_RECORD_CSV AC_RECORD_ID
#   CMRR_RECORD_ID PILOT_RESTORED, and (pilot restored) pilot_sigma_lin
#   MC_N_EFFECTIVE.
cmrr_mc_campaign_guard() {
  CAMPAIGN_MANIFEST="${CORNERS_OUT}/campaign.manifest"
  # shellcheck disable=SC2034  # consumed by the runner after this returns
  PILOT_RESTORED=0
  local pilot="${RECORDS_DIR}/${RECORD_ID}.pilot.txt"

  if [[ "${RECORD_RESUMED:-0}" != "1" ]]; then
    local v
    AC_RECORD_CSV="${AC_RECORD_CSV:-${AC_LATEST_CSV:-}}"
    CMRR_RECORD_CSV="${CMRR_RECORD_CSV:-${CMRR_LATEST_CSV:-}}"
    for v in AC_RECORD_CSV CMRR_RECORD_CSV; do
      if [[ -z "${!v:-}" || ! -s "${!v}" ]]; then
        echo "${_cmrr_mc_self}: ${v} ('${!v:-}') is missing or empty -- cannot bind the campaign manifest." >&2
        exit 3
      fi
    done
    AC_RECORD_ID="$(basename "${AC_RECORD_CSV}" .csv)"
    CMRR_RECORD_ID="$(basename "${CMRR_RECORD_CSV}" .csv)"
    cp "${DUT_NETLIST_SRC}" "${DUT_NETLIST_SNAPSHOT}"
    if ! cmrr_mc_render_manifest | python3 -I "${CMRR_MC_MANIFEST_TOOL}" publish "${CAMPAIGN_MANIFEST}"; then
      echo "${_cmrr_mc_self}: could not publish ${CAMPAIGN_MANIFEST} -- aborting before any simulation." >&2
      exit 3
    fi
    echo "${_cmrr_mc_self}: campaign manifest published: ${CAMPAIGN_MANIFEST}" >&2
    return 0
  fi

  if [[ ! -f "${CAMPAIGN_MANIFEST}" ]]; then
    _cmrr_mc_refuse "it has no campaign manifest" \
      "corners/${RECORD_ID}/ has no campaign.manifest, so the inputs its existing samples were drawn" \
      "under (seeds, DUT/template bytes, joined records, solver) cannot be verified. This is a legacy" \
      "campaign (begun before issue #163) or one that stopped before its manifest was published." \
      "It cannot be resumed; its partial evidence is left exactly as it is."
  fi

  if [[ -z "${AC_RECORD_CSV:-}" ]]; then
    AC_RECORD_CSV="$(_cmrr_mc_stored_path ac_record_csv)" \
      || _cmrr_mc_refuse "malformed manifest" "${CAMPAIGN_MANIFEST} lacks ac_record_csv"
  fi
  if [[ -z "${CMRR_RECORD_CSV:-}" ]]; then
    CMRR_RECORD_CSV="$(_cmrr_mc_stored_path cmrr_record_csv)" \
      || _cmrr_mc_refuse "malformed manifest" "${CAMPAIGN_MANIFEST} lacks cmrr_record_csv"
  fi
  AC_RECORD_ID="$(basename "${AC_RECORD_CSV}" .csv)"
  CMRR_RECORD_ID="$(basename "${CMRR_RECORD_CSV}" .csv)"

  local diffs rc=0
  diffs="$(cmrr_mc_render_manifest | python3 -I "${CMRR_MC_MANIFEST_TOOL}" compare "${CAMPAIGN_MANIFEST}" 2>&1)" || rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    _cmrr_mc_refuse "inputs differ from the campaign manifest" \
      "this invocation's inputs differ from ${CAMPAIGN_MANIFEST}:" "${diffs}"
  fi
  echo "${_cmrr_mc_self}: resume -- inputs match ${CAMPAIGN_MANIFEST}" >&2

  if [[ -s "${pilot}" ]]; then
    cmrr_mc_restore_pilot "${pilot}"
  fi
}

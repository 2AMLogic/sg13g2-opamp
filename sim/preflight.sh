# Source me:  source "${SIM_DIR}/preflight.sh"
#
# Shared preflight preamble for every sim/*/run_*.sh harness: sources
# sim/env.sh, then verifies a resolvable PDK install, built OSDI device
# models, and ngspice on PATH -- the same guard clauses (no resolvable PDK,
# missing OSDI build, missing ngspice) every harness in sim/ needs before it
# can run a single corner. Exports NGSPICE_VERSION for the caller, exactly as
# each script did on its own before this file existed, plus
# SG13G2_MOS_CORNERS, the PDK's MOS process-corner set every harness sweeps,
# and SG13G2_NGSPICE_ERR_RE, the broken-simulation log signature every harness
# scans its raw ngspice log for (see their own headers below). Three companion
# functions cover the remaining shared per-caller work:
# sg13g2_preflight_require_netlist (the DUT_NETLIST_SRC guard most -- not all
# -- callers need), sg13g2_preflight_record_paths (the record-id and
# output-path block all ten callers need) and sg13g2_sim_broken (the per-point
# "did this simulation actually solve?" gate all ten callers apply) -- see
# their own headers below.
#
# Callers MUST compute SCRIPT_DIR/SIM_DIR/REPO_ROOT themselves BEFORE
# sourcing this file, mirroring sim/env.sh's own convention:
#
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
#   REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"
#   source "${SIM_DIR}/preflight.sh"
#
# Resolving SIM_DIR/REPO_ROOT *inside* this file via ${BASH_SOURCE[0]} would
# incorrectly resolve to this file's own directory (sim/), not the invoking
# script's -- confirmed empirically (see issue #47's "Verified Corrections").
#
# Error text is derived from "$0" (the top-level invoking script's own
# basename), not a hardcoded per-script literal: "$0" inside a sourced file
# still resolves to the caller's own path (ordinary bash semantics, unlike
# ${BASH_SOURCE[0]}), so this works unmodified for every caller without
# threading the name through as an argument.
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

_sg13g2_preflight_self="$(basename "$0")"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "${_sg13g2_preflight_self}: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "${_sg13g2_preflight_self}: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "${_sg13g2_preflight_self}: ngspice not on PATH." >&2; exit 3; }
# shellcheck disable=SC2034  # consumed by callers after they source this file
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

# SG13G2_NGSPICE_ERR_RE
#   The "this point's simulation is broken" log signature every sim/*/run_*.sh
#   harness greps its raw ngspice log for, as one `grep -E` alternation.
#
#   These seven strings are here because ngspice DOES NOT report them through
#   its exit status: it exits 0 after falling back through gmin stepping,
#   after a non-convergent DC operating point, and after a singular-matrix
#   bailout, and it still writes its `wrdata` rows in those cases. rc and a
#   non-empty output file therefore cannot, on their own, distinguish a solved
#   point from a silently-degraded one -- scanning the log is the only
#   detector, which is why every harness in sim/ does it.
#
#   Do not narrow this set in one bench. A bench that greps for fewer
#   alternatives records points as PASS that every sibling bench would fail,
#   against CLAUDE.md's "verification is the product" -- that is exactly the
#   drift issue #60 found in run_gmid_sweep.sh (which checked only the first
#   four) and removed by routing every site through sg13g2_sim_broken below --
#   except run_offset_mc.sh's per-draw scan, which runs inside Python and
#   reads this constant out of its environment instead. WIDENING the set
#   per-bench is supported and explicit: see that function's --extra hook.
SG13G2_NGSPICE_ERR_RE="Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|singular matrix|gmin stepping failed|no convergence"

# sg13g2_sim_broken [--extra <alternations>] <rc> <log> [required-output-file]
#   Decide whether one simulated point is broken. Returns 0 (success/true)
#   when it IS broken, 1 when it looks good -- the sense the `if sim_broken
#   ...; then <record a failure>` call sites in sim/ already used before this
#   extraction. A point is broken when ANY of:
#
#     * <rc> (ngspice's exit status for that point) is non-zero;
#     * <required-output-file> is given and is missing or empty;
#     * <log> matches SG13G2_NGSPICE_ERR_RE (case-insensitive), plus any
#       --extra alternations.
#
#   The optional third argument is what distinguishes the call sites, and the
#   distinctions are deliberate, not incidental:
#
#     * Most callers pass the CSV the testbench's `wrdata` was supposed to
#       produce, so a point that wrote nothing is caught even when ngspice
#       exited 0.
#     * run_offset_sweep.sh's closed-loop pass has no wrdata CSV at all (it
#       reads a CL_VOUT echo line out of the log, and checks for that line
#       itself right after), so it passes two arguments and no output file.
#
#   --extra <alternations>
#       Widen the regex for this call with additional `grep -E` alternations
#       (no leading "|"). Three benches legitimately watch for one more
#       analysis-appropriate string than the shared core: input-cmr for
#       "DC solution failed", slew-rate for "Transient solution failed",
#       cmrr-mismatch for "Simulation interrupted". Stating those at the call
#       site keeps them visible as deliberate per-bench widenings rather than
#       as copy-paste divergence. SG13G2_NGSPICE_ERR_EXTRA in the environment
#       supplies the same widening for a caller that has no --extra of its
#       own, e.g. when debugging a new failure mode across benches without
#       editing them.
#
#   A caller that needs the log signature ALONE (run_cmrr_mismatch_mc.sh
#   folds it into a larger condition and wants a 0/1 value, not an exit
#   status) passes rc=0 with no output file and converts:
#
#     sig="$(sg13g2_sim_broken 0 "${log}" && echo 1 || echo 0)"
sg13g2_sim_broken() {
  local extra="${SG13G2_NGSPICE_ERR_EXTRA:-}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --extra)
        if [[ $# -lt 2 ]]; then
          echo "${_sg13g2_preflight_self}: sg13g2_sim_broken: --extra needs a value" >&2
          exit 3
        fi
        extra="$2"
        shift 2
        ;;
      --)
        shift
        break
        ;;
      *)
        break
        ;;
    esac
  done

  if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "${_sg13g2_preflight_self}: sg13g2_sim_broken: expected <rc> <log> [required-output-file], got $# argument(s)" >&2
    exit 3
  fi

  local rc="$1" log="$2" outfile="${3:-}"
  local re="${SG13G2_NGSPICE_ERR_RE}"
  [[ -n "${extra}" ]] && re="${re}|${extra}"

  [[ "${rc}" -ne 0 ]] && return 0
  if [[ -n "${outfile}" && ! -s "${outfile}" ]]; then
    return 0
  fi
  grep -qiE "${re}" "${log}" && return 0
  return 1
}

# SG13G2_MOS_CORNERS
#   cornerMOSlv.lib's five MOS process sections [DR-1] -- typical,
#   slow-slow, fast-fast, slow-fast, fast-slow -- in the order every
#   sim/*/run_*.sh harness iterates them. This is a fixed property of the
#   PDK, not a per-measurement parameter, and the order is load-bearing:
#   each bench's point_id numbering is assigned by iterating this list, and
#   sibling benches' records are meant to join point-by-point on point_id.
#
#   Callers copy it into their own local CORNERS array rather than reading
#   this name directly in their sweep loops:
#
#     CORNERS=("${SG13G2_MOS_CORNERS[@]}")
#
#   so the ten harnesses keep one definition of the corner set between them
#   and a future corner rename/addition cannot silently land in nine benches
#   and miss the tenth (which would record a stale corner set with no error,
#   against CLAUDE.md's "PVT corners on every recorded result").
# shellcheck disable=SC2034  # consumed by callers after they source this file
SG13G2_MOS_CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)

# sg13g2_preflight_require_netlist [--no-hint]
#   Verify design/netlist/opamp_core.spice exists and is non-empty, exiting 3
#   with the same message every caller used before this extraction. Exports
#   DUT_NETLIST_SRC for callers that reference it afterward (e.g. to
#   snapshot the netlist alongside their own evidence record).
#
#   Two of the nine callers that need this check
#   (run_cmrr_mismatch_mc.sh, run_offset_mc.sh) never printed the second
#   "regenerate via xschem" hint line the other seven do -- pass --no-hint
#   to reproduce that narrower message exactly. run_gmid_sweep.sh is the
#   tenth run_*.sh harness and does not call this function at all: it sweeps
#   bare devices and never references design/netlist/opamp_core.spice.
sg13g2_preflight_require_netlist() {
  DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
  if [[ ! -s "${DUT_NETLIST_SRC}" ]]; then
    echo "${_sg13g2_preflight_self}: ${DUT_NETLIST_SRC} missing -- regenerate it first, see design/README.md" >&2
    if [[ "${1:-}" != "--no-hint" ]]; then
      echo "${_sg13g2_preflight_self}:   (cd design && xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch)" >&2
    fi
    exit 3
  fi
}

# sg13g2_preflight_record_paths [--prefix <p>] [--resumable]
#   Mint this run's record id and derive the append-only output paths every
#   sim/*/run_*.sh harness writes into, then create the three output
#   directories. Sets, for the caller to use afterward:
#
#     REPO_GIT_SHA    short HEAD of this repo, or "unknown" outside a checkout
#     RECORD_ID       <prefix>YYYYmmdd-HHMMSS-<REPO_GIT_SHA> (UTC)
#     EXPERIMENT_DIR  the calling harness's own directory (= SCRIPT_DIR)
#     SNAPSHOTS_OUT   ${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}
#     CORNERS_OUT     ${EXPERIMENT_DIR}/corners/${RECORD_ID}
#     RECORDS_DIR     ${EXPERIMENT_DIR}/records
#     CSV_OUT         ${RECORDS_DIR}/${RECORD_ID}.csv
#     MD_OUT          ${RECORDS_DIR}/${RECORD_ID}.md
#
#   Callers needing a further record-id-derived path (run_offset_mc.sh's
#   DRAWS_CSV) derive it locally from RECORDS_DIR/RECORD_ID after this call
#   rather than growing this function a knob per bench.
#
#   Two of the ten callers vary the RECORD_ID line, and both variants are
#   load-bearing rather than incidental:
#
#   --prefix <p>  prepend <p> to the minted id. run_offset_mc.sh passes
#                 "mc-" so its Monte Carlo records sort and read distinctly
#                 from the deterministic sweep's records in the same
#                 experiment directory.
#   --resumable   honor a RECORD_ID already set in the environment instead
#                 of minting a new one. run_cmrr_mismatch_mc.sh's resume
#                 feature (see its own header) replays the same RECORD_ID to
#                 continue a killed campaign; without this flag the resumed
#                 run would mint a fresh id and restart from zero. The
#                 minting expression stays inside the ${RECORD_ID:-...}
#                 default so `date` is not even evaluated on a resumed run,
#                 exactly as that script did before this extraction.
# shellcheck disable=SC2034  # CSV_OUT/MD_OUT are consumed by callers after this returns
sg13g2_preflight_record_paths() {
  local prefix="" resumable=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prefix)
        if [[ $# -lt 2 ]]; then
          echo "${_sg13g2_preflight_self}: sg13g2_preflight_record_paths: --prefix needs a value" >&2
          exit 3
        fi
        prefix="$2"
        shift 2
        ;;
      --resumable)
        resumable=1
        shift
        ;;
      *)
        echo "${_sg13g2_preflight_self}: sg13g2_preflight_record_paths: unknown argument '$1'" >&2
        exit 3
        ;;
    esac
  done

  REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if [[ "${resumable}" -eq 1 ]]; then
    RECORD_ID="${RECORD_ID:-${prefix}$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}}"
  else
    RECORD_ID="${prefix}$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"
  fi

  EXPERIMENT_DIR="${SCRIPT_DIR}"
  SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
  CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
  RECORDS_DIR="${EXPERIMENT_DIR}/records"
  CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
  MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
  mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"
}

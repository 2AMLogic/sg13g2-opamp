# Source me:  source "${SIM_DIR}/preflight.sh"
#
# Shared preflight preamble for every sim/*/run_*.sh harness: sources
# sim/env.sh, then verifies a resolvable PDK install, built OSDI device
# models, and ngspice on PATH -- the same guard clauses (no resolvable PDK,
# missing OSDI build, missing ngspice) every harness in sim/ needs before it
# can run a single corner. Exports NGSPICE_VERSION for the caller, exactly as
# each script did on its own before this file existed, plus
# SG13G2_MOS_CORNERS, the PDK's MOS process-corner set every harness sweeps
# (see its own header below). A companion function,
# sg13g2_preflight_require_netlist, covers the DUT_NETLIST_SRC guard most
# (not all) callers also need -- see its own header below.
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

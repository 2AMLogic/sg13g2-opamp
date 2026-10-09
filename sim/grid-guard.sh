# Source me:  source "${SIM_DIR}/grid-guard.sh"
# Deliberately standalone (not in preflight.sh): preflight probes ngspice, and
# the guard must fire before any ngspice launch.
# shellcheck shell=bash

# sg13g2_guard_local_grid <script-name> <allow-flag 0|1>
#
# INTERIM guard (issue #110; delete once #97/#98 move the MC benches onto
# `klt sim` requests). The Monte Carlo runners fan out hundreds to thousands
# of local `ngspice -b` runs. On a shared dispatch worker the daemon exports
# KLT_SIM_BACKEND=batch, meaning grids belong on the Spot batch fleet. Refuse
# (exit 2, before any ngspice launch) when that is set, unless the caller
# passed the explicit --allow-local-grid opt-in (allow-flag=1).
sg13g2_guard_local_grid() {
  local script="$1" allow="${2:-0}"
  if [[ "${KLT_SIM_BACKEND:-}" == "batch" && "${allow}" != "1" ]]; then
    echo "${script}: refusing to run a local Monte Carlo grid: KLT_SIM_BACKEND=batch" >&2
    echo "${script}: marks this host as a shared dispatch worker, where grids go to the" >&2
    echo "${script}: Spot batch fleet via \`klt sim\` (migration tracked in issues #97/#98)." >&2
    echo "${script}: Pass --allow-local-grid to override deliberately." >&2
    exit 2
  fi
}

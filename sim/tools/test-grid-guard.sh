#!/usr/bin/env bash
# Negative control for the interim local-grid guard (issue #110).
# Asserts both MC runners exit 2 with the refusal message when
# KLT_SIM_BACKEND=batch and no --allow-local-grid. Launches no ngspice:
# the guard fires before any simulation (uses a PATH stub that fails loudly
# if ngspice is ever invoked). Needs the same PDK/OSDI preflight as the runners.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sim="$(cd "${here}/.." && pwd)"
stub="$(mktemp -d)"; trap 'rm -rf "${stub}"' EXIT
printf '#!/bin/sh\necho "ngspice stub invoked" >&2\nexit 99\n' > "${stub}/ngspice"
chmod +x "${stub}/ngspice"
fail=0
for r in input-offset/run_offset_mc.sh cmrr-mismatch/run_cmrr_mismatch_mc.sh; do
  out="$(KLT_SIM_BACKEND=batch PATH="${PATH}:${stub}" bash "${sim}/${r}" 2>&1)"; rc=$?
  if [[ ${rc} -eq 2 && "${out}" == *"refusing to run a local Monte Carlo grid"* \
        && "${out}" != *"ngspice stub invoked"* ]]; then
    echo "PASS ${r}: refused (rc=2)"
  else
    echo "FAIL ${r}: rc=${rc}"; echo "${out}" | tail -5; fail=1
  fi
done
exit "${fail}"

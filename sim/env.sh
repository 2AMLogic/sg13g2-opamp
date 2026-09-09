# Source me:  source sim/env.sh
#
# Resolves the SG13G2 PDK environment the same way sg13g2-bandgap's
# sim/env.sh (and that repo's design/xschemrc) do (PDK_ROOT/PDK env vars,
# falling back to the usual open_pdks install prefixes: /usr/share/pdk,
# /usr/local/share/pdk, ~/share/pdk, ~/.ciel, ~/.volare), so an interactive
# ngspice session and every sim/*/run_*.sh script agree on which PDK install
# is in use. Safe to source from any directory; does not require `klt` to be
# installed (this repo's testbenches must remain runnable in a sandbox that
# has ngspice but not klayout-tools).
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

# ${(%):-%x} is the zsh equivalent of ${BASH_SOURCE[0]} -- sourced from both
# shells; shellcheck cannot parse the zsh half.
# shellcheck disable=SC2296
_sg13g2_env_self="${BASH_SOURCE[0]:-${(%):-%x}}"
_sg13g2_sim_dir="$(cd "$(dirname "${_sg13g2_env_self}")" && pwd)"
_sg13g2_repo_root="$(cd "${_sg13g2_sim_dir}/.." && pwd)"

export PDK="${PDK:-ihp-sg13g2}"

if [[ -z "${PDK_ROOT:-}" ]]; then
  for _sg13g2_candidate in /usr/share/pdk /usr/local/share/pdk \
                           "${HOME}/share/pdk" "${HOME}/.ciel" "${HOME}/.volare"; do
    if [[ -d "${_sg13g2_candidate}/${PDK}/libs.tech/ngspice" ]]; then
      export PDK_ROOT="${_sg13g2_candidate}"
      break
    fi
  done
fi

if [[ -n "${PDK_ROOT:-}" && -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  export SG13G2_NGSPICE_MODELS="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models"
  # OSDI-compiled Verilog-A device models (PSP103 MOS, r3_cmc resistors).
  # This directory is where the PDK's own .spiceinit/install.py expect them
  # and where sim/tools/build-osdi.sh writes them; it does NOT exist in a
  # freshly-unpacked IHP-Open-PDK v0.3.0 tree, because that release ships
  # the Verilog-A sources but no prebuilt .osdi binaries. Every testbench
  # that instantiates a MOS loads from here via `pre_osdi`.
  export SG13G2_OSDI_DIR="${PDK_ROOT}/${PDK}/libs.tech/ngspice/osdi"
  echo "sg13g2: PDK_ROOT=${PDK_ROOT} PDK=${PDK}"
  if [[ ! -f "${SG13G2_OSDI_DIR}/psp103.osdi" ]]; then
    echo "sg13g2: OSDI device models not built yet in ${SG13G2_OSDI_DIR}" >&2
    echo "sg13g2: MOS devices (sg13_lv_*) will not simulate until they are." >&2
    echo "sg13g2: Build them with:  sim/tools/build-osdi.sh" >&2
    echo "sg13g2: (see sim/README.md 'OSDI device models' for why this step exists)." >&2
  fi
else
  echo "sg13g2: no ${PDK} install found under PDK_ROOT or the usual prefixes." >&2
  echo "sg13g2: set PDK_ROOT to an open_pdks-shaped IHP-Open-PDK checkout and re-source," >&2
  echo "sg13g2: e.g. via klayout-tools' scripts/fetch-ihp-sg13g2.sh, then:" >&2
  echo "sg13g2:   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2" >&2
  echo "sg13g2: see sim/pdk.json for the pinned release this repo's evidence records target." >&2
fi

unset _sg13g2_env_self _sg13g2_sim_dir _sg13g2_candidate
# _sg13g2_repo_root intentionally left exported-free but available to callers
# that source this file inline; not exported to avoid leaking into child envs.

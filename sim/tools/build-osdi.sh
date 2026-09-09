#!/usr/bin/env bash
# build-osdi.sh -- build the SG13G2 OSDI device models this repo's testbenches need.
#
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # fetch compiler + compile models
#   sim/tools/build-osdi.sh --check         # verify only: models present + loadable
#
# WHAT THIS DOES AND WHY
#
# SG13G2's HV/LV MOS (PSP103.6) and its resistor models (rppd/rsil/rhigh,
# all r3_cmc-based) are Verilog-A compact models. ngspice can only
# instantiate them through OSDI-compiled shared libraries, and
# IHP-Open-PDK's v0.3.0 release tarball (the release sim/pdk.json pins)
# ships the Verilog-A *sources* but no prebuilt .osdi binaries. Without
# them, every MOS and every resistor in design/netlist/*.spice is
# unsimulatable -- see sim/README.md "OSDI device models" for the full
# account, including why the alternatives were rejected.
#
# This script compiles the PDK's OWN Verilog-A sources (from the tarball
# pinned + sha256-verified in sim/pdk.json) with a checksum-pinned release
# of OpenVAF-Reloaded -- the compiler the PDK's own
# libs.tech/verilog-a/openvaf-compile-va.sh prefers by name (`openvaf-r`).
# No third-party .osdi *binary* is ever downloaded or vendored: the model
# code that ends up in the simulator is the PDK's, byte for byte.
#
# Output goes to $PDK_ROOT/$PDK/libs.tech/ngspice/osdi/ -- the location the
# PDK's own .spiceinit and install.py use. That is PDK-install territory
# (generated output), NOT tracked in this repo: .osdi files are
# platform-specific native shared libraries and are deliberately not
# committed here.
set -euo pipefail

# --------------------------------------------------------------------------
# Pins. These are the single source of truth; sim/pdk.json's
# "osdi_toolchain" block restates them as a greppable fact sheet (that file
# is documentation, not consumed by tooling). Keep the two in sync.
# --------------------------------------------------------------------------
OPENVAF_REPO="OpenVAF/OpenVAF-Reloaded"
OPENVAF_TAG="v24.0.1mob"
OPENVAF_BASE_URL="https://github.com/${OPENVAF_REPO}/releases/download/${OPENVAF_TAG}"

# asset name -> sha256, as published by GitHub's release API for ${OPENVAF_TAG}
# (`gh api repos/OpenVAF/OpenVAF-Reloaded/releases --jq '.[0].assets[]|{name,digest}'`,
# re-checked 2026-08-21). Only the macos-aarch64 entry has been executed and
# used to produce evidence in this repo so far -- see sim/README.md.
OPENVAF_ASSET_macos_aarch64="openvaf-r-${OPENVAF_TAG}-macos-aarch64.tar.gz"
OPENVAF_SHA_macos_aarch64="b59a6d7ffba0cdc2e3d3d27edb62d686cde72e7fbe9931f7bed6a4538c15e85e"
OPENVAF_ASSET_macos_x86_64="openvaf-r-${OPENVAF_TAG}-macos-x86_64.tar.gz"
OPENVAF_SHA_macos_x86_64="1635e728a81830326c06d4f81e96f2a8943e661b906d4046084c35ff7595f41e"
OPENVAF_ASSET_linux_x86_64="openvaf-r-${OPENVAF_TAG}-linux-x86_64.tar.gz"
OPENVAF_SHA_linux_x86_64="3297e32f68becf5e0d4709d7f731d7d26f87f88dc136041334677d3ab36279e3"

# Linux/x86_64 only (issue #31): the pinned openvaf-r release above ships
# lib/libLLVM.so.21.1 as a *dangling symlink* to
# ../../x86_64-linux-gnu/libLLVM.so.21.1 -- it assumes the host already has a
# system-installed LLVM 21, which no current Ubuntu LTS ships (24.04/noble
# tops out at libllvm20). Fetch the real .so from the official LLVM apt
# repo's .deb (dpkg-deb -x, no root needed) and point LD_LIBRARY_PATH at it
# for our own openvaf-r invocations. Pin re-checked 2026-08-21; see
# https://apt.llvm.org/noble/pool/main/l/llvm-toolchain-21/ for updates.
LIBLLVM21_DEB_URL="https://apt.llvm.org/noble/pool/main/l/llvm-toolchain-21/libllvm21_21.1.8~++20251221032922+2078da43e25a-1~exp1~20251221153059.70_amd64.deb"
LIBLLVM21_DEB_SHA256="f1f058fff19f9d711c32b9efe5cd473dd2f0e7d5338d082fa5a25858322048cd"
LIBLLVM21_DEB_CODENAME="noble"
LIBLLVM21_DEB_ASSET="libllvm21_21.1.8-${LIBLLVM21_DEB_CODENAME}_amd64.deb"

# model basename -> subdirectory under libs.tech/verilog-a, mirroring the
# PDK's own openvaf-compile-va.sh / ngspice/install.py model list.
MODELS=("psp103:psp103" "psp103_nqs:psp103" "r3_cmc:r3_cmc" "mosvar:mosvar")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

CHECK_ONLY=0
FORCE=0
for arg in "$@"; do
  case "${arg}" in
    --check) CHECK_ONLY=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "build-osdi.sh: unknown argument '${arg}'" >&2; exit 2 ;;
  esac
done

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "build-osdi.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

VA_DIR="${PDK_ROOT}/${PDK}/libs.tech/verilog-a"
OSDI_DIR="${PDK_ROOT}/${PDK}/libs.tech/ngspice/osdi"

if [[ ! -d "${VA_DIR}" ]]; then
  echo "build-osdi.sh: ${VA_DIR} not found -- is PDK_ROOT really an IHP-Open-PDK install?" >&2
  exit 3
fi

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "build-osdi.sh: neither sha256sum nor shasum available -- cannot verify download." >&2
    exit 3
  fi
}

# --------------------------------------------------------------------------
# Linux/x86_64 only (issue #31): fetch, checksum-verify, and unpack the real
# libLLVM.so.21 shared library that the pinned openvaf-r release expects the
# host to already provide (see the LIBLLVM21_* pins above for why). Mirrors
# the openvaf-r tarball fetch-and-verify flow below. Caller must have set
# CACHE_DIR first. Prints the directory containing libLLVM.so.21.1 on
# stdout for the caller to fold into LD_LIBRARY_PATH; caches the extraction
# so repeat runs cost nothing.
# --------------------------------------------------------------------------
ensure_libllvm21() {
  local deb="${CACHE_DIR}/${LIBLLVM21_DEB_ASSET}"
  local extract_dir="${CACHE_DIR}/${LIBLLVM21_DEB_ASSET%.deb}"
  local libdir="${extract_dir}/usr/lib/x86_64-linux-gnu"

  if [[ ! -f "${libdir}/libLLVM.so.21.1" ]]; then
    if ! command -v dpkg-deb >/dev/null 2>&1; then
      cat >&2 <<EOF
build-osdi.sh: openvaf-r (${OPENVAF_TAG}, linux-x86_64) needs libLLVM.so.21,
  which this host does not provide as a system package (no current Ubuntu LTS
  ships libllvm21; 24.04/noble tops out at libllvm20), and dpkg-deb -- needed
  to extract it from the official LLVM apt repo's .deb without root -- is not
  on PATH. Install dpkg-deb (Debian/Ubuntu: already present; otherwise
  'apt-get install dpkg') or apply the workaround manually:

    curl -fsSL -o libllvm21.deb '${LIBLLVM21_DEB_URL}'
    sha256sum libllvm21.deb   # expect ${LIBLLVM21_DEB_SHA256}
    dpkg-deb -x libllvm21.deb /tmp/libllvm21
    export LD_LIBRARY_PATH=/tmp/libllvm21/usr/lib/x86_64-linux-gnu
    sim/tools/build-osdi.sh
EOF
      exit 3
    fi

    if [[ ! -f "${deb}" ]]; then
      echo "build-osdi.sh: fetching ${LIBLLVM21_DEB_URL}" >&2
      curl -fsSL -o "${deb}.part" "${LIBLLVM21_DEB_URL}"
      mv "${deb}.part" "${deb}"
    fi

    local got
    got="$(sha256_of "${deb}")"
    if [[ "${got}" != "${LIBLLVM21_DEB_SHA256}" ]]; then
      echo "build-osdi.sh: SHA256 MISMATCH for ${LIBLLVM21_DEB_ASSET}" >&2
      echo "  expected ${LIBLLVM21_DEB_SHA256}" >&2
      echo "  got      ${got}" >&2
      echo "build-osdi.sh: refusing to use an unverified libLLVM; removing the download." >&2
      rm -f "${deb}"
      exit 4
    fi
    echo "build-osdi.sh: sha256 ${got} OK (${LIBLLVM21_DEB_ASSET})" >&2

    rm -rf "${extract_dir}"
    mkdir -p "${extract_dir}"
    dpkg-deb -x "${deb}" "${extract_dir}"
  fi

  [[ -f "${libdir}/libLLVM.so.21.1" ]] || {
    echo "build-osdi.sh: ${libdir}/libLLVM.so.21.1 missing after extracting ${LIBLLVM21_DEB_ASSET}." >&2
    exit 4
  }
  echo "${libdir}"
}

# --------------------------------------------------------------------------
# --check: assert every model this repo's testbenches load is present and
# actually loadable by the ngspice on PATH. Cheap enough to call from a
# run_*.sh preflight.
# --------------------------------------------------------------------------
REQUIRED_OSDI=(psp103.osdi psp103_nqs.osdi r3_cmc.osdi mosvar.osdi)

check_models() {
  local missing=0 m
  for m in "${REQUIRED_OSDI[@]}"; do
    if [[ ! -f "${OSDI_DIR}/${m}" ]]; then
      echo "build-osdi.sh: MISSING ${OSDI_DIR}/${m}" >&2
      missing=1
    fi
  done
  [[ ${missing} -eq 0 ]] || return 1

  command -v ngspice >/dev/null 2>&1 || {
    echo "build-osdi.sh: ngspice not on PATH -- cannot verify the models load." >&2
    return 1
  }

  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' RETURN
  {
    echo "* build-osdi.sh --check: load every OSDI model, instantiate one of each family"
    echo ".lib \"${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerMOShv.lib\" mos_tt"
    echo ".lib \"${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerRES.lib\" res_typ"
    echo "Vdd vdd 0 dc 3.3"
    echo "Vg g 0 dc 1.0"
    echo "XMP d1 g vdd vdd sg13_hv_pmos w=10u l=1u ng=1 m=1"
    echo "Rd1 d1 0 100k"
    echo "XMN d2 g 0 0 sg13_hv_nmos w=2u l=0.5u ng=1 m=1"
    echo "Rd2 vdd d2 100k"
    echo "XR1 vdd r1b 0 rppd w=2u l=82.7u m=1 b=0"
    echo "Rr1 r1b 0 1"
    echo ".control"
    for m in "${REQUIRED_OSDI[@]}"; do echo "pre_osdi ${OSDI_DIR}/${m}"; done
    echo "op"
    echo "print v(d1) v(d2) v(r1b)"
    echo ".endc"
    echo ".end"
  } > "${tmp}/check.cir"

  if ! ngspice -b "${tmp}/check.cir" > "${tmp}/check.log" 2>&1; then
    echo "build-osdi.sh: ngspice returned non-zero on the model-load check:" >&2
    cat "${tmp}/check.log" >&2
    return 1
  fi
  if grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type" "${tmp}/check.log"; then
    echo "build-osdi.sh: model-load errors in the check run:" >&2
    grep -iE "Unable to find definition of model|couldn't be loaded|Unknown model type" "${tmp}/check.log" >&2
    return 1
  fi
  if ! grep -q "^v(d1)" "${tmp}/check.log"; then
    echo "build-osdi.sh: check netlist produced no operating point:" >&2
    cat "${tmp}/check.log" >&2
    return 1
  fi
  echo "build-osdi.sh: OK -- all ${#REQUIRED_OSDI[@]} OSDI models present and loadable in ${OSDI_DIR}"
  grep -E "^v\(" "${tmp}/check.log"
  return 0
}

if [[ ${CHECK_ONLY} -eq 1 ]]; then
  check_models
  exit $?
fi

if [[ ${FORCE} -eq 0 ]] && check_models >/dev/null 2>&1; then
  echo "build-osdi.sh: models already built and loadable in ${OSDI_DIR} (use --force to rebuild)."
  exit 0
fi

# --------------------------------------------------------------------------
# Resolve the platform asset.
# --------------------------------------------------------------------------
uname_s="$(uname -s)"
uname_m="$(uname -m)"
case "${uname_s}/${uname_m}" in
  Darwin/arm64)  asset="${OPENVAF_ASSET_macos_aarch64}"; sha="${OPENVAF_SHA_macos_aarch64}" ;;
  Darwin/x86_64) asset="${OPENVAF_ASSET_macos_x86_64}";  sha="${OPENVAF_SHA_macos_x86_64}" ;;
  Linux/x86_64)  asset="${OPENVAF_ASSET_linux_x86_64}";  sha="${OPENVAF_SHA_linux_x86_64}" ;;
  *)
    echo "build-osdi.sh: no pinned OpenVAF-Reloaded ${OPENVAF_TAG} asset for ${uname_s}/${uname_m}." >&2
    echo "build-osdi.sh: see ${OPENVAF_BASE_URL} for the asset list; add the pin above once verified." >&2
    exit 3
    ;;
esac

# Persistent cache, NOT /tmp: this repo has already lost a PDK install to a
# /tmp sweep between sessions, and re-downloading a ~60 MB compiler every
# time is avoidable churn. Override with SG13G2_TOOLS_CACHE.
CACHE_DIR="${SG13G2_TOOLS_CACHE:-${HOME}/.cache/sg13g2-opamp}"
mkdir -p "${CACHE_DIR}"
tarball="${CACHE_DIR}/${asset}"
prefix="${CACHE_DIR}/${asset%.tar.gz}"

if [[ ! -f "${tarball}" ]]; then
  echo "build-osdi.sh: fetching ${OPENVAF_BASE_URL}/${asset}"
  curl -fsSL -o "${tarball}.part" "${OPENVAF_BASE_URL}/${asset}"
  mv "${tarball}.part" "${tarball}"
fi

got="$(sha256_of "${tarball}")"
if [[ "${got}" != "${sha}" ]]; then
  echo "build-osdi.sh: SHA256 MISMATCH for ${asset}" >&2
  echo "  expected ${sha}" >&2
  echo "  got      ${got}" >&2
  echo "build-osdi.sh: refusing to run an unverified compiler; removing the download." >&2
  rm -f "${tarball}"
  exit 4
fi
echo "build-osdi.sh: sha256 ${got} OK (${asset})"

if [[ ! -x "${prefix}/bin/openvaf-r" ]]; then
  rm -rf "${prefix}"
  tar -xzf "${tarball}" -C "${CACHE_DIR}"
fi

OPENVAF="${prefix}/bin/openvaf-r"
[[ -x "${OPENVAF}" ]] || { echo "build-osdi.sh: ${OPENVAF} missing after extraction." >&2; exit 4; }

# macOS: the published bundle's dylibs carry a signature that no longer
# matches their bytes (they are relocated after signing), so the kernel
# SIGKILLs openvaf-r the moment dyld maps libLLVM.dylib -- observed as a
# silent exit 137 with no output, `codesign -v lib/libLLVM.dylib` reporting
# "invalid signature (code or signature have been modified)". Re-signing
# ad-hoc locally fixes it. This does NOT weaken the integrity guarantee:
# the bytes were already verified against the pinned sha256 above, and
# ad-hoc signing only re-seals what we just checksummed.
if [[ "${uname_s}" == "Darwin" ]] && command -v codesign >/dev/null 2>&1; then
  for dylib in "${prefix}"/lib/*.dylib; do
    [[ -f "${dylib}" ]] || continue
    if ! codesign -v "${dylib}" >/dev/null 2>&1; then
      echo "build-osdi.sh: re-signing $(basename "${dylib}") ad-hoc (upstream signature is stale)"
      codesign --force --sign - "${dylib}" >/dev/null 2>&1
    fi
  done
fi

# Linux/x86_64: openvaf-r's own lib/libLLVM.so.21.1 is a dangling symlink
# (see the LIBLLVM21_* pins above) -- fetch+verify the real .so and fold its
# directory into LD_LIBRARY_PATH for every openvaf-r invocation below.
# Other platforms are unaffected (empty string -> LD_LIBRARY_PATH untouched).
OPENVAF_EXTRA_LD_LIBRARY_PATH=""
if [[ "${uname_s}/${uname_m}" == "Linux/x86_64" ]]; then
  OPENVAF_EXTRA_LD_LIBRARY_PATH="$(ensure_libllvm21)"
  echo "build-osdi.sh: libLLVM.so.21 resolved via ${OPENVAF_EXTRA_LD_LIBRARY_PATH} (apt.llvm.org libllvm21, issue #31)"
fi

run_openvaf() {
  if [[ -n "${OPENVAF_EXTRA_LD_LIBRARY_PATH}" ]]; then
    LD_LIBRARY_PATH="${OPENVAF_EXTRA_LD_LIBRARY_PATH}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" "${OPENVAF}" "$@"
  else
    "${OPENVAF}" "$@"
  fi
}

echo "build-osdi.sh: compiler: $(run_openvaf --version 2>&1 | head -1) (${OPENVAF_REPO} ${OPENVAF_TAG})"

mkdir -p "${OSDI_DIR}"
for entry in "${MODELS[@]}"; do
  model="${entry%%:*}"
  subdir="${entry##*:}"
  src="${VA_DIR}/${subdir}/${model}.va"
  [[ -f "${src}" ]] || { echo "build-osdi.sh: missing Verilog-A source ${src}" >&2; exit 4; }
  echo "build-osdi.sh: compiling ${model}.va -> ${OSDI_DIR}/${model}.osdi"
  # -D__NGSPICE__ and the model list mirror the PDK's own
  # libs.tech/verilog-a/openvaf-compile-va.sh, so what lands here is what
  # the PDK intends ngspice to load -- not a locally invented build.
  ( cd "${VA_DIR}/${subdir}" && run_openvaf -D__NGSPICE__ -o "${OSDI_DIR}/${model}.osdi" "${model}.va" )
done

echo
check_models

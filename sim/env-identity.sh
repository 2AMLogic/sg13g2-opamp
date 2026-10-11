# Source me (via sim/preflight.sh, or directly from an offline test):
#   source "${SIM_DIR}/env-identity.sh"
#
# The run-time PDK/model identity lifecycle (issues #191, #209), split out of
# sim/preflight.sh -- like sim/record-paths.sh -- so it can be exercised
# offline against a fake PDK install: this file sources nothing, checks no
# PDK/OSDI/ngspice and runs no simulator. At CALL time it needs SIM_DIR,
# PDK_ROOT, PDK and NGSPICE_VERSION (all set by sim/preflight.sh), python3 on
# PATH, and sg13g2_publish_noclobber (sim/record-paths.sh) for finalize.
#
# Contract (issue #209). A record's <id>.env.json sidecar describes the
# model/include closure, OSDI build manifest, observed release marker,
# ngspice and configured pin the run STARTED with, and it is published only
# if a fresh capture immediately before finalization still matches:
#
#   sg13g2_preflight_record_paths / klt_begin_record     (reserve the id)
#   sg13g2_env_identity_begin <id> <scratch-file>        (before 1st solver)
#   ... solvers ...
#   sg13g2_env_identity_finalize <id> <scratch-file> records/<id>.env.json
#   ... only then publish the record's finalized files (.md / .sim.json) ...
#
# Guarantee: a PERSISTENT change to any of those inputs between the begin
# capture and the finalize recheck refuses finalization (exit 4, nothing
# published, incomplete artifacts kept). Limitation: this is a before/after
# comparison, NOT an immutable snapshot of the PDK -- a file changed and
# restored before the finalize recheck is not detected, and a record cannot
# prove which bytes each individual solver invocation read. Snapshotting the
# install is deliberate future work (see sim/README.md).
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

_sg13g2_preflight_self="${_sg13g2_preflight_self:-$(basename "$0")}"

# sg13g2_capture_env_identity <record-id> <out-file>   (issue #191)
#   Writes one run-time PDK/model identity sidecar: the hashed SPICE
#   model/include closure this PDK install actually loads, the OSDI
#   build-manifest identity and the observed release marker, bound to
#   <record-id>. Contract and verifier: sim/tools/env_identity.py. Never
#   overwrites an existing file; returns non-zero (after saying why) on an
#   incompatible/unreadable install.
#
#   Do not call this directly from a runner: a capture taken only when a
#   record is finalized describes whatever bytes are on disk when the run
#   ENDS, not the bytes its measurements actually used. Use the
#   begin/finalize pair below (issue #209) so the record can only finalize
#   under the identity it started with.
sg13g2_capture_env_identity() {
  python3 "${SIM_DIR}/tools/env_identity.py" capture \
    --pdk-root "${PDK_ROOT}" --pdk "${PDK}" --pin "${SIM_DIR}/pdk.json" \
    --record-id "$1" --ngspice "${NGSPICE_VERSION}" --out "$2"
}

# sg13g2_env_identity_begin <record-id> <scratch-file>   (issue #209)
#   Capture the run-time PDK/model identity into private record scratch
#   BEFORE the first solver launches. Call it immediately after
#   sg13g2_preflight_record_paths / klt_begin_record and before any ngspice
#   (or `klt sim`) invocation. A capture failure here means this run could
#   not vouch for its environment BEFORE doing any work, so it aborts with
#   exit 3 (preflight) having simulated nothing -- the counterpart of the
#   end-of-run finalize below, which exits 4.
#
#   <scratch-file> must live outside records/ (the finalized sidecar is
#   published there only by finalize, no-clobber, on success) -- e.g. the
#   klt wrapper's SCRATCH dir, or the private mktemp dir run_pvt_sweep.sh
#   creates under TMPDIR.
sg13g2_env_identity_begin() {
  if [[ $# -ne 2 ]]; then
    echo "${_sg13g2_preflight_self}: sg13g2_env_identity_begin: expected <record-id> <scratch-file>, got $# argument(s)" >&2
    exit 3
  fi
  sg13g2_capture_env_identity "$1" "$2" || {
    echo "${_sg13g2_preflight_self}: could not capture the run-time PDK/model identity before solving -- refusing to start; nothing was simulated." >&2
    exit 3
  }
}

# sg13g2_env_identity_finalize <record-id> <begin-file> <dest>   (issue #209)
#   The finalize half of the identity lifecycle: recheck the BEGIN capture
#   taken before the first solver against a FRESH capture of the live
#   install, and only on a match publish the ORIGINAL begin sidecar
#   (never a fresh capture) to <dest> -- records/<record-id>.env.json --
#   with the shared no-clobber publish (sg13g2_publish_noclobber,
#   sim/record-paths.sh). On any drift -- a hashed model/include byte, the
#   model closure, the OSDI build manifest, the observed release marker,
#   ngspice or the configured environment differing from the begin capture
#   -- exit 4 and publish nothing: the record must not finalize, and its
#   incomplete artifacts stay on disk for inspection. If <dest> already
#   exists (a later suffixed envelope of the same record reusing the first
#   sidecar) it must be byte-identical to the begin capture, else exit 4.
#
#   Guarantee and limit: this detects PERSISTENT drift across the run. It
#   is a before/after comparison, not an immutable snapshot -- a change
#   reverted before the final recheck is undetected (documented in
#   sim/README.md; PDK snapshotting is deliberate future work).
sg13g2_env_identity_finalize() {
  if [[ $# -ne 3 ]]; then
    echo "${_sg13g2_preflight_self}: sg13g2_env_identity_finalize: expected <record-id> <begin-file> <dest>, got $# argument(s)" >&2
    exit 4
  fi
  local record_id="$1" begin="$2" dest="$3"
  if [[ ! -s "${begin}" ]]; then
    echo "${_sg13g2_preflight_self}: no begin identity capture at ${begin} -- sg13g2_env_identity_begin must run before the first solver; record ${record_id} not finalized." >&2
    exit 4
  fi
  if ! python3 "${SIM_DIR}/tools/env_identity.py" compare \
      --before "${begin}" --pdk-root "${PDK_ROOT}" --pdk "${PDK}" \
      --pin "${SIM_DIR}/pdk.json" --ngspice "${NGSPICE_VERSION}"; then
    echo "${_sg13g2_preflight_self}: run-time PDK/model identity drifted while record ${record_id} ran -- refusing to finalize; incomplete artifacts kept for inspection, begin capture: ${begin}." >&2
    exit 4
  fi
  # A sidecar already at <dest> (an earlier suffixed envelope of this record
  # id, or one published concurrently between the test and the `ln`) is
  # acceptable only if it is byte-identical to this run's begin capture.
  if [[ -e "${dest}" ]] || ! sg13g2_publish_noclobber "${begin}" "${dest}" 2>/dev/null; then
    if ! cmp -s "${begin}" "${dest}"; then
      echo "${_sg13g2_preflight_self}: could not publish the PDK identity sidecar ${dest}: it already exists with different content (records are append-only) or the publish failed; record ${record_id} not finalized." >&2
      exit 4
    fi
  fi
}

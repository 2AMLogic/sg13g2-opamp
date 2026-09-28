# Source me:  source "${SIM_DIR}/preflight.sh"
#
# Shared preflight preamble for every sim/*/run_*.sh harness: sources
# sim/env.sh, then verifies a resolvable PDK install, built OSDI device
# models, and ngspice on PATH -- the same guard clauses (no resolvable PDK,
# missing OSDI build, missing ngspice) every harness in sim/ needs before it
# can run a single corner, plus one WARN-ONLY check (never an exit): the live
# ngspice against sim/pdk.json's pin, per DR-0005 -- see its own block below.
# Exports NGSPICE_VERSION for the caller, exactly as
# each script did on its own before this file existed, plus
# SG13G2_MOS_CORNERS, the PDK's MOS process-corner set every harness sweeps,
# and SG13G2_NGSPICE_ERR_RE, the broken-simulation log signature every harness
# scans its raw ngspice log for (see their own headers below). Six companion
# functions cover the remaining shared per-caller work:
# sg13g2_preflight_require_netlist (the DUT_NETLIST_SRC guard most -- not all
# -- callers need), sg13g2_preflight_record_paths (the record-id and
# output-path block all ten callers need), sg13g2_sim_broken (the per-point
# "did this simulation actually solve?" gate all ten callers apply),
# sg13g2_latest_record_csv (resolve the newest committed sibling record every
# cross-referencing caller joins against), sg13g2_csv_lookup (read one
# column out of such a record by header name, keyed on point_id) and
# sg13g2_render_netlist (the shared sed-template render three callers each
# carried their own byte-identical copy of) -- see their own headers below.
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
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed -E 's/^\*\* *//; s/ *:.*$//')"

# Pinned-ngspice trip-wire -- WARNS, never fails (issue #74).
#
#   sim/pdk.json's osdi_toolchain.ngspice_actually_used is the ngspice build
#   every committed record in this tree was produced with, and the build
#   DR-0005 (spec/decision-records/0005-ngspice-reltol-policy.md) ran its
#   solver-tolerance screen against. That record's own follow-through notes
#   that "a future ngspice release changing its own defaults would warrant
#   re-running this screen" -- an obligation nothing enforced before this
#   check, so a host ngspice upgrade was silently baked into new records.
#
#   The pin is read by sed, NOT by a JSON parser: nothing in sim/
#   requires jq today and this check must not be the reason it starts to.
#   ngspice_actually_used is the only occurrence of that key in the file, so
#   a single-key extraction is unambiguous. Keeping the pin in its existing
#   nested home (rather than duplicating it into a top-level key) means
#   there is exactly one value to bump, so the check can never disagree with
#   the fact sheet it reads.
#
#   DELIBERATELY NOT an `exit 3` like the three guards above. DR-0005's
#   obligation is "re-run the screen", not "stop the fleet": every harness in
#   sim/ sources this file, so a hard failure here would strand the whole
#   tree on the next ngspice upgrade. Both sides are compared in the
#   NORMALIZED form (the `ngspice -v` line-2 shape above), and an
#   unreadable value on either side falls into the mismatch branch with a
#   self-describing placeholder -- an unparseable version warns rather than
#   silently matching.
_sg13g2_ngspice_pin="$(sed -n 's/.*"ngspice_actually_used"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${SIM_DIR}/pdk.json" 2>/dev/null | head -n 1)"
_sg13g2_ngspice_live="${NGSPICE_VERSION}"
[[ -n "${_sg13g2_ngspice_live}" ]] || _sg13g2_ngspice_live="(unreadable -- 'ngspice -v' line 2 did not match the expected '** ngspice-NN : ...' shape)"
[[ -n "${_sg13g2_ngspice_pin}" ]] || _sg13g2_ngspice_pin="(unreadable -- no \"ngspice_actually_used\" string in ${SIM_DIR}/pdk.json)"

if [[ "${_sg13g2_ngspice_live}" != "${_sg13g2_ngspice_pin}" ]]; then
  cat >&2 <<BANNER
${_sg13g2_preflight_self}: WARNING: ngspice does not match sim/pdk.json's pin.
${_sg13g2_preflight_self}:   pinned (sim/pdk.json, osdi_toolchain.ngspice_actually_used): ${_sg13g2_ngspice_pin}
${_sg13g2_preflight_self}:   live   (ngspice -v, normalized):                             ${_sg13g2_ngspice_live}
${_sg13g2_preflight_self}: DR-0005 (spec/decision-records/0005-ngspice-reltol-policy.md) measured this
${_sg13g2_preflight_self}: tree's solver-tolerance convention against the pinned build, and notes that
${_sg13g2_preflight_self}: "a future ngspice release changing its own defaults would warrant re-running
${_sg13g2_preflight_self}: this screen". Until that screen is re-run, a record minted by this run carries
${_sg13g2_preflight_self}: an unscreened solver, and joining it against committed evidence is a
${_sg13g2_preflight_self}: mixed-environment join rather than the like-for-like one DR-0005 licenses.
${_sg13g2_preflight_self}: WARNING ONLY -- this run continues and this check never changes an exit
${_sg13g2_preflight_self}: status. Either restore the pinned build, or re-run DR-0005's screen and bump
${_sg13g2_preflight_self}: the pin in sim/pdk.json with a decision record.
BANNER
fi

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

# sg13g2_latest_record_csv [--require-header <name>] [--exclude <glob>] <dir>
#   Print the newest committed record CSV directly under <dir> -- the
#   "which sibling record does this bench join against?" resolution six
#   harnesses each carried their own copy of before this extraction. Prints
#   the empty string (and returns 0) when <dir> holds no match, so the
#   caller keeps making its own "required vs. optional record" call with the
#   `[[ -z ... || ! -s ... ]]` guard it already had:
#
#     AC_RECORD_CSV="$(sg13g2_latest_record_csv "${SIM_DIR}/open-loop-ac/records")"
#
#   "Newest" is the LAST entry of `find -maxdepth 1 -name '*.csv' | sort`,
#   not an mtime comparison, and that is deliberate: record ids are minted
#   as <prefix>YYYYmmdd-HHMMSS-<sha> by sg13g2_preflight_record_paths above,
#   so a lexicographic sort of the filenames IS chronological order and is
#   reproducible on a fresh checkout, where every file's mtime is the clone
#   time. Non-recursive on purpose -- per-corner scratch under
#   records/<id>/ is not a record.
#
#   Two knobs, both needed by run_offset_mc.sh's deterministic-record join
#   and by nothing else today (see its own header comment for why that join
#   has to be narrower than the plain newest-CSV rule):
#
#   --require-header <name>
#       Consider only files whose FIRST line contains <name>, so a bench can
#       ask for "the newest record of a particular shape" rather than the
#       newest record of any shape. run_offset_mc.sh requires
#       vos_closed_loop_v -- the deterministic issue-#11 bench's own column,
#       absent from the MC digest on purpose -- so that a RE-run, executed
#       once this campaign has landed a digest of its own beside it, still
#       joins the deterministic record instead of its own previous output.
#   --exclude <glob>
#       Skip files matching <glob> (passed to find as `! -name <glob>`).
#       run_offset_mc.sh excludes '*-draws.csv', its own per-draw sidecar.
#
#   Passing one knob without the other is supported, but note they guard
#   different failure modes and run_offset_mc.sh needs both: the header
#   filter alone would still let a '*-draws.csv' sidecar win if a future
#   draws file ever carried the deterministic column.
sg13g2_latest_record_csv() {
  local require_header="" exclude=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --require-header)
        if [[ $# -lt 2 ]]; then
          echo "${_sg13g2_preflight_self}: sg13g2_latest_record_csv: --require-header needs a value" >&2
          exit 3
        fi
        require_header="$2"
        shift 2
        ;;
      --exclude)
        if [[ $# -lt 2 ]]; then
          echo "${_sg13g2_preflight_self}: sg13g2_latest_record_csv: --exclude needs a value" >&2
          exit 3
        fi
        exclude="$2"
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

  if [[ $# -ne 1 ]]; then
    echo "${_sg13g2_preflight_self}: sg13g2_latest_record_csv: expected <dir>, got $# argument(s)" >&2
    exit 3
  fi

  local -a _find_args=("$1" -maxdepth 1 -name '*.csv')
  [[ -n "${exclude}" ]] && _find_args+=(! -name "${exclude}")

  local _found="" _f
  while IFS= read -r _f; do
    if [[ -n "${require_header}" ]]; then
      head -n 1 "${_f}" 2>/dev/null | grep -q "${require_header}" || continue
    fi
    _found="${_f}"
  done < <(find "${_find_args[@]}" 2>/dev/null | sort)
  printf '%s' "${_found}"
}

# sg13g2_csv_lookup <csv> <header> <point_id>
#   Print the <header> column of <csv>'s row whose point_id (column 1) is
#   <point_id> -- the per-point join four harnesses each carried their own
#   copy of before this extraction. Empty output when the header or the row
#   is absent; callers that need a placeholder apply their own
#   `[[ -n ... ]] || x=nan` afterward, exactly as they did before.
#
#   The column is resolved by HEADER NAME, never by a hardcoded index, so a
#   join keeps working when the source record gains a column -- which it is
#   expected to, records here being append-only evidence that grows columns
#   over time.
#
#   Reading a MISSING or unreadable <csv> yields empty output rather than a
#   failure (the awk's own `2>/dev/null || true`, carried over from the
#   majority of the call sites this replaced). That is safe because every
#   call site has already asserted its record is non-empty with the
#   `[[ -z ... || ! -s ... ]]` guard at resolution time; it is not licence
#   to skip that guard.
sg13g2_csv_lookup() {
  if [[ $# -ne 3 ]]; then
    echo "${_sg13g2_preflight_self}: sg13g2_csv_lookup: expected <csv> <header> <point_id>, got $# argument(s)" >&2
    exit 3
  fi

  awk -F, -v hdr="$2" -v pid="$3" '
    NR==1 { for (i = 1; i <= NF; i++) if ($i == hdr) col = i; next }
    col && $1 == pid { print $col }' "$1" 2>/dev/null || true
}

# sg13g2_render_netlist [--vcm <v>] <template> <out> <corner> <temp> <vdd> [extra sed args...]
#   Render one netlist <template> to <out> through the shared eight-way sed
#   substitution every sim/*/run_*.sh harness needs
#   (@@PDK_ROOT@@/@@PDK@@/@@OSDI_DIR@@/@@MOS_SECTION@@/@@TEMP_C@@/@@VDD_V@@/
#   @@CL_F@@/@@DUT_NETLIST@@) -- the `render()` function three callers each
#   carried their own byte-identical copy of before this extraction.
#
#   --vcm <v>
#       Add a ninth `s|@@VCM_V@@|<v>|g` substitution, positioned exactly
#       where the two former render() copies that took a fixed `vcm`
#       positional argument (run_offset_sweep.sh, run_swing_sweep.sh) placed
#       it: right after @@VDD_V@@, before @@CL_F@@. A caller that instead
#       supplies its own `@@VCM_V@@` substitution as one of its extra sed
#       args (run_cmr_sweep.sh's coarse/fine passes) omits this flag --
#       passing both would substitute @@VCM_V@@ twice, harmlessly but
#       redundantly, since sed applies -e expressions in argument order and
#       the second match against already-substituted text is a no-op.
#
#   Any further arguments are forwarded to `sed` positionally, immediately
#   before <template>, exactly as the three former copies forwarded their
#   own trailing "$@" -- this is how each caller's own per-pass placeholders
#   (e.g. @@PASS_LABEL@@, @@SWEEP_CSV@@) are substituted.
#
#   Reads OSDI_DIR, CL_F, PDK_ROOT, PDK from the caller's environment (set by
#   the caller before this is called), exactly as the local copies did.
sg13g2_render_netlist() {
  local vcm=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --vcm)
        if [[ $# -lt 2 ]]; then
          echo "${_sg13g2_preflight_self}: sg13g2_render_netlist: --vcm needs a value" >&2
          exit 3
        fi
        vcm="$2"
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

  if [[ $# -lt 5 ]]; then
    echo "${_sg13g2_preflight_self}: sg13g2_render_netlist: expected <template> <out> <corner> <temp> <vdd> [extra sed args...], got $# argument(s)" >&2
    exit 3
  fi

  local tmpl="$1" out="$2" corner="$3" temp="$4" vdd="$5"
  shift 5

  local -a vcm_arg=()
  [[ -n "${vcm}" ]] && vcm_arg=(-e "s|@@VCM_V@@|${vcm}|g")

  sed \
    -e "s|@@PDK_ROOT@@|${PDK_ROOT}|g" \
    -e "s|@@PDK@@|${PDK}|g" \
    -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
    -e "s|@@MOS_SECTION@@|${corner}|g" \
    -e "s|@@TEMP_C@@|${temp}|g" \
    -e "s|@@VDD_V@@|${vdd}|g" \
    "${vcm_arg[@]}" \
    -e "s|@@CL_F@@|${CL_F}|g" \
    -e "s|@@DUT_NETLIST@@|${DUT_NETLIST_SNAPSHOT}|g" \
    "$@" \
    "${tmpl}" > "${out}"
}

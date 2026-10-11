# sim/ — ngspice testbenches and append-only evidence records

Per `CLAUDE.md`: **verification is the product, no claim without a
testbench**, PVT corners on every recorded result, and results here are
**append-only evidence** — a re-run mints a new, timestamped record; nothing
under an experiment's `records/`, `netlist-snapshots/` or `corners/` is ever
edited or deleted after it lands. This follows the same per-experiment shape
(`README.md` / `testbench/` / `corners/` / `netlist-snapshots/` / `records/`)
`sg13g2-bandgap/sim/<experiment>/` established on this same PDK.

## Append-only enforcement and superseding a mistaken record

CI enforces the rule above rather than trusting it:
[`tools/check_append_only_evidence.py`](tools/check_append_only_evidence.py)
(run by `.github/workflows/signoff.yml`) compares the previous Git tree with
the tested tree and fails if any previously committed file under
`sim/<experiment>/records/`, `netlist-snapshots/` or `corners/`,
`signoff/reports/` or `signoff/characterization/reports/` was modified,
deleted, renamed (no rename detection: the old path must still exist) or had
its mode changed. The failure names the path. New files are always allowed, and
so are edits to everything outside those directories (selectors such as
`signoff/characterization/selection.json`, manifests, generators, `run_*.sh`,
testbenches, READMEs). The comparison is PR base vs the tested tree on pull
requests and the push's `before` vs `after` on pushes; the first push of a
branch (all-zero `before`) has nothing to compare and is gated by its PR. There
is no bypass label. Run it locally with
`python3 sim/tools/check_append_only_evidence.py --base origin/main`.

**To supersede a mistaken record, never edit or delete it.** Re-run the bench so
a new timestamped record lands next to the original (new `records/`,
`netlist-snapshots/` and `corners/<record-id>/` paths), then change the mutable
selector (for example `signoff/characterization/selection.json`) to cite the
corrected record and regenerate the dependent reports as new appended records.
The original stays in the tree as history; explain why it was superseded in the
new record's README/PR text.

## Shared `klt sim` envelope gate

Every `sim/<bench>/klt/compare.py` imports its grid (`PROCESSES` x
`TEMPERATURES` x `SUPPLIES`), key helpers (`make_key` / `key_str`),
`InputError` and envelope gate (`read_envelope` / `index_envelope` /
`check_grid`) from [`tools/klt_envelope.py`](tools/klt_envelope.py) (stdlib
only; negative controls in `tools/test_klt_envelope.py`). A bench keeps only its
`MEASUREMENTS`, any per-corner check (passed as `corner_check=` or
`reject_statuses=`), its harness loader and its comparison. A new `klt sim`
bench imports this module instead of copying an existing `compare.py`.

## PDK pin

Every record in this tree is generated against the PDK revision pinned in
[`pdk.json`](pdk.json) (`IHP-Open-PDK` tag `v0.3.0`, fetchable via
`klayout-tools`' `scripts/fetch-ihp-sg13g2.sh`). `source env.sh` resolves
`PDK_ROOT`/`PDK` the same way `sg13g2-bandgap/sim/env.sh` does (env vars
first, then the usual open_pdks install prefixes) — every experiment's
`run_*.sh` sources it, and an interactive `ngspice` session can too.

## Run-time PDK/model identity: before/after drift check

The pin above is configuration, not evidence. A record that carries a
run-time identity sidecar, `records/<record-id>.env.json` (contract and
verifier in [`tools/env_identity.py`](tools/env_identity.py), issue #191),
pins the hashed SPICE model/include closure the run loads, the OSDI
`.build-manifest`, the observed release marker (`.fetched-version`), the
ngspice build and the configured `source`/`release_tag`/`variant`. Three code
paths mint one today: `open-loop-ac/run_pvt_sweep.sh`, the native
`input-noise/run_noise_sweep.sh` (issue #214) and the shared
`klt sim` wrapper lifecycle (`tools/klt_run_common.sh`, used by the
`output-swing`, `input-noise`, `cmrr-psrr` and `slew-rate` `klt/run.sh`).

**Guarantee (issue #209).** The identity is captured into private scratch
*before the first solver launches* (`sg13g2_env_identity_begin`,
[`env-identity.sh`](env-identity.sh)) and compared with a fresh capture
*immediately before the record is finalized*
(`sg13g2_env_identity_finalize`). Only if every compared field is unchanged
is the **begin** capture published, no-clobber, as the sidecar; a host-path
change alone (same bytes under a different `PDK_ROOT`) is not drift, since
model paths are install-relative and `record_id` is not compared. On any
persistent change — a used model/include byte, the closure, the OSDI
manifest, the release marker, ngspice or the configured pin — the run exits
4 with a diagnostic naming what changed, and publishes nothing that looks
finalized: no sidecar and no `records/<id>.sim.json` / `.compare.json` for a
klt wrapper; no `records/<id>.csv` / `.md` / `.env.json` for the native
`run_pvt_sweep.sh` / `run_noise_sweep.sh`. Its incomplete artifacts stay for
inspection (the klt scratch dir, or `corners/<id>/` plus
`records/<id>.csv.raw`, and the begin
capture in the scratch dir named on stderr). At finalization the simulator version is
**re-observed** (a fresh `ngspice -v`, normalized like preflight's) rather
than reusing the value preflight read at start, so a persistent version
change during the run is drift; a missing `ngspice`, a non-zero `-v` exit
(even if it printed a version), empty output or an unparseable version
also refuses finalization with exit 4. (The configured-pin check in
preflight stays warn-only.) A failed begin capture exits 3
before anything is simulated. Re-run under a fresh record id once the
environment is stable.

**Live OSDI binaries (issue #218).** The `.build-manifest` digest is accepted
as the recorded identity only after its claims are checked against the live
bytes, at *both* the begin capture and the finalize recheck
(`validate_osdi_outputs` in [`tools/env_identity.py`](tools/env_identity.py)):
the manifest must carry the supported `schema=1` and exactly one well-formed
`output.<model>.osdi=<sha256>` entry for each required model (`psp103`,
`psp103_nqs`, `r3_cmc`, `mosvar` -- the `MODELS` list of
[`tools/build-osdi.sh`](tools/build-osdi.sh), kept in agreement by a test), each
binary must resolve inside the PDK OSDI directory, be readable and hash to its
entry. Otherwise capture refuses, naming the model: at begin the run exits 3
having simulated nothing; at finalize it exits 4 with nothing published, so a
binary replaced or deleted after begin with the manifest untouched no longer
finalizes. The sidecar schema is unchanged; sidecars minted before this check
are still verified offline under their existing policy and carry no such
guarantee.

**Limitation.** This is a before/after comparison, **not an immutable
snapshot** of the PDK: a file changed and restored before the final check
is not detected, and the sidecar cannot prove which bytes each individual
solver invocation read. Copying the install into a per-run snapshot would
close that gap at the cost of storage and lifecycle scope; it is deliberate
future work. Records minted before this check (and the committed
`legacy-unverified` records without any sidecar) are unchanged and carry no
such guarantee. The remaining `run_*.sh` benches write no sidecar; the
resume-capable `cmrr-mismatch/run_cmrr_mismatch_mc.sh` keeps its own
campaign-manifest input check and is not part of this lifecycle. Offline
controls: `tools/test_env_identity.py` (the comparison and OSDI output validation) and
`tools/test_env_drift_lifecycle.py` (the klt wrapper and both native
runners, stub solvers, fake install).

## Cross-record AC joins (issue #224)

`cmrr-psrr/run_cmrr_psrr_sweep.sh`, `input-offset/run_offset_sweep.sh` and
`output-swing/run_swing_sweep.sh` import per-grid-point values (`av0_db`, and
`vout_dc_v` / `ivdd_total_a` for two of them) from an earlier
`open-loop-ac` record. A matching PVT key alone does not make that valid, so
before the first solver each runs `sg13g2_ac_join_admit`
([`ac-join.sh`](ac-join.sh), checks in
[`tools/ac_join_admission.py`](tools/ac_join_admission.py)).

**Source selection.** The default source is the newest
`open-loop-ac/records/*.csv` (lexicographic = chronological id order);
`AC_RECORD_CSV=<path>` selects another. Both get the identical admission
check -- an explicit path is never trusted more than the default. (The
optional `OFFSET_RECORD_CSV` import in `output-swing` is a different
experiment's record and is not covered by this check.)

**Compatibility guarantee.** A source is admitted only if all hold; every
failure is reported together and the run exits 3 having simulated nothing
(and leaving no stray record directories):

- it has a verified `records/<id>.env.json` sidecar (schema, hashes, pin);
- that identity equals this run's captured environment (model closure bytes
  and OSDI manifest via `identity_sha256`, release marker, configured pin,
  simulator) -- identities are compared, not record ids or host paths;
- `netlist-snapshots/<id>/opamp_core.spice` is byte-identical to this run's
  DUT snapshot;
- load (`Cload` in each source per-point netlist equals the consumer's CL)
  and common-mode configuration (`vcm_v` = VDD/2) match;
- each requested `(corner, temp, vdd)` point has exactly one source row, a
  consistent `point_id`, `op_pass == 1` and finite required columns, and the
  source has no points outside the requested grid.

On success the finalized consumer record carries `records/<id>.env.json`
(its own identity, now usable as a future source) and
`records/<id>.ac-join.json` binding the accepted source's CSV, sidecar and
DUT-snapshot sha256 plus the compatibility basis; its `.md` points at both.

**Frozen source (issue #226).** Admission reads the selected CSV once into a
single byte buffer; the checks, the recorded `csv_sha256` and a private
read-only snapshot (`<id>.ac-source.csv` in the run's scratch dir) all come
from that buffer, so replacing the file during or after admission cannot make
validated rows and recorded hash differ. Consumers read per-point values only
through `sg13g2_ac_lookup` (snapshot hash re-verified on every lookup); a
missing or corrupted snapshot fails the run (status 4) and never falls back
to the original path. A snapshot that cannot be created stops the run before
the first solver. `ac-join.json` records `source.selection_path` (the original
path), `source.csv_sha256` and `source.snapshot_sha256` (equal by
construction). Not covered: `input-cmr` (no admission check) and
`cmrr-mismatch` read their own sources.

**Legacy sources.** Records minted before the identity lifecycle have no
sidecar (all committed `open-loop-ac` records today). They stay as historical
evidence, unmodified, but are *refused* for a new join: no identity is guessed
into an append-only record.

**Regenerating an incompatible source.** Run
`sim/open-loop-ac/run_pvt_sweep.sh` under the same DUT and model install you
will run the consumer against (it mints a new record with a sidecar), commit
it, then re-run the consumer (newest-record default) or pass
`AC_RECORD_CSV=sim/open-loop-ac/records/<new-id>.csv`. A changed DUT or PDK
means the consumer's prior joined records are not comparable either; they
are not rewritten. Offline controls: `tools/test_ac_join_admission.py`.

## OSDI device models

SG13G2's LV/HV MOS (PSP103.6) compact model is Verilog-A; ngspice can only
instantiate it through an OSDI-compiled shared library, and the pinned
IHP-Open-PDK v0.3.0 release ships the Verilog-A *sources* only (no prebuilt
`.osdi`). `sim/tools/build-osdi.sh` compiles the PDK's own sources with a
checksum-pinned OpenVAF-Reloaded release (see that script's header for full
provenance). A successful build also publishes a versioned build manifest,
`$PDK_ROOT/$PDK/libs.tech/ngspice/osdi/.build-manifest` (local PDK install,
not tracked in Git), binding the compiler pin (tag, platform asset and sha256,
libLLVM deb sha256), the compile flags, a hash of every Verilog-A file under
each model's source directory (so an edited included file is detected), and
the sha256 of each `.osdi`. `--check` is read-only: it requires the manifest
to match the current inputs (missing, stale, malformed or unknown-schema
manifests, edited sources, changed pins/flags and replaced binaries all fail
with a rebuild instruction), then runs the ngspice load probe. A normal build
reuses existing binaries only when the manifest is fresh and the probe passes;
`--force` always rebuilds. The manifest is removed before compiling and
written only after all models compile and the probe passes, so a failed build
never certifies a partial set. **One-time rebuild:** installs built before the
manifest existed have none, so run `sim/tools/build-osdi.sh` once. Every
experiment's `run_*.sh` preflights this before simulating. Offline tests:
`sim/tools/test_build_osdi_manifest.py` (stub compiler and ngspice).

## Solver tolerance convention

Every record in this tree is produced at **ngspice's default solver
tolerance**: no `reltol` / `abstol` / `vntol` override line appears in any
deck under `sim/`, and none may be added — decided in
[`spec/decision-records/0005-ngspice-reltol-policy.md`](../spec/decision-records/0005-ngspice-reltol-policy.md)
(DR-0005), which measured all eight deterministic benches at default vs
tightened tolerance on one host and rejected tightening on convergence
evidence (a tree-wide `reltol=1e-9` breaks input-cmr 21/45 and slew-rate
39/45; even `1e-5` breaks input-cmr 6/45 at ~10x wall cost — 31m51s vs 3m16s, DR-0005). The one
known tolerance-sensitivity — the gm/ID bench's finite-difference `gds` /
`gm_gds` columns above `~+0.45 V` overdrive, ~20 % cross-host — stays
documented in that bench's README ("Cross-host reproducibility envelope"),
which is the standing reading rule for those numbers; a reader who needs a
converged `gds` re-derives it from a scratch-copy tightened run using that
README's reproduce recipe. Circuit-bench spec quantities are measured
tolerance-insensitive at print precision (DR-0005's table), so a
mixed-tolerance join across benches is not valid evidence — cross-bench
column joins assume both sides ran at this default. A future proposal to
pin a tolerance must re-run DR-0005's screen and clear its zero-broken
gate first.

DR-0005 screened that convention against one ngspice build — the one pinned
as `osdi_toolchain.ngspice_actually_used` in [`pdk.json`](pdk.json) — and
notes that a future ngspice release changing its own solver defaults would
warrant re-running the screen. **That pin is now enforced as a warning** in
[`preflight.sh`](preflight.sh) (the file every experiment's `run_*.sh`
sources): it compares the live `ngspice -v` against the pin and, on mismatch
only, prints a stderr banner naming both versions and the re-run obligation.
It is deliberately **not** a hard failure — the obligation is to re-run the
screen, not to stop the fleet, so an ngspice upgrade still lets every bench
run, it just says so loudly. A matching version prints nothing. Records
minted while that banner is showing carry an unscreened solver: treat a join
between them and committed evidence as mixed-environment until the screen is
re-run and the pin bumped by a decision record.

## Experiments

- [`gm-id-characterization/`](gm-id-characterization/) — gm/ID, gm/gds, Cgg
  and fT vs Vgs/overdrive for SG13G2's LV core MOS devices
  (`sg13_lv_nmos`/`sg13_lv_pmos`), across four channel lengths and the five
  `cornerMOSlv.lib` process corners (issue #5). The first engineering
  artifact for this block, per `spec/porting-plan.md` §4's "gm/ID first"
  ordering.
- [`open-loop-ac/`](open-loop-ac/) — open-loop DC gain (`Av0`), GBW into
  `CL = 2 pF` [DR-1], phase margin, gain margin and Iq for
  `design/opamp_core.sch`, across the full 45-point `mos_tt/ss/ff/sf/fs` x
  `{-40, 27, 125} °C` x `{1.08, 1.20, 1.32} V` PVT grid (issue #9). The
  first circuit-level (rather than device-level) bench in this tree.
- [`input-offset/`](input-offset/) — deterministic, corner-only DC
  input-referred offset of `design/opamp_core.sch` on that same 45-point PVT
  grid (issue #11), measured two independent ways (open-loop differential
  null sweep, plus a closed-loop DC error referred back through
  `open-loop-ac/`'s per-point `Av0`) — that sweep is the directory's
  **systematic** evidence. Its **statistical (mismatch) complement** — the
  `3σ`, MC N≥300 "combined with, not instead of, process corners" basis
  `spec/target-spec.md`'s offset row commits to — is the same directory's
  Monte Carlo campaign, `run_offset_mc.sh` (issue #17): seeded, per-draw
  sampling of every `cornerMOSlv.lib` `<corner>_mismatch` section across
  the five corners x `{-40, 27, 125} °C` at the fixed 1.20 V supply, with
  a zero-spread negative control, an in-campaign seed-determinism
  self-check, and a systematic-value join against the deterministic
  record.
- [`slew-rate/`](slew-rate/) — rising/falling large-signal slew rate into
  `CL = 2 pF` [DR-1] at a fixed input common mode `VDD/2`, over the same
  45-point PVT grid (issue #12). Source of `spec/target-spec.md`'s
  slew-rate row.
- [`input-noise/`](input-noise/) — input-referred voltage noise of the same
  schematic in a unity-gain closed-loop configuration, over the same
  45-point PVT grid and the same `CL` (issue #13): integrated
  **100 Hz – 1 MHz** µVrms plus spot densities at 100 Hz / 1 kHz / 10 kHz /
  100 kHz / 1 MHz, with a per-point noise-gain guard and a flicker/thermal
  spectral split. This experiment also **chose** the band
  `spec/target-spec.md`'s noise row is stated over — see its `README.md`
  "Choosing the band".
- [`output-swing/`](output-swing/) — DC output swing of the same
  schematic into `CL = 2 pF` [DR-1] (no resistive load — an upper
  bound), from the open-loop differential DC transfer curve with the
  input common mode pinned at `VDD/2`, read at the **−6 dB
  incremental-gain** criterion, over the same 45-point PVT grid
  (issue #15). Reports headroom from VDD and VSS per point (the
  comparable-across-supplies form the spec row requires), the tracking
  span, and the hard-clipped reach, with per-point cross-checks against
  the `open-loop-ac/` and `input-offset/` records. Source of
  `spec/target-spec.md`'s output-swing row.
- [`cmrr-psrr/`](cmrr-psrr/) — common-mode and positive-supply rejection
  of the same schematic, over the same 45-point PVT grid and the same
  `CL` (issue #14): two harnesses (common-mode injection at both inputs vs
  VDD supply injection) sharing `sim/open-loop-ac/`'s self-biased DC
  topology, both swept 10 mHz – 1 GHz so the DC figure is read from a
  machine-verified flat shelf, with per-point op-point cross-checks
  against the joined open-loop record's `Av0`. Also **found** the ~1.5 Hz
  zero in this DUT's supply path — see its `README.md` "The 10 mHz sweep
  start and the ~1.5 Hz supply zero" — and measured PSRR+'s ~4 dB
  in-band degradation across the 100 Hz – 10 kHz band. Source of
  `spec/target-spec.md`'s CMRR and PSRR rows (the CMRR row's ratified
  systematic floor).
- [`cmrr-mismatch/`](cmrr-mismatch/) — mismatch Monte Carlo CMRR of the
  same schematic, over the same 45-point grid (issue #26, companion to
  #17): the `cmrr-psrr/` CMRR harness re-run with the PDK's own
  per-corner mismatch decks (`sg13g2_moslv_mod_mismatch.lib`'s
  per-instance `agauss()` wrappers), 300 independently drawn samples per
  point joined to the same per-point `Av0`, with seed-deterministic
  reproduction, a per-point zero-mismatch negative control asserted
  against the committed systematic record, and per-sample DC/plateau
  sanity. Quotes the **+3σ-of-Acm** part per point — see its `README.md`
  "Choosing the 3σ domain" for why the bound is computed in the linear
  domain. Source of `spec/target-spec.md`'s CMRR row's
  mismatch-inclusive evidence — the record the DR-0002 residual-(c)
  re-ratification pass cites: issue #32's
  [`spec/decision-records/0004-cmrr-mismatch-inclusive-ratification.md`](../spec/decision-records/0004-cmrr-mismatch-inclusive-ratification.md),
  binding the row's `[DR-4]` mismatch-inclusive bound.

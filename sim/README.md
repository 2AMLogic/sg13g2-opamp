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

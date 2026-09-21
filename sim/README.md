# sim/ — ngspice testbenches and append-only evidence records

Per `CLAUDE.md`: **verification is the product, no claim without a
testbench**, PVT corners on every recorded result, and results here are
**append-only evidence** — a re-run mints a new, timestamped record; nothing
under an experiment's `records/`, `netlist-snapshots/` or `corners/` is ever
edited or deleted after it lands. This follows the same per-experiment shape
(`README.md` / `testbench/` / `corners/` / `netlist-snapshots/` / `records/`)
`sg13g2-bandgap/sim/<experiment>/` established on this same PDK.

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
provenance); `--check` verifies the models are present and loadable without
rebuilding. Every experiment's `run_*.sh` preflights this before simulating.

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
  mismatch-inclusive evidence (DR-0002 residual (c), not yet
  re-ratified).

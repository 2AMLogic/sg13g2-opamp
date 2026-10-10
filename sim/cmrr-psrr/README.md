# cmrr-psrr

Common-mode rejection ratio (CMRR) and positive-supply rejection ratio
(PSRR+) benches for `design/opamp_core.sch`'s two-stage Miller-compensated
op-amp (issue #14), across the full PVT grid, into `CL = 2 pF` [DR-1]. These
are the `spec/target-spec.md` §2 `[TBD-8]`/`[TBD-9]` rows — the last two
rejection-ratio classic rows with no measurement behind them. CMRR and
PSRR are bundled in one experiment because both are small-signal AC
rejection-ratio measurements against the same DUT and the same PVT grid,
sharing all of the sweep scaffolding (runner, sanity checks, record
format); only the injected perturbation differs — common-mode input for
CMRR, supply rail for PSRR — exactly the bundling rationale issue #14
states (and the same one `sim/open-loop-ac/` uses for Av0/GBW/PM/GM).

## What this bench measures

For every point on the `cornerMOSlv.lib` `mos_tt/ss/ff/sf/fs` [DR-1] x
temperature `{-40, 27, 125} °C` x supply `{1.08, 1.20, 1.32} V` grid
(45 points), two ngspice AC analyses (10 mHz – 1 GHz, one per harness):

- **CMRR** — `Av0 / Acm`, where `Acm` is the common-mode gain this bench
  measures (one AC perturbation applied **in phase** to both inputs, output
  read), and `Av0` is the **same grid point's** differential open-loop DC
  gain taken from `sim/open-loop-ac/records/*.csv`'s per-point `av0_db`
  column — joined, **not re-measured** (issue #14's own wording).
- **PSRR+** — `Av0 / Avs`, where `Avs` is the supply-to-output gain
  (VDD perturbed with the signal input quiet, output read). `vss` is ground
  in this single-supply part (the `Vss` source pins it to 0 V), so there
  is no distinct negative rail to perturb — PSRR+ (VDD rejection) is the
  only supply rejection this topology defines, the case issue #14's
  "and/or VSS if the design has a distinct negative rail" wording
  anticipated.

Both ratios are reported at the **flat low-frequency shelf** (the DC
figure — see "The 10 mHz sweep start and the ~1.5 Hz supply zero" below)
and, additionally, at **1 kHz** to document in-band behavior. The full
10 mHz – 1 GHz spectra for both harnesses are committed per point under
`corners/<record-id>/`.

## Method

### DC bias: byte-equal to the open-loop bench

Both harnesses reuse `sim/open-loop-ac/`'s self-biased topology exactly
(`Lbreak = 1e18 H` from `inn` to `out`; `inp` held at `Vcm = VDD/2`; the
external ideal `ibias = 10 µA`) — see that bench's template header and
README for the loop-break reasoning. Keeping the DC network identical is
**load-bearing**, not stylistic: each ratio divides the open-loop record's
per-point `Av0` into this bench's freshly measured `Acm`/`Avs`, which is
only a valid statement about the same amplifier at the same operating
point if both benches actually share that point. The runner verifies the
shared-op-point assumption two ways per point, and this committed record
passes both with margin to spare:

- `op_xcheck_psrr_delta_v` — the CMRR harness's and PSRR harness's echoed
  operating points agree to **0 V** at every grid point (they are DC-identical
  netlists by construction; this guard exists so a future edit to one
  template that breaks that equivalence is caught mechanically).
- `ol_vout_delta_v` — this bench's `vout_dc_v` agrees with the joined
  open-loop record's own `vout_dc_v` to **0 V** at every grid point
  (`<= 1e-3 V` would have been tolerated; the measured agreement is exact
  to the logged precision).

### Common-mode injection (CMRR harness)

The perturbation node `cmpert` (dc 0, ac 1 V) reaches **both** input gates
in phase: `inp` through its own DC-bias source (referenced to `cmpert`, so
`inp` sits at exactly `Vcm` at DC and exactly the 1 V perturbation at AC),
and `inn` through `Ccm = 1 F`, which is a DC open — so `inn`'s DC remains
set by `Lbreak` alone, leaving the self-bias loop the open-loop bench
establishes **undisturbed** — and an AC short from the sweep's lowest
frequency up (`|Z| <= 16 Ω` at 10 mHz) against `inn`'s only other AC paths
(M1's femtofarad-scale gate impedance, ~1e16 Ω, and the open `Lbreak`).
Tying `inn` directly to the CM node instead would pin it at `Vcm` and
destroy the feedback that makes this operating point well-defined at all.
Residual differential-drive imbalance from the `Ccm` divider is ~1e-15,
thirteen orders below the measured outputs.

### Supply injection (PSRR harness)

`Vdd` carries `ac 1` on top of its DC value; the signal input is
AC-grounded (`Vinp` has no `ac` value); `inn` is quiet via the same
`Lbreak` argument. The supply-rejection scope note that matters: `ibias`
is an **external ideal 10 µA current source** (per
`design/opamp_sizing.md` "Bias scope"), and an ideal current source is an
AC open with zero AC value — so supply ripple does **not** ride into the
bias reference, and this bench measures the amplifier core's supply
rejection under an ideal reference. A part with an on-die bias generator
would fold that generator's supply sensitivity into its PSRR; this block
has no bias generator in scope (the same scope decision the Iq rows make,
`design/opamp_sizing.md` "Iq reporting note").

### The 10 mHz sweep start and the ~1.5 Hz supply zero

The PSRR transfer is **not flat from 1 Hz down to DC**: this DUT's
VDD→out response carries a genuine zero near ~1.5 Hz (at the nominal
point, supply gain rises ~4 dB from its 35.5 dB DC shelf to a ~39.6 dB
in-band shelf spanning roughly 100 Hz – 10 kHz before the output pole
rolls it off — i.e. **PSRR+ degrades by ~4 dB between DC and the
mid-band**). Three dev-time checks (documented in
`testbench/tb_psrr.spice.tmpl`'s header, data preserved in the template's
provenance note and visible in every committed `corners/*_psrr_ac.csv`)
establish the zero belongs to the DUT's supply path, not the harness:
raising `Lbreak` from 1e18 H to 1e21 H changes the response by <1e-4 dB
at every frequency (a loop-break artifact would move with L); the `d2`
and `tail` nodes' VDD responses carry the same low-frequency shape (the
zero lives in the first stage's supply path); and a finite-difference DC
sweep (`vdd ±1 mV`, `vcm` tracking `vdd/2`) reads the fully loop-closed
DC limit, ≈ **−3.8 dB**, distinct from the shelf as the `Lbreak`-imposed
f→0 suppression requires.

So both harnesses sweep from 10 mHz (not 1 Hz): the DC figure is read at a
machine-verified flat shelf. The 10 mHz start itself sits inside the
window whose lower edge is the `Lbreak`-`Cgg` loop-closing corner
(single-millihertz scale for `L = 1e18 H`) — going lower would re-enter the
suppressed region and/or the zero's skirt, so the shelf is read at 10 mHz
and the runner re-verifies flatness per point with a **plateau guard**
(`Acm`/`Avs` at 10 mHz vs 0.1 Hz, tolerance 0.05 dB). One grid point
(`mos_ss_-40C_1.08V`, the coldest/lowest-rail corner, whose supply zero
sits lowest) reads a guard delta of 0.066 dB — its DC PSRR figure carries
a ±0.1 dB-class residual, flagged in
`corners/<record-id>/sanity_checks.txt` rather than hidden. Every other
point passes with orders of margin (the CMRR side of the grid is flat to
<1e-4 dB everywhere). The Acm0/Avs0 read convention is otherwise exactly
the open-loop bench's Av0 plateau read, pushed one decade-class lower
because this transfer needs it.

### Per-point sanity checks

Same DC rule as `sim/open-loop-ac/` (necessary-not-sufficient, same
caveats about this OSDI/PSP103 build's missing per-device op-point
queries — see that README): output within 15 % of mid-rail, no internal
node within 2 % of a rail. This record: 45/45 pass. Additionally:
the two op-point cross-checks above (`op_xcheck_psrr_delta_v`,
`ol_vout_delta_v`: 0 failures, exact agreement) and the plateau guard
(1 documented 0.066 dB note, 0 others).

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
sim/cmrr-psrr/run_cmrr_psrr_sweep.sh
```

Requires `ngspice` on `PATH` (developed and run against `ngspice-46`)
plus the OSDI models `sim/tools/build-osdi.sh` builds; does **not**
require `xschem` at run time (`design/netlist/opamp_core.spice` is
committed, pre-netlisted). Also requires a committed
`sim/open-loop-ac/records/*.csv` to join `av0_db` from — the newest record
is picked automatically; override with `AC_RECORD_CSV=<path>`. Runs the
full 45-point grid (90 ngspice invocations, two harnesses per point) in
about four minutes on a modern laptop. Writes a new, timestamped,
append-only record under `netlist-snapshots/<record-id>/`,
`corners/<record-id>/` and `records/<record-id>.{csv,md}` — never
overwriting a prior run.

## What was actually measured (this repo's committed record)

Record [`20260921-151815-707b34c`](records/20260921-151815-707b34c.md) —
all 45 points converged in both harnesses, all 45 passed every DC sanity
check, op-point cross-checks exact, one plateau-guard note documented
above. `Av0` joined from
[`sim/open-loop-ac/records/20260910-221601-22feaba.csv`](../open-loop-ac/records/20260910-221601-22feaba.csv):

| Metric | Range across all 45 points | Worst point (binding corner) |
|---|---|---|
| CMRR (DC, 10 mHz shelf) | 30.75 – 62.83 dB | 30.75 dB at `mos_fs_125C_1.08V` |
| CMRR @ 1 kHz | 30.75 – 62.83 dB (flat DC–1 kHz across the grid) | same |
| PSRR+ (DC, 10 mHz shelf) | 1.87 – 29.54 dB | 1.87 dB at `mos_ff_125C_1.32V` |
| PSRR+ @ 1 kHz | 1.30 – 9.06 dB | 1.30 dB at `mos_sf_-40C_1.32V` |

Nominal (`mos_tt_27C_1.20V`): **CMRR 35.32 dB**, **PSRR+ 6.43 dB at DC,
degrading to 2.30 dB at 1 kHz** (the supply zero at work). Full per-point
data: [`records/20260921-151815-707b34c.csv`](records/20260921-151815-707b34c.csv).
Raw per-point ngspice logs and AC sweep data, both harnesses:
[`corners/20260921-151815-707b34c/`](corners/20260921-151815-707b34c/).
Frozen DUT netlist this record ran against:
[`netlist-snapshots/20260921-151815-707b34c/opamp_core.spice`](netlist-snapshots/20260921-151815-707b34c/opamp_core.spice).

### Reading these numbers honestly: both rejection ratios are low

These are **weak figures in absolute terms, and that is the measurement,
not a bench defect** — the per-point operating points, cross-checks and
flat-shelf guards above all say the harness measured a healthy, regulating
amplifier. Two structural properties of this core produce them, both
expected for this canary's deliberately simple topology:

- **CMRR (~31–63 dB)**: with perfectly matched devices (this is a
  deterministic, no-mismatch simulation), the common-mode gain is set by
  the first stage's structural asymmetry — a current-mirror load whose
  diode-connected side (`d1`) presents `1/gm` while the mirror-output side
  (`d2`) presents `ro` — plus the tail source's finite impedance. The
  CM-induced `d2` excursion is then multiplied by the full second-stage
  gain, unlike the textbook framed around the first stage's differential
  outputs. A real part's random mismatch would typically degrade CMRR
  further (the offset row's systematic/statistical split applies here
  too — see "What this bench does not claim").
- **PSRR+ (~2–30 dB)**: the output PMOS (`M6`, source on `vdd`) receives
  supply ripple directly, and it is only partially cancelled by how
  `d2` follows VDD through the first stage — and the amplifier reference
  is externally biased, with no supply-independent biasing in scope
  (an on-die bandgap-referenced bias, or a cascoded/regulated supply
  path, is what real low-PSRR designs use; improving this core either way
  would be a design change outside this bench's scope). Supply ripple
  effectively reaches the output at roughly half the differential
  sensitivity at the nominal point, degrading to ~80 % of it at the
  binding corner (Avs 39.8 dB against Av0 41.7 dB at FF / 125 °C /
  1.32 V).

`spec/target-spec.md`'s rows quote the DC worst-case/best-case figures with
these binding corners, tagged `[P]` (proposed/measured, not ratified) per
the offset/noise rows' precedent.

### Measured vs. predicted binding corners

Both rows' "Binding corner (predicted)" cells said **"to be determined"**
— no pre-schematic prediction existed to contradict. The measurement fills
them in, and they are **not the same corner** (the exact case the issue's
Test Plan anticipated: "they need not be the same corner"):

- **CMRR binds at `FS / 125 °C / 1.08 V`** — hot, low-rail, the *same
  corner that already binds DC gain, GBW, input-referred noise and
  systematic offset* in this grid. Consistent picture: the same
  hot/low-supply degradation that drags Av0 down drags the ratio with it
  — the binding point splits into Av0 37.78 dB against Acm +7.03 dB.
- **PSRR+ binds at `FF / 125 °C / 1.32 V`** (DC) — the *only* row so far
  that binds at the fast/hot/high-rail corner: supply rejection here is
  dominated by the direct `M6` path (fast devices, high gm and low
  impedance into the output at high rail), not by the low-gain mechanism
  that binds every other row. In-band (1 kHz) the worst point moves to
  `SF / −40 °C / 1.32 V`.

Issue #14's bundling fallback ("if the two measurements turn out to need
materially different testbench topologies, split PSRR into its own issue")
was not triggered: both harnesses share the identical DC network, runner,
sanity checks and record format, differing only in the injection source.

## What this bench does not claim

- **Not a closed-loop CMRR/PSRR measurement.** Both ratios are open-loop
  transfer-function ratios (`Av0/Acm`, `Av0/Avs`) per the standard
  definition and issue #14's own wording — the figures a closed-loop
  application would realize also depend on the feedback network's noise
  gain, out of this bench's scope.
- **Not a statistical/mismatch CMRR.** Devices are perfectly matched in
  these deterministic corner runs; the measured CMRR is the *systematic*
  rejection of the nominal design (mirror asymmetry, finite tail
  impedance). Random input-pair/mirror mismatch — typically the dominant
  real-part CMRR term — is not measured here, exactly the way
  `sim/input-offset/` splits systematic from statistical offset (the
  spec row's statistical-basis column keeps "deterministic
  corner-worst-case" accordingly; a mismatch Monte Carlo pass is the
  natural follow-on, sibling to the offset row's #17).
- **Not a bias-generator PSRR.** The external ideal 10 µA reference
  injects zero supply ripple (see "Supply injection" above); a part with
  an on-die bias generator would measure worse than this.
- **Not a single-number frequency promise.** The scalar rows quote the DC
  shelf; PSRR+ demonstrably degrades ~4 dB by the 100 Hz – 10 kHz band
  (see "The 10 mHz sweep start and the ~1.5 Hz supply zero"), and the
  committed per-point spectra are the artifact to consult for any
  frequency-specific use.
- **Not a ratified spec claim.** `spec/target-spec.md` rows updated from
  this record are tagged `[P]`, not `[DR-n]`, per that file's Status
  (DRAFT) and value-tag legend.
- **Not input-CMR (input common-mode range) characterization** — the
  measurement runs at one fixed `Vcm = VDD/2` per grid point, per the
  fleet's bench convention (input common-mode range is its own issue, #21).

## The `klt sim` path (`klt/`, issue #99): 45-corner envelope committed

`klt/` expresses the **PSRR+** half of this bench as a `klt sim` request, for
T1 item 5 (`signoff/README.md`, "Item 5 envelope coverage, per ratified
row"). **Status: evidence increment. A real 45-corner supply-gain envelope
was run through the batch fleet and is committed unmodified
(`klt/records/20261010-094256-469573d.sim.json`), with its measured comparison
against the harness record (`.compare.json`).** The PSRR verdict is still an
offline join with the harness open-loop Av0 (below), so this is not yet a
fully `klt sim`-graded PSRR row. The CMRR bench is a separate ratified row
(`sim/cmrr-mismatch/`, #98) and is not in `klt/`.

| File | Role |
|---|---|
| `klt/psrr.request.json` | 45-point grid (`mos_tt/ss/ff/sf/fs` × −40/27/125 °C × 1.08/1.20/1.32 V; each process corner a bundle with `cornerCAP.lib cap_typ`; `vinp` swept with `vdd` so Vcm = VDD/2), `ac dec 20 10m 1g`, OSDI preload + `stage_model_inputs` (the single-request form; the sharded form below replaces both), default solver tolerance (DR-0005) |
| `klt/tb_psrr.body.spice` | the template's circuit as a body: exactly one DUT `.include`, no `.control`; `Vdd` carries `ac 1`, `Vinp` carries none |
| `klt/run.sh` | sources `sim/preflight.sh` (which sources `sim/env.sh`); submits to the batch backend (`PSRR_KLT_MODE=shard`, the default, or `single`); writes the envelope **unmodified** to `klt/records/<UTC>-<sha>.sim.json` only after `compare.py validate` passes (45 unique points, no errored/inconclusive corner, `coverage.nothing_checked` false, nothing skipped); in shard mode also keeps the raw per-shard requests, bodies and reports in `<id>.shards/` |
| `klt/shard.py`, `klt/test_shard.py` | the per-process shard bridge for the klt 0.5.0 fleet runner, and its validation-gated merge; tests with negative controls (below) |
| `klt/compare.py`, `klt/test_compare.py` | grid join and tolerance report; offline stdlib-only; tests with negative controls |

### Which encoding: Avs in the tool, Av0 joined offline

PSRR = Av0 / Avs needs two AC excitations (`Vinp ac 1` for Av0, `Vdd ac 1`
for Avs). One AC solve cannot carry both, and a `limits` entry applies to one
measurement of one request. So this is **not** a single-solve PSRR ratio, and
it is not described as one. The request reports `avs0_db` (10 mHz, the DC
shelf) and `avs_1khz_db`; `compare.py` joins the same-point Av0 from
`sim/open-loop-ac/records/20260910-221601-22feaba.csv` on (process,
temperature, VDD), computes `PSRR = Av0 − Avs0`, and applies the ratified
bound (≥ 1.87 dB, DC shelf) **offline**. Consequences, stated plainly:

- Av0 is **harness evidence**, not a `klt sim` Av0 envelope. This is the same
  join the harness itself makes (above). If #85's AC envelope lands, the join
  can use it instead (the other option in the issue).
- The PSRR verdict is `compare.py`'s, not the tool's. The tool grades one
  limit: the harness's flat-shelf plateau guard (|Avs(10 mHz) − Avs(0.1 Hz)|
  ≤ 0.05 dB), which also keeps `coverage.nothing_checked` false. The harness
  record documents one point over it (`mos_ss_-40C_1.08V`, 0.066 dB), so a
  full-grid envelope will report that corner as a limit miss: a result, kept.
- The DC shelf (10 mHz) and the 1 kHz figure are separate measurements; the
  ratified row is the DC shelf. Absent same-point Av0 or Avs, `compare.py`
  fails closed.
- **The worst point clears the bound by 0.0009 dB** (FF / 125 °C / 1.32 V,
  1.8709 dB vs 1.87 dB), far less than the comparison tolerance. Any
  tool/harness verdict difference at that corner is therefore reported as
  "explained by tolerance", and must not be read as agreement.

### The shard bridge (why the committed envelope was not one request)

The fleet runner image still pins klt 0.5.0 (2AMLogic/2am#2193). On it,
`psrr.request.json` cannot run as one request: the `{"lib","section"}` object
form of the per-process bundle (the fixed `cornerCAP.lib cap_typ` section),
`options.osdi_preload`/`stage_model_inputs`, and `ngspice_init` are not
carried (the runner drops or rejects them), a 0.7.0 client is refused
(`batch_runner_version_mismatch`, exit 87), and a 0.5.0 client has no `batch`
backend. The proven route (sg13g2-bandgap `sim/harness/README.md`) is the
client `klayout-tools==0.6.0` (`KLT="uvx --from klayout-tools==0.6.0 klt"`; it
submits, and the runner accepts it) with one request per process corner.
`klt/shard.py gen` derives the five requests from the master request:

| Master request | Each shard (`mos_xx`, 9 corners) |
|---|---|
| `corners.process` bundle `[mos_xx, {cornerCAP.lib, cap_typ}]` | `models.lib` = `cornerMOSlv.lib`, `corners.process` = `["mos_xx"]`; the cap section becomes a body-level selection card `.lib ".../cornerCAP.lib" cap_typ` against the image's baked PDK root (`/opt/pdk`) |
| `options.osdi_preload`, `stage_model_inputs` | a body `.control` block of four `pre_osdi` cards (the documented deviation from the netlist-body contract) |
| `options.ngspice_init` (`set measureprec/numdgt=12`) | the same two `set` cards in that `.control` block |
| body `.include` of the DUT netlist | the DUT netlist inlined (its `.end` dropped); the 0.6.0 client uploads the body file only |
| everything else | identical: measurements, the one limit, `ac dec 20 10m 1g`, temperature and supply axes, default solver tolerance (DR-0005) |

`shard.py merge` is a pure transform: it concatenates the five reports in
canonical grid order and recomputes the aggregates (counts, `metrics`, the
`measurements[]` worst-case rollup, by klt's own rule); no corner or
measurement is edited, and shard-specific fields (netlist hash, fleet job) move
into per-shard arrays under `environment`/`provenance` instead of standing for
the grid. It refuses, exit 2, and the tests (`klt/test_shard.py`) hold each
refusal: a missing, duplicate or unexpected shard; a shard whose submitted
request digest differs from the manifest's (and an absent digest); a corner that
belongs to another process; a missing, duplicate or wrong-VDD point; a shard
whose coverage is dirty (`nothing_checked`, skipped); a klt error report. The
positive control shows the merge is exactly the 45 unique ratified points, edits
no corner, is independent of shard order, and passes `compare.py validate`; an
errored corner survives the merge and is then refused by the gate. The five shards
are proved to partition the grid by `check_manifest`, which `gen` and `merge`
both run.

The committed envelope was minted by `run.sh` (shard mode) across several
invocations, because the fleet was repeatedly full (`no capacity in any of
the 30 pools`, `8 instance(s) already running ... exceeds
BATCH_MAX_CONCURRENT_INSTANCES=8`): `PSRR_KLT_RESUME_DIR` reuses a prior shard
report only when its request is byte-identical to the one just generated, and
`PSRR_KLT_SUBMIT_TRIES` re-submits a capacity refusal a bounded number of
times (never locally). The five shard requests, bodies and reports are kept
beside the envelope in `klt/records/20261010-094256-469573d.shards/`; the five
fleet jobs are `klt-sim-8b0cf80b0eea` (`mos_tt`), `klt-sim-a5c104a8e55f`
(`mos_ss`), `klt-sim-a03984cc4e7f` (`mos_ff`), `klt-sim-eba6cbaf121d`
(`mos_sf`) and `klt-sim-7a549124cc61` (`mos_fs`), all on the baked image
`ami-0e40e3245f1923ac8` (ngspice 46). When the runner image is bumped, use
`PSRR_KLT_MODE=single` with a client whose `klt --version` equals the
runner's.

### Measured comparison: `klt sim` envelope vs the harness record

`klt/records/20261010-094256-469573d.{sim,compare}.json`, from client klt
0.6.0, host preflight ngspice-46 + OSDI check passing, joined on (process,
temperature, VDD) against `records/20260921-151815-707b34c.csv` (Avs) and
`sim/open-loop-ac/records/20260910-221601-22feaba.csv` (Av0). The envelope has
exactly the 45 unique ratified points, no errored or inconclusive corner,
`coverage.nothing_checked` false and nothing skipped.

- **No joined point is out of tolerance.** Over all 45 points the largest
  |tool − harness| is 4.96e-5 dB on `avs0_db` and on the derived `psrr_db`
  (`mos_fs` / 27 °C / 1.08 V; median 2.2e-5 dB), 4.93e-5 dB on `avs_1khz_db`
  (`mos_sf` / −40 °C / 1.32 V) and 8.8e-8 dB on the plateau delta. That is the
  harness CSV's own print precision (four decimals, half-unit 5e-5 dB), not a
  method difference: the shelf is read at 10 mHz in both paths from the same
  `ac dec 20 10m 1g` sweep, and a Linux/x86_64 fleet instance reproduces a
  macOS/aarch64 harness record to the digits it printed, so DR-0005's
  cross-host figure is not visible at this precision. The comparator's
  tolerances (0.02 dB; 0.005 dB for the plateau delta) are therefore about
  400x and 57,000x wider than the measured spread. They are left as they were
  argued, deliberately conservative, because they never touch a pass/fail
  limit.
- **The ratified bound is met, with the same razor margin the harness
  reports.** Offline PSRR = Av0 − Avs0: worst point `mos_ff` / 125 °C / 1.32 V,
  1.870894 dB against the ≥ 1.87 dB bound (margin 0.0009 dB; harness 1.8709 dB
  at the same point). The next worst are `mos_ff` / 125 °C / 1.20 V (2.5244 dB)
  and `mos_sf` / 125 °C / 1.32 V (2.9570 dB). Tool and harness agree on the
  binding corner and the verdict, so no verdict difference needs explaining by
  tolerance. This is an offline verdict (Av0 is harness evidence), not a tool
  one.
- **One `klt sim` limit miss, kept as a result.** The envelope's status is
  `fail`: 44 corners pass and `mos_ss` / −40 °C / 1.08 V misses the
  flat-shelf plateau guard, |Avs(10 mHz) − Avs(0.1 Hz)| = 0.06608 dB against
  the 0.05 dB limit (margin −0.01608 dB). It is the same point the harness
  record documents (0.0660786 dB; the comparator cross-checks the harness
  flag and they agree). The harness section above attributes it to this being
the coldest, lowest-rail corner, where the supply zero sits lowest, so the
10 mHz read is still on the skirt of the shelf. The envelope is consistent with
that (it is not an independent test of it): at `mos_ss` the delta is 0.0661 dB
at −40 °C / 1.08 V, falls to 0.0193 dB at 27 °C and 0.0068 dB at 125 °C (same
1.08 V), and to 0.0083 dB at −40 °C / 1.20 V. The guard says how well the
shelf is read; the residual is 0.066 dB on a PSRR of 29.54 dB, 27.7 dB above
the bound, so it cannot change a PSRR verdict. The nearest other point is
`mos_ss` / 27 °C / 1.08 V at 0.0193 dB (inside the limit). Neither the limit nor the shelf read was changed to
  hide the miss.
- Provenance and what the envelope is not: the client was klt 0.6.0 (not
  0.7.0), the grid ran as five per-process shards, each with its cap-corner
  card and OSDI preload moved into the body; the one-corner local prototype
  with the shard body (below) shows that this changes no number. The
  envelope's own `environment.remote.fleet` array carries the five jobs.

### One-corner prototype (supply `alter` interacts with the AC source)

`corners.supply_v`'s `alter vdd=<V>` changes the DC value of the same source
that carries `ac 1`. To check that it keeps the AC magnitude, two single
corners were run locally with `klt sim --backend local` (klt 0.7.0,
ngspice-46, OSDI preflight passing), on a one-corner copy of the request.
These are prototypes, **not envelopes, not committed, and not coverage**.

| Corner | `avs0_db` | `avs_1khz_db` | plateau delta | Harness CSV (`avs0_db`, `avs_1khz_db`, plateau) |
|---|---|---|---|---|
| `mos_tt` / 27 °C / 1.20 V | 35.51667 | 39.65232 | 0.000612 | 35.5167, 39.6523, 0.0006117 |
| `mos_ss` / −40 °C / 1.08 V | 14.77841 | 35.26690 | 0.066079 (limit miss) | 14.7784, 35.2669, 0.0660786 |

Result: `alter vdd` sets the DC value and preserves `ac 1` (the second corner
is off-nominal; both agree with the harness to the CSV's printed digits, and
the known plateau-guard miss reproduces). The comparison tolerance in
`compare.py` (0.02 dB) is a provisional, argued bound (DR-0005's 9.9e-4
cross-host relative current difference moves a gain by at most about
0.017 dB). The committed 45-point envelope has now quantified the per-point
spread (next section): it is 4.96e-5 dB at most.

A third single corner was run locally with klt 0.7.0 on the shard-form body and
request (`mos_ss`, −40 °C, 1.08 V; the pre_osdi and cap-card paths pointed at the
local PDK): `avs0_db` 14.77840504, `avs_1khz_db` 35.26689954, plateau delta
0.06607858 (limit miss), identical to the batch envelope's `mos_ss` point, so
the body-level `pre_osdi`/`.lib` and the inlined DUT change no number.

### Running it

`klt/run.sh` submits the grid to the batch fleet; **never** run the grid
locally on a shared dispatch host (`PSRR_KLT_BACKEND=local` is refused in shard
mode). Before submitting, `sim/preflight.sh` and `sim/tools/build-osdi.sh
--check` must pass. Shard mode needs a client that has the batch backend and
that the runner accepts (`KLT="uvx --from klayout-tools==0.6.0 klt"`); single
mode needs a client whose `klt --version` equals the runner's. Tests:

    python3 -m unittest discover -s sim/cmrr-psrr/klt -p 'test_*.py'

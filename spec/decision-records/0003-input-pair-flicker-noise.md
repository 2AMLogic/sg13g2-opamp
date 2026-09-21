# 0003: Input-pair flicker noise — keep the minimum-length input pair (re-size declined)

- **Status**: decided — this record sets no new spec value and binds no new
  bound: the `[DR-2]` input-referred-noise row it examines stays exactly as
  ratified (worst-case bound `≤ 108.9 µVrms` over `100 Hz – 1 MHz`, flicker
  dominance written into the row itself). It records the design-side answer
  to issue #19's question: a stated decision on whether to re-size the input
  pair for flicker noise, with either outcome fully specified and reversible
  via this record (the same "Decided by: Builder agent" pattern as
  [0001-topology-and-cl.md](0001-topology-and-cl.md), which the two keys later
  carried into force; unlike 0001 there is nothing here waiting on a future
  ratification pass — the keys already ratified the row this decision leaves
  standing).
- **Date**: 2026-09-21
- **Decided by**: Builder agent, issue #19
- **Related**: #19 (the issue this decides), #13 (the noise bench that
  measured the flicker dominance — its `README.md` § "What the flicker
  dominance says about the design" is the observation this decision closes),
  #9 (the sizing pass that set the minimum-length input pair and scoped noise
  out), #5 (the gm/ID study every sizing decision cites, per `CLAUDE.md`),
  #16 / [0002-target-spec-ratification.md](0002-target-spec-ratification.md)
  (the two-key ratification that bound the noise row **at** the measured
  worst case of the committed sizing),
  `spec/target-spec.md` (input-referred-noise row),
  `sim/input-noise/records/20260918-203850-90844d2.csv` (measured evidence),
  `sim/gm-id-characterization/records/20260909-063633-b402592.csv` (the
  "CSV" below)

## Context

`sim/input-noise/` (issue #13) measured this block's input-referred noise
across the full 45-point PVT grid and found the spectrum **flicker
(`1/f`) dominated across the entire chosen `100 Hz – 1 MHz` band**: the
fitted flicker corner is `1.15 – 1.82 MHz` at every corner — *above* the band
top — and the flicker term carries `91.4 – 94.0 %` of the in-band mean-square
noise. The integrated figure is `73.4 – 108.9 µVrms`
(`sim/input-noise/records/20260918-203850-90844d2.csv`; nominal
`mos_tt_27C_1.20V` `87.3 µVrms`, worst `108.9 µVrms` at
`mos_fs_125C_1.08V`), against a fitted thermal floor of only
`17.9 – 28.1 nV/√Hz`.

The direct cause is visible in the committed sizing: `design/opamp_sizing.md`
(issue #9) sized the input pair at minimum length,
`W/L = 3.2 µm / 0.13 µm` (`0.416 µm²` per device), chosen for `f_T`, and that
pass **explicitly did not consider noise** ("Out of scope"). Flicker noise
scales as `1/(W·L)`, so minimum-length input devices put the `1/f` corner
above the whole measurement band.

Two facts frame the decision:

1. **The ratified spec already describes this amplifier, knowingly.**
   [0002](0002-target-spec-ratification.md) ratified one bound per measured
   row **at** the measured worst case — including the noise row, whose
   ratified cell states the flicker dominance, the corner-above-band-top
   fact, and the band choice's dependence on them ("The integrated figure is
   91–94 % flicker-dominated at every corner, so the flicker-worst corner
   binds"). Both keys ratified a bound that encodes the `1/f`-dominated
   spectrum, on record evidence.
2. **Issue #19 exists precisely so this decision is made, not implied.**
   The noise bench deliberately recorded the dominance as measured behavior
   and refused to act on it ("whether to re-size for noise is a design
   decision, not that bench's to make" — `sim/input-noise/README.md`), and
   asked: is a `~1/f`-corner-above-band amplifier the canary block this repo
   wants? A wrong call is expensive in either direction — an unexamined
   noise limitation locked in, or a re-measurement cascade whose cost lands
   only later.

## Decision

**Do not re-size the input pair for flicker noise. Keep `W1 = W2 = 3.2 µm`,
`L = 0.13 µm`** exactly as `design/opamp_sizing.md` committed them. The
flicker-dominated noise spectrum is **accepted as an examined property of the
committed sizing** — recorded here with its rationale and a named re-open
trigger, so it is accepted rather than unexamined, exactly the distinction
issue #19 (and its "not just 'no action taken'" acceptance criterion) asks
for.

The rationale is the quantified trade below, read against what this repo's
ratified spec and canary role actually demand. All first-order estimates in
this section derive from two committed sources only — the measured
`S(f) = A/f + B` fit of `sim/input-noise/records/20260918-203850-90844d2.csv`
and literal rows of the gm/ID CSV, per `CLAUDE.md`'s "every sizing decision
cites it" rule — and are hand computations in the same spirit as
`design/opamp_sizing.md`'s own first-order table: **estimates to size a
*decision*, not simulated claims** (no bench was re-run; claims are only ever
made from committed records).

### What a re-size could buy

Flicker mean-square scales as `1/(W·L)`; the thermal term does not (it is
set by `gm` at the bias point). Holding the committed bias discipline —
branch current `5 µA` per device and `gm/Id ≈ 22 /V`, the level of the
committed row (`nmos,0.13u,mos_tt,0.3900,0.6000,1.560450e-05,3.452262e-04,1.809463e-05,1.355950e-14,22.123503,19.078931,4.052100e+09,0.3598,0.0302`)
— the two natural length steps are:

- **Option A — `L = 0.26 µm` at matched inversion**: CSV row
  `nmos,0.26u,mos_tt,0.3100,0.6000,1.707378e-05,3.609641e-04,1.530449e-05,1.844430e-14,21.141429,23.585503,3.114741e+09,0.2489,0.0611`
  → `W = 10 µm × (5/17.0738) ≈ 2.93 µm`, `W·L ≈ 0.762 µm²` — only
  **1.83×** the committed `0.416 µm²`. First-order consequence: flicker
  coefficient `A → A/1.83`, corner `1.65 MHz → ≈ 0.90 MHz` nominal
  (`1.15 – 1.82 MHz → ≈ 0.63 – 1.00 MHz` grid) — the corner moves **to**
  the band top, not below it in any meaningful sense. Integrated figure
  (scaling the nominal split `87.3 µVrms`, ≈ 93 % flicker): roughly
  `87.3 → ≈ 66 µVrms` nominal; worst corner `108.9 → ≈ 83 µVrms`. In-band
  flicker mean-square share stays `≈ 88 – 89 %`. **Not a qualitative
  change**: a `~1/f`-corner-at-band-top amplifier instead of one above it,
  bought for a ~20 % figure improvement while paying the full re-measurement
  cost below.
- **Option B — `L = 0.52 µm` at matched inversion**: CSV row
  `nmos,0.52u,mos_tt,0.2500,0.6000,7.943278e-06,1.817773e-04,5.989285e-06,2.703020e-14,22.884419,30.350417,1.070312e+09,0.1950,0.0550`
  → `W = 10 µm × (5/7.9433) ≈ 6.29 µm`, `W·L ≈ 3.27 µm²` — **7.9×**
  committed. Corner `1.65 MHz → ≈ 210 kHz` nominal (`≈ 145 – 230 kHz`
  grid); integrated roughly `87.3 → ≈ 38 µVrms` nominal and
  `108.9 → ≈ 47 µVrms` worst (flicker share `≈ 64 %`). Pushing to **20×
  area** reaches `≈ 210 kHz → ≈ 83 kHz` and `108.9 → ≈ 37 µVrms` worst
  (share `≈ 43 %`). The **hard asymptote is the thermal floor** — an
  (unbuildable) corner-at-band-bottom re-size integrates to only
  `≈ 28 – 29 µVrms` at the hot/low-rail points (thermal-only integral of the
  fitted `17.9 – 28.1 nV/√Hz` over the band), i.e. the *maximum* a
  re-size can ever buy is a factor of `≈ 3.8`, and the realistic
  `8 – 20×`-area versions buy `≈ 2.3 – 2.9×`. The thermal floor itself
  cannot be improved by re-sizing: it is set by `gm` at the bias point, and
  the bias budget is pinned by the ratified quiescent-power row
  (`Iq ≤ 119.7 µA` total, `[DR-2]`) — buying thermal headroom means raising
  tail current, which breaks a different ratified bound.

As a check against issue #19's expected trade axes: at matched `gm/Id`,
`gm1` is essentially preserved (`110.6 µS` committed vs
`21.14 × 5 ≈ 105.7 µS` Option A and `22.88 × 5 ≈ 114.4 µS` Option B —
`−5 %` / `+3 %`), so first-order `GBW = gm1/(2π·Cc)`, slew `= Itail/Cc` and
`Iq` are **not** where this trade lands. What a longer input pair actually
costs, per the same CSV rows, is device speed and capacitance: `f_T`
`4.05 → 3.11 → 1.07 GHz` and scaled `Cgg` `4.34 → ≈ 5.4 → ≈ 17 fF` per
device (commit → A → B), plus the area itself. None of these is GBW-limiting
first-order — which is exactly why the real cost is not in the AC rows but
in the evidence lattice (below).

### What a re-size would cost

1. **Every ratified measured row would describe a previous DUT.** All ten
   `[DR-2]` performance rows trace to committed `sim/` records of *this*
   schematic. Issue #19 names the minimum directly affected benches
   (`sim/open-loop-ac/`, `sim/input-offset/`, `sim/input-noise/`); in
   practice the whole measured set is downstream of the same netlist slice
   — CMRR/PSRR join `Av0` per point from `open-loop-ac`, and slew, swing and
   `Iq` read on the same DUT — so each re-run record must be regenerated for
   the rows' evidence to again describe the committed schematic
   (`CLAUDE.md`: `sim/` results are append-only evidence, and no claim
   without a testbench).
2. **A re-run would then face bounds ratified at the old DUT's worst
   case.** Any row that comes back weaker on the new DUT — phase margin
   (larger input-device capacitances at `d1`/`d2`; the `≥ 60°` bound has
   only `16.4°` of measured margin over it), DC gain, spot densities at the
   fast corners — lands exactly on [0002](0002-target-spec-ratification.md)'s
   relax-after-measured-FAIL rule: a bound weaker than a previously ratified
   row needs the market key to explicitly find it still competitive against
   named public parts, or escalate to the operator
   ([2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)). A
   noise-driven re-size would manufacture that confrontation with no
   consumer demand behind it.
3. **`8 – 20×` input-pair area and capacitance**, inherited by the layout
   pass that does not exist yet (the Area row stays `[TBD-12]` precisely
   because no layout exists — the layout would now start from a
   `6.29 µm × 0.52 µm`-class pair instead of `3.2 µm × 0.13 µm`).
4. **Twin comparability.** The band was chosen to match `sky130-opamp`'s
   proposed row for this *same* topology so the three-foundry rows compare
   (`sim/input-noise/README.md` § "Choosing the band"). Each twin derives
   its numbers from its own PDK's committed sizing; a noise-driven re-size
   unique to this block forks its DUT from the shared structural baseline
   the twin rule exists to protect.

### Why the flicker-dominated amplifier is acceptable here

- **The bound is the measurement, and the keys ratified it knowing the
  shape.** The ratified noise row encodes the dominance and the band
  defense in its own cell; nothing is out of compliance, and no row demands
  a noise figure the DUT does not have.
- **On thermal noise this design already matches its twin.** The fitted
  thermal floor (`17.9 – 28.1 nV/√Hz`) brackets `sky130-opamp`'s
  `≈ 30 nV/√Hz` estimate for the same topology
  (`sim/input-noise/README.md`); what differs from the twin is the flicker
  term — a documented consequence of the `f_T`-motivated minimum-length
  choice (#9) that the re-size options above can only partially buy back,
  at `8 – 20×` area, and never past the `≈ 3.8×` thermal asymptote.
- **No consumer exists.** This is a standalone canary block with a bench of
  its own and no named downstream load (the framing [0001](0001-topology-and-cl.md)
  itself used for `CL`); no ratified row, twin expectation, or open issue
  asks for input-referred noise below the bound. Spending the full
  re-measurement + re-ratification + layout-area cost against no demand is
  the low-value shape issue #19 warns against, in either direction.
- **The canary's product is the evidence chain, not the noise number.**
  Per `CLAUDE.md` ("Verification is the product", the friction protocol),
  this repo's deliverable is a fully-tracked PVT lattice of reproducible
  benches — the `.noise` bench is deterministic and byte-reproducible, so
  the measured flicker dominance is not an anomaly hidden in a corner but
  the honest, reproducible signature of this DUT. Keeping the DUT fixed
  preserves that lattice intact; re-sizing restarts it mid-flight, before
  any layout or consumer gives the restart a reason.

### Re-open trigger

This decline is a decision, not a verdict on all futures. A **named
consumer requiring input-referred noise below the `[DR-2]` bound** — a
`1/f`-sensitive application, a fleet-level noise target placed under the
spec by its own decision record, or a twin-comparability ruling that
re-commits the three blocks to a shared noise-motivated sizing — re-opens
this record, and the Option A/B sketch above (matched-inversion lengthening
at fixed `gm/Id`, `A ∝ 1/(W·L)` scaling, `gm1`/`GBW`/`Iq` preserved
first-order) is the concrete starting point for the superseding record, in
the same way `design/opamp_sizing.md` left its `Rz` follow-up.

## Alternatives considered

- **Option A re-size (`L = 0.26 µm`, matched inversion, `1.83×` area) —
  rejected.** Moves the corner to the band top and improves the integrated
  figure ~20 %, without changing the row's `1/f`-dominated character — the
  full re-measurement/re-ratification cost for a non-qualitative gain.
- **Option B-class re-size (`≈ 8 – 20×` area at `L = 0.52 µm`, matched
  inversion) — rejected.** A real (`≈ 2.3 – 2.9×`) improvement toward a
  thermal-floor asymptote of at most `≈ 3.8×`, at the price of regenerating
  the measured rows' evidence, a two-key re-ratification with relax-rule
  exposure on the other rows, `8 – 20×` input-pair area/capacitance, and a
  forked DUT baseline vs the twins — for a consumer-less canary block.
- **Widen `W` only, keep `L = 0.13 µm` — rejected.** At fixed `5 µA`, added
  width deepens weak inversion (raises `gm/Id` toward the `≈ 29.5 /V` peak
  of this length family) instead of preserving the committed bias level —
  eroding exactly the `Vth`-shift margin against `mos_ss`/cold that the #9
  pass chose its `0.0302 V` overdrive to protect (`design/opamp_sizing.md`
  § M1/M2, "Headroom check"), while buying flicker area no faster per
  `µm²` than Option A, which already fails the cost/benefit test.
- **Raise tail current to improve the thermal floor as well — rejected.**
  Orthogonal to the flicker question (thermal `∝ 1/√gm` at fixed `Id`
  budget), and the bias budget is itself a ratified `[DR-2]` bound
  (`Iq ≤ 119.7 µA`); raising it relaxes a ratified row — the exact act
  `CLAUDE.md` forbids to make results pass.
- **Chopper stabilization / HBT input pair — rejected, out of scope by
  construction.** This block is CMOS only absent a decision record opening
  the HBT-input stretch (none exists, per `spec/target-spec.md` §3);
  chopping is a topology change that would supersede
  [0001](0001-topology-and-cl.md) wholesale, not a sizing amendment to it.
- **Leave the question pending (no decision) — rejected.** Issue #19's
  acceptance criteria require a committed, stated decision with rationale
  so the observation is closed rather than left open; deferring is the
  "unexamined property" state this record exists to end.

## Consequences

- The committed input-pair sizing stands: `W1 = W2 = 3.2 µm`,
  `L = 0.13 µm`; `design/opamp_sizing.md`'s device table is unchanged, now
  with an explicit note (in its "Out of scope" section's vicinity) recording
  this decision, so noise stops being an unexamined side effect of the
  `f_T`-motivated sizing.
- The `[DR-2]` input-referred-noise row in `spec/target-spec.md` keeps its
  ratified value and tag; the row now cross-references this record, so the
  dominance in its cell is a examined, accepted design property, not merely
  a recorded measurement. No bound moves — this record neither tightens nor
  relaxes anything.
- `sim/input-noise/README.md` § "What the flicker dominance says about the
  design" closes its own open question by pointing here (and at issue #19).
- Future work touching the input pair knows the one place to start: the
  re-open trigger above, and the Option A/B sketch with it.
- No netlist, schematic, bench, or spec value changes in this record's own
  pass — the deliverable *is* the decision and its cross-references.

## Out of scope

- No schematic or netlist change (`design/opamp_core.sch`,
  `design/netlist/opamp_core.spice` untouched).
- No bench re-run and no new `sim/` record — avoiding the re-measurement
  cascade is the substance of the decision, and records are append-only.
- No spec value or tag change and no two-key re-ratification — nothing
  ratified moves.
- No HBT-input or chopping stretch, and no topology re-opening — CMOS-only,
  per `CLAUDE.md` absent a future record.

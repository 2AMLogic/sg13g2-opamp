# input-cmr — input common-mode range (ICMR) PVT bench

[Issue #21](https://github.com/2AMLogic/sg13g2-opamp/issues/21) —
*sim: input common-mode range (ICMR) characterization bench*. Measures the
input common-mode range of `design/opamp_core.sch` / `design/netlist/opamp_core.spice`
(the DR-1 two-stage Miller-compensated op-amp) across the full PVT grid
this repo's benches share (`cornerMOSlv.lib` `mos_tt/ss/ff/sf/fs` [DR-1] x
`{-40, 27, 125} °C` x `{1.08, 1.20, 1.32} V`, into `CL = 2 pF` [DR-1]),
reporting per corner the lower and upper input common-mode bound, the
mechanism that sets each bound, and — new capability for this repo — a
per-point record of whether the amplifier's own nominal `Vcm = VDD/2`
bias point lies inside the measured range at all.

This is the bench `sim/slew-rate/`'s dev-time study anticipated: that
bench found its measured slew rate collapses 2.6x under a single-ended
drive that merely *moves* the input common mode, because the NMOS tail
device's `Vds` headroom at `Vcm ≈ VDD/2` is tight — exactly the
sensitivity this bench now characterizes directly ([issue #12],
`sim/slew-rate/README.md` "Why an antiphase differential drive"). This
bench filled the spec row that previously did not exist:
`spec/target-spec.md`'s input common-mode range row.

## What this bench measures

The input common-mode range is defined here, operationally, from the
input stage's own DC state: sweep the input common mode `Vcm` with the
differential input pinned at **exactly zero** (both inputs tied through a
0 V source), record the input stage's internal operating point per
sample — `v(tail)` (= `Vds` of the NMOS tail device M5, whose source sits
at VSS; also the pair's common source node), `v(d1)`/`v(d2)` (the pair
drain nodes, `Vds + v(tail)` of the input pair devices), `v(ibias)`
(M5's gate bias, via the diode-connected Mbias it mirrors), and the total
Vdd current — and report, per corner, the maximal `Vcm` interval in
which every input-stage-relevant device provably stays saturated:

- **lower bound** — the `Vcm` where `v(tail)` falls through the measured
  saturation voltage of M5. M5's gate bias is `v(ibias)`, a diode
  voltage set by the external 10 µA alone and therefore **constant
  across the whole `Vcm` sweep**, so one same-bias replica probe per
  grid point fixes the requirement exactly. `Vdsat(M5)` is read at the
  knee of the replica's `Id5(Vds)` curve: the first `Vds` whose
  incremental slope `dId/dVds` has fallen to 10 % of the curve's maximum
  (triode-Ron) slope — an operational criterion of exactly the same kind
  as the output-swing bench's −6 dB rule, stated here openly and
  tunable via `SLOPE_FRAC` for a reviewer re-running a **new, append-only
  record** (the committed record's number is the 0.10 this README
  describes).
- **upper bound** — the `Vcm` where the input pair's `Vds` compresses to
  its own saturation requirement `Vgs − Vth`, with `Vth` measured by the
  replica probe at the pair's **true body bias at the bound** (`Vsb` =
  `v(tail)` there; bulk is VSS in the DUT, so the body effect is real and
  is honoured, not corrected analytically). On DUT observables the
  condition rearranges to `v(d1) − Vcm ≥ −Vth`, which is what the
  crossing search resolves.

The bench carries each bound's **mechanism** as a named per-point
verdict, corroborated by margins: the lower bound's margin columns carry
the pair's own saturation margin at that bound (≥ 0.215 V at every
point of the grid — the pair never binds low-side), and the upper
bound's margin columns carry M5's own margin there (≥ 0.194 V — the
tail never binds high-side). Across the committed record all 45 points
attribute the lower bound to `m5_headroom` and the upper bound to
`pair_saturation` — the two mechanisms `design/opamp_sizing.md`'s
"Headroom check" analysis and issue #21's acceptance criteria name.

### Open-loop common-mode sweep, not a closed-loop buffer

A unity-gain buffer (output fed back to the input, ramp the input
rail-to-rail) masquerades as the obvious ICMR bench, and it cannot
locate the input stage's saturation edge: a buffer's DC incremental
tracking gain `dVout/dVcm` stays within ~1.3 % of unity while the
open-loop DC gain `Av` is above its measured worst-corner value
(`Av0` = 77.6 V/V, `sim/open-loop-ac/`), and only collapses to 1/2 — a
"stops tracking" event — once `Av` itself has already fallen to ~1 V/V,
~38 dB below the design's measured worst-case `Av0`. By the time a
buffer visibly stops tracking, the input stage has long been fully
degenerate; a buffer-tracking criterion would report wherever ~0 dB of
residual open-loop gain happens to survive, not the input stage. The
mirror image of this argument is exactly why `sim/output-swing/` chose
an open-loop differential sweep over a buffer sweep for the *output*
stage (its README.md "Open-loop transfer curve, not a closed-loop
buffer sweep").

With `Vid` pinned at exactly zero, the input stage's DC bias is
well-posed by symmetry: the pair branches are mirror-balanced (`d1`/`d2`
held by the M3/M4 diode mirror), so the input-stage state per `Vcm`
sample is a direct function of the common mode alone. The output *does*
rail in this configuration (there is no feedback) — that is expected,
harmless to the input-stage state, and recorded in the committed scan
curves as supporting evidence (the total supply current column shows
the front-end starvation at the lower bound directly).

### Why measured replica probes, not model op-point queries

This tree's OSDI/PSP103 build exposes no OP-info interface —
`@m.xm…[vdsat]`-style model op-point queries fail with "no such device
or model name"; `sim/gm-id-characterization/README.md` "Why
finite-difference DC/AC, not model op-point queries" documents the same
wall. Both bound-setting devices therefore get their requirement
**measured** from the PDK's own device I-V curves, per
`testbench/tb_cmr_mech.spice.tmpl`, at the DUT's own operating bias,
corner and temperature:

- **Tail (M5, `sg13_lv_nmos` w=2.2u l=0.52u).** The probe reproduces
  the DUT's `ibias` node exactly — its own diode-connected Mbias replica
  of the same geometry carrying the same external 10 µA settles at the
  same `Vgs`, machine-checked against the main sweep's `v(ibias)`
  (agreement: 0.000 V at every point of the committed record; any
  mismatch beyond 1 mV fails the point) — and an M5 replica with
  source=bulk=VSS (Vsb = 0, exactly as in the DUT) yields `Id5(Vds)`.
  The 0.52 µm device has a genuine saturation knee, so the slope-based
  knee rule above is well-defined: on the committed curves the knee sits
  at `Vds` = 0.11 V (−40 °C) / 0.135 V (27 °C) / 0.18 V (125 °C) at the
  TT corner, consistent with `design/opamp_sizing.md`'s own
  "≈ its overdrive, 0.155 V" paper estimate for this device at 27 °C.
- **Pair (M1/M2, `sg13_lv_nmos` w=3.2u l=0.13u; one geometry, one
  replica serves both).** At L = 0.13 µm the knee rule is undefined —
  DIBL keeps a large slope component long past the physical edge, so no
  slope fraction ever crosses — so the pair's requirement is read from
  the saturation condition itself, `Vds >= Vgs − Vth`, with `Vth` per
  this repo's own gm/ID convention (constant-current threshold,
  `Id = 100 nA × W/L` at the replica geometry = 2.4615 µA, log-Id linear
  interpolation — exactly `sim/gm-id-characterization/run_gmid_sweep.sh`'s
  Vth definition), re-measured here at the DUT's own body bias, corner
  and temperature. `design/opamp_sizing.md`'s sizing methodology rests
  on the same `Vgs − Vth` overdrive chain, so the criterion is
  kind-consistent with the documentation the bounds are sanity-checked
  against.

### The pair-saturation fixed point

The pair's `Vth` depends on its body bias (`Vsb = v(tail)`), which
itself moves ~1:1 with the bound — a circular dependence this bench
closes with a bounded fixed-point loop: a probe's `Vth` re-locates the
coarse crossing, whose tail bias re-seeds the next probe's body bias,
until the crossing moves < 2 mV (contraction is ~10x per round, so two
rounds after the centre-bias seed typically suffice; hard cap is four
rounds). The fine pass then resolves the bound at 250 µV, and a **final
verification probe at the recorded bound's own body bias** must
reproduce the bound within two fine steps (0.5 mV) — `hi_converged`, a
hard per-point check; the round-to-round shift is recorded per point.
Across the committed record the largest final residual is 0.38 mV.

### Two passes (coarse locate, then fine read)

Per grid point: a coarse full-span sweep (`Vcm` from `VDD−50 mV` down
to `50 mV` at 5 mV — both hard degenerate ends provably inside the
window) locates each bound's crossing (innermost-crossing scan from the
in-range side, so a degenerate re-entry cannot widen the range), then a
fine pass per side (`±12 mV` around the locate, 250 µV step) resolves
the bound. A bound touching its fine window's edge is rejected as a
window artifact — the same rule `sim/output-swing/` applies to its
linear-region boundaries.

### Bias and load conventions

Identical to every other circuit-level bench in this tree: the external
ideal 10 µA `ibias` source sunk from Vdd through the DUT's own
diode-connected Mbias (`design/opamp_sizing.md` "Bias scope"), `CL = 2 pF`
[DR-1] attached for environment parity (no DC effect), no resistive
load. The testbench `.include`s the DUT's flat netlist directly (same
convention as the siblings; `testbench/tb_cmr.spice.tmpl`'s method block
documents the details), and the runner freezes a copy of
`design/netlist/opamp_core.spice` into the record's snapshot directory
plus a geometry lockstep guard — the replica probe templates hard-code
the DUT's XM1/XM2 and XM5/Mbias geometries and the runner fails if the
DUT netlist ever drifts from them.

## Per-point sanity checks

Every grid point must pass all of these (the runner prints each failed
check's name to the corners log; 45/45 pass in the committed record):

1. `v(ibias)` constant across the whole sweep (≤ 1 mV spread) — it is a
   diode voltage set by the bias current alone; movement means the bias
   leg or the sweep misbehaved.
2. The replica-reproduced bias matches the DUT's own `v(ibias)` (≤ 1 mV).
3. All probes resolved requirements in plausible bands (`Vdsat5` in
   (0, VDD/2); each `Vth` in (0.05, 0.8) V).
4. Each bound located uniquely on its side and strictly inside its fine
   window; the hi bound located by both coarse passes (seed and
   re-locate).
5. Bounds form a coherent separated interval (span > 50 mV) and the
   pair's verification probe reproduced the bound within 0.5 mV
   (`hi_converged`). Whether `Vcm = VDD/2` itself lies **inside** the
   interval is deliberately *not* a gate — see "The low-rail finding"
   below; it is recorded per point (`contains_vcm`, `centre_gap_lo_v`).
6. The centre op point's front-end nodes sit in plausible bands (the
   output is *expected* to be railed: open-loop configuration).
7. The bound-setting and verification probes' `Vth` values agree within
   5 mV (the residual coarse-vs-fine seed gap).

## Cross-checks (logged, not gated)

- **`sim/open-loop-ac/` join** — the centre op point (`Vcm = VDD/2`) of
  this bench's own sweep, joined per `point_id` against the AC bench's
  committed per-point operating point. `x_vibias_ac_delta_v` is 0.000 V
  at every point — the bias network state is identical. `v(tail)` and
  `v(d1)` differ by 2–16 mV across the grid (8.1–16.0 mV and 1.9–13.8 mV
  measured), tracking the systematic offset scale: the AC bench's servo
  holds `inn = out ≠ inp` (a vos-scale split between the pair gates),
  while this bench pins `Vid = 0` exactly, so the front-end sits at a
  slightly different (vos-scale) bias point. `v(d2)` differs by far
  more, 0.156–0.230 V: `d2` is the first-stage output node (the output
  PMOS's gate, per `design/netlist/opamp_core.spice`), so its value is
  set by the loop/load condition each bench imposes — servo-balanced in
  the AC bench, railed through the output stage in this open-loop
  bench — not by the pair-gate split. These deltas are measured and the
  record's columns (per node) exist so a reviewer can see each one's
  size for what that node is, not as a defect.
- **`sim/output-swing/` join** — the closed-loop-buffer usable interval
  (`buffer_use_lo/hi/span`): a unity-gain buffer at input `Vcm` needs
  the output to reach `Vcm` too, so the usable interval is the
  intersection of this bench's ICMR with the output stage's own
  measured −6 dB reach at the same `point_id`. At the 1.08 V rail the
  output's high-side reach clips the interval at several corners —
  `buffer_use_span_v` worst 0.161 V at `SS / 125 °C / 1.08 V`.
- **Supply-current evidence** — `ratio_ivdd_lo_c_a` compares total Vdd
  current at the lower bound against the centre op point. At
  in-range-centre points it reads 0.88–1.0 (the front end carries
  slightly less current at the starved-tail edge); at the 15 low-rail
  points whose centre lies *below* the measured range it exceeds 1
  (worst 1.49) — the centre itself is the more starved bias point
  there, which is the low-rail finding in one column, corroborated by
  `sim/input-offset/`'s committed per-point tail-voltage columns
  (`vtail_sample_v` as low as 0.073 V at `TT / −40 °C / 1.08 V`).

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
test -d "$PDK_ROOT/$PDK/libs.tech/ngspice/osdi" || sim/tools/build-osdi.sh
sim/input-cmr/run_cmr_sweep.sh
```

Requires ngspice on PATH plus the OSDI device models
`sim/tools/build-osdi.sh` builds (see `sim/README.md`); does not require
xschem or klt at run time. A full 45-point run takes a few minutes on
this host (ngspice-46). Overrides: `SLOPE_FRAC` (M5 knee fraction,
shipped 0.10), `AC_RECORD_CSV` / `SWING_RECORD_CSV` (sibling-record
joins). Any override mints a NEW record directory (append-only
convention); it never rewrites the committed one.

## What was actually measured (this repo's committed record)

Record `records/20260921-174405-65f5fb4.{csv,md}` — 45/45 points
converged, 0 per-point sanity failures, mechanism attribution
`m5_headroom` (lower) / `pair_saturation` (upper) at every point:

```
worst ICMR span        0.2532 V at SS / 125 °C / 1.08 V
best  ICMR span        0.6769 V at FF / −40 °C / 1.32 V
worst lower bound      0.6401 V at SS / −40 °C / 1.08 V
worst upper bound      0.7954 V at FS / 125 °C / 1.08 V
measured Vdsat(M5)     0.11 V (−40 °C) / 0.135 V (27 °C) / 0.18 V (125 °C) at TT
largest fp residual    0.38 mV (verification probe at the recorded bound)
```

Per-corner bounds, margins, requirements, and joins are in the record's
CSV; the raw coarse/fine scan curves and replica-probe I-V curves each
number was read from are in `corners/<record-id>/`, with the rendered
netlists in `netlist-snapshots/<record-id>/`.

### The low-rail finding

At every 1.08 V corner except the fully-fast ones (`ff` at all three
temperatures, `fs` at 125 °C), and at four slow-corner 1.20 V points
(`ss` at all three temperatures, `sf` at −40 °C), the DR-1's own
nominal `Vcm = VDD/2` bias point lies **below** the measured lower
bound — mid-rail input common mode starves the tail device past its
saturation knee before the range even starts. The worst gap is 100 mV
(`SS / −40 °C / 1.08 V`: bound 0.6401 V vs mid-rail 0.54 V); several
points miss by only a few mV (`fs / 27 °C / 1.08 V`: +2.6 mV,
`ss / 125 °C / 1.20 V`: +4.7 mV), so the miss is a PVT envelope, not a
design-wide failure. This is the quantitative confirmation of the
tail-headroom sensitivity `sim/slew-rate/`'s dev-time study observed
(issue #12; issue #21's own `## Problem`): the sizing pass's paper
"Headroom check" estimated `Vgs(M1) + Vov(M5) ≈ 0.545 V` of lower bound
at the 1.08 V rail, and the measured bound disagrees in the direction
the slew bench's drive-amplitude study already pointed — the paper
chain was ~23 mV optimistic at `TT / 27 °C / 1.08 V` (measured 0.568 V,
mostly because the real `Vgs(M1)` is ≈ 0.43 V, not the 0.39 V assumed)
and up to 95 mV optimistic at the slow/cold/low corner — the real
`ov5`-headroom margin at mid-rail there is negative, so a usable 1.08 V
design needs either a higher input common mode than VDD/2, a
higher-overdrive tail re-bias, or explicit acceptance of a tail device
in its knee region at these corners (with the CMRR/slew consequences
that follow).

### Measured vs. predicted binding corner (honest comparison)

`design/opamp_sizing.md`'s headroom analysis predicted the slow/cold
low-VDD corner binds the input stage; **confirmed** — the measured
worst lower bound is `SS / −40 °C / 1.08 V`, the same point that binds
slew rate (`sim/slew-rate/`), and the whole lower-bound family moves
with `Vgs(M1)` (SS > TT > FF, cold > hot, as expected from a threshold
shift carried into a source-follower chain). No prediction existed for
the upper bound; the measured worst upper bound binds at
`FS / 125 °C / 1.08 V` — the same corner family that binds DC gain,
GBW, input-referred noise, systematic offset and CMRR in
`spec/target-spec.md`'s rows — via the same low-VDD front-end weakness
(`v(d1)` sits lowest and `v(tail)` highest relative to the requirement
there). The supply axis binds both ends simultaneously (every worst
figure lands at 1.08 V), matching the low-VDD convention of the
output-swing and Iq rows.

### Measured vs. `design/opamp_sizing.md`'s first-order headroom analysis

The sizing pass's own numbers, re-derived against the measured record:
`Vgs(M1)` ≈ 0.39 V assumed vs ≈ 0.43 V measured (TT/27 °C, both rails);
the tail's saturation requirement "≈ overdrive 0.155 V" vs the
knee-criterion's 0.135 V at 27 °C TT — same order, with the knee
criterion (an edge-of-triode statement) landing slightly inside the
paper's constant-current-overdrive convention, exactly as expected for
a PSP device. Chain-summing measured quantities is a first-order
consistency check, not a fine-step reproduction: `Vgs(M1)` from the
centre operating point plus `Vdsat5,knee` lands 2.5–35.2 mV above the
measured lower bound across the in-range points (worst at the high
rail, because the pair's `Vgs` is not actually constant across the
sweep — it rises toward the hi compression edge, which is also why the
record's `vgs1_hi_v` + `vdsat5_meas_v` chain runs 59–127 mV above
`icmr_lo_v`). Only the at-the-crossing form — `Vcm_lo = Vgs(M1 at the
bound) + Vdsat5`, with the `Vgs` taken at the bound itself — closes to
the fine step, and that is these bounds' own definition, not an
independent chain. The record's `vtail_lo_v` column lets any reviewer
verify the crossing sample sits within one fine step (250 µV) of the
measured knee, and the hi bound's
`v(d1) − Vcm ≥ −Vth` form is the paper's `VDD − |VSG3| + Vth(M1)`
chain algebra rearranged onto measured nodes.

## What this bench does not claim

- **Nominal devices only.** Perfectly matched geometry — no mismatch
  Monte Carlo, no random samples. A real part's ICMR bounds shift with
  the same random threshold mismatch that dominates the offset row's
  statistical half; a mismatch-inclusive ICMR would need the same
  follow-on treatment as #17 (offset MC) / #26 (CMRR MC).
- **Not a closed-loop usability verdict.** The bounds are the *input
  stage's own* saturation-limited range at each PVT point. Nothing here
  says a buffer/type-any closed loop regulates at every point inside
  the interval (loop gain, the output stage's reach — see the
  `buffer_use_*` join columns — and transient/slew behaviour at that
  bias all qualify it); the `buffer_use_*` columns state only the
  DC-reach intersection.
- **"Saturation" is criterion-explicit, not model-oracle.** The two
  operational edge definitions (10 %-of-max-slope knee for the 0.52 µm
  M5; `Vgs − Vth(CC)` for the 0.13 µm pair, this repo's gm/ID Vth
  convention at the true body bias) are stated openly above, are
  measured from the PDK's own device curves with the raw curves
  committed, and are deliberately different because the two devices'
  physics differ. Other defensible conventions (e.g. an overdrive-based
  M5 criterion, which reads ≈ 50 mV higher and would push the lower
  bounds up correspondingly) can be re-derived from the same committed
  curves — the record's value columns carry everything needed — but
  the committed numbers are the definitions stated here, applied
  uniformly across the grid. A criterion re-run mints a new record; it
  does not change this one.
- **No transient behaviour.** DC only — settling, CM-step response and
  the slew interaction with common-mode position are other benches'
  scope (`sim/slew-rate/` for the drive-position part of that story).
- **DC loads only in spirit.** No resistive load is attached (fleet
  convention; a loaded-ICMR decision is separate), and `CL` is present
  purely for environment parity — it has no effect on a DC analysis.

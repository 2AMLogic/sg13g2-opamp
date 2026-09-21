# output-swing — DC output-swing PVT bench

`sim/output-swing/` measures the DC output swing of
`design/opamp_core.sch` (`design/netlist/opamp_core.spice`) — the
maximum/minimum DC output voltage the amplifier can reach into
`CL = 2 pF` [DR-1] **while still tracking its input** — across the full
cornerMOSlv.lib process x temperature x supply grid
(`mos_tt/ss/ff/sf/fs` x `{-40, 27, 125} °C` x `{1.08, 1.20, 1.32} V` =
45 points), the same grid every other `sim/` bench in this repo runs.
This is the bench behind `spec/target-spec.md`'s output-swing row
(`[TBD-10]` until this experiment existed), and the last of the
"classic rows" that name a single testbench measurement.

## What this bench measures

**Output swing, operationally**: from the open-loop differential DC
transfer curve `Vout(Vid)` — `Vid = V(inp) − V(inn)`, input common mode
pinned at `Vcm = VDD/2` — the linear region's rail-ward **bounds**:
beyond them the amplifier's incremental gain has collapsed and the
output no longer tracks the input. Both bounds are reported **as headroom
from the rail** (VDD − Vout_max, Vout_min − VSS), not as absolute volts,
per the row's own requirement, so the same record compares directly
across the `{1.08, 1.20, 1.32} V` supply grid.

Physically, the two bounds are set by this topology's output stage
(`design/opamp_sizing.md` "Stage 2"): `M6` (PMOS output gain device,
`source = vdd`, `drain = out`) bounds the **high** rail — as `Vout`
rises toward VDD, `M6`'s `Vsd` collapses toward its saturation/triode
edge and its incremental gain falls; `M7` (NMOS output current sink,
`drain = out`, `source = vss`) bounds the **low** rail the same way as
`Vout` approaches VSS. The bench deliberately drives the **input**
into its safe common-mode range throughout (below), so both measured
bounds reflect the output stage, not the input pair.

## Method

### Open-loop transfer curve, not a closed-loop buffer sweep

`testbench/tb_swing.spice.tmpl` uses
`sim/input-offset/tb_offset_null.spice.tmpl`'s differential-drive
convention: one common-mode source plus two B-sources,

```
V(inp) = Vcm + Vid/2      V(inn) = Vcm - Vid/2
```

so the input common mode stays **exactly** at `Vcm = VDD/2` for every
swept `Vid`. The resulting `Vout(Vid)` is a monotonic saturating S-curve:
hard-railed low for `Vid` far below the linear region, hard-railed high
for `Vid` far above, a steep high-gain linear region in between (whose
center — the single `Vout = Vcm` crossing — is exactly
`sim/input-offset/`'s offset number for the same grid point).

The alternative a closed-loop unity-gain buffer sweep (wire `out` to
`inn`, ramp the input rail-to-rail, watch where the output stops
following) was rejected for a structural reason: in a buffer the output
**is** the input common mode, and this design's input pair has its own
common-mode range problems (its tail node needs `Vgs(M1) + Vov(M5)` of
headroom below the lowest usable input level) that bind at *least* as
early as the output stage does on the low rail. A buffer therefore
measures where the **input stage** leaves its range, understating the
output stage's true swing. Pinning the input common mode at `Vcm` —
where the input pair provably amplifies at every grid point
(`sim/input-offset/` and `sim/open-loop-ac/` both recorded sane
operation there) — makes the measured bounds output-stage properties,
which is what the spec row means by "output swing".

No feedback is used (unlike `sim/open-loop-ac/`'s `Lbreak` DC servo):
the DC operating point of the standalone open-loop amplifier is
ill-posed only in the sense that its output rails away from the linear
region — precisely what a transfer-curve swing bench wants to see. Each
`.dc` point solves directly; `CL` is attached for DUT-environment parity
with the rest of the tree but has no effect on a DC analysis.

### The swing criterion (the number's definition)

"Still tracking the input" needs a threshold, and the threshold is part
of the number. This bench reads both bounds at the **−6 dB
incremental-gain boundary**: the outermost sweep points around the
peak-gain point whose two-point incremental gain
`dVout/dVid` is still ≥ **½ of the curve's own peak** incremental gain.
The `Vout` values at those boundary samples are `vout_max_track_v` /
`vout_min_track_v`; everything beyond them has the amplifier perceiving
less than half its nominal gain.

Why −6 dB, concretely: it is the classic half-gain compression point of
a DC transfer curve — far enough inside the rails that the number means
"an amplifier, not an emitter follower" (the −3 dB-in-power analogue of
small-signal specs), while not a knife-edge criterion like
"gain has dropped by 1%" that would sit at the exact saturation edge
where model noise and step size dominate. The criterion fraction is a
knob (`CRITERION_FRAC` in `run_swing_sweep.sh`, documented as 0.5 here)
so a reviewer can re-run at a stricter/looser criterion and mint a new
record under the append-only convention — but **the committed record's
numbers are the 0.5 (−6 dB) criterion's numbers**, and
`spec/target-spec.md`'s row states the criterion where it cites them.
A swing figure quoted without its criterion is as incomplete as the
noise row would be without its band.

### Two passes (coarse locate, then fine read)

Per grid point, `run_swing_sweep.sh` renders the one template twice:

1. **Coarse** — `Vid` swept `± 100 mV` at `500 µV` steps (401 points,
   the same window `sim/input-offset/` uses to prove the crossing
   unique), recording `v(out)` only. Locates the linear region's center
   and reads both **hard-clipped plateau levels** (`vout_clip_high_v` /
   `vout_clip_low_v`) — the raw reach, deliberately kept distinct in the
   record from the tracking bounds.
2. **Fine** — `Vid` swept `± 25 mV` around the coarse crossing at
   `10 µV` steps (5001 points), recording `v(out)` and `i(vdd)`. The
   linear region spans well under 12 mV of `Vid` everywhere on this grid
   (measured `Av0` is 77.6–181 V/V per `sim/open-loop-ac/`), so ±25 mV
   brackets both −6 dB boundaries with >4x margin; the 10 µV step keeps
   each boundary read to ~1–2 mV of output volts at the worst gain.

### Bias and load conventions

Identical to `sim/open-loop-ac/`'s and `sim/input-offset/`'s, so all
benches bias the same DUT the same way: external ideal
`ibias = 10 µA` sunk into the DUT's `Mbias` node, per
`design/opamp_sizing.md` "Bias scope". `CL = 2 pF` [DR-1] attached at
`out` (DC analysis: no effect on the result, DUT-environment parity
only). **No resistive load** — see "What this bench does not claim".

## Per-point sanity checks

A grid point's row enters the record with `op_pass = 1` only if every
rule below holds (failures are still recorded, flagged `op_pass = 0`,
and named in the record's `sanity_checks.txt`; the grid must stay
complete either way — a missing point is a hole in the evidence, not a
"bad point"):

1. **Unique crossing** — exactly one `Vout = Vcm` crossing in the coarse
   sweep (the same uniqueness rule as `sim/input-offset/`'s coarse pass).
2. **Real clipping, judged by slope ratio** — the coarse curve's own
   peak segment gain is computed, and both window ends must sit on parts
   of the curve whose incremental slope is ≤ 1% of that peak. An
   *absolute* millivolt-flatness rule was tried first and is **wrong at
   hot corners**: at 125 °C the "railed" output still creeps
   ~0.3 mV per mV of `Vid` (leakage-fed), which is ~10⁻⁶ of the peak
   gain — clearly clipped — but breaches any absolute mV threshold.
3. **Crossing strictly inside the fine window** — an edge crossing would
   mean the coarse locate was wrong by more than the fine half-span and
   the fine read is not trustworthy.
4. **Monotonic fine curve** — `Vout` never decreases (beyond 1e-9 V of
   fp wiggle); a non-monotonic transfer curve would make "the linear
   region" ambiguous.
5. **Plausible peak gain** — the fine curve's peak incremental gain is
   ≥ 10 V/V (same floor as `sim/input-offset/`'s local-gain rule).
6. **−6 dB region strictly inside the fine window** — an edge-touching
   region would mean the window truncated the boundary and the reported
   bound is an artifact of the window, not the amplifier.
7. **Physical bounds** — both headrooms strictly positive and strictly
   inside the supply span; the tracking bounds strictly inside the
   hard-clip plateau levels (the −6 dB point lies before the plateau by
   construction); the plateaus straddle mid-rail.

## Cross-checks (logged, not gated)

Every grid point joins the already-merged sibling records on `point_id`,
and the record carries the comparison columns:

- `vos_crossing_v` vs `sim/input-offset/`'s `vos_null_v` — the same
  DUT, grid, drive configuration and crossing definition, measured by an
  independent bench: they agree to **≤ 0.65 nV** across all 45 points
  (both are interpolations of the same deterministic DC solution, so
  this is a strong convergence check, not an independent-physics one).
- `peak_inc_gain_v_v` vs `sim/open-loop-ac/`'s `av0_db` (`av0_ratio`):
  **1.017–1.255** across the grid — the incremental DC gain sits within
  ~2–26% of the AC bench's 1 Hz gain at the same point, the expected
  small bias-point/analysis difference.
- `ivdd_center_a` vs `sim/open-loop-ac/`'s `ivdd_total_a` (`ivdd_ratio`):
  **1.0041–1.0098** — the mid-swing supply current matches the AC
  bench's operating-point current to under 1%.

A large disagreement in these columns would not be filtered out
automatically (they are diagnostics, not gates) — it would show up when
the record is read, with the per-point data to trace it.

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time: build the OSDI models
sim/output-swing/run_swing_sweep.sh
```

`PDK_ROOT`/`PDK` may also be left unset if the PDK is installed under one
of the usual prefixes `sim/env.sh` checks. Requires ngspice on PATH plus
the OSDI models `sim/tools/build-osdi.sh` builds; does not require xschem
or `klt` at run time (`design/netlist/opamp_core.spice` is committed,
pre-netlisted — see `design/README.md`). The pinned PDK revision every
record targets is `sim/pdk.json`.

Writes append-only evidence under `corners/<record-id>/` (per-point
ngspice logs + coarse/fine transfer-curve CSVs + `sanity_checks.txt`),
`netlist-snapshots/<record-id>/` (the exact DUT netlist copy and both
rendered testbenches) and `records/<record-id>.{csv,md}`. A re-run mints
a new timestamped record; nothing under `records/`, `corners/` or
`netlist-snapshots/` is ever edited or deleted after it lands.

## What was actually measured (this repo's committed record)

Committed record: `records/20260921-151759-707b34c.{csv,md}` — 45 of 45
points simulated, 45/45 passing the per-point sanity checks, ngspice-46
against PDK tag `v0.3.0` (`sim/pdk.json`). All numbers below are from
that record, at the −6 dB incremental-gain criterion.

**By supply rail** (worst/best over the 15 process x temperature points
at each supply):

| Supply | headroom from VDD | headroom from VSS | tracking span |
|---|---|---|---|
| 1.08 V | 251.5 – 307.8 mV | 141.2 – 206.8 mV | 571.0 – 687.3 mV |
| 1.20 V | 260.0 – 310.6 mV | 145.8 – 215.0 mV | 674.4 – 793.9 mV |
| 1.32 V | 268.6 – 319.1 mV | 151.1 – 223.1 mV | 777.9 – 900.1 mV |

**Extremes across the grid**:

- Worst span: **571.0 mV** (`Vout` 0.206–0.777 V) at `mos_ss / 125 °C /
  1.08 V`. The four next-worst spans are all also `125 °C / 1.08 V`
  points (`fs`, `tt`, `sf`, `ff` in order — 572.1–578.3 mV), so at the
  binding supply the hot end dominates the process axis for span.
- Worst high-rail headroom: **251.5 mV** at `mos_fs / −40 °C / 1.08 V`.
- Worst low-rail headroom: **141.2 mV** at `mos_ff / −40 °C / 1.08 V`.
- Best span: **900.1 mV** at `mos_ff / −40 °C / 1.32 V`.

The hard-clipped reach is much wider than the tracking bounds (e.g. at
the nominal `mos_tt / 27 °C / 1.20 V`: reach 4.3 µV – 1.116 V vs.
tracking 0.173 – 0.919 V) — the amplifier's output can be *pushed*
rail-ward, but it stops *amplifying* hundreds of millivolts before the
plateaus; both are recorded, and the spec row quotes the tracking
bounds, not the reach.

### Measured vs. predicted binding corner (honest comparison)

`spec/target-spec.md`'s prediction for this row was "low VDD / worst
output-stage headroom corner". Measured: **confirmed on the supply axis
and corrected on the process/temperature axis**. Every worst figure —
worst span, worst per-rail headroom — lands at 1.08 V, the low end of
the supply grid, exactly as predicted. But no single process x
temperature point binds both rails **and** the span: the worst span
sits at `mos_ss / 125 °C` (hot), while the worst *high-rail* headroom
(`fs / −40 °C`) and worst *low-rail* headroom (`ff / −40 °C`) sit at
cold split corners — the per-rail worsts and the span worst are three
different points. The pre-schematic prediction named only the supply
axis, so it was right as far as it went; a finer prediction would also
have had to commit to an axis (span vs. per-rail headroom) that this
measurement now shows to be mixed.

## What this bench does not claim

- **Unloaded swing.** No resistive load is attached at `out` (only
  `CL = 2 pF` [DR-1], which a DC analysis ignores). A loaded swing
  bench (voltage swing into a stated `RL`) would need the output stage
  to *source/sink* current at the rails, and its numbers would be
  strictly smaller. Loaded swing is a separate bench with its own row
  decision, not covered by this record.
- **DC only.** This is the DC transfer curve's tracking bounds. Whether
  the amplifier can *settle at* those bounds through large-signal
  motion that first slews (the `sim/slew-rate/` bench's regime) is a
  different question this record does not address.
- **Ideal bias.** The 10 µA `ibias` reference is an external ideal
  source per `design/opamp_sizing.md` "Bias scope", like every other
  bench in this tree — a real bias generator adds its own variation
  outside this record's evidence.
- **Deterministic corners only.** Every device is nominal (no mismatch
  deck, no Monte Carlo; same caveat as `sim/input-offset/`). Random
  device mismatch shifts the output stage's current balance and can
  move these bounds; no statistical basis is claimed here.
- **No per-device operating-point claims.** This OSDI/PSP103 build
  exposes no queryable per-device op-point parameters
  (`sim/gm-id-characterization/README.md` "Why finite-difference DC/AC,
  not model op-point queries") — the M6/M7 saturation narrative above is
  design context from `design/opamp_sizing.md`, corroborated by the
  measured per-rail asymmetry, not a per-device measurement.
- **The criterion is a choice.** The −6 dB boundary is stated, defended
  and re-runnable, but it *is* the number's definition — see "The
  swing criterion"; quoting these figures without it is not a testable
  claim.

# open-loop-ac

Standalone open-loop AC characterization of `design/opamp_core.sch`'s
two-stage Miller-compensated op-amp (issue #9), across the full PVT grid,
into `CL = 2 pF` [DR-1]. This is the first `sim/` bench built on the DR-1
topology and `design/opamp_sizing.md`'s gm/ID sizing pass — it exists to
check whether that first-order sizing actually delivers a working amplifier
before any classic-row spec target is proposed against it.

## What this bench measures

For every point on the `cornerMOSlv.lib` `mos_tt/ss/ff/sf/fs` [DR-1] x
temperature `{-40, 27, 125} °C` x supply `{1.08, 1.20, 1.32} V` grid
(45 points):

- **Av0** — open-loop DC gain (dB), read at the lowest swept frequency
  (1 Hz).
- **GBW** — unity-gain (0 dB) crossover frequency, into `CL = 2 pF`.
- **Phase margin** — `180° + phase` at that crossover (see "Sign
  convention" below for why `180°`, not the loop-gain convention's
  reference).
- **Gain margin** — `-gain(dB)` at the first `-180°` phase crossing above
  the unity-gain frequency, if the sweep (1 Hz - 1 GHz) resolves one.
- **Iq** — total DC current drawn from `Vdd` (`ivdd_total_a`), and
  separately the same figure minus the fixed `10 uA` `ibias` reference
  current (`ivdd_signal_path_a`) — see `design/opamp_sizing.md`'s "Iq
  reporting note" for why these are reported as two numbers, not one.
- **DC operating point** (`vout_dc_v`, `vd1_dc_v`, `vd2_dc_v`,
  `vtail_dc_v`, `vibias_dc_v`) and a per-point pass/fail sanity check
  (`op_pass`) — see "Per-point sanity checks" below.

## Method

### DC bias / AC loop-break: the large-inductor trick

A standalone open-loop op-amp has an ill-posed DC operating point without
some form of external stabilization — its own DC gain, if achievable at
all in an ideal sense, would drive the output to a rail for any nonzero
input offset. `testbench/tb_openloop_ac.spice.tmpl` uses the same class of
trick this issue names ("the standard large-L/large-C feedback trick, or
an ideal servo"): an ideal inductor `Lbreak = 1e18 H` from `inn` (inverting
input) to `out`. An ideal inductor is a dead short at DC regardless of its
inductance, so `Lbreak` forces `inn = out` at DC; with the amplifier's own
large open-loop gain, this self-consistently settles near a unity-gain
buffer's bias point (`Vout(dc)` close to `Vinp(dc) = Vcm = VDD/2`) — the
same self-bias a real closed-loop configuration would reach, without
loading the AC response the way a real (finite) feedback network would.

**Choosing `Lbreak`**: the value matters, and a much smaller one *does not
work here*. `inn`'s only other AC path to ground is `M1`'s own gate
capacitance (`Cgg`, femtofarad-scale). At `Lbreak = 1e9 H` (the value
`sg13g2-bandgap/sim/loop-gain-phase-margin/`'s *different* loop-gain
measurement uses successfully), the `Lbreak`-`Cgg` corner frequency lands
within this sweep's own 1 Hz - 1 GHz range (confirmed empirically during
this issue's dev-time prototyping: with `Lbreak = 1e9 H`, the low-frequency
`Av0` plateau this bench needs to read is visibly corrupted — near 0 dB at
1 Hz instead of the real plateau value, only recovering the true DC gain
well above the corner frequency). `Lbreak = 1e18 H` pushes that corner
frequency far below 1 Hz, restoring a flat, cleanly-readable low-frequency
plateau across the whole grid — confirmed against every one of the 45
committed points below (`gm-id`-style dev-time verification, not itself a
committed record, since this observation is about testbench construction,
not the DUT).

### Sign convention

The AC test signal (`1 V`, so `vdb(out)` **is** `Av(f)` in dB directly) is
injected at `inp`; `inn` carries no separate AC source (`Lbreak` isolates
it from `out` at AC). Per `design/opamp_core.sch`'s own "polarity" header
and `design/opamp_sizing.md`, `inp` is this design's **non-inverting**
input, so this measures `Av(f) = Vout(f)/Vinp(f)` directly — phase starts
near `0°` at low frequency (not near `180°`, unlike a loop-gain-style
negative-feedback measurement), so **phase margin here is `180° + phase`
at the unity-gain crossing**, and gain margin is read at the first `-180°`
phase crossing above that.

### Per-point sanity checks

Per this issue's own Test Plan ("assert the DC operating point actually
lands correctly... do not let a non-regulating point read as a plausible
margin"), `run_pvt_sweep.sh` checks, for every point:

- `|Vout(dc) - Vcm| <= 0.15 * VDD` (output within 15% of `VDD` of
  mid-rail).
- `Vd1`, `Vd2`, `Vtail`, `Vout` each strictly between `0.02*VDD` and
  `0.98*VDD` (no internal node fully railed to a supply).

**What this check does and does not verify**: this OSDI/PSP103 build
exposes no queryable per-device operating-point parameters (`gm`/`gds`/
region flags) — the same limitation
`sim/gm-id-characterization/README.md` documents ("Why finite-difference
DC/AC, not model op-point queries"). So this is a *necessary, not
sufficient*, proxy for "the input pair and output stage are really in
saturation": a point that fails it is definitely not regulating correctly;
a point that passes it has a plausible, non-degenerate bias point, but has
not been proven device-by-device to sit in saturation the way a real
per-device query could confirm. A point failing this check makes
`run_pvt_sweep.sh` record it as `op_pass=0` in the CSV — every point in
this issue's committed record passed (`0` failures across all 45 points,
see below).

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
sim/open-loop-ac/run_pvt_sweep.sh
```

Requires `ngspice` on `PATH` (developed and run against `ngspice-46`) plus
the OSDI models `sim/tools/build-osdi.sh` builds; does **not** require
`xschem` at run time — `design/netlist/opamp_core.spice` is a committed,
pre-netlisted artifact (regenerate it from `design/opamp_core.sch` with the
one command in `design/README.md` if the schematic changes). Runs the full
45-point grid in under two minutes on a modern laptop. Writes a new,
timestamped, append-only record under `netlist-snapshots/<record-id>/`,
`corners/<record-id>/` and `records/<record-id>.{csv,md}` — never
overwriting a prior run.

## What was actually measured (this repo's committed record)

Record [`20260910-221601-22feaba`](records/20260910-221601-22feaba.md) —
all 45 points converged, all 45 passed the per-point DC sanity check:

| Metric | Range across all 45 points | Worst point |
|---|---|---|
| Av0 | 37.78 - 45.20 dB | 37.78 dB at `mos_fs_125C_1.08V` |
| GBW (into `CL = 2 pF`) | 4.74 - 6.62 MHz | 4.74 MHz at `mos_fs_125C_1.08V` |
| Phase margin | 76.36 - 78.64° | 76.36° at `mos_ff_125C_1.32V` |
| Gain margin | 22.17 - 24.12 dB | 22.17 dB at `mos_ss_125C_1.08V` |
| Iq (total, incl. `ibias`) | 99.9 - 119.7 uA | 119.7 uA at `mos_ss_-40C_1.32V` |

Full per-point data: [`records/20260910-221601-22feaba.csv`](records/20260910-221601-22feaba.csv).
Raw per-point ngspice logs and AC sweep data:
[`corners/20260910-221601-22feaba/`](corners/20260910-221601-22feaba/).
Frozen DUT netlist this record ran against:
[`netlist-snapshots/20260910-221601-22feaba/opamp_core.spice`](netlist-snapshots/20260910-221601-22feaba/opamp_core.spice).

### Measured vs. predicted binding corners (honest comparison)

`spec/target-spec.md` §2's "Binding corner (predicted)" column guessed
`SS / -40 °C` for both DC gain and GBW (reasoned generically, before any
schematic existed, from "lowest gm, highest output impedance loss"). The
**measured** worst corner for both is instead **`FS / 125 °C / 1.08 V`** —
gain and bandwidth both fall monotonically as temperature rises across
this grid (compare `mos_tt_-40C_1.20V` at 43.31 dB / 5.99 MHz against
`mos_tt_125C_1.20V` at 40.26 dB / 4.84 MHz), the opposite of what the
generic "SS is always worst" placeholder assumed. Phase margin's predicted
binding corner (`FF / 125 °C`, "fastest devices, most peaking risk") **is**
confirmed by measurement (`mos_ff_125C_1.32V` is the measured worst PM
point). This kind of correction — a real testbench superseding a
pre-schematic prediction — is exactly what `spec/target-spec.md`'s
"Binding corner (predicted)" column footnotes as expected to happen.

### Measured vs. `design/opamp_sizing.md`'s first-order estimate

The gm/gds-loaded hand estimate in `design/opamp_sizing.md` predicted
`Av0 ~= 49.0 dB`, `GBW ~= 17.6 MHz`, `SR ~= 10 V/us` (not measured by this
AC-only bench). The measured nominal point (`mos_tt_27C_1.20V`: `41.95 dB`,
`5.48 MHz`) undershoots both — expected, and explained by
`design/opamp_sizing.md`'s own "Expected systematic offset" section: the
real DC operating point this bench's `.op` step finds (`vd2_dc_v` well
below the hand-sizing note's target `d2` node voltage) puts the real `M6`
well off the CSV row the hand sizing cited, at a different, lower-`gm`
bias point than the hand estimate assumed. **The measured 76-79° phase
margin and 22-24 dB gain margin are still comfortably healthy** despite
the lower-than-predicted `Av0`/GBW — this is a case where the sizing
pass's own compensation-network math (`Cc`/`M6` chosen jointly for a
`p2/GBW ~= 2.2` ratio) turned out conservative rather than wrong.

## What this bench does not claim

- **Not slew rate.** This is an AC-only bench; `SR` is not measured here
  (per this issue's own scope — `[TBD-5]` is left untouched in
  `spec/target-spec.md` unless a slew number is actually measured, which it
  is not by this experiment).
- **Not noise, offset, CMRR, PSRR, or output swing.** Each is explicitly
  out of scope for this issue — see `design/opamp_sizing.md`'s own "Out of
  scope" section.
- **Not a ratified spec claim.** `spec/target-spec.md` rows updated from
  this record are tagged `[P]` (proposal), not `[DR-n]`, per this issue's
  own scope — see that file's Status (`DRAFT`) and its value-tag legend.
- **Not proof the input pair/output stage are in saturation at a
  device-by-device level** — see "Per-point sanity checks" above for the
  honest scope of what is actually checked.

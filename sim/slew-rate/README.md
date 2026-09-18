# slew-rate

Large-signal step (slew-rate) characterization of `design/opamp_core.sch`'s
two-stage Miller-compensated op-amp (issue #12), across the full PVT grid,
into `CL = 2 pF` [DR-1]. This is the bench behind `spec/target-spec.md`'s
slew-rate row, which was `[TBD-5]` — no measurement existed — until this
experiment landed. It is deliberately the same shape as
[`../open-loop-ac/`](../open-loop-ac/): same DUT netlist, same 45-point PVT
grid, same DC-bias trick, same per-point DC sanity rule, same append-only
record layout. Only the stimulus (a large-signal step instead of a small AC
signal) and the post-processing (`dV/dt` instead of a Bode read) differ.

## What this bench measures

For every point on the `cornerMOSlv.lib` `mos_tt/ss/ff/sf/fs` [DR-1] x
temperature `{-40, 27, 125} °C` x supply `{1.08, 1.20, 1.32} V` grid
(45 points):

- **`SR+` (rising slew rate)** and **`SR-` (falling slew rate)** — `dV/dt`
  of the output, measured over a fixed `VDD/2 ± 0.15 V` window on a
  full-swing transition, into `CL = 2 pF` [DR-1], at a fixed input common
  mode `Vcm = VDD/2`.
- **Inner-window cross-check** (`VDD/2 ± 0.075 V`) — the same edge measured
  over half the window. If the output is genuinely slew-limited (a constant
  slope) the two agree; a settling tail or a small-signal exponential would
  not. Across all 45 points the two agree to within **0.44 %**.
- **DC operating point** (`vout_dc_v`, `vd1_dc_v`, `vd2_dc_v`,
  `vtail_dc_v`, `vibias_dc_v`) and the per-point `op_pass` sanity flag —
  the identical rule `../open-loop-ac/` applies.
- **Iq** — total DC current drawn from `Vdd` (`ivdd_total_a`), and the same
  figure minus the fixed `10 uA` `ibias` reference (`ivdd_signal_path_a`),
  per `design/opamp_sizing.md`'s "Iq reporting note".

## Method

### DC bias: the same large-inductor trick `../open-loop-ac/` uses

`testbench/tb_slew.spice.tmpl` re-uses `../open-loop-ac/`'s ideal-inductor
DC feedback (`Lbreak = 1e18 H` from `inn` to `out`): a dead short at DC, so
the loop settles at a unity-gain-buffer-like bias point
(`Vout(dc) ≈ Vcm = VDD/2`), and an open circuit on this bench's nanosecond
timescale (`dI/dt = V/L ≈ 1e-18 A/s` for a 1 V swing — the inductor current,
and therefore the charge it can deliver to `inn`, is frozen for the entire
transient). The output is therefore **open-loop** during each step: it slews
all the way to a rail, and the measurement window sits in the linear ramp
between the rails, clear of both the step edge and the soft approach to
either rail.

### Why an antiphase differential drive

Both inputs are stepped **antiphase** by `±0.3 V` each (`inp` directly,
`inn` through `Cinj = 1 uF` from an antiphase source so the `Lbreak` DC
servo still sets `inn`'s bias). The differential input is therefore
`±0.6 V` while the **input common mode stays fixed at `VDD/2`**.

This is not cosmetic. `design/opamp_sizing.md`'s "Headroom check" notes the
NMOS tail device `M5` has only `≈0.21 V` of `Vds` at `Vcm ≈ 0.6 V`
nominally, and less at the slow/cold corner — so the tail *current*, which
is exactly the quantity a slew measurement reads, moves with the input
common mode. A single-ended step (into a unity-gain buffer, or into this
same open-loop bias arrangement) moves the common mode by half the step and
therefore corrupts the measurement. Measured during this bench's
development at `mos_ss / -40 °C / 1.08 V`:

| Drive | Differential input | `SR+` | `SR-` | Asymmetry |
|---|---|---|---|---|
| Single-ended `±0.15 V` step at `inp` | `±0.15 V` | 6.6 V/µs | 2.5 V/µs | **2.6x** |
| Antiphase `±0.075 V` per input (same differential drive) | `±0.15 V` | 5.30 V/µs | 5.15 V/µs | 2.9 % |
| Antiphase `±0.3 V` per input (this bench's committed drive) | `±0.60 V` | 7.54 V/µs | 7.51 V/µs | 0.3 % |

At a *matched* differential drive the antiphase construction is symmetric
and the single-ended one is not: the 2.6x "asymmetry" is an artifact of the
single-ended drive's own common-mode excursion, not a property of the
amplifier. Across the full committed grid the antiphase drive's rise/fall
asymmetry is **≤ 3.6 %**.

### Choosing the drive amplitude

Full tail-current steering needs only `|Vid| > √2·Vov ≈ 43 mV` at the
nominal corner, but the measured slew rate keeps creeping up past that,
because a larger drive raises the tail node (the conducting input device
acts as a source follower) and so recovers a little more tail current from
the limited `Vds` headroom described above. Dev-time amplitude sweep at
`mos_ss / -40 °C / 1.08 V`, identical construction and measurement window
to the committed bench:

| Per-input step | Differential drive | `SR+` | `SR-` |
|---|---|---|---|
| ±0.075 V | ±0.15 V | 5.30 | 5.15 |
| ±0.125 V | ±0.25 V | 6.49 | 6.33 |
| ±0.20 V | ±0.40 V | 7.13 | 6.99 |
| **±0.30 V** | **±0.60 V** | **7.54** | **7.51** |
| ±0.40 V | ±0.80 V | 7.66 | 7.95 |
| ±0.50 V | ±1.00 V | 7.69 | 8.14 |

`±0.3 V` per input is the committed choice: within ~2 % of the large-drive
asymptote of `SR+`, still symmetric between edges, and it keeps both input
pins inside the rails at the worst-case low supply (`0.24 V` / `0.84 V` on
a 1.08 V rail). The amplitude is a **stated bench condition**, recorded in
every record's `vstep_v` column — not a free parameter a later re-run may
silently change.

### Measurement window

`SR` is read between the interpolated crossings of `VDD/2 - 0.15 V` and
`VDD/2 + 0.15 V` on a full-swing edge (`0.3 V / Δt`). The window is fixed
relative to mid-rail rather than to the achieved rail-to-rail swing, so it
sits inside the linear ramp at every corner: across the committed record
the output reaches `-0.012…-0.006 V` at the low rail and `0.969…1.251 V`
at the high rail, both well outside the window at their own supply.

The committed per-point waveform (`corners/<record-id>/<point>_tran.csv`,
written on a uniform 1 ns grid via `.options interp`) **is** the data each
recorded slew number was measured from — `run_slew_sweep.sh` re-reads that
file; nothing is computed from discarded internal timesteps.

### Per-point sanity checks

Every point carries four flags in the record CSV; `run_slew_sweep.sh`
reports any failure in the record's summary and in
`corners/<record-id>/sanity_checks.txt`:

- **`op_pass`** — `|Vout(dc) - Vcm| ≤ 0.15·VDD`, and `Vd1`, `Vd2`,
  `Vtail`, `Vout` each strictly between `0.02·VDD` and `0.98·VDD`. The
  identical rule (and the identical honest scope) as
  [`../open-loop-ac/README.md`](../open-loop-ac/README.md) "Per-point
  sanity checks": this OSDI/PSP103 build exposes no queryable per-device
  operating-point parameters, so it is a *necessary, not sufficient*,
  proxy for "every device is really in saturation".
- **`linearity_pass`** — inner and outer measurement windows agree to 2 %
  on both edges (the output really was on a constant-slope ramp).
- **`traverse_pass`** — the output had parked *below* the window before the
  rising edge and *above* it before the falling edge, so each measured
  window lies inside one full-swing transition.
- **`drive_pass`** — `inn`'s excursion through `Cinj` is `2·vstep` peak-to-
  peak (within 2 %) and centred on its own DC bias (within 10 mV), i.e. the
  antiphase drive arrived undistorted and the coupling capacitor did not
  shape the waveform.

All 45 points of the committed record pass all four.

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
sim/slew-rate/run_slew_sweep.sh
```

Requires `ngspice` on `PATH` (developed and run against `ngspice-46`) plus
the OSDI models `sim/tools/build-osdi.sh` builds; does **not** require
`xschem` at run time — `design/netlist/opamp_core.spice` is a committed,
pre-netlisted artifact. The full 45-point grid takes roughly 8 minutes on a
modern laptop (each point is an 800 ns transient at a 50 ps maximum
timestep). Writes a new, timestamped, append-only record under
`netlist-snapshots/<record-id>/`, `corners/<record-id>/` and
`records/<record-id>.{csv,md}` — never overwriting a prior run.

## What was actually measured (this repo's committed record)

Record [`20260918-210216-90844d2`](records/20260918-210216-90844d2.md) —
all 45 points converged, all 45 passed every per-point check:

| Metric | Range across all 45 points | Worst point |
|---|---|---|
| `SR+` (rising) | 7.54 - 10.27 V/µs | 7.54 V/µs at `mos_ss_-40C_1.08V` |
| `SR-` (falling) | 7.51 - 9.91 V/µs | 7.51 V/µs at `mos_ss_-40C_1.08V` |
| `SR` (worse edge of each point) | 7.51 - 9.91 V/µs | **7.51 V/µs at `mos_ss_-40C_1.08V`** |
| Iq (total, incl. `ibias`) | 99.9 - 119.7 uA | 119.7 uA at `mos_ss_-40C_1.32V` |

Full per-point data: [`records/20260918-210216-90844d2.csv`](records/20260918-210216-90844d2.csv).
Raw per-point ngspice logs and output waveforms:
[`corners/20260918-210216-90844d2/`](corners/20260918-210216-90844d2/).
Frozen DUT netlist this record ran against:
[`netlist-snapshots/20260918-210216-90844d2/opamp_core.spice`](netlist-snapshots/20260918-210216-90844d2/opamp_core.spice).

The `Iq` column reproduces `../open-loop-ac/`'s record point-for-point
(99.9 - 119.7 uA, same worst point `mos_ss_-40C_1.32V`) — expected, since
both benches establish the same DC bias by the same means, and a useful
cross-check that this bench's DC start point is the one the AC bench
characterized.

### Measured vs. predicted binding corner (honest comparison)

`spec/target-spec.md` §2's "Binding corner (predicted)" column predicted
**`SS / -40 °C / low VDD`** ("lowest tail-current headroom") for the
slew-rate row. **The measurement confirms it**: `mos_ss_-40C_1.08V` is the
worst point on both edges. Slew rate rises monotonically with temperature
in this design (`mos_tt` at 1.20 V: 8.61 / 8.90 / 9.30 V/µs rising at
`-40 / 27 / 125 °C`) and with supply — so the coldest, slowest, lowest-rail
corner is worst on all three axes at once.

This is the opposite outcome from the DC-gain and GBW rows, where
`../open-loop-ac/` **corrected** the same pre-schematic prediction to
`FS / 125 °C / 1.08 V`. Both outcomes are recorded as measured; neither
prediction was adjusted after the fact.

### Measured vs. `design/opamp_sizing.md`'s first-order estimate

That sizing pass predicted `SR ≈ I_tail / Cc = 10 uA / 1 pF = 10 V/µs`
(explicitly "not measured by this AC-only bench"). The measured nominal
point (`mos_tt_27C_1.20V`) is **8.90 V/µs rising, 8.71 V/µs falling** —
about 11 % below the hand estimate, and the worst corner is 25 % below it.
Two first-order reasons, both consistent with this bench's own data:

- The slewing node carries more capacitance than `Cc` alone — `M6`'s gate
  capacitance (`Cgg ≈ 88.5 fF` at the CSV's `W = 10 um` reference, i.e.
  `≈ 0.29 pF` at `M6`'s `W = 33 um`) and the `d2`/`out` drain parasitics sit
  alongside the `1.0 pF` `Cc` the hand estimate divided by.
- The tail current at `Vcm = VDD/2` is itself slightly below the nominal
  `10 uA` where `M5`'s `Vds` headroom is tight — directly visible in the
  drive-amplitude sweep above, where raising the drive (and with it the
  tail node) recovers measurable slew rate.

Unlike `Av0`/GBW — which came in ~7 dB and ~3x under their hand estimates —
the slew estimate held up to within ~11 %, which is the accuracy the
`I_tail/Cc` rule of thumb is usually credited with.

## What this bench does not claim

- **Not a ratified spec claim.** `spec/target-spec.md`'s slew-rate row is
  updated from this record with a `[P]` (proposal) tag, not `[DR-n]`;
  ratification is a separate, still-open piece of work (see that file's
  Status, still `DRAFT`).
- **Not settling time, overshoot or small-signal step response.** This
  bench deliberately drives the amplifier open-loop into both rails, so it
  measures the slewing ramp and nothing about closed-loop settling. A
  unity-gain-buffer step-response bench would be its own experiment.
- **Not an input common-mode range (ICMR) characterization.** The drive
  amplitude's residual effect on the measured slew rate is a *symptom* of
  the tail device's limited `Vds` headroom, recorded here honestly; it is
  not a measurement of where the input common-mode range actually ends.
  Filed as its own follow-on (see issue #12's PR for the link) rather than
  guessed at here.
- **Not noise, offset, CMRR, PSRR or output swing.** Each remains its own
  follow-on `sim/<slug>/`, per `design/opamp_sizing.md`'s "Out of scope".
- **Not proof the input pair/output stage are in saturation at a
  device-by-device level** — see "Per-point sanity checks" above for the
  honest scope of what is actually checked.

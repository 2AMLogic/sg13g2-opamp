# input-noise

Input-referred voltage-noise characterization of `design/opamp_core.sch`'s
two-stage Miller-compensated op-amp (issue #13), across the full PVT grid,
into `CL = 2 pF` [DR-1]. This bench exists to close
`spec/target-spec.md`'s input-referred-noise row, which was `[TBD-6]`
("band not yet chosen") — so **choosing the band/metric convention is part
of this experiment**, not a prerequisite it inherited. See "Choosing the
band" below for that choice and its basis.

## What this bench measures

For every point on the `cornerMOSlv.lib` `mos_tt/ss/ff/sf/fs` [DR-1] x
temperature `{-40, 27, 125} °C` x supply `{1.08, 1.20, 1.32} V` grid
(45 points):

- **`vni_int_vrms`** — input-referred noise **integrated over
  100 Hz – 1 MHz**, in RMS volts. This is the headline figure the spec row
  cites.
- **Spot densities** (`vni_100hz_v_rthz` … `vni_1mhz_v_rthz`) — input-referred
  noise density in V/√Hz at **100 Hz, 1 kHz, 10 kHz, 100 kHz and 1 MHz**
  (the band edges plus the three decades between them).
- **Flicker/thermal split** — a weighted least-squares fit of the in-band
  power spectrum to `S(f) = A/f + B`, reported as the flicker coefficient
  (`flicker_coeff_v2`, V²), the thermal floor (`thermal_floor_v_rthz`,
  `√B` in V/√Hz), the **flicker corner** (`flicker_corner_hz`, `A/B`) and
  the flicker term's share of the in-band mean-square noise
  (`flicker_frac_of_msq`).
- **Closed-loop gain guard** (`clgain_100hz`, `clgain_1mhz`) — the
  configuration's own measured gain at both band edges, so a point whose
  bandwidth had collapsed could not silently report an inflated
  input-referred density (see "Per-point sanity checks").
- **DC operating point** (`vout_dc_v`, `vd1_dc_v`, `vd2_dc_v`,
  `vtail_dc_v`, `vibias_dc_v`) and `ivdd_total_a`, on the same convention
  `sim/open-loop-ac/` records them.
- **`vni_int_crosscheck_ratio`** — an independent trapezoidal integral of
  the written spectrum divided by ngspice's own `inoise_total`, so the
  headline number is never taken on trust from a single simulator vector.

## Choosing the band

`spec/target-spec.md` carried no noise band at all before this experiment,
so the band is chosen here, explicitly:

> **Input-referred noise is specified as an integrated figure over
> 100 Hz – 1 MHz (µVrms), plus spot densities in nV/√Hz at 100 Hz, 1 kHz,
> 10 kHz, 100 kHz and 1 MHz.**

Basis, in order of precedence:

1. **The three-foundry twin's own proposed band.**
   [`sky130-opamp/spec/target-spec.md`](https://github.com/2AMLogic/sky130-opamp/blob/main/spec/target-spec.md)'s
   input-referred-noise row proposes exactly `100 Hz – 1 MHz` (with a
   `≈ 30 nV/√Hz` thermal-floor estimate) for the *same* two-stage
   Miller-compensated topology under the same `CLAUDE.md` classic-row
   framing. Per this repo's "three-foundry twin" rule (keep the benches
   structurally identical, derive the numbers from THIS PDK), matching
   that band is what makes the sg13g2 and sky130 rows comparable. That
   row is `[P]` (proposed), not ratified — it is a sibling *precedent*,
   not an inherited ratification, and is cited as such.
2. **The fleet's ratified metric *shape*.** `gf180-bandgap`'s ratified
   amendment A6 specifies its noise row as *"band: 0.1–10 Hz integrated
   µVrms … add a spot-noise point if a later wave feeds an ADC"* —
   i.e. **an integrated figure over an explicitly stated band, plus spot
   densities**. That two-part shape (not that bandgap-specific
   drift-band, which is wrong for a general-purpose amplifier) is what is
   carried here; `gf180-bandgap/sim/output-noise/` is also the fleet's
   nearest ngspice `.noise` implementation precedent.
3. **This PDK's own measured numbers make the bounds defensible:**
   - **Upper bound 1 MHz** is set by the measured worst-case unity-gain
     bandwidth of this very design — `4.74 MHz` at `mos_fs_125C_1.08V`
     (`sim/open-loop-ac/records/20260910-221601-22feaba.csv`). Input
     referral divides by the configuration's gain, so it stops being
     meaningful once the gain rolls off; `1 MHz` sits ~4.7x below the
     worst-case GBW, and the per-point guard below confirms the closed-loop
     gain is still `0.96–0.99` at 1 MHz at **every** one of the 45 points.
     The reference-only wide sweep shows exactly what a careless upper
     bound would have bought: input-referred density bottoms out near
     `30–40 nV/√Hz` at `10 MHz` and then **rises** to
     `118–143 nV/√Hz` at `100 MHz` — the gain-rolloff artifact, not
     amplifier noise.
   - **Lower bound 100 Hz** is stated because the measured spectrum is
     `1/f`-dominated (see below), and a `1/f` integral diverges
     logarithmically: the lower bound *is* part of the number, so leaving
     it implicit would make the row unfalsifiable. `100 Hz` keeps three
     full decades of the flicker region inside the band (the integral is
     `93–94%` flicker-dominated at every corner) without letting an
     arbitrarily low bound dominate the figure.

**Anyone re-deriving this row must state the band with the number.** A
`µVrms` figure without both bounds is not a claim about this amplifier.

## Method

### Why closed loop (and not `sim/open-loop-ac/`'s `Lbreak` trick)

`testbench/tb_noise.spice.tmpl` wires the DUT as a **unity-gain voltage
follower**: `Vfb` (a 0 V, noiseless, ideal source used as a wire and
current probe) ties `inn` to `out`, and the AC test source drives `inp`.
Real feedback then sets the DC operating point — no ideal-inductor trick
is needed — and the noise gain from the amplifier's own input to the
output is `1` across the whole band, so ngspice's `inoise_spectrum`
(output noise divided by the measured `Vinp → out` transfer function) *is*
the input-referred noise density directly.

The issue's scope allowed either this or `sim/open-loop-ac/`'s
`Lbreak = 1e18 H` open-loop DC-bias configuration. **The open-loop
configuration was prototyped first and rejected on evidence**: with
`Lbreak` in place, the same `.noise` analysis on the same DUT at
`mos_tt / 27 °C / 1.20 V` returns an input-referred spectrum falling
`~10x per decade in amplitude` between 10 Hz and 100 kHz
(`0.58 mV/√Hz @ 10 Hz`, `98 µV/√Hz @ 100 Hz`, `10 µV/√Hz @ 1 kHz`),
i.e. `S_v ∝ 1/f²` with a low-frequency plateau below ~10 Hz — a shape
neither `1/f` flicker nor thermal noise produces. Two independent checks
say that shape is an artifact of the huge inductor in the noise solve, not
device physics:

- A **single-device probe** of this same PDK's `sg13_lv_nmos`
  (`W = 3.2 µm`, `L = 0.13 µm`, resistively loaded, no inductor) returns a
  textbook `1/f` power slope — `3.16x per decade in amplitude`
  (`4.79e-5 → 1.52e-5 → 4.79e-6 …` V/√Hz per decade from 0.1 Hz) — over
  a thermal floor that matches `√(4kTγg_m)` with the same probe's measured
  `g_m = 406 µS` to within ~3%.
- The **closed-loop configuration below** reproduces that same textbook
  shape on the full amplifier (`27.9 µV/√Hz @ 1 Hz → 2.79 µV/√Hz @ 100 Hz
  → 881 nV/√Hz @ 1 kHz`, exactly `3.16x` per decade) and its thermal
  asymptote agrees with an independent hand estimate of the same order
  (`≈ 30 nV/√Hz`, cf. the twin's estimate for the same topology).

Both prototyping observations are about *testbench construction*, not
about the DUT, so — following the precedent
`sim/open-loop-ac/README.md` set with its "Choosing `Lbreak`" section —
they are documented here rather than minted as their own committed
record.

### Units check (`testbench/tb_noise_units_check.spice`)

Every number in this experiment's records depends on two ngspice
conventions that are easy to get backwards, and that a sibling repo's
testbench comment documents *differently* than what ngspice-46 actually
does here:

1. `inoise_spectrum`/`onoise_spectrum` are densities in **V/√Hz**, not
   V²/Hz.
2. `inoise_total`/`onoise_total` are already-square-rooted **RMS volts**
   over the swept band, not mean-square V².

Rather than assume either, `run_noise_sweep.sh` runs a PDK-free reference
deck — a `1 kΩ` resistor's Johnson noise through an ideal, noiseless `x100`
VCVS — **before** simulating any DUT point, and asserts (0.5% tolerance)
that it reads `e_n = √(4kTR) = 4.0704 nV/√Hz`, that the output density is
exactly `100x` that, and that the 1 kHz–10 kHz integral is
`e_n·√(9000 Hz) = 386.1 nVrms`. All three passed for this record
(`corners/<record-id>/units_check.txt`). A future ngspice whose `noise`
output used the other convention fails the run loudly instead of silently
rescaling every recorded figure by a square root.

### Per-point sanity checks

`run_noise_sweep.sh` checks, for every point:

- The same DC rule `sim/open-loop-ac/` applies —
  `|Vout(dc) − Vcm| ≤ 0.15·VDD`, and `Vd1`, `Vd2`, `Vtail`, `Vout` each
  strictly between `0.02·VDD` and `0.98·VDD` — so a non-regulating point
  cannot read as a plausible noise figure.
- **A noise-gain guard specific to this bench**: the measured closed-loop
  gain must be within `0.9 … 1.1` at **both** band edges (100 Hz and
  1 MHz). This is what makes the band choice checkable per point rather
  than assumed from one nominal corner.

All 45 points passed both (measured closed-loop gain `0.961 – 0.992`
across the grid). The same honest-scope caveat as `sim/open-loop-ac/`
applies: this OSDI/PSP103 build exposes no queryable per-device
operating-point parameters, so these are *necessary, not sufficient*,
proxies for "every device is really in saturation".

**Not available in this build**: ngspice's per-device noise-contribution
summary (the optional `pts_per_summary` argument to `noise`) prints
nothing for these OSDI/Verilog-A devices, so this bench cannot attribute
the measured noise to individual transistors the way
`gf180-bandgap/sim/output-noise/nominal_noise_breakdown.py` does for a
built-in-model PDK. The flicker/thermal fit above is the decomposition
that *is* available here, and it is a spectral decomposition, not a
per-device one.

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
sim/input-noise/run_noise_sweep.sh
```

Requires `ngspice` on `PATH` (developed and run against `ngspice-46`) plus
the OSDI models `sim/tools/build-osdi.sh` builds; does **not** require
`xschem` or `klt` at run time — `design/netlist/opamp_core.spice` is a
committed, pre-netlisted artifact. Runs the full 45-point grid in about
2 minutes on a modern laptop (110 s wall on the machine that produced the
committed record). Writes a new, timestamped, append-only record
under `netlist-snapshots/<record-id>/`, `corners/<record-id>/` and
`records/<record-id>.{csv,md}` — never overwriting a prior run.

## What was actually measured (this repo's committed record)

Record [`20260918-203850-90844d2`](records/20260918-203850-90844d2.md) —
all 45 points converged, all 45 passed the per-point sanity checks:

| Metric (band: 100 Hz – 1 MHz) | Range across all 45 points | Worst point |
|---|---|---|
| **Integrated input-referred noise** | **73.4 – 108.9 µVrms** | **108.9 µVrms at `mos_fs_125C_1.08V`** |
| Spot density @ 100 Hz | 2.34 – 3.48 µV/√Hz | 3.48 µV/√Hz at `mos_fs_125C_1.08V` |
| Spot density @ 1 kHz | 741 – 1100 nV/√Hz | 1100 nV/√Hz at `mos_fs_125C_1.08V` |
| Spot density @ 1 MHz | 29.5 – 44.3 nV/√Hz | 44.3 nV/√Hz at `mos_fs_125C_1.08V` |
| Fitted thermal floor (`√B`) | 17.9 – 28.1 nV/√Hz | 28.1 nV/√Hz at `mos_ss_125C_1.08V` |
| Fitted flicker corner (`A/B`) | 1.15 – 1.82 MHz | — (see below) |
| Flicker share of in-band mean-square | 91.4 – 94.0 % | — |

Nominal point (`mos_tt_27C_1.20V`): **87.3 µVrms** integrated,
`2.79 µV/√Hz @ 100 Hz`, `881 nV/√Hz @ 1 kHz`, `35.4 nV/√Hz @ 1 MHz`,
flicker corner `1.65 MHz`.

Full per-point data: [`records/20260918-203850-90844d2.csv`](records/20260918-203850-90844d2.csv).
Raw per-point ngspice logs, in-band spectra and reference-only wide
(1 Hz – 100 MHz) spectra:
[`corners/20260918-203850-90844d2/`](corners/20260918-203850-90844d2/).
Frozen DUT netlist this record ran against:
[`netlist-snapshots/20260918-203850-90844d2/opamp_core.spice`](netlist-snapshots/20260918-203850-90844d2/opamp_core.spice).

**Reproducibility**: the sweep was re-run end-to-end from the same commit
before this experiment was committed, and the second run's per-point CSV was
**byte-identical** to the committed one (only the record id, which embeds the
run timestamp, differs). `.noise` here is a deterministic small-signal
analysis — no Monte Carlo, no random seed — so a re-run on the same PDK pin
and the same ngspice build is expected to reproduce exactly; the duplicate
run was discarded rather than committed, since a second identical record is
not additional evidence.

### Which corner binds, and why it is not the same question at both band edges

**`FS / 125 °C / 1.08 V` binds the integrated figure** (108.9 µVrms) —
the same corner that already binds DC gain and GBW in
`sim/open-loop-ac/`. It also binds all three spot densities. The
runner-up ordering is informative: `mos_ss_125C_1.08V` (106.9 µVrms) and
`mos_tt_125C_1.08V` (106.6 µVrms) are within 2% of it, i.e. **temperature
and supply dominate the process axis** for this row — every one of the
three worst points is `125 °C / 1.08 V` (`FS`, `SS`, `TT` in that order),
and every one of the three best points is at `−40 °C` (`FF`/`SF` at
1.32 V, then `FF` at 1.20 V), regardless of process corner.

**The flicker-vs-thermal regime does not shift the binding corner here,
but it does split which sub-metric a corner is worst for.** The
integrated figure is `91–94%` flicker at every corner, so its binding
corner is the flicker-worst one (`FS / 125 °C / 1.08 V`). The *fitted
thermal floor* binds elsewhere — `28.1 nV/√Hz` at `mos_ss_125C_1.08V`,
the lowest-`g_m` hot corner, exactly where `√(4kTγ/g_m)` should be worst.
Because the band's upper decade is still flicker-dominated
(`flicker_corner_hz` is `1.15–1.82 MHz`, i.e. *above* the band top), the
thermal-worst corner never gets to set the integrated number. A
narrower, higher band (e.g. `100 kHz – 10 MHz`) would bind at
`SS / 125 °C / 1.08 V` instead — which is precisely why the band is
stated as part of the spec row rather than left implicit.

### What the flicker dominance says about the design (not a claim, an observation)

`design/opamp_sizing.md` sized the input pair at `L = 0.13 µm`
(minimum length, `W/L = 3.2 µm / 0.13 µm`) for `f_T`, and that sizing pass
explicitly did not consider noise. The measured flicker corner
(`1.15 – 1.82 MHz`) is the direct consequence: flicker noise scales as
`1/(W·L)`, so the `0.416 µm²` input devices put the `1/f` corner above the
whole measurement band. This is recorded here as measured behavior of the
committed sizing; **whether to re-size for noise is a design decision, not
this bench's to make** — it is filed separately
([issue #19](https://github.com/2AMLogic/sg13g2-opamp/issues/19)) rather
than acted on here.

## What this bench does not claim

- **Not a ratified spec value.** The `spec/target-spec.md` noise row
  updated from this record is tagged `[P]` (proposal), per that file's
  value-tag legend and `Status: DRAFT`.
- **Not a per-device noise attribution** — see "Per-point sanity checks"
  above for why the per-device breakdown is unavailable in this
  OSDI/PSP103 build.
- **Not output-referred noise, and not noise in any other closed-loop
  gain configuration.** The number is input-referred in a unity-gain
  follower; a `1 + R2/R1` configuration multiplies it by its own noise
  gain.
- **Not a statistical (mismatch/Monte-Carlo) figure.** This is a
  deterministic PVT-corner sweep; no MC deck is run, and the noise row's
  "Statistical basis" column is left as not-applicable rather than
  claimed.
- **Not bias-generator noise.** `ibias` is an ideal (noiseless) 10 µA
  source, per `design/opamp_sizing.md`'s "Bias scope" — a real bias
  generator's own noise is not in this number.
- **Not post-layout.** No extracted parasitics; the DUT is the committed
  schematic netlist.

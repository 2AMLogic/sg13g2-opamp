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

## The `klt sim` path (issue #85)

[`klt/`](klt/) expresses this same bench as `klt sim` requests, because T1
item 5 ("full corner verification vs a ratified spec") accepts only a `klt
sim` envelope (see `signoff/README.md`). It is a second measurement path for
the same circuit, not a new bench.

| File | What it is |
|---|---|
| [`klt/tb_openloop_ac.body.spice`](klt/tb_openloop_ac.body.spice) | The test circuit as a `klt sim` circuit body: element-for-element the circuit in `testbench/tb_openloop_ac.spice.tmpl` (flat DUT include, `Lbreak = 1e18 H`, `CL = 2 pF`, 10 µA external `ibias`, 1 V AC at `inp` only), with exactly one `.include` of `design/netlist/opamp_core.spice` and no `.control` block. |
| [`klt/openloop_ac.request.json`](klt/openloop_ac.request.json) | AC request: `ac dec 20 1 1g` over the 45-point grid; Av0, GBW and the phase at the 0 dB crossing, each with its ratified bound as `limits`. |
| [`klt/openloop_op.request.json`](klt/openloop_op.request.json) | Operating-point request: same body, grid and options; total Vdd current (`ivdd_total_a`, the Iq row) with its ratified bound, the DC node voltages, and the per-point sanity checks below as tool-graded measurements. |
| [`klt/run.sh`](klt/run.sh) | Runs both requests, gates each envelope, writes them unmodified to `klt/records/<UTC>-<sha>.{ac,op}.sim.json`, then writes the comparison `klt/records/<UTC>-<sha>.compare.json`. |
| [`klt/compare.py`](klt/compare.py) | The validation gate and the comparison against this bench's harness record; tests in [`klt/test_compare.py`](klt/test_compare.py). |

### How the two paths relate, and which one is the record of evidence

The harness record
[`records/20260910-221601-22feaba.csv`](records/20260910-221601-22feaba.csv)
stays the **record of evidence** for the four rows this bench carries. It is
what DR-0002 ratified the bounds on, and nothing in `klt/` edits or replaces
it. A `klt sim` envelope pair under `klt/records/` is the **gradable form** of
the same measurement: the tool assigns each row's pass/fail verdict and
binding corner against the ratified bound. The `compare.json` written beside
each pair ties the two together point by point. Where the two disagree beyond
the stated tolerance, the disagreement is reported in that file and must be
explained here before the envelope is cited anywhere.

**No envelope is committed yet.** The real 45-corner run is blocked; see
"Status" below.

### Grid encoding

- Process: one `corners.process` bundle per `cornerMOSlv.lib` section
  (`mos_tt/ss/ff/sf/fs`), each bundle also selecting `cornerCAP.lib`
  `cap_typ`. That reproduces the template's fixed `cap_typ` line (the Miller
  capacitor is a `cap_cmim` device).
- Supply: `corners.supply_v` sweeps `vdd` `{1.08, 1.20, 1.32}` and `vinp`
  `{0.54, 0.60, 0.66}` **together by index** (klt's semantics for multiple
  supply keys). That gives `Vcm = VDD/2` at every corner, as the harness does.
  The OP request asserts it per corner (`op_vcm_frac` within `0.5 ± 1e-4`).
- Temperature: `.temp` per corner (−40, 27, 125 °C), `tnom = 27`, as in
  the template.
- Solver tolerance: ngspice defaults, with no `reltol`/`abstol`/`vntol`
  override (DR-0005). `options.ngspice_init` sets only `measureprec`/`numdgt`,
  the number of digits ngspice prints.

### Why two requests

`klt sim` runs **one analysis per corner** (klayout-tools `docs/cli/sim.md`,
"Still one analysis per corner"; klayout-tools#2482). Av0, GBW and PM come
from the AC sweep. Iq and the DC sanity checks are operating-point
quantities, and an AC solve's plot does not carry them. So the bench is two
requests over the identical body and grid. `compare.py` joins them on the
full (process, temperature, VDD) key and refuses anything but the same 45
unique points on both sides. Both envelopes are kept as the tool wrote them.

### Measurement method, row by row

| Row (ratified bound [DR-2]) | Envelope measurement | Same as the harness? |
|---|---|---|
| Open-loop DC gain ≥ 37.8 dB | `av0_db`: `.meas ac find vdb(out) at=1` | Yes. Both read the first sweep point (1 Hz). |
| GBW ≥ 4.74 MHz | `gbw_hz`: `.meas ac when vdb(out)=0` | **No, a bounded one-signed difference.** ngspice interpolates the crossing linearly in *frequency* between the two bracketing sweep points. `run_pvt_sweep.sh` interpolates linearly in *log10(frequency)* with the same bracketing fraction. The tool value is larger by `f_lin/f_log − 1`, which lies between 0 and 1.657e-3 at 20 points/decade. Recomputed per corner from the harness's own committed raw sweeps (`corners/20260910-221601-22feaba/*_ac.csv`), it ranges from 7.0e-5 to 1.66e-3 across the 45 points. `compare.py` corrects for it per corner and reports the uncorrected difference too. At the binding corner the bias makes the tool's GBW slightly *higher*, never lower, so it cannot turn a harness pass into a tool fail. |
| Phase margin ≥ 60° | `phase_at_ugf_rad`: `.meas ac find vp(out) when vdb(out)=0`, limits `min −2π/3 rad`, `max 0 rad` | The same bracketing fraction as the harness, but **not the same phase**: `vp(out)` is the *wrapped* phase, in (−180°, 180°], while the harness's `pm_deg` uses the continuous phase (`cph`). This bench *defines* PM as `180° + phase at the 0 dB crossing` ("Sign convention" above). A `min −2π/3` limit alone is therefore *not* `PM ≥ 60°`: an unstable corner with PM = −10° has a continuous phase of −190°, `vp` reads +170°, and it would pass. The `max 0` limit makes the tool's own verdict fail safe: the phase at the crossing is negative for this non-inverting bench, so a positive reading can only be a wrap, and it now fails. With both bounds, the tool verdict equals `PM ≥ 60°` for PM in (−180°, 180°], i.e. continuous phase at the crossing in (−360°, 0°]; more than 360° of lag at the crossing is implausible for this two-stage bench. **Remaining edge case:** near PM ≈ 0° the two bracketing sweep points can sit either side of the wrap (about −179° and +179°), and `find … when` interpolates to an arbitrary value between them, which can land inside [−120°, 0°] and pass. The tool verdict alone does not catch that; `compare.py` does, because the derived `180° + phase` then differs from the harness's continuous-phase PM by far more than the 0.1° tolerance. The envelope's margin × 180/π is `PM − 60°` while PM ≤ 120° (above that the `max 0` bound is the nearer one; the measured PM is 76-79°). The tool grades the phase rather than PM itself because an `expr` cannot read a `.meas` result in the same request (checked on ngspice-42; klayout-tools#2826), so the 180° offset cannot be added inside the tool. Radians rather than `set units=degrees`: a runner that silently ignored `ngspice_init` would then grade degrees against a radian bound and pass everything. |
| Iq ≤ 119.7 µA (total, incl. `ibias`) | `ivdd_total_a`: `-i(vdd)` after `op` | Yes. Same operating point, same sign convention. |

The per-point DC sanity check ("Per-point sanity checks" above) is
reproduced exactly as tool-graded OP measurements: `op_vout_offset_frac =
|Vout − VDD/2|/VDD ≤ 0.15`, and `op_{vout,vd1,vd2,vtail}_rail_frac` within
`[0.02, 0.98]`. A point failing any of them fails the OP envelope, and
`compare.py` requires the tool's sanity result to equal the harness's
`op_pass` at every point. Both requests also set
`options.fail_on_diagnostic: ["singular_matrix", "nonconvergence"]`. A corner
whose solve needed gmin/source stepping is therefore graded `inconclusive`,
never `pass`, which mirrors the harness's broken-simulation detector
(`SG13G2_NGSPICE_ERR_RE`) treating those log lines as a broken point. The OP
request adds a `[−0.1, 1.42] V` plausibility window on the node voltages.

### Comparison tolerance

These are per-metric tolerances in `compare.py`'s `TOLERANCES`. A comparison
tolerance never loosens a ratified bound or a solver tolerance. A tool
verdict on the far side of a bound from the harness verdict is reported in
`bound_verdict_disagreements` even when the two values agree within
tolerance.

| Metric | Tolerance | Why |
|---|---|---|
| `ivdd_total_a` | 1e-3 relative | ngspice's default `reltol = 1e-3` is the solver's own DC acceptance criterion. DR-0005 measured a 9.9e-4 relative drain-current difference between the macOS/aarch64 and Linux/x86_64 default-tolerance records of this PDK. The harness ran on macOS/aarch64. The envelope runs on the fleet's Linux image. |
| DC node voltages | 1e-3 relative + 1 µV | Same basis (`reltol`, `vntol = 1 µV`). |
| `av0_db` | 0.02 dB | Two gm/gds stage ratios, each moving by at most about 1e-3 under that current envelope: 20·log10(1.002) = 0.017 dB. |
| `gbw_hz` (after the per-corner method correction) | 2e-3 relative | GBW ≈ gm1/Cc, which moves by about 1e-3, doubled for margin. The method term is removed exactly, not absorbed. |
| PM (derived as 180° + phase) | 0.1° | A 2e-3 shift in the second-pole/GBW ratio moves PM by about 0.03° at this design's ~77°. |

Both sides' print quantisation (the harness CSV is `%.6g`) is two decades
below these tolerances.

**Bound proximity, stated in advance:** the harness's worst Av0 is
**37.7812 dB at `mos_fs_125C_1.08V`, below the 37.8 dB bound by 0.019 dB**.
That is inside the 0.02 dB comparison tolerance, so a tool value on either
side of 37.8 dB at that corner would agree with the harness. The verdict of
record is the envelope's, unrounded, and `compare.py` will list a flip there
as an explained disagreement rather than hide it. Iq's worst point
(119.655 µA at `mos_ss_-40C_1.32V`) sits 3.8e-4 relative under its bound,
also inside its comparison tolerance. GBW's worst (4.74216 MHz at
`mos_fs_125C_1.08V`, 4.6e-4 relative margin) can only move up under the
method bias. PM's worst (76.36°) is 16° clear.

### Status (2026-10-09): the real run is blocked

Two independent blockers. Neither is solved by running the grid locally on
a shared dispatch host, and that is not done.

1. **The batch fleet runner is older than the client.** The fleet image pins
   klt **0.5.0** (2AMLogic/2am `infra/aws/batch-image-pins.env`,
   `PIN_KLAYOUT_TOOLS_VERSION`). klt's runner/client version gate rejects
   the job before simulating. A submission of `openloop_ac.request.json` with
   klt `0.7.0+g4cbdfa769875` staged its 14 model inputs and launched job
   `klt-sim-671820687a2e`. The job then failed with exit 87,
   `batch_runner_version_mismatch`: "the fleet runner runs klt 0.5.0 but the
   submitting client is 0.7.0+g4cbdfa769875 -- the request was not run". All
   45 corners came back `error`. The requests also need features that 0.5.0
   lacks: `options.osdi_preload` with `stage_model_inputs`, per-section
   corner libraries, `expr` measurements, `ngspice_init` and
   `fail_on_diagnostic`. So the runner must move forward. Pinning the client
   back to 0.5.0 does not work. Tracked in 2AMLogic/2am#2193. After the bump,
   run with a client whose `klt --version` equals the runner's, for example
   `KLT="uvx --from klayout-tools==X.Y.Z klt" sim/open-loop-ac/klt/run.sh`.
2. **The preflight needs the pinned ngspice.** `run.sh` sources
   `sim/preflight.sh`, whose OSDI check loads the `.osdi` binaries with the
   local ngspice. These are the same binaries the request stages to the
   fleet. They target OSDI v0.4 (ngspice-46, the `sim/pdk.json` pin). A host
   with ngspice-42 ("only supports OSDI v0.3") fails the check, and
   `run.sh` exits 3 before submitting anything. Run from a host with the
   pinned ngspice-46.

What *was* verified without the real run:

- The client accepts both requests, including model staging and the
  include closure.
- The request mechanics were checked on a behavioural stand-in DUT with one
  local corner. `alter` of `vdd`/`vinp` tracks as intended. `.meas ac` with
  `at=1` and `when vdb(out)=0` produces the expected values. The tool's GBW
  equals the linear-in-frequency interpolation and its phase equals the
  harness's interpolation on the same sweep data. The OP `expr`
  measurements and their limits grade as intended.
- `compare.py` passes 31 offline tests, including negative controls for
  reordered, missing, duplicate, extra and off-grid points, null and
  non-finite values, perturbations outside tolerance, sanity disagreement
  and a bound flip.
- `run.sh` failure paths: missing PDK, missing OSDI, missing ngspice and
  missing klt exit 3. A klt error, an errored corner or failed validation
  exits 4 and writes nothing to `records/`. Repeated runs mint distinct
  append-only records and leave the harness CSV byte-identical. These paths
  were exercised with replayed envelopes, never real simulator output.

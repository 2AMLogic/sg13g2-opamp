# Issue #430 — nulling-resistor screening of the Miller compensation

**A nulling resistor retires the fast/hot phase-margin miss, and leaves the
slew problem untouched.** In series with the extracted Miller capacitor of the
retained 25.7 µm layout, an ideal 2 kΩ resistor lifts the 45-corner AC grid to
a minimum phase margin of **67.0238°** (job `klt-sim-1ed9082547d5`), with zero
diagnostics. The falling slew at `mos_ss / 1.08 V / −40 °C` stays below the
7.51 V/µs bound at every resistance screened, and the retained extraction
already reads **7.4682 V/µs** there with no resistor at all — a pre-existing
miss that the resistor neither causes nor cures. With phase margin to spare,
a smaller capacitor buys that slew back: at 2 kΩ a 25.5, 25.3 or 25.0 µm side
gives **7.5780, 7.6909 or 7.8650 V/µs** falling while fast/hot phase margin
holds at 66.70°, 66.38° or 65.87° (§7).

These are screening DUTs built from the pinned 0.9.0 extraction: the resistor
is an ideal card, no GDS changes, and nothing here is drawn. **The fast/hot
finding stays open** until a resistor is in the layout and that layout is
re-extracted (§8). This record changes no design, layout, spec or bench file.

All legs ran the committed open-loop AC and slew benches through the pinned
generator and runner (`klayout-tools==0.9.0`, batch fleet,
`capacity_wait_s=600` on every request), one corner per request unless stated.
The single corners went up as `klt sim --batch-set` sets (at most 13 requests
in flight, `--wait-for-capacity 600`, `--capacity-retries 3`) and the grids
with `--submit-only` then `--attach`; no request was refused for capacity.

## 1. Inputs and reproduction pins

| Input | Value |
|---|---|
| Opamp source | `36596fcda50e5998a5088c56c7c9032a15a0b61b` (the #312 pinned source, as in PR #439) |
| GDS (25.7 µm cap) | `ab2d926e1974e4e04f0c0363af5139b64034f544e4fdc192df3dd7a79830aa05` |
| 0.9.0 extraction | `80cd19a17ee5d7e008efb662e322147e556598993f0d73c9ca16ba532019f1ea` (reproduced this run with the #429 `klt pex --extract-only` recipe, byte-exact) |
| AC/OP generator (`klt_measure.py`) | `36596fc` blob, SHA-256 `d4ea4008b5dfec24eab6e7996781df4b2c924f217eac19d888f84844b6b6eda0` |
| DUT and slew-request generator | `../rz_screen.py` (this record's tool; regenerates every single-corner DUT below byte-for-byte from the extraction above) |
| Runner | fleet `klt 0.9.0` (commit `5dbbad05ff42265c92a6f3d2f20d1bbcd2957d49`), ngspice-47, binary SHA-256 `39ca1adb8266…`, IHP-Open-PDK `v0.3.0` |
| Runner KLayout | `0.30.13` in these envelopes; PR #439's records read `0.30.12`. KLayout takes no part in an ngspice measurement and the engine binary hash is identical |

The 0.1 Ω control leg (§2) reproduces the pinned baseline phase at
`mos_ff / 1.32 V / 125 °C` to 6.4e-6 rad, which is what 0.1 Ω times the
measured resistance sensitivity predicts; the grid's fast/hot corner equals
its single-corner leg to all 12 printed digits.

## 2. Method

**Screening DUT.** The extraction's `X$32 out__t1 \$6__t3 cap_cmim l=25.7U
w=25.7U` card is lifted off its d2-side terminal onto a new node and closed
again through an ideal resistor:

```
X$32 out__t1 cc_rz cap_cmim l=25.7U w=25.7U
Rz_cc cc_rz \$6__t3 2000
```

The `out`-side plate, every device card and the whole parasitic star network
are untouched, so a screening DUT is the retained layout plus one ideal
element. `--bare` first drops every parasitic `R`/`C` card and collapses each
`<net>__tN` terminal onto its hub — the drawn-device DUT of
`cc-sizing-430/README.md` §1 — before the resistor is inserted.
`--cap-side S` also rewrites the capacitor's `l=`/`w=` to a square of side S.

**The control is 0.1 Ω, not 0 Ω.** ngspice warns on an exact 0 Ω card and
clamps it, and a 1e-9 Ω card — accepted without a warning — puts a 1e9 S
conductance next to µS device conductances: the solution degrades instead. On
the first pass of this run those legs read `av0` 0.21 dB low (45.584 dB against
45.798 dB), fast/hot PM +0.065° high, one leg came back inconclusive on a
`nonconvergence` warning, and the falling slew +0.031 V/µs high (jobs
`klt-sim-3be6c6fd2a4e`, `klt-sim-cbd24d53f9fb`, `klt-sim-0a38c38ef293`). They
are not records, and `rz_screen.py` now refuses a resistance below 0.01 Ω.

| leg, `mos_ff / 1.32 V / 125 °C` | phase at UGF (rad) | PM (°) | GBW (MHz) | av0 (dB) | job |
|---|---|---|---|---|---|
| pinned baseline, PR #431 | −2.097648803209 | 59.8136 | 10.908 | 45.7979 | `klt-sim-3e33c106fc7d` |
| **0.1 Ω control** | −2.097642375716 | 59.8139 | 10.9078 | 45.7979 | `klt-sim-7381cda4254b` |
| 1 Ω | −2.097584528839 | 59.8173 | 10.9078 | 45.7979 | `klt-sim-835cd2266c86` |
| 10 Ω | −2.097006122474 | 59.8504 | 10.9072 | 45.7979 | `klt-sim-e2e915a93561` |

**Slew legs** adapt `sim/slew-rate/klt/tb_slew.body.spice` to the `.SUBCKT`
DUT exactly the way `klt_measure.py` adapts the AC/OP bench (include +
`Xdut`, pins matched by name) and drop the six measurements and three
B-sources that read the d1/d2/tail internal nodes, which a `.SUBCKT` DUT
hides. The 20 remaining measurements, the drive, the load, the analysis and
every limit are the committed bench — the same form as PR #439's slew records.

PM is `180 + degrees(phase_at_ugf_rad)`; signed margin is phase minus
−2.0943951023931953 rad.

## 3. Resistance sweep on the extraction

| Rz (Ω) | FF / 1.32 V / 125 °C PM | GBW (MHz) | job |
|---|---|---|---|
| 0.1 (control) | 59.8139 | 10.9078 | `klt-sim-7381cda4254b` |
| 250 | 60.7318 | 10.8940 | `klt-sim-b29afba0e63d` |
| 500 | 61.6450 | 10.8828 | `klt-sim-9bcb83fbbabd` |
| 1000 | 63.4568 | 10.8687 | `klt-sim-5a01dda8ae2b` |
| 1500 | 65.2496 | 10.8654 | `klt-sim-dfed29a56770` |
| **2000** | **67.0238** | 10.8732 | `klt-sim-f173899224e6` |
| 2500 | 68.7799 | 10.8920 | `klt-sim-960adfa990df` |
| 3000 | 70.5183 | 10.9223 | `klt-sim-26d09416b7ba` |
| 4000 | 73.9427 | 11.0178 | `klt-sim-55f9e04b325b` |
| 6000 | 80.5676 | 11.3767 | `klt-sim-2eb950d5473a` |
| 10000 | 92.5262 | 13.1052 | `klt-sim-ffaa23602aa6` |

Phase margin rises monotonically with Rz across the whole 250 Ω–10 kΩ range
and is at or above 60° from 250 Ω up; the linear estimate puts the 60° crossing
near 51 Ω. The gain per kΩ falls slowly, from 3.67° at 250 Ω to 3.27° at
10 kΩ. `av0` is 45.7979 dB at every resistance (the resistor sits behind a
capacitor, so the operating point cannot move) and fast/hot GBW stays within
−0.4 % / +20 % of the control across the sweep. The unrounded phases are in
`records/ext_rz<Rz>_ff.ac.json`.

The other screened corners behave the same way. `mos_fs / 1.08 V / 125 °C` is
the ratified GBW corner and `mos_sf / 1.32 V / 125 °C` the second-tightest
phase-margin corner of PR #439's grid:

| Rz (Ω) | FS / 1.08 V / 125 °C PM | GBW (MHz) | SF / 1.32 V / 125 °C PM | TT / 1.08 V / 27 °C PM |
|---|---|---|---|---|
| 1 (control) | 62.7939 | 9.4745 | 60.0876 | 64.0362 |
| 1000 | 65.9637 | 9.4425 | — | — |
| 2000 | 69.0788 | 9.4402 | 67.1398 | 71.0004 |
| 3000 | 72.1400 | 9.4682 | 70.5616 | 74.3911 |
| 6000 | 81.0270 | 9.7457 | — | — |

GBW at its binding corner never falls below 9.4402 MHz, 1.99× the 4.74 MHz
bound. Jobs: FS `klt-sim-49d214013474`, `klt-sim-aab43c80ce09`,
`klt-sim-d84e10830576`, `klt-sim-17dacc80679a`, `klt-sim-244b677be0bd`; SF
`klt-sim-bc47ada5ae39`, `klt-sim-93b25a7ee56a`, `klt-sim-71043087a888`; TT
`klt-sim-04874a9eb305`, `klt-sim-0670c4cb4def`, `klt-sim-7ba2227e2413`.
TT / 1.08 V / 27 °C passes with no diagnostic at all three resistances.

## 4. Drawn-device legs: the parasitic penalty with a resistor present

| Rz (Ω) | drawn DUT PM (°) | extraction PM (°) | parasitics | drawn job |
|---|---|---|---|---|
| 1000 | 64.0147 | 63.4568 | −0.5579° | `klt-sim-eb8d62652727` |
| 2000 | 67.6066 | 67.0238 | −0.5828° | `klt-sim-c58dee895907` |
| 3000 | 71.1273 | 70.5183 | −0.6091° | `klt-sim-7b41a6fde138` |
| 6000 | 81.2661 | 80.5676 | −0.6985° | `klt-sim-2effab1bab21` |

Fast/hot, both legs at the 25.7 µm capacitor; the last column is taken from
the unrounded phases, so it can differ from a difference of the printed ones.
The layout's parasitic penalty was −0.534° without a resistor (PR #431, leg C
minus leg B); with one it is −0.558° to −0.699° over 1–6 kΩ. A resistor therefore buys its phase margin on
the extracted layout at about 99 % of what it buys on the bare devices.

## 5. Slew does not respond to the resistor

`mos_ss / 1.08 V / −40 °C`, the ratified slew corner, both edges in V/µs:

| Rz (Ω) | rising | falling | falling margin to 7.51 | verdict | job |
|---|---|---|---|---|---|
| 0.1 (control) | 7.8599 | **7.4682** | −0.0418 | fail | `klt-sim-9257f0c91fec` |
| 1 | 7.8599 | **7.4682** | −0.0418 | fail | `klt-sim-d1a67e372226` |
| 10 | 7.8599 | **7.4682** | −0.0418 | fail | `klt-sim-b06d2c860b0b` |
| 250 | 7.8598 | **7.4681** | −0.0419 | fail | `klt-sim-9603afd30dfa` |
| 500 | 7.8598 | **7.4680** | −0.0420 | fail | `klt-sim-4272f8300404` |
| 1000 | 7.8597 | **7.4678** | −0.0422 | fail | `klt-sim-2d53e0d74419` |
| 2000 | 7.8595 | **7.4674** | −0.0426 | fail | `klt-sim-2e7d6f69c507` |
| 3000 | 7.8593 | **7.4670** | −0.0430 | fail | `klt-sim-4d2244c6e637` |
| 6000 | 7.8588 | **7.4657** | −0.0443 | fail | `klt-sim-0628a33ccad7` |
| 10000 | 7.8581 | **7.4636** | −0.0464 | fail | `klt-sim-cbe4d205a07c` |

- **The retained 25.7 µm extraction fails the falling bound by 0.56 % with no
  resistor.** PR #439 measured this corner on the drawn-device DUT (7.4786
  V/µs, `klt-sim-d220eeb786af`) and on the 26.0 µm extraction (7.3067); this is
  the first reading on the retained layout's own extraction. The schematic-leg
  record behind the 7.51 bound reads 7.51441 V/µs, a pass by 0.06 %. The
  representation finding stands on the extraction too: −0.14 % from drawn
  devices to extracted layout, −0.62 % from the schematic record to the
  extraction.
- The resistor costs at most 0.0046 V/µs of falling slew (0.06 % at 10 kΩ,
  0.0008 V/µs at 2 kΩ) and leaves the rising edge alone. It is not a slew
  lever in either direction.
- Every other slew measurement passed in every leg, and no leg carried a
  diagnostic.

## 6. The 45-point grid at Rz = 2 kΩ

The sizing note's candidate (`Rz ≈ 1/gm6 ≈ 2.06 kΩ`, `design/opamp_sizing.md`)
on the 25.7 µm extraction, full grid, `SG13G2_PEX_POINTS` unset: AC grid
`klt-sim-1ed9082547d5` (45/45 pass), OP grid `klt-sim-e52094c643b2` (45/45
pass), slew grid `klt-sim-4b1c150ee103` (44 pass, 1 fail). Zero diagnostics in
all three envelopes. Envelopes: `records/grid_rz2000_ac.json`,
`records/grid_rz2000_op.json`, `records/grid_rz2000_slew.json`.

| metric | worst value | corner | ratified limit | verdict |
|---|---|---|---|---|
| PM (phase −1.971806334087 rad) | 67.0238° | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≥ 60° | **pass** (+0.122589 rad) |
| DC gain | 42.6763 dB | `mos_fs / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 37.8 dB | pass |
| GBW | 8.1801 MHz | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 4.74 MHz | pass |
| Iq (`ivdd_total_a`, 45 values) | 84.8472 µA | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≤ 119.7 µA | pass |
| slew, rising edge | 7.8595 V/µs | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 7.51 V/µs | 45 pass |
| slew, falling edge | **7.4674 V/µs** | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 7.51 V/µs | 44 pass, **1 fail** |

The four lowest phase margins are 67.0238° (FF), 67.1398° (SF), 67.1909° (SS)
and 67.4110° (FS), all at 1.32 V / 125 °C; the highest is 77.3452° at
`mos_ss / 1.08 V / −40 °C`. The next-lowest falling edges after the failure
are 7.7252 V/µs (`mos_sf / 1.08 V / −40 °C`) and 7.7476 V/µs
(`mos_ss / 1.08 V / 27 °C`). At `mos_sf / 1.08 V / 27 °C`, where PR #439's
26.0 µm grid lost both edges to `timestep_too_small`, this grid measures
8.5000 V/µs rising and 8.0128 V/µs falling with no diagnostic; TT / 1.08 V /
27 °C measures 8.7557 and 8.2346 V/µs. Both corners are measured on this DUT
only; whether the resistor or the capacitor size removed the solver error is
not isolated.

## 7. Rz = 2 kΩ with a smaller capacitor

The resistor leaves about 7° of phase margin in hand at fast/hot, and PR #439
showed falling slew falling as 1/C. Spending some of that margin on a smaller
capacitor, at the three corners that bind:

| side (µm) | C (fF) | FF PM | FF GBW (MHz) | FS GBW (MHz) | SS slew rise | SS slew fall | fall margin | jobs (FF / FS / slew) |
|---|---|---|---|---|---|---|---|---|
| 25.7 | 994.85 | 67.0238° | 10.8732 | 9.4402 | 7.8595 | **7.4674** | −0.0426 | `klt-sim-f173899224e6` / `klt-sim-d84e10830576` / `klt-sim-2e7d6f69c507` |
| 25.5 | 979.46 | 66.7036° | 11.0114 | 9.5651 | 7.9799 | **7.5780** | +0.0680 (+0.91 %) | `klt-sim-d8be17d2dc96` / `klt-sim-ad36dfa403dd` / `klt-sim-e42c23f7a9bd` |
| 25.3 | 964.18 | 66.3800° | 11.1503 | 9.6907 | 8.1030 | **7.6909** | +0.1809 (+2.41 %) | `klt-sim-17073e5450e0` / `klt-sim-46df649997d0` / `klt-sim-80e49f9d0777` |
| 25.0 | 941.50 | 65.8672° | 11.3741 | 9.8804 | 8.2930 | **7.8650** | +0.3550 (+4.73 %) | `klt-sim-68ae0a841dfb` / `klt-sim-9f8580680429` / `klt-sim-9c3a8b9c159b` |

- Every binding corner passes at 25.5 µm and below, with the unrounded FF
  phases −1.977394711431, −1.983042752583 and −1.991992568900 rad.
- Phase margin at fast/hot costs about **0.21° per 1 % of capacitance** with
  the resistor present (0.18° per 1 % without it, PR #439 §2), so the trade is
  slightly more expensive in phase than the bare-capacitor sweep suggested and
  starts from a 7° surplus.
- Falling slew follows 1/C to within 0.1–0.3 %: the inverse-C estimate from
  the control (7.4682 × 994.85 / C) reads 7.5856, 7.7057 and 7.8914 V/µs at
  25.5, 25.3 and 25.0 µm, 0.10 %, 0.19 % and 0.34 % above the measurements. The
  same model puts the 7.51 V/µs crossing at 25.63 µm and a +1 % slew margin at
  25.50 µm.
- These are nine single corners at three capacitor sizes, not a grid. The
  45-point grids exist only for 25.7 µm (§6). A candidate for the layout must
  take its own full grid after extraction.

## 8. Disposition

**#312.** Nothing changes for the regeneration reference: the retained
geometry is still the 25.7 µm layout at `36596fc` (59.8136° at fast/hot), and
#312 remains blocked by #430. This record adds one fact the regeneration will
meet: that layout's own extraction reads 7.4682 V/µs falling at
`mos_ss / 1.08 V / −40 °C`, 0.56 % under the ratified bound, where the
schematic-leg record passes by 0.06 %. That is the #237-family representation
finding, now measured on the extracted layout, and it belongs to #86 / #237.

**#332 / #342.** The nulling-resistor option is the one compensation change on
this topology that retires the fast/hot miss, and its window is wide:
fast/hot passes from 250 Ω to 10 kΩ, and the FS, SF and TT corners pass at
every resistance screened on them (1 kΩ to 6 kΩ). The PDK resistor's own
spread (below) moves a 2 kΩ part only to 1.8–2.2 kΩ. The resistance costs no
slew, no gain, no supply current and under 0.4 % of GBW at 2 kΩ. Slew is not
a compensation problem on this design: the falling bound is missed by 0.56 %
at the retained size with or without a resistor, and only a smaller capacitor
(§7, buying 0.9–4.7 %) or more edge current (bias or topology, #332/#342
scope) recovers it. Carry into the new topology: the resistance sensitivity
(3.3–3.7° per kΩ at fast/hot for the `gm6` of this design), the parasitic
penalty with a resistor present (−0.56° to −0.70° over 1–6 kΩ), and the
measured falling-slew deficit of the retained layout.

**What a layout increment needs** (not done here; stated so it is not
rediscovered):

1. Draw the resistor. `design/opamp_sizing.md` names the PDK poly resistor
   `rppd`. On the pinned `v0.3.0` install `cornerRES.lib` gives
   `rsh_rppd` = 260 Ω/sq typical, 234 (`res_bcs`) and 286 (`res_wcs`): ±10 %,
   well inside the window of §3. 2 kΩ is 7.7 squares.
2. The committed AC/OP and slew requests carry only `cornerMOSlv.lib` and
   `cornerCAP.lib` sections. A drawn resistor needs a `cornerRES.lib` section
   in every process bundle, and which resistor corner rides with which MOS
   corner is a request decision nobody has made. `r3_cmc.osdi` is already in
   the preload list.
3. `layout/devices.py` wraps `mos_array` and `cap_array` only; the block has
   no resistor device, LVS reference expansion or extraction precedent.
   The screening resistor is ideal: its own parasitic capacitance, its
   tolerance and its mismatch are unmodelled here.
4. Re-extract with klt 0.9.0, rerun the fast/hot leg, then the 45-point AC/OP
   and slew grids on the extraction. DRC and LVS must be rerun at whatever
   capacitor side is chosen: PR #439 found the `metal5.space.1` transition
   between 25.8 and 25.9 µm and an unexplained LVS mismatch at 25.8 µm, both
   above the 25.3–25.5 µm a slew margin points at, but neither is tested there.
5. If the resistor lands, the input-noise, offset, CMRR and PSRR benches need
   re-measuring on the new extraction: an ideal resistor in series with a
   capacitor cannot touch them, a drawn poly resistor can.

A resistor drawn into DR-0001 and the same resistor drawn into the #332
topology would be the same fix built twice. Which layout receives it is the
open decision; this record makes either path a sized one.

## 9. Records

50 envelopes under `records/`, each naming its fleet job in
`environment.remote.job_id`: 34 single-corner AC legs (`ext_rz<Rz>_<corner>.ac.json`
on the extraction, `bare_rz<Rz>_ff.ac.json` on the drawn DUT,
`ext_rz2000_cc<side>_<corner>.ac.json` for §7), 13 single-corner slew legs
(`*_ss.slew.json`) and the three 45-point grids of §6. `python3
../rz_screen.py dut <extraction> <out> --rz <ohms> [--bare] [--cap-side <um>]`
reproduces every single-corner DUT from the extraction of §1; the grid
envelopes ran on the DUT of the 2 kΩ leg, SHA-256 `9dd5683c0991b8638234e834ae1b20203f05271be16b95bbe7aa496c07c68aef`.

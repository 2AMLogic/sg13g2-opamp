# Issue #430 — the 24.3 µm trim: both ratified bounds hold on one drawn candidate

**Trimming the nulling-resistor candidate's Miller capacitor from 25.3 to
24.3 µm closes DR-0012's `cap_wcs` falling-slew miss while every AC bound
stays clear.** The candidate is PR #452's drawn `rppd` candidate with one
number changed — `XCc out cc_rz cap_cmim w=24.3u l=24.3u`, `XRz` untouched —
plus a 1.64 µm `TopMetal1` strap extension the smaller `cap_array` cell
needs to still reach its `cc_c4` via landing (`generate.py`'s
`devices.patch_tm1_strap_reach`, the `patch_mim_bottom_plate` pattern). It
passes DRC, LVS and ERC, and its klt 0.9.0 extraction measures **64.6954°**
at `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` (unrounded phase
−2.01244546394 rad, signed margin +0.081949638 rad; baseline 59.8136°,
−0.003254 rad; the 25.3 µm candidate 66.4616°). The 45-corner AC and OP
grids pass with zero diagnostics. Under [DR-0013](../../../spec/decision-records/0013-extracted-resistor-body-star-solver-abort.md)
clause 4 the entire extracted-leg slew row stays `ungraded` pending a rerun
with a corrected extractor — the extraction's `rppd` body still sits on its
star leaf — with both control grids recorded as the bracket (body-on-hub
control grid 45/45, worst 8.2907 V/µs; schematic grid 45/45, worst edge
8.3501 V/µs, separately gradeable for schematic-leg signoff under clause 5).

The number the trim was sized for: DR-0012's nine passive slew sections at
`mos_ss / 1.08 V / −40 °C` now **pass at every section on both edges** —
the gradeable schematic leg reads **7.6553–7.6562 / 7.6351–7.6352 V/µs**
rising/falling at `cap_wcs` (was 7.0852 / 7.0739 fail at 25.3 µm), the
body-on-hub bracket 7.9875 / 7.5844–7.5846 — against the 7.51 V/µs bound,
with the worst passive AC section keeping **61.6649°** against the 60°
bound. Both windows the capacitor trades between now overlap at one size.

#332 was checked first per the issue's implementation guidance (2026-11-24,
`origin/main` @ `fb11d9c`): it is open and no replacement topology has
landed, so the DR-0001 qualification branch applies. As with PR #452, the
design change stays on a candidate branch — `signoff/characterization/
generate.py --mint` refuses any netlist but the committed one — so this
record is evidence plus a bundle, and no file under `design/`, `layout/`
or `signoff/` changes on `main`.

## 1. The candidate

| Item | Value |
|---|---|
| Source revision | `f837d60418a768314b748ad7f02b62025b7ceefc`, branch `candidate/issue-430-rz-243` — two commits on main `fb11d9c`: `973ed2b` (schematic, netlist, layout, strap patch, regenerated artifacts, manifest pins) and `f837d60` (documentation) |
| Same change as a patch | `candidate/candidate.patch`, SHA-256 `7095b3f532952293e37c6339b65c8c9bf09933f536ed9f43437b971c8884424d`; `git apply --check` passes against main `fb11d9c` (11 files: sources, docs, manifest pins; the binary/regenerated artifacts are the bundle's own copies) |
| Device | `XRz cc_rz d2 vss rppd w=1u l=7.47u m=1 b=0` (unchanged); `XCc out cc_rz cap_cmim w=24.3u l=24.3u m=1` |
| Capacitance | `C(24.3 µm) = 1.5·24.3² + 0.16·24.3 = 889.62 fF` (92.27 % of `C(25.3 µm)` = 964.18 fF) |
| GDS | `candidate/opamp_core.gds`, SHA-256 `61ac5d53cfbd9e680f1cd778c5cdfde27db6dae5fce9b48956d39a108c9ba77d` |
| klt 0.9.0 extraction | `candidate/opamp_core_pex.spice`, SHA-256 `f32f4d0bb8eb9a9a8fb006e09cfd3aa712abf5cbd1118f932d2ac9480f4405cf` (PR #429's `klt pex --extract-only` recipe; envelope `candidate/extraction.json`: exit 4, `not_checked`, 39 devices on 10 nets, `body_bias.status = biased`, klt 0.9.0 / klayout 0.30.13). The `rppd` card is `X$39 $5__t4 $7__t1 vss__t23 rppd l=7.47U w=1U` — body on its own star leaf, so DR-0013 clause 4 governs the extracted-leg slew rows |
| Schematic netlist | `candidate/opamp_core.spice`, SHA-256 `a0f4f2b3e630d5a1559bd54e04b385eb2a17a065dfb87d8a692b7b861462758f` (xschem 3.4.7, `design/check_netlist_regen.py --update`) |
| Baselines | 25.3 µm candidate `4f0af8d` (`rz-layout-430/`, PM 66.4616°, passive-section slew 7.0739 V/µs fail); bare-capacitor layout at `36596fc` (59.8136°) |

### Structural verdicts on the candidate GDS

| Check | Tool | Result |
|---|---|---|
| Layout regeneration | klt 0.6.0 (klayout 0.30.12), `layout/klt-pin.txt` revision | regenerates; 10 nets, 95 terminals, no open, no short; `patch_tm1_strap_reach` applied (strap column 57.83–59.47 × 29.44–31.5 µm, the 24.3 µm cell's own strap top 29.44 µm being 0.34 µm short of the `cc_c4` landing) |
| DRC | `klt drc --deck sg13g2`, klt 0.6.0 | clean, 0 violations (`candidate/drc_report.json`) |
| LVS | `klt lvs`, klt 0.6.0 | match: nets 10/10, devices 39/39, pins 6; resistor card `R$39 … 1942.2 rppd L=7.47U W=1U` paired as before (`candidate/lvs_report.json`) |
| ERC supply | klt `0.6.0+g5265f1a27e8f` | clean, 0 findings (`candidate/erc_report.json`) |
| Area | `measure_area.py` | 2785.48 µm² (83.9 × 33.2 µm), was 2811.888 µm² (84.9 × 33.12 µm) at 25.3 µm (`candidate/area_measurement.json`) |

The strap extension is the one layout edit beyond the number: at 24.3 µm
the `cap_array` cell's `TopMetal1` strap tops at y = 29.44 µm and the
`cc_c4` via landing pad spans 29.78–31.42 µm — a 0.34 µm open on `cc_rz`
that the connectivity self-check caught and the patch closes by drawing
the missing column (same width, same x span). It crosses no other
`TopMetal1` geometry and changes no device.

## 2. Method

The DUT is the extraction of §1, included and instantiated as `Xdut` by
`klt_measure.py` and `rz_screen.py` exactly as in PR #452. Every
committed-bench request is built by `../rz_candidate.py bench` from that
one file (44 requests), and DR-0013's bracket by `../rz_candidate.py
bracket` from the extraction plus the candidate schematic netlist (20
requests: the body-on-hub edit `body_on_hub` of the same extraction, and
the schematic netlist, each as the 45-corner slew grid plus the nine
passive sections at the binding slew corner). All legs ran the committed
open-loop AC and slew benches through `klt sim` 0.9.3.dev on the batch
fleet against the fleet's pinned runner (klt 0.9.0, ngspice-47 KLU,
`capacity_wait_s = 600` on every request; singles as `--batch-set` with
`--capacity-retries 3`, grids with `--submit-only` then `--attach`); no
request was refused for capacity and nothing ran locally. Controls are
labelled as such wherever they appear; none of them is the committed bench
and none of them supports a bound.

PM is `180 + degrees(phase_at_ugf_rad)`; signed margin is phase minus
−2.0943951023931953 rad.

## 3. Fast/hot leg and the single corners

| leg | phase at UGF (rad) | signed margin (rad) | PM (°) | GBW (MHz) | av0 (dB) | job |
|---|---|---|---|---|---|---|
| baseline, PR #431 | −2.097648803209 | −0.003254 | 59.8136 | 10.908 | 45.7979 | `klt-sim-3e33c106fc7d` |
| 25.3 µm candidate, PR #452 | −1.981618139166 | +0.112776963 | 66.4616 | 11.1455 | 45.7976 | `klt-sim-4dd456ca73cb` |
| **24.3 µm candidate, `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C`** | **−2.01244546394** | **+0.081949638** | **64.6954** | 11.9138 | 45.7976 | `klt-sim-176933466b21` |
| `mos_sf / 1.32 V / Vinp 0.66 V / 125 °C` | −2.010191345848 | +0.084203757 | 64.8245 | 11.6172 | 46.6569 | `klt-sim-31f72b0b994c` |
| `mos_fs / 1.08 V / Vinp 0.54 V / 125 °C` (GBW corner) | −1.973178256758 | +0.121216846 | 66.9452 | 10.3575 | 42.6760 | `klt-sim-5b2cf67cca3e` |
| `mos_tt / 1.08 V / Vinp 0.54 V / 27 °C` | −1.941636258662 | +0.152758844 | 68.7524 | 11.4880 | 45.5536 | `klt-sim-4400ec7739f5` |

- The trim costs the fast/hot leg 1.7662° of the 25.3 µm candidate's PM —
  the capacitor's own 0.24–0.28° per 1 % of C, 7.73 % of C — and buys back
  slew below. Gain is unchanged to 0.0001 dB at every corner; GBW rises
  6.9 % at the binding corner, as 1/C.
- The binding single slew leg on the extraction aborts as DR-0013 predicts
  (`timestep_too_small` at 1.40292e-09 s; job `klt-sim-f14c08df2be0`); the
  bracket for that corner is §5–§6.

## 4. The 45-point grids on the committed benches

AC grid `klt-sim-4e7981ce7d35` (45/45 pass), OP grid `klt-sim-4c3f266103fc`
(45/45 pass), slew grid `klt-sim-54600add3594` (observed: 7 completed corners,
38 solver errors; entire extracted slew row **`ungraded`** per DR-0013 clause
4, §5). Zero diagnostics in the AC and OP envelopes. Envelopes:
`records/grid_ac.json`, `records/grid_op.json`, `records/grid_slew.json`.

| metric | worst value | corner | ratified limit | verdict |
|---|---|---|---|---|
| PM (phase −2.01244546394 rad) | 64.6954° | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≥ 60° | **pass** (+0.081949638 rad) |
| DC gain | 42.6760 dB | `mos_fs / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 37.8 dB | pass |
| GBW | 9.0430 MHz | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 4.74 MHz | pass |
| Iq (`ivdd_total_a`) | 84.8463 µA | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≤ 119.7 µA | pass |
| slew, rising edge (extracted) | 9.5250 V/µs (observed min across 7 completed; 38 solver errors) | `mos_sf / 1.20 V / Vinp 0.60 V / −40 °C` | ≥ 7.51 V/µs | **ungraded** (DR-0013 cl. 4; §5) |
| slew, falling edge (extracted) | 8.9880 V/µs (observed min across 7 completed; 38 solver errors) | `mos_ss / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 7.51 V/µs | **ungraded** (DR-0013 cl. 4; §5) |

Against the 25.3 µm candidate's grid, PM fell 1.7662° at the binding corner
and GBW rose 7.4 % (8.4163 → 9.0430 MHz); gain and Iq are unchanged to
0.001. The extracted slew grid is **not a grid pass** and under DR-0013
clause 4 it is not a grid failure either: the entire extracted-leg slew row
remains **`ungraded`** pending a rerun with a corrected extractor, and is
not graded by any control. On the committed grid, 7 completed corners
(all observing ≥ 7.51 V/µs on both edges) and 38 solver errors
(`timestep_too_small` and `analysis_aborted` on the `rppd` body star leaf)
are recorded as observations. Both control results in §5 are kept only as
the clause 4 bracket; under clause 5, the schematic slew leg
(`ctl_sch_grid_slew`, 45/45, worst 8.3501 V/µs) is separately gradeable for
schematic-leg signoff.

## 5. The extracted-leg slew row: ungraded under DR-0013, bracketed

The extraction's `rppd` body terminal sits on its own star leaf (`vss__t23`),
so per [DR-0013](../../../spec/decision-records/0013-extracted-resistor-body-star-solver-abort.md)
clause 4 — decided by #451 after PR #452's controls — the entire
extracted-leg slew row of this candidate is **`ungraded` on the committed
bench**, neither failed nor graded by a control: as observations, the grid
records 7 completed corners and 38 solver errors (`records/grid_slew.json`,
every diagnostic preserved; 37 name `xdut.ibias__t12` at timesteps cut to
6.25e-23 s and one names `xdut.vss__t1`, the same node family), the single
binding leg aborts
(`klt-sim-f14c08df2be0`), and 8 of the 9 passive sections abort
(`records/pass_ss_*.slew.json`; the 1 completed corner,
`res_bcs + cap_bcs`, job `klt-sim-278360d2a909`, observes 9.6986 /
9.1396 V/µs — the same one-in-nine completion rate DR-0013 records).

While the extractor ask
([2AMLogic/klayout-tools#7317](https://github.com/2AMLogic/klayout-tools/issues/7317))
is open, both control grids below are recorded as the DR-0013 clause 4
bracket for the ungraded extracted row (neither grades the extracted row).
Separately, under DR-0013 clause 5, the schematic netlist leg
(`ctl_sch_grid_slew`) is gradeable on its own for schematic-leg signoff:

| bracket, worst edge over 45 corners | worst edge (V/µs) | corner | job |
|---|---|---|---|
| schematic netlist (`ctl_sch_grid_slew`; separately gradeable per DR-0013 cl. 5) | 8.3501 falling (rising ≥ 8.3851) | `mos_ss / 1.08 V / −40 °C` | `klt-sim-9bd6fa5e1522` |
| same extraction, body on hub (`ctl_bodyhub_grid_slew`; control bracket only) | 8.2907 falling (rising ≥ 8.7603) | `mos_ss / 1.08 V / −40 °C` | `klt-sim-9af67e045da5` |

Both control grids complete 45/45 with zero diagnostics and sit 11.2 % /
10.4 % above the 7.51 V/µs bound at their worst edge. The DR-0013 clause 4
re-run obligation stands: the extracted-leg slew row stays **`ungraded`**
until a pinned extractor release re-homes body terminals and the
extracted-leg slew grid is re-run on the committed bench against this
candidate.

## 6. DR-0012's nine passive sections

`{res_bcs, res_typ, res_wcs} × {cap_bcs, cap_typ, cap_wcs}` at nominal
(`mos_tt / 27 °C / 1.20 V`) and at the binding corners for PM and GBW. AC
on the extraction, 27 legs, all pass (`records/pass_*.ac.json`):

| point | resistor section | PM (°), `cap_bcs` | PM (°), `cap_typ` | PM (°), `cap_wcs` |
|---|---|---|---|---|
| `mos_ff / 1.32 V / 125 °C` | `res_bcs` | **61.6649** | 64.0275 | 66.0711 |
| | `res_typ` | 62.3042 | 64.6954 | 66.7617 |
| | `res_wcs` | 62.9406 | 65.3604 | 67.4495 |
| `mos_fs / 1.08 V / 125 °C` | `res_bcs` | 64.1823 | 66.3591 | 68.2250 |
| | `res_typ` | 64.7456 | 66.9452 | 68.8293 |
| | `res_wcs` | 65.3067 | 67.5292 | 69.4316 |
| `mos_tt / 1.20 V / 27 °C` | `res_bcs` | 64.3216 | 66.6651 | 68.6383 |
| | `res_typ` | 64.9842 | 67.3544 | 69.3485 |
| | `res_wcs` | 65.6440 | 68.0409 | 70.0560 |

At `res_typ`, GBW at `cap_bcs` / `cap_typ` / `cap_wcs` is 12.9367 / 11.9138
/ 11.0183 MHz at `mos_ff / 1.32 V / 125 °C`, 11.2628 / 10.3575 /
9.5713 MHz at `mos_fs / 1.08 V / 125 °C` and 13.5950 / 12.4754 /
11.5284 MHz at nominal; gain is 45.7976, 42.6760 and 46.7213 dB at the
three points and does not move with either section. The lowest phase
margin over all 27 legs is **61.6649°**, at `res_bcs` with `cap_bcs` at
the binding corner (job `klt-sim-2859af83336f`), 1.66° above the bound;
the lowest GBW is 9.5691 MHz at `mos_fs / 1.08 V / 125 °C` with `res_bcs`
and `cap_wcs` (`klt-sim-21228dc85599`), 2.02× the bound.

**Slew at the binding corner clears 7.51 V/µs at every section on the
gradeable schematic leg and both bracket controls.** The nine extracted
passive slew legs remain **`ungraded`** under DR-0013 clause 4 (observed:
1 completed corner, 8 solver errors; §5). Below are the separately
gradeable schematic legs under DR-0013 clause 5 and the body-on-hub
extraction control bracket (control only; does not grade the extracted row),
at `mos_ss / 1.08 V / −40 °C`, rising / falling in V/µs (bound ≥ 7.51 on
both edges):

| schematic (gradeable per DR-0013 cl. 5) | `cap_bcs` | `cap_typ` | `cap_wcs` |
|---|---|---|---|
| `res_bcs` | 9.2683 / 9.2113 pass | 8.3855 / 8.3500 pass | **7.6562 / 7.6351 pass** |
| `res_typ` | 9.2677 / 9.2116 pass | 8.3851 / 8.3501 pass | **7.6557 / 7.6352 pass** |
| `res_wcs` | 9.2672 / 9.2117 pass | 8.3846 / 8.3502 pass | **7.6553 / 7.6352 pass** |

| body-on-hub extraction control (bracket only) | `cap_bcs` | `cap_typ` | `cap_wcs` |
|---|---|---|---|
| `res_bcs` | 9.6986 / 9.1396 | 8.7603 / 8.2907 | **7.9875 / 7.5846** |
| `res_typ` | 9.6986 / 9.1396 | 8.7603 / 8.2907 | **7.9875 / 7.5845** |
| `res_wcs` | 9.6986 / 9.1395 | 8.7602 / 8.2906 | **7.9875 / 7.5844** |

The 18 envelope jobs are in `controls/ctl_{sch,bodyhub}_ss_<res>_<cap>_slew.slew.json`.
The trim moves the `cap_wcs` falling edge as 1/C predicts: on the
`res_bcs / cap_wcs` schematic leg (`ctl_sch_ss_res_bcs_cap_wcs_slew.slew.json`),
`sr_fall_v_per_us` rises 7.93 % (**7.073931 → 7.635106 V/µs**) for 7.73 %
less capacitance, and the resistor section still changes slew by under
0.02 %. At 25.3 µm those `cap_wcs` legs failed by 5.8 %; at 24.3 µm the
schematic leg passes by 1.67 % (worst falling 7.6351 V/µs) and the
body-on-hub control bracket sits 0.99 % above 7.51 V/µs (worst falling
7.5844 V/µs).

## 7. Disposition

**Both ratified bounds hold at one demonstrated size: 24.3 µm.** Phase
margin (the finding #430 was filed for): 64.6954° at the binding corner,
61.6649° over the nine passive sections, 45/45 on the AC grid. Slew: the
separately gradeable schematic leg (DR-0013 clause 5) clears 7.51 V/µs on
both edges across the 45-corner grid and at every passive section, while
the extracted-leg slew row stays **`ungraded`** under DR-0013 clause 4 with
both control results kept as its bracket pending a rerun with a corrected
extractor.

The measured trade-off between the two simulated drawn-`rppd` candidates
(25.3 µm in `rz-layout-430/` vs **24.3 µm** here, at fixed bias
`Iq ≈ 85 µA`, `CL = 2 pF`, `Rz = 2 kΩ`): shrinking `Cc` by 7.73 %
(`964.18 → 889.62 fF`) **reduced** worst passive-section PM (`mos_ff /
1.32 V / 125 °C`, `res_bcs / cap_bcs`) from **63.4876° to 61.6649°**
(−1.8227°, leaving 1.6649° above 60°) and **increased** `res_bcs / cap_wcs`
schematic falling slew from **7.073931 V/µs** (fail, below 7.51) to
**7.635106 V/µs** (+7.93 %, +1.67 % above 7.51; body-on-hub control worst
7.5844 V/µs, +0.99 %). A smaller capacitor therefore reduces PM and
increases slew: around 24.3 µm, a further 1 % reduction in `C` moves PM
roughly **−0.23° to −0.30°** (−0.23° from the 25.3 → 24.3 µm worst-passive
slope of 22.65°/ln C; −0.25° to −0.30° across the 24.3 µm `cap_bcs`–`cap_wcs`
sections at `res_typ`) and moves slew roughly **+1 %** (as 1/C). Only
**24.3 µm** is directly simulated and verified to clear both bounds; any
endpoint bounds around it are unsimulated extrapolations anchored at 24.3 µm
at fixed bias and `Rz = 2 kΩ`:

- **Estimated upper side bound** (`cap_wcs` falling slew = 7.51 V/µs,
  assuming pure 1/C scaling from 24.3 µm): **~24.5 µm** on the schematic
  leg (`7.6351 V/µs → C ≈ 904.4 fF`, `s ≈ 24.50 µm`) or **~24.4 µm** on the
  body-on-hub control (`7.5844 V/µs → C ≈ 898.4 fF`, `s ≈ 24.42 µm`). The
  25.3 µm candidate is already above this limit (7.0739 V/µs fail); the
  ~25.65 µm figure from `cc-sizing-430/` was the `cap_typ` bare-capacitor
  crossover, not `cap_wcs`.
- **Estimated lower side bound** (worst passive `res_bcs / cap_bcs` fast/hot
  PM = 60°, extrapolating from 61.6649° at 24.3 µm): **~23.4 µm** assuming
  the 25.3 → 24.3 µm log-linear slope (22.65°/ln C, `C ≈ 826.6 fF`,
  `s ≈ 23.42 µm`), or **~23.5–23.6 µm** assuming a steeper linear
  0.26–0.30° per 1 % of `C` (`C ≈ 833–840 fF`).

**#312.** The qualifying reference is now `f837d60` on
`candidate/issue-430-rz-243` (this record's `candidate/` bundle; patch
`7095b3f5…` against main `fb11d9c`). The landing constraint is unchanged
from PR #452's §7: `signoff/characterization/generate.py --mint` refuses
every schematic-leg record simulated against any netlist but the committed
one, so the design lands in the same change as #312's coordinated evidence
refresh (the `layout/klt-pin.txt` bump, the schematic-leg re-minting and
the Monte Carlo policy of #326), not before it. Under DR-0013 clause 4 the
extracted-leg slew row stays `ungraded` (with controls recorded as its
bracket) until the extractor fix is pinned; under clause 5 the schematic
slew leg and the rest of the row set grade normally.

**#332 / #342.** Carried into the new topology's compensation sizing, on
top of PR #452's numbers:

- **resistor-only sensitivity (fixed-capacitance controls)**: on the fixed
  25.7 µm `cap_cmim` extraction (`rz-nulling-430/`, ideal-resistor sweep vs
  its 0.1 Ω control at 59.8139°), 2 kΩ lifts fast/hot PM to 67.0238°
  (+7.21°, 3.61°/kΩ average; local slope 3.27–3.67°/kΩ across 0.25–10 kΩ)
  for no DC gain change, no supply-current change and −0.32 % (< 0.4 %) of
  GBW. On the drawn `rppd` candidates at fixed `cap_typ`, the ±10 %
  `res_bcs`/`res_wcs` section spread around 2.00 kΩ (`ΔR = 0.400 kΩ`) moves
  fast/hot PM by **3.43°/kΩ** at fixed 25.3 µm (`rz-layout-430/`,
  65.7746° → 67.1460°) and **3.33°/kΩ** at fixed 24.3 µm (this record,
  64.0275° → 65.3604°). Against the 25.7 µm bare-capacitor baseline
  (`36596fc`, 59.8136°), the net lift — which combines adding `2 kΩ rppd`
  with shrinking `Cc` — is +4.88° at 24.3 µm (64.6954°) and +6.65° at
  25.3 µm (66.4616°);
- **capacitor trade rate with `Rz = 2 kΩ` present**: a smaller capacitor
  reduces PM and increases slew. Trimming 25.3 → 24.3 µm (−7.73 % of `C`)
  moved worst passive PM from 63.4876° to 61.6649° (−1.8227°, 22.65°/ln C)
  and `res_bcs / cap_wcs` schematic falling slew from 7.073931 to
  7.635106 V/µs (+7.93 %, as 1/C); across the 24.3 µm `cap_bcs`–`cap_wcs`
  sections at `res_typ`, PM moves 0.25–0.30° per 1 % of `C` (0.24–0.28° at
  25.3 µm);
- **demonstrated qualifying size and estimated overlap window** at this
  bias (`Iq ≈ 85 µA`, `CL = 2 pF`, `Rz = 2 kΩ rppd`): **24.3 µm**
  (`889.62 fF`) is the demonstrated size clearing both bounds (61.6649°
  worst passive PM vs ≥ 60°; 7.6351 V/µs schematic / 7.5844 V/µs worst
  body-on-hub `cap_wcs` falling slew vs ≥ 7.51 V/µs; 25.3 µm failed
  `cap_wcs` slew at 7.0739 V/µs). Extrapolated (unsimulated) endpoints from
  24.3 µm at fixed bias and `Rz = 2 kΩ`: **~23.4–23.6 µm** lower bound
  (assuming 22.65°/ln C to 0.30°/1 % C PM slope to 60°) to **~24.5 µm**
  schematic / **~24.4 µm** body-on-hub upper bound (assuming 1/C slew
  scaling to 7.51 V/µs);
- a drawn PDK resistor leaves the extracted-leg slew row `ungraded` under
  DR-0013 clause 4 until 2AMLogic/klayout-tools#7317 lands (recorded with
  controls as a bracket, never graded by a control), while the schematic
  slew leg stays separately gradeable under clause 5.

Nothing here relaxes a ratified bound or moves a spec row. Existing
records under `cc-sizing-430/`, `rz-nulling-430/`, `rz-layout-430/` and
`rz-solver-451/` are untouched controls.

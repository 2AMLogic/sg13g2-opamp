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
grids pass with zero diagnostics. The extracted-leg slew rows stay
`ungraded` under [DR-0013](../../spec/decision-records/0013-extracted-resistor-body-star-solver-abort.md)
— the extraction's `rppd` body still sits on its star leaf — with the
bracket this record adds: the schematic grid 45/45 (worst edge
8.3501 V/µs) and the body-on-hub control grid 45/45 (worst 8.2907 V/µs).

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
| Area | `measure_area.py` | 2775.662 µm² (83.9 µm wide), was 2811.888 µm² at 25.3 µm (`candidate/area_measurement.json`) |

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
(45/45 pass), slew grid `klt-sim-54600add3594` (7 pass, **38 error**, §5).
Zero diagnostics in the AC and OP envelopes. Envelopes: `records/grid_ac.json`,
`records/grid_op.json`, `records/grid_slew.json`.

| metric | worst value | corner | ratified limit | verdict |
|---|---|---|---|---|
| PM (phase −2.01244546394 rad) | 64.6954° | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≥ 60° | **pass** (+0.081949638 rad) |
| DC gain | 42.6760 dB | `mos_fs / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 37.8 dB | pass |
| GBW | 9.0430 MHz | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 4.74 MHz | pass |
| Iq (`ivdd_total_a`) | 84.8463 µA | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≤ 119.7 µA | pass |
| slew, rising edge | 9.5250 V/µs of 7 measured | `mos_sf / 1.20 V / Vinp 0.60 V / −40 °C` | ≥ 7.51 V/µs | 7 pass, **38 ungraded** (§5) |
| slew, falling edge | 8.9880 V/µs of 7 measured | `mos_ss / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 7.51 V/µs | 7 pass, **38 ungraded** (§5) |

Against the 25.3 µm candidate's grid, PM fell 1.7662° at the binding corner
and GBW rose 7.4 % (8.4163 → 9.0430 MHz); gain and Iq are unchanged to
0.001. The slew grid is **not a grid pass** and under DR-0013 it is not a
grid failure either: every leg that completes passes both edges, the other
38 carry `timestep_too_small` and `analysis_aborted` on the `rppd` body
star leaf, and the row grades by its bracket (§5).

## 5. The extracted-leg slew row: ungraded under DR-0013, bracketed

The extraction's `rppd` body terminal sits on its own star leaf (`vss__t23`),
so per [DR-0013](../../spec/decision-records/0013-extracted-resistor-body-star-solver-abort.md)
clause 4 — decided by #451 after PR #452's controls — the extracted-leg
slew row of this candidate is **`ungraded` on the committed bench**, not
failed: the grid aborts 38 of 45 corners (`records/grid_slew.json`, every
diagnostic preserved; 37 name `xdut.ibias__t12` at timesteps cut to
6.25e-23 s and one names `xdut.vss__t1`, the same node family), the single
binding leg aborts
(`klt-sim-f14c08df2be0`), and 8 of the 9 passive sections abort
(`records/pass_ss_*.slew.json`; the one that completes,
`res_bcs + cap_bcs`, job `klt-sim-278360d2a909`, passes at 9.6986 /
9.1396 V/µs — the same one-in-nine lottery pass rate DR-0013 records).

What the row reads while the extractor ask
([2AMLogic/klayout-tools#7317](https://github.com/2AMLogic/klayout-tools/issues/7317))
is open, from this record's `bracket` legs (all controls, none the
committed bench):

| bracket, worst edge over 45 corners | worst edge (V/µs) | corner | job |
|---|---|---|---|
| schematic netlist (`ctl_sch_grid_slew`) | 8.3501 falling (rising ≥ 8.3851) | `mos_ss / 1.08 V / −40 °C` | `klt-sim-9bd6fa5e1522` |
| same extraction, body on hub (`ctl_bodyhub_grid_slew`) | 8.2907 falling (rising ≥ 8.7603) | `mos_ss / 1.08 V / −40 °C` | `klt-sim-9af67e045da5` |

Both brackets pass 45/45 with zero diagnostics and sit 11.2 % / 10.4 %
above the 7.51 V/µs bound at their worst edge. The DR-0013 re-run
obligation stands: when a pinned extractor release re-homes body
terminals, the extracted-leg slew grid is re-run on the committed bench
against this candidate.

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

**Slew at the binding corner now passes at every section.** The nine
extracted legs are ungraded per §5 (8 abort, 1 lottery-passes); the
gradeable schematic legs and the body-on-hub bracket, `mos_ss / 1.08 V /
−40 °C`, rising / falling in V/µs (bound ≥ 7.51 on both edges):

| schematic | `cap_bcs` | `cap_typ` | `cap_wcs` |
|---|---|---|---|
| `res_bcs` | 9.2683 / 9.2113 pass | 8.3855 / 8.3500 pass | **7.6562 / 7.6351 pass** |
| `res_typ` | 9.2677 / 9.2116 pass | 8.3851 / 8.3501 pass | **7.6557 / 7.6352 pass** |
| `res_wcs` | 9.2672 / 9.2117 pass | 8.3846 / 8.3502 pass | **7.6553 / 7.6352 pass** |

| body-on-hub extraction control | `cap_bcs` | `cap_typ` | `cap_wcs` |
|---|---|---|---|
| `res_bcs` | 9.6986 / 9.1396 pass | 8.7603 / 8.2907 pass | **7.9875 / 7.5846 pass** |
| `res_typ` | 9.6986 / 9.1396 pass | 8.7603 / 8.2907 pass | **7.9875 / 7.5845 pass** |
| `res_wcs` | 9.6986 / 9.1395 pass | 8.7602 / 8.2906 pass | **7.9875 / 7.5844 pass** |

The 18 envelope jobs are in `controls/ctl_{sch,bodyhub}_ss_<res>_<cap>_slew.slew.json`.
The trim moves the `cap_wcs` falling edge exactly as 1/C predicts: the
schematic leg gains 7.93 % (7.0739 → 7.6351 V/µs) for 7.73 % less
capacitance, and the resistor section still changes slew by under 0.02 %.
At 25.3 µm the same legs failed by 5.8 %; at 24.3 µm they pass by 1.67 %
(schematic) / 0.99 % (body-on-hub bracket).

## 7. Disposition

**Both ratified bounds hold at one size.** Phase margin (the finding #430
was filed for): 64.6954° at the binding corner, 61.6649° over the nine
passive sections, 45/45 on the AC grid. Slew: every gradeable leg and both
brackets clear 7.51 V/µs on both edges at every passive section, the
extracted-leg row ungraded-with-bracket per DR-0013. The measured
trade-off the next iteration inherits: at 24.3 µm the trim spent 1.823° of
the 25.3 µm candidate's 3.49° passive-section PM margin to buy 7.9 % of
`cap_wcs` slew; the windows at fixed bias now overlap with 1.66° of PM and
1.67 % of slew to spare, and a further 1 % trim of C would move each
roughly +0.26° / −1 % — the crossover sits near 23.9 µm if slew margin
ever needs buying again.

**#312.** The qualifying reference is now `f837d60` on
`candidate/issue-430-rz-243` (this record's `candidate/` bundle; patch
`7095b3f5…` against main `fb11d9c`). The landing constraint is unchanged
from PR #452's §7: `signoff/characterization/generate.py --mint` refuses
every schematic-leg record simulated against any netlist but the committed
one, so the design lands in the same change as #312's coordinated evidence
refresh (the `layout/klt-pin.txt` bump, the schematic-leg re-minting and
the Monte Carlo policy of #326), not before it. The extracted-leg slew row
it will regenerate stays ungraded until the extractor fix of DR-0013 is
pinned; everything else in the row set grades from this record.

**#332 / #342.** Carried into the new topology's compensation sizing, on
top of PR #452's numbers:

- the drawn 2 kΩ `rppd` lifts fast/hot phase margin 4.88° above the
  bare-capacitor baseline at 24.3 µm (6.65° at 25.3 µm), 3.43° per kΩ, for
  no gain, no supply current and under 0.4 % of GBW;
- with the resistor present the capacitor trades PM for slew at
  0.24–0.28° per 1 % of C against 1/C of slew, both sections measured;
- at DR-0012's `cap_wcs` the 7.51 V/µs bound and the 60° PM bound overlap
  only below ~25.65 µm and above ~23.9 µm of square side at this bias —
  the measured crossover window, should the new topology want to re-derive
  its own;
- a drawn PDK resistor leaves the extracted-leg slew row ungraded until
  2AMLogic/klayout-tools#7317 lands (DR-0013): budget the bracket, not the
  bench, for that row.

Nothing here relaxes a ratified bound or moves a spec row. Existing
records under `cc-sizing-430/`, `rz-nulling-430/`, `rz-layout-430/` and
`rz-solver-451/` are untouched controls.

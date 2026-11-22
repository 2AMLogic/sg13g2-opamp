# Issue #430 — the drawn nulling resistor: candidate, extraction and corner grids

**The drawn candidate clears the fast/hot phase-margin bound with 6.46° to
spare, and the committed slew bench cannot grade its extraction.** A nominal
2 kΩ PDK `rppd` resistor in series with a 25.3 µm Miller capacitor — the
geometry PR #445 pointed at — is drawn into DR-0001, passes DRC, LVS and ERC,
and its klt 0.9.0 extraction measures **66.4616°** at `mos_ff / 1.32 V /
Vinp 0.66 V / 125 °C` (unrounded phase −1.981618139166 rad, signed margin
+0.112776963 rad; baseline 59.8136°, −0.003254 rad). The 45-corner AC and OP
grids pass with zero diagnostics. The 45-corner slew grid aborts on 37
corners with `timestep_too_small`, and the controls in §6 put the trigger on
the PDK `rppd` card of the extracted netlist, not on the layout's parasitics.

Two further facts decide what can land. On the schematic netlist the same
resistor passes the slew grid 45/45, but DR-0012's independent passive
sections put falling slew at **7.07 V/µs** at `cap_wcs`, against the 7.51
V/µs bound, at every resistor section. And the candidate is a netlist change:
`signoff/characterization/generate.py --mint` refuses it, because every
committed schematic-leg record simulates the previous netlist. **The design
therefore stays on a candidate branch** (§1); this record is evidence, and
no file under `design/`, `layout/` or `signoff/` changes.

All legs ran the committed open-loop AC and slew benches through `klt sim`
0.9.0 on the batch fleet (`capacity_wait_s = 600` on every request; singles
as `--batch-set` with `--capacity-retries 3`, grids with `--submit-only`
then `--attach`); no request was refused for capacity and nothing ran
locally. Controls are labelled as such wherever they appear; none of them
is the committed bench and none of them supports a bound.

## 1. The candidate

| Item | Value |
|---|---|
| Source revision | `4f0af8db24bf9ad2cc985f701b105db39e88c073`, branch `candidate/issue-430-rz` — two commits on main `ca30f38`: `95dfee6` (schematic, netlist, layout, regenerated artifacts, manifest pins) and `4f0af8d` (documentation) |
| Same change as a patch | `candidate/candidate.patch`, SHA-256 `9a3f4ba7431f4850d2f7ab55eac85cf79c615be51ba43e09f63387d6a4dc1d51`; `git apply --check` passes against main `4aef58a` |
| Device | `XRz cc_rz d2 vss rppd w=1u l=7.47u m=1 b=0`; `XCc out cc_rz cap_cmim w=25.3u l=25.3u m=1` |
| GDS | `candidate/opamp_core.gds`, SHA-256 `8f5e66fd8914501f35291500913bbc87880500ec4fbcd564455f198eb0edf22f` |
| klt 0.9.0 extraction | `candidate/opamp_core_pex.spice`, SHA-256 `7acd312ef6e9496e26a2d1cab45de147d12a1a68c8a883e636a640f9b425f253` (PR #429's `klt pex --extract-only` recipe; envelope `candidate/extraction.json`: exit 4, `not_checked`, 39 devices on 10 nets, `body_bias.status = biased`) |
| Schematic netlist | `candidate/opamp_core.spice`, SHA-256 `c00a892ede5a5695296204875fa2be34efdf89d505af31cfa4c8ff6c9a91b261` (xschem 3.4.7, `design/check_netlist_regen.py --update`) |
| Baseline, for comparison | retained 25.7 µm layout at `36596fc`: GDS `ab2d926e…`, extraction `80cd19a1…`, fast/hot phase −2.097648803209 rad (PR #431, job `klt-sim-3e33c106fc7d`) |

The resistor is `klt gen res_array` with `flavor="rppd"`: an 8.31 µm × 1.0 µm
poly body placed above the capacitor's `Metal5` plate, right of its
`TopMetal1` strap. `d2` ends at its `R0_A` pad; its `R0_B` pad rises to a new
`cc_c4` track that returns to the strap. The extraction carries it as
`X$39 $5__t4 $8__t1 vss__t23 rppd l=7.47U w=1U`, between the `d2` hub `$5`
and the series-node hub `$8`, with its body on the `vss` rail.

Nominal resistance is the PDK symbol's expression at `res_typ`,
`70e-6 / w + 260 * l / (w + 6e-9)` = **2000.6 Ω**; the klt 0.9.0 deck reports
the same 2000.6 Ω. `design/opamp_sizing.md` on the candidate branch carries
the sizing basis.

### Structural verdicts on the candidate GDS

| Check | Tool | Result |
|---|---|---|
| Layout regeneration | klt 0.6.0 at `layout/klt-pin.txt`, builder KLayout 0.30.10 | `generate.py --check` byte-identical; 10 nets, 95 terminals, no open, no short |
| DRC | `klt drc --deck sg13g2`, klt 0.6.0 | clean, 0 violations; the resistor's identification layers `28/0`, `111/0`, `128/0` join `14/0` under `layers_in_stream_without_rules` |
| LVS | `klt lvs`, klt 0.6.0 | match: nets 10/10, devices 39/39, pins 6; the resistor extracts as class `rppd`, `R$39 $5 $8 vss 1942.2 rppd L=7.47U W=1U`, paired with the reference card |
| ERC supply | klt `0.6.0+g5265f1a27e8f` | clean, 0 findings |
| Area | `measure_area.py` | 2811.888 µm² (84.9 µm × 33.1 µm), was 2775.662 µm² |

The pinned LVS deck values the resistor at 260 Ω/sq × L/W = 1942.2 Ω, without
the contact resistance or width offset; the reference mirrors that formula,
so the compare is the deck agreeing with itself and the electrical nominal
stays 2000.6 Ω. The candidate reports are in `candidate/`.

## 2. Method

The DUT is the extraction of §1, included and instantiated as `Xdut` by
`klt_measure.py` and `rz_screen.py` exactly as in PR #445. Every request is
built by `../rz_candidate.py bench` from that one file; it regenerates all
44 requests of `records/` byte-for-byte, and `../rz_candidate.py control`
regenerates all 35 of `controls/` from the extraction and the schematic
netlist. The process bundles carry `cornerMOSlv.lib`, `cornerCAP.lib` and
`cornerRES.lib` sections as #446 left them.

PM is `180 + degrees(phase_at_ugf_rad)`; signed margin is phase minus
−2.0943951023931953 rad.

## 3. Fast/hot leg and the single corners

| leg | phase at UGF (rad) | signed margin (rad) | PM (°) | GBW (MHz) | av0 (dB) | job |
|---|---|---|---|---|---|---|
| baseline, PR #431 | −2.097648803209 | −0.003254 | 59.8136 | 10.908 | 45.7979 | `klt-sim-3e33c106fc7d` |
| **candidate, `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C`** | **−1.981618139166** | **+0.112776963** | **66.4616** | 11.1455 | 45.7976 | `klt-sim-4dd456ca73cb` |
| `mos_sf / 1.32 V / Vinp 0.66 V / 125 °C` | −1.979748010637 | +0.114647092 | 66.5688 | 10.8747 | 46.6569 | `klt-sim-4a65dffbfc53` |
| `mos_fs / 1.08 V / Vinp 0.54 V / 125 °C` (GBW corner) | −1.945149400302 | +0.149245702 | 68.5511 | 9.6862 | 42.6760 | `klt-sim-3e18dca3f9cc` |
| `mos_tt / 1.08 V / Vinp 0.54 V / 27 °C` | −1.913500845275 | +0.180894257 | 70.3645 | 10.7352 | 45.5536 | `klt-sim-0c8ae9417918` |

- The binding corner reads 66.4616°: 6.4616° above the bound, 6.6480° above
  the bare-capacitor baseline, and 0.0816° above the screening leg it was
  sized from (ideal 2 kΩ with a 25.3 µm capacitor on the retained
  extraction, 66.3800°, PR #445). The drawn model and the new parasitics
  together cost nothing visible: the grid's fast/hot corner equals this leg
  to all printed digits.
- TT / 1.08 V / 27 °C passes with no diagnostic.
- Gain is unchanged within 0.001 dB at every screened corner (the resistor
  sits behind a capacitor, so the operating point cannot move).

## 4. The 45-point grids on the committed benches

AC grid `klt-sim-6a7dc3460919` (45/45 pass), OP grid `klt-sim-ebdc51dbffd3`
(45/45 pass), slew grid `klt-sim-aa4d9ece076e` (8 pass, **37 error**). Zero
diagnostics in the AC and OP envelopes. Envelopes: `records/grid_ac.json`,
`records/grid_op.json`, `records/grid_slew.json`.

| metric | worst value | corner | ratified limit | verdict |
|---|---|---|---|---|
| PM (phase −1.981618139166 rad) | 66.4616° | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≥ 60° | **pass** (+0.112776963 rad) |
| DC gain | 42.6760 dB | `mos_fs / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 37.8 dB | pass |
| GBW | 8.4163 MHz | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 4.74 MHz | pass |
| Iq (`ivdd_total_a`) | 84.8463 µA | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≤ 119.7 µA | pass |
| slew, rising edge | 8.9593 V/µs of 8 measured | `mos_ss / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 7.51 V/µs | 8 pass, **37 ungraded** |
| slew, falling edge | 8.3493 V/µs of 8 measured | `mos_ss / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 7.51 V/µs | 8 pass, **37 ungraded** |

The four lowest phase margins are 66.4616° (FF), 66.5688° (SF), 66.6184° (SS)
and 66.8478° (FS), all at 1.32 V / 125 °C; the highest is 76.8118° at
`mos_ss / 1.08 V / −40 °C`. Against PR #445's ideal-resistor grid at the
25.7 µm capacitor, the binding AC numbers moved the way the smaller
capacitor predicts: PM −0.56°, GBW +2.9 %, gain and Iq unchanged to 0.001.

The slew grid is **not a grid pass**. The 8 measured corners all pass on both
edges and every other measurement; the other 37 carry `timestep_too_small`
and `analysis_aborted` (§5). A partial grid cannot establish a full-grid
pass.

## 5. The slew bench cannot grade the extracted candidate

| leg, `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | verdict | abort | job |
|---|---|---|---|
| candidate, committed bench | error | `xdut.ibias__t12`, 5.07812e-12 s | `klt-sim-d5b717b82ba5` |
| nine passive sections, committed bench | 9 × error | `xdut.ibias__t12` in 8, `xdut.vss__t1` in 1; 6.875e-12 to 3.96e-09 s | `records/pass_ss_*.slew.json` |

In the grid, 37 corners abort the same way: 24 name `xdut.ibias__t12` at a
time between 7.8e-14 and 2.7e-08 s with the timestep cut to 6.25e-23 s, and 13
fail at the initial timepoint on the same node. The node is the drain
terminal of one unit of the diode-connected `Mbias`, on the parasitic star
network; PR #439's 26.0 µm grid lost one corner the same way, on
`xdut.ibias__t0`. Nothing is suppressed: every diagnostic is in the envelope.

The same bench at the same corner, with one thing changed at a time:

| control | verdict | rising / falling (V/µs) | job |
|---|---|---|---|
| same extraction, `rppd` card swapped for an ideal 2000.6 Ω | pass | 8.1009 / 7.6888 | `klt-sim-c6f7a52627da` |
| schematic netlist, with its `rppd` card | pass | 7.7626 / 7.7401 | `klt-sim-9544ea96c7b5` |
| `method=gear` | pass | 8.1003 / 7.6881 | `klt-sim-5a144c630274` |
| card body moved from `vss__t23` to the `vss` hub | pass | 8.1003 / 7.6881 | `klt-sim-2a4f50276d0c` |
| `sw_et=1` on the card, `res_typ` / `cap_typ` | error | `xdut.ibias__t12`, 1.92683e-09 s | `klt-sim-fe709b78c1ba` |

Readings, each with the sample size that supports it:

- **The layout is not the trigger.** The extraction with an ideal resistor in
  place of the model card runs the committed bench cleanly, and reads the
  slew the screening predicted for this geometry (8.1030 / 7.6909, PR #445).
- **The model card is.** Removing only the card cures the corner; keeping it
  on the schematic netlist, which has no star network, also runs — the whole
  45-corner grid passes there with zero diagnostics (below). The model alone
  in a transient runs under both integration methods (`controls/probe_r_*.json`).
- **No knob tried is a cure.** `method=gear` passes this corner and its grid
  still aborts on 36 of 45 (job `klt-sim-982291a18712`, 9 pass), with the
  same node. At this corner 8 of the 9 passive sections abort under `gear`,
  8 of 9 with `sw_et=1`, and the single pass under each lands on a different
  section. Which corners pass is a lottery with roughly a one-in-five rate,
  not a property of the corner: the 8 that pass on the committed bench and
  the 9 under `gear` are not the same set, and the binding `mos_ss / 1.08 V /
  −40 °C` corner is in the second set only.
- The three controls that pass at the binding corner agree to 0.01 %: 8.10 /
  7.69 V/µs, with falling slew 2.4 % above the bound.

The cause is open. It is the family PR #431's TT investigation owns — a
solver path on the `ibias` star nodes — now reached from a device model
rather than a corner, and it gates the extracted-leg slew row for any design
that draws a PDK resistor.

## 6. DR-0012's nine passive sections

`{res_bcs, res_typ, res_wcs} × {cap_bcs, cap_typ, cap_wcs}` at nominal
(`mos_tt / 27 °C / 1.20 V`) and at the binding corners for PM and GBW. AC on
the extraction, 27 legs, all pass (`records/pass_*.ac.json`):

| point | resistor section | PM (°), `cap_bcs` | PM (°), `cap_typ` | PM (°), `cap_wcs` |
|---|---|---|---|---|
| `mos_ff / 1.32 V / 125 °C` | `res_bcs` | 63.4876 | 65.7746 | 67.6994 |
| | `res_typ` | 64.1492 | **66.4616** | 68.4070 |
| | `res_wcs` | 64.8079 | 67.1460 | 69.1118 |
| `mos_fs / 1.08 V / 125 °C` | `res_bcs` | 65.8545 | 67.9495 | 69.7392 |
| | `res_typ` | 66.4358 | 68.5511 | 70.3562 |
| | `res_wcs` | 67.0150 | 69.1507 | 70.9712 |
| `mos_tt / 1.20 V / 27 °C` | `res_bcs` | 66.1337 | 68.3386 | 70.2117 |
| | `res_typ` | 66.8160 | 69.0459 | 70.9386 |
| | `res_wcs` | 67.4954 | 69.7504 | 71.6629 |

At `res_typ`, GBW at `cap_bcs` / `cap_typ` / `cap_wcs` is 12.1463 / 11.1455 /
10.3017 MHz at `mos_ff / 1.32 V / 125 °C`, 10.5685 / 9.6862 / 8.9240 MHz at
`mos_fs / 1.08 V / 125 °C` and 12.7288 / 11.6729 / 10.7619 MHz at nominal;
gain is 45.7976, 42.6760 and 46.7213 dB at the three points and does not
move with either section.

 The
lowest phase margin over all 27 legs is **63.4876°**, at `res_bcs` with
`cap_bcs` at the binding corner (job `klt-sim-c540813d0819`), 3.49° above
the bound; the lowest GBW is 8.9224 MHz at `mos_fs / 1.08 V / 125 °C` with
`res_bcs` and `cap_wcs` (`klt-sim-2ccd4af24278`), 1.88× the bound. The
resistor's ±10 % section spread moves fast/hot phase margin by 3.43° per
kΩ, inside the 3.3–3.7° PR #445 measured; the capacitor's sections move GBW
as 1/C and, across the ±8 % of capacitance they span, phase margin by 0.24°
to 0.28° per 1 % at the binding corner (0.21° to 0.27° at the other two
points), bracketing the 0.21° PR #445 read across 25.0–25.7 µm.

**Slew at the binding corner fails at `cap_wcs`.** The nine slew legs on the
extraction all abort (§5), so the same nine sections were run on the
schematic netlist, where the bench runs:

| schematic, `mos_ss / 1.08 V / −40 °C` | `cap_bcs` | `cap_typ` | `cap_wcs` |
|---|---|---|---|
| `res_bcs` | 8.5836 / 8.5437 pass | 7.7630 / 7.7400 pass | **7.0856 / 7.0739 fail** |
| `res_typ` | 8.5831 / 8.5438 pass | 7.7626 / 7.7401 pass | **7.0852 / 7.0739 fail** |
| `res_wcs` | 8.5826 / 8.5439 pass | 7.7621 / 7.7401 pass | **7.0848 / 7.0740 fail** |

Rising / falling in V/µs; the nine jobs are in
`controls/ctl_sch_ss_<res>_<cap>_slew.slew.json`. The resistor section changes slew by
0.01 %; the capacitor section changes it by −8.6 % at `cap_wcs` and +10.4 %
at `cap_bcs`. On the standing grid, which holds the capacitor at `cap_typ`,
the schematic netlist passes all 45 corners (grid `klt-sim-a5259320ae50`:
worst rising 7.7626, worst falling 7.7400, both at `mos_ss / 1.08 V /
−40 °C`; zero diagnostics). This is **not a regression from the resistor**:
slew follows 1/C, so the retained 25.7 µm capacitor would read about 3 %
lower at the same section. It is the ratified slew bound's exposure once the
capacitor is allowed its own corner, and DR-0012 says that question is
asked, not assumed.

## 7. Disposition

**Phase margin (the finding #430 was filed for).** Closed on the candidate's
evidence: 66.4616° at the binding corner, 63.4876° over the nine passive
sections, 45/45 on the grid.

**#312.** The reference for #312's klt 0.9.0 regeneration is still the 25.7
µm layout at `36596fc`. The candidate that meets the bound is
`4f0af8d` on `candidate/issue-430-rz`; three things stand between it and
that role:

1. its netlist change retires every committed schematic-leg record. The
   T1 item-8 report refuses to re-mint against it (`generate.py --mint`:
   "simulated netlist … is not the committed design netlist", 18 rows in
   error), so the design has to land in the same change as #312's
   coordinated evidence refresh, not before it;
2. the extracted-leg slew row cannot be graded until the solver finding of
   §5 is resolved — the schematic leg is not affected;
3. the slew bound's status under DR-0012 at `cap_wcs` (§6) is a decision for
   the ADR's owners.

**#332 / #342.** Carry into the new topology's compensation sizing:

- a drawn 2 kΩ `rppd` in series with the Miller capacitor lifts fast/hot
  phase margin 6.6480° above the bare-capacitor baseline at 25.3 µm, at
  3.43° per kΩ, for no gain, no supply current and under 0.4 % of GBW;
- with the resistor present, phase margin costs about 0.25° per 1 % of
  capacitance and slew follows 1/C: a 0.964 pF capacitor passes the
  standing grid with 2.4 % of falling-slew margin and fails `cap_wcs` by
  5.8 %;
- the PDK resistor's thermal node defeats the committed transient bench on
  an extracted netlist. A replacement topology that draws one will meet the
  same wall; size its compensation against the schematic leg until the
  solver path is fixed.

Results that need repeating on a changed topology: everything here. The
input-noise, offset, CMRR and PSRR benches need re-measuring once the
resistor lands; PR #445 §8 already carries that into the signoff handoff.

## 8. Records

79 fleet envelopes, each naming its job in `environment.remote.job_id`:

- `records/` — 44 on the committed benches: four single-corner AC legs
  (`cand_<corner>.ac.json`), the binding slew leg (`cand_ss_slew.slew.json`),
  three grids (`grid_ac.json`, `grid_op.json`, `grid_slew.json`), 27 passive
  AC legs and 9 passive slew legs;
- `controls/` — 35 that are not the committed bench: the ideal-resistor
  swap, the schematic netlist (single, grid and nine passive sections),
  `method=gear` (single, grid, nine passive sections), `sw_et=1` (nine) and
  the body on the hub (one), and the two model-alone probes;
- `candidate/` — the GDS, both netlists, the extraction envelope, the DRC,
  LVS, ERC and area reports of the candidate revision, and its patch.

`python3 ../rz_candidate.py bench candidate/opamp_core_pex.spice <dir>`
rebuilds the 44 requests of `records/`; `python3 ../rz_candidate.py control
candidate/opamp_core_pex.spice candidate/opamp_core.spice <dir>` rebuilds
the 35 of `controls/`; `python3 ../rz_candidate.py grade <dir>` prints the
worst case of every measurement in a directory of envelopes.

### Job index

| envelope | job | verdict |
|---|---|---|
| `records/cand_ff.ac.json` | `klt-sim-4dd456ca73cb` | pass, PM 66.4616° |
| `records/cand_fs.ac.json` | `klt-sim-3e18dca3f9cc` | pass, PM 68.5511° |
| `records/cand_sf.ac.json` | `klt-sim-4a65dffbfc53` | pass, PM 66.5688° |
| `records/cand_ss_slew.slew.json` | `klt-sim-d5b717b82ba5` | error, aborted |
| `records/cand_tt.ac.json` | `klt-sim-0c8ae9417918` | pass, PM 70.3645° |
| `records/grid_ac.json` | `klt-sim-6a7dc3460919` | 45 pass, 0 fail, 0 error |
| `records/grid_op.json` | `klt-sim-ebdc51dbffd3` | 45 pass, 0 fail, 0 error |
| `records/grid_slew.json` | `klt-sim-aa4d9ece076e` | 8 pass, 0 fail, 37 error |
| `records/pass_ff_res_bcs_cap_bcs.ac.json` | `klt-sim-c540813d0819` | pass, PM 63.4876° |
| `records/pass_ff_res_bcs_cap_typ.ac.json` | `klt-sim-b7a1681c6554` | pass, PM 65.7746° |
| `records/pass_ff_res_bcs_cap_wcs.ac.json` | `klt-sim-e0dcebace9ee` | pass, PM 67.6994° |
| `records/pass_ff_res_typ_cap_bcs.ac.json` | `klt-sim-b935d0ff7c86` | pass, PM 64.1492° |
| `records/pass_ff_res_typ_cap_typ.ac.json` | `klt-sim-2fbf74775312` | pass, PM 66.4616° |
| `records/pass_ff_res_typ_cap_wcs.ac.json` | `klt-sim-361ba16c1002` | pass, PM 68.4070° |
| `records/pass_ff_res_wcs_cap_bcs.ac.json` | `klt-sim-2560e14b1461` | pass, PM 64.8079° |
| `records/pass_ff_res_wcs_cap_typ.ac.json` | `klt-sim-ae43e1ee98aa` | pass, PM 67.1460° |
| `records/pass_ff_res_wcs_cap_wcs.ac.json` | `klt-sim-bb929081ffe9` | pass, PM 69.1118° |
| `records/pass_fs_res_bcs_cap_bcs.ac.json` | `klt-sim-6264c9786bde` | pass, PM 65.8545° |
| `records/pass_fs_res_bcs_cap_typ.ac.json` | `klt-sim-29ce129fef3a` | pass, PM 67.9495° |
| `records/pass_fs_res_bcs_cap_wcs.ac.json` | `klt-sim-2ccd4af24278` | pass, PM 69.7392° |
| `records/pass_fs_res_typ_cap_bcs.ac.json` | `klt-sim-36897dad78c3` | pass, PM 66.4358° |
| `records/pass_fs_res_typ_cap_typ.ac.json` | `klt-sim-e339775fad24` | pass, PM 68.5511° |
| `records/pass_fs_res_typ_cap_wcs.ac.json` | `klt-sim-6fcc9b285437` | pass, PM 70.3562° |
| `records/pass_fs_res_wcs_cap_bcs.ac.json` | `klt-sim-e7f06656d8ac` | pass, PM 67.0150° |
| `records/pass_fs_res_wcs_cap_typ.ac.json` | `klt-sim-a31e5d13c005` | pass, PM 69.1507° |
| `records/pass_fs_res_wcs_cap_wcs.ac.json` | `klt-sim-621ff988a36c` | pass, PM 70.9712° |
| `records/pass_ss_res_bcs_cap_bcs_slew.slew.json` | `klt-sim-ebddfe3dc7cf` | error, aborted |
| `records/pass_ss_res_bcs_cap_typ_slew.slew.json` | `klt-sim-014f6c656d3d` | error, aborted |
| `records/pass_ss_res_bcs_cap_wcs_slew.slew.json` | `klt-sim-7e19b6abc2dd` | error, aborted |
| `records/pass_ss_res_typ_cap_bcs_slew.slew.json` | `klt-sim-eaa102513477` | error, aborted |
| `records/pass_ss_res_typ_cap_typ_slew.slew.json` | `klt-sim-49536dd554ab` | error, aborted |
| `records/pass_ss_res_typ_cap_wcs_slew.slew.json` | `klt-sim-6f937648cc90` | error, aborted |
| `records/pass_ss_res_wcs_cap_bcs_slew.slew.json` | `klt-sim-4513d9bcfa63` | error, aborted |
| `records/pass_ss_res_wcs_cap_typ_slew.slew.json` | `klt-sim-903e18bcad38` | error, aborted |
| `records/pass_ss_res_wcs_cap_wcs_slew.slew.json` | `klt-sim-d9d24ec8e9c5` | error, aborted |
| `records/pass_tt27_res_bcs_cap_bcs.ac.json` | `klt-sim-7c895d1049d5` | pass, PM 66.1337° |
| `records/pass_tt27_res_bcs_cap_typ.ac.json` | `klt-sim-8fb9fdabcb8e` | pass, PM 68.3386° |
| `records/pass_tt27_res_bcs_cap_wcs.ac.json` | `klt-sim-73214e8a2bfb` | pass, PM 70.2117° |
| `records/pass_tt27_res_typ_cap_bcs.ac.json` | `klt-sim-6a5b466bcdb7` | pass, PM 66.8160° |
| `records/pass_tt27_res_typ_cap_typ.ac.json` | `klt-sim-66a38ea00392` | pass, PM 69.0459° |
| `records/pass_tt27_res_typ_cap_wcs.ac.json` | `klt-sim-bcea5643dedd` | pass, PM 70.9386° |
| `records/pass_tt27_res_wcs_cap_bcs.ac.json` | `klt-sim-bdfa33d5184a` | pass, PM 67.4954° |
| `records/pass_tt27_res_wcs_cap_typ.ac.json` | `klt-sim-d7192624f377` | pass, PM 69.7504° |
| `records/pass_tt27_res_wcs_cap_wcs.ac.json` | `klt-sim-d445b3900460` | pass, PM 71.6629° |
| `controls/ctl_bodyhub_ss_res_typ_cap_typ_slew.slew.json` | `klt-sim-2a4f50276d0c` | pass, 8.1003 / 7.6881 V/µs |
| `controls/ctl_gear_grid.slew.json` | `klt-sim-982291a18712` | 9 pass, 0 fail, 36 error |
| `controls/ctl_gear_ss_res_bcs_cap_bcs_slew.slew.json` | `klt-sim-dfc8e64f939f` | error, aborted |
| `controls/ctl_gear_ss_res_bcs_cap_typ_slew.slew.json` | `klt-sim-2a268279012a` | error, aborted |
| `controls/ctl_gear_ss_res_bcs_cap_wcs_slew.slew.json` | `klt-sim-3b254673eb49` | error, aborted |
| `controls/ctl_gear_ss_res_typ_cap_bcs_slew.slew.json` | `klt-sim-6b9ee041e4d6` | error, aborted |
| `controls/ctl_gear_ss_res_typ_cap_typ_slew.slew.json` | `klt-sim-fa39922d9dc8` | pass, 8.1003 / 7.6881 V/µs |
| `controls/ctl_gear_ss_res_typ_cap_wcs_slew.slew.json` | `klt-sim-53a123f6c059` | error, aborted |
| `controls/ctl_gear_ss_res_wcs_cap_bcs_slew.slew.json` | `klt-sim-8105f75037ab` | error, aborted |
| `controls/ctl_gear_ss_res_wcs_cap_typ_slew.slew.json` | `klt-sim-1ac0a1feb4a9` | error, aborted |
| `controls/ctl_gear_ss_res_wcs_cap_wcs_slew.slew.json` | `klt-sim-b32e76d5f798` | error, aborted |
| `controls/ctl_gear_ss_slew.slew.json` | `klt-sim-5a144c630274` | pass, 8.1003 / 7.6881 V/µs |
| `controls/ctl_ideal_ss_slew.slew.json` | `klt-sim-c6f7a52627da` | pass, 8.1009 / 7.6888 V/µs |
| `controls/ctl_sch_grid.slew.json` | `klt-sim-a5259320ae50` | 45 pass, 0 fail, 0 error |
| `controls/ctl_sch_ss_res_bcs_cap_bcs_slew.slew.json` | `klt-sim-2e69aa7c9d43` | pass, 8.5836 / 8.5437 V/µs |
| `controls/ctl_sch_ss_res_bcs_cap_typ_slew.slew.json` | `klt-sim-28db2c2297fe` | pass, 7.7630 / 7.7400 V/µs |
| `controls/ctl_sch_ss_res_bcs_cap_wcs_slew.slew.json` | `klt-sim-ab7e47f96b15` | fail, 7.0856 / 7.0739 V/µs |
| `controls/ctl_sch_ss_res_typ_cap_bcs_slew.slew.json` | `klt-sim-45e7ae6ab8e2` | pass, 8.5831 / 8.5438 V/µs |
| `controls/ctl_sch_ss_res_typ_cap_typ_slew.slew.json` | `klt-sim-6dce72fcf4a7` | pass, 7.7626 / 7.7401 V/µs |
| `controls/ctl_sch_ss_res_typ_cap_wcs_slew.slew.json` | `klt-sim-e01998b919ea` | fail, 7.0852 / 7.0739 V/µs |
| `controls/ctl_sch_ss_res_wcs_cap_bcs_slew.slew.json` | `klt-sim-52d817c69b40` | pass, 8.5826 / 8.5439 V/µs |
| `controls/ctl_sch_ss_res_wcs_cap_typ_slew.slew.json` | `klt-sim-cb87fab5edb4` | pass, 7.7621 / 7.7401 V/µs |
| `controls/ctl_sch_ss_res_wcs_cap_wcs_slew.slew.json` | `klt-sim-1277014d81ec` | fail, 7.0848 / 7.0740 V/µs |
| `controls/ctl_sch_ss_slew.slew.json` | `klt-sim-9544ea96c7b5` | pass, 7.7626 / 7.7401 V/µs |
| `controls/ctl_swet1_ss_res_bcs_cap_bcs_slew.slew.json` | `klt-sim-6b169d911df4` | error, aborted |
| `controls/ctl_swet1_ss_res_bcs_cap_typ_slew.slew.json` | `klt-sim-78d97b28e05b` | error, aborted |
| `controls/ctl_swet1_ss_res_bcs_cap_wcs_slew.slew.json` | `klt-sim-f8de7fadbe3c` | error, aborted |
| `controls/ctl_swet1_ss_res_typ_cap_bcs_slew.slew.json` | `klt-sim-e2d099588aa1` | error, aborted |
| `controls/ctl_swet1_ss_res_typ_cap_typ_slew.slew.json` | `klt-sim-fe709b78c1ba` | error, aborted |
| `controls/ctl_swet1_ss_res_typ_cap_wcs_slew.slew.json` | `klt-sim-e417c3e1fd81` | error, aborted |
| `controls/ctl_swet1_ss_res_wcs_cap_bcs_slew.slew.json` | `klt-sim-110180c6f5a8` | pass, 8.9702 / 8.4816 V/µs |
| `controls/ctl_swet1_ss_res_wcs_cap_typ_slew.slew.json` | `klt-sim-a370149a86fe` | error, aborted |
| `controls/ctl_swet1_ss_res_wcs_cap_wcs_slew.slew.json` | `klt-sim-61072793d500` | error, aborted |
| `controls/probe_r_default.json` | `klt-sim-4a71009d4b08` | pass, vout_final_v 1.45918e-18, t_10_90_s 8.6974e-09 |
| `controls/probe_r_gear.json` | `klt-sim-2eb67c7670fa` | pass, vout_final_v 1.1234e-55, t_10_90_s 8.69689e-09 |

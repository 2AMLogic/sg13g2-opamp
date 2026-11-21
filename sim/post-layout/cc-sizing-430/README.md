# Issue #430 — Miller-capacitor sizing trial on DR-0001

**The trial rejected the 26.0 µm capacitor.** The re-extracted candidate
meets the fast/hot phase-margin bound (60.2318°) and misses the slow/cold
falling-slew bound (7.3067 V/µs against 7.51 V/µs). The screening models
predict disjoint capacitor-size windows (§6). #430 tracks the open phase-margin
finding for #332/#342. The 25.7 µm layout remains the reference for #312,
which stays blocked on #430 (§8).

All legs below run the committed open-loop AC / slew benches through the
pinned `klt_measure.py` generator and runner (`klayout-tools==0.9.0`,
`klayout==0.30.12`, IHP-Open-PDK `v0.3.0`, batch fleet, `capacity_wait_s=600`
on every request), one corner per request unless stated.

## 1. Inputs and reproduction pins

| Input | Value |
|---|---|
| Opamp source | `36596fcda50e5998a5088c56c7c9032a15a0b61b` (`feature/issue-312`, the #312 pinned source). Use the generator pinned below. Its SHA-256 at `main` revision `1ae310e` was `fbcccfd35f538ee98f037785e35a023b74509b1d808a90eb89d95174e8921e1f`. |
| Baseline GDS (25.7 µm cap) | `ab2d926e1974e4e04f0c0363af5139b64034f544e4fdc192df3dd7a79830aa05` |
| Baseline 0.9.0 extraction | `80cd19a17ee5d7e008efb662e322147e556598993f0d73c9ca16ba532019f1ea` (reproduced this run, byte-exact) |
| Candidate GDS 25.8 µm | `5812666924b88a436cef1db3624b5b0c3f5fc37f4dfd749f89cf0d7214120a1c` |
| Candidate GDS 26.0 µm | `aeed70cb2890df25a7b5a12c4956f0518279943cb309b7d4257f44a35f83fb2a` |
| Candidate extraction 25.8 µm | `38c262910838ee1e40b04d21b8ef4b5e4fda622b2e47c28918b7e38d6ac668f5` |
| Candidate extraction 26.0 µm | `331a675fdb3ce42c56c059ddd09414b6f26ce4233ecc1ee8c8327391efc8edcd` |
| Generator (`klt_measure.py`) | `36596fc` blob, SHA-256 `d4ea4008b5dfec24eab6e7996781df4b2c924f217eac19d888f84844b6b6eda0` |

Screening DUT ("leg B" of `attribution-312.md`): the pinned 0.9.0 extraction
minus every parasitic `R`/`C` card with `<net>__tN` terminal nodes collapsed
onto `<net>` (31 drawn MOS units + the `cap_cmim` card), with the
`X$32 … cap_cmim l=…U w=…U` side rewritten per candidate. The 25.7 µm leg-B
DUT reproduces the pinned leg-B phase at FF to all 12 printed digits
(`-2.088332597777` rad, job `klt-sim-f9421dd9cc13` = pinned
`klt-sim-52d304323333`), so the transform is behaviorally identical to PR
#431's. The slew legs adapt `sim/slew-rate/klt/tb_slew.body.spice` to the
`.SUBCKT` DUT exactly the way `klt_measure.py` adapts the AC/OP bench (include
+ `Xdut`, pins matched by name), dropping the six d1/d2/tail-internal
measurements (`vd1_dc_v`, `vd2_dc_v`, `vtail_dc_v`, `op_vd1_rail_frac`,
`op_vd2_rail_frac`, `op_vtail_rail_frac`) and the `Bfd1/Bfd2/Bftail`
B-sources that feed them; both edge slew measurements, the linearity,
pre-edge, drive-integrity and vout sanity checks are unchanged.

For a square `cap_cmim` of side `s` in µm, the model in `cap_cmim.sym`
gives `C(s) = 1.5s² + 0.16s` in fF, including the perimeter term.

| side (µm) | C (fF) | Δ vs 25.7 |
|---|---|---|
| 25.7 | 994.85 | — |
| 25.8 | 1002.59 | +0.78% |
| 26.0 | 1018.16 | +2.35% |
| 27.0 | 1097.82 | +10.35% |

## 2. Screening on the drawn-device DUT (batch fleet, one corner per job)

PM corner `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` (the binding corner);
GBW also read at `mos_fs / 1.08 V / 125 °C` (the ratified GBW binding
corner); slew at `mos_ss / 1.08 V / −40 °C` (the ratified slew binding
corner, worse edge = falling at every size here).

| side | FF PM (°) | FF GBW (MHz) | FS/125 °C/1.08 V GBW (MHz) | slew rise (V/µs) | slew fall (V/µs) | jobs |
|---|---|---|---|---|---|---|
| 25.7 | 60.3474 | 10.945 | 9.506 | 7.8776 | **7.4786 fail** | FF `klt-sim-f9421dd9cc13`, FS `klt-sim-be43509505bf`, slew `klt-sim-d220eeb786af` |
| 26.0 | 60.7557 | 10.741 | 9.321 | 7.7013 | **7.3167 fail** | FF `klt-sim-0b3d77524b83`, FS `klt-sim-8634a742fa3d`, slew `klt-sim-f3803da9a921` |
| 27.0 | 62.0939 | 10.072 | 8.734 | **7.1541 fail** | **6.8123 fail** | FF `klt-sim-9efb83456a97`, FS `klt-sim-c9c279426dc7`, slew `klt-sim-9580a67de411` |

(Correction during finalisation: the 25.7 µm FS leg's original submission
`klt-sim-4fb9c39c1531` was never launched by the fleet (no `status.json`
after 26 min of attach); its planned cell in an earlier draft of this table
quoted a number no job had produced. The leg was re-submitted as
`klt-sim-be43509505bf` and the measured value — 9.5057 MHz — is what the
table now carries. Every other cell above is byte-backed by its record
envelope under `records/`.)

Readings:

- Drawn-DUT FF phase margin rises by about **0.176° per 1% increase in Cc**
  over 25.7–27.0 µm (approximately 17.65° per unit of ln C).
- Both slew edges decrease as Cc grows. The baseline inverse-C estimate for
  falling slew is `7.4786 × 994.85 / C` V/µs, with C in fF. At 26.0 µm it
  predicts 7.3074 V/µs against 7.3167 measured. At 27.0 µm it predicts
  6.7771 V/µs against 6.8123 measured, 0.52% below the measurement.
- **The falling slew edge already misses the ratified 7.51 V/µs bound at the
  baseline 25.7 µm size on the drawn DUT** — a *pre-existing* miss
  (representation: the schematic-leg record behind the 7.51 bound reads
  7.51441 V/µs falling at this corner; the drawn-device DUT reads 7.4786,
  −0.47%). This is a #237-family representation finding recorded here, not a
  sizing regression.
- FS / 1.08 V / 125 °C GBW falls from 9.5057 MHz at 25.7 µm to
  8.734156 MHz at 27.0 µm, still above the 4.74 MHz bound.
- DC gain is untouched by the cap (45.797 dB at FF at every size).

## 3. Confirmation legs on real re-extractions (FF / 1.32 V / 125 °C)

Candidate GDS regenerated from the `36596fc` tree with only
`CAP_W_UM`/`CAP_L_UM` + the netlist `XCc` line changed (26.0 µm) or 25.8 µm,
extracted with the pinned `klt pex --extract-only` recipe (§1 hashes), then
measured through the same one-corner request form:

| leg | phase at UGF (rad) | signed margin (rad) | PM (°) | verdict vs 60° | job |
|---|---|---|---|---|---|
| baseline 0.9.0 extraction (PR #431) | −2.097648803209 | −0.003254 | 59.8136 | fail | `klt-sim-3e33c106fc7d` |
| **25.8 µm re-extraction (largest side tested DRC-clean)** | −2.095208623385 | −0.000814 | **59.9534** | **fail by 0.047°** | `klt-sim-e7009efe0455` |
| **26.0 µm re-extraction** | −2.090349614598 | +0.00404549 | **60.2318** | **pass by 0.232°** | `klt-sim-09ad05540075` |

The parasitic penalty (leg-B → extraction) at the changed sizes is −0.524°
(26.0 µm) vs −0.534° at 25.7 µm — the penalty is size-stable, so the
screening fit transfers to extractions. PM = `180 + degrees(phase_at_ugf_rad)`,
margin = phase − (−2.0943951023931953). The baseline phase gives 59.8136°,
correcting the 59.8149° originally quoted in #430.

## 4. Layout verdicts for the geometry change (pinned flow, local)

| side | DRC (`klt drc --deck sg13g2`) | LVS (committed compare) |
|---|---|---|
| 25.7 (control) | clean | match (cap geometry warning only, as committed) |
| 25.8 | clean | **mismatch**: `device.property` on the `cap_cmim` C parameter + 2 `topology` net-name conflicts (`$6`/`D2`, `out`/`OUT`) |
| 25.9 | 1 × `metal5.space.1` (miller_cap) | not run |
| 26.0 | 1 × `metal5.space.1` (miller_cap → d2 riser Metal5 pad) | match (cap geometry warning only) |

The checks bracket the `metal5.space.1` transition between 25.8 µm
(clean) and 25.9 µm (violation). The exact side at the spacing limit is
undetermined. At 26.0 µm the enlarged Metal5 bottom plate comes within
0.07 µm of the `d2` via stack's Metal5 landing pad. Keeping that candidate
would require a routing change, such as moving `fp.TRACK_UM["d2_c4"]`.
The same LVS flow reports a mismatch at 25.8 µm and matches at 25.7 and
26.0 µm. The cause of the 25.8 µm mismatch remains open.

## 5. Full 45-point grid on the 26.0 µm re-extraction

The rejected-candidate grid still runs for the record (the issue asks for the
full grid on the screened candidate; 26.0 µm is the PM-passing leg of §3).
Three batch jobs — AC grid `klt-sim-4de34fc6d942`, OP grid
`klt-sim-b9572a8a298e` (first submit `klt-sim-a585b200e6b0` was never
launched by the fleet and its wait was SIGTERM'd; the identical request
re-submitted and finished in 10 s), slew grid `klt-sim-1d695edc4427`.
Envelopes: `records/grid26.0_ac.json`, `records/grid26.0_op.json`,
`records/grid26.0_slew.json`.

| metric | worst measured value | corner | ratified limit | verdict |
|---|---|---|---|---|
| PM (from `phase_at_ugf_rad` = −2.090349614598 rad) | 60.2318° | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≥ 60° | **pass** (+0.00404549 rad) |
| DC gain | 42.6763 dB | `mos_fs / 1.08 V / Vinp 0.54 V / 125 °C` | ≥ 37.8 dB | pass (+4.88 dB) |
| GBW | 8.0019 MHz | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 4.74 MHz | pass (+69%) |
| Iq (`ivdd_total_a`) | 84.8472 µA | `mos_ff / 1.32 V / Vinp 0.66 V / 125 °C` | ≤ 119.7 µA | pass |
| slew, rising edge | 7.6842 V/µs | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 7.51 V/µs | 44 pass, 1 error |
| slew, falling edge | **7.3067 V/µs** | `mos_ss / 1.08 V / Vinp 0.54 V / −40 °C` | ≥ 7.51 V/µs | 43 pass, **1 fail**, 1 error |

Grid statuses: AC 45/45 pass, zero diagnostics. OP 45/45 pass, zero
diagnostics. Slew 43 pass / 1 fail / 1 error.

- At SS / 1.08 V / −40 °C, the 26.0 µm falling edge measured
  7.3167 V/µs on the drawn DUT and 7.3067 V/µs on the extraction. The other
  43 measured falling edges passed. The next lowest was 7.5595 V/µs at
  `mos_sf / 1.08 V / −40 °C`.
- At `mos_sf / 1.08 V / Vinp 0.54 V / 27 °C`, ngspice reported
  `timestep_too_small` at 5.33 ps on node `xdut.ibias__t0`. Both slew
  measurements are null and carry the error status.
- The TT/1.08 V/27 °C corner — inconclusive in the #429-era diagnosis —
  **passes cleanly in all three grids on this extraction** (no diagnostics);
  the inconclusive result does not persist here.
- Worst non-binding corners for reference: 2nd-worst PM 60.5122°
  (`mos_sf / 1.32 V / 125 °C`), max Iq 84.85 µA is 71% of the limit.

The 26.0 µm candidate passes PM, gain, GBW and Iq across all 45 corners.
The measured falling-edge failure at SS / 1.08 V / −40 °C rejects the
candidate. Both edges remain ungraded at SF / 1.08 V / 27 °C.

## 6. Estimated size limits and measured checks

Ratified bounds: PM ≥ 60° (`mos_ff/1.32/125 °C`), slew ≥ 7.51 V/µs
(worse edge, worst corner `mos_ss/−40 °C/1.08 V`), GBW ≥ 4.74 MHz, DC gain
≥ 37.8 dB, Iq ≤ 119.7 µA (`spec/target-spec.md` §2 [DR-2]).

- The inverse-C falling-slew model crosses 7.51 V/µs at
  `C = 994.85 × 7.4786 / 7.51` ≈ **990.69 fF**. Inverting the square-cap
  formula in §1 gives **s ≈ 25.646 µm**. Smaller sides favor slew.
- For extracted PM, starting from 59.8136° at 25.7 µm and using the drawn
  sensitivity in §2 with the approximately constant parasitic penalty in §3,
  the required increase is about 0.19°. The estimated crossing is
  `C = 994.85 × exp(0.19 / 17.65)` ≈ **1005.6 fF**, or **s ≈ 25.839 µm**.
  Larger sides favor PM. The measured extractions bracket 60° at
  25.8 µm (59.9534°) and 26.0 µm (60.2318°).
- The estimated crossings are about 0.19 µm apart. At 25.6 µm the models
  predict 7.537 V/µs falling slew (margin +0.027 V/µs) and about 59.68°
  extracted PM. DRC passed at 25.8 µm and failed at 25.9 µm, so the
  checks leave DRC at the estimated PM crossing undetermined.

Gain and GBW passed at the screened AC points. Only the 26.0 µm extraction
has an OP grid in these records. All 45 Iq values meet the 119.7 µA limit.

## 7. Disposition for #332 / #342

Use the DR-0001 measurements and local sizing estimates below as inputs to
the compensation analysis on the new topology.

- representation (lumped `ng=1` → drawn fingers): **−1.64°** PM at FF/125 °C
  (PR #431); drawn slew falling edge **−0.47%** vs the schematic record at
  SS/−40 °C/1.08 V (this run);
- layout parasitics: **−0.53°** PM (size-stable across 995→1018 fF);
- Drawn-DUT PM sensitivity is approximately **+0.176° per +1% Cc**. The
  inverse-C falling-slew model starts at 7.4786 V/µs (SS/−40 °C/1.08 V,
  994.85 fF) and underestimates the 27.0 µm measurement by 0.52%.
- slew binds before GBW: GBW margin at its binding corner is ≈ 2× on the
  drawn DUT, slew margin is −0.4% at baseline — a future PM-vs-slew trade
  should buy margin with edge *current* (bias/topology, #332/#342 scope) or a
  nulling resistor (§ design/opamp_sizing.md "Rz", candidate ≈ 1/gm6), not
  with Cc alone;
- DRC passed at 25.8 µm. The 25.9 and 26.0 µm plates violate
  `metal5.space.1` at the `d2` riser. Check this spacing at the selected
  side if the new layout uses the same track.

Results needing re-measurement on a changed topology: everything in §2–§5
(the representation and parasitic terms are this layout's), plus the FF/TT
schematic references of PR #431.

## 8. Handoff to #312

The reference for #312's klt 0.9.0 regeneration remains the **25.7 µm
geometry** at `36596fcda50e5998a5088c56c7c9032a15a0b61b` (GDS
`ab2d926e…`, extraction `80cd19a1…`, full hashes in §1). Its measured
FF / 1.32 V / 125 °C phase margin is 59.8136°. **#312 remains blocked by
#430** pending a disposition of that miss. #332/#342 carry the trade into
the topology work (§7). The 26.0 µm trial failed falling slew and DRC.

## 9. Records

The 14 JSON envelopes under `records/` each identify their fleet job. They cover
screening AC legs (`screen_*ac*.json`, including the re-submitted FS 25.7
leg `screen_fs_cc25.7.ac.json`), screening slew legs (`screen_*slew*.json`),
confirmation legs (`confirm_*.json`), 26.0 µm grid AC/OP (`grid26.0_ac.json`,
`grid26.0_op.json`) and slew grid (`grid26.0_slew.json`). This trial changes
no design, layout, spec or bench file — `git diff` on this PR is
documentation and records only.

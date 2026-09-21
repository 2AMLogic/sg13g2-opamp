# Target specification — sg13g2-opamp

- **Status**: **RATIFIED (partial)** — via the two-key (EE + market)
  mechanism, on the PR that carries
  [`decision-records/0002-target-spec-ratification.md`](decision-records/0002-target-spec-ratification.md):
  that record recommends one bound per measured row, and the ratification act
  is that PR's two `RATIFY-KEY` reviews (per
  [2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372) — neither
  key held by the PR's author); the merge commit is the ratification record.
  The operating conditions in §1 and the measured rows in §2 below are
  ratified (`[DR-2]` tags; and
  [`0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md),
  `proposed` until now, is carried into force with them) — originally
  including the CMRR and offset rows with their measured systematic halves
  only. The CMRR row's mismatch-inclusive 3σ bound is now **also**
  ratified ([`0004-cmrr-mismatch-inclusive-ratification.md`](decision-records/0004-cmrr-mismatch-inclusive-ratification.md),
  `[DR-4]` — the same two-key mechanism on that record's own PR, superseding
  the row's `[DR-2]` systematic half, which stays in-row as context), while
  the offset row's mismatch-driven statistical half remains explicitly
  outstanding pending its own re-ratification pass (#17). The one
  residual `[TBD-#n]` row (Area) is **not** ratified — it keeps its tag
  and carries an explicit statement of why it cannot yet be ratified.
- **Date**: 2026-09-06
- **Assembled by**: Loom Builder agent, issue #2 (bootstrap/scaffolding pass)
- **Scope**: 1.2 V core (LV) variant only, matching this repo's own
  `README.md` draft framing ("supply/power at 1.2 V"). The 3.3 V I/O (HV)
  device flavor is named as a possible future stretch row but is
  **explicitly not opened here** — per `CLAUDE.md`'s decision-record
  discipline, opening it requires its own `spec/` decision record, never a
  silent addition alongside this table.

This file is the block's single consolidated target-spec table, following
the row set `CLAUDE.md` already names: *"DC gain, GBW into a stated CL,
phase margin, slew, input-referred noise, offset (with statistical basis),
CMRR/PSRR, output swing — at PVT corners, with the load stated on every
row."* Before this file existed, that row set lived only as prose in
`CLAUDE.md` and `README.md`. Nothing in this pass performs circuit design,
schematic capture, or simulation — at that bootstrap commit every numeric
target below was either an engineering placeholder proposal `[P]` or
explicitly `[TBD-#n]` pending SG13G2 device data (`design/`, `sim/`, `layout/`, and
`measurements/` then held only placeholder `README.md` files, verified
against `main` @ `f8d5be9`, 2026-09-06). Since then the classic benches
(issues #9, #11, #12, #13, #15) measured the now-measured rows below across
the full PVT grid, and
[`decision-records/0002-target-spec-ratification.md`](decision-records/0002-target-spec-ratification.md)
ratified one bound per measured row (`[DR-2]` tags) via the two-key
mechanism. The only row still carrying a `[TBD-#n]` tag is the one whose
evidence does not exist yet (Area — no layout) — see the residual notes
in §2 and 0002's residual register. (The CMRR/PSRR bench landed on `main`
mid-pass, PR #25, and its rows are ratified with the caveats stated
in-row.)

## How to read this table

**Value tags** — every non-definitional value carries one, following
[`gf180-temp-por/spec/target-spec.md`](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/target-spec.md)'s
convention (also used by the twin's
[`gf180-opamp/spec/target-spec.md`](https://github.com/2AMLogic/gf180-opamp/blob/main/spec/target-spec.md)),
so a future reviewer can tell a carried decision from a new proposal at a
glance:

| Tag | Meaning |
|---|---|
| **[DR-n]** | Carried unchanged from decision record `n`. `[DR-1]` ([`decision-records/0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md)) is carried by the corner-grid and CL rows in §1; `[DR-2]` ([`decision-records/0002-target-spec-ratification.md`](decision-records/0002-target-spec-ratification.md)) is carried by every ratified operating-condition row in §1 and performance row in §2 — its one recommended bound per row is the number this table binds — and `[DR-4]` ([`decision-records/0004-cmrr-mismatch-inclusive-ratification.md`](decision-records/0004-cmrr-mismatch-inclusive-ratification.md)) by the CMRR row's mismatch-inclusive 3σ bound, which supersedes that row's `[DR-2]` systematic half (the superseded floor keeps its `[DR-2]` tag in-row as context). |
| **[P]** | **Proposed by this bootstrap pass** — an engineering placeholder with no measured SG13G2 device data behind it yet (e.g. carried from the block's own README/CLAUDE.md framing, or a structural convention borrowed from a sibling repo's ratified spec). Needs an explicit ratification decision before it binds. After the DR-0004 re-ratification, the only `[P]` values in this table are §1's deliberately un-opened HV stretch row and the offset row's mismatch-statistical cells (issue #17's Monte Carlo campaign now measures those; they stay `[P]` until the 0002 residual-(b) re-ratification pass binds them — see 0002's residual register). The CMRR row's formerly-`[P]` mismatch-inclusive cells became `[DR-4]` in that pass. |
| **[TBD-#n]** | Deliberately unset — no SG13G2 device data exists yet to propose even a placeholder number. `#n` is the row's index in §2 below, so a future characterization pass can address each unset row individually. Tracked collectively under the gap-to-T1 tracker (linked from `README.md` and `porting-plan.md`) — item 5, "Full PVT corner simulation vs a ratified spec" — rather than one issue per row; no per-row characterization issue has been filed yet. |

**Status** column values in use: `Ratified [DR-2]` (a committed `sim/`
record backs the number and the two-key ratification recorded in
[`0002-target-spec-ratification.md`](decision-records/0002-target-spec-ratification.md)
bound the row — one bound per row); `Ratified, mismatch-inclusive [DR-4]`
(the CMRR row: the two-key re-ratification recorded in
[`0004-cmrr-mismatch-inclusive-ratification.md`](decision-records/0004-cmrr-mismatch-inclusive-ratification.md)
— DR-0002 residual (c), discharged — bound the row's mismatch-inclusive
3σ figure, measured by `sim/cmrr-mismatch/` (issue #26, record
`20260921-172304-65f5fb4`), superseding the row's `[DR-2]` systematic-only
floor, which stays in-row as context); `Ratified, systematic only [DR-2] —
mismatch-driven 3σ measured [P] (not yet re-ratified)` (the offset row:
its mismatch MC evidence now exists — `sim/input-offset/run_offset_mc.sh`,
issue #17, record `mc-20260921-174056-0a509fb` — and the 0002 residual-(b)
re-ratification pass that would supersede the systematic-only bound has
not run); `Ratified, systematic only [DR-2] — statistical basis
outstanding` (kept as vocabulary for any future row whose statistical
basis is committed but not yet measured — no row currently uses it, both
of its former users having moved to the mismatch-measured value above);
and `not ratifiable yet —
<reason>` (a `[TBD-#n]` residual row whose evidence does not exist yet:
Area, pending a layout).
The pre-ratification
draft vocabulary (`not started`, `Measured (not yet ratified)`, `Measured,
systematic only (not yet ratified; statistical basis outstanding)`)
described the same rows before the DR-0002 pass, and
`Ratified, systematic only [DR-2] — mismatch-inclusive 3σ measured [P]
(not yet re-ratified)` described the CMRR row between that pass and the
DR-0004 supersession.

**Binding corner** — the corner at which a row's hard edge binds. It was
reasoned as a **prediction** from the topology's *generic* behavior (a
two-stage Miller-compensated op-amp) at the 2026-09-06 bootstrap pass, when
no schematic existed to simulate; per the rule stated then, each measured
row's `sim/` record has since superseded the prediction, and the row cells
below record the measured binding corner — and where it corrected the
prediction — alongside it. CLAUDE.md's "no claim without a testbench"
applies to any future *pass/fail* verdict on these rows.

## 1. Global operating conditions

| Parameter | Value | Notes |
|---|---|---|
| Supply voltage, VDD | **1.2 V ±10% → 1.08–1.32 V** [DR-2] | Primary variant, using SG13G2's LV core devices (`sg13_lv_nmos`/`sg13_lv_pmos`, PSP 103.6 model, `V_GS ≤ 1.65 V @125°C`). Matches this repo's own `README.md` draft framing ("supply/power at 1.2 V") — not yet cross-checked against a ratified sibling spec, since neither `sg13g2-bandgap` nor `sg13g2-ldo` targets a 1.2 V-primary rail (both are 3.3 V-primary, per `sg13g2-bandgap/spec/porting-plan.md` DR-0002). This repo's 1.2 V choice is this block's own, carried from its own README, not inherited from a sibling. |
| Supply voltage, VDD (stretch) | **3.3 V I/O (HV flavor) — not opened** [P] | SG13G2's `sg13_hv_nmos`/`sg13_hv_pmos` (3.3 V I/O, `V_GS ≤ 3.3 V Maximum`) are named here only so a future decision record has a place to point at. Per `CLAUDE.md`, opening this row requires its own decision record; it is not in scope now. Never mixed with 1.2 V-flavor (LV) devices in one variant. |
| Operating temperature | **−40…+125 °C** [DR-2] | Matches the fleet-wide convention (`sg13g2-bandgap`, `gf180-bandgap`, `gf180-temp-por`) for a commercial-grade PDK part. Originally proposed by analogy, pre-measurement; since the benches, every ratified §2 row below is measured across exactly this temperature range (ratified on that evidence by [DR-0002](decision-records/0002-target-spec-ratification.md)). |
| Corner grid | **`cornerMOSlv.lib`: `tt`/`ff`/`ss`/`sf`/`fs` [DR-1]** | Ratified by [decision record 0001](decision-records/0001-topology-and-cl.md): the standard five-corner `mos_tt`/`mos_ff`/`mos_ss`/`mos_sf`/`mos_fs` grid on `cornerMOSlv.lib`, confirmed against the real PDK install by issue #5's gm/ID characterization sweep (`sim/gm-id-characterization/`) and now carried into this table. Temperature axis (`−40…+125 °C` row above) is crossed with this grid at testbench time, not folded into the corner-file grid itself. |
| Load capacitance, CL | **2 pF [DR-1]** | Ratified by [decision record 0001](decision-records/0001-topology-and-cl.md): a representative moderate load for this standalone canary op-amp's own bench (no downstream consumer or twin-repo precedent to match), chosen so GBW/slew targets derived from it stay meaningful for this block's likely bias-current budget. See the decision record's `## Alternatives considered` for rejected larger/consumer-matched CL choices. |

## 2. Performance targets

| Parameter | Target | Stretch | Statistical basis | Binding corner (predicted) | Status |
|---|---|---|---|---|---|
| Open-loop DC gain | **Ratified bound ≥ 37.8 dB worst-case [DR-2]** — measured envelope 37.8 dB worst / 45.2 dB best, `sim/open-loop-ac/records/20260910-221601-22feaba.csv`, citing `design/opamp_sizing.md`'s sizing pass | — | — (deterministic corner-worst-case candidate) | Predicted: SS / −40 °C (lowest gm, highest output impedance loss). **Measured worst case is instead FS / 125 °C / 1.08 V** — gain falls monotonically with rising temperature across this grid, the opposite of the pre-schematic guess; see `sim/open-loop-ac/README.md` "Measured vs. predicted binding corners" | Ratified [DR-2] |
| GBW (into stated CL = 2 pF [DR-1], above) | **Ratified bound ≥ 4.74 MHz worst-case [DR-2]** — measured envelope 4.74 MHz worst / 6.62 MHz best, `sim/open-loop-ac/records/20260910-221601-22feaba.csv` | — | — | Predicted: SS / −40 °C / low VDD (slowest devices). **Measured worst case is instead FS / 125 °C / 1.08 V**, same correction as the DC-gain row above | Ratified [DR-2] |
| Phase margin (at GBW, same CL) | **Ratified bound ≥ 60° [DR-2]** — measured worst case 76.4° at FF / 125 °C / 1.32 V, clearing this bound with comfortable margin (`sim/open-loop-ac/records/20260910-221601-22feaba.csv`) | ≥ 45° at the FF/hot corner if 60° is unreachable there | — (deterministic corner-worst-case) | FF / 125 °C (fastest devices, most peaking risk) — **confirmed** by measurement, the one row where the pre-schematic prediction and the measured worst corner agree | Ratified [DR-2] |
| Slew rate (into stated CL = 2 pF [DR-1], above) | **Ratified bound ≥ 7.51 V/µs worst-case [DR-2]** — measured envelope 7.51 V/µs worst / 9.91 V/µs best, `sim/slew-rate/records/20260918-210216-90844d2.csv`, worse of the rising/falling edge at each point (rising alone: 7.54–10.27 V/µs), at a fixed input common mode `Vcm = VDD/2` with the `±0.3 V`-per-input antiphase drive that record states | — | — (deterministic corner-worst-case) | Predicted: SS / −40 °C / low VDD (lowest tail-current headroom). **Confirmed** by measurement — `mos_ss_-40C_1.08V` is the measured worst point on both edges; slew rate rises monotonically with temperature and supply in this design, so the coldest/slowest/lowest-rail corner binds on all three axes at once. See `sim/slew-rate/README.md` "Measured vs. predicted binding corner" | Ratified [DR-2] |
| Input-referred noise (band: **100 Hz – 1 MHz integrated**, plus spot densities; same stated CL = 2 pF [DR-1]) | **Ratified bound ≤ 108.9 µVrms worst-case [DR-2]**, integrated over 100 Hz – 1 MHz — measured envelope 108.9 µVrms worst / 87.3 µVrms nominal (`TT / 27 °C / 1.20 V`) / 73.4 µVrms best — measured `sim/input-noise/records/20260918-203850-90844d2.csv`. Spot densities, nominal / worst-case: **2.79 / 3.48 µV/√Hz @ 100 Hz**, **881 / 1100 nV/√Hz @ 1 kHz**, **35.4 / 44.3 nV/√Hz @ 1 MHz**. The **band is part of the number** and was chosen in this measurement's own pass (the row previously read `[TBD-6]`, "band not yet chosen"): it matches the `sky130-opamp` twin's proposed `100 Hz – 1 MHz` row for the same topology, and its bounds are defended against this PDK's own measured GBW and the measured `1/f`-dominated spectrum — see `sim/input-noise/README.md` "Choosing the band". The flicker-dominated character of this spectrum — the foundation of the row's own corner binding — was examined and **accepted as a committed-sizing property** by [0003-input-pair-flicker-noise.md](decision-records/0003-input-pair-flicker-noise.md) (issue #19's re-size decision: declined, the quantified trade and the re-open trigger in that record; the ratified bound here moves neither way). A µVrms figure quoted without both bounds is not a claim about this amplifier | — | — (deterministic corner-worst-case; no mismatch/MC noise deck run, and the ideal `ibias` source contributes no noise) | **Measured: FS / 125 °C / 1.08 V** — the same corner that binds DC gain and GBW above; temperature and supply dominate the process axis (all three worst points are `125 °C / 1.08 V`). The integrated figure is 91–94 % flicker-dominated at every corner, so the flicker-worst corner binds; the *thermal* floor binds elsewhere (28.1 nV/√Hz at SS / 125 °C / 1.08 V), which is why a higher or narrower band would bind at a different corner | Ratified [DR-2] |
| Input-referred offset | **Systematic (deterministic, corner-only): ratified bound +21.9 mV worst-case [DR-2]** — measured envelope +21.9 mV worst / +11.4 mV best, `sim/input-offset/records/20260918-203858-90844d2.csv`, two independent methods agreeing to ≤ 0.3 mV at every point. **Mismatch-driven random 3σ evidence now measured [P]** — σ(Vos) 8.81–9.13 mV at every sampled point (dominated by the minimum-sized input pair, 0.13 µm × 3.2 µm, against SG13G2's `delvto` area law), so the 3σ random term is 26.4–27.4 mV, worst 27.4 mV at `SS / 125 °C / 1.20 V`, `sim/input-offset/records/mc-20260921-174056-0a509fb.csv` (N = 300 draws per point, campaign seed `20260921`); the worst-case single-PVT total, \|systematic\| + 3σ, is **46.7 mV at `FS / 125 °C / 1.20 V`**, and the random term exceeds the ratified bound's own envelope at every sampled point | — | **3σ, mismatch MC N≥300 + process corners — discharged [P]** by `sim/input-offset/run_offset_mc.sh` (issue #17, record `mc-20260921-174056-0a509fb`): all five `cornerMOSlv.lib` families' `<corner>_mismatch` sections (SG13G2's own per-device `agauss()` mismatch deck, `sg13g2_moslv_mod_mismatch.lib`, layered on the deterministic process-corner parameters — combined with, not instead of, the corners, the two-bench split of issue #11's deterministic sweep keeping the systematic join and negative control) × `{-40, 27, 125} °C` at the fixed 1.20 V supply (the full supply axis already covered deterministically by the #11 record); N = 300 at every corner×temperature point; seed-deterministic (same seed → byte-identical re-run, verified in-campaign), zero-spread plain-section negative control at `TT / 27 °C / 1.20 V` reproducing #11's `vos_null_v` there to 1.17 µV, 4800/4800 draws passing per-draw sanity. Companion discipline to the CMRR row's #26 | Predicted: "likely SS/FF split-corner pairing on the input differential pair". **Partly confirmed, partly corrected by measurement**: the split corners are indeed the extremes (`FS` worst / `SF` best in 7 of 9 temperature-supply cells, bracketing `TT` in all 9) for the systematic term, but the prediction named no temperature or supply and those dominate — the systematic binding point is **FS / 125 °C / 1.08 V [DR-2]**, the same binding point as DC gain and GBW. **The mismatch rationale behind the original prediction is now tested and quantified [P]**: σ(Vos) runs near-flat across corners/temperatures (8.8→9.1 mV), tracking the input pair's `delvto` area law — see `sim/input-offset/README.md` "Monte Carlo mismatch campaign (issue #17)" | Ratified, systematic only [DR-2] — mismatch-driven 3σ measured [P] (`sim/input-offset/`, record `mc-20260921-174056-0a509fb`; not yet re-ratified — a future 0002 residual-(b) re-ratification pass cites it) |
| CMRR | **Ratified bound ≥ 26.68 dB worst-case — mismatch-inclusive CMRR, the +3σ-of-Acm figure [DR-4]** — envelope **26.68 dB worst / 37.57 dB best**, `sim/cmrr-mismatch/records/20260921-172304-65f5fb4.csv`: per grid point, CMRR of the +3σ part of the 300-draw common-mode-gain distribution (mean+3σ of the drawn Acm in the **linear** domain, mapped below the same joined `Av0` — the 3σ-domain choice [0004](decision-records/0004-cmrr-mismatch-inclusive-ratification.md)'s EE key rules on, because the dB-domain 3σ is meaningless at the near-cancellation corners; see `sim/cmrr-mismatch/README.md` "Choosing the 3σ domain"), using SG13G2's own per-corner mismatch decks — directly comparable to the systematic floor by construction, and below it at **all 45 points** (by 1.77 dB at `mos_ff_27C_1.32V` up to 25.48 dB at the systematic best point `mos_fs_-40C_1.08V`, whose structural near-cancellation does not survive mismatch), quantifying this row's registered "expected worse" premise. The definition (Av0 minus the +3σ point of the drawn-Acm distribution, linear domain, N=300 + process corners) is part of the ratified number per [DR-0004](decision-records/0004-cmrr-mismatch-inclusive-ratification.md) — a CMRR figure quoted without it is not a claim about this amplifier. **Superseded systematic (nominal-device) floor, kept as context [DR-2]: ≥ 30.75 dB worst-case** — measured envelope 30.75 dB worst / 62.83 dB best, `sim/cmrr-psrr/records/20260921-151815-707b34c.csv`, computed as the same grid point's open-loop gain `Av0` (`sim/open-loop-ac/`'s committed record, joined per point, not re-measured) divided by the common-mode gain this bench injects at both inputs in phase, over the full 45-point PVT grid into `CL = 2 pF` [DR-1]. Flat from DC (10 mHz shelf read, machine-verified plateau) to 1 kHz at every corner. Systematic (nominal-device) CMRR only — perfectly matched devices, so this is the structural floor (mirror-load first-stage asymmetry amplified by the second stage); random mismatch, typically the dominant real-part CMRR term, is not part of that figure (the offset row's systematic/statistical split, applied to CMRR) | — | **3σ of the drawn-Acm distribution, mismatch MC N=300 + process corners [DR-4]** — discharged by `sim/cmrr-mismatch/` (issue #26, record `20260921-172304-65f5fb4`) and ratified binding by [0004](decision-records/0004-cmrr-mismatch-inclusive-ratification.md): seed-deterministic per-point sample sequences (same seed → byte-identical re-run), a per-point zero-mismatch negative control asserted against the committed systematic record, and per-sample DC/plateau sanity (13,500 samples, 0 exclusions); N stays at the spec floor ≥300 (re-derived — the linear-σ sampling error is ≈4% at N=300, inside the 5% target). Companion discipline to the offset row's #17 | **Ratified (mismatch-inclusive) [DR-4]: SS / −40 °C / 1.08 V at 26.68 dB** — a different, colder corner than the superseded systematic binding point (whose own figure falls to 28.04 dB), with the grid's largest relative Acm spread (σ/µ ≈ 25.6 %) and the worst single draw of all 13,500 samples at 25.94 dB; the mismatch-inclusive envelope is 26.68–37.57 dB and is flat to 1 kHz at every point (the mismatch term is a DC-accurate offset-like error — see `sim/cmrr-mismatch/README.md` "Reading these numbers honestly"). **Superseded systematic binding point [DR-2]: FS / 125 °C / 1.08 V** — the same corner that binds DC gain, GBW, noise and systematic offset (best case 62.83 dB at FS / −40 °C / 1.08 V; see `sim/cmrr-psrr/README.md` "Measured vs. predicted binding corners") | Ratified, mismatch-inclusive [DR-4] (`sim/cmrr-mismatch/`, record `20260921-172304-65f5fb4`, cited by [0004](decision-records/0004-cmrr-mismatch-inclusive-ratification.md) — supersedes the row's systematic-only [DR-2] half, kept as context; cf. the offset row, whose own statistical re-ratification is still pending) |
| PSRR | **Ratified bound ≥ 1.87 dB worst-case (DC shelf; PSRR+) [DR-2]** — measured envelope 1.87 dB worst / 29.54 dB best (DC shelf), `sim/cmrr-psrr/records/20260921-151815-707b34c.csv`, computed as the same grid point's `Av0` divided by the VDD-to-output gain (PSRR+, `vss` being ground in this single-supply part), with the ideal external 10 µA `ibias` reference contributing no supply ripple (an on-die bias generator is out of this core's scope, per `design/opamp_sizing.md` "Bias scope"). **PSRR+ is strongly frequency-dependent** — the supply path has a genuine ~1.5 Hz zero, so rejection degrades ~4 dB from the DC shelf to the 100 Hz–10 kHz band (nominal 6.43 dB DC → 2.30 dB at 1 kHz; worst-in-band 1.30 dB at SF / −40 °C / 1.32 V); the quoted range is the DC shelf, and the per-point 10 mHz–1 GHz spectra are part of the record | — | — (deterministic corner-worst-case) | **Measured: FF / 125 °C / 1.32 V** (DC) — the only row so far binding at the fast/hot/high-rail corner (the direct output-PMOS supply path dominates), unlike every other row; in-band (1 kHz) worst is SF / −40 °C / 1.32 V. CMRR and PSRR do **not** bind at the same corner, as this row's own issue (#14) anticipated. See `sim/cmrr-psrr/README.md` "The 10 mHz sweep start and the ~1.5 Hz supply zero" | Ratified [DR-2] (DC shelf) |
| Input common-mode range (ICMR) | **0.6158–0.8690 V at the worst-span corner `mos_ss / 125 °C / 1.08 V`; span 0.2532 V worst / 0.6769 V best, lower bound worst 0.6401 V at `SS / −40 °C / 1.08 V`, upper bound worst 0.7954 V at `FS / 125 °C / 1.08 V` [P]** — measured `sim/input-cmr/records/20260921-174405-65f5fb4.csv`, the input stage's own saturation-limited bounds (lower: `v(tail) = Vdsat(M5)`, with the tail's saturation knee measured by a same-bias replica probe; upper: pair `Vds ≥ Vgs − Vth` with `Vth` per the gm/ID constant-current convention measured at the bound's true body bias — criterion-explicit, both mechanisms named per point: `m5_headroom` below, `pair_saturation` above, at all 45 points). **The measured envelope does not contain this design's own nominal `Vcm = VDD/2` bias point at the low rail**: 15 of 45 points (every 1.08 V corner except `ff` ×3 and `fs / 125 °C`, plus `ss` ×3 and `sf / −40 °C` at 1.20 V) sit *below* the measured lower bound at mid-rail, worst by 100 mV (`SS / −40 °C / 1.08 V`) — the tail-starvation sensitivity `sim/slew-rate/`'s dev-time study observed, quantified here; a usable 1.08 V design needs a higher-than-mid-rail input common mode, a re-biased tail, or explicit acceptance of a knee-region tail there. The closed-loop-buffer usable interval (intersection with `sim/output-swing/`'s measured reach) is a further-recorded column: worst 0.1612 V at `SS / 125 °C / 1.08 V`. These bounds pre-date ratification and are not part of [DR-2] | — | — (deterministic corner-worst-case; nominal matched devices only — threshold mismatch moves a real part's ICMR the same way it dominates the offset row's statistical half; a mismatch MC pass is the natural follow-on, sibling to #17/#26) | Predicted (lower bound): slow/cold/low-VDD per `design/opamp_sizing.md`'s "Headroom check" — **confirmed**: worst lower bound at `SS / −40 °C / 1.08 V`, and the paper chain is directionally right but ~23 mV optimistic at `TT / 27 °C / 1.08 V` and up to ~95 mV at the binding corner (the real `Vgs(M1)` is ≈ 0.43 V, not the 0.39 V assumed). No prediction existed for the upper bound; measured worst upper bound at **`FS / 125 °C / 1.08 V`** — the same corner family that binds DC gain, GBW, noise, systematic offset and CMRR. See `sim/input-cmr/README.md` "Measured vs. predicted binding corner" | Measured (not yet ratified) |
| Output swing | **Ratified bound: headroom ≥ 251 mV from VDD and ≥ 141 mV from VSS worst-case, tracking span ≥ 0.571 V worst-case [DR-2]** — measured envelope span 0.571 V worst / 0.900 V best, `sim/output-swing/records/20260921-151759-707b34c.csv` at the **−6 dB incremental-gain** criterion that record's own README defines ("The swing criterion"); the worst-span point is `mos_ss / 125 °C / 1.08 V` (`Vout` 0.206–0.777 V), best `mos_ff / −40 °C / 1.32 V`; into `CL = 2 pF` [DR-1], no resistive load (an **upper bound** — a loaded-row decision is separate). Headroom per rail is the comparable-across-supplies form; absolute `Vout` bounds per point are in the record | — | — (deterministic corner-worst-case; no mismatch/MC deck — same nominal-device caveat as the offset row's systematic half) | Predicted: low VDD / worst output-stage headroom corner. **Confirmed on the supply axis, corrected on the process/temperature axis**: every worst figure (span, per-rail headroom) lands at 1.08 V, but no single process x temperature point binds both rails and the span — worst span at **SS / 125 °C** (hot), worst high-rail headroom at **FS / −40 °C** (251 mV), worst low-rail headroom at **FF / −40 °C** (141 mV). See `sim/output-swing/README.md` "Measured vs. predicted binding corner" | Ratified [DR-2] (unloaded; a loaded-row decision is separate) |
| Quiescent power | **Ratified bound Iq ≤ 119.7 uA worst-case (total Vdd current, incl. the external 10 uA `ibias` reference) [DR-2]** — measured envelope 119.7 uA worst / 99.9 uA best, `sim/open-loop-ac/records/20260910-221601-22feaba.csv`; signal-path-only figures (excluding `ibias`) are ~10 uA lower per point, see that record's `ivdd_signal_path_a` column and `design/opamp_sizing.md`'s "Iq reporting note" | — | — (deterministic corner-worst-case) | Predicted: FF / 125 °C / 1.32 V (leakage + fastest devices) — matches `gf180-bandgap`'s ratified Iq binding-corner convention. **Measured worst case is instead SS / −40 °C / 1.32 V** — the coldest, slowest corner drew the most current in this design, opposite the leakage-dominated prediction (consistent with a bias point where lower `Vth`-headroom margin, not leakage, sets `Iq` at this corner) | Ratified [DR-2] |
| Area | **[TBD-12]** | — | n/a (not a PVT line) | n/a | not ratifiable yet — Area is a post-layout property and no layout exists in this repo. Stays `[TBD-12]` (0002 residual register) |

Every `[TBD-#n]` row above is deliberately left unset rather than guessed,
per `CLAUDE.md`'s "no claim without a testbench" rule. After the DR-0002
ratification pass, one row keeps that tag, with an explicit reason it
cannot yet be ratified (see the Status column above and
[0002](decision-records/0002-target-spec-ratification.md)'s residual
register): Area, a post-layout property for which no layout exists. It
stays unset — ratifying it now would be exactly the kind of evidence-free
claim that rule forbids. It will be ratified by a future two-key
ratification pass once a layout exists, amending 0002 rather than
starting over — and likewise for the offset row's Monte Carlo statistical
basis (#17), whose own future pass will supersede the corresponding
ratified systematic half. The CMRR row's mismatch-inclusive term (#26) is
the one residual whose pass has now run:
[0004-cmrr-mismatch-inclusive-ratification.md](decision-records/0004-cmrr-mismatch-inclusive-ratification.md)
cited its record and superseded that row's systematic half, amending 0002
residual (c) exactly as pre-registered.

## 3. What this table is not

- **Ratified, but not blanket-ratified.** This table's measured rows are
  ratified by
  [0002-target-spec-ratification.md](decision-records/0002-target-spec-ratification.md)
  via `CLAUDE.md`'s two-key mechanism — an EE key and a market key, both
  posted on the ratification PR and neither held by that PR's author
  ([2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)); the
  merge commit is the ratification record. The Area row above, the offset
  row's statistical-basis column (#17 — its own re-ratification pass still
  pending), the loaded-swing decision, and the deliberately un-opened HV
  stretch row are explicitly **not** ratified and stay pending their own
  evidence; the CMRR row's mismatch-inclusive component (#26) moved out of
  this list with
  [0004-cmrr-mismatch-inclusive-ratification.md](decision-records/0004-cmrr-mismatch-inclusive-ratification.md)
  citing its record and superseding that row's systematic half. Per the
  generalized 2026-08-28 ruling (cited in issue #2's
  original body), a spec DR ratified with both keys needs no separate
  per-PR operator statement; the residual-row ratification passes cite and
  amend 0002 rather than starting over — 0004 is the first to run.
- **Not a commitment that every remaining `[TBD-#n]` row will end up
  non-trivial.** The corner grid and load capacitance rows in §1 are now
  resolved (`[DR-1]`); the remaining `[TBD-#n]` rows in §2 may still turn
  out to be determined jointly with future sizing work rather than
  independently.
- **Not opening the 3.3 V I/O (HV) stretch row.** It is named, not scoped
  in.
- **Not sizing an HBT input stage.** Per `CLAUDE.md`, this block is
  **CMOS only** unless a decision record opens the HBT-input stretch — no
  such record exists, so every row above assumes a CMOS (LV core) input
  stage.

## 4. Sources

- [`decision-records/0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md) —
  the `[DR-1]`-tagged corner-grid and CL rows in §1 above; the topology
  decision (input-pair polarity, output-stage class, cascode-or-not) that
  the remaining `[TBD-#n]` sizing rows in §2 size against; carried into
  force (`proposed` → `ratified`) with the DR-0002 pass below.
- [`decision-records/0002-target-spec-ratification.md`](decision-records/0002-target-spec-ratification.md) —
  the ratification record: one recommended bound per measured row (the
  `[DR-2]` tags in §1–§2 above), the residual register for the
  un-ratified rows, and the two-key (EE + market) process that bound them
  on the PR that landed this pass; its residual register has since been
  amended by
  [0004](decision-records/0004-cmrr-mismatch-inclusive-ratification.md),
  which discharged residual (c) for the CMRR row.
- [`decision-records/0003-input-pair-flicker-noise.md`](decision-records/0003-input-pair-flicker-noise.md) —
  the design-side decision on the noise row's `1/f`-dominated spectrum
  (issue #19): input-pair re-size **declined**, the committed
  minimum-length sizing accepted as an examined property rather than an
  unexamined side effect, with the quantified re-size trade (`1.83×` area
  moves the corner only to the band top; `8 – 20×` area buys
  `≈ 2.3 – 2.9×` integrated noise against a `≈ 3.8×` thermal asymptote)
  and the re-open trigger. No bound moves — the noise row above keeps its
  `[DR-2]` value; the row's cell cross-references the record.
- [`decision-records/0004-cmrr-mismatch-inclusive-ratification.md`](decision-records/0004-cmrr-mismatch-inclusive-ratification.md) —
  the CMRR-row re-ratification record (issue #32, DR-0002 residual (c)):
  binds the CMRR row's mismatch-inclusive 3σ bound (`[DR-4]` in §2 above,
  citing issue #26's record below), states the definition that is part of
  the ratified number (Av0 minus the +3σ point of the drawn-Acm
  distribution, linear domain, N=300 + process corners), registers the
  market key's relax-rule obligation for the weaker-than-systematic bound,
  and requests the EE key's ruling on the 3σ-domain choice — all under the
  same two-key mechanism as 0002, which that record's residual register
  amendment accompanies.
- `design/opamp_sizing.md` (issue #9) — the gm/ID sizing pass, citing
  `sim/gm-id-characterization/records/*.csv`, that sizes the DR-1 topology
  into `design/opamp_core.sch`; the DC gain, GBW, phase margin and
  quiescent power rows in §2 above (now `[DR-2]`) trace to this sizing
  and the bench below, not to a hand guess.
- `sim/open-loop-ac/records/20260910-221601-22feaba.{csv,md}` (issue #9) —
  the open-loop AC PVT-grid bench (45 points,
  `mos_tt/ss/ff/sf/fs` x `{-40,27,125} °C` x `{1.08,1.20,1.32} V`) this
  record's DC gain, GBW, phase margin and quiescent power numbers in §2
  above (now `[DR-2]`) are measured from.
- `sim/input-offset/records/20260918-203858-90844d2.{csv,md}` (issue #11) —
  the deterministic, corner-only DC input-referred offset bench (45 points,
  same grid and same `point_id` keys as the AC record above, measured two
  independent ways) the **systematic** half of the
  input-referred offset row in §2 (now `[DR-2]`) is measured from, and
  the source of that row's per-point systematic join and negative-control
  anchor in the Monte Carlo record below.
- `sim/input-offset/records/mc-20260921-174056-0a509fb.{csv,md}` (issue
  #17) — the device-mismatch Monte Carlo campaign (N = 300 draws per
  point, 16 points: all five corner families' `<corner>_mismatch` sections ×
  `{-40, 27, 125} °C` at the fixed 1.20 V supply, plus a plain-section
  negative control at the nominal point; campaign seed `20260921`, per-draw
  seeds and the full per-draw population committed in the `-draws.csv`
  twin) the `[P]`-tagged mismatch-inclusive 3σ half of the
  input-referred offset row in §2 and that row's statistical-basis column
  are measured from. Its negative control reproduces issue #11's
  `mos_tt_27C_1.20V` figure to 1.17 µV with exactly zero spread across
  its 300 draws; a same-seed duplicate draw is bit-identical (verified
  in-campaign, every run).
- `sim/slew-rate/records/20260918-210216-90844d2.{csv,md}` (issue #12) —
  the large-signal step (slew-rate) PVT-grid bench (the same 45 points,
  `mos_tt/ss/ff/sf/fs` x `{-40,27,125} °C` x `{1.08,1.20,1.32} V`, into
  `CL = 2 pF` [DR-1]) the slew-rate row in §2 above (now `[DR-2]`) is
  measured from. That experiment's `README.md` states the bench conditions
  the row cites (input common mode `VDD/2`, `±0.3 V`-per-input antiphase
  drive, `VDD/2 ± 0.15 V` measurement window) and the per-point checks
  behind them.
- `sim/input-noise/records/20260918-203850-90844d2.{csv,md}` (issue #13) —
  the input-referred-noise PVT-grid bench (same 45 points, unity-gain
  closed-loop `.noise` analysis) the noise row in §2 above (now `[DR-2]`) is
  measured from, and the experiment that **chose that row's band**
  (`100 Hz – 1 MHz` integrated + spot densities) — see that experiment's
  `README.md` "Choosing the band" for the sibling-repo precedent
  ([`sky130-opamp/spec/target-spec.md`](https://github.com/2AMLogic/sky130-opamp/blob/main/spec/target-spec.md)'s
  proposed band for the same topology) and the measured basis for both
  bounds.
- `sim/cmrr-psrr/records/20260921-151815-707b34c.{csv,md}` (issue #14) —
  the CMRR and PSRR+ PVT-grid bench (the same 45 points, two ngspice AC
  harnesses per point, joined per point to `sim/open-loop-ac/`'s `Av0`)
  the CMRR and PSRR rows in §2 above (now `[DR-2]`) are measured from —
  including the PSRR row's frequency-dependence figures and the CMRR
  row's systematic-only caveat (mismatch-inclusive CMRR tracked by #26).
  Landed mid-ratification-pass as PR #25.
- `sim/cmrr-mismatch/records/20260921-172304-65f5fb4.{csv,md}` (issue
  #26) — the mismatch Monte Carlo CMRR PVT-grid evidence (the same 45
  points, 300 independently drawn mismatch samples per point on the
  `sim/cmrr-psrr/` CMRR harness with SG13G2's own mismatch decks, same
  joined `Av0`) the CMRR row's mismatch-inclusive `[DR-4]` figures in §2
  above are measured from — the +3σ-of-Acm envelope 26.68–37.57 dB, its
  SS / −40 °C / 1.08 V binding corner, and the seed-determinism /
  negative-control / per-sample-sanity artifacts backing them. The two-key
  re-ratification pass that cites this record has now run:
  [0004-cmrr-mismatch-inclusive-ratification.md](decision-records/0004-cmrr-mismatch-inclusive-ratification.md)
  (DR-0002 residual (c)), superseding the `[DR-2]` systematic bound, which
  stays in-row as context.
- `sim/output-swing/records/20260921-151759-707b34c.{csv,md}` (issue #15) —
  the DC output-swing PVT-grid bench (the same 45 points, open-loop
  differential DC transfer curve) the output-swing row in §2 above (now
  `[DR-2]`) is measured from, at the **−6 dB incremental-gain** criterion
  that experiment's `README.md` defines ("The swing criterion") —
  headroom from both rails, tracking span, hard-clipped reach, and
  per-point cross-checks against the `open-loop-ac/` and `input-offset/`
  records at the same grid points.
- `sim/input-cmr/records/20260921-174405-65f5fb4.{csv,md}` (issue #21) —
  the input common-mode range (ICMR) PVT-grid bench (the same 45 points,
  open-loop common-mode sweep with the differential input pinned at zero)
  the ICMR row in §2 above is measured from, at the criterion-explicit
  saturation-bounds definitions that experiment's `README.md` states
  ("What this bench measures", "The saturation-edge probes"): lower
  bound at the measured `Vdsat(M5)` knee via a same-bias replica probe,
  upper bound at the pair's `Vds ≥ Vgs − Vth` with `Vth` per the repo's
  gm/ID constant-current convention measured at the bound's true body
  bias — including the low-rail finding that the nominal `Vcm = VDD/2`
  bias point sits below the measured lower bound at 15 of 45 points,
  and per-point cross-checks against the `open-loop-ac/` and
  `output-swing/` records at the same grid points.
- `CLAUDE.md` (this repo) — the row set, the "CMOS only" and "gm/ID first"
  rules, and the friction protocol.
- `README.md` (this repo) — the 1.2 V-primary supply framing this table's
  scope carries forward.
- [`sg13g2-bandgap/spec/porting-plan.md`](https://github.com/2AMLogic/sg13g2-bandgap/blob/main/spec/porting-plan.md) — SG13G2's LV/HV device-flavor split (§2 table), corner-file layout (§7), and mismatch-deck naming this table cites.
- [`gf180-bandgap` README](https://github.com/2AMLogic/gf180-bandgap#target-specification-ratified-2026-07-31-see-issue-1-and-35) — ratified target-spec table shape (Target / Stretch / Corner binding columns) and statistical-basis wording (`3σ, mismatch MC N≥300 + process corners`) this table borrows.
- [`gf180-temp-por/spec/target-spec.md`](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/target-spec.md) — the standalone `spec/target-spec.md` file precedent (rather than inline in `README.md`) and the `[DR-n]`/`[P]`/`[TBD-#n]` value-tag convention.
- [`gf180-opamp/spec/target-spec.md`](https://github.com/2AMLogic/gf180-opamp/blob/main/spec/target-spec.md) — the twin repo's already-built version of this exact deliverable, read directly for this same-shape draft.
- Gap-to-T1 tracker (linked from `README.md` once opened) — the
  artifact-presence checklist this spec's eventual evidence trail (`sim/`,
  `layout/`) will need to satisfy.

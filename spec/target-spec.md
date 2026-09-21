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
  `proposed` until now, is carried into force with them) — the CMRR and
  offset rows with their measured systematic halves only, their
  mismatch-inclusive residuals explicitly outstanding (#26, #17). The one
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
| **[DR-n]** | Carried unchanged from decision record `n`. `[DR-1]` ([`decision-records/0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md)) is carried by the corner-grid and CL rows in §1; `[DR-2]` ([`decision-records/0002-target-spec-ratification.md`](decision-records/0002-target-spec-ratification.md)) is carried by every ratified operating-condition row in §1 and performance row in §2 — its one recommended bound per row is the number this table binds. |
| **[P]** | **Proposed by this bootstrap pass** — an engineering placeholder with no measured SG13G2 device data behind it yet (e.g. carried from the block's own README/CLAUDE.md framing, or a structural convention borrowed from a sibling repo's ratified spec). Needs an explicit ratification decision before it binds. After the DR-0002 ratification, the only `[P]` value left in this table is §1's deliberately un-opened HV stretch row (plus the offset row's not-yet-discharged statistical-basis column) — see 0002's residual register. |
| **[TBD-#n]** | Deliberately unset — no SG13G2 device data exists yet to propose even a placeholder number. `#n` is the row's index in §2 below, so a future characterization pass can address each unset row individually. Tracked collectively under the gap-to-T1 tracker (linked from `README.md` and `porting-plan.md`) — item 5, "Full PVT corner simulation vs a ratified spec" — rather than one issue per row; no per-row characterization issue has been filed yet. |

**Status** column values in use: `Ratified [DR-2]` (a committed `sim/`
record backs the number and the two-key ratification recorded in
[`0002-target-spec-ratification.md`](decision-records/0002-target-spec-ratification.md)
bound the row — one bound per row); `Ratified, systematic only [DR-2] —
statistical basis outstanding` (the offset and CMRR rows: their
deterministic systematic terms are ratified, while the mismatch/Monte
Carlo bases they owe are not — tracked by #17 for the offset row and #26
for the CMRR row); and `not ratifiable yet — <reason>` (a `[TBD-#n]`
residual row whose evidence does not exist yet: Area, pending a layout).
The pre-ratification
draft vocabulary (`not started`, `Measured (not yet ratified)`, `Measured,
systematic only (not yet ratified; statistical basis outstanding)`)
described the same rows before the DR-0002 pass.

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
| Input-referred offset | **Systematic (deterministic, corner-only): ratified bound +21.9 mV worst-case [DR-2]** — measured envelope +21.9 mV worst / +11.4 mV best, `sim/input-offset/records/20260918-203858-90844d2.csv`, two independent methods agreeing to ≤ 0.3 mV at every point. **Random (mismatch) contribution not yet measured** — the total offset of a real part is this systematic term plus a random term no bench in this repo has produced yet | — | **3σ, mismatch MC N≥300 + process corners [P]** — unchanged: `sim/input-offset/` is deliberately deterministic (no Monte Carlo, no mismatch deck, no random draw), so it does **not** discharge this column; sample count still not re-derived for this topology or for SG13G2's own mismatch decks (`sg13g2_moslv_mod_mismatch.lib`). Tracked by the Monte Carlo follow-on #17 | Predicted: "likely SS/FF split-corner pairing on the input differential pair". **Partly confirmed, partly corrected by measurement**: the split corners are indeed the extremes (`FS` worst / `SF` best in 7 of 9 temperature-supply cells, bracketing `TT` in all 9), but the prediction named no temperature or supply and those dominate — the measured binding point is **FS / 125 °C / 1.08 V**, the same binding point as DC gain and GBW. The mismatch rationale behind the original prediction is untested here by construction; see `sim/input-offset/README.md` "Measured vs. predicted binding corner" | Ratified, systematic only [DR-2] — statistical basis outstanding (#17) |
| CMRR | **Ratified bound ≥ 30.75 dB worst-case — systematic, nominal-device CMRR only [DR-2]** — measured envelope 30.75 dB worst / 62.83 dB best, `sim/cmrr-psrr/records/20260921-151815-707b34c.csv`, computed as the same grid point's open-loop gain `Av0` (`sim/open-loop-ac/`'s committed record, joined per point, not re-measured) divided by the common-mode gain this bench injects at both inputs in phase, over the full 45-point PVT grid into `CL = 2 pF` [DR-1]. Flat from DC (10 mHz shelf read, machine-verified plateau) to 1 kHz at every corner. **Systematic (nominal-device) CMRR only** — perfectly matched devices, so this is the structural floor (mirror-load first-stage asymmetry amplified by the second stage); random mismatch, typically the dominant real-part CMRR term, is not measured here (the offset row's systematic/statistical split, applied to CMRR) | — | — (deterministic corner-worst-case; ideal-device systematic CMRR only — no mismatch/MC deck, so a real part's CMRR is expected worse; a mismatch Monte Carlo pass is the natural follow-on, tracked by #26, sibling to the offset row's #17) | **Measured: FS / 125 °C / 1.08 V** — the same corner that binds DC gain, GBW, noise and systematic offset (best case 62.83 dB at FS / −40 °C / 1.08 V). See `sim/cmrr-psrr/README.md` "Measured vs. predicted binding corners" | Ratified, systematic only [DR-2] — mismatch-inclusive CMRR outstanding (0002 residual register) |
| PSRR | **Ratified bound ≥ 1.87 dB worst-case (DC shelf; PSRR+) [DR-2]** — measured envelope 1.87 dB worst / 29.54 dB best (DC shelf), `sim/cmrr-psrr/records/20260921-151815-707b34c.csv`, computed as the same grid point's `Av0` divided by the VDD-to-output gain (PSRR+, `vss` being ground in this single-supply part), with the ideal external 10 µA `ibias` reference contributing no supply ripple (an on-die bias generator is out of this core's scope, per `design/opamp_sizing.md` "Bias scope"). **PSRR+ is strongly frequency-dependent** — the supply path has a genuine ~1.5 Hz zero, so rejection degrades ~4 dB from the DC shelf to the 100 Hz–10 kHz band (nominal 6.43 dB DC → 2.30 dB at 1 kHz; worst-in-band 1.30 dB at SF / −40 °C / 1.32 V); the quoted range is the DC shelf, and the per-point 10 mHz–1 GHz spectra are part of the record | — | — (deterministic corner-worst-case) | **Measured: FF / 125 °C / 1.32 V** (DC) — the only row so far binding at the fast/hot/high-rail corner (the direct output-PMOS supply path dominates), unlike every other row; in-band (1 kHz) worst is SF / −40 °C / 1.32 V. CMRR and PSRR do **not** bind at the same corner, as this row's own issue (#14) anticipated. See `sim/cmrr-psrr/README.md` "The 10 mHz sweep start and the ~1.5 Hz supply zero" | Ratified [DR-2] (DC shelf) |
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
starting over — and likewise for the two in-row statistical residuals, the
offset row's Monte Carlo basis (#17) and the CMRR row's
mismatch-inclusive term (#26), each of which will supersede the
corresponding ratified systematic half.

## 3. What this table is not

- **Ratified, but not blanket-ratified.** This table's measured rows are
  ratified by
  [0002-target-spec-ratification.md](decision-records/0002-target-spec-ratification.md)
  via `CLAUDE.md`'s two-key mechanism — an EE key and a market key, both
  posted on the ratification PR and neither held by that PR's author
  ([2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)); the
  merge commit is the ratification record. The Area row above, the offset
  row's statistical-basis column (#17), the CMRR row's
  mismatch-inclusive component (#26), the loaded-swing decision, and the
  deliberately un-opened HV stretch row are explicitly **not** ratified
  and stay pending their own evidence. Per the generalized 2026-08-28
  ruling (cited in issue #2's
  original body), a spec DR ratified with both keys needs no separate
  per-PR operator statement; a future ratification pass for the residual
  rows cites and amends 0002 rather than starting over.
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
  on the PR that landed this pass.
- [`decision-records/0003-input-pair-flicker-noise.md`](decision-records/0003-input-pair-flicker-noise.md) —
  the design-side decision on the noise row's `1/f`-dominated spectrum
  (issue #19): input-pair re-size **declined**, the committed
  minimum-length sizing accepted as an examined property rather than an
  unexamined side effect, with the quantified re-size trade (`1.83×` area
  moves the corner only to the band top; `8 – 20×` area buys
  `≈ 2.3 – 2.9×` integrated noise against a `≈ 3.8×` thermal asymptote)
  and the re-open trigger. No bound moves — the noise row above keeps its
  `[DR-2]` value; the row's cell cross-references the record.
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
  input-referred offset row in §2 (now `[DR-2]`, statistical basis still
  outstanding — #17) is measured from. Explicitly **not** the
  source of that row's statistical-basis column, which needs a Monte Carlo
  mismatch pass this record does not perform.
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
- `sim/output-swing/records/20260921-151759-707b34c.{csv,md}` (issue #15) —
  the DC output-swing PVT-grid bench (the same 45 points, open-loop
  differential DC transfer curve) the output-swing row in §2 above (now
  `[DR-2]`) is measured from, at the **−6 dB incremental-gain** criterion
  that experiment's `README.md` defines ("The swing criterion") —
  headroom from both rails, tracking span, hard-clipped reach, and
  per-point cross-checks against the `open-loop-ac/` and `input-offset/`
  records at the same grid points.
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

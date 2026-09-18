# Target specification — sg13g2-opamp

- **Status**: **DRAFT** — engineering input, not yet ratified. A first
  decision record now exists
  ([`decision-records/0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md),
  status `proposed`), but nothing in this repo has been through the
  ratification process yet; ratification of this table as a whole is a
  future issue, once the remaining `[TBD-#n]` sizing rows are filled in.
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
schematic capture, or simulation — every numeric target below is either an
engineering placeholder proposal `[P]` or explicitly `[TBD-#n]` pending
SG13G2 device data that does not exist in this repo yet (`design/`, `sim/`,
`layout/`, and `measurements/` all currently hold only placeholder
`README.md` files, verified against `main` @ `f8d5be9`, 2026-09-06).

## How to read this table

**Value tags** — every non-definitional value carries one, following
[`gf180-temp-por/spec/target-spec.md`](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/target-spec.md)'s
convention (also used by the twin's
[`gf180-opamp/spec/target-spec.md`](https://github.com/2AMLogic/gf180-opamp/blob/main/spec/target-spec.md)),
so a future reviewer can tell a carried decision from a new proposal at a
glance:

| Tag | Meaning |
|---|---|
| **[DR-n]** | Carried unchanged from decision record `n`. `[DR-1]` ([`decision-records/0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md)) is the first, carried by the corner-grid and CL rows in §1 below. |
| **[P]** | **Proposed by this bootstrap pass** — an engineering placeholder with no measured SG13G2 device data behind it yet (e.g. carried from the block's own README/CLAUDE.md framing, or a structural convention borrowed from a sibling repo's ratified spec). Needs an explicit ratification decision before it binds. |
| **[TBD-#n]** | Deliberately unset — no SG13G2 device data exists yet to propose even a placeholder number. `#n` is the row's index in §2 below, so a future characterization pass can address each unset row individually. Tracked collectively under the gap-to-T1 tracker (linked from `README.md` and `porting-plan.md`) — item 5, "Full PVT corner simulation vs a ratified spec" — rather than one issue per row; no per-row characterization issue has been filed yet. |

**Status** column values in use: `not started` (no `sim/` evidence exists for
this row at all), `Measured (not yet ratified)` (a committed `sim/` record
backs the number, but no ratification decision has been taken), and
`Measured, systematic only (not yet ratified; statistical basis outstanding)`
— used by the offset row, whose deterministic corner sweep is committed while
the statistical basis its own column commits to is not. There is still no
`ratifiable` or `conditional` row, unlike the more mature siblings this
table's shape is borrowed from.

**Binding corner** — the corner at which a row's hard edge is expected to
bind, reasoned from the topology's *generic* behavior (a two-stage
Miller-compensated op-amp) since no schematic exists yet to simulate. This is
a **prediction**, not a measurement — CLAUDE.md's "no claim without a
testbench" applies to any future *pass/fail* verdict on these rows, not to
this placeholder prediction of where the number will eventually bind. A
`sim/` record's full PVT grid supersedes the prediction once it exists.

## 1. Global operating conditions

| Parameter | Value | Notes |
|---|---|---|
| Supply voltage, VDD | **1.2 V ±10% → 1.08–1.32 V** [P] | Primary variant, using SG13G2's LV core devices (`sg13_lv_nmos`/`sg13_lv_pmos`, PSP 103.6 model, `V_GS ≤ 1.65 V @125°C`). Matches this repo's own `README.md` draft framing ("supply/power at 1.2 V") — not yet cross-checked against a ratified sibling spec, since neither `sg13g2-bandgap` nor `sg13g2-ldo` targets a 1.2 V-primary rail (both are 3.3 V-primary, per `sg13g2-bandgap/spec/porting-plan.md` DR-0002). This repo's 1.2 V choice is this block's own, carried from its own README, not inherited from a sibling. |
| Supply voltage, VDD (stretch) | **3.3 V I/O (HV flavor) — not opened** [P] | SG13G2's `sg13_hv_nmos`/`sg13_hv_pmos` (3.3 V I/O, `V_GS ≤ 3.3 V Maximum`) are named here only so a future decision record has a place to point at. Per `CLAUDE.md`, opening this row requires its own decision record; it is not in scope now. Never mixed with 1.2 V-flavor (LV) devices in one variant. |
| Operating temperature | **−40…+125 °C** [P] | Matches the fleet-wide convention (`sg13g2-bandgap`, `gf180-bandgap`, `gf180-temp-por`) for a commercial-grade PDK part. No SG13G2-specific device data has been checked against this range yet for this block — proposed by analogy, not measured. |
| Corner grid | **`cornerMOSlv.lib`: `tt`/`ff`/`ss`/`sf`/`fs` [DR-1]** | Ratified by [decision record 0001](decision-records/0001-topology-and-cl.md): the standard five-corner `mos_tt`/`mos_ff`/`mos_ss`/`mos_sf`/`mos_fs` grid on `cornerMOSlv.lib`, confirmed against the real PDK install by issue #5's gm/ID characterization sweep (`sim/gm-id-characterization/`) and now carried into this table. Temperature axis (`−40…+125 °C` row above) is crossed with this grid at testbench time, not folded into the corner-file grid itself. |
| Load capacitance, CL | **2 pF [DR-1]** | Ratified by [decision record 0001](decision-records/0001-topology-and-cl.md): a representative moderate load for this standalone canary op-amp's own bench (no downstream consumer or twin-repo precedent to match), chosen so GBW/slew targets derived from it stay meaningful for this block's likely bias-current budget. See the decision record's `## Alternatives considered` for rejected larger/consumer-matched CL choices. |

## 2. Performance targets

| Parameter | Target | Stretch | Statistical basis | Binding corner (predicted) | Status |
|---|---|---|---|---|---|
| Open-loop DC gain | **37.8 dB worst-case, 45.2 dB best-case [P]** — measured `sim/open-loop-ac/records/20260910-221601-22feaba.csv`, citing `design/opamp_sizing.md`'s sizing pass | — | — (deterministic corner-worst-case candidate) | Predicted: SS / −40 °C (lowest gm, highest output impedance loss). **Measured worst case is instead FS / 125 °C / 1.08 V** — gain falls monotonically with rising temperature across this grid, the opposite of the pre-schematic guess; see `sim/open-loop-ac/README.md` "Measured vs. predicted binding corners" | Measured (not yet ratified) |
| GBW (into stated CL = 2 pF [DR-1], above) | **4.74 MHz worst-case, 6.62 MHz best-case [P]** — measured `sim/open-loop-ac/records/20260910-221601-22feaba.csv` | — | — | Predicted: SS / −40 °C / low VDD (slowest devices). **Measured worst case is instead FS / 125 °C / 1.08 V**, same correction as the DC-gain row above | Measured (not yet ratified) |
| Phase margin (at GBW, same CL) | **≥ 60° [P]** — measured worst case 76.4° at FF / 125 °C / 1.32 V, clearing this target with comfortable margin (`sim/open-loop-ac/records/20260910-221601-22feaba.csv`) | ≥ 45° at the FF/hot corner if 60° is unreachable there | — (deterministic corner-worst-case) | FF / 125 °C (fastest devices, most peaking risk) — **confirmed** by measurement, the one row where the pre-schematic prediction and the measured worst corner agree | not started (target itself unchanged; measured number is new) |
| Slew rate (into stated CL = 2 pF [DR-1], above) | **7.51 V/µs worst-case, 9.91 V/µs best-case [P]** — measured `sim/slew-rate/records/20260918-210216-90844d2.csv`, worse of the rising/falling edge at each point (rising alone: 7.54–10.27 V/µs), at a fixed input common mode `Vcm = VDD/2` with the `±0.3 V`-per-input antiphase drive that record states | — | — (deterministic corner-worst-case) | Predicted: SS / −40 °C / low VDD (lowest tail-current headroom). **Confirmed** by measurement — `mos_ss_-40C_1.08V` is the measured worst point on both edges; slew rate rises monotonically with temperature and supply in this design, so the coldest/slowest/lowest-rail corner binds on all three axes at once. See `sim/slew-rate/README.md` "Measured vs. predicted binding corner" | Measured (not yet ratified) |
| Input-referred noise (band: **100 Hz – 1 MHz integrated**, plus spot densities; same stated CL = 2 pF [DR-1]) | **108.9 µVrms worst-case, 87.3 µVrms nominal (`TT / 27 °C / 1.20 V`), 73.4 µVrms best-case [P]**, integrated over 100 Hz – 1 MHz — measured `sim/input-noise/records/20260918-203850-90844d2.csv`. Spot densities, nominal / worst-case: **2.79 / 3.48 µV/√Hz @ 100 Hz**, **881 / 1100 nV/√Hz @ 1 kHz**, **35.4 / 44.3 nV/√Hz @ 1 MHz**. The **band is part of the number** and was chosen in this measurement's own pass (the row previously read `[TBD-6]`, "band not yet chosen"): it matches the `sky130-opamp` twin's proposed `100 Hz – 1 MHz` row for the same topology, and its bounds are defended against this PDK's own measured GBW and the measured `1/f`-dominated spectrum — see `sim/input-noise/README.md` "Choosing the band". A µVrms figure quoted without both bounds is not a claim about this amplifier | — | — (deterministic corner-worst-case; no mismatch/MC noise deck run, and the ideal `ibias` source contributes no noise) | **Measured: FS / 125 °C / 1.08 V** — the same corner that binds DC gain and GBW above; temperature and supply dominate the process axis (all three worst points are `125 °C / 1.08 V`). The integrated figure is 91–94 % flicker-dominated at every corner, so the flicker-worst corner binds; the *thermal* floor binds elsewhere (28.1 nV/√Hz at SS / 125 °C / 1.08 V), which is why a higher or narrower band would bind at a different corner | Measured (not yet ratified) |
| Input-referred offset | **Systematic (deterministic, corner-only): +21.9 mV worst-case, +11.4 mV best-case [P]** — measured `sim/input-offset/records/20260918-203858-90844d2.csv`, two independent methods agreeing to ≤ 0.3 mV at every point. **Random (mismatch) contribution not yet measured** — the total offset of a real part is this systematic term plus a random term no bench in this repo has produced yet | — | **3σ, mismatch MC N≥300 + process corners [P]** — unchanged: `sim/input-offset/` is deliberately deterministic (no Monte Carlo, no mismatch deck, no random draw), so it does **not** discharge this column; sample count still not re-derived for this topology or for SG13G2's own mismatch decks (`sg13g2_moslv_mod_mismatch.lib`). Tracked by the Monte Carlo follow-on | Predicted: "likely SS/FF split-corner pairing on the input differential pair". **Partly confirmed, partly corrected by measurement**: the split corners are indeed the extremes (`FS` worst / `SF` best in 7 of 9 temperature-supply cells, bracketing `TT` in all 9), but the prediction named no temperature or supply and those dominate — the measured binding point is **FS / 125 °C / 1.08 V**, the same binding point as DC gain and GBW. The mismatch rationale behind the original prediction is untested here by construction; see `sim/input-offset/README.md` "Measured vs. predicted binding corner" | Measured, systematic only (not yet ratified; statistical basis outstanding) |
| CMRR | **[TBD-8]** | — | — (deterministic corner-worst-case) | to be determined | not started |
| PSRR | **[TBD-9]** | — | — (deterministic corner-worst-case) | to be determined | not started |
| Output swing | **[TBD-10]** | — | — | low VDD / worst output-stage headroom corner | not started |
| Quiescent power | **Iq = 119.7 uA worst-case (total Vdd current, incl. the external 10 uA `ibias` reference), 99.9 uA best-case [P]** — measured `sim/open-loop-ac/records/20260910-221601-22feaba.csv`; signal-path-only figures (excluding `ibias`) are ~10 uA lower per point, see that record's `ivdd_signal_path_a` column and `design/opamp_sizing.md`'s "Iq reporting note" | — | — (deterministic corner-worst-case) | Predicted: FF / 125 °C / 1.32 V (leakage + fastest devices) — matches `gf180-bandgap`'s ratified Iq binding-corner convention. **Measured worst case is instead SS / −40 °C / 1.32 V** — the coldest, slowest corner drew the most current in this design, opposite the leakage-dominated prediction (consistent with a bias point where lower `Vth`-headroom margin, not leakage, sets `Iq` at this corner) | Measured (not yet ratified) |
| Area | **[TBD-12]** | — | n/a (not a PVT line) | n/a | not started |

Every `[TBD-#n]` row above is deliberately left unset rather than guessed,
per `CLAUDE.md`'s "no claim without a testbench" and "gm/ID first" rules,
and per this issue's explicit scope (scaffolding only, no circuit design or
simulation). The topology decision and gm/ID device-characterization pass
these rows depend on are now both committed
([`decision-records/0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md)
and `sim/gm-id-characterization/`, respectively) — filling the remaining
`[TBD-#n]` rows above is now a sizing exercise against that topology and
that data, not a decision that is still outstanding, per `CLAUDE.md`'s
"gm/ID first, committed to `sim/` before sizing."

## 3. What this table is not

- **Not ratified.** `spec/decision-records/` now exists (`0001-topology-and-cl.md`,
  status `proposed`), but nothing in this repo has passed ratification
  (per `CLAUDE.md`'s two-key mechanism — an EE key and a market key) yet —
  that is a future issue's job, once the remaining `[TBD-#n]` rows above
  have real SG13G2 device data behind them. Per the generalized 2026-08-28
  ruling (cited in issue #2's original body), a scope-only spec DR ratified
  with both keys needs no separate per-PR operator statement — but that
  ruling applies at ratification time, not to this DRAFT.
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
  the remaining `[TBD-#n]` sizing rows in §2 will size against.
- `design/opamp_sizing.md` (issue #9) — the gm/ID sizing pass, citing
  `sim/gm-id-characterization/records/*.csv`, that sizes the DR-1 topology
  into `design/opamp_core.sch`; the `[P]`-tagged DC gain, GBW, phase margin
  and quiescent power rows in §2 above trace to this sizing and the bench
  below, not to a hand guess.
- `sim/open-loop-ac/records/20260910-221601-22feaba.{csv,md}` (issue #9) —
  the open-loop AC PVT-grid bench (45 points,
  `mos_tt/ss/ff/sf/fs` x `{-40,27,125} °C` x `{1.08,1.20,1.32} V`) this
  update's `[P]`-tagged DC gain, GBW, phase margin and quiescent power
  numbers in §2 above are measured from.
- `sim/input-offset/records/20260918-203858-90844d2.{csv,md}` (issue #11) —
  the deterministic, corner-only DC input-referred offset bench (45 points,
  same grid and same `point_id` keys as the AC record above, measured two
  independent ways) the `[P]`-tagged **systematic** half of the
  input-referred offset row in §2 is measured from. Explicitly **not** the
  source of that row's statistical-basis column, which needs a Monte Carlo
  mismatch pass this record does not perform.
- `sim/slew-rate/records/20260918-210216-90844d2.{csv,md}` (issue #12) —
  the large-signal step (slew-rate) PVT-grid bench (the same 45 points,
  `mos_tt/ss/ff/sf/fs` x `{-40,27,125} °C` x `{1.08,1.20,1.32} V`, into
  `CL = 2 pF` [DR-1]) the `[P]`-tagged slew-rate row in §2 above is
  measured from. That experiment's `README.md` states the bench conditions
  the row cites (input common mode `VDD/2`, `±0.3 V`-per-input antiphase
  drive, `VDD/2 ± 0.15 V` measurement window) and the per-point checks
  behind them.
- `sim/input-noise/records/20260918-203850-90844d2.{csv,md}` (issue #13) —
  the input-referred-noise PVT-grid bench (same 45 points, unity-gain
  closed-loop `.noise` analysis) the `[P]`-tagged noise row in §2 above is
  measured from, and the experiment that **chose that row's band**
  (`100 Hz – 1 MHz` integrated + spot densities) — see that experiment's
  `README.md` "Choosing the band" for the sibling-repo precedent
  ([`sky130-opamp/spec/target-spec.md`](https://github.com/2AMLogic/sky130-opamp/blob/main/spec/target-spec.md)'s
  proposed band for the same topology) and the measured basis for both
  bounds.
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

# Target specification — sg13g2-opamp

- **Status**: **DRAFT** — engineering input, not yet ratified. No decision
  record exists yet in this repo; ratification is a future issue, once
  gm/ID device-characterization data lands under `sim/`.
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
| **[DR-n]** | Carried unchanged from decision record `n`. None exist yet in this repo — no row currently carries this tag. |
| **[P]** | **Proposed by this bootstrap pass** — an engineering placeholder with no measured SG13G2 device data behind it yet (e.g. carried from the block's own README/CLAUDE.md framing, or a structural convention borrowed from a sibling repo's ratified spec). Needs an explicit ratification decision before it binds. |
| **[TBD-#n]** | Deliberately unset — no SG13G2 device data exists yet to propose even a placeholder number. `#n` is the row's index in §2 below, so a future characterization pass can address each unset row individually. Tracked collectively under the gap-to-T1 tracker (linked from `README.md` and `porting-plan.md`) — item 5, "Full PVT corner simulation vs a ratified spec" — rather than one issue per row; no per-row characterization issue has been filed yet. |

**Status** column values: `not started` (no `sim/` evidence exists for this
row at all — true of every row in this pass) — there is no `ratifiable` or
`conditional` row yet, unlike the more mature siblings this table's shape is
borrowed from.

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
| Corner grid | **[TBD-1]** | Process corners for SG13G2's LV MOS flavor are not yet enumerated in this repo. SG13G2 ships per-device-family corner files (`cornerMOSlv.lib`, `cornerMOShv.lib`, `cornerRES.lib`, `cornerCAP.lib`, per `sg13g2-bandgap/spec/porting-plan.md` §7) — the likely template is the standard `tt`/`ff`/`ss`/`fs`/`sf` grid on `cornerMOSlv.lib`, but this has not been confirmed against this block's actual device menu (which resistor/cap flavors it uses, if any) yet — see [`porting-plan.md`](porting-plan.md) §4. |
| Load capacitance, CL | **[TBD-2]** | GBW/phase-margin targets are stated "into stated CL" per `CLAUDE.md`; no CL has been chosen yet since no application/bench context exists for this standalone op-amp characterization. |

## 2. Performance targets

| Parameter | Target | Stretch | Statistical basis | Binding corner (predicted) | Status |
|---|---|---|---|---|---|
| Open-loop DC gain | **[TBD-3]** | — | — (deterministic corner-worst-case candidate) | SS / −40 °C (lowest gm, highest output impedance loss) | not started |
| GBW (into stated CL, [TBD-2] above) | **[TBD-4]** | — | — | SS / −40 °C / low VDD (slowest devices) | not started |
| Phase margin (at GBW, same CL) | **≥ 60° [P]** | ≥ 45° at the FF/hot corner if 60° is unreachable there | — (deterministic corner-worst-case) | FF / 125 °C (fastest devices, most peaking risk) | not started |
| Slew rate | **[TBD-5]** | — | — | SS / −40 °C / low VDD (lowest tail-current headroom) | not started |
| Input-referred noise | **[TBD-6]** — band not yet chosen | — | n/a until a band is set | n/a | not started |
| Input-referred offset | **[TBD-7]** | — | **3σ, mismatch MC N≥300 + process corners [P]** — matches `gf180-bandgap`'s ratified statistical-basis convention (also carried by the `gf180-opamp` twin); sample count not yet re-derived for this topology or for SG13G2's own mismatch decks (`sg13g2_moslv_mod_mismatch.lib`) | to be determined once a topology is drawn — likely SS/FF split-corner pairing on the input differential pair | not started |
| CMRR | **[TBD-8]** | — | — (deterministic corner-worst-case) | to be determined | not started |
| PSRR | **[TBD-9]** | — | — (deterministic corner-worst-case) | to be determined | not started |
| Output swing | **[TBD-10]** | — | — | low VDD / worst output-stage headroom corner | not started |
| Quiescent power | **[TBD-11]** | — | — (deterministic corner-worst-case) | FF / 125 °C / 1.32 V (leakage + fastest devices) — matches `gf180-bandgap`'s ratified Iq binding-corner convention, adapted to this block's 1.2 V rail | not started |
| Area | **[TBD-12]** | — | n/a (not a PVT line) | n/a | not started |

Every `[TBD-#n]` row above is deliberately left unset rather than guessed,
per `CLAUDE.md`'s "no claim without a testbench" and "gm/ID first" rules,
and per this issue's explicit scope (scaffolding only, no circuit design or
simulation). Filling any of them requires, at minimum, a topology decision
(tracked in [`porting-plan.md`](porting-plan.md)) and a gm/ID
device-characterization pass committed to `sim/`, per `CLAUDE.md`'s
"gm/ID first, committed to `sim/` before sizing."

## 3. What this table is not

- **Not ratified.** No `spec/decision-records/` directory exists yet in
  this repo. Ratification (per `CLAUDE.md`'s two-key mechanism — an EE key
  and a market key) is a future issue's job, once the `[TBD-#n]` rows above
  have real SG13G2 device data behind them. Per the generalized 2026-08-28
  ruling (cited in issue #2's original body), a scope-only spec DR ratified
  with both keys needs no separate per-PR operator statement — but that
  ruling applies at ratification time, not to this DRAFT.
- **Not a commitment that every `[TBD-#n]` row will end up non-trivial.**
  Some rows (e.g. the corner grid, or the load capacitance) may turn out to
  be determined jointly with a topology decision rather than independently.
- **Not opening the 3.3 V I/O (HV) stretch row.** It is named, not scoped
  in.
- **Not sizing an HBT input stage.** Per `CLAUDE.md`, this block is
  **CMOS only** unless a decision record opens the HBT-input stretch — no
  such record exists, so every row above assumes a CMOS (LV core) input
  stage.

## 4. Sources

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

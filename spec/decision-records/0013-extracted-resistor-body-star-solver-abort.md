# 0013 — The extracted-resistor body star leaf: default solver settings stand, the extracted-leg slew row waits on the extractor

- **Status**: decided — this record sets no spec value and edits no
  ratified row. It records the simulation-methodology answer to issue
  #451's question — the committed slew bench aborts on any extraction
  whose PDK resistor card's body terminal sits on its own parasitic star
  leaf; is that a bench-settings problem (a DR-0005 tolerance/option
  change), a model problem, or an extractor problem? — with either
  outcome fully specified and reversible via this record.
- **Date**: 2026-11-22
- **Decided by**: Builder agent, issue #451
- **Related**: #451 (the issue this decides),
  [0005](0005-ngspice-reltol-policy.md) (the default-solver-settings rule
  this interprets), #430 and
  [PR #452](https://github.com/2AMLogic/sg13g2-opamp/pull/452) (the drawn
  candidate, its extraction and the controls that motivated the question),
  #439 (the no-resistor grid that lost one corner on the same node
  family), PR #431 (the open TT `ibias` star investigation — the same
  node family reached from a corner), #332 / #342 (the topology work
  gated on the extracted-leg slew row), #312 (the klt pin — the abort is
  not a runner-version artifact; local and fleet abort byte-identically),
  [2AMLogic/klayout-tools#7317](https://github.com/2AMLogic/klayout-tools/issues/7317)
  (the extractor-side ask this decision hands the fix to),
  `sim/post-layout/rz-solver-451/` (the evidence record: 17 control legs
  and three grids, every diagnostic preserved),
  `sim/post-layout/rz-layout-430/` (the candidate and its controls)

## Context

The committed slew bench (`sim/slew-rate/klt/slew.request.json`) aborts
its transient on the klt 0.9.0 extraction of any design that draws a PDK
`rppd` resistor: `Timestep too small … timestep = 6.25e-23 s`, naming a
bias-network star node. On the #430 candidate, 37 of 45 corners abort;
which corners pass is deterministic per deck but uncorrelated with corner
physics (8/45 under trapezoidal integration, a different 9/45 under
`method=gear`). PR #452's controls already established that the layout's
parasitics are not the trigger (ideal-resistor swap passes) and the model
card is (removing only it cures the corner), and that no knob tried there
was a cure. Issue #451 asked for the mechanism, named with evidence, and
for the decision to be recorded where DR-0005's "ngspice default solver
settings" rule is interpreted.

The evidence record `sim/post-layout/rz-solver-451/` isolates the
mechanism by star surgery on the extraction, one change at a time, all
legs one corner (`mos_ss / 1.08 V / −40 °C`) on the batch fleet:

- Merging **only the `rppd` card's body-terminal leaf** (`vss__t23`)
  onto the rail hub cures the corner — and the whole 45-corner grid
  (45/45, zero diagnostics, worst 8.1003 / 7.6881 V/µs at the binding
  corner, matching every passing control of #430 §5 to 0.0001 V/µs).
- Keeping that leaf while merging **every other leaf** (152) also runs
  clean; keeping it plus **one companion leaf** of the same net fails
  again; the failure needs the near-floating body node and a multi-node
  star.
- The body leaf's star resistance set anywhere from **1 mΩ to 6 MΩ**
  aborts identically in kind — the extra node, not the ohms.
- The model **alone** with its body behind the same resistance runs, and
  so does the **schematic** netlist (no star network) with the body
  equally isolated: the abort needs the extracted amplifier around the
  near-floating body node. `sw_et=1` (the physical thermal tie) does not
  cure it, so the model's thermal network is not the carrier.
- The failure mode is **Newton non-convergence**, not local-truncation-
  error step collapse: the abort time moves with `itl4` (identical at 10
  and 100 iterations; 500 iterations advance past the first wall and fail
  later), and an LTE cut never consults the iteration limit. A 10× looser
  `reltol` does not cure it; screening runs with `reltol` 1e-4, `abstol`,
  `gmin`, `trtol`, `chgtol` and `.options interp` removed all abort.
  `.options noopiter` passes with the correct slew to six digits — the
  circuit's answer is fine; the iteration is what fails.
- The abort is deterministic per deck: 10/10 identical local runs, and a
  full 45-corner grid rerun identical corner-by-corner and
  abort-detail-by-abort-detail to #430's submission. The solver names the
  `ibias` star (the bias diode's drain leaf — the amplifier's
  highest-gain re-entry point for rail ripple) wherever the trigger sits;
  merging the `ibias` star alone does not cure.

## Decision

1. **DR-0005's default solver settings stand, and this failure is not a
   tolerance question.** The committed slew bench gains no `.options`
   card, no `ngspice_init` line and no analysis change for this abort:
   the isolation ladder shows no solver setting cures it (the cures
   attempted by iteration suppression — `noopiter` — or by method change
   — `gear`, which still loses 36/45 corners — are not verification
   settings). This record is the interpretation of DR-0005 for the
   `timestep_too_small` family: a transient abort that survives a
   six-decade resistance sweep and both tolerance directions is
   topological, and the answer is to name the topology, not to tune the
   solver.
2. **The mechanism is named: extractor × model interaction.** The klt
   star extraction puts the `rppd` card's body terminal on its own
   parasitic leaf; the r3_cmc body node is near-floating (internal
   capacitances only), and on this amplifier that topology makes
   ngspice-47's Newton iteration fail on the bias network. Not the
   bench, not the layout's parasitic magnitudes, not the thermal
   network, and not the design.
3. **The fix belongs to the extractor**, and has been filed there
   ([2AMLogic/klayout-tools#7317](https://github.com/2AMLogic/klayout-tools/issues/7317)):
   device body/bulk terminals should sit on the net hub (or a declared
   terminal-class star policy), because their parasitic separation is
   not meaningful for a quasi-static star model. Until a klt release
   carrying that change is pinned here, the fix does not land in this
   repo; netlist surgery on committed extractions is a control, never
   the committed bench.
4. **Until then, the extracted-leg slew row of any design whose PDK
   resistor body sits on a star leaf is `ungraded`, with the bracket
   recorded.** The row is not failed — every leg that completes passes
   it — and it is not graded by a control. The body-on-hub control grid
   (`sim/post-layout/rz-solver-451/records/c451_bodyhub_grid_slew.slew.json`,
   45/45, worst 8.1003 / 7.6881 V/µs) and the schematic-leg grid
   (`c451_sch_grid_slew.slew.json`, 45/45, worst 7.7626 / 7.7401 V/µs)
   bracket what the row reads; the signoff story cites this record. When
   a pinned extractor release re-homes body terminals, the extracted-leg
   slew grid is re-run on the committed bench and the row grades
   normally — that re-run, not this record, closes it.
5. **A drawn PDK resistor does not block schematic-leg signoff.** The
   schematic netlist's `rppd` card has its body on the port rail and its
   grid passes 45/45 with zero diagnostics; the schematic leg of every
   slew-bound row continues to grade normally while 4 holds.

Nothing here relaxes a ratified bound or moves a spec row; DR-0012's
`cap_wcs` slew exposure question is untouched and remains with its ADR's
owners.

## Reversal

Re-open by a new decision record if the extractor ask lands differently
than #7317 proposes (for example a star policy that still separates body
terminals but keeps them solver-safe), or if a future ngspice release
makes the near-floating body leaf transient-safe on its own — in which
case the extracted-leg slew grid is re-run on the committed bench and
clause 4 retires with that evidence.

# 0007: Area definition (TBD-12) — propose the hierarchical geometry bounding box of `opamp_core` as an integration footprint

- **Status**: `proposed — not ratified`. Nothing here binds. This record edits
  none of `spec/target-spec.md`, `spec/integrator.json`, `signoff/`, or any
  consumer verdict: the Area row stays `[TBD-12]`, `area_mm2` stays `null`,
  and no area target or performance bound is set. Binding requires the
  independent two-key gate of
  [0002](0002-target-spec-ratification.md) (EE key `RATIFY-KEY: ee` and market
  key `RATIFY-KEY: market`), **neither key held by the author of this draft or
  by the design's author**. Neither the drafting agent nor the design author
  supplies those approvals; the drafting agent does not self-ratify.
- **Date**: 2026-10-09
- **Decided by**: Builder agent, issue #115 (draft recommendation and
  measurement only)
- **Related**: #115, #3 (gap-to-T1 tracker), #16 / [0002](0002-target-spec-ratification.md)
  (residual (a) Area `[TBD-12]`), [0006](0006-icmr-row-resolution.md) (draft-only
  precedent), `layout/README.md`

## Context

0002 left Area `[TBD-12]` because no layout existed. A routed layout is now
committed (`layout/opamp_core/opamp_core.gds`), but no record selects what
"area" means. That choice must precede any number: bounding box, active
(device) area and placed-cell area are different quantities, and a figure
quoted without a definition is not comparable across PDKs. The same
definition can be proposed to the gf180 and sky130 twins; any change there is
outside this record.

## Measurement (committed; reproducible offline)

Record: `layout/opamp_core/area_measurement.json`, produced and verified by
`layout/opamp_core/measure_area.py` (`klayout.db`, no PDK, klt or simulator;
the GDS is read, never regenerated).

| Quantity | Value |
|---|---|
| Source | `layout/opamp_core/opamp_core.gds`, sha256 `07fcb21698709178395cb2f04ba998c3752efb6eff24aace7626d9ffc10e553e` |
| Cell (explicit by name) | `opamp_core` |
| Definition id | `opamp-core-hier-bbox-v1` |
| dbu | 0.001 µm |
| Box (DBU) | left −11500, bottom −700, right 73800, top 31840 |
| Width x height | 85300 x 32540 DBU = **85.3 µm x 32.54 µm** |
| Area | 2 775 662 000 DBU² = **2775.662 µm²** = **0.002775662 mm²** |

Rules (also the JSON's `definition.rules`): named cell only; recursive through
instance transformations and arrays; all layers/datatypes carrying geometry
(boxes, polygons, paths, boundary/outline layers); **text never counts**;
integer-DBU arithmetic, area = integer width x integer height, converted by
exact decimal arithmetic (1 mm² = 1 000 000 µm²) with no rounding. Missing
cell, empty geometry, unreadable file and nonpositive dbu fail with a
diagnostic. `measure_area.py --check` re-derives the record and fails on
input-hash, definition or value drift; it never writes.

The figure is a measurement of this committed GDS only. It changes if the GDS
bytes change (the check then fails until the record is refreshed together
with the signoff pins). It is reported as measured, not as a target.

## Options

1. **Hierarchical geometry bounding box of the named `opamp_core` cell
   (recommended) — an integration footprint.** Unambiguous, tool-independent,
   reproducible from the GDS bytes alone, identical across the three PDK twins
   with no device-recognition rules. Cost: it includes whitespace inside the
   box and includes every drawn layer (including any outline layer), so it
   overstates silicon actually used. **A geometry bounding box is not
   necessarily a legal placement boundary, a pad-ring footprint, a keepout
   budget, or an area target.** Integrators must still add spacing, guard
   rings, routing channels and ring/keepout allowances.
2. **Active/device area** (sum of device or active-layer regions).
   **Deferred.** Needs a separate definition of which layers/devices count
   (gates, diffusion, wells, capacitor plates, tap rings), and an overlap
   policy (merged vs summed). No number is claimed here.
3. **Placed-cell area** (sum of placed device-cell boxes). **Deferred.**
   Needs a policy for overlapping or abutting cell boxes and for what a
   "placed cell" is in a block whose devices are flattened on import. No
   number is claimed here.
4. **Bounding box including a pad ring / keepout halo.** Not available: no pad
   ring exists, and halo width is an integration decision outside this block.

## Recommendation

Propose option 1 as the definition for the Area row, identified as
`opamp-core-hier-bbox-v1`, with the measurement above as its provenance. Options 2 and 3
remain separate follow-up definitions; each would need its own record.

## Gates (each separate; none is authorized by this draft)

- **Draft completion (this record, issue #115).** Supplies the definition and
  reproducible measurement only. It does **not** resolve TBD-12.
- **Independent two-key ratification.** Non-author EE and market reviews per
  [0002](0002-target-spec-ratification.md), recorded on the PR that flips this
  record's status.
- **Subsequent publication change** (after ratification, separate PR). Must
  resolve or re-defer TBD-12 in the target-spec Area row and
  `spec/integrator.json` together. `signoff/sync_integrator.py` today derives
  maturity/artifact fields only and hard-codes TBD-12 as unratified in
  `GDS_NOTE`; that change must extend its `derive`, `current`, drift checks and
  update handling to manage the approved area value and provenance and revise
  the note, with tests. It must also audit characterization selectors, consumer
  wording and other TBD-12 references. Historical decision records and
  append-only evidence keep their original context.

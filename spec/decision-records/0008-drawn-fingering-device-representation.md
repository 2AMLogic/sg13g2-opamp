# 0008: Device representation: the schematic carries the drawn fingering (issue #237, option 1)

- **Status**: decided. Implementation is staged; see "Sequencing". This record
  sets no spec value and moves no ratified bound. No `spec/target-spec.md`
  row, `spec/integrator.json` value or `signoff/` verdict is edited by the PR
  that carries it. It chooses how the design netlist represents its
  transistors and orders the work that follows from that choice.
- **Date**: 2026-10-15
- **Decided by**: Builder agent, issue #237. This is the Curator/Champion-approved
  recommended approach, confirmed by the probe below.
- **Related**: #237, #86 / PR #236 (the first post-layout run),
  #241 (open-loop AC bench loop-break defect, found by this probe),
  2AMLogic/klayout-tools#3298 (tool gap: `klt pex` has no parasitic-free
  leg), `sim/fingering-probe/` (the probe), `layout/opamp_core/generate.py`
  (`PAIRS` / `FOLDED`, the drawn device tables), `layout/opamp_core/lvs_reference.py`

## Context

The first 45-corner pex run (`layout/opamp_core/pex_report.json`) compared
a reference leg built from `design/netlist/opamp_core.spice`, with one lumped
`ng=1 m=1` device per transistor, against the extracted leg. The extracted leg
has the drawn interdigitated units (M1-M5, Mbias: 2 units each), folded
fingers (M7: 7 x 1.7 um, M6: 12 x 2.75 um) and rail-tied dummies. Its deltas
(Iq -19.8..-31.7 %, gain -3.6..+18.7 %, GBW +8.6..+27.8 %) are not what a
lumped-RC annotation can produce. The issue asked for the delta to be
attributed before choosing between putting the drawn fingering into the
schematic (option 1) and normalising the pex reference leg (option 2).

## Probe (batch fleet, append-only records)

`sim/fingering-probe/` measures a chain of DUTs with the committed
post-layout open-loop AC bench (`sim/post-layout/measure_openloop_ac.sh`,
CL = 2 pF [DR-1], 10 uA external ibias). It runs on the five MOS process
corners at 27 C / 1.20 V, each variant as two `klt sim` requests on the Spot
batch fleet (`environment.remote.job_id` in every envelope; listed in each
record). The chain is lumped -> drawn (`ng`/`m` form) -> expanded (one card
per finger + dummies) -> extracted with every R/C stripped -> extracted.

Record `20261015-081352-9a66a66` (committed bench), step deltas, min..max over
the corners:

| step | Av0 | GBW | PM | Iq |
|---|---:|---:|---:|---:|
| lumped -> drawn (representation) | +7.61..+7.87 % | +3.48..+4.47 % | -2.07..-1.70 % | **-26.71..-24.86 %** |
| drawn -> expanded (`ng`/`m` vs separate cards + dummies) | 0.00 % | -0.28..-0.26 % | -0.13..-0.12 % | 0.00 % |
| expanded -> extracted, R/C stripped (diffusion geometry) | 0.00 % | +0.01 % | +0.04..+0.05 % | 0.00 % |
| R/C stripped -> extracted (parasitics) | -2.87..+9.79 % | +17.75..+21.77 % | +0.17..+0.42 % | -0.01 % |

Record `20261015-083637-cefcca1` uses the same DUTs with `inn` AC-grounded by
1 F. This diagnoses the bench's loop break and is not a bench change:

| step | Av0 | GBW | PM | Iq |
|---|---:|---:|---:|---:|
| lumped -> drawn (representation) | +8.60..+8.97 % | +1.95..+2.57 % | -3.69..-3.16 % | -26.71..-24.86 % |
| drawn -> extracted, R/C stripped | 0.00 % | -0.39..-0.36 % | -0.17..-0.16 % | 0.00 % |
| R/C stripped -> extracted (parasitics) | 0.00 % | -0.41..-0.38 % | -0.84..-0.81 % | -0.01 % |
| drawn -> extracted (a reconciled pex delta) | 0.00 % | -0.81..-0.74 % | -1.01..-0.98 % | -0.01 % |

Findings:

1. **The hypothesis holds for the DC rows.** The representation step carries
   the whole Iq delta (about -25 %, mos_tt: 109.7 -> 81.5 uA) and most of the
   gain delta. The bias mirrors are set by fingers of different unit widths
   (Mbias/M5 2 x 1.1 um, M7 7 x 1.7 um), and the model sees narrow devices
   that the lumped schematic never simulated.
2. **`sg13_lv_*` treats `ng`/`m` the same as separate drawn instances.**
   Writing the drawn form as `w=<unit> ng=1 m=<units>` (pairs) and
   `w=<total> ng=<fingers> m=1` (folded) matches the per-finger expansion
   with dummies to within 0.4 % on every row, and 0.00 % on Av0 and Iq. The
   dummies and the model-computed vs extracted diffusion geometry are
   negligible. No `klt` mishandling of `ng`/`m` was found.
3. **The residual "parasitic" AC deltas are a bench artifact.** The committed
   open-loop bench leaves `inn` AC-floating (`Lbreak` with no C to ground).
   That makes Av0/GBW sensitive to any capacitance on `inn`, and roughly halves
   GBW (mos_tt lumped 5.49 vs 11.18 MHz) while overstating PM by 12-14 deg.
   With `inn` AC-grounded, the parasitics move GBW -0.4 %, PM -0.8 % and Av0
   0.00 %, a plausible lumped-RC size. This bench defect is outside #237's
   scope. It affects ratified item-5 evidence, so it is filed as **#241**.

## Decision

**Option 1: the schematic carries the drawn fingering.** Each transistor in
`design/opamp_core.sch` / `design/netlist/opamp_core.spice` is written as
drawn, with the same totals as today (no device is resized):

| device | today | as drawn |
|---|---|---|
| M1, M2 | `w=3.2u ng=1 m=1` | `w=1.6u ng=1 m=2` |
| M3, M4 | `w=1.04u ng=1 m=1` | `w=0.52u ng=1 m=2` |
| M5, Mbias | `w=2.2u ng=1 m=1` | `w=1.1u ng=1 m=2` |
| M7 | `w=11.9u ng=1 m=1` | `w=11.9u ng=7 m=1` |
| M6 | `w=33u ng=1 m=1` | `w=33u ng=12 m=1` |

This is exactly the probe's `drawn` variant
(`sim/fingering-probe/netlist-snapshots/20261015-081352-9a66a66/drawn.spice`).
The pex reference leg then instantiates the same per-device geometry as the
extracted leg (finding 2). `delta[]` becomes a parasitic measurement once the
bench is fixed (#241), and the pre-layout evidence describes the devices the
layout draws.

Rejected:

- **Option 2 alone** (finger-expanded pex reference only). It would isolate
  parasitics in `delta[]`, but items 5 and 8 would keep describing lumped devices
  that draw 25 % more Iq than the drawn circuit.
- **Redrawing the layout to match the lumped devices.** A single-finger
  33 um / 1.04 um M6 is not a drawable matched structure, and this reopens DRC/LVS.
  The probe gives no sign that the layout is wrong.

## Consequences

- The drawn circuit is a different operating point from the one sized in
  `design/opamp_sizing.md`. At mos_tt/27 C/1.20 V, Iq is 81.5 uA, not 109.7 uA, and
  Av0 is about 3.3 dB higher. Sizing is not changed by this record. If a re-run
  row no longer meets its ratified bound, that is reported and goes through
  `spec/`. The spec is not relaxed.
- Every pre-layout bench reads `design/netlist/opamp_core.spice`, so every
  item 5/8 number moves. The characterization report
  (`signoff/characterization/generate.py --check`, gated in CI) rejects any
  record whose simulated netlist is not the committed design netlist. **The
  netlist cannot change ahead of the re-runs without breaking the signoff
  gate**, so the netlist change and the re-runs land together.

## Sequencing

1. Done in the PR carrying this record: the probe and its two records, this
   decision, #241 and klayout-tools#3298 filed.
2. #241: fix the open-loop AC loop break (and the PSRR bench's identical
   construction) across the twin benches.
3. #237 remainder, as one change: edit `design/opamp_core.sch`, regenerate the
   netlist with `klt netlist` (`design/check_netlist_regen.py` must pass),
   teach `generate.verify_against_netlist()` and `lvs_reference.py` the
   `ng`/`m` form (the LVS reference expansion must stay 38/38), and re-run every
   moved pre-layout bench as new append-only records at PVT corners with
   the load stated. Most benches are still local `ngspice -b` grids
   (`sim/*/run_*.sh`). On a shared dispatch worker they must go through `klt sim`
   on the batch fleet, so this step depends on those benches having a
   `klt sim` form, or on a simulation host.
4. Re-run `bash layout/opamp_core/run_pex.sh` on the batch fleet. Item 7 is
   cited only if the new deltas are parasitic-scale (finding 3 predicts
   under 1 % on Av0/GBW/PM/Iq with a correct loop break).

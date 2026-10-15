# sim/fingering-probe

Issue [#237](https://github.com/2AMLogic/sg13g2-opamp/issues/237) device-representation
probe. It is a diagnostic, not a spec bench. It attributes the
schematic-vs-extracted deltas of the first post-layout run
(`layout/opamp_core/pex_report.json`, #86/#236) step by step. The question is
whether they come from parasitics or from the schematic leg simulating lumped
devices that the layout does not draw.

- `build_probe_netlists.py <out-dir>` writes the DUT netlists (stdlib + the
  `layout/` tables; device sizes, unit counts and finger counts come from
  `generate.PAIRS` / `generate.FOLDED` after `verify_against_netlist()`):

  | variant | what it is |
  |---|---|
  | `lumped` | `design/netlist/opamp_core.spice` byte-for-byte: one `ng=1 m=1` device per transistor (the #236 reference leg) |
  | `drawn` | the same nine instances written as drawn: matched pairs `w=<unit> ng=1 m=2` (interdigitated units, unshared diffusion), folded devices `w=<total> ng=<fingers> m=1` (shared S/D). The candidate option-1 schematic form. No dummies, no parasitics |
  | `expanded` | one `ng=1 m=1` card per drawn unit/finger, plus the rail-tied dummy columns (the option-2 finger-expanded reference). Model-computed AS/AD |
  | `extracted_nopar` | `layout/opamp_core/opamp_core_pex.spice` with every R and C card dropped and every `<net>__tN` star node collapsed onto its net. Same devices, extracted AS/AD/PS/PD |
  | `extracted` | `layout/opamp_core/opamp_core_pex.spice` byte-for-byte (the #236 extracted leg) |
  | `<v>_innac` | `<v>` (lumped, drawn, extracted_nopar, extracted) plus `Cprobe_inn_acgnd inn vss 1`: inn AC-grounded. This diagnoses the bench's loop break (`Lbreak inn out 1e18`, nothing else on inn), not the amplifier |

- `run_probe.sh` measures each variant with the committed post-layout open-loop
  AC bench (`sim/post-layout/measure_openloop_ac.sh`, CL = 2 pF [DR-1],
  10 uA external ibias, Iq = total Vdd current including ibias). It uses a reduced
  grid: the five MOS process corners at 27 C and VDD = 1.20 V. Each variant
  is two `klt sim` requests (AC + OP) on the batch fleet, and
  `environment.remote.job_id` of every envelope is copied into the record.
  The grid never runs locally. `PROBE_SET=innac` measures the four `_innac`
  variants.
- `summarize.py` joins the per-variant measurement documents into
  `records/<id>.json` and `records/<id>.md`. Its step deltas use the same
  percent-change definition as `klt pex` `delta[]`.

Layout (append-only, like every `sim/*/` bench): `netlist-snapshots/<id>/`
(the DUTs simulated), `corners/<id>/<variant>/` (requests, bench body, both
`klt sim` envelopes, stderr, measurement document) and `records/<id>.{json,md}`.

## Records

| record | set | result |
|---|---|---|
| `20261015-081352-9a66a66` | base | lumped -> drawn carries the whole Iq delta (-24.9..-26.7 %) and +7.6..+7.9 % Av0. Expansion and extracted diffusion move nothing (<0.3 %). The residual extracted_nopar -> extracted step (GBW +17.8..+21.8 %, Av0 -2.9..+9.8 %) is far too large for fF/ohm-scale parasitics |
| `20261015-083637-cefcca1` | innac | with inn AC-grounded, the parasitics step collapses to Av0 0.00 %, GBW -0.4 %, PM -0.8 %, Iq -0.01 %, and drawn -> extracted is under 1.1 % on every row. The base residual is a bench artifact: the floating inn roughly halves GBW (mos_tt lumped 5.49 vs 11.18 MHz) and overstates PM by 12-14 deg. Filed as #241 |

An earlier innac attempt (record id `20261015-082802-48d070c`) was killed by a
daemon restart before its first variant returned. It left only empty
envelopes and was never committed, so it is not evidence. It was discarded and
the set re-run as `20261015-083637-cefcca1`.

Conclusions and the design decision: `spec/decision-records/0008-drawn-fingering-device-representation.md`.

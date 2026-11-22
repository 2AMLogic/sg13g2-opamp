# 0012 — Typical passive models on the standing PVT grid

- **Status**: decided
- **Date**: 2026-11-22
- **Decided by**: Builder agent, issue #446

## Standing circuit benches

Pair each MOS section (`mos_tt`, `mos_ss`, `mos_ff`, `mos_sf`, `mos_fs`)
with `cornerCAP.lib cap_typ` and `cornerRES.lib res_typ` from the SG13G2
ngspice model directory (`libs.tech/ngspice/models/`). At the pinned PDK
release, `res_typ` sets the `rppd` sheet resistance to 260 Ω/□.
[SG13G2 v0.3.0 resistor sections](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/v0.3.0/ihp-sg13g2/libs.tech/ngspice/models/cornerRES.lib)

The five MOS sections, three temperatures (−40, 27, 125 °C) and three
supplies (1.08, 1.20, 1.32 V) still give 45 points. Single-point requests
use the same passive pair at nominal. The offset and CMRR mismatch benches
use plain `res_typ` and `cap_typ` in both the MOS mismatch run and its
plain-MOS negative control, where the expected spread across draws is zero.
The ratified rows retain their existing loads and limits.
[Target spec §§1–2](../target-spec.md)

SG13G2 already holds the Miller capacitor at `cap_typ` across the MOS grid.
GF180 pairs every MOS section with `res_typical` and `mimcap_typical`.
SKY130 loads `res_typical__cap_typical` at every MOS corner. Using typical
passives across all three benches keeps the routine results comparable.
Tying the lowest resistor value to fast MOS would assume the same direction
of worst-case sensitivity for every measurement. The separate sweep below
tests the independent combinations. [GF180 bench policy](https://github.com/2AMLogic/gf180-opamp/blob/4a5a11037a76c0473743e2a12c39471c1264c67c/sim/gain-gbw-pm/README.md)
· [SKY130 AC bench](https://github.com/2AMLogic/sky130-opamp/blob/a1c59575dfb692ac571568f7777628b72abed501/sim/opamp-characterization/testbench/opamp_ac.spice.tmpl#L47-L62)

## Verification when the first drawn resistor lands

The issue that first introduces a drawn resistor into `opamp_core`
(#430 or the #332/#342 topology work) must run a supplementary `klt sim`
sweep on that design. Run all nine combinations of
`{res_bcs, res_typ, res_wcs} × {cap_bcs, cap_typ, cap_wcs}` at nominal
(`mos_tt`, 27 °C, 1.20 V) and at each binding PVT corner for the affected
rows. Use the batch fleet with `--backend batch --wait-for-capacity 600`.
Record the load, MOS section, temperature, supply and both passive sections
with each measurement, and grade against the existing bounds. This follows
the GF180 compensation-resistor and capacitor study.
[GF180 DR-0003 §(d)](https://github.com/2AMLogic/gf180-opamp/blob/4a5a11037a76c0473743e2a12c39471c1264c67c/spec/decision-records/0003-target-spec-ratification.md)
· [GF180 issue #70](https://github.com/2AMLogic/gf180-opamp/issues/70)

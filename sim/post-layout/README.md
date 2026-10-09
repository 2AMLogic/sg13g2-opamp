# sim/post-layout

`klt pex --measure-command` target for T1 item 7 (issue #86). Not a new bench:
it reuses `sim/open-loop-ac/testbench/tb_openloop_ac.spice.tmpl` and
`sim/preflight.sh` (corner list, broken-simulation gate) over the same
45-point grid, and measures the DUT netlist it is handed (flat schematic, or a
`.SUBCKT` such as the extracted netlist).

- `measure_openloop_ac.sh <netlist>` -- prints the `{"corners": [...]}` document
  (`av0_db`, `gbw_hz`, `pm_deg`, `iq_a` per corner).
- `ac_metrics.py` -- AC post-processing shared by that script (same definitions
  as `sim/open-loop-ac/run_pvt_sweep.sh`).
- `check_bounds.py <pex_report.json>` -- grades extracted values against the
  ratified `spec/target-spec.md` Sec 2 bounds.
- `test_post_layout.py` -- offline checks (no ngspice/PDK).
- Driver: `layout/opamp_core/run_pex.sh`.

Under `KLT_SIM_BACKEND=batch` the measure script refuses a multi-point local
grid (exit 2); `SG13G2_PEX_POINTS=corner:temp:vdd` runs a single debug point.

## Status (issue #86)

The 45-corner run has NOT been done: `klt pex --measure-command` runs the
command locally once per leg (90 ngspice runs), and there is no way to route
that grid to the batch fleet (2AMLogic/klayout-tools#2962). No
`layout/opamp_core/pex_report.json` is committed and item 7 stays uncited.
Run `bash layout/opamp_core/run_pex.sh` on a host without
`KLT_SIM_BACKEND=batch`, then `python3 sim/post-layout/check_bounds.py
layout/opamp_core/pex_report.json`.

One-point debug probe (`mos_tt:27:1.20`, run on this host, not committed):
extraction succeeded (38 devices, 9 nets, `body_bias.status` = `biased`) and
both legs simulated, but schematic vs extracted differ materially (DC gain
41.95 -> 49.68 dB, GBW 5.48 -> 6.90 MHz, PM 77.8 -> 76.6 deg, Iq 109.7 ->
81.5 uA). All four stay inside the ratified bounds at that point, but the Iq
and gain shift is large for a lumped-RC model and should be understood when
the full grid is run.

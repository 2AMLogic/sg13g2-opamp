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

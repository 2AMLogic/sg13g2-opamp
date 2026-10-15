# sim/post-layout

`klt pex --measure-command` target for T1 item 7 (issue #86). Not a new bench:
`klt/` holds the committed open-loop AC bench as `klt sim` requests (circuit
body, AC request, OP request; the same files as the issue-#85 `sim/open-loop-ac`
klt path, over the same ratified 45-point grid, CL = 2 pF), and the measure
script runs them against whatever DUT netlist `klt pex` hands it (flat
schematic, or the extracted `.SUBCKT`, instantiated as `Xdut` with pins matched
by name).

- `measure_openloop_ac.sh <netlist>` -- prints the `{"corners": [...]}` document
  (`av0_db`, `gbw_hz`, `pm_deg`, `iq_a` per corner). It never launches ngspice:
  the 45 corners are `klt sim` requests that go to the Spot batch fleet
  (`"backend": "batch"` in the requests). A failed batch submit is a hard
  failure, never a local fallback.
- `klt_measure.py` -- builds the per-DUT requests and converts the two
  envelopes (AC + OP; `klt sim` runs one analysis per corner) into the
  measurement document, refusing any non-gradable corner.
- `check_bounds.py <pex_report.json>` -- grades extracted values against the
  ratified `spec/target-spec.md` Sec 2 bounds.
- `test_post_layout.py` -- offline checks (no ngspice/PDK/klt).
- Driver: `layout/opamp_core/run_pex.sh`.

Measurement method: Av0 = `vdb(out)` at 1 Hz, GBW = ngspice `.meas ... when
vdb(out)=0` (linear-in-frequency interpolation between `dec 20` sweep points,
so it reads slightly different from the log-interpolated GBW of
`sim/open-loop-ac/run_pvt_sweep.sh`; identical on both legs, so the pex delta is
unaffected), PM = 180 deg + phase at that crossing, Iq = total `-i(vdd)` at the
OP including the external 10 uA ibias.

## Status (issue #86)

The 45-corner run was done: `bash layout/opamp_core/run_pex.sh` wrote
`layout/opamp_core/pex_report.json` (180 `delta[]` rows, all pass) and
`layout/opamp_core/opamp_core_pex.spice`. `check_bounds.py` grades all four
extracted rows PASS against the ratified bounds. **The run is not cited for T1
item 7.** The schematic leg simulates lumped `ng=1` devices, while the
extracted leg simulates the drawn unit/finger devices, plus dummies. The
legs are therefore not comparable, and the large gain, GBW and Iq deltas cannot
be attributed to parasitics. The #237 probe (`sim/fingering-probe/`) has
since quantified this. The representation difference carries the Iq delta
(about -25 %) and most of the gain delta. The remaining AC deltas come from
this bench leaving `inn` AC-floating (`Lbreak` with no C to ground; #241):
with `inn` AC-grounded, the parasitics move GBW -0.4 % and PM -0.8 %. See
`spec/decision-records/0008-drawn-fingering-device-representation.md` and
`signoff/README.md` (item 7).

The requests declare `backend: "batch"`. The report records no
`environment.remote` or job id, and the per-corner `klt sim` envelopes went to
a scratch directory that was not kept, so nothing committed proves where the
simulations ran beyond that declaration. A future run should keep the `klt
sim` envelopes, or their `environment.remote` job ids, with the report.

History: earlier attempts were rejected by the fleet with
`batch_runner_version_mismatch` (runner klt 0.5.0 vs client 0.7.x;
2AMLogic/2am#2193). Once that cleared, the first run failed in this harness with
klt's `outdir_locked`: `klt pex` locks the tree holding `KLT_PEX_ARTIFACTS_DIR`,
and `klt sim` defaulted its `.klt/sim` output next to the request inside it.
`measure_openloop_ac.sh` now passes `-o` to a scratch directory outside that
tree.

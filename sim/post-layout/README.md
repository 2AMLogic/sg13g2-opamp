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

The 45-corner run has NOT been done, and no `layout/opamp_core/pex_report.json`
exists, so item 7 stays uncited (`unmet / no_evidence`). The batch submit is
rejected before any simulation:

    batch_runner_version_mismatch: the fleet runner runs klt 0.5.0 but the
    submitting client is 0.7.0+g4cbdfa769875 -- the request was not run

(`klt sim --backend batch` and the full `bash layout/opamp_core/run_pex.sh`
both reproduce it; `uvx --from klayout-tools==0.5.0` cannot be used instead,
that release has no `batch` backend.) The same runner mismatch is
2AMLogic/2am#2193. The local fallback is also unavailable on the authoring
host (ngspice-42 cannot load the OSDI models; `sim/tools/build-osdi.sh
--check` fails), and the shared-host rule forbids it for a grid anyway. An
earlier note here recorded a one-point local probe (gain 41.95 -> 49.68 dB
etc.); it could not be reproduced on this host and is withdrawn as evidence.

What does work end to end on this host: `klt pex` extraction of the committed
GDS (deck `sg13g2`, bound to the PDK models; 489-line `.SUBCKT opamp_core`
netlist), the schematic-side request build, and the batch submit up to the
runner rejection. Re-run `bash layout/opamp_core/run_pex.sh`, then
`python3 sim/post-layout/check_bounds.py layout/opamp_core/pex_report.json`,
once the fleet runner matches the client.

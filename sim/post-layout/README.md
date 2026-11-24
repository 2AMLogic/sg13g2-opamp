# sim/post-layout

`klt pex --measure-command` target for T1 item 7 (issue #86). Not a new bench:
the committed open-loop AC bench as `klt sim` requests (circuit body, AC
request, OP request) is read from `../open-loop-ac/klt/`, the single source for
both the pre- and post-layout legs (issue #85 path), over the same ratified 45-point grid, CL = 2 pF), and the measure
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
- `rz_candidate.py` -- builds the `klt sim` legs of a drawn-candidate record
  (`bench`: the committed benches, with DR-0012's nine passive sections;
  `control`: diagnostic controls; `bracket`: DR-0013's extracted-leg slew
  brackets -- body-on-hub and schematic, grid plus nine sections each) and
  grades a directory of envelopes.
- `rz_solver.py` -- builds the `klt sim` legs of the issue #451 solver
  investigation (star surgery, body-resistance ladder, solver-option ladder,
  the model-alone probe, and three 45-corner grids) from the #430 candidate;
  `grade` is `rz_candidate.py`'s.
- `cc-sizing-430/`, `rz-nulling-430/`, `rz-layout-430/` -- the append-only
  issue #430 records: the capacitor-sizing trial, the ideal-resistor
  screening, and the drawn resistor's extraction and corner grids.
- `rz-trim-430/` -- the append-only issue #430 record closing the sizing:
  the 24.3 µm trim of the drawn candidate clears DR-0012's `cap_wcs`
  falling-slew bound (7.6352 V/µs schematic, bracket 7.5846) while every AC
  bound holds (worst passive section 61.6649°), with the extracted-leg slew
  rows ungraded-with-bracket per DR-0013.
- `rz-solver-451/` -- the append-only issue #451 record: the extracted-leg
  slew abort named (the `rppd` body terminal's star leaf; Newton
  non-convergence), its controls and grids. Decision: DR-0013.
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
this bench leaving `inn` AC-floating (`Lbreak` with no C to ground; fixed
by #241, `Cinn_acgnd inn vss 1` in `sim/open-loop-ac/klt/tb_openloop_ac.body.spice`; the
`pex_report.json` of #236 predates the fix and is superseded):
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

## Verifying a committed envelope's deck (issue #460)

A `klt sim` envelope records `provenance.input.content_hash` (the same value
as `environment.netlist_sha256`): the SHA-256 of the deck it ran. For these
benches that deck is the committed bench body with its one DUT `.include`
re-pointed by `klt_measure.dut_lines` -- at the DUT's **absolute** path. The
hash therefore reproduces only from the checkout that built the deck, and a
mismatch reads exactly like tampering.

- `environment.netlist_closure` lists the deck's SHA-256 first, then the
  SHA-256 of each included file as klt staged it. For these benches that is
  the DUT, and it is path-free: compare `sha256sum <dut>` with the entry
  after the deck's to prove which DUT bytes ran.
- `klt_measure.build` and `rz_screen.slew_build` report
  `deck_content_sha256`: the deck's SHA-256 with the DUT include line replaced
  by `.include "<DUT:<SHA-256 of the DUT>>"`. It is a function of the bench
  and the DUT bytes alone -- equal from any checkout and any artifacts
  directory, different when either changes. Record it next to
  `netlist_sha256` with a new leg. A leg that rewrites the deck after the
  build (`rz_candidate.py`'s `gear` legs, `rz_solver.py`'s `options` legs)
  has to hash the final deck instead;
  from the repository root, with the DUT passed exactly as the deck's include
  line carries it (absolute):

      python3 -c 'import sys; sys.path.insert(0, "sim/post-layout"); \
        import klt_measure as km; \
        print(km.deck_content_sha256(open(sys.argv[1]).read(), sys.argv[2]))' \
        <deck.body.spice> "$PWD/<dut>"

  Today's generators, at `edd2a0f`, built from
  `rz-layout-430/candidate/opamp_core_pex.spice`, give
  `091ec7819d36df81b542954a1d8106ccf97df0be14025da18dc15a83b24f91a4` for the
  committed open-loop bench and
  `62601233d11f93d980ee10b976e1fdeca5cebfdc5f8090173ac4b29c0e3f4245` for the
  committed slew bench: what they build now, not what an earlier leg ran.
- No envelope under `rz-layout-430/` records a `deck_content_sha256`. The only
  way to check one against its `content_hash` is to regenerate the deck,
  substitute the author's absolute DUT path for yours, and compare. The
  envelope does not record that path. Measured on `rz-layout-430/records/`
  at `edd2a0f`: neither of its two decks (AC `630f231c...`, slew
  `36493e6b...`) regenerates to the committed hash from another checkout,
  and 42 plausible author paths reproduce neither.
- A leg whose DUT was written to a scratch directory stays unverifiable by
  that route even given the author's checkout root, because its include
  points into a directory the caller chose. Eleven envelopes under
  `rz-layout-430/controls/` are of this kind (`ctl_ideal_ss_slew`,
  `ctl_bodyhub_ss_res_typ_cap_typ_slew`, the nine `ctl_swet1_*`): their DUTs
  match no committed file, though `rz_candidate.py control` regenerates each
  byte-for-byte from the committed extraction, as their `netlist_closure`
  hashes confirm.

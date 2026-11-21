# Attribution: klt 0.9.0 post-layout phase-margin miss and TT non-convergence (issue #429)

Investigation of the two post-layout results that park #312: the phase-margin
fail at `mos_ff / vdd=1.32 / vinp=0.66 / 125 C` on the klt 0.9.0 extraction
(margin -0.0033 rad against the `min: -2.0944 rad` limit of
`sim/open-loop-ac/klt/openloop_ac.request.json`), and the inconclusive
`mos_tt / vdd=1.08 / vinp=0.54 / 27 C` corner ("Dynamic gmin stepping failed",
`nonconvergence` listed in `options.fail_on_diagnostic`).

**Verdict up front.**

1. **FF compensation margin is routed to #430.** With the same drawn devices
   and extracted capacitors, PM is 59.7844° with the star resistors collapsed
   and 59.8136° with their extracted values. Both endpoints miss 60°.
   #312 is parked `Blocked by: #430`.
2. **The cause of TT gmin failure remains open.** The 1 TΩ substrate-tie
   control is inconclusive on the fleet. A local trace shows recovery by
   source stepping. The 1 MΩ and 1 GΩ batch outcomes are unverified (Step 4).

## Inputs and reproduction pins

| Input | Value |
|---|---|
| Opamp source | `36596fcda50e5998a5088c56c7c9032a15a0b61b` (`feature/issue-312`) |
| GDS SHA-256 | `ab2d926e1974e4e04f0c0363af5139b64034f544e4fdc192df3dd7a79830aa05` |
| Baseline netlist (0.7.1, 38 devices) | `03db91a88151fadba6109cc93a950d6c22b11356bbd74c8b74142699975329f2` (same Git blob `6cfc7ad0…` on main and the branch) |
| Regenerated 0.9.0 netlist (32 devices) | `80cd19a17ee5d7e008efb662e322147e556598993f0d73c9ca16ba532019f1ea` (reproduced this run, matches the Curator's reproduction) |
| Extraction tools | `klayout-tools==0.9.0` (commit `5dbbad05ff42265c92a6f3d2f20d1bbcd2957d49`), `klayout==0.30.12` |
| PDK | IHP-Open-PDK `v0.3.0`, variant `ihp-sg13g2`, `PDK_ROOT=/home/ubuntu/share/pdk` |
| Sim runner | `klt sim` 0.9.0 via the batch fleet; runner engine ngspice-47 (recorded in every envelope) |

The two extractions' **real device cards are identical** after terminal-node
normalization (31 MOS units + the `cap_cmim` Miller device; verified by
multiset diff). The netlists differ only in (a) the six `*_dummy` devices,
(b) the parasitic values below, (c) device instance coordinates (GDS regen).

Net-name map (both extractions): `$3` = tail, `$5` = d1 (M1/M3 side),
`$6` = d2 (M2/M4 drain, M6 gate, Miller-cap plate), pins as named.

## Step 1 — schematic legs (committed evidence)

Same generator (`sim/post-layout/klt_measure.py` @ `36596fc`), same committed
bench (`sim/open-loop-ac/klt/tb_openloop_ac.body.spice`), one corner per
invocation, batch backend with `capacity_wait_s=600`. The bench, requests and
DUT blobs are byte-identical between `36596fc` and this branch's base
`1ae310e` (verified by `git diff --stat`), so the record ids cite `1ae310e`.

| record | corner | status | phase_at_ugf_rad | margin | PM | job (ac / op) |
|---|---|---|---|---|---|---|
| `records/20261120-205258-1ae310e` | mos_ff/1.32V/125C | pass | -2.059712309425 | +0.034683 rad | 61.9872° | `klt-sim-0d8650ae20cc` / `klt-sim-b5b910ababa3` |
| `records/20261120-205456-1ae310e` | mos_tt/1.08V/27C | pass | -1.972878688341 | +0.121516 rad | 66.9624° | `klt-sim-948a3ba54f78` / `klt-sim-381f5f5d9e9e` |

Both match the corrected AC-grounded schematic record of 2026-10-15
(61.9872° / 66.9624°) and the historical klt 0.7.0 cross-checks
(+0.03468 / +0.12152 rad).

## Step 2 — per-net parasitic comparison, 0.7.1 baseline vs 0.9.0 regen

Lumped (star-summed) resistance per net and net-to-vsubs capacitance:

| net | R 0.7.1 (Ω) | R 0.9.0 (Ω) | C 0.7.1 (fF) | C 0.9.0 (fF) |
|---|---|---|---|---|
| `$3` tail | 13.8596 | 13.8596 | 5.059199 | 5.059199 |
| `$5` d1 | 19.7225 | 19.7225 | 7.017582 | 7.015709 |
| `$6` d2 | 26.0923 | 26.1374 | 10.08496 | 10.234443 |
| ibias | 16.9719 | 16.9719 | 5.960358 | 5.960358 |
| inn | 4.7103 | 4.7103 | 1.635448 | 1.635448 |
| inp | 5.5024 | 5.5024 | 1.89146 | 1.89146 |
| out | 24.0739 | 24.0959 | 16.414749 | 16.582416 |
| vdd | 46.4258 | 46.6456 | 20.240201 | 20.335716 |
| vss | 53.3204 | 53.3204 | 23.53043 | 23.53043 |

Coupling terms: all identical except `Ccc__6_out` (the Miller-cap plate pair):
0.999487 fF → 0.042025 fF (vertical-overlap accounting around the drawn MIM
device changed between versions). Every other `Ccc__*` is byte-identical.

**What dropping the dummies changed:** the six dummies (2× nfet W=1.1/L=0.52,
2× nfet W=1.6/L=0.13, 2× pfet W=0.52/L=0.52) tie all four terminals to
vdd/vss. Their removal deleted 8 star-R terminals from vdd and 16 from vss
(net R still +0.22 Ω / +0 Ω) and moved `Cvdd` +0.0955 fF. Nothing on the
signal path.

**Magnitude check:** the compensation/output path changed by at most
+0.15 fF on d2 and +0.17 fF on out (≈1.5%/1% of those nets' 10–16 fF) and
-0.96 fF of d2–out coupling — against a 994.847 fF Miller device. These
deltas cannot move phase margin by degrees.

## Step 2 (cont.) — controlled legs: representation vs parasitics

Five legs on the identical bench and request form (one corner per request,
batch fleet, runner klt 0.9.0). Leg B is the 0.9.0 netlist with every `R`/`C`
parasitic card removed and terminal nodes `<net>__tN` collapsed onto the hub
net (device cards, geometry terms `AS/AD/PS/PD` and the MIM device untouched).

**FF / 1.32 V / 125 C (the failing corner):**

| leg | phase_at_ugf_rad | margin | PM | av0 (dB) | GBW (MHz) | job |
|---|---|---|---|---|---|---|
| A schematic lumped `ng=1` | -2.059712309425 | +0.034683 | 61.9872° | 42.2614 | 10.673 | `klt-sim-0d8650ae20cc` |
| B drawn fingers, no parasitics | -2.088332597777 | +0.006063 | 60.3474° | 45.7971 | 10.945 | `klt-sim-52d304323333` |
| C drawn + 0.9.0 parasitics | -2.097648803209 | **-0.003254** | 59.8136° | 45.7979 | 10.908 | `klt-sim-3e33c106fc7d` |
| D drawn + 0.7.1 parasitics (committed 38-dev netlist) | -2.097323701316 | **-0.002929** | 59.8322° | 45.7980 | 10.900 | `klt-sim-3b1905a88ea0` |
| E drawn + 0.9.0 capacitors, all star R collapsed (resistance-only control) | -2.098158563064 | **-0.003763** | 59.7844° | 45.7971 | 10.910 | `klt-sim-825253be86cb` |

PM is `180 + degrees(phase_at_ugf_rad)` (the repository formula in
`sim/post-layout/klt_measure.py`), recomputed from the recorded radians. All
deltas below are **later leg minus earlier leg** (negative = margin lost).
Margins are `phase_at_ugf_rad + 2.0943951` (limit `-2*pi/3`).

Decomposition of the 2.17° schematic→extracted drop:

- **Device representation (B minus A): -1.6398°.** The dominant term. The #237
  confound (lumped `ng=1` vs drawn unit/finger devices) is what the schematic
  leg under-models; it also carries most of the av0 shift (+3.54 dB) seen in
  the committed 0.7.1-era deltas.
- **Parasitics (C minus B): -0.5338°.** With the drawn devices held fixed,
  the extracted capacitors alone lower PM by 0.5630° (E minus B). Adding the
  extracted star resistors raises it by 0.0292° (C minus E). The comparison
  measures only the collapsed and full-star endpoints. PM at intermediate
  resistances or with a different resistor network is unmeasured.
- **Complete netlists (C minus D, new minus old): -0.0186°.** This comparison
  includes the GDS revision and dummy removal as well as the extractor change.
  The committed 0.7.1 netlist misses
  the same bound on the corrected bench. The committed `pex_report.json`
  "pass" at this corner (extracted 75.19° vs schematic 76.36°) graded the
  superseded floating-inn bench (issue #241); on the corrected AC-grounded
  bench both extractions read ≈59.8°, i.e. the miss appeared when the bench
  was corrected, not when the extractor moved.

**TT / 1.08 V / 27 C:**

| leg | status | phase_at_ugf_rad | margin | PM | job (ac) |
|---|---|---|---|---|---|
| A schematic lumped | pass | -1.972878688341 | +0.121516 | 66.9624° | `klt-sim-948a3ba54f78` |
| B drawn, no parasitics | pass | -2.015401739781 | +0.078993 | 64.5260° | `klt-sim-4b783bcd1672` |
| C drawn + 0.9.0 parasitics | **inconclusive** | -2.024018434830 | +0.070377 | 64.0323° | `klt-sim-6f36c264add6` |
| D drawn + 0.7.1 parasitics | pass | -2.023699145293 | +0.070696 | 64.0506° | `klt-sim-be93d0cd9ad7` |
| E 0.9.0 capacitors only, star R collapsed | pass | -2.024498960725 | +0.069896 | 64.0048° | `klt-sim-f1718f9e56dc` |

Leg C reproduces the historical grid (`klt-sim-89ae2e1c2ed4`) exactly:
margin -0.0033 rad at FF, +0.07 rad at TT, same diagnostic. Representation at
TT is -2.4364° (B minus A), parasitics -0.4937° (C minus B; capacitors -0.5212°,
resistors +0.0275°) — the same story as FF.

## Step 3 — routing

The FF miss persists with the extracted capacitance alone, which supports
routing the compensation margin to design. The 0.9.0 `--resistance-graph`
report classifies all nine nets as `legacy`, including d2 (26.1374 Ω) and out
(24.0959 Ω). Legs C and E therefore leave the physical path resistances in
2AMLogic/klayout-tools#5894 unvalidated. **#430** carries the attribution
numbers and states its relation to #332/#342 (their new topology keeps the
two-stage Miller path, and #342's ruling already requires PM to stay
competitive on whatever lands, so the compensation re-derivation must absorb
these numbers or sequence behind an interim fix — not be built twice).
#312 is parked `Blocked by: #430`.

## Step 4 — TT / 1.08 V / 27 C convergence investigation

**Mechanism: ngspice DC-homotopy failure; trigger not isolated.** Evidence:

- Local single-corner probe of leg C with `keep_artifacts` (ngspice-47 log):
  `dynamic gmin stepping` fails, `true gmin stepping` fails, **`source
  stepping` completes**, and the AC measurements match the fleet envelope to
  12 digits (ngspice deterministic).
- The found operating point is well-regulated: `vout_dc_v` = 0.5399 V
  (= VDD/2 within 84 µV, OP job `klt-sim-e84f79fd991d`), `ivdd_total_a`
  78.88 µA — consistent with legs B (0.53991 V) and D (0.53991 V).
- **Body connectivity and the final operating point are fine, but neither
  identifies why gmin stepping failed.** The envelope reports
  `body_bias.status = biased`, zero unbiased devices, and the recovered
  `vout` is regulated. Yet `vsubs` has exactly one DC connection,
  `Rvsubs_dctie vsubs 0 1e12` (line 424 of the netlist); its other nine
  connections are capacitors. A node with a 1e12 ohm DC path is the kind
  gmin homotopy can struggle with, so a weakly-tied `vsubs` remains a live
  explanation. The source-stepping trace above is from a **local** probe, not
  the batch fleet.
- Legs B, D and E pass on the same bench at TT. Collapsing the star
  resistors in E changes the network at many nodes at once, so this comparison
  cannot identify the node that triggered the warning in C.

**Substrate-tie control.** The two batch probes vary only `Rvsubs_dctie` in
leg C at TT / 1.08 V / 27 °C. All three requests grade `nonconvergence` under
`options.fail_on_diagnostic`.

| Tie to ground | Batch job | Corner status | gmin diagnostic |
|---|---|---|---|
| 1 TΩ (leg C) | `klt-sim-6f36c264add6` | inconclusive | `nonconvergence` warning: `Dynamic gmin stepping failed` |
| 1 MΩ | `klt-sim-dbec6a890e20` | unverified | unavailable |
| 1 GΩ | `klt-sim-cc7d8db86c3e` | unverified | unavailable |

On 2026-11-21, the pinned klt 0.9.0 client's `--job-status` lookup for
each probe reported that the `batch-runner-submit` profile was unavailable.
`--attach` returned `batch_unknown_job` in that same environment. Neither
read establishes the current fleet state. The last reported queue observation
was `pending` about 40 minutes after submission.

A completed solve that clears the warning at a stronger tie would show
sensitivity to that tie at this corner. If both probes reproduce the warning,
neither tested tie value is a sufficient remedy. Other weak nodes and their
effect on the solver trajectory would remain open. The trigger and its
disposition under #429 step 4 are unresolved. Upstream
[klayout-tools#6955](https://github.com/2AMLogic/klayout-tools/issues/6955)
tracks the missing recovery information in the diagnostic envelope.

## Step 5 — handoff to #312

Summary posted on #312; its open "needs a decision" park was replaced by a
`Blocked by: #430` park record. No bound, corner list, `layout/klt-pin.txt`
pin or diagnostic option changed anywhere in this investigation (verified by
diff against the branch base).

## What was ruled out

- A miss unique to the new extraction. Both complete FF netlists miss 60°
  (C minus D, new minus old, is -0.0186°).
- A requirement for the star resistors to produce the FF miss. Collapsing
  them leaves leg E at 59.7844°.
- Dummy removal touching the signal path (rails only).
- Unbiased device bodies at TT (body_bias biased). A weakly-tied `vsubs` is NOT ruled out; see the Step 4 probe.
- The common bench alone as a sufficient trigger at TT (legs B, D and E pass).
- A discrepancy in the measured phase between the local and fleet leg C runs.

## Reproduction appendix

Schematic legs and controlled legs: `SG13G2_PEX_POINTS=<corner>
KLT_PEX_SIM_BACKEND=batch python3 sim/post-layout/klt_measure.py build
<dut> <dir>` with `klt_measure.py`, bench and requests taken from `36596fc`
(blobs identical to this branch's base), then `klt sim <dir>/openloop_ac.request.json
--format json` with `klayout-tools==0.9.0`. Leg B's DUT is the regenerated
netlist minus `R`/`C` cards with `<net>__tN` collapsed to `<net>`.
Extraction: the pinned recipe in issue #429's Curator Enhancement (verified
this run: `klt pex … --extract-only` exits 4 with `status=not_checked`, and
the three SHA-256s above reproduce).

To collect the two Step 4 envelopes on a batch-enabled host, start with the
verified 0.9.0 `opamp_core_pex.spice` in a scratch directory. Set `generator`
to the absolute path of `sim/post-layout/klt_measure.py` in the `36596fc`
checkout. The final command attaches to the existing job ID. A report with an
inconclusive corner can have a nonzero exit code.

```bash
for entry in 1e6:klt-sim-dbec6a890e20 1e9:klt-sim-cc7d8db86c3e; do
    tie=${entry%%:*}
    job=${entry#*:}
    sed "s/^Rvsubs_dctie vsubs 0 1e+12$/Rvsubs_dctie vsubs 0 $tie/" \
        opamp_core_pex.spice > "$tie.spice"
    SG13G2_PEX_POINTS=mos_tt:27:1.08 KLT_PEX_SIM_BACKEND=batch \
        python3 "$generator" build "$tie.spice" "$tie" || exit 1
    rc=0
    klt sim "$tie/openloop_ac.request.json" --backend batch --attach "$job" \
        --format json > "$tie/result.json" || rc=$?
    echo "$tie ohm, $job, klt exit $rc"
done
```

For each envelope, verify `environment.remote.job_id`, then record the single
TT corner's `status` and any `diagnostics[]` entry for `nonconvergence`.

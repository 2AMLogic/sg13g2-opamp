# Issue #451 — the extracted-leg slew abort, named: the `rppd` body terminal's star leaf

**The committed slew bench aborts on the #430 extraction because the klt
0.9.0 star extraction puts the PDK resistor card's *body* terminal on its
own parasitic leaf, and ngspice-47's Newton iteration then fails on this
amplifier's bias network — not because of any tolerance, option or
layout-parasitic magnitude.** Merging that one leaf onto the rail hub —
changing nothing else — runs the binding corner and all 45 corners of the
grid cleanly; the failure survives body-star resistances from 1 mΩ to
6 MΩ, so it is the extra node, not the ohms. The failure is a Newton
non-convergence (the fatal timestep cut is iteration-limited: `itl4=100`
aborts at the identical timepoint, `itl4=500` converges past it and dies
later after 500 iterations; a local-truncation-error cut never consults
`itl4`), which settles issue #451's open question 1. DR-0005's default
solver settings stand: no tolerance or option change cures the abort
(`reltol` 1e-4/1e-2, `itl4`, `gmin`, `trtol`, `chgtol`, `abstol`,
`method=gear` — #430 §5 — and `.options interp` on/off all leave the
bench aborted or merely move the abort), so the decision this record
carries is [DR-0013](../../../spec/decision-records/0013-extracted-resistor-body-star-solver-abort.md):
the bench gains no options, and the extracted-leg slew row of a design
whose PDK resistor body sits on a star leaf stays **ungraded on the
committed bench** until the extractor-side change lands — bracketed below
by the body-on-hub control grid (45/45) and the schematic grid (45/45).

Every leg here is a **control** built by `../rz_solver.py controls` from
the #430 candidate netlists (`../rz-layout-430/candidate/`), run through
`klt sim` 0.9.3.dev on the batch fleet against the fleet's pinned runner
(klt 0.9.0, ngspice-47 KLU, `capacity_wait_s = 600` on every request;
singles as one `--batch-set --capacity-retries 3`, grids as
`--submit-only` + `--attach`). None of them is the committed bench and
none of them supports a bound. The #430 record and its controls
(`../rz-layout-430/`) are read-only evidence this builds on.

## 1. The abort is deterministic per deck (issue #451 AC-1)

| check | outcome |
|---|---|
| `c451_ss_slew` (the committed bench, extraction, `mos_ss / 1.08 V / −40 °C`), local `--backend local`, 10 runs | 10 × error, byte-identical: `time = 5.07812e-12 s`, `timestep = 6.25e-23 s`, node `xdut.ibias__t12` |
| same leg on the fleet, #430's submission (job `klt-sim-d5b717b82ba5`) and this record's (job `klt-sim-9e4ad711a8d9`) | identical to every printed digit — local and fleet engines agree |
| the 45-corner grid, #430's submission (`klt-sim-aa4d9ece076e`) vs this record's rerun (`klt-sim-c88dacfe26d5`) | **all 45 corner outcomes identical** (same 8 pass), and the abort time *and* named node identical on every one of the 37 error corners |

So the abort is fully deterministic per deck on this engine family, and
reproduces "deterministically enough to test against": one command, one
answer. What *is* a lottery is the pass/fail pattern **across decks**:
which corners pass does not follow corner physics — the 8 that pass under
the default trapezoidal method and the 9 under `method=gear` (#430,
`klt-sim-982291a18712`) are not the same set, and the 8 passing corners
here are the same 8 as #430's submission. Pass rates with sample sizes:
**8/45 twice** on the committed bench (this record plus #430), 9/45 under
`method=gear`, 1 pass in 9 passive sections per submission (#430 §5).
The `.options noopiter` leg below shows why: a run that skips Newton
iteration entirely passes with the correct slew to 6 digits — the solve
sits on a numerical edge that tiny differences in the numeric trajectory
(corner parameters, integration method) tip either way.

## 2. The trigger, isolated by star surgery (issue #451 open question 3)

All legs at `mos_ss / 1.08 V / −40 °C`, committed bench, one thing changed
at a time. "Star surgery" = merging star leaf nodes onto their net hub
(the leaf's star resistor dropped, references renamed); the builder is
loud and refuses a leaf that is not one (`../rz_solver.py`,
`merge_leaves`). Rising/falling slew in V/µs for the passes.

| leg | change | verdict | values | job |
|---|---|---|---|---|
| `c451_ss_slew` | nothing (the repro) | **error** `t=5.07812e-12`, `xdut.ibias__t12` | — | `klt-sim-9e4ad711a8d9` |
| `c451_merge23_ss_slew` | merge **only** `vss__t23` (the `rppd` card's body leaf) onto the vss hub | **pass** | 8.1003 / 7.6881 | `klt-sim-679ea37c9a98` |
| `c451_bodyleaf_only_ss_slew` | merge **every** star leaf (152) *except* `vss__t23` | **pass** | 8.1003 / 7.6881 | `klt-sim-3a07214796a7` |
| `c451_vss_rest_merged_ss_slew` | keep `vss__t23`; merge the other 42 vss leaves | **pass** | 8.1001 / 7.6880 | `klt-sim-9340b9338d1e` |
| `c451_keep23t0_ss_slew` | keep `vss__t23` + one more vss leaf (`vss__t0`, of `X$1`); merge the other 41 | **error** `t=8.73622e-10`, `xdut.ibias__t12` | — | `klt-sim-c543cc23536e` |
| `c451_bodyR1m_ss_slew` | `Rvss_t23`: 6.06 Ω → 1e-3 Ω | **error** `t=1.15723e-11`, `xdut.ibias__t12` | — | `klt-sim-2576fc7a1f50` |
| `c451_bodyR6meg_ss_slew` | `Rvss_t23`: 6.06 Ω → 6.06e6 Ω | **error** `t=5.30273e-12`, `xdut.ibias__t12` | — | `klt-sim-a2ef5fab7763` |
| `c451_bodyhub_ss_slew` | the card's body terminal moved onto the vss hub (#430's `bodyhub` edit) | **pass** | 8.1003 / 7.6881 | `klt-sim-8fe4e5d9d99d` |
| `c451_sch_bodyR_ss_slew` | the **schematic** netlist, `rppd` body behind the same 6.06 Ω | **pass** | 7.7626 / 7.7401 | `klt-sim-e4e1e7637ef8` |
| `c451_probe_r_bodyR` | the `rppd` model alone in a transient, body behind 6.06 Ω | **pass** | 8.6974e-9 s (10–90 %) | `klt-sim-63e3667aa8e6` |
| #430 `ctl_ideal_ss_slew` | extraction, card swapped for an ideal 2000.6 Ω | pass | 8.1009 / 7.6888 | `klt-sim-c6f7a52627da` |
| #430 `ctl_sch_ss_slew` | schematic netlist with its `rppd` card (body on the port rail) | pass | 7.7626 / 7.7401 | `klt-sim-9544ea96c7b5` |

Readings, each with the legs that support it:

- **The named factor is the `rppd` card's body leaf.** Merging only that
  leaf cures the corner; merging 152 other leaves (all but it) leaves a
  passing deck, so no other single leaf is the trigger; keeping that leaf
  plus just one companion vss leaf fails again. The body leaf is
  necessary, and the star must be multi-node for it to bite.
- **It is the extra node, not the resistance.** 1 mΩ through 6 MΩ — six
  decades of body-star resistance — all abort, naming the same
  `ibias`-family node. No RC time-constant story spans that range; what
  the deck loses at every value is the *identity* of the body node with
  the rail.
- **The extractor's star is a necessary accomplice, not the model or the
  bench alone.** The model by itself with its body behind the same 6.06 Ω
  runs (`c451_probe_r_bodyR`, and #430's `probe_r_*`); the schematic
  netlist — no star network at all — with the body equally isolated runs
  (`c451_sch_bodyR_ss_slew`). The abort needs the near-floating body node
  *and* the extracted amplifier around it.
- **Not the thermal network.** `sw_et=1` — the physical thermal tie
  instead of the 1e6 S one — does not cure (#430 §5, `ctl_swet1_*`), and
  the model-alone probes run under both methods with the body isolated.
  Issue #451's question 3 is answered on the star side of the dichotomy.

## 3. Newton non-convergence, not LTE collapse (issue #451 open question 1)

On the repro leg's own deck, ngspice's DC solve converges (dynamic gmin
stepping completes; the initial transient solution prints), and the
transient then dies. The three readings that classify the cut:

| leg | change | verdict | abort | job |
|---|---|---|---|---|
| `c451_ss_slew_itl4_100` | transient iteration limit 10 → 100 | **error** | `t=5.07812e-12` — the *identical* timepoint and node | `klt-sim-eae2c5557e20` |
| `c451_ss_slew_itl4_500` | → 500 | **error** | `t=5.00371e-08` — converges past the first wall, dies later | `klt-sim-450a44e095aa` |
| `c451_ss_slew_reltol_1e2` | `reltol` 1e-3 → 1e-2 (10× looser) | **error** | `t=3.36907e-08` | `klt-sim-eed869c15c69` |
| `c451_ss_slew_noopiter` | skip Newton iteration | **pass** | 8.1003 / 7.6881 | `klt-sim-5308ac2516f8` |

- The abort time *moves with `itl4`* — 100 iterations change nothing, 500
  carry the solve 10 decades of timepoints further. A local-truncation-
  error step cut never consults the iteration limit, so the fatal cut is
  **iteration-driven: Newton fails to converge** at a sequence of
  timepoints, oscillating rather than closing (100 iterations do not
  satisfy it where 10 do not).
- A 10× looser `reltol` does not cure it, so it is not a marginal
  tolerance question — consistent with DR-0005's finding that spec-cited
  quantities are tolerance-insensitive at print precision, and the reason
  [DR-0013](../../../spec/decision-records/0013-extracted-resistor-body-star-solver-abort.md)
  keeps the defaults. (`reltol=1e-4`, `abstol`, `gmin`, `trtol`, `chgtol`
  and `.options interp` removal were screened the same way in this
  investigation's scratch runs: every one aborts; only `method=gear` and
  `noopiter` pass this corner, and neither is a verification setting —
  gear still loses 36/45 corners, #430 `klt-sim-982291a18712`.)
- `noopiter` passing with the correct slew to 6 digits is the sharpest
  statement of the edge the solve sits on: the circuit's answer is fine;
  the *iteration* is what fails.

## 4. Why the solver names the `ibias` star (issue #451 open question 2)

The named node — `xdut.ibias__t12`, the drain terminal of one unit of the
diode-connected `Mbias` on its star leaf — is where the solver *first
fails*, not where the pathology lives: merging the whole `ibias` star
does not cure the abort (the run fails at `t=2.84472e-09` with the node
renamed to plain `ibias`; this investigation's scratch legs), and every
cure in §2 leaves the `ibias` star untouched. The bias diode's drain is
the amplifier's highest-gain re-entry point for rail/body ripple, so it
is the node whose residual breaks tolerance first when the near-floating
body node perturbs the solve. That is the same node family PR #439's
no-resistor extraction lost one corner on (`xdut.ibias__t0`) and the one
PR #431's TT investigation (still open) diagnosed from a corner rather
than a device model: one marginal family, reached by two routes. The
`rppd` body leaf makes it the rule (37/45) instead of the exception
(1/45).

## 5. The grid (issue #451 AC-3) and the row's disposition

| grid | verdict | worst rising / falling (V/µs) | job |
|---|---|---|---|
| committed bench, extraction (`c451_grid_slew`) | **8 pass / 37 error** — identical to #430's `klt-sim-aa4d9ece076e`, corner by corner and abort detail by abort detail | 8.9593 / 8.3493 (of the 8 measured, #430) | `klt-sim-c88dacfe26d5` |
| body-on-hub control (`c451_bodyhub_grid_slew`) | **45/45 pass, zero diagnostics** | 8.1003 / 7.6881 at `mos_ss / 1.08 V / −40 °C` — 2.4 % above the 7.51 V/µs bound on the falling edge | `klt-sim-3e4de704d8a5` |
| schematic netlist (`c451_sch_grid_slew`) | **45/45 pass, zero diagnostics** | 7.7626 / 7.7401 at `mos_ss / 1.08 V / −40 °C` | `klt-sim-dba022c2e188` |

The 45-corner extracted-leg slew grid of the drawn #430 candidate
**cannot complete on the committed bench**: twice submitted, twice 8/45
with deterministic aborts, and the mechanism is extraction-topological,
not a bench setting (§3), so no bench-side change is available that does
not first pass [DR-0013](../../../spec/decision-records/0013-extracted-resistor-body-star-solver-abort.md)'s
no-options test. The reason is recorded there: the row stays ungraded on
the committed bench until `klt extract` stops putting device body
terminals on their own star leaves (the extractor-side ask:
2AMLogic/klayout-tools#7317), and the
body-on-hub grid above is the bracket: it is the same netlist with one
terminal re-homed, it completes 45/45, and it reads 8.1003 / 7.6881 at
the binding corner — within 0.0001 V/µs of every passing control of #430
§5. The schematic leg grades normally and is unaffected.

Out of scope, unchanged by this record: the design (#430 / #332 / #342),
DR-0012's `cap_wcs` slew exposure, and every ratified bound. Observed on
klt 0.9.3.dev client (fleet runner klt 0.9.0, ngspice-47 KLU); #312's pin
bump is unaffected by this finding — the abort is not a runner-version
artifact, as the byte-identical local/leet aborts of §1 show.

## 6. Reproduce

```sh
python3 sim/post-layout/rz_solver.py controls \
    sim/post-layout/rz-layout-430/candidate/opamp_core_pex.spice \
    sim/post-layout/rz-layout-430/candidate/opamp_core.spice <dir>
# singles: one batch-set
klt sim --batch-set $(find <dir> -name 'c451_*.request.json' | grep -v grid | tr '\n' ' ') \
    --capacity-retries 3 --wait-for-capacity 600
# grids: submit, then attach each printed job id
for g in c451_grid_slew c451_bodyhub_grid_slew c451_sch_grid_slew; do
  klt sim <dir>/$g/$g.request.json --backend batch --submit-only --wait-for-capacity 600
  klt sim <dir>/$g/$g.request.json --backend batch --attach <job-id>
done
```

The star surgery, the body-resistance ladder, the body-hub edit and the
schematic body resistor are all regenerable offline from
`sim/post-layout/test_rz_solver.py`'s fixtures; the builder is loud
(wrong leaf counts, a missing star resistor or a second `rppd` card each
exit 1 and write nothing). The 10-run determinism protocol of §1 is
`klt sim <dir>/c451_ss_slew/c451_ss_slew.request.json --backend local`
repeated ten times.

## 7. Records

17 fleet envelopes in `records/`, each naming its job in
`environment.remote.job_id`:

| envelope | job | verdict |
|---|---|---|
| `records/c451_ss_slew.slew.json` | `klt-sim-9e4ad711a8d9` | error, `t=5.07812e-12`, `xdut.ibias__t12` |
| `records/c451_ss_slew_itl4_100.slew.json` | `klt-sim-eae2c5557e20` | error, identical abort |
| `records/c451_ss_slew_itl4_500.slew.json` | `klt-sim-450a44e095aa` | error, `t=5.00371e-08` |
| `records/c451_ss_slew_reltol_1e2.slew.json` | `klt-sim-eed869c15c69` | error, `t=3.36907e-08` |
| `records/c451_ss_slew_noopiter.slew.json` | `klt-sim-5308ac2516f8` | pass, 8.1003 / 7.6881 V/µs |
| `records/c451_merge23_ss_slew.slew.json` | `klt-sim-679ea37c9a98` | pass, 8.1003 / 7.6881 V/µs |
| `records/c451_bodyleaf_only_ss_slew.slew.json` | `klt-sim-3a07214796a7` | pass, 8.1003 / 7.6881 V/µs |
| `records/c451_vss_rest_merged_ss_slew.slew.json` | `klt-sim-9340b9338d1e` | pass, 8.1001 / 7.6880 V/µs |
| `records/c451_keep23t0_ss_slew.slew.json` | `klt-sim-c543cc23536e` | error, `t=8.73622e-10` |
| `records/c451_bodyR1m_ss_slew.slew.json` | `klt-sim-2576fc7a1f50` | error, `t=1.15723e-11` |
| `records/c451_bodyR6meg_ss_slew.slew.json` | `klt-sim-a2ef5fab7763` | error, `t=5.30273e-12` |
| `records/c451_bodyhub_ss_slew.slew.json` | `klt-sim-8fe4e5d9d99d` | pass, 8.1003 / 7.6881 V/µs |
| `records/c451_sch_bodyR_ss_slew.slew.json` | `klt-sim-e4e1e7637ef8` | pass, 7.7626 / 7.7401 V/µs |
| `records/c451_probe_r_bodyR.json` | `klt-sim-63e3667aa8e6` | pass, `t_10_90_s` 8.6974e-09 s |
| `records/c451_grid_slew.slew.json` | `klt-sim-c88dacfe26d5` | 8 pass, 37 error — identical to #430's grid |
| `records/c451_bodyhub_grid_slew.slew.json` | `klt-sim-3e4de704d8a5` | 45 pass, 0 fail, 0 error |
| `records/c451_sch_grid_slew.slew.json` | `klt-sim-dba022c2e188` | 45 pass, 0 fail, 0 error |

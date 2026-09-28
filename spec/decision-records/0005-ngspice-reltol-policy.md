# 0005: ngspice solver-tolerance policy — keep the default `reltol`; the gm/ID cross-host envelope stays documented, not pinned away

- **Status**: decided — this record sets no spec value and binds no new
  bound: no `spec/target-spec.md` row's value or bound is edited by the PR
  that carries this record (measured below: every spec-cited quantity is
  tolerance-insensitive at print precision). It records the
  simulation-methodology answer to issue #68's question — is a tighter
  ngspice `reltol` the standing convention for `sim/`, or is the documented
  gm/ID cross-host envelope the preferred answer? — with either outcome
  fully specified and reversible via this record (the same "Decided by:
  Builder agent" pattern as [0003](0003-input-pair-flicker-noise.md); like
  0003 there is nothing here waiting on a future ratification pass, because
  nothing here moves a ratified row).
- **Date**: 2026-09-28
- **Decided by**: Builder agent, issue #68
- **Related**: #68 (the issue this decides), #65 /
  [PR #69](https://github.com/2AMLogic/sg13g2-opamp/pull/69) (the
  cross-host envelope measurement and its cause analysis — this record's
  motivating evidence), #5 (the gm/ID study whose `gds` column carries the
  envelope), #60 (routed every harness's per-point check through
  `sg13g2_sim_broken` — the detector this study leans on),
  `sim/gm-id-characterization/README.md` § "Cross-host reproducibility
  envelope" (the standing reading rule this decision keeps),
  `sim/gm-id-characterization/records/20260909-063633-b402592.csv` (the
  committed macOS/aarch64 default-tolerance record),
  `sim/gm-id-characterization/records/20260928-161200-a6fa678.csv` (the
  committed Linux/x86_64 default-tolerance record),
  `sim/preflight.sh` (`SG13G2_NGSPICE_ERR_RE` / `sg13g2_sim_broken`)

## Context

#65 established, by measurement, that the ~20 % cross-host spread on the
gm/ID study's `gds` / `gm_gds` columns is **not** a device-model or
compiler-platform effect but ngspice's default DC convergence tolerance:
neither gm/ID template sets `.options reltol`, the PDK's `.spiceinit` does
not override it, and the bench derives `gds` as a central difference whose
fractional signal falls to `5.8e-04` — a ~1700x amplification of anything
the convergence test leaves unconstrained. A diagnostic Linux run at
`reltol=1e-9` reproduced the committed macOS record on 2238 of 2240 rows
(the other two by `3.7e-07`), at no runtime cost on that grid. #65
deliberately deferred the decision to #68: per `CLAUDE.md`'s
three-foundry-twin rule a solver-tolerance change is a decision for all
three sibling repos, and plausibly for more benches than gm/ID.

This record closes that decision with the measurement #68's curator
scoped: **all eight deterministic benches, run twice on one host** (this
one: macOS/aarch64, ngspice-46, IHP-Open-PDK `v0.3.0`, the pinned OSDI
`psp103` build), as committed and with a candidate tolerance added to every
templated deck, reporting which recorded columns move, the max relative
delta, and the `sg13g2_sim_broken` count under each configuration.

### Measurement setup

Scratch copies of `sim/` + `design/` under `/tmp` (the
`sim/gm-id-characterization/README.md` § "Cross-host reproducibility
envelope" reproduce recipe, with its sed pattern widened to the twelve
circuit-level `.options temp=@@TEMP_C@@ tnom=27` templates as the curator's
gotcha note requires — 14 of 14 templates patched per configuration,
confirmed by grepping the **rendered netlist snapshots**, not the
templates: 40/40 gm/ID snapshots and 45/45, 90/90, 135/135, 165/165 or
270/270 templated snapshots per circuit bench carry the injected `reltol`,
the default-run snapshots carry none, and each circuit bench's one
remaining snapshot without it is the committed non-templated
`design/netlist/opamp_core.spice` include, which has no `.options` line to
patch). Nothing under any experiment's
committed `records/` was touched: per that README's own evidence rule, a
tightened-tolerance run is a diagnostic and is reported here, not
committed as evidence. Harness dependency order matters and was followed
per configuration: `open-loop-ac` before `output-swing` (its Av0
cross-check column) before `input-cmr` (its buffer-interval columns), and
`open-loop-ac` before `cmrr-psrr`.

### What the measurement found

**1. On this host, the default-tolerance solve of every bench is already
converged: tightening moves nothing that a spec row cites.** Default vs
`reltol=1e-9` on the benches where the tightened configuration runs clean,
max relative delta over all 45 common point rows per bench:

| Bench | Columns that move (default vs 1e-9) | Max relative delta |
|---|---|---|
| `gm-id-characterization` | none — all 2240 rows identical at the CSV's 7-significant-figure print precision (also at `1e-6`, `1e-7`) | 0 |
| `open-loop-ac` | none — `av0_db`, `gbw_hz`, `pm_deg`, all DC operating points, all 45 rows | 0 |
| `input-noise` | `vni_100khz_v_rthz` at one corner point | 1.06e-06 |
| `cmrr-psrr` | `psrr_plateau_delta_db` only (a near-zero diagnostic column); `cmrr_db` / `psrr_db` / `acm0_db` / `avs0_db` identical | 1.32e-02 |
| `output-swing` | tracking bounds ≤1.3e-07; `vout_clip_low_v` 1.1e-04; `peak_inc_gain_v_v` 9.8e-06 | 1.1e-04 |
| `input-offset` | `vos_null_v` 7.2e-09; `vos_coarse_fine_delta_v` 2.1e-01 on a sub-µV difference-of-near-identicals (its own coarse/fine resolution artifact) | 7.2e-09 (headline) |
| `slew-rate` (vs `1e-6`; see 2 below) | `sr_*_v_per_us` ≤3.4e-06; `vout` extrema ≤2.8e-05 | 3.4e-06 (headline) |
| `input-cmr` (vs `1e-5`, 39 common rows; see 2 below) | `icmr_lo/hi/span_v`, `buffer_use_*` ≤2.8e-08; diagnostic margin columns larger at the rail corner (`vds1/2_hi_v` 2.1e-03, a qualitative `margin_pair_hi` flip at `mos_ff_27C_1.32V`) | 2.8e-08 (headline) |

The gm/ID envelope itself reproduces exactly as documented, **as a
cross-host property**: this run at default tolerance is bit-identical (all
columns, all 2240 rows) to the committed macOS/aarch64 record
(`20260909-063633-b402592.csv`), while diffing the same run against the
committed **Linux/x86_64** default-tolerance record
(`20260928-161200-a6fa678.csv`) gives `gds_s` 19.8 %, `gm_gds` 20.4 %
(worst, `pmos / 1.04u / mos_tt`, high overdrive), `gm_s` 7.1e-03,
`ids_a` 9.9e-04, with `cgg_f` / `vth_v` / `overdrive_v` identical — the
~20 % envelope, quantified. The envelope lives in the *Linux* run's
unconverged `gds`, not in this host's; a solver's default-tolerance
iteration path is host-dependent, which is precisely why "the default
happens to converge here" is not a property anyone may rely on — and
equally why the envelope must be carried as a documented reading rule
rather than assumed away.

**2. Tightened tolerance breaks convergence on two benches — at every
candidate value tight enough to matter.** `sg13g2_sim_broken` counts
(broken simulation points per bench; every harness applies the shared
`SG13G2_NGSPICE_ERR_RE` detector plus the ngspice exit-status and
required-output legs):

| Tolerance | gm/ID (40 pts) | open-loop-ac | input-noise | cmrr-psrr | output-swing | input-offset (det.) | slew-rate | input-cmr |
|---|---|---|---|---|---|---|---|---|
| `1e-3` (default) | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| `1e-5` | — | — | — | — | — | — | — | **6** (39/45 pass; 31m51s wall vs 3m16s at default, ~10x) |
| `1e-6` | 0 | — | — | — | — | — | 0 | **16** (29/45 pass) |
| `1e-7` | 0 | — | — | — | — | — | 0 | **21** (24/45 pass) |
| `1e-9` | 0 | 0 | 0 | 0 | 0 | 0 | **39** (6/45 pass) | **21** (24/45 pass) |

The two failure modes are the documented "silently degraded" class, and
the detector catches both:

- **input-cmr**: DC operating-point solve failures on the coarse
  full-span passes — "True gmin stepping failed" / "Dynamic gmin stepping
  failed" / "source stepping failed" banners in the per-point logs. The
  breakage is monotone in tolerance (6 → 16 → 21 → 21 from `1e-5` to
  `1e-9`) and concentrated at the rail/temperature edges (e.g.
  `mos_ss_-40C_*`, `mos_ff_27C_1.32V`). At `1e-5` the same bench also
  costs input-cmr ~10x wall time (31m51s vs 3m16s at default; its output-swing prerequisite slows similarly, 12m22s vs 77s — measured 2026-09-28, this host).
- **slew-rate**: TRAN "Timestep too small" collapse at `1e-9` (timestep
  driven to `6.25e-23`, "tran simulation(s) aborted", ngspice rc=1 — 39 of
  45 points). Clean at `1e-7` and `1e-6`.

**3. The negative controls behave as the issue predicted — on the arm that
fires here.** `abstol=1e-15` on the gm/ID grid breaks 7 of 40 points (all
`pmos`, `0.52u`/`1.04u`) with "Dynamic gmin stepping failed" banners:
`sg13g2_sim_broken` fires exactly as designed — the detector is verified
against the failure mode the policy must never paper over. `vntol=1e-12`
breaks **zero** points on this host (40/40 clean): the banner the issue
reported is real but host/iteration-path-dependent, the same
host-dependence this record's whole subject. Neither `abstol` nor `vntol`
is changed by this decision.

**4. The looser candidate is rejected on numbers, not preference.** The
candidate value must close the gm/ID envelope; the demonstrated closure
standard is print-precision cross-host agreement, met only at `1e-9`
(#65's Linux measurement: 2238/2240 rows, residual `3.7e-07`). At `1e-6`
the 1700x amplification arithmetic bounds the `gds` residual at ~`1.7e-03`
relative — two decades above print precision, a 100x improvement on the
20 % envelope but not its closure — and `1e-6` additionally breaks 16
input-cmr points. No value between "closes the envelope" and "keeps the
fleet green" exists: the closure requirement wants ≤`1e-9`, the
convergence requirement wants the default.

## Decision

**The standing convention for this `sim/` tree is ngspice's default
solver tolerance: no `reltol` (or `abstol`/`vntol`) override lines in any
deck under `sim/`, including the standalone units-check deck
(`sim/input-noise/testbench/tb_noise_units_check.spice`), which keeps its
`.options temp` line unchanged.** The gm/ID cross-host envelope stays
documented, not pinned away: `sim/gm-id-characterization/README.md` §
"Cross-host reproducibility envelope" (written by #65) is the standing
answer for that bench's `gds`-class columns, and its "What a reader should
assume" reading rules (quote `gds` / `gm_gds` above `~+0.45 V` overdrive
to no better than ~20 %, or re-derive from a scratch-copy tightened run;
cite `gm/Id`, `fT`, `Id` without a reproducibility tolerance) remain the
way those numbers are consumed.

The rejection of tightening is a measured result, not a preference, and
any future proposal to tighten must re-run this record's screen and clear
its gate:

1. **Zero `sg13g2_sim_broken` across every point of every bench at the
   proposed value** — unattainable today at any tightened value tested
   (`1e-5` breaks input-cmr x6, `1e-6` x16, `1e-7` x21, `1e-9` x21 plus
   slew-rate x39), and rescuing a value with `gmin`/`itl` workarounds is
   forbidden (issue #68's own rule — a tolerance that needs convergence
   aids to complete the fleet is a worse convention than the documented
   envelope).
2. **Closure at print precision on the gm/ID grid, cross-host** — met only
   at `1e-9`, which fails (1).
3. **No runtime regression** — `1e-5` already costs input-cmr ~10x wall (31m51s vs 3m16s).

What a future record diff is entitled to assume, per this record: every
committed record in this tree was produced at ngspice's default tolerance
with no deck-level override (this was true before this decision and stays
true by decision now); circuit-bench spec quantities are
tolerance-insensitive at print precision (measured above), so a cross-host
delta on them is an environment difference only up to the envelope the
producing bench's own README documents; a **mixed-tolerance join is not
valid evidence** — `output-swing`, `input-offset`, `cmrr-psrr` and
`input-cmr` cross-check columns against `open-loop-ac`'s record, and those
joins assume both sides ran at the same (default) tolerance.

## Alternatives considered

- **Pin `reltol=1e-9` tree-wide (the issue's measured starting point)** —
  rejected: breaks input-cmr (21/45) and slew-rate (39/45) on this host;
  fails the zero-broken gate the issue itself set.
- **Pin a looser `reltol` (`1e-6` / `1e-7`)** — rejected: does not close
  the gm/ID envelope at print precision (residual bound ~`1.7e-03` at
  `1e-6` via the 1700x amplification), and still breaks input-cmr
  (16/45 at `1e-6`, 21/45 at `1e-7`).
- **Pin `reltol=1e-5` (where only 6 input-cmr points break)** — rejected:
  a convention that breaks any points fails the gate; it improves the
  envelope bound to ~`1.7e-02` (barely), and costs input-cmr ~10x wall (31m51s vs 3m16s).
- **Tighten only the two gm/ID templates (bench-local pinning)** —
  rejected: the convention must be uniform across the tree (and across the
  three twin repos) for record diffs to stay interpretable; a per-bench
  tolerance map makes every cross-bench join a mixed-tolerance join.
  Scratch-copy tightened re-derivation remains available to any reader who
  needs a converged `gds` — the README's reproduce recipe, which this
  study used, with the sed pattern widened per the curator's gotcha note.
- **Keep the default and document (chosen)** — the only option with a
  clean fleet, zero runtime cost, unchanged records, and a reading rule
  that already exists. The envelope is real but narrow: it lives in one
  column class of one bench, above `+0.45 V` overdrive, where no sizing
  pass biases a gain device.

## Post-merge follow-through

- `sim/README.md` gains a "Solver tolerance convention" section stating
  the ratified convention (rides this PR).
- `sim/gm-id-characterization/README.md`'s "What a reader should assume"
  bullet that deferred this decision to issue #68 now points at this
  record (rides this PR).
- **No rollout is needed**: the decision changes nothing — no template is
  edited, no record is re-minted, no spec row moves. This explicit
  statement discharges the issue's rollout-follow-up criterion.
- A follow-up issue records the measured convergence fragility
  (input-cmr monotone breakage vs tolerance; slew-rate TRAN collapse at
  `1e-9`; the `vntol=1e-12` banner's host-dependence) as the standing
  gate any future tolerance proposal must clear, and notes that a future
  ngspice release changing its own defaults would warrant re-running this
  screen.
- Matching convention statements are filed in `2AMLogic/gf180-opamp` and
  `2AMLogic/sky130-opamp` so all three twins record the same answer — a
  shared non-decision is shared (cross-linked from issue #68).

## Out of scope

- Re-deriving or relaxing any `spec/target-spec.md` row (measured: nothing
  a row cites moves at tightened tolerance on this host — there is nothing
  to re-derive).
- Applying any tolerance to any template, and re-minting any record —
  rejected with the decision above.
- The two Monte Carlo benches (`input-offset` MC, `cmrr-mismatch` MC):
  per the issue's scope, they inherit their parents' exposure and their
  reported statistic is dominated by drawn spread, not solver tolerance;
  they are reasoned about here, not re-run.
- Cross-host (Linux) re-measurement: #65's committed Linux record is the
  cross-host leg this record diffs against; this study's paired runs are
  same-host by design (the issue's own "on a single host" scope).

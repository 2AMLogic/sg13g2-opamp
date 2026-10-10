# cmrr-mismatch

Mismatch Monte Carlo CMRR evidence for `design/opamp_core.sch` (issue #26,
companion to #17) — the **mismatch-inclusive** CMRR residual DR-0002's
residual register (c) names this issue owner of, measured with
SG13G2's own mismatch decks on the same harness as the ratified
**systematic** CMRR bench `sim/cmrr-psrr/` (issue #14, PR #25). Per point
of the same 45-point `cornerMOSlv.lib` `mos_tt/ss/ff/sf/fs` [DR-1] x
`{-40, 27, 125} °C` x `{1.08, 1.20, 1.32} V` grid, 300 independently
drawn mismatch samples (each a fresh per-instance `agauss()` draw of all
eight MOSFETs) establish the statistical distribution of the common-mode
gain, and the quoted per-point figure is the CMRR of the **+3σ part** of
that distribution (per the offset row's `3σ, mismatch MC N≥300 + process
corners` statistical-basis convention, applied to CMRR).

## What this bench measures

`CMRR = Av0 / Acm` exactly as `sim/cmrr-psrr/` defines it — `Acm` is the
common-mode gain measured by the identical CMRR harness
(`tb_cmrr_mc.spice.tmpl` is
[`sim/cmrr-psrr/testbench/tb_cmrr.spice.tmpl`](../cmrr-psrr/testbench/tb_cmrr.spice.tmpl)
plus a Monte Carlo loop; same self-biased DC network, same `cmpert`
in-phase injection, same 10 mHz shelf read), and `Av0` is the **same grid
point's** differential gain joined from `sim/open-loop-ac/records/*.csv`
— joined, **not re-measured**, per issue #26's own harness-reuse wording.
What differs per sample is only the device population: the runner points
`cornerMOSlv.lib` at the PDK's per-corner **mismatch** sections
(`<corner>_mismatch` → `sg13g2_moslv_mismatch.lib`'s sigmas
(`delvto_mm` 3.9 mV·µm nmos / 2.2 mV·µm pmos, `factuo_mm`, `dw/dl_mm`,
Pelgrom-scaled by `1/sqrt(m·l·w)`) consumed by
`sg13g2_moslv_mod_mismatch.lib`'s `agauss()` wrappers on `w`, `l`,
`delvto` and `factuo` of every instance).

Each sample records: the DC operating-point nodes (#14's per-point sanity
rule applied **per sample**), the Acm shelf value (10 mHz), the 0.1 Hz
plateau-guard partner, and 1 kHz. The per-point record columns carry the
linear-domain Acm `mean`/`sigma`, the **+3σ Acm point**
(`cmrr_3sigma_db = Av0 − 20·log10(mean+3σ)` — see "Choosing the 3σ
domain"), the dB-domain empirical mean/1st-percentile/worst sample, and
the exclusion counts.

### Choosing the 3σ domain

The bound is computed in the **linear** Acm domain (V/V), mapped to dB
once at the +3σ point. The dB image of the draw distribution is
heavy-tailed on the **rejection-good** side at several low-rail corners:
where the two competing structural Acm terms nearly cancel (e.g.
`mos_fs_-40C_1.08V`'s ratified 62.83 dB systematic CMRR, or
`mos_tt_27C_1.08V`'s 51.43 dB), a random draw that completes the
cancellation sends Acm tens of dB down **without any risk attached**, so a
dB-domain mean−3σ would be dominated by those benign outliers and lie
arbitrarily below every observed sample. The mismatch perturbation is
roughly additive and zero-mean around the structural value in the linear
domain, so `mean + 3σ` is the meaningful "+3σ part" Acm. The empirical
dB-domain 1st percentile and worst-observed-sample columns are recorded
beside the bound for direct scrutiny; at N=300 the bound sits at-or-just
above the observed sample minimum at every point of the committed record
(grid worst sample 25.94 dB at the binding point vs. the 26.68 dB bound),
which is the expected relation for a +3σ point.

## Method

- **Seeds** — deterministic per point: `setseed = 260000 + grid_index`
  (corner-major, 0-based); each point's sequence is a pure function of
  (corner, temp, vdd, section, seed, N). Every rendered netlist carries
  its seed in the committed header comment. Reproducibility is
  machine-checked and committed: the nominal point re-run with the same
  seed is **byte-identical** to the grid run's sample file, and a re-run
  with seed 990000 is verified to be a different draw
  (`corners/<record-id>/repro_check.txt`, both PASS).
- **N derivation** — the spec row's floor is `N≥300`; 300 is kept. Two
  pilots (the nominal point and #14's measured systematic binding corner
  `mos_fs_125C_1.08V`, 300 samples each) fix the linear-domain Acm
  sigma's relative sampling error `SE(σ̂)/σ ≈ 1/√(2N)` at ≈4.1%, inside
  the 5% target (`mc_target_sigma_re` in `records/<id>.pilot.txt`);
  points with heavy-tailed dB images (73 of 300 samples at
  `mos_tt_27C_1.08V` below −10 dB Acm) are visible in the committed
  pilot sample files.
- **Negative control** — every grid point also runs 3 iterations against
  the **plain** `<corner>` section: the exact zero-mismatch
  configuration `sim/cmrr-psrr/` ran (no `agauss()` anywhere in the
  wrapper). The runner asserts, per point and per iteration: all
  iterations identical, **and** equal to #25's committed
  `sim/cmrr-psrr/records/20260921-151815-707b34c.csv` row for that point
  (`acm0_db`, the derived `cmrr_db`, `vout_dc_v`, `vibias_dc_v`;
  tolerances 5e-3 dB / 5e-4 V) — i.e. the zero-mismatch deck reproduces
  #25's systematic CMRR through the full Monte Carlo machinery. 45/45
  pass in the committed record; each point's negative-control echo lines
  are committed alongside its MC sample file.
- **Per-sample AC points** — `ac dec 1 10m 1k` = {10 mHz, 0.1 Hz, 1 Hz,
  10 Hz, 100 Hz, 1 kHz}: the 10 mHz shelf (Acm0 read, #14's convention)
  plus the 0.1 Hz plateau-guard partner (tolerance 0.05 dB, samples
  failing are excluded and counted) plus 1 kHz (#14's in-band figure —
  flat to the shelf here too: `cmrr_1khz_3sigma_db` equals the shelf
  bound to <0.01 dB at all 45 points). Full 10 mHz–1 GHz spectra are NOT
  re-swept per sample: #14's committed spectra establish the shelf
  shape, and every sample's 10 mHz-vs-0.1 Hz delta is recorded and
  guarded per sample (max observed 0.0 dB in the committed record).
- **Per-sample DC sanity** — #14's rule per sample (output within 15% of
  VDD of mid-rail, no internal node within 2% of a rail): 13,500 samples,
  **0 exclusions** in the committed record. The guard exists so a
  non-regulating draw cannot read as a plausible rejection ratio.
- **Record integrity** — passing points keep their extracted sample
  files (`OP`/`AC` echo lines, one file per point) as the committed
  artifact; raw solver stdout is retained only for points that fail a
  check (none in the committed record), keeping the append-only record
  reviewable without 13,500 solver banners.

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
sim/cmrr-mismatch/run_cmrr_mismatch_mc.sh
```

Requires `ngspice` on `PATH` (developed and run against `ngspice-46`)
plus the OSDI models `sim/tools/build-osdi.sh` builds; does **not**
require `xschem` or `klt` at run time (`design/netlist/opamp_core.spice`
is committed, pre-netlisted). Requires the committed
`sim/open-loop-ac/records/*.csv` (joined `av0_db`) and
`sim/cmrr-psrr/records/*.csv` (negative-control cross-check); newest of
each is picked automatically for a fresh run (a resume uses the ones its
campaign manifest names), overridable with `AC_RECORD_CSV` /
`CMRR_RECORD_CSV`. Full run: 2×300 pilot samples + 45×300 grid samples +
45×3 negative-control + 2×300 repro ≈ 14,300 ngspice loop iterations in
~17 minutes on a laptop. Writes a new, timestamped, append-only record
under `netlist-snapshots/<record-id>/`, `corners/<record-id>/` and
`records/<record-id>.{csv,md}` — never overwriting a prior run.

### Resuming an interrupted campaign (issue #163)

A killed campaign can be continued by replaying its id
(`RECORD_ID=<id> sim/cmrr-mismatch/run_cmrr_mismatch_mc.sh`): completed
`*_mc_samples.txt` files, the DUT snapshot and the saved pilot are reused.
That is only sound if the replay is the **same experiment**, so the runner
binds every campaign to its inputs:

- **Manifest.** A fresh run snapshots the DUT and publishes
  `corners/<id>/campaign.manifest` before its first simulation. It is
  immutable: created atomically and never rewritten. It is committed with the
  campaign's other evidence. It holds sorted `key: value` lines covering:
  - the DUT source and snapshot sha256, and the
    `testbench/tb_cmrr_mc.spice.tmpl` sha256;
  - the joined `sim/open-loop-ac/` and `sim/cmrr-psrr/` record paths and
    sha256;
  - the grid (corners, temperatures, supplies) and `CL`;
  - `MC_SEED_BASE`, `MC_SEED_ALT`, `MC_N_FLOOR`, `MC_TARGET_SIGMA_RE` and
    `MC_NEGCTL_N`;
  - every validation tolerance (`NEGCTL_TOL_DB/V`, `OP_RAIL_FRAC`,
    `OP_MID_FRAC`, `PLATEAU_TOL_DB`);
  - the normalized `ngspice -v` version;
  - the PDK name, its `.fetched-version` and one sha256 over every `*.lib` in
    the PDK's `libs.tech/ngspice/models/`.

  Paths inside the checkout are stored repo-relative and PDK files by
  content only, so moving the checkout or the PDK install does not change
  the experiment. Not bound: the OSDI binaries (`build-osdi.sh --check`
  gates them; a rebuild need not be byte-identical) and the runner's own
  bytes.
- **Resume check.** A resume re-renders the manifest from the current
  invocation and compares it to the stored one before any sample, the
  snapshot or the pilot is touched. On any difference it exits 3 and prints
  each differing key with its `stored=` and `current=` values. Such a
  difference is, for example, a different seed, edited template or DUT,
  changed bytes in a joined record, another ngspice, or an edited model
  library. Start a new campaign (unset `RECORD_ID`) to run with the new
  inputs. The joined records are the ones the manifest names, **not** the
  newest: a record committed after the campaign began does not change a
  resumed join. An explicit `AC_RECORD_CSV`/`CMRR_RECORD_CSV` naming a
  different file is refused.
- **Pilot.** The saved `records/<id>.pilot.txt` is checked against the
  current seed base, N floor, sigma target, joined record ids and ngspice
  version. Both `mc_n_effective` and `pilot_acm_sigma_max_linear` are
  restored from it, so a resumed record reports the original pilot sigma
  (it used to read `unset`). The pilot file is published atomically.
- **Legacy campaigns.** An incomplete campaign with no manifest is refused
  (exit 3) with instructions to start a new id, and nothing is modified.
  Such a campaign was begun before #163, or it stopped before its manifest
  was published. Its samples' inputs cannot be verified. Finalized records
  stay refused by `sim/record-paths.sh` (#140) exactly as before.

Implementation: [`campaign-guard.sh`](campaign-guard.sh) (sourced by the
runner) and [`campaign_manifest.py`](campaign_manifest.py) (render /
publish / compare). Offline controls with no simulation:
`sim/tools/test_cmrr_mismatch_resume.py`. They use throwaway fixture trees
and a stub `ngspice` that answers only `-v`.

**Local-grid guard (interim, issue #110).** On a shared dispatch worker the
daemon exports `KLT_SIM_BACKEND=batch`; `run_cmrr_mismatch_mc.sh` then refuses
(exit 2, before any ngspice launch) unless `--allow-local-grid` is passed.
Migration to `klt sim` requests is tracked in #97/#98.
`sim/tools/test-grid-guard.sh` is the negative control.

## What was actually measured (this repo's committed record)

Record [`20260921-172304-65f5fb4`](records/20260921-172304-65f5fb4.md) —
all 45 points x 300 samples converged and passed every per-sample
sanity check (0 exclusions), negative control 45/45 vs #25,
reproducibility PASS, plateau guard flat (max 0.0 dB). `Av0` joined from
[`sim/open-loop-ac/records/20260910-221601-22feaba.csv`](../open-loop-ac/records/20260910-221601-22feaba.csv):

| Metric (DC shelf unless stated) | `Av0` | Systematic (#25) | Mismatch-inclusive 3σ (this record) |
|---|---|---|---|
| Worst point | — | 30.75 dB at `mos_fs_125C_1.08V` | **26.68 dB at `mos_ss_-40C_1.08V`** |
| Best point | — | 62.83 dB at `mos_fs_-40C_1.08V` | **37.57 dB at `mos_ss_125C_1.08V`** |
| Nominal (`mos_tt_27C_1.20V`) | 41.95 dB | 35.32 dB | **32.60 dB** (mean 35.44, 1st pct 33.48, worst 33.24) |
| @ 1 kHz | — | flat DC–1 kHz | **identical to shelf at every point** (≤0.01 dB) |
| Worst single draw | — | — | 25.94 dB (the binding point, of 13,500 samples) |

Full per-point data:
[`records/20260921-172304-65f5fb4.csv`](records/20260921-172304-65f5fb4.csv);
per-sample artifacts and controls under
[`corners/20260921-172304-65f5fb4/`](corners/20260921-172304-65f5fb4/)
(including `repro_check.txt` and each point's negative-control file);
rendered per-point netlists with their seeds under
[`netlist-snapshots/20260921-172304-65f5fb4/`](netlist-snapshots/20260921-172304-65f5fb4/).

### Per-draw table (`-draws.csv`)

[`records/20260921-172304-65f5fb4-draws.csv`](records/20260921-172304-65f5fb4-draws.csv)
holds one row per draw (45 points x 300 = 13,500 rows):
`point_id,corner,temp_c,vdd_v,draw_index,draw_seed,status,fail_reason,acm10m_db,acm1k_db,av0_db,cmrr_db`.
It is a pure post-processing of the committed `corners/<id>/*_mc_samples.txt`
echo files by [`make_draws_csv.sh`](make_draws_csv.sh) (no simulation; nothing
is reconstructed from mean and sigma). `status`/`fail_reason` apply the same
per-draw gates as the per-point statistics, so an excluded draw is visible
(this record has none). `draw_seed` is the point's `setseed`
(`MC_SEED_BASE` + grid index; every draw of a point shares it, `draw_index`
is the sample). `av0_db` is the point's joined systematic `Av0`, repeated per
row (not re-measured per draw), and `cmrr_db = av0_db - acm10m_db`. The
script recomputes `mc_n`, `mc_n_ok`, exclusions, `acm_lin_mean`,
`acm_lin_sigma`, `cmrr_3sigma_db` and `cmrr_db_min` from the draws and exits
non-zero unless they equal the summary CSV at its printed precision; the
worst single draw is 25.94 dB at `mos_ss_-40C_1.08V`. Future runs of
`run_cmrr_mismatch_mc.sh` emit `<id>-draws.csv` through the same script.
Offline controls: `sim/tools/test_make_draws_csv.py`.

**Caveat (DR-0004).** The ratified bound (>= 26.68 dB) is a +3 sigma-of-Acm
aggregate, not a per-draw pass/fail limit. This file does not discharge it,
and no per-draw yield limit or `target_yield` is asserted here (that needs
its own ratification, #108).

### Reading these numbers honestly

- **Mismatch makes the binding corner worse *and* moves it.** The
  mismatch-inclusive figure is below the systematic value at **all 45
  points** (by −1.77 dB at `mos_ff_27C_1.32V` up to −25.48 dB at
  `mos_fs_-40C_1.08V`), exactly the "a real part's CMRR is expected
  worse than the ratified floor" premise DR-0002 registered — now
  quantified. It also changes the ranking: the systematic binding corner
  (`FS / 125 °C / 1.08 V`, 30.75 dB) falls to 28.04 dB, but the
  mismatch-inclusive worst point is a **different, colder corner** —
  `SS / −40 °C / 1.08 V` at **26.68 dB** (its Acm draw distribution has
  by far the largest linear sigma, 1.11 V/V around a 4.31 V/V mean,
  25.6% relative). Pre-schematic intuition offered no mismatch-mode
  prediction to contradict; this is the first ranking of record.
- **Structural cancellations do not survive mismatch.** The two deepest
  systematic-CMRR points — `mos_fs_-40C_1.08V` (62.83 dB) and
  `mos_tt_27C_1.08V` (51.43 dB) — are near-cancellations between the
  mirror-load asymmetry and tail-impedance terms (small Acm ⇒ large
  CMRR); their mismatch-inclusive figures collapse to 37.35 dB and
  37.07 dB respectively. The systematic record's spread
  (30.75–62.83 dB) largely evaporates: the mismatch-inclusive envelope
  is 26.68–37.57 dB, an ~11 dB band across the grid.
- **The 1 kHz figure tracks the shelf.** The systematic bench found CMRR
  flat DC–1 kHz at every corner; the mismatch term does not change that
  at any of the 45 points (the mismatch-induced CM error is a DC-accurate
  offset-like term; the in-band `cmrr_1khz_3sigma_db` column equals the
  shelf bound).

## What this bench does not claim

- **Not a closed-loop CMRR measurement** — same scope as #14: the figure
  is the open-loop transfer ratio `Av0/Acm`; a closed-loop application's
  rejection also depends on its feedback network's noise gain.
- **A drawn part's own differential-gain variation is not folded in.**
  Per issue #26's definition, every sample's CMRR divides the *joined
  systematic* `Av0` of its grid point, not the drawn part's own
  differential gain — that is the deliberate harness reuse which keeps
  the mismatch-inclusive figure directly comparable to the ratified
  systematic floor; the residual between the two records is then purely
  the mismatch-induced change in Acm. The per-sample Av0 perturbation is
  a second-order term on the ratio; re-measuring it per sample would need
  a differential-drive harness per draw, which is a different bench.
- **Not a PSRR mismatch axis.** Per issue #26's implementation guidance,
  no PSRR mismatch deck was opened: the PSRR+ row's supply path is
  dominated by the direct output-PMOS path, and nothing here is evidence
  about it.
- **Not a ratification (at landing; since superseded by DR-0004).** When
  this record landed, the `spec/target-spec.md` CMRR row's
  mismatch-inclusive figure updated from it was tagged `[P]` (measured,
  not re-ratified): the systematic bound stayed the ratified `[DR-2]`
  number, per DR-0002's residual (c), which reserved the superseding
  re-ratification of this term to a future two-key pass that cites this
  record (tracked by the follow-up issue filed in the same PR as this
  record). That pass has since run — issue #32 /
  [`spec/decision-records/0004-cmrr-mismatch-inclusive-ratification.md`](../../spec/decision-records/0004-cmrr-mismatch-inclusive-ratification.md)
  cites this record, and the row's mismatch-inclusive figure is now the
  ratified `[DR-4]` bound (the systematic floor staying in-row as
  context). This README's method and caveats are unchanged by that pass.
- **Not input-CMR characterization** — every point and sample runs at
  one fixed `Vcm = VDD/2`, the fleet's bench convention (ICMR is its own
  issue, #21).
- **The seeds are reproducible, not privileged.** The committed seeds
  (`260000 + index`) are arbitrary-but-fixed; a different seed family
  draws different parts. N=300 fixes each point's sigma to ≈±4%; the
  empirical percentile/min columns are the honest tail record at this N.

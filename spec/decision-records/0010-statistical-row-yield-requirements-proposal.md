# 0010: Yield requirements for the two statistical rows — coordinated proposal (issue #108)

- **Status**: `proposed`. This record is a **proposal for ratification**. It
  supplies **neither** the EE key nor the market key, ratifies **no** number,
  and changes **no** limit, `[P]` tag, `spec/target-spec.md` row,
  `spec/integrator.json` value or `sim/` / `signoff/` evidence. Every limit,
  yield and confidence figure below is a **candidate with explicitly
  provisional assumptions**, to be accepted, replaced or rejected by the
  independent ratification that follows (two-key mechanism of
  [DR-0002](0002-target-spec-ratification.md)). Nothing here is a yield or
  compliance claim, and nothing here unblocks #105 or satisfies T1 item 6.
- **Date**: 2026-10-19
- **Decided by**: operator ruling (attended fleet-decide 2026-10-19, option 1:
  prepare one coordinated proposal, recorded in the comments of #108);
  prepared by Builder agent, issue #108. The ruling authorizes preparation
  only.
- **Related**: #108 (this issue; stays open — this PR is `Part of #108`),
  #105 (downstream; stays blocked on *ratified* requirements and usable
  samples), #101 / [DR-0009](0009-literal-limits-design-margin-direction.md)
  (the design-margin plan; the systematic-offset limit is its subject —
  coordination point, not a completed approval), #107 (closed; persisted the
  CMRR per-draw file), #3 (T1 tracker),
  [DR-0002](0002-target-spec-ratification.md) (residual (b), the offset
  statistical basis; PR #27 provenance gate),
  [DR-0004](0004-cmrr-mismatch-inclusive-ratification.md)

## Context

`klt yield` grades T1 item 6 from three inputs per statistical row: a
**per-sample limit**, a **target yield**, and a **confidence level**. The spec
ratifies none of them for either statistical row:

- **Input-referred offset.** Ratified bound +21.9 mV is the *systematic*
  (deterministic, corner-only) half. The mismatch 3σ figures (26.4–27.4 mV)
  are `[P]`, pending the DR-0002 residual-(b) pass.
- **CMRR, mismatch-inclusive.** DR-0004 ratifies ≥ 26.68 dB as the
  **+3σ-of-Acm aggregate** per grid point (linear domain, `Av0 −
  20·log10(mean+3σ)`). That is a statistic of a distribution, not a
  per-sample limit.

A three-sigma aggregate is not a per-sample limit and not a demonstrated tail
yield: the nominal ≈ 99.87 % one-sided coverage of "+3σ" holds only if the
distribution is Gaussian *in the domain it is computed in*, which is exactly
what a yield claim must show rather than assume (DR-0004 itself records that
the dB-domain image of the CMRR draws is heavy-tailed).

Per `CLAUDE.md`, agents do not set or relax ratified spec. This record
therefore frames the choice, shows what each alternative costs, and lists
what a ratifier must decide. It deliberately does not pick limits to fit the
measured distributions.

## Evidence inventory (pinned at `671d93d`)

All paths below resolve at `671d93d`. Counts were re-derived from the
committed files on 2026-10-19 by read-only parsing; **no simulation,
campaign or cloud job was run**.

### Offset — raw per-draw evidence exists

| Item | Finding |
|---|---|
| File | `sim/input-offset/records/mc-20260921-174056-0a509fb-draws.csv` (record `mc-20260921-174056-0a509fb`) |
| Population | 4800 rows = 16 points × N = 300: 15 mismatch points plus one `negctrl` point (`mos_tt_negctrl_27C_1.20V`) |
| Axes covered | 5 process corners × {−40, 27, 125} °C at **VDD = 1.20 V only**. The 1.08 V / 1.32 V supply axis is *not* sampled with mismatch |
| Status | 4800/4800 `PASS`; 0 failed, 0 missing, 0 non-finite |
| Identity | `(point_id, draw_index)` unique. `draw_seed` takes only 300 distinct values — the **same 300 seeds are reused at every point**, so draws are paired across points, not independent between them |
| What `vos_v` is | The **total** per-draw offset (systematic + random), not the random component alone. Per-point mean 12.5–19.6 mV, per-point σ 8.8–9.1 mV; the zero-spread `negctrl` reads 15.714 mV (the systematic value at that point). The random component must be derived as `vos_v − (that point's systematic)` using the committed systematic record, not re-estimated from the same draws |
| Extremes | min −9.7 mV, max +44.3 mV |
| Consumers | `signoff/yield-inputs/offset_draws_to_sampleset.py` (+ `--check`, tests in CI) → `offset-mc-20260921-174056-0a509fb.sampleset.json`. Converter refuses duplicate/missing draws and non-finite PASS values; non-PASS draws become `null`; `negctrl` is dropped |
| Negative control | The zero-spread `negctrl` is a no-mismatch nominal, **not** a seeded known-bad population, so it cannot serve as the `klt yield` `detected` control (see `signoff/yield-inputs/README.md`) |

### CMRR — raw per-draw evidence exists (README is stale)

| Item | Finding |
|---|---|
| File | `sim/cmrr-mismatch/records/20260921-172304-65f5fb4-draws.csv` (record `20260921-172304-65f5fb4`) |
| Population | 13 500 rows = 45 PVT points × N = 300; columns include `acm10m_db`, `acm1k_db`, `av0_db`, `cmrr_db` per draw |
| Status | 13 500/13 500 `PASS`; 0 excluded, matching DR-0004 |
| Identity | `(point_id, draw_index)` unique (13 500 distinct). `draw_seed` is **per point** (`260000 + grid index`), not per draw — draws within a point are one seeded sequence; reproducibility is by (point, seed, N), which the record's `repro_check.txt` verifies |
| Per-draw CMRR | min 25.942 dB (at `mos_ss_-40C_1.08V`, the binding point); only **1 of 13 500** draws is below the 26.68 dB aggregate bound; 257 draws are below the superseded 30.75 dB systematic floor |
| Consumers | **None.** No CMRR sample-set converter exists. `signoff/yield-inputs/README.md` still says CMRR is "summary-only" (blocked on #107); #107 is closed and the per-draw file exists, so that row is stale. A small correction is included in this PR |
| Negative control | The per-point zero-mismatch negative control is asserted against the systematic record (DR-0004), but like offset it is not a known-bad population for `klt yield` |

**Summary-only vs raw**: both rows now have raw per-draw evidence. Neither
requirement below may be evaluated from `*_mean` / `*_sigma` columns; samples
are never reconstructed from mean/sigma.

### Observations that bear on the choice (not on acceptance)

- Against the *systematic* literal +21.9 mV, 1103 of 4800 offset draws
  (23 %) exceed |21.9 mV|. This is context for why the systematic bound
  **cannot** double as a per-sample limit — it is a bound on a different
  quantity (the deterministic term). It is not evidence of failure, and no
  result is "moved" by it.
- Against the CMRR aggregate 26.68 dB, 1/13 500 draws fall below. The
  aggregate is a +3σ edge, so a per-sample pass fraction near 99.99 % at the
  binding point is the *expected* relation (DR-0004 notes it); it says
  nothing about other points' tails or about a tail beyond N = 300.

## What a defensible yield claim needs

### Claim form (proposed, both rows)

A yield claim is: *the per-sample pass probability `p` at a stated PVT point
satisfies `p ≥ Y` with confidence `C`*, shown by a one-sided exact
(Clopper–Pearson) binomial lower bound on the pass count. PVT corners remain
**deterministic worst-case axes** (as the spec's `[DR-1]` grid already is),
so the claim is made **per grid point** and graded by the worst point. Samples
are **not pooled across points** (different distributions; and offset draws
reuse seeds across points).

A distribution-free binomial claim is preferred over a Gaussian-tail claim
because it does not assume the shape (heavy-tailed in dB, per DR-0004). Its
cost is sample size.

### Required N (exact binomial, one-sided, per point)

Smallest N such that observing ≤ k failures demonstrates `p ≥ Y` at
confidence `C` (derived: smallest N with `P(X ≤ k | N, 1−Y) ≤ 1−C`; for k = 0
this is `N ≥ ln(1−C)/ln(Y)`).

| Target Y | C | k = 0 | k = 1 | k = 3 |
|---|---|---|---|---|
| 95 % | 90 % | 45 | 77 | 132 |
| 95 % | 95 % | 59 | 93 | 153 |
| 99 % | 90 % | 230 | 388 | 667 |
| 99 % | 95 % | 299 | 473 | 773 |
| 99.7 % | 90 % | 767 | 1296 | 2226 |
| 99.7 % | 95 % | 998 | 1580 | 2583 |
| 99.9 % | 90 % | 2302 | 3889 | 6679 |
| 99.9 % | 95 % | 2995 | 4742 | 7752 |

Reading it against the existing N = 300 per point: with **zero** failures,
N = 300 demonstrates only Y ≈ 99.24 % at C = 90 % and Y ≈ 99.01 % at
C = 95 %. With **one** failure it demonstrates less than 99 % at C = 95 %
(a 99 % claim needs N ≥ 473). Hence **N = 300 does not support a 99.7 % or
99.9 % (≈ "3σ-class") per-point tail-yield claim at any of the confidence
levels above**, and a "+3σ" statistic computed from 300 draws is not a proof
of such a tail. Existing N = 300 is *sufficient* only for a ≤ 99 % claim with
zero failures at a single point.

### Inconclusive outcomes (defined before any execution)

For each point: **PASS** when the Clopper–Pearson lower bound ≥ Y;
**FAIL** when the *upper* bound on `p` is < Y (i.e. failures demonstrably
exceed the budget); otherwise **INCONCLUSIVE** (more samples needed). An
INCONCLUSIVE point is neither a pass nor a fail: the row's grade is
`inconclusive`, never silently rounded to pass. Non-`PASS` simulation status
(op-fail, plateau-fail, non-finite) counts as a **failed sample** in the
denominator, never as an exclusion; a campaign with excluded samples reports
the exclusions beside the verdict.

## Row 1 — Input-referred offset (random component)

### Observable and decomposition

Report two quantities and never merge them:

- **Systematic offset `Vos_sys`** at each PVT point (deterministic, nominal
  devices) — unchanged, ratified literal +21.9 mV worst case [DR-2]; its
  margin is #101 / DR-0009's subject. **This record changes nothing about it.**
- **Random offset `Vos_rand = Vos_draw − Vos_sys`** at the same point
  (mismatch-driven, zero-mean by construction of the deck, σ ≈ 8.8–9.1 mV
  dominated by the 0.13 µm × 3.2 µm input pair's `delvto` area law).

The claimed per-sample quantity must be stated in one of two ways; the
ratifier chooses:

| Option | Per-sample observable | Relation to the ratified systematic bound | Trade-off |
|---|---|---|---|
| **A. Random-only symmetric limit** | `\|Vos_rand\| ≤ L_rand` | Independent of the +21.9 mV systematic bound; the *part* sees `\|Vos_sys\| + \|Vos_rand\|` | Needs a product allocation for `L_rand`; reads cleanly against the area law, but a part's observed offset is the sum |
| **B. Total-offset limit** | `\|Vos_total\| ≤ L_tot` (the draw as measured) | The systematic bound is a *component*; `L_tot` ≥ +21.9 mV by construction | What a customer measures, but couples the random claim to the (contested, #101) systematic margin and to the supply axis not sampled with mismatch |

No candidate value is proposed for `L_rand` / `L_tot`: **a limit chosen from
the measured 3σ (26.4–27.4 mV) or from the draw maximum would be circular**,
and **no product allocation (downstream ADC/DAC budget, trim range, input
range) exists in the repo to justify one.** This is reported as a missing
input. The ratifier must supply the allocation; if none exists, the
alternative on the table is "**no per-sample offset yield claim; the 3σ
aggregate is the stated claim**" (see Option C).

| Option | What it commits to | Consequence for T1 item 6 |
|---|---|---|
| **C. Aggregate-only** | Keep "3σ, mismatch MC N ≥ 300 + corners" as the *stated* claim; declare **no** `target_yield` | Item 6 would need a different grading basis; `klt yield` cannot be fed |
| **A/B + Y,C from the table** | A numeric limit with e.g. Y = 99 % / C = 95 % (N ≥ 299 at k = 0) | Feasible near-term only for ≤ 99 % and zero failures; ≥ 99.7 % needs ≥ 998 per point |

### Offset evidence gaps (this row)

1. **Statistical basis undecided** (DR-0002 residual (b)). The 3σ figures are
   `[P]`. **Final ratification of any offset yield requirement is sequenced
   after that decision**; this record is provisional until then.
2. **No product allocation** for the random limit (see above).
3. **Supply axis**: mismatch draws exist only at VDD = 1.20 V; the
   systematic term varies to +21.9 mV at 1.08 V (`FS/125 °C`). A claim whose
   scope includes 1.08 V / 1.32 V needs mismatch draws there too, or an
   explicit scope restriction to 1.20 V.
4. **Seed reuse across points** (same 300 seeds at all points): within-point
   statistics are valid; cross-point independence must not be assumed (no
   pooling; correlation of the *worst-point* selection is a stated caveat).
5. **Systematic subtraction** needs the matching committed systematic record
   (`sim/input-offset/records/20260918-203858-90844d2.csv`) joined per point
   at a pinned SHA; a converter for `Vos_rand` does not exist (the existing
   converter emits total `vos_v` only).
6. **Negative control**: needs a seeded known-bad population (e.g. inflated
   mismatch) so `klt yield` can return `detected`; the zero-spread `negctrl`
   is not one.
7. **Gate**: PR #27 ratification-provenance (DR-0009) remains unresolved and
   applies to any bound that cites DR-0002.

## Row 2 — CMRR, mismatch-inclusive

### Observable

Per draw: `cmrr_db = Av0 − Acm` at the grid point (columns `cmrr_db`; the
10 mHz shelf and 1 kHz in-band values coincide at every point per DR-0004).
Per-sample claim: `cmrr_db ≥ L_cmrr` at each of the 45 points, into
CL = 2 pF [DR-1], with the joined systematic `Av0` as defined by DR-0004.

| Option | Per-sample limit | Trade-off |
|---|---|---|
| **A. Re-use the aggregate as the per-sample limit** (`L_cmrr = 26.68 dB`) | Easy to state; the measured pass fraction at the binding point is 299/300 → **fails to demonstrate 99 % at C = 95 %** even with one failure | Equates a +3σ statistic with a per-sample limit — rejected by the ruling unless independently justified |
| **B. A new product-justified dB limit** | Needs the downstream common-mode budget (not in repo) | Cleanest; blocked on the missing allocation |
| **C. Aggregate-only** | Keep DR-0004's +3σ definition as the claim; no `target_yield` | Same consequence as offset Option C |

No numeric `L_cmrr` is proposed other than naming the **existing ratified
26.68 dB aggregate** as the one value already in the spec, with the caveat
above. The linear-vs-dB domain choice DR-0004 asked the EE key to rule on
carries over unchanged: a *per-sample* dB limit (Options A/B) is
domain-independent, because the pass test is on each draw's dB value — one
more reason a per-sample claim is cleaner than a dB-domain 3σ.

### CMRR evidence gaps (this row)

1. **No sample-set converter** for the CMRR draws file (belongs to #105 after
   ratification; not written here). The converter must also validate against
   the summary CSV (points, N, seeds) as the offset converter does.
2. **Seed provenance**: seeds are per point, not per draw; identity relies on
   `(point_id, draw_index)`. Acceptable for within-point analysis;
   independent-draw claims rest on the seeded-sequence determinism check.
3. **Full 45-point grid is per-point**, so a worst-point claim over 45 points
   multiplies exposure: a point-wise 95 % confidence statement is not a 95 %
   statement over all 45 jointly. Either the ratifier accepts per-point
   confidence or sets `C` higher (e.g. Bonferroni-style C' = 1 − (1−C)/45 =
   99.89 % for C = 95 %, which raises the required N materially — e.g. Y = 99 %
   k = 0 needs ≈ 677 per point).
4. **Negative control**: as offset — a known-bad seeded population is needed;
   the per-point zero-mismatch control is a consistency check, not a
   detection control.
5. **Gate**: DR-0004 itself is "submitted for ratification" under the same
   two-key mechanism and the same PR #27 provenance discrepancy; a
   per-sample yield requirement layered on it inherits that gate.

## Alternatives considered (overall)

1. **Pick limits from the observed distributions** (e.g. the draw maximum or
   a 3σ edge as `L`). Rejected: circular; a pass would be constructed, not
   shown.
2. **Reconstruct CMRR samples from `acm_lin_mean`/`acm_lin_sigma`.**
   Rejected: forbidden by the ruling and unnecessary now that the draws exist.
3. **Gaussian tail model for the yield (`Y = Φ(L)` from mean, σ).** Rejected
   as the *primary* method: assumes the shape the evidence says is
   heavy-tailed in dB (DR-0004); acceptable only as an informative secondary.
4. **Separate offset-only and CMRR-only records.** Rejected: the ruling asks
   for one coordinated proposal; the two rows share the claim form, sample
   size and inconclusive rules.
5. **Declare both rows aggregate-only (no yield claim).** Retained as
   Option C on both rows — it is the honest outcome if no product allocation
   is supplied.

## Bounded validation / resource plan (a plan only — nothing is run)

Required only if the ratifier selects a per-sample claim with Y ≥ 99 %
and the existing N = 300 is insufficient. Axes follow the existing benches
(harnesses `sim/input-offset/run_offset_mc.sh` and `sim/cmrr-mismatch/`).

| Item | Offset | CMRR |
|---|---|---|
| Axes | 5 corners × 3 T × {1.08, 1.20, 1.32} V = 45 points (adds the unsampled supply axis) | 45 points (existing grid) |
| Samples/point (example: Y = 99 %, C = 95 %, ≤ 1 failure) | 473 | 473 (or ≈ 677 at k = 0 with 45-way correction) |
| Total new draws (example) | 45 × 473 ≈ 21 285 | 45 × 473 ≈ 21 285 |
| Runtime / cost | **Unknown** — the existing campaigns' wall-clock and fleet cost are not recorded in the repo as comparable figures; must be measured from the pinned harness records before a request | Same |
| Executor prerequisites | A `klt sim` `monte_carlo` request form of the shell harnesses (currently shell ngspice scripts, not `klt sim` requests — `signoff/yield-inputs/README.md`); fleet backend; seed policy giving **per-draw** seeds (offset reuses; CMRR is per-point) | Same |
| Stop / retry | Stop on first harness negative-control mismatch beyond the existing tolerances; one retry on infrastructure failure only (no re-seeding to "get a pass"); cap total spend at the budget the separate authorization names | Same |

**This ruling launches no simulation, cloud job or campaign.** Execution and
spending need a separate authorization that names the budget.

## Decision requested of the ratifiers (none taken here)

1. Per row: Option A/B (a numeric per-sample limit, with its **product
   allocation named**) or Option C (aggregate-only, no yield claim).
2. If A/B: `Y`, `C`, the per-point vs joint confidence rule, and the
   inconclusive-outcome rule above (or amendments to it).
3. Offset only: the DR-0002 residual-(b) statistical-basis decision, **before**
   final ratification of the offset requirement.
4. Whether any extra measurement (plan above) is authorized, and its budget.

## Consequences

- Nothing in `spec/target-spec.md`, `spec/integrator.json`, `sim/` or
  `signoff/` changes except the one correction to the stale CMRR "summary-only"
  row in `signoff/yield-inputs/README.md`.
- Until ratified requirements and usable samples exist, **#105 stays
  blocked** and T1 item 6 stays `unmet / no_evidence`.
- This PR is `Part of #108`; #108 stays open for the ratification receipts.

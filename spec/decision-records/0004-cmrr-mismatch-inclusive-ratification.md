# 0004: CMRR re-ratification — bind the mismatch-inclusive 3σ figure (0002 residual (c), two-key)

- **Status**: `submitted for ratification` — this record's bound binds when,
  and only when, the PR that carries it has been ratified by **both keys** of
  the two-key mechanism (defined in
  [0002-target-spec-ratification.md](0002-target-spec-ratification.md)'s
  Status block, per
  [2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)): an EE key
  (`RATIFY-KEY: ee`) and a market key (`RATIFY-KEY: market`), each posted as
  a PR review verdict, **neither key held by this PR's author or the
  design's author** (non-author enforcement). The merge commit of that PR is
  the ratification record. Until both keys are present and approving, the
  bound below is a recommendation, not a ratified value — and the
  `[DR-2]` systematic floor it is poised to supersede stays the row's
  binding bound.
- **Date**: 2026-09-21
- **Decided by**: Builder agent, issue #32 (recommendation + this record);
  the EE key and the market key (ratification verdicts on the PR)
- **Related**: [0002-target-spec-ratification.md](0002-target-spec-ratification.md)
  (amended — its residual (c) is discharged for the CMRR row by this record,
  exactly as its "a future re-ratification cites its record and supersedes
  this systematic bound" wording anticipated); `spec/target-spec.md` (the
  CMRR row this re-tags); #32 (the issue this decides), #26 (the CMRR
  mismatch Monte Carlo campaign, closed — its record is this record's entire
  measured basis), #17 (the offset row's sibling statistical campaign, whose
  own re-ratification pass this record deliberately does **not** ride),
  #14/#25 (the systematic CMRR bench being superseded),
  `sim/cmrr-mismatch/records/20260921-172304-65f5fb4.{csv,md}` (the record
  cited below), `sim/cmrr-psrr/records/20260921-151815-707b34c.{csv,md}` (the
  systematic floor's own record), `sim/open-loop-ac/records/20260910-221601-22feaba.csv`
  (the joined `Av0` both records divide by)

## Context

DR-0002 ratified the CMRR row's bound as the **systematic, nominal-device
floor** — **≥ 30.75 dB worst-case** (measured envelope 30.75–62.83 dB, worst
`FS / 125 °C / 1.08 V`, `sim/cmrr-psrr/records/20260921-151815-707b34c.csv`)
— with the mismatch-inclusive term explicitly registered as residual (c),
owned by #26, and this exact path pre-registered: "a future re-ratification
cites its record and supersedes this systematic bound", the keys ratifying
the floor "understanding this" — a real part's CMRR is expected worse than
the ratified floor.

#26's Monte Carlo campaign has now landed and closed:
`sim/cmrr-mismatch/records/20260921-172304-65f5fb4.{csv,md}` measures the
mismatch-inclusive CMRR across the same full 45-point PVT grid
(`mos_tt/ss/ff/sf/fs` × `{−40, 27, 125} °C` × `{1.08, 1.20, 1.32} V`, the
`[DR-1]` corner grid), with **N = 300 independent per-instance mismatch
draws per point** (13,500 samples, 0 excluded — 0 op-fail, 0 plateau-fail),
each sample's CMRR dividing the **same grid point's joined systematic `Av0`**
(`sim/open-loop-ac/records/20260910-221601-22feaba.csv`, joined, not
re-measured — the harness-reuse convention that keeps the result directly
comparable to the ratified floor by construction), using SG13G2's own
per-corner mismatch decks (`sg13g2_moslv_mod_mismatch.lib`), seed-deterministic
per point (`setseed = 260000 + grid index`; same seed → byte-identical re-run,
machine-checked and committed in
`corners/20260921-172304-65f5fb4/repro_check.txt`), with a per-point
zero-mismatch negative control asserted against the committed systematic
record (`sim/cmrr-psrr/records/20260921-151815-707b34c.csv`, tolerances
5e-3 dB / 5e-4 V). N stays at the spec row's `N≥300` floor, re-derived
there: the worst-pilot linear-σ sampling error is ≈ 4.1 %
(`SE(σ̂)/σ ≈ 1/√(2N)`), inside the 5 % target.

What the record found, quoted verbatim from
`sim/cmrr-mismatch/records/20260921-172304-65f5fb4.md`'s worst/best-corner
summary:

```
cmrr_3sigma_db: worst(min) 26.68 at mos_ss_-40C_1.08V, best(max) 37.57 at mos_ss_125C_1.08V
cmrr_1khz_3sigma_db: worst(min) 26.68 at mos_ss_-40C_1.08V, best(max) 37.57 at mos_ss_125C_1.08V
excluded samples total: 0 (op_fail 0, plateau_fail 0) of 13500
```

The mismatch-inclusive figure — **the +3σ-of-Acm envelope, 26.68 dB worst /
37.57 dB best, binding at `SS / −40 °C / 1.08 V`** (`mos_ss_-40C_1.08V`) —
is **below the systematic floor at all 45 points**: by 1.77 dB at
`mos_ff_27C_1.32V` up to 25.48 dB at the systematic best point
`mos_fs_-40C_1.08V` (62.83 dB), whose structural near-cancellation does not
survive mismatch. The record quantifies DR-0002's registered "expected
worse" premise and moves the binding corner to a different, colder point
than the systematic floor's own `FS / 125 °C / 1.08 V` (whose
mismatch-inclusive figure falls to 28.04 dB). The mismatch-inclusive
envelope is flat DC (10 mHz shelf) to 1 kHz at every point — the
mismatch-induced common-mode error is a DC-accurate, offset-like term, so
the in-band `cmrr_1khz_3sigma_db` figure equals the shelf bound at all 45
points, mirroring the systematic bench's own flatness finding.

## Decision

**The CMRR row's binding bound becomes the mismatch-inclusive figure:
≥ 26.68 dB worst-case** — the +3σ-of-Acm envelope's worst edge (26.68 dB worst
/ 37.57 dB best, binding at `SS / −40 °C / 1.08 V`,
`sim/cmrr-mismatch/records/20260921-172304-65f5fb4.{csv,md}`), superseding
the `[DR-2]` systematic floor exactly along DR-0002 residual (c)'s
pre-registered path. The **definition is part of the ratified number**: per
grid point, the CMRR of the +3σ part of the 300-draw common-mode-gain
distribution — the joined `Av0` minus `20·log10(mean + 3σ)` of the drawn
`Acm` in the **linear** domain — with N = 300 plus the process corners
(the five `cornerMOSlv.lib` families' mismatch sections crossed with the
`[DR-1]` temperature/supply grid). A CMRR figure quoted without this
definition is not a claim about this amplifier, the same way the noise row's
band is part of its number.

The superseded **systematic floor (≥ 30.75 dB worst-case, `FS / 125 °C /
1.08 V`, `sim/cmrr-psrr/records/20260921-151815-707b34c.csv`) stays in the
row as context** per the value-tag convention: it is the structural
mirror-load floor that a nominal (perfectly matched) device exhibits, and
the measured distance between it and the ratified bound — 1.77 to 25.48 dB
across the grid — is itself information about where structural
cancellation does and does not survive mismatch.

**This bound is weaker than the previously ratified row it supersedes
(26.68 < 30.75 dB), and it is ratified under DR-0002's pre-registered relax
rule, which the market key must apply explicitly**:
[0002](0002-target-spec-ratification.md)'s residual register states the rule
as it binds this pass — "the market key must explicitly find any bound
*weaker than a previously ratified row* still competitive against named
public parts, or escalate to the operator — the relax-after-measured-FAIL
rule of [#372](https://github.com/2AMLogic/2am/issues/372), which applies to
those future passes". That rule exists precisely for this moment: the
superseded floor was ratified "understanding this" (the same residual's
wording), and the measured evidence now replaces a number no real part
meets with the +3σ figure drawn parts do. The market key's verdict must
either name the public parts the 26.68 dB bound remains competitive against,
or escalate to the operator — it may not pass silently on the reduction.
This is a supersede-on-new-evidence, not a relax-after-measured-FAIL of a
failed bench: no bench failed, no result was moved to make a pass — the
binding figure is the statistical bound the row's own committed
statistical-basis column (`3σ, mismatch MC N≥300 + process corners`)
always said it would bind by once #26's evidence existed.

**What the EE key must specifically rule on** (beyond accepting the number
itself): the **3σ-domain choice** documented in `sim/cmrr-mismatch/README.md`
"Choosing the 3σ domain" — the bound is computed in the **linear Acm
domain** (`Av0 − 20·log10(mean+3σ)`) because the dB image of the draw
distribution is heavy-tailed on the rejection-good side at the low-rail
near-cancellation corners: a draw that completes a structural cancellation
sends Acm tens of dB down with no risk attached, so a dB-domain mean−3σ
would be dominated by those benign outliers and lie arbitrarily below every
observed sample. The mismatch perturbation is roughly additive and
zero-mean around the structural value in the linear domain, so `mean + 3σ`
is the meaningful "+3σ part". The empirical dB-domain 1st percentile and
worst-observed-sample columns sit beside the bound in the record (grid worst
sample 25.94 dB at the binding point vs. the 26.68 dB bound — the expected
at-or-just-above-sample-minimum relation for a +3σ point at N = 300). The
linear-domain choice is the only judgment this ratification makes beyond
accepting the measured number; the EE key rules on it by name.

## Alternatives considered

- **Keep the systematic floor as the binding bound, record the
  mismatch-inclusive figure as context only** — rejected: the floor is a
  number no drawn part meets (it is below the floor at all 45 points), and
  DR-0002 pre-registered explicitly that the re-ratification "supersedes
  this systematic bound". Keeping it binding would leave the row's
  pass/fail verdict keyed to a nominal-device fiction after the honest
  figure exists — the exact evidence-free-regress the two-key mechanism
  exists to prevent, inverted.
- **Bind at the worst observed draw (25.94 dB at `mos_ss_-40C_1.08V`)** —
  rejected: the row's committed statistical basis is `3σ, mismatch MC
  N≥300 + process corners`, so the pre-registered binding figure is the +3σ
  point of the distribution, not one sample of the 300-draw population — a
  single observed minimum over-fits sampling noise at N = 300 (which is
  exactly why it sits at-or-just below the bound). The worst-sample figure
  stays in the record as scrutiny context.
- **Bind at the dB-domain mean−3σ** — rejected: at the near-cancellation
  corners the dB-domain distribution's tail is dominated by benign
  rejection-good outliers (the README's quantified example: 73 of 300
  samples at `mos_tt_27C_1.08V` below −10 dB Acm), making a dB-domain 3σ
  bound meaningless there — see "What the EE key must specifically rule on"
  above.
- **Ratify the envelope as a range (26.68–37.57 dB)** — rejected for the
  same reason DR-0002 rejected range-binding: a row needs one binding edge
  for a pass/fail verdict; the envelope stays in the row as context.
- **Wait for #17's offset re-ratification and ratify both statistical rows
  in one pass** — rejected: DR-0002 already rejected the "wait for all the
  MC passes and ratify the whole table at once" alternative once, and issue
  #32 (confirmed by Champion at promotion) explicitly allows this pass to
  run standalone; the offset row's own re-ratification remains a separate
  residual-(b) pass citing `sim/input-offset/records/mc-20260921-174056-0a509fb.{csv,md}`.

## Post-merge follow-through

- `spec/target-spec.md`'s CMRR row re-tags with this record's merge (the
  edits ride the same PR): the ratified bound cell becomes the
  mismatch-inclusive figure `[DR-4]`, the systematic floor is kept in-row
  as superseded context `[DR-2]`, the Status column moves to the new
  `Ratified, mismatch-inclusive [DR-4]` vocabulary, and the legend's tag
  and status-vocabulary entries update with it (issue #32's test plan).
- The offset row deliberately keeps its
  `Ratified, systematic only [DR-2] — mismatch-driven 3σ measured [P]
  (not yet re-ratified)` status; its re-ratification is the sibling
  residual-(b) pass, on #17's record.
- [0002](0002-target-spec-ratification.md)'s residual register is amended
  by this pass — residual (c) is discharged for the CMRR row (its offset
  companion, residual (b), stays open pending #17's own pass).

## Out of scope

- The offset row's statistical re-ratification (#17's record exists; the
  pass does not — it goes through its own PR under the same two-key
  mechanism, amending DR-0002 residual (b)).
- Any loaded-swing decision (DR-0002 residual (d)) and the HV stretch row
  (residual (e)) — untouched.
- Any PSRR mismatch axis: per #26's implementation guidance, no PSRR
  mismatch deck was opened; nothing in the cited record is evidence about
  PSRR+.
- Closed-loop CMRR: the figure is the open-loop transfer ratio `Av0/Acm`,
  same scope as #14; a closed-loop application's rejection also depends on
  its feedback network's noise gain.
- Per-sample differential-gain (`Av0`) perturbation: the record
  deliberately reuses the joined systematic `Av0` per sample (the
  deliberate harness-reuse choice that keeps the figure comparable to the
  floor); the per-sample `Av0` term is second-order on the ratio and would
  need a different bench (see `sim/cmrr-mismatch/README.md` "What this
  bench does not claim").

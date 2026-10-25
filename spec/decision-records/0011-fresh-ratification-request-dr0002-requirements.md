# 0011: Fresh ratification request for the unchanged DR-0002 requirements (issue #101)

- **Status**: `submitted for ratification` — this record's requirements
  (the unchanged DR-0002 table plus DR-0004's mismatch-inclusive CMRR bound,
  with the three disclosed FAILs) are ratified when, and only when, the PR
  that carries this status line has been ratified by **both keys** of the
  two-key mechanism ([2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)):
  an EE key (`RATIFY-KEY: ee`) and a market key (`RATIFY-KEY: market`), each
  posted as a PR review verdict, **neither key held by this PR's author or
  the design's author**. The merge commit of that PR is then the ratification
  record. This record supplies neither key, changes **no** limit, comparison
  rule, rounding convention, grade, `spec/target-spec.md` row,
  `spec/integrator.json` value or `sim/` / `signoff/` record. Until both
  keys are present and approving, the PR must not be merged and the limits
  remain only the conservative working limits. (Previous status:
  `submitted for fresh ratification`, preparation only, PR #293.)
- **Date**: 2026-10-20
- **Decided by**: operator direction (attended fleet-decide 2026-10-19,
  option 1: prepare a focused documentation-only fresh-ratification PR,
  recorded in the comments of #101); prepared by Builder agent, issue #101.
  The direction authorizes preparation only. It is not a key and approves no
  target value.
- **Related**: #101 (stays open; this PR is `Part of #101`, never
  `Closes`), PR #27 (carried DR-0002), [DR-0002](0002-target-spec-ratification.md),
  [DR-0009](0009-literal-limits-design-margin-direction.md) (the completed
  PR #27 search and the literal-limit direction),
  [DR-0004](0004-cmrr-mismatch-inclusive-ratification.md),
  [DR-0010](0010-statistical-row-yield-requirements-proposal.md),
  PR #292 (corrected open-loop evidence report),
  [`design/margin-plan.md`](../../design/margin-plan.md),
  `ratification/ee-key/`, `ratification/market-key/`

## Context

DR-0002 states that its bounds bind only when PR #27 is ratified by an EE
key and a market key, each posted as a PR review verdict by someone who is
neither the PR author nor the design author. DR-0009 recorded the search for
that trail (PR #27 reviews, timeline, repository and upstream-epic searches)
and found **no** key verdict: PR #27 has zero formal reviews and was merged
by the fleet bot. DR-0009 did not claim authority is absent everywhere, and
this record does not either.

This record does **not** reconstruct, infer or backdate any approval. It
does not cite the PR #27 merge, the Judge evaluation or the operator
direction as a key. It asks for new, real verdicts on the unchanged
requirements.

## What is submitted for review (unchanged)

The requirements are DR-0002's table, verbatim, plus DR-0004's
mismatch-inclusive CMRR bound. Nothing is added, relaxed or re-rounded.

| Row | Requirement (unchanged) | Source |
|---|---|---|
| Open-loop DC gain | >= 37.8 dB worst case | DR-0002 |
| GBW (CL = 2 pF) | >= 4.74 MHz worst case | DR-0002 |
| Phase margin | >= 60 deg | DR-0002 |
| Slew rate (CL = 2 pF) | >= 7.51 V/us worst edge | DR-0002 |
| Input-referred noise, 100 Hz - 1 MHz | <= 108.9 uVrms | DR-0002 |
| Input offset, systematic | <= 21.9 mV | DR-0002 |
| CMRR, mismatch-inclusive (+3 sigma of Acm, linear) | >= 26.68 dB | DR-0004 |
| PSRR+ (DC shelf) | >= 1.87 dB | DR-0002 |
| Output swing, CL = 2 pF, unloaded | headroom >= 251 mV (VDD), >= 141 mV (VSS); tracking span >= 0.571 V | DR-0002 |
| Quiescent power | <= 119.7 uA total VDD current | DR-0002 |
| Supply / temperature | 1.2 V +/-10 %, -40...+125 C | DR-0002 |

The reviewers should also see the operating conditions, loads and the
45-point `mos_tt/ss/ff/sf/fs` x `{-40, 27, 125} C` x `{1.08, 1.2, 1.32} V`
grid exactly as DR-0002 states them.

## Disclosed failures (raw values against the literal limits)

Current evidence is the newest characterization report,
`signoff/characterization/reports/20261020-052800-9a4a35d.{md,json}` (PR
#292), which grades raw values against the literal bounds with no rounding
or tolerance. As recorded there:

| Row | Literal limit | Raw worst case | Binding point | Grade |
|---|---|---|---|---|
| Input-referred noise | <= 108.9 uVrms | 108.949 uVrms | `mos_fs_125C_1.08V` | **FAIL** |
| Input offset, systematic | <= 21.9 mV | 21.9273527 mV | `mos_fs_125C_1.08V` | **FAIL** |
| Output swing, tracking span | >= 0.571 V | 0.570957773 V | `mos_ss_125C_1.08V` | **FAIL** |

The report's overall verdict is **FAIL** (3 FAIL, 5 MEASURED, 10 PASS,
1 PENDING; 9 of 12 ratified bounds PASS).

**Change since DR-0009.** DR-0009 listed four failing rows. The open-loop DC
gain row now grades PASS (minimum 38.2293 dB against >= 37.8 dB at
`mos_fs_125C_1.08V`) only because the report was re-minted from
`sim/open-loop-ac/records/20261015-103057-895d555.csv`, the grounded-`inn`
record that explicitly supersedes the AC-floating-`inn` record
`20260910-221601-22feaba` (bench defect fixed under #241). The threshold did
not move and no rounding was applied; the prior report with the 37.7812 dB
FAIL remains in `signoff/characterization/reports/` unedited. The same
re-selection also moves the GBW, phase-margin and quiescent-current readings
(now 8.06239 MHz, 61.9872 deg, 119.655 uA), all of which still clear their
unchanged bounds. This is a change of evidence, not of requirement.

The three remaining FAILs stay FAIL. No display-rounding convention is
proposed here; the raw worst cases round onto the bounds, but that is not a
pass under the literal comparison rule, and choosing a convention would be a
spec change that needs its own review.

## Unresolved evidence and authority gaps

These are stated so the reviewers do not mistake this request for closure:

1. **PR #27 approval trail** — still not located (DR-0009). This request is
   the remedy the operator chose; it does not declare PR #27 validly
   ratified, and DR-0004 (which builds on DR-0002) inherits the same open
   question.
2. **Downstream consumers of the re-selected record.** The historical
   CMRR/PSRR records and other results derived from the old Av0 keep their
   actual provenance. They were not recomputed against the corrected record.
   Any dependency that needs new evidence requires separately authorized
   simulation; none is authorized or run here.
3. **Offset statistical basis (DR-0002 residual (b)).** The systematic offset
   limit is submitted; the statistical basis is outstanding and is the
   subject of the DR-0010 proposal, which is itself unratified.
4. **Other DR-0002 residuals**: Area (`[TBD-12]`, needs layout), loaded
   output swing, and the HV stretch row remain un-ratified and out of scope.
5. **Design margin.** The three FAIL rows have no design fix. The
   coordinated plan is [`design/margin-plan.md`](../../design/margin-plan.md);
   it selects no circuit change.
6. **No new simulation.** Everything above is offline reading of committed
   records. No bench was re-run for this request.

## What the reviewers are asked to do

Through the existing ratification protocol (`ratification/ee-key/` and
`ratification/market-key/`), on this PR:

- The **EE key** assesses whether the unchanged requirements are supported
  by the cited evidence, including the corrected open-loop record, and the
  disclosed FAILs.
- The **market key** assesses whether the unchanged requirements are
  competitive; per DR-0002 and #372, any bound weaker than a previously
  ratified one is found competitive or escalated.
- Neither reviewer may be this PR's author or the design's author.
- If either key concludes that the unchanged requirements or the three
  disclosed FAILs need an operator tradeoff (for example a restated bound or
  a rounding convention), it follows the protocol's escalation path to the
  operator. A requirement change is a new proposal reviewed on its own, not
  an edit to this record.

## Decision

None. This record takes no decision on any number. The ratification event
is a pair of real, non-author, approving key verdicts on the PR that carries
the `submitted for ratification` status above (or on a successor the keys
name); the operator then ratifies. Until those verdicts exist, status and
provenance citations elsewhere must say "ratification pending" and must not
mark the PR #27 gap closed.

## Out of scope

- Supplying either key, or treating the operator direction, the Judge, the
  Champion or the fleet bot as a key.
- Changing any limit, the comparison rule, rounding, or any grade.
- Editing or regenerating any historical report, record or FAIL.
- Any simulation, EDA campaign, spending, provisioning, circuit change,
  merge authority or closure of #101.

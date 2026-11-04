# 0011: Fresh ratification request for the DR-0002 requirements, as revised (issue #101)

- **Status**: `submitted for ratification` — this record's requirements
  (the rows of the "What is submitted for review" table only: GBW, phase
  margin, slew rate, PSRR+ restated to >= 26.9 dB, quiescent power and
  supply / temperature; every row listed under "Rows not submitted as
  bounds", including open-loop gain, CMRR, swing headroom, noise, offset and
  tracking span, is a measured value with status only and is **not**
  ratified) are
  ratified when, and only when, the PR
  that carries this status line has been ratified by **both keys** of the
  two-key mechanism ([2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)):
  an EE key (`RATIFY-KEY: ee`) and a market key (`RATIFY-KEY: market`), each
  posted as a PR review verdict, **neither key held by this PR's author or
  the design's author**. The merge commit of that PR is then the ratification
  record. This record supplies neither key. It changes **no** limit other
  than the Revision 3 PSRR+ restatement below (>= 26.9 dB, superseding the
  DR-0002 1.87 dB floor) and the Revision 4 withdrawal of six rows from
  submission, and changes no comparison rule, rounding
  convention, grade, `spec/target-spec.md` row, `spec/integrator.json` value
  or `sim/` / `signoff/` record. **Superseded pending gap 6:** the PSRR+
  1.87 dB floor still recorded in `spec/target-spec.md` (line 127),
  `spec/integrator.json` (`psrr_db_worst_min_dc_shelf: 1.87`),
  `signoff/characterization/selection.json` (pins `707b34c`) and the minted
  report `20261020-052800-9a4a35d` (1.8709 dB) is **superseded by the
  >= 26.9 dB bound in this record once ratified**; those files are not edited
  here and keep grading the withdrawn floor until gap 6 carries them to
  26.9 dB, repoints `selection.json` to `f8ef0ba` and re-mints. Until both
  keys are present and approving, the PR must not be merged and the limits
  remain only the conservative working limits. (Previous status:
  `submitted for fresh ratification`, preparation only, PR #293.)
  **Revision 2** (operator send-back after the two-key review of head
  `44d9e7ec`, round 20261031-r5): the three rows whose own records fail their
  working limit (noise, systematic offset, tracking span) are no longer
  submitted as bounds, only as measured values with status; the PSRR+ row
  cites the current record; and the record states what the block is for at
  these numbers. Both keys re-run on the revised head.
  **Revision 3** (operator ruling r5-q75 option 3 on the market-key
  escalation at head `e14ccdc2`: restate the bounds): the PSRR+ row is
  restated to >= 26.9 dB and the two documentation fixes land. The CMRR,
  gain and swing rows are **not yet restated**; they need re-derivation or a
  design change and are tracked separately. Both keys must re-review the
  revised head.
  **Revision 4** (operator send-back r5-q89 option 2, items A-C): open-loop
  DC gain (>= 37.8 dB), mismatch-inclusive CMRR (>= 26.68 dB) and the swing
  headroom rows (>= 251 / >= 141 mV) are moved out of the submitted table
  into "Rows not submitted as bounds", as Revision 2 did for noise, offset
  and span; their restatement (#332, #333) is not landed on this branch.
  The PSRR+ supersession is stated in this Status clause (above), and the
  remaining "unchanged" wording is corrected. Both keys re-review, because
  the submitted rows changed.
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
direction as a key. It asks for new, real verdicts on the requirements
as revised here.

## What is submitted for review

The requirements are the rows of DR-0002's table below, **minus the six rows
listed under "Rows not submitted as bounds" below**. The PSRR+ row is
restated (Revision 3); no other submitted number is added, relaxed or
re-rounded.

| Row | Requirement | Source |
|---|---|---|
| GBW (CL = 2 pF) | >= 4.74 MHz worst case | DR-0002 |
| Phase margin | >= 60 deg | DR-0002 |
| Slew rate (CL = 2 pF) | >= 7.51 V/us worst edge | DR-0002 |
| PSRR+ (DC shelf) | >= 26.9 dB worst case (restated by operator ruling r5-q75 option 3; supersedes the DR-0002 1.87 dB floor; evidence is the current record, see below) | Operator ruling, revision 3 |
| Quiescent power | <= 119.7 uA total VDD current | DR-0002 |
| Supply / temperature | 1.2 V +/-10 %, -40...+125 C | DR-0002 |

The reviewers should also see the operating conditions, loads and the
45-point `mos_tt/ss/ff/sf/fs` x `{-40, 27, 125} C` x `{1.08, 1.2, 1.32} V`
grid exactly as DR-0002 states them.

## Rows not submitted as bounds (measured value and status only)

The EE key found that the DR-0002 noise, offset and span limits are the
4-significant-figure display rounding of the very extremum that fails them,
with no derivation independent of the measurement. Revision 4 adds open-loop
DC gain, mismatch-inclusive CMRR and the swing headroom rows, which the
operator sent back (r5-q75, r5-q89) pending restatement. This record
therefore does **not** ask either key to ratify a bound for any of these
rows. They are
presented as measured values with their status; they stay unratified
working limits (`[P]`) until the DR-0009 design-margin path
([`design/margin-plan.md`](../../design/margin-plan.md)) or a separate
restated-bound record reviewed on its own selects a bound with margin. This
record picks no margin amount, tolerance or rounding convention and relaxes
nothing: the DR-0002 working limits and the literal comparison rule are
untouched.

| Row | Measured worst case | Status |
|---|---|---|
| Open-loop DC gain | 38.2293 dB (`mos_fs_125C_1.08V`) | PASS against the 37.8 dB working limit; no bound submitted (restatement pending, #332) |
| CMRR, mismatch-inclusive (+3 sigma of Acm, linear; DR-0004) | 26.6826 dB (`mos_ss_-40C_1.08V`) | meets the 26.68 dB working limit by 0.0026 dB; no bound submitted (derivation-or-design choice pending, #332) |
| Output swing, headroom from VDD / VSS | 251.491128 mV / 141.167273 mV (`mos_fs_-40C_1.08V` / `mos_ff_-40C_1.08V`) | PASS against the 251 / 141 mV working limits; no bound submitted (restatement as an output range pending, #333) |
| Input-referred noise, 100 Hz - 1 MHz | 108.949 uVrms (`mos_fs_125C_1.08V`) | FAIL against the 108.9 uVrms working limit; no bound submitted |
| Input offset, systematic | 21.9273527 mV (`mos_fs_125C_1.08V`) | FAIL against the 21.9 mV working limit; no bound submitted |
| Output swing, tracking span | 0.570957773 V (`mos_ss_125C_1.08V`) | FAIL against the 0.571 V working limit; no bound submitted |

All of these remain unratified working limits (`[P]`) with no ratified bound.

## PSRR+ evidence: current record

The PSRR+ record previously cited,
`sim/cmrr-psrr/records/20260921-151815-707b34c`, is **superseded for the
PSRR measurement itself** (not merely stale in its Av0 join): it measured
with `inn` AC-floating, which produced the "~1.5 Hz supply-path zero" and
the ~1.30 dB worst in-band figure (issue #241). The current record is
`sim/cmrr-psrr/klt/records/20261015-103521-0f41068.*`, joined to
`sim/open-loop-ac/records/20261015-103057-895d555`: PSRR+ (DC shelf) is
**26.90 dB worst** (`mos_fs_125C_1.08V`) to 36.33 dB best, all 45 corners
above 1.87 dB, with the zero gone. This record submits the restated >= 26.9 dB
bound (operator ruling r5-q75 option 3, replacing the 1.87 dB floor). The
current records `20261015-103521-0f41068` and `20261027-011449-f8ef0ba`
agree on a raw worst case of 26.9010753 dB at `mos_fs_125C_1.08V`, so the
bound clears by about 0.001 dB under the literal comparison rule. That is
essentially no margin; whether to require more is for the EE key.
The 1.87 dB floor was measured on the superseded record and is withdrawn; the zero and in-band-degradation
text of DR-0002 / `spec/target-spec.md` is **withdrawn from what is
submitted** as a bench artifact. Re-pointing `selection.json` (still on
707b34c) and correcting the `spec/target-spec.md` context strings is a
separate change through `spec/` (gap 6).

## What the block is for at these numbers

The market key (head `44d9e7ec`) found the CMRR (26.68 dB), PSRR+ floor and
other rows uncompetitive against catalog parts (e.g. LMV321 / NCS2001 /
TLV9001 CMRR minima of 50-63 dB) and escalated. This record does not claim
catalog competitiveness. The block is an **open-source canary and
cross-foundry comparison vehicle**: a two-stage Miller op-amp whose purpose is
to exercise the open SG13G2 flow and `klt` end to end and to give the
sg13g2 / gf180 / sky130 twin a like-for-like result set, with every number
derived from this PDK's models. It is a low-power (<= 119.7 uA), 1.2 V core,
2 pF-load embedded-style amplifier, not a precision or general catalog
part, and its CMRR, PSRR+, noise, offset and swing figures should be read
that way. Whether to accept the gaps as a canary, declare a non-precision
class, or restate bounds is the operator tradeoff the market key asked for;
this record does not pre-empt it.

## Disclosed failures (raw values against the literal limits)

These are the three rows above, kept for the audit trail. Current evidence is the newest characterization report,
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
bounds. This is a change of evidence, not of requirement.

The three remaining FAILs stay FAIL and, per the section above, are not
submitted as bounds (nor are the PASSing gain, CMRR and headroom rows). No display-rounding convention is
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
   limit is not submitted (measured value with status only, see "Rows not
   submitted as bounds"); the statistical basis is outstanding and is the
   subject of the DR-0010 proposal, which is itself unratified.
4. **Other DR-0002 residuals**: Area (`[TBD-12]`, needs layout), loaded
   output swing, and the HV stretch row remain un-ratified and out of scope.
5. **Design margin.** The three FAIL rows have no design fix. The
   coordinated plan is [`design/margin-plan.md`](../../design/margin-plan.md);
   it selects no circuit change.
6. **PSRR selection and stale context.** `signoff/characterization/selection.json`
   still pins the superseded PSRR record, and `spec/target-spec.md` context
   strings (Av0 envelope, GBW envelope, 76.4 deg phase margin, the 1.5 Hz
   zero) predate the corrected bench. Not edited here (spec changes go
   through `spec/` with their own record).
7. **No new simulation.** Everything above is offline reading of committed
   records. No bench was re-run for this request.

## What the reviewers are asked to do

Through the existing ratification protocol (`ratification/ee-key/` and
`ratification/market-key/`), on this PR:

- The **EE key** assesses whether the submitted requirements are supported
  by the cited evidence, including the corrected open-loop record and the
  current PSRR record, and the measured-value-only rows.
- The **market key** assesses whether the submitted requirements are
  competitive; per DR-0002 and #372, any bound weaker than a previously
  ratified one is found competitive or escalated.
- Neither reviewer may be this PR's author or the design's author.
- If either key concludes that the submitted requirements or the three
  disclosed FAILs need an operator tradeoff (for example a restated bound or
  a rounding convention), it follows the protocol's escalation path to the
  operator. A requirement change is a new proposal reviewed on its own, not
  an edit to this record.

## Decision

None. This record decides no number beyond the Revision 3 PSRR+ restatement
(operator ruling r5-q75 option 3) and the Revision 4 withdrawal of six rows
from submission (operator send-back r5-q89 option 2). The ratification event
is a pair of real, non-author, approving key verdicts on the PR that carries
the `submitted for ratification` status above (or on a successor the keys
name); the operator then ratifies. Until those verdicts exist, status and
provenance citations elsewhere must say "ratification pending" and must not
mark the PR #27 gap closed.

## Out of scope

- Supplying either key, or treating the operator direction, the Judge, the
  Champion or the fleet bot as a key.
- Changing any limit other than the PSRR+ restatement above, the comparison
  rule, rounding, or any grade.
- Editing or regenerating any historical report, record or FAIL.
- Any simulation, EDA campaign, spending, provisioning, circuit change,
  merge authority or closure of #101.

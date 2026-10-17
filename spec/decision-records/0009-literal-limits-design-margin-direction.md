# 0009: Literal limits retained; coordinated design-margin plan prepared (issue #101)

- **Status**: direction record. It supplies **neither** the EE key nor the
  market key, changes **no** limit, comparison rule, rounding convention,
  guard band or PASS/FAIL grade, and selects no circuit change. No
  `spec/target-spec.md` row, `spec/integrator.json` value,
  `signoff/characterization/selection.json` entry or `sim/` / `signoff/`
  record is edited by the PR that carries it. It records an operator
  ruling and an unresolved provenance gate, and points at the plan that
  prepares the design work.
- **Date**: 2026-10-17
- **Decided by**: operator ruling (attended session 2026-10-16, batch 16 Q3
  option 2, recorded 2026-10-17 05:42 UTC, in the comments of issue #101);
  recorded here by Builder agent, issue #101. The ruling is the authority
  for the direction only.
- **Related**: #101 (this issue; stays open), #239 (offset contribution to
  the same plan), #90 / PR #94 (the characterization report that surfaced
  the four FAIL rows), PR #27 (carried
  [DR-0002](0002-target-spec-ratification.md)), #16, #106,
  [`design/margin-plan.md`](../../design/margin-plan.md) (the plan)

## Context

Four bounds ratified by [DR-0002](0002-target-spec-ratification.md) are
stricter than the raw worst case of the records DR-0002 cites, which only
round onto them. The characterization report compares raw values against
the literal bound, so these rows grade FAIL:

| Row | Literal limit | Cited raw extremum | Binding point |
|---|---|---|---|
| Open-loop DC gain | >= 37.8 dB | 37.7812 dB | `mos_fs_125C_1.08V` |
| Input-referred noise, 100 Hz - 1 MHz integrated | <= 108.9 µVrms | 108.949 µVrms | `mos_fs_125C_1.08V` |
| Input-offset, systematic | <= 21.9 mV | 21.9273527 mV | `mos_fs_125C_1.08V` |
| Output swing, tracking span (CL = 2 pF, unloaded) | >= 0.571 V | 0.570957773 V | `mos_ss_125C_1.08V` |

The original report offered three paths (restate the bounds, ratify a
displayed-decimal comparison convention, keep the bounds literal and gain
margin). Those alternatives remain archived in the body of #101.

## Decision

The operator selected the third path:

1. **All four literal limits stand**, as written in `spec/target-spec.md`
   section 2, with their conditions, loads and PVT coverage.
2. **All four raw grades stand as FAIL** against the cited extrema above.
   No display-rounding convention is adopted; no new PASS is created.
3. **One coordinated design-margin study/PR plan** covers all four rows,
   with #239 as the offset contribution (not a competing specification).
   It is [`design/margin-plan.md`](../../design/margin-plan.md). It selects
   no circuit change, topology, clock, numeric tolerance or margin amount.
4. **Authorized by the ruling**: source and evidence study, and planning.
   **Not authorized**: any simulation or EDA campaign, compute launch,
   spending, provisioning, merge, closure, regeneration or edit of any
   historical record, or any numerical waiver.

This record is not a ratification. DR-0002's two-key mechanism remains the
only route to change a ratified bound, and nothing here changes it.

## PR #27 ratification-provenance gate

Issue #101 asks that the independent PR #27 provenance discrepancy be
reconciled: locate valid authority for the two keys DR-0002 requires, or
record the gate as unresolved.

**What DR-0002 requires.** Its Status says the bounds bind only when PR #27
is ratified by an EE key (`RATIFY-KEY: ee`) and a market key
(`RATIFY-KEY: market`), each posted as a PR review verdict, neither held by
the PR or design author, and that "the merge commit of that PR is the
ratification record".

**What was searched (2026-10-17, read-only).**

- PR #27 via `gh pr view`: 0 formal reviews; two comments, both from
  `loom-fleet-dispatch`. The first is a Judge evaluation (APPROVED at
  `2b166ea`) that verifies the bounds against the bench records and says
  nothing about keys. The second says the merge is "deferred by design"
  until both keys approve on the PR and names the required keys.
- PR #27 timeline events (`issues/27/events`): labeled/unlabeled by the
  fleet bot, then `merged` by `loom-fleet-dispatch[bot]`. No event shows a
  key-holder acting and no `loom:auto-merge-ok` label appears.
- `gh api pulls/27/reviews`: empty.
- Repository issue search for `RATIFY-KEY`, `ratification key` and
  `loom:auto-merge-ok`. Hits are #16 (the ratification issue), #32 and #114
  (later re-ratifications), #106 (reviewer-tree install), and #3, #99, #100,
  #101, #162, #239, which mention the keys in passing; a follow-up
  read of the bodies and comments of #3, #16, #32, #99, #100, #101, #106,
  #114, #162 and #239 (grep for `RATIFY-KEY`, `ratification key`,
  `loom:auto-merge-ok`, `EE key`, `market key`) found no key verdict for
  PR #27. The
  `loom:auto-merge-ok` search returned nothing. Issue #16's comments are Curator/Champion
  evaluations; #106's comments say merge alone does not prove two-key
  ratification.
- `git log --all --grep='RATIFY-KEY'` on the repository: no commit.
- `ratification/ee-key/` and `ratification/market-key/` hold rubric and
  manifest files (the reviewer trees), not verdicts.

**Finding: unresolved.** Within that search no EE or market key verdict
exists for PR #27, and the merge was performed by the fleet bot. The
merge commit `65f5fb4` is therefore the only candidate ratification record,
and by DR-0002's own text a merge alone does not establish it. This record
does **not** assert that no authority exists elsewhere: key verdicts may
have been given in a venue this search did not cover (for example the
upstream epic [2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)
or an operator channel). A follow-up read of that epic (body and comments, 2026-10-17) found it
names other repositories' PRs (sky130-sar-adc#46, sky130-pll#53,
gf180-pll#158, sky130-bandgap#197, gf180-ldo#127, sky130-ldo#50) and
no verdict for sg13g2-opamp PR #27; it was not searched beyond that text.

**Consequences, none of which is a decision taken here.**

- The provenance gate stays **open**. It is independent of #101's design
  work and is not cleared by this direction.
- The current limits stay in force as the conservative position; they are
  not withdrawn on provenance grounds.
- This operator direction is neither key, and a later holder of either key
  would still need to act through the DR-0002 mechanism.
- Anyone holding a valid verdict for PR #27 can close the gate by linking it
  from this record in a follow-up edit. Records that build on DR-0002 (for
  example DR-0004) inherit the same open question and are not edited here.

## Finding for the keys: the DC-gain FAIL traces to a superseded record

While tracing the binding points for the plan, the gain row's cited
37.7812 dB was found to come from
`sim/open-loop-ac/records/20260910-221601-22feaba.csv`, measured with `inn`
AC-floating. That bench defect was fixed under #241, and
`sim/open-loop-ac/records/20261015-103057-895d555.csv` (grounded `inn`,
which supersedes the old record and says so in its header) reports
38.2293 dB at the same corner, with the batch `klt sim` envelope
`sim/open-loop-ac/klt/records/20261016-161057-8caa272.ac.sim.json` agreeing
at 38.229 dB. `signoff/characterization/selection.json` still pins the old
record, which is why the report grades DC gain FAIL.

This record **does not** treat that as a PASS, repin the selection or edit
the spec. The ruling preserves the cited extremum and raw FAIL, so the
gain row stays FAIL here. Whether to repoint the characterization
selection at the grounded-`inn` record (which changes graded content and
needs a newly minted characterization report) is a separate decision for
the operator and the keys. The plan records both numbers side by side.

## Consequences

- The four rows remain FAIL until a future, separately authorized design
  change or a ratified specification change says otherwise.
- A future sizing change needs its own issue, a citation of the gm/ID study
  (`sim/gm-id-characterization/`), normal review, and, if it changes
  measured rows, a new characterization report from an actually authorized
  run. Consumer-facing numbers in `spec/consumers.md` and
  `spec/integrator.json` follow the consumer-consistency rules in the plan.
- #101 stays open. Completing the plan is not numerical acceptance and not
  signoff.

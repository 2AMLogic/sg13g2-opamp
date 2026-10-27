# Work Plan

This roadmap is generated from the repository's current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews

## Important

`loom:important`; taken before unlabelled work.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7)
- **#100**: sim: express the output-swing bench as a klt sim request (T1 item 5 coverage, follow-up to #85)
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR)
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record
- **#237**: design: reconcile schematic device representation with drawn fingering before citing post-layout (T1 item 7)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7)
- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews

## In Progress

Issues currently being built (`loom:building`).

- **#101**: Prepare a four-row design-margin plan while preserving literal limits and raw FAILs

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#302**: docs: request EE and market key review of DR-0010

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)

## Proposed

Issues carrying `loom:curated`.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(curated)*
- **#100**: sim: express the output-swing bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(curated)*
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record *(curated)*
- **#237**: design: reconcile schematic device representation with drawn fingering before citing post-layout (T1 item 7) *(curated)*
- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 1 |
| Important | 5 |
| Ready (`loom:issue`) | 3 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 1 |
| Curated | 6 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

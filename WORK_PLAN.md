# Work Plan

This roadmap is generated from the repository's current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#99**: sim: express the PSRR bench as a klt sim request (T1 item 5 coverage, follow-up to #85)

## Important

`loom:important`; taken before unlabelled work.

- **#100**: sim: express the output-swing bench as a klt sim request (T1 item 5 coverage, follow-up to #85)
- **#237**: design: reconcile schematic device representation with drawn fingering before citing post-layout (T1 item 7)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## In Progress

Issues currently being built (`loom:building`).

- **#99**: sim: express the PSRR bench as a klt sim request (T1 item 5 coverage, follow-up to #85)
- **#271**: Consolidate the four serialized-cell checkers in characterization generate.py into one helper

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#270**: docs(signoff): count PSRR's complete klt sim request in item-5 summary
- **#272**: refactor: consolidate serialized-cell checkers into one _cell_problem helper

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(curated)*
- **#99**: sim: express the PSRR bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#100**: sim: express the output-swing bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(curated)*
- **#237**: design: reconcile schematic device representation with drawn fingering before citing post-layout (T1 item 7) *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 2 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 2 |
| Approved PRs awaiting merge | 0 |
| Curated | 5 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

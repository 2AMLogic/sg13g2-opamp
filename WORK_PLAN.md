# Work Plan

This roadmap is generated from the repository's current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

_None._

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#85**: sim: express the open-loop AC bench as a `klt sim` request, the first gradable envelope toward T1 item 5

## In Progress

Issues currently being built (`loom:building`).

- **#96**: sim: express the input-noise bench as a klt sim request (T1 item 5 coverage, follow-up to #85)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#102**: sim: open-loop AC bench as klt sim AC + OP requests with a harness comparison (no envelope yet: fleet runner klt 0.5.0)

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(curated)*
- **#43**: README: embed the fleet burndown chart (one line) *(curated)*
- **#85**: sim: express the open-loop AC bench as a `klt sim` request, the first gradable envelope toward T1 item 5 *(curated)*
- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(curated)*
- **#95**: sim: express the slew-rate bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#96**: sim: express the input-noise bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#97**: sim: express the input-offset bench (systematic half) as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 8 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

# Work Plan

This roadmap is generated from the repository's current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

- **#164**: ci: protect nested klt record trees with the append-only evidence gate

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#85**: sim: express the open-loop AC bench as a `klt sim` request, the first gradable envelope toward T1 item 5

## In Progress

Issues currently being built (`loom:building`).

_None._

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#102**: sim: open-loop AC bench as klt sim AC + OP requests with a harness comparison (no envelope yet: fleet runner klt 0.5.0)

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#164**: ci: protect nested klt record trees with the append-only evidence gate

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(curated)*
- **#43**: README: embed the fleet burndown chart (one line) *(curated)*
- **#85**: sim: express the open-loop AC bench as a `klt sim` request, the first gradable envelope toward T1 item 5 *(curated)*
- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(curated)*
- **#95**: sim: express the slew-rate bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#96**: sim: express the input-noise bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#97**: sim: express the input-offset bench (systematic half) as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#99**: sim: express the PSRR bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#100**: sim: express the output-swing bench as a klt sim request (T1 item 5 coverage, follow-up to #85) *(curated)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*
- **#180**: CI: signoff/test_regenerate.py is never run; discover all tests instead of hand-listing *(architect)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 0 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 1 |
| Curated | 10 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

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
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR)
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record
- **#237**: design: reconcile schematic device representation with drawn fingering before citing post-layout (T1 item 7)
- **#325**: sim: express the input-cmr (ICMR) bench as a klt sim request so the drawn-fingering re-run (#237) can run on the batch fleet
- **#326**: decision: how do the offset-MC and CMRR-mismatch-MC rows follow the drawn-fingering netlist change (#237)
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)
- **#353**: signoff: cite the committed 45-corner output-swing envelope in T1 item 5 (replace three stale gap rows)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#101**: Prepare a four-row design-margin plan while preserving literal limits and raw FAILs
- **#311**: Bump klayout-tools pin 0.6.0, 44cc42323184 → 0.8.0
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)

## In Progress

Issues currently being built (`loom:building`).

_None._

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#302**: docs: request EE and market key review of DR-0010

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)
- **#352**: docs: roadmap as of 2026-11-13

## Proposed

Issues carrying `loom:curated`.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(curated)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(curated)*
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record *(curated)*
- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews *(curated)*
- **#311**: Bump klayout-tools pin 0.6.0, 44cc42323184 → 0.8.0 *(curated)*
- **#312**: Move layout/klt-pin.txt to klt 0.8.0: re-transcribe DECK_MIN_UM and regenerate layout evidence *(curated)*
- **#325**: sim: express the input-cmr (ICMR) bench as a klt sim request so the drawn-fingering re-run (#237) can run on the batch fleet *(curated)*
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling) *(curated)*
- **#342**: design: raise PSRR+ via bias/topology change, re-run 45 corners, carry bounds into spec (PR #303 operator ruling) *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*
- **#355**: Split signoff/characterization/generate.py (2,972 lines) along its existing section banners *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 1 |
| Important | 8 |
| Ready (`loom:issue`) | 4 |
| In Progress (`loom:building`) | 0 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 2 |
| Curated | 9 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

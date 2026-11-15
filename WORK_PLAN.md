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

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#101**: Prepare a four-row design-margin plan while preserving literal limits and raw FAILs
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)
- **#387**: test_klt_envelope metavar assertion depends on terminal width (COLUMNS)

## In Progress

Issues currently being built (`loom:building`).

- **#380**: Four more copies of the op_pass DC-sanity rule survive #366's dedupe (cmrr-mismatch x2, input-offset, post-layout)
- **#390**: csv_summary.numeric() cannot distinguish a wholly-absent metric column from an unusable cell, so a writer/summariser column-name drift now prints "n/a" into a record instead of failing the sweep

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#302**: docs: request EE and market key review of DR-0010

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)
- **#394**: refactor: fold the last four op_pass DC-sanity copies into one shared predicate
- **#395**: fix: csv_summary raises KeyError on absent column, skips short-row None cells

## Proposed

Issues carrying `loom:curated`.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(curated)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(curated)*
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record *(curated)*
- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews *(curated)*
- **#312**: Move layout/klt-pin.txt to klt 0.8.0: re-transcribe DECK_MIN_UM and regenerate layout evidence *(curated)*
- **#325**: sim: express the input-cmr (ICMR) bench as a klt sim request so the drawn-fingering re-run (#237) can run on the batch fleet *(curated)*
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling) *(curated)*
- **#342**: design: raise PSRR+ via bias/topology change, re-run 45 corners, carry bounds into spec (PR #303 operator ruling) *(curated)*
- **#380**: Four more copies of the op_pass DC-sanity rule survive #366's dedupe (cmrr-mismatch x2, input-offset, post-layout) *(curated)*
- **#387**: test_klt_envelope metavar assertion depends on terminal width (COLUMNS) *(curated)*
- **#390**: csv_summary.numeric() cannot distinguish a wholly-absent metric column from an unusable cell, so a writer/summariser column-name drift now prints "n/a" into a record instead of failing the sweep *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 1 |
| Important | 7 |
| Ready (`loom:issue`) | 4 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 3 |
| Curated | 11 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

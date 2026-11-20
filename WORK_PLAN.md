# Work Plan

This roadmap is generated from the repository's current GitHub label state.

<!-- guide:plan-body:start -->
_Generated: 2026-11-20T22:35:48Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews *(held)*
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)

## Important

`loom:important`; taken before unlabelled work.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(held)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(held)*
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record *(held)*
- **#237**: design: reconcile schematic device representation with drawn fingering before citing post-layout (T1 item 7) *(held)*
- **#325**: sim: express the input-cmr (ICMR) bench as a klt sim request so the drawn-fingering re-run (#237) can run on the batch fleet *(held)*
- **#326**: decision: how do the offset-MC and CMRR-mismatch-MC rows follow the drawn-fingering netlist change (#237) *(held)*
- **#428**: sim preflight: on batch-fleet runs take OSDI identity from the runner-reported digests, not a locally built .build-manifest, then write the #325 input-cmr record
- **#429**: post-layout: attribute the klt 0.9.0 extracted phase-margin miss (ff / 1.32 V / 125 C) and the tt / 1.08 V / 27 C non-convergence, then route #312 to a design or klt follow-up
- **#430**: design: post-layout phase margin misses the 60 deg bound at mos_ff/1.32V/125C (extracted PM 59.81 deg; ng=1-vs-drawn representation -1.64 deg, parasitics -0.53 deg)

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)
- **#428**: sim preflight: on batch-fleet runs take OSDI identity from the runner-reported digests, not a locally built .build-manifest, then write the #325 input-cmr record
- **#430**: design: post-layout phase margin misses the 60 deg bound at mos_ff/1.32V/125C (extracted PM 59.81 deg; ng=1-vs-drawn representation -1.64 deg, parasitics -0.53 deg)
- **#432**: Remove the circular dpkg-deb recovery instructions from the OSDI build

## In Progress

Issues currently being built (`loom:building`).

- **#429**: post-layout: attribute the klt 0.9.0 extracted phase-margin miss (ff / 1.32 V / 125 C) and the tt / 1.08 V / 27 C non-convergence, then route #312 to a design or klt follow-up

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#302**: docs: request EE and market key review of DR-0010
- **#431**: sim: attribute the 0.9.0 post-layout PM miss (design finding) and TT gmin non-convergence (solver path)

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)

## Proposed

Issues carrying `loom:curated`.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7) *(curated)* *(held)*
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(curated)* *(held)*
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record *(curated)* *(held)*
- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews *(curated)* *(held)*
- **#312**: Move layout/klt-pin.txt to klt 0.8.0: re-transcribe DECK_MIN_UM and regenerate layout evidence *(curated)* *(held)*
- **#325**: sim: express the input-cmr (ICMR) bench as a klt sim request so the drawn-fingering re-run (#237) can run on the batch fleet *(curated)* *(held)*
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling) *(curated)*
- **#342**: design: raise PSRR+ via bias/topology change, re-run 45 corners, carry bounds into spec (PR #303 operator ruling) *(curated)* *(held)*
- **#429**: post-layout: attribute the klt 0.9.0 extracted phase-margin miss (ff / 1.32 V / 125 C) and the tt / 1.08 V / 27 C non-convergence, then route #312 to a design or klt follow-up *(curated)*
- **#430**: design: post-layout phase margin misses the 60 deg bound at mos_ff/1.32V/125C (extracted PM 59.81 deg; ng=1-vs-drawn representation -1.64 deg, parasitics -0.53 deg) *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 2 |
| Important | 9 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 5 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 2 |
| Approved PRs awaiting merge | 1 |
| Curated | 10 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

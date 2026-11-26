# Work Plan

This roadmap is generated from the repository's current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#300**: Open the ratification PRs for DR-0011 (#101) and then DR-0010 (#108), with both key reviews
- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)

## Important

`loom:important`; taken before unlabelled work.

- **#86**: signoff: first `klt pex` post-layout run on opamp_core.gds (T1 item 7)
- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR)
- **#108**: spec: ratify per-draw limits and target_yield for the statistical rows (offset random half, CMRR) -- needs a decision record
- **#237**: design: reconcile schematic device representation with drawn fingering before citing post-layout (T1 item 7)
- **#325**: sim: express the input-cmr (ICMR) bench as a klt sim request so the drawn-fingering re-run (#237) can run on the batch fleet
- **#326**: decision: how do the offset-MC and CMRR-mismatch-MC rows follow the drawn-fingering netlist change (#237)
- **#428**: sim preflight: on batch-fleet runs take OSDI identity from the runner-reported digests, not a locally built .build-manifest, then write the #325 input-cmr record
- **#429**: post-layout: attribute the klt 0.9.0 extracted phase-margin miss (ff / 1.32 V / 125 C) and the tt / 1.08 V / 27 C non-convergence, then route #312 to a design or klt follow-up
- **#435**: Resubmit the 1 MΩ and 1 GΩ TT substrate-tie probes and record the results on PR #431

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)
- **#428**: sim preflight: on batch-fleet runs take OSDI identity from the runner-reported digests, not a locally built .build-manifest, then write the #325 input-cmr record

## In Progress

Issues currently being built (`loom:building`).

- **#503**: Reproduce the output-swing audit from batch DC sweeps
- **#514**: Bind batch CMRR and PSRR envelopes into the cmrr-psrr characterization record
- **#543**: Factor duplicated batch klt envelope loaders and drop two unused constants in signoff/characterization/records.py

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#544**: refactor: share batch klt envelope validation helpers and drop dead constants

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)
- **#333**: docs(DR-0011): revision 5 restates swing as output range, discloses CMRR/gain gaps
- **#490**: docs: record the open TT tie measurements and replacement procedure
- **#528**: characterization: bind batch CMRR/PSRR envelopes behind a cmrr_psrr_klt audit
- **#538**: feat(signoff): admit batch two-pass swing evidence via swing_raw_audit

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
- **#429**: post-layout: attribute the klt 0.9.0 extracted phase-margin miss (ff / 1.32 V / 125 C) and the tt / 1.08 V / 27 C non-convergence, then route #312 to a design or klt follow-up *(curated)*
- **#435**: Resubmit the 1 MΩ and 1 GΩ TT substrate-tie probes and record the results on PR #431 *(curated)*
- **#502**: Reproduce the input-noise spectrum audit from a batch run *(curated)*
- **#503**: Reproduce the output-swing audit from batch DC sweeps *(curated)*
- **#505**: Measure systematic CMRR and PSRR+ for the same DUT on the batch fleet *(curated)*
- **#514**: Bind batch CMRR and PSRR envelopes into the cmrr-psrr characterization record *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 2 |
| Important | 9 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 3 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 5 |
| Curated | 14 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

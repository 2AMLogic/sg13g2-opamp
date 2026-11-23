# Work Plan

This roadmap is generated from the repository's current GitHub label state.

<!-- guide:plan-body:start -->
_Generated: 2026-11-23T04:24:42Z (snapshot; compare against live labels)_
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
- **#430**: design: post-layout phase margin misses the 60 deg bound at mos_ff/1.32V/125C (extracted PM 59.81 deg; ng=1-vs-drawn representation -1.64 deg, parasitics -0.53 deg)
- **#435**: Collect the two substrate-tie batch results for PR #431 on a batch-enabled worker

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#332**: DR-0011: re-derive CMRR bound, re-check gain/swing vs market comps, restate swing headroom (PR #303 operator ruling)
- **#428**: sim preflight: on batch-fleet runs take OSDI identity from the runner-reported digests, not a locally built .build-manifest, then write the #325 input-cmr record
- **#429**: post-layout: attribute the klt 0.9.0 extracted phase-margin miss (ff / 1.32 V / 125 C) and the tt / 1.08 V / 27 C non-convergence, then route #312 to a design or klt follow-up

## In Progress

Issues currently being built (`loom:building`).

- **#459**: test flake (instrumented, two owners decisive): test_overlapping_starts_give_exactly_one_owner fails on T1 signoff register
- **#464**: .loom/account-ranking.codex (dispatcher-written) is untracked and not gitignored, so check-main-clean.sh exits 3 on a clean main
- **#468**: Consolidate duplicated request, deck-rewrite, and hashing helpers in sim/post-layout/
- **#469**: Two doc-accuracy nits in sim/post-layout after the deck_content_sha256 rollout
- **#470**: Deduplicate generic harness-CSV negative controls across all six sim/*/klt/test_compare.py suites
- **#471**: Read sweep log fields once so a missing marker skips only the affected point

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#463**: test: give the reservation race diagnostic inode/ctime and a clock probe

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#303**: docs: submit DR-0011 for two-key ratification (status flip)
- **#333**: docs(DR-0011): revision 5 restates swing as output range, discloses CMRR/gain gaps

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
- **#430**: design: post-layout phase margin misses the 60 deg bound at mos_ff/1.32V/125C (extracted PM 59.81 deg; ng=1-vs-drawn representation -1.64 deg, parasitics -0.53 deg) *(curated)*
- **#435**: Collect the two substrate-tie batch results for PR #431 on a batch-enabled worker *(curated)*
- **#459**: test flake (instrumented, two owners decisive): test_overlapping_starts_give_exactly_one_owner fails on T1 signoff register *(curated)*
- **#464**: .loom/account-ranking.codex (dispatcher-written) is untracked and not gitignored, so check-main-clean.sh exits 3 on a clean main *(curated)*
- **#469**: Two doc-accuracy nits in sim/post-layout after the deck_content_sha256 rollout *(curated)*

## Proposed (Architect / Hermit)

- **#105**: signoff: express the statistical rows as klt yield evidence for T1 item 6 (offset MC, mismatch CMRR) *(architect)*
- **#444**: Retire five-job submission from the PSRR supply-gain runner *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 2 |
| Important | 10 |
| Ready (`loom:issue`) | 3 |
| In Progress (`loom:building`) | 6 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 2 |
| Curated | 14 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

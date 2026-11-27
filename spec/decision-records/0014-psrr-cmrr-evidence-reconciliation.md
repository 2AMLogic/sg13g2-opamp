# 0014 — PSRR/CMRR evidence reconciliation: the AC-grounded-`inn` batch record is the evidence of record; no bound moves

- **Status**: decided (draft; ratification stays with the operator) — this
  record sets no spec value and edits no ratified bound. It reconciles the
  *evidence citations* in `spec/target-spec.md` §2 (CMRR and PSRR rows) and
  §4 (Sources) with the record the characterization report now binds, and
  records four findings. Every bound literal (`≥ 1.87 dB`, `≥ 26.68 dB`,
  `≥ 30.75 dB`) is unchanged.
- **Date**: 2026-11-27
- **Decided by**: Builder agent, issue #539
- **Related**: #539 (this issue), #514 / PR #528 (rebound
  `signoff/characterization/selection.json` and
  `signoff/evidence/testbenches.txt` to the batch record),
  [0002](0002-target-spec-ratification.md) (source of `[DR-2]`),
  [0004](0004-cmrr-mismatch-inclusive-ratification.md) (source of
  `[DR-4]` and the comparability claim examined below), #342 (owns any
  PSRR bound restatement; 2026-11-08 operator ruling), #101 / DR-0011
  (fresh ratification of unchanged DR-0002 requirements)

## Context

PR #528 re-bound the characterization report's `cmrr_systematic` and `psrr`
rows from `sim/cmrr-psrr/records/20260921-151815-707b34c.{csv,md}` (the
floating-`inn` harness; now retained as the `cmrr-psrr-harness` regression
control for `acm0_db`) to the AC-grounded-`inn` in-deck batch record
`sim/cmrr-psrr/records/20261125-103814-7fb5ff0.{csv,md}`, summarized from the
`klt` envelopes `sim/cmrr-psrr/klt/records/20261125-011804-02d78dd.cmrr.sim.json`
and `sim/cmrr-psrr/klt/records/20261125-011604-02d78dd.direct.sim.json`.
(`sim/cmrr-psrr/records/20261125-011804-02d78dd.{csv,md}` is an unselected
append-only intermediate record and is not cited as the selected summary.)
`spec/` was left untouched there because a spec change needs a decision
record. `spec/target-spec.md` §2 still cited the old record for the CMRR
row's superseded-floor half and the PSRR row.

## Finding 1 — which numbers come from the selected record

From `sim/cmrr-psrr/records/20261125-103814-7fb5ff0.csv` (45 points):

| Quantity | Worst | Best |
|---|---|---|
| PSRR+ (DC shelf, `psrr_db`) | 26.9010753 dB (26.9 dB) at `mos_fs_125C_1.08V` | 36.3277705 dB (36.33 dB) at `mos_sf_-40C_1.32V` |
| Systematic CMRR (`cmrr_db`) | 31.1986386 dB (31.2 dB) at `mos_fs_125C_1.08V` | 63.53404 dB (63.53 dB) at `mos_fs_-40C_1.08V` |

## Finding 2 — `≥ 1.87 dB` is no longer a meaningful physical floor, and stays

The `[DR-2]` PSRR bound `≥ 1.87 dB` was set equal to the worst value of the
floating-`inn` harness record `20260921-151815-707b34c`. That construction is
superseded; on the AC-grounded-`inn` construction the same row measures
26.90 dB, so it clears the bound by 25.03 dB (26.9010753 − 1.87). The bound
therefore no longer reflects a physical floor for this amplifier's DC PSRR+.

**The bound literal is nevertheless not changed here.** The 2026-11-08
operator ruling on #342 says to raise PSRR+ through the design and "do not
set the bound to whatever the current design achieves", and `CLAUDE.md`
reserves spec changes to the two-key ratification. Re-pointing the bound to
26.90 dB is rejected. Any restatement belongs to #342 / a ratification pass.

## Finding 3 — 1 kHz / supply-zero evidence state

- The selected November direct record reads only the 10 mHz DC shelf and the
  0.1 Hz plateau guard. It carries **no 1 kHz figure**.
- The October AC-grounded batch record
  `sim/cmrr-psrr/klt/records/20261015-103521-0f41068.{md,sim.json}`, joined to
  `sim/open-loop-ac/records/20261015-103057-895d555.csv`, **already measured**
  1 kHz PSRR+ on the AC-grounded construction: 26.90–36.33 dB across all 45
  corners (`sim/cmrr-psrr/README.md`: "the 4 dB zero is gone"). The `~1.5 Hz`
  / `~4 dB` supply zero in the old §2 text was a floating-`inn` artifact.
- What is absent is an *in-deck (unjoined)* 1 kHz measurement. If one is
  wanted, it is a separate `loom:triage` issue (`klt sim`, batch,
  `--wait-for-capacity 600`); it is not run in this change.

## Finding 4 — DR-0004's "directly comparable to the systematic floor by construction"

**Holds against the superseded record; does not hold exactly against the
selected record.** DR-0004's mismatch-inclusive record
(`sim/cmrr-mismatch/records/20260921-172304-65f5fb4.csv`) joins `Av0` from
the floating-`inn` `sim/open-loop-ac/records/20260910-221601-22feaba.csv`.
It matched `20260921-151815-707b34c` exactly (same joined `Av0`). The
selected `cmrr_systematic` (`20261125-103814-7fb5ff0.csv`) uses in-deck
AC-grounded `Av0`, which is **+0.2199 dB to +1.7850 dB** higher across the 45
corners (recomputed from the two CSVs), while `acm0_db` agrees within
4.3e-5 dB. The two CMRR figures therefore differ by that `Av0` offset until
`cmrr-mismatch` is re-joined or re-run under separate authorization. The
ratified `≥ 26.68 dB` bound is unaffected; the comparison "below the
systematic floor at all 45 points" is not re-evaluated here.

## Decision

1. `spec/target-spec.md` §2 (CMRR superseded-floor half, PSRR row) and §4
   Sources cite the selected record and the October 1 kHz evidence, and mark
   `20260921-151815-707b34c` as the superseded floating-`inn` record kept for
   `[DR-2]` bound provenance and the `Acm0` regression control.
2. No bound value changes. The substrings pinned by
   `signoff/characterization/selection.json`,
   `signoff/check_integrator_contract.py` and
   `sim/cmrr-psrr/klt/test_compare.py` are preserved verbatim.
3. Restating the PSRR bound, re-joining `cmrr-mismatch`, and an in-deck 1 kHz
   re-measure are out of scope (#342, separate issues).

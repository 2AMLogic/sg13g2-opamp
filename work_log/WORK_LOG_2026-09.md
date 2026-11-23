# Work Log Archive — 2026-09

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

### 2026-09-22

- **Issue #41** (closed): Remove empty measurements/ scaffold: its role was absorbed by sim per-bench records
- **Issue #37** (closed): 2am: reuse rule 9 — name this block's consumers in the spec, carry their requirement rows, publish the integrator view as data
- **Issue #30** (closed): docs: input-noise README non-claim bullet predates the DR-0002 ratification (noise row is [DR-2], not [P])
- **PR #42**: chore: remove empty measurements/ scaffold (#41)
- **PR #40**: docs(spec): record consumers with per-row verdicts, publish integrator view as data
- **PR #39**: docs: past-tense the input-noise non-claim bullet after DR-0002

### 2026-09-21

- **Issue #32** (closed): spec: re-ratify the CMRR row on the mismatch-inclusive 3σ record (DR-0002 residual (c), two-key)
- **Issue #26** (closed): sim: mismatch Monte Carlo CMRR evidence for the DR-1 op-amp (companion to #17)
- **Issue #23** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read
- **Issue #21** (closed): sim: input common-mode range (ICMR) characterization bench
- **Issue #19** (closed): design: decide whether to re-size the input pair for flicker noise (1/f corner measured above the whole noise band)
- **Issue #17** (closed): sim: Monte Carlo statistical evidence for input-referred offset (seed/N/negative control)
- **Issue #16** (closed): spec: ratify target-spec.md via the two-key (EE + market) mechanism
- **Issue #15** (closed): sim: output-swing bench for the DR-1 op-amp
- **Issue #14** (closed): sim: CMRR/PSRR bench for the DR-1 op-amp
- **PR #36**: docs: re-ratify the CMRR row on the mismatch-inclusive 3σ record (DR-4)
- **PR #35**: sim: add mismatch Monte Carlo offset evidence for the DR-1 op-amp
- **PR #34**: sim: add input common-mode range (ICMR) PVT bench for the DR-1 op-amp
- **PR #33**: sim: add mismatch Monte Carlo CMRR evidence for the DR-1 op-amp
- **PR #31**: feat(signoff): add a klt-graded T1 signoff verdict of record
- **PR #28**: docs: decide input-pair flicker-noise re-size (declined) in DR-0003
- **PR #27**: spec: ratify measured target-spec rows via two-key DR-0002
- **PR #25**: sim: add CMRR/PSRR+ PVT bench for the DR-1 op-amp
- **PR #24**: sim: add output-swing PVT bench for the DR-1 op-amp

### 2026-09-18

- **Issue #13** (closed): sim: input-referred noise bench for the DR-1 op-amp (choose band, then measure)
- **Issue #12** (closed): sim: slew-rate (large-signal step) bench for the DR-1 op-amp
- **Issue #11** (closed): sim: input-referred offset bench (deterministic, corner-only) for the DR-1 op-amp
- **PR #22**: sim: add slew-rate (large-signal step) PVT bench for the DR-1 op-amp
- **PR #20**: sim: add input-referred noise PVT bench, choose the noise band
- **PR #18**: feat(sim): add deterministic PVT input-referred offset bench

### 2026-09-10

- **Issue #9** (closed): design: first-cut gm/ID sizing + xschem schematic of the DR-0001 two-stage Miller op-amp, with an open-loop gain/GBW/PM bench into CL = 2 pF across the five-corner grid
- **PR #10**: feat: first-cut gm/ID sizing, xschem schematic, and open-loop AC bench for DR-0001 op-amp

### 2026-09-09

- **Issue #6** (closed): spec: topology + CL decision record, informed by gm/ID study (issue #5)
- **Issue #5** (closed): sim: gm/ID characterization sweep of SG13G2 LV core MOS — the first engineering task (porting-plan §4, gm/ID-first)
- **PR #8**: spec: ratify two-stage topology and CL target (DR-1)
- **PR #7**: sim: gm/ID characterization sweep of SG13G2 LV core MOS (issue #5)

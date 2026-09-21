# 0002: Target-spec ratification — one bound per measured classic row (two-key EE + market)

- **Status**: `submitted for ratification` — this record's bounds bind when,
  and only when, the PR that carries it has been ratified by **both keys** of
  the two-key mechanism ([2AMLogic/2am#372](https://github.com/2AMLogic/2am/issues/372)):
  an EE key (`RATIFY-KEY: ee`) and a market key (`RATIFY-KEY: market`), each
  posted as a PR review verdict, **neither key held by this PR's author or
  the design's author** (non-author enforcement, epic phase B2). The merge
  commit of that PR is the ratification record. Until both keys are present
  and approving, everything below is a recommendation, not a ratified value.
- **Date**: 2026-09-21
- **Decided by**: Builder agent, issue #16 (per-row recommendation + this
  record); the EE key and the market key (ratification verdicts on the PR)
- **Related**: `spec/target-spec.md` (this record flips its `Status` header
  and re-tags its measured rows `[DR-2]`);
  [0001-topology-and-cl.md](0001-topology-and-cl.md) (carried into force —
  `proposed` → `ratified` — with this record, resolving the `[DR-1]` rows in
  §1); #9 (open-loop AC bench + sizing), #11 (offset), #12 (slew), #13
  (noise), #14 (CMRR + PSRR bench, merged mid-pass as PR #25), #15
  (output swing) — the merged bench evidence every bound below cites;
  #17 (Monte Carlo offset statistics, open — owns the offset
  statistical-basis residual); #26 (CMRR mismatch Monte Carlo, open —
  owns the mismatch-inclusive CMRR residual registered below); #3
  (gap-to-T1 tracker, item 5 — re-evaluated on merge, see
  "Post-merge follow-through")

## Context

`spec/target-spec.md` was assembled 2026-09-06 as `Status: DRAFT`: every
number was either an engineering placeholder `[P]` or deliberately unset
`[TBD-#n]`, because no SG13G2 device data yet existed. Since then the
classic-row benches have all merged and are committed under `sim/`, each
sweeping the full 45-point PVT grid (`mos_tt/ss/ff/sf/fs` x `{-40, 27, 125} °C`
x `{1.08, 1.20, 1.32} V`, the `[DR-1]` corner grid and CL):

- `sim/open-loop-ac/records/20260910-221601-22feaba.csv` (issue #9) — DC
  gain, GBW, phase margin, quiescent power
- `sim/input-offset/records/20260918-203858-90844d2.csv` (issue #11) —
  systematic offset, two independent methods agreeing to ≤ 0.3 mV per point
- `sim/slew-rate/records/20260918-210216-90844d2.csv` (issue #12) — slew
  rate, worse edge per point
- `sim/input-noise/records/20260918-203850-90844d2.csv` (issue #13) —
  input-referred noise, integrated band + spot densities (the band itself
  chosen and defended in that experiment's own pass)
- `sim/cmrr-psrr/records/20260921-151815-707b34c.csv` (issue #14) —
  CMRR and PSRR+ over the same grid, two AC harnesses per point, joined
  per point to `sim/open-loop-ac/`'s `Av0`
- `sim/output-swing/records/20260921-151759-707b34c.csv` (issue #15) —
  per-rail headroom and tracking span at the −6 dB incremental-gain criterion

Issue #16 (this record's parent) is gap-to-T1 tracker (#3) item 5's "ratify
the spec table" half: the tracker item stays unmet while a spec is unratified
even when every bench exists, so this record ratifies exactly what the merged
evidence covers and names what it deliberately does not.

The CMRR/PSRR bench (#14) landed on `main` **during** this ratification
pass (PR #25, commit `64a6f1f`, 2026-09-21) — this record incorporates its
measured rows as ratified bounds below rather than holding them back, per
issue #16's own preference for ratifying more rows in one pass. What still
does **not** exist on `main` as of this record: any layout (so no Area
number), the offset row's statistical basis (the mismatch Monte Carlo pass,
#17 — `sim/input-offset/` is deliberately deterministic and does not
discharge that column), and mismatch-inclusive CMRR evidence (#26; the
`sim/cmrr-psrr/` bench measures perfectly matched devices — its measured
30.75 dB floor is the structural term only).

## Decision

Ratify the table at the **measured worst case of the 45-point PVT grid** for
every measured row — one bound per row, stated so a future pass/fail verdict
against a re-run bench is unambiguous. Per the safety property carried from
the ratification-via-PR policy
([2AMLogic/2am#357](https://github.com/2AMLogic/2am/issues/357)) and the
two-key epic: **values are ratified on their evidence, never relaxed to make
results pass.** This is this table's *first* ratification — there is no
previously ratified value anywhere in this repo, so no bound below relaxes
anything; each is set AT the measured worst case it cites, not below it.

| `spec/target-spec.md` row | Bound ratified `[DR-2]` | Evidence (measured envelope) |
|---|---|---|
| Open-loop DC gain | **≥ 37.8 dB worst-case** across the grid | 37.8–45.2 dB, worst `FS / 125 °C / 1.08 V` (`sim/open-loop-ac/`) |
| GBW (into CL = 2 pF `[DR-1]`) | **≥ 4.74 MHz worst-case** | 4.74–6.62 MHz, worst `FS / 125 °C / 1.08 V` (`sim/open-loop-ac/`) |
| Phase margin (at GBW, same CL) | **≥ 60°** | measured worst 76.4° at `FF / 125 °C / 1.32 V` — clears the bound at every point (`sim/open-loop-ac/`) |
| Slew rate (into CL = 2 pF) | **≥ 7.51 V/µs worst-case** (worse edge) | 7.51–9.91 V/µs, worst `mos_ss / −40 °C / 1.08 V` (`sim/slew-rate/`, bench conditions in its README) |
| Input-referred noise, band **100 Hz–1 MHz** (band part of the number) | **≤ 108.9 µVrms worst-case**, integrated over that band; spot densities as stated in the row | 73.4 (best) / 87.3 (nominal) / 108.9 (worst) µVrms, worst `FS / 125 °C / 1.08 V` (`sim/input-noise/`) |
| Input-referred offset — **systematic component only**; see residual (b) | **+21.9 mV worst-case magnitude** (measured range +11.4…+21.9 mV) | `sim/input-offset/`, two methods per point |
| CMRR — **systematic, nominal-device floor**; see residual (c) | **≥ 30.75 dB worst-case** (mismatch-inclusive CMRR outstanding, #26) | 30.75–62.83 dB, worst `FS / 125 °C / 1.08 V` (`sim/cmrr-psrr/`) |
| PSRR+ (DC shelf; strongly frequency-dependent — the row's own in-band degradation figures are part of the ratified number) | **≥ 1.87 dB worst-case at the DC shelf** | 1.87–29.54 dB DC shelf, worst `FF / 125 °C / 1.32 V`; worst-in-band 1.30 dB at 1 kHz, `SF / −40 °C / 1.32 V` (`sim/cmrr-psrr/`) |
| Output swing (CL = 2 pF, no resistive load, −6 dB incremental-gain criterion) | **headroom ≥ 251 mV from VDD and ≥ 141 mV from VSS worst-case; tracking span ≥ 0.571 V worst-case** | span 0.571 V worst `mos_ss / 125 °C / 1.08 V` / 0.900 V best (`sim/output-swing/`) |
| Quiescent power | **Iq ≤ 119.7 uA worst-case** (total Vdd current incl. the external 10 uA `ibias` reference) | 99.9–119.7 uA, worst `SS / −40 °C / 1.32 V` (`sim/open-loop-ac/`) |

The §1 operating conditions are ratified with the same pass, as
`[DR-2]`: supply **1.2 V ±10% (1.08–1.32 V)** and operating temperature
**−40…+125 °C** — every bound above is measured across exactly these ranges,
which is the evidence that makes them binding rather than analogy. The
`[DR-1]` corner grid and CL = 2 pF rows carry unchanged from
[0001-topology-and-cl.md](0001-topology-and-cl.md), which this record moves
from `proposed` to `ratified` — the "future spec-ratification issue" its
status line has been waiting for is exactly this pass.

Why worst-case as the bound, per row — the one option recommended over the
alternatives (`## Alternatives considered` below) is: **the bound a re-run
bench must meet at every point of the grid.** The measured envelope
(worst/best) stays in the spec row as context; the ratified number is the
single worst-case edge. For the phase-margin row the bound stays the
original ≥ 60° proposal — measurement cleared it at every corner (worst 76.4°;
a relaxation to a weaker number would be exactly the "relax to make results
pass" shape the mechanism forbids — and there is no reason to relax a bound
the evidence clears by 16.4°).

The two rows added by the mid-pass CMRR/PSRR landing get the same discipline,
with their caveats made part of the ratified number, mirroring the offset
row: CMRR's measured 30.75 dB floor is ratified explicitly as the
*systematic, nominal-device* bound — the mismatch-inclusive term is a
registered residual (#26), and a future re-ratification of the
mismatch-inclusive row will supersede this bound exactly as #17's MC pass
will supersede the offset row's systematic half. PSRR+'s bound is the
DC shelf (1.87 dB worst) with the row's own frequency dependence —
including the worst-in-band 1.30 dB at 1 kHz through the supply path's
~1.5 Hz zero — part of the ratified number, the same way the noise row's
band is part of its number: a PSRR figure without its frequency context
is not a claim about this amplifier.

## Residual register — explicitly NOT ratified by this record

Each residual below stays un-ratified and carries an explicit statement of
why it cannot yet be ratified (per issue #16's first acceptance criterion:
"ratify what has already converged and leave a documented residual"):

- **(a) Area — `[TBD-12]`**: a post-layout property; no layout exists in
  this repo. Not a PVT line; not ratifiable from `sim/` evidence by
  construction.
- **(b) Offset statistical-basis column — stays `[P]`/outstanding**:
  `sim/input-offset/` is deliberately deterministic; the 3σ mismatch MC N≥300
  basis the row's column commits to is tracked by #17. The row's *systematic*
  component IS ratified (above); its statistical basis is not. A future
  ratification pass on the total-offset number cites #17's record and
  supersedes this half.
- **(c) CMRR mismatch-inclusive component — outstanding**: the CMRR bound
  above is the systematic, nominal-device floor; the mismatch-inclusive
  CMRR term (typically the dominant real-part term) has no measured
  evidence yet. Tracked by #26; a future re-ratification cites its record
  and supersedes this systematic bound. A real part's CMRR is expected
  worse than the ratified floor — the keys ratify the floor understanding
  this, exactly as the offset row's systematic half was ratified.
- **(d) Loaded output swing**: the ratified swing bound is unloaded (no
  resistive load) at CL = 2 pF — an upper bound. A loaded-row decision is a
  separate decision record, never a silent amendment of this one.
- **(e) HV (3.3 V I/O) stretch row (§1)**: deliberately left `[P]` and
  un-opened by this ratification. Opening it requires its own decision record
  per `CLAUDE.md`; this record does not open it.

None of the residuals is upgraded or deprecated by this pass; a future
ratification PR covering them amends this record rather than replacing it
(and the market key must explicitly find any bound *weaker than a previously
ratified row* still competitive against named public parts, or escalate to
the operator — the relax-after-measured-FAIL rule of #372, which applies to
those future passes; it has nothing to relax here, see "Decision").

## Alternatives considered

- **Ratify at the best-case or at a nominal point** — rejected: a spec a
  re-run bench must *pass* is a worst-case bound; nominal/best-case numbers
  describe the measured envelope, not a guarantee, and would make every
  corner other than the best one a guaranteed FAIL.
- **Ratify the measured envelope as a range** — rejected: a row needs one
  binding edge for a pass/fail verdict; keeping the envelope in the row as
  context covers the information without ambiguity about which edge binds.
- **Wait for the mismatch/Monte Carlo passes (#17 offset, #26 CMRR) and
  ratify the whole table at once** — rejected: issue #16's own Test Plan
  allows (and the gap-to-T1 tracker urgently needs) ratification of what
  has converged, with the residuals documented rather than blocking the
  measured nine. (The original shape of this alternative — wait for the
  CMRR/PSRR bench — was mooted mid-pass when #25 landed; its rows are
  incorporated above instead of held back.)
- **Phase margin at a weaker bound (45°)** — rejected: the stretch column
  already records the 45°-at-FF/hot fallback; measurement cleared 60° at
  every point, so the ratified bound is the original 60°.
- **Iq bound as signal-path-only (excluding `ibias`)** — rejected: the total
  Vdd current including the external 10 uA `ibias` reference is the larger,
  conservative, and unambiguous measurement; signal-path-only figures stay in
  the row as notes.
- **Swing bound as absolute `Vout` bounds per point** — rejected: per-rail
  headroom is the comparable-across-supplies form the row already uses;
  absolute per-point `Vout` stays in the record CSV.

## Post-merge follow-through

- **Gap-to-T1 tracker (#3), item 5** — re-evaluated once this PR merges (its
  acceptance criterion): the tracker's item text is updated to state exactly
  which rows are now ratified (the ten `[DR-2]` performance rows above plus
  the §1 operating conditions) and which remain open (Area `[TBD-12]`,
  offset statistical basis pending #17, mismatch-inclusive CMRR pending
  #26, the loaded-swing and HV decisions). Item 5's "vs a ratified spec" clause is
  satisfied for its ratified rows from the merge commit forward; the tracker
  item itself may still stay open while the residual rows are unratified.
- **Future residual ratification** — whichever residual lands next goes
  through its own PR under the same two-key mechanism, amending this record.

## Out of scope

- Any circuit change, sizing change, or simulation — this record only
  ratifies measured results; `design/` and `sim/` are untouched.
- The HV stretch row, the loaded-swing decision, and the Area row's
  eventual value — see the residual register.
- Filling, guessing, or placeholder-proposing any residual row.
- `spec/porting-plan.md`, `README.md`, and the gap-to-T1 tracker's own issue
  body (the #3 edit is post-merge, above).

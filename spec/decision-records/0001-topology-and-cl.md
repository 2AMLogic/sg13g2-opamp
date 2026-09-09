# 0001: Two-stage topology (input-pair polarity, output stage, cascode) and CL target

- **Status**: proposed (input to a future spec-ratification issue; this
  repo has no ratified spec yet — `spec/target-spec.md` itself is still
  DRAFT — matching `sg13g2-bandgap`'s own DR-0001, which is also "proposed"
  pending a future ratification pass, not "ratified")
- **Date**: 2026-09-09
- **Decided by**: Builder agent, issue #6
- **Related**: #5 (gm/ID device-characterization study this record cites),
  `spec/target-spec.md` (`[TBD-1]`, `[TBD-2]`), `spec/porting-plan.md` §4
  ("Open items and next steps")

## Context

`spec/porting-plan.md` §4 named two open items ahead of any sizing work on
this block: the two-stage Miller-compensated topology's input-pair
polarity, output-stage class, and cascode-or-not; and the load-capacitance
(`CL`) target the GBW/phase-margin rows in `spec/target-spec.md` are stated
"into." Both were explicitly deferred by issue #5 (its own "Out of scope"
section), which committed the prerequisite gm/ID device-characterization
data (`sim/gm-id-characterization/records/20260909-063633-b402592.csv`,
merged from `sim/gm-id-characterization/records/20260909-063633-b402592.md`)
these decisions now draw on.

Neither same-PDK sibling (`sg13g2-bandgap`, `sg13g2-ldo`) has a topology
that transfers wholesale (`spec/porting-plan.md` §3) — this is genuinely
new circuit design for this fleet, not a port. Per `CLAUDE.md`, this block
is CMOS only; no HBT-input stretch record exists, so every device
considered here is `sg13_lv_nmos` / `sg13_lv_pmos` (PSP103.6, LV core,
1.2 V-primary).

All figures below are read directly from
`sim/gm-id-characterization/records/20260909-063633-b402592.csv` (issue
#5's merged, all-quantities-derived table; W=10 um, Vds=0.6 V, 27 °C
nominal, `cornerMOSlv.lib`'s five process corners). Every cited row is a
literal `(device, length, corner, vgs, ...)` tuple present in that CSV —
grep it directly to reproduce any number quoted here.

## Decision

**Input-pair polarity: NMOS.** At the input pair's likely short-channel
bias point (`L = 0.13u`, `mos_tt`, overdrive ≈ 0.31 V — the CSV row
`nmos,0.13u,mos_tt,0.6700,...,7.419938,19.278468,3.839065e+10,0.3598,0.3102`),
`sg13_lv_nmos` reaches `fT ≈ 3.84e10 Hz` (and `4.14e10 Hz` at overdrive
≈ 0.33 V) versus `sg13_lv_pmos` at the matching overdrive
(`pmos,0.13u,mos_tt,0.7300,...,5.848394,12.919903,2.156298e+10,0.4038,0.3262`)
reaching only `fT ≈ 2.16e10–2.27e10 Hz` over the same overdrive range — the
NMOS device is **≈1.8x faster** at matched length, corner and overdrive.
Both `run_gmid_sweep.sh`'s own automated sanity check
(`corners/20260909-063633-b402592/sanity_checks.txt`) and the CSV rows
above corroborate this at overdrive ≈0.3 V: `nmos fT=4.138e+10` vs.
`pmos fT=2.269e+10`. Since the input pair's `gm` directly sets both GBW
(`GBW ≈ gm1 / (2*pi*CL)`) and input-referred thermal noise floor for a
fixed bias current, and `gm/Id` is comparable between the two polarities at
this length (NMOS peak gm/Id ≈29.5 vs. PMOS peak ≈28.2 at `L=0.13u`, per
`sanity_checks.txt`), the ≈1.8x fT advantage is a real efficiency gain, not
an artifact of unequal bias efficiency. NMOS also carries a same-length,
same-overdrive-range **intrinsic-gain** edge at the input pair itself: over
overdrive ≈0.31–0.33 V, NMOS `gm/gds ≈ 19.0–19.3` (the two `mos_tt`,
`L=0.13u` rows cited above) versus PMOS `gm/gds ≈ 12.4–12.9` over overdrive
≈0.33–0.35 V (the two `mos_tt`, `L=0.13u` rows cited above) — so an NMOS
input pair also contributes more to first-stage gain per device than a
PMOS input pair would at the same channel length.

**Output stage: single-ended, Class-A common-source, PMOS gain device.**
The second (output) gain stage uses a PMOS common-source transistor (gate
driven from the first stage's single-ended output node, drain = block
output) loaded by an NMOS constant-current sink — the canonical two-stage
Miller-compensated shape `CLAUDE.md` names, paired with the NMOS input
pair's PMOS current-mirror load from the first stage. The PMOS device is
chosen for the gain transistor specifically because this PDK's
characterization data shows PMOS's intrinsic gain (`gm/gds`) growing far
faster with channel length than NMOS's: at `L=1.04u`, `mos_tt`, overdrive
≈0.15–0.19 V, PMOS reaches `gm/gds ≈ 129–148`
(`pmos,1.04u,mos_tt,0.5500,...,8.977259,129.242228,...` through
`pmos,1.04u,mos_tt,0.5100,...,10.606425,147.603497,...`), while NMOS at the
same length and a comparable overdrive reaches only `gm/gds ≈ 33`
(`nmos,1.04u,mos_tt,0.3700,...,10.814042,33.468456,...`) — a **≈4x**
intrinsic-gain advantage for PMOS at this length, confirmed to hold at the
`mos_ss` worst-process corner too (`pmos,1.04u,mos_ss,0.6100,...,
8.515294,124.100924,...` vs. `nmos,1.04u,mos_ss,0.4100,...,10.905081,
33.074753,...`). Sizing the output-stage PMOS gain device at a
moderate/long channel (candidate `L ≈ 1.04u` class, final length TBD in a
future sizing pass) lets the second stage carry the bulk of total loop gain
from a single non-cascoded device, per the cascode decision below. This is
not yet a bias/sizing commitment (out of scope, see below) — only the
device-polarity and stage-class choice.

**Cascode: not used (non-cascoded two-stage).** At this block's 1.2 V ±10%
rail (`spec/target-spec.md` §1, 1.08–1.32 V), a cascode adds a stacked
`Vgs+Vds,sat` budget line that this PDK's own device data shows is not free:
even a single NMOS input-pair device already needs overdrive ≈0.3 V plus
headroom for its Vth (`Vth ≈ 0.36 V` at `mos_tt`, `0.42 V` at `mos_ss`, both
`L=0.13u`, per the CSV's `vth_v` column) to sit at a reasonable `gm/Id`
point — stacking a cascode device on top of the input pair or the output
gain device would consume input common-mode range and output swing headroom
this block has little of to spare at 1.08 V (worst-case low rail). Instead,
this decision leans on the PMOS output-stage device's own high intrinsic
gain at moderate length (above) to reach adequate total DC gain without a
cascode: an illustrative (non-binding) DC-gain estimate from `gm/gds`
alone — NMOS input stage at `L=0.13u`/`mos_tt` (`gm/gds ≈ 19.28`, the
`vgs=0.6700` row cited above) times PMOS output stage at `L=1.04u`/`mos_tt`
(`gm/gds ≈ 129.24`, the `vgs=0.5500` row cited above) — gives a two-stage
product of `19.28 x 129.24 ≈ 2492` (≈68 dB). At the `mos_ss` worst process
corner, the same estimate using NMOS input `gm/gds ≈ 19.72`
(`nmos,0.13u,mos_ss,0.7500,...,6.680126,19.722285,4.138741e+10,0.4212,0.3288`)
times PMOS output `gm/gds ≈ 124.10` (the `vgs=0.6100` row cited above)
gives `19.72 x 124.10 ≈ 2447` (≈67.8 dB) — the estimate holds up similarly
across corners at these specific bias points, before any mirror/tail
loading is accounted for. This is a plausibility check that a non-cascoded
architecture can plausibly reach a canary-block-class DC gain target, not
a sizing commitment; actual `[TBD-3]` DC-gain sizing (with mirror/tail
loading, and a specific channel length for every device) is explicitly out
of scope for this record (see below).

**CL target: 2 pF.** No twin-repo precedent exists yet (`gf180-opamp`,
`sky130-opamp` have no `spec/decision-records/` directory or CL proposal as
of this record's date — checked directly). Chosen on independent
engineering judgment as a representative moderate load for a standalone
canary op-amp characterized on its own bench: large enough to be a
realistic stand-in for driving an external test-pad plus probe/ESD
parasitic capacitance (commonly 1–3 pF for a small test-chip bond pad plus
scope-probe loading), yet small enough that GBW/slew-rate targets derived
from it stay meaningful for this block's likely bias-current budget (an
excessively large CL, e.g. 10+ pF, would force either a much higher tail
current than a canary block needs, or an unrealistically low GBW target).
2 pF sits in the "low single-digit pF" range this issue's curation guidance
named as the common choice for this class of standalone op-amp bench.

## Alternatives considered

- **PMOS input pair.** Rejected. At matched length/corner/overdrive, PMOS
  trails NMOS on both `fT` (≈1.8x lower, see Decision) and `gm/gds`
  (≈1.5x lower at `L=0.13u`), so a PMOS input pair would either need a
  larger bias current to match NMOS's GBW/gain contribution (worse power
  efficiency) or accept lower GBW/gain at the same current. PMOS's usual
  input-pair advantage in other processes (lower 1/f noise, easier
  near-rail common-mode range when biased from VDD) is not cited here as
  disqualifying — but this PDK's characterization data does not show a
  compensating gm/gds or fT advantage for PMOS at the input-pair's likely
  short-channel bias point to offset the bandwidth/gain cost, so the
  decision is made on the measured device data per `CLAUDE.md`'s "gm/ID
  first" rule rather than on generic architecture folklore.
- **NMOS output-stage gain device (paired with a PMOS input pair, or an
  NMOS common-source stage after an NMOS-input first stage).** Rejected.
  The PSP103 characterization data shows the *opposite* length-dependent
  behavior from what this alternative would need, at a matched overdrive
  range (≈0.21–0.28 V) across the length step: NMOS's `gm/gds` grows only
  modestly with length (`≈26.7` at `L=0.52u`, overdrive 0.275 V, up to
  `≈33.1` at `L=1.04u`, overdrive 0.244 V — a ≈1.2x step —
  `nmos,0.52u,mos_tt,0.4700,...,8.227983,26.748364,...` and
  `nmos,1.04u,mos_tt,0.4100,...,9.219885,33.059188,...`), while PMOS's
  `gm/gds` grows far more sharply over the same length step (`≈39.9` at
  `L=0.26u`, overdrive 0.224 V, up to `≈121.5` at `L=1.04u`, overdrive
  0.212 V — a ≈3.0x step —
  `pmos,0.26u,mos_tt,0.6100,...,7.928844,39.900296,...` and
  `pmos,1.04u,mos_tt,0.5700,...,8.315235,121.508494,...`). An NMOS
  output-stage gain device would forfeit the intrinsic-gain headroom PMOS
  offers at moderate length, making a non-cascoded design (see Decision)
  harder to justify without a longer, larger device or an explicit
  cascode.
- **Cascoded (telescopic or folded) two-stage.** Rejected for this record.
  A cascode would recover more DC gain per stage than the non-cascoded
  design's own `gm/gds`-based estimate (above), but at the direct cost of
  stacked-device headroom on a rail with only 1.08 V of worst-case low-rail
  margin to spend across input pair, tail source, and output-stage
  device(s). The non-cascoded estimate above already reaches a plausible
  canary-block DC-gain range without paying that headroom cost, so cascode
  is deferred rather than adopted as a first design; nothing in this record
  forecloses re-opening a cascode option in a superseding record if a
  future sizing pass finds the non-cascoded gain estimate does not close
  once mirror/tail loading and mismatch are accounted for.
- **Folded-cascode single-stage (instead of a two-stage Miller topology
  altogether).** Rejected — out of scope by construction: `CLAUDE.md`
  mandates a two-stage Miller-compensated topology for this block; this
  record makes decisions within that mandate (input-pair polarity, output
  class, cascode-or-not), not a decision to abandon it.
- **CL matched to a specific downstream consumer circuit's input
  capacitance.** Rejected — this is a standalone canary block with no named
  downstream consumer yet (per `README.md`'s framing), so there is no
  concrete consumer capacitance to match. A generic bench-representative
  value (2 pF, see Decision) is used instead, consistent with
  `spec/porting-plan.md` §4's framing of `CL` as independent of any
  specific application context for this block.
- **A larger CL (e.g. 5–10 pF) to stress-test slew rate / output-stage
  drive strength.** Rejected as the primary target — a larger CL is a
  reasonable *stretch* row for a future spec revision once nominal sizing
  exists, but as the primary GBW/phase-margin target it would force this
  canary block's bias currents higher than its role warrants, per
  `CLAUDE.md`'s framing of this block as a canary, not a heavy-load driver.

## Consequences

- `spec/target-spec.md` §1's `[TBD-1]` (corner grid) and `[TBD-2]` (CL) rows
  are updated to `[DR-1]`-tagged, resolved values: the `cornerMOSlv.lib`
  `tt`/`ss`/`ff`/`sf`/`fs` five-corner grid (confirmed against the real PDK
  install by issue #5, now ratified into the spec by this record), and
  `CL = 2 pF`.
- Every gm/ID-dependent `[TBD-#n]` row in `spec/target-spec.md` §2
  (`[TBD-3]` DC gain, `[TBD-4]` GBW, `[TBD-5]` slew rate, `[TBD-11]`
  quiescent power) can now be sized against a concrete topology and load,
  citing `sim/gm-id-characterization/records/*.csv` directly per
  `CLAUDE.md`'s "gm/ID first" rule — but no such sizing is performed by
  this record (see "Out of scope" below).
- The non-cascoded architecture choice means output swing (`[TBD-10]`) and
  input common-mode range are not further constrained by cascode headroom,
  but the two-stage DC-gain budget now depends on the output-stage PMOS
  device being sized at a moderate-to-long channel length (candidate
  `L ≈ 1.04u` class) to realize the `gm/gds` advantage this record cites —
  a future sizing pass that instead sizes that device short (for area or
  bandwidth reasons) would need to re-examine whether the non-cascoded
  DC-gain estimate in this record still closes.
- This decision is unverified in simulation beyond the device-level gm/ID
  data cited above — no schematic exists yet in this repo. If a future
  sizing or schematic-level pass finds the non-cascoded DC-gain budget does
  not close (e.g. once mirror/tail-device loading and mismatch are
  included), that finding should produce a superseding record, not a
  silent addition of a cascode.

## Out of scope

This record does **not** perform any actual amplifier sizing — no device
widths, lengths, bias currents, or mirror ratios are chosen here. That is
explicitly a follow-on issue, to cite
`sim/gm-id-characterization/records/*.csv`'s full gm/Id-vs-overdrive curves
directly per `CLAUDE.md`'s "gm/ID first" rule, once this record's topology
and `CL` choices are available to size against.

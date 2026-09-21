# input-offset

DC input-referred offset characterization of `design/opamp_core.sch`'s
two-stage Miller-compensated op-amp, in two complementary benches that
share this directory, one method, and one netlist:

- **Deterministic, corner-only sweep** (`run_offset_sweep.sh`, issue #11)
  across the full PVT grid — fills `spec/target-spec.md`'s `[TBD-7]` offset
  row's *systematic* half.
- **Device-mismatch Monte Carlo campaign** (`run_offset_mc.sh`, issue #17)
  — the same row's *statistical* half (`3σ`, mismatch MC N≥300, combined
  with — not instead of — process corners). See
  "Monte Carlo mismatch campaign (issue #17)" below for the campaign's
  method, seeding, scope, and self-verification gates.

## What this bench measures

For every point on the `cornerMOSlv.lib` `mos_tt/ss/ff/sf/fs` [DR-1] x
temperature `{-40, 27, 125} °C` x supply `{1.08, 1.20, 1.32} V` grid
(45 points — the same grid, and the same `point_id` keys, as
`sim/open-loop-ac/`):

- **`Vos`** (`vos_null_v`) — the differential input voltage
  `V(inp) - V(inn)` that forces `Vout` to mid-rail (`VDD/2`), measured by
  sweeping that differential input with the input common mode pinned at
  `VDD/2`. This is the bench's primary result.
- **`Vos` by a second, independent method** (`vos_closed_loop_v`) — the same
  quantity obtained by closing a DC unity-gain loop and referring the
  resulting output error back through the DC gain `sim/open-loop-ac/`
  measured at the *same* grid point, plus the per-point difference between
  the two methods (`vos_method_delta_v`).
- **Local DC gain at the null** (`av_local_db`) — the small-signal slope
  `dVout/dVid` fitted at the null. Not a spec row (that is
  `sim/open-loop-ac/`'s `Av0`); it is here as a sanity number, because a
  railed or degenerate "null" shows up immediately as a collapsed slope.
- **Operating point at the null** (`vout_sample_v`, `vd1_sample_v`,
  `vd2_sample_v`, `vtail_sample_v`, `vibias_sample_v`, `ivdd_sample_a`) —
  ngspice's own solution at the swept sample nearest the null, plus a
  per-point pass/fail sanity check (`op_pass`); see "Per-point sanity
  checks" below.
- **Convergence evidence** (`vos_coarse_fine_delta_v`) — the difference
  between the coarse locate pass's null and the fine pass's null, so the
  reported number is demonstrably not an artifact of one step size.

## Method

### Definition, and why it needs no gain correction

Input-referred offset is defined here operationally: `Vos` is the value of

```
Vid = V(inp) - V(inn)
```

at which `Vout = Vcm = VDD/2`, with both inputs driven from one common-mode
source so that the input common mode stays *exactly* at `Vcm` for every
swept `Vid`:

```
V(inp) = Vcm + Vid/2        V(inn) = Vcm - Vid/2
```

`VDD/2` is the null target because it is the same mid-rail bias point the
rest of this repo's benches settle to (`sim/open-loop-ac/`'s `Lbreak` DC
servo lands `Vout(dc)` near `Vcm` by construction), so the two experiments'
operating points are directly comparable point-by-point.

This "sweep the differential input until the output nulls" formulation is
what makes the primary number free of any gain correction: `Vos` is read
directly off the swept input axis, not computed as an output error divided
by a separately measured gain.

### Sign convention

`inp` is this design's **non-inverting** input (`design/opamp_core.sch`'s
own "polarity" header; `design/opamp_sizing.md`), so `Vout` rises with
`Vid`. A **positive** reported `Vos` therefore means *`inp` must be held
above `inn` by `Vos` to bring the output to mid-rail* — i.e. the
amplifier's own systematic imbalance pulls the output low and the input
must compensate upward.

### Two passes (coarse locate, then fine read)

`run_offset_sweep.sh` renders `testbench/tb_offset_null.spice.tmpl` twice per
grid point:

1. **Coarse**: `Vid` swept `-100 mV … +100 mV` at `500 µV`. `±100 mV` is far
   wider than any plausible systematic offset of this topology, and wide
   enough that the output is hard-railed at both ends — which is what makes
   the single `Vout = Vcm` crossing unambiguous. The runner **requires
   exactly one crossing** and fails the point otherwise.
2. **Fine**: `Vid` re-swept over `±0.5 mV` around the coarse crossing at
   `4 µV`, i.e. sampled 125x finer. The reported `Vos` is interpolated from
   this pass; `vos_coarse_fine_delta_v` records how far it moved from the
   coarse read. Across the committed record that delta never exceeds
   **2.4 µV** on offsets of 11–22 mV (about 1 part in 5000), so the result
   is converged with three orders of magnitude of headroom in the fine
   window, not fitted to its edge.

The fine pass also records every internal node and the supply current, so
the DUT's operating point *at* the null is committed evidence rather than
something re-derived later. The coarse pass records `v(out)` alone — that
asymmetry is what keeps `corners/` to ~3 MB per run instead of ~17 MB.

### Two methods (primary + cross-check)

Issue #11 named two acceptable measurement routes. This bench runs **both**
at every point, because two independent routes to the same number are
strictly better evidence than one:

| | Primary | Cross-check |
|---|---|---|
| Testbench | `testbench/tb_offset_null.spice.tmpl` | `testbench/tb_offset_cl.spice.tmpl` |
| Configuration | open loop, differential input swept | DC unity-gain loop (`Lbreak = 1e18 H`, the same trick `sim/open-loop-ac/` uses) |
| Measured | `Vid` at which `Vout = Vcm` | `Vout - Vcm` with `V(inp) = Vcm` |
| Gain correction | none needed | `Vos = -(Vout - Vcm)·(1 + Av)/Av`, with `Av` from `sim/open-loop-ac/records/*.csv`'s `av0_db` column, **same grid point** |
| Input common mode | exactly `Vcm` | `Vcm - Vos/2` (`inn` follows the output) |

The two are expected to agree closely but not exactly, for one structural
reason worth stating rather than hiding: their input common-mode levels
differ by half an offset (tens of microvolts), which is a CMRR-order
difference. Measured agreement across the committed record is **≤ 304 µV
worst case, 104 µV mean** — around 1.4 % of the offset at the worst point.
The runner flags any point where the two methods disagree by more than
`max(200 µV, 5 % of |Vos|)` (`xcheck_pass = 0`); no point in the committed
record does.

### Per-point sanity checks

`run_offset_sweep.sh` records `op_pass = 0` for any point where:

- the coarse sweep does not have **exactly one** `Vout = Vcm` crossing, or
  the fine sweep's crossing sits on the edge of its window (both of these
  actually abort the point rather than merely flagging it);
- `Vd1`, `Vd2`, `Vtail` or `Vout` at the null is outside
  `(0.02·VDD, 0.98·VDD)` — i.e. any node railed to a supply;
- the fitted local gain at the null is below `20 dB` (a flat/degenerate
  "null" must not read as a plausible offset);
- `|Vos|` is not comfortably inside the coarse locate window.

**What this check does and does not verify**: exactly as in
`sim/open-loop-ac/README.md`, this OSDI/PSP103 build exposes no queryable
per-device operating-point parameters, so this is a *necessary, not
sufficient*, proxy for "every device is really in saturation at the null".
Every point in the committed record passed (`0` failures across all 45),
as did the two-method agreement check.

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
sim/input-offset/run_offset_sweep.sh    # deterministic 45-point PVT sweep (issue #11)
sim/input-offset/run_offset_mc.sh       #   Monte Carlo mismatch campaign (issue #17)
                                         #   (--seed <n> --n <N>, N>=300 enforced)
```

Requires `ngspice` on `PATH` (developed and run against `ngspice-46`) plus
the OSDI models `sim/tools/build-osdi.sh` builds; does **not** require
`xschem` at run time — `design/netlist/opamp_core.spice` is a committed,
pre-netlisted artifact. Also reads the newest
`sim/open-loop-ac/records/*.csv` for the cross-check's per-point `Av0`
(override with `AC_RECORD_CSV=<path>`); the record's own header names which
AC record it cross-referenced. The deterministic sweep runs the full 45-point
grid (135 ngspice invocations) in a few minutes on a modern laptop. The MC
campaign requires a committed deterministic record (it joins the systematic
values and anchors its negative control), runs 16 points x N draws (16x300
+ 1 = 4801 ngspice invocations, parallelizable with `--parallel`), and
refuses `--n < 300`. Both write new, timestamped, append-only records under
`netlist-snapshots/<record-id>/`, `corners/<record-id>/` and
`records/<record-id>.{csv,md}` — never overwriting a prior run.

## What was actually measured (this repo's committed record)

Record [`20260918-203858-90844d2`](records/20260918-203858-90844d2.md) —
all 45 points converged, all 45 passed both the per-point sanity check and
the two-method agreement check:

| Quantity | Range across all 45 points | Worst point |
|---|---|---|
| **`Vos`** (systematic, deterministic) | **+11.43 mV … +21.93 mV** | **+21.93 mV at `mos_fs_125C_1.08V`** |
| Two-method disagreement | 1.2 µV … 304 µV | 304 µV at `mos_fs_125C_1.08V` |
| Coarse-vs-fine null shift | < 2.4 µV | 2.4 µV at `mos_ss_-40C_1.32V` |
| Local DC gain at the null | 38.02 … 46.79 dB | 38.02 dB at `mos_fs_125C_1.08V` |
| Iq at the null (total, incl. `ibias`) | 100.7 … 120.2 µA | 120.2 µA at `mos_ss_-40C_1.32V` |

`Vos` is **positive at all 45 points** — this is a one-sided systematic
offset, not a scatter about zero (which is exactly what a deterministic,
mismatch-free measurement of a topology-driven imbalance should look like).

Full per-point data: [`records/20260918-203858-90844d2.csv`](records/20260918-203858-90844d2.csv).
Raw per-point ngspice logs and the full coarse/fine `Vid` sweep curves:
[`corners/20260918-203858-90844d2/`](corners/20260918-203858-90844d2/).
Frozen DUT netlist this record ran against:
[`netlist-snapshots/20260918-203858-90844d2/opamp_core.spice`](netlist-snapshots/20260918-203858-90844d2/opamp_core.spice).

### What drives it, and how it varies

Temperature and supply dominate; the process corner is a second-order
modifier:

- **Temperature** is the strongest axis. At `mos_tt / 1.20 V`, `Vos` rises
  monotonically `13.51 mV (-40 °C) → 15.72 mV (27 °C) → 18.53 mV (125 °C)`.
- **Supply** is next, inversely. At `mos_tt / 27 °C`, `Vos` falls
  `17.43 mV (1.08 V) → 15.72 mV (1.20 V) → 14.46 mV (1.32 V)`.
- **Process corner** moves it by only `1.65 – 2.93 mV` within any one
  `(temperature, supply)` cell — an order of magnitude less than the
  11–22 mV the offset itself spans.

The offset tracks the DC gain inversely across the whole grid: the worst
offset point (`mos_fs_125C_1.08V`) is also the lowest-gain point, both here
and in `sim/open-loop-ac/`. That is the expected signature of the mechanism
`design/opamp_sizing.md` predicted qualitatively in its "Expected systematic
offset" section — `M4` is forced by `M3`'s diode connection to a `Vsg` that
does not match what `M6`'s own bias point needs at `d2`, so the input pair
must carry a `Vgs` imbalance to reconcile the two, and the size of that
imbalance scales with how hard the first stage has to work (i.e. inversely
with its gain). Measured `V(d1) - V(d2)` at the null runs
`159 mV … 238 mV` across the grid, with `Vos` ranging from `6 %` to `13 %`
of that difference.

### Measured vs. predicted binding corner (honest comparison)

`spec/target-spec.md` §2's offset row predicted the binding corner as
*"to be determined once a topology is drawn — likely SS/FF split-corner
pairing on the input differential pair."* The measurement **partly confirms
and partly corrects** that:

- **Confirmed**: the *split* corners really are the extremes. In 7 of the 9
  `(temperature, supply)` cells, `mos_fs` is the worst corner and `mos_sf`
  the best; they bracket `mos_tt` in every cell. (The two exceptions are
  both at `1.08 V`, at `-40 °C` and `27 °C`, where `mos_ss` is worst and
  `mos_ff` best.)
- **Corrected**: the prediction named no temperature or supply, and those
  turn out to dominate. The measured binding point is
  **`FS / 125 °C / 1.08 V`** — the *same* binding point
  `sim/open-loop-ac/` measured for DC gain and GBW, and again not the
  "`SS / -40 °C`"-flavored generic guess the pre-schematic table made for
  its other rows.
- **Not addressed by this bench at all**: the *reason* the prediction named
  the input differential pair is random mismatch between `M1` and `M2`.
  This bench instantiates `M1` and `M2` identically and loads no mismatch
  deck, so it neither confirms nor refutes that part. Issue #17's Monte
  Carlo pass is what tests it.

Per `spec/target-spec.md`'s own footnote, this kind of correction — a real
testbench superseding a pre-schematic prediction — is expected, and
`sim/open-loop-ac/README.md` set the precedent for recording it rather than
quietly overwriting the guess.

## Monte Carlo mismatch campaign (issue #17)

The statistical half of the offset row — the `3σ, mismatch MC N≥300 +
process corners` basis `spec/target-spec.md` commits to and gap-to-T1
tracker #3 item 6 tracks — is produced by
[`run_offset_mc.sh`](run_offset_mc.sh), rendering
[`testbench/tb_offset_mc.spice.tmpl`](testbench/tb_offset_mc.spice.tmpl) once
per draw. This campaign's structure follows the convention
`sg13g2-bandgap`'s `sim/closed-loop-vref-mc` established on this same PDK
(recorded seed + sample count + deterministic negative control + mismatch
layered on process corners), with this repo's own two-bench split (the
deterministic sweep above remains the systematic source of truth, and the
campaign joins its per-point values rather than re-measuring them).

**Seeding — the mechanism that actually reaches the draws.** SG13G2's LV
MOS mismatch (`sg13g2_moslv_mod_mismatch.lib`) draws each device instance
via `agauss()` expressions on its instance parameters (w, l, delvto,
factuo), evaluated at circuit elaboration, not at netlist parse — so the
only seeding path that reaches them is `setseed <n>` in `.control`
followed by `reset` (which re-reads the deck and re-draws), verified
empirically on this exact PDK/OSDI/ngspice combination: same per-draw seed
→ byte-identical sweep across separate invocations; different seed → a
genuinely new draw of every device; plain (non-mismatch) section → output
invariant to the seed, which is exactly the negative control's required
zero-spread property. Every draw is its own ngspice invocation with
seed `base + draw_index`, `run_offset_mc.sh` refuses `--n < 300`, and an
in-campaign duplicate-draw self-check fails the whole campaign (no record
written) unless same-seed draws are bit-identical.
`tb_offset_mc.spice.tmpl`'s header documents two adjacent pit-falls for
the record: an `.options` seed placed on a netlist's FIRST line is
silently swallowed by ngspice's title-card rule, and
`sg13g2-bandgap`'s netlist-level `.options rndseed` finding does NOT
transfer to this deck (their HBT mismatch is `.param`-level, evaluated at
parse time — a different seeding path).

**Scope: corners × temperatures at nominal supply, N per point.** 15
mismatch points — every `cornerMOSlv.lib` family [DR-1]
(`mos_tt/ss/ff/sf/fs`) × {-40, 27, 125} °C — at the fixed nominal 1.20 V
supply, N = 300 draws per point, plus a 16th negative-control point
(`mos_tt` plain section at the nominal point, same seed sequence). Supply
is the axis held fixed while mismatch is sampled: the deterministic sweep
already covers all three supplies at every one of these corners and
temperatures, and random-vs-supply interaction is not an evidence class
issue #17 names. Each corner family is drawn N≥300 at EACH of its three
temperatures, so the row's "N≥300 per corner" basis holds everywhere it is
claimed.

**Per-draw method: the primary null sweep, coarse pass only.** Each draw
is the same open-loop differential-null measurement as the deterministic
bench's primary method, but single-pass: the committed deterministic
record's own `vos_coarse_fine_delta_v` evidence bounds the coarse-vs-fine
null delta at ≤ 2.4 µV across all 45 of its points — three orders of
magnitude below the mismatch term measured here — so re-running the fine
pass per draw would buy no statistical accuracy. Per-draw sanity gates
(clean simulator exit, no convergence error, exactly one `Vout = Vcm`
crossing, comfortably inside the ±100 mV window) fail the draw, not the
campaign; a point with any failed draw carries `status=FAIL` in the
digest.

**Hard gates, every run** (all three must pass or no record is written —
and the seed-determinism gate is what caught this campaign's own first
draft, whose seed line never reached the draws):

1. *Seed determinism*: a duplicated draw (same seed, separate invocation)
   must be bit-identical.
2. *Negative-control zero spread*: all N plain-section draws on the
   identical seed sequence must produce exactly the same Vos — any spread
   is a harness bug, not noise.
3. *Negative-control anchor*: that figure must reproduce the deterministic
   record's committed fine-pass `Vos` at `mos_tt_27C_1.20V` within 50 µV.

**Evidence volume.** Only draw 0's netlist + log per point (plus the
frozen DUT snapshot) is committed, matching the digest's per-point rows —
the 4801 per-draw netlists/logs/sweeps are campaign scratch, deleted on
exit; the full per-draw population lands in the committed
`records/<record-id>-draws.csv` (point, mode, draw index, per-draw seed,
status, Vos), one row per draw.

### What the campaign actually measured (this repo's committed record)

Record [`mc-20260921-174056-0a509fb`](records/mc-20260921-174056-0a509fb.md)
— campaign seed `20260921`, N = 300 per point, 16 points, 4800 of 4800
draws passed every per-draw sanity rule, all three hard gates passed
(machine-readable output in
[`corners/mc-20260921-174056-0a509fb/sanity_checks.txt`](corners/mc-20260921-174056-0a509fb/sanity_checks.txt)):

| Quantity | Range across the 15 mismatch points | Worst point |
|---|---|---|
| Mismatch σ(Vos) | 8.81 … 9.13 mV | 9.13 mV at `mos_ss_mismatch_125C` |
| **Mismatch 3σ** | 26.4 … **27.4 mV** | **27.4 mV at `mos_ss_mismatch_125C`** |
| MC sample mean vs deterministic systematic (harness-bias check) | ≤ 51 µV (σ/√N ≈ 0.5 mV) | 51 µV at `mos_ff_mismatch_-40C` |
| Negative control vs deterministic record | 1.17 µV (gate 50 µV) | single point, exactly zero spread |
| Worst-case single-PVT total (\|systematic\| + 3σ) | \[quoted per point in the digest] | **46.7 mV at `mos_fs_mismatch_125C`** |

The mismatch term **dominates a real part's offset budget**: systematic
offset runs 11–22 mV across the deterministic grid, while the 3σ random
term is ~27 mV at every point — the input differential pair is minimum-sized
(`0.13 µm` × `3.2 µm`, 0.416 µm² area), and SG13G2's
`sg13g2_lv_nmos_delvto_mm = 3.9 mV·µm` area law puts roughly
`3.9 mV / √0.416 µm² ≈ 6 mV` of 1-σ Vth scatter on each of its two devices
(~8.5 mV pair-referred), which is exactly the σ(Vos) the campaign measured.
That per-device area scaling is also why the 3σ figure is nearly
corner/temperature-flat (8.8→9.1 mV): mismatch is a device-area property;
PVT moves the systematic mean, not the spread. Pre-layout, schematic-level,
`[P]`-tagged — same non-claim stance as the deterministic record.

Full per-draw data:
[`records/mc-20260921-174056-0a509fb-draws.csv`](records/mc-20260921-174056-0a509fb-draws.csv).
Per-point digest:
[`records/mc-20260921-174056-0a509fb.csv`](records/mc-20260921-174056-0a509fb.csv).
Representative draw-0 netlists + logs and the frozen DUT snapshot:
[`netlist-snapshots/mc-20260921-174056-0a509fb/`](netlist-snapshots/mc-20260921-174056-0a509fb/),
[`corners/mc-20260921-174056-0a509fb/`](corners/mc-20260921-174056-0a509fb/).

## What this bench does not claim

- **The deterministic sweep is not the statistical offset.** No Monte
  Carlo, no mismatch deck (`sg13g2_moslv_mod_mismatch.lib`), no random
  draw, no seed — every matched pair is instantiated identically, so it
  measures the **systematic** offset only. The statistical complement now
  exists in the same directory as the Monte Carlo campaign below (issue
  #17); a real part's offset is the systematic number here *plus* the
  3σ random term that campaign measures — do not read either number alone
  as a worst-case part.
- **Not an offset over input common-mode range.** Every point is measured at
  `Vcm = VDD/2` only. Offset-vs-common-mode is the CMRR row (`[TBD-8]`) and
  needs its own bench.
- **Not a temperature-drift specification.** The temperature trend above is
  three sampled temperatures on a PVT grid, not a characterized drift
  coefficient.
- **Not a ratified spec claim for its 3σ half.** The `spec/target-spec.md`
  offset row's systematic term is ratified `[DR-2]`
  (`decision-records/0002-target-spec-ratification.md`); the
  Monte-Carlo-measured 3σ cells this directory adds stay `[P]` until the
  0002 residual-(c) re-ratification pass binds them — the same
  disposition `sim/cmrr-mismatch/` (issue #26) carries for the CMRR row.
  A bench's job ends at measured, machine-checked evidence.
- **Not proof the devices are in saturation at the null** at a
  device-by-device level — see "Per-point sanity checks" above for the
  honest scope of what is actually checked.

# input-offset

Deterministic, **corner-only** DC input-referred offset characterization of
`design/opamp_core.sch`'s two-stage Miller-compensated op-amp (issue #11),
across the full PVT grid. This bench fills `spec/target-spec.md`'s
`[TBD-7]` offset row with a measured number for the *systematic* half of
that row; the *statistical* half (`3σ, mismatch MC N≥300 + process corners`)
is deliberately a separate follow-on (issue #17) and nothing here claims it.

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
sim/input-offset/run_offset_sweep.sh
```

Requires `ngspice` on `PATH` (developed and run against `ngspice-46`) plus
the OSDI models `sim/tools/build-osdi.sh` builds; does **not** require
`xschem` at run time — `design/netlist/opamp_core.spice` is a committed,
pre-netlisted artifact. Also reads the newest
`sim/open-loop-ac/records/*.csv` for the cross-check's per-point `Av0`
(override with `AC_RECORD_CSV=<path>`); the record's own header names which
AC record it cross-referenced. Runs the full 45-point grid (135 ngspice
invocations) in a few minutes on a modern laptop. Writes a new, timestamped,
append-only record under `netlist-snapshots/<record-id>/`,
`corners/<record-id>/` and `records/<record-id>.{csv,md}` — never
overwriting a prior run.

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

## What this bench does not claim

- **Not the statistical offset.** No Monte Carlo, no mismatch deck
  (`sg13g2_moslv_mod_mismatch.lib`), no random draw, no seed — every matched
  pair is instantiated identically, so this measures the **systematic**
  offset only. `spec/target-spec.md`'s statistical-basis column
  (`3σ, mismatch MC N≥300 + process corners`) stays untouched, pending issue
  #17. A real part's offset is the systematic number here *plus* a random
  term this bench cannot see; do not read the 21.93 mV worst case as a
  worst-case part.
- **Not an offset over input common-mode range.** Every point is measured at
  `Vcm = VDD/2` only. Offset-vs-common-mode is the CMRR row (`[TBD-8]`) and
  needs its own bench.
- **Not a temperature-drift specification.** The temperature trend above is
  three sampled temperatures on a PVT grid, not a characterized drift
  coefficient.
- **Not a ratified spec claim.** The `spec/target-spec.md` row updated from
  this record is tagged `[P]` (proposal), not `[DR-n]` — see that file's
  Status (`DRAFT`) and its value-tag legend.
- **Not proof the devices are in saturation at the null** at a
  device-by-device level — see "Per-point sanity checks" above for the
  honest scope of what is actually checked.

# opamp_sizing — gm/ID sizing pass for the DR-0001 two-stage Miller op-amp

First-cut device sizing for the topology
[`spec/decision-records/0001-topology-and-cl.md`](../spec/decision-records/0001-topology-and-cl.md)
(DR-1) fixed — NMOS input pair, PMOS mirror load, single-ended Class-A
common-source PMOS output gain device loaded by an NMOS current sink,
non-cascoded, `CL = 2 pF` — sized against
[`sim/gm-id-characterization/records/20260909-063633-b402592.csv`](../sim/gm-id-characterization/records/20260909-063633-b402592.csv)
(the "CSV" below), per `CLAUDE.md`'s "gm/ID first" rule. Every device choice
below cites a literal `(device, length, corner, vgs, ...)` row of that CSV,
the same discipline DR-1 itself used. This is a sizing **pass**, not a
verified result — `sim/open-loop-ac/` (this same issue) is the testbench
that checks whether these first-order numbers hold up in real simulation.

All CSV rows were characterized at `W = 10 um`, `Vds = 0.6 V`, 27 °C,
`Vsb = 0`. Because `gm`, `Id` and `Cgg` all scale ~linearly with `W` at
fixed `Vgs`/`Vds`/`L` (the CSV's own normalization argument, see
`sim/gm-id-characterization/README.md`), every device below is sized by
picking a CSV row (fixing `Vgs`, hence `gm/Id`, `gm/gds`, `overdrive`) and
then scaling `W` linearly to hit the target branch current. Scaled
quantities are marked "(scaled)" below; un-marked numbers are read directly
from the cited row.

## Bias scope (per issue #9 "Out of scope")

A single `ibias` pin, driven by an ideal external current source in the
`sim/open-loop-ac/` bench, is the only bias input this design accepts — no
bias generator (bandgap/PTAT reference, cascode bias tree, etc.) is
designed here. Internally, `ibias` feeds exactly one diode-connected NMOS
reference device (`Mbias`); every other current-source/sink leg that needs
a fixed gate bias (the tail `M5`, the output-stage sink `M7`) mirrors off
`Mbias`'s gate node at the *same* channel length, so each mirror ratio is a
plain `W` ratio at one shared `Vgs` — no second bias branch, cascode bias,
or beta-multiplier is introduced. This one choice (single length family for
all `ibias`-mirrored NMOS legs) does cost second-stage gain relative to
what a longer-`L` `M7` could reach — see "Output stage" below, where the
trade-off is made explicit rather than silently absorbed into a bias
generator that would be out of scope.

## Stage 1 — NMOS input pair + PMOS mirror load + NMOS tail

### M1, M2 — NMOS input pair

CSV row: `nmos,0.13u,mos_tt,0.3900,0.6000,1.560450e-05,3.452262e-04,1.809463e-05,1.355950e-14,22.123503,20.002735e-4(gm)... ,4.052100e+09,0.3598,0.0302`
(full row: `nmos,0.13u,mos_tt,0.3900,0.6000,1.560450e-05,3.452262e-04,1.809463e-05,1.355950e-14,22.123503,19.078931,4.052100e+09,0.3598,0.0302`)

- `Vgs = 0.39 V`, `Vth = 0.3598 V` → overdrive `= 0.0302 V` (moderate
  inversion, chosen over the peak-`gm/Id` deep-subthreshold points so the
  pair has margin against `Vth` shifting `+` at `mos_ss`/cold without
  falling out of saturation given the ~0.21 V tail headroom available at a
  `Vcm ≈ 0.6 V` input common mode on a 1.08 V worst-case low rail — see
  "Headroom check" below).
- `gm/Id = 22.1235 /V`, `gm/gds = 19.0789`, `Cgg = 1.35595e-14 F`,
  `fT = 4.0521e9 Hz`, all at the CSV's `W = 10 um` reference.
- **Target branch current**: `I_D1 = I_D2 = 5 uA`.
- **Sizing**: `W = 10 um * (5 uA / 15.6045 uA) = 3.20 um` → **`W1 = W2 = 3.2 um`, `L = 0.13 um`** (`sg13_lv_nmos`, `ng=1`, `m=1`).
- **Scaled**: `gm1 = 22.1235/V * 5 uA = 110.6 uS`; `gds1 = gm1 / 19.0789 = 5.80 uS`;
  `Cgg1(scaled) = 1.35595e-14 F * 0.32 = 4.34 fF`.

### M3, M4 — PMOS mirror load

CSV row: `pmos,0.52u,mos_tt,0.6100,0.6000,4.790860e-05,3.572028e-04,5.267933e-06,4.779600e-14,7.455922,67.807013,1.189442e+09,0.3681,0.2419`

- `Vgs(sg) = 0.61 V`, overdrive `= 0.2419 V`, `gm/Id = 7.4559 /V`,
  `gm/gds = 67.807`, `Cgg = 4.7796e-14 F` at `W = 10 um`.
- Length `0.52 um` (not the minimum `0.13 um`, nor DR-1's `1.04 um`
  output-device class) is chosen to keep this load device's own `gds`
  small relative to `gm1` without paying `1.04 um`'s area/bias-current cost
  on a device that only needs to mirror the input pair's own modest 5 uA
  branch current — the mirror's job here is minimizing its contribution to
  the first-stage pole/output-impedance loss, not maximizing its own
  intrinsic gain the way the *output*-stage PMOS device (below) does.
- **Target branch current**: `I_D3 = I_D4 = 5 uA` (matches the input pair).
- **Sizing**: `W = 10 um * (5 uA / 47.9086 uA) = 1.045 um` → **`W3 = W4 = 1.04 um`, `L = 0.52 um`** (`sg13_lv_pmos`).
- **Scaled**: `gm3 = 7.4559/V * 5 uA = 37.28 uS`; `gds3 = 37.28 uS / 67.807 = 0.550 uS`.
- **Wiring**: `M3` diode-connected (`gate = drain = d1`, `source = vdd`);
  `M4` mirrors (`gate = d1`, `drain = d2`, `source = vdd`). `d1 = M1` drain,
  `d2 = M2` drain `= M6` gate (the first-stage output / second-stage input
  node the Miller cap lands on).

### M5 — NMOS tail current source

CSV row: `nmos,0.52u,mos_tt,0.3500,0.6000,4.560231e-05,6.097077e-04,2.221050e-05,3.897390e-14,13.370106,27.451327,2.489820e+09,0.1950,0.1550`

- `Vgs = 0.35 V`, `Vth = 0.1950 V` → overdrive `= 0.1550 V`, deliberately
  *lower* than the mirror-load or output-stage overdrives above so the tail
  device's own saturation `Vds` requirement (`≈` its overdrive, `0.155 V`)
  fits under the `≈0.21 V` of `Vds` the tail node actually gets at a
  `Vcm = 0.6 V` input common mode with the input pair's `Vgs1 = 0.39 V`
  (`0.6 - 0.39 = 0.21 V`, see "Headroom check" below) — a higher-overdrive
  tail choice (e.g. the `0.275 V`-overdrive row used for `M7`'s family
  elsewhere in this table) would not leave the tail device saturated at
  this common-mode point.
- `gm/Id = 13.3701 /V`, `gm/gds = 27.4513` at `W = 10 um`.
- **Target current**: `I_tail = 10 uA` (`= I_D1 + I_D2`).
- **Sizing**: `W = 10 um * (10 uA / 45.6023 uA) = 2.193 um` → **`W5 = 2.2 um`, `L = 0.52 um`**.
- **Scaled**: `I_D5 ≈ 45.6023 uA * 0.22 = 10.03 uA` (target hit to ~0.3%);
  `gds5 = 2.22105e-5 S * 0.22 = 4.89 uS` (`ro5 ≈ 205 kΩ`, the tail's own
  output impedance — relevant to CMRR, not scoped by this open-loop bench).
- **Wiring**: `drain = tail` (sources of `M1`/`M2`), `gate = ibias`,
  `source = vss`.

### Mbias — NMOS diode-connected bias reference

Same CSV row as `M5` (`nmos,0.52u,mos_tt,0.3500,...`), same `L = 0.52 um`,
so it shares one `Vgs` node with every NMOS leg that mirrors off it.
**Sized identically to `M5`: `W = 2.2 um`, `L = 0.52 um`, `gate = drain =
ibias`, `source = vss`.** The bench's ideal `ibias` current source is set
to **`10 uA`**, so `Mbias` reproduces exactly the CSV row above at its
design point, and `M5` (unit-matched, `1:1`) mirrors that `10 uA` into the
tail by construction — no separate tail-current calibration needed beyond
matching `W5 = Wbias`.

### Headroom check (input common mode, `Vcm = 0.6 V`, 1.08 V worst-case low rail)

- Tail node `= Vcm - Vgs1 = 0.6 - 0.39 = 0.21 V`. `M5` needs
  `Vds5 >= overdrive5 = 0.155 V` to stay saturated — `0.21 V` clears this
  with `≈55 mV` of margin at the nominal `mos_tt` point. This margin
  shrinks at `mos_ss`/cold (`Vth` up, `Vgs1` for the same `Id` up, tail
  node lower) — the `sim/open-loop-ac/` bench's per-point saturation check
  is exactly what confirms this margin actually survives the full PVT
  grid, not just this nominal hand-check.
- `d1`/`d2` node (`≈ VDD - Vsg3 = VDD - 0.61 V`): at `VDD = 1.08 V`
  (worst-case low rail) this is `≈0.47 V`, comfortably inside `M3`/`M4`'s
  saturation region (`Vsd = 0.61 V >> overdrive 0.2419 V`) and inside
  `M6`'s gate-drive range (see "Output stage" below).

### Stage 1 gain (first order)

`Av1 = gm1 / (gds1 + gds3) = 110.6 uS / (5.80 uS + 0.550 uS) = 110.6 / 6.35 ≈ 17.4`
(`≈ 24.8 dB`). This is the mirror/tail-*loaded* first-stage gain — lower
than a bare `gm1/gds1` estimate (`≈19.1`) would suggest, because `gds3`
(the mirror load's own output conductance) adds in parallel. This is the
kind of loading DR-1's own topology estimate explicitly excluded ("before
any mirror/tail loading is accounted for") and that this sizing pass now
includes.

## Stage 2 — PMOS output gain device + NMOS output current sink + compensation

### M6 — PMOS output gain device

CSV row: `pmos,1.04u,mos_tt,0.5500,0.6000,1.641100e-05,1.473258e-04,1.139920e-06,8.849680e-14,8.977259,129.242228,2.649545e+08,0.3577,0.1923`

- `L = 1.04 um` (DR-1's own candidate output-device length class — the
  longest length this repo's gm/ID study characterized, chosen because
  PMOS `gm/gds` grows sharply with length in this PDK, per DR-1's own
  citation of this same length family).
- `Vgs(sg) = 0.55 V`, overdrive `= 0.1923 V`, `gm/Id = 8.9773 /V`,
  `gm/gds = 129.242`, `Cgg = 8.8497e-14 F` at `W = 10 um`.
- **Target current, derived from the compensation budget below**:
  `I_D6 ≈ 54.2 uA`.
- **Sizing**: `W = 10 um * (54.2 uA / 16.411 uA) = 33.03 um` → **`W6 = 33 um`, `L = 1.04 um`**.
- **Scaled**: `I_D6 = 16.411 uA * 3.3 = 54.16 uA`; `gm6 = 147.3258 uS * 3.3 = 486.2 uS`;
  `gds6 = 1.13992e-6 S * 3.3 = 3.76 uS`.
- **Wiring**: `source = vdd`, `gate = d2` (stage-1 output), `drain = out`.

### M7 — NMOS output current sink

CSV row: same family as `M5`/`Mbias`, `nmos,0.52u,mos_tt,0.3500,0.6000,4.560231e-05,6.097077e-04,2.221050e-05,...,13.370106,27.451327,...,0.1950,0.1550`.

- **Deliberately kept at `L = 0.52 um`** (the tail/`Mbias` family length),
  *not* a longer `L` (e.g. the `1.04 um` NMOS row, `gm/gds = 30.72` at
  `Vgs = 0.53 V`, which would cut this device's `gds` contribution by
  ~2.4x) — see "Bias scope" above: mirroring `M7`'s gate off the same
  `ibias` node as `M5`/`Mbias` only gives an accurate current ratio when
  all three share one `L` (same `Vth`/mobility at a given `Vgs`). Using a
  second length for `M7` would need a second diode-connected bias branch
  fed some other way — a bias-generator feature explicitly out of scope
  for this pass. This is a deliberate gain-vs-bias-simplicity trade-off,
  not an oversight; see "Stage 2 gain" below for its cost, and "Follow-up
  candidates" for the fix if `sim/open-loop-ac/`'s measured `Av0` needs it.
- **Target current**: `I_D7 ≈ I_D6 = 54.2 uA` (matches the gain device's
  branch current at the shared `out` node).
- **Sizing**: `W = 10 um * (54.2 uA / 45.6023 uA) = 11.885 um` → **`W7 = 11.9 um`, `L = 0.52 um`**.
- **Scaled** (same `Vgs = 0.35 V` as `M5`/`Mbias`, so this is a `W`-ratio
  mirror off `Mbias` at ratio `11.9 / 2.2 = 5.41x` of the `10 uA` `ibias`
  reference, giving `I_D7 ≈ 54.1 uA` — matches `M6`'s target to ~0.1 uA):
  `gds7 = 2.22105e-5 S * 1.19 = 26.4 uS`.
- **Wiring**: `drain = out`, `gate = ibias`, `source = vss`.

### Stage 2 gain (first order)

`Av2 = gm6 / (gds6 + gds7) = 486.2 uS / (3.76 uS + 26.4 uS) = 486.2 / 30.2 ≈ 16.1`
(`≈ 24.1 dB`). `M7`'s `gds` (the single-length-family trade-off above)
dominates this sum — a longer-`L` `M7` would raise `Av2` to `≈33` (`≈30.4
dB`) at the cost of the bias-generator scope this pass avoids. See
"Follow-up candidates."

### Cc — Miller compensation capacitor

`cap_cmim`, connected from `out` to `d2` (the node `M6`'s gate sits on),
the standard two-stage Miller placement across the second (inverting,
`gm6`) stage.

**Sizing target**: the classic two-stage 60° phase-margin rule of thumb —
non-dominant pole `p2 = gm6 / (2*pi*CL)` at least `2.2x` the unity-gain
frequency `GBW = gm1 / (2*pi*Cc)` — i.e. `Cc >= 2.2 * CL * (gm1/gm6)`.
Working this the other way, `Cc = 1.0 pF` (half of `CL = 2 pF` [DR-1])
requires `gm6 >= 2.2 * gm1 * (CL/Cc) = 2.2 * 110.6 uS * 2 = 486.6 uS` — this
is exactly the `gm6` target `M6`'s sizing above hits (`486.2 uS`, matched
to ~0.1%), so `Cc` and `M6`'s current were sized jointly, not independently.

**`Cc = 1.0 pF`**, `cap_cmim`, `w = l` chosen from the model's own area/
perimeter capacitance formula in `cap_cmim.sym`
(`C = m*(w*l*1.5e-3 + 2*(w+l)*40e-12)` F, `w`/`l` in meters) — solving
`1.5e-3 * w^2 + 160e-12*w - 1.0e-12 = 0` for a square plate gives
`w = l ≈ 25.7 um`. **`w = l = 25.7 um`, `m = 1`.**

### Rz — nulling resistor: evaluated, not populated this pass

The issue scopes an "optional nulling Rz." **Not used in this first-cut
sizing**: the non-dominant-pole-to-GBW ratio the `Cc`/`M6` joint sizing
above already reaches (`p2/GBW`, computed below) lands at `≈2.2`, the same
threshold value the classic rule of thumb uses to reach `≈60°` phase margin
*without* a zero-nulling resistor. Adding one now, before any simulated
number exists to size it against, would be sizing a device against no
data — exactly what `CLAUDE.md`'s "gm/ID first" / "no claim without a
testbench" language warns against. **If `sim/open-loop-ac/`'s measured
phase margin comes in short of a future target, a PDK poly resistor
(`rppd`, already used elsewhere in this fleet, e.g.
`sg13g2-bandgap/design/bandgap_core.sch`) in series with `Cc`, sized near
`Rz ≈ 1/gm6 ≈ 2.06 kΩ` (using the scaled `gm6` above) to cancel the RHP
zero, is the first thing to try** — noted here so a future pass has a
concrete starting point instead of re-deriving it from scratch.

## First-order expected performance

| Quantity | Formula | Value |
|---|---|---|
| `Av0` (open-loop DC gain) | `Av1 * Av2 = 17.4 * 16.1` | `≈ 280` (`≈ 49.0 dB`) |
| `GBW` (into `CL = 2 pF` [DR-1]) | `gm1 / (2*pi*Cc)` | `110.6 uS / (2*pi*1 pF) ≈ 17.6 MHz` |
| Non-dominant pole `p2` | `gm6 / (2*pi*CL)` | `486.2 uS / (2*pi*2 pF) ≈ 38.7 MHz` |
| `p2 / GBW` ratio | — | `≈ 2.2` (60° rule-of-thumb target, no `Rz`) |
| `SR` (slew rate) | `I_tail / Cc` | `10 uA / 1 pF = 10 V/us` |
| `Iq`, signal-path branches | `I_tail + I_D6` | `10 uA + 54.2 uA ≈ 64.2 uA` |
| `Iq`, incl. `ibias` reference | `+ I(ibias)` | `≈ 74.2 uA` (see note below) |

**`Iq` reporting note**: the `10 uA` `ibias` reference current is, per this
issue's explicit scope, an *external* bias input, not a generator this
design owns — the same way a real chip's amplifier instance would share
one bandgap/bias-tree current across many blocks rather than each block
owning its own reference. `sim/open-loop-ac/` records **both** numbers
(total `VDD` supply current, and the signal-path-only figure above) rather
than picking one silently, so a future spec-bookkeeping pass can decide
which one a `[TBD-11]` quiescent-power row should actually cite.

**These are gm/gds-loaded, hand-computed first-order numbers, not a
simulated result.** `sim/open-loop-ac/` is the testbench that measures
`Av0`, unity-gain frequency, phase margin and gain margin directly from
`design/opamp_core.sch`'s real netlist across the full PVT grid — see that
experiment's own `README.md` and `records/` for what was actually measured
and how it compares to this table.

## Expected systematic offset (qualitative)

`M4` (mirror output) is forced by `M3`'s diode connection to carry
`≈ I_D1` at `Vsg = 0.61 V` regardless of `d2`'s voltage, while `M6`'s
target bias point independently needs `d2 ≈ VDD - 0.55 V` to source
`54.2 uA`. In a real (non-ideal-servo) closed loop, the input pair carries
a small systematic `Vgs` imbalance to reconcile this — an expected
built-in systematic input-referred offset contribution from stage-2 current
sizing, not a design defect. This is exactly the kind of second-order
effect `sim/open-loop-ac/`'s ideal-servo DC bias point (see that
experiment's `README.md`) is built to establish correctly rather than
leaving ambiguous, and exactly why a future `[TBD-7]` offset row needs its
own dedicated Monte Carlo bench (explicitly out of scope here, see below)
rather than a hand estimate.

## Device summary

| Device | Type | W | L | Branch I | CSV anchor row (`Vgs`, corner) |
|---|---|---|---|---|---|
| M1, M2 | `sg13_lv_nmos` | 3.2 um | 0.13 um | 5 uA each | `nmos,0.13u,mos_tt,0.39` |
| M3, M4 | `sg13_lv_pmos` | 1.04 um | 0.52 um | 5 uA each | `pmos,0.52u,mos_tt,0.61` |
| M5 | `sg13_lv_nmos` | 2.2 um | 0.52 um | 10 uA (tail) | `nmos,0.52u,mos_tt,0.35` |
| Mbias | `sg13_lv_nmos` | 2.2 um | 0.52 um | 10 uA (= `ibias`) | `nmos,0.52u,mos_tt,0.35` |
| M6 | `sg13_lv_pmos` | 33 um | 1.04 um | 54.2 uA | `pmos,1.04u,mos_tt,0.55` |
| M7 | `sg13_lv_nmos` | 11.9 um | 0.52 um | 54.1 uA | `nmos,0.52u,mos_tt,0.35` |
| Cc | `cap_cmim` | 25.7 um x 25.7 um | — | — | (model formula, not gm/ID) |

Pin list (matches `design/opamp_core.sym`): `vdd`, `vss`, `inn`, `inp`,
`out`, `ibias`. `inn = M1` gate (inverting), `inp = M2` gate
(non-inverting) — see `design/opamp_core.sch`'s own header for the polarity
derivation (increasing `inp` raises `out`, the opposite for `inn`).

## Out of scope (per issue #9)

No bias generator beyond the single `ibias` pin/diode-reference described
above; no slew/large-signal, noise, offset Monte Carlo, CMRR, PSRR, or
output-swing bench (each its own follow-on `sim/<slug>/`, per this issue's
own scope); no layout/DRC/LVS; no re-opening of DR-1's cascode decision
(the loaded `Av0 ≈ 49 dB` first-order estimate above is lower than DR-1's
own unloaded `≈68 dB` illustrative estimate — if `sim/open-loop-ac/`'s
*measured* `Av0` does not close against a future ratified target, that
finding belongs in this record plus a superseding decision record, per
DR-1's own "Consequences" section, not a silent topology change here).

## Follow-up candidates (not performed here)

- Replace `M7`'s length family with a dedicated `L = 1.04 um` bias branch
  (recovering `Av2 ≈ 33`, `Av0 ≈ 574`, `≈55.2 dB`) if the measured `Av0`
  needs the extra ~6 dB and a bias-generator follow-on issue is opened to
  own the second reference branch this would need.
- A nulling `Rz` (candidate value `≈1/gm6 ≈ 2.06 kOhm`, PDK `rppd`) if
  measured phase margin comes in short of a future target.

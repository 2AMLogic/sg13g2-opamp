# gm-id-characterization

The first gm/ID device-characterization study for this block (issue #5),
and — verified against `sg13g2-bandgap`, `gf180-opamp`, and `sky130-opamp` at
the time this issue was curated — the first anywhere in the fleet. It exists
because `CLAUDE.md`'s "gm/ID first" rule and `spec/porting-plan.md` §4 both
name this sweep as the required predecessor to any sizing work, the topology
decision, and the load-capacitance (`CL`) choice.

## What this study measures

For each of SG13G2's two LV core MOS polarities (`sg13_lv_nmos`,
`sg13_lv_pmos`, PSP103.6 compact model), at four channel lengths and all
five `cornerMOSlv.lib` process corners, swept over gate bias from deep
subthreshold to strong inversion at a fixed `Vds = 0.6 V` (`VDD/2`,
`VDD = 1.2 V`, this block's nominal 1.2 V-primary supply per
`spec/target-spec.md` §1):

- **Id** — drain current
- **gm** — transconductance, `d(Id)/d(Vgs)`
- **gds** — output conductance, `d(Id)/d(Vds)`
- **gm/Id** — the gm/ID figure of merit itself
- **gm/gds** — intrinsic gain
- **Cgg** — total gate capacitance
- **fT** — `gm / (2*pi*Cgg)`, the intrinsic transition frequency
- **Vth** (constant-current definition) and **Vgs-Vth overdrive** — see
  "Threshold voltage definition" below

**Sweep grid**: device {nmos, pmos} x length {0.13u, 0.26u, 0.52u, 1.04u} x
corner {mos_tt, mos_ss, mos_ff, mos_sf, mos_fs} = 40 (device, length,
corner) combinations, 56 Vgs points each (`0.05 V` to `1.15 V`, `0.02 V`
step) = 2240 rows per full run.

- **Lengths**: `0.13 um` is SG13G2's minimum 1.2 V (LV) NFET/PFET GatPoly
  width (`libs.doc/doc/SG13G2_os_layout_rules.pdf`, rules Gat.a1/Gat.a2 —
  both `0.13`), confirmed against the local PDK install, not the PSP103
  model card's own `l=0.34u`/`l=0.28u` defaults (those are just the model
  file's example instantiation, not the process Lmin). The other three
  lengths are 2x/4x/8x multiples, per the issue's "minimum length to a few
  multiples of it" scope.
- **Corner grid**: `cornerMOSlv.lib`'s five `.LIB mos_*` process sections
  (`tt`/`ss`/`ff`/`sf`/`fs`), the same grid `spec/target-spec.md` §1's
  `[TBD-1]` guessed at (now confirmed correct against the local PDK
  install). Temperature is fixed at 27 C nominal for this pass — a full
  temperature-corner cross is deliberately deferred (see "Out of scope /
  follow-up" below); the sizing-relevant axis for a gm/ID sweep is process
  corner, and this block's classic-row testbenches (once a topology exists)
  will carry the temperature axis the way `sg13g2-bandgap`'s do.
- **Width**: fixed at `W = 10 um`, `ng=1`, `m=1` for every point. gm/ID
  methodology normalizes out W (gm, Id and Cgg all scale ~linearly with W at
  fixed Vgs/Vds/L, so gm/Id, gm/gds and fT are W-independent) — a single
  representative W avoids doing a redundant width sweep.
- **Bias**: `Vsb = 0` (source and body tied together) for both devices —
  the standard gm/ID characterization bias, per Sedra/Silveira-style sweeps.
  Body effect (Vsb != 0) is not part of this study's scope.

## Cold-start invocation

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh                 # one-time; idempotent (--check to verify only)
sim/gm-id-characterization/run_gmid_sweep.sh
```

(`PDK_ROOT`/`PDK` may be left unset if the PDK is installed under one of the
prefixes `sim/env.sh` checks automatically — `/usr/share/pdk`,
`/usr/local/share/pdk`, `~/share/pdk`, `~/.ciel`, `~/.volare`.) Requires
`ngspice` on `PATH` (developed and run against `ngspice-46`); does not
require `xschem` or `klt`. Runs in well under a minute (~30s on a modern
laptop for the full 40-point grid).

This generates one netlist per (device, length, corner) point from
`testbench/tb_gmid_{nmos,pmos}.spice.tmpl`, runs each through `ngspice -b`,
and writes a new, timestamped, append-only evidence record — never
overwriting a prior run — under:

- `netlist-snapshots/<record-id>/<device>_<length>_<corner>.spice` — the
  exact generated netlist for each point
- `corners/<record-id>/<device>_<length>_<corner>.log` — the raw ngspice
  batch output, and `..._dc.csv` — the raw per-point DC sweep dump
- `corners/<record-id>/sanity_checks.txt` — the automated correctness
  checks (see below)
- `records/<record-id>.md` — the human-readable summary
- `records/<record-id>.csv` — the parsed, merged, all-quantities-derived
  table (device, length, corner, vgs, vds, id, gm, gds, cgg, gm/Id, gm/gds,
  fT, Vth, overdrive) — **the summary artifact a sizing pass can work from
  without re-running ngspice**
- `records/<record-id>_gm_id_vs_overdrive.png`,
  `records/<record-id>_ft_vs_length.png` — plots of the same data (skipped,
  without failing the sweep, if `matplotlib` is not installed)

Exits non-zero if any point fails, the completeness matrix is short a cell,
or a sanity check fails.

## Threshold voltage definition

`Vth` is extracted per (device, length, corner) group using the
**constant-current definition**: `Id = 100 nA * (W/L)`, found by linear
interpolation in `log(Id)` vs `Vgs` between the two swept points bracketing
that current (accurate through the exponential subthreshold region). This
is one common, simple Vth convention among several in use industry-wide;
it is not itself a spec commitment — a future sizing pass is free to use a
different Vth extraction method against the same raw `Id(Vgs)` data in this
study's CSV if a different convention suits it better.

## Why finite-difference DC/AC, not model op-point queries

This PDK's PSP103 OSDI build (compiled from the Verilog-A sources by
`sim/tools/build-osdi.sh`, OpenVAF-Reloaded) does not expose `gm`/`gds`/
`cgg` as queryable operating-point parameters the way some legacy built-in
SPICE models do (`@m.xxx[gm]`-style access) — checked directly against the
Verilog-A source (`psp103.va` and its `.include` files) and found no
declared OP-info output for these quantities. So this testbench derives
them instead:

- **gm, gds**: a single nested `.dc` sweep — outer axis `Vds` at three
  closely-spaced points (`{0.58, 0.60, 0.62} V`), inner axis `Vgs` over the
  full range. `gm = d(Id)/d(Vgs)` via ngspice's `deriv()` on the central
  (`Vds=0.6V`) block; `gds = d(Id)/d(Vds)` via a central difference across
  the outer axis at matching `Vgs` indices.
- **Cgg, fT**: a second pass, one `Vgs` point at a time (`alter` + a single
  10 MHz `ac` analysis), reading `Cgg = Im(Ig) / (2*pi*f)` from the gate
  current phasor. `fT = gm / (2*pi*Cgg)` is then computed by the driver
  script from the two passes' results.

## ngspice gotchas this testbench works around

Two non-obvious ngspice behaviors cost significant debugging time building
this testbench; documented here so a future editor of these templates does
not rediscover them the hard way.

1. **wrdata column layout.** `wrdata file v1 v2 v3 v4` does **not** write
   one shared x-axis column followed by four value columns. It writes a
   *(scale, value)* pair **per requested vector**, so four vectors become
   **eight** columns: `scale1 v1 scale2 v2 scale3 v3 scale4 v4`. Verified
   empirically by comparing `wrdata` output against explicit
   `print vec[i,i]` at the same index for every vector. The awk merge step
   in `run_gmid_sweep.sh` reads columns `$2,$4,$6,$8` for
   `vgs,ids,gm,gds` — **not** `$1,$2,$3,$4` — because of this.
2. **Cross-plot vector lookup.** Every `dc`/`ac`/`op` analysis run from a
   `.control` block creates a new "plot" (`dc1`, `ac1`, `ac2`, ...) and
   makes it ngspice's *current* plot. A bare vector name (no plot prefix)
   resolves against the *current* plot only — a vector created under `dc1`
   becomes invisible to a bare-name reference once an `ac` analysis has run
   and made `ac1` (or later `ac2`, `ac3`, ...) current, **even to `print` or
   `wrdata`**, and even if the vector was only ever *read* (not
   re-assigned) after that point. This testbench avoids the problem
   entirely in the AC loop rather than working around it: Vgs values for
   the AC sweep are regenerated by plain arithmetic (`0.05 + i*0.02`, no
   dependency on any `dc`-plot vector), and each point's Vgs and Cgg are
   `echo`ed as separate, ordered lines (`GMID_VGS ...` then, after `ac` has
   run, `GMID_CGG ...`) rather than assembled into an ngspice-side result
   vector — because even *writing into* an existing vector's index
   (`vec[i] = value`) silently stops taking visible effect once the current
   plot has moved on from whatever plot that vector belongs to. The driver
   script pairs `GMID_VGS`/`GMID_CGG` lines by their sequence order in the
   log, not by any shared vector.
   - A related but distinct quirk: reading a **single** element by bare
     index (`vec[i]`) to define a *new* vector fails ("When creating a new
     vector, it cannot be indexed"); the fix is the same range syntax used
     for slices, with equal start/end (`vec[i,i]`).

## Observed sub-peak gm/ID roll-off in deep subthreshold

The raw gm/ID-vs-overdrive curves (see
`records/<record-id>_gm_id_vs_overdrive.png`) show a genuine peak a little
above the sweep's deepest-subthreshold point (`Vgs = 0.05 V`), not a
monotonic rise all the way from `Vgs = 0`: gm/Id at `Vgs = 0.05 V` sits
noticeably *below* the value at `Vgs = 0.07–0.25 V` for every
(device, length) combination checked. This is consistent with secondary
leakage-current components the PSP103 compact model includes (e.g.
junction/GIDL-type leakage, which does not scale with `Vgs` the same way
drift-diffusion subthreshold current does) pulling the local `Id` up
(and therefore local gm/Id down) right at the edge of the leakage floor —
not a numerical artifact of this testbench's finite-difference `gm`
(`gds` at the same points scales in step with `Id`, ruling out a
gds-dominated numerical blowup, and the effect spans many points, not just
the one or two nearest the sweep boundary where a one-sided `deriv()`
approximation would be expected to be less accurate). The automated sanity
check (see below) checks monotonic decrease from the observed *peak*
onward, which is the region that matters for a real sizing decision — no
practical amplifier design biases an input or bias device this deep in a
leakage-dominated subthreshold tail. The raw pre-peak points are still
recorded in the CSV, unedited, per `spec/porting-plan.md` §3's
append-only-evidence convention; they are just excluded from the
monotonicity *check*, not from the *data*.

## Sanity checks (issue #5 Test Plan)

`run_gmid_sweep.sh` runs two automated checks after every sweep, writing
`corners/<record-id>/sanity_checks.txt` and folding the result into
`records/<record-id>.md`:

1. **gm/ID monotonically decreasing vs overdrive**, from its observed peak
   onward (see above), at `mos_tt`, for every (device, length) pair.
2. **fT increases as length decreases**, compared across all four lengths
   at `mos_tt`, near a representative `0.3 V` overdrive.

Both checks passed for the record run to produce this README (see the
linked record for its own timestamp/hash). A failing sanity check makes
`run_gmid_sweep.sh` exit non-zero.

## Completeness

`run_gmid_sweep.sh` also asserts every one of the 40 (device, length,
corner) cells produced at least 50 of its 56 expected merged rows — a
silently-skipped corner or polarity fails the sweep rather than passing
silently, per this issue's own Test Plan "Edge cases" item.

## What this study is not

- **Not a circuit claim.** No schematic exists yet in this repo
  (`design/` is still a scaffold `README.md`) — this is pure device
  characterization, feeding the *next* design step, not a claim against any
  `spec/target-spec.md` row directly.
- **Not the topology decision or the CL choice.** Both are explicitly out
  of scope for this issue (`spec/porting-plan.md` §4's first two bullets) —
  see the follow-up issue filed alongside this study for tracking that
  next step now that gm/ID data exists to inform it.
- **Not a full PVT (temperature x corner) sweep.** Temperature is fixed at
  27 C nominal; see "Sweep grid" above.
- **Not a body-effect (Vsb != 0) characterization.** `Vsb = 0` throughout.

## Which `spec/target-spec.md` rows this study feeds

Per `CLAUDE.md`'s "gm/ID first" ordering, every gm/ID-dependent row in
`spec/target-spec.md` §2 is currently `[TBD-#n]` pending exactly this kind
of data. This study is the device-level input those rows will draw on once
a topology exists to size:

- **`[TBD-3]` Open-loop DC gain** — from `gm/gds` (intrinsic gain) at the
  chosen input-pair and load-device operating points.
- **`[TBD-4]` GBW (into stated CL)** — from `gm` at the input pair's chosen
  bias, once `CL` (`[TBD-2]`) is chosen.
- **`[TBD-5]` Slew rate** — from the chosen tail/bias current and `CL`.
- **`[TBD-11]` Quiescent power** — from the chosen bias currents, which a
  gm/ID-based sizing pass picks using this study's `gm/Id` vs overdrive
  curves.
- Indirectly, **`[TBD-1]` Corner grid** — this study is the first place in
  the repo the `cornerMOSlv.lib` five-corner grid guessed at in
  `spec/target-spec.md` §1 is exercised and confirmed against the real PDK
  install.

`fT` (this study) also bounds how aggressively a future compensation-scheme
decision can push non-dominant-pole placement, relevant to the phase-margin
row, though no specific `[TBD-#n]` row is fT itself.

## Out of scope / follow-up

Per this issue's own "Out of scope" section: the topology decision and the
`CL` choice are not made here. A follow-up issue is filed to track using
this study's data for those decisions. A full temperature-corner cross (this
pass fixes 27 C) is also a candidate future extension, filed as a follow-up
rather than expanding this issue's scope after the fact.

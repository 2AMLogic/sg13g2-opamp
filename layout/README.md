# layout/

The block's placed-and-routed `opamp_core` GDS, plus the SG13G2
drawing/routing **scaffold** it is drawn with and the smoke fixture that
proves the scaffold.

- **`opamp_core/`** — all nine instances of
  `design/netlist/opamp_core.spice`, placed, wired and labelled, with a
  committed `klt drc --deck sg13g2` report. This is what `signoff/` cites for
  T1 items 2 and 3. Read ["The op-amp layout"](#the-op-amp-layout-opamp_core)
  below before reading anything into that.
- **`builder.py` / `devices.py` / `sg13g2_layers.py`** — the machinery:
  a cited SG13G2 layer table, a `klayout.db` builder with routing / via / tap
  primitives, and `klt gen` wrappers for the three device flavours the
  netlist needs.
- **`scaffold_smoke/`** — one device of every shape the netlist asks for,
  deliberately *not* wired into the topology, as proof the scaffold draws
  legal geometry. It is scaffolding proof only, and nothing under `signoff/`
  cites it.
- **What still does not exist**: no LVS, no parasitic extraction, no
  post-layout sim, no supply/ERC spec
  ([#29](https://github.com/2AMLogic/sg13g2-opamp/issues/29)), no pad ring.

## Files

The structure mirrors `2AMLogic/sg13g2-bandgap`'s: shared drawing modules at
`layout/`, and one directory per group of drawn artifacts holding its
`generate.py`, its `.gds` and its `drc_report.json`.

| Path | What it is |
|---|---|
| `sg13g2_layers.py` | The SG13G2 layer table + the curated deck's 43 rule minima, each with its provenance inline. `verify_deck_minima()` re-derives the minima from the installed `klt` and raises on drift. Counterpart of the precedent's `common.py` layer table. |
| `builder.py` | `Builder`: one `kdb.Layout` at `dbu = 0.001`, micron-valued `box`/`label`/`pr_boundary`/`route_h`/`route_v`/`cut_array`/`landing_pad`/`via`/`via_stack`/`tap`, `place_stream` for importing a generator stream, and a timestamp-free `write`. Counterpart of `_klayout_builder_base.py`. |
| `devices.py` | `lv_nmos()` / `lv_pmos()` / `cmim_cap()` — thin, validated wrappers over `klt gen mos_array` / `klt gen cap_array` against the `ihp-sg13g2` PDK — plus `patch_mim_bottom_plate()`, the one implementation of the MIM.c correction both committed streams use. |
| `opamp_core/floorplan.py` | Every coordinate of the block in one file: device placements, the Metal3 track ordinates and the Metal2 lanes, with the invariants they rest on asserted at import time. |
| `opamp_core/generate.py` | Places and routes the block, cross-checks itself against the netlist file, re-extracts the drawn connectivity, writes the GDS and runs DRC. Also `--check`, `--devices` and `--negative-control`. |
| `opamp_core/opamp_core.gds` | **The committed layout.** |
| `opamp_core/drc_report.json` | Its committed `klt drc --deck sg13g2 --format json` report. |
| `scaffold_smoke/generate.py` | The smoke fixture: draws every device shape the netlist asks for plus one of each routing/tap/via primitive, writes the GDS, runs DRC, writes the report. Also `--check` and `--negative-control`. |
| `scaffold_smoke/sg13g2_opamp_scaffold_smoke.gds` | The committed smoke stream. |
| `scaffold_smoke/drc_report.json` | Its committed `klt drc --deck sg13g2 --format json` report. |

## Regenerating

```sh
# From the repo root. Requires `klt` on PATH and an ihp-sg13g2 PDK install
# (found via $PDK_ROOT, else the same candidate list sim/env.sh searches).
python3 layout/opamp_core/generate.py

# Verify instead of overwrite: regenerates into a temp dir and fails on any
# drift from the committed GDS (byte-for-byte) or DRC verdict/coverage.
python3 layout/opamp_core/generate.py --check

# DRC each generated device stream on its own, before assembly.
python3 layout/opamp_core/generate.py --devices

# Negative control: delete one wire and prove the connectivity self-check
# notices (and that `klt drc` does not). Writes nothing to the repo.
python3 layout/opamp_core/generate.py --negative-control

# The scaffold's own smoke fixture, same four verbs minus --devices.
python3 layout/scaffold_smoke/generate.py [--check|--negative-control]
```

### Revisions the committed artifacts were produced with

| Thing | Value |
|---|---|
| `klt` (for `opamp_core/`) | `0.6.0+gd574697ed72c` — read back from `opamp_core/drc_report.json`'s own `provenance.klt_version` rather than transcribed, so this row cannot drift from the committed bytes it describes. |
| `klt` (for `scaffold_smoke/`) | `0.6.0+g9c11986ad447` — the revision that stream was first written with ([#44](https://github.com/2AMLogic/sg13g2-opamp/issues/44)). It still regenerates **byte-for-byte** at `gd574697ed72c` (`scaffold_smoke/generate.py --check` passes), so the two revisions draw identical geometry for this repo's shapes; the older value is kept because it is the one the committed bytes were actually produced with. |
| Curated `sg13g2` deck | `sha256:894326a4e37fb24fef2f7ffc6ae1da55a0e262b0f0bc1c09adc4862909278fda`, 43 rules, `released: yes` (`klt deck hash --deck sg13g2`) — unchanged across both `klt` revisions above |
| KLayout inside `klt` | `0.30.12`, which the report flags as `provenance.klayout_version_mismatch: true` — that `klt` build was tested against `klayout==0.30.10`. Per `klt`'s own warning the *verdict* is unaffected; report counts could in principle differ on the tested engine. |
| KLayout used by `builder.py` | `0.30.10` (the host `python3`'s `klayout` package), i.e. the tested version |
| PDK | IHP-Open-PDK `v0.3.0`, variant `ihp-sg13g2` — the release `sim/pdk.json` pins for this repo's evidence records |

**These are deliberately not `signoff/klt-pin.txt`.** That pin
(`b15edf5e3a2e56467a3406c98a2555eb1a5ae45c`, `klt 0.5.0`) exists so `klt
signoff --manifest`'s *T1 checklist skeleton* cannot move under the committed
verdict of record. It governs **how the register is graded**, not how the
evidence is produced, and the two are independent on purpose: the DRC
envelope `signoff/block-manifest.json` now cites for items 2 and 3 was
produced by the `klt` in the first row, and is *graded* by the pinned one.
Both were checked to agree — `klt signoff --manifest` renders items 2 and 3
`met` with byte-identical citation blocks at `0.5.0+gb15edf5e3a2e` (via
`uvx --from git+…@b15edf5e3a2e…`, the revision CI installs) and at
`0.6.0+gd574697ed72c` (the host `klt`), both re-grades matching the committed
record verbatim. A future change that makes them disagree owns reconciling
the two revisions, and must say which one moved.

## Which option was chosen, and why

Issue [#44](https://github.com/2AMLogic/sg13g2-opamp/issues/44) offered two
routes and allowed a mix. **A mix was chosen: `klt gen` generators for device
geometry (option 1), hand-drawn `klayout.db` primitives ported from the
in-fleet `2AMLogic/sg13g2-bandgap` precedent for everything else (option 2).**

**Devices via `klt gen`, because the generators genuinely work on this family
and the tool's validation is worth more than ours.** Verified on this host,
2026-09-28, against `klt 0.6.0+g9c11986ad447`: `klt gen mos_array --pdk
ihp-sg13g2` and `klt gen cap_array --pdk ihp-sg13g2` both resolve the
`ihp-sg13g2` family and draw *this* PDK's layer numbers — `mos_array` draws
`Activ` 1/0, `GatPoly` 5/0, `Cont` 6/0, `Metal1` 8/0 and, with
`flavor="pfet"`, `NWell` 31/0; `cap_array` draws `MIM` 36/0 over `Metal5` 67/0
with a `Vmim` 129/0 via to `TopMetal1` 126/0 — exactly the layers the curated
deck's `nfet` / `pfet` / `cap_cmim` device classes name (`klt deck devices
--deck sg13g2`). Each of the three streams is independently `klt drc --deck
sg13g2` clean.

> **Caveat on the tool's own help text.** `klt gen --help` on this revision
> claims "every generator except resistor_strip only supports the
> sky130/gf180mcu PDK families today (any other resolved family is an
> application error)". That is **stale** — the sg13g2 invocations above
> succeed, exit 0, and report `pdk.variant: ihp-sg13g2`. The behaviour, not
> the help text, is what this scaffold relies on, and `devices.run_gen()`
> asserts the resolved variant rather than trusting it.

**Everything else hand-drawn, because no generator covers it and the
precedent does.** Routing bars, via stacks with per-metal landing pads,
well/substrate ties, labels, PR boundary and deterministic GDS write-out are
all needed for interconnect regardless of what draws the devices.
`builder.py` follows `2AMLogic/sg13g2-bandgap`'s
`layout/_klayout_builder_base.py` + `layout/common.py` (at that repo's
`889a0d9`): same `dbu = 0.001`, same rounding `_u()`, same micron-valued
`box()`, same `gds2_write_timestamps = False` write. Three deliberate
departures:

1. `route_h`/`route_v` are **methods** here, free functions taking a
   `BuilderBase` there.
2. Every helper sizes itself from `DECK_MIN_UM` — the values `klt deck rules
   --deck sg13g2` reports — instead of a hand-entered literal (the
   precedent's `route_h`/`route_v` default to `width = 0.3`). A deck bump
   that tightens a rule this code sized against therefore fails the
   regeneration loudly via `verify_deck_minima()` instead of leaving a stale
   constant in place.
3. `Builder.via()` draws a **separate, independently sized landing pad on each
   of the two metals** it joins. SG13G2's upper via rules are strongly
   asymmetric — `metal5.enclosing.topvia1.1` is 0.10 µm while
   `topmetal1.enclosing.topvia1.1` is 0.42 µm *and* `topmetal1.width.1` is
   1.64 µm — so one shared pad sized off the lower metal violates two of the
   upper metal's rules. The bandgap precedent has no metal-to-metal `via()`
   helper to depart from; this is the SG13G2-specific part that had to be
   derived here.

The two primitives the issue identified as genuinely missing from the bandgap
repo (LV core MOS, MIM cap) are therefore supplied as **generator wrappers**
rather than as hand-drawn geometry — with one exception, below, where the
generator's output had to be corrected.

---

# The op-amp layout (`opamp_core/`)

85.3 µm × 32.5 µm (`prBoundary` 189/0 at `(-11.5, -0.7)`–`(73.8, 31.84)`),
nine instances, nine nets, six labelled ports.
`sha256:2c5829ed6a664ca7904b0012cac09c8a832e11b1cc0d2279f0c7b680e38cf4c9`.

## Floorplan

Three columns, read left to right:

| Column | Contents | x (µm) |
|---|---|---|
| 1 | Stage 1 + the bias reference, stacked bottom-to-top in signal order: tail/bias pair (XM5 + XMbias), input pair (XM1 + XM2), mirror load (XM3 + XM4) | 0 … 12.6 |
| 2 | Stage 2: output tail XM7 below, the folded gain device XM6 above | 21 … 41.4 |
| 3 | The Miller capacitor XCc | 46 … 72.7 |

XCc alone is 26.7 µm × 28.8 µm — **larger than the entire amplifier** — which
is why it gets a column rather than a corner. The left channel (x < 0) carries
the vertical links between channels and the five left-edge port pads.

`opamp_core/floorplan.py` holds every one of those coordinates, and the two
invariants the routing rests on (`Metal2` vertical / `Metal3` horizontal; one
unique, non-crowding ordinate per horizontal track) are asserted there at
import time rather than left as prose.

## Matching: what was chosen for XM1/XM2 and XM3/XM4, and what it costs

**Both matched pairs — and the tail/bias pair XM5/XMbias, which is equally a
matched pair — are drawn as one-row interdigitated arrays in `B A A B` order
with a dummy column at each end.** Each netlist device is split into two
half-width units (`XM1` = 2 × 1.6 µm, not 1 × 3.2 µm; `XM3` = 2 × 0.52 µm;
`XM5` = 2 × 1.1 µm), and the four units are placed so both devices share one
centroid.

The order comes from `klt gen mos_array`'s own
`topology="common_centroid"` numbering, which at `rows=1, cols=4` lays the
units out `U2 U0 U1 U3`. Taking device A = `{U0, U1}` and device B =
`{U2, U3}` puts A's centroid at the mean of columns 2 and 3 and B's at the
mean of columns 1 and 4 — **the same x, the array centre**. That is the
property that matters: a linear gradient in oxide thickness, implant dose or
stress across the array shifts both devices' thresholds by the same amount,
so it cancels in the difference.

That ordering is `klt`'s behaviour, not this repo's, so **it is asserted at
build time rather than assumed**: `assert_common_centroid()` reads each
array's unit source pads back out of `klt gen`'s own port report and raises
unless the mean x of device A's columns equals device B's to within one
database unit (1 nm). Without it a future `klt` could renumber the units and
nothing else here would notice — the nets would still be wired correctly, so
DRC would still be clean and the connectivity check would still pass, and
`signoff/check_signoff.py` re-hashes the committed stream rather than
regenerating it.

The dummy columns give the two outermost *real* units the same diffusion/poly
neighbourhood the inner ones have, so the edge-of-array etch and stress
environment is not itself a mismatch term.

**Dummies are tied, not floated.** `mos_array` draws the dummy columns but
reports no ports for them, so their pads are derived geometrically
(`PlacedDevice.dummy_sites()`, from the array's own uniform column pitch) and
every one — both diffusion pads *and the gate* — is strapped to that array's
body/source rail. A floating dummy gate is not a cosmetic issue: it is an
undefined boundary condition on the very edge device the dummy exists to
protect, free to couple and to invert the diffusion under it. The
connectivity self-check below fails if any of them is left unconnected.

### What this arrangement does *not* do, stated plainly

- **It is one-dimensional.** A `rows=2, cols=2` cross-quad would also cancel
  a gradient along *y*; this cancels only along *x*. It was rejected because
  in a cross-quad each device's two units sit on opposite diagonals, so the
  two drain nets must cross each other, and with the tracks available that
  costs two extra metal levels and a pair of *unequal* drain routes — trading
  a second-order placement gradient for a first-order wiring asymmetry on the
  differential pair. On a block with no committed thermal or stress gradient
  data, that is not a trade worth making blind. If post-layout offset (T1
  item 7) comes back worse than `spec/target-spec.md` allows, the cross-quad
  is the first thing to revisit, and this paragraph is the record of why it
  was not done first.
- **`B A A B` is symmetric but not homogeneous.** Device A occupies the two
  inner columns and B the two outer ones, so while the *first* moment matches
  exactly, the second (curvature) does not. Any four-unit one-row
  interdigitation has this property; only more units, or two dimensions, fix
  it.
- **Routing asymmetry was corrected where it was largest, and not
  everywhere.** Because A is inner and B is outer, A's drain track and gate
  track are ~3 µm shorter than B's — a deliberate ~10 % capacitance imbalance
  on a differential net if left alone. `generate.py`'s "matching-driven track
  balancing" block extends the shorter track of each pair (`d1_c1`/`d2_c1`,
  `inn`/`inp`) to the longer one's span. Measured on a fresh `build()`, the
  two **drain** tracks come out exactly equal — `d1_c1` and `d2_c1` both span
  −6.300 … 7.910 µm — so the in-array drain halves do match. The two **gate**
  tracks do not, and the next bullet says why.
- **`inp` keeps 2.0 µm more Metal3 than `inn`, because of its pin pad.** The
  balancing loop runs *before* the pin loop, and `PIN_SITES`
  (`opamp_core/floorplan.py`) then places `inp`'s labelled pad at x = −10.00
  against `inn`'s at −8.00: at channel C2's 0.80 µm track pitch, two 0.60 µm
  pads on adjacent tracks at the same x would touch, and staggering x is
  cheaper than either spreading C2 (which moves every track above it) or
  shrinking the pads below legibility. Drawing the pads extends `inp`'s track
  to −10.300 while `inn` stops at −8.300, so `inp` ends up **2.000 µm (12.6 %)
  longer** — 0.8 µm² of 0.40 µm-wide Metal3, ≲0.01 fF, ~0.2 % of the pair's
  own C<sub>gs</sub> — on the two differential input gate nets. The stagger is
  preferred at that price and the residual is disclosed rather than fixed. If
  T1 item 7 ever shows it matters, the fix is to run the balancing loop *after*
  the pin loop (or fold the pad extents into it) and refresh the stream, its
  DRC report and the signoff record together.
- **The mirror's two drain tracks are not balanced at all, and are not a
  matched pair.** `d1_c2` (XM3's drains) spans −5.100 … 7.650 and `d2_c2`
  (XM4's drains) −6.300 … 18.000 — 11.550 µm apart. 1.200 µm of that is the
  vertical-lane offset (`LANE_UM` puts the `d1` and `d2` lanes 1.2 µm apart in
  the left channel); the remaining 10.350 µm is topological, because `d2_c2`
  has to reach the mid-lane at x = 18.0 to carry the stage-1 output across to
  XM6's gate and the capacitor, and `d1_c2` has nowhere to go. No balancing is
  attempted here and none is implied: `d1` is the diode-connected reference
  node (held at 1/g<sub>m3</sub>) and `d2` is the high-impedance stage-1
  output, so the two nodes are asymmetric by topology and equal wire on them
  would not make them symmetric. The ≈4.6 µm² of extra Metal3 on `d2` is of
  order 0.05 fF on the same per-area basis as above; what it does to the
  dominant pole is an item-7 question, and it is the reason the Miller
  capacitor's big plate-to-substrate parasitic is deliberately kept off this
  node (see below).
- **No device-level mismatch number is claimed here.** This section is a
  statement of *layout intent*. Whether the drawn pair actually meets the
  ratified offset and CMRR rows is T1 item 7's question, answered by
  extraction and re-simulation, and it has not been asked yet.

## The wide devices: XM6 and XM7 are folded

`XM6` (w = 33 µm) is drawn as 12 parallel fingers of 2.75 µm and `XM7`
(w = 11.9 µm) as 7 of 1.70 µm — both exact divisions, both through
`mos_array`'s `finger_topology="parallel"`, which straps alternating S/D
segments and ties every gate, i.e. draws one transistor of width
`fingers × w_um`. Unfolded, XM6 alone would be a 33 µm-tall strip taller than
the rest of the amplifier; folded it is 20.4 × 7.7 µm. Neither carries dummy
columns — they are not matched to anything, and a dummy finger on XM6 would
cost 1.8 µm of pitch to protect a device whose absolute threshold is set by
the bias loop, not by a neighbour.

## The Miller capacitor's plates are not interchangeable

The netlist writes `XCc out d2`. Which terminal becomes which plate is the
layout's decision, and the layout makes it deliberately: **the `Metal5`
bottom plate carries `out`, and the `MIM` top plate carries `d2`.** The
bottom plate is a 26.7 µm square sitting over the substrate, so it has far
more parasitic capacitance to ground than the MIM plate above it; that
parasitic belongs on `out`, stage 2's low-impedance output, not on `d2`, the
high-impedance stage-1 output and XM6's gate, where it would move the
dominant pole and the compensation with it.

## Ports and labels

All six declared ports (`vdd vss inn inp out ibias`) are labelled in the
stream. Each label is written **twice**: on `TEXT` (63/0) — the documentation
layer `Builder.label()` defaults to, the one this README names, and the one
`coverage.layers_in_stream_without_rules` reports below — and again on
`Metal3` (30/0), the port's own conductor, where an LVS run looks for a net
name. Nothing in this repo reads the second one yet; `klt lvs` is T1 item 4.

## The connectivity claim, and why it is not LVS

DRC cannot see a short (two nets touching is legal geometry) and cannot see
an open. So the generator checks connectivity itself, in two steps:

1. `verify_against_netlist()` parses `design/netlist/opamp_core.spice` and
   asserts the device table in `generate.py` matches it — every instance
   name, model, W, L and drain/gate/source/bulk net, plus `ng=1`/`m=1`, plus
   that every declared port is used. A re-netlisted schematic that moves a
   net fails the regeneration instead of silently producing a layout of the
   old circuit.
2. `check_connectivity()` re-extracts the drawn interconnect with KLayout's
   own `LayoutToNetlist` (Metal1 → TopMetal1, through Via1/2/3/4 and
   TopVia1) and asserts that **every terminal of each net lands on one
   extracted net, no two nets share one, and the stream extracts to exactly
   nine nets** — the last clause being what catches a floating conductor,
   including an untied dummy gate.

On the committed stream: **9 nets, 93 terminals, no open, no short, nothing
floating.**

**This is not LVS.** No device is *recognised* from the geometry, so nothing
confirms that a drawn stack is the transistor its model card names;
extraction stops at `Metal1`, so each device's own contact-to-diffusion
connection is taken on `klt gen`'s word — and for the same reason the
extraction layer set (`_CONDUCTORS`/`_CUTS` in `opamp_core/generate.py`) omits
`MIM` (36/0) and `Vmim` (129/0), so the capacitor's own top-plate stack is
taken on `klt gen`'s word too: the `d2` probe lands on `TopMetal1`, and a
missing `Vmim` would be as invisible to this check as a missing
contact-to-diffusion stack is. No parasitics are computed.
`klt lvs` (T1 item 4) and `klt extract --parasitics` (item 7) remain unrun.

### The connectivity check has been shown to fail

`python3 layout/opamp_core/generate.py --negative-control` rebuilds the block
with one Metal2 riser deleted — the one carrying `d2` from the mirror's drain
track up to XM6's gate and the capacitor — and reports:

```
negative control: klt drc on the broken block says status=clean violations=0
negative control: 2 connectivity failure(s) reported
  d2: OPEN -- its 9 terminals extract onto 2 separate nets; one terminal of each at (3.440, 14.870), (31.190, 27.220)
  FLOATING -- the stream extracts to 10 nets but the netlist declares 9; some drawn conductor is connected to nothing (a dummy gate, or a wire that missed its via)
OK: the connectivity check detects a removed wire, and names the net
```

Note the first line: **the broken block is still DRC-clean.** An amplifier
with its compensation capacitor disconnected passes `klt drc --deck sg13g2`
without a murmur. That is the exact size of the gap between "DRC clean" and
"correct", and the reason this check exists.

## What the DRC verdict is worth (`opamp_core/drc_report.json`)

`status: clean`, `violation_count: 0`, **37 of the deck's 43 rules checked**.
Per T1 item 3, a clean status from a deck with undisclosed holes is a false
claim, so the holes are disclosed here, quoted verbatim from the report's own
`coverage` block.

**`coverage.deck_scope`** — the rule families the curated deck carries at all:

```
["Act", "Cnt", "Gat", "M1", "M2", "M3", "M4", "M5",
 "TM1", "TM2", "TV1", "TV2", "V1", "V2", "V3", "V4"]
```

**`coverage.layers_in_stream_without_rules`** — layers the block *draws* that
the deck has **no rule of any kind** for:

```
["31/0", "36/0", "63/0", "129/0", "189/0"]
```

i.e. `NWell` (31/0), `MIM` (36/0), `TEXT` (63/0), `Vmim` (129/0),
`prBoundary` (189/0). Read plainly: **the clean verdict says nothing about the
two n-wells that hold the PMOS groups, nor about their separation, and nothing
about the Miller capacitor's plate** — two of the things a reviewer would most
want checked about this block. (The merged 31/0 in the committed stream is two
disjoint polygons — the mirror's, (0, 22)–(12.6, 25.88), and the gain device's,
(21, 21)–(41.38, 28.65), 8.4 µm apart — so both the wells themselves and the
gap between them are entirely unchecked; that is IHP `NW.*` territory, which
the curated deck does not carry.) `TEXT` and `prBoundary` are documentation
layers and legitimately carry no rules. (The implant layers `nSD` 7/0 and `pSD` 14/0 are
absent from this list only because `klt gen mos_array` does not draw them at
all, which is its own gap — see below.)

**`coverage.rules_skipped`** — 6 of the deck's 43 rules had no applicable
geometry in this stream (every one with `reason: "no_applicable_geometry"`):

```
["topmetal1.enclosing.topvia2.1", "topmetal2.enclosing.topvia2.1",
 "topmetal2.space.1", "topmetal2.width.1", "topvia2.space.1",
 "topvia2.width.1"]
```

These are the TopMetal2 level and the TopVia2 cut, which the block does not
draw — it routes on Metal1–Metal3 and reaches Metal5/TopMetal1 only for the
capacitor. They are skipped for the honest reason (no such geometry), not
because the deck lacks them.

### `klt gen mos_array` draws no source/drain implants

Neither `nSD` (7/0) nor `pSD` (14/0) appears anywhere in the committed
stream: the generator draws `Activ`, `GatPoly`, `Cont`, `Metal1` and (for a
pfet) `NWell`, and no implant mask. The curated deck carries no implant rule,
so `klt drc --deck sg13g2` is silent about it, and IHP's own device
recognition derives `sg13_lv_nmos`/`sg13_lv_pmos` from `Activ ∧ GatPoly ∧
¬NWell` rather than from the implant — so this stream is not obviously
un-extractable. It is, however, not a manufacturable mask set, and **no claim
is made here that it is**. This is a tool gap, filed generically upstream per
this repo's friction protocol:
[`2AMLogic/klayout-tools#2580`](https://github.com/2AMLogic/klayout-tools/issues/2580).

## The old smoke fixture's coverage (`scaffold_smoke/drc_report.json`)

The scaffold fixture's own report is narrower than the block's — it checks 29
rules, not 37 — and its coverage is disclosed separately below, unchanged.

**`coverage.deck_scope`** — the rule families the curated deck carries at all:

```
["Act", "Cnt", "Gat", "M1", "M2", "M3", "M4", "M5",
 "TM1", "TM2", "TV1", "TV2", "V1", "V2", "V3", "V4"]
```

**`coverage.layers_in_stream_without_rules`** — layers the fixture *draws*
that the deck has **no rule of any kind** for:

```
["7/0", "14/0", "31/0", "36/0", "63/0", "129/0", "189/0"]
```

i.e. `nSD` (7/0), `pSD` (14/0), `NWell` (31/0), `MIM` (36/0), `TEXT` (63/0),
`Vmim` (129/0), `prBoundary` (189/0). Read plainly: **the clean verdict says
nothing about the PMOS well, nothing about the implants, and nothing about the
MIM capacitor** — three of the four things a reviewer would most want checked
about this particular fixture. `TEXT`/`prBoundary` are documentation layers
and legitimately carry no rules.

**`coverage.rules_skipped`** — 14 of the deck's 43 rules had no applicable
geometry in this stream (every one with `reason: "no_applicable_geometry"`; 29
rules were checked):

```
["metal3.enclosing.via3.1", "metal4.enclosing.via4.1", "metal4.space.1",
 "metal4.width.1", "topmetal1.enclosing.topvia2.1",
 "topmetal2.enclosing.topvia2.1", "topmetal2.space.1", "topmetal2.width.1",
 "topvia2.space.1", "topvia2.width.1", "via3.space.1", "via3.width.1",
 "via4.space.1", "via4.width.1"]
```

These are the Metal4/TopMetal2 levels and the Via3/Via4/TopVia2 cuts, which
the fixture does not draw. They are skipped for the honest reason (no such
geometry), not because the deck lacks them.

---

## Curated deck vs. IHP's foundry deck — not a hypothetical gap

**This section applies to every DRC verdict in this repository**, the block's
and the fixture's alike.

`klt drc --deck sg13g2` runs **klayout-tools' own curated starter deck**: 43
rules. **It is not IHP's foundry signoff deck**, and no result in this
repository is a signoff-DRC result. IHP's signoff deck under
`$PDK_ROOT/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/` emits **111
distinct rule ids**, plus its templated `M2..M5` / `V2..V4` families. Whole
families the curated deck does not carry include every `NW.*` (n-well), every
`MIM.*`, `TGO.*` (thick-gate-oxide), `pSD.*`, `Cnt.e`/`Cnt.g1`/`Cnt.g2`,
`Gat.a1`/`Gat.a2`/`Gat.g`, `M1.e`/`M1.f`/`M1.g`/`M1.i` (wide-line spacing and
45° bends), and the antenna, density, latch-up, seal-ring and pad tables.

**A curated-deck-clean verdict from this repo is therefore not, and must never
be reported as, signoff-clean.** That holds for `opamp_core/drc_report.json`
exactly as it holds for the fixture's: 37 rules checked out of a 43-rule
starter deck is not 111 rules plus the antenna, density, latch-up, seal-ring
and pad tables. Concretely, found while building the scaffold and inherited
unchanged by the block:

> `klt gen cap_array --pdk ihp-sg13g2` draws `Metal5` enclosing the `MIM`
> plate by **0.50 µm**. IHP's own **`MIM.c`** requires **0.60 µm**
> (`rule_decks/beol/6_11_mim.drc`, "Rule MIM.c: Min. Metal5 enclosure of MIM
> is 0.60 um"; `drc_rules/Mim_c = 0.6` in
> `rule_decks/sg13g2_tech_default.json`). The curated deck carries no MIM
> rule, so it reports the shortfall as clean.

Rather than commit geometry known to violate a foundry rule, **both** streams
widen the bottom plate themselves — `devices.patch_mim_bottom_plate()`,
against `devices.MIM_METAL5_ENCLOSURE_UM`. The patch is reported in each
generator's stdout and is a no-op (returning `None`) if a future `klt` fixes
the generator, so it cannot silently double-draw. It lives in `devices.py`,
not in either `generate.py`, precisely because a foundry rule that no
`klt drc` run in this repo checks must have exactly one implementation: two
copies would drift, and only one of the two committed streams would clear
MIM.c. **This one rule is the exception, not a general audit**: the other
uncarried rule ids have not been checked by hand, and nothing here claims
they pass.

Filed upstream per this repo's friction protocol as a generic tool gap:
[`2AMLogic/klayout-tools#2576`](https://github.com/2AMLogic/klayout-tools/issues/2576)
(generator draws below the PDK's own plate-enclosure minimum; curated deck has
no rule that can catch it). The stale `klt gen --help` family claim quoted
above is filed separately as
[`2AMLogic/klayout-tools#2577`](https://github.com/2AMLogic/klayout-tools/issues/2577).

### The DRC flow has been shown to fail

`python3 layout/scaffold_smoke/generate.py --negative-control` draws three deliberately
illegal shapes with `klt draw` (which has no PDK awareness — its own help text
says "it will happily emit rule-violating geometry") and asserts the verdict.
Result on the revisions above:

```
negative control: status=violations violations=3 rule_counts={'activ.width.1': 1, 'metal1.space.1': 1, 'metal1.width.1': 1}
OK: the DRC flow flags violations, and attributes them correctly
```

A 0.10 µm Metal1 line (`metal1.width.1` = 0.16), a 0.10 µm Metal1 gap
(`metal1.space.1` = 0.18) and a 0.10 µm Activ (`activ.width.1` = 0.15) each
come back flagged and correctly attributed, so the clean verdict on the smoke
fixture is a real pass and not a silently inert check. Nothing from the
negative control is committed — it runs entirely in a temp directory, so the
byte-for-byte regeneration criterion is untouched.

### The DRC flow's negative control covers the block too

The fixture's `--negative-control` and the block's are different experiments
and both are needed: the fixture's proves the *DRC deck* is not inert (it
flags illegal geometry), the block's proves the *connectivity check* is not
inert (it flags a missing wire that DRC calls clean). Neither substitutes for
the other, and neither commits anything.

---

## Determinism

Both committed streams reproduce **byte-for-byte** on a clean checkout at the
same `klt` revision. `--check` automates the comparison for each: it
regenerates into a temp directory and fails on any difference in the GDS
bytes or in the DRC report's `status` / `violation_count` / `coverage`.

| Stream | sha256 (= its report's `provenance.input.content_hash`) |
|---|---|
| `opamp_core/opamp_core.gds` | `2c5829ed6a664ca7904b0012cac09c8a832e11b1cc0d2279f0c7b680e38cf4c9` |
| `scaffold_smoke/sg13g2_opamp_scaffold_smoke.gds` | `d514a4f1309d40fc580ddbeb311e2393247ba02c2f2d9718e0275a33b8e5eaf5` |

Three things make that hold:

1. `Builder.write` sets `SaveLayoutOptions.gds2_write_timestamps = False`.
   Without it KLayout stamps wall-clock time into every `BGNLIB`/`BGNSTR`
   record and no two runs agree.
2. `klt gen`'s intermediate streams are written to a temp directory and each
   one's top cell is **flattened on import**, so neither their own timestamps
   nor their generator-internal cell names reach the committed stream. The
   result is not a fully flat stream: it has exactly two levels — the assembly
   top plus one cell per placed device, named by this repo
   (`tail_pair`, `input_pair`, `mirror`, `out_tail`, `gain`, `miller_cap`) —
   and no `$1`-suffixed names leak in from the generators.
3. Every coordinate is a pure function of the constants in
   `opamp_core/floorplan.py` / `scaffold_smoke/generate.py` and
   `sg13g2_layers.py`. `params` are serialised with `sort_keys=True`, and the
   committed DRC report's `file` field is rewritten to the repo-relative GDS
   path so no host's absolute paths are embedded.

**What would legitimately change the bytes**: a different `klt` revision
(device geometry comes from its generators), or a curated-deck revision that
moves a rule minimum this code sizes against — the latter fails loudly first,
because `verify_deck_minima()` runs before anything is drawn and raises on any
drift from the transcribed 43 values, naming both content hashes. A *change
to the netlist* would also change the bytes, and would fail loudly first for
the same reason: `verify_against_netlist()` runs before anything is drawn.

**If the bytes change, the signoff register must be refreshed in the same
change.** `signoff/block-manifest.json` pins the GDS's sha256 for items 2 and
3, `signoff/pinned-inputs.json` names the file it is the hash of, and
`signoff/check_signoff.py` re-hashes it offline — so a regenerated layout
fails CI until the DRC report, both pins and a new graded record under
`signoff/reports/` are refreshed together. That is the intended behaviour,
not an obstacle.

### What CI actually enforces, and what it does not

**The paragraphs above are all true, and all verified by hand, not by CI.**
`.github/workflows/signoff.yml` re-hashes the committed GDS offline
(`signoff/check_signoff.py`) and fails if a committed byte moves without the
DRC report and the signoff pins moving with it — that closes "someone
hand-edited the stream". It does **not** run `opamp_core/generate.py --check`
or `scaffold_smoke/generate.py --check` for either stream: nothing in CI
regenerates a stream and diffs it against the committed bytes on every push,
so "byte-for-byte reproducible" is not a continuously machine-checked
property of *either* generator here — only a property a human verified by
running `--check` and recorded in the revision table above.

Item 2 of the T1 checklist accepts either "reproducibly generated" **or**
"documented provenance" (`signoff/README.md` → "What the manifest cites").
This repo's manifest cites `opamp_core/` for item 2, and that citation rests
on the **documented-provenance** alternative — the revision table above, plus
`verify_deck_minima()` and `verify_against_netlist()` failing loudly on drift
— not on a CI-enforced "reproducibly generated" one. (`scaffold_smoke/` is
not cited by `signoff/` at all — see the top of this file — so nothing about
its byte-for-byte claim is graded either way; it is treated the same as
`opamp_core/` here only so this section states one policy for both
generators rather than leaving the uncited one to guess.)

CI does not run `generate.py` at all, so nothing above is CI-enforced. One
assumption is machine-checked independent of who runs it, though: the
block's single most fragile one, that `klt gen mos_array`'s common-centroid
unit ordering (`U2 U0 U1 U3`) is what makes the `B A A B` interdigitation
described in
["Matching"](#matching-what-was-chosen-for-xm1xm2-and-xm3xm4-and-what-it-costs)
above actually common-centroid. `assert_common_centroid()` in
`opamp_core/generate.py` asserts it at every regeneration and every `--check`
run, so a future `klt` that renumbered the units fails the very next *local*
run instead of only showing up as an unexplained byte diff that nobody was
running `--check` to see.

Standing up a second CI job that installs `klt` **and** the pinned
IHP-Open-PDK release to run `--check` on every push for both generators was
considered and deferred: it needs a PDK checkout (and caching strategy) in
Actions that the rest of this repo's CI deliberately avoids
(`.github/workflows/signoff.yml`'s own header: "needs no PDK, no ngspice and
no klayout install of its own"), a materially larger and less-tested
surface than this repo's other CI. The record of that decision, and the
reasoning behind it, is
[#50](https://github.com/2AMLogic/sg13g2-opamp/issues/50).

## Devices covered by the smoke fixture

All nine instances in `design/netlist/opamp_core.spice` collapse to six
distinct `(flavour, W, L)` shape classes, and the smoke fixture draws one of
each:

| Cell | Device | W / L | Stands in for |
|---|---|---|---|
| `m_in_pair` | `sg13_lv_nmos` | 3.2 µm / 0.13 µm | `XM1`, `XM2` input pair |
| `m_mirror` | `sg13_lv_pmos` | 1.04 µm / 0.52 µm | `XM3`, `XM4` mirror load |
| `m_tail` | `sg13_lv_nmos` | 2.2 µm / 0.52 µm | `XM5`, `XMbias` tail + bias diode |
| `m_gain` | `sg13_lv_pmos` | 33 µm / 1.04 µm | `XM6` output gain device (widest) |
| `m_out_tail` | `sg13_lv_nmos` | 11.9 µm / 0.52 µm | `XM7` output tail |
| `c_miller` | `cap_cmim` | 25.7 µm / 25.7 µm | `XCc` Miller cap |

The fixture deliberately **does not** wire these into the schematic's
topology. A partially-connected op-amp in `layout/` would invite exactly the
"this is the layout" misreading that the top of this file forbids; the devices
sit in a row, with the tap and routing primitives exercised separately below
them.

Matched-array topology (common-centroid `rows`/`cols`, dummy columns) is
available from `mos_array` but is deliberately left at `rows=1, cols=1,
dummy=0` here: how the input pair and the mirror are interleaved is a
floorplanning decision belonging to the op-amp layout itself, and it is made
in `opamp_core/` — see ["Matching"](#matching-what-was-chosen-for-xm1xm2-and-xm3xm4-and-what-it-costs)
above — not baked into a smoke fixture.

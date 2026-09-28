# layout/

SG13G2 drawing/routing **scaffold** for this block, plus a DRC-clean smoke
fixture that proves it. This is the machinery the op-amp layout is drawn
*with* — it is not the op-amp layout, and nothing here is a signoff claim.

- **What exists**: a cited SG13G2 layer table, a `klayout.db` builder with
  routing / via / tap primitives, `klt gen` wrappers for the three device
  flavours `design/netlist/opamp_core.spice` needs, and one committed smoke
  GDS + `klt drc --deck sg13g2` report.
- **What does not**: `opamp_core` itself is not drawn or routed (issue
  [#45](https://github.com/2AMLogic/sg13g2-opamp/issues/45)); no LVS, no
  parasitic extraction, no post-layout sim, no supply/ERC spec
  ([#29](https://github.com/2AMLogic/sg13g2-opamp/issues/29)).
- **Nothing under `signoff/` cites or is changed by anything in this
  directory.** The smoke fixture is scaffolding proof; pinning it as T1
  evidence would be a false claim (see "What the DRC verdict is worth").

## Files

The structure mirrors `2AMLogic/sg13g2-bandgap`'s: shared drawing modules at
`layout/`, and one directory per group of drawn artifacts holding its
`generate.py`, its `.gds` and its `drc_report.json`. The op-amp layout itself
(#45) belongs in a sibling `layout/opamp_core/`.

| Path | What it is |
|---|---|
| `sg13g2_layers.py` | The SG13G2 layer table + the curated deck's 43 rule minima, each with its provenance inline. `verify_deck_minima()` re-derives the minima from the installed `klt` and raises on drift. Counterpart of the precedent's `common.py` layer table. |
| `builder.py` | `Builder`: one `kdb.Layout` at `dbu = 0.001`, micron-valued `box`/`label`/`pr_boundary`/`route_h`/`route_v`/`cut_array`/`landing_pad`/`via`/`via_stack`/`tap`, `place_stream` for importing a generator stream, and a timestamp-free `write`. Counterpart of `_klayout_builder_base.py`. |
| `devices.py` | `lv_nmos()` / `lv_pmos()` / `cmim_cap()` — thin, validated wrappers over `klt gen mos_array` / `klt gen cap_array` against the `ihp-sg13g2` PDK. The two primitives the precedent lacks. |
| `scaffold_smoke/generate.py` | The smoke fixture: draws every device shape the netlist asks for plus one of each routing/tap/via primitive, writes the GDS, runs DRC, writes the report. Also `--check` and `--negative-control`. |
| `scaffold_smoke/sg13g2_opamp_scaffold_smoke.gds` | The committed smoke stream. |
| `scaffold_smoke/drc_report.json` | Its committed `klt drc --deck sg13g2 --format json` report. |

## Regenerating

```sh
# From the repo root. Requires `klt` on PATH and an ihp-sg13g2 PDK install
# (found via $PDK_ROOT, else the same candidate list sim/env.sh searches).
python3 layout/scaffold_smoke/generate.py

# Verify instead of overwrite: regenerates into a temp dir and fails on any
# drift from the committed GDS (byte-for-byte) or DRC verdict/coverage.
python3 layout/scaffold_smoke/generate.py --check

# Negative control: prove the DRC flow can fail. Writes nothing to the repo.
python3 layout/scaffold_smoke/generate.py --negative-control
```

### Revisions the committed artifacts were produced with

| Thing | Value |
|---|---|
| `klt` | `0.6.0+g9c11986ad447` (`klt --version`) |
| Curated `sg13g2` deck | `sha256:894326a4e37fb24fef2f7ffc6ae1da55a0e262b0f0bc1c09adc4862909278fda`, 43 rules, `released: yes` (`klt deck hash --deck sg13g2`) |
| KLayout inside `klt` | `0.30.12`, which the report flags as `provenance.klayout_version_mismatch: true` — that `klt` build was tested against `klayout==0.30.10`. Per `klt`'s own warning the *verdict* is unaffected; report counts could in principle differ on the tested engine. |
| KLayout used by `builder.py` | `0.30.10` (the host `python3`'s `klayout` package), i.e. the tested version |
| PDK | IHP-Open-PDK `v0.3.0`, variant `ihp-sg13g2` — the release `sim/pdk.json` pins for this repo's evidence records |

**This is deliberately not `signoff/klt-pin.txt`.** That pin
(`b15edf5e3a2e56467a3406c98a2555eb1a5ae45c`) exists so `klt signoff
--manifest`'s *T1 checklist skeleton* cannot move under the committed verdict
of record. It governs the signoff register, and nothing in `layout/` is cited
by that register, so this directory does not inherit it. If a future change
does pin a layout artifact as T1 evidence, that change owns reconciling the
two revisions.

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

## What the DRC verdict is worth (coverage disclosure)

The committed report says `status: clean`, `violation_count: 0`. Per T1 item
3, a clean status from a deck with undisclosed holes is a false claim, so the
holes are disclosed here, quoted from the report's own `coverage` block.

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

### Curated deck vs. IHP's foundry deck — not a hypothetical gap

`klt drc --deck sg13g2` runs **klayout-tools' own curated starter deck**: 43
rules. IHP's signoff deck under
`$PDK_ROOT/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/` emits **111
distinct rule ids**, plus its templated `M2..M5` / `V2..V4` families. Whole
families the curated deck does not carry include every `NW.*` (n-well), every
`MIM.*`, `TGO.*` (thick-gate-oxide), `pSD.*`, `Cnt.e`/`Cnt.g1`/`Cnt.g2`,
`Gat.a1`/`Gat.a2`/`Gat.g`, `M1.e`/`M1.f`/`M1.g`/`M1.i` (wide-line spacing and
45° bends), and the antenna, density, latch-up, seal-ring and pad tables.

**A curated-deck-clean verdict from this repo is therefore not, and must never
be reported as, signoff-clean.** Concretely, found while building this
scaffold:

> `klt gen cap_array --pdk ihp-sg13g2` draws `Metal5` enclosing the `MIM`
> plate by **0.50 µm**. IHP's own **`MIM.c`** requires **0.60 µm**
> (`rule_decks/beol/6_11_mim.drc`, "Rule MIM.c: Min. Metal5 enclosure of MIM
> is 0.60 um"; `drc_rules/Mim_c = 0.6` in
> `rule_decks/sg13g2_tech_default.json`). The curated deck carries no MIM
> rule, so it reports the shortfall as clean.

Rather than commit geometry known to violate a foundry rule, the smoke
fixture widens the bottom plate itself —
`scaffold_smoke/generate.py`'s `_patch_mim_bottom_plate`, against
`devices.MIM_METAL5_ENCLOSURE_UM`. The patch is reported in the generator's
stdout and is a no-op (returning `None`) if a future `klt` fixes the
generator, so it cannot silently double-draw. **This one rule is the
exception, not a general audit**: the other uncarried rule ids have not been
checked by hand, and this scaffold does not claim they pass.

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

## Determinism

`python3 layout/scaffold_smoke/generate.py` reproduces
`scaffold_smoke/sg13g2_opamp_scaffold_smoke.gds` **byte-for-byte** on a clean checkout at
the same `klt` revision (verified by running it twice and comparing sha256:
`d514a4f1309d40fc580ddbeb311e2393247ba02c2f2d9718e0275a33b8e5eaf5` both times
— the same value the report records as `provenance.input.content_hash`;
`--check` automates the comparison). Three things make that hold:

1. `Builder.write` sets `SaveLayoutOptions.gds2_write_timestamps = False`.
   Without it KLayout stamps wall-clock time into every `BGNLIB`/`BGNSTR`
   record and no two runs agree.
2. `klt gen`'s intermediate streams are written to a temp directory and
   re-imported **flattened** into the assembly, so neither their own
   timestamps nor their internal cell names reach the committed stream.
3. Every coordinate is a pure function of the constants in
   `scaffold_smoke/generate.py` and `sg13g2_layers.py`. `params` are serialised with
   `sort_keys=True`, and the committed DRC report's `file` field is rewritten
   to the repo-relative GDS path so no host's absolute paths are embedded.

**What would legitimately change the bytes**: a different `klt` revision
(device geometry comes from its generators), or a curated-deck revision that
moves a rule minimum this code sizes against — the latter fails loudly first,
because `verify_deck_minima()` runs before anything is drawn and raises on any
drift from the transcribed 43 values, naming both content hashes.

## Devices covered

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
floorplanning decision belonging to the op-amp layout itself (#45), not
something a scaffold smoke fixture should bake in.

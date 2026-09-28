# T1 signoff — the graded verdict of record

This block's position on the klayout-tools **design-evidence ladder** is not
prose in this file. It is
[`block-manifest.json`](block-manifest.json) — what this block claims, and the
evidence envelope backing each claim — graded mechanically by `klt signoff
--manifest`, with the graded output committed under
[`reports/`](reports/) as append-only evidence.

Read the newest record in `reports/` for the current per-item verdict. Nothing
in this file restates it, on purpose: a hand-maintained checkbox list goes
stale the moment either the evidence or the checklist moves, and both move.
(The checklist itself grew an eleventh item — power delivery (structural) — on
2026-09-17, 2AMLogic/klayout-tools#2025, which invalidated every hand-read T1
claim in the fleet at a stroke. That is exactly the failure mode this
register replaces.)

```bash
bash signoff/regenerate.sh --dry-run      # render the report, write nothing
bash signoff/regenerate.sh                # mint a new record under reports/
python3 signoff/check_signoff.py          # offline: pins + record consistency
python3 signoff/check_signoff.py --run-klt  # + re-grade and diff vs the record
```

`klt signoff --manifest` exits **3** when the block is not yet T1 and **0**
only at full T1 — both mean the report rendered. Exit 1/2 mean no report was
produced. The scripts above encode that distinction; a caller of `klt` that
treats 3 as failure cannot run on a block that is not already finished.

- **Checklist** (the item skeleton, parsed at run time):
  `klayout-tools/docs/design-evidence-tiers.md`
- **Grader contract** (manifest shape, reasons, what is and is not graded):
  `klayout-tools/docs/cli/signoff.md`
- **klt revision this repo grades against**: pinned in
  [`klt-pin.txt`](klt-pin.txt) — floating `main` would make the committed
  record disagree with a re-run for reasons unrelated to this block's evidence.

## Block kind: `analog`

Confirmed against the block, not assumed: this repository is the plain-CMOS
twin of its gf180/sky130 counterparts (per `CLAUDE.md`, CMOS only unless a
decision record opens the HBT stretch — none has), `design/opamp_core.sch`
holds a hand-captured two-stage Miller op-amp schematic, the netlist under
`design/netlist/` is regenerated from that schematic rather than synthesized,
and there is no RTL, no gate-level netlist and no partition boundary to
declare — so this is a single-kind `analog` manifest, graded against the
Analog column of the per-kind items (1, 2, 5, 7 and 11), not a
`mixed-signal` one.

Consequence worth stating: for an analog partition, **item 7 accepts a `klt
pex` report and nothing else**, and item 5 accepts `klt sim` and nothing else.
A clean DRC, or any pre-layout corner sweep — however thorough — renders
`wrong_kind`, not `met`.

## What the manifest cites, and what it deliberately does not

**The manifest cites two items: 2 (Layout) and 3 (DRC clean).** Both cite the
same envelope — `layout/opamp_core/drc_report.json`, the `klt drc --deck
sg13g2` run over the committed `layout/opamp_core/opamp_core.gds` — and both
pin the same hash, because a DRC envelope records the sha256 of the stream it
ran on. Everything else still renders `unmet` with reason `no_evidence`,
which remains the honest graded result rather than a placeholder.

**Why a `drc` envelope is a legitimate citation for item 2, and not
borrowed-green.** Item 2 has no `klt` verb of its own, so the grader scores it
on "some passing envelope was cited at all", never on topical relevance — a
passing envelope for anything would render `met` and the tool would have no
basis to object. That is exactly why the citation has to earn its place by
argument, here:

- The envelope's `provenance.input.content_hash` **is** the committed GDS's
  own sha256. The envelope does not merely pass; it names the artifact item 2
  is about, by content.
- `pinned-inputs.json` maps that pin to `layout/opamp_core/opamp_core.gds`
  and `check_signoff.py` re-hashes the file offline, so the chain "the record
  says `met`" → "because this envelope passed" → "on exactly the stream
  committed in this repo" is closed on both ends and fails CI if either end
  moves.
- The half item 2 asks for that no envelope can carry — "reproducibly
  generated or with documented provenance" — **this block claims the
  documented-provenance alternative, not a CI-enforced "reproducibly
  generated" one.** `layout/opamp_core/generate.py --check` regenerates into
  a temp directory and fails on any byte difference, but nothing in
  `.github/workflows/signoff.yml` runs it: CI verifies the *committed hash*
  offline (`check_signoff.py`, above) and never re-invokes the generator, so
  byte-for-byte regeneration is a property verified by a human running
  `--check` by hand, not one this register can point to as continuously
  machine-checked. CI does not run `generate.py` at all, so it does not
  enforce this either — but the one assumption identified as most likely to
  break silently is machine-checked independent of who runs it: that `klt
  gen mos_array`'s common-centroid unit ordering is what makes the block's
  `B A A B` interdigitation actually common-centroid, via
  `assert_common_centroid()` inside `generate.py` itself. A `klt` behaviour
  change that broke it fails the very next *local* regeneration or `--check`
  run — not CI — rather than only showing up as an unexplained byte diff
  nobody was looking at. The documented-provenance claim itself rests on
  `layout/README.md`'s revision table (exact `klt` revision, curated-deck
  hash and PDK release the committed bytes were produced with) and its
  "Determinism" section. Standing up a second CI job that installs `klt`
  **and** the pinned PDK to run `--check` on every push was considered and
  deferred as materially higher cost (PDK checkout/caching in Actions) than
  this repo's other CI; see
  [#50](https://github.com/2AMLogic/sg13g2-opamp/issues/50) for the record of
  that decision.

**Item 3's coverage disclosure is in `layout/README.md`**, quoted verbatim
from the cited report's own `coverage` block: `deck_scope` (16 rule
families), `layers_in_stream_without_rules` (`31/0`, `36/0`, `63/0`, `129/0`,
`189/0` — the n-well and the MIM plate among them) and `rules_skipped` (6 of
43, all `no_applicable_geometry`). `klt signoff` reports those three fields
but does not grade them, so a `met` verdict on item 3 is **not** evidence the
gaps were disclosed; read the disclosure, not the verdict. And the deck
itself is klayout-tools' own curated 43-rule starter deck, **not IHP's
foundry signoff deck** — see `layout/README.md` → "Curated deck vs. IHP's
foundry deck".

**Items 1, 9 and 10 are uncited on purpose**, for the reason item 2 had to
argue its way past: they have no `klt` verb behind them and no envelope names
the artifact they are about, so any citation would be borrowed-green. This
repo already owns artifacts those items describe (schematic + regenerated
netlist under `design/`; seven manifest-driven bench suites under `sim/` with
documented cold-start invocations and a pinned PDK revision; a README and
Apache-2.0 license; CI), but asserting them through an unrelated citation
would make the record say something no check verified.
`klayout-tools/docs/cli/signoff.md` recommends exactly this default — leave
them visibly `unmet` rather than borrowed-green.

**Items 4, 7 and 11 are uncited because the checks have not been run.** The
layout now exists, so the blocker that held them is gone, but `klt lvs`
(item 4), `klt extract --parasitics` + post-layout re-simulation (item 7) and
an ERC/supply spec (item 11,
[#29](https://github.com/2AMLogic/sg13g2-opamp/issues/29)) are each their own
piece of work and none has been done. The layout generator does run a
connectivity **self-check** — it re-extracts the drawn metal and asserts the
nine nets are wired as `design/netlist/opamp_core.spice` says, with no open,
no short and nothing floating — but that is not LVS (no device recognition,
extraction stops at Metal1) and is deliberately **not** cited as item 4.
Tracker: [#3](https://github.com/2AMLogic/sg13g2-opamp/issues/3).

**Items 5 and 6 are uncited because this repo's evidence is not in a
gradable shape.** `spec/target-spec.md` is partially ratified (decision
record [`0002-target-spec-ratification.md`](../spec/decision-records/0002-target-spec-ratification.md),
`[DR-2]` — one bound per measured row), and seven bench suites
(`sim/gm-id-characterization`, `sim/open-loop-ac`, `sim/input-offset`,
`sim/input-noise`, `sim/slew-rate`, `sim/output-swing`, `sim/cmrr-psrr`)
record append-only CSV + Markdown evidence against the PVT grid. But item 5
accepts only a `klt sim` JSON envelope and item 6 only a `klt yield` one,
and this repo's records are harness-native artifacts, not envelopes — so
until either an envelope-producing bench lands or a wrapper is introduced
upstream, both rows correctly render `no_evidence`. Item 6 additionally has
a substantive gap: no Monte Carlo campaign exists at all yet (tracked in
[#17](https://github.com/2AMLogic/sg13g2-opamp/issues/17) and
[#26](https://github.com/2AMLogic/sg13g2-opamp/issues/26)).

**Item 8 is uncited because no aggregated characterization report exists
yet** — no single artifact summarizes per-spec-row performance across
conditions with the evidence record behind each verdict. When one does, the
correct citation is the opt-in `generic` envelope wrapper (`"kind":
"generic"`), the evidence kind only item 8 accepts.

## Disclosures that travel with the current claim

- **Item 3's DRC coverage gaps are disclosed in `layout/README.md`** →
  "What the DRC verdict is worth", quoted verbatim from the cited report's
  own `coverage` block. This was the honesty note this register was opened
  with ("when item 3 first goes `met`, its coverage gaps must be stated in
  the claim — a `met` verdict alone is not evidence that coverage was
  disclosed"), and it is now discharged.
- **Item 2's provenance is disclosed in the same file** → "Determinism":
  which `klt` revision produced the bytes, what would legitimately change
  them, and the fact that changing them fails this register's own offline
  check until the pins are refreshed.
- **The source/drain implants are not drawn.** `klt gen mos_array` emits no
  `nSD`/`pSD` on this family, the curated deck has no implant rule, and
  neither the DRC verdict nor the signoff record can see it. Stated in
  `layout/README.md` and filed upstream as
  [`2AMLogic/klayout-tools#2580`](https://github.com/2AMLogic/klayout-tools/issues/2580).
  Nothing in this register should be read as a claim that the committed
  stream is a manufacturable mask set.

One honesty note still pending, from the issue that introduced this register:

- When item 7 first goes `met`, its `body_bias` statement must be read and
  restated: an unexamined `body_bias` field is no statement that "every
  device body was biased"; here, today, the question has not been asked with
  the tool that answers it.

## How this is kept from rotting

`klt signoff` compares a manifest pin against the *cited envelope's own*
recorded input hash. It never opens the repo artifact that hash is supposed
to be the hash **of** — so a pin can go stale in a way the grader structurally
cannot see. [`pinned-inputs.json`](pinned-inputs.json) names the artifact
behind every pin and [`check_signoff.py`](check_signoff.py) re-hashes it,
which closes that gap. Both of the current pins resolve to
`layout/opamp_core/opamp_core.gds`, so regenerating the layout without also
refreshing the DRC report, both pins and the graded record fails the offline
half of CI — by design. The checker also enforces the converse: it gathers a
row for every new pin, and rejects a `pinned-inputs.json` entry for an item
the manifest does not cite.

CI runs both halves
([`.github/workflows/signoff.yml`](../.github/workflows/signoff.yml)), on
every push and every PR:

| Check | Where | Needs |
|---|---|---|
| Manifest shape, pins vs. committed artifacts, record consistency | offline half of the `signoff` job, via `check_signoff.py` | python3 only |
| Re-grade with the pinned `klt` and diff against the committed record | online half of the `signoff` job, via `check_signoff.py --run-klt` | network (installs `klt` at `klt-pin.txt`'s revision) |

So a manifest citing an artifact that has since changed, a record that no
longer matches what `klt` would say today, and a mis-keyed evidence entry
that `klt` would silently ignore all fail a build instead of rotting
quietly.

## Fleet roll-up

`block` is required in this manifest (klt itself calls it optional) because it
is how this block's row is identified in the fleet roll-up,
[2AMLogic/2am#956](https://github.com/2AMLogic/2am/issues/956), which
consumes this exact file via `klt signoff --fleet`.

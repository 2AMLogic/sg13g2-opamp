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
python3 signoff/check_inventories.py      # offline: item 1/9/10 inventory entries
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

**The manifest cites eight items: 1, 9 and 10 (the inventories below),
8 (the characterization report, below) and 2 (Layout), 3 (DRC clean),
4 (LVS clean) and 11 (Power delivery, structural).** The layout items are about the same
committed stream, `layout/opamp_core/opamp_core.gds`, and every one of them
pins that stream's own sha256 — because a `drc`, `lvs` or `erc` envelope all
record the sha256 of the layout they ran on in `provenance.input`:

| Item | Envelope cited | Produced by |
|---|---|---|
| 2, 3 | `layout/opamp_core/drc_report.json` | `klt drc --deck sg13g2` |
| 4 | `layout/opamp_core/lvs_report.json` | `layout/opamp_core/run_lvs.sh` |
| 11 | **both** `layout/opamp_core/erc_report.json` *and* the same LVS report | `layout/opamp_core/run_erc.sh` (+ the LVS run above) |

Items 5, 6 and 7 still render `unmet` with reason `no_evidence`, which
remains the honest graded result rather than a placeholder. Item 8 is cited
but renders `unmet` with reason `check_failed`. Its envelope truthfully
carries `status: "fail"`, because the characterization report it wraps grades
four ratified rows FAIL (see below and
[#101](https://github.com/2AMLogic/sg13g2-opamp/issues/101)).

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

**Items 1, 9 and 10 are cited through artifact-anchored `generic` envelopes**
(klayout-tools#2718, available from the pinned revision on). These items have
no `klt` verb, so the old advice was to leave them visibly `unmet` rather than
borrow a passing DRC report. The grader now accepts a `generic` envelope that
declares `"t1_item": <id>`, names the audited file in `provenance.input.path`,
records its `content_hash`, and is pinned by the manifest at the same hash;
`klt signoff` re-hashes that file, so an edit after the attestation renders the
row `unmet` / `stale_evidence`. The three audited files are plain-text
inventories under [`evidence/`](evidence/):

| Item | Envelope | Inventory it is bound to | What the inventory attests |
|---|---|---|---|
| 1 Design sources | [`design-sources.json`](evidence/design-sources.json) | [`design-sources.txt`](evidence/design-sources.txt) | the schematic, symbol, committed netlist and the `xschem` command that regenerates the netlist; the netlist was regenerated from the schematic against PDK v0.3.0 and matched the committed one byte for byte except the `** sch_path:` header comment |
| 9 Testbenches shipped | [`testbenches.json`](evidence/testbenches.json) | [`testbenches.txt`](evidence/testbenches.txt) | one line per ratified measurement row of `spec/target-spec.md` section 2: its `sim/` bench, cold-start command, committed record and the pinned PDK revision (`sim/pdk.json`) |
| 10 Repo hygiene | [`hygiene.json`](evidence/hygiene.json) | [`hygiene.txt`](evidence/hygiene.txt) | the README sections (what the block is, the spec table, how to reproduce), `LICENSE` and the CI workflow `.github/workflows/signoff.yml` |

**What that does and does not mean.** `status: "pass"` in each envelope is the
author's assertion, bound to bytes. It is not a re-audit by the tool: `klt
signoff` verifies that the inventory still has the hash the envelope named, not
that its contents are true. The audit behind the assertion is stated in each
inventory's header. In particular the item 9 audit was *static* (scripts,
templates, READMEs, committed records and the PDK/OSDI preflight were checked;
the PVT and Monte Carlo grids were not re-executed for the attestation), and
`Area` (`[TBD-12]`) is not a ratified row, claims no measurement and has no
bench. Refresh an envelope (and its manifest pin) whenever the inventory it
names changes; `check_signoff.py` fails offline if the pin and the file
disagree, and `--run-klt` fails with `stale_evidence` if only the inventory
moved.

**What CI re-checks in those inventories, and what stays a dated audit.**
A hash binds the inventory *text*; it does not notice a cited record being
deleted or a runner losing its executable bit while the text stands still.
[`check_inventories.py`](check_inventories.py) (offline, stdlib-only, run in
the offline half of the `signoff` job) reads the three inventories through a
documented parseable subset of their existing format — `key: value` lines in
`design-sources.txt` / `hygiene.txt`, `row | bench | command | record` lines
in `testbenches.txt`; the grammar is in the script's docstring — and on every
push and PR verifies:

| Continuously checked (CI) | Inventory |
|---|---|
| schematic, symbol, committed netlist, `xschemrc` and sizing basis exist; `netlist-origin` names the listed schematic; the `regenerate` command's `cd`/`--rcfile`/`-o`/schematic arguments resolve to the listed `xschemrc`, netlist directory and schematic, and the netlist file name is the schematic stem + `.spice`; `design/README.md` has the "Running xschem / regenerating the netlist" heading; `sim/pdk.json` exists | `design-sources.txt` |
| per row: bench dir exists; the cold-start runner lives in it, exists, has the executable mode, and parses with `bash -n`; every `${EXPERIMENT_DIR}/testbench/…` template it references exists; the bench README has a "Cold-start invocation" section that names the runner; the cited record exists under `<bench>/records/`, is non-empty and has its `.md` companion. Shared harness files exist (`.sh` ones parse); `sim/tools/build-osdi.sh` is executable; the stated PDK pin agrees with `sim/pdk.json`'s `source`/`release_tag` | `testbenches.txt` |
| `README.md` has the "Why this block, on this PDK", "Target specification", "Reproducing the results" and "License" headings; `spec/target-spec.md` has a section 2 heading; every bench README has "Cold-start invocation"; `design/README.md`, `signoff/README.md`, `LICENSE` (with its Apache License 2.0 header) and the workflow exist; the workflow triggers on push and pull_request and runs `check_signoff.py`, `check_signoff.py --run-klt` and this validator | `hygiene.txt` |
| in a git checkout: every path above is tracked, and every runner's *committed* mode is `100755` | all three |

Negative controls ([`test_check_inventories.py`](test_check_inventories.py),
also in the offline half) build a throwaway fixture tree from what the
inventories name — never touching the real checkout — and assert the exact
diagnostic for a deleted cited record, a runner without its executable bit
(working tree and committed mode), invalid shell syntax, a missing design
source, a missing hygiene artifact, a missing heading, template, shared
harness file or workflow step, and a PDK pin that disagrees.

**Still dated manual audits (2026-10-08), not machine-checked:** that the
committed netlist is what `xschem` generates from the schematic (the
regeneration diff needs xschem and the PDK; a path existing says nothing about
equivalence); byte freshness of any source, record or README (only
existence, headings and the cited command are checked — record *contents*
for item 8 are pinned separately by `characterization/selection.json`); that
any PVT/MC grid ran as recorded or would reproduce today; that the PDK v0.3.0
install and OSDI build resolve (`build-osdi.sh --check` needs the PDK); and
that README prose is accurate beyond carrying the named headings. Limits of
the parse itself: a template whose path is built some other way than
`${EXPERIMENT_DIR}/testbench/<name>` is not seen, and a `${var}` inside a
template name is matched as a glob (at least one file must match). Changing an
inventory's wording outside the documented subset fails this check rather
than being skipped; changing it at all still needs the envelope, the
`pinned-inputs.json`/manifest pin and a new signoff record refreshed together.

Item 2 is still cited through the native `drc` envelope, which the grader
accepts without being able to judge its relevance (`topic: not bound` in the
report); binding it with a `generic` envelope over the GDS is a possible
follow-up and is not done here.

**Item 7 is uncited because the check has not been run.** `klt extract
--parasitics` + post-layout re-simulation is its own piece of work and none
has been done. Tracker:
[#3](https://github.com/2AMLogic/sg13g2-opamp/issues/3).

**Item 11 is the one compound citation, and what it does and does not
prove.** T1 item 11 (power delivery, structural — klayout-tools#2025) is the
first item no single artifact proves, so its manifest entry is a *list*: the
`klt erc` supply run plus the LVS report item 4 already cites. The supply
spec that run grades against is
[`layout/opamp_core/erc_supply_spec.json`](../layout/opamp_core/erc_supply_spec.json),
which carries an inline justification for every `stackup` entry, every
`label_layer` and both `ties[]` entries; the run is
[`layout/opamp_core/run_erc.sh`](../layout/opamp_core/run_erc.sh). What the
graded verdict rests on, stated here rather than left in the envelope:

- **Two supplies, `vdd` and `vss`** — this block's entire supply set — each
  declared `"kind": "supply"` with `islands: 1`, each resolving to exactly
  one labelled island, with zero `erc.unconnected_net`, zero
  `erc.supply_short` and zero `erc.missing_tie` (`erc_status: "clean"`,
  `erc_finding_count: 0`).
- **Both supplies are paired to a reference-side net** in the cited LVS
  report's `net_correspondence` (`vdd` → `VDD`, `vss` → `VSS`, both
  `pin: true`), which is the analog branch of the item — the block cites no
  `place-and-route` response, so `power_connectivity: "unchecked"` is the
  right and sufficient state here, exactly as it is for item 4.
- **Ties are declared, not disclosed away.** klayout-tools#2169 — where a
  declared `ties[]` entry collapsed a routed design into one island and
  reported a *false* `erc.supply_short` — is fixed in the `klt` that produced
  the committed report (`provenance.klt_version`), so the honest move is to
  declare the ties and let them be computed, not to file a
  `ties_disclosure` that item 11 would (correctly) render `unmet`. Both ties
  are graded as `checked` work, neither is `skipped`.
- **The n-well tie is derived from drawn geometry; the substrate tie is a
  caller assertion.** SG13G2 draws no p-substrate layer, so `psub_tie_vss`
  uses `well_layer: null` + `well_boxes` (klayout-tools#2255) naming the
  three NMOS guard-ring extents one at a time. The report says so itself in
  `erc_coverage.checked_by_well_assertion`. That is weaker provenance than
  the drawn `NWell` the `vdd` tie uses, and it is stated rather than buried.
- **What a clean `erc.unconnected_net` here is *not* evidence of.** The rule
  counts islands *carrying the declared label* (klayout-tools#2497), and this
  stream draws exactly one label per port — so it cannot, even in principle,
  report a severed-but-unlabelled rail fragment. `nets[].matched_islands: 1`
  in the report is that bound made visible. The independent evidence that no
  fragment is orphaned is the cited LVS compare (9/9 nets, 38/38 devices,
  `status: "match"`) and the generator's own connectivity self-check — not
  this rule.
- **The antenna half of the same envelope checked nothing.** `klt` ships an
  antenna-ratio limit table for sky130 only, so every one of the 49
  gate×level antenna work items is in `coverage.skipped` with reason
  `missing_antenna_pdk` and the envelope's own `status` is `not_checked`.
  Item 11 deliberately does not grade that field (it grades the supply rules
  directly), and antenna is tracked separately as klayout-tools#1994 — but a
  reader should not mistake the `met` row for an antenna verdict.

The layout generator also runs a connectivity **self-check** — it re-extracts
the drawn metal and asserts the nine nets are wired as
`design/netlist/opamp_core.spice` says, with no open, no short and nothing
floating — but that is not LVS (no device recognition, extraction stops at
Metal1) and is deliberately **not** cited as item 4 or item 11.

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
upstream, both rows correctly render `no_evidence`.

Item 6: the Monte Carlo campaigns now exist (offset random half, issue #17,
`sim/input-offset/records/mc-20260921-174056-0a509fb*`; mismatch-inclusive
CMRR, issue #26, `sim/cmrr-mismatch/records/20260921-172304-65f5fb4.csv`),
but no `klt yield` report is cited, for three recorded reasons: the spec
ratifies no per-draw limit or `target_yield` for either row (#108), the CMRR
record holds per-point summaries only, not per-draw samples (#107), and the
offset draws need a reshape into a sample-set document
([`yield-inputs/`](yield-inputs/README.md)). Item 6 stays `unmet`
until those close.

**Item 8 is cited through a `generic` envelope over a generated
characterization report** — [`characterization/`](characterization/README.md).
`characterization/generate.py` reads an explicit, hash-pinned record selection
(`characterization/selection.json`: the same records
[`evidence/testbenches.txt`](evidence/testbenches.txt) maps, checked against
it) and renders, for every claimed spec row, units, load and conditions, the
ratified bound and its decision record, the measured worst case and binding
point, the source record and its sha256, expected-versus-observed grid
coverage and a verdict. Minted records under `characterization/reports/` are
append-only; [`evidence/characterization.json`](evidence/characterization.json)
(`"kind": "generic"`, `"t1_item": 8`) binds the newest JSON record by repo path
and hash, and the manifest and `pinned-inputs.json` pin that same hash.
Regenerating it needs no ngspice, no PDK and no network:

```bash
python3 signoff/characterization/generate.py          # render; writes nothing
python3 signoff/characterization/generate.py --check  # cited record reproduces
```

That re-reads committed evidence; it is **not** a re-run of the simulations
(each bench README's "Cold-start invocation" is). What the item 8 row does and
does not mean:

- The generator writes the envelope's `status`. It writes `"pass"` only when
  the report's overall verdict is `PASS`: every ratified bound met, full valid
  grid coverage on every selected record, no input in error. Otherwise it
  writes `"fail"`, and klt then grades item 8 `unmet` (`check_failed`).
  `check_signoff.py` re-derives the cited record from its selected evidence
  (`generate.py --check`). A record that moved, or an envelope that no longer
  matches the newest report and its verdict, fails offline.
- **Bounds are compared literally, and the current report is FAIL.** Every raw
  grid value must meet the ratified bound as written. No rounding or
  precision convention is applied, because no ratification record defines
  one. Four rows miss the literal bound: DC gain, integrated noise,
  systematic offset and swing span, by 0.0188 dB, 0.049 µVrms, 0.027 mV and
  0.042 mV respectively. Their raw worst cases come from the very records
  DR-0002 cites, and only round onto the bounds it wrote. Whether to restate
  those bounds or ratify a comparison convention is a spec decision for the
  keys ([#101](https://github.com/2AMLogic/sg13g2-opamp/issues/101)), not
  something this tooling settles. Until then item 8 stays `unmet`.
- The first minted record, `characterization/reports/20261009-005750-622fb9c`,
  and the verdict of record graded from it, `reports/20261009-005834-69b7b63`
  (8/11, item 8 `met`), used a rounding rule that has since been withdrawn.
  Both are kept unedited as append-only history, but they are superseded and
  must not be read as the current verdict.
- Unratified measured quantities (offset mismatch 3σ `[P]`, ICMR) are
  reported in their own section with no pass/fail, the superseded systematic
  CMRR floor is context only, and Area stays `PENDING`. The offset Monte
  Carlo campaign's fixed 1.20 V supply is carried with its numbers.
- **It is item 8 evidence only.** It is an offline aggregation of
  harness-native records, not a `klt sim` / `klt yield` envelope, and is not
  cited for item 5 or 6 — `check_signoff.py` fails if the manifest cites it
  under any other item. Every number in it is pre-layout.

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
- **Item 11's three caveats are in "What the manifest cites" above** — the
  asserted (rather than drawn) substrate region behind the `vss` tie, the
  single-label bound on `erc.unconnected_net`, and the fact that the same
  envelope's antenna half checked nothing on this PDK. This discharges the
  honesty note the item was opened with: a `met` power-delivery row is a
  statement about the declared supplies' continuity in *metal*, not a
  statement that every rail fragment was found or that antenna was graded.

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
which closes that gap. Every layout pin — including both parts of item 11's
compound citation, whose `pinned-inputs.json` entry is a list with one
artifact per part — resolves to `layout/opamp_core/opamp_core.gds`, so
regenerating the layout without also refreshing the DRC, LVS and ERC reports,
every pin and the graded record fails the offline half of CI — by design.
Item 8's pin resolves to the minted characterization record, and the same
offline half re-derives that record from the `sim/` evidence it selects. The
checker also enforces the converse: it gathers a row for every new pin, and
rejects a `pinned-inputs.json` entry for an item the manifest does not cite.

One gap this does **not** close, stated because it is real: the ERC *supply
spec* is a second document the `klt erc` envelope merely names. Newer `klt`
hashes it into `provenance.spec` and `klt signoff` verifies it
(klayout-tools#2508), but the revision pinned in `klt-pin.txt` predates that,
so editing `erc_supply_spec.json` without re-running `run_erc.sh` would not
fail a build here. Re-run it whenever the spec changes; a klt-pin bump past
#2508 retires this caveat.

CI runs both halves
([`.github/workflows/signoff.yml`](../.github/workflows/signoff.yml)), on
every push and every PR:

| Check | Where | Needs |
|---|---|---|
| Manifest shape, pins vs. committed artifacts, record consistency, item 8 report reproduces | offline half of the `signoff` job, via `check_signoff.py` | python3 only |
| Item 1/9/10 inventory entries still hold (paths, runner modes, `bash -n`, records, doc headings) | offline half of the `signoff` job, via `check_inventories.py` | python3 + bash (+ git for the tracked/mode checks) |
| Inventory validator negative controls | offline half of the `signoff` job, `python3 -m unittest discover -s signoff -p 'test_check_inventories.py'` | python3 + bash + git |
| Characterization report negative controls | offline half of the `signoff` job, `python3 -m unittest discover -s signoff/characterization` | python3 only |
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

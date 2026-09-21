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

**Today the manifest cites nothing, and every T1 item renders `unmet` with
reason `no_evidence`.** That is the honest graded result, not a placeholder:
an accurate machine-readable statement that no `klt`-gradable envelope exists
in this repository yet. This block is early — it has a schematic, a
regenerated netlist and seven committed bench suites under `sim/`, but no
layout, no DRC/LVS chain, no post-layout run and no Monte Carlo campaign — and
the graded record says exactly that, on the record, where a hand-maintained
list would already be arguing with itself. As evidence lands in a gradable
shape, items gain citations and rows flip `unmet` → `met` mechanically.

**Items 1, 2, 9 and 10 are uncited on purpose.** They have no `klt` verb
behind them, so the grader scores them on "some passing envelope was cited at
all", never on topical relevance — citing a passing envelope for "Repo
hygiene" would render `MET` and the tool would have no basis to object. This
repo already owns artifacts those items describe (schematic + regenerated
netlist under `design/`; seven manifest-driven bench suites under `sim/`
with documented cold-start invocations and a pinned PDK revision; a README
and Apache-2.0 license; and, as of this change, CI), but asserting them
through an unrelated citation would make the record say something no check
verified. `klayout-tools/docs/cli/signoff.md` recommends exactly this
default — leave the four visibly `unmet` rather than borrowed-green.

**Items 3, 4, 7 and 11 are uncited because there is no layout.** `layout/`
still holds a placeholder README: no GDS/OASIS exists, so no `klt drc`, `klt
lvs`, `klt pex` or `klt erc` report can exist either. The whole
items-2-through-4-and-7-and-11 chain is sequenced behind the layout work
(tracker [#3](https://github.com/2AMLogic/sg13g2-opamp/issues/3), "What
stands between here and T1" step 3); item 11's specifics are tracked in
[#29](https://github.com/2AMLogic/sg13g2-opamp/issues/29).

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

## Disclosures that would travel with a claim — none today

Nothing is cited, so there is nothing to disclose; the manifest makes no
per-item claim beyond "no gradable check backs this row yet". Two honesty
notes for the future, taken from the issue that introduced this register:

- When item 3 first goes `met`, its DRC **coverage gaps** (rule-free layers,
  skipped rules) must be stated in the claim — a `met` verdict alone is not
  evidence that coverage was disclosed.
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
which closes that gap the moment the first citation appears (the map is
empty today, and the checker enforces that it gathers a row with every new
pin).

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

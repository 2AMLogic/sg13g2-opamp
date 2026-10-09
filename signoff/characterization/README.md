# Characterization report — T1 item 8

One aggregated artifact summarizing **every claimed spec row** of
[`spec/target-spec.md`](../../spec/target-spec.md) section 2 across the PVT
grid, with the evidence record each verdict rests on. It is generated, not
hand-written, from committed evidence only:

| File | What it is |
|---|---|
| [`selection.json`](selection.json) | The **explicit record selection**: every record the report reads, by path and pinned by sha256, and every claimed row (column, extremum, unit, load, ratified bound copied verbatim from the spec, decision record). Nothing is discovered by glob or file mtime. |
| [`generate.py`](generate.py) | Stdlib-only generator: audits the selected records, aggregates, and renders the report. |
| [`test_generate.py`](test_generate.py) | Negative controls (removed corner, injected failing point, failed simulation point, duplicate point, non-finite value, missing record, unpinned change, mixed ngspice, different netlist, dB-domain CMRR, spec/inventory drift, append-only minting) plus reproduction tests. |
| [`reports/`](reports/) | Minted records, **append-only**: `<UTC yyyymmdd-HHMMSS>-<short sha of HEAD>.json` (machine-readable) and its `.md` rendering. |

## Regenerate from a cold checkout (no ngspice, no PDK, no network)

```bash
python3 signoff/characterization/generate.py           # print the report; writes nothing
python3 signoff/characterization/generate.py --format json
python3 signoff/characterization/generate.py --check   # newest minted record reproduces
python3 -m unittest discover -s signoff/characterization   # negative controls
```

Python 3.9+ standard library only. This **re-reads committed records**; it
does not re-run a single simulation. Re-running the simulations behind the
records is a different, far more expensive operation (an SG13G2 PDK install,
ngspice, and long PVT / Monte Carlo grids) — see each bench README's
"Cold-start invocation" and
[`../evidence/testbenches.txt`](../evidence/testbenches.txt). A re-simulation
mints new `sim/*/records/`; this report only changes when `selection.json` is
deliberately edited to select them.

## What every row carries

Units; load and operating conditions; the ratified bound and the decision
record that binds it; the measured worst case and its **binding point**, plus
the best case; the source record path, column and sha256; expected versus
observed versus valid grid coverage (with missing and failed points named);
and a verdict:

| Verdict | Meaning |
|---|---|
| `PASS` | every expected point present and valid, and every point meets the ratified bound |
| `FAIL` | at least one valid point violates the bound (reported even if the grid is also incomplete) |
| `INCOMPLETE` | no violation seen, but expected points are missing or failed their bench's own validity flags — a failed point is never an extremum and can never turn into a pass |
| `ERROR` | the evidence cannot be trusted as selected: missing record, hash differs from its pin, duplicate `point_id`, non-finite or non-numeric value, point outside the grid or mislabelled, mixed ngspice version, a different simulated netlist, a broken definition (e.g. CMRR not in the linear domain), or a bound that no longer matches the spec text / a record the item 9 inventory does not cite |
| `MEASURED` | an unratified quantity (`[P]` or "Measured (not yet ratified)"): reported with its evidence, never given pass/fail |
| `PENDING` | no evidence by construction (Area, `[TBD-12]`) |

The report's overall verdict is `ERROR` > `FAIL` (ratified rows only) >
`INCOMPLETE` > `PASS`. The superseded systematic CMRR floor is shown as context
and never fails the report. Separately, the generator refuses a selection that
leaves any spec section 2 row or any item 9 inventory row uncovered.

**Comparison precision.** Each bound is compared at the precision it was
ratified at (the measured value is rounded half-to-even to the decimals
written in the bound). DR-0002 set each bound *at* the measured worst case it
cites, written to that precision; four rows (DC gain, noise, systematic
offset, swing span) clear their bound only that way, and the report lists
them and shows every row's raw margin and `strict_literal_pass` rather than
hiding the difference. This report interprets no bound beyond that and relaxes
none.

**Offset is two pieces of evidence, kept apart.** The ratified bound is the
systematic (nominal-device) half; the mismatch-driven 3σ half is measured
`[P]` and not yet ratified, and its Monte Carlo campaign ran at a **fixed
1.20 V supply** — the report carries that limit with the numbers.

## Minting a new record, and the item 8 citation

```bash
python3 signoff/characterization/generate.py --mint
```

writes `reports/<record-id>.json` + `.md` (refusing to overwrite, and refusing
to mint at all when the inputs are in `ERROR`) and re-wraps
[`../evidence/characterization.json`](../evidence/characterization.json): a
`generic` envelope, `t1_item: 8`, whose `provenance.input` binds the new JSON
record by repo path and sha256 and whose `status` is `pass` only when the
report's overall verdict is `PASS`. Then refresh the two pins it prints —
`signoff/block-manifest.json` `evidence["8"].content_hash` and
`signoff/pinned-inputs.json` `inputs["8"]` — re-grade with
`bash signoff/regenerate.sh`, and run `python3 signoff/check_signoff.py`
(which also runs `generate.py --check`).

This report is cited for **item 8 only**. It is a generic aggregation of
harness-native records, not a `klt sim` or `klt yield` envelope, and must not
be cited as item 5 or item 6 evidence; `check_signoff.py` fails if the
manifest cites it anywhere else.

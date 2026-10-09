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
| `PASS` | every expected point present and valid, and every point's raw value meets the ratified bound as written |
| `FAIL` | at least one valid point violates the bound (reported even if the grid is also incomplete) |
| `INCOMPLETE` | no violation seen, but expected points are missing or failed their bench's own validity flags — a failed point is never an extremum and can never turn into a pass |
| `ERROR` | the evidence cannot be trusted as selected: missing record, hash differs from its pin, duplicate `point_id`, non-finite or non-numeric value, point outside the grid or mislabelled, mixed ngspice version, a different simulated netlist, a broken definition (e.g. CMRR not in the linear domain), or a bound that no longer matches the spec text / a record the item 9 inventory does not cite |
| `MEASURED` | an unratified quantity (`[P]` or "Measured (not yet ratified)"): reported with its evidence, never given pass/fail |
| `PENDING` | no evidence by construction (Area, `[TBD-12]`) |

The report's overall verdict is `ERROR` > `FAIL` (ratified rows only) >
`INCOMPLETE` > `PASS`. The superseded systematic CMRR floor is shown as context
and never fails the report. Separately, the generator refuses a selection that
leaves any spec section 2 row or any item 9 inventory row uncovered.

**Comparison is literal.** Every valid grid point's raw value, scaled to the
bound's unit, must satisfy the ratified bound exactly as written. `>= 37.8`
means 37.7999 fails, and `>= 60` means 59.9 fails. No rounding, tolerance or
precision convention is applied, because no ratification record defines one
and choosing one is a spec decision, not this report's. Each row shows its raw
margin, and also its worst value rounded to the bound's written decimals. The
rounded value is **informational only and never gates a verdict**.

With the committed evidence that makes the report **FAIL**. Four rows (DC gain
>= 37.8 dB, integrated noise <= 108.9 µVrms, systematic offset <= 21.9 mV,
swing span >= 0.571 V) miss the literal bound by 0.0188 dB, 0.049 µVrms,
0.027 mV and 0.042 mV. Their raw worst cases (37.7812 dB, 108.949 µVrms,
21.927 mV, 0.570958 V) come from the very records DR-0002 cites, and they only
round onto the bounds DR-0002 wrote. The report lists them under
`overall.fail_only_beyond_written_decimals`. Restating those bounds, or
ratifying a comparison convention, is for the keys in a decision record:
[#101](https://github.com/2AMLogic/sg13g2-opamp/issues/101). Until then, FAIL
is the honest verdict, and the item 8 envelope carries `status: fail`.

The first minted record, `reports/20261009-005750-622fb9c` (schema
`characterization-report/1`), compared values after rounding them to the
bound's decimals, and graded PASS. That rule has been withdrawn. The record is
kept unedited as append-only history, but it is superseded and no longer
cited. `--check` verifies only the newest record.

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

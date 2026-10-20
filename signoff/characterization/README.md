# Characterization report — T1 item 8

One aggregated artifact summarizing **every claimed spec row** of
[`spec/target-spec.md`](../../spec/target-spec.md) section 2 across the PVT
grid, with the evidence record each verdict rests on. It is generated, not
hand-written, from committed evidence only:

| File | What it is |
|---|---|
| [`selection.json`](selection.json) | The **explicit record selection**: every record the report reads, by path and pinned by sha256, and every claimed row (column, extremum, unit, load, ratified bound copied verbatim from the spec, decision record). Nothing is discovered by glob or file mtime. |
| [`generate.py`](generate.py) | Stdlib-only generator: audits the selected records, aggregates, and renders the report. |
| [`test_generate.py`](test_generate.py) | Negative controls (removed corner, injected failing point, failed simulation point, duplicate point, non-finite value, missing record, unpinned change, mixed ngspice, different netlist, dB-domain CMRR, fabricated MC statistic, broken draws population, spec/inventory drift, append-only minting) plus reproduction tests. |
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

With the committed evidence that makes the report **FAIL**. Three rows
(integrated noise <= 108.9 µVrms, systematic offset <= 21.9 mV, swing span
>= 0.571 V) miss the literal bound by 0.049 µVrms, 0.027 mV and 0.042 mV.
Their raw worst cases (108.949 µVrms, 21.927 mV, 0.570958 V) come from the very
records DR-0002 cites, and they only round onto the bounds DR-0002 wrote.
(DC gain was a fourth, at 37.7812 dB, until the selection moved to the
corrected inn-AC-grounded open-loop record, issue #241, whose worst case is
38.2293 dB. The earlier reports that graded the superseded record are kept
unedited; see "Corrected open-loop record" below.) The report lists them under
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

## Offset Monte Carlo statistics audit (issue #199)

An MC record may pin the raw per-draw population behind its summary
(`draws_csv` + `draws_csv_sha256`, always together). Naming draws opts the
record into the **statistics audit** (definition check
`offset_mc_statistics`): every published per-point statistic — mean, sample
σ (N−1), 3σ, min/max over the passing draws, and
`vos_total_wc_det_plus_3sigma_v = |vos_systematic_det_v| + 3σ` — is
recomputed from those draws exactly as
[`sim/input-offset/run_offset_mc.sh`](../../sim/input-offset/run_offset_mc.sh)
computes it (accumulation in draw order), and each summary cell must be that
recomputed value **as the bench serializes it** (`printf %.9g`, nine
significant digits). The tolerance is the serialization itself: a cell that
is not the nine-digit rendering of the recomputed value — e.g. a fabricated
σ, mean, extremum or total — is an `ERROR` naming the point and the offending
field, never a published MEASURED row. The population itself must be complete
and singular (missing, duplicated, seed/metadata-conflicting or non-finite
PASS draws fail, via the [`../yield-inputs/`](../yield-inputs/) converter
contract); the `negctrl` draws are audited on their own and never pooled into
the mismatch statistics. Repinning a drifted draws file is a deliberate
selection edit, exactly like repinning a summary.

## CMRR mismatch statistics audit (issue #208)

The `cmrr-mismatch` record's `cmrr_linear_3sigma` check only proves that its
own summary is self-consistent (a coherently edited mean, sigma and CMRR would
satisfy it). The record therefore also pins its raw population under
`mc_samples` in [`selection.json`](selection.json): one sha256-pinned
`<point>_mc_samples.txt` per grid point (a pinned *list* of files, not the
offset draws CSV contract), the bench acceptance thresholds, and the
`av0_join` record Av0 comes from. Definition check `cmrr_mc_statistics`
re-derives every summary cell offline (stdlib only) with
`sim/cmrr-mismatch/mc_samples.py` `point_stats` — the same function
`run_cmrr_mismatch_mc.sh` uses — and holds each to the bench's `printf %.6g`.
The DR-0004 linear-domain definition is unchanged. Wrong counts, missing or
duplicated OP/AC pairs, non-finite tokens, stale pins and a wrong Av0 join are
point-specific errors. Historical sim records are untouched; only a new
report is minted.

## Input-noise raw-evidence audit (issue #213)

The `input-noise` record pins, per PVT point, its raw ngspice log and in-band
spectrum under `noise_raw` in [`selection.json`](selection.json) (sha256 for
each file, plus the documented 100 Hz - 1 MHz / 81-point / `dec 20` band).
Definition check `noise_raw_audit` re-derives the summary offline (stdlib only)
with [`sim/input-noise/noise_post.py`](../../sim/input-noise/noise_post.py),
the module `run_noise_sweep.sh` itself runs, so bench and audit share one
definition. Two checks run independently and both report: **integrated-log**
(`vni_int_vrms` must be the single `NOISE_INOISE_TOTAL` token of the pinned log,
which the bench copies verbatim) and **spectrum-derived** (five spot densities,
flicker/thermal split, flicker corner and fraction, and the trapezoidal
cross-check ratio, each at the bench's `printf %.6g`; `nan` where undefined).
The trapezoidal integral stays a cross-check of the logged figure, never a
substitute for it. Missing, duplicated or foreign-point associations, changed
pins, non-finite samples and malformed frequency grids are point-specific
errors; the report's sources table shows the audit status and the pin-set hash.
Historical sim records are untouched; only a new report is minted.

## Output-swing raw-evidence audit (issue #230)

The `output-swing` record pins, per PVT point, its raw DC evidence under
`swing_raw` in [`selection.json`](selection.json): one sha256-pinned coarse
and one fine transfer-curve `wrdata` file, one sha256-pinned rendered bench
netlist per pass, and the measurement configuration (coarse window, fine
half-span and step, the 0.5 x peak criterion — which must be exactly
[`sim/output-swing/swing_post.py`](../../sim/output-swing/swing_post.py)
`CONFIG`). Definition check `swing_raw_audit` re-derives the summary offline
(stdlib only) with that module — the same code `run_swing_sweep.sh` runs, so
bench and audit share one definition of the sampled estimator. The pinned
netlists must agree with the configuration and the point they are pinned to
(supply, `Vcm = VDD/2`, corner section, temperature, sweep window, recorded
vectors, wrdata target, pass label), the fine window must be centred on the
coarse crossing recomputed from the pinned coarse curve, and each curve must
carry exactly as many samples as its netlist's sweep declares. Per point the
audit recomputes the unique-crossing and plateau checks, the tracking bounds
at the sampled 0.5-times-peak region, both headrooms, the span, the fine
interpolated crossing, the peak incremental gain and the mid-swing supply
current, and holds each committed cell to the bench's `printf %.9g`
serialization of that value. Curves are strictly parsed (finite samples,
increasing scales, agreeing duplicate scale columns, exact column count);
missing, truncated, malformed or non-finite evidence, multiple or missing
coarse crossings and a fine window that truncates the accepted region are
errors naming the point and file. A summary edited coherently — bounds,
headrooms and span together, hash refreshed — still fails while the pinned
curves disagree. The record's cross-bench diagnostic columns
(`vos_offset_record_v`, `vos_delta_v`, `av0_ac_record_db`, `av0_ratio`,
`ivdd_ac_record_a`, `ivdd_ratio`) are logged, not gated, and stay outside
the audit. Historical sim records are untouched; only a new report is minted.

## Minting a new record, and the item 8 citation

```bash
python3 signoff/characterization/generate.py --mint
```

writes `reports/<record-id>.json` + `.md` (refusing to overwrite, and refusing
to mint at all when the inputs are in `ERROR`) and re-wraps
[`../evidence/characterization.json`](../evidence/characterization.json): a
`generic` envelope, `t1_item: 8`, whose `provenance.input` binds the new JSON
record by repo path and sha256 and whose `status` is `pass` only when the
report's overall verdict is `PASS`. Publication is serialized: a mint takes an
exclusive lock (`.mint.lock` in `reports/`, held for the life of the process),
publishes both records through no-clobber links so an existing destination is
refused byte-for-byte intact, rolls back a part-way failure, and swaps the
evidence envelope in atomically — a reader never sees a truncated envelope,
and a concurrent mint with the same record id refuses instead of overwriting.
A lock left behind by a killed mint is removed by hand before re-running.
Then refresh the two pins it prints —
`signoff/block-manifest.json` `evidence["8"].content_hash` and
`signoff/pinned-inputs.json` `inputs["8"]` — re-grade with
`bash signoff/regenerate.sh`, and run `python3 signoff/check_signoff.py`
(which also runs `generate.py --check`).

This report is cited for **item 8 only**. It is a generic aggregation of
harness-native records, not a `klt sim` or `klt yield` envelope, and must not
be cited as item 5 or item 6 evidence; `check_signoff.py` fails if the
manifest cites it anywhere else.

## PDK provenance (issue #191)

The report's `pdk_pin` is the *configured* release in `sim/pdk.json`; it is not
evidence of what a run loaded. Each selected record may additionally pin a
run-time **environment sidecar** (`sim/<bench>/records/<record-id>.env.json`,
contract and verifier in `sim/tools/env_identity.py`, captured before the
run's first solver and published only if it still matches when the harness
finalizes the record -- see `sim/README.md` "Run-time PDK/model identity",
issue #209, for that guarantee and its before/after limitation):

- `configured` (what `sim/pdk.json` asserted) is kept apart from `observed`
  (install `.fetched-version`, ngspice);
- `models` hashes the resolved `.lib`/`.include` closure of the SPICE model
  files the run loads, by path relative to the PDK install root, so absolute
  host paths never define identity and two installs with the same release marker
  but different model bytes have different `identity_sha256`;
- `osdi` binds the `sim/tools/build-osdi.sh` build manifest (Verilog-A inputs and
  compiled outputs).

Selection: add `env_sidecar` and `env_sidecar_sha256` (both, or neither) to a
`records` entry. Per-record status in the report:

| status | meaning |
|---|---|
| `verified` | sidecar pinned, bound to this record, identity recomputes, compatible with the current `sim/pdk.json` release/simulator |
| `legacy-unverified` | no sidecar selected (every record committed before #191); numbers and electrical verdicts are unchanged, PDK provenance is *not claimed* and is never invented retroactively -- it needs a new run and a new record |
| `error` | sidecar missing, hash-pin mismatch, malformed, tampered, for another record, or incompatible (e.g. `release_tag` changed after the run): the record's rows grade ERROR, so a configuration change cannot relabel old records as verified |

This is reported separately from the electrical PASS/FAIL. The report states PDK
reproducibility as claimed only when every selected record is `verified`.
Validation is offline: no PDK, simulator or network (`python3 -m unittest
discover -s signoff/characterization`, `-s sim/tools -p test_env_identity.py`).
Only the `open-loop-ac` harness and the shared klt wrapper
(`sim/tools/klt_run_common.sh`) write sidecars so far; other bespoke
`run_*.sh` harnesses are legacy until they call the helper.

## Load (CL) validation

A row's displayed load is **derived**, not copied. Each non-pending row in
`selection.json` carries `load_condition: {cl, applicability, note}`; free-text
`load` is rejected. The generator parses `cl` (so `2 pF`, `2e-12 F` and
`2000 fF` are the same load) and checks it against

1. the ratified `Load capacitance, CL` row of `spec/target-spec.md` section 1, and
2. every `CL = <value> <unit>` the sha256-pinned source record's `.md` states.

Any disagreement is an `ERROR` naming the contradiction, regardless of whether
the row passes or fails electrically. `applicability` is `applies` (AC, slew,
noise, swing, ... rows) or `dc_ignored` (DC analyses, where attached
capacitance does not affect the result; the report makes no load claim there).
A legacy `applies` record that states no CL is disclosed as `UNVERIFIED`
(matches the spec only) rather than given invented provenance; records are not
rewritten, and future finalized records should state `CL = <value> <unit>`.
Other condition prose (`conditions`) is labelled descriptive and unverified.

## Corrected open-loop record (issue #101)

`open-loop-ac` selects `sim/open-loop-ac/records/20261015-103057-895d555`
(`inn` AC-grounded, issue #241), which supersedes the floating-`inn` record
`20260910-221601-22feaba`. The old record stays selected, hash-pinned, as
`open-loop-ac-floating-inn`: it is the Av0 join the CMRR mismatch summary was
measured against, so the CMRR result keeps its real provenance and is **not**
presented as recomputed against the corrected Av0 (the same dependency holds
for any other result that joined the old Av0; new numbers need separately
authorized new evidence).

The new CSV has no `op_pass` / `gm_status` columns and names `iq_a` where the
old one named `ivdd_total_a`. Nothing was deleted to make it fit: the record
selects `klt_raw` (six sha256-pinned files: the AC and OP `klt sim` envelopes,
the `klt pex --measure-command` measurement document, both requests and the
bench body) and runs definition check `open_loop_klt_audit`
(`KLT_AUDIT_RULE` in the generated report). Column mapping:

| CSV column | recomputed from |
|---|---|
| `av0_db` | AC envelope `av0_db` (`find vdb(out) at=1`) |
| `gbw_hz` | AC envelope `gbw_hz` (`when vdb(out)=0`) |
| `pm_deg` | `180 + degrees(phase_at_ugf_rad)` |
| `iq_a` | OP envelope `ivdd_total_a` (`-i(vdd)`), which **includes** the bench's 10 µA `Iibias` reference |

Operating-point sanity (Vcm = VDD/2, |Vout - VDD/2| <= 0.15 VDD, Vout within
0.02 VDD of neither rail) is recomputed from the raw OP values. The legacy
check on the internal nodes `vd1`/`vd2`/`vtail` and the gain-margin status are
not re-measured by the corrected bench; the audit joins the superseded
record's `op_pass` as disclosed evidence (the AC ground element does not change
the DC operating point, confirmed by Vout and total VDD current agreeing to
10 µV and 10 nA), and says so in the report caveats. The envelopes ran on the
batch fleet, whose worker could not read the PDK release stamp, so the record's
PDK provenance stays legacy/unverified.

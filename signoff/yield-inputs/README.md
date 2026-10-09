# yield-inputs (T1 item 6 staging, issue #105)

Item 6 ("Statistical claims carry Monte Carlo evidence") is graded only from a
`klt yield` JSON report. This directory holds the **input** half of that
evidence and nothing else. **No `klt yield` report is committed, and
`block-manifest.json` has no `"6"` entry, because none can honestly be made
yet.** Item 6 stays `unmet / no_evidence`.

## The two statistical rows (verified against `spec/target-spec.md`)

No other row is statistical (noise, DC gain, GBW, PM, slew, swing, ICMR are
"deterministic corner-worst-case").

| Row | Per-draw data committed | Ratified per-draw limit | `target_yield` | State |
|---|---|---|---|---|
| Input-referred offset, random half | yes: `sim/input-offset/records/mc-20260921-174056-0a509fb-draws.csv` (15 points x N=300, seeds per draw) | **none**. Row is "Ratified, systematic only [DR-2]"; mismatch 3 sigma is `[P]`. The one ratified offset number (+21.9 mV) is the systematic bound (precision under #101), not a per-draw yield limit | none in spec | blocked on a decision, #108 |
| CMRR, mismatch-inclusive | **no**: only per-point summaries (`acm_lin_mean`, `acm_lin_sigma`, ...) | DR-0004's >= 26.68 dB is a +3 sigma aggregate, not a per-draw limit | none in spec | blocked on a bench change (#107) and a decision (#108) |

Not done, on purpose: inventing a limit or `target_yield`; reconstructing CMRR
samples from mean/sigma; re-running either campaign (the harnesses are shell
ngspice scripts, not `klt sim` requests, so a re-run through the batch fleet
needs the bench change in #107); using the offset record's zero-spread
`negctrl` point as a `klt yield` negative control (it is a no-mismatch
nominal, not a seeded known-bad variant, and `klt yield`'s `detected` verdict
needs a degraded population).

## What is here

`offset_draws_to_sampleset.py` reshapes the long-format draws CSV into a
`klt yield` sample-set document, one measurement per mismatch `point_id`
(`vos_v` in draw order, non-PASS draws as `null`, the `negctrl` point
dropped). It declares **no limits and no target_yield**. It is deterministic;
`--check` verifies the committed `offset-mc-*.sampleset.json` reproduces from
the committed CSV. Ingestion was verified with a throwaway `klt yield` using a
scratch limits file that is deliberately not committed (a limit chosen by an
agent would be an invented bound). The need for this converter is reported
upstream as 2AMLogic/klayout-tools#2931.

## Running `klt yield` here

The installed host `klt` lacks the `klt_yield_native` extension, and
`klayout-tools[yield]` does not resolve from PyPI (upstream
2AMLogic/klayout-tools#2900). Use a throwaway venv built from the pinned
revision (`signoff/klt-pin.txt`), not the host tool; see
`docs/cli/yield.md#building-the-native-extension` in that checkout.

## To close item 6

1. Decision record binding per-draw limits and `target_yield` (#108).
2. Persist CMRR per-draw samples (#107).
3. `klt yield` with a `--limits` file and a real seeded negative control; commit
   the report under `sim/<bench>/records/`; add `"6"` to the manifest with its
   `content_hash`; run `signoff/regenerate.sh`.

# margin-plan — coordinated design-margin study for the four literal-limit rows

Status: **plan only**. It selects no circuit change, topology, clock, numeric
tolerance or margin amount; it changes no limit or grade; it runs and
regenerates nothing. Authority for the direction is the operator ruling
recorded in
[DR-0009](../spec/decision-records/0009-literal-limits-design-margin-direction.md)
(issue #101). Completing this plan is not numerical acceptance and not signoff.

Every claim below is marked **[derived]** (read from a cited committed
record or document, or plain arithmetic on one) or **[hypothesis]** (an
engineering expectation not traced to a record here; it is a thing to test,
not a finding).

## 1. The four rows, as ruled

The literal limits and cited raw extrema are unchanged and all four rows
remain **FAIL** on raw values. No displayed-decimal comparison is used; the
small differences are not a justified tolerance.

| Row | Literal limit | Cited raw extremum | Binding point | Raw margin | Source record (column) |
|---|---|---|---|---|---|
| Open-loop DC gain | >= 37.8 dB | 37.7812 dB | `mos_fs_125C_1.08V` | -0.0188 dB | `sim/open-loop-ac/records/20260910-221601-22feaba.csv` (`av0_db`) |
| Input-referred noise, 100 Hz - 1 MHz integrated | <= 108.9 µVrms | 108.949 µVrms | `mos_fs_125C_1.08V` | -0.049 µVrms | `sim/input-noise/records/20260918-203850-90844d2.csv` (`vni_int_vrms`) |
| Input-offset, systematic | <= 21.9 mV | 21.9273527 mV | `mos_fs_125C_1.08V` | -0.027 mV | `sim/input-offset/records/20260918-203858-90844d2.csv` (`vos_null_v`) |
| Output swing, tracking span (CL = 2 pF, unloaded) | >= 0.571 V | 0.570957773 V | `mos_ss_125C_1.08V` | -0.042 mV | `sim/output-swing/records/20260921-151759-707b34c.csv` (`swing_span_v`) |

All four binding points are at 125 °C and VDD = 1.08 V **[derived]**:
three at FS (gain, noise, offset) and one at SS (swing). The load is CL = 2 pF
on every row (DR-1), with no resistive load, so the swing is an upper bound.

### How isolated each binding point is [derived]

Second-worst raw values in the same records, to show the failures are
single-corner, not a broad shortfall:

| Row | Binding point | Second-worst point | Second-worst value | Its margin to the limit |
|---|---|---|---|---|
| Gain | `mos_fs_125C_1.08V` 37.7812 dB | `mos_tt_125C_1.08V` | 38.9343 dB | +1.134 dB |
| Noise | `mos_fs_125C_1.08V` 108.949 µVrms | `mos_ss_125C_1.08V` | 106.896 µVrms | +2.004 µVrms |
| Offset | `mos_fs_125C_1.08V` 21.9273527 mV | `mos_ss_125C_1.08V` | 21.1370862 mV | +0.763 mV |
| Swing span | `mos_ss_125C_1.08V` 0.570957773 V | `mos_fs_125C_1.08V` | 0.572086158 V | +1.086 mV |

For the offset row exactly one of the 45 grid points exceeds 21.9 mV. That
fact, and the 45-point coverage, are preserved (section 5).

### Finding: the gain row's FAIL traces to a superseded record [derived]

The 37.7812 dB figure was measured with `inn` AC-floating (issue #241). The
grounded-`inn` record `sim/open-loop-ac/records/20261015-103057-895d555.csv`,
which supersedes it, reports **38.2293 dB at the same corner**
(`mos_fs_125C_1.08V`), and the batch envelope
`sim/open-loop-ac/klt/records/20261016-161057-8caa272.ac.sim.json` reports
38.229 dB there. `signoff/characterization/selection.json` still pins the
floating-`inn` record, so the characterization report still grades gain FAIL.

This plan **does not treat that as a PASS** and does not repin anything: the
ruling preserves the cited extremum and the raw FAIL. Whether to repoint the
selection (graded content; needs a newly minted report from an authorized
run) is for the operator and the keys; see DR-0009. For design purposes the
plan treats the gain margin as **unknown in sign** until that is decided.
The other three benches are DC or closed-loop measurements and the
grounded-`inn` correction concerns the AC loop break only; this plan does
not assume it leaves them unchanged beyond the committed `klt sim`
envelopes (noise `20261015-061719-80878d7`, offset `20261015-081722-8e276bc`),
which reproduce the harness values at the binding points per
`signoff/README.md`.

## 2. What sets each row (current sizing)

Sizing and the gm/ID citations are in
[`design/opamp_sizing.md`](opamp_sizing.md), anchored on
`sim/gm-id-characterization/records/20260909-063633-b402592.csv` (the study
that sizing cites; a later record, `20260928-161200-a6fa678`, also exists).
Devices: M1/M2 3.2 µm / 0.13 µm input pair; M3/M4 1.04 µm / 0.52 µm PMOS
mirror; M5 and Mbias 2.2 µm / 0.52 µm; M6 33 µm / 1.04 µm; M7 11.9 µm /
0.52 µm; Cc 1.0 pF.

| Row | Quantity and device that set it | Basis |
|---|---|---|
| Gain | Av1 = gm1 / (gds1 + gds3), Av2 = gm6 / (gds6 + gds7); in the sizing pass M7's gds (single-length mirror family, L = 0.52 µm) dominates the stage-2 conductance (26.4 µS vs 3.76 µS) | [derived] from `opamp_sizing.md`; first-order numbers (≈ 49 dB) overshoot the measured worst case, so magnitudes are **not** traced |
| Noise | Input pair M1/M2 flicker noise at minimum length; spectrum 1/f-dominated: at the binding point 93.7 % of in-band mean-square noise is flicker and the flicker corner is 1.62 MHz, above the band top | [derived] from `20260918-203850-90844d2.csv` (`flicker_frac_of_msq`, `flicker_corner_hz`) and DR-0003 |
| Offset | Stage-2 current sizing: M4 is forced to carry about I_D1 while M6 independently needs d2 near VDD - 0.55 V, so the input pair carries a built-in Vgs imbalance; at the binding point d2 sits at 0.3339 V against 0.3059 V (SS) and 0.3603 V (TT) at the same 125 °C / 1.08 V | [derived] qualitative mechanism from `opamp_sizing.md` ("Expected systematic offset"); d2 values from `20260918-203858-90844d2.csv` (`vd2_sample_v`); causal attribution of the corner dependence is a **hypothesis** |
| Swing span | VDD minus the two headrooms; at the binding point 1.08 - 0.303013651 - 0.206028576 = 0.570957773 V (upper headroom 0.303 V, lower 0.206 V) | [derived] arithmetic on `20260921-151759-707b34c.csv` (`headroom_hi_v`, `headroom_lo_v`) |

## 3. Coupling table

Direction of expected movement for each candidate investigation (`+` helps
the row, `-` hurts, `0` expected neutral, `?` unknown). Nothing here selects
a candidate or proposes a number. Every entry is a **[hypothesis]** unless a
citation is given; the point of the table is to say what each study must
measure, not to predict its result.

| Candidate investigation | Gain | Noise | Offset (systematic) | Swing | Other rows to re-check | Status |
|---|---|---|---|---|---|---|
| A. Longer M7 on a dedicated bias branch (the sizing doc's own follow-up candidate; needs a second reference branch) | + (first-order Av2 about 16 to about 33 in `opamp_sizing.md`; magnitude not traced) | 0 | ? (shifts stage-2 operating point) | ? (M7 sets the lower headroom) | Iq, PSRR, area, PM | [derived] that it is a documented candidate; effect directions are hypothesis |
| B. Longer or larger input pair | + (higher gm/gds at longer L, per the gm/ID record) | + (DR-0003 quantifies: matched-gm/Id lengthening at fixed current, 1.83x area moves the corner only to the band top; 8 to 20x area buys about 2.3 to 2.9x integrated noise) | ? | ? (input-pair Vgs moves the tail node) | GBW, ICMR (tail headroom), CMRR, area | DR-0003 figures are [derived]; others hypothesis. DR-0003 declined a re-size and names a re-open trigger, so this candidate reopens that record. |
| C. Re-balance M6 / M4 current and Vsg so d2 sits closer to the diode-mirror node | 0 | 0 | + | ? (M6 sets the upper headroom) | Iq, GBW, PM, slew | hypothesis; offset side is the #239 section |
| D. Raise stage-1 gain (for example M3/M4 length, tail/pair sizing) | + | 0 | + (systematic offset referred to the input shrinks with Av1) | 0 | ICMR, PM, GBW | hypothesis |
| E. M6 / M7 overdrive (width, current) to buy headroom | ? | ? | ? | + | Iq, GBW, PM, slew | hypothesis |
| F. Nulling Rz (sizing doc's PM candidate) | 0 | 0 | 0 | 0 | PM only | [derived] it is a PM lever, listed for completeness; not a margin lever for these four rows |

Coupled-row warnings that any study must address, not resolve here:
Iq already has a raw margin of only 0.045 µA against its 119.7 µA bound in
the grounded-`inn` record (119.655 µA at `mos_ss_-40C_1.32V`); slew has
7.5144 V/µs against 7.51; and PM is 61.99° against 60° there
(`signoff/README.md` coverage table). Candidates that spend current
or move the stage-2 bias (A, C, E) therefore compete with rows that are
already near their own limits **[derived]**.

## 4. Candidate investigation steps and the evidence each needs

Each step is a study to propose, not an authorization to run anything.

1. **Settle the gain baseline.** Evidence: the operator/key decision on which
   open-loop record the characterization selection pins (section 1 finding);
   until then, report gain margin against both records, side by side.
2. **Attribute each binding corner.** Evidence: per-device operating-point
   data (gm, gds, Vdsat, saturation margin) at `mos_fs_125C_1.08V` and
   `mos_ss_125C_1.08V` from the existing benches' per-point columns where
   they exist; a new run only if a column is missing and authorized.
3. **Quantify the lever per row.** For candidates A to E, a hand/gm-id
   estimate first, citing the gm/ID study (`sim/gm-id-characterization/`);
   magnitudes from `opamp_sizing.md` first-order numbers are not trusted
   without re-derivation against the measured corner values.
4. **Cost the coupled rows.** For each surviving candidate, list the rows
   in the table's "Other rows to re-check" column with their current raw
   margins (section 3 warnings).
5. **Write a sizing proposal as its own issue.** Any resulting sizing
   change needs its own issue, a citation of the applicable gm/ID
   characterization, and normal technical review. This plan is not that
   proposal and does not pre-approve one. Constraints that carry over:
   gm/ID-first sizing, CMOS-only, the classic spec rows, and a stated load
   on every row. HBT input stays closed.

## 5. Offset contribution (issue #239)

*Stub heading for #239.* Issue #239 is the offset contribution to this same
plan, not a competing specification and not a separate permission to loosen
the offset bound. Its PR fills this section; if it edits this file
concurrently, it waits for the #101 PR to merge. This section must keep:

- the literal limit (<= 21.9 mV) and the raw 21.9273527 mV, a miss of
  0.027 mV;
- the existing 45-point offset coverage with its single failing point
  (`mos_fs_125C_1.08V`); the other 44 pass **[derived]**;
- the distinction between **systematic** offset (this row, nominal-device,
  deterministic, corner-only) and **statistical** mismatch/yield work
  (#105, #108; mismatch-driven 3σ is measured `[P]` and not ratified), which
  this plan does not touch.

## 6. Prospective validation plan

For a future, separately authorized design change. Nothing here is run by
this PR.

- **Grid.** The full `[DR-1]` 45-point PVT grid: processes `mos_tt/ss/ff/sf/fs`
  x {-40, 27, 125} °C x {1.08, 1.20, 1.32} V, Vcm as each bench defines it.
  The binding corners above are re-examined first but never the only ones.
- **Testbenches.** `sim/open-loop-ac` (gain), `sim/input-noise`,
  `sim/input-offset`, `sim/output-swing` (span, with CL = 2 pF, no resistive
  load), plus every coupled row's bench named in section 3 (GBW, PM, Iq,
  slew, ICMR, CMRR, PSRR). The swing bench has only a one-point `klt sim`
  prototype; its 45-point request is tracked in #100 and is a prerequisite
  for `klt sim` coverage of the swing row.
- **Grading.** Raw values against the **unchanged literal limits**. No
  rounding, tolerance or guard-band reinterpretation. A row PASSes only if
  its raw worst case clears the literal limit at every grid point.
- **Provenance.** New records are appended with a fresh timestamp and git
  short-hash, never edited over; no historical record under `sim/` or
  `signoff/` is regenerated or amended, and every reported FAIL stays on the
  record. Characterization selection and T1 coverage semantics are kept:
  an envelope's coverage is evidence coverage, not numerical acceptance.
- **New characterization report.** A new `signoff/characterization/` report
  is minted only by an actually authorized run, reporting raw grades
  honestly. Nothing in this plan regenerates a report, re-attests a bench
  that has not been run, or claims a proposed design passes.
- **Compute.** Any grid or Monte Carlo run is expressed as a `klt sim`
  request and goes to the batch fleet; it needs its own authorization,
  which this plan does not carry.

## 7. Consistency across files if a future authorized change lands

The unchanged limit, the FAIL and the "envelope coverage is not numerical
acceptance" meaning currently agree across these files, and this PR edits
none of them:

- `spec/target-spec.md` section 2 rows (DC gain, noise, offset, swing): limit
  text and cited record paths.
- `spec/integrator.json`: `dc_gain_db_worst_min` 37.8,
  `input_noise_uv_rms_worst_max_100Hz_1MHz` 108.9,
  `offset_systematic_mv_worst_max` 21.9, `output_swing_span_v_worst_min` 0.571.
- `spec/consumers.md`: the offset and noise rows (about lines 70, 71, 90, 91)
  that quote 21.9 mV and 108.9 µVrms to consumers.
- `signoff/characterization/selection.json` (bound values and the pinned
  records) and its disclosure about bound precision.
- `signoff/README.md` (item 5 coverage table and its disclosures) and T1
  item 5.

A future authorized change that moves a measured value or a bound would
have to: update the pinned records and mint a new characterization report;
update `spec/integrator.json` and `spec/consumers.md` in the same change
(`signoff/check_integrator_contract.py` and `signoff/check_inventories.py`
exist for this); and, for a bound change, go through the DR-0002
two-key mechanism, which this operator direction does not satisfy. A design
change with unchanged limits needs only the first two.

## 8. Open items outside this plan

- **PR #27 ratification provenance**: unresolved; see DR-0009.
- **Gain baseline record** (section 1 finding): operator/key decision.
- **Offset contribution**: #239.
- **Swing 45-point `klt sim` request**: #100.

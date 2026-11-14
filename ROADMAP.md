# Roadmap

A two-stage Miller-compensated op-amp on IHP SG13G2 (CMOS devices only), with
every spec row carried on recorded PVT evidence.

Status as of 2026-11-13, `main` @ `85e7dbb`.

[`WORK_PLAN.md`](WORK_PLAN.md) is the generated label snapshot and the newest
record under [`signoff/reports/`](signoff/reports/) is the verdict of record;
where they disagree with this file, this file is stale.

## Where it stands

The graded register (`signoff/reports/20261027-011623-f8ef0ba.signoff.json`,
graded at the klayout-tools revision in `signoff/klt-pin.txt`, v0.8.0) marks
**7 of 11 T1 items met**. Tracker: [#3](https://github.com/2AMLogic/sg13g2-opamp/issues/3).

| T1 item | Verdict | Evidence, or what is missing |
|---|---|---|
| 1 Design sources | met | `design/opamp_core.sch`, `design/netlist/opamp_core.spice` |
| 2 Layout | met | `layout/opamp_core/opamp_core.gds`, generator `layout/opamp_core/generate.py` |
| 3 DRC clean | met | `layout/opamp_core/drc_report.json` (coverage gaps quoted in `layout/README.md`) |
| 4 LVS clean | met | `layout/opamp_core/lvs_report.json`, `match` |
| 5 Corner verification | unmet, `check_failed` | eight rows cited as `klt sim` envelopes; noise and systematic offset are recorded literal-bound misses; swing (three rows) and mismatch CMRR are declared gaps |
| 6 Monte Carlo evidence | unmet, `no_evidence` | offset and CMRR campaigns exist as harness records; no `klt yield` report, and no ratified per-draw limit or target yield |
| 7 Post-layout | unmet, `no_evidence` | `layout/opamp_core/pex_report.json` exists but is not cited: its two legs simulate different device geometry (`signoff/README.md`, "Item 7") |
| 8 Characterization report | unmet, `check_failed` | `signoff/characterization/` regenerates offline; the report is FAIL against the literal bounds |
| 9 Testbenches shipped | met | `signoff/evidence/testbenches.json` |
| 10 Repo hygiene | met | `signoff/evidence/hygiene.json` |
| 11 Power delivery | met | `layout/opamp_core/erc_report.json` plus the item 4 LVS report |

Spec: `spec/target-spec.md` is ratified in part (DR-0002, DR-0004). Area stays
`[TBD-12]` (DR-0007 is `proposed`; `layout/opamp_core/area_measurement.json`
is a proposed measurement). DR-0010 (statistical-row yield requirements) and
DR-0011 (fresh ratification request) are on `main` unratified.

**The direction changed on 2026-11-04.** The ratification review of DR-0011
(PR [#303](https://github.com/2AMLogic/sg13g2-opamp/pull/303)) found the
mismatch-inclusive CMRR, PSRR+ and gain bounds uncompetitive, and the offline
re-derivation in PR [#333](https://github.com/2AMLogic/sg13g2-opamp/pull/333)
showed a resize cannot close CMRR in the DR-0001 topology. The ruling on
[#332](https://github.com/2AMLogic/sg13g2-opamp/issues/332): open a topology
decision record that supersedes DR-0001, re-run every row on it, and ratify
once on the new design. No such record is on `main` yet; everything measured
so far describes the DR-0001 circuit.

## Now

1. **Topology decision record for the CMRR / gain / PSRR+ redesign**
   ([#332](https://github.com/2AMLogic/sg13g2-opamp/issues/332), ready).
   Done when `spec/decision-records/0012-*.md` is on `main` with status
   `proposed`, a first-order derivation of mismatch-inclusive CMRR, gain and
   PSRR+ that cites `sim/gm-id-characterization/` for every sizing choice, and
   the DR-0001 rows it supersedes. The 45-corner re-runs are Next.
2. **Finish the klayout-tools 0.8.0 pin sweep on the simulation side**
   ([#311](https://github.com/2AMLogic/sg13g2-opamp/issues/311), ready).
   Done when the shard-mode instruction in `sim/cmrr-psrr/README.md` names
   0.8.0 and every `corners.supply_v` key in the committed
   `sim/**/*.request.json` files is shown to name a voltage source. No grid.
3. **Cite the committed output-swing envelope in T1 item 5** (no issue yet).
   `signoff/block-manifest.json` still declares the three swing rows as gaps
   ("request not yet written or run"), but PR #323 committed
   `sim/output-swing/klt/records/20261101-010941-b7a1a86.sim.json`. Done when
   the manifest cites it and a new record is appended under
   `signoff/reports/`. The item stays `unmet` (the span miss is recorded, CMRR
   is still a gap); a stale gap becomes evidence.

## Next

- **Schematic, netlist and benches on the new topology**
  ([#332](https://github.com/2AMLogic/sg13g2-opamp/issues/332),
  [#342](https://github.com/2AMLogic/sg13g2-opamp/issues/342)). After Now 1 is
  ratified: `design/opamp_core.sch`, the regenerated netlist, and new
  append-only 45-corner `klt sim` records for every row, slew and quiescent
  current re-derived rather than inherited. #342 then measures PSRR+.
- **ICMR as a `klt sim` request**
  ([#325](https://github.com/2AMLogic/sg13g2-opamp/issues/325)). The offline
  half is on `feature/issue-325`; the record waits on a worker PDK install
  with the OSDI build manifest the preflight requires. Done when
  `sim/input-cmr/klt/` and a 45-point record reproducing
  `sim/input-cmr/records/20260921-174405-65f5fb4` are on `main`.
- **Drawn-fingering netlist** (DR-0008 step 3,
  [#237](https://github.com/2AMLogic/sg13g2-opamp/issues/237)), after #325 and
  the decision in #326. Done when `design/check_netlist_regen.py` passes on
  the `ng`/`m` form and the LVS reference still expands to 38 of 38 devices.
- **Post-layout citation, T1 item 7**
  ([#86](https://github.com/2AMLogic/sg13g2-opamp/issues/86)), after #237.
  Done when a `klt pex` report whose two legs share device geometry is cited
  in the manifest.
- **DR-0011 prose and review hygiene**
  ([#344](https://github.com/2AMLogic/sg13g2-opamp/issues/344),
  [#343](https://github.com/2AMLogic/sg13g2-opamp/issues/343)), after #332 and
  #342 fix the numbers they refer to.

## Later

- **Layout of the new topology, and items 2 to 4, 7 and 11 re-earned on it.**
  Question first: does the new circuit reuse the `layout/builder.py`
  primitives and floorplan, or need new device generators upstream?
- **Statistical rows as `klt yield` evidence, T1 item 6**
  ([#105](https://github.com/2AMLogic/sg13g2-opamp/issues/105)). Question
  first: per-draw limits and target yield (DR-0010, #108), and whether the
  Monte Carlo campaigns can run as batch requests rather than local grids.
- **Area row.** Question first: which definition DR-0007 ratifies.

## Blocked and waiting

- **Ratification of DR-0011 and DR-0010**
  ([#300](https://github.com/2AMLogic/sg13g2-opamp/issues/300),
  [#101](https://github.com/2AMLogic/sg13g2-opamp/issues/101),
  [#108](https://github.com/2AMLogic/sg13g2-opamp/issues/108); PRs #303, #302).
  Agents do not ratify. PR #303 is held and, per the ruling on #332, is not to
  merge as it stands; PR #333 targets its branch and conflicts. Items 5 and 8
  cannot turn `met` until bounds are ratified on the new design.
- **Layout pin move**
  ([#312](https://github.com/2AMLogic/sg13g2-opamp/issues/312)). On
  `feature/issue-312` the layout regenerated at a newer klayout-tools returned
  one phase-margin miss and one non-convergent corner out of 45 post-layout;
  how to proceed is a maintainer decision.
- **Monte Carlo rows after the netlist change**
  ([#326](https://github.com/2AMLogic/sg13g2-opamp/issues/326)): decision pending.
- **Upstream:** source/drain implants are not drawn by `klt gen mos_array`
  ([klayout-tools#2580](https://github.com/2AMLogic/klayout-tools/issues/2580)),
  so the committed stream is not a manufacturable mask set.

Two items are dispatchable today (#332, #311), a third once its issue is
filed. Most of the remaining backlog waits on the topology record.

## Not planned

- Relaxing a ratified bound to make a row pass.
- A `klt sim` form of the mismatch-CMRR Monte Carlo (#98, closed not planned).
- HBT-input and 3.3 V variants, unless a decision record opens one.

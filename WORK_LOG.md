# Work Log

<!-- Maintained by the Loom Guide role. Newest entries first. -->

### 2026-10-10

- **Issue #142** (closed): Dedup the copy-pasted envelope validation core across sim/*/klt/compare.py
- **PR #145**: sim: share the klt envelope gate across sim/*/klt/compare.py
- **Issue #140** (closed): sim: reserve record IDs atomically and refuse overwriting finalized evidence
- **PR #144**: sim: reserve record IDs atomically and refuse overwriting finalized evidence
- **Issue #106** (closed): Install ratification/ee-key and ratification/market-key reviewer trees (product#151)
- **PR #143**: ratification: install ee-key and market-key reviewer trees (#106)
- **Issue #136** (closed): signoff: enforce LVS reference freshness from schematic netlist to recorded match
- **PR #138**: signoff: enforce LVS reference freshness from schematic netlist to recorded match
- **PR #139**: sim: PSRR supply-gain klt sim request, runner and comparator (first increment)
- **Issue #134** (closed): signoff: bind ERC supply-spec bytes to the structural power-delivery evidence
- **PR #137**: signoff: bind ERC supply-spec bytes to item-11 evidence
- **PR #133**: sim: one-corner DUT prototype of the input-noise klt sim request (Part of #96)
- **Issue #98** (closed): sim: express the ratified mismatch-inclusive CMRR row as klt sim evidence (T1 item 5 coverage, follow-up to #85)
- **Issue #123** (closed): Auditor guard review: temporary scratch variables blocked by worktree confinement

### 2026-10-09

- **Issue #122** (closed): Auditor Capability Request: Python unavailable for offline signoff validation
- **PR #130**: sim: input-noise bench as a klt sim request (Part of #96, first increment)
- **PR #128**: spec: draft reproducible GDS bounding-box area definition for TBD-12
- **PR #127**: post-layout: klt-sim-based measure command for item 7 (partial; run blocked by batch runner mismatch) (#86)
- **PR #126**: signoff: post-layout pex harness for T1 item 7 (partial, #86)
- **PR #125**: ci: enforce append-only evidence against the previous Git tree
- **PR #120**: ci: run sim/ offline tests and evidence checkers in signoff.yml
- **PR #118**: sim: express the slew-rate bench as a klt sim request (T1 item 5, #95)
- **PR #117**: spec: draft DR-0006 resolving the ICMR row (not ratified)
- **PR #116**: post-layout: klt pex harness for T1 item 7 (#86) - grid NOT run
- **PR #113**: test(signoff): negative controls for check_signoff.py and sync_integrator.py
- **PR #112**: sim: guard MC runners against local grid execution under batch backend
- **PR #109**: signoff: record why T1 item 6 stays unmet; stage offset-MC sample-set (#105)
- **PR #104**: feat(signoff): continuously validate the item 1/9/10 inventory entries
- **PR #103**: integration: synchronize published GDS availability and graded maturity
- **PR #94**: signoff: per-spec-row characterization report from committed evidence (T1 item 8)
- **Issue #115** (closed): spec: select an area definition (resolve TBD-12) now that a DRC-clean routed GDS exists
- **Issue #121** (closed): ci: enforce append-only evidence against the previous Git tree
- **Issue #119** (closed): ci: run the sim/ offline tests and evidence checkers in signoff.yml
- **Issue #114** (closed): spec: resolve the unratified ICMR row -- measured lower bound excludes mid-rail Vcm at 15 of 45 PVT points
- **Issue #111** (closed): signoff: negative-control tests for check_signoff.py and sync_integrator.py
- **Issue #110** (closed): sim: guard MC runners against local grid execution when KLT_SIM_BACKEND=batch
- **Issue #92** (closed): signoff: continuously validate the static audit inventory entries
- **Issue #91** (closed): integration: synchronize published GDS availability and graded maturity
- **Issue #90** (closed): characterization: generate a reproducible per-row report from committed evidence
- **Issue #89** (closed): Auditor guard review: keep literal body=@path rejection

### 2026-10-08

- **PR #88**: signoff: bind T1 items 1, 9 and 10 to audited artifacts (klt 3a75c3ae)
- **Issue #84** (closed): signoff: bind T1 items 1, 9 and 10 to audited artifacts (klayout-tools#2718 landed)

### 2026-10-03

- **Issue #71** (closed): Retire the scaffold_smoke fixture: its DRC coverage is a strict subset of opamp_core's, and nothing cites it
- **PR #81**: Retire scaffold_smoke fixture; relocate DRC-deck negative control

### 2026-09-29

- **Issue #78** (closed): Wire the remaining sim/*/run_*.sh sed-render callers onto sg13g2_render_netlist (PR #77's helper missed 6 sites)
- **Issue #29** (closed): T1 item 11 (power delivery, structural): no klt erc supply spec or report in this repo
- **PR #80**: feat(signoff): klt erc supply spec + report for T1 item 11 (power delivery)
- **PR #79**: sim: wire remaining sed-render callers onto sg13g2_render_netlist

### 2026-09-28

- **Issue #74** (closed): Bench convergence fragility at tightened ngspice reltol — standing gate from DR-0005
- **Issue #73** (closed): Extract duplicated render() sed-template helper from run_*.sh into sim/preflight.sh
- **Issue #68** (closed): Decide whether sim/ benches should pin a tighter ngspice reltol (gm/ID's ~20% cross-host gds spread is tolerance-limited, and removable for free)
- **Issue #65** (closed): The committed gm/ID record does not reproduce numerically on a second host (up to ~20% on gm_gds)
- **Issue #64** (closed): sim/input-cmr/run_cmr_sweep.sh is committed non-executable, so its own documented invocation fails
- **Issue #62** (closed): Remove four unused layout/ accessors and the vestigial MIM-patch alias in scaffold_smoke
- **Issue #61** (closed): Extract duplicated sim_broken/latest_csv_in/csv_lookup helpers from run_*.sh into sim/preflight.sh
- **Issue #60** (closed): Dedup the ngspice broken-sim regex across 11 sites in sim/*/run_*.sh — gm-id's copy has drifted narrower
- **Issue #59** (closed): Remove duplicated run_drc(): consolidate into devices.py
- **Issue #57** (closed): layout: LVS the routed opamp_core GDS against the schematic netlist (T1 item 4)
- **Issue #56** (closed): Extract duplicated RECORD_ID/output-path boilerplate from sim/*/run_*.sh into sim/preflight.sh
- **Issue #54** (closed): Dedup MOS corner list: 10 identical CORNERS arrays across sim/*/run_*.sh
- **Issue #52** (closed): Remove duplicated run_drc(): identical klt-drc + report-write logic in layout/opamp_core and layout/scaffold_smoke
- **Issue #50** (closed): signoff: the layout's byte-for-byte regeneration claim is not enforced by CI, only the committed hash is
- **Issue #47** (closed): sim: extract the duplicated run_*.sh preflight preamble (env.sh source, OSDI/ngspice/netlist checks) into one shared sourced helper
- **Issue #45** (closed): layout: first-cut drawn-and-routed opamp_core GDS with a committed generator and klt drc report (T1 items 2-3)
- **Issue #44** (closed): layout: sg13g2 drawing/routing scaffold in layout/ (LV core MOS + MIM cap primitives, DRC-clean smoke fixture)
- **PR #77**: sim: extract duplicated render() sed-template helper into sim/preflight.sh
- **PR #76**: feat: warn when the live ngspice diverges from sim/pdk.json's pin
- **PR #75**: docs: keep default ngspice reltol, record tolerance study as DR-0005
- **PR #72**: sim: consolidate the record-join helpers into sim/preflight.sh
- **PR #70**: refactor: drop unused layout accessors and the scaffold_smoke MIM-patch alias
- **PR #69**: docs(gm-id): document the cross-host reproducibility envelope and identify its cause
- **PR #67**: fix: mark sim/input-cmr/run_cmr_sweep.sh executable (100644 -> 100755)
- **PR #66**: feat: add committed klt lvs compare for opamp_core (T1 item 4)
- **PR #63**: refactor: move the ngspice broken-sim gate into sim/preflight.sh
- **PR #58**: sim: hold the record-id and output-path preamble once in sim/preflight.sh
- **PR #55**: refactor: hold the MOS corner set once in sim/preflight.sh
- **PR #53**: refactor: consolidate the duplicated run_drc into layout/devices.py
- **PR #51**: signoff: state the layout regeneration claim as documented-provenance, not CI-enforced
- **PR #49**: layout: drawn-and-routed opamp_core GDS with a committed generator and klt drc report (T1 items 2-3)
- **PR #48**: sim: extract duplicated run_*.sh preflight preamble into sim/preflight.sh
- **PR #46**: feat: SG13G2 drawing/routing scaffold in layout/ (LV core MOS + MIM cap primitives, DRC-clean smoke fixture)

### 2026-09-22

- **Issue #41** (closed): Remove empty measurements/ scaffold: its role was absorbed by sim per-bench records
- **Issue #37** (closed): 2am: reuse rule 9 — name this block's consumers in the spec, carry their requirement rows, publish the integrator view as data
- **Issue #30** (closed): docs: input-noise README non-claim bullet predates the DR-0002 ratification (noise row is [DR-2], not [P])
- **PR #42**: chore: remove empty measurements/ scaffold (#41)
- **PR #40**: docs(spec): record consumers with per-row verdicts, publish integrator view as data
- **PR #39**: docs: past-tense the input-noise non-claim bullet after DR-0002

### 2026-09-21

- **Issue #32** (closed): spec: re-ratify the CMRR row on the mismatch-inclusive 3σ record (DR-0002 residual (c), two-key)
- **Issue #26** (closed): sim: mismatch Monte Carlo CMRR evidence for the DR-1 op-amp (companion to #17)
- **Issue #23** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read
- **Issue #21** (closed): sim: input common-mode range (ICMR) characterization bench
- **Issue #19** (closed): design: decide whether to re-size the input pair for flicker noise (1/f corner measured above the whole noise band)
- **Issue #17** (closed): sim: Monte Carlo statistical evidence for input-referred offset (seed/N/negative control)
- **Issue #16** (closed): spec: ratify target-spec.md via the two-key (EE + market) mechanism
- **Issue #15** (closed): sim: output-swing bench for the DR-1 op-amp
- **Issue #14** (closed): sim: CMRR/PSRR bench for the DR-1 op-amp
- **PR #36**: docs: re-ratify the CMRR row on the mismatch-inclusive 3σ record (DR-4)
- **PR #35**: sim: add mismatch Monte Carlo offset evidence for the DR-1 op-amp
- **PR #34**: sim: add input common-mode range (ICMR) PVT bench for the DR-1 op-amp
- **PR #33**: sim: add mismatch Monte Carlo CMRR evidence for the DR-1 op-amp
- **PR #31**: feat(signoff): add a klt-graded T1 signoff verdict of record
- **PR #28**: docs: decide input-pair flicker-noise re-size (declined) in DR-0003
- **PR #27**: spec: ratify measured target-spec rows via two-key DR-0002
- **PR #25**: sim: add CMRR/PSRR+ PVT bench for the DR-1 op-amp
- **PR #24**: sim: add output-swing PVT bench for the DR-1 op-amp

### 2026-09-18

- **Issue #13** (closed): sim: input-referred noise bench for the DR-1 op-amp (choose band, then measure)
- **Issue #12** (closed): sim: slew-rate (large-signal step) bench for the DR-1 op-amp
- **Issue #11** (closed): sim: input-referred offset bench (deterministic, corner-only) for the DR-1 op-amp
- **PR #22**: sim: add slew-rate (large-signal step) PVT bench for the DR-1 op-amp
- **PR #20**: sim: add input-referred noise PVT bench, choose the noise band
- **PR #18**: feat(sim): add deterministic PVT input-referred offset bench

### 2026-09-10

- **Issue #9** (closed): design: first-cut gm/ID sizing + xschem schematic of the DR-0001 two-stage Miller op-amp, with an open-loop gain/GBW/PM bench into CL = 2 pF across the five-corner grid
- **PR #10**: feat: first-cut gm/ID sizing, xschem schematic, and open-loop AC bench for DR-0001 op-amp

### 2026-09-09

- **Issue #6** (closed): spec: topology + CL decision record, informed by gm/ID study (issue #5)
- **Issue #5** (closed): sim: gm/ID characterization sweep of SG13G2 LV core MOS — the first engineering task (porting-plan §4, gm/ID-first)
- **PR #8**: spec: ratify two-stage topology and CL target (DR-1)
- **PR #7**: sim: gm/ID characterization sweep of SG13G2 LV core MOS (issue #5)

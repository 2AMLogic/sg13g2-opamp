# Porting plan — what carries over from sg13g2-bandgap and sg13g2-ldo

**Status: engineering input, not a ratified decision.** This document is the
required reading for anyone starting design work on this block once
[`target-spec.md`](target-spec.md)'s `[TBD-#n]` rows start getting filled
in. It does not ratify anything itself — no decision record exists yet in
this repo — and it does not perform any circuit design, schematic capture,
or simulation; it only names the nearest mature siblings and what a
two-stage Miller-compensated op-amp on SG13G2 can and cannot borrow from
them.

**This is a same-PDK port, not a cross-PDK one.** `sg13g2-bandgap` and
`sg13g2-ldo` are both on IHP SG13G2 — the identical PDK this repo targets.
That means none of the device-menu, model-library, or voltage-flavor-naming
translation work a cross-PDK port (e.g. `sg13g2-bandgap`'s own port from
`gf180-bandgap`/`sky130-bandgap`) requires is needed here. This plan is
deliberately lighter than that precedent's shape — closer in spirit to a
same-PDK architecture/topology survey than to a full cross-PDK device-menu
translation table. Its section structure ("what carries over unchanged" /
"what changes, and why" / "what does not transfer, and why") is borrowed
directly from `sg13g2-bandgap/spec/porting-plan.md`, which is itself the
structural model both this document and the `gf180-opamp` twin's own
porting plan cite.

## Sources checked

- [`2AMLogic/sg13g2-bandgap`](https://github.com/2AMLogic/sg13g2-bandgap) —
  same-PDK. `design/bandgap_amp.sch` (211 lines, verified 2026-09-06) is a
  **real, non-placeholder amplifier**: a PMOS input pair folded through an
  NMOS-then-PMOS mirror chain, closing the loop for `bandgap_core.sch`. It
  is the closest existing CMOS amplifier design in this exact PDK, and is
  this repo's nearest same-PDK amplifier precedent — worth reading for
  device-menu and topology inspiration (SG13G2 device names, common-mode
  handling near a one-VBE rail). It is a single-stage error amplifier for a
  bandgap loop, not a general-purpose two-stage Miller-compensated op-amp,
  so **only device-level patterns transfer, not the topology wholesale**
  (see §3). Its own `spec/porting-plan.md` is the structural model this
  document's section shape is borrowed from (see above), and
  [`sg13g2-bandgap#4`](https://github.com/2AMLogic/sg13g2-bandgap/issues/4)
  confirms the gap-to-T1 tracker shape this issue's own tracker deliverable
  follows.
- [`2AMLogic/sg13g2-ldo`](https://github.com/2AMLogic/sg13g2-ldo) —
  same-PDK, but **no transferable circuit content**. Its
  `design/ldo_erramp_placeholder.sch` exists, but its own header comment
  states explicitly: *"This is NOT a stand-in for any sibling repo's
  amplifier circuit — there is no gain stage, bias network, or compensation
  here to have copied."* It is a single ideal voltage-controlled voltage
  source (xschem's generic `vcvs.sym`, netlists as a native SPICE E-element,
  no PDK device involved) — a first schematic-entry placeholder for
  `ldo_core`, not a design artifact. **This block has no circuit-level
  content to port from `sg13g2-ldo`.** What does transfer is its
  `spec/porting-plan.md` (sections 2.2 "Error amplifier" and 4 "Ordered
  list of decision records") as a **process precedent only** — how that
  repo scoped and sequenced its own error-amp decision — not as a source of
  transferable device-level work. (The original issue #2 body's phrase
  "sg13g2-ldo's error-amp work" refers to this planning process, not to the
  placeholder schematic itself — see the issue's "Verified references"
  section for the full correction.)
- [`2AMLogic/gf180-opamp`](https://github.com/2AMLogic/gf180-opamp) — the
  three-foundry twin (different PDK). Its own
  [`spec/porting-plan.md`](https://github.com/2AMLogic/gf180-opamp/blob/main/spec/porting-plan.md)
  and
  [`spec/target-spec.md`](https://github.com/2AMLogic/gf180-opamp/blob/main/spec/target-spec.md)
  are the same-shape deliverables for this exact bootstrap issue on the
  twin repo, already built and Champion-approved — read directly as a
  same-shape example, though gf180's device menu, supply scope, and sibling
  set are all different and do not transfer numerically.
- [`2AMLogic/klayout-tools`, `docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md) —
  the T1 ("sim-validated") checklist this plan's linked gap-to-T1 tracker
  surveys.

## 1. What carries over unchanged

Same PDK means the *process* transfers wholesale; only the *topology* is
new (neither sibling is a standalone, general-purpose op-amp).

- **The verification discipline.** PVT-cornered testbenches (per
  `CLAUDE.md`: DC gain, GBW into a stated CL, phase margin, slew,
  input-referred noise, offset with statistical basis, CMRR/PSRR, output
  swing, at PVT corners with the load stated on every row), append-only
  `sim/` records, no claim without a testbench. Identical across every
  block in the fleet regardless of PDK.
- **The friction protocol.** Tool gaps against `klayout-tools` get filed
  generically, design specifics stay out of that tracker. Unchanged by
  topology or PDK.
- **The SG13G2 device menu itself.** Because this is a same-PDK port, the
  LV core devices (`sg13_lv_nmos`/`sg13_lv_pmos`, 1.2 V, PSP 103.6 model)
  and HV I/O devices (`sg13_hv_nmos`/`sg13_hv_pmos`, 3.3 V,
  `V_GS ≤ 3.3 V Maximum`) that `sg13g2-bandgap`'s porting plan already
  documents (its §2 device-flavor table) are the *same* devices this repo
  would use — no cross-PDK translation table is needed the way
  `sg13g2-bandgap`'s own porting plan needed one to map gf180's/sky130's
  device menus onto SG13G2's genuinely different one (bipolar device
  selection, voltage-flavor renaming, resistor-flavor TC tradeoffs). Device
  *numbers* (Vth, gm/ID sweeps) are not yet pulled into this repo — that is
  future device-characterization work — but the *menu* to characterize is
  already known and documented by a sibling.
- **CMOS-only default.** Per `CLAUDE.md`, this block is CMOS only unless a
  decision record opens the HBT-input stretch. `sg13g2-bandgap`'s own
  bipolar-vs-CMOS decision (its DR-0001, which chose the HBT `npn13G2` for
  its bandgap core) does **not** transfer as a precedent for this block —
  that decision was specific to a bandgap reference's VBE-based topology,
  which has no analog in a general-purpose op-amp's input stage. This
  repo's own CMOS-only default stands until its own decision record says
  otherwise.
- **gm/ID-first sizing.** `CLAUDE.md`'s "gm/ID first, committed to `sim/`
  before sizing" is the same practice `sg13g2-bandgap` follows; nothing
  about a two-stage op-amp topology changes that ordering.
- **The decision-record process itself**, once one is needed. No
  `spec/decision-records/` directory exists in this repo yet (this
  bootstrap pass makes no decisions requiring one). When the first real
  decision is made (e.g. picking a compensation scheme, or opening the
  3.3 V I/O stretch row), it should follow one of the two precedented
  conventions — `sg13g2-bandgap`'s `NNNN-<slug>.md` or `sg13g2-ldo`'s
  `DR-NNN-<slug>.md` — picked once and kept consistent within this repo;
  the fleet has not converged on one, so neither choice is wrong.

## 2. What changes, and why

Neither sibling is an amplifier-as-the-whole-block the way this repo is.
`sg13g2-bandgap`'s error amplifier is a sub-block tuned to a bandgap
reference's own narrow needs; `sg13g2-ldo`'s "error amp" is not a design
artifact at all (§ Sources above). This is exactly the gap the fleet-wide
op-amp effort (this repo plus its `gf180-opamp`/`sky130-opamp` twins) exists
to close: standalone, classic-row-specified amplifiers that the rest of the
fleet's blocks embed but never characterize on their own terms.

| Aspect | sg13g2-bandgap / sg13g2-ldo | sg13g2-opamp | Why it changes |
|---|---|---|---|
| What is being specced | An error amplifier *inside* a larger loop (bandgap reference loop; LDO regulation loop — currently unimplemented), specced only indirectly through the host block's own rows (PSRR, output-reference accuracy) | A standalone two-stage Miller-compensated op-amp, specced directly on its own classic rows (gain, GBW/PM into stated CL, slew, noise, offset, CMRR/PSRR, swing, power) | Neither sibling's spec table has an amplifier-level GBW/PM/slew/CMRR row at all — those rows do not exist to copy, only the host-level rows their amplifier subserves (where one is even designed — `sg13g2-ldo`'s is not). This repo has to originate its own row set from `CLAUDE.md`, not extract one from a sibling's ratified table. |
| Input stage topology | `bandgap_amp.sch`: a single-stage PMOS differential input pair, folded through an NMOS-then-PMOS mirror chain — sized for a bandgap loop's narrow common-mode range near a one-VBE rail | Needs its own common-mode range and gain-stage decision for a general-purpose input, with no fixed host context to lean on | `bandgap_amp.sch`'s device-level patterns (PMOS input pair, fold/mirror chain, SG13G2 device naming) are worth reading, but the sizing itself was never meant to serve an arbitrary common-mode input range — a standalone op-amp's input stage is a first-class design decision here, not inherited. |
| Number of gain stages / compensation | `bandgap_amp.sch` is single-stage (folded, not a cascaded two-stage design); no Miller compensation exists in either sibling to reuse | Two-stage, Miller-compensated between stages, sized against a stated external `CL` per `CLAUDE.md` | `CLAUDE.md`'s topology mandate (two-stage Miller-compensated) has no sibling precedent to borrow from in this PDK at all — this is genuinely new circuit design, not a port. |
| Amplifier-characterization testbench shape | Neither sibling ships a standalone open-loop-gain / GBW / phase-margin / CMRR / PSRR testbench for its embedded (or, for `sg13g2-ldo`, not-yet-designed) amplifier — those quantities, where measured at all, are measured only at the host-block level | Needs the full classic-row testbench suite: open-loop AC sweep for gain/GBW/PM, transient step for slew, noise analysis, CMRR/PSRR AC sweeps, swing sweep, Iq measurement | No sibling in this PDK has built this testbench shape yet — the twin `gf180-opamp` repo's own porting plan names `sg13g2-bandgap`'s amplifier-characterization *intent* as the nearest cross-repo analog, but no SG13G2 sibling has actually shipped one to copy from directly. |
| Input/output common-mode range | Bounded by each host circuit's own fixed internal nodes (a bandgap error amp's inputs pinned near a PTAT/CTAT-derived node) | Must be specified in general, since a standalone op-amp has no fixed host context — this is exactly the new "swing" and "CMRR" rows in `target-spec.md` that neither sibling's design work carries | A standalone amplifier's common-mode/output-swing spec is a first-class deliverable here; for `sg13g2-bandgap` it was an internal implementation detail of a larger loop, never separately specified. |

## 3. What does not transfer, and why

- **`bandgap_amp.sch`'s literal schematic.** It is sized for a narrow,
  fixed internal role (correcting a bandgap core's PTAT/CTAT mismatch near
  a one-VBE common-mode point) and is single-stage, not a general-purpose,
  standalone two-stage Miller-compensated op-amp meant to drive an
  arbitrary external `CL`. Copying it wholesale would inherit sizing
  decisions made for a different design problem — only its device-level
  patterns (device menu, fold/mirror structure, SG13G2 naming
  conventions) are worth reading, per the "Sources checked" note above.
- **`sg13g2-ldo`'s placeholder VCVS as circuit content.** As stated in its
  own header comment and reiterated above, `ldo_erramp_placeholder.sch` has
  no gain stage, bias network, or compensation to copy. Its
  `spec/porting-plan.md` transfers only as a *process* precedent (how that
  repo scoped and sequenced its own error-amp decision-record work), never
  as a source of device-level design content. A future reader should not
  infer from the original issue #2 body's phrase "sg13g2-ldo's error-amp
  work" that any circuit was actually ported from it — none was, or could
  have been.
- **`sg13g2-bandgap`'s bipolar-device-selection decision record (DR-0001).**
  That record exists specifically because a bandgap reference's core
  topology can be built around either a real HBT (`npn13G2`) or a
  low-gain PNP (`pnpMPA`) — a question with no analog for a general-purpose
  CMOS op-amp input stage. Per `CLAUDE.md`'s CMOS-only default (§1 above),
  this repo does not face an equivalent bipolar-vs-CMOS decision unless a
  future decision record explicitly opens the HBT-input stretch.
- **Either sibling's own numeric mismatch/PVT evidence.** Any measured
  coefficient in `sg13g2-bandgap`'s decision records (e.g. its HBT
  matching-coefficient discussion) is specific to that circuit's own
  devices and operating point. Only the *practice* of measuring rather than
  assuming transfers, per `CLAUDE.md`'s "no claim without a testbench" —
  the numbers themselves do not.

## 4. Open items and next steps

- **Topology decision.** Neither sibling's amplifier schematic transfers
  directly (§3), so the first real design decision this repo needs is its
  own two-stage Miller-compensated topology choice (input-pair polarity,
  output-stage class, cascode-or-not) — not yet made, and out of scope for
  this bootstrap pass.
- **Load capacitance (`CL`) target.** `target-spec.md`'s GBW/PM rows are
  stated "into stated CL" per `CLAUDE.md`, but no CL value has been chosen
  yet — tied to the topology decision above, not independent of it.
- **Device characterization.** `CLAUDE.md`'s "gm/ID first" ordering means
  the next concrete step, once this bootstrap pass merges, is a gm/ID
  characterization sweep over SG13G2's LV core MOS flavor, committed to
  `sim/` before any sizing work — the same practice `sg13g2-bandgap`
  already followed on this PDK for its own devices.
- **Gap-to-T1 tracker.** Tracks the block's current distance from the
  klayout-tools T1 ("sim-validated") design-evidence tier — every
  checklist item is currently unmet, since no schematic/layout/sim work has
  started. Linked from `README.md`. It is the natural place future passes
  record progress against items 1–11 as design work lands.

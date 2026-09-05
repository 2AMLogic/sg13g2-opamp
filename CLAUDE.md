# sg13g2-opamp — agent instructions

Open-source canary block: a two-stage miller-compensated operational amplifier on ihp sg13g2,
on IHP SG13G2, IHP's open-source 130 nm SiGe BiCMOS PDK, designed and verified by AI agents.

- **PDK**: IHP SG13G2 (https://github.com/IHP-GmbH/IHP-Open-PDK). Open-source flow: xschem + ngspice for
  design/sim, klayout-tools (`klt`) for layout work.
- **New block; three-foundry twin.** sg13g2-opamp, gf180-opamp, and
  sky130-opamp were opened together and share spec structure and bench
  definitions so results compare across PDKs. Keep the benches structurally
  identical; derive every number from THIS PDK's models.
- **gm/ID first.** Commit the device-characterization study before sizing;
  every sizing decision cites it.
- **The classic rows are the spec**: DC gain, GBW into a stated CL, phase
  margin, slew, input-referred noise, offset (with statistical basis), CMRR/
  PSRR, output swing — at PVT corners, with the load stated on every row.
- **CMOS only** unless a decision record opens the HBT-input stretch.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail out of it and
  describe the gap, not the design.
- **Verification is the product**: no claim without a testbench; PVT corners
  on every recorded result; `sim/` results are append-only evidence.
- Spec changes go through `spec/` with a decision record; agents do not
  relax the ratified spec to make results pass.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->

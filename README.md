# sg13g2-opamp

A two-stage Miller-compensated operational amplifier on IHP SG13G2 on
[IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK), IHP's open-source 130 nm SiGe BiCMOS PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

**Status: just opened.** Nothing is designed yet. The first work is
the device-characterization study — gm/ID curves for the PDK's core CMOS devices, committed as the sizing basis every later claim leans on.

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result under PVT corners. Where the agents hit friction with the
open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction is
filed as a public issue against the tool itself, so the fix benefits everyone
using this PDK, not just this repo.

## Why this block, on this PDK

An operational amplifier is the most conspicuous absence in an analog IP
catalog that already ships bandgaps, LDOs, PLLs, and ADCs — every one of
which embeds amplifiers it never characterizes standalone. This repo, with
its gf180 and sky130 twins opened the same day, closes that gap with the
same block on three foundries: a two-stage Miller OTA specified and
verified the same way everywhere, so the cross-PDK comparison is itself a
result.

On SG13G2 the CMOS devices (not the HBTs) are the design vehicle — this is
deliberately the plain-CMOS twin of the gf180/sky130 repos, so the
three-way comparison stays honest. An HBT-input variant is a stretch row
that only a decision record can open.

## Target specification (DRAFT — engineering to ratify)

DC gain, GBW and phase margin into a stated capacitive load, slew rate,
input-referred noise, offset sigma (basis stated), CMRR, PSRR, swing,
supply/power at 1.2 V. Rows filled only from committed benches, PVT corners
recorded.

## License

Apache-2.0.

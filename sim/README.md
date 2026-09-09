# sim/ — ngspice testbenches and append-only evidence records

Per `CLAUDE.md`: **verification is the product, no claim without a
testbench**, PVT corners on every recorded result, and results here are
**append-only evidence** — a re-run mints a new, timestamped record; nothing
under an experiment's `records/`, `netlist-snapshots/` or `corners/` is ever
edited or deleted after it lands. This follows the same per-experiment shape
(`README.md` / `testbench/` / `corners/` / `netlist-snapshots/` / `records/`)
`sg13g2-bandgap/sim/<experiment>/` established on this same PDK.

## PDK pin

Every record in this tree is generated against the PDK revision pinned in
[`pdk.json`](pdk.json) (`IHP-Open-PDK` tag `v0.3.0`, fetchable via
`klayout-tools`' `scripts/fetch-ihp-sg13g2.sh`). `source env.sh` resolves
`PDK_ROOT`/`PDK` the same way `sg13g2-bandgap/sim/env.sh` does (env vars
first, then the usual open_pdks install prefixes) — every experiment's
`run_*.sh` sources it, and an interactive `ngspice` session can too.

## OSDI device models

SG13G2's LV/HV MOS (PSP103.6) compact model is Verilog-A; ngspice can only
instantiate it through an OSDI-compiled shared library, and the pinned
IHP-Open-PDK v0.3.0 release ships the Verilog-A *sources* only (no prebuilt
`.osdi`). `sim/tools/build-osdi.sh` compiles the PDK's own sources with a
checksum-pinned OpenVAF-Reloaded release (see that script's header for full
provenance); `--check` verifies the models are present and loadable without
rebuilding. Every experiment's `run_*.sh` preflights this before simulating.

## Experiments

- [`gm-id-characterization/`](gm-id-characterization/) — gm/ID, gm/gds, Cgg
  and fT vs Vgs/overdrive for SG13G2's LV core MOS devices
  (`sg13_lv_nmos`/`sg13_lv_pmos`), across four channel lengths and the five
  `cornerMOSlv.lib` process corners (issue #5). The first engineering
  artifact for this block, per `spec/porting-plan.md` §4's "gm/ID first"
  ordering.

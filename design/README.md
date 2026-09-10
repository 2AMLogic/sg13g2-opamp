# design/

Schematics (xschem) and netlists for the DR-0001 two-stage Miller-compensated
op-amp core (issue #9).

```
design/
  xschemrc            repo xschem config: resolves the SG13G2 PDK, adds
                       this repo's own symbol/testbench directories to the
                       library path (ported from sg13g2-bandgap's
                       design/xschemrc, same PDK, same fleet convention)
  opamp_sizing.md      gm/ID sizing pass -- W/L/Id for every device, citing
                       sim/gm-id-characterization/records/*.csv directly
  opamp_core.sch       the op-amp core schematic
  opamp_core.sym       hierarchical-instantiation symbol for the above
  netlist/             xschem-generated .spice netlists (committed --
                       reviewable in git, same convention sg13g2-bandgap
                       uses)
```

## What's here (issue #9)

- **`opamp_sizing.md`** — the gm/ID sizing pass: `W`/`L`/`Id`/mirror ratios
  for every device of the DR-0001 topology (NMOS input pair, PMOS mirror
  load, NMOS tail, PMOS output gain device, NMOS output current sink,
  Miller `Cc`), each choice citing a literal row of
  `sim/gm-id-characterization/records/20260909-063633-b402592.csv`, plus
  first-order expected `Av0`/GBW/SR/`Iq`. Read this first — the schematic
  below implements exactly what it derives.
- **`opamp_core.sch`** — the schematic itself: `sg13_lv_nmos`/`sg13_lv_pmos`
  input pair, mirror, tail, output stage, and a `cap_cmim` Miller cap (CMOS
  only, per `CLAUDE.md`; no nulling `Rz` in this first pass — see
  `opamp_sizing.md`'s "Rz" section for why). Pins: `vdd`, `vss`, `inn`,
  `inp`, `out`, `ibias`. Full topology and polarity rationale is in the
  schematic's own header comment.
- **`opamp_core.sym`** — hierarchical-instantiation symbol, pin order
  matching the schematic's own `iopin` list exactly.
- **`netlist/opamp_core.spice`** — the netlist this schematic regenerates
  to (see "Running xschem / regenerating the netlist" below). This is a
  **flat** netlist (xschem emits its top-level `.subckt`/`.ends` lines as
  full-line SPICE comments, `**.subckt ...`, when the schematic is
  netlisted directly rather than instantiated as a symbol elsewhere) — so
  `sim/open-loop-ac/`'s testbench `.include`s it directly rather than
  instantiating an `X...` line.

## Running xschem / regenerating the netlist

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
cd design && xschem --rcfile ./xschemrc opamp_core.sch   # interactive
```

To regenerate the committed netlist headlessly (no X server needed) — the
**one documented command** this issue's acceptance criteria names:

```bash
export PDK_ROOT=/path/to/ihp-open-pdk
export PDK=ihp-sg13g2
cd design
xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./opamp_core.sch
```

Same fleet convention `sg13g2-bandgap/design/README.md` and
`sim/smoke_test/run_smoke_test.sh` use (`xschem -n -x -q -r`: netlist,
headless X, quiet, regenerate-existing). The netlist lands in
`design/netlist/opamp_core.spice` and is committed (reviewable in git).

**A resolvable SG13G2 PDK install is required** (`PDK_ROOT`/`PDK` pointing
at an `ihp-sg13g2/` open_pdks-shaped directory — see `CLAUDE.md`;
klayout-tools' own `scripts/fetch-ihp-sg13g2.sh` fetches a pinned
IHP-Open-PDK release into that shape). This repo does not vendor the PDK
itself.

## What has been verified in this environment (issue #9)

- **Netlisting**: `opamp_core.sch` was netlisted headlessly with a real,
  fetched SG13G2 PDK install (`xschem -n -x -q -r`, command above) with
  zero errors, and the resulting `design/netlist/opamp_core.spice`
  (committed) was checked device-by-device against the schematic's own
  header pin mapping — e.g. `XM1 d1 inn tail vss sg13_lv_nmos ...`, `XM3
  d1 d1 vdd vdd sg13_lv_pmos ...` (diode-connected), confirming the
  schematic is syntactically valid and wired exactly as documented, using
  only `sg13_lv_nmos`/`sg13_lv_pmos`/`cap_cmim` devices and the stated
  ports.
- **Full-circuit simulation**: unlike `sg13g2-bandgap`'s original issue #9
  (whose HBT-only op-point check could not exercise the PSP103 MOS models
  because no OSDI build existed in that environment), **this** repo's
  sandbox has a working OSDI build (`sim/tools/build-osdi.sh --check`
  passes) and a working `ngspice`/`xschem` install, so `opamp_core.spice`
  was actually simulated, not just netlisted — see
  `sim/open-loop-ac/README.md` for the full open-loop AC PVT-grid bench
  and its results.

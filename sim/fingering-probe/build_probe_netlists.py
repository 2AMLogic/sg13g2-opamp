#!/usr/bin/env python3
"""Write the five DUT netlists of the issue-#237 device-representation probe.

  build_probe_netlists.py <out-dir>

The first post-layout run (layout/opamp_core/pex_report.json, #86/#236) shows
schematic-vs-extracted deltas (Iq -20..-32 %, gain up to +18.7 %, GBW up to
+27.8 %) that a lumped-RC annotation cannot produce. Its two legs differ in
per-device geometry as well as parasitics: the schematic leg simulates one
lumped ``ng=1`` device per instance, the extracted leg the drawn units and
fingers. This script writes one netlist per step between the two, so the
probe (run_probe.sh) can attribute the delta step by step:

  lumped           design/netlist/opamp_core.spice, byte-for-byte (the
                   reference leg of the #236 run).
  drawn            the same nine instances, each written as drawn:
                   matched-pair devices as ``w=<unit> ng=1 m=<units>`` (the
                   layout's interdigitated units have unshared diffusion),
                   folded devices as ``w=<total> ng=<fingers> m=1`` (the
                   layout's fingers share S/D). This is the candidate
                   option-1 schematic form. No dummies, no parasitics.
  expanded         one ``ng=1 m=1`` card per drawn unit/finger plus the
                   rail-tied dummy columns -- the option-2 finger-expanded
                   reference, the lvs_reference.py expansion re-expressed
                   with sg13_lv_* calls. Model-computed AS/AD per card.
  extracted_nopar  layout/opamp_core/opamp_core_pex.spice with every
                   parasitic removed: the per-terminal ``<net>__tN`` star
                   nodes collapsed onto their hub net, every R and C card
                   dropped. Same devices, same extracted AS/AD/PS/PD.
  extracted        layout/opamp_core/opamp_core_pex.spice, byte-for-byte
                   (the extracted leg of the #236 run).

plus ``<v>_innac`` for v in lumped/drawn/extracted_nopar/extracted: the same
netlist with inn AC-grounded by a 1 F capacitor (see inn_acgnd()), a
diagnostic of the bench's loop-break method.

Device sizes, unit counts and finger counts come from generate.PAIRS /
generate.FOLDED (the tables the layout is drawn from), after
generate.verify_against_netlist() has checked them against the schematic.
Deterministic output; stdlib only.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "layout"))
sys.path.insert(0, str(REPO / "layout" / "opamp_core"))

from generate import (  # noqa: E402
    CAP_L_UM,
    CAP_W_UM,
    FOLDED,
    PAIRS,
    UNITS_PER_DEVICE,
    verify_against_netlist,
)

SCHEMATIC = REPO / "design" / "netlist" / "opamp_core.spice"
PEX = REPO / "layout" / "opamp_core" / "opamp_core_pex.spice"
#: lvs_reference.DUMMY_COLUMNS_PER_PAIR (one dummy column at each array end).
DUMMY_COLUMNS_PER_PAIR = 2
VARIANTS = ("lumped", "drawn", "expanded", "extracted_nopar", "extracted")
#: Variants also written with inn AC-grounded (see inn_acgnd()).
INNAC_BASES = ("lumped", "drawn", "extracted_nopar", "extracted")
INNAC_CARD = "Cprobe_inn_acgnd inn vss 1"


def _um(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".") + "u"


def _header(variant: str, what: str) -> list[str]:
    return [
        f"* issue-#237 device-representation probe, variant '{variant}'.",
        f"* {what}",
        "* Written by sim/fingering-probe/build_probe_netlists.py -- DO NOT EDIT.",
        "* Flat netlist (instantiated directly by the open-loop AC bench body).",
    ]


def _cap() -> str:
    # The schematic writes `XCc out d2`; keep its terminal order.
    return f"XCc out d2 cap_cmim w={_um(CAP_W_UM)} l={_um(CAP_L_UM)} m=1"


def drawn() -> str:
    lines = _header("drawn", "Nine instances, each with the drawn fingering (pairs m=units, folded ng=fingers).")
    for p in PAIRS:
        w_unit = p.w_total_um / UNITS_PER_DEVICE
        for inst, d, g in ((p.inst_a, p.drain_a, p.gate_a), (p.inst_b, p.drain_b, p.gate_b)):
            lines.append(
                f"{inst} {d} {g} {p.source_net} {p.body_net} {p.flavour} "
                f"w={_um(w_unit)} l={_um(p.l_um)} ng=1 m={UNITS_PER_DEVICE}"
            )
    for f in FOLDED:
        lines.append(
            f"{f.inst} {f.drain_net} {f.gate_net} {f.source_net} {f.body_net} {f.flavour} "
            f"w={_um(f.w_total_um)} l={_um(f.l_um)} ng={f.fingers} m=1"
        )
    lines.append(_cap())
    return "\n".join(lines) + "\n"


def expanded() -> str:
    lines = _header("expanded", "One ng=1 card per drawn unit/finger, plus the rail-tied dummy columns.")
    for p in PAIRS:
        w_unit = p.w_total_um / UNITS_PER_DEVICE
        geo = f"w={_um(w_unit)} l={_um(p.l_um)} ng=1 m=1"
        for inst, d, g in ((p.inst_a, p.drain_a, p.gate_a), (p.inst_b, p.drain_b, p.gate_b)):
            for u in range(UNITS_PER_DEVICE):
                lines.append(f"{inst}_u{u} {d} {g} {p.source_net} {p.body_net} {p.flavour} {geo}")
        for k in range(DUMMY_COLUMNS_PER_PAIR):
            b = p.body_net
            lines.append(f"XM{p.cell}_dummy{k} {b} {b} {b} {b} {p.flavour} {geo}")
    for f in FOLDED:
        geo = f"w={_um(f.finger_w_um)} l={_um(f.l_um)} ng=1 m=1"
        for k in range(f.fingers):
            lines.append(
                f"{f.inst}_f{k} {f.drain_net} {f.gate_net} {f.source_net} {f.body_net} {f.flavour} {geo}"
            )
    lines.append(_cap())
    return "\n".join(lines) + "\n"


_TERM = re.compile(r"^(\\?\$?\w+?)__t\d+$")


def extracted_nopar(text: str) -> str:
    """Strip every parasitic element; collapse star nodes onto their hub."""
    # Join continuation lines first so each card is one logical line.
    cards: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("+") and cards:
            cards[-1] += " " + raw[1:].strip()
        else:
            cards.append(raw)
    out = [
        "* issue-#237 device-representation probe, variant 'extracted_nopar'.",
        "* layout/opamp_core/opamp_core_pex.spice with every R and C card dropped",
        "* and every <net>__tN terminal node collapsed onto <net>.",
        "* Written by sim/fingering-probe/build_probe_netlists.py -- DO NOT EDIT.",
    ]
    dropped_r = dropped_c = devices = 0
    for card in cards:
        s = card.strip()
        if not s or s.startswith("*"):
            continue
        head = s[0].upper()
        if head == "R":
            dropped_r += 1
            continue
        if head == "C":
            dropped_c += 1
            continue
        if s.upper().startswith(".GLOBAL"):
            continue  # vsubs only carried the dropped substrate caps
        if head == "X":
            fields = s.split()
            fields = [(_TERM.match(f).group(1) if _TERM.match(f) else f) for f in fields]
            s = " ".join(fields)
            devices += 1
        out.append(s)
    if dropped_r == 0 or dropped_c == 0 or devices == 0:
        raise SystemExit(f"unexpected pex netlist shape: R={dropped_r} C={dropped_c} X={devices}")
    if any("__t" in line for line in out if not line.startswith("*")):
        raise SystemExit("a <net>__tN node survived the collapse")
    out.insert(4, f"* dropped {dropped_r} R and {dropped_c} C cards; kept {devices} device cards.")
    return "\n".join(out) + "\n"


def inn_acgnd(text: str, variant: str) -> str:
    """The same DUT with a 1 F capacitor from inn to vss (``<variant>_innac``).

    The committed open-loop bench breaks the loop with Lbreak = 1e18 H from
    inn to out and nothing else on inn, so at AC inn is a floating node held
    only by whatever capacitance the DUT puts on it: M1's gate capacitance in
    the schematic, plus every extracted parasitic touching inn in the pex
    netlist. This variant pins inn to AC ground (1 F; with the 1e18 H the
    L-C corner is ~1.6e-10 Hz, far below the 1 Hz sweep start; at DC the
    capacitor is open, so inn = out still sets the bias point). It is a
    diagnostic of the bench's loop-break method, not a bench change: if the
    parasitics step collapses here, the extracted leg's large AC deltas come
    from coupling into the floating inn node, not from the parasitics' effect
    on the amplifier itself.
    """
    lines = text.splitlines()
    note = f"* {variant}_innac: {variant} plus {INNAC_CARD!r} (inn AC-grounded; bench diagnostic)."
    for i, line in enumerate(lines):
        if line.strip().upper().startswith(".ENDS"):
            return "\n".join([note, *lines[:i], INNAC_CARD, *lines[i:]]) + "\n"
    for i, line in enumerate(lines):
        if line.strip().lower() == ".end":
            return "\n".join([note, *lines[:i], INNAC_CARD, *lines[i:]]) + "\n"
    raise SystemExit(f"{variant}: no .ENDS/.end to insert the inn AC ground before")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.exit(__doc__)
    drift = verify_against_netlist()
    if drift:
        sys.exit("generate.PAIRS/FOLDED disagree with the schematic:\n  " + "\n  ".join(drift))
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCHEMATIC, out / "lumped.spice")
    (out / "drawn.spice").write_text(drawn() + ".end\n", encoding="utf-8")
    (out / "expanded.spice").write_text(expanded() + ".end\n", encoding="utf-8")
    (out / "extracted_nopar.spice").write_text(
        extracted_nopar(PEX.read_text(encoding="utf-8")), encoding="utf-8"
    )
    shutil.copyfile(PEX, out / "extracted.spice")
    for v in INNAC_BASES:
        (out / f"{v}_innac.spice").write_text(
            inn_acgnd((out / f"{v}.spice").read_text(encoding="utf-8"), v), encoding="utf-8"
        )
    for v in VARIANTS + tuple(f"{b}_innac" for b in INNAC_BASES):
        print(out / f"{v}.spice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

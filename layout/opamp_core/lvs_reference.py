#!/usr/bin/env python3
"""Emit the plain-element LVS reference netlist ``klt lvs`` compares against.

``design/netlist/opamp_core.spice`` is a *simulation-form* netlist: nine
lumped instances (``XM1``..``XM7``, ``XMbias``, ``XCc``), each ``ng=1 m=1``.
The layout this repo commits is *not* lumped -- ``layout/opamp_core/
generate.py`` draws each matched pair as a ``B A A B`` interdigitated array
of four half-width unit devices plus two dummy columns, and each wide device
as a folded multi-finger MOS -- so extraction sees **38** devices where the
schematic names **9**. ``klt lvs`` offers exactly one built-in for that gap,
``options.combine_devices``, and on this block it does not work: KLayout's
own ``Netlist.combine_devices()`` trips an internal-consistency error on the
arrays' partial-match groups (matched-vs-dummy sharing three of four
terminals), measured and reported as klayout-tools issue #1185 -- the same
finding this repo's #57 recorded as its measured baseline, finding 3.

The route this script takes is the one klt itself established for folded
devices: its ``reference.form: "subckt-call"`` converter expands a
``nf>1`` MOS call into ``nf`` parallel unit-width plain-element ``M`` cards
(``netlist_normalize._expand_mos_fingers``, klayout-tools #1487 -- one card
per drawn finger, ``W = w_total / nf``, is "the same per-finger width a real
drawn multi-finger layout extracts as", that module's own words). This
script applies the identical expansion to **every** drawn split in this
block, sourced from the same tables ``generate.py`` draws from --
:data:`generate.PAIRS` (units per device, dummy columns and their body-rail
strapping), :data:`generate.FOLDED` (fingers), the Miller cap -- so the
reference can never describe an array topology the layout does not draw.
The schematic itself is never edited (``design/netlist/opamp_core.spice``
is a read-only reference): what this script writes is a *derived* artifact,
and it refuses to run if the tables have drifted from the schematic
(:func:`generate.verify_against_netlist` runs first).

The Miller capacitor gets a real ``C`` value, not the ``0`` placeholder the
subckt-call converter emits (klayout-tools #1907 -- that form excludes the
placeholder from the compare on both sides, so capacitance is paired on
topology alone; #57's finding 1). The value is the PDK's own ``cmim`` model
applied to the schematic's own plate geometry -- ``C = A*CJ + P*CJSW`` with
``CJ = 1.5e-15`` F/um^2 (``cornerCAP.lib``'s typical-corner ``cap_carea``)
and ``CJSW = 4.0e-17`` F/um (``cmim_core``'s ``CJSW = 40E-18``), both
transcribed in the curated sg13g2 deck's ``cap_cmim`` device entry -- the
same coefficients, and the same ``A``/``P``, the layout side extracts, so
agreement here is the model agreeing with itself on both sides of the same
geometry, not a number copied from the layout's report.

Card shapes mirror klt's own converter byte-for-byte (``M<n> d g s b nfet
L=..U W=..U`` / ``C<n> a b <farads> cap_cmim A=..P P=..U``, values rounded
to 6 decimals, no trailing zeros, ``U``/``P`` unit suffixes) -- see
``netlist_normalize._format_um``/``._format_um2``.

Usage (from the repo root)::

    python3 layout/opamp_core/lvs_reference.py                   # regenerate
    python3 layout/opamp_core/lvs_reference.py --check           # diff only
    python3 layout/opamp_core/lvs_reference.py --negative-control

Output is byte-for-byte deterministic (plain text, no timestamps), so
``--check`` fails only when the arrays, the netlist, or the cap model
coefficients actually changed.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYOUT_DIR = HERE.parent
REPO_ROOT = LAYOUT_DIR.parent
sys.path.insert(0, str(LAYOUT_DIR))
sys.path.insert(0, str(HERE))

import devices  # noqa: E402
from generate import (  # noqa: E402
    CAP_L_UM,
    CAP_W_UM,
    CAP_BOTTOM_NET,
    CAP_TOP_NET,
    FOLDED,
    PAIRS,
    UNITS_PER_DEVICE,
    verify_against_netlist,
)

REFERENCE_PATH = HERE / "opamp_core.lvs_reference.spice"
REQUEST_PATH = HERE / "lvs_request.json"

#: PDK ``cmim`` model coefficients, transcribed from the curated sg13g2
#: deck's ``cap_cmim`` ``CapacitorDevice`` (``klayout_tools.decks.sg13g2``),
#: which itself transcribes them from the PDK's own model libraries -- see
#: the module docstring for the file-by-file provenance. These are *model*
#: constants, not measurements of this block.
CAP_AREA_F_UM2 = 1.5e-15  # CJ = cap_carea (cornerCAP.lib, typical corner)
CAP_PERIM_F_UM = 4.0e-17  # CJSW = 40E-18 (cmim_core)

#: Dummy columns per matched-pair array: ``generate.generate_devices`` draws
#: ``rows=1, cols=2 * UNITS_PER_DEVICE, dummy=1`` -- one dummy column at
#: each end of the row, and :func:`generate.route_pair` straps every pad on
#: both of them (source, gate and drain) to the array's body rail. Sourced
#: here as a literal with this cross-reference rather than recomputed, so a
#: change to the array shape has to touch both files to stay honest.
DUMMY_COLUMNS_PER_PAIR = 2

_MOS_CLASS = {"sg13_lv_nmos": "nfet", "sg13_lv_pmos": "pfet"}


def _fmt(value_um: float) -> str:
    """Microns -> klt's own card format: 6 decimals, no trailing zeros, ``U``.

    Mirrors ``netlist_normalize._format_um`` (via ``pdk_models``) exactly,
    so a future side-by-side of this file's cards against a real
    ``subckt-call`` conversion cannot differ on formatting.
    """
    text = f"{value_um:.6f}".rstrip("0").rstrip(".")
    return (text or "0") + "U"


def _fmt_um2(value_um2: float) -> str:
    """Square microns -> the same, with the ``P`` (1e-12 == um^2) suffix.

    Mirrors ``netlist_normalize._format_um2``: a value already in um^2 needs
    no numeric conversion, only the pico suffix.
    """
    text = f"{value_um2:.6f}".rstrip("0").rstrip(".")
    return (text or "0") + "P"


def _inst_base(inst: str) -> str:
    """``XM5`` -> ``M5``: drop the subckt-call ``X``, keep the M letter."""
    rest = inst[1:]
    return rest if rest[:1].upper() == "M" else "M" + rest


def build_reference() -> str:
    """The plain-element reference, as text. Raises if tables drift."""
    drift = verify_against_netlist()
    if drift:
        raise SystemExit(
            "the layout device tables disagree with "
            "design/netlist/opamp_core.spice:\n  " + "\n  ".join(drift)
        )

    lines = [
        "* Auto-generated by layout/opamp_core/lvs_reference.py -- DO NOT EDIT.",
        "* Source of device sizes/nets: design/netlist/opamp_core.spice (via",
        "* generate.PAIRS/generate.FOLDED, cross-checked at generation time).",
        "* Source of the expansion (38 drawn units vs 9 schematic instances):",
        "* generate.py's interdigitated matched arrays (unit + dummy columns)",
        "* and folded multi-finger devices -- see lvs_reference.py's docstring",
        "* for why options.combine_devices cannot close that gap here.",
        "* Card shapes mirror klt's subckt-call converter (netlist_normalize).",
    ]
    for pair in PAIRS:
        cls = _MOS_CLASS[pair.flavour]
        w_unit = pair.w_total_um / UNITS_PER_DEVICE
        geometry = f"L={_fmt(pair.l_um)} W={_fmt(w_unit)}"
        for inst, drain, gate in (
            (pair.inst_a, pair.drain_a, pair.gate_a),
            (pair.inst_b, pair.drain_b, pair.gate_b),
        ):
            for unit in range(UNITS_PER_DEVICE):
                lines.append(
                    f"{_inst_base(inst)}_u{unit} {drain} {gate} "
                    f"{pair.source_net} {pair.body_net} {cls} {geometry}"
                )
        for dummy in range(DUMMY_COLUMNS_PER_PAIR):
            # route_pair straps every pad of both dummy columns -- source,
            # gate and drain -- to the array's body rail, so the dummy is a
            # real device whose four terminals all sit on that rail.
            lines.append(
                f"M{pair.cell}_dummy{dummy} {pair.body_net} {pair.body_net} "
                f"{pair.body_net} {pair.body_net} {cls} {geometry}"
            )
    for dev in FOLDED:
        cls = _MOS_CLASS[dev.flavour]
        w_finger = dev.w_total_um / dev.fingers
        geometry = f"L={_fmt(dev.l_um)} W={_fmt(w_finger)}"
        for finger in range(dev.fingers):
            lines.append(
                f"{_inst_base(dev.inst)}_f{finger} {dev.drain_net} "
                f"{dev.gate_net} {dev.source_net} {dev.body_net} {cls} {geometry}"
            )
    area = CAP_W_UM * CAP_L_UM
    perimeter = 2.0 * (CAP_W_UM + CAP_L_UM)
    cap_c = area * CAP_AREA_F_UM2 + perimeter * CAP_PERIM_F_UM
    lines.append(
        f"Cc {CAP_BOTTOM_NET} {CAP_TOP_NET} {cap_c:.5e} "
        f"cap_cmim A={_fmt_um2(area)} P={_fmt(perimeter)}"
    )
    lines.append(".end")
    return "\n".join(lines) + "\n"


def negative_control(klt: str = "klt") -> int:
    """Prove the committed compare can *fail*, writing nothing to the repo.

    Perturbs one net in a scratch copy of this reference (the tail pair's
    shared source: ``vss`` -> ``vdd`` on XM5's units only), re-runs
    ``klt lvs`` against it in a temp dir, and asserts the verdict flips to
    ``mismatch`` naming real unmatched devices. An LVS whose reference
    cannot fail proves nothing -- the same discipline ``generate.py
    --negative-control`` applies to the connectivity self-check.
    """
    broken = build_reference().replace(
        f"{_inst_base(PAIRS[0].inst_a)}_u0 {PAIRS[0].drain_a} "
        f"{PAIRS[0].gate_a} {PAIRS[0].source_net} {PAIRS[0].body_net}",
        f"{_inst_base(PAIRS[0].inst_a)}_u0 {PAIRS[0].drain_a} "
        f"{PAIRS[0].gate_a} {'vdd'} {PAIRS[0].body_net}",
        1,
    )
    with tempfile.TemporaryDirectory(prefix="sg13g2-opamp-lvs-negctl-") as tmp:
        request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
        # The committed request's paths are relative to the request file's
        # own directory, so the scratch copy needs the committed GDS beside
        # it -- the compare must run against the real layout, with only the
        # reference perturbed.
        shutil.copy2(
            HERE / request["layout"]["file"], Path(tmp) / request["layout"]["file"]
        )
        ref = Path(tmp) / "broken_reference.spice"
        ref.write_text(broken, encoding="utf-8")
        request["reference"]["netlist"] = ref.name
        req = Path(tmp) / "request.json"
        req.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        proc = subprocess.run(
            [devices.require_klt(klt), "lvs", str(req), "--format", "json"],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=False,
        )
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            print(
                f"FAIL: klt lvs produced no JSON envelope (exit {proc.returncode}):"
                f"\n{proc.stdout[:500]}\n{proc.stderr[:500]}",
                file=sys.stderr,
            )
            return 1
        status = report.get("status")
        unmatched = sum(
            1
            for entry in report.get("mismatches", [])
            if entry.get("category") == "device.unmatched"
        )
        print(
            f"negative control: perturbed reference -> status={status} "
            f"mismatch_count={report.get('mismatch_count')} "
            f"device.unmatched entries={unmatched}"
        )
        if status != "mismatch":
            print(
                "FAIL: the committed LVS compare passed a deliberately broken "
                "reference, so a passing verdict from it means nothing",
                file=sys.stderr,
            )
            return 1
        print("OK: the committed LVS compare detects a perturbed reference net")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate to a temp file and diff against the committed "
        "reference instead of overwriting it (exit 1 on drift)",
    )
    ap.add_argument(
        "--negative-control",
        action="store_true",
        help="prove the LVS compare detects a deliberately perturbed "
        "reference net (writes nothing to the repo)",
    )
    ap.add_argument("--klt", default="klt", help="klt executable (default: klt)")
    args = ap.parse_args(argv)

    if args.negative_control:
        return negative_control(args.klt)

    text = build_reference()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="sg13g2-opamp-lvsref-") as tmp:
            out = Path(tmp) / REFERENCE_PATH.name
            out.write_text(text, encoding="utf-8")
            if not filecmp.cmp(out, REFERENCE_PATH, shallow=False):
                print(
                    f"FAIL: regenerated reference differs from committed "
                    f"{REFERENCE_PATH.relative_to(REPO_ROOT)}",
                    file=sys.stderr,
                )
                return 1
        print("OK: regenerated reference matches the committed one")
        return 0

    REFERENCE_PATH.write_text(text, encoding="utf-8")
    n_devices = (
        sum(UNITS_PER_DEVICE * 2 + DUMMY_COLUMNS_PER_PAIR for _pair in PAIRS)
        + sum(dev.fingers for dev in FOLDED)
        + 1
    )
    print(f"wrote {REFERENCE_PATH.relative_to(REPO_ROOT)} ({n_devices} device cards)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Smoke fixture for this repo's SG13G2 layout scaffold.

Draws one instance of **every distinct (device flavour, W, L) shape class**
``design/netlist/opamp_core.spice`` asks for -- all nine instances collapse to
six shapes -- plus one of each routing/tap/via primitive the scaffold
provides, and writes a single GDS. That stream is then checked with
``klt drc --deck sg13g2``; both the GDS and the JSON report are committed.

**This is scaffolding proof, not a T1 claim.** It proves the scaffold draws
legal geometry for this block's device shapes and that the DRC flow runs. It
is *not* the op-amp layout (issue #45), it is not LVS'd, it is not extracted,
and nothing under ``signoff/`` cites it. The fixture deliberately does not
connect the devices into the schematic's topology: a partially-wired op-amp
would invite exactly the misreading this paragraph forbids.

Determinism: every drawn coordinate is a pure function of the constants in
this file plus the installed ``klt``/curated-deck revision. ``klt gen``'s
intermediate streams go to a scratch directory and are re-imported flattened,
so their own GDS timestamps never reach the committed stream, and
``Builder.write`` disables timestamp records. Two runs on the same ``klt``
revision produce byte-identical output; see ``layout/README.md``.

Layout follows the in-fleet per-artifact-group convention from
``2AMLogic/sg13g2-bandgap``: the shared drawing modules sit at ``layout/``
(``builder.py`` / ``devices.py`` / ``sg13g2_layers.py``, the counterparts of
that repo's ``_klayout_builder_base.py`` + ``common.py``), and each group of
drawn artifacts gets its own directory holding a ``generate.py``, its ``.gds``
and its ``drc_report.json``. The op-amp layout itself (#45) belongs in a
sibling ``layout/opamp_core/``, not here.

Usage (from the repo root)::

    python3 layout/scaffold_smoke/generate.py    # regenerate GDS + DRC report
    python3 layout/scaffold_smoke/generate.py --check
                                                 # regenerate to a temp dir and
                                                 # diff against the committed
                                                 # artifacts (exit 1 on drift)
    python3 layout/scaffold_smoke/generate.py --negative-control
                                                 # prove `klt drc --deck sg13g2`
                                                 # actually flags violations
"""

from __future__ import annotations

import argparse
import filecmp
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYOUT_DIR = HERE.parent
REPO_ROOT = LAYOUT_DIR.parent
sys.path.insert(0, str(LAYOUT_DIR))

import devices
from builder import Builder
from sg13g2_layers import (
    DECK_MIN_UM,
    L_METAL1,
    L_METAL2,
    L_METAL3,
    L_METAL5,
    L_TOPMETAL1,
    verify_deck_minima,
)

TOP_CELL = "sg13g2_opamp_scaffold_smoke"
GDS_PATH = HERE / f"{TOP_CELL}.gds"
DRC_REPORT_PATH = HERE / "drc_report.json"

#: Every distinct ``(flavour, W, L)`` in ``design/netlist/opamp_core.spice``,
#: read from that file on ``origin/main`` and listed in netlist order. Nine
#: instances collapse to six shapes: ``XM1``/``XM2`` share one, as do
#: ``XM3``/``XM4`` and ``XM5``/``XMbias``. Each entry's comment names the
#: instances it stands in for and their role.
DEVICE_SHAPES: tuple[tuple[str, str, float, float, str], ...] = (
    # cell name        flavour          W       L     instances covered
    ("m_in_pair", "sg13_lv_nmos", 3.2, 0.13, "XM1/XM2 input pair"),
    ("m_mirror", "sg13_lv_pmos", 1.04, 0.52, "XM3/XM4 mirror load"),
    ("m_tail", "sg13_lv_nmos", 2.2, 0.52, "XM5/XMbias tail + bias diode"),
    ("m_gain", "sg13_lv_pmos", 33.0, 1.04, "XM6 output gain device"),
    ("m_out_tail", "sg13_lv_nmos", 11.9, 0.52, "XM7 output tail"),
    ("c_miller", "cap_cmim", 25.7, 25.7, "XCc Miller cap"),
)

#: Gap between adjacent placed devices, in microns. Well clear of every
#: same-layer spacing minimum the curated deck carries (the largest is
#: ``topmetal1.space.1`` at 1.64 um) and of IHP's own ``NW.b1`` (1.80 um,
#: minimum PWell width between different-net NWell regions) -- which the
#: curated deck does *not* carry, so clearing it here is a deliberate choice
#: rather than something the committed DRC report checks.
DEVICE_GAP_UM = 3.0

#: Vertical clearance between the device row and the tap/routing rows below
#: it, in microns. Same reasoning as :data:`DEVICE_GAP_UM`.
ROW_GAP_UM = 3.0


def _tap_row(b: Builder, x_start: float, y: float) -> float:
    """One substrate tie and one well tie, side by side. Returns the next free x."""
    x = x_start
    for kind in ("psub", "nwell"):
        # 1 x 4 contact rows: enough cuts to exercise cut_array's pitch
        # arithmetic (cont.space.1) rather than just its single-cut case.
        activ = b.tap(kind, x, y, rows=1, cols=4)
        b.label(f"tap_{kind}", (activ[0] + activ[2]) / 2.0, activ[3] + 0.3)
        x = activ[2] + DEVICE_GAP_UM
    return x


def _routing_row(b: Builder, x_start: float, y: float) -> float:
    """Metal1/Metal2 bars joined by a Via1, and a Metal5 -> TopMetal1 via.

    Exercises ``route_h``/``route_v``, ``via`` and ``via_stack``, and pulls the
    ``via1.*``/``metal2.*`` rules into the DRC report's ``rules_checked`` --
    without them the report would check only 11 of the deck's 43 rules.
    """
    # Metal1 bar, Metal2 bar above it, joined by a 2x2 Via1 at the overlap.
    m1_x1 = x_start + 6.0
    b.route_h(L_METAL1, y, x_start, m1_x1)
    b.route_v(
        L_METAL2, m1_x1 - 0.5, y, y + 6.0, width=DECK_MIN_UM["metal2.width.1"] * 2
    )
    b.via(L_METAL1, L_METAL2, m1_x1 - 0.5, y, rows=2, cols=2)
    b.label("m1_m2_via", m1_x1 - 0.5, y - 1.0)

    # Metal2 -> Metal3, so via2/metal3 are checked too.
    x = m1_x1 + DEVICE_GAP_UM
    b.route_h(L_METAL3, y, x, x + 4.0)
    b.route_h(L_METAL2, y, x, x + 4.0)
    b.via(L_METAL2, L_METAL3, x + 2.0, y, rows=2, cols=2)

    # Metal5 -> TopMetal1: the asymmetric-enclosure case landing_pad exists
    # for (metal5.enclosing.topvia1.1 = 0.10 um vs
    # topmetal1.enclosing.topvia1.1 = 0.42 um, topmetal1.width.1 = 1.64 um).
    x = x + 4.0 + DEVICE_GAP_UM + DECK_MIN_UM["topmetal1.space.1"]
    b.route_h(L_METAL5, y, x, x + 4.0)
    pad = b.via(L_METAL5, L_TOPMETAL1, x + 2.0, y)
    b.label("m5_tm1_via", (pad[0] + pad[2]) / 2.0, pad[3] + 0.5)
    return max(m1_x1, x + 4.0)


def build(scratch: Path, klt: str = "klt") -> tuple[Builder, list[dict]]:
    """Draw the fixture. Returns the builder and a per-device provenance list."""
    b = Builder(TOP_CELL)
    placed_meta: list[dict] = []

    x = 0.0
    device_row_y = 0.0
    top_of_row = 0.0
    for cell_name, flavour, w_um, l_um, covers in DEVICE_SHAPES:
        if flavour == "sg13_lv_nmos":
            dev = devices.lv_nmos(w_um, l_um, cell_name, scratch, klt=klt)
        elif flavour == "sg13_lv_pmos":
            dev = devices.lv_pmos(w_um, l_um, cell_name, scratch, klt=klt)
        elif flavour == "cap_cmim":
            dev = devices.cmim_cap(w_um, l_um, cell_name, scratch, klt=klt)
        else:  # pragma: no cover - DEVICE_SHAPES is a closed set
            raise ValueError(f"unknown device flavour {flavour!r}")

        placed = b.place_stream(dev.gds_path, cell_name, x, device_row_y)
        b.label(f"{cell_name} ({flavour})", placed.x0, placed.y1 + 0.5)

        patched = None
        if dev.kind == "cap_cmim":
            patched = _patch_mim_bottom_plate(b, placed)

        placed_meta.append(
            {
                "cell": cell_name,
                "device": dev.kind,
                "covers": covers,
                "generator": dev.generator,
                "params": dev.params,
                "placed_bbox_um": [placed.x0, placed.y0, placed.x1, placed.y1],
                "mim_c_patch_um": patched,
            }
        )
        x = placed.x1 + DEVICE_GAP_UM
        top_of_row = max(top_of_row, placed.y1)

    # Tap and routing rows below the device row.
    tap_y = -(ROW_GAP_UM + 1.0)
    _tap_row(b, 0.0, tap_y)
    routing_y = tap_y - ROW_GAP_UM - DECK_MIN_UM["topmetal1.space.1"] - 2.0
    _routing_row(b, 0.0, routing_y)

    bx0, by0, bx1, by1 = b.bbox_um()
    b.pr_boundary(bx0 - 1.0, by0 - 1.0, bx1 + 1.0, by1 + 1.0)
    return b, placed_meta


def _patch_mim_bottom_plate(b: Builder, placed) -> dict | None:
    """Widen the placed MIM cap's ``Metal5`` bottom plate to clear IHP's MIM.c.

    Thin alias for :func:`devices.patch_mim_bottom_plate`, which is where the
    rule, the shortfall arithmetic and the no-op-on-a-fixed-generator
    behaviour live. The helper moved there when ``layout/opamp_core`` (issue
    #45) needed the same patch: a foundry rule no ``klt drc`` run in this repo
    checks must have exactly one implementation, or the two copies drift and
    only one of the two committed streams clears MIM.c.
    """
    return devices.patch_mim_bottom_plate(b, placed)


def run_drc(gds: Path, report: Path, klt: str = "klt") -> dict:
    """``klt drc --deck sg13g2 --format json`` over ``gds``, written to ``report``.

    The report's ``file`` field is rewritten to the committed GDS's
    repo-relative path -- ``klt`` records the path it was handed, and embedding
    either this host's absolute paths or (under ``--check``) a temp directory
    would make the byte-for-byte regeneration criterion unachievable. Every
    other field, including ``provenance.input.content_hash`` (the stream's own
    sha256), is left exactly as ``klt`` emitted it.
    """
    argv = [
        devices.require_klt(klt),
        "drc",
        str(gds),
        "--deck",
        "sg13g2",
        "--format",
        "json",
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"`klt drc` did not emit JSON (exit {proc.returncode}): {exc}\n"
            f"{proc.stderr.strip()}\n{proc.stdout[:2000]}"
        ) from exc
    data["file"] = str(GDS_PATH.relative_to(REPO_ROOT))
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    return data


#: Deliberately illegal geometry for the negative control, drawn with
#: ``klt draw`` (no PDK awareness, no rule checking -- see ``klt draw --help``:
#: "it will happily emit rule-violating geometry"). Each shape breaks exactly
#: one transcribed rule, so the expected violation set is an exact match, not
#: "at least one violation".
NEGATIVE_CONTROL_SHAPES = {
    "shapes": [
        # 0.10 um Metal1 line: metal1.width.1 is 0.16 um (IHP M1.a).
        {"layer": [8, 0], "rect_um": [0, 0, 5.0, 0.10]},
        # ...with a 0.10 um gap to the next Metal1 line: metal1.space.1 is
        # 0.18 um (IHP M1.b). The second line is itself 0.20 um, i.e. legal
        # width, so the space violation is attributable on its own.
        {"layer": [8, 0], "rect_um": [0, 0.20, 5.0, 0.40]},
        # 0.10 um Activ: activ.width.1 is 0.15 um (IHP Act.a).
        {"layer": [1, 0], "rect_um": [0, -2.0, 5.0, -1.90]},
    ]
}

#: What :data:`NEGATIVE_CONTROL_SHAPES` must provoke, exactly.
NEGATIVE_CONTROL_EXPECTED = {
    "activ.width.1": 1,
    "metal1.space.1": 1,
    "metal1.width.1": 1,
}


def negative_control(klt: str = "klt") -> int:
    """Prove the DRC flow can *fail*, into a temp dir, committing nothing.

    A DRC step that has never returned a violation is not evidence of
    anything. This draws three known-illegal shapes, runs the same
    ``klt drc --deck sg13g2`` invocation the smoke fixture uses, and asserts
    the verdict is ``violations`` with exactly the expected rule counts.

    Nothing is committed: the stream and its report live in a temp directory
    that is deleted on exit, so the deterministic-regeneration criterion for
    the committed artifacts is untouched.
    """
    exe = devices.require_klt(klt)
    with tempfile.TemporaryDirectory(prefix="sg13g2-layout-negctl-") as tmp:
        bad_gds = Path(tmp) / "negative_control.gds"
        draw = subprocess.run(
            [
                exe,
                "draw",
                "--params",
                json.dumps(NEGATIVE_CONTROL_SHAPES),
                "--cell-name",
                "negative_control",
                "-o",
                str(bad_gds),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if draw.returncode != 0:
            print(f"FAIL: `klt draw` failed: {draw.stderr.strip()}", file=sys.stderr)
            return 1
        drc = json.loads(
            subprocess.run(
                [exe, "drc", str(bad_gds), "--deck", "sg13g2", "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
        )
    print(
        f"negative control: status={drc['status']} "
        f"violations={drc['violation_count']} rule_counts={drc['rule_counts']}"
    )
    if drc["status"] == "clean":
        print(
            "FAIL: the DRC flow reported known-illegal geometry as clean, so a "
            "'clean' verdict from it means nothing",
            file=sys.stderr,
        )
        return 1
    if drc["rule_counts"] != NEGATIVE_CONTROL_EXPECTED:
        print(
            f"FAIL: expected rule_counts {NEGATIVE_CONTROL_EXPECTED}, "
            f"got {drc['rule_counts']}",
            file=sys.stderr,
        )
        return 1
    print("OK: the DRC flow flags violations, and attributes them correctly")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temp dir and diff against the committed "
        "artifacts instead of overwriting them (exit 1 on any drift)",
    )
    ap.add_argument(
        "--negative-control",
        action="store_true",
        help="instead of regenerating, prove `klt drc --deck sg13g2` flags "
        "known-illegal geometry (nothing is written to the repo)",
    )
    ap.add_argument("--klt", default="klt", help="klt executable (default: klt)")
    args = ap.parse_args(argv)

    if args.negative_control:
        return negative_control(args.klt)

    deck = verify_deck_minima(args.klt)
    print(
        f"curated sg13g2 deck: {deck['rule_count']} rules, "
        f"{deck['content_hash']}  (DECK_MIN_UM verified in step)"
    )

    with tempfile.TemporaryDirectory(prefix="sg13g2-layout-smoke-") as tmp:
        scratch = Path(tmp)
        b, meta = build(scratch / "gen", klt=args.klt)

        gds_out = (scratch / GDS_PATH.name) if args.check else GDS_PATH
        report_out = (scratch / DRC_REPORT_PATH.name) if args.check else DRC_REPORT_PATH
        gds_out.parent.mkdir(parents=True, exist_ok=True)
        b.write(gds_out)
        print(f"wrote {gds_out}  bbox_um={tuple(round(v, 3) for v in b.bbox_um())}")

        drc = run_drc(gds_out, report_out, klt=args.klt)
        cov = drc["coverage"]
        print(
            f"klt drc --deck sg13g2: status={drc['status']} "
            f"violations={drc['violation_count']} "
            f"rules_checked={len(cov['rules_checked'])} "
            f"rules_skipped={len(cov['rules_skipped'])} "
            f"layers_in_stream_without_rules={cov['layers_in_stream_without_rules']}"
        )
        for entry in meta:
            patch = entry["mim_c_patch_um"]
            note = "" if patch is None else f"  [MIM.c patched: {patch}]"
            print(
                f"  {entry['cell']:<12} {entry['device']:<14} {entry['covers']}{note}"
            )

        if drc["status"] != "clean":
            print("FAIL: DRC is not clean", file=sys.stderr)
            for v in drc["violations"][:20]:
                print(f"  {v}", file=sys.stderr)
            return 1

        if args.check:
            ok = True
            if not filecmp.cmp(gds_out, GDS_PATH, shallow=False):
                print(
                    f"FAIL: regenerated GDS differs from committed {GDS_PATH}",
                    file=sys.stderr,
                )
                ok = False
            committed = json.loads(DRC_REPORT_PATH.read_text())
            fresh = json.loads(report_out.read_text())
            for key in ("status", "violation_count", "coverage"):
                if committed.get(key) != fresh.get(key):
                    print(
                        f"FAIL: committed DRC report's {key!r} differs from a "
                        "fresh run",
                        file=sys.stderr,
                    )
                    ok = False
            if not ok:
                return 1
            print("OK: regenerated artifacts match the committed ones")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

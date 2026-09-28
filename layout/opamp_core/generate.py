#!/usr/bin/env python3
"""Draw and route ``opamp_core``: the block's first-cut placed-and-routed GDS.

Reads ``design/netlist/opamp_core.spice`` -- nine instances, ports ``vdd vss
inn inp out ibias`` -- and emits one committed stream plus its
``klt drc --deck sg13g2`` report. Unlike ``layout/scaffold_smoke`` (which
proves the scaffold draws legal *shapes* and deliberately leaves the devices
unwired), this generator places every device in the netlist's topology and
wires them together.

**What this is evidence for, and what it is not.** It is T1 item 2 (a
committed GDS with documented provenance -- see "Determinism" in
``layout/README.md``: CI verifies the committed hash, not a fresh ``--check``
regeneration, so this block claims item 2's documented-provenance
alternative rather than a CI-enforced "reproducibly generated" one; see
`#50 <https://github.com/2AMLogic/sg13g2-opamp/issues/50>`_) and item 3 (a
committed DRC report with its coverage disclosed). It is **not** LVS: nothing
here compares the drawn connectivity against the SPICE netlist with an LVS
engine, and no parasitics are extracted. See ``layout/README.md`` for the full
scope and the
coverage disclosure, and note in particular that ``klt drc --deck sg13g2``
runs klayout-tools' own curated 43-rule starter deck, **not** IHP's foundry
signoff deck.

The connectivity claims this file makes are machine-checked here rather than
asserted, in two steps that are only worth something together:

* :func:`verify_against_netlist` parses
  ``design/netlist/opamp_core.spice`` and asserts that the device table below
  -- every instance name, model, W, L and drain/gate/source/bulk net -- is
  what the file actually says, so the layout stays answerable to the netlist
  rather than to a transcription of it.
* :func:`check_connectivity` re-extracts the drawn interconnect with
  KLayout's own ``LayoutToNetlist`` and asserts that every device terminal
  lands on the net that table puts it on, that no two nets share an extracted
  net, and that the stream contains no floating conductor at all.
* :func:`assert_common_centroid` asserts the one *matching* claim that rests
  on ``klt gen mos_array``'s own unit numbering: that each matched array's
  two devices share a centroid in x to within one database unit. A future
  ``klt`` that renumbered the units would otherwise break the ``B A A B``
  order silently, with every other check in this file still passing.

Together they catch an open, a short, an untied dummy and a drifted netlist
-- none of which DRC can see. They are still **not LVS**: no device is
*recognised* from the geometry, extraction stops at ``Metal1``, and no
parasitics are computed. ``klt lvs`` is T1 item 4 and out of scope here.

Usage (from the repo root)::

    python3 layout/opamp_core/generate.py                    # regenerate
    python3 layout/opamp_core/generate.py --check            # verify only
    python3 layout/opamp_core/generate.py --devices          # per-device DRC
    python3 layout/opamp_core/generate.py --negative-control # break it on purpose
"""

from __future__ import annotations

import argparse
import filecmp
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import klayout.db as kdb

HERE = Path(__file__).resolve().parent
LAYOUT_DIR = HERE.parent
REPO_ROOT = LAYOUT_DIR.parent
sys.path.insert(0, str(LAYOUT_DIR))
sys.path.insert(0, str(HERE))

import devices
import floorplan as fp
from builder import DBU_UM, Builder, Placed
from sg13g2_layers import (
    L_METAL1,
    L_METAL2,
    L_METAL3,
    L_METAL4,
    L_METAL5,
    L_TOPMETAL1,
    L_TOPVIA1,
    L_VIA1,
    L_VIA2,
    L_VIA3,
    L_VIA4,
    verify_deck_minima,
)

TOP_CELL = "opamp_core"
GDS_PATH = HERE / f"{TOP_CELL}.gds"
DRC_REPORT_PATH = HERE / "drc_report.json"
NETLIST_PATH = REPO_ROOT / "design" / "netlist" / "opamp_core.spice"


# --------------------------------------------------------------------------- #
# What the netlist asks for
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MatchedPair:
    """Two matched devices drawn as one interdigitated one-row array.

    Each netlist device is split into :data:`UNITS_PER_DEVICE` half-width
    units, and the four units are placed ``B A A B`` left-to-right with a
    dummy column at each end. ``mos_array``'s ``topology="common_centroid"``
    numbering is what produces that order: with ``rows=1, cols=4`` it places
    ``U2 U0 U1 U3``, so taking device A = ``{U0, U1}`` and device B =
    ``{U2, U3}`` puts both devices' centroids on the same x (the array
    centre) -- the property that cancels a first-order linear gradient in
    oxide thickness, implant dose or stress across the pair.

    See ``layout/README.md`` for why a one-row interdigitation was chosen over
    a two-row cross-quad, and what that choice costs.
    """

    cell: str
    flavour: str
    w_total_um: float
    """Per-device width from the netlist. Each unit draws half of it."""
    l_um: float
    inst_a: str
    inst_b: str
    source_net: str
    drain_a: str
    drain_b: str
    gate_a: str
    gate_b: str
    body_net: str


@dataclass(frozen=True)
class FoldedDevice:
    """One wide netlist device drawn as a folded multi-finger MOS.

    ``mos_array``'s ``finger_topology="parallel"`` straps alternating S/D
    segments and ties every gate, i.e. it draws exactly one transistor of
    width ``fingers * w_um``; the folding is a layout choice about aspect
    ratio and gate resistance, not a change of device.
    """

    cell: str
    flavour: str
    w_total_um: float
    l_um: float
    fingers: int
    inst: str
    source_net: str
    drain_net: str
    gate_net: str
    body_net: str

    @property
    def finger_w_um(self) -> float:
        return self.w_total_um / self.fingers


#: Units each matched device is split into. Two is the smallest split that
#: admits a common centroid; more units would improve the match further but
#: each extra column adds a diffusion edge and 1.5-1.8 um of pitch, and the
#: input pair's units are already only 1.6 um wide.
UNITS_PER_DEVICE = 2

PAIRS: tuple[MatchedPair, ...] = (
    MatchedPair(
        cell="tail_pair",
        flavour="sg13_lv_nmos",
        w_total_um=2.2,
        l_um=0.52,
        inst_a="XM5",
        inst_b="XMbias",
        source_net="vss",
        drain_a="tail",
        drain_b="ibias",
        gate_a="ibias",
        gate_b="ibias",
        body_net="vss",
    ),
    MatchedPair(
        cell="input_pair",
        flavour="sg13_lv_nmos",
        w_total_um=3.2,
        l_um=0.13,
        inst_a="XM1",
        inst_b="XM2",
        source_net="tail",
        drain_a="d1",
        drain_b="d2",
        gate_a="inn",
        gate_b="inp",
        body_net="vss",
    ),
    MatchedPair(
        cell="mirror",
        flavour="sg13_lv_pmos",
        w_total_um=1.04,
        l_um=0.52,
        inst_a="XM3",
        inst_b="XM4",
        source_net="vdd",
        drain_a="d1",
        drain_b="d2",
        # XM3 is diode-connected: both gates sit on d1, XM3's own drain.
        gate_a="d1",
        gate_b="d1",
        body_net="vdd",
    ),
)

FOLDED: tuple[FoldedDevice, ...] = (
    FoldedDevice(
        cell="out_tail",
        flavour="sg13_lv_nmos",
        w_total_um=11.9,
        l_um=0.52,
        fingers=7,  # 11.9 / 7 = 1.70 um per finger, exactly
        inst="XM7",
        source_net="vss",
        drain_net="out",
        gate_net="ibias",
        body_net="vss",
    ),
    FoldedDevice(
        cell="gain",
        flavour="sg13_lv_pmos",
        w_total_um=33.0,
        l_um=1.04,
        fingers=12,  # 33.0 / 12 = 2.75 um per finger, exactly
        inst="XM6",
        source_net="vdd",
        drain_net="out",
        gate_net="d2",
        body_net="vdd",
    ),
)

#: ``XCc``, the Miller capacitor, from the netlist: ``w=25.7u l=25.7u``.
CAP_W_UM = 25.7
CAP_L_UM = 25.7

#: Which plate carries which net. The netlist writes ``XCc out d2``; the
#: layout decides which terminal is which plate, and it is not a free choice:
#: the ``Metal5`` bottom plate is a 26.7 um square sitting over the
#: substrate, so it carries far more parasitic capacitance to ground than the
#: ``MIM`` top plate above it. That parasitic is put on ``out`` -- stage 2's
#: low-impedance output -- rather than on ``d2``, the high-impedance stage-1
#: output and XM6's gate, where an extra ~0.7 pF-scale shunt would move the
#: dominant pole and the compensation with it.
CAP_BOTTOM_NET = "out"
CAP_TOP_NET = "d2"

#: The six ports ``design/netlist/opamp_core.spice`` declares (``*.iopin``).
#: Every one must appear as a label in the committed stream.
PORT_NETS = ("vdd", "vss", "inn", "inp", "out", "ibias")


# --------------------------------------------------------------------------- #
# The netlist is read, not paraphrased
# --------------------------------------------------------------------------- #
def parse_netlist(path: Path = NETLIST_PATH) -> dict[str, dict]:
    """Parse the subcircuit instances out of ``opamp_core.spice``.

    Deliberately minimal: one ``X`` card per line, nodes between the instance
    name and the model name, ``key=value`` parameters after it. That is the
    whole of what xschem writes for this block, and a parser that accepts
    less than SPICE is one that cannot silently mis-read the file it exists
    to check.
    """
    instances: dict[str, dict] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or not line[0] in "Xx":
            continue
        fields = line.split()
        params: dict[str, str] = {}
        body: list[str] = []
        for field_ in fields[1:]:
            if "=" in field_:
                key, _, value = field_.partition("=")
                params[key] = value
            else:
                body.append(field_)
        if not body:
            continue
        instances[fields[0]] = {
            "nodes": body[:-1],
            "model": body[-1],
            "params": params,
        }
    return instances


def _microns(value: str) -> float:
    return float(value[:-1]) if value.endswith("u") else float(value)


def verify_against_netlist(path: Path = NETLIST_PATH) -> list[str]:
    """Check this module's device table against the netlist file itself.

    :func:`check_connectivity` proves the drawn metal matches the net
    assignments declared in :data:`PAIRS` and :data:`FOLDED`. This proves
    those declarations match ``design/netlist/opamp_core.spice`` -- so
    together the two make the layout answerable to the netlist file, not to a
    transcription of it that could drift the next time the schematic is
    re-netlisted.

    It is still not LVS: no device is *recognised* from the geometry, and
    nothing checks that a drawn transistor is the transistor the model card
    names. That is ``klt lvs``, T1 item 4.
    """
    problems: list[str] = []
    instances = parse_netlist(path)

    expected: dict[str, tuple[str, float, float, tuple[str, ...]]] = {}
    for pair in PAIRS:
        expected[pair.inst_a] = (
            pair.flavour,
            pair.w_total_um,
            pair.l_um,
            (pair.drain_a, pair.gate_a, pair.source_net, pair.body_net),
        )
        expected[pair.inst_b] = (
            pair.flavour,
            pair.w_total_um,
            pair.l_um,
            (pair.drain_b, pair.gate_b, pair.source_net, pair.body_net),
        )
    for dev in FOLDED:
        expected[dev.inst] = (
            dev.flavour,
            dev.w_total_um,
            dev.l_um,
            (dev.drain_net, dev.gate_net, dev.source_net, dev.body_net),
        )

    missing = sorted(set(instances) - set(expected) - {"XCc"})
    extra = sorted(set(expected) - set(instances))
    if missing:
        problems.append(f"netlist has instances this layout does not draw: {missing}")
    if extra:
        problems.append(
            f"this layout draws instances the netlist does not have: {extra}"
        )

    for name, (model, w_um, l_um, nodes) in sorted(expected.items()):
        found = instances.get(name)
        if found is None:
            continue
        if found["model"] != model:
            problems.append(f"{name}: netlist model {found['model']!r} != {model!r}")
        if tuple(found["nodes"]) != nodes:
            problems.append(
                f"{name}: netlist nodes {tuple(found['nodes'])} != the "
                f"drain/gate/source/bulk nets this layout wires, {nodes}"
            )
        for key, want in (("w", w_um), ("l", l_um)):
            have = _microns(found["params"].get(key, "nan"))
            if abs(have - want) > 1e-9:
                problems.append(
                    f"{name}: netlist {key}={have} um, layout draws {want} um"
                )
        for key in ("ng", "m"):
            if found["params"].get(key, "1") != "1":
                problems.append(
                    f"{name}: netlist sets {key}={found['params'][key]}, which this "
                    "layout does not implement (it draws ng=1, m=1 devices and "
                    "folds/splits them itself)"
                )

    cap = instances.get("XCc")
    if cap is None:
        problems.append(
            "netlist has no XCc: the Miller capacitor is drawn but not declared"
        )
    else:
        if cap["model"] != "cap_cmim":
            problems.append(f"XCc: netlist model {cap['model']!r} != 'cap_cmim'")
        # The netlist gives the two terminals as an unordered pair; which one
        # becomes the MIM top plate is the layout's call (see CAP_BOTTOM_NET).
        if set(cap["nodes"]) != {CAP_BOTTOM_NET, CAP_TOP_NET}:
            problems.append(
                f"XCc: netlist terminals {cap['nodes']} != the two plate nets this "
                f"layout wires, {sorted({CAP_BOTTOM_NET, CAP_TOP_NET})}"
            )
        for key, want in (("w", CAP_W_UM), ("l", CAP_L_UM)):
            have = _microns(cap["params"].get(key, "nan"))
            if abs(have - want) > 1e-9:
                problems.append(f"XCc: netlist {key}={have} um, layout draws {want} um")

    declared = {node for inst in instances.values() for node in inst["nodes"]}
    for port in PORT_NETS:
        if port not in declared:
            problems.append(f"port {port!r} is not connected to any netlist instance")
    return problems


# --------------------------------------------------------------------------- #
# Placement bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class PlacedDevice:
    """A placed ``klt gen`` stream plus its ports in assembly coordinates.

    ``klt gen`` reports port locations in the generated cell's own frame and
    ``Builder.place_stream`` positions that cell by its bounding-box corner,
    so the two have to be reconciled once, here, rather than at every call
    site.
    """

    name: str
    generated: devices.GeneratedDevice
    placed: Placed
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        bbox = self.generated.report["bbox_um"]
        dx = self.placed.x0 - bbox["x0"]
        dy = self.placed.y0 - bbox["y0"]
        self.ports = {
            port["name"]: (port["x_um"] + dx, port["y_um"] + dy)
            for port in self.generated.report["ports"]
        }

    def port(self, name: str) -> tuple[float, float]:
        return self.ports[name]

    def unit_ports(self, terminal: str) -> list[tuple[int, tuple[float, float]]]:
        """``[(unit index, (x, y)), ...]`` for terminal ``"S"``/``"D"``/``"G"``."""
        out = []
        for name, xy in self.ports.items():
            if name.startswith("U") and name.endswith(f"_{terminal}"):
                out.append((int(name[1:-2]), xy))
        return sorted(out)

    def tap_ports(self) -> list[tuple[float, float]]:
        return [
            xy for name, xy in sorted(self.ports.items()) if name.startswith("TAP_")
        ]

    def dummy_sites(self) -> list[tuple[float, float]]:
        """Every contactable pad on the array's two dummy columns.

        ``mos_array`` draws the dummy columns but reports no ports for them,
        so their pads have to be derived. A one-row array is a uniform grid:
        the column pitch is the x step between consecutive units' sources, and
        the dummies sit exactly one pitch outside the outermost units, with
        their S/G/D pads at the same three offsets and the same two y values
        as every real unit.

        **Tying them matters electrically, not just cosmetically.** A floating
        dummy gate is a poorly-defined boundary condition for the edge device
        it is there to protect -- it can couple, and it can invert the
        diffusion underneath it. Every pad returned here is strapped to the
        array's body/source rail by :func:`route_pair`.
        """
        sources = self.unit_ports("S")
        if len(sources) < 2:
            raise ValueError(f"{self.name}: need >= 2 units to derive a column pitch")
        xs = sorted(xy[0] for _i, xy in sources)
        pitch = xs[1] - xs[0]
        for lo, hi in pairwise(xs):
            if abs((hi - lo) - pitch) > 1e-9:
                raise ValueError(
                    f"{self.name}: unit columns are not uniformly pitched "
                    f"({xs}); dummy pad positions cannot be derived"
                )
        sites: list[tuple[float, float]] = []
        for terminal in ("S", "G", "D"):
            pads = sorted(xy for _i, xy in self.unit_ports(terminal))
            sites.append((pads[0][0] - pitch, pads[0][1]))
            sites.append((pads[-1][0] + pitch, pads[-1][1]))
        return sites


# --------------------------------------------------------------------------- #
# Routing helpers. Metal2 is vertical, Metal3 horizontal -- see floorplan.py.
# --------------------------------------------------------------------------- #
class Router:
    """Thin net-aware layer over :class:`builder.Builder`.

    Every wire is recorded against its net name so :func:`check_connectivity`
    can report a failure in terms of nets rather than coordinates, and so the
    drawn x-extent of each horizontal track is known without re-reading the
    layout.
    """

    def __init__(self, b: Builder) -> None:
        self.b = b
        self.track_span: dict[str, tuple[float, float]] = {}
        self.probe: dict[str, list[tuple[tuple[int, int], float, float]]] = {}

    # -- probes -------------------------------------------------------------
    def expect(self, net: str, layer: tuple[int, int], x: float, y: float) -> None:
        """Record that ``(x, y)`` on ``layer`` must extract onto net ``net``."""
        self.probe.setdefault(net, []).append((layer, x, y))

    # -- horizontal ---------------------------------------------------------
    def track(self, name: str, x0: float, x1: float) -> float:
        """Draw (or widen) horizontal track ``name`` to cover ``[x0, x1]``."""
        y = fp.TRACK_UM[name]
        lo, hi = min(x0, x1), max(x0, x1)
        old = self.track_span.get(name)
        if old is not None:
            lo, hi = min(lo, old[0]), max(hi, old[1])
        self.track_span[name] = (lo, hi)
        return y

    def draw_tracks(self) -> None:
        """Emit every track requested by :meth:`track`, once, at full span."""
        for name, (x0, x1) in sorted(self.track_span.items()):
            self.b.route_h(
                L_METAL3,
                fp.TRACK_UM[name],
                x0 - fp.VIA_OVERTRAVEL_UM,
                x1 + fp.VIA_OVERTRAVEL_UM,
                width=fp.track_width_um(name),
            )

    # -- vertical -----------------------------------------------------------
    def drop(self, net: str, x: float, y_port: float, track: str) -> None:
        """Wire a Metal1 device port to horizontal track ``track``."""
        y_track = self.track(track, x, x)
        self.b.via(L_METAL1, L_METAL2, x, y_port)
        lo, hi = min(y_port, y_track), max(y_port, y_track)
        self.b.route_v(
            L_METAL2,
            x,
            lo - fp.VIA_OVERTRAVEL_UM,
            hi + fp.VIA_OVERTRAVEL_UM,
            width=fp.W_WIRE_UM,
        )
        self.b.via(L_METAL2, L_METAL3, x, y_track)
        self.expect(net, L_METAL1, x, y_port)

    def riser(self, net: str, x: float, tracks: list[str]) -> None:
        """One vertical Metal2 wire joining two or more horizontal tracks."""
        ys = sorted(self.track(name, x, x) for name in tracks)
        self.b.route_v(
            L_METAL2,
            x,
            ys[0] - fp.VIA_OVERTRAVEL_UM,
            ys[-1] + fp.VIA_OVERTRAVEL_UM,
            width=fp.W_WIRE_UM,
        )
        for y in ys:
            self.b.via(L_METAL2, L_METAL3, x, y)
            self.expect(net, L_METAL3, x, y)

    def strap(
        self, net: str, sites: list[tuple[float, float]], track: str, margin: float
    ) -> None:
        """One Metal2 patch covering ``sites``, dropped to ``track``.

        Used for a dummy column, whose three pads are only ~0.34 um apart in x
        -- too close for three separate wires, and needless anyway since all
        three carry the same net.
        """
        xs = [x for x, _y in sites]
        ys = [y for _x, y in sites]
        y_track = self.track(track, min(xs) - margin, max(xs) + margin)
        x0, x1 = min(xs) - margin, max(xs) + margin
        y0 = min(min(ys) - margin, y_track)
        y1 = max(max(ys) + margin, y_track)
        self.b.box(L_METAL2, x0, y0, x1, y1)
        for x, y in sites:
            self.b.via(L_METAL1, L_METAL2, x, y)
            self.expect(net, L_METAL1, x, y)
        self.b.via(L_METAL2, L_METAL3, (x0 + x1) / 2.0, y_track)

    # -- pins ---------------------------------------------------------------
    def pin(self, net: str, x: float, track: str) -> None:
        """A labelled Metal3 pad on ``track``: the block's port for ``net``.

        The label is drawn twice, on purpose: once on ``TEXT`` (63/0), the
        documentation layer ``builder.Builder.label`` defaults to and the one
        ``layout/README.md`` names, and once on ``Metal3`` itself, where an
        LVS run would look for a net name. Nothing in *this* repo reads the
        second one yet -- ``klt lvs`` is T1 item 4 and out of scope here --
        but a text on the port's own conductor costs nothing and is what
        makes the stream usable when it does.
        """
        size = max(fp.PIN_PAD_UM, fp.track_width_um(track))
        half = size / 2.0
        y = self.track(track, x - half, x + half)
        self.b.box(L_METAL3, x - half, y - half, x + half, y + half)
        self.b.label(net, x, y)
        self.b.label(net, x, y, layer=L_METAL3)
        self.expect(net, L_METAL3, x, y)


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
def generate_devices(
    scratch: Path, klt: str = "klt"
) -> dict[str, devices.GeneratedDevice]:
    """Run every ``klt gen`` invocation this block needs."""
    out: dict[str, devices.GeneratedDevice] = {}
    for pair in PAIRS:
        maker = devices.lv_nmos if pair.flavour == "sg13_lv_nmos" else devices.lv_pmos
        out[pair.cell] = maker(
            pair.w_total_um / UNITS_PER_DEVICE,
            pair.l_um,
            pair.cell,
            scratch,
            klt=klt,
            rows=1,
            cols=2 * UNITS_PER_DEVICE,
            dummy=1,
            topology="common_centroid",
            guard_ring=True,
        )
    for dev in FOLDED:
        maker = devices.lv_nmos if dev.flavour == "sg13_lv_nmos" else devices.lv_pmos
        out[dev.cell] = maker(
            dev.finger_w_um,
            dev.l_um,
            dev.cell,
            scratch,
            klt=klt,
            fingers=dev.fingers,
            guard_ring=True,
        )
    out["miller_cap"] = devices.cmim_cap(
        CAP_W_UM, CAP_L_UM, "miller_cap", scratch, klt=klt
    )
    return out


def place_all(
    b: Builder, generated: dict[str, devices.GeneratedDevice]
) -> dict[str, PlacedDevice]:
    placed: dict[str, PlacedDevice] = {}
    for name, dev in generated.items():
        x, y = fp.PLACE_UM[name]
        placed[name] = PlacedDevice(name, dev, b.place_stream(dev.gds_path, name, x, y))
    return placed


def assert_common_centroid(
    pair: MatchedPair, dev: PlacedDevice, side: Callable[[int], str]
) -> None:
    """Assert the ``B A A B`` assignment really is common-centroid in x.

    The whole matching claim in ``layout/README.md`` rests on one fact this
    repo does not control: that ``klt gen mos_array``'s internal
    ``topology="common_centroid"`` numbering lays four units out ``U2 U0 U1
    U3``, so that :func:`route_pair`'s ``{U0, U1} -> A`` / ``{U2, U3} -> B``
    split puts both devices' centroids on the array centre.

    If a future ``klt`` renumbered the units, *nothing else in this repo would
    notice*: the nets would still be wired correctly, so DRC would still be
    clean and :func:`check_connectivity` would still pass, and
    ``signoff/check_signoff.py`` re-hashes the committed stream rather than
    regenerating it. The only tripwire would be a human reading a byte diff
    from ``--check``. So assert the property itself instead of documenting it:
    the mean x of device A's unit columns must equal device B's to within one
    database unit.
    """
    columns = dict(dev.unit_ports("S"))
    if len(columns) != 2 * UNITS_PER_DEVICE:
        raise AssertionError(
            f"{dev.name}: expected {2 * UNITS_PER_DEVICE} unit source ports "
            f"from `klt gen mos_array`, got {sorted(columns)}"
        )
    centroid = {}
    for which in ("a", "b"):
        xs = [x for unit, (x, _y) in columns.items() if side(unit) == which]
        centroid[which] = sum(xs) / len(xs)
    if abs(centroid["a"] - centroid["b"]) > DBU_UM:
        raise AssertionError(
            f"{dev.name} ({pair.inst_a}/{pair.inst_b}) is not common-centroid "
            f"in x: device A's columns centre at {centroid['a']:.4f} um, "
            f"device B's at {centroid['b']:.4f} um "
            f"(unit source pads at "
            f"{[(u, round(x, 4)) for u, (x, _y) in sorted(columns.items())]}). "
            "`klt gen mos_array`'s common_centroid numbering is no longer "
            "U2 U0 U1 U3, so route_pair()'s {U0,U1}->A / {U2,U3}->B split -- "
            "and the matching claim in layout/README.md that rests on it -- "
            "is wrong for this klt revision."
        )


def route_pair(
    r: Router, pair: MatchedPair, dev: PlacedDevice, tracks: dict[str, str]
) -> None:
    """Wire one ``B A A B`` matched array.

    The per-array discipline the whole floorplan rests on: **sources and
    drains route down, gates route up.** Within a unit device the gate pad
    sits between the source and drain pads in x, only 0.34 um from each -- too
    close for three vertical wires at ``metal2.space.1``. Sending the gate the
    other way puts it in a disjoint y band, so the three lanes never coexist.
    """

    # `mos_array`'s common-centroid numbering pairs U0 with U1 and U2 with U3;
    # device A is the first pair, device B the second (see MatchedPair).
    def side(unit: int) -> str:
        return "a" if unit in (0, 1) else "b"

    assert_common_centroid(pair, dev, side)

    for _unit, (x, y) in dev.unit_ports("S"):
        r.drop(pair.source_net, x, y, tracks["source"])
    for unit, (x, y) in dev.unit_ports("D"):
        which = side(unit)
        r.drop(getattr(pair, f"drain_{which}"), x, y, tracks[f"drain_{which}"])
    for unit, (x, y) in dev.unit_ports("G"):
        which = side(unit)
        r.drop(getattr(pair, f"gate_{which}"), x, y, tracks[f"gate_{which}"])
    for x, y in dev.tap_ports():
        # Only the ring's W and E ports are used. TAP_N/TAP_S sit on the
        # array's x centre line, which falls between two source/drain lanes
        # 0.41 um away -- inside metal2.space.1 once a 0.40 um wire is drawn
        # on each. The ring is one continuous Metal1 loop, so tying it at two
        # opposite sides reaches all of it.
        if abs(x - dev.placed.x0) > 1.0 and abs(x - dev.placed.x1) > 1.0:
            continue
        r.drop(pair.body_net, x, y, tracks["body"])
    r.strap(pair.body_net, dev.dummy_sites()[0::2], tracks["body"], margin=0.21)
    r.strap(pair.body_net, dev.dummy_sites()[1::2], tracks["body"], margin=0.21)


def build(
    scratch: Path, klt: str = "klt", omit_riser: str | None = None
) -> tuple[Builder, Router, dict, list[dict]]:
    """Draw and route the whole block.

    ``omit_riser`` deliberately leaves one inter-channel wire out, for
    :func:`negative_control`. It is never set on the committed run.
    """
    b = Builder(TOP_CELL)
    r = Router(b)
    generated = generate_devices(scratch, klt=klt)
    placed = place_all(b, generated)

    tp, ip, mr = placed["tail_pair"], placed["input_pair"], placed["mirror"]
    xm7, xm6, cap = placed["out_tail"], placed["gain"], placed["miller_cap"]

    # -- stage 1 + bias: three matched arrays, bottom to top ---------------- #
    route_pair(
        r,
        PAIRS[0],
        tp,
        {
            "source": "vss_rail",
            "drain_a": "tail_c0",
            "drain_b": "ibias_c0",
            "gate_a": "ibias_c1",
            "gate_b": "ibias_c1",
            "body": "vss_rail",
        },
    )
    route_pair(
        r,
        PAIRS[1],
        ip,
        {
            "source": "tail_c1",
            "drain_a": "d1_c1",
            "drain_b": "d2_c1",
            "gate_a": "inn",
            "gate_b": "inp",
            "body": "vss_c1",
        },
    )
    route_pair(
        r,
        PAIRS[2],
        mr,
        {
            "source": "vdd_rail",
            "drain_a": "d1_c2",
            "drain_b": "d2_c2",
            "gate_a": "d1_c3",
            "gate_b": "d1_c3",
            "body": "vdd_rail",
        },
    )

    # -- stage 2: two folded devices ---------------------------------------- #
    r.drop("vss", *xm7.port("U0_S"), "vss_rail")
    r.drop("out", *xm7.port("U0_D"), "out_stage2")
    r.drop("ibias", *xm7.port("U0_G"), "ibias_c1")
    for x, y in xm7.tap_ports():
        if abs(x - xm7.placed.x0) > 1.0 and abs(x - xm7.placed.x1) > 1.0:
            continue
        r.drop("vss", x, y, "vss_rail")

    r.drop("vdd", *xm6.port("U0_S"), "vdd_rail")
    r.drop("d2", *xm6.port("U0_G"), "d2_c4")
    for x, y in xm6.tap_ports():
        if abs(x - xm6.placed.x0) > 1.0 and abs(x - xm6.placed.x1) > 1.0:
            continue
        r.drop("vdd", x, y, "vdd_rail")
    # XM6's drain is the block output: a single Metal2 wire the full height of
    # stage 2, down to the output track the cap and XM7 share.
    r.drop("out", *xm6.port("U0_D"), "out_stage2")

    # -- inter-channel risers, in the lanes left of column 1 ----------------- #
    r.riser("tail", fp.LANE_UM["tail"], ["tail_c0", "tail_c1"])
    r.riser("ibias", fp.LANE_UM["ibias"], ["ibias_c0", "ibias_c1"])
    r.riser("d1", fp.LANE_UM["d1"], ["d1_c1", "d1_c2", "d1_c3"])
    r.riser("d2", fp.LANE_UM["d2"], ["d2_c1", "d2_c2"])
    if omit_riser != "d2_mid":
        r.riser("d2", fp.MID_LANE_UM["d2"], ["d2_c2", "d2_c4"])
    else:
        # Keep the track spans identical to the intact block, so the injected
        # fault is exactly one missing wire and not a different floorplan.
        r.track("d2_c2", fp.MID_LANE_UM["d2"], fp.MID_LANE_UM["d2"])
        r.track("d2_c4", fp.MID_LANE_UM["d2"], fp.MID_LANE_UM["d2"])
    # The input pair's substrate ring hangs off its own local track; one wire
    # at the array's left edge takes it down to the global VSS trunk.
    r.riser("vss", ip.port("TAP_W")[0], ["vss_rail", "vss_c1"])

    # -- the Miller capacitor ------------------------------------------------ #
    mim_patch = devices.patch_mim_bottom_plate(b, cap.placed)
    m5 = cap.placed.layer_bbox[L_METAL5]
    tm1 = cap.placed.layer_bbox[L_TOPMETAL1]
    # Bottom plate (Metal5) -> `out`: land the stack well inside the plate, so
    # the via's own landing pad merges into it rather than notching its edge.
    bot_x = m5[0] + 1.0
    r.track("out_stage2", bot_x, bot_x)
    b.via_stack(L_METAL3, L_METAL5, bot_x, fp.TRACK_UM["out_stage2"])
    r.expect("out", L_METAL5, bot_x, fp.TRACK_UM["out_stage2"])
    # Top plate (MIM) -> `d2`, reached through the generator's own TopMetal1
    # strap. The stack lands above the bottom plate's top edge so the Metal5
    # landing pad it draws on the way up does not touch it.
    top_x = (tm1[0] + tm1[2]) / 2.0
    r.track("d2_c4", top_x, top_x)
    b.via_stack(L_METAL3, L_TOPMETAL1, top_x, fp.TRACK_UM["d2_c4"])
    r.expect("d2", L_TOPMETAL1, top_x, fp.TRACK_UM["d2_c4"])
    r.expect(CAP_BOTTOM_NET, L_METAL5, (m5[0] + m5[2]) / 2.0, (m5[1] + m5[3]) / 2.0)
    r.expect(CAP_TOP_NET, L_TOPMETAL1, (tm1[0] + tm1[2]) / 2.0, tm1[1] + 1.0)
    # `d2` runs from XM6's gate along the top of stage 2 to the cap; `out`
    # from XM7's drain along the bottom to the plate below it.
    r.track("d2_c4", xm6.port("U0_G")[0], top_x)
    r.track("out_stage2", xm7.port("U0_D")[0], bot_x)

    # -- matching-driven track balancing ------------------------------------- #
    # The two halves of a differential net see the same *device*, but not
    # automatically the same *wire*: in a B A A B row, device A's drains sit
    # on the two inner columns and B's on the two outer ones, so d1's track is
    # 3 um shorter than d2's and inn's is 3 um shorter than inp's. Left alone
    # that is a deliberate ~10% capacitance imbalance on a differential pair.
    # Extending the shorter track of each pair to the longer one's span costs
    # a few square microns of Metal3 and removes it.
    for a, bnet in (("d1_c1", "d2_c1"), ("inn", "inp")):
        span = (
            min(r.track_span[a][0], r.track_span[bnet][0]),
            max(r.track_span[a][1], r.track_span[bnet][1]),
        )
        r.track(a, *span)
        r.track(bnet, *span)

    # -- pins ---------------------------------------------------------------- #
    for net in PORT_NETS:
        x, track = fp.PIN_SITES[net]
        r.pin(net, x, track)
    # Keep the two trunks continuous to the left edge of the block.
    r.track("vss_rail", fp.BLOCK_X_LEFT_UM, fp.BLOCK_X_LEFT_UM)
    r.track("vdd_rail", fp.BLOCK_X_LEFT_UM, fp.BLOCK_X_LEFT_UM)

    r.draw_tracks()

    bx0, by0, bx1, by1 = b.bbox_um()
    b.pr_boundary(
        bx0 - fp.PR_MARGIN_UM,
        by0 - fp.PR_MARGIN_UM,
        bx1 + fp.PR_MARGIN_UM,
        by1 + fp.PR_MARGIN_UM,
    )

    provenance = [
        {
            "cell": name,
            "device": dev.kind,
            "generator": dev.generator,
            "params": dev.params,
            "placed_bbox_um": [
                round(v, 4)
                for v in (
                    placed[name].placed.x0,
                    placed[name].placed.y0,
                    placed[name].placed.x1,
                    placed[name].placed.y1,
                )
            ],
        }
        for name, dev in generated.items()
    ]
    summary = {
        "bbox_um": [round(v, 4) for v in b.bbox_um()],
        "mim_c_patch_um": mim_patch,
    }
    return b, r, summary, provenance


# --------------------------------------------------------------------------- #
# Connectivity self-check
# --------------------------------------------------------------------------- #
#: Which layers the self-check treats as conductors, and which cut joins each
#: adjacent pair. Extraction deliberately stops at ``Metal1``: below it lies
#: the device itself, and this check is about the *interconnect* this file
#: drew, not about the generators' internals.
_CONDUCTORS = (L_METAL1, L_METAL2, L_METAL3, L_METAL4, L_METAL5, L_TOPMETAL1)
_CUTS = (L_VIA1, L_VIA2, L_VIA3, L_VIA4, L_TOPVIA1)


def check_connectivity(b: Builder, r: Router) -> list[str]:
    """Extract the drawn interconnect and compare it against the netlist.

    Returns a list of human-readable failures (empty means pass). Three
    independent things are asserted:

    1. **No open.** Every probe point recorded for a net must land on one and
       the same extracted net.
    2. **No short.** No two distinct netlist nets may land on the same
       extracted net.
    3. **Nothing else.** The extraction must find *exactly* as many nets as
       the netlist declares -- so no drawn conductor is left floating, and in
       particular no dummy device's gate is.

    None of the three is visible to DRC -- a short between two nets is
    perfectly legal geometry, and so is an isolated island of metal -- so
    without this, "DRC clean" would say nothing at all about whether the
    block is wired the way the netlist says.

    What it does **not** do: it never opens
    ``design/netlist/opamp_core.spice``. It compares the drawn metal against
    the net assignments *this module* declares in :data:`PAIRS` /
    :data:`FOLDED`, and it stops at ``Metal1``, so a device's own
    contact-to-diffusion stack is taken on the generator's word. Checking the
    layout against the netlist file, with device recognition, is ``klt lvs``
    (T1 item 4) and is out of this issue's scope.
    """
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(b.layout, b.cell, []))
    layers: dict[tuple[int, int], object] = {}
    for pair in (*_CONDUCTORS, *_CUTS):
        idx = b.layout.layer(*pair)
        layers[pair] = l2n.make_polygon_layer(idx, f"{pair[0]}_{pair[1]}")
        l2n.connect(layers[pair])
    for lower, cut, upper in zip(_CONDUCTORS[:-1], _CUTS, _CONDUCTORS[1:], strict=True):
        l2n.connect(layers[lower], layers[cut])
        l2n.connect(layers[cut], layers[upper])
    l2n.extract_netlist()

    failures: list[str] = []
    cluster_of: dict[str, int] = {}
    for net_name, probes in sorted(r.probe.items()):
        clusters: dict[int, tuple[float, float]] = {}
        for layer, x, y in probes:
            extracted = l2n.probe_net(layers[layer], kdb.DPoint(x, y))
            if extracted is None:
                failures.append(
                    f"{net_name}: nothing extracted at ({x:.3f}, {y:.3f}) on "
                    f"{layer[0]}/{layer[1]} -- that terminal is on no conductor"
                )
                continue
            clusters.setdefault(extracted.cluster_id, (x, y))
        if len(clusters) > 1:
            where = ", ".join(
                f"({x:.3f}, {y:.3f})" for x, y in sorted(clusters.values())
            )
            failures.append(
                f"{net_name}: OPEN -- its {len(probes)} terminals extract onto "
                f"{len(clusters)} separate nets; one terminal of each at {where}"
            )
        if clusters:
            cluster_of[net_name] = next(iter(clusters))

    seen: dict[int, str] = {}
    for net_name, cid in sorted(cluster_of.items()):
        clash = seen.get(cid)
        if clash is not None:
            failures.append(
                f"SHORT -- {clash!r} and {net_name!r} extract onto the same net"
            )
        seen[cid] = net_name

    netlist = l2n.netlist()
    circuit = netlist.circuit_by_name(b.cell.name)
    extracted_nets = 0 if circuit is None else sum(1 for _ in circuit.each_net())
    if extracted_nets != len(r.probe):
        failures.append(
            f"FLOATING -- the stream extracts to {extracted_nets} nets but the "
            f"netlist declares {len(r.probe)}; some drawn conductor is "
            "connected to nothing (a dummy gate, or a wire that missed its via)"
        )
    return failures


# --------------------------------------------------------------------------- #
# DRC
# --------------------------------------------------------------------------- #
def negative_control(klt: str = "klt") -> int:
    """Prove :func:`check_connectivity` can *fail*, writing nothing to the repo.

    A check that has never returned a failure is not evidence of anything.
    This rebuilds the block with one wire deliberately deleted -- the Metal2
    riser that carries ``d2`` from the mirror's drain track up to XM6's gate
    and the Miller capacitor -- and asserts that the check reports ``d2``
    open. The deleted riser is chosen because its absence is *invisible to
    DRC*: the remaining geometry is still perfectly legal, and a plain
    ``klt drc`` run on the broken block still comes back clean. That is the
    whole point of having this check at all.

    Nothing is committed: the broken layout is built in memory and the
    scratch generator streams live in a temp directory.
    """
    with tempfile.TemporaryDirectory(prefix="sg13g2-opamp-negctl-") as tmp:
        b, r, _summary, _prov = build(Path(tmp) / "gen", klt=klt, omit_riser="d2_mid")
        failures = check_connectivity(b, r)
        broken_gds = Path(tmp) / "broken.gds"
        b.write(broken_gds)
        drc = json.loads(
            subprocess.run(
                [
                    devices.require_klt(klt),
                    "drc",
                    str(broken_gds),
                    "--deck",
                    "sg13g2",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
        )
    print(
        f"negative control: klt drc on the broken block says status="
        f"{drc['status']} violations={drc['violation_count']}"
    )
    if drc["status"] != "clean":
        print(
            "NOTE: removing that wire also broke DRC, so this run does not "
            "demonstrate the DRC-invisible case the check exists for",
            file=sys.stderr,
        )
    print(f"negative control: {len(failures)} connectivity failure(s) reported")
    for failure in failures:
        print(f"  {failure}")
    if not failures:
        print(
            "FAIL: the connectivity check passed a block with a wire removed, "
            "so a passing verdict from it means nothing",
            file=sys.stderr,
        )
        return 1
    if not any(f.startswith("d2: OPEN") for f in failures):
        print(
            "FAIL: expected the check to report `d2` open; it reported "
            "something else, so it is not detecting the fault that was injected",
            file=sys.stderr,
        )
        return 1
    print("OK: the connectivity check detects a removed wire, and names the net")
    return 0


def drc_each_device(klt: str = "klt") -> int:
    """DRC every device stream on its own, before any of them is assembled.

    Asked for explicitly by this block's acceptance criteria for the two
    outliers -- XM6 at w=33 um and the 25.7 um square MIM -- and cheap enough
    to run for all six. A violation inside a single generated device is a
    different problem from one created by the assembly, and a per-device pass
    is what tells the two apart.
    """
    exe = devices.require_klt(klt)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="sg13g2-opamp-devices-") as tmp:
        generated = generate_devices(Path(tmp), klt=klt)
        for name, dev in generated.items():
            out = json.loads(
                subprocess.run(
                    [
                        exe,
                        "drc",
                        str(dev.gds_path),
                        "--deck",
                        "sg13g2",
                        "--format",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout
            )
            bbox = dev.report["bbox_um"]
            print(
                f"  {name:<12} {dev.kind:<14} "
                f"{bbox['x1'] - bbox['x0']:6.2f} x {bbox['y1'] - bbox['y0']:6.2f} um  "
                f"drc={out['status']} violations={out['violation_count']}"
            )
            if out["status"] != "clean":
                failures += 1
                for violation in out["violations"][:10]:
                    print(f"      {violation}", file=sys.stderr)
    if failures:
        print(f"FAIL: {failures} device stream(s) are not DRC clean", file=sys.stderr)
        return 1
    print("OK: every device stream is individually clean before assembly")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temp dir and diff against the committed "
        "artifacts instead of overwriting them (exit 1 on any drift)",
    )
    ap.add_argument(
        "--devices",
        action="store_true",
        help="instead of assembling, DRC each generated device stream on its "
        "own and report (writes nothing to the repo)",
    )
    ap.add_argument(
        "--negative-control",
        action="store_true",
        help="instead of regenerating, prove the connectivity self-check "
        "detects a deliberately removed wire (writes nothing to the repo)",
    )
    ap.add_argument("--klt", default="klt", help="klt executable (default: klt)")
    args = ap.parse_args(argv)

    if args.devices:
        return drc_each_device(args.klt)
    if args.negative_control:
        return negative_control(args.klt)

    drift = verify_against_netlist()
    if drift:
        print(
            f"FAIL: this generator disagrees with {NETLIST_PATH.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )
        for problem in drift:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(
        f"netlist cross-check: {NETLIST_PATH.relative_to(REPO_ROOT)} agrees with "
        f"{len(PAIRS) * 2 + len(FOLDED) + 1} drawn instances"
    )

    deck = verify_deck_minima(args.klt)
    print(
        f"curated sg13g2 deck: {deck['rule_count']} rules, "
        f"{deck['content_hash']}  (DECK_MIN_UM verified in step)"
    )

    with tempfile.TemporaryDirectory(prefix="sg13g2-opamp-core-") as tmp:
        scratch = Path(tmp)
        b, r, summary, provenance = build(scratch / "gen", klt=args.klt)

        failures = check_connectivity(b, r)
        if failures:
            print(
                "FAIL: the drawn interconnect does not match the netlist",
                file=sys.stderr,
            )
            for failure in failures:
                print(f"  {failure}", file=sys.stderr)
            return 1
        print(
            f"connectivity self-check: {len(r.probe)} nets, "
            f"{sum(len(v) for v in r.probe.values())} terminals, no open, no short"
        )

        gds_out = (scratch / GDS_PATH.name) if args.check else GDS_PATH
        report_out = (scratch / DRC_REPORT_PATH.name) if args.check else DRC_REPORT_PATH
        gds_out.parent.mkdir(parents=True, exist_ok=True)
        b.write(gds_out)
        print(f"wrote {gds_out}  bbox_um={summary['bbox_um']}")
        for entry in provenance:
            print(f"  {entry['cell']:<12} {entry['device']:<14} {entry['params']}")
        if summary["mim_c_patch_um"] is not None:
            print(f"  MIM.c patched: {summary['mim_c_patch_um']}")

        drc = devices.run_drc(gds_out, report_out, GDS_PATH, REPO_ROOT, klt=args.klt)
        cov = drc["coverage"]
        print(
            f"klt drc --deck sg13g2: status={drc['status']} "
            f"violations={drc['violation_count']} "
            f"rules_checked={len(cov['rules_checked'])} "
            f"rules_skipped={len(cov['rules_skipped'])} "
            f"layers_in_stream_without_rules={cov['layers_in_stream_without_rules']}"
        )
        if drc["status"] != "clean":
            print("FAIL: DRC is not clean", file=sys.stderr)
            for violation in drc["violations"][:30]:
                print(f"  {violation}", file=sys.stderr)
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
                        f"FAIL: committed DRC report's {key!r} differs from a fresh run",
                        file=sys.stderr,
                    )
                    ok = False
            if not ok:
                return 1
            print("OK: regenerated artifacts match the committed ones")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

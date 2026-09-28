"""Floorplan constants for ``opamp_core``: every coordinate in one place.

Separated from :mod:`generate` so the numbers a reviewer needs to argue with
-- where each device sits, which horizontal track carries which net -- are
readable without wading through the drawing code, and so a change to one of
them is a one-line diff.

Two conventions hold everywhere below, and the routing in ``generate.py``
depends on both:

**Routing discipline.** ``Metal2`` carries every *vertical* wire and
``Metal3`` every *horizontal* one. Neither layer appears in any ``klt gen``
device stream (those draw only ``Activ``/``GatPoly``/``Cont``/``Metal1`` and,
for a pfet, ``NWell``), so an M2 or M3 wire may cross a device freely; only
wires on the *same* layer can collide, and a vertical/horizontal split makes
those collisions one-dimensional and checkable by inspection.

**Every horizontal track has a unique y, and no two are closer than one wire
width plus ``metal3.space.1``.** Both are asserted at import time by
:func:`_assert_track_pitch`. Two nets therefore never share -- or crowd -- a
track ordinate anywhere in the block, so no M3-vs-M3 short or spacing
violation is possible by construction, whatever x-range each track spans.

The remaining failure mode -- two different nets' vertical M2 wires sharing an
x lane over an overlapping y band -- is what the per-array "sources and drains
route *down*, gates route *up*" rule exists to prevent, and what
``generate.py``'s extracted-connectivity self-check catches if the rule is
ever broken.
"""

from __future__ import annotations

from itertools import pairwise

# --------------------------------------------------------------------------- #
# Wire widths, in microns. The signal width is a deliberate 2x margin over the
# curated deck's own minimum for both routing layers (metal2.width.1 =
# metal3.width.1 = 0.20), for the same reason builder.DEFAULT_ROUTE_WIDTH_UM
# takes one: a bar drawn at exactly the minimum turns any rounding slip into a
# violation.
# --------------------------------------------------------------------------- #
W_WIRE_UM = 0.40

#: The two supply trunks are drawn wider than signal wires. This is a
#: *legibility* choice, not a current-density one: no IR-drop or
#: electromigration budget has been computed for this block (T1 item 11, issue
#: #29, is explicitly out of this layout's scope), so nothing here may be read
#: as a sized power grid.
W_RAIL_UM = 1.00

#: Curated-deck minimum spacing on both routing layers (``metal2.space.1`` is
#: 0.21 um and ``metal3.space.1`` is 0.21 um). Used by the import-time track
#: pitch assertion; every geometry-drawing helper sizes itself from
#: ``sg13g2_layers.DECK_MIN_UM`` directly.
_ROUTE_SPACE_UM = 0.21

#: How far a wire is extended past the centre of the via at each of its ends,
#: in microns. A via landing pad is 0.39 um across and a signal wire 0.40 um,
#: so without this the pad would poke 0.195 um out of the end of its own wire
#: and leave a 5 nm jog in the outline. Extending the wire swallows the pad.
VIA_OVERTRAVEL_UM = 0.20


# --------------------------------------------------------------------------- #
# Placement: the lower-left corner of each placed device's *bounding box*, in
# microns (`Builder.place_stream` positions by bbox corner, not by the
# generator stream's own origin, which for a `klt gen` stream is an interior
# point of the device).
#
# Three columns:
#   1. x ~ 0..13   stage 1 + the bias reference, stacked bottom-to-top in
#                  signal order: tail/bias pair, input pair, mirror load.
#   2. x ~ 21..42  stage 2: output tail below, the wide gain device above.
#   3. x ~ 46..73  the Miller capacitor, which is larger than the whole
#                  amplifier and therefore gets its own column.
# --------------------------------------------------------------------------- #
PLACE_UM: dict[str, tuple[float, float]] = {
    "tail_pair": (0.0, 4.0),  # XM5 + XMbias
    "input_pair": (0.0, 13.0),  # XM1 + XM2
    "mirror": (0.0, 22.0),  # XM3 + XM4
    "out_tail": (21.0, 4.0),  # XM7
    "gain": (21.0, 21.0),  # XM6
    "miller_cap": (46.0, 2.0),  # XCc
}

# --------------------------------------------------------------------------- #
# Horizontal (Metal3) tracks: one entry per (net, purpose), y in microns,
# ordered bottom-to-top.
#
# The channel each track sits in, and why it sits where it does:
#
#  * `vss_rail`, `tail_c0`, `ibias_c0` and `out_stage2` sit below the NMOS row.
#  * C1 (y 8.2..13.0) separates the tail pair from the input pair. The tail
#    pair's *gates* rise into the bottom of it and the input pair's
#    sources/drains descend into the top of it, so `ibias_c1` must stay below
#    every track the input pair drops to -- otherwise the two arrays' vertical
#    wires share a y band, and their x lanes (which interleave, as little as
#    0.48 um apart) would collide.
#  * C2 (y 17.7..22.0) separates the input pair from the mirror, and obeys the
#    same ordering for the same reason: the input pair's gate tracks (`inn`,
#    `inp`) sit below the mirror's drop tracks (`vdd_rail`, `d1_c2`, `d2_c2`).
#  * `vdd_rail` doubles as the mirror's source track and as stage 2's supply
#    track; it is the one horizontal wire both columns share.
# --------------------------------------------------------------------------- #
TRACK_UM: dict[str, float] = {
    "vss_rail": 0.80,  # global VSS trunk
    "tail_c0": 2.20,  # XM5 drains
    "ibias_c0": 3.00,  # XMbias drains + the `ibias` pin
    "out_stage2": 3.80,  # XM7 drain <-> XM6 drain <-> cap bottom plate
    "ibias_c1": 9.20,  # tail-pair gates (rising) + XM7 gate
    "vss_c1": 10.10,  # input-pair tap ring + its dummies
    "tail_c1": 10.90,  # input-pair sources (descending)
    "d1_c1": 11.70,  # XM1 drains
    "d2_c1": 12.50,  # XM2 drains
    "inn": 18.00,  # input-pair A gates (rising)
    "inp": 18.80,  # input-pair B gates (rising)
    "vdd_rail": 20.00,  # global VDD trunk: mirror + gain sources and wells
    "d1_c2": 21.00,  # XM3 drains
    "d2_c2": 21.80,  # XM4 drains
    "d1_c3": 27.00,  # mirror gates (rising) -- XM3 is diode-connected
    "d2_c4": 29.60,  # XM6 gate up to the capacitor's top plate
}

#: Tracks drawn at :data:`W_RAIL_UM` instead of :data:`W_WIRE_UM`.
RAIL_TRACKS = frozenset({"vss_rail", "vdd_rail"})

# --------------------------------------------------------------------------- #
# Vertical (Metal2) lanes reserved in the channel to the left of column 1, in
# microns. Each carries one net between two or more of its horizontal tracks;
# nothing else is drawn at x < 0 except the labelled pin pads.
# --------------------------------------------------------------------------- #
LANE_UM: dict[str, float] = {
    "tail": -1.50,
    "ibias": -3.90,
    "d1": -5.10,
    "d2": -6.30,
}

#: A second vertical lane, in the empty gap between columns 1 and 2, carrying
#: `d2` from the mirror's drain track up to the track that feeds XM6's gate
#: and the capacitor's top plate. Routing it here rather than out to the left
#: channel keeps ~50 um of Metal3 off the block's most capacitance-sensitive
#: node (the stage-1 output, and XM6's gate).
MID_LANE_UM: dict[str, float] = {
    "d2": 18.00,
}

#: Where each port's labelled pad sits: ``net -> (x, track)``.
#:
#: `inp`'s pad is pushed one step further left than the rest. At the 0.80 um
#: track pitch of channel C2 a pad wider than its own track would otherwise
#: touch its neighbour's track, and staggering x is cheaper than either
#: spreading the channel or shrinking the pads below legibility.
PIN_SITES: dict[str, tuple[float, str]] = {
    "vss": (-8.00, "vss_rail"),
    "ibias": (-8.00, "ibias_c0"),
    "inn": (-8.00, "inn"),
    "inp": (-10.00, "inp"),
    "vdd": (-8.00, "vdd_rail"),
    "out": (43.00, "out_stage2"),
}

#: Pin pads are square, at least this wide, and never narrower than the track
#: they sit on.
PIN_PAD_UM = 0.60

#: How far the supply trunks run past the leftmost lane, in microns -- far
#: enough to carry their labelled pin pads and no further (channel C2's
#: tracks are only 0.80 um apart, so an over-long trunk would crowd `inp`'s
#: staggered pad).
BLOCK_X_LEFT_UM = -8.60

#: prBoundary margin around the drawn geometry, in microns.
PR_MARGIN_UM = 1.00


def track_width_um(name: str) -> float:
    """Drawn width of track ``name``, in microns."""
    return W_RAIL_UM if name in RAIL_TRACKS else W_WIRE_UM


def _assert_track_pitch() -> None:
    """No two Metal3 tracks may share, or crowd, an ordinate.

    This is the invariant the module docstring rests on: with it, an M3
    short or M3 spacing violation between two nets is impossible however
    their x-ranges overlap, so the routing code never has to reason about
    horizontal-vs-horizontal conflicts at all.
    """
    seen: dict[float, str] = {}
    for name, y in TRACK_UM.items():
        clash = seen.get(y)
        if clash is not None:
            raise AssertionError(
                f"tracks {clash!r} and {name!r} share y={y} um; the "
                "unique-ordinate invariant that makes M3 shorts impossible by "
                "construction no longer holds"
            )
        seen[y] = name

    ordered = sorted(TRACK_UM.items(), key=lambda kv: kv[1])
    for (lo_name, lo_y), (hi_name, hi_y) in pairwise(ordered):
        gap = (hi_y - track_width_um(hi_name) / 2.0) - (
            lo_y + track_width_um(lo_name) / 2.0
        )
        if gap < _ROUTE_SPACE_UM:
            raise AssertionError(
                f"tracks {lo_name!r} (y={lo_y}) and {hi_name!r} (y={hi_y}) are "
                f"{gap:.3f} um apart, below metal3.space.1 = {_ROUTE_SPACE_UM} um"
            )


_assert_track_pitch()

"""``klayout.db`` drawing/routing scaffold for SG13G2 layout in this repo.

Everything here is PDK-generic *machinery* parameterised by the layer table in
:mod:`sg13g2_layers` -- boxes, labels, horizontal/vertical routing bars, via
stacks, per-metal via landing pads and well/substrate taps -- plus
deterministic GDS write-out. Device geometry is **not** drawn here: the three
devices this block needs (``sg13_lv_nmos``, ``sg13_lv_pmos``, ``cap_cmim``)
come from :mod:`devices`, which drives ``klt gen``. See ``layout/README.md``
for why the split falls there.

Structure follows the in-fleet precedent in ``2AMLogic/sg13g2-bandgap``
(``layout/_klayout_builder_base.py`` + ``layout/common.py`` at that repo's
``889a0d9``, read 2026-09-28): a ``Builder`` holding one ``kdb.Layout`` at
``dbu = 0.001`` (1 nm), micron-valued public API, integer database units
internally via a rounding ``_u()``, and a ``write()`` that disables GDS
timestamps. Three deliberate departures from that precedent, also recorded in
``layout/README.md``:

* ``route_h``/``route_v`` are methods here, free functions taking a
  ``BuilderBase`` there;
* every routing/via/tap helper sizes itself from
  :data:`sg13g2_layers.DECK_MIN_UM` rather than from a hand-entered literal
  (the precedent's ``route_h``/``route_v`` default to ``width = 0.3``);
* :meth:`Builder.via` draws a **separate, independently sized** landing pad on
  each of the two metals it joins, because SG13G2's upper via rules are
  strongly asymmetric (see :meth:`Builder.landing_pad`).

Determinism: :meth:`Builder.write` disables GDS timestamp records
(``SaveLayoutOptions.gds2_write_timestamps = False``). Without that, KLayout
stamps the current wall-clock time into every ``BGNLIB``/``BGNSTR`` record
and two runs of the same generator produce different bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import klayout.db as kdb
from sg13g2_layers import (
    CUT_SIZE_UM,
    DECK_MIN_UM,
    L_METAL1,
    L_PRBOUNDARY,
    L_TEXT,
    LAYER_NAMES,
    VIA_STACK,
    Layer,
)

DBU_UM = 0.001

#: Default routing-bar widths, per layer, in microns. Each is a deliberate
#: margin over the curated deck's own minimum width for that layer (see
#: :data:`sg13g2_layers.DECK_MIN_UM`) rather than the bare minimum, so a
#: rounding slip in a caller's coordinate arithmetic does not immediately
#: become a width violation.
DEFAULT_ROUTE_WIDTH_UM: dict[Layer, float] = {
    L_METAL1: 0.32,  # 2x metal1.width.1 (0.16)
}

#: Extra metal overlap of a cut beyond the curated deck's own
#: ``<metal>.enclosing.<cut>.1`` minimum, in microns. Drawing exactly the
#: minimum makes every via a zero-margin shape, so one rounding slip in a
#: caller's coordinates is a violation; this margin buys one 20 nm grid step.
CUT_ENCLOSURE_MARGIN_UM = 0.02

#: Enclosure to draw on a metal for which the curated deck transcribes **no**
#: ``<metal>.enclosing.<cut>.1`` rule at all. SG13G2 genuinely has only a
#: one-sided enclosure rule on its lower vias -- IHP's own ``5_19_via1.drc``
#: emits ``V1.a``/``V1.b``/``V1.c`` and no ``V1.d``, i.e. Metal1 must enclose
#: Via1 by 0.01 um and Metal2 has no enclosure requirement -- so this is a
#: self-imposed floor, not a transcribed rule, and nothing checks it.
DEFAULT_CUT_ENCLOSURE_UM = 0.10


@dataclass(frozen=True)
class Placed:
    """A placed sub-cell: its name, its bounding box, and its **per-layer**
    bounding boxes, all in microns and all in the assembly's coordinates.

    ``layer_bbox`` is what makes a placed generator stream reviewable against
    a rule the curated deck does not carry: e.g. IHP's ``MIM.c`` (Metal5 must
    enclose MIM by 0.60 um) can only be checked, or patched, if the caller can
    ask where the placed cell's ``MIM`` and ``Metal5`` shapes actually landed.
    """

    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    layer_bbox: dict[Layer, tuple[float, float, float, float]] = field(
        default_factory=dict
    )


class Builder:
    """One ``kdb.Layout`` plus a top cell, with micron-valued drawing helpers."""

    def __init__(self, top_cell: str, layout: kdb.Layout | None = None) -> None:
        if layout is None:
            layout = kdb.Layout()
            layout.dbu = DBU_UM
        self.layout = layout
        self.cell = self.layout.create_cell(top_cell)
        self._layers: dict[Layer, int] = {}
        for pair in LAYER_NAMES:
            self._layer_index(pair)

    # ----------------------------------------------------------------- core --
    def _layer_index(self, pair: Layer) -> int:
        """Layer index for ``(layer, datatype)``, creating + naming on first use."""
        idx = self._layers.get(pair)
        if idx is None:
            idx = self.layout.layer(*pair)
            name = LAYER_NAMES.get(pair)
            if name is not None:
                self.layout.set_info(idx, kdb.LayerInfo(pair[0], pair[1], name))
            self._layers[pair] = idx
        return idx

    def _u(self, value_um: float) -> int:
        """Microns -> database units, rounded (never truncated)."""
        # `int(round(...))` rather than a bare `round(...)`: byte-parity with the
        # sg13g2-bandgap precedent this module ports (`BuilderBase._u`), and an
        # explicit statement that the dbu type is integral.
        return int(round(value_um / self.layout.dbu))  # noqa: RUF046

    def box(
        self,
        layer: Layer,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        cell: kdb.Cell | None = None,
    ) -> None:
        """Axis-aligned rectangle on ``layer``, corners in microns (any order)."""
        target = self.cell if cell is None else cell
        target.shapes(self._layer_index(layer)).insert(
            kdb.Box(
                self._u(min(x0, x1)),
                self._u(min(y0, y1)),
                self._u(max(x0, x1)),
                self._u(max(y0, y1)),
            )
        )

    def polygon(self, layer: Layer, poly: kdb.Polygon) -> None:
        """Arbitrary polygon on ``layer``, in **database units** as-is.

        For assembly-level overlays derived from a placed stream's own
        geometry (e.g. the tap-implant bands this block draws over the
        generated guard rings): the caller computes the polygon in KLayout's
        own coordinate system, so no micron conversion happens here.
        """
        self.cell.shapes(self._layer_index(layer)).insert(poly)

    def label(self, text: str, x: float, y: float, layer: Layer = L_TEXT) -> None:
        """Documentation text on ``layer`` (``TEXT`` 63/0 by default).

        Text is *not* a pin: LVS pin labelling is out of this scaffold's scope
        (see ``layout/README.md``'s scope note).
        """
        self.cell.shapes(self._layer_index(layer)).insert(
            kdb.Text(text, kdb.Trans(kdb.Vector(self._u(x), self._u(y))))
        )

    def pr_boundary(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Place-and-route boundary rectangle (``prBoundary`` 189/0)."""
        self.box(L_PRBOUNDARY, x0, y0, x1, y1)

    def bbox_um(self) -> tuple[float, float, float, float]:
        """Top cell bounding box in microns."""
        b = self.cell.bbox()
        d = self.layout.dbu
        return (b.left * d, b.bottom * d, b.right * d, b.top * d)

    def write(self, path: str | Path) -> None:
        """Write GDS **without** timestamp records, so bytes are reproducible."""
        opts = kdb.SaveLayoutOptions()
        opts.gds2_write_timestamps = False
        self.layout.write(str(path), opts)

    # -------------------------------------------------------------- placing --
    def place_stream(
        self,
        gds_path: str | Path,
        cell_name: str,
        x: float,
        y: float,
        source_top: str | None = None,
    ) -> Placed:
        """Import a GDS stream as a flat sub-cell and instantiate it.

        ``x``/``y`` position the imported geometry's **bounding-box lower-left
        corner**, in microns -- not its coordinate origin, which for a
        ``klt gen`` stream is an interior point of the device and therefore
        useless for floorplanning.

        The source top cell is flattened on import so the resulting stream has
        exactly two levels (assembly top + one cell per placed device) and no
        generator-internal cell names leak in with ``$1`` disambiguation
        suffixes.
        """
        src = kdb.Layout()
        src.read(str(gds_path))
        if source_top is None:
            tops = list(src.top_cells())
            if len(tops) != 1:
                raise ValueError(
                    f"{gds_path} has {len(tops)} top cells "
                    f"({[c.name for c in tops]}); pass source_top=..."
                )
            top = tops[0]
        else:
            top = src.cell(source_top)
            if top is None:
                raise ValueError(f"{gds_path} has no cell named {source_top!r}")
        if src.dbu != self.layout.dbu:
            raise ValueError(
                f"{gds_path} has dbu={src.dbu}, assembly has {self.layout.dbu}"
            )
        top.flatten(-1, True)

        sub = self.layout.create_cell(cell_name)
        for li in src.layer_indexes():
            info = src.get_info(li)
            dest = self._layer_index((info.layer, info.datatype))
            for shape in top.shapes(li).each():
                if shape.is_text():
                    sub.shapes(dest).insert(shape.text)
                else:
                    sub.shapes(dest).insert(shape.polygon)

        b = sub.bbox()
        dx = self._u(x) - b.left
        dy = self._u(y) - b.bottom
        self.cell.insert(
            kdb.CellInstArray(sub.cell_index(), kdb.Trans(kdb.Vector(dx, dy)))
        )
        d = self.layout.dbu

        def shifted(box: kdb.Box) -> tuple[float, float, float, float]:
            return (
                (box.left + dx) * d,
                (box.bottom + dy) * d,
                (box.right + dx) * d,
                (box.top + dy) * d,
            )

        layer_bbox: dict[Layer, tuple[float, float, float, float]] = {}
        for pair, idx in self._layers.items():
            lb = sub.bbox_per_layer(idx)
            if not lb.empty():
                layer_bbox[pair] = shifted(lb)
        return Placed(
            name=cell_name,
            x0=(b.left + dx) * d,
            y0=(b.bottom + dy) * d,
            x1=(b.right + dx) * d,
            y1=(b.top + dy) * d,
            layer_bbox=layer_bbox,
        )

    # -------------------------------------------------------------- routing --
    def _route_width(self, layer: Layer, width: float | None) -> float:
        if width is not None:
            return width
        explicit = DEFAULT_ROUTE_WIDTH_UM.get(layer)
        if explicit is not None:
            return explicit
        name = LAYER_NAMES.get(layer, "")
        minimum = DECK_MIN_UM.get(f"{name.lower()}.width.1")
        if minimum is None:
            raise ValueError(
                f"no default routing width for layer {layer} ({name!r}): the "
                "curated deck transcribes no width rule for it -- pass width="
            )
        return 2.0 * minimum

    def route_h(
        self,
        layer: Layer,
        y_center: float,
        x0: float,
        x1: float,
        width: float | None = None,
    ) -> tuple[float, float, float, float]:
        """Horizontal bar on ``layer`` centred at ``y_center``, spanning
        ``[x0, x1]`` (order-independent). ``width`` defaults to twice the
        curated deck's minimum width for the layer. Returns the drawn box."""
        w = self._route_width(layer, width)
        half = w / 2.0
        box = (min(x0, x1), y_center - half, max(x0, x1), y_center + half)
        self.box(layer, *box)
        return box

    def route_v(
        self,
        layer: Layer,
        x_center: float,
        y0: float,
        y1: float,
        width: float | None = None,
    ) -> tuple[float, float, float, float]:
        """Vertical counterpart of :meth:`route_h`."""
        w = self._route_width(layer, width)
        half = w / 2.0
        box = (x_center - half, min(y0, y1), x_center + half, max(y0, y1))
        self.box(layer, *box)
        return box

    # ------------------------------------------------------------ cuts/vias --
    def cut_array(
        self,
        cut_layer: Layer,
        x_center: float,
        y_center: float,
        rows: int = 1,
        cols: int = 1,
        cell: kdb.Cell | None = None,
    ) -> tuple[float, float, float, float]:
        """A ``rows`` x ``cols`` array of minimum-size cuts on ``cut_layer``,
        centred on ``(x_center, y_center)``, pitched at cut size plus the
        curated deck's minimum cut spacing. Returns the array's bounding box.

        Cut size is the deck's own minimum width for the layer
        (:data:`sg13g2_layers.CUT_SIZE_UM`): SG13G2's cuts are fixed-size
        squares, so drawing one larger is a different geometry, not a safer
        one.
        """
        if rows < 1 or cols < 1:
            raise ValueError(f"cut_array needs rows/cols >= 1, got {rows}x{cols}")
        size = CUT_SIZE_UM[cut_layer]
        name = LAYER_NAMES[cut_layer].lower()
        pitch = size + DECK_MIN_UM[f"{name}.space.1"]
        span_x = cols * size + (cols - 1) * (pitch - size)
        span_y = rows * size + (rows - 1) * (pitch - size)
        x_start = x_center - span_x / 2.0
        y_start = y_center - span_y / 2.0
        for r in range(rows):
            for c in range(cols):
                x = x_start + c * pitch
                y = y_start + r * pitch
                self.box(cut_layer, x, y, x + size, y + size, cell=cell)
        return (x_start, y_start, x_start + span_x, y_start + span_y)

    def landing_pad(
        self,
        metal: Layer,
        cut: Layer,
        cuts: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        """A via landing pad on ``metal`` over the cut bounding box ``cuts``.

        Sized from the curated deck alone, per metal, in two steps:

        1. enclose the cuts by that metal's own
           ``<metal>.enclosing.<cut>.1`` minimum plus
           :data:`CUT_ENCLOSURE_MARGIN_UM` (or by
           :data:`DEFAULT_CUT_ENCLOSURE_UM` where the deck transcribes no such
           rule);
        2. grow the result symmetrically until it also clears that metal's
           ``<metal>.width.1`` minimum in both axes.

        **Per metal** matters: the two metals a via joins can demand wildly
        different geometry on this PDK. Metal5 need only enclose TopVia1 by
        0.10 um (``metal5.enclosing.topvia1.1``) while TopMetal1 must enclose
        the same cut by 0.42 um (``topmetal1.enclosing.topvia1.1``) *and* be
        at least 1.64 um wide (``topmetal1.width.1``) -- a single shared pad
        sized off the lower metal violates both of the upper metal's rules.
        """
        cx0, cy0, cx1, cy1 = cuts
        metal_name = LAYER_NAMES[metal].lower()
        cut_name = LAYER_NAMES[cut].lower()
        rule = DECK_MIN_UM.get(f"{metal_name}.enclosing.{cut_name}.1")
        enc = (
            rule + CUT_ENCLOSURE_MARGIN_UM
            if rule is not None
            else DEFAULT_CUT_ENCLOSURE_UM
        )
        x0, y0, x1, y1 = (cx0 - enc, cy0 - enc, cx1 + enc, cy1 + enc)
        min_w = DECK_MIN_UM.get(f"{metal_name}.width.1")
        if min_w is not None:
            grow_x = max(0.0, (min_w - (x1 - x0)) / 2.0)
            grow_y = max(0.0, (min_w - (y1 - y0)) / 2.0)
            x0, y0, x1, y1 = (x0 - grow_x, y0 - grow_y, x1 + grow_x, y1 + grow_y)
        self.box(metal, x0, y0, x1, y1)
        return (x0, y0, x1, y1)

    def via(
        self,
        bottom: Layer,
        top: Layer,
        x_center: float,
        y_center: float,
        rows: int = 1,
        cols: int = 1,
    ) -> tuple[float, float, float, float]:
        """One via between two **adjacent** metal levels: the cut array plus a
        per-metal landing pad (see :meth:`landing_pad`) on each side.

        Returns the **larger** of the two landing pads, so a caller routing up
        to the via has one box that covers both levels' footprints. Raises if
        the two levels are not adjacent in :data:`sg13g2_layers.VIA_STACK` --
        a multi-level jump must be spelled out as a stack of adjacent vias, so
        the missing intermediate metal cannot be forgotten silently.
        """
        cut = next(
            (c for (b, c, t) in VIA_STACK if b == bottom and t == top),
            None,
        )
        if cut is None:
            raise ValueError(
                f"{LAYER_NAMES.get(bottom, bottom)} -> "
                f"{LAYER_NAMES.get(top, top)} is not an adjacent metal pair in "
                "sg13g2_layers.VIA_STACK; build the stack one level at a time"
            )
        cuts = self.cut_array(cut, x_center, y_center, rows, cols)
        pads = [self.landing_pad(m, cut, cuts) for m in (bottom, top)]
        return max(pads, key=lambda p: (p[2] - p[0]) * (p[3] - p[1]))

    def via_stack(
        self,
        bottom: Layer,
        top: Layer,
        x_center: float,
        y_center: float,
        rows: int = 1,
        cols: int = 1,
    ) -> tuple[float, float, float, float]:
        """Chain :meth:`via` across every level between ``bottom`` and ``top``.

        Returns the widest landing-pad box drawn (the coarse top levels'
        enclosures dominate).
        """
        levels = [b for (b, _c, _t) in VIA_STACK] + [VIA_STACK[-1][2]]
        try:
            lo, hi = levels.index(bottom), levels.index(top)
        except ValueError as exc:
            raise ValueError(
                f"via_stack endpoints must be routing metals in VIA_STACK: {exc}"
            ) from exc
        if hi <= lo:
            raise ValueError(
                f"via_stack needs bottom below top, got "
                f"{LAYER_NAMES.get(bottom, bottom)} -> {LAYER_NAMES.get(top, top)}"
            )
        widest = (x_center, y_center, x_center, y_center)
        for i in range(lo, hi):
            pad = self.via(levels[i], levels[i + 1], x_center, y_center, rows, cols)
            if (pad[2] - pad[0]) > (widest[2] - widest[0]):
                widest = pad
        return widest

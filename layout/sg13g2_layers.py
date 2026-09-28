"""SG13G2 drawing-layer table and the curated-deck rule minima this repo's
layout code sizes geometry against.

Every ``(layer, datatype)`` pair below is transcribed from **IHP's own**
KLayout layer-property file shipped with the PDK:

    ``$PDK_ROOT/ihp-sg13g2/libs.tech/klayout/tech/sg13g2.lyp``

(read on 2026-09-28 from the IHP-Open-PDK ``v0.3.0`` install this repo's
``sim/pdk.json`` pins for its evidence records: ``release_tag: v0.3.0``,
``variant: ihp-sg13g2``). Each ``.lyp`` entry is cited by its own
``<name>``/``<source>`` pair, e.g. ``'Metal1.drawing' 8/0``. The routing
stack is additionally cross-checked against the same install's GDS
stream-out layer map, ``libs.tech/klayout/tech/sg13g2.map`` (e.g.
``Metal1 NET,SPNET,PIN,LEFPIN,VIA 8 0``), noted inline where it applies.

Every pair that the curated deck *also* declares is additionally
cross-checked against klayout-tools' own ``sg13g2`` deck --
``klayout_tools/decks/sg13g2.py``'s ``LAYER_NAMES`` and
``EXTRACTION_DECK`` tables -- because that deck is what ``klt drc --deck
sg13g2`` actually reads, so a disagreement between the PDK's ``.lyp`` and
the deck would silently produce geometry the checker cannot see. Where a
pair appears in the ``.lyp`` but *not* in the curated deck, the comment
says so explicitly rather than implying a cross-check that did not happen.

**Nothing here is copied from a sibling PDK.** IHP's numbering is unrelated
to gf180mcu's and sky130's: SG13G2 puts Metal1 on ``8/0``, Via1 on ``19/0``
and Metal2 on ``10/0`` -- i.e. the via between Metal1 and Metal2 carries a
*higher* layer number than Metal2 itself, which is exactly the kind of
ordering assumption a cross-PDK copy gets wrong.

Provenance of the rule minima in :data:`DECK_MIN_UM`: they are the values
``klt deck rules --deck sg13g2 --format json`` reports for klayout-tools'
curated SG13G2 deck, each of which that deck in turn cites back to an
official IHP rule id in
``ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/{feol,beol}/*.drc``.
The inline comment on each entry carries that official rule id.
:func:`verify_deck_minima` re-derives the whole table from the installed
``klt`` and raises on any drift, so a deck bump cannot silently invalidate
geometry sized against these constants.
"""

from __future__ import annotations

import json
import subprocess

Layer = tuple[int, int]

# --------------------------------------------------------------------------- #
# FEOL
# --------------------------------------------------------------------------- #
#: Diffusion / active area. Also the *only* tap mask SG13G2 has: unlike
#: sky130 the PDK draws no distinct well/substrate-tie layer and derives
#: ``ntap``/``ptap`` from this same layer (see klayout-tools'
#: ``decks/sg13g2.py``: ``EXTRACTION_DECK.tap is None``).
L_ACTIV: Layer = (1, 0)  # sg13g2.lyp 'Activ.drawing'; deck LAYER_NAMES (1,0)
#: Gate / interconnect polysilicon.
L_GATPOLY: Layer = (5, 0)  # sg13g2.lyp 'GatPoly.drawing'; deck (5,0)
#: n+ source/drain implant (NMOS S/D, n-well tie).
L_NSD: Layer = (7, 0)  # sg13g2.lyp 'nSD.drawing'
#: p+ source/drain implant (PMOS S/D, substrate tie).
L_PSD: Layer = (14, 0)  # sg13g2.lyp 'pSD.drawing'
#: n-well. PMOS bodies and n-well taps sit inside one of these.
L_NWELL: Layer = (31, 0)  # sg13g2.lyp 'NWell.drawing'; deck EXTRACTION_DECK.nwell
#: Thick-gate-oxide ("HV" device) marker. Deliberately **never drawn** by
#: this repo: the block is an LV-core-MOS design (see
#: ``design/netlist/opamp_core.spice`` -- ``sg13_lv_nmos``/``sg13_lv_pmos``
#: only). Named here so a future reader can see the omission is a choice.
L_THICKGATEOX: Layer = (44, 0)  # sg13g2.lyp 'ThickGateOx.drawing'
#: Contact (Activ/GatPoly -> Metal1).
L_CONT: Layer = (6, 0)  # sg13g2.lyp 'Cont.drawing'; deck (6,0)

# --------------------------------------------------------------------------- #
# BEOL routing stack. Note the non-monotonic numbering (see module docstring).
# --------------------------------------------------------------------------- #
L_METAL1: Layer = (8, 0)  # sg13g2.lyp 'Metal1.drawing'; sg13g2.map Metal1 8 0
L_VIA1: Layer = (19, 0)  # sg13g2.lyp 'Via1.drawing'; sg13g2.map Via1 19 0
L_METAL2: Layer = (10, 0)  # sg13g2.lyp 'Metal2.drawing'; sg13g2.map Metal2 10 0
L_VIA2: Layer = (29, 0)  # sg13g2.lyp 'Via2.drawing'; sg13g2.map Via2 29 0
L_METAL3: Layer = (30, 0)  # sg13g2.lyp 'Metal3.drawing'; sg13g2.map Metal3 30 0
L_VIA3: Layer = (49, 0)  # sg13g2.lyp 'Via3.drawing'
L_METAL4: Layer = (50, 0)  # sg13g2.lyp 'Metal4.drawing'
L_VIA4: Layer = (66, 0)  # sg13g2.lyp 'Via4.drawing'
L_METAL5: Layer = (67, 0)  # sg13g2.lyp 'Metal5.drawing'; MIM bottom plate
L_TOPVIA1: Layer = (125, 0)  # sg13g2.lyp 'TopVia1.drawing'
L_TOPMETAL1: Layer = (126, 0)  # sg13g2.lyp 'TopMetal1.drawing'; MIM top routing
L_TOPVIA2: Layer = (133, 0)  # sg13g2.lyp 'TopVia2.drawing'
L_TOPMETAL2: Layer = (134, 0)  # sg13g2.lyp 'TopMetal2.drawing'

# --------------------------------------------------------------------------- #
# MIM capacitor (cap_cmim). The bottom plate is ``Metal5`` (67/0) above, the
# top plate ``MIM`` (36/0), and the via up from the top plate to ``TopMetal1``
# (126/0) is ``Vmim`` (129/0) -- a cut layer of its own, distinct from the
# ``TopVia1`` (125/0) that bridges Metal5 -> TopMetal1 in ordinary routing.
# All four are transcribed from the curated deck's own
# ``EXTRACTION_DECK.capacitors[0]`` ('cap_cmim': ``top_plate=(36, 0)``,
# ``bottom_plate=(67, 0)``, ``top_plate_via=(129, 0)``,
# ``top_plate_via_metal=(126, 0)``) and cross-checked against sg13g2.lyp.
# Note upstream's own recognition term joins *both* cut layers
# (``mim_via = vmim_drw.join(topvia1_drw).and(mim_drw)``, quoted in that
# deck's source), so TopVia1 on a MIM plate is legal too -- Vmim is what
# ``klt gen cap_array`` actually draws on this family, which is why the
# scaffold names it.
# --------------------------------------------------------------------------- #
L_MIM: Layer = (36, 0)  # sg13g2.lyp 'MIM.drawing'; deck cap_cmim.top_plate
L_VMIM: Layer = (129, 0)  # sg13g2.lyp 'Vmim.drawing'; deck cap_cmim.top_plate_via

# --------------------------------------------------------------------------- #
# Non-drawing / documentation layers. Neither appears in the curated sg13g2
# deck's LAYER_NAMES or EXTRACTION_DECK, so neither is cross-checked against
# it -- both come from sg13g2.lyp alone, and `klt drc --deck sg13g2` reports
# them under coverage.layers_in_stream_without_rules (disclosed in
# layout/README.md).
# --------------------------------------------------------------------------- #
L_TEXT: Layer = (63, 0)  # sg13g2.lyp 'TEXT.drawing'; not in curated deck
L_PRBOUNDARY: Layer = (189, 0)  # sg13g2.lyp 'prBoundary.drawing'; not in deck

# --------------------------------------------------------------------------- #
# Net-naming text layers: the ``metal_labels`` entries of the curated deck's
# ``EXTRACTION_DECK`` -- the layers ``klt extract``/``klt lvs`` actually read
# to give an extracted net a name (a label anywhere on a metal net, on this
# layer, names that net). Transcribed from ``decks/sg13g2.py``'s
# ``metal_labels = ((8, 25), (10, 25), (30, 25), (50, 25), (67, 25),
# (126, 25), (134, 25))``. A label on the *drawing* layer (e.g. Metal3 30/0)
# or on ``TEXT`` 63/0 names nothing -- extraction ignores both -- which is
# why the port pins carry a third label on the routing layer's text purpose
# (see ``generate.Router.pin``).
# --------------------------------------------------------------------------- #
L_METAL3_TEXT: Layer = (30, 25)  # sg13g2.lyp 'Metal3.text'; deck metal_labels[2]

#: Names attached to each layer index in written streams, so ``klt layers``
#: and a KLayout session both show human-readable names without needing the
#: PDK's ``.lyp`` loaded.
LAYER_NAMES: dict[Layer, str] = {
    L_ACTIV: "Activ",
    L_GATPOLY: "GatPoly",
    L_NSD: "nSD",
    L_PSD: "pSD",
    L_NWELL: "NWell",
    L_CONT: "Cont",
    L_METAL1: "Metal1",
    L_VIA1: "Via1",
    L_METAL2: "Metal2",
    L_VIA2: "Via2",
    L_METAL3: "Metal3",
    L_VIA3: "Via3",
    L_METAL4: "Metal4",
    L_VIA4: "Via4",
    L_METAL5: "Metal5",
    L_TOPVIA1: "TopVia1",
    L_TOPMETAL1: "TopMetal1",
    L_TOPVIA2: "TopVia2",
    L_TOPMETAL2: "TopMetal2",
    L_MIM: "MIM",
    L_VMIM: "Vmim",
    L_TEXT: "TEXT",
    L_METAL3_TEXT: "Metal3.text",
    L_PRBOUNDARY: "prBoundary",
}

#: Via/contact cut sizes, in microns. SG13G2's cuts are fixed-size squares;
#: these are the curated deck's own minimum-width values for each cut layer
#: (a cut drawn *larger* than minimum is a different device geometry in the
#: PDK's own PCells, so the scaffold draws exactly minimum).
CUT_SIZE_UM: dict[Layer, float] = {
    L_CONT: 0.16,  # Cnt.a
    L_VIA1: 0.19,  # V1.a
    L_VIA2: 0.19,  # V2.a
    L_VIA3: 0.19,  # V3.a
    L_VIA4: 0.19,  # V4.a
    L_TOPVIA1: 0.42,  # TV1.a
    L_TOPVIA2: 0.90,  # TV2.a
}

#: Which cut layer bridges each adjacent metal pair, lowest level first.
VIA_STACK: list[tuple[Layer, Layer, Layer]] = [
    (L_METAL1, L_VIA1, L_METAL2),
    (L_METAL2, L_VIA2, L_METAL3),
    (L_METAL3, L_VIA3, L_METAL4),
    (L_METAL4, L_VIA4, L_METAL5),
    (L_METAL5, L_TOPVIA1, L_TOPMETAL1),
    (L_TOPMETAL1, L_TOPVIA2, L_TOPMETAL2),
]

#: Every rule minimum (microns) klayout-tools' curated ``sg13g2`` deck
#: enforces, keyed by the deck's own rule id. The comment on each line is the
#: official IHP rule id the deck cites. Re-derivable with
#: ``klt deck rules --deck sg13g2 --format json``; see
#: :func:`verify_deck_minima`.
DECK_MIN_UM: dict[str, float] = {
    "activ.width.1": 0.15,  # Act.a
    "activ.space.1": 0.21,  # Act.b
    "gatpoly.width.1": 0.13,  # Gat.a
    "gatpoly.space.1": 0.18,  # Gat.b
    "gatpoly.separation.activ.1": 0.07,  # Gat.d
    "cont.width.1": 0.16,  # Cnt.a
    "cont.space.1": 0.18,  # Cnt.b
    "activ.enclosing.cont.1": 0.07,  # Cnt.c
    "gatpoly.enclosing.cont.1": 0.07,  # Cnt.d
    "metal1.width.1": 0.16,  # M1.a
    "metal1.space.1": 0.18,  # M1.b
    "via1.width.1": 0.19,  # V1.a
    "via1.space.1": 0.22,  # V1.b
    "metal1.enclosing.via1.1": 0.01,  # V1.c
    "metal2.width.1": 0.20,  # M2.a
    "metal2.space.1": 0.21,  # M2.b
    "via2.width.1": 0.19,  # V2.a
    "via2.space.1": 0.22,  # V2.b
    "metal2.enclosing.via2.1": 0.005,  # V2.c
    "metal3.width.1": 0.20,  # M3.a
    "metal3.space.1": 0.21,  # M3.b
    "via3.width.1": 0.19,  # V3.a
    "via3.space.1": 0.22,  # V3.b
    "metal3.enclosing.via3.1": 0.005,  # V3.c
    "metal4.width.1": 0.20,  # M4.a
    "metal4.space.1": 0.21,  # M4.b
    "via4.width.1": 0.19,  # V4.a
    "via4.space.1": 0.22,  # V4.b
    "metal4.enclosing.via4.1": 0.005,  # V4.c
    "metal5.width.1": 0.20,  # M5.a
    "metal5.space.1": 0.21,  # M5.b
    "topvia1.width.1": 0.42,  # TV1.a
    "topvia1.space.1": 0.42,  # TV1.b
    "metal5.enclosing.topvia1.1": 0.10,  # TV1.c
    "topmetal1.enclosing.topvia1.1": 0.42,  # TV1.d
    "topmetal1.width.1": 1.64,  # TM1.a
    "topmetal1.space.1": 1.64,  # TM1.b
    "topvia2.width.1": 0.90,  # TV2.a
    "topvia2.space.1": 1.06,  # TV2.b
    "topmetal1.enclosing.topvia2.1": 0.50,  # TV2.c
    "topmetal2.enclosing.topvia2.1": 0.50,  # TV2.d
    "topmetal2.width.1": 2.00,  # TM2.a
    "topmetal2.space.1": 2.00,  # TM2.b
}

#: Deck content hash :data:`DECK_MIN_UM` was transcribed from, so a drift
#: report can name both sides. From ``klt deck hash --deck sg13g2``.
DECK_CONTENT_HASH = (
    "sha256:894326a4e37fb24fef2f7ffc6ae1da55a0e262b0f0bc1c09adc4862909278fda"
)


def verify_deck_minima(klt: str = "klt") -> dict[str, object]:
    """Re-derive :data:`DECK_MIN_UM` from the installed ``klt`` and raise on
    any drift.

    This is the machine-checked half of the transcription above: a deck
    revision that tightens a rule this scaffold sized geometry against must
    fail a regeneration loudly rather than leave a stale constant in place.

    Returns the installed deck's content hash and rule count. Raises
    ``AssertionError`` on any missing/extra/changed rule value, and
    ``RuntimeError`` if ``klt`` is not runnable.
    """
    try:
        raw = subprocess.run(
            [klt, "deck", "rules", "--deck", "sg13g2", "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        raise RuntimeError(
            f"could not run `{klt} deck rules --deck sg13g2`: {exc}"
        ) from exc
    report = json.loads(raw)
    installed = {r["id"]: r["value_um"] for r in report["rules"]}

    drift: list[str] = []
    for rule_id, value in sorted(DECK_MIN_UM.items()):
        if rule_id not in installed:
            drift.append(
                f"{rule_id}: transcribed {value} um, absent from installed deck"
            )
        elif installed[rule_id] != value:
            drift.append(
                f"{rule_id}: transcribed {value} um, installed deck says "
                f"{installed[rule_id]} um"
            )
    for rule_id in sorted(set(installed) - set(DECK_MIN_UM)):
        drift.append(
            f"{rule_id}: installed deck enforces {installed[rule_id]} um, "
            "not transcribed in DECK_MIN_UM"
        )
    if drift:
        raise AssertionError(
            "sg13g2_layers.DECK_MIN_UM has drifted from the installed curated "
            f"deck (transcribed from {DECK_CONTENT_HASH}, installed "
            f"{report['content_hash']}):\n  " + "\n  ".join(drift)
        )
    return {
        "content_hash": report["content_hash"],
        "rule_count": len(installed),
    }

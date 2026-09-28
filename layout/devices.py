"""Device primitives for this block's three shapes, as ``klt gen`` wrappers.

``design/netlist/opamp_core.spice`` instantiates exactly three device
flavours -- ``sg13_lv_nmos``, ``sg13_lv_pmos`` and ``cap_cmim`` -- and this
module is the one place that turns each into drawn geometry. It does so by
invoking ``klt gen`` rather than drawing the devices by hand:

* ``sg13_lv_nmos`` / ``sg13_lv_pmos`` -> ``klt gen mos_array`` with
  ``flavor="nfet"`` / ``"pfet"``;
* ``cap_cmim`` -> ``klt gen cap_array``.

**Why generators and not hand-drawn primitives.** Verified on this host
against ``klt 0.6.0+g9c11986ad447`` on 2026-09-28: all three of those
generator invocations resolve the ``ihp-sg13g2`` family and draw this PDK's
own layer numbers -- ``mos_array`` draws ``Activ`` (1/0), ``GatPoly`` (5/0),
``Cont`` (6/0), ``Metal1`` (8/0) and, for ``flavor="pfet"``, ``NWell``
(31/0); ``cap_array`` draws ``MIM`` (36/0) over ``Metal5`` (67/0) with a
``Vmim`` (129/0) via up to ``TopMetal1`` (126/0), exactly the four layers the
curated deck's ``cap_cmim`` device class names. Each of the three streams is
independently ``klt drc --deck sg13g2`` clean. Device geometry is therefore
the part of this scaffold that does **not** need to be derived by hand, so it
isn't.

**What that claim is worth, and what it is not.** "Clean" above means clean
under **klayout-tools' own curated ``sg13g2`` starter deck** -- 43 rules --
not under IHP's signoff deck, which emits 111 distinct rule ids (plus its
templated ``M2..M5``/``V2..V4`` families) from
``libs.tech/klayout/tech/drc/rule_decks/``. This is not a theoretical gap:
``cap_array``'s sg13g2 output draws ``Metal5`` enclosing ``MIM`` by 0.50 um,
and IHP's own ``MIM.c`` requires 0.60 um (``rule_decks/beol/6_11_mim.drc``,
``Mim_c = 0.6`` in ``rule_decks/sg13g2_tech_default.json``). The curated deck
carries **no MIM rules at all**, so it cannot see it.
:data:`MIM_METAL5_ENCLOSURE_UM` records that rule so the caller can patch the
bottom plate; ``layout/README.md`` states the caveat in full. Nothing here is
a signoff claim.

``klt`` is invoked as a subprocess, not imported: this repo pins a *deck*
revision, not a Python API, and the CLI's JSON report is the documented,
schema-versioned contract (``schema_version``, ``provenance``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: PDK variant every generator call resolves. Matches ``sim/env.sh``'s own
#: ``PDK="${PDK:-ihp-sg13g2}"`` and ``sim/pdk.json``'s ``variant``.
PDK_VARIANT = "ihp-sg13g2"

#: Where to look for the PDK install when ``$PDK_ROOT`` is unset -- the same
#: candidate list, in the same order, that ``sim/env.sh`` searches, so a
#: layout regen and a testbench run cannot silently disagree about which
#: install is in use. ``klt pdk find`` also searches ``~/share/pdk`` on its
#: own, so an empty result here is not fatal.
PDK_ROOT_CANDIDATES = (
    "/usr/share/pdk",
    "/usr/local/share/pdk",
    "~/share/pdk",
    "~/.ciel",
    "~/.volare",
)

#: IHP's ``MIM.c``: minimum ``Metal5`` enclosure of ``MIM``, in microns.
#: Transcribed from the PDK's own signoff deck --
#: ``libs.tech/klayout/tech/drc/rule_decks/beol/6_11_mim.drc`` ("Rule MIM.c:
#: Min. Metal5 enclosure of MIM is 0.60 um"), value
#: ``drc_rules/Mim_c = 0.6`` in that deck's
#: ``rule_decks/sg13g2_tech_default.json``. **Not** in klayout-tools' curated
#: ``sg13g2`` deck, which transcribes no MIM rule, so no ``klt drc`` run in
#: this repo checks it -- it is here because ``klt gen cap_array`` draws only
#: 0.50 um and a caller that wants to clear IHP's rule has to widen the
#: bottom plate itself.
MIM_METAL5_ENCLOSURE_UM = 0.60

#: What ``klt gen cap_array`` actually draws for that enclosure, in microns
#: (measured from its own stream, klt 0.6.0+g9c11986ad447). Kept next to the
#: rule so the shortfall is arithmetic in the source, not prose in a README.
CAP_ARRAY_METAL5_ENCLOSURE_UM = 0.50


@dataclass(frozen=True)
class GeneratedDevice:
    """One ``klt gen`` invocation's result: the stream plus its report."""

    kind: str
    """Netlist device flavour drawn: ``sg13_lv_nmos``, ``sg13_lv_pmos`` or
    ``cap_cmim``."""

    generator: str
    """``klt gen`` generator name (``mos_array`` / ``cap_array``)."""

    params: dict[str, object]
    """Params object passed to ``--params``, verbatim."""

    gds_path: Path
    """Stream ``klt gen`` wrote."""

    cell_name: str
    """Top cell inside that stream."""

    report: dict
    """Parsed ``--format json`` report (``schema_version``, ``bbox_um``,
    ``ports``, ``drc_hints``, ``provenance``, ...)."""

    @property
    def klt_version(self) -> str:
        return str(self.report["provenance"]["klt_version"])

    @property
    def bbox_um(self) -> tuple[float, float, float, float]:
        b = self.report["bbox_um"]
        return (b["x0"], b["y0"], b["x1"], b["y1"])


def resolve_pdk_root() -> str | None:
    """``$PDK_ROOT`` if set, else the first candidate holding this variant."""
    env = os.environ.get("PDK_ROOT")
    if env:
        return env
    for candidate in PDK_ROOT_CANDIDATES:
        root = Path(candidate).expanduser()
        if (root / PDK_VARIANT / "libs.tech" / "klayout").is_dir():
            return str(root)
    return None


def require_klt(klt: str = "klt") -> str:
    """Absolute path to the ``klt`` executable, or a clear failure."""
    found = shutil.which(klt)
    if found is None:
        raise RuntimeError(
            f"{klt!r} is not on PATH. This scaffold drives device geometry "
            "through `klt gen`; install klayout-tools (see layout/README.md's "
            "'Regenerating' section) rather than hand-drawing the devices."
        )
    return found


def run_gen(
    generator: str,
    params: dict[str, object],
    out_gds: Path,
    cell_name: str,
    klt: str = "klt",
) -> dict:
    """Run one ``klt gen`` generator against the ``ihp-sg13g2`` PDK.

    Returns the parsed JSON report. Raises on a non-zero exit, on a report
    that is not JSON, and on any generator ``warnings`` -- a warning from a
    device generator is a statement that the drawn geometry is not what the
    params asked for, which must never pass silently into a committed GDS.
    """
    out_gds.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        require_klt(klt),
        "gen",
        generator,
        "--pdk",
        PDK_VARIANT,
        "--params",
        json.dumps(params, sort_keys=True),
        "--cell-name",
        cell_name,
        "-o",
        str(out_gds),
        "--format",
        "json",
    ]
    pdk_root = resolve_pdk_root()
    if pdk_root is not None:
        argv += ["--pdk-root", pdk_root]

    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"`klt gen {generator}` failed (exit {proc.returncode}):\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"`klt gen {generator}` did not emit JSON: {exc}\n{proc.stdout[:2000]}"
        ) from exc
    if report.get("warnings"):
        raise RuntimeError(
            f"`klt gen {generator}` warned, so the drawn geometry is not what "
            f"the params asked for: {report['warnings']}"
        )
    resolved = report.get("pdk", {}).get("variant")
    if resolved != PDK_VARIANT:
        raise RuntimeError(
            f"`klt gen {generator}` resolved PDK variant {resolved!r}, not "
            f"{PDK_VARIANT!r}; a sibling PDK's layer numbers would be drawn. "
            "Set $PDK_ROOT to an install containing ihp-sg13g2."
        )
    return report


# --------------------------------------------------------------------------- #
# The three device shapes
# --------------------------------------------------------------------------- #
def _mos(
    kind: str,
    flavor: str,
    w_um: float,
    l_um: float,
    cell_name: str,
    out_dir: Path,
    klt: str = "klt",
) -> GeneratedDevice:
    # rows=cols=1, dummy=0: this scaffold's job is to prove the *shape* is
    # legal at the netlist's sizes. Matched-array topology (common-centroid
    # rows/cols, dummy columns) is a floorplanning decision that belongs to
    # the op-amp layout itself (issue #45), not to the scaffold, and enabling
    # it here would bake a placement choice into a smoke fixture.
    params: dict[str, object] = {
        "w_um": w_um,
        "l_um": l_um,
        "rows": 1,
        "cols": 1,
        "dummy": 0,
        "flavor": flavor,
        "gate_contact": True,
    }
    gds = out_dir / f"{cell_name}.gds"
    report = run_gen("mos_array", params, gds, cell_name, klt=klt)
    return GeneratedDevice(
        kind=kind,
        generator="mos_array",
        params=params,
        gds_path=gds,
        cell_name=cell_name,
        report=report,
    )


def lv_nmos(
    w_um: float, l_um: float, cell_name: str, out_dir: Path, klt: str = "klt"
) -> GeneratedDevice:
    """``sg13_lv_nmos``: ``Activ`` + ``GatPoly`` with no ``NWell``.

    That absence *is* the device recognition: the curated deck's ``nfet``
    class requires ``Activ`` (1/0) and ``GatPoly`` (5/0) and **excludes**
    ``NWell`` (31/0) on both terminals (``klt deck devices --deck sg13g2``),
    mirroring IHP's own ``mos_extraction.lvs`` derivation of
    ``sg13_lv_nmos``.
    """
    return _mos("sg13_lv_nmos", "nfet", w_um, l_um, cell_name, out_dir, klt=klt)


def lv_pmos(
    w_um: float, l_um: float, cell_name: str, out_dir: Path, klt: str = "klt"
) -> GeneratedDevice:
    """``sg13_lv_pmos``: the same stack, enclosed in an ``NWell`` (31/0).

    The well is drawn by the generator (``flavor="pfet"``), and it is the only
    thing distinguishing this from :func:`lv_nmos` in the curated deck's
    ``pfet`` class -- which *requires* ``NWell`` on both terminals. Note the
    curated deck transcribes **no** ``NWell`` rule of any kind, so a
    ``klt drc --deck sg13g2`` pass says nothing about the well; IHP's own deck
    emits four (``NW.b``, ``NW.b1``, ``NW.f1``, ``NW.f1.digibnd``). See
    ``layout/README.md``'s coverage disclosure.
    """
    return _mos("sg13_lv_pmos", "pfet", w_um, l_um, cell_name, out_dir, klt=klt)


def cmim_cap(
    w_um: float, l_um: float, cell_name: str, out_dir: Path, klt: str = "klt"
) -> GeneratedDevice:
    """``cap_cmim``: one ``MIM`` (36/0) plate over ``Metal5`` (67/0).

    The netlist gives ``XCc`` as ``w=25.7u l=25.7u``; ``cap_array``'s params
    call the same two dimensions ``plate_w_um``/``plate_h_um``, and ``num=1``
    because ``XCc`` is a single unit cap, not a matched bank.
    """
    params: dict[str, object] = {
        "plate_w_um": w_um,
        "plate_h_um": l_um,
        "num": 1,
    }
    gds = out_dir / f"{cell_name}.gds"
    report = run_gen("cap_array", params, gds, cell_name, klt=klt)
    return GeneratedDevice(
        kind="cap_cmim",
        generator="cap_array",
        params=params,
        gds_path=gds,
        cell_name=cell_name,
        report=report,
    )

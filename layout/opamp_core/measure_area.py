#!/usr/bin/env python3
"""Reproducible GDS bounding-box area measurement for TBD-12 (PROPOSED).

Measures the hierarchical geometry bounding box of one *named* cell of a GDS
and emits a deterministic JSON record.  Offline: reads the committed GDS with
`klayout.db`, never regenerates it, needs no PDK, klt or simulator.

Definition `opamp-core-hier-bbox-v1` (see spec/decision-records/
0007-area-definition.md, status "proposed -- not ratified"):

  * the cell is selected by name (never "the first top cell");
  * the box is the union of the bounding boxes of every geometric shape on
    every layer/datatype, recursively through all instances, including
    instance transformations (rotation, reflection, magnification) and
    regular arrays;
  * boxes, polygons and paths all count (boundary/outline layers included);
    a path counts with its drawn width and end extensions;
  * text labels never count; layers holding only text contribute nothing;
  * only geometry under the named cell contributes (sibling top cells and
    unreferenced cells do not);
  * all arithmetic is integer database units (DBU); the area is the product
    of integer width and height, converted to um^2 and mm^2 by exact decimal
    arithmetic (1 um^2 = dbu_um^2 * DBU^2; 1 mm^2 = 1,000,000 um^2) with no
    rounding.

This is a geometry bounding box.  It is not a legal placement boundary, a
pad-ring footprint, a keepout budget or an area target.

Usage (from anywhere):
  measure_area.py                 print the measurement JSON to stdout
  measure_area.py --write         (re)write layout/opamp_core/area_measurement.json
  measure_area.py --check         re-derive and compare; NEVER writes
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_GDS = "layout/opamp_core/opamp_core.gds"
DEFAULT_RECORD = HERE / "area_measurement.json"
DEFAULT_CELL = "opamp_core"
DEFINITION_ID = "opamp-core-hier-bbox-v1"
SCHEMA = "sg13g2-opamp/area-measurement/1"

DEFINITION_RULES = [
    "named cell only; sibling top cells and unreferenced cells excluded",
    "recursive through instances incl. rotation, reflection and arrays",
    "all layers/datatypes with geometry; boxes, polygons and paths count",
    "text labels excluded; text-only layers contribute nothing",
    "integer-DBU box; area = integer width * integer height",
    "um^2 = DBU product * dbu_um^2 and mm^2 = um^2 / 1e6, exact decimal, unrounded",
]


class MeasureError(Exception):
    """A clear, user-facing failure (bad input or drift)."""


def _kdb():
    try:
        import klayout.db as kdb
    except ImportError as e:  # pragma: no cover
        raise MeasureError(
            "python module 'klayout' is not installed (pip install klayout)"
        ) from e
    return kdb


def _dec(d: Decimal) -> str:
    """Exact, plain (non-exponent) decimal string."""
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    p = path.resolve()
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError as e:
        raise MeasureError(
            f"GDS {p} is outside the repo; a repo-relative path is required "
            "for a portable record"
        ) from e


def measure(gds: Path, cell_name: str = DEFAULT_CELL, rel_path: str | None = None) -> dict:
    """Return the measurement record (a plain dict) for `cell_name` in `gds`."""
    kdb = _kdb()
    if not gds.is_file():
        raise MeasureError(f"GDS not found: {rel_path or gds.name}")
    digest = sha256_file(gds)
    layout = kdb.Layout()
    try:
        layout.read(str(gds))
    except Exception as e:
        raise MeasureError(f"cannot read {gds.name} as GDS: {e}") from e

    dbu = layout.dbu
    if not (dbu > 0):
        raise MeasureError(f"nonpositive database unit {dbu!r} in {gds.name}")
    dbu_dec = Decimal(repr(float(dbu)))
    if dbu_dec <= 0:  # pragma: no cover - guarded above
        raise MeasureError(f"nonpositive database unit {dbu!r} in {gds.name}")

    cell = layout.cell(cell_name)
    if cell is None:
        names = sorted(c.name for c in layout.each_cell())
        raise MeasureError(
            f"cell {cell_name!r} not found in {gds.name} "
            f"(cells: {', '.join(names) or 'none'})"
        )

    box = kdb.Box()  # empty
    n_layers = 0
    for li in layout.layer_indexes():
        it = kdb.RecursiveShapeIterator(layout, cell, li)
        it.shape_flags = kdb.Shapes.SBoxes | kdb.Shapes.SPolygons | kdb.Shapes.SPaths
        region = kdb.Region(it)  # exact transformed polygons; texts excluded
        if region.is_empty():
            continue
        n_layers += 1
        box += region.bbox()
    if box.empty():
        raise MeasureError(
            f"cell {cell_name!r} in {gds.name} has no geometry (texts do not count)"
        )

    w, h = box.width(), box.height()
    if w <= 0 or h <= 0:
        raise MeasureError(
            f"cell {cell_name!r} has a degenerate bounding box {w} x {h} DBU"
        )
    area_dbu2 = w * h  # Python int: exact
    area_um2 = Decimal(area_dbu2) * dbu_dec * dbu_dec
    area_mm2 = area_um2 / Decimal(1_000_000)
    return {
        "schema": SCHEMA,
        "status": "proposed -- not ratified (TBD-12 is unresolved)",
        "definition": {"id": DEFINITION_ID, "rules": DEFINITION_RULES},
        "source": {
            "gds_path": rel_path if rel_path is not None else _rel(gds),
            "gds_sha256": digest,
            "cell": cell_name,
        },
        "dbu_um": _dec(dbu_dec),
        "bbox_dbu": {
            "left": box.left,
            "bottom": box.bottom,
            "right": box.right,
            "top": box.top,
            "width": w,
            "height": h,
        },
        "geometry_layer_count": n_layers,
        "width_um": _dec(Decimal(w) * dbu_dec),
        "height_um": _dec(Decimal(h) * dbu_dec),
        "area_dbu2": area_dbu2,
        "area_um2": _dec(area_um2),
        "area_mm2": _dec(area_mm2),
    }


def render(record: dict) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def _flat(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flat(v, f"{prefix}{k}."))
    else:
        out[prefix.rstrip(".")] = d
    return out


def check(record_path: Path, gds: Path | None = None) -> list[str]:
    """Re-derive and compare.  Returns a list of problems (empty = ok).  Never writes."""
    try:
        recorded = json.loads(record_path.read_text())
    except FileNotFoundError:
        return [f"record not found: {record_path.name}"]
    except (ValueError, OSError) as e:
        return [f"record {record_path.name} is not valid JSON: {e}"]
    if not isinstance(recorded, dict):
        return [f"record {record_path.name} is not a JSON object"]
    src = recorded.get("source")
    if not isinstance(src, dict) or not isinstance(src.get("gds_path"), str) \
            or not isinstance(src.get("cell"), str):
        return ["record lacks source.gds_path / source.cell"]
    gds_path = gds if gds is not None else REPO / src["gds_path"]
    problems: list[str] = []
    if gds_path.is_file() and sha256_file(gds_path) != src.get("gds_sha256"):
        problems.append(
            f"input-hash drift: GDS sha256 {sha256_file(gds_path)} != recorded "
            f"{src.get('gds_sha256')}"
        )
    try:
        fresh = measure(gds_path, src["cell"], rel_path=src["gds_path"])
    except MeasureError as e:
        return problems + [str(e)]
    if recorded.get("definition", {}).get("id") != DEFINITION_ID:
        problems.append(
            f"definition drift: recorded id {recorded.get('definition', {}).get('id')!r} "
            f"!= {DEFINITION_ID!r}"
        )
    a, b = _flat(recorded), _flat(fresh)
    for k in sorted(set(a) | set(b)):
        if k == "source.gds_sha256" and any("input-hash" in p for p in problems):
            continue
        if a.get(k, "<missing>") != b.get(k, "<missing>"):
            problems.append(
                f"value drift in {k}: recorded {a.get(k, '<missing>')!r}, "
                f"re-derived {b.get(k, '<missing>')!r}"
            )
    if render(recorded) != render(fresh) and not problems:
        problems.append("record is not in canonical form (re-run with --write)")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gds", default=DEFAULT_GDS, help="repo-relative GDS (default: %(default)s)")
    ap.add_argument("--cell", default=DEFAULT_CELL)
    ap.add_argument("--record", default=str(DEFAULT_RECORD))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the record file")
    mode.add_argument("--check", action="store_true", help="verify the record; never writes")
    args = ap.parse_args(argv)
    try:
        if args.check:
            problems = check(Path(args.record))
            if problems:
                for p in problems:
                    print(f"FAIL: {p}", file=sys.stderr)
                return 1
            print(f"OK: {Path(args.record).name} matches a fresh derivation")
            return 0
        text = render(measure(REPO / args.gds, args.cell, rel_path=args.gds))
    except MeasureError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.write:
        Path(args.record).write_text(text)
        print(f"wrote {args.record}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

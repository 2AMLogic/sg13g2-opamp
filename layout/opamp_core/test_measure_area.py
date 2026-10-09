"""Tests for measure_area.py: synthetic, hand-computable layouts + negative controls.

Run: python3 -m unittest discover -s layout/opamp_core -p 'test_measure_area.py' -v
Needs only the `klayout` python module (no PDK, klt or simulator).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import klayout.db as kdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import measure_area as ma  # noqa: E402


class Fx(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def gds(self, layout, name="t.gds"):
        p = self.tmp / name
        layout.write(str(p))
        return p

    def measure(self, layout, cell="TOP"):
        return ma.measure(self.gds(layout), cell, rel_path="t.gds")


def new_layout(dbu=0.005):
    ly = kdb.Layout()
    ly.dbu = dbu
    return ly


class Geometry(Fx):
    def test_flat_box_exact_numbers_nondefault_dbu(self):
        ly = new_layout(0.005)
        top = ly.create_cell("TOP")
        l1 = ly.layer(1, 0)
        top.shapes(l1).insert(kdb.Box(-10, 20, 90, 70))  # 100 x 50 DBU
        r = self.measure(ly)
        self.assertEqual(r["bbox_dbu"], dict(left=-10, bottom=20, right=90, top=70, width=100, height=50))
        self.assertEqual(r["dbu_um"], "0.005")
        self.assertEqual(r["width_um"], "0.5")
        self.assertEqual(r["height_um"], "0.25")
        self.assertEqual(r["area_dbu2"], 5000)
        self.assertEqual(r["area_um2"], "0.125")        # 5000 * 0.005^2
        self.assertEqual(r["area_mm2"], "0.000000125")  # 0.125 / 1e6
        self.assertEqual(r["geometry_layer_count"], 1)

    def test_child_translation_rotation_reflection_and_array(self):
        ly = new_layout(0.001)
        child = ly.create_cell("CH")
        child.shapes(ly.layer(2, 0)).insert(kdb.Box(0, 0, 10, 4))  # 10 wide, 4 tall
        top = ly.create_cell("TOP")
        top.shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 1, 1))
        # R90 about origin: child -> x in [-4,0], y in [0,10]; shifted by (100,0)
        top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(1, False, 100, 0)))
        # mirrored (M0 = about x axis) at (0,-50): y in [-54,-50]
        top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(0, True, 0, -50)))
        # 3 x 2 array, pitch (30, 20) at origin (200, 300): x to 200+60+10, y to 300+20+4
        top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(200, 300),
                                     kdb.Vector(30, 0), kdb.Vector(0, 20), 3, 2))
        r = self.measure(ly)
        # x: min 0 (top box / mirrored child), max 270; y: min -54, max 324
        self.assertEqual(r["bbox_dbu"], dict(left=0, bottom=-54, right=270, top=324, width=270, height=378))
        self.assertEqual(r["area_dbu2"], 270 * 378)
        self.assertEqual(r["area_um2"], "0.10206")    # 102060 DBU^2 * (1e-3 um)^2
        self.assertEqual(r["area_mm2"], "0.00000010206")

    def test_rotated_child_only(self):
        ly = new_layout(0.001)
        child = ly.create_cell("CH")
        child.shapes(ly.layer(2, 0)).insert(kdb.Box(0, 0, 10, 4))
        top = ly.create_cell("TOP")
        top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(1, False, 100, 0)))
        r = self.measure(ly)
        self.assertEqual(r["bbox_dbu"], dict(left=96, bottom=0, right=100, top=10, width=4, height=10))

    def test_nested_hierarchy(self):
        ly = new_layout(0.001)
        a = ly.create_cell("A")
        a.shapes(ly.layer(3, 0)).insert(kdb.Box(0, 0, 5, 5))
        b = ly.create_cell("B")
        b.insert(kdb.CellInstArray(a.cell_index(), kdb.Trans(10, 10)))
        top = ly.create_cell("TOP")
        top.insert(kdb.CellInstArray(b.cell_index(), kdb.Trans(1, False, 0, 0)))  # R90
        r = self.measure(ly)
        # A at (10..15,10..15) in B; R90 maps (x,y)->(-y,x): x in [-15,-10], y in [10,15]
        self.assertEqual(r["bbox_dbu"], dict(left=-15, bottom=10, right=-10, top=15, width=5, height=5))

    def test_polygon_and_path_count(self):
        ly = new_layout(0.001)
        top = ly.create_cell("TOP")
        top.shapes(ly.layer(1, 0)).insert(kdb.Polygon([kdb.Point(0, 0), kdb.Point(0, 10), kdb.Point(10, 0)]))
        top.shapes(ly.layer(4, 0)).insert(kdb.Path([kdb.Point(0, 0), kdb.Point(0, 50)], 20))  # x -10..10
        r = self.measure(ly)
        self.assertEqual(r["bbox_dbu"], dict(left=-10, bottom=0, right=10, top=50, width=20, height=50))
        self.assertEqual(r["geometry_layer_count"], 2)

    def test_boundary_layer_counts(self):
        # An outline/boundary-type layer (e.g. prBoundary 189/4) is geometry too.
        ly = new_layout(0.001)
        top = ly.create_cell("TOP")
        top.shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 10, 10))
        top.shapes(ly.layer(189, 4)).insert(kdb.Box(-5, -5, 15, 20))
        r = self.measure(ly)
        self.assertEqual(r["bbox_dbu"], dict(left=-5, bottom=-5, right=15, top=20, width=20, height=25))

    def test_text_does_not_enlarge(self):
        ly = new_layout(0.001)
        top = ly.create_cell("TOP")
        top.shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 10, 10))
        top.shapes(ly.layer(1, 0)).insert(kdb.Text("far", kdb.Trans(100000, -50000)))
        top.shapes(ly.layer(9, 9)).insert(kdb.Text("textonly", kdb.Trans(-70000, 70000)))
        child = ly.create_cell("CH")
        child.shapes(ly.layer(1, 0)).insert(kdb.Text("c", kdb.Trans(9999, 9999)))
        top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(500, 500)))
        r = self.measure(ly)
        self.assertEqual(r["bbox_dbu"], dict(left=0, bottom=0, right=10, top=10, width=10, height=10))
        self.assertEqual(r["geometry_layer_count"], 1)

    def test_only_named_cell_contributes(self):
        ly = new_layout(0.001)
        top = ly.create_cell("TOP")
        top.shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 10, 10))
        other = ly.create_cell("OTHER")  # second top cell, far away
        other.shapes(ly.layer(1, 0)).insert(kdb.Box(1000, 1000, 5000, 5000))
        orphan = ly.create_cell("ORPHAN")  # not referenced by TOP
        orphan.shapes(ly.layer(1, 0)).insert(kdb.Box(-900, -900, 0, 0))
        r = self.measure(ly, "TOP")
        self.assertEqual(r["bbox_dbu"]["width"], 10)
        r2 = self.measure(ly, "OTHER")
        self.assertEqual(r2["bbox_dbu"], dict(left=1000, bottom=1000, right=5000, top=5000, width=4000, height=4000))

    def test_deterministic_bytes(self):
        ly = new_layout()
        top = ly.create_cell("TOP")
        top.shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 7, 9))
        p = self.gds(ly)
        a = ma.render(ma.measure(p, "TOP", rel_path="t.gds"))
        b = ma.render(ma.measure(p, "TOP", rel_path="t.gds"))
        self.assertEqual(a, b)
        self.assertNotIn(str(self.tmp), a)


class Failures(Fx):
    def test_missing_cell(self):
        ly = new_layout()
        ly.create_cell("TOP").shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 1, 1))
        with self.assertRaisesRegex(ma.MeasureError, "cell 'NOPE' not found.*TOP"):
            self.measure(ly, "NOPE")

    def test_empty_cell(self):
        ly = new_layout()
        ly.create_cell("TOP")
        with self.assertRaisesRegex(ma.MeasureError, "no geometry"):
            self.measure(ly)

    def test_text_only_cell_is_empty(self):
        ly = new_layout()
        ly.create_cell("TOP").shapes(ly.layer(1, 0)).insert(kdb.Text("x", kdb.Trans(5, 5)))
        with self.assertRaisesRegex(ma.MeasureError, "no geometry"):
            self.measure(ly)

    def test_malformed_gds(self):
        p = self.tmp / "bad.gds"
        p.write_bytes(b"this is not a gds stream at all")
        with self.assertRaisesRegex(ma.MeasureError, "cannot read"):
            ma.measure(p, "TOP", rel_path="bad.gds")

    def test_missing_file(self):
        with self.assertRaisesRegex(ma.MeasureError, "not found"):
            ma.measure(self.tmp / "nope.gds", "TOP", rel_path="nope.gds")

    def test_nonpositive_dbu(self):
        # KLayout refuses to hold dbu <= 0; the guard must still be exercised
        # if a Layout reports it.  Patch the reader to report 0.
        ly = new_layout()
        ly.create_cell("TOP").shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 1, 1))
        p = self.gds(ly)
        real = kdb.Layout

        class Zero(real):
            @property
            def dbu(self):
                return 0.0

        orig = kdb.Layout
        kdb.Layout = Zero
        try:
            with self.assertRaisesRegex(ma.MeasureError, "nonpositive database unit"):
                ma.measure(p, "TOP", rel_path="t.gds")
        finally:
            kdb.Layout = orig

    def test_zero_area_box_rejected(self):
        ly = new_layout()
        ly.create_cell("TOP").shapes(ly.layer(1, 0)).insert(kdb.Path([kdb.Point(0, 0), kdb.Point(10, 0)], 0))
        with self.assertRaises(ma.MeasureError):
            self.measure(ly)


class CheckMode(Fx):
    def setUp(self):
        super().setUp()
        ly = new_layout(0.001)
        ly.create_cell("TOP").shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 100, 40))
        self.g = self.gds(ly)
        self.rec = self.tmp / "rec.json"
        self.rec.write_text(ma.render(ma.measure(self.g, "TOP", rel_path="t.gds")))

    def mutate(self, fn):
        d = json.loads(self.rec.read_text())
        fn(d)
        self.rec.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")

    def probs(self):
        return ma.check(self.rec, gds=self.g)

    def test_clean(self):
        self.assertEqual(self.probs(), [])

    def test_check_does_not_write(self):
        before = (self.rec.read_bytes(), self.g.read_bytes(), sorted(p.name for p in self.tmp.iterdir()))
        self.probs()
        self.mutate(lambda d: d.update(area_um2="9"))
        self.probs()
        after_names = sorted(p.name for p in self.tmp.iterdir())
        self.assertEqual(before[2], after_names)
        self.assertEqual(before[1], self.g.read_bytes())

    def test_altered_gds_bytes(self):
        ly = new_layout(0.001)
        ly.create_cell("TOP").shapes(ly.layer(1, 0)).insert(kdb.Box(0, 0, 101, 40))
        ly.write(str(self.g))
        out = "\n".join(self.probs())
        self.assertIn("input-hash drift", out)
        self.assertIn("bbox_dbu.width", out)

    def test_altered_hash_only(self):
        self.mutate(lambda d: d["source"].update(gds_sha256="0" * 64))
        out = "\n".join(self.probs())
        self.assertIn("input-hash drift", out)

    def test_altered_definition(self):
        self.mutate(lambda d: d["definition"].update(id="something-else"))
        self.assertIn("definition drift", "\n".join(self.probs()))

    def test_altered_coordinates(self):
        self.mutate(lambda d: d["bbox_dbu"].update(right=101))
        self.assertIn("value drift in bbox_dbu.right", "\n".join(self.probs()))

    def test_altered_area_values(self):
        for key in ("area_dbu2", "area_um2", "area_mm2", "width_um", "dbu_um"):
            with self.subTest(key=key):
                self.setUp()
                self.mutate(lambda d: d.update({key: "1"}))
                self.assertIn(f"value drift in {key}", "\n".join(self.probs()))

    def test_altered_cell_name(self):
        self.mutate(lambda d: d["source"].update(cell="NOPE"))
        self.assertIn("not found", "\n".join(self.probs()))

    def test_malformed_record(self):
        self.rec.write_text("{not json")
        self.assertIn("not valid JSON", "\n".join(self.probs()))
        self.rec.write_text("[]")
        self.assertIn("not a JSON object", "\n".join(self.probs()))
        self.rec.write_text("{}")
        self.assertIn("lacks source", "\n".join(self.probs()))


class Committed(unittest.TestCase):
    """The committed record against the committed GDS (offline, no regeneration)."""

    def test_committed_record_checks_clean(self):
        self.assertEqual(ma.check(ma.DEFAULT_RECORD), [])

    def test_committed_record_is_proposal_with_expected_shape(self):
        d = json.loads(ma.DEFAULT_RECORD.read_text())
        self.assertEqual(d["source"]["cell"], "opamp_core")
        self.assertEqual(d["definition"]["id"], ma.DEFINITION_ID)
        self.assertIn("not ratified", d["status"])
        b = d["bbox_dbu"]
        self.assertEqual(b["width"] * b["height"], d["area_dbu2"])

    def test_cli_check_exit_codes(self):
        r = subprocess.run([sys.executable, str(HERE / "measure_area.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, str(HERE / "measure_area.py"), "--check",
                            "--record", str(HERE / "does_not_exist.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()

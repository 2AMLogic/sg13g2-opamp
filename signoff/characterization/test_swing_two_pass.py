#!/usr/bin/env python3
"""Offline tests for the batch two-pass swing admission (issue #503):

    python3 -m unittest discover -s signoff/characterization -p 'test_swing_two_pass.py'

Curves are SYNTHETIC (built by sim/output-swing/klt/test_two_pass.py helpers):
these tests check that selection and the report reader admit hash-pinned
pass evidence, feed the existing `swing_raw_audit` definition check, and
surface each failure with its corner. They are not evidence about any circuit,
and no live batch artifact is exercised.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "sim" / "output-swing" / "klt"))
import common  # noqa: E402
import defchecks  # noqa: E402
import records  # noqa: E402
import selection  # noqa: E402
import test_two_pass as TP  # noqa: E402

PID = TP.PID


class Fixture:
    def __init__(self, tmp: Path, pids=(PID,)):
        self.root = tmp
        self.pids = list(pids)
        self.files: dict = {}

    def write(self, pid, coarse, fine):
        entry = {}
        for kind, doc in (("coarse", coarse), ("fine", fine)):
            rel = f"ev/{pid}_{kind}.json"
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(doc, pid=pid)), encoding="utf-8")
            entry[kind] = {"path": rel, "sha256": common.sha256_file(path)}
        self.files[pid] = entry

    def load(self):
        errors: list = []
        expected = []
        for p in self.pids:
            corner, temp, vdd = p.rsplit("_", 2)
            expected.append((p, {"corner": corner, "temp": temp[:-1], "vdd": vdd[:-1]}))
        pop = records._load_swing_two_pass_population(
            self.root, "rec", {"files": self.files}, expected, errors, "sha256:" + "a" * 64, "ngspice-45")
        return pop, errors


class SwingTwoPassAdmission(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = Fixture(Path(self._tmp.name))

    def good(self, amp=0.45):
        return TP.make_pair(TP.tanh_curve(amp, 0.003, 0.015))

    def test_valid_pair_feeds_the_existing_definition_check(self):
        self.fx.write(PID, *self.good())
        pop, errors = self.fx.load()
        self.assertEqual(errors, [])
        a = TP.T.audit_pair(PID, *self.good())
        row = dict(a["fields"], point_id=PID)
        self.assertIsNone(defchecks._check_swing_raw(row, pop))

    def test_matching_wrong_passes_cannot_replace_the_selected_dut_or_corner(self):
        for field, value, expected in (("dut_sha256", "c" * 64, "selected snapshot"),
                                       ("process", "mos_ss", "selected grid"),
                                       ("simulator", "ngspice-46", "simulator")):
            with self.subTest(field=field):
                self.fx.write(PID, *(dict(p, **{field: value}) for p in self.good()))
                pop, errors = self.fx.load()
                self.assertIsNone(pop)
                self.assertTrue(any(PID in e and expected in e for e in errors), errors)

    def test_tampered_headroom_fails_the_definition_check(self):
        self.fx.write(PID, *self.good())
        pop, _ = self.fx.load()
        a = TP.T.audit_pair(PID, *self.good())
        row = dict(a["fields"], point_id=PID,
                   headroom_hi_v=TP.serialize(float(a["fields"]["headroom_hi_v"]) + 0.05))
        problem = defchecks._check_swing_raw(row, pop)
        self.assertIn("headroom_hi_v", problem)

    def test_valid_below_limit_span_is_admitted_not_refused(self):
        self.fx.write(PID, *self.good(amp=0.30))
        pop, errors = self.fx.load()
        self.assertEqual(errors, [])
        self.assertLess(pop[PID]["fine"]["span"], 0.571)

    def test_crossing_outside_fine_window_names_corner(self):
        self.fx.write(PID, *TP.make_pair(TP.tanh_curve(0.45, 0.003, 0.015), TP.tanh_curve(0.45, 0.003, 0.070)))
        pop, errors = self.fx.load()
        self.assertIsNone(pop)
        self.assertTrue(any(f"point {PID}: fine sweep: fine_sweep_no_crossing" in e for e in errors), errors)

    def test_clipped_tracking_region_names_corner(self):
        self.fx.write(PID, *TP.make_pair(TP.ramp_curve(0.6, 0.04, 0.015)))
        pop, errors = self.fx.load()
        self.assertIsNone(pop)
        self.assertTrue(any("linear_region_touches_window_edge" in e and PID in e for e in errors), errors)

    def test_mismatched_duts_name_corner(self):
        coarse, fine = self.good()
        fine["dut_sha256"] = "c" * 64
        self.fx.write(PID, coarse, fine)
        pop, errors = self.fx.load()
        self.assertIsNone(pop)
        self.assertTrue(any(f"point {PID}: coarse/fine passes disagree on dut_sha256" in e for e in errors), errors)

    def test_edited_evidence_without_repin_is_refused(self):
        self.fx.write(PID, *self.good())
        p = self.fx.root / self.fx.files[PID]["fine"]["path"]
        p.write_text(p.read_text().replace("ngspice-45", "ngspice-44"), encoding="utf-8")
        pop, errors = self.fx.load()
        self.assertIsNone(pop)
        self.assertTrue(any("does not match its selection pin" in e for e in errors), errors)

    def test_missing_corner_and_wrong_point_file_are_named(self):
        other = "mos_ss_27C_1.20V"
        fx = Fixture(Path(self._tmp.name), pids=(PID, other))
        fx.write(PID, *self.good())
        pop, errors = fx.load()
        self.assertIsNone(pop)
        self.assertTrue(any(other in e and "no pinned raw" in e for e in errors), errors)
        # evidence for another point pinned under this point's name
        fx.write(other, *TP.make_pair(TP.tanh_curve(0.45, 0.003, 0.015), pid=PID))
        fx.files[other] = {k: dict(v) for k, v in fx.files[other].items()}
        doc = json.loads((fx.root / fx.files[other]["coarse"]["path"]).read_text())
        self.assertEqual(doc["pid"], other)  # fixture stamps the pinned pid; tamper it
        doc["pid"] = PID
        path = fx.root / fx.files[other]["coarse"]["path"]
        path.write_text(json.dumps(doc))
        fx.files[other]["coarse"]["sha256"] = common.sha256_file(path)
        _, errors = fx.load()
        self.assertTrue(any(other in e and f"evidence for point {PID!r}" in e for e in errors), errors)


class SwingTwoPassSelectionShape(unittest.TestCase):
    def setUp(self):
        self.selected = json.loads((HERE / "selection.json").read_text(encoding="utf-8"))
        self.swing = self.selected["records"]["output-swing"]
        pin = {"path": "a", "sha256": "sha256:x"}
        self.files = {PID: {"coarse": pin, "fine": pin}}

    def load_with_two_pass(self, evidence):
        self.swing["swing_two_pass"] = evidence
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            path.write_text(json.dumps(self.selected), encoding="utf-8")
            selection.load_selection(path)

    def test_shape_validator(self):
        del self.swing["swing_raw"]
        self.load_with_two_pass({"files": self.files})
        for bad in ({"files": {PID: {"coarse": self.files[PID]["coarse"]}}},
                    {"files": {}}, {"files": self.files, "x": 1}, []):
            with self.subTest(evidence=bad), self.assertRaisesRegex(selection.SelectionError, "swing_two_pass"):
                self.load_with_two_pass(bad)

    def test_record_cannot_pin_both_swing_formats(self):
        with self.assertRaisesRegex(selection.SelectionError, "swing_raw.*swing_two_pass.*name exactly one"):
            self.load_with_two_pass({"files": self.files})


if __name__ == "__main__":
    unittest.main()

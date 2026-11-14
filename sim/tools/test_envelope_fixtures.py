#!/usr/bin/env python3
"""Tests for envelope_fixtures.py, the shared test-side envelope kit (issue #358).

    python3 -m unittest discover -s sim/tools -p 'test_*.py'

These pin the *shape* the per-bench test_compare.py suites consume: the
`schema_version: 3` wrapper, the corner dict and its `corner_id` spelling, the
status rollups, and the grading semantics. The bench suites build their
negative controls on top of this, so a silent change here would weaken every
one of them at once -- which is exactly the lockstep risk that folding the
three copied copies into one module was meant to remove.

Self-contained: builds its own tiny rows/request rather than importing a bench,
so a bench rename cannot make this file vacuous. Stdlib only, offline.
"""

from __future__ import annotations

import ast
import csv
import inspect
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envelope_fixtures as F  # noqa: E402

# Two rows of a toy harness: the same columns build_envelope reads off any
# bench's record (corner / temp_c / vdd_v) plus one measurement column.
ROWS = [
    {"corner": "mos_tt", "temp_c": "27", "vdd_v": "1.2", "x": "5.0"},
    {"corner": "mos_ss", "temp_c": "-40", "vdd_v": "1.08", "x": "11.0"},
]


def make_key(process, temp_c, vdd_v):
    """A stand-in for each bench's C.make_key, with the same (p, int, float) shape."""
    return (str(process), int(round(float(temp_c))), round(float(vdd_v), 3))


def vals(row):
    return {"x": float(row["x"])}


LIMITS = {"x": {"max": 10.0}}


class TestGrade(unittest.TestCase):
    def test_no_limits_is_pass(self):
        for empty in (None, {}):
            self.assertEqual(F.grade(1e30, empty), "pass")

    def test_max_only(self):
        self.assertEqual(F.grade(9.0, {"max": 10.0}), "pass")
        self.assertEqual(F.grade(10.0, {"max": 10.0}), "pass")   # inclusive
        self.assertEqual(F.grade(10.1, {"max": 10.0}), "fail")

    def test_min_only(self):
        self.assertEqual(F.grade(2.0, {"min": 1.0}), "pass")
        self.assertEqual(F.grade(1.0, {"min": 1.0}), "pass")     # inclusive
        self.assertEqual(F.grade(0.9, {"min": 1.0}), "fail")

    def test_two_sided_band(self):
        band = {"min": -1.0, "max": 1.0}
        self.assertEqual(F.grade(0.0, band), "pass")
        self.assertEqual(F.grade(-1.5, band), "fail")
        self.assertEqual(F.grade(1.5, band), "fail")

    def test_explicit_none_bound_does_not_gate(self):
        self.assertEqual(F.grade(-1e9, {"min": None, "max": 1.0}), "pass")
        self.assertEqual(F.grade(1e9, {"min": -1.0, "max": None}), "pass")


class TestHarnessRows(unittest.TestCase):
    def test_rows_are_strings_in_file_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.csv")
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(ROWS[0].keys()))
                w.writeheader()
                w.writerows(ROWS)
            got = F.harness_rows(p)
        self.assertEqual([dict(r) for r in got], ROWS)
        self.assertTrue(all(isinstance(v, str) for r in got for v in r.values()))


class TestRequestLimits(unittest.TestCase):
    def test_limits_are_lifted_and_absent_means_none(self):
        req = {"measurements": [{"name": "a", "limits": {"max": 1.0}}, {"name": "b"}]}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json")
            with open(p, "w") as f:
                json.dump(req, f)
            self.assertEqual(F.request_limits(p), {"a": {"max": 1.0}, "b": None})


class TestBuildEnvelope(unittest.TestCase):
    def test_exact_envelope_shape(self):
        env = F.build_envelope(ROWS, vals, make_key, LIMITS)
        self.assertEqual(env, {
            "schema_version": 3,
            "status": "fail",          # row 2 is 11.0 against max 10.0
            "corner_count": 2,
            "coverage": {"nothing_checked": False, "skipped": []},
            "corners": [
                {
                    "corner_id": "mos_tt/vdd=1.200_vinp=0.600V/27C",
                    "process": "mos_tt", "temperature_c": 27,
                    "supply_v": {"vdd": 1.2, "vinp": 0.6},
                    "status": "pass",
                    "measurements": [{"name": "x", "value": 5.0, "status": "pass"}],
                },
                {
                    "corner_id": "mos_ss/vdd=1.080_vinp=0.540V/-40C",
                    "process": "mos_ss", "temperature_c": -40,
                    "supply_v": {"vdd": 1.08, "vinp": 0.54},
                    "status": "fail",
                    "measurements": [{"name": "x", "value": 11.0, "status": "fail"}],
                },
            ],
        })

    def test_corner_order_follows_row_order(self):
        env = F.build_envelope(list(reversed(ROWS)), vals, make_key, LIMITS)
        self.assertEqual([c["process"] for c in env["corners"]], ["mos_ss", "mos_tt"])

    def test_all_pass_rolls_up_to_pass(self):
        env = F.build_envelope(ROWS, vals, make_key, {"x": None})
        self.assertEqual(env["status"], "pass")
        self.assertEqual([c["status"] for c in env["corners"]], ["pass", "pass"])

    def test_supply_key_names_the_mid_rail_in_id_and_dict(self):
        env = F.build_envelope(ROWS[:1], vals, make_key, LIMITS, supply_key="vcm")
        c = env["corners"][0]
        self.assertEqual(c["corner_id"], "mos_tt/vdd=1.200_vcm=0.600V/27C")
        self.assertEqual(c["supply_v"], {"vdd": 1.2, "vcm": 0.6})

    def test_status_fn_is_injectable(self):
        env = F.build_envelope(ROWS, vals, make_key, LIMITS, status_fn=lambda v, lim: "fail")
        self.assertEqual(env["status"], "fail")
        self.assertTrue(all(m["status"] == "fail" for c in env["corners"] for m in c["measurements"]))

    def test_vals_fn_sees_the_raw_row_and_sets_measurement_order(self):
        seen = []

        def spy(row):
            seen.append(row)
            return {"b": 1.0, "a": 2.0}

        env = F.build_envelope(ROWS, spy, make_key, {"a": None, "b": None})
        self.assertEqual(seen, ROWS)
        self.assertEqual([m["name"] for m in env["corners"][0]["measurements"]], ["b", "a"])


class TestRegrade(unittest.TestCase):
    def _env(self):
        return F.build_envelope(ROWS, vals, make_key, LIMITS)

    def test_perturbed_value_restamps_corner_and_rollup(self):
        env = self._env()
        c = env["corners"][0]
        c["measurements"][0]["value"] = 99.0
        F.regrade(env, c, LIMITS)
        self.assertEqual(c["measurements"][0]["status"], "fail")
        self.assertEqual(c["status"], "fail")
        self.assertEqual(env["status"], "fail")

    def test_repaired_value_clears_the_corner_and_the_rollup(self):
        env = F.build_envelope(ROWS[1:], vals, make_key, LIMITS)
        self.assertEqual(env["status"], "fail")
        c = env["corners"][0]
        c["measurements"][0]["value"] = 1.0
        F.regrade(env, c, LIMITS)
        self.assertEqual(c["status"], "pass")
        self.assertEqual(env["status"], "pass")

    def test_null_value_keeps_its_prior_status(self):
        """A null value is an input error for the comparator to name; the
        fixture must not grade it away (every bench's null negative control
        depends on this)."""
        env = self._env()
        c = env["corners"][1]
        self.assertEqual(c["measurements"][0]["status"], "fail")
        c["measurements"][0]["value"] = None
        F.regrade(env, c, LIMITS)
        self.assertEqual(c["measurements"][0]["status"], "fail")
        self.assertEqual(c["status"], "fail")

    def test_status_fn_is_injectable(self):
        env = self._env()
        c = env["corners"][0]
        F.regrade(env, c, LIMITS, status_fn=lambda v, lim: "fail")
        self.assertEqual(c["status"], "fail")

    def test_other_corners_are_untouched(self):
        env = self._env()
        before = [m["status"] for m in env["corners"][1]["measurements"]]
        env["corners"][0]["measurements"][0]["value"] = 99.0
        F.regrade(env, env["corners"][0], LIMITS)
        self.assertEqual([m["status"] for m in env["corners"][1]["measurements"]], before)


class TestFind(unittest.TestCase):
    def test_returns_the_corner_and_its_named_measurement(self):
        env = F.build_envelope(ROWS, vals, make_key, LIMITS)
        c, m = F.find(env, ("mos_ss", -40, 1.08), "x", make_key)
        self.assertIs(c, env["corners"][1])
        self.assertEqual((m["name"], m["value"]), ("x", 11.0))

    def test_finds_through_a_reordered_corner_list(self):
        env = F.build_envelope(ROWS, vals, make_key, LIMITS)
        env["corners"].reverse()
        c, _ = F.find(env, ("mos_tt", 27, 1.2), "x", make_key)
        self.assertEqual(c["process"], "mos_tt")

    def test_absent_point_raises_keyerror_naming_point_and_measurement(self):
        env = F.build_envelope(ROWS, vals, make_key, LIMITS)
        point = ("mos_ff", 125, 1.32)
        with self.assertRaises(KeyError) as cm:
            F.find(env, point, "x", make_key)
        self.assertEqual(cm.exception.args[0], (point, "x"))

    def test_absent_measurement_raises_keyerror(self):
        env = F.build_envelope(ROWS, vals, make_key, LIMITS)
        with self.assertRaises(KeyError):
            F.find(env, ("mos_tt", 27, 1.2), "not_a_measurement", make_key)


class TestNonCircularity(unittest.TestCase):
    """The fixture kit must not grade via the code under test (issue #358 step 2).

    These suites build their envelopes FROM the committed harness record. If
    the builder imported a comparator -- or klt_envelope's graders -- the
    negative controls would compare the tool against itself and could no
    longer fail. make_key and status_fn are therefore parameters, not imports.
    """

    def test_module_imports_only_stdlib(self):
        """Read the real import statements, not the prose: nothing from a bench
        comparator or from klt_envelope may be imported here."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "envelope_fixtures.py")
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                self.fail(f"relative import in envelope_fixtures.py: {ast.dump(node)}")
        self.assertEqual(imported, {"__future__", "csv", "json", "typing"})

    def test_make_key_and_status_fn_are_parameters(self):
        self.assertIn("make_key", inspect.signature(F.build_envelope).parameters)
        self.assertIn("status_fn", inspect.signature(F.build_envelope).parameters)
        self.assertIn("make_key", inspect.signature(F.find).parameters)
        self.assertIn("status_fn", inspect.signature(F.regrade).parameters)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Offline negative-control tests for compare.py (issue #97).

    python3 -m unittest discover -s sim/input-offset/klt -p 'test_*.py'

What these fixtures are, stated plainly: the synthetic envelopes below are
BUILT FROM the committed harness record, so a test that only checks "the
baseline agrees" would be circular. The baseline case is only the control
that every negative case perturbs; the tests that carry weight are the
negative controls (reordered, missing, duplicate, extra, null, NaN,
perturbed, mis-biased Vcm, incomplete coverage, errored corner, sanity-flag
disagreement, bound flip), each of which must fail and name the point/metric
it failed on. None of this is evidence about the circuit -- the envelope in
records/ is.
"""

from __future__ import annotations

import copy
import csv
import json
import math
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
import compare as C  # noqa: E402

BENCH = os.path.dirname(HERE)
HARNESS_CSV = os.path.join(BENCH, "records", "20260918-203858-90844d2.csv")
REQUEST = os.path.join(HERE, "offset.request.json")
BOUND = C.OFFSET_BOUND_V


def _harness_rows():
    with open(HARNESS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _status(value, limits):
    if not limits:
        return "pass"
    lo, hi = limits.get("min"), limits.get("max")
    return "pass" if (lo is None or value >= lo) and (hi is None or value <= hi) else "fail"


def _request_limits():
    with open(REQUEST) as f:
        req = json.load(f)
    return {m["name"]: m.get("limits") for m in req["measurements"]}


def _envelope(rows):
    """A synthetic klt-sim-shaped envelope carrying the harness's own numbers."""
    limits = _request_limits()
    corners = []
    for r in rows:
        k = C.make_key(r["corner"], r["temp_c"], r["vdd_v"])
        vdd = float(r["vdd_v"])
        vd1, vd2, vtail = (float(r[c]) for c in ("vd1_sample_v", "vd2_sample_v", "vtail_sample_v"))
        vals = {
            "vos_null_v": float(r["vos_null_v"]), "vos_crossings_n": 1.0,
            "gain_local_vv": 10 ** (float(r["av_local_db"]) / 20),
            "vd1_dc_v": vd1, "vd2_dc_v": vd2, "vtail_dc_v": vtail,
            "vibias_dc_v": float(r["vibias_sample_v"]),
            "op_vd1_rail_frac": vd1 / vdd, "op_vd2_rail_frac": vd2 / vdd, "op_vtail_rail_frac": vtail / vdd,
        }
        ms = [{"name": n, "value": v, "status": _status(v, limits[n])} for n, v in vals.items()]
        corners.append({
            "corner_id": f"{k[0]}/vdd={vdd:.3f}_vinp={vdd / 2:.3f}V/{k[1]}C",
            "process": k[0], "temperature_c": k[1],
            "supply_v": {"vdd": vdd, "vinp": vdd / 2},
            "status": "fail" if any(m["status"] == "fail" for m in ms) else "pass",
            "measurements": ms,
        })
    return {
        "schema_version": 3,
        "status": "fail" if any(c["status"] == "fail" for c in corners) else "pass",
        "corner_count": len(corners),
        "coverage": {"nothing_checked": False, "skipped": []},
        "corners": corners,
    }


def _regrade(env, corner):
    lim = _request_limits()
    for m in corner["measurements"]:
        m["status"] = _status(m["value"], lim[m["name"]]) if m["value"] is not None else m["status"]
    corner["status"] = "fail" if any(m["status"] == "fail" for m in corner["measurements"]) else "pass"
    env["status"] = "fail" if any(c["status"] == "fail" for c in env["corners"]) else "pass"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _harness_rows()
        cls.harness = C.load_harness_csv(HARNESS_CSV)

    def env(self):
        return _envelope(self.rows)

    def tool(self, env):
        return C.index_envelope(env, "test")

    def compare(self, env):
        return C.compare(self.tool(env), self.harness, env)

    @staticmethod
    def find(env, point, name):
        k = C.make_key(*point)
        for c in env["corners"]:
            if C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == k:
                for m in c["measurements"]:
                    if m["name"] == name:
                        return c, m
        raise KeyError((point, name))


WORST = ("mos_fs", 125, 1.08)   # the harness's binding corner
MID = ("mos_tt", 27, 1.2)


class TestRequest(Base):
    def test_request_carries_the_ratified_bound(self):
        self.assertEqual(_request_limits()["vos_null_v"], {"min": -BOUND, "max": BOUND})
        self.assertEqual(BOUND, 0.0219)

    def test_request_declares_every_measurement_compare_reads(self):
        self.assertEqual(set(_request_limits()), set(C.MEASUREMENTS))

    def test_request_is_the_ratified_45_point_grid(self):
        with open(REQUEST) as f:
            req = json.load(f)
        self.assertEqual([p["name"] for p in req["corners"]["process"]], list(C.PROCESSES))
        self.assertEqual(req["corners"]["temperature_c"], list(C.TEMPERATURES))
        self.assertEqual(req["corners"]["supply_v"]["vdd"], list(C.SUPPLIES))
        self.assertEqual(req["corners"]["supply_v"]["vinp"], [v / 2 for v in C.SUPPLIES])
        self.assertEqual(req["analysis"]["kind"], "dc")
        self.assertEqual(req["backend"], "batch")
        # DR-0005: default solver tolerance -- no override in options or the body
        self.assertNotIn("reltol", json.dumps(req["options"]))
        with open(os.path.join(HERE, "tb_offset.body.spice")) as f:
            body = [ln for ln in f if not ln.startswith("*")]
        for word in ("reltol", "abstol", "vntol"):
            self.assertFalse(any(word in ln for ln in body), word)
        self.assertEqual(sum(ln.lower().startswith(".include") for ln in body), 1)

    def test_sweep_window_brackets_the_harness_envelope_and_matches_the_crossing_count(self):
        with open(REQUEST) as f:
            req = json.load(f)
        start, stop, step = req["analysis"]["args"].split()[1:]
        start, stop, step = float(start), float(stop), float(step[:-1]) * 1e-6
        npts = round((stop - start) / step) + 1
        vos = [float(h["vos_null_v"]) for h in self.harness.values()]
        self.assertLess(start, min(vos) - 5e-3)
        self.assertGreater(stop, max(vos) + 5e-3)
        expr = next(m["expr"] for m in req["measurements"] if m["name"] == "vos_crossings_n")
        self.assertIn(f"[1,{npts - 1}]", expr)
        self.assertIn(f"*{npts - 1}", expr)
        self.assertIn(f"[0,{npts - 2}]", expr)

    def test_crossing_count_must_be_exactly_one(self):
        self.assertEqual(_request_limits()["vos_crossings_n"], {"min": 0.5, "max": 1.5})


class TestHarnessInputs(Base):
    def test_committed_record_is_the_full_grid(self):
        self.assertEqual(set(self.harness), set(C.expected_keys()))
        self.assertEqual(len(self.harness), 45)

    def test_duplicate_harness_row_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.csv")
            with open(HARNESS_CSV) as f:
                lines = f.read().splitlines()
            with open(p, "w") as f:
                f.write("\n".join(lines + [lines[1]]) + "\n")
            with self.assertRaisesRegex(C.InputError, "duplicate row"):
                C.load_harness_csv(p)

    def test_nonfinite_harness_value_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.csv")
            rows = _harness_rows()
            rows[3]["vos_null_v"] = "nan"
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            with self.assertRaisesRegex(C.InputError, "non-finite"):
                C.load_harness_csv(p)

    def test_missing_harness_row_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.csv")
            with open(HARNESS_CSV) as f:
                lines = f.read().splitlines()
            with open(p, "w") as f:
                f.write("\n".join(lines[:-1]) + "\n")
            with self.assertRaisesRegex(C.InputError, "missing from harness CSV"):
                C.load_harness_csv(p)


class TestBaselineControl(Base):
    def test_identical_numbers_agree(self):
        rep = self.compare(self.env())
        self.assertEqual(rep["status"], "agree")
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["out_of_tolerance"], [])
        self.assertEqual(rep["bound_verdict_disagreements"], [])

    def test_the_worst_point_is_the_harness_binding_corner(self):
        rep = self.compare(self.env())
        self.assertEqual(rep["row"]["harness_worst"]["point"], "mos_fs_125C_1.08V")
        self.assertAlmostEqual(rep["row"]["harness_worst"]["value"], 0.02193, places=5)

    def test_reordered_corners_join_identically(self):
        env = self.env()
        env["corners"].reverse()
        self.assertEqual(self.compare(env)["status"], "agree")


class TestEnvelopeNegativeControls(Base):
    def test_missing_corner(self):
        env = self.env()
        env["corners"].pop(7)
        env["corner_count"] = 44
        with self.assertRaisesRegex(C.InputError, "missing from test"):
            self.tool(env)

    def test_duplicate_corner(self):
        env = self.env()
        env["corners"].append(copy.deepcopy(env["corners"][0]))
        env["corner_count"] = 46
        with self.assertRaisesRegex(C.InputError, "duplicate corner"):
            self.tool(env)

    def test_extra_off_grid_corner(self):
        env = self.env()
        extra = copy.deepcopy(env["corners"][0])
        extra["supply_v"] = {"vdd": 1.10, "vinp": 0.55}
        env["corners"].append(extra)
        env["corner_count"] = 46
        with self.assertRaisesRegex(C.InputError, "not a point of the ratified grid"):
            self.tool(env)

    def test_corner_count_mismatch(self):
        env = self.env()
        env["corner_count"] = 44
        with self.assertRaisesRegex(C.InputError, "corner_count"):
            self.tool(env)

    def test_null_measurement(self):
        env = self.env()
        _, m = self.find(env, WORST, "vos_null_v")
        m["value"] = None
        with self.assertRaisesRegex(C.InputError, "mos_fs_125C_1.08V: measurement vos_null_v"):
            self.tool(env)

    def test_nonfinite_measurement(self):
        env = self.env()
        _, m = self.find(env, WORST, "gain_local_vv")
        m["value"] = float("nan")
        with self.assertRaisesRegex(C.InputError, "non-finite"):
            self.tool(env)

    def test_absent_measurement(self):
        env = self.env()
        c, m = self.find(env, WORST, "vos_crossings_n")
        c["measurements"].remove(m)
        with self.assertRaisesRegex(C.InputError, "vos_crossings_n missing"):
            self.tool(env)

    def test_vcm_not_half_vdd(self):
        env = self.env()
        c, _ = self.find(env, WORST, "vos_null_v")
        c["supply_v"]["vinp"] = 0.60
        with self.assertRaisesRegex(C.InputError, "vinp 0.6 != vdd/2"):
            self.tool(env)

    def test_errored_corner_is_not_evidence(self):
        env = self.env()
        c, _ = self.find(env, WORST, "vos_null_v")
        c["status"] = "error"
        with self.assertRaisesRegex(C.InputError, "corner status 'error'"):
            self.tool(env)

    def test_inconclusive_run_is_not_evidence(self):
        env = self.env()
        env["status"] = "inconclusive"
        with self.assertRaisesRegex(C.InputError, "aggregate status"):
            self.tool(env)

    def test_nothing_checked(self):
        env = self.env()
        env["coverage"]["nothing_checked"] = True
        with self.assertRaisesRegex(C.InputError, "nothing_checked"):
            self.tool(env)

    def test_skipped_coverage(self):
        env = self.env()
        env["coverage"]["skipped"] = ["limit:[0,...]"]
        with self.assertRaisesRegex(C.InputError, "skipped is non-empty"):
            self.tool(env)

    def test_klt_error_envelope(self):
        with self.assertRaisesRegex(C.InputError, "klt error envelope"):
            C.index_envelope({"error": {"code": "batch_runner_version_mismatch"}}, "test")

    def test_nonpositive_gain_is_input_error(self):
        env = self.env()
        _, m = self.find(env, MID, "gain_local_vv")
        m["value"] = -3.0
        with self.assertRaisesRegex(C.InputError, "not positive"):
            self.compare(env)


class TestComparisonNegativeControls(Base):
    def _set(self, env, point, name, value):
        c, m = self.find(env, point, name)
        m["value"] = value
        _regrade(env, c)

    def test_perturbed_offset_outside_tolerance_is_named(self):
        env = self.env()
        _, m = self.find(env, MID, "vos_null_v")
        self._set(env, MID, "vos_null_v", m["value"] * 1.01)
        rep = self.compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V vos_null_v" in s for s in rep["out_of_tolerance"]))

    def test_perturbation_inside_tolerance_is_accepted(self):
        env = self.env()
        _, m = self.find(env, MID, "vos_null_v")
        self._set(env, MID, "vos_null_v", m["value"] + 2e-6)
        self.assertEqual(self.compare(env)["status"], "agree")

    def test_perturbed_dc_voltage_outside_tolerance_is_named(self):
        env = self.env()
        _, m = self.find(env, ("mos_ff", 125, 1.32), "vd1_dc_v")
        self._set(env, ("mos_ff", 125, 1.32), "vd1_dc_v", m["value"] * 1.01)
        rep = self.compare(env)
        self.assertTrue(any("mos_ff_125C_1.32V vd1_dc_v" in s for s in rep["out_of_tolerance"]))

    def test_gain_outside_tolerance_is_named(self):
        env = self.env()
        _, m = self.find(env, MID, "gain_local_vv")
        self._set(env, MID, "gain_local_vv", m["value"] * 1.05)   # +0.42 dB
        rep = self.compare(env)
        self.assertTrue(any("mos_tt_27C_1.20V gain_local_db" in s for s in rep["out_of_tolerance"]))

    def test_sanity_flag_disagreement_is_named(self):
        for name, bad in (("vos_crossings_n", 3.0), ("gain_local_vv", 2.0), ("op_vd2_rail_frac", 0.001)):
            env = self.env()
            self._set(env, ("mos_sf", 27, 1.2), name, bad)
            rep = self.compare(env)
            self.assertTrue(any("mos_sf_27C_1.20V op_sanity" in s for s in rep["out_of_tolerance"]), name)


class TestBoundVerdicts(Base):
    """A bound miss stays a miss; a flip is explained only inside the tolerance."""

    def test_the_harness_binding_corner_exceeds_the_ratified_bound(self):
        """The committed record's own worst point is 21.927 mV against the
        ratified 21.9 mV: the bound carries no slack, so the tool grades it a
        miss and the harness verdict (also a miss) agrees."""
        rep = self.compare(self.env())
        p = next(p for p in rep["points"] if p["point_id"] == "mos_fs_125C_1.08V")
        self.assertFalse(p["row"]["tool_pass"])
        self.assertFalse(p["row"]["harness_pass"])
        self.assertTrue(p["row"]["agree"])
        self.assertEqual(rep["row"]["harness_points_over_bound"], ["mos_fs_125C_1.08V"])
        self.assertEqual(rep["row"]["harness_worst"]["verdict"], "fail")

    def test_negative_offset_beyond_the_bound_fails_the_row(self):
        env = self.env()
        c, m = self.find(env, MID, "vos_null_v")
        m["value"] = -(BOUND + 0.002)
        _regrade(env, c)
        self.assertEqual(c["status"], "fail")
        p = next(p for p in self.compare(env)["points"] if p["point_id"] == "mos_tt_27C_1.20V")
        self.assertFalse(p["row"]["tool_pass"])

    def test_unexplained_flip_is_reported(self):
        env = self.env()
        c, m = self.find(env, MID, "vos_null_v")
        m["value"] = BOUND + 0.002
        _regrade(env, c)
        rep = self.compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 1)

    def test_flip_inside_the_tolerance_of_the_bound_is_explained(self):
        """A flip is explained only when the two values differ by less than the
        comparison tolerance. Here the tool reads the binding corner 0.5 uV
        under the bound while the harness (21.927 mV) is over it: 27 uV apart
        against a ~3 uV tolerance, so the flip must stay UNEXPLAINED."""
        env = self.env()
        c, m = self.find(env, WORST, "vos_null_v")
        m["value"] = BOUND - 5e-7
        _regrade(env, c)
        rep = self.compare(env)
        self.assertEqual(len(rep["bound_verdict_disagreements"]), 1)
        self.assertFalse(rep["bound_verdict_disagreements"][0]["explained_by_tolerance"])
        self.assertEqual(rep["status"], "disagree")


class TestCli(Base):
    def test_validate_and_compare_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.json")
            with open(good, "w") as f:
                json.dump(self.env(), f)
            self.assertEqual(C.main(["validate", good]), 0)
            out = os.path.join(d, "r.json")
            rc = C.main(["compare", "--envelope", good, "--harness-csv", HARNESS_CSV,
                         "--json-out", out, "--provenance", "k=v"])
            self.assertEqual(rc, 0)
            with open(out) as f:
                rep = json.load(f)
            self.assertEqual(rep["status"], "agree")
            self.assertEqual(rep["provenance"], {"k": "v"})

            bad = os.path.join(d, "bad.json")
            env = self.env()
            env["corners"].pop()
            env["corner_count"] = 44
            with open(bad, "w") as f:
                json.dump(env, f)
            self.assertEqual(C.main(["validate", bad]), 2)

            pert = os.path.join(d, "pert.json")
            env = self.env()
            _, m = self.find(env, MID, "vos_null_v")
            m["value"] *= 1.05
            with open(pert, "w") as f:
                json.dump(env, f)
            self.assertEqual(C.main(["compare", "--envelope", pert, "--harness-csv", HARNESS_CSV]), 1)


if __name__ == "__main__":
    unittest.main()

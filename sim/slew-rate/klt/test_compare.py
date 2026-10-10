#!/usr/bin/env python3
"""Offline negative-control tests for compare.py (issue #95).

    python3 -m unittest discover -s sim/slew-rate/klt -p 'test_*.py'

What these fixtures are, stated plainly: the synthetic envelopes below are
BUILT FROM the committed harness record, so a test that only checks "the
baseline agrees" would be circular. The baseline case is here only as the
control that every negative case perturbs; the tests that carry weight are
the negative controls (reordered, missing, duplicate, extra, null, NaN,
perturbed, mis-biased Vcm, incomplete coverage, errored corner, integrity
flag disagreement, bound flips on either edge), each of which must fail and
name the point/metric it failed on. None of this is evidence about the
circuit -- the envelope in records/ is.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# compare.py imports the shared envelope core from sim/tools (issue #142).
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
import compare as C  # noqa: E402

BENCH = os.path.dirname(HERE)
HARNESS_ID = "20260918-210216-90844d2"
HARNESS_CSV = os.path.join(BENCH, "records", f"{HARNESS_ID}.csv")
HARNESS_TRAN_DIR = os.path.join(BENCH, "corners", HARNESS_ID)
REQUEST = os.path.join(HERE, "slew.request.json")
BOUND = C.SLEW_BOUND_V_PER_US


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
        vout, vd1, vd2, vtail = (float(r[c]) for c in ("vout_dc_v", "vd1_dc_v", "vd2_dc_v", "vtail_dc_v"))
        sr_r, sr_f = float(r["sr_rise_v_per_us"]), float(r["sr_fall_v_per_us"])
        sr_ri, sr_fi = float(r["sr_rise_inner_v_per_us"]), float(r["sr_fall_inner_v_per_us"])
        vals = {
            "t_rise_outer_s": 0.3 / sr_r * 1e-6, "t_fall_outer_s": 0.3 / sr_f * 1e-6,
            "t_rise_inner_s": 0.15 / sr_ri * 1e-6, "t_fall_inner_s": 0.15 / sr_fi * 1e-6,
            "sr_rise_v_per_us": sr_r, "sr_fall_v_per_us": sr_f,
            "sr_rise_inner_v_per_us": sr_ri, "sr_fall_inner_v_per_us": sr_fi,
            "lin_rise_ratio": sr_ri / sr_r, "lin_fall_ratio": sr_fi / sr_f,
            "pre_rise_orel_v": -0.3, "pre_fall_orel_v": 0.3,
            "vinn_max_v": vout + 0.3, "vinn_min_v": vout - 0.3, "vout_dc_v": vout,
            "drive_pp_v": 0.6, "drive_centre_err_v": 0.0,
            "vd1_dc_v": vd1, "vd2_dc_v": vd2, "vtail_dc_v": vtail,
            "vibias_dc_v": float(r["vibias_dc_v"]),
            "op_vout_offset_frac": abs(vout - vdd / 2) / vdd, "op_vout_rail_frac": vout / vdd,
            "op_vd1_rail_frac": vd1 / vdd, "op_vd2_rail_frac": vd2 / vdd,
            "op_vtail_rail_frac": vtail / vdd,
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
    for m in corner["measurements"]:
        m["status"] = _status(m["value"], _request_limits()[m["name"]]) if m["value"] is not None else m["status"]
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

    def compare(self, env, methods=None):
        return C.compare(self.tool(env), self.harness, methods, env)

    @staticmethod
    def find(env, point, name):
        k = C.make_key(*point)
        for c in env["corners"]:
            if C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == k:
                for m in c["measurements"]:
                    if m["name"] == name:
                        return c, m
        raise KeyError((point, name))


WORST = ("mos_ss", -40, 1.08)


class TestRequest(Base):
    def test_request_carries_the_ratified_bound_on_each_edge(self):
        lim = _request_limits()
        for n in C.EDGE_MEASUREMENTS:
            self.assertEqual(lim[n], {"min": BOUND}, n)

    def test_request_declares_every_measurement_compare_reads(self):
        self.assertEqual(set(_request_limits()), set(C.MEASUREMENTS))

    def test_request_is_the_ratified_45_point_grid(self):
        with open(REQUEST) as f:
            req = json.load(f)
        self.assertEqual([p["name"] for p in req["corners"]["process"]], list(C.PROCESSES))
        self.assertEqual(req["corners"]["temperature_c"], list(C.TEMPERATURES))
        self.assertEqual(req["corners"]["supply_v"]["vdd"], list(C.SUPPLIES))
        self.assertEqual(req["corners"]["supply_v"]["vinp"], [v / 2 for v in C.SUPPLIES])
        self.assertEqual(req["analysis"]["kind"], "tran")
        # DR-0005: default solver tolerance -- no override in options or the body
        self.assertNotIn("reltol", json.dumps(req["options"]))
        with open(os.path.join(HERE, "tb_slew.body.spice")) as f:
            body = [ln for ln in f if not ln.startswith("*")]
        for word in ("reltol", "abstol", "vntol"):
            self.assertFalse(any(word in ln for ln in body), word)

    def test_timeout_covers_the_harness_per_corner_cost(self):
        # harness: ~8 min for 45 points ~ 11 s/corner; demand >= 10x headroom.
        with open(REQUEST) as f:
            self.assertGreaterEqual(json.load(f)["options"]["timeout_s"], 110)


class TestHarnessInputs(Base):
    def test_committed_record_is_the_full_grid(self):
        self.assertEqual(set(self.harness), set(C.expected_keys()))
        self.assertEqual(len(self.harness), 45)

    def test_meas_algorithm_reproduces_the_record_from_its_own_waveforms(self):
        worst = 0.0
        for k in C.expected_keys():
            mc = C.method_check(os.path.join(HARNESS_TRAN_DIR, f"{C.key_str(k)}_tran.csv"),
                                float(self.harness[k]["vcm_v"]))
            for col, v in mc.items():
                h = float(self.harness[k][col])
                worst = max(worst, abs(v / h - 1))
        self.assertLessEqual(worst, C.METHOD_CHECK_REL)

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
            rows[3]["sr_rise_v_per_us"] = "nan"
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

    def test_the_worst_point_is_the_ratified_binding_corner(self):
        rep = self.compare(self.env())
        self.assertEqual(rep["row"]["harness_worst"]["point"], "mos_ss_-40C_1.08V")
        self.assertAlmostEqual(rep["row"]["harness_worst"]["value"], 7.51, places=2)

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
        _, m = self.find(env, WORST, "sr_fall_v_per_us")
        m["value"] = None
        with self.assertRaisesRegex(C.InputError, "mos_ss_-40C_1.08V: measurement sr_fall_v_per_us"):
            self.tool(env)

    def test_nonfinite_measurement(self):
        env = self.env()
        _, m = self.find(env, WORST, "sr_rise_v_per_us")
        m["value"] = float("nan")
        with self.assertRaisesRegex(C.InputError, "non-finite"):
            self.tool(env)

    def test_absent_measurement(self):
        env = self.env()
        c, m = self.find(env, WORST, "lin_fall_ratio")
        c["measurements"].remove(m)
        with self.assertRaisesRegex(C.InputError, "lin_fall_ratio missing"):
            self.tool(env)

    def test_vcm_not_half_vdd(self):
        env = self.env()
        c, _ = self.find(env, WORST, "sr_rise_v_per_us")
        c["supply_v"]["vinp"] = 0.60
        with self.assertRaisesRegex(C.InputError, "vinp 0.6 != vdd/2"):
            self.tool(env)

    def test_errored_corner_is_not_evidence(self):
        env = self.env()
        c, _ = self.find(env, WORST, "sr_rise_v_per_us")
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


class TestComparisonNegativeControls(Base):
    def _scale(self, env, point, name, factor):
        c, m = self.find(env, point, name)
        m["value"] *= factor
        _regrade(env, c)

    def test_perturbed_edge_outside_tolerance_is_named(self):
        env = self.env()
        self._scale(env, ("mos_tt", 27, 1.2), "sr_fall_v_per_us", 1.01)
        rep = self.compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V sr_fall_v_per_us" in s for s in rep["out_of_tolerance"]))

    def test_perturbation_inside_tolerance_is_accepted(self):
        env = self.env()
        self._scale(env, ("mos_tt", 27, 1.2), "sr_fall_v_per_us", 1.0015)
        self.assertEqual(self.compare(env)["status"], "agree")

    def test_perturbed_dc_voltage_outside_tolerance_is_named(self):
        env = self.env()
        self._scale(env, ("mos_ff", 125, 1.32), "vd1_dc_v", 1.01)
        rep = self.compare(env)
        self.assertTrue(any("mos_ff_125C_1.32V vd1_dc_v" in s for s in rep["out_of_tolerance"]))

    def test_worst_edge_is_the_min_of_the_two(self):
        env = self.env()
        self._scale(env, ("mos_tt", 27, 1.2), "sr_rise_v_per_us", 0.9)
        rep = self.compare(env)
        p = next(p for p in rep["points"] if p["point_id"] == "mos_tt_27C_1.20V")
        self.assertAlmostEqual(p["metrics"]["sr_worst_v_per_us"]["tool"],
                               p["metrics"]["sr_rise_v_per_us"]["tool"])

    def test_integrity_flag_disagreement_is_named(self):
        for name, label in (("lin_rise_ratio", "ramp_linearity"), ("pre_fall_orel_v", "full_swing_traverse"),
                            ("drive_pp_v", "drive_integrity"), ("op_vd2_rail_frac", "op_sanity")):
            env = self.env()
            c, m = self.find(env, ("mos_sf", 27, 1.2), name)
            m["value"] = {"lin_rise_ratio": 1.5, "pre_fall_orel_v": 0.0, "drive_pp_v": 0.3,
                          "op_vd2_rail_frac": 0.001}[name]
            _regrade(env, c)
            rep = self.compare(env)
            self.assertTrue(any(f"mos_sf_27C_1.20V {label}" in s for s in rep["out_of_tolerance"]), name)

    def test_method_check_failure_is_reported(self):
        methods = {k: {} for k in C.expected_keys()}
        k = C.make_key(*WORST)
        methods[k] = {"sr_rise_v_per_us": float(self.harness[k]["sr_rise_v_per_us"]) * 1.001}
        rep = self.compare(self.env(), methods)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_ss_-40C_1.08V sr_rise_v_per_us" in s for s in rep["method_check_failures"]))


class TestBoundVerdicts(Base):
    """A bound miss stays a miss; a flip is explained only inside the tolerance."""

    def test_either_edge_failing_fails_the_row(self):
        for edge in ("sr_rise_v_per_us", "sr_fall_v_per_us"):
            env = self.env()
            c, m = self.find(env, ("mos_tt", 27, 1.2), edge)
            m["value"] = BOUND - 0.5
            _regrade(env, c)
            self.assertEqual(c["status"], "fail")
            rep = self.compare(env)
            p = next(p for p in rep["points"] if p["point_id"] == "mos_tt_27C_1.20V")
            self.assertFalse(p["row"]["tool_pass"])
            self.assertTrue(p["row"]["harness_pass"])
            self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 1)
            self.assertEqual(rep["status"], "disagree")

    def test_flip_within_tolerance_of_bound_is_explained_not_hidden(self):
        # the binding corner sits ~5e-4 relative above the bound; a tool value
        # 1e-3 lower (inside the 2e-3 tolerance) fails the bound.
        env = self.env()
        c, m = self.find(env, WORST, "sr_fall_v_per_us")
        m["value"] = BOUND - 0.001
        _regrade(env, c)
        rep = self.compare(env)
        self.assertEqual(len(rep["bound_verdict_disagreements"]), 1)
        d = rep["bound_verdict_disagreements"][0]
        self.assertTrue(d["explained_by_tolerance"])
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)

    def test_tool_fail_everywhere_is_reported_per_point(self):
        env = self.env()
        for c in env["corners"]:
            for m in c["measurements"]:
                if m["name"] in C.EDGE_MEASUREMENTS:
                    m["value"] = BOUND - 1.0
            _regrade(env, c)
        rep = self.compare(env)
        self.assertGreater(rep["unexplained_bound_verdict_disagreements"], 30)


class TestCli(Base):
    def test_validate_and_compare_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.json")
            with open(good, "w") as f:
                json.dump(self.env(), f)
            self.assertEqual(C.main(["validate", good]), 0)
            out = os.path.join(d, "r.json")
            rc = C.main(["compare", "--envelope", good, "--harness-csv", HARNESS_CSV,
                         "--harness-tran-dir", HARNESS_TRAN_DIR, "--json-out", out,
                         "--provenance", "k=v"])
            self.assertEqual(rc, 0)
            with open(out) as f:
                rep = json.load(f)
            self.assertEqual(rep["status"], "agree")
            self.assertEqual(rep["provenance"], {"k": "v"})
            self.assertEqual(rep["method_check_failures"], [])

            bad = os.path.join(d, "bad.json")
            env = self.env()
            env["corners"].pop()
            env["corner_count"] = 44
            with open(bad, "w") as f:
                json.dump(env, f)
            self.assertEqual(C.main(["validate", bad]), 2)

            pert = os.path.join(d, "pert.json")
            env = self.env()
            c, m = self.find(env, ("mos_tt", 27, 1.2), "sr_rise_v_per_us")
            m["value"] *= 1.05
            with open(pert, "w") as f:
                json.dump(env, f)
            rc = C.main(["compare", "--envelope", pert, "--harness-csv", HARNESS_CSV,
                         "--harness-tran-dir", HARNESS_TRAN_DIR])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

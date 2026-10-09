#!/usr/bin/env python3
"""Offline negative-control tests for compare.py (issue #85).

    python3 -m unittest discover -s sim/open-loop-ac/klt -p 'test_*.py'

What these fixtures are, stated plainly: the synthetic envelopes below are
BUILT FROM the committed harness record, so a test that only checks "the
baseline agrees" would be circular. The baseline case is here only as the
control that every negative case perturbs; the tests that carry weight are
the negative controls (reordered, missing, duplicate, extra, null, NaN,
perturbed, mis-biased Vcm, incomplete coverage, errored corner), each of
which must fail and name the point/metric it failed on. None of this is
evidence about the circuit -- the envelope in records/ is.
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
import compare as C  # noqa: E402

BENCH = os.path.dirname(HERE)
HARNESS_ID = "20260910-221601-22feaba"
HARNESS_CSV = os.path.join(BENCH, "records", f"{HARNESS_ID}.csv")
HARNESS_AC_DIR = os.path.join(BENCH, "corners", HARNESS_ID)


def _read(path):
    with open(path) as f:
        return f.read()


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def _harness_rows():
    with open(HARNESS_CSV, newline="") as f:
        return list(csv.DictReader(f))


REQUEST_AC = os.path.join(HERE, "openloop_ac.request.json")
REQUEST_OP = os.path.join(HERE, "openloop_op.request.json")
PHASE_MIN_RAD = -2.0 * math.pi / 3.0  # PM >= 60 deg under this bench's PM = 180 deg + phase


def _status(value, kind, bound):
    """Grade like klt sim's `limits`: kind "min"/"max", or "range" with bound (min, max)."""
    if bound is None:
        return "pass"
    if kind == "range":
        lo, hi = bound
        return "pass" if lo <= value <= hi else "fail"
    return "pass" if C._passes(value, kind, bound) else "fail"


def _wrap_rad(phi):
    """ngspice vp(): phase wrapped to (-pi, pi]."""
    w = math.fmod(phi + math.pi, 2.0 * math.pi)
    if w <= 0.0:
        w += 2.0 * math.pi
    return w - math.pi


def _envelope(kind, rows, bias):
    """A synthetic klt-sim-shaped envelope carrying the harness's own numbers."""
    corners = []
    for r in rows:
        k = C.make_key(r["corner"], r["temp_c"], r["vdd_v"])
        vdd = float(r["vdd_v"])
        if kind == "ac":
            vals = [
                ("av0_db", float(r["av0_db"]), "min", 37.8),
                ("gbw_hz", float(r["gbw_hz"]) * (1 + bias[k]), "min", 4.74e6),
                ("phase_at_ugf_rad", math.radians(float(r["pm_deg"]) - 180.0), "range",
                 (PHASE_MIN_RAD, 0.0)),
            ]
        else:
            vout, vd1, vd2, vtail = (float(r[c]) for c in ("vout_dc_v", "vd1_dc_v", "vd2_dc_v", "vtail_dc_v"))
            vals = [
                ("ivdd_total_a", float(r["ivdd_total_a"]), "max", 119.7e-6),
                ("vout_dc_v", vout, None, None),
                ("vd1_dc_v", vd1, None, None),
                ("vd2_dc_v", vd2, None, None),
                ("vtail_dc_v", vtail, None, None),
                ("vibias_dc_v", float(r["vibias_dc_v"]), None, None),
                ("op_vcm_frac", 0.5, None, None),
                ("op_vout_offset_frac", abs(vout - vdd / 2) / vdd, "max", 0.15),
                ("op_vout_rail_frac", vout / vdd, None, None),
                ("op_vd1_rail_frac", vd1 / vdd, None, None),
                ("op_vd2_rail_frac", vd2 / vdd, None, None),
                ("op_vtail_rail_frac", vtail / vdd, None, None),
            ]
        ms = [{"name": n, "value": v, "status": _status(v, kd, b)} for n, v, kd, b in vals]
        st = "fail" if any(m["status"] == "fail" for m in ms) else "pass"
        corners.append({
            "corner_id": f"{k[0]}/vdd={vdd:.3f}_vinp={vdd / 2:.3f}V/{k[1]}C",
            "process": k[0], "temperature_c": k[1],
            "supply_v": {"vdd": vdd, "vinp": vdd / 2},
            "status": st, "measurements": ms,
        })
    return {
        "schema_version": 3,
        "status": "fail" if any(c["status"] == "fail" for c in corners) else "pass",
        "corner_count": len(corners),
        "coverage": {"nothing_checked": False, "skipped": []},
        "corners": corners,
    }


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _harness_rows()
        cls.harness = C.load_harness_csv(HARNESS_CSV)
        cls.bias = {k: C.gbw_method_bias(os.path.join(HARNESS_AC_DIR, f"{C.key_str(k)}_ac.csv"))
                    for k in C.expected_keys()}

    def envs(self):
        return _envelope("ac", self.rows, self.bias), _envelope("op", self.rows, self.bias)

    def run_compare(self, ac_env, op_env, harness=None):
        ac = C.index_envelope(ac_env, "ac")
        op = C.index_envelope(op_env, "op")
        return C.compare(ac, op, harness or self.harness, self.bias, ac_env, op_env)


class TestHarnessInputs(Base):
    def test_committed_record_is_the_full_grid(self):
        self.assertEqual(sorted(self.harness), sorted(C.expected_keys()))
        self.assertEqual(len(self.harness), 45)

    def test_gbw_method_bias_is_one_signed_and_bounded(self):
        for k, b in self.bias.items():
            self.assertGreaterEqual(b, 0.0, C.key_str(k))
            self.assertLessEqual(b, C.GBW_METHOD_BIAS_MAX + 1e-12, C.key_str(k))

    def test_harness_raw_sweeps_reproduce_the_record(self):
        # The raw AC sweeps compare.py derives the GBW method bias from are
        # the ones the CSV was computed from: re-deriving the harness's own
        # log-interpolated GBW from them must give the CSV value.
        for k in C.expected_keys():
            path = os.path.join(HARNESS_AC_DIR, f"{C.key_str(k)}_ac.csv")
            fr, db = [], []
            for line in _read(path).splitlines():
                p = line.split()
                if len(p) >= 4:
                    fr.append(float(p[0]))
                    db.append(float(p[1]))
            i = next(i for i in range(1, len(db)) if db[i - 1] >= 0 > db[i])
            frac = db[i - 1] / (db[i - 1] - db[i])
            g = 10 ** (math.log10(fr[i - 1]) + frac * (math.log10(fr[i]) - math.log10(fr[i - 1])))
            self.assertAlmostEqual(g / self.harness[k]["gbw_hz"], 1.0, delta=1e-5, msg=C.key_str(k))

    def test_duplicate_harness_row_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "dup.csv")
            lines = _read(HARNESS_CSV).splitlines()
            _write(p, "\n".join(lines + [lines[5]]) + "\n")
            with self.assertRaisesRegex(C.InputError, r"duplicate row"):
                C.load_harness_csv(p)

    def test_nonfinite_harness_value_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "nan.csv")
            rows = copy.deepcopy(self.rows)
            rows[3]["av0_db"] = "nan"
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            with self.assertRaisesRegex(C.InputError, rf"{rows[3]['point_id']}: harness av0_db"):
                C.load_harness_csv(p)

    def test_missing_harness_row_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "short.csv")
            lines = _read(HARNESS_CSV).splitlines()
            dropped = lines.pop(10).split(",")[0]
            _write(p, "\n".join(lines) + "\n")
            with self.assertRaisesRegex(C.InputError, rf"{dropped}: missing from harness CSV"):
                C.load_harness_csv(p)


class TestBaselineControl(Base):
    def test_identical_numbers_agree(self):
        rep = self.run_compare(*self.envs())
        self.assertEqual(rep["status"], "agree", rep["out_of_tolerance"])
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)

    def test_historical_gain_failure_stays_a_failure(self):
        # The harness's own worst Av0 (37.7812 dB at mos_fs_125C_1.08V) is
        # below the ratified 37.8 dB; nothing in the comparison may round it
        # into a pass.
        rep = self.run_compare(*self.envs())
        hw = rep["rows"]["open_loop_dc_gain"]["harness_worst"]
        self.assertEqual(hw["point"], "mos_fs_125C_1.08V")
        self.assertEqual(hw["verdict"], "fail")
        pt = next(p for p in rep["points"] if p["point_id"] == "mos_fs_125C_1.08V")
        self.assertFalse(pt["rows"]["open_loop_dc_gain"]["harness_pass"])
        self.assertEqual(pt["rows"]["open_loop_dc_gain"]["tool_status"], "fail")

    def test_reordered_corners_join_identically(self):
        ac, op = self.envs()
        base = self.run_compare(ac, op)
        ac2, op2 = copy.deepcopy(ac), copy.deepcopy(op)
        ac2["corners"].reverse()
        op2["corners"] = op2["corners"][17:] + op2["corners"][:17]
        rep = self.run_compare(ac2, op2)
        self.assertEqual(rep["points"], base["points"])


class TestEnvelopeNegativeControls(Base):
    def test_missing_corner(self):
        ac, _ = self.envs()
        gone = ac["corners"].pop(7)
        ac["corner_count"] = len(ac["corners"])
        with self.assertRaisesRegex(C.InputError, rf"{gone['process']}_{gone['temperature_c']}C_.*missing from"):
            C.index_envelope(ac, "ac")

    def test_duplicate_corner(self):
        _, op = self.envs()
        op["corners"].append(copy.deepcopy(op["corners"][4]))
        op["corner_count"] = len(op["corners"])
        with self.assertRaisesRegex(C.InputError, r"duplicate corner"):
            C.index_envelope(op, "op")

    def test_extra_off_grid_corner(self):
        ac, _ = self.envs()
        extra = copy.deepcopy(ac["corners"][0])
        extra["temperature_c"] = 85
        ac["corners"].append(extra)
        ac["corner_count"] = len(ac["corners"])
        with self.assertRaisesRegex(C.InputError, r"mos_tt_85C_1.08V: not a point of the ratified grid"):
            C.index_envelope(ac, "ac")

    def test_corner_count_mismatch(self):
        ac, _ = self.envs()
        ac["corner_count"] = 44
        with self.assertRaisesRegex(C.InputError, r"corner_count 44"):
            C.index_envelope(ac, "ac")

    def test_null_measurement(self):
        ac, _ = self.envs()
        ac["corners"][12]["measurements"][1]["value"] = None
        pid = C.key_str(C.make_key(ac["corners"][12]["process"], ac["corners"][12]["temperature_c"],
                                   ac["corners"][12]["supply_v"]["vdd"]))
        with self.assertRaisesRegex(C.InputError, rf"{pid}: measurement gbw_hz value None"):
            C.index_envelope(ac, "ac")

    def test_nonfinite_measurement(self):
        _, op = self.envs()
        op["corners"][30]["measurements"][0]["value"] = float("inf")
        with self.assertRaisesRegex(C.InputError, r"measurement ivdd_total_a value inf"):
            C.index_envelope(op, "op")

    def test_absent_measurement(self):
        _, op = self.envs()
        op["corners"][2]["measurements"] = [m for m in op["corners"][2]["measurements"]
                                            if m["name"] != "op_vd2_rail_frac"]
        with self.assertRaisesRegex(C.InputError, r"measurement op_vd2_rail_frac missing"):
            C.index_envelope(op, "op")

    def test_vcm_not_half_vdd(self):
        ac, _ = self.envs()
        ac["corners"][20]["supply_v"]["vinp"] = 0.6
        ac["corners"][20]["supply_v"]["vdd"] = 1.32
        with self.assertRaisesRegex(C.InputError, r"vinp 0.6 != vdd/2"):
            C.index_envelope(ac, "ac")

    def test_errored_corner_is_not_evidence(self):
        ac, _ = self.envs()
        ac["corners"][0]["status"] = "error"
        with self.assertRaisesRegex(C.InputError, r"mos_tt_-40C_1.08V: corner status 'error'"):
            C.index_envelope(ac, "ac")

    def test_inconclusive_run_is_not_evidence(self):
        ac, _ = self.envs()
        ac["status"] = "inconclusive"
        with self.assertRaisesRegex(C.InputError, r"aggregate status 'inconclusive'"):
            C.index_envelope(ac, "ac")

    def test_nothing_checked(self):
        _, op = self.envs()
        op["coverage"]["nothing_checked"] = True
        with self.assertRaisesRegex(C.InputError, r"nothing_checked"):
            C.index_envelope(op, "op")

    def test_skipped_coverage(self):
        _, op = self.envs()
        op["coverage"]["skipped"] = [{"id": "limit:x", "reason": "unavailable_measurement"}]
        with self.assertRaisesRegex(C.InputError, r"coverage.skipped is non-empty"):
            C.index_envelope(op, "op")

    def test_klt_error_envelope(self):
        with self.assertRaisesRegex(C.InputError, r"klt error envelope"):
            C.index_envelope({"schema_version": 1, "error": {"command": "sim", "message": "x"}}, "ac")


class TestComparisonNegativeControls(Base):
    def _perturb(self, env, idx, name, fn):
        for m in env["corners"][idx]["measurements"]:
            if m["name"] == name:
                m["value"] = fn(m["value"])
        c = env["corners"][idx]
        return C.key_str(C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]))

    def test_perturbed_gain_outside_tolerance_is_named(self):
        ac, op = self.envs()
        pid = self._perturb(ac, 9, "av0_db", lambda v: v + 0.05)
        rep = self.run_compare(ac, op)
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(len(rep["out_of_tolerance"]), 1)
        self.assertIn(f"{pid} av0_db", rep["out_of_tolerance"][0])

    def test_perturbation_inside_tolerance_is_accepted(self):
        ac, op = self.envs()
        self._perturb(ac, 9, "av0_db", lambda v: v + 0.015)
        self.assertEqual(self.run_compare(ac, op)["status"], "agree")

    def test_perturbed_iq_outside_tolerance_is_named(self):
        ac, op = self.envs()
        pid = self._perturb(op, 33, "ivdd_total_a", lambda v: v * 1.002)
        rep = self.run_compare(ac, op)
        self.assertIn(f"{pid} ivdd_total_a", "\n".join(rep["out_of_tolerance"]))

    def test_perturbed_phase_outside_tolerance_is_named(self):
        ac, op = self.envs()
        pid = self._perturb(ac, 40, "phase_at_ugf_rad", lambda v: v + math.radians(0.2))
        rep = self.run_compare(ac, op)
        self.assertIn(f"{pid} pm_deg", "\n".join(rep["out_of_tolerance"]))

    def test_gbw_without_method_correction_would_be_flagged(self):
        # Negative control for the method term itself: a tool value equal to
        # the harness's log-interpolated GBW is NOT what ngspice's .meas
        # produces; at the corners where the method bias exceeds the 2e-3
        # solver tolerance it must be flagged -- and where it does not, the
        # report still carries the uncorrected difference.
        ac, op = self.envs()
        for c in ac["corners"]:
            k = C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"])
            for m in c["measurements"]:
                if m["name"] == "gbw_hz":
                    m["value"] = self.harness[k]["gbw_hz"] * (1 - 3e-3)
        rep = self.run_compare(ac, op)
        flagged = [s for s in rep["out_of_tolerance"] if " gbw_hz:" in s]
        self.assertEqual(len(flagged), 45)
        pt = rep["points"][0]["metrics"]["gbw_hz"]
        self.assertIn("rel_delta_uncorrected", pt)

    def test_op_sanity_disagreement_is_named(self):
        ac, op = self.envs()
        for m in op["corners"][5]["measurements"]:
            if m["name"] == "op_vd1_rail_frac":
                m["status"] = "fail"
        c = op["corners"][5]
        pid = C.key_str(C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]))
        rep = self.run_compare(ac, op)
        self.assertIn(f"{pid} op sanity", "\n".join(rep["out_of_tolerance"]))

    def test_bound_flip_within_tolerance_is_reported_as_explained(self):
        # A tool Av0 of 37.8005 dB at the harness's 37.7812 dB point is inside
        # the 0.02 dB comparison tolerance (delta 0.0193 dB) but on the other
        # side of the 37.8 dB bound: the disagreement must be REPORTED (never
        # hidden), flagged as explained by tolerance, and the tool's verdict
        # stands -- and the comparison as a whole still agrees.
        ac, op = self.envs()
        for c in ac["corners"]:
            if (c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == ("mos_fs", 125, 1.08):
                for m in c["measurements"]:
                    if m["name"] == "av0_db":
                        m["value"], m["status"] = 37.8005, "pass"
        rep = self.run_compare(ac, op)
        pt = next(p for p in rep["points"] if p["point_id"] == "mos_fs_125C_1.08V")
        self.assertTrue(pt["metrics"]["av0_db"]["within"], pt["metrics"]["av0_db"])
        d = rep["bound_verdict_disagreements"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["point"], "mos_fs_125C_1.08V")
        self.assertTrue(d[0]["explained_by_tolerance"])
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)
        self.assertEqual(rep["out_of_tolerance"], [])
        self.assertEqual(rep["status"], "agree")

    def test_bound_flip_beyond_tolerance_value_disagrees(self):
        # The same flip with a value outside the 0.02 dB tolerance (37.81 dB,
        # delta 0.0288 dB) is an out-of-tolerance point: the run disagrees.
        ac, op = self.envs()
        for c in ac["corners"]:
            if (c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == ("mos_fs", 125, 1.08):
                for m in c["measurements"]:
                    if m["name"] == "av0_db":
                        m["value"], m["status"] = 37.81, "pass"
        rep = self.run_compare(ac, op)
        pt = next(p for p in rep["points"] if p["point_id"] == "mos_fs_125C_1.08V")
        self.assertFalse(pt["metrics"]["av0_db"]["within"])
        self.assertIn("mos_fs_125C_1.08V av0_db", "\n".join(rep["out_of_tolerance"]))
        self.assertEqual(rep["status"], "disagree")

    def test_bound_flip_outside_tolerance_is_unexplained(self):
        ac, op = self.envs()
        c = ac["corners"][0]
        for m in c["measurements"]:
            if m["name"] == "av0_db":
                m["status"] = "fail"  # status inconsistent with a value far above the bound
        rep = self.run_compare(ac, op)
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 1)
        self.assertEqual(rep["status"], "disagree")


class TestPhaseWrap(Base):
    """vp(out) is wrapped to (-pi, pi]; the harness's PM uses continuous phase.

    The PM row is graded as phase_at_ugf_rad in [-2*pi/3, 0]. The max-0 bound
    is what makes a wrapped unstable corner fail in the tool's OWN verdict;
    the residual straddle case near PM ~ 0 is caught only by the comparison.
    """

    def _set_phase(self, ac, key, value):
        for c in ac["corners"]:
            if C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == key:
                for m in c["measurements"]:
                    if m["name"] == "phase_at_ugf_rad":
                        m["value"] = value
                        m["status"] = _status(value, "range", (PHASE_MIN_RAD, 0.0))
                c["status"] = "fail" if any(m["status"] == "fail" for m in c["measurements"]) else "pass"
                return C.key_str(key)
        raise AssertionError(key)

    def test_request_limits_are_the_ratified_bounds(self):
        with open(REQUEST_AC) as f:
            ac_req = json.load(f)
        with open(REQUEST_OP) as f:
            op_req = json.load(f)
        lim = {m["name"]: m.get("limits") for m in ac_req["measurements"] + op_req["measurements"]}
        self.assertEqual(lim["av0_db"], {"min": 37.8})
        self.assertEqual(lim["gbw_hz"], {"min": 4.74e6})
        self.assertEqual(lim["ivdd_total_a"], {"max": 119.7e-6})
        # Two-sided: min alone would pass a wrapped unstable corner.
        self.assertEqual(set(lim["phase_at_ugf_rad"]), {"min", "max"})
        self.assertAlmostEqual(lim["phase_at_ugf_rad"]["min"], PHASE_MIN_RAD, places=15)
        self.assertEqual(lim["phase_at_ugf_rad"]["max"], 0.0)

    def test_wrapped_unstable_corner_fails_the_tool_verdict(self):
        # PM = -10 deg: continuous phase -190 deg, vp() reads +170 deg.
        phi = _wrap_rad(math.radians(-10.0 - 180.0))
        self.assertAlmostEqual(math.degrees(phi), 170.0, places=9)
        self.assertEqual(_status(phi, "min", PHASE_MIN_RAD), "pass")  # the min-only hole
        self.assertEqual(_status(phi, "range", (PHASE_MIN_RAD, 0.0)), "fail")
        # The verdict equals PM >= 60 deg across PM in (-180, 180] deg.
        for pm in [x * 0.5 for x in range(-359, 361)]:
            got = _status(_wrap_rad(math.radians(pm - 180.0)), "range", (PHASE_MIN_RAD, 0.0)) == "pass"
            self.assertEqual(got, pm >= 60.0, pm)

    def test_wrapped_unstable_corner_is_flagged_by_the_comparison(self):
        ac, op = self.envs()
        k = C.expected_keys()[7]
        pid = self._set_phase(ac, k, _wrap_rad(math.radians(-10.0 - 180.0)))
        rep = self.run_compare(ac, op)
        self.assertIn(f"{pid} pm_deg", "\n".join(rep["out_of_tolerance"]))
        self.assertEqual(rep["status"], "disagree")

    def test_straddle_interpolation_near_zero_pm_is_caught_by_the_comparison(self):
        # Harness: PM 0.5 deg (continuous phase -179.5 deg, a fail). Tool: the
        # bracketing points straddled the wrap and .meas interpolated to
        # -100 deg, which passes [-120, 0]. The tool verdict alone is wrong;
        # the comparison must name the point and refuse to agree.
        ac, op = self.envs()
        k = C.expected_keys()[3]
        harness = copy.deepcopy(self.harness)
        harness[k]["pm_deg"] = 0.5
        pid = self._set_phase(ac, k, math.radians(-100.0))
        rep = self.run_compare(ac, op, harness)
        self.assertIn(f"{pid} pm_deg", "\n".join(rep["out_of_tolerance"]))
        d = [x for x in rep["bound_verdict_disagreements"] if x["point"] == pid]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["row"], "phase_margin")
        self.assertFalse(d[0]["explained_by_tolerance"])
        self.assertEqual(rep["status"], "disagree")


class TestCli(Base):
    def test_validate_and_compare_exit_codes(self):
        ac, op = self.envs()
        with tempfile.TemporaryDirectory() as d:
            pa, po, pj = (os.path.join(d, n) for n in ("ac.json", "op.json", "cmp.json"))
            _write(pa, json.dumps(ac))
            _write(po, json.dumps(op))
            self.assertEqual(C.main(["validate", "--kind", "ac", pa]), 0)
            self.assertEqual(C.main(["validate", "--kind", "op", pa]), 2)  # wrong kind: OP names absent
            args = ["compare", "--ac", pa, "--op", po, "--harness-csv", HARNESS_CSV,
                    "--harness-ac-dir", HARNESS_AC_DIR, "--json-out", pj, "--provenance", "klt=test"]
            self.assertEqual(C.main(args), 0)
            rep = json.loads(_read(pj))
            self.assertEqual(rep["provenance"], {"klt": "test"})
            self.assertEqual(len(rep["inputs"]["ac_envelope"]["sha256"]), 64)
            ac["corners"][3]["measurements"][0]["value"] += 1.0
            _write(pa, json.dumps(ac))
            self.assertEqual(C.main(args), 1)
            ac["corners"].pop()
            ac["corner_count"] -= 1
            _write(pa, json.dumps(ac))
            self.assertEqual(C.main(args), 2)


if __name__ == "__main__":
    unittest.main()

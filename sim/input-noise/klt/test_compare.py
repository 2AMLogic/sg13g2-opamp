#!/usr/bin/env python3
"""Offline negative-control tests for compare.py (issue #96).

    python3 -m pytest sim/input-noise/klt/test_compare.py
    python3 -m unittest discover -s sim/input-noise/klt -p 'test_*.py'

What these fixtures are, stated plainly: the synthetic envelopes below are
BUILT FROM the committed harness record, so a test that only checks "the
baseline agrees" would be circular. The baseline case is here only as the
control that every negative case perturbs; the tests that carry weight are the
negative controls (reordered, missing, duplicate, extra, null, NaN, perturbed,
mis-biased Vcm, wrong band, incomplete coverage, errored corner, bound flips),
each of which must fail and name the point/metric it failed on.

These are comparator tests, NOT signoff evidence and NOT a statement about the
circuit: no real `klt sim` envelope for this bench exists yet. The envelope in
records/ (when one lands) is the evidence.
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
HARNESS_ID = "20260918-203850-90844d2"
HARNESS_CSV = os.path.join(BENCH, "records", f"{HARNESS_ID}.csv")
REQUEST = os.path.join(HERE, "noise.request.json")
BOUND = C.NOISE_BOUND_VRMS


def _harness_rows():
    with open(HARNESS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _status(value, limits):
    if not limits:
        return "pass"
    lo, hi = limits.get("min"), limits.get("max")
    return "pass" if (lo is None or value >= lo) and (hi is None or value <= hi) else "fail"


def _request():
    with open(REQUEST) as f:
        return json.load(f)


def _request_limits():
    return {m["name"]: m.get("limits") for m in _request()["measurements"]}


def _envelope(rows):
    """A synthetic klt-sim-shaped envelope carrying the harness's own numbers."""
    limits = _request_limits()
    corners = []
    for r in rows:
        k = C.make_key(r["corner"], r["temp_c"], r["vdd_v"])
        vdd = float(r["vdd_v"])
        vals = {C.INTEGRATED: float(r["vni_int_vrms"])}
        for m, col in C.SPOTS.items():
            vals[m] = float(r[col])
        vals.update(C.BAND_EXPECTED)
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
        if m["value"] is not None:
            m["status"] = _status(m["value"], lim[m["name"]])
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


WORST = ("mos_fs", 125, 1.08)   # harness-worst integrated noise (108.949 uVrms)
MID = ("mos_tt", 27, 1.2)       # a comfortably in-bound point (87.3 uVrms)


class TestRequest(Base):
    def test_request_carries_the_ratified_bound(self):
        self.assertEqual(_request_limits()[C.INTEGRATED], {"max": BOUND})
        self.assertAlmostEqual(BOUND, 108.9e-6, places=12)

    def test_request_declares_every_measurement_compare_reads(self):
        self.assertEqual(set(_request_limits()), set(C.MEASUREMENTS))

    def test_band_is_the_ratified_100hz_to_1mhz(self):
        req = _request()
        self.assertEqual(req["analysis"]["kind"], "noise")
        self.assertEqual(req["analysis"]["args"], "v(out) Vinp dec 20 100 1meg")
        by = {m["name"]: m for m in req["measurements"]}
        self.assertEqual(by[C.INTEGRATED]["expr"], "noise2.inoise_total")
        # the band/spot integrity checks are graded by the tool, not just read
        for n in C.BAND_CHECKS:
            self.assertIn("limits", by[n], n)
            lo, hi = by[n]["limits"]["min"], by[n]["limits"]["max"]
            self.assertLessEqual(lo, C.BAND_EXPECTED[n])
            self.assertGreaterEqual(hi, C.BAND_EXPECTED[n])

    def test_request_is_the_ratified_45_point_grid(self):
        req = _request()
        self.assertEqual([p["name"] for p in req["corners"]["process"]], list(C.PROCESSES))
        for p in req["corners"]["process"]:
            self.assertEqual(p["sections"][1], {"lib": "libs.tech/ngspice/models/cornerCAP.lib", "section": "cap_typ"})
        self.assertEqual(req["corners"]["temperature_c"], list(C.TEMPERATURES))
        self.assertEqual(req["corners"]["supply_v"]["vdd"], list(C.SUPPLIES))
        self.assertEqual(req["corners"]["supply_v"]["vinp"], [v / 2 for v in C.SUPPLIES])
        self.assertTrue(req["options"]["stage_model_inputs"])
        self.assertEqual(len(req["options"]["osdi_preload"]), 4)
        # DR-0005: default solver tolerance -- no override in options or the body
        self.assertNotIn("reltol", json.dumps(req["options"]))
        with open(os.path.join(HERE, "tb_noise.body.spice")) as f:
            body = [ln for ln in f if not ln.startswith("*")]
        for word in ("reltol", "abstol", "vntol", ".control", ".end\n"):
            self.assertFalse(any(word in ln for ln in body), word)
        self.assertEqual(sum(ln.startswith(".include") for ln in body), 1)
        self.assertTrue(any(".include ../../../design/netlist/opamp_core.spice" in ln for ln in body))
        self.assertTrue(any(ln.startswith("Cload out vss 2e-12") for ln in body))


class TestHarnessInputs(Base):
    def test_committed_record_is_the_full_grid(self):
        self.assertEqual(set(self.harness), set(C.expected_keys()))
        self.assertEqual(len(self.harness), 45)

    def test_harness_worst_is_the_documented_corner(self):
        worst = max((v["vni_int_vrms"], k) for k, v in self.harness.items())
        self.assertEqual(C.key_str(worst[1]), "mos_fs_125C_1.08V")
        self.assertAlmostEqual(worst[0] * 1e6, 108.949, places=3)

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
            rows[3]["vni_int_vrms"] = "nan"
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

    def test_short_or_malformed_row_is_input_error(self):
        """A truncated row or an unparsable temp_c is exit-2 material (an
        InputError), never a raw KeyError/ValueError (issue #181)."""
        with open(HARNESS_CSV) as f:
            lines = f.read().splitlines()
        short = lines[0] + "\n" + lines[1].split(",")[0] + "\n" + "\n".join(lines[2:]) + "\n"
        cells = lines[1].split(",")
        cells[lines[0].split(",").index("temp_c")] = "hot"
        malformed = "\n".join([lines[0], ",".join(cells)] + lines[2:]) + "\n"
        for text in (short, malformed):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "h.csv")
                with open(p, "w") as f:
                    f.write(text)
                with self.assertRaises(C.InputError):
                    C.load_harness_csv(p)


class TestBaselineControl(Base):
    def test_identical_numbers_agree(self):
        rep = self.compare(self.env())
        self.assertEqual(rep["status"], "agree")
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["out_of_tolerance"], [])
        self.assertEqual(rep["bound_verdict_disagreements"], [])
        self.assertTrue(rep["tolerances_provisional"])

    def test_bound_miss_stays_a_miss(self):
        # the harness worst (108.949 uVrms) is above the literal 108.9 uVrms
        # bound; the tool's verdict there is a fail and the two paths agree.
        env = self.env()
        c, m = self.find(env, WORST, C.INTEGRATED)
        self.assertEqual(m["status"], "fail")
        self.assertEqual(c["status"], "fail")
        p = next(p for p in self.compare(env)["points"] if p["point_id"] == "mos_fs_125C_1.08V")
        self.assertFalse(p["row"]["tool_pass"])
        self.assertFalse(p["row"]["harness_pass"])
        self.assertTrue(p["row"]["agree"])

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
        _, m = self.find(env, WORST, C.INTEGRATED)
        m["value"] = None
        with self.assertRaisesRegex(C.InputError, "mos_fs_125C_1.08V: measurement inoise_int_vrms"):
            self.tool(env)

    def test_nonfinite_measurement(self):
        env = self.env()
        _, m = self.find(env, WORST, "inoise_1khz_v_rthz")
        m["value"] = float("nan")
        with self.assertRaisesRegex(C.InputError, "non-finite"):
            self.tool(env)

    def test_absent_measurement(self):
        env = self.env()
        c, m = self.find(env, WORST, "inoise_1mhz_v_rthz")
        c["measurements"].remove(m)
        with self.assertRaisesRegex(C.InputError, "inoise_1mhz_v_rthz missing"):
            self.tool(env)

    def test_vcm_not_half_vdd(self):
        env = self.env()
        c, _ = self.find(env, WORST, C.INTEGRATED)
        c["supply_v"]["vinp"] = 0.60
        with self.assertRaisesRegex(C.InputError, "vinp 0.6 != vdd/2"):
            self.tool(env)

    def test_wrong_band_is_refused(self):
        # a different upper band edge changes the number; it is not a looser measurement
        env = self.env()
        _, m = self.find(env, MID, "band_f_last_hz")
        m["value"] = 1e7
        with self.assertRaisesRegex(C.InputError, "band_f_last_hz"):
            self.tool(env)

    def test_wrong_point_count_is_refused(self):
        env = self.env()
        _, m = self.find(env, MID, "band_points")
        m["value"] = 41.0
        with self.assertRaisesRegex(C.InputError, "band_points"):
            self.tool(env)

    def test_misplaced_spot_frequency_is_refused(self):
        env = self.env()
        _, m = self.find(env, MID, "spot_f_10khz_hz")
        m["value"] = 10000.0 * 1.12
        with self.assertRaisesRegex(C.InputError, "spot_f_10khz_hz"):
            self.tool(env)

    def test_errored_corner_is_not_evidence(self):
        env = self.env()
        c, _ = self.find(env, WORST, C.INTEGRATED)
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

    def test_perturbed_integrated_outside_tolerance_is_named(self):
        env = self.env()
        self._scale(env, MID, C.INTEGRATED, 1.01)
        rep = self.compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V inoise_int_vrms" in s for s in rep["out_of_tolerance"]))

    def test_perturbation_inside_tolerance_is_accepted(self):
        env = self.env()
        self._scale(env, MID, C.INTEGRATED, 1.0015)
        self.assertEqual(self.compare(env)["status"], "agree")

    def test_perturbed_spot_density_outside_tolerance_is_named(self):
        env = self.env()
        self._scale(env, ("mos_ss", -40, 1.32), "inoise_100khz_v_rthz", 0.98)
        rep = self.compare(env)
        self.assertTrue(any("mos_ss_-40C_1.32V inoise_100khz_v_rthz" in s for s in rep["out_of_tolerance"]))

    def test_each_spot_is_joined_to_its_own_column(self):
        env = self.env()
        _, m = self.find(env, MID, "inoise_1khz_v_rthz")
        m["value"] = float(self.harness[C.make_key(*MID)]["vni_10khz_v_rthz"])  # swapped decade
        rep = self.compare(env)
        self.assertTrue(any("inoise_1khz_v_rthz" in s for s in rep["out_of_tolerance"]))


class TestBoundVerdicts(Base):
    """A bound miss stays a miss; a flip is explained only inside the tolerance."""

    def test_clear_miss_in_tool_is_an_unexplained_disagreement(self):
        env = self.env()
        c, m = self.find(env, MID, C.INTEGRATED)
        m["value"] = BOUND * 1.10
        _regrade(env, c)
        self.assertEqual(c["status"], "fail")
        rep = self.compare(env)
        p = next(p for p in rep["points"] if p["point_id"] == "mos_tt_27C_1.20V")
        self.assertFalse(p["row"]["tool_pass"])
        self.assertTrue(p["row"]["harness_pass"])
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 1)
        self.assertEqual(rep["status"], "disagree")

    def test_flip_within_tolerance_of_bound_is_explained_not_hidden(self):
        # the harness-worst sits 4.5e-4 relative above the bound (failing); a
        # tool value 1e-3 lower passes the bound, inside the 2e-3 tolerance.
        env = self.env()
        c, m = self.find(env, WORST, C.INTEGRATED)
        m["value"] = BOUND * 0.9999
        _regrade(env, c)
        self.assertEqual(m["status"], "pass")
        rep = self.compare(env)
        self.assertEqual(len(rep["bound_verdict_disagreements"]), 1)
        self.assertTrue(rep["bound_verdict_disagreements"][0]["explained_by_tolerance"])
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)

    def test_tool_passes_everywhere_is_reported_where_harness_fails(self):
        env = self.env()
        for c in env["corners"]:
            for m in c["measurements"]:
                if m["name"] == C.INTEGRATED:
                    m["value"] = BOUND * 0.5
            _regrade(env, c)
        rep = self.compare(env)
        self.assertGreater(len(rep["out_of_tolerance"]), 40)
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
            _, m = self.find(env, MID, C.INTEGRATED)
            m["value"] *= 1.05
            with open(pert, "w") as f:
                json.dump(env, f)
            rc = C.main(["compare", "--envelope", pert, "--harness-csv", HARNESS_CSV])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

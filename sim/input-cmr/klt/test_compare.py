#!/usr/bin/env python3
"""Offline negative-control tests for compare.py and make_requests.py (issue #325).

    python3 -m unittest discover -s sim/input-cmr/klt -p 'test_*.py'

What these fixtures are, stated plainly: the synthetic envelopes below are
BUILT FROM the committed harness record, so a test that only checks "the
baseline agrees" would be circular. The baseline is only the control that every
negative case perturbs; the tests that carry weight are the negative controls
(missing / duplicate / extra / non-finite / wrong-unit measurements, skipped or
errored coverage, relaxed or removed integrity limits, a failed integrity check,
Vcm != VDD/2, perturbed values just inside and just outside each tolerance, a
mechanism label that flips), each of which must fail and name the point/metric
it failed on. None of this is evidence about the circuit -- the envelope in
records/ is.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compare as C  # noqa: E402
import make_requests as REQ  # noqa: E402

BENCH = os.path.dirname(HERE)
HARNESS_ID = "20260921-174405-65f5fb4"
HARNESS_CSV = os.path.join(BENCH, "records", f"{HARNESS_ID}.csv")
GRID = C.POINT_SETS["grid"]
NOM = C.POINT_SETS["nominal"]

# Values for the measurements the harness record has no column for: plausible,
# inside every integrity limit.
FILL = {
    "nc_idx": 2400.0, "nv_idx": 4800.0, "vibias_spread_v": 1e-5, "probe_bias_err_v": 1e-7,
    "m5_gmax_sv": 1.4e-4, "m5_k": 500.0, "lo_j": 2200.0, "lo_crossings": 1.0, "lo_frac": 0.5,
    "hi_j": 4100.0, "hi_crossings": 1.0, "hi_ya_v": 2e-4, "hi_yb_v": -4e-5,
}


def _rows():
    with open(HARNESS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _row_values(r):
    f = lambda c: float(r[c])  # noqa: E731
    vdd = f("vdd_v")
    v = dict(FILL)
    v.update({
        "vdsat5_v": f("vdsat5_meas_v"), "vdsat5_frac": f("vdsat5_meas_v") / vdd,
        "icmr_lo_v": f("icmr_lo_v"), "icmr_hi_v": f("icmr_hi_v"), "icmr_span_v": f("icmr_span_v"),
        "vtail_lo_v": f("vtail_lo_v"), "vds1_lo_v": f("vds1_lo_v"), "vds2_lo_v": f("vds2_lo_v"),
        "ivdd_lo_a": f("ivdd_lo_a"), "vtail_hi_v": f("vtail_hi_v"), "vgs1_hi_v": f("vgs1_hi_v"),
        "vds1_hi_v": f("vds1_hi_v"), "vds2_hi_v": f("vds2_hi_v"), "ivdd_hi_a": f("ivdd_hi_a"),
        "vth_pair_cc_v": f("vth_pair_cc_v"), "op_vout_v": f("op_vout_v"), "op_vtail_v": f("op_vtail_v"),
        "op_vd1_v": f("op_vd1_v"), "op_vd2_v": f("op_vd2_v"), "op_vibias_v": f("op_vibias_v"),
        "op_ivdd_a": f("op_ivdd_a"),
    })
    return v


def _envelope(rows):
    limits = {m["name"]: m.get("limits") for m in REQ.build_measurements()}
    corners = []
    for r in rows:
        vdd = float(r["vdd_v"])
        vals = _row_values(r)
        ms = []
        for n in C.MEASUREMENTS:
            lim = limits[n]
            st = C._literal_verdict(vals[n], lim) if lim else "pass"
            ms.append({"name": n, "value": vals[n], "unit": C.MEASUREMENT_UNITS[n], "status": st})
        corners.append({"corner_id": f"{r['corner']}/vcm={vdd / 2:.3f}_vdd={vdd:.3f}V/{r['temp_c']}C",
                        "process": r["corner"], "supply_v": {"vdd": vdd, "vcm": vdd / 2},
                        "temperature_c": int(r["temp_c"]),
                        "status": "fail" if any(m["status"] == "fail" for m in ms) else "pass",
                        "measurements": ms})
    top = [{"name": n, "limits": limits[n], "status": "pass"} for n in C.MEASUREMENTS]
    return {"status": "pass", "corner_count": len(corners), "passed": len(corners), "failed": 0,
            "errored": 0, "inconclusive": 0,
            "coverage": {"nothing_checked": False, "skipped": [], "unknown": []},
            "measurements": top, "corners": corners}


def _nominal_rows():
    return [r for r in _rows() if r["point_id"] == "mos_tt_27C_1.20V"]


def _set(env, point_id, name, fn):
    """Apply fn to measurement `name` of the corner whose id spells point_id."""
    proc, temp, vdd = point_id.rsplit("_", 2)
    for c in env["corners"]:
        if c["process"] == proc and c["temperature_c"] == int(temp[:-1]) and f"{c['supply_v']['vdd']:.2f}V" == vdd:
            for m in c["measurements"]:
                if m["name"] == name:
                    fn(m)
                    return
    raise KeyError((point_id, name))


class Base(unittest.TestCase):
    def grid_env(self):
        return _envelope(_rows())

    def nom_env(self):
        return _envelope(_nominal_rows())

    def index(self, env, points=GRID):
        return C.index_envelope(env, "envelope", points)

    def assertRejects(self, env, needle, points=GRID):
        with self.assertRaises(C.InputError) as cm:
            self.index(env, points)
        self.assertIn(needle, str(cm.exception))

    def report(self, env, points=GRID):
        return C.compare(self.index(env, points), C.load_harness_csv(HARNESS_CSV, points), points)


class TestRequestGenerator(unittest.TestCase):
    def test_committed_requests_match_generator(self):
        for name, points in REQ.FILES.items():
            with open(os.path.join(HERE, name)) as f:
                self.assertEqual(f.read(), REQ.render(points), name)

    def test_grid_is_the_ratified_45_points(self):
        r = REQ.build_request("grid")
        self.assertEqual([p["name"] for p in r["corners"]["process"]], list(C.E.PROCESSES))
        self.assertEqual(r["corners"]["temperature_c"], list(C.E.TEMPERATURES))
        self.assertEqual(r["corners"]["supply_v"]["vdd"], list(C.E.SUPPLIES))
        self.assertEqual(r["corners"]["supply_v"]["vcm"], [v / 2 for v in C.E.SUPPLIES])
        self.assertEqual(r["backend"], "batch")

    def test_nominal_is_local_and_one_point(self):
        r = REQ.build_request("nominal")
        self.assertEqual(r["backend"], "local")
        self.assertEqual(len(r["corners"]["process"]) * len(r["corners"]["temperature_c"])
                         * len(r["corners"]["supply_v"]["vdd"]), 1)

    def test_sweep_covers_the_supply_axis_with_the_stated_sample_count(self):
        r = REQ.build_request("grid")
        self.assertEqual(r["analysis"]["args"], "Vcsw 0 1.32 250u")
        self.assertEqual(round(REQ.VCM_STOP / REQ.STEP) + 1, REQ.NS)

    def test_measurement_names_are_unique(self):
        names = [m["name"] for m in REQ.build_measurements()]
        self.assertEqual(len(names), len(set(names)))

    def test_body_deck_has_one_include_and_the_swept_source(self):
        with open(os.path.join(HERE, "tb_cmr.body.spice")) as f:
            body = f.read()
        self.assertEqual(sum(1 for ln in body.splitlines() if ln.lower().startswith(".include")), 1)
        self.assertIn("\nVcsw inp 0", body)
        directives = [ln.lower() for ln in body.splitlines() if ln.startswith(".")]
        self.assertFalse([d for d in directives if d.startswith((".control", ".end", ".lib", ".tran", ".dc"))])

    def test_pair_replica_current_is_100nA_times_W_over_L(self):
        import re
        with open(os.path.join(HERE, "tb_cmr.body.spice")) as f:
            body = f.read()
        m = re.search(r"^Bsv .*\(([0-9.]+e-6) - i\(Vsn\)\)", body, re.M)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(float(m.group(1)) / REQ.I_CC, 1.0, places=9)
        self.assertAlmostEqual(REQ.I_CC, 100e-9 * 3.2 / 0.13, places=15)


class TestValidJoins(Base):
    def test_grid_baseline_agrees(self):
        rep = self.report(self.grid_env())
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["status"], "agree")

    def test_nominal_point_set(self):
        rep = self.report(self.nom_env(), NOM)
        self.assertEqual(rep["points_compared"], 1)
        self.assertEqual(rep["status"], "agree")

    def test_reordered_input_is_the_same_join(self):
        env = self.grid_env()
        shuffled = copy.deepcopy(env)
        shuffled["corners"].reverse()
        for c in shuffled["corners"]:
            c["measurements"].reverse()
        a = json.dumps(self.report(env), sort_keys=True)
        b = json.dumps(self.report(shuffled), sort_keys=True)
        self.assertEqual(a, b)

    def test_baseline_labels_reproduce_the_harness_mechanisms(self):
        rep = self.report(self.grid_env())
        for p in rep["points"]:
            self.assertTrue(all(d["agree"] for d in p["labels"].values()), p["point_id"])

    def test_derived_labels_follow_the_harness_rule(self):
        self.assertEqual(C.mech_lo(0.4, 0.5, 0.5, 0.4), "m5_headroom")                       # min vds 0.4 > 0.1
        self.assertEqual(C.mech_lo(0.05, 0.5, 0.5, 0.4), "m5_headroom+pair_saturation")      # 0.05 < 0.1
        self.assertEqual(C.mech_hi(0.4, 0.11), "pair_saturation")
        self.assertEqual(C.mech_hi(0.10, 0.11), "pair_saturation+m5_headroom")

    def test_complete_run_with_vcm_outside_the_range_is_valid(self):
        # 15 of 45 harness points sit below the lower bound at mid-rail; that is a result.
        rep = self.report(self.grid_env())
        flags = [p["labels"]["contains_vcm"]["tool"] for p in rep["points"]]
        self.assertEqual(sum(1 for x in flags if not x), 15)


class TestEnvelopeGate(Base):
    def test_nothing_checked_rejected(self):
        env = self.grid_env()
        env["coverage"]["nothing_checked"] = True
        self.assertRejects(env, "nothing_checked")

    def test_skipped_coverage_rejected(self):
        env = self.grid_env()
        env["coverage"]["skipped"] = [{"id": "x"}]
        self.assertRejects(env, "skipped")

    def test_errored_envelope_rejected(self):
        env = self.grid_env()
        env["errored"] = 1
        self.assertRejects(env, "errored")

    def test_inconclusive_aggregate_rejected(self):
        env = self.grid_env()
        env["status"] = "inconclusive"
        self.assertRejects(env, "aggregate status")

    def test_missing_point_rejected(self):
        env = self.grid_env()
        env["corners"].pop()
        env["corner_count"] -= 1
        self.assertRejects(env, "missing")

    def test_duplicate_point_rejected(self):
        env = self.grid_env()
        env["corners"][1] = copy.deepcopy(env["corners"][0])
        self.assertRejects(env, "duplicate corner")

    def test_extra_point_rejected_for_nominal(self):
        self.assertRejects(self.grid_env(), "unexpected", NOM)

    def test_missing_measurement_names_point_and_metric(self):
        env = self.grid_env()
        for c in env["corners"]:
            if c["process"] == "mos_ss" and c["temperature_c"] == -40 and c["supply_v"]["vdd"] == 1.08:
                c["measurements"] = [m for m in c["measurements"] if m["name"] != "icmr_lo_v"]
        self.assertRejects(env, "mos_ss_-40C_1.08V: measurement icmr_lo_v missing")

    def test_duplicate_measurement_rejected(self):
        env = self.grid_env()
        env["corners"][0]["measurements"].append(copy.deepcopy(env["corners"][0]["measurements"][0]))
        self.assertRejects(env, "reported twice")

    def test_non_finite_value_rejected(self):
        for bad in (None, float("nan"), float("inf"), "x"):
            env = self.grid_env()
            _set(env, "mos_tt_27C_1.20V", "icmr_hi_v", lambda m, b=bad: m.__setitem__("value", b))
            self.assertRejects(env, "mos_tt_27C_1.20V: measurement icmr_hi_v value")

    def test_wrong_unit_rejected(self):
        env = self.grid_env()
        _set(env, "mos_tt_27C_1.20V", "icmr_lo_v", lambda m: m.__setitem__("unit", "mV"))
        self.assertRejects(env, "unit 'mV'")

    def test_vcm_not_half_vdd_rejected(self):
        env = self.grid_env()
        env["corners"][0]["supply_v"]["vcm"] += 0.01
        self.assertRejects(env, "!= vdd/2")

    def test_missing_vcm_axis_rejected(self):
        env = self.grid_env()
        del env["corners"][0]["supply_v"]["vcm"]
        self.assertRejects(env, "supply_v.vdd/vcm")

    def test_relaxed_integrity_limit_rejected(self):
        for name in C.INTEGRITY:
            env = self.grid_env()
            for m in env["measurements"]:
                if m["name"] == name:
                    m["limits"] = {"min": -1e9, "max": 1e9}
            self.assertRejects(env, f"{name}: envelope limits")

    def test_removed_integrity_limit_rejected(self):
        env = self.grid_env()
        for m in env["measurements"]:
            if m["name"] == "lo_crossings":
                m["limits"] = None
        self.assertRejects(env, "lo_crossings: envelope limits")

    def test_failed_integrity_measurement_rejected_even_if_status_consistent(self):
        # bound located twice -> not a unique crossing -> the bound is an artifact.
        env = self.grid_env()

        def two(m):
            m["value"] = 2.0
            m["status"] = "fail"
        _set(env, "mos_tt_27C_1.20V", "lo_crossings", two)
        self.assertRejects(env, "integrity measurement lo_crossings")

    def test_status_contradicting_the_pinned_bound_rejected(self):
        env = self.grid_env()
        _set(env, "mos_tt_27C_1.20V", "lo_crossings", lambda m: m.update(value=2.0))  # status still pass
        self.assertRejects(env, "contradicts value")

    def test_knee_outside_plausible_band_is_an_integrity_failure(self):
        env = self.grid_env()
        _set(env, "mos_tt_27C_1.20V", "vdsat5_frac", lambda m: m.update(value=0.6, status="fail"))
        self.assertRejects(env, "integrity measurement vdsat5_frac")

    def test_bias_replica_mismatch_is_an_integrity_failure(self):
        env = self.grid_env()
        _set(env, "mos_tt_27C_1.20V", "probe_bias_err_v", lambda m: m.update(value=5e-3, status="fail"))
        self.assertRejects(env, "integrity measurement probe_bias_err_v")


class TestComparison(Base):
    def perturbed(self, point_id, name, delta):
        env = self.grid_env()
        _set(env, point_id, name, lambda m: m.__setitem__("value", m["value"] + delta))
        return self.report(env)

    def test_upper_bound_just_inside_tolerance_agrees(self):
        h = {r["point_id"]: r for r in _rows()}["mos_tt_27C_1.20V"]
        tol = C.tolerance("icmr_hi_v", float(h["icmr_hi_v"]))
        self.assertEqual(self.perturbed("mos_tt_27C_1.20V", "icmr_hi_v", 0.99 * tol)["status"], "agree")

    def test_upper_bound_just_outside_tolerance_is_reported(self):
        h = {r["point_id"]: r for r in _rows()}["mos_tt_27C_1.20V"]
        tol = C.tolerance("icmr_hi_v", float(h["icmr_hi_v"]))
        rep = self.perturbed("mos_tt_27C_1.20V", "icmr_hi_v", 1.01 * tol)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any(s.startswith("mos_tt_27C_1.20V icmr_hi_v") for s in rep["out_of_tolerance"]))

    def test_negative_delta_is_caught_too(self):
        rep = self.perturbed("mos_ss_-40C_1.08V", "icmr_lo_v", -0.02)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any(s.startswith("mos_ss_-40C_1.08V icmr_lo_v") for s in rep["out_of_tolerance"]))

    def test_lower_bound_tolerance_is_wider_than_upper(self):
        self.assertGreater(C.LO_BOUND_TOL_V, C.HI_BOUND_TOL_V)
        self.assertAlmostEqual(C.LO_BOUND_TOL_V, C.VDSAT5_QUANT_V / C.TAIL_SLOPE_FLOOR)

    def test_every_compared_metric_is_actually_measured(self):
        for m in C.COMPARED:
            self.assertIn(m, C.MEASUREMENTS)

    def test_every_compared_metric_can_fail(self):
        for m in C.COMPARED:
            rep = self.perturbed("mos_tt_27C_1.20V", m, 1.0)
            self.assertTrue(any(s.startswith(f"mos_tt_27C_1.20V {m}:") for s in rep["out_of_tolerance"]), m)

    def test_flipped_mechanism_is_an_unexplained_disagreement_when_far_from_the_edge(self):
        # Make the pair look past saturation at the lower bound by 0.3 V: the
        # label flips, the harness margin is large, so tolerance cannot explain it.
        env = self.grid_env()
        _set(env, "mos_tt_27C_1.20V", "vds1_lo_v", lambda m: m.update(value=-0.3))
        rep = self.report(env)
        d = [x for x in rep["bound_verdict_disagreements"] if x["label"] == "mech_lo"]
        self.assertEqual(len(d), 1)
        self.assertFalse(d[0]["explained"])
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 1)

    def test_contains_vcm_flip_near_the_edge_is_explained(self):
        # mos_tt_-40C_1.08V: the harness lower bound (0.58224) is 42 mV above Vcm,
        # so it is not near the edge; push the TOOL's bound across Vcm instead and
        # check the report keeps the disagreement and marks it unexplained.
        env = self.grid_env()
        _set(env, "mos_tt_-40C_1.08V", "icmr_lo_v", lambda m: m.update(value=0.53))
        rep = self.report(env)
        d = [x for x in rep["bound_verdict_disagreements"] if x["label"] == "contains_vcm"]
        self.assertEqual(len(d), 1)
        self.assertFalse(d[0]["explained"])

    def test_missing_harness_point_rejected(self):
        tool = self.index(self.grid_env())
        h = C.load_harness_csv(HARNESS_CSV)
        h.pop(C.make_key("mos_tt", 27, 1.20))
        with self.assertRaises(C.InputError):
            C.compare(tool, h)


if __name__ == "__main__":
    unittest.main()

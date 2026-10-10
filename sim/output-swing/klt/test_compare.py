#!/usr/bin/env python3
"""Offline negative-control tests for compare.py (issue #100).

    python3 -m unittest discover -s sim/output-swing/klt -p 'test_*.py'

What these fixtures are, stated plainly: the synthetic envelopes below are
BUILT FROM the committed harness record, so a test that only checks "the
baseline agrees" would be circular. The baseline is here only as the control
that every negative case perturbs; the tests that carry weight are the negative
controls (reordered, missing, duplicate, extra, null, NaN, wrong unit, absent
metric, skipped/errored/inconclusive coverage, nothing_checked, relaxed or
inconsistent limits, failed integrity check, perturbed value), each of which
must fail and name the point/metric it failed on. None of this is evidence
about the circuit -- the envelope in records/ is.
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
import compare as C  # noqa: E402

BENCH = os.path.dirname(HERE)
HARNESS_ID = "20260921-151759-707b34c"
HARNESS_CSV = os.path.join(BENCH, "records", f"{HARNESS_ID}.csv")
REQUEST = os.path.join(HERE, "swing.nominal.request.json")
NOMINAL = C.NOMINAL_KEY
GRID = C.POINT_SETS["grid"]
NOM = C.POINT_SETS["nominal"]


def _rows():
    with open(HARNESS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _status(value, limits):
    return C.literal_verdict(value, limits) if limits else "pass"


def _row_measurements(r):
    """The measurement values a faithful tool run would report for harness row r."""
    vdd = float(r["vdd_v"])
    vmax, vmin = float(r["vout_max_track_v"]), float(r["vout_min_track_v"])
    return {
        "gpk_vv": float(r["peak_inc_gain_v_v"]), "mono_min_dv_v": 5e-6,
        "pk_idx": 2500.0, "lo_idx": 2000.0, "hi_idx": 3000.0,
        "vmax_track_v": vmax, "vmin_track_v": vmin,
        "headroom_hi_v": vdd - vmax, "headroom_lo_v": vmin, "swing_span_v": vmax - vmin,
    }


def _request_limits():
    with open(REQUEST) as f:
        return {m["name"]: m.get("limits") for m in json.load(f)["measurements"]}


def _envelope(rows):
    limits = _request_limits()
    corners = []
    worst = {}
    for r in rows:
        vdd = float(r["vdd_v"])
        vals = _row_measurements(r)
        ms = [{"name": n, "value": v, "unit": C.MEASUREMENT_UNITS[n], "status": _status(v, limits[n])}
              for n, v in vals.items()]
        corners.append({"corner_id": f"{r['corner']}/vcm={vdd / 2:.3f}_vdd={vdd:.3f}V/{r['temp_c']}C",
                        "process": r["corner"], "supply_v": {"vdd": vdd, "vcm": vdd / 2},
                        "temperature_c": int(r["temp_c"]),
                        "status": "fail" if any(m["status"] == "fail" for m in ms) else "pass",
                        "measurements": ms})
    top = [{"name": n, "limits": limits[n], "status": "pass"} for n in C.RATIFIED]
    failed = sum(1 for c in corners if c["status"] == "fail")
    return {"status": "fail" if failed else "pass", "corner_count": len(corners),
            "passed": len(corners) - failed, "failed": failed, "errored": 0, "inconclusive": 0,
            "coverage": {"nothing_checked": False, "skipped": [], "unknown": []},
            "measurements": top, "corners": corners}


def _nominal_rows():
    return [r for r in _rows() if r["point_id"] == "mos_tt_27C_1.20V"]


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


class TestValidJoins(Base):
    def test_grid_baseline_agrees(self):
        tool = self.index(self.grid_env())
        h = C.load_harness_csv(HARNESS_CSV)
        rep = C.compare(tool, h)
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["status"], "agree")

    def test_nominal_point_set(self):
        tool = self.index(self.nom_env(), NOM)
        h = C.load_harness_csv(HARNESS_CSV, NOM)
        rep = C.compare(tool, h, NOM)
        self.assertEqual(rep["points_compared"], 1)
        self.assertEqual(rep["status"], "agree")

    def test_reordered_input_is_the_same_join(self):
        env = self.grid_env()
        shuffled = copy.deepcopy(env)
        shuffled["corners"].reverse()
        for c in shuffled["corners"]:
            c["measurements"].reverse()
        a = C.compare(self.index(env), C.load_harness_csv(HARNESS_CSV))
        b = C.compare(self.index(shuffled), C.load_harness_csv(HARNESS_CSV))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_complete_below_bound_span_is_a_valid_fail(self):
        # The harness record's own worst point misses 0.571 V literally.
        key = C.make_key("mos_ss", 125, 1.08)
        rows = _rows()
        env = _envelope(rows)
        tool = self.index(env)
        self.assertEqual(tool[key]["swing_span_v__status"], "fail")
        self.assertLess(tool[key]["swing_span_v"], 0.571)
        self.assertEqual(env["status"], "fail")  # still a gradable, complete envelope
        rep = C.compare(tool, C.load_harness_csv(HARNESS_CSV))
        row = next(p for p in rep["points"] if p["point_id"] == C.key_str(key))["rows"]["swing_span_v"]
        self.assertEqual((row["tool_verdict"], row["harness_verdict"]), ("fail", "fail"))
        self.assertEqual(rep["status"], "agree")

    def test_literal_fail_survives_passing_tolerance(self):
        # Tool value 0.570999 V is far inside the comparison tolerance of the
        # harness value yet is below the literal 0.571 V bound: still a FAIL.
        key = C.make_key("mos_ss", 125, 1.08)
        env = self.grid_env()
        for c in env["corners"]:
            if (c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == ("mos_ss", 125, 1.08):
                for m in c["measurements"]:
                    if m["name"] == "swing_span_v":
                        m["value"] = 0.570999
                        m["status"] = "fail"
        tool = self.index(env)
        rep = C.compare(tool, C.load_harness_csv(HARNESS_CSV))
        p = next(p for p in rep["points"] if p["point_id"] == C.key_str(key))
        self.assertTrue(p["metrics"]["swing_span_v"]["within"])
        self.assertEqual(p["rows"]["swing_span_v"]["tool_verdict"], "fail")

    def test_verdict_disagreement_near_bound_is_explained_not_hidden(self):
        # Tool span 0.571002 passes the literal bound while the harness value
        # 0.570957773 fails it: a reported disagreement, explained by the
        # tolerance (the harness value is within tolerance of the bound).
        key = C.make_key("mos_ss", 125, 1.08)
        env = self.grid_env()
        for c in env["corners"]:
            if (c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == ("mos_ss", 125, 1.08):
                for m in c["measurements"]:
                    if m["name"] == "swing_span_v":
                        m["value"], m["status"] = 0.571002, "pass"
        rep = C.compare(self.index(env), C.load_harness_csv(HARNESS_CSV))
        d = rep["bound_verdict_disagreements"]
        self.assertEqual([(x["point"], x["row"]) for x in d], [(C.key_str(key), "swing_span_v")])
        self.assertTrue(d[0]["explained_by_tolerance"])
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)

    def test_far_verdict_flip_is_unexplained(self):
        env = self.grid_env()
        for c in env["corners"]:
            for m in c["measurements"]:
                if m["name"] == "headroom_lo_v" and c["process"] == "mos_tt" and c["temperature_c"] == 27 \
                        and c["supply_v"]["vdd"] == 1.2:
                    m["value"], m["status"] = 0.10, "fail"
        rep = C.compare(self.index(env), C.load_harness_csv(HARNESS_CSV))
        self.assertEqual(rep["status"], "disagree")
        self.assertGreaterEqual(rep["unexplained_bound_verdict_disagreements"], 1)
        self.assertTrue(any("headroom_lo_v" in s for s in rep["out_of_tolerance"]))

    def test_perturbed_value_outside_tolerance_is_reported(self):
        env = self.grid_env()
        c = env["corners"][0]
        for m in c["measurements"]:
            if m["name"] == "vmax_track_v":
                m["value"] += 0.05
        rep = C.compare(self.index(env), C.load_harness_csv(HARNESS_CSV))
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("vmax_track_v" in s for s in rep["out_of_tolerance"]))

    def test_tolerance_is_not_a_limit(self):
        # The comparison tolerance (> 1 mV at nominal) is wider than the margin
        # of a near-bound value; RATIFIED_LIMITS must stay the literal numbers.
        self.assertEqual(C.RATIFIED_LIMITS, {"headroom_hi_v": {"min": 0.251}, "headroom_lo_v": {"min": 0.141},
                                             "swing_span_v": {"min": 0.571}})
        self.assertEqual({n: l for n, l in _request_limits().items() if n in C.RATIFIED}, C.RATIFIED_LIMITS)


class TestEnvelopeRejections(Base):
    def corner(self, env, i=0):
        return env["corners"][i]

    def meas(self, c, name):
        return next(m for m in c["measurements"] if m["name"] == name)

    def test_missing_point(self):
        env = self.grid_env()
        env["corners"].pop()
        env["corner_count"] -= 1
        self.assertRejects(env, "missing from envelope")

    def test_duplicate_point(self):
        env = self.grid_env()
        env["corners"][1] = copy.deepcopy(env["corners"][0])
        self.assertRejects(env, "duplicate corner")

    def test_extra_point(self):
        env = self.nom_env()
        extra = copy.deepcopy(env["corners"][0])
        extra["temperature_c"] = 125
        env["corners"].append(extra)
        env["corner_count"] = 2
        self.assertRejects(env, "unexpected point", NOM)

    def test_grid_envelope_with_extra_off_grid_point(self):
        env = self.grid_env()
        extra = copy.deepcopy(env["corners"][0])
        extra["supply_v"] = {"vdd": 1.5, "vcm": 0.75}
        env["corners"].append(extra)
        env["corner_count"] += 1
        self.assertRejects(env, "unexpected point")

    def test_missing_measurement(self):
        env = self.nom_env()
        c = self.corner(env)
        c["measurements"] = [m for m in c["measurements"] if m["name"] != "swing_span_v"]
        self.assertRejects(env, "measurement swing_span_v missing", NOM)

    def test_duplicate_measurement(self):
        env = self.nom_env()
        c = self.corner(env)
        c["measurements"].append(copy.deepcopy(c["measurements"][0]))
        self.assertRejects(env, "reported twice", NOM)

    def test_null_value(self):
        env = self.nom_env()
        self.meas(self.corner(env), "headroom_hi_v")["value"] = None
        self.assertRejects(env, "headroom_hi_v value None is missing or non-finite", NOM)

    def test_nonfinite_values(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            env = self.nom_env()
            self.meas(self.corner(env), "vmax_track_v")["value"] = bad
            self.assertRejects(env, "vmax_track_v", NOM)

    def test_boolean_value_is_not_a_number(self):
        env = self.nom_env()
        self.meas(self.corner(env), "vmax_track_v")["value"] = True
        self.assertRejects(env, "non-finite", NOM)

    def test_wrong_unit(self):
        env = self.nom_env()
        m = self.meas(self.corner(env), "swing_span_v")
        m["value"] *= 1000
        m["unit"] = "mV"
        self.assertRejects(env, "swing_span_v unit 'mV' != 'V'", NOM)

    def test_missing_unit(self):
        env = self.nom_env()
        self.meas(self.corner(env), "headroom_lo_v")["unit"] = None
        self.assertRejects(env, "headroom_lo_v unit None", NOM)

    def test_per_measurement_error_inconclusive_not_checked(self):
        for st in ("error", "inconclusive", "not_checked", None):
            env = self.nom_env()
            self.meas(self.corner(env), "swing_span_v")["status"] = st
            self.assertRejects(env, f"swing_span_v status {st!r}", NOM)

    def test_corner_status_errored(self):
        for st in ("error", "inconclusive"):
            env = self.nom_env()
            self.corner(env)["status"] = st
            self.assertRejects(env, f"corner status {st!r}", NOM)

    def test_aggregate_status_not_pass_fail(self):
        for st in ("error", "inconclusive", "not_checked", None):
            env = self.nom_env()
            env["status"] = st
            self.assertRejects(env, "only a complete pass/fail run is evidence", NOM)

    def test_errored_or_inconclusive_counts(self):
        for field in ("errored", "inconclusive"):
            env = self.nom_env()
            env[field] = 1
            self.assertRejects(env, f"{field} = 1", NOM)

    def test_nothing_checked(self):
        for v in (True, None):
            env = self.nom_env()
            env["coverage"]["nothing_checked"] = v
            self.assertRejects(env, "nothing_checked", NOM)

    def test_skipped_coverage(self):
        env = self.nom_env()
        env["coverage"]["skipped"] = [{"id": "limit:x", "reason": "r"}]
        self.assertRejects(env, "coverage.skipped is non-empty", NOM)

    def test_missing_coverage_block(self):
        env = self.nom_env()
        del env["coverage"]
        self.assertRejects(env, "no coverage block", NOM)

    def test_klt_error_envelope(self):
        self.assertRejects({"error": "batch_runner_version_mismatch"}, "klt error envelope", NOM)

    def test_corner_count_mismatch(self):
        env = self.nom_env()
        env["corner_count"] = 2
        self.assertRejects(env, "corner_count", NOM)

    def test_relaxed_limit_is_not_evidence(self):
        env = self.nom_env()
        env["measurements"][[m["name"] for m in env["measurements"]].index("swing_span_v")]["limits"] = {"min": 0.5}
        self.assertRejects(env, "!= literal ratified bound", NOM)

    def test_absent_limit_is_not_evidence(self):
        env = self.nom_env()
        env["measurements"] = [m for m in env["measurements"] if m["name"] != "headroom_hi_v"]
        self.assertRejects(env, "headroom_hi_v: envelope limits None", NOM)

    def test_verdict_contradicting_value(self):
        env = self.nom_env()
        m = self.meas(self.corner(env), "swing_span_v")
        m["status"] = "fail"  # value 0.7457 V >= 0.571 V
        self.assertRejects(env, "contradicts value", NOM)
        env = self.nom_env()
        m = self.meas(self.corner(env), "headroom_lo_v")
        m["value"], m["status"] = 0.10, "pass"  # 0.10 V < 0.141 V
        self.assertRejects(env, "contradicts value", NOM)

    def test_failed_integrity_check_is_not_evidence(self):
        for name, val in (("lo_idx", 0.0), ("hi_idx", 4999.0), ("gpk_vv", 3.0), ("mono_min_dv_v", -0.01)):
            env = self.nom_env()
            m = self.meas(self.corner(env), name)
            m["value"], m["status"] = val, "fail"
            self.assertRejects(env, f"integrity measurement {name}", NOM)

    def test_vcm_not_mid_rail(self):
        env = self.nom_env()
        self.corner(env)["supply_v"]["vcm"] = 0.55
        self.assertRejects(env, "!= vdd/2", NOM)

    def test_missing_vcm(self):
        env = self.nom_env()
        del self.corner(env)["supply_v"]["vcm"]
        self.assertRejects(env, "missing process or supply_v", NOM)


class TestHarnessCsv(Base):
    def write(self, rows, header=None):
        header = header or list(rows[0].keys())
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
        self.addCleanup(os.unlink, f.name)
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
        f.close()
        return f.name

    def test_missing_row(self):
        rows = _rows()[:-1]
        with self.assertRaises(C.InputError) as cm:
            C.load_harness_csv(self.write(rows))
        self.assertIn("missing from harness CSV", str(cm.exception))

    def test_duplicate_row(self):
        rows = _rows()
        rows[1] = dict(rows[0])
        with self.assertRaises(C.InputError) as cm:
            C.load_harness_csv(self.write(rows))
        self.assertIn("duplicate harness row", str(cm.exception))

    def test_extra_row_for_grid(self):
        rows = _rows()
        extra = dict(rows[0])
        extra["vdd_v"], extra["point_id"] = "1.50", "mos_tt_-40C_1.50V"
        with self.assertRaises(C.InputError) as cm:
            C.load_harness_csv(self.write(rows + [extra]))
        self.assertIn("unexpected point in harness CSV", str(cm.exception))

    def test_nonfinite_and_blank(self):
        for bad in ("nan", "inf", ""):
            rows = _rows()
            rows[0]["swing_span_v"] = bad
            with self.assertRaises(C.InputError):
                C.load_harness_csv(self.write(rows))

    def test_absent_column(self):
        rows = [{k: v for k, v in r.items() if k != "headroom_lo_v"} for r in _rows()]
        with self.assertRaises(C.InputError) as cm:
            C.load_harness_csv(self.write(rows))
        self.assertIn("headroom_lo_v", str(cm.exception))

    def test_nominal_ignores_other_rows(self):
        h = C.load_harness_csv(HARNESS_CSV, NOM)
        self.assertIn(NOMINAL, h)

    def test_compare_refuses_point_missing_on_either_side(self):
        tool = self.index(self.nom_env(), NOM)
        h = C.load_harness_csv(HARNESS_CSV)
        with self.assertRaises(C.InputError):
            C.compare(tool, h)  # grid requested, tool has only nominal


class TestCli(Base):
    def test_validate_and_compare_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            ok = os.path.join(d, "ok.json")
            with open(ok, "w") as f:
                json.dump(self.nom_env(), f)
            self.assertEqual(C.main(["validate", ok, "--points", "nominal"]), 0)
            self.assertEqual(C.main(["validate", ok]), 2)  # grid expected, one point given
            out = os.path.join(d, "rep.json")
            self.assertEqual(C.main(["compare", "--envelope", ok, "--harness-csv", HARNESS_CSV,
                                     "--points", "nominal", "--json-out", out,
                                     "--provenance", "k=v"]), 0)
            with open(out) as f:
                rep = json.load(f)
            self.assertEqual(rep["provenance"], {"k": "v"})
            self.assertEqual(len(rep["inputs"]["envelope"]["sha256"]), 64)
            bad = os.path.join(d, "bad.json")
            env = self.nom_env()
            env["coverage"]["nothing_checked"] = True
            with open(bad, "w") as f:
                json.dump(env, f)
            self.assertEqual(C.main(["validate", bad, "--points", "nominal"]), 2)
            self.assertEqual(C.main(["validate", os.path.join(d, "absent.json"), "--points", "nominal"]), 2)


class TestCommittedRecords(unittest.TestCase):
    """Every committed prototype envelope still passes the gate it was written under."""

    def test_committed_nominal_records_validate_and_compare(self):
        rec = os.path.join(HERE, "records")
        found = [f for f in sorted(os.listdir(rec)) if f.endswith(".nominal.sim.json")] if os.path.isdir(rec) else []
        for f in found:
            path = os.path.join(rec, f)
            self.assertEqual(C.main(["validate", path, "--points", "nominal"]), 0, f)
            self.assertIn(C.main(["compare", "--envelope", path, "--harness-csv", HARNESS_CSV,
                                  "--points", "nominal"]), (0, 1), f)


if __name__ == "__main__":
    unittest.main()

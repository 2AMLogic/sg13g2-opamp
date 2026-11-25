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

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
import compare as C  # noqa: E402
import envelope_control_mixin as M  # noqa: E402
import envelope_fixtures as F  # noqa: E402
import offset_post as P  # noqa: E402

BENCH = os.path.dirname(HERE)
HARNESS_CSV = os.path.join(BENCH, "records", "20260918-203858-90844d2.csv")
REQUEST = os.path.join(HERE, "offset.request.json")
CL_REQUEST = os.path.join(HERE, "offset_cl.request.json")
# The selected same-DUT open-loop record (selection.json `open-loop-ac`): the
# Av0 join source the batch path uses, whose grounded-inn Av0 differs from the
# harness record's floating-inn Av0 by up to 1.785 dB.
AV0_CSV = os.path.join(BENCH, "..", "open-loop-ac", "records", "20261015-103057-895d555.csv")
BOUND = C.OFFSET_BOUND_V


def _harness_rows():
    return F.harness_rows(HARNESS_CSV)


def _request_limits():
    return F.request_limits(REQUEST)


def _vals(r):
    """This bench's measurement dict for one harness row."""
    vdd = float(r["vdd_v"])
    vd1, vd2, vtail = (float(r[c]) for c in ("vd1_sample_v", "vd2_sample_v", "vtail_sample_v"))
    return {
        "vos_null_v": float(r["vos_null_v"]), "vos_crossings_n": 1.0,
        "gain_local_vv": 10 ** (float(r["av_local_db"]) / 20),
        "vd1_dc_v": vd1, "vd2_dc_v": vd2, "vtail_dc_v": vtail,
        "vout_null_dc_v": float(r["vout_sample_v"]),
        "vibias_dc_v": float(r["vibias_sample_v"]),
        "op_vd1_rail_frac": vd1 / vdd, "op_vd2_rail_frac": vd2 / vdd, "op_vtail_rail_frac": vtail / vdd,
    }


def _cl_vals(r):
    """The closed-loop envelope's measurement dict for one harness row."""
    return {"vout_cl_v": float(r["vout_cl_v"])}


def _envelope(rows):
    """A synthetic klt-sim-shaped envelope carrying the harness's own numbers."""
    return F.build_envelope(rows, _vals, C.make_key, _request_limits())


def _cl_envelope(rows):
    return F.build_envelope(rows, _cl_vals, C.make_key, F.request_limits(CL_REQUEST))


def _av0_text(rows):
    """A synthetic open-loop-ac record CSV joining the harness's own Av0."""
    lines = ["point_id,corner,temp_c,vdd_v,av0_db"]
    for r in rows:
        lines.append(f"{r['point_id']},{r['corner']},{r['temp_c']},{r['vdd_v']},{r['av0_db_ac_record']}")
    return "\n".join(lines) + "\n"


def _regrade(env, corner):
    F.regrade(env, corner, _request_limits())


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _harness_rows()
        cls.harness = C.load_harness_csv(HARNESS_CSV)

    def env(self):
        return _envelope(self.rows)

    def tool(self, env):
        return C.index_envelope(env, "test", kind="null")

    def cl(self, rows=None):
        return C.index_envelope(_cl_envelope(rows if rows is not None else self.rows), "test", kind="cl")

    def av0(self, rows=None):
        """{key: Av0} joined from a synthetic record carrying the harness's own
        Av0 (the circular control baseline; the selected grounded record is
        joined by the dedicated test below)."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "av0.csv")
            with open(path, "w") as f:
                f.write(_av0_text(rows if rows is not None else self.rows))
            return P.read_av0_csv(path)

    def compare(self, env, cl=None, av0=None):
        return C.compare(self.tool(env), self.cl() if cl is None else cl, self.harness,
                         self.av0() if av0 is None else av0, env)

    # -- helpers: the CL fixture as a mutable envelope ----------------------
    def cl_env(self):
        return _cl_envelope(self.rows)

    def cl_env_perturbed(self, point, fn):
        env = self.cl_env()
        c, m = F.find(env, point, "vout_cl_v", C.make_key)
        m["value"] = fn(m["value"])
        F.regrade(env, c, F.request_limits(CL_REQUEST))
        return env

    def cl_from_env(self, env):
        return C.index_envelope(env, "test", kind="cl")

    @staticmethod
    def find(env, point, name):
        return F.find(env, point, name, C.make_key)


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

    def test_cl_request_is_the_same_grid_with_one_op_analysis(self):
        with open(CL_REQUEST) as f:
            req = json.load(f)
        self.assertEqual(req["netlist"], "tb_offset_cl.body.spice")
        self.assertEqual([p["name"] for p in req["corners"]["process"]], list(C.PROCESSES))
        self.assertEqual(req["corners"]["temperature_c"], list(C.TEMPERATURES))
        self.assertEqual(req["corners"]["supply_v"]["vdd"], list(C.SUPPLIES))
        self.assertEqual(req["corners"]["supply_v"]["vinp"], [v / 2 for v in C.SUPPLIES])
        self.assertEqual(req["analysis"], {"kind": "op", "args": ""})
        self.assertEqual(req["backend"], "batch")
        self.assertEqual({m["name"] for m in req["measurements"]}, set(C.CL_MEASUREMENTS))
        self.assertNotIn("limits", json.dumps(req["measurements"]))
        self.assertNotIn("reltol", json.dumps(req["options"]))

    def test_cl_body_is_the_harness_closed_loop_topology(self):
        with open(os.path.join(HERE, "tb_offset_cl.body.spice")) as f:
            body = [ln for ln in f if not ln.startswith("*")]
        text = "\n".join(body)
        for word in ("reltol", "abstol", "vntol"):
            self.assertFalse(any(word in ln for ln in body), word)
        self.assertEqual(sum(ln.lower().startswith(".include") for ln in body), 1)
        # The harness's closed-loop conditions (tb_offset_cl.spice.tmpl),
        # element for element: the DC loop-closing inductor, the inp drive at
        # Vcm, the 10 uA reference, CL = 2 pF, and NO differential source.
        for element in ("Lbreak inn out 1e18", "Vinp inp 0 dc 0.6", "Iibias vdd ibias dc 10u",
                        "Cload out vss 2e-12", "Vdd vdd 0 dc 1.2", "Vss vss 0 dc 0"):
            self.assertEqual(sum(ln.strip() == element for ln in body), 1, element)
        for absent in ("Vid", "Binp", "Binn", "Borel"):
            self.assertNotIn(absent, text.replace("num_threads", ""), absent)

    def test_null_body_still_carries_the_null_topology(self):
        with open(os.path.join(HERE, "tb_offset.body.spice")) as f:
            body = [ln for ln in f if not ln.startswith("*")]
        for element in ("Vid id 0 dc 0", "Binp inp 0 v = v(cm) + v(id)/2",
                        "Binn inn 0 v = v(cm) - v(id)/2", "Borel orel 0 v=v(out)-v(cm)"):
            self.assertEqual(sum(ln.strip() == element for ln in body), 1, element)
        self.assertNotIn("Lbreak", "\n".join(body))


class TestHarnessInputs(M.HarnessCsvControlMixin, Base):
    harness_csv = HARNESS_CSV
    nonfinite_col = "vos_null_v"

    def load_csv(self, path):
        return C.load_harness_csv(path)

    def test_committed_record_is_the_full_grid(self):
        self.assertEqual(set(self.harness), set(C.expected_keys()))
        self.assertEqual(len(self.harness), 45)


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


class TestEnvelopeNegativeControls(M.EnvelopeControlMixin, Base):
    """The shared gate's thirteen generic envelope refusals
    (envelope_control_mixin), each run through this bench's own comparator
    gate. The bench-specific input check stays below."""

    WORST = WORST
    null_meas = "vos_null_v"
    nonfinite_meas = "gain_local_vv"
    absent_meas = "vos_crossings_n"

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


class TestClosedLoopControls(Base):
    """The second method's join: derivation, agreement and the Av0 binding."""

    def test_selected_grounded_av0_join_still_agrees(self):
        """The batch path joins the SELECTED open-loop record (inn
        AC-grounded), the harness joined the floating-inn record it dated:
        0.22..1.785 dB apart. Referring the harness's own vout_cl back through
        the selected record's Av0 must stay inside the documented tolerance
        (<= 2.9e-3 relative on vos_cl), or the join-source allowance is wrong."""
        rep = self.compare(self.env(), av0=P.read_av0_csv(AV0_CSV))
        self.assertEqual(rep["status"], "agree", rep["out_of_tolerance"][:3])
        worst = max(abs(p["metrics"]["vos_closed_loop_v"]["delta"]) for p in rep["points"])
        self.assertLess(worst, 60e-6)

    def test_derived_closed_loop_matches_the_harness_definition(self):
        """offset_post.derive reproduces run_offset_sweep.sh's vos_cl / delta
        from the harness's own vout_cl and Av0 (same formula, same order), to
        beyond the %.9g serialization the record writes."""
        for r in self.rows:
            with self.subTest(point=r["point_id"]):
                d = P.derive(_vals(r), float(r["vout_cl_v"]), float(r["vdd_v"]), float(r["av0_db_ac_record"]))
                self.assertAlmostEqual(d["vos_closed_loop_v"], float(r["vos_closed_loop_v"]), delta=1e-9)
                self.assertAlmostEqual(d["vos_method_delta_v"], float(r["vos_method_delta_v"]), delta=1e-9)
                self.assertTrue(d["op_pass"])
                self.assertTrue(d["xcheck_pass"], d["xcheck_why"])

    def test_method_disagreement_is_named(self):
        """vout_cl moved by 2 mV: referred back through ~150 V/V that is a
        ~2 mV vos_cl shift, far beyond max(200 uV, 5% |vos|) -- the xcheck
        disagreement must name the corner."""
        env = self.cl_env_perturbed(MID, lambda v: v - 2e-3)
        rep = self.compare(self.env(), cl=self.cl_from_env(env))
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V xcheck" in s for s in rep["out_of_tolerance"]),
                        rep["out_of_tolerance"][:3])
        self.assertTrue(any("mos_tt_27C_1.20V vout_cl_v" in s for s in rep["out_of_tolerance"]))

    def test_vout_cl_inside_tolerance_is_accepted(self):
        env = self.cl_env_perturbed(MID, lambda v: v + 3e-6)
        self.assertEqual(self.compare(self.env(), cl=self.cl_from_env(env))["status"], "agree")

    def test_missing_av0_row_fails_the_cross_check_naming_the_corner(self):
        rows = [r for r in self.rows if r["point_id"] != "mos_tt_27C_1.20V"]
        rep = self.compare(self.env(), av0=self.av0(rows))
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V xcheck" in s and "no finite Av0" in s
                            for s in rep["out_of_tolerance"]), rep["out_of_tolerance"][:3])
        p = next(p for p in rep["points"] if p["point_id"] == "mos_tt_27C_1.20V")
        self.assertFalse(p["integrity_checks"]["xcheck"]["tool_pass"])
        self.assertTrue(p["derived"]["av0_db_joined"] != p["derived"]["av0_db_joined"])

    def test_swapped_av0_corner_is_refused(self):
        """An Av0 row whose columns spell a different point than its point_id
        (a temperature/VDD key swap) is a foreign-corner Av0: refused, naming
        the row, before any comparison runs."""
        rows = [dict(r) for r in self.rows]
        swap = next(r for r in rows if r["point_id"] == "mos_tt_27C_1.20V")
        swap["temp_c"], swap["vdd_v"] = swap["vdd_v"], swap["temp_c"]
        with self.assertRaisesRegex(P.OffsetPostError, "mos_tt_27C_1.20V.*disagrees with its corner/temp_c/vdd_v"):
            self.av0(rows)

    def test_duplicate_av0_point_is_refused(self):
        rows = [dict(r) for r in self.rows] + [dict(self.rows[0])]
        with self.assertRaisesRegex(P.OffsetPostError, "duplicate point"):
            self.av0(rows)

    def test_off_grid_av0_point_is_refused(self):
        rows = [dict(r) for r in self.rows if r["point_id"] != "mos_tt_27C_1.20V"]
        stray = dict(rows[0])
        stray.update(point_id="mos_tt_99C_1.20V", temp_c="99", vdd_v="1.20")
        with self.assertRaisesRegex(P.OffsetPostError, "mos_tt_99C_1.20V is not a point of the ratified grid"):
            self.av0(rows + [stray])

    def test_av0_csv_without_the_column_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "noav0.csv")
            with open(path, "w") as f:
                f.write("point_id,corner,temp_c,vdd_v\n")
            with self.assertRaisesRegex(P.OffsetPostError, "no av0_db column"):
                P.read_av0_csv(path)

    def test_nan_av0_cell_fails_the_cross_check_like_the_harness(self):
        rows = [dict(r) for r in self.rows]
        rows[0]["av0_db_ac_record"] = "nan"
        av0 = self.av0(rows)
        rep = self.compare(self.env(), av0=av0)
        k = C.make_key(rows[0]["corner"], rows[0]["temp_c"], rows[0]["vdd_v"])
        self.assertTrue(av0[k] != av0[k])
        p = next(p for p in rep["points"] if p["point_id"] == rows[0]["point_id"])
        self.assertFalse(p["integrity_checks"]["xcheck"]["tool_pass"])

    def test_cl_envelope_missing_corner_is_refused(self):
        env = self.cl_env()
        env["corners"].pop()
        env["corner_count"] = 44
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cl.json")
            with open(path, "w") as f:
                json.dump(env, f)
            with self.assertRaisesRegex(C.InputError, "missing from"):
                C.E.load_envelope(path, C.index_envelope, kind="cl")


class TestCli(Base):
    def test_validate_and_compare_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.json")
            with open(good, "w") as f:
                json.dump(self.env(), f)
            good_cl = os.path.join(d, "good.cl.json")
            with open(good_cl, "w") as f:
                json.dump(self.cl_env(), f)
            av0_csv = os.path.join(d, "av0.csv")
            with open(av0_csv, "w") as f:
                f.write(_av0_text(self.rows))
            self.assertEqual(C.main(["validate", "--kind", "null", good]), 0)
            self.assertEqual(C.main(["validate", "--kind", "cl", good_cl]), 0)
            out = os.path.join(d, "r.json")
            rc = C.main(["compare", "--envelope", good, "--cl", good_cl, "--av0-csv", av0_csv,
                         "--harness-csv", HARNESS_CSV,
                         "--json-out", out, "--provenance", "k=v"])
            self.assertEqual(rc, 0)
            with open(out) as f:
                rep = json.load(f)
            self.assertEqual(rep["status"], "agree")
            self.assertEqual(rep["provenance"], {"k": "v"})
            self.assertIn("cl_envelope", rep["inputs"])
            self.assertIn("av0_csv", rep["inputs"])

            bad = os.path.join(d, "bad.json")
            env = self.env()
            env["corners"].pop()
            env["corner_count"] = 44
            with open(bad, "w") as f:
                json.dump(env, f)
            self.assertEqual(C.main(["validate", "--kind", "null", bad]), 2)

            bad_cl = os.path.join(d, "bad.cl.json")
            env = self.cl_env()
            env["corners"][0]["measurements"][0]["value"] = None
            with open(bad_cl, "w") as f:
                json.dump(env, f)
            self.assertEqual(C.main(["validate", "--kind", "cl", bad_cl]), 2)

            pert = os.path.join(d, "pert.json")
            env = self.env()
            _, m = self.find(env, MID, "vos_null_v")
            m["value"] *= 1.05
            with open(pert, "w") as f:
                json.dump(env, f)
            self.assertEqual(C.main(["compare", "--envelope", pert, "--cl", good_cl,
                                     "--av0-csv", av0_csv, "--harness-csv", HARNESS_CSV]), 1)

            swapped = os.path.join(d, "swapped.csv")
            rows = [dict(r) for r in self.rows]
            rows[0]["temp_c"], rows[0]["vdd_v"] = rows[0]["vdd_v"], rows[0]["temp_c"]
            with open(swapped, "w") as f:
                f.write(_av0_text(rows))
            self.assertEqual(C.main(["compare", "--envelope", good, "--cl", good_cl,
                                     "--av0-csv", swapped, "--harness-csv", HARNESS_CSV]), 2)


if __name__ == "__main__":
    unittest.main()

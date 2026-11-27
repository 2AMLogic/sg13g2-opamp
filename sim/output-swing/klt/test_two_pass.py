#!/usr/bin/env python3
"""Offline tests for two_pass.py (issue #503).

    python3 -m unittest discover -s sim/output-swing/klt -p 'test_*.py'

The curves are SYNTHETIC (tanh / clipped-ramp transfer curves built here), so
nothing below is evidence about the circuit: it checks that the pairing and
audit surface each failure the issue names -- a crossing outside the fine
window, a clipped tracking region, a tampered headroom, coarse/fine passes of
different DUTs -- with the corner and reason, and that a valid below-limit span
is reproduced and graded as a genuine spec failure rather than refused.
Live (batch) evidence is NOT exercised here.
"""
from __future__ import annotations

import csv
import math
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import two_pass as T  # noqa: E402
from swing_post import CONFIG, serialize, sweep_count  # noqa: E402

PID = "mos_tt_27C_1.20V"
VDD, VCM = 1.2, 0.6
FIXTURE_WORKER = {"worker_version_banner": "fixture ngspice build", "ami_id": "fixture-ami",
                  "model_inputs": {"fixture.lib": "c" * 64}}
CS, CE, CSTEP = (float(CONFIG[k]) for k in ("coarse_start_v", "coarse_stop_v", "coarse_step_v"))
FSTEP, HALF = float(CONFIG["fine_step_v"]), float(CONFIG["fine_halfspan_v"])


def grid(start, stop, step):
    return [start + i * step for i in range(sweep_count(start, stop, step))]


def tanh_curve(amp, width, vos):
    return lambda x: VCM + amp * math.tanh((x - vos) / width)


def ramp_curve(amp, half, vos):
    return lambda x: VCM + amp * max(-1.0, min(1.0, (x - vos) / half))


def make_pair(coarse_fn, fine_fn=None, pid=PID, vos_shift=0.0):
    """A coarse pass of coarse_fn and a fine pass centred on its own measured
    crossing (shifted by vos_shift to model a stale window)."""
    fine_fn = fine_fn or coarse_fn
    cvid = grid(CS, CE, CSTEP)
    cvout = [coarse_fn(x) for x in cvid]
    start, stop, _ = T.fine_window(cvid, cvout, VCM)
    start, stop = start + vos_shift, stop + vos_shift
    fvid = grid(start, stop, FSTEP)
    ident = dict(dut_sha256="a" * 64, bench_sha256=T.BENCH_2PF_SHA256, simulator="ngspice-45", process="mos_tt",
                 temp_c=27.0, vdd_v=VDD, vcm_v=VCM, pid=pid, **FIXTURE_WORKER)
    coarse = dict(ident, start=CS, stop=CE, step=CSTEP, vid=cvid, vout=cvout)
    fine = dict(ident, start=start, stop=stop, step=FSTEP, vid=fvid,
                vout=[fine_fn(x) for x in fvid], ivdd=[-12e-6] * len(fvid))
    return coarse, fine


class TwoPass(unittest.TestCase):
    def test_valid_pair_reproduces_every_audit_field_and_grades_pass(self):
        a = T.audit_pair(PID, *make_pair(tanh_curve(0.45, 0.003, 0.015)))
        self.assertEqual(tuple(a["fields"]), T.swing_post.AUDIT_FIELDS)
        self.assertEqual(a["fields"]["op_pass"], "1")
        self.assertEqual(a["fields"]["vos_crossing_v"][:5], "0.015")
        self.assertTrue(all(a["verdicts"].values()), a["verdicts"])
        self.assertEqual(T.check_summary(PID, a["fields"], a), [])

    def test_below_limit_span_is_valid_and_graded_as_failure(self):
        a = T.audit_pair(PID, *make_pair(tanh_curve(0.30, 0.003, 0.015)))
        self.assertTrue(a["valid"])
        self.assertFalse(a["verdicts"]["swing_span_v"])
        self.assertLess(float(a["fields"]["swing_span_v"]), 0.571)

    def test_crossing_outside_fine_window_is_named(self):
        # coarse crossing at 15 mV; the fine curve of the (changed) circuit crosses at 70 mV
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015), tanh_curve(0.45, 0.003, 0.070))
        with self.assertRaisesRegex(T.PairError, rf"point {PID}: fine sweep: fine_sweep_no_crossing"):
            T.audit_pair(PID, coarse, fine)

    def test_stale_fixed_window_is_not_the_crossing_window(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015), vos_shift=0.002)
        with self.assertRaisesRegex(T.PairError, "not the coarse crossing"):
            T.audit_pair(PID, coarse, fine)

    def test_clipped_tracking_region_is_named(self):
        with self.assertRaisesRegex(T.PairError, f"point {PID}: fine sweep: linear_region_touches_window_edge"):
            T.audit_pair(PID, *make_pair(ramp_curve(0.6, 0.04, 0.015)))

    def test_tampered_headroom_in_summary_is_named(self):
        a = T.audit_pair(PID, *make_pair(tanh_curve(0.45, 0.003, 0.015)))
        row = dict(a["fields"], headroom_hi_v=serialize(float(a["fields"]["headroom_hi_v"]) + 0.05))
        bad = T.check_summary(PID, row, a)
        self.assertEqual(len(bad), 1)
        self.assertIn(f"point {PID}: headroom_hi_v", bad[0])

    def test_coarse_and_fine_from_different_duts_are_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        fine["dut_sha256"] = "c" * 64
        with self.assertRaisesRegex(T.PairError, f"point {PID}: coarse/fine passes disagree on dut_sha256"):
            T.audit_pair(PID, coarse, fine)

    def test_different_pvt_or_simulator_is_refused(self):
        for key, val in (("temp_c", 125.0), ("process", "mos_ss"), ("simulator", "ngspice-44")):
            coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
            fine[key] = val
            with self.assertRaisesRegex(T.PairError, f"disagree on {key}"):
                T.audit_pair(PID, coarse, fine)

    def test_wrong_pinned_fine_step_and_short_curve_are_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        fine["step"] = 20e-6
        with self.assertRaisesRegex(T.PairError, "fine step"):
            T.audit_pair(PID, coarse, fine)
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        fine["vid"], fine["vout"], fine["ivdd"] = fine["vid"][:-1], fine["vout"][:-1], fine["ivdd"][:-1]
        with self.assertRaisesRegex(T.PairError, "samples"):
            T.audit_pair(PID, coarse, fine)

    def test_population_names_missing_duplicate_and_extra_passes(self):
        pids = [PID, "mos_ss_27C_1.20V"]
        c1, f1 = make_pair(tanh_curve(0.45, 0.003, 0.015))
        out, problems = T.audit_population(pids, [c1, c1], [f1, dict(f1, pid="mos_ff_27C_1.20V")])
        self.assertIn(PID, out)
        text = "\n".join(problems)
        self.assertIn(f"point {PID}: duplicate coarse pass", text)
        self.assertIn("point mos_ss_27C_1.20V: missing coarse pass", text)
        self.assertIn("point mos_ss_27C_1.20V: missing fine pass", text)
        self.assertIn("point mos_ff_27C_1.20V: fine pass is outside the expected grid", text)

    def test_waveform_conversion_requires_vectors_and_increasing_sweep(self):
        wf = {"variables": [{"index": 0, "name": "vid"}, {"index": 1, "name": "v(out)"}],
              "points": [[0.0, 0.1], [1.0, 0.2]]}
        vid, (vout,) = T.waveform_to_pass_curves(wf, ("v(out)",))
        self.assertEqual((vid, vout), ([0.0, 1.0], [0.1, 0.2]))
        with self.assertRaisesRegex(T.PairError, "lacks a requested vector"):
            T.waveform_to_pass_curves(wf, ("v(out)", "i(vdd)"))
        wf["points"] = [[1.0, 0.1], [0.5, 0.2]]
        with self.assertRaisesRegex(T.PairError, "invalid curve"):
            T.waveform_to_pass_curves(wf, ("v(out)",))


class TwoPassNegativeControls(unittest.TestCase):
    """Each guard of audit_pair / audit_population must fire on bad evidence."""

    def test_missing_curve_keys_are_pair_errors_not_keyerrors(self):
        for label, key in (("coarse", "vout"), ("coarse", "vid"), ("fine", "ivdd"), ("fine", "vout"), ("fine", "vid")):
            coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
            del {"coarse": coarse, "fine": fine}[label][key]
            with self.assertRaisesRegex(T.PairError, f"point {PID}: {label} pass records no {key}"):
                T.audit_pair(PID, coarse, fine)

    def test_vout_or_ivdd_length_mismatch_is_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        fine["ivdd"] = fine["ivdd"][:-1]
        with self.assertRaisesRegex(T.PairError, r"samples.*\(ivdd\)"):
            T.audit_pair(PID, coarse, fine)
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        coarse["vout"] = coarse["vout"][:-1]
        with self.assertRaisesRegex(T.PairError, r"coarse curve.*\(vout\)"):
            T.audit_pair(PID, coarse, fine)

    def test_incomplete_corner_does_not_abort_population(self):
        pids = [PID, "mos_ss_27C_1.20V"]
        c1, f1 = make_pair(tanh_curve(0.45, 0.003, 0.015))
        c2, f2 = make_pair(tanh_curve(0.45, 0.003, 0.015), pid=pids[1])
        del f1["ivdd"]
        out, problems = T.audit_population(pids, [c1, c2], [f1, f2])
        self.assertEqual(list(out), [pids[1]])
        self.assertEqual(problems, [f"point {PID}: fine pass records no ivdd"])

    def test_pass_for_another_point_is_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        fine["pid"] = "mos_ss_27C_1.20V"
        with self.assertRaisesRegex(T.PairError, "fine pass is for point 'mos_ss_27C_1.20V'"):
            T.audit_pair(PID, coarse, fine)

    def test_unpinned_coarse_sweep_is_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        coarse["step"] = CSTEP * 2
        with self.assertRaisesRegex(T.PairError, "not the pinned configuration"):
            T.audit_pair(PID, coarse, fine)

    def test_common_mode_not_half_vdd_is_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        coarse["vdd_v"] = fine["vdd_v"] = 1.5
        with self.assertRaisesRegex(T.PairError, "common mode is not VDD/2"):
            T.audit_pair(PID, coarse, fine)

    def test_coarse_sweep_with_two_crossings_is_refused(self):
        wiggle = lambda x: VCM + 0.45 * math.tanh(x / 0.003) * (1 if abs(x) < 0.06 else -1)
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        coarse["vout"] = [wiggle(x) for x in coarse["vid"]]
        with self.assertRaisesRegex(T.PairError, r"coarse sweep has [2-9]\d* Vout=Vcm crossings"):
            T.audit_pair(PID, coarse, fine)

    def test_coarse_sweep_that_never_saturates_fails_plateau_check(self):
        # 1 mV/V gain over the +-100 mV window: one crossing, no clipped ends.
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        coarse["vout"] = [VCM + 1.0 * (x - 0.015) for x in coarse["vid"]]
        with self.assertRaisesRegex(T.PairError, "plateau check failed"):
            T.audit_pair(PID, coarse, fine)

    def test_fine_window_rejects_non_single_crossing(self):
        cvid = grid(CS, CE, CSTEP)
        with self.assertRaisesRegex(ValueError, "crossings"):
            T.fine_window(cvid, [VCM + 0.3] * len(cvid), VCM)

    def test_coarse_curve_from_another_window_is_refused(self):
        # Right sample count and step, but the axis is shifted 0.2 V from the declared window.
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        n = len(coarse["vid"])
        coarse["vid"] = grid(CS - 0.2, CE - 0.2, CSTEP)[:n]
        coarse["vout"] = [tanh_curve(0.45, 0.003, 0.015)(x) for x in coarse["vid"]]
        with self.assertRaisesRegex(T.PairError, "coarse curve spans .* not the declared sweep"):
            T.audit_pair(PID, coarse, fine)

    def test_fine_curve_from_another_window_is_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        other = tanh_curve(0.45, 0.003, 0.070)
        fine["vid"] = grid(fine["start"] + 0.055, fine["stop"] + 0.055, FSTEP)[:len(fine["vid"])]
        fine["vout"] = [other(x) for x in fine["vid"]]
        with self.assertRaisesRegex(T.PairError, "fine curve spans .* not the declared sweep"):
            T.audit_pair(PID, coarse, fine)

    def test_op_pass_rule_failure_is_refused(self):
        coarse, fine = make_pair(tanh_curve(0.45, 0.003, 0.015))
        real = T.swing_post.fine_measure
        with mock.patch.object(T.swing_post, "fine_measure", lambda *a: dict(real(*a), op_pass=0)):
            with self.assertRaisesRegex(T.PairError, r"per-point sanity rule failed \(op_pass=0\)"):
                T.audit_pair(PID, coarse, fine)

    def test_waveform_short_or_non_numeric_row_is_pair_error(self):
        wf = {"variables": [{"index": 0, "name": "vid"}, {"index": 1, "name": "v(out)"}],
              "points": [[0.0, 0.1], [1.0]]}
        with self.assertRaisesRegex(T.PairError, "short or non-numeric"):
            T.waveform_to_pass_curves(wf, ("v(out)",))
        wf["points"] = [[0.0, 0.1], [1.0, "x"]]
        with self.assertRaisesRegex(T.PairError, "short or non-numeric"):
            T.waveform_to_pass_curves(wf, ("v(out)",))

    def test_summary_cells_compare_numerically_not_as_bytes(self):
        a = T.audit_pair(PID, *make_pair(tanh_curve(0.45, 0.003, 0.015)))
        # authored vdd_v/vcm_v texts and a trailing-zero cell are the same cells
        row = dict(a["fields"], vdd_v="1.20", vcm_v="0.600", headroom_hi_v=a["fields"]["headroom_hi_v"] + "0")
        self.assertEqual(T.check_summary(PID, row, a), [])
        for bad in ("", None, "x", "1.3", "nan"):
            self.assertEqual(len(T.check_summary(PID, dict(a["fields"], vdd_v=bad), a)), 1, bad)
        # a nan reproduced cell is matched only by a nan cell
        a2 = {"fields": dict(a["fields"], vos_crossing_v="nan")}
        self.assertEqual(T.check_summary(PID, dict(a["fields"], vos_crossing_v="NaN"), a2), [])
        self.assertEqual(len(T.check_summary(PID, dict(a["fields"], vos_crossing_v="0"), a2)), 1)

    def test_waveform_variables_must_be_objects(self):
        with self.assertRaisesRegex(T.PairError, "variables must be objects"):
            T.waveform_to_pass_curves({"variables": ["vid", "v(out)"], "points": []}, ("v(out)",))

    def test_limits_are_the_ratified_literals(self):
        import compare as C
        self.assertEqual(T.LIMITS, {n: l["min"] for n, l in C.RATIFIED_LIMITS.items()})


SWING = os.path.normpath(os.path.join(HERE, ".."))
RECORD = os.path.join(SWING, "records", "20260921-151759-707b34c.csv")
CORNERS = os.path.join(SWING, "corners", "20260921-151759-707b34c")


class ArchivedEvidence(unittest.TestCase):
    """Replays the committed 45-corner record: the summary row comes from the
    record, never from the audit, so the comparison rule is not circular."""

    def test_committed_record_reproduces_with_no_false_tamper(self):
        with open(RECORD, newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 45)
        bad, failing = [], []
        for r in rows:
            pid = r["point_id"]
            with open(os.path.join(CORNERS, f"{pid}_coarse.csv")) as fh:
                cvid, (cvout,) = T.swing_post.parse_wrdata(fh.read(), T.swing_post.COARSE_VECTORS, pid)
            with open(os.path.join(CORNERS, f"{pid}_fine.csv")) as fh:
                fvid, (fvout, fivdd) = T.swing_post.parse_wrdata(fh.read(), T.swing_post.FINE_VECTORS, pid)
            vdd, vcm = float(r["vdd_v"]), float(r["vcm_v"])
            start, stop, _ = T.fine_window(cvid, cvout, vcm)
            ident = dict(dut_sha256="a" * 64, bench_sha256=T.BENCH_2PF_SHA256, simulator="ngspice", pid=pid,
                         process=r["corner"], temp_c=float(r["temp_c"]), vdd_v=vdd, vcm_v=vcm, **FIXTURE_WORKER)
            coarse = dict(ident, start=CS, stop=CE, step=CSTEP, vid=cvid, vout=cvout)
            fine = dict(ident, start=start, stop=stop, step=FSTEP, vid=fvid, vout=fvout, ivdd=fivdd)
            out, problems = T.audit_population([pid], [coarse], [fine])
            bad += problems
            if pid in out:
                bad += T.check_summary(pid, r, out[pid])
                failing += [(pid, n) for n, ok in out[pid]["verdicts"].items() if not ok]
        self.assertEqual(bad, [])
        # the one genuine literal miss documented in compare.py
        self.assertEqual(failing, [("mos_ss_125C_1.08V", "swing_span_v")])


if __name__ == "__main__":
    unittest.main()

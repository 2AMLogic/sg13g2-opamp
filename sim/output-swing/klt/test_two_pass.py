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

import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import two_pass as T  # noqa: E402
from swing_post import CONFIG, serialize, sweep_count  # noqa: E402

PID = "mos_tt_27C_1.20V"
VDD, VCM = 1.2, 0.6
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
    ident = dict(dut_sha256="a" * 64, bench_sha256="b" * 64, simulator="ngspice-45", process="mos_tt",
                 temp_c=27.0, vdd_v=VDD, vcm_v=VCM, pid=pid)
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


if __name__ == "__main__":
    unittest.main()

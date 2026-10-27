#!/usr/bin/env python3
"""Offline tests for compare_direct.py (issue #307).

    python3 -m unittest discover -s sim/cmrr-psrr/klt -p 'test_*.py'

The committed direct envelope and join record are the baseline; the tests that
carry weight are the negative controls, each of which must fail and name the
point: a perturbed psrr_db, a bound-verdict flip, a missing point, a missing
measurement, a skipped/errored corner and a non-45-point join record.
"""

from __future__ import annotations

import copy
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
import compare_direct as D  # noqa: E402
from klt_envelope import InputError  # noqa: E402

RECORDS = os.path.join(HERE, "records")
JOIN = os.path.join(RECORDS, "20261016-171154-ff5ee9a.compare.json")
ENVELOPE = sorted(glob.glob(os.path.join(RECORDS, "*.direct.sim.json")))[0]


def _env():
    with open(ENVELOPE) as f:
        return json.load(f)


def _meas(env, idx, name):
    return next(m for m in env["corners"][idx]["measurements"] if m["name"] == name)


class CompareDirect(unittest.TestCase):
    def setUp(self):
        self.join = D.load_join(JOIN)

    def _compare(self, env):
        return D.compare(D.index_envelope(env), self.join)

    def test_baseline_agrees(self):
        rep = self._compare(_env())
        self.assertEqual(rep["status"], "agree")
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["row"]["direct_worst"]["point"], "mos_fs_125C_1.08V")

    def test_perturbed_psrr_is_out_of_tolerance(self):
        env = _env()
        _meas(env, 7, "psrr_db")["value"] += 0.5
        rep = self._compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(len(rep["out_of_tolerance"]), 1)
        self.assertIn("psrr_db", rep["out_of_tolerance"][0])

    def test_bound_verdict_flip_is_reported(self):
        env = _env()
        _meas(env, 3, "psrr_db")["value"] = 1.0
        rep = self._compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(len(rep["bound_verdict_disagreements"]), 1)

    def test_missing_point_refused(self):
        env = _env()
        env["corners"].pop()
        env["corner_count"] = 44
        with self.assertRaises(InputError):
            D.index_envelope(env)

    def test_missing_measurement_refused(self):
        env = _env()
        env["corners"][0]["measurements"] = [m for m in env["corners"][0]["measurements"] if m["name"] != "psrr_db"]
        with self.assertRaisesRegex(InputError, "psrr_db"):
            D.index_envelope(env)

    def test_errored_measurement_refused(self):
        env = _env()
        _meas(env, 0, "psrr_db")["status"] = "error"
        with self.assertRaises(InputError):
            D.index_envelope(env)

    def test_short_join_record_refused(self):
        with open(JOIN) as f:
            rec = json.load(f)
        rec["points"] = rec["points"][:-1]
        path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "short-join-%d.json" % os.getpid())
        with open(path, "w") as f:
            json.dump(rec, f)
        try:
            with self.assertRaises(InputError):
                D.load_join(path)
        finally:
            os.unlink(path)

    def test_envelope_carries_the_ratified_bound(self):
        env = _env()
        with open(os.path.join(HERE, "psrr_direct.request.json")) as f:
            req = json.load(f)
        psrr = next(m for m in req["measurements"] if m["name"] == "psrr_db")
        self.assertEqual(psrr["limits"], {"min": D.PSRR_BOUND_DB})
        self.assertEqual(env["status"], "pass")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""The mixin's contract, proved on a minimal synthetic bench (issue #370).

A two-point fake bench implementing the EnvelopeControlMixin contract runs
all thirteen controls through klt_envelope.index_envelope itself; if the
mixin's derived refusal fragments ever drift from the shared gate's messages
or a control stops raising, this runs red.
"""

from __future__ import annotations

import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import klt_envelope as K  # noqa: E402
from envelope_control_mixin import EnvelopeControlMixin  # noqa: E402

MS = ("m_one", "m_two")
KEYS = (("mos_tt", 27, 1.2), ("mos_ff", 125, 1.32))


def _env():
    corners = []
    for k in KEYS:
        corners.append({
            "corner_id": K.key_str(k), "process": k[0], "temperature_c": k[1],
            "supply_v": {"vdd": k[2], "vinp": k[2] / 2}, "status": "pass",
            "measurements": [{"name": n, "value": 1.0, "status": "pass"} for n in MS],
        })
    return {"schema_version": 3, "status": "pass", "corner_count": len(corners),
            "coverage": {"nothing_checked": False, "skipped": []}, "corners": corners}


class FakeBench(EnvelopeControlMixin, unittest.TestCase):
    """A minimal conforming bench: two corners, two measurements, explicit
    point set (so the extra-corner control exercises the requested-set
    message branch)."""

    WORST = KEYS[0]
    null_meas = "m_one"
    nonfinite_meas = "m_two"
    absent_meas = "m_one"
    points = KEYS          # the gate below requires exactly KEYS, not the ratified grid

    def env(self):
        return _env()

    def gate(self, env):
        K.index_envelope(env, "test", MS, points=KEYS)


class TestMixinContract(unittest.TestCase):
    def test_all_thirteen_controls_run_and_refuse_through_a_minimal_gate(self):
        names = sorted(n for n in dir(FakeBench) if n.startswith("test_"))
        self.assertEqual(len(names), 13, names)
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
            unittest.TestSuite(FakeBench(n) for n in names))
        self.assertEqual(result.testsRun, 13)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()

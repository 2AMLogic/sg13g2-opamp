"""Offline tests for offset_sweep.classify_sweep (no PDK, no ngspice).

  python3 -m unittest discover -s sim/input-offset -p 'test_*.py'
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("offset_sweep", os.path.join(HERE, "offset_sweep.py"))
os_ = importlib.util.module_from_spec(_s)
_s.loader.exec_module(os_)

TARGET = 0.6


class ClassifySweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.n = 0

    def write(self, text):
        self.n += 1
        p = os.path.join(self.tmp.name, "s%d.csv" % self.n)
        with open(p, "w") as f:
            f.write(text)
        return p

    def check(self, text, status, reason):
        r = os_.classify_sweep(self.write(text), TARGET)
        self.assertEqual((r[0], r[1]), (status, reason), r)
        if status == "FAIL":
            self.assertEqual(r[2], "nan")
        return r

    def test_valid_crossing_preserves_offset(self):
        r = self.check("-0.1 0.0\n0.1 1.2\n", "PASS", "")
        self.assertEqual(r[2], "%.9g" % 0.0)
        r = self.check("-0.05 0.2\n0.0 0.5\n0.05 0.8\n0.06 1.0\n", "PASS", "")
        frac = (0.6 - 0.5) / (0.8 - 0.5)
        self.assertEqual(r[2], "%.9g" % (0.0 + frac * (0.05 - 0.0)))

    def test_no_crossing(self):
        self.check("-0.1 0.0\n0.1 0.2\n", "FAIL", "crossings=0")

    def test_multiple_crossings(self):
        self.check("-0.05 0.0\n0.0 1.2\n0.05 0.0\n", "FAIL", "crossings=2")

    def test_out_of_window(self):
        self.check("0.0 0.0\n0.2 1.2\n", "FAIL", "vos_outside_window")

    def test_nonfinite_either_column(self):
        for tok in ("nan", "NaN", "inf", "+inf", "-inf", "-Infinity"):
            self.check("-0.1 %s\n0.1 1.0\n" % tok, "FAIL", "nonfinite_sweep_data")
            self.check("%s 0.0\n0.1 1.2\n" % tok, "FAIL", "nonfinite_sweep_data")
            self.check("-0.1 0.0\n0.1 %s\n" % tok, "FAIL", "nonfinite_sweep_data")
            self.check("-0.1 0.0\n%s 1.2\n" % tok, "FAIL", "nonfinite_sweep_data")

    def test_issue_numeric_control(self):
        self.check("-0.1 -inf\n0.1 1.0\n", "FAIL", "nonfinite_sweep_data")

    def test_nonfinite_interpolation(self):
        # finite samples whose interpolation overflows to inf/nan
        self.check("-1e308 -1e308\n1e308 1e308\n", "FAIL", "nonfinite_offset")

    def test_malformed_tokens(self):
        for bad in ("abc 0.0\n0.1 1.2\n", "-0.1 0.0\n0.1 1.2x\n", "-0.1 0,5\n0.1 1.2\n"):
            self.check(bad, "FAIL", "malformed_sweep_token")

    def test_missing_or_empty_output(self):
        r = os_.classify_sweep(os.path.join(self.tmp.name, "absent.csv"), TARGET)
        self.assertEqual(r, ("FAIL", "no_sweep_file", "nan"))
        self.check("", "FAIL", "no_sweep_file")
        self.check("onlyonetoken\n", "FAIL", "no_sweep_file")

    def test_failed_draw_does_not_suppress_later_draws(self):
        paths = [self.write("-0.1 nan\n0.1 1.0\n"), self.write("junk x\n"),
                 self.write("-0.1 0.0\n0.1 1.2\n")]
        res = [os_.classify_sweep(p, TARGET)[0] for p in paths]
        self.assertEqual(res, ["FAIL", "FAIL", "PASS"])


if __name__ == "__main__":
    unittest.main()

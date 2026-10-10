"""Offline tests for cmr_analysis (no ngspice, no PDK).

  python3 -m unittest sim/input-cmr/test_cmr_analysis.py

Committed raw curves pin the exact output lines the runner reads (the
values in records/20260921-174405-65f5fb4.csv); synthetic curves pin the
deliberately different predicates, scan directions, neighbour samples and
missing-bound sentinels of each locator.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, "cmr_analysis.py")
_s = importlib.util.spec_from_file_location("cmr_analysis", MOD)
ca = importlib.util.module_from_spec(_s)
_s.loader.exec_module(ca)

FF = os.path.join(HERE, "corners", "20260921-174405-65f5fb4", "mos_ff_-40C_1.08V")
FINE_STEP = "0.00025"


def curve(samples, extra=()):
    """Write a 12-column raw curve: samples are (vcm, vtail, vd1[, vd2, ivdd])."""
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    for s in samples:
        vcm, vtail, vd1 = s[0], s[1], s[2]
        vd2 = s[3] if len(s) > 3 else vd1
        ivdd = s[4] if len(s) > 4 else 1e-5
        cols = []
        for y in (0.0, vtail, vd1, vd2, 0.4, ivdd):
            cols += [vcm, y]
        f.write(" ".join(f"{c:.8e}" for c in cols) + " \n")
    for line in extra:
        f.write(line + "\n")
    f.close()
    return f.name


class Fixture(unittest.TestCase):
    def setUp(self):
        self.paths = []

    def tearDown(self):
        for p in self.paths:
            os.unlink(p)

    def mk(self, samples, extra=()):
        p = curve(samples, extra)
        self.paths.append(p)
        return p


class CommittedCurves(unittest.TestCase):
    # mos_ff_-40C_1.08V: vdsat5 0.11, vth_pair_cc 0.41897616, icmr_hi 0.942995622
    def test_fine_hi_reproduces_record(self):
        self.assertEqual(ca.fine_hi([FF + "_finehi.csv", "0.41897616"]),
                         "0.942995622 0.447953459 0.494792721 0.447953459 "
                         "0.076078528 0.076082038 4.32881894e-05 1")

    def test_fine_hi_verify_same_vth_closes(self):
        self.assertEqual(ca.fine_hi_verify([FF + "_finehi.csv", "0.41897616", "0.942995622", FINE_STEP]),
                         "0.942995622 1 1.74211756e-11")

    def test_fine_lo_reproduces_record(self):
        self.assertEqual(ca.fine_lo([FF + "_finelo.csv", "0.11"]),
                         "0.524166351 0.110196642 0.44348717 0.44349636 3.25170101e-05 1")

    def test_coarse_and_relocate(self):
        self.assertEqual(ca.coarse_bounds([FF + "_coarse.csv", "0.11", "0.41897616"]),
                         "0.524164 0.942996 0.4496092 1 1")
        self.assertEqual(ca.fp_relocate([FF + "_coarse.csv", "0.41897616"]),
                         "0.94299618 0.445920083 1")

    def test_verify_and_bound_share_crossing(self):
        vcm, vd1 = ca.read_samples(FF + "_finehi.csv", ca.COL_VCM, ca.COL_VD1)
        for d in (-0.004, 0.0, 0.002):
            vth = 0.41897616 + d
            bound, _ = ca.fine_hi_crossing(vcm, vd1, vth)
            got = ca.fine_hi([FF + "_finehi.csv", repr(vth)]).split()[0]
            ver = ca.fine_hi_verify([FF + "_finehi.csv", repr(vth), got, FINE_STEP]).split()
            self.assertEqual(got, f"{bound:.9g}")
            self.assertEqual(ver[0], got)
            self.assertEqual(ver[1], "1")

    def test_cli_matches_functions(self):
        out = subprocess.run([sys.executable, "-I", MOD, "fine-hi", FF + "_finehi.csv", "0.41897616"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out, ca.fine_hi([FF + "_finehi.csv", "0.41897616"]) + "\n")
        bad = subprocess.run([sys.executable, "-I", MOD, "fine-hi", FF + "_finehi.csv"],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)


class Reader(Fixture):
    def test_short_rows_skipped_and_columns(self):
        p = self.mk([(0.1, 0.2, 0.3, 0.4, 5e-5)], extra=["1 2 3", "", "* comment"])
        vcm, vtail, vd1, vd2, ivdd = ca.read_samples(p, 0, 3, 5, 7, 11)
        self.assertEqual((vcm, vtail, vd1, vd2, ivdd), ([0.1], [0.2], [0.3], [0.4], [5e-5]))


class FineHi(Fixture):
    # y = vd1 - vcm + vth; vth = 0.5 throughout.
    def test_no_crossing_sentinels(self):
        p = self.mk([(0.1, 0.0, 0.9), (0.2, 0.0, 0.9), (0.3, 0.0, 0.9)])
        self.assertEqual(ca.fine_hi([p, "0.5"]), "nan nan nan nan nan nan nan 0")
        self.assertEqual(ca.fine_hi_verify([p, "0.5", "0.2", FINE_STEP]), "nan 0 nan")
        self.assertEqual(ca.fine_hi([p, "nan"]), "nan nan nan nan nan nan nan 0")
        self.assertEqual(ca.fine_hi_verify([p, "0.5", "nan", FINE_STEP]), "nan 0 nan")

    def test_exact_zero_endpoint_is_in_range(self):
        # y: +0.1, 0 (exact), -0.1 -> a >= 0 > b first holds at i=1
        p = self.mk([(0.1, 0.05, -0.3), (0.2, 0.06, -0.3), (0.3, 0.07, -0.3)])
        self.assertEqual(ca.fine_hi_crossing([0.1, 0.2, 0.3], [-0.3, -0.3, -0.3], 0.5), (0.2, 1))
        self.assertEqual(ca.fine_hi([p, "0.5"]).split()[:2], ["0.2", "0.06"])

    def test_rising_crossing_ignored(self):
        # y: -0.1 -> +0.1 is not a falling crossing
        self.assertEqual(ca.fine_hi_crossing([0.1, 0.2], [-0.5, -0.2], 0.5), (None, None))

    def test_multiple_crossings_first_ascending_and_lower_neighbour(self):
        # y: +0.1, -0.1, +0.1, -0.1 -> bound in the first pair, s = 0
        p = self.mk([(0.1, 0.01, -0.3), (0.2, 0.02, -0.4), (0.3, 0.03, -0.1), (0.4, 0.04, -0.2)])
        f = ca.fine_hi([p, "0.5"]).split()
        self.assertEqual(f[0], "0.15")
        self.assertEqual(f[1], "0.01")   # vtail at s = i (lower-Vcm sample)
        self.assertEqual(f[-1], "1")     # strictly inside the window

    def test_verify_convergence_threshold(self):
        p = self.mk([(0.1, 0.01, -0.3), (0.2, 0.02, -0.4)])
        self.assertEqual(ca.fine_hi_verify([p, "0.5", "0.1504", FINE_STEP]), "0.15 1 0.0004")
        self.assertEqual(ca.fine_hi_verify([p, "0.5", "0.1506", FINE_STEP]).split()[1], "0")


class FineLo(Fixture):
    def test_scan_down_upper_neighbour_and_sentinels(self):
        # vtail - 0.1: -0.05, +0.05, -0.05, +0.05 -> scanning down, first
        # a >= 0 > b at i=3 (bound 0.35), state at s=3 (upper sample)
        p = self.mk([(0.1, 0.05, 0.5), (0.2, 0.15, 0.5), (0.3, 0.05, 0.5), (0.4, 0.15, 0.6, 0.7, 2e-5)])
        self.assertEqual(ca.fine_lo([p, "0.1"]), "0.35 0.15 0.45 0.55 2e-05 1")
        self.assertEqual(ca.fine_lo([p, "nan"]), "nan nan nan nan nan 0")
        self.assertEqual(ca.fine_lo([p, "1.0"]), "nan nan nan nan nan 0")

    def test_exact_zero_endpoint(self):
        # vtail - 0.1 at top sample exactly 0 -> counts (a >= 0), bound there
        p = self.mk([(0.1, 0.0, 0.5), (0.2, 0.1, 0.5)])
        self.assertEqual(ca.fine_lo([p, "0.1"]).split()[0], "0.2")
        self.assertEqual(ca.fine_lo([p, "0.1"]).split()[-1], "0")  # on the window edge


class Coarse(Fixture):
    def test_coarse_predicates_and_neighbours(self):
        # lo: vtail vs 0.1 scanned downward, either direction counts.
        # hi: vd1 - vcm vs -0.5 scanned upward; hi_vsb_seed = vtail[i].
        p = self.mk([(0.1, 0.05, -0.3), (0.2, 0.15, -0.25), (0.3, 0.2, -0.25), (0.4, 0.25, -0.15)])
        self.assertEqual(ca.coarse_bounds([p, "0.1", "0.5"]), "0.15 0.25 0.2 1 1")
        # fp-relocate: same hi crossing, seed is vtail[i - 1]
        self.assertEqual(ca.fp_relocate([p, "0.5"]), "0.25 0.15 1")

    def test_coarse_exact_zero_endpoint_and_sentinels(self):
        # y_hi + vth: +0.1, 0 -> (a > 0 >= b) holds with b == 0: x = 0.2
        p = self.mk([(0.1, 0.2, -0.3), (0.2, 0.2, -0.3)])
        self.assertEqual(ca.coarse_bounds([p, "0.1", "0.5"]), "nan 0.2 0.2 0 1")
        self.assertEqual(ca.fp_relocate([p, "0.5"]), "0.2 0.2 1")
        self.assertEqual(ca.coarse_bounds([p, "nan", "0.5"]), "nan nan nan 0 0")
        self.assertEqual(ca.coarse_bounds([p, "0.1", "nan"]), "nan nan nan 0 0")
        self.assertEqual(ca.fp_relocate([p, "nan"]), "nan nan 0")

    def test_coarse_rising_crossing_counts(self):
        # Unlike the fine hi locator, coarse accepts a crossing in either direction.
        p = self.mk([(0.1, 0.2, -0.5), (0.2, 0.2, -0.2)])
        self.assertEqual(ca.fp_relocate([p, "0.5"]).split()[0], "0.15")
        self.assertEqual(ca.fine_hi([p, "0.5"]), "nan nan nan nan nan nan nan 0")


if __name__ == "__main__":
    unittest.main()

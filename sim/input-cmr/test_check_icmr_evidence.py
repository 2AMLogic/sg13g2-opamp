"""Offline tests for check_icmr_evidence (no ngspice).

  python3 -m unittest sim/input-cmr/test_check_icmr_evidence.py
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("cie", os.path.join(HERE, "check_icmr_evidence.py"))
cie = importlib.util.module_from_spec(_s)
_s.loader.exec_module(cie)

HDR = ("point_id,vdd_v,vcm_v,op_pass,icmr_lo_v,icmr_hi_v,icmr_span_v,"
       "buffer_use_lo_v,buffer_use_hi_v,buffer_use_span_v,contains_vcm")


def write(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    f.write("\n".join([HDR] + lines) + "\n")
    f.close()
    return f.name


def load_lines(lines):
    p = write(lines)
    try:
        return cie.load(p)
    finally:
        os.unlink(p)


class Committed(unittest.TestCase):
    def test_figures(self):
        s = cie.summarize(cie.load())
        self.assertEqual(s["n"], 45)
        self.assertEqual(s["n_excl_midrail"], 15)
        self.assertEqual((s["lo_id"], s["hi_id"]), ("mos_ss_-40C_1.08V", "mos_fs_125C_1.08V"))
        self.assertAlmostEqual(s["lo"], 0.640129553, 9)
        self.assertAlmostEqual(s["hi"], 0.795393113, 9)
        self.assertAlmostEqual(s["max_gap"], 0.100129553, 9)
        self.assertEqual(s["worst_span_id"], "mos_ss_125C_1.08V")
        self.assertAlmostEqual(s["buf_hi"], 0.772224158, 9)

    def test_outward_candidate(self):
        rows = cie.load()
        s = cie.summarize(rows)
        lo, hi = cie.outward_safe(s["lo"], s["hi"])
        self.assertEqual((lo, hi), (0.641, 0.795))
        self.assertEqual(cie.check_candidate(rows, lo, hi), [])
        # naive display rounding (0.6401) is NOT guaranteed
        self.assertEqual(cie.check_candidate(rows, 0.6401, 0.7954),
                         ["mos_ss_-40C_1.08V", "mos_fs_125C_1.08V"])
        # input-stage upper bound is not a buffer-usable bound
        self.assertNotEqual(cie.check_candidate(rows, lo, hi, key="buffer"), [])


class Malformed(unittest.TestCase):
    OK = "a,1.2,0.6,1,0.5,0.9,0.4,0.5,0.8,0.3,1"

    def test_ok(self):
        self.assertEqual(len(load_lines([self.OK])), 1)

    def test_bad_rows(self):
        for bad in ("a,1.2,0.6,1,0.5,0.9,0.4,0.5,0.8,0.3,1",  # duplicate id
                    ",1.2,0.6,1,0.5,0.9,0.4,0.5,0.8,0.3,1",   # missing id
                    "b,1.2,0.6,0,0.5,0.9,0.4,0.5,0.8,0.3,1",  # op_pass
                    "b,1.2,0.6,1,0.9,0.5,0.4,0.5,0.8,0.3,1",  # lo>hi
                    "b,1.2,0.6,1,x,0.9,0.4,0.5,0.8,0.3,1",    # non-numeric
                    "b,1.2,0.6,1,nan,0.9,0.4,0.5,0.8,0.3,1",  # non-finite
                    "b,1.2,0.6,1,0.5,0.9,0.4,0.5,0.8,0.3,2"):  # contains_vcm
            with self.assertRaises(cie.EvidenceError, msg=bad):
                load_lines([self.OK, bad])

    def test_changed_binding_corner(self):
        rows = load_lines([self.OK, "b,1.2,0.6,1,0.7,0.9,0.2,0.7,0.8,0.1,0"])
        s = cie.summarize(rows)
        self.assertEqual(s["lo_id"], "b")
        self.assertEqual(s["n_excl_midrail"], 1)


if __name__ == "__main__":
    unittest.main()

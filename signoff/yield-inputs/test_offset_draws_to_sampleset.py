"""Offline fixture tests for offset_draws_to_sampleset.py (stdlib only)."""
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("o2s", HERE / "offset_draws_to_sampleset.py")
o2s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o2s)

SUM_HDR = "point_id,mode,mos_section,temp_c,vdd_v,seed_base,n_draws,n_pass,status\n"
SUMMARY = (SUM_HDR +
           "pA,mismatch,secA,27,1.20,100,3,3,PASS\n"
           "pB,mismatch,secB,27,1.20,200,3,2,PASS\n"
           "pN,negctrl,secN,27,1.20,100,3,3,PASS\n")
DRAW_HDR = ("point_id,mode,corner,mos_section,temp_c,vdd_v,draw_index,"
            "draw_seed,status,fail_reason,vos_v")


def drow(pid, mode, sec, idx, seed, status="PASS", vos="0.01"):
    return f"{pid},{mode},c,{sec},27,1.20,{idx},{seed},{status},,{vos}"


def good_rows():
    r = [drow("pA", "mismatch", "secA", i, 100 + i, vos=f"0.0{i + 1}") for i in range(3)]
    r += [drow("pB", "mismatch", "secB", 0, 200, vos="0.05"),
          drow("pB", "mismatch", "secB", 1, 201, "FAIL", "nan"),
          drow("pB", "mismatch", "secB", 2, 202, vos="0.07")]
    r += [drow("pN", "negctrl", "secN", i, 100 + i, vos="0") for i in range(3)]
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        (self.dir / "sum.csv").write_text(SUMMARY)

    def write(self, rows):
        p = self.dir / "draws.csv"
        p.write_text(DRAW_HDR + "\n" + "\n".join(rows) + "\n")
        return p

    def build(self, rows):
        return o2s.build(self.write(rows), self.dir / "sum.csv")

    def fails(self, rows, *needles):
        with self.assertRaises(o2s.DrawValidationError) as cm:
            self.build(rows)
        text = "\n".join(cm.exception.problems)
        for n in needles:
            self.assertIn(n, text)


class Valid(Base):
    def test_valid_failed_null_negctrl_excluded(self):
        doc = self.build(good_rows())
        self.assertEqual([m["name"] for m in doc["measurements"]], ["pA", "pB"])
        self.assertEqual(doc["measurements"][0]["samples"], [0.01, 0.02, 0.03])
        self.assertEqual(doc["measurements"][1]["samples"], [0.05, None, 0.07])
        json.loads(o2s.render(doc))

    def test_row_order_independent(self):
        self.assertEqual(self.build(good_rows()), self.build(good_rows()[::-1]))


class Invalid(Base):
    def test_duplicate_draw(self):
        r = good_rows() + [drow("pA", "mismatch", "secA", 1, 101)]
        self.fails(r, "duplicate draw_index 1", "point 'pA'", "line 11")

    def test_missing_draw(self):
        r = good_rows()
        del r[1]
        self.fails(r, "1 of 3 expected draws missing (1)")

    def test_missing_point(self):
        self.fails(good_rows()[:3] + good_rows()[6:], "point 'pB'")

    def test_index_out_of_range(self):
        r = good_rows() + [drow("pA", "mismatch", "secA", 3, 103)]
        self.fails(r, "draw_index 3 outside 0..2")

    def test_conflicting_metadata(self):
        r = good_rows()
        r[0] = drow("pA", "mismatch", "other", 0, 100, vos="0.01")
        self.fails(r, "mos_section 'other' conflicts")

    def test_conflicting_mode(self):
        r = good_rows()
        r[0] = drow("pA", "negctrl", "secA", 0, 100)
        self.fails(r, "mode 'negctrl' conflicts")

    def test_seed_mismatch(self):
        r = good_rows()
        r[0] = drow("pA", "mismatch", "secA", 0, 999)
        self.fails(r, "draw_seed 999")

    def test_unknown_mode_and_status(self):
        r = good_rows()
        r[0] = drow("pA", "bogus", "secA", 0, 100)
        r[1] = drow("pA", "mismatch", "secA", 1, 101, "WEIRD")
        self.fails(r, "unknown mode 'bogus'", "unknown status 'WEIRD'")

    def test_unknown_point(self):
        self.fails(good_rows() + [drow("zz", "mismatch", "s", 0, 1)],
                   "point not in campaign summary")

    def test_pass_nonfinite(self):
        for bad in ("nan", "NaN", "inf", "-inf", "Infinity", "1e999", "", "abc"):
            r = good_rows()
            r[0] = drow("pA", "mismatch", "secA", 0, 100, vos=bad)
            with self.subTest(bad=bad):
                self.fails(r, "PASS vos_v", "point 'pA'")

    def test_pass_count_disagrees_with_summary(self):
        r = good_rows()
        r[2] = drow("pA", "mismatch", "secA", 2, 102, "FAIL", "nan")
        self.fails(r, "n_pass=3")

    def test_render_refuses_nan(self):
        with self.assertRaises(ValueError):
            o2s.render({"measurements": [{"samples": [float("nan")]}]})

    def test_missing_column(self):
        p = self.dir / "draws.csv"
        p.write_text("point_id,mode\npA,mismatch\n")
        with self.assertRaises(o2s.DrawValidationError):
            o2s.build(p, self.dir / "sum.csv")

    def test_cli_exit_and_diagnostics(self):
        p = self.write(good_rows() + [drow("pA", "mismatch", "secA", 1, 101)])
        err = io.StringIO()
        with redirect_stderr(err):
            rc = _run(["--draws", str(p), "--summary", str(self.dir / "sum.csv"),
                       "--out", str(self.dir / "o.json")])
        self.assertEqual(rc, 1)
        self.assertIn("duplicate draw_index 1", err.getvalue())
        self.assertFalse((self.dir / "o.json").exists())


def _run(argv):
    import sys
    old = sys.argv
    sys.argv = ["x"] + argv
    try:
        return o2s.main()
    finally:
        sys.argv = old


class Committed(Base):
    def test_committed_sampleset_reproduces_byte_for_byte(self):
        self.assertEqual(o2s.render(o2s.build(o2s.DRAWS, o2s.SUMMARY)),
                         o2s.OUT.read_text())

    def test_check_detects_changed_sampleset(self):
        out = self.dir / "o.json"
        out.write_text(o2s.OUT.read_text().replace("0.0", "0.1", 1))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(_run(["--check", "--out", str(out)]), 1)
        out.write_text(o2s.OUT.read_text())
        self.assertEqual(_run(["--check", "--out", str(out)]), 0)

    def test_committed_campaign_shape(self):
        doc = json.loads(o2s.OUT.read_text())
        self.assertEqual(len(doc["measurements"]), 15)
        self.assertTrue(all(len(m["samples"]) == 300 for m in doc["measurements"]))
        self.assertFalse(any("negctrl" in m["name"] for m in doc["measurements"]))


if __name__ == "__main__":
    unittest.main()

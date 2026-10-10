"""Offline controls for sim/cmrr-mismatch/make_draws_csv.sh (issue #107).

Synthetic two-point record under a TemporaryDirectory: positive round-trip,
determinism, and negative controls (tampered draw, truncated file, forged
summary column, excluded-draw visibility, overwrite refusal). One test also
runs the real committed record (13,500 rows, worst draw 25.94 dB). No PDK,
ngspice or klt is needed.
"""
import csv
import math
import subprocess
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SIM_DIR / "cmrr-mismatch" / "make_draws_csv.sh"
REAL_RECORD = SIM_DIR / "cmrr-mismatch" / "records" / "20260921-172304-65f5fb4.csv"

N = 6
AV0 = 40.0
HEADER = ("point_id,corner,temp_c,vdd_v,vcm_v,av0_db,sys_acm0_db,sys_cmrr_db,mc_n,mc_n_ok,"
          "mc_n_excluded,op_fail,plateau_fail,acm_lin_mean,acm_lin_sigma,acm_plus_3sigma_db,"
          "cmrr_3sigma_db,cmrr_db_mean,cmrr_db_p01,cmrr_db_min,cmrr_1khz_3sigma_db,plateau_max_db")
ACM = [4.0, 5.0, 6.0, 4.5, 5.5, 5.2]


def sample_text(acm, bad_op=None):
    out = []
    for k, a in enumerate(acm):
        vout = 0.6 if k != bad_op else 0.05  # 0.05 V is far off midrail
        out.append(f"OP {k} {vout} 0.6 0.45 0.15 0.38 0.0001")
        out.append(f"AC {k} {a} {a} {a - 0.001}")
    return "\n".join(out) + "\n"


def summary_row(pid, acm, n_bad=0):
    ok = [a for k, a in enumerate(acm) if k != 0 or not n_bad]
    lin = [10 ** (a / 20) for a in ok]
    mu = sum(lin) / len(lin)
    sd = math.sqrt(sum((x - mu) ** 2 for x in lin) / (len(lin) - 1))
    g = lambda x: f"{x:.6g}"
    cm = [AV0 - a for a in ok]
    return dict(point_id=pid, corner="mos_tt", temp_c="27", vdd_v="1.20", vcm_v="0.6",
                av0_db=g(AV0), mc_n=str(N), mc_n_ok=str(len(ok)),
                mc_n_excluded=str(n_bad), op_fail=str(n_bad), plateau_fail="0",
                acm_lin_mean=g(mu), acm_lin_sigma=g(sd),
                cmrr_3sigma_db=g(AV0 - 20 * math.log10(mu + 3 * sd)),
                cmrr_db_min=g(min(cm)))


class MakeDrawsCsv(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.rec_dir = self.root / "records"
        self.samples = self.root / "corners" / "rid"
        self.rec_dir.mkdir()
        self.samples.mkdir(parents=True)

    def build(self, bad_op=None, forge=None):
        pid = "mos_tt_27C_1.20V"
        (self.samples / f"{pid}_mc_samples.txt").write_text(sample_text(ACM, bad_op))
        row = summary_row(pid, ACM, n_bad=1 if bad_op is not None else 0)
        if forge:
            row[forge[0]] = forge[1]
        cols = HEADER.split(",")
        rec = self.rec_dir / "rid.csv"
        with open(rec, "w", newline="") as f:
            w = csv.DictWriter(f, cols, restval="0", lineterminator="\n")
            w.writeheader()
            w.writerow(row)
        return rec

    def run_script(self, rec, out=None, extra=()):
        out = out or self.rec_dir / "rid-draws.csv"
        p = subprocess.run(
            [str(SCRIPT), "--record-csv", str(rec), "--samples-dir", str(self.samples),
             "--out", str(out), *extra],
            capture_output=True, text=True)
        return p, out

    def test_roundtrip_and_deterministic(self):
        rec = self.build()
        p, out = self.run_script(rec)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = list(csv.DictReader(open(out)))
        self.assertEqual(len(rows), N)
        self.assertTrue(all(r["status"] == "PASS" for r in rows))
        self.assertEqual(rows[0]["draw_seed"], "260000")
        self.assertAlmostEqual(float(rows[2]["cmrr_db"]), AV0 - 6.0, places=4)
        p2, out2 = self.run_script(rec, out=self.rec_dir / "again.csv")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertEqual(out.read_bytes(), out2.read_bytes())

    def test_excluded_draw_visible(self):
        rec = self.build(bad_op=0)
        p, out = self.run_script(rec)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = list(csv.DictReader(open(out)))
        self.assertEqual(len(rows), N)
        self.assertEqual((rows[0]["status"], rows[0]["fail_reason"]), ("EXCLUDED", "op_fail"))

    def test_gate_disagreement_fails(self):
        # record says no exclusions, sample file has an op-window failure
        rec = self.build()
        (self.samples / "mos_tt_27C_1.20V_mc_samples.txt").write_text(sample_text(ACM, bad_op=0))
        p, out = self.run_script(rec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("ROUND-TRIP MISMATCH", p.stderr)
        self.assertFalse(out.exists())

    def test_tampered_draw_fails(self):
        rec = self.build()
        f = self.samples / "mos_tt_27C_1.20V_mc_samples.txt"
        f.write_text(f.read_text().replace("AC 1 5.0 5.0 4.999", "AC 1 7.0 7.0 6.999"))
        p, out = self.run_script(rec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("ROUND-TRIP MISMATCH", p.stderr)
        self.assertFalse(out.exists())

    def test_forged_summary_fails(self):
        for col, val in (("cmrr_db_min", "1"), ("acm_lin_sigma", "9.9"), ("mc_n_ok", "5")):
            rec = self.build(forge=(col, val))
            p, out = self.run_script(rec)
            self.assertEqual(p.returncode, 1, col)
            self.assertIn(col, p.stderr)
            self.assertFalse(out.exists())

    def test_truncated_samples_fail(self):
        rec = self.build()
        f = self.samples / "mos_tt_27C_1.20V_mc_samples.txt"
        lines = f.read_text().splitlines()
        f.write_text("\n".join(lines[:-1]) + "\n")  # drop the last AC line
        p, out = self.run_script(rec)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(out.exists())

    def test_refuses_overwrite(self):
        rec = self.build()
        p, out = self.run_script(rec)
        self.assertEqual(p.returncode, 0, p.stderr)
        before = out.read_bytes()
        p2, _ = self.run_script(rec)
        self.assertEqual(p2.returncode, 3)
        self.assertEqual(out.read_bytes(), before)

    def test_committed_record(self):
        out = self.root / "real-draws.csv"
        p = subprocess.run([str(SCRIPT), "--record-csv", str(REAL_RECORD), "--out", str(out)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = list(csv.DictReader(open(out)))
        self.assertEqual(len(rows), 13500)
        worst = min(rows, key=lambda r: float(r["cmrr_db"]))
        self.assertEqual(worst["point_id"], "mos_ss_-40C_1.08V")
        self.assertAlmostEqual(float(worst["cmrr_db"]), 25.94, places=2)
        committed = REAL_RECORD.with_name(REAL_RECORD.stem + "-draws.csv")
        self.assertEqual(out.read_bytes(), committed.read_bytes())


if __name__ == "__main__":
    unittest.main()

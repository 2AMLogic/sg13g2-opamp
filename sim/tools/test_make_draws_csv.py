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

    # --- strict sample validation (issue #174) -------------------------------
    def _invalid(self, mutate, needle):
        rec = self.build()
        f = self.samples / "mos_tt_27C_1.20V_mc_samples.txt"
        f.write_text(mutate(f.read_text()))
        p, out = self.run_script(rec)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("INVALID SAMPLES", p.stderr)
        self.assertIn("mos_tt_27C_1.20V_mc_samples.txt", p.stderr)
        self.assertIn(needle, p.stderr)
        self.assertFalse(out.exists())
        self.assertEqual(list(self.rec_dir.glob("*.tmp.*")), [])

    def test_nan_plateau_partner_fails(self):
        # only the 0.1 Hz partner (a01) is NaN; a10 stays finite
        self._invalid(lambda t: t.replace("AC 2 6.0 6.0 5.999", "AC 2 6.0 nan 5.999"),
                      "draw 2: non-finite value 'nan' in field acm01")

    def test_infinities_fail(self):
        for tok in ("inf", "-inf", "+Infinity", "1e999"):
            self._invalid(lambda t, tok=tok: t.replace("AC 2 6.0 6.0 5.999", f"AC 2 6.0 {tok} 5.999"),
                          "field acm01")
        self._invalid(lambda t: t.replace("OP 1 0.6 ", "OP 1 -inf "), "field vout")

    def test_malformed_tokens_fail(self):
        for bad in ("abc", "1.2.3", "0x10", "1_0", "5,0", "--1"):
            self._invalid(lambda t, bad=bad: t.replace("AC 3 4.5 4.5 4.499", f"AC 3 {bad} 4.5 4.499"),
                          "malformed numeric token")
        self._invalid(lambda t: t.replace("AC 3 ", "AC x3 "), "malformed draw index")

    def test_duplicate_indices_fail(self):
        self._invalid(lambda t: t + "AC 2 6.0 6.0 5.999\n", "duplicate AC record for draw 2")
        self._invalid(lambda t: t + "OP 2 0.6 0.6 0.45 0.15 0.38 0.0001\n",
                      "duplicate OP record for draw 2")

    def test_missing_pairs_fail(self):
        def drop(prefix):
            return lambda t: "".join(l for l in t.splitlines(True) if not l.startswith(prefix))
        self._invalid(drop("AC 4 "), "draw 4: missing AC")
        self._invalid(drop("OP 4 "), "draw 4: missing OP")
        self._invalid(lambda t: "", "empty sample file")

    def test_short_and_long_records_fail(self):
        self._invalid(lambda t: t.replace("AC 1 5.0 5.0 4.999", "AC 1 5.0 5.0"), "AC record has 4 tokens")
        self._invalid(lambda t: t.replace("OP 1 0.6 0.6 0.45 0.15 0.38 0.0001",
                                          "OP 1 0.6 0.6 0.45 0.15 0.38"), "OP record has 7 tokens")
        self._invalid(lambda t: t.replace("AC 1 5.0 5.0 4.999", "AC 1 5.0 5.0 4.999 9"),
                      "AC record has 6 tokens")

    def test_unknown_record_fails(self):
        self._invalid(lambda t: t + "XX 6 1 2 3\n", "unknown record type 'XX'")
        self._invalid(lambda t: t + "op 6 1 2 3\n", "unknown record type 'op'")

    def test_finite_excluded_plateau_unchanged(self):
        # finite plateau failure is still an exclusion, not a parse error
        rec = self.build()
        f = self.samples / "mos_tt_27C_1.20V_mc_samples.txt"
        f.write_text(f.read_text().replace("AC 2 6.0 6.0 5.999", "AC 2 6.0 7.0 5.999"))
        p, out = self.run_script(rec)
        self.assertEqual(p.returncode, 1)  # record says no exclusions -> round-trip mismatch
        self.assertIn("ROUND-TRIP MISMATCH", p.stderr)
        self.assertNotIn("INVALID SAMPLES", p.stderr)

    def test_campaign_shares_strict_parser(self):
        runner = (SIM_DIR / "cmrr-mismatch" / "run_cmrr_mismatch_mc.sh").read_text()
        conv = SCRIPT.read_text()
        for text in (runner, conv):
            self.assertIn("import mc_samples", text)
        self.assertIn("mc_samples.read_samples(file)", runner)
        self.assertIn("INVALID", runner)
        self.assertIn("read_samples_raw", conv)
        self.assertNotIn("ops[int(p[1])]", runner + conv)

    def test_campaign_stat_point_rejects_nan(self):
        # drive the runner's own extraction through the shared module directly
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mc_samples", SIM_DIR / "cmrr-mismatch" / "mc_samples.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        f = self.root / "s.txt"
        f.write_text(sample_text(ACM).replace("AC 0 4.0 4.0", "AC 0 4.0 nan"))
        with self.assertRaises(mod.SampleError):
            mod.read_samples(str(f))
        f.write_text(sample_text(ACM))
        n, ops, acs = mod.read_samples(str(f))
        self.assertEqual((n, acs[1]), (N, [5.0, 5.0, 4.999]))

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

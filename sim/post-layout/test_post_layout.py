"""Offline checks for sim/post-layout (no ngspice, no PDK needed).

  python3 -m unittest sim/post-layout/test_post_layout.py   (or run directly)
"""
import importlib.util
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ac, cb = load("ac_metrics"), load("check_bounds")


def write_point(d, pid, vdd, vout, gain_db=40.0, fp=1e4):
    """Single-pole + second pole at 10x GBW => known GBW and PM."""
    csv, log = os.path.join(d, pid + ".csv"), os.path.join(d, pid + ".log")
    gbw = gain_db_to_gbw(gain_db, fp)
    with open(csv, "w") as f:
        for i in range(0, 181):
            fr = 10 ** (i / 20)
            mag = 10 * 0 + gain_db - 10 * math.log10(1 + (fr / fp) ** 2) - 10 * math.log10(1 + (fr / (10 * gbw)) ** 2)
            ph = -math.degrees(math.atan(fr / fp)) - math.degrees(math.atan(fr / (10 * gbw)))
            f.write(f"{fr} {mag} {fr} {ph}\n")
    with open(log, "w") as f:
        f.write(f"OP_VOUT {vout}\nOP_IVDD 1e-4\n")
    return csv, log, gbw


def gain_db_to_gbw(gain_db, fp):
    return 10 ** (gain_db / 20) * fp


class AcMetrics(unittest.TestCase):
    def test_document(self):
        with tempfile.TemporaryDirectory() as d:
            csv, log, gbw = write_point(d, "p", 1.2, 0.6)
            tsv = os.path.join(d, "points.tsv")
            open(tsv, "w").write(f"p\tmos_tt\t27\t1.20\t{csv}\t{log}\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ac.main(tsv)
            doc = json.loads(buf.getvalue())
        c = doc["corners"][0]
        self.assertEqual(c["corner_id"], "mos_tt/1.20V/27C")
        m = {x["name"]: x["value"] for x in c["measurements"]}
        self.assertAlmostEqual(m["av0_db"], 40.0, delta=0.01)
        self.assertAlmostEqual(m["gbw_hz"] / gbw, 1.0, delta=0.03)
        self.assertTrue(40 < m["pm_deg"] < 90)
        self.assertEqual(m["iq_a"], 1e-4)

    def test_railed_point_is_loud(self):
        with tempfile.TemporaryDirectory() as d:
            csv, log, _ = write_point(d, "p", 1.2, 1.19)
            tsv = os.path.join(d, "points.tsv")
            open(tsv, "w").write(f"p\tmos_tt\t27\t1.20\t{csv}\t{log}\n")
            with self.assertRaises(SystemExit):
                ac.main(tsv)


def report(over=None):
    rows = []
    vals = {"av0_db": 45.0, "gbw_hz": 6e6, "pm_deg": 70.0, "iq_a": 1.0e-4}
    vals.update(over or {})
    for i in range(45):
        for n, v in vals.items():
            rows.append({"spec_row": n, "corner_id": f"c{i}", "extracted_value": v, "status": "pass"})
    return {"measurement": {"mode": "command"}, "delta": rows}


class Bounds(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(cb.grade(report())[0])

    def test_each_row_can_fail(self):
        for k, v in {"av0_db": 30.0, "gbw_hz": 1e6, "pm_deg": 50.0, "iq_a": 2e-4}.items():
            ok, lines = cb.grade(report({k: v}))
            self.assertFalse(ok, k)
            self.assertTrue(any("FAIL" in l and k in l for l in lines), k)

    def test_incomplete_report_fails(self):
        r = report(); r["delta"] = r["delta"][:10]
        self.assertFalse(cb.grade(r)[0])
        r = report(); r["measurement"]["mode"] = "testbench"
        self.assertFalse(cb.grade(r)[0])


if __name__ == "__main__":
    unittest.main()

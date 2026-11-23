"""Offline checks for sim/post-layout (no ngspice, no PDK needed).

  python3 -m unittest sim/post-layout/test_post_layout.py   (or run directly)
"""
import hashlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


km, cb = load("klt_measure"), load("check_bounds")


def corner(proc, vdd, temp, av0=45.0, gbw=6e6, phase_deg=-110.0, vout=None, iq=1e-4, status="pass"):
    vout = vdd / 2 if vout is None else vout
    return (
        {"corner_id": f"{proc}/vdd={vdd:.3f}_vinp={vdd/2:.3f}V/{temp}C", "process": proc,
         "supply_v": {"vdd": vdd, "vinp": vdd / 2}, "temperature_c": temp, "status": status,
         "measurements": [{"name": "av0_db", "value": av0}, {"name": "gbw_hz", "value": gbw},
                          {"name": "phase_at_ugf_rad", "value": math.radians(phase_deg)}]},
        {"corner_id": "x", "process": proc, "supply_v": {"vdd": vdd, "vinp": vdd / 2},
         "temperature_c": temp, "status": "pass",
         "measurements": [{"name": "ivdd_total_a", "value": iq}, {"name": "vout_dc_v", "value": vout}]},
    )


def convert(pairs, tmp):
    ac, op = os.path.join(tmp, "ac.json"), os.path.join(tmp, "op.json")
    json.dump({"corners": [p[0] for p in pairs]}, open(ac, "w"))
    json.dump({"corners": [p[1] for p in pairs]}, open(op, "w"))
    buf = io.StringIO()
    os.environ["KLT_MEASURE_EXPECTED_CORNERS"] = str(len(pairs))
    try:
        km.convert(ac, op, buf)
    finally:
        del os.environ["KLT_MEASURE_EXPECTED_CORNERS"]
    return json.loads(buf.getvalue())


class KltMeasure(unittest.TestCase):
    def test_document(self):
        with tempfile.TemporaryDirectory() as d:
            doc = convert([corner("mos_tt", 1.2, 27)], d)
        c = doc["corners"][0]
        self.assertEqual(c["corner_id"], "mos_tt/1.20V/27C")
        m = {x["name"]: x["value"] for x in c["measurements"]}
        self.assertEqual(m["av0_db"], 45.0)
        self.assertEqual(m["gbw_hz"], 6e6)
        self.assertAlmostEqual(m["pm_deg"], 70.0)
        self.assertEqual(m["iq_a"], 1e-4)

    def test_railed_point_is_loud(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            convert([corner("mos_tt", 1.2, 27, vout=1.19)], d)

    def test_errored_corner_is_loud(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            convert([corner("mos_tt", 1.2, 27, status="error")], d)

    def test_missing_value_is_loud(self):
        a, o = corner("mos_tt", 1.2, 27)
        a["measurements"][1]["value"] = None
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            convert([(a, o)], d)

    def test_count_mismatch_is_loud(self):
        with tempfile.TemporaryDirectory() as d:
            ac, op = os.path.join(d, "a.json"), os.path.join(d, "o.json")
            p = corner("mos_tt", 1.2, 27)
            json.dump({"corners": [p[0]]}, open(ac, "w"))
            json.dump({"corners": [p[1]]}, open(op, "w"))
            with self.assertRaises(SystemExit):  # 1 corner, full grid expected
                km.convert(ac, op, io.StringIO())

    def test_build_flat_and_subckt(self):
        with tempfile.TemporaryDirectory() as d:
            flat = os.path.join(d, "flat.spice")
            open(flat, "w").write("* flat\nM1 a b c d x\n")
            km.build(flat, os.path.join(d, "f"))
            body = open(os.path.join(d, "f", "tb_openloop_ac.body.spice")).read()
            self.assertIn(f'.include "{flat}"', body)
            self.assertNotIn("Xdut", body)
            sub = os.path.join(d, "sub.spice")
            open(sub, "w").write(".SUBCKT opamp_core VDD VSS INN INP OUT IBIAS\n.ENDS\n")
            km.build(sub, os.path.join(d, "s"))
            body = open(os.path.join(d, "s", "tb_openloop_ac.body.spice")).read()
            self.assertIn("Xdut vdd vss inn inp out ibias opamp_core", body)
            op = json.load(open(os.path.join(d, "s", "openloop_op.request.json")))
            self.assertFalse(any("d1" in m["expr"] or "tail" in m["expr"] for m in op["measurements"]))
            ac = json.load(open(os.path.join(d, "s", "openloop_ac.request.json")))
            self.assertEqual(len(ac["corners"]["process"]) * len(ac["corners"]["temperature_c"])
                             * len(ac["corners"]["supply_v"]["vdd"]), 45)

    def test_subckt_missing_pin_is_loud(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "sub.spice")
            open(sub, "w").write(".SUBCKT opamp_core VDD VSS INN INP OUT\n.ENDS\n")
            with self.assertRaises(SystemExit):
                km.build(sub, os.path.join(d, "s"))

    def test_build_reports_a_path_independent_deck_digest_and_unchanged_files(self):
        """klt's content_hash embeds the DUT path, so it differs per checkout;
        deck_content_sha256 must not, and the written files must not change.
        One DUT path carries regex metacharacters on purpose."""
        subckt = ".SUBCKT opamp_core VDD VSS INN INP OUT IBIAS\nM1 a b c d x\n.ENDS\n"
        reqs = ("openloop_ac.request.json", "openloop_op.request.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, \
                mock.patch.dict(os.environ):
            os.environ.pop("SG13G2_PEX_POINTS", None)
            os.environ.pop("KLT_PEX_SIM_BACKEND", None)
            dut_a = os.path.join(a, "pex[1](v2).spice")
            dut_b = os.path.join(b, "nested", "deeper", "pex.spice")
            os.makedirs(os.path.dirname(dut_b))
            for dut in (dut_a, dut_b):
                open(dut, "w").write(subckt)
            s_a = km.build(dut_a, os.path.join(a, "art"))
            s_b = km.build(dut_b, os.path.join(b, "elsewhere", "art"))
            for fname in reqs:
                self.assertEqual(open(os.path.join(a, "art", fname), "rb").read(),
                                 open(os.path.join(b, "elsewhere", "art", fname), "rb").read())
            committed = json.load(open(os.path.join(km.KLT_DIR, "openloop_ac.request.json")))
            committed.pop("_comment")
            committed["netlist"] = "tb_openloop_ac.body.spice"
            self.assertEqual(json.load(open(os.path.join(a, "art", reqs[0]))), committed)

            self.assertEqual(set(s_a), {"netlist", "netlist_sha256", "deck_content_sha256",
                                        "dut", "dut_sha256", "requests"})
            self.assertEqual(s_a["requests"], [os.path.join(a, "art", f) for f in reqs])
            self.assertEqual((s_a["netlist"], s_a["dut"]),
                             (os.path.join(a, "art", "tb_openloop_ac.body.spice"), dut_a))
            self.assertEqual(s_a["deck_content_sha256"], s_b["deck_content_sha256"])
            self.assertNotEqual(s_a["netlist_sha256"], s_b["netlist_sha256"])
            self.assertEqual(s_a["dut_sha256"], s_b["dut_sha256"])
            body_a, body_b = open(s_a["netlist"]).read(), open(s_b["netlist"]).read()
            for s, body in ((s_a, body_a), (s_b, body_b)):
                self.assertIn(f'\n.include "{s["dut"]}"\nXdut vdd vss inn inp out ibias opamp_core\n',
                              body)
                self.assertEqual(s["netlist_sha256"],
                                 hashlib.sha256(open(s["netlist"], "rb").read()).hexdigest())
                self.assertEqual(s["dut_sha256"],
                                 hashlib.sha256(open(s["dut"], "rb").read()).hexdigest())
                self.assertEqual(s["deck_content_sha256"], km.deck_content_sha256(body, s["dut"]))
                token = f'.include "<DUT:{s["dut_sha256"]}>"'
                self.assertEqual(s["deck_content_sha256"], hashlib.sha256(
                    body.replace(f'.include "{s["dut"]}"', token).encode()).hexdigest())
            self.assertEqual(body_a.replace(f'.include "{dut_a}"', ".include DUT"),
                             body_b.replace(f'.include "{dut_b}"', ".include DUT"))

    def test_deck_content_sha256_covers_a_flat_dut_and_tracks_content(self):
        flat = "* flat\nM1 a b c d x\n"
        with tempfile.TemporaryDirectory() as d:
            dut = os.path.join(d, "flat.spice")
            open(dut, "w").write(flat)
            s = km.build(dut, os.path.join(d, "art"))
            body = open(s["netlist"]).read()
            self.assertNotIn("Xdut", body)
            self.assertEqual(s["deck_content_sha256"], km.deck_content_sha256(body, dut))
            open(dut, "a").write("M2 a b c d x\n")
            s_dut = km.build(dut, os.path.join(d, "art-dut"))
            bench = tempfile.mkdtemp()
            try:
                shutil.copytree(km.KLT_DIR, bench, dirs_exist_ok=True)
                path = os.path.join(bench, "tb_openloop_ac.body.spice")
                text = open(path).read()
                open(path, "w").write(text.replace("Cload out vss 2e-12", "Cload out vss 1e-12"))
                saved = km.KLT_DIR
                km.KLT_DIR = bench
                try:
                    s_bench = km.build(dut, os.path.join(d, "art-bench"))
                finally:
                    km.KLT_DIR = saved
            finally:
                shutil.rmtree(bench)
        self.assertEqual(len({s["deck_content_sha256"], s_dut["deck_content_sha256"],
                              s_bench["deck_content_sha256"]}), 3)

    def test_deck_content_sha256_is_loud_without_exactly_one_dut_include(self):
        with tempfile.TemporaryDirectory() as d:
            dut = os.path.join(d, "dut.spice")
            open(dut, "w").write("M1 a b c d x\n")
            inc = f'.include "{dut}"'
            for text in ("* no include\n", f"{inc}\n{inc}\n", f'.include "{dut}.bak"\n', f"  {inc}\n"):
                with self.assertRaises(SystemExit, msg=text):
                    km.deck_content_sha256(text, dut)


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

"""Offline checks for sim/post-layout/rz_screen.py (no ngspice, no PDK, no klt).

  python3 -m unittest sim/post-layout/test_rz_screen.py   (or run directly)
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


km, rz = load("klt_measure"), load("rz_screen")


def read(path):
    with open(path) as f:
        return f.read()


def load_json(path):
    with open(path) as f:
        return json.load(f)

# The shape of a `klt pex` extraction, cut down to one MOS unit, the Miller
# capacitor and four parasitic cards (star resistor, coupling capacitor,
# substrate tie). Node names follow the extractor: `out__t1` is the `out`
# hub's first terminal, `\$6` the internal d2 net.
EXTRACTED = """* extracted by klt extract --deck sg13g2
.GLOBAL vsubs

* cell opamp_core
.SUBCKT opamp_core ibias inn inp out vdd vss
* device instance $28 r0 *1 36.4,24.515 pfet
X$28 out__t4 \\$6__t6 vdd__t27 vdd__t9 sg13_lv_pmos L=1.04U W=2.75U AS=0.5775P
+ AD=0.5775P PS=3.17U PD=3.17U
* device instance $32 r0 *1 59.45,15.45 cap_cmim
X$32 out__t1 \\$6__t3 cap_cmim l=25.7U w=25.7U
* device instance out_t1 r0 *1 0,0 
Rout_t1 out__t1 out 3.23993663293
* device instance $6_t3 r0 *1 0,0 
R_6_t3 \\$6__t3 \\$6 4.54352735021
* device instance cc__6_out r0 *1 0,0 
Ccc__6_out \\$6 out 4.2025e-17
* device instance vsubs_dctie r0 *1 0,0 
Rvsubs_dctie vsubs 0 1e+12
.ENDS opamp_core
"""
CAP_LINE = "X$32 out__t1 \\$6__t3 cap_cmim l=25.7U w=25.7U"
RZ_LINE = "Rz_cc cc_rz \\$6__t3 2000"
NEW_CAP_LINE = "X$32 out__t1 cc_rz cap_cmim l=25.7U w=25.7U"


def derive(text=EXTRACTED, ohms=2000.0, is_bare=False, side=None):
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "src.spice"), os.path.join(d, "dst.spice")
        open(src, "w").write(text)
        summary = rz.dut(src, dst, ohms, is_bare, side)
        return read(dst).split("\n"), summary


def committed_slew():
    return load_json(os.path.join(rz.SLEW_DIR, "slew.request.json"))


class Env:
    """Set SG13G2_PEX_POINTS / KLT_PEX_SIM_BACKEND for a block, restore after."""

    def __init__(self, points=None, backend=None):
        self.values = {"SG13G2_PEX_POINTS": points, "KLT_PEX_SIM_BACKEND": backend}

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in self.values}
        for k, v in self.values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def slew_for(text, points=None, backend=None):
    with Env(points, backend), tempfile.TemporaryDirectory() as d:
        dut = os.path.join(d, "dut.spice")
        open(dut, "w").write(text)
        art = os.path.join(d, "art")
        summary = rz.slew_build(dut, art)
        return (summary, read(os.path.join(art, "tb_slew.body.spice")),
                load_json(os.path.join(art, "slew.request.json")), rz.sha256_file(dut))


class Dut(unittest.TestCase):
    def test_inserts_rz_on_the_d2_plate_only(self):
        lines, summary = derive()
        self.assertIn(NEW_CAP_LINE, lines)
        self.assertIn(RZ_LINE, lines)
        self.assertEqual(lines.index(RZ_LINE), lines.index(NEW_CAP_LINE) + 1)
        changed = (NEW_CAP_LINE, RZ_LINE)
        self.assertEqual([l for l in lines if l not in changed],
                         [l for l in EXTRACTED.split("\n") if l != CAP_LINE])
        self.assertEqual(summary["d2_terminal"], "\\$6__t3")
        self.assertEqual(summary["out_terminal"], "out__t1")
        self.assertEqual(summary["rz_card"], RZ_LINE)
        self.assertEqual(summary["rz_ohms"], 2000.0)
        self.assertFalse(summary["bare"])
        self.assertIsNone(summary["cap_side_um"])

    def test_rz_follows_the_cap_card_continuation_lines(self):
        lines, _ = derive(EXTRACTED.replace("cap_cmim l=25.7U w=25.7U", "cap_cmim l=25.7U\n+ w=25.7U"))
        i = lines.index("X$32 out__t1 cc_rz cap_cmim l=25.7U")
        self.assertEqual(lines[i + 1], "+ w=25.7U")
        self.assertEqual(lines[i + 2], RZ_LINE)

    def test_bare_strips_parasitics_and_collapses_terminal_nodes(self):
        lines, summary = derive(is_bare=True)
        self.assertEqual([l for l in lines if l and not l.startswith(("*", "+", "."))], [
            "X$28 out \\$6 vdd vdd sg13_lv_pmos L=1.04U W=2.75U AS=0.5775P",
            "X$32 out cc_rz cap_cmim l=25.7U w=25.7U",
            "Rz_cc cc_rz \\$6 2000",
        ])
        self.assertNotIn("__t", "\n".join(lines))
        self.assertIn("+ AD=0.5775P PS=3.17U PD=3.17U", lines)
        self.assertIn("* device instance out_t1 r0 *1 0,0 ", lines)
        self.assertTrue(summary["bare"])
        self.assertEqual(summary["d2_terminal"], "\\$6")

    def test_cap_side_rewrites_l_and_w(self):
        lines, summary = derive(side=25.3)
        self.assertIn("X$32 out__t1 cc_rz cap_cmim l=25.3U w=25.3U", lines)
        self.assertEqual(summary["cap_card_before"], CAP_LINE)
        self.assertEqual(summary["cap_side_um"], 25.3)

    def test_resistance_bounds(self):
        for ohms in (0.0, 1e-9, -100.0, float("nan"), float("inf")):
            with self.assertRaises(SystemExit):
                rz.insert_rz(EXTRACTED, ohms)
        for ohms in (rz.MIN_OHMS, 0.1, 1.0, 2000.0):
            new, _ = rz.insert_rz(EXTRACTED, ohms)
            self.assertIn(f"Rz_cc cc_rz \\$6__t3 {ohms:g}", new.split("\n"))

    def test_loud_shapes(self):
        edits = {
            "no cap card": EXTRACTED.replace("cap_cmim", "cap_other"),
            "two cap cards": EXTRACTED.replace(".ENDS opamp_core",
                                               "X$33 a b cap_cmim l=1U w=1U\n.ENDS opamp_core"),
            "cap not on out": EXTRACTED.replace("X$32 out__t1", "X$32 inn__t0"),
            "both plates on out": EXTRACTED.replace("X$32 out__t1 \\$6__t3", "X$32 out__t1 out__t2"),
            "cap card without l=/w= for a resize": EXTRACTED.replace(" l=25.7U w=25.7U", ""),
        }
        for label, text in edits.items():
            with self.assertRaises(SystemExit, msg=label):
                rz.insert_rz(text, 2000.0, 25.3 if "l=/w=" in label else None)
        with self.assertRaises(SystemExit):
            rz.insert_rz(EXTRACTED, 2000.0, 0.0)
        with self.assertRaises(SystemExit):
            rz.insert_rz(EXTRACTED, 2000.0, float("nan"))

    def test_bare_is_loud(self):
        no_parasitics = EXTRACTED
        for card in ("Rout_t1 out__t1 out 3.23993663293", "R_6_t3 \\$6__t3 \\$6 4.54352735021",
                     "Ccc__6_out \\$6 out 4.2025e-17", "Rvsubs_dctie vsubs 0 1e+12"):
            no_parasitics = no_parasitics.replace(card + "\n", "")
        with self.assertRaises(SystemExit):
            rz.bare(no_parasitics)
        for odd_node in ("a__tx", "a__t"):
            survivor = EXTRACTED.replace(".ENDS opamp_core", f"Xkeep {odd_node} b c cap_other\n.ENDS opamp_core")
            with self.assertRaises(SystemExit, msg=odd_node):
                rz.bare(survivor)

    def test_main_prints_the_summary_and_writes_the_dut(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "s.spice"), os.path.join(d, "d.spice")
            open(src, "w").write(EXTRACTED)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = rz.main(["dut", src, dst, "--rz", "1500", "--cap-side", "25"])
            self.assertEqual(rc, 0)
            summary = json.loads(out.getvalue())
            written = rz.sha256_file(dst)
        self.assertEqual(summary["rz_card"], "Rz_cc cc_rz \\$6__t3 1500")
        self.assertEqual(summary["cap_card"], "X$32 out__t1 cc_rz cap_cmim l=25U w=25U")
        self.assertEqual(summary["sha256"], written)
        with self.assertRaises(SystemExit):
            rz.main(["dut", "/nonexistent", "/tmp/loom-430-rz/never-written.spice", "--rz", "1500"])


class SlewBuild(unittest.TestCase):
    def test_subckt_dut_drops_only_the_internal_node_readings(self):
        summary, body, req, dut_sha = slew_for(EXTRACTED, "mos_ss:-40:1.08", "batch")
        committed = committed_slew()
        self.assertIn('\n.include "' + summary["dut"] + '"\nXdut ibias inn inp out vdd vss opamp_core\n', body)
        for source in rz.INTERNAL_SOURCES:
            self.assertNotIn("\n" + source + " ", body)
        self.assertNotIn("opamp_core.spice", body)
        self.assertIn("Borel orel 0 v=v(out)-v(vdd)/2", body)
        self.assertIn("Cload out vss 2e-12", body)
        internal = ("vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "op_vd1_rail_frac",
                    "op_vd2_rail_frac", "op_vtail_rail_frac")
        self.assertEqual(req["measurements"],
                         [m for m in committed["measurements"] if m["name"] not in internal])
        self.assertEqual((len(req["measurements"]), summary["measurements"]), (20, 20))
        for key in ("analysis", "engine", "models", "options", "netlist_source"):
            self.assertEqual(req[key], committed[key], key)
        self.assertNotIn("_comment", req)
        self.assertEqual(req["netlist"], "tb_slew.body.spice")
        self.assertEqual(req["corners"], {"process": [committed["corners"]["process"][1]],
                                          "supply_v": {"vdd": [1.08], "vinp": [0.54]},
                                          "temperature_c": [-40]})
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["batch"], {"capacity_wait_s": 600})
        self.assertEqual((summary["corners"], summary["backend"]), (1, "batch"))
        self.assertEqual(summary["dut_sha256"], dut_sha)

    def test_flat_dut_is_included_without_an_instance(self):
        summary, body, req, _ = slew_for("* flat\nM1 a b c d x\n", "mos_tt:27:1.20")
        self.assertNotIn("Xdut", body)
        self.assertEqual(summary["corners"], 1)
        self.assertEqual(req["corners"], {"process": [committed_slew()["corners"]["process"][0]],
                                          "supply_v": {"vdd": [1.2], "vinp": [0.6]},
                                          "temperature_c": [27]})
        self.assertEqual(req["batch"], {"capacity_wait_s": 600})

    def test_full_grid_and_no_backend_override(self):
        summary, _, req, _ = slew_for(EXTRACTED)
        self.assertIsNone(summary["corners"])
        self.assertEqual(len(req["corners"]["process"]) * len(req["corners"]["supply_v"]["vdd"])
                         * len(req["corners"]["temperature_c"]), 45)
        self.assertEqual(req["corners"], committed_slew()["corners"])
        local = slew_for(EXTRACTED, None, "local")[2]
        self.assertEqual((local["backend"], "batch" in local), ("local", False))

    def test_point_filter_matches_the_ac_generator(self):
        for points in ("mos_ff:125:1.32", "mos_ss:-40:1.08", "mos_tt:27:1.20 mos_fs:27:1.08",
                       "mos_sf:27:1.08 mos_sf:-40:1.32"):
            with Env(points, "batch"), tempfile.TemporaryDirectory() as d:
                dut = os.path.join(d, "dut.spice")
                open(dut, "w").write(EXTRACTED)
                km.build(dut, os.path.join(d, "ac"))
                ac = load_json(os.path.join(d, "ac", "openloop_ac.request.json"))
            slew = slew_for(EXTRACTED, points, "batch")[2]
            self.assertEqual(slew["corners"], ac["corners"], points)
            self.assertEqual(slew["batch"], {"capacity_wait_s": 600})

    def test_loud_inputs(self):
        with self.assertRaises(SystemExit):
            slew_for(".SUBCKT opamp_core ibias inn inp out vdd\n.ENDS\n", "mos_tt:27:1.08")
        with self.assertRaises(SystemExit):
            slew_for(EXTRACTED, "mos_xx:27:1.08")
        with self.assertRaises(SystemExit):
            slew_for(EXTRACTED, "mos_tt:27:9.99")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                rz.slew_build(os.path.join(d, "missing.spice"), os.path.join(d, "art"))

    def test_bench_without_the_internal_sources_is_loud(self):
        saved = rz.SLEW_DIR
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(saved, d, dirs_exist_ok=True)
            body_path = os.path.join(d, "tb_slew.body.spice")
            open(body_path, "w").write(read(body_path).replace(
                "Bftail ftail 0 v=v(tail)/v(vdd)\n", ""))
            rz.SLEW_DIR = d
            try:
                with self.assertRaises(SystemExit):
                    slew_for(EXTRACTED, "mos_tt:27:1.08")
            finally:
                rz.SLEW_DIR = saved
        self.assertIn("Bftail ftail 0 v=v(tail)/v(vdd)", read(os.path.join(saved, "tb_slew.body.spice")))


class Restrict(unittest.TestCase):
    def test_keeps_the_paired_supply_by_index_and_touches_nothing_else(self):
        req = committed_slew()
        before = copy.deepcopy(req)
        n = rz.restrict(req, "mos_fs:125:1.08 mos_tt:125:1.08")
        self.assertEqual(n, 2)
        self.assertEqual(req["corners"], {"process": [before["corners"]["process"][0], before["corners"]["process"][4]],
                                          "supply_v": {"vdd": [1.08], "vinp": [0.54]},
                                          "temperature_c": [125]})
        self.assertEqual({k: v for k, v in req.items() if k != "corners"},
                         {k: v for k, v in before.items() if k != "corners"})


if __name__ == "__main__":
    unittest.main()

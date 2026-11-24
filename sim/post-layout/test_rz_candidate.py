"""Offline checks for sim/post-layout/rz_candidate.py (no ngspice, no PDK, no klt).

  python3 -m unittest sim/post-layout/test_rz_candidate.py   (or run directly)
"""
import contextlib
import hashlib
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


rc = load("rz_candidate")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def deck_body_path(entry):
    name = "tb_slew.body.spice" if entry["kind"] == "slew" else "tb_openloop_ac.body.spice"
    return os.path.join(os.path.dirname(entry["request"]), name)


def canonical_deck_digest(body, dut):
    with open(dut, "rb") as f:
        dut_sha256 = hashlib.sha256(f.read()).hexdigest()
    token = f'.include "<DUT:{dut_sha256}>"'
    return hashlib.sha256(body.replace(f'.include "{dut}"', token).encode("utf-8")).hexdigest()


# The shape of the klt 0.9.0 extraction of the drawn candidate, cut down to
# the Miller capacitor, the nulling resistor and one star resistor per net.
EXTRACTED = """* extracted by klt extract --deck sg13g2
.GLOBAL vsubs

* cell opamp_core
.SUBCKT opamp_core ibias inn inp out vdd vss
* device instance $38 r0 *1 59.15,15.15 cap_cmim
X$38 out__t1 \\$8__t0 cap_cmim l=25.3U w=25.3U
* device instance $39 r0 *1 64.655,29.4 rppd
X$39 \\$5__t4 \\$8__t1 vss__t23 rppd l=7.47U w=1U
* device instance _5_t4 r0 *1 0,0
R_5_t4 \\$5__t4 \\$5 5.21860256368
* device instance _8_t1 r0 *1 0,0
R_8_t1 \\$8__t1 \\$8 1.57225
* device instance vsubs_dctie r0 *1 0,0
Rvsubs_dctie vsubs 0 1e+12
.ENDS opamp_core
"""
SCHEMATIC = """** sch_path: /x/design/opamp_core.sch
XM1 d1 inn tail vss sg13_lv_nmos w=3.2u l=0.13u ng=1 m=1
XCc out cc_rz cap_cmim w=25.3u l=25.3u m=1
XRz cc_rz d2 vss rppd w=1u l=7.47u m=1 b=0
.end
"""
BENCH_NAMES = (
    ["cand_ff", "cand_fs", "cand_sf", "cand_tt", "cand_ss_slew", "grid_ac", "grid_op", "grid_slew"]
    + [f"pass_{p}_{r}_{c}" for p in ("ff", "fs", "tt27")
       for r in rc.RES_SECTIONS for c in rc.CAP_SECTIONS]
    + [f"pass_ss_{r}_{c}_slew" for r in rc.RES_SECTIONS for c in rc.CAP_SECTIONS]
)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dut = os.path.join(self.tmp, "pex.spice")
        self.sch = os.path.join(self.tmp, "opamp_core.spice")
        with open(self.dut, "w") as f:
            f.write(EXTRACTED)
        with open(self.sch, "w") as f:
            f.write(SCHEMATIC)
        os.environ.pop("SG13G2_PEX_POINTS", None)
        self.addCleanup(os.environ.pop, "SG13G2_PEX_POINTS", None)

    def req(self, entry):
        return load_json(entry["request"])


class PassivesTest(unittest.TestCase):
    def base(self):
        return {"corners": {"process": [
            {"name": "mos_ff", "sections": ["mos_ff",
                                            {"lib": rc.CAP_LIB, "section": "cap_typ"},
                                            {"lib": rc.RES_LIB, "section": "res_typ"}]},
            {"name": "mos_ss", "sections": ["mos_ss",
                                            {"lib": rc.CAP_LIB, "section": "cap_typ"},
                                            {"lib": rc.RES_LIB, "section": "res_typ"}]},
        ]}}

    def test_rewrites_both_sections_in_every_process(self):
        req = self.base()
        self.assertEqual(rc.set_passives(req, "res_wcs", "cap_bcs"), 4)
        for proc in req["corners"]["process"]:
            self.assertEqual(proc["sections"][0], proc["name"])
            self.assertEqual(proc["sections"][1]["section"], "cap_bcs")
            self.assertEqual(proc["sections"][2]["section"], "res_wcs")
            self.assertEqual(proc["sections"][1]["lib"], rc.CAP_LIB)

    def test_does_not_mutate_the_source_sections(self):
        req = self.base()
        before = json.loads(json.dumps(req))
        rc.set_passives(req, "res_bcs", "cap_wcs")
        self.assertEqual(req["corners"]["process"][0]["sections"][1]["lib"], before["corners"]["process"][0]["sections"][1]["lib"])


class RewritesTest(unittest.TestCase):
    def test_gear_follows_the_last_options_line(self):
        body = "* head\n.options tnom=27 interp\nR1 a 0 1\n.control\n"
        out = rc.insert_gear(body)
        self.assertEqual(out.split("\n")[2], rc.GEAR)
        self.assertEqual(out.count(rc.GEAR), 1)
        self.assertEqual(out.split("\n")[1], ".options tnom=27 interp")

    def test_gear_needs_an_options_line(self):
        with self.assertRaises(ValueError):
            rc.insert_gear("R1 a 0 1\n")

    def test_ideal_swap_replaces_the_single_rppd_card(self):
        out = rc.ideal_swap(EXTRACTED)
        self.assertIn("Rz_cc \\$5__t4 \\$8__t1 2000.6\n", out)
        self.assertFalse([l for l in out.split("\n") if "rppd" in l and not l.startswith("*")])
        self.assertIn("X$38 out__t1 \\$8__t0 cap_cmim l=25.3U w=25.3U", out)

    def test_ideal_swap_refuses_without_exactly_one_card(self):
        for text in (EXTRACTED.replace(" rppd ", " rsil "), EXTRACTED + "X$40 a b c rppd l=1U w=1U\n"):
            with self.assertRaises(SystemExit):
                rc.ideal_swap(text)


class BenchTest(Scratch):
    def test_builds_the_44_recorded_legs(self):
        out = os.path.join(self.tmp, "bench")
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = rc.bench(self.dut, out)
        self.assertEqual(sorted(m["name"] for m in manifest), sorted(BENCH_NAMES))
        by = {m["name"]: m for m in manifest}
        self.assertEqual(by["cand_ff"]["point"], "mos_ff:125:1.32")
        self.assertEqual(by["cand_ss_slew"]["point"], "mos_ss:-40:1.08")
        self.assertEqual(by["pass_tt27_res_bcs_cap_wcs"]["point"], "mos_tt:27:1.20")
        for name in BENCH_NAMES:
            self.assertEqual(by[name]["corners"], 45 if name.startswith("grid_") else 1, name)
        self.assertEqual(len(load_json(os.path.join(out, "manifest.json"))), 44)

    def test_single_corner_requests_restricted_and_unflagged(self):
        out = os.path.join(self.tmp, "bench")
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = rc.bench(self.dut, out)
        for entry in manifest:
            req = self.req(entry)
            cs = req["corners"]
            if entry["point"]:
                proc, temp, vdd = entry["point"].split(":")
                self.assertEqual([p["name"] for p in cs["process"]], [proc], entry["name"])
                self.assertEqual(cs["temperature_c"], [float(temp)], entry["name"])
                self.assertEqual(cs["supply_v"]["vdd"], [float(vdd)], entry["name"])
            self.assertEqual(req["backend"], "batch")
            self.assertEqual(req["batch"]["capacity_wait_s"], 600)
            self.assertNotIn("_comment", req)

    def test_passive_legs_cover_nine_combinations_at_each_binding_point(self):
        out = os.path.join(self.tmp, "bench")
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = rc.bench(self.dut, out)
        for entry in manifest:
            req = self.req(entry)
            sections = req["corners"]["process"][0]["sections"]
            want_cap = entry["cap"] or "cap_typ"
            want_res = entry["res"] or "res_typ"
            self.assertEqual((sections[1]["section"], sections[2]["section"]), (want_cap, want_res), entry["name"])
            self.assertEqual(entry["passive_sections_rewritten"], 2 if entry["res"] else 0)
        passive = [e for e in manifest if e["res"]]
        self.assertEqual(len(passive), 36)
        self.assertEqual({(e["res"], e["cap"]) for e in passive},
                         {(r, c) for r in rc.RES_SECTIONS for c in rc.CAP_SECTIONS})

    def test_grids_keep_the_standing_typical_passives(self):
        out = os.path.join(self.tmp, "bench")
        with contextlib.redirect_stdout(io.StringIO()):
            rc.bench(self.dut, out)
        req = load_json(os.path.join(out, "grid_slew", "grid_slew.request.json"))
        self.assertEqual(len(req["corners"]["process"]), 5)
        self.assertEqual({(s["lib"], s["section"]) for p in req["corners"]["process"] for s in p["sections"][1:]},
                         {(rc.CAP_LIB, "cap_typ"), (rc.RES_LIB, "res_typ")})
        self.assertEqual(len(req["measurements"]), 20)

    def test_every_leg_records_the_digest_of_the_deck_it_built(self):
        out = os.path.join(self.tmp, "bench")
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = rc.bench(self.dut, out)
        for entry in manifest:
            body = open(deck_body_path(entry)).read()
            self.assertEqual(len(entry["deck_content_sha256"]), 64, entry["name"])
            self.assertEqual(entry["deck_content_sha256"], canonical_deck_digest(body, self.dut), entry["name"])
            self.assertEqual(entry["deck_content_sha256"], rc.km.deck_content_sha256(body, self.dut), entry["name"])

    def test_digest_tracks_the_deck_and_not_the_request(self):
        out = os.path.join(self.tmp, "bench")
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = rc.bench(self.dut, out)
        open_loop = {e["deck_content_sha256"] for e in manifest if e["kind"] in ("ac", "op")}
        slew = {e["deck_content_sha256"] for e in manifest if e["kind"] == "slew"}
        self.assertEqual((len(open_loop), len(slew)), (1, 1))
        self.assertNotEqual(open_loop, slew)
        self.assertGreater(len({e["request_sha256"] for e in manifest}), 2)

    def test_digest_is_path_independent_while_body_sha256_is_not(self):
        elsewhere = os.path.join(self.tmp, "elsewhere", "nested", "pex.spice")
        os.makedirs(os.path.dirname(elsewhere))
        shutil.copy(self.dut, elsewhere)
        with contextlib.redirect_stdout(io.StringIO()):
            here = {e["name"]: e for e in rc.bench(self.dut, os.path.join(self.tmp, "a"))}
            there = {e["name"]: e for e in rc.bench(elsewhere, os.path.join(self.tmp, "b"))}
        self.assertEqual(sorted(here), sorted(there))
        for name, entry in here.items():
            self.assertEqual(entry["deck_content_sha256"], there[name]["deck_content_sha256"], name)
            self.assertEqual(entry["request_sha256"], there[name]["request_sha256"], name)
            if "body_sha256" in entry:
                self.assertEqual(entry["dut_sha256"], there[name]["dut_sha256"], name)
                self.assertNotEqual(entry["body_sha256"], there[name]["body_sha256"], name)


class ControlTest(Scratch):
    def build(self):
        out = os.path.join(self.tmp, "ctl")
        with contextlib.redirect_stdout(io.StringIO()):
            return rc.control(self.dut, self.sch, out), out

    def test_control_comment_is_set_only_on_the_gear_ideal_and_schematic_single_legs(self):
        manifest, out = self.build()
        self.assertEqual(len(manifest), 35)
        names = [m["name"] for m in manifest]
        self.assertIn("ctl_ideal_ss_slew", names)
        self.assertIn("ctl_sch_grid_slew", names)
        self.assertIn("ctl_gear_grid_slew", names)
        self.assertIn("ctl_bodyhub_ss_res_typ_cap_typ_slew", names)
        self.assertIn("probe_r_gear", names)
        for entry in manifest:
            if entry["kind"] == "probe":
                continue
            req = self.req(entry)
            self.assertEqual(req["backend"], "batch")
            body = open(os.path.join(os.path.dirname(entry["request"]), "tb_slew.body.spice")).read()
            self.assertEqual(rc.GEAR in body, entry["gear"], entry["name"])
            if entry["gear"] or entry["name"] in ("ctl_ideal_ss_slew", "ctl_sch_ss_slew"):
                self.assertTrue(req["_comment"].startswith("issue #430 CONTROL"), entry["name"])
            else:
                self.assertNotIn("_comment", req, entry["name"])

    def test_ideal_leg_drops_the_model_and_schematic_legs_use_the_schematic(self):
        manifest, out = self.build()
        by = {m["name"]: m for m in manifest}
        ideal = load_json(os.path.join(out, "manifest.json"))
        entry = next(m for m in ideal if m["name"] == "ctl_ideal_ss_slew")
        text = open(entry["dut"]).read()
        self.assertFalse([l for l in text.split("\n") if "rppd" in l and not l.startswith("*")])
        self.assertIn("Rz_cc \\$5__t4 \\$8__t1 2000.6", text)
        self.assertEqual(entry["swap"], "rppd card -> ideal resistor, 2000.6 ohm")
        for name in ("ctl_sch_ss_slew", "ctl_sch_grid_slew", "ctl_sch_ss_res_bcs_cap_typ_slew"):
            self.assertEqual(by[name]["dut_sha256"], rc.sha256_file(self.sch), name)
        self.assertEqual(by["ctl_gear_ss_slew"]["dut_sha256"], rc.sha256_file(self.dut))

    def test_variants_rewrite_the_card_the_way_the_record_describes(self):
        manifest, out = self.build()
        by = {m["name"]: m for m in manifest}
        swet = open(by["ctl_swet1_ss_res_typ_cap_typ_slew"]["dut"]).read()
        self.assertIn("X$39 \\$5__t4 \\$8__t1 vss__t23 rppd l=7.47U w=1U sw_et=1\n", swet)
        hub = open(by["ctl_bodyhub_ss_res_typ_cap_typ_slew"]["dut"]).read()
        self.assertIn("X$39 \\$5__t4 \\$8__t1 vss rppd l=7.47U w=1U\n", hub)
        self.assertNotIn("vss__t23", hub)
        self.assertEqual(sum(1 for n in by if n.startswith("ctl_swet1_")), 9)
        self.assertEqual(sum(1 for n in by if n.startswith("ctl_bodyhub_")), 1)

    def test_probe_is_the_model_alone_on_the_binding_slew_corner(self):
        manifest, out = self.build()
        by = {m["name"]: m for m in manifest}
        for name, gear in (("probe_r_default", False), ("probe_r_gear", True)):
            req = self.req(by[name])
            self.assertEqual(by[name]["corners"], 1)
            self.assertEqual(req["corners"]["process"][0]["name"], "mos_ss")
            self.assertEqual(req["corners"]["temperature_c"], [-40])
            self.assertEqual([m["name"] for m in req["measurements"]], ["vout_final_v", "t_10_90_s"])
            body = open(os.path.join(os.path.dirname(by[name]["request"]), "probe.body.spice")).read()
            self.assertIn("XR1 in out 0 rppd l=7.47u w=1u", body)
            self.assertEqual((rc.GEAR + "\n") in body, gear)

    def test_every_dut_leg_records_a_digest_and_the_probes_record_none(self):
        manifest, out = self.build()
        for entry in manifest:
            if entry["kind"] == "probe":
                self.assertNotIn("deck_content_sha256", entry, entry["name"])
                continue
            dut = os.path.abspath(entry["dut"])
            body = open(deck_body_path(entry)).read()
            self.assertEqual(entry["deck_content_sha256"], canonical_deck_digest(body, dut), entry["name"])
            self.assertEqual(entry["deck_content_sha256"], rc.km.deck_content_sha256(body, dut), entry["name"])
            self.assertEqual(entry["dut_sha256"], rc.sha256_file(dut), entry["name"])
            self.assertEqual(entry["body_sha256"], rc.sha256_file(deck_body_path(entry)), entry["name"])
        by = {m["name"]: m for m in manifest}
        same_point = [by[n] for n in ("ctl_ideal_ss_slew", "ctl_sch_ss_slew",
                                      "ctl_swet1_ss_res_typ_cap_typ_slew", "ctl_bodyhub_ss_res_typ_cap_typ_slew")]
        self.assertEqual(len({e["deck_content_sha256"] for e in same_point}), 4)

    def test_gear_legs_digest_the_rewritten_deck_not_the_pre_gear_one(self):
        manifest, out = self.build()
        with contextlib.redirect_stdout(io.StringIO()):
            plain = {e["name"]: e for e in rc.bench(self.dut, os.path.join(self.tmp, "bench"))}
        by = {m["name"]: m for m in manifest}
        pairs = [("ctl_gear_ss_slew", "cand_ss_slew"), ("ctl_gear_grid_slew", "grid_slew")]
        pairs += [(f"ctl_gear_ss_{r}_{c}_slew", f"pass_ss_{r}_{c}_slew")
                  for r in rc.RES_SECTIONS for c in rc.CAP_SECTIONS]
        for geared_name, plain_name in pairs:
            geared = open(deck_body_path(by[geared_name])).read()
            self.assertEqual(geared.count("\n" + rc.GEAR + "\n"), 1, geared_name)
            self.assertEqual(by[geared_name]["deck_content_sha256"], canonical_deck_digest(geared, self.dut),
                             geared_name)
            ungeared = canonical_deck_digest(geared.replace(rc.GEAR + "\n", "", 1), self.dut)
            self.assertEqual(ungeared, plain[plain_name]["deck_content_sha256"], geared_name)
            self.assertNotEqual(ungeared, by[geared_name]["deck_content_sha256"], geared_name)
            self.assertEqual(by[geared_name]["body_sha256"], rc.sha256_file(deck_body_path(by[geared_name])), geared_name)


class BracketTest(Scratch):
    BRACKET_NAMES = (
        ["ctl_bodyhub_grid_slew", "ctl_sch_grid_slew"]
        + [f"ctl_{tag}_ss_{r}_{c}_slew" for tag in ("bodyhub", "sch")
           for r in rc.RES_SECTIONS for c in rc.CAP_SECTIONS]
    )

    def build(self):
        out = os.path.join(self.tmp, "brk")
        with contextlib.redirect_stdout(io.StringIO()):
            return rc.bracket(self.dut, self.sch, out), out

    def test_builds_the_20_dr0013_bracket_legs(self):
        manifest, out = self.build()
        self.assertEqual(sorted(m["name"] for m in manifest), sorted(self.BRACKET_NAMES))
        self.assertEqual(len(load_json(os.path.join(out, "manifest.json"))), 20)
        by = {m["name"]: m for m in manifest}
        for name in self.BRACKET_NAMES:
            self.assertEqual(by[name]["corners"], 45 if name.endswith("grid_slew") else 1, name)
            self.assertEqual(by[name]["point"], None if name.endswith("grid_slew") else "mos_ss:-40:1.08", name)

    def test_every_leg_is_a_labelled_control_on_the_batch_backend(self):
        manifest, out = self.build()
        for entry in manifest:
            req = self.req(entry)
            self.assertEqual(req["backend"], "batch")
            self.assertEqual(req["batch"]["capacity_wait_s"], 600)
            self.assertTrue(req["_comment"].startswith("issue #430 CONTROL"), entry["name"])
            self.assertFalse(entry["gear"])

    def test_bodyhub_legs_run_the_one_leaf_star_surgery_dut(self):
        manifest, out = self.build()
        by = {m["name"]: m for m in manifest}
        bodyhub = os.path.join(out, "opamp_core_pex_bodyhub.spice")
        hub = open(bodyhub).read()
        self.assertIn("X$39 \\$5__t4 \\$8__t1 vss rppd l=7.47U w=1U\n", hub)
        self.assertNotIn("vss__t23", hub)
        for name in self.BRACKET_NAMES:
            if name.startswith("ctl_bodyhub_"):
                self.assertEqual(by[name]["dut"], os.path.abspath(bodyhub), name)
                self.assertEqual(by[name]["dut_sha256"], rc.sha256_file(bodyhub), name)
            else:
                self.assertEqual(by[name]["dut"], os.path.abspath(self.sch), name)
                self.assertEqual(by[name]["dut_sha256"], rc.sha256_file(self.sch), name)

    def test_section_legs_rewrite_both_passive_sections(self):
        manifest, out = self.build()
        by = {m["name"]: m for m in manifest}
        for tag in ("bodyhub", "sch"):
            for r in rc.RES_SECTIONS:
                for c in rc.CAP_SECTIONS:
                    entry = by[f"ctl_{tag}_ss_{r}_{c}_slew"]
                    self.assertEqual(entry["res"], r)
                    self.assertEqual(entry["cap"], c)
                    req = self.req(entry)
                    for proc in req["corners"]["process"]:
                        secs = [s for s in proc["sections"] if isinstance(s, dict)]
                        self.assertEqual([s["section"] for s in secs if s.get("lib") == rc.CAP_LIB], [c])
                        self.assertEqual([s["section"] for s in secs if s.get("lib") == rc.RES_LIB], [r])
            grid = by[f"ctl_{tag}_grid_slew"]
            self.assertEqual(grid["res"], None)
            self.assertEqual(grid["passive_sections_rewritten"], 0)

    def test_grid_digests_match_the_same_dut_bench_grid(self):
        manifest, out = self.build()
        with contextlib.redirect_stdout(io.StringIO()):
            plain = {e["name"]: e for e in rc.bench(self.dut, os.path.join(self.tmp, "bench"))}
        by = {m["name"]: m for m in manifest}
        # The body-on-hub edit changes the DUT, so its digest differs from the
        # bench grid's; the schematic grid digests the schematic netlist.
        self.assertNotEqual(by["ctl_bodyhub_grid_slew"]["deck_content_sha256"],
                            plain["grid_slew"]["deck_content_sha256"])
        self.assertNotEqual(by["ctl_sch_grid_slew"]["deck_content_sha256"],
                            plain["grid_slew"]["deck_content_sha256"])
        for entry in manifest:
            dut = os.path.abspath(entry["dut"])
            body = open(deck_body_path(entry)).read()
            self.assertEqual(entry["deck_content_sha256"], canonical_deck_digest(body, dut), entry["name"])
            self.assertEqual(entry["dut_sha256"], rc.sha256_file(dut), entry["name"])


class GradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def env(self, corners, job):
        path = os.path.join(self.tmp, f"{job}.json")
        with open(path, "w") as f:
            json.dump({"status": "pass", "corners": corners,
                       "environment": {"remote": {"job_id": job}}}, f)
        return path

    def test_reports_the_worst_phase_with_pm_and_margin_and_worst_iq(self):
        def corner(cid, phase, iq):
            return {"corner_id": cid, "measurements": [
                {"name": "phase_at_ugf_rad", "value": phase, "status": "pass"},
                {"name": "ivdd_total_a", "value": iq, "status": "pass"},
                {"name": "sr_fall_v_per_us", "value": None, "status": "error"}]}
        self.env([corner("a", -1.98, 8e-5), corner("b", -2.01, 9e-5)], "klt-sim-1")
        self.env([corner("c", -1.95, 1e-4)], "klt-sim-2")
        with open(os.path.join(self.tmp, "manifest.json"), "w") as f:
            f.write("[1, 2]")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc.grade(self.tmp)
        text = out.getvalue()
        pm = 180 - 2.01 * 180 / 3.141592653589793
        line = next(l for l in text.split("\n") if l.startswith("phase_at_ugf_rad"))
        self.assertIn(f"-2.01 PM={pm:.4f} margin={-2.01 - rc.PM_LIMIT_RAD:+.9f} at b [pass] job klt-sim-1", line)
        self.assertIn("ivdd_total_a           0.0001 at c [pass] job klt-sim-2", text)
        self.assertNotIn("sr_fall", text)


if __name__ == "__main__":
    unittest.main()

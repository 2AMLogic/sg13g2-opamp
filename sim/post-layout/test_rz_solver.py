"""Offline checks for sim/post-layout/rz_solver.py (no ngspice, no PDK, no klt).

  python3 -m unittest sim/post-layout/test_rz_solver.py   (or run directly)
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


rs = load("rz_solver")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def deck_body_path(entry):
    return os.path.join(os.path.dirname(entry["request"]), "tb_slew.body.spice")


def canonical_deck_digest(body, dut):
    with open(dut, "rb") as f:
        dut_sha256 = hashlib.sha256(f.read()).hexdigest()
    token = f'.include "<DUT:{dut_sha256}>"'
    return hashlib.sha256(body.replace(f'.include "{dut}"', token).encode("utf-8")).hexdigest()


# The shape of the klt 0.9.0 extraction of the drawn candidate, cut down to
# the Miller capacitor, the nulling resistor and a two-leaf vss star plus one
# escaped-net leaf, so the star-surgery legs have something to chew on.
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
* device instance _8_t0 r0 *1 0,0
R_8_t0 \\$8__t0 \\$8 1.57225
* device instance _8_t1 r0 *1 0,0
R_8_t1 \\$8__t1 \\$8 1.57225
* device instance vss_t0 r0 *1 0,0
Rvss_t0 vss__t0 vss 1.36464261466
* device instance vss_t23 r0 *1 0,0
Rvss_t23 vss__t23 vss 6.06319582466
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
CONTROL_NAMES = [
    "c451_ss_slew",
    "c451_ss_slew_itl4_100", "c451_ss_slew_itl4_500",
    "c451_ss_slew_reltol_1e2", "c451_ss_slew_noopiter",
    "c451_merge23_ss_slew", "c451_bodyleaf_only_ss_slew",
    "c451_vss_rest_merged_ss_slew", "c451_keep23t0_ss_slew",
    "c451_bodyR1m_ss_slew", "c451_bodyR6meg_ss_slew",
    "c451_bodyhub_ss_slew", "c451_sch_bodyR_ss_slew",
    "c451_probe_r_bodyR",
    "c451_grid_slew", "c451_bodyhub_grid_slew", "c451_sch_grid_slew",
]


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

    def build(self):
        out = os.path.join(self.tmp, "controls")
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = rs.controls(self.dut, self.sch, out)
        return out, {e["name"]: e for e in manifest}


class StarSurgery(unittest.TestCase):
    def setUp(self):
        self.text = EXTRACTED

    def test_leaf_node_names_count_both_spellings(self):
        self.assertEqual(rs.leaf_node_names(self.text, "vss"), ["vss__t0", "vss__t23"])
        self.assertEqual(rs.leaf_node_names(self.text, "8"), ["\\$8__t0", "\\$8__t1"])
        self.assertEqual(rs.leaf_node_names(self.text, "\\$8"), ["\\$8__t0", "\\$8__t1"])

    def test_merge_drops_the_resistor_and_renames_every_reference(self):
        out, dropped = rs.merge_leaves(self.text, [("vss", "vss__t23")])
        self.assertEqual(dropped, 1)
        self.assertNotIn("Rvss_t23 ", out)
        self.assertNotIn("vss__t23", out)
        self.assertIn("X$39 \\$5__t4 \\$8__t1 vss rppd l=7.47U w=1U", out)
        self.assertIn("Rvss_t0 vss__t0 vss 1.36464261466", out)

    def test_merge_of_an_escaped_net_writes_the_escaped_hub(self):
        out, dropped = rs.merge_leaves(self.text, [("8", "\\$8__t1")])
        self.assertEqual(dropped, 1)
        self.assertNotIn("R_8_t1 ", out)
        self.assertNotIn("\\$8__t1", out)
        self.assertIn("X$39 \\$5__t4 \\$8 vss__t23 rppd l=7.47U w=1U", out)

    def test_merge_refuses_a_leaf_of_another_net(self):
        with self.assertRaises(SystemExit):
            rs.merge_leaves(self.text, [("vss", "out__t1")])

    def test_merge_refuses_a_node_that_is_not_a_star_leaf(self):
        with self.assertRaises(SystemExit):
            rs.merge_leaves(self.text, [("vss", "vss__t99")])

    def test_set_leaf_resistance_rewrites_the_one_line(self):
        out = rs.set_leaf_resistance(self.text, "vss__t23", "1e-3")
        self.assertIn("Rvss_t23 vss__t23 vss 1e-3", out)
        self.assertIn("Rvss_t0 vss__t0 vss 1.36464261466", out)

    def test_set_leaf_resistance_refuses_an_unknown_leaf(self):
        with self.assertRaises(SystemExit):
            rs.set_leaf_resistance(self.text, "vss__t99", "1")

    def test_body_on_hub_moves_only_the_card(self):
        out = rs.body_on_hub(self.text)
        self.assertIn("X$39 \\$5__t4 \\$8__t1 vss rppd l=7.47U w=1U", out)
        self.assertIn("Rvss_t23 vss__t23 vss 6.06319582466", out)

    def test_body_on_hub_refuses_without_exactly_one_card(self):
        with self.assertRaises(SystemExit):
            rs.body_on_hub(EXTRACTED + "X$40 a b c rppd l=1U w=1U\n")

    def test_sch_body_resistor_inserts_the_leaf_pair(self):
        out = rs.sch_body_resistor(SCHEMATIC)
        self.assertIn("XRz cc_rz d2 rzbody rppd w=1u l=7.47u m=1 b=0", out)
        self.assertIn("Rrzbody rzbody vss 6.06319582466", out)

    def test_insert_options_lands_after_the_last_options_line(self):
        body = ".options tnom=27 interp\nV1 a 0 1\n"
        self.assertEqual(rs.insert_options(body, "itl4=100"),
                         ".options tnom=27 interp\n.options itl4=100\nV1 a 0 1\n")


class ControlsBuild(Scratch):
    def test_builds_the_17_legs_of_the_record(self):
        out, by_name = self.build()
        self.assertEqual(sorted(by_name), sorted(CONTROL_NAMES))
        manifest = load_json(os.path.join(out, "manifest.json"))
        self.assertEqual(len(manifest), 17)

    def test_single_corner_legs_sit_at_the_binding_point(self):
        _, by_name = self.build()
        for name in CONTROL_NAMES:
            if name.endswith("_grid_slew"):
                continue
            self.assertEqual(by_name[name]["point"], "mos_ss:-40:1.08", name)
            self.assertEqual(by_name[name]["corners"], 1, name)

    def test_grids_keep_the_standing_45_corner_matrix(self):
        _, by_name = self.build()
        for name in ("c451_grid_slew", "c451_bodyhub_grid_slew", "c451_sch_grid_slew"):
            self.assertEqual(by_name[name]["corners"], 45, name)
            req = self.req(by_name[name])
            self.assertNotIn("SG13G2_PEX_POINTS", json.dumps(req))

    def test_flags_every_leg_as_an_issue_451_control(self):
        _, by_name = self.build()
        for name in CONTROL_NAMES:
            comment = self.req(by_name[name])["_comment"]
            self.assertTrue(comment.startswith("issue #451 CONTROL, not the committed bench:"), name)

    def test_solver_ladder_rides_the_body_after_its_last_options(self):
        _, by_name = self.build()
        body = open(os.path.join(os.path.dirname(by_name["c451_ss_slew_itl4_100"]["request"]),
                                 "tb_slew.body.spice")).read()
        self.assertIn(".options tnom=27 interp\n.options itl4=100", body)
        for name, option in (("c451_ss_slew_itl4_500", "itl4=500"),
                             ("c451_ss_slew_reltol_1e2", "reltol=1e-2"),
                             ("c451_ss_slew_noopiter", "noopiter")):
            body = open(os.path.join(os.path.dirname(by_name[name]["request"]),
                                     "tb_slew.body.spice")).read()
            self.assertIn(".options " + option, body)
        baseline = open(os.path.join(os.path.dirname(by_name["c451_ss_slew"]["request"]),
                                     "tb_slew.body.spice")).read()
        self.assertNotIn("itl4", baseline)

    def test_star_surgery_legs_carry_the_described_edits(self):
        out, by_name = self.build()
        merge23 = open(os.path.join(out, "opamp_core_pex_merge23.spice")).read()
        self.assertNotIn("vss__t23", merge23)
        self.assertIn("Rvss_t0 vss__t0 vss 1.36464261466", merge23)
        leaf_only = open(os.path.join(out, "opamp_core_pex_bodyleaf_only.spice")).read()
        self.assertIn("Rvss_t23 vss__t23 vss 6.06319582466", leaf_only)
        self.assertNotIn("vss__t0", leaf_only)
        self.assertNotIn("\\$5__t4", leaf_only)
        self.assertIn("X$39 \\$5 \\$8 vss__t23 rppd l=7.47U w=1U", leaf_only)
        rest = open(os.path.join(out, "opamp_core_pex_vss_rest_merged.spice")).read()
        self.assertIn("Rvss_t23 vss__t23 vss 6.06319582466", rest)
        self.assertNotIn("vss__t0", rest)
        keep = open(os.path.join(out, "opamp_core_pex_keep23t0.spice")).read()
        self.assertEqual(keep, EXTRACTED)
        for tag, ohms in rs.BODY_R_RUNGS:
            ladder = open(os.path.join(out, f"opamp_core_pex_bodyR{tag}.spice")).read()
            self.assertIn(f"Rvss_t23 vss__t23 vss {ohms}", ladder)
        hub = open(os.path.join(out, "opamp_core_pex_bodyhub.spice")).read()
        self.assertIn("X$39 \\$5__t4 \\$8__t1 vss rppd l=7.47U w=1U", hub)

    def test_star_surgery_notes_name_the_drop_counts(self):
        _, by_name = self.build()
        counts = {"c451_merge23_ss_slew": 1, "c451_bodyleaf_only_ss_slew": 4,
                  "c451_vss_rest_merged_ss_slew": 1, "c451_keep23t0_ss_slew": 0}
        for name, n in counts.items():
            self.assertIn(f"({n} star resistors dropped)", by_name[name]["note"], name)

    def test_schematic_and_probe_legs_use_their_own_duts(self):
        out, by_name = self.build()
        sch = open(os.path.join(out, "opamp_core_sch_bodyR.spice")).read()
        self.assertIn("Rrzbody rzbody vss 6.06319582466", sch)
        probe = open(os.path.join(out, "c451_probe_r_bodyR", "probe.body.spice")).read()
        self.assertIn("XR1 in out rzbody rppd l=7.47u w=1u", probe)
        self.assertIn("Rrzbody rzbody 0 6.06319582466", probe)
        self.assertEqual(self.req(by_name["c451_probe_r_bodyR"])["netlist"], "probe.body.spice")

    def test_every_batch_request_waits_for_capacity(self):
        _, by_name = self.build()
        for name in CONTROL_NAMES:
            req = self.req(by_name[name])
            self.assertEqual(req.get("backend"), "batch", name)
            self.assertGreaterEqual(req.get("batch", {}).get("capacity_wait_s", 0), 600, name)

    def test_manifest_records_the_dut_and_body_digests(self):
        _, by_name = self.build()
        for name in CONTROL_NAMES:
            entry = by_name[name]
            if entry["kind"] == "probe":
                self.assertNotIn("deck_content_sha256", entry, name)
                continue
            self.assertTrue(os.path.exists(entry["dut"]), name)
            self.assertEqual(entry["dut_sha256"], rs.sha256_file(entry["dut"]), name)
            if entry["kind"] == "slew":
                self.assertTrue(entry["body_sha256"], name)
            body = open(deck_body_path(entry)).read()
            self.assertEqual(len(entry["deck_content_sha256"]), 64, name)
            self.assertEqual(entry["deck_content_sha256"],
                             canonical_deck_digest(body, os.path.abspath(entry["dut"])), name)
            self.assertEqual(entry["deck_content_sha256"],
                             rs.km.deck_content_sha256(body, os.path.abspath(entry["dut"])), name)

    def test_options_legs_digest_the_rewritten_deck_not_the_pre_rewrite_one(self):
        _, by_name = self.build()
        plain = by_name["c451_ss_slew"]["deck_content_sha256"]
        for tag, option in rs.SOLVER_LADDER:
            name = f"c451_ss_slew_{tag}"
            entry = by_name[name]
            rewritten = open(deck_body_path(entry)).read()
            self.assertEqual(rewritten.count("\n.options " + option + "\n"), 1, name)
            self.assertEqual(entry["deck_content_sha256"],
                             canonical_deck_digest(rewritten, self.dut), name)
            unrewritten = canonical_deck_digest(
                rewritten.replace(".options " + option + "\n", "", 1), self.dut)
            self.assertEqual(unrewritten, plain, name)
            self.assertNotEqual(entry["deck_content_sha256"], plain, name)


if __name__ == "__main__":
    unittest.main()

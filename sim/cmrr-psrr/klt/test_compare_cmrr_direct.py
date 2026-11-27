#!/usr/bin/env python3
"""Offline tests for compare_cmrr_direct.py (issue #505).

    python3 -m unittest discover -s sim/cmrr-psrr/klt -p 'test_*.py'

The committed CMRR envelope, the PSRR direct envelope run under the same fleet
image, and the superseded harness record are the baseline. The tests that carry
weight are the negative controls, each of which must fail and name the cause:
a swapped common-mode/supply stimulus, a stale or misjoined Av0 point (wrong
corner, wrong DUT hash), a failed plateau guard (shown, not hidden), and an old
fixed-harness record presented as batch evidence.
"""

from __future__ import annotations

import copy
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
import compare_cmrr_direct as C  # noqa: E402
from klt_envelope import InputError  # noqa: E402

RECORDS = os.path.join(HERE, "records")
CMRR = sorted(glob.glob(os.path.join(RECORDS, "*.cmrr.sim.json")))[-1]
PSRR = sorted(glob.glob(os.path.join(RECORDS, "*.direct.sim.json")))[-1]
HARNESS = os.path.join(HERE, "..", "records", "20260921-151815-707b34c.csv")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _read(path):
    with open(path) as f:
        return f.read()


def _meas(env, idx, name):
    return next(m for m in env["corners"][idx]["measurements"] if m["name"] == name)


class CompareCmrrDirect(unittest.TestCase):
    def setUp(self):
        self.cmrr, self.psrr = _load(CMRR), _load(PSRR)
        self.harness = C.load_harness(HARNESS)
        self.cbody, self.pbody = _read(C.DEFAULT_CMRR_BODY), _read(C.DEFAULT_PSRR_BODY)

    def _compare(self, cmrr=None, psrr=None, cbody=None, pbody=None):
        cmrr, psrr = cmrr or self.cmrr, psrr or self.psrr
        return C.compare(C.index_envelope(cmrr), C.index_envelope(psrr, "psrr", C.PSRR_MEASUREMENTS), self.harness,
                         cmrr, psrr, cbody or self.cbody, pbody or self.pbody)

    def test_baseline_agrees(self):
        rep = self._compare()
        self.assertEqual(rep["status"], "agree")
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["row"]["worst"]["point"], "mos_fs_125C_1.08V")
        self.assertEqual(rep["row"]["worst"]["verdict"], "pass")
        self.assertEqual(rep["plateau_guard_failures"], [])

    def test_harness_av0_shift_is_reported_not_hidden(self):
        shift = self._compare()["row"]["harness_shift_db"]
        # The committed open-loop record's own shift vs the floating-inn record.
        self.assertAlmostEqual(shift["av0_min"], 0.2199, places=3)
        self.assertAlmostEqual(shift["av0_max"], 1.785, places=3)

    def test_envelope_bodies_are_the_committed_bodies(self):
        C.check_body_hash(self.cmrr, C.DEFAULT_CMRR_BODY, "cmrr")
        C.check_body_hash(self.psrr, C.DEFAULT_PSRR_BODY, "psrr")
        with self.assertRaisesRegex(InputError, "stale or different body"):
            C.check_body_hash(self._with_closure(self.cmrr, C.DEFAULT_CMRR_BODY, "0" * 64), C.DEFAULT_CMRR_BODY, "cmrr")

    @staticmethod
    def _with_closure(env, body, sha):
        env = copy.deepcopy(env)
        for c in env["environment"]["netlist_closure"]:
            if c["path"].endswith(os.path.basename(body)):
                c["sha256"] = sha
        return env

    # --- negative control: swapped common-mode / supply stimulus
    def test_swapped_stimulus_body_refused(self):
        swapped = self.cbody.replace("Vcmb inpb midb dc 0 ac 1", "Vsrip vddb vdd dc 0 ac 1")
        with self.assertRaisesRegex(InputError, "swapped stimulus|AC sources"):
            self._compare(cbody=swapped)
        with self.assertRaisesRegex(InputError, "Vcmb"):
            self._compare(pbody=self.pbody + "Vcmb inpb midb dc 0 ac 1\n")

    def test_ac_magnitude_is_read_from_the_source_card(self):
        card = "Vsrip vddb vdd dc 0 ac 1"
        for magnitude in ("0.5", "1m", "1.001", "1e-1", "1e", "0.5 ac 1"):
            with self.subTest(magnitude=magnitude):
                changed = self.pbody.replace(card, f"Vsrip vddb vdd dc 0 ac {magnitude} $ ac 1")
                with self.assertRaisesRegex(InputError, "PSRR body: Vsrip must have unit AC magnitude"):
                    C.check_stimulus(self.cbody, changed)
        C.check_stimulus(self.cbody, self.pbody.replace(card, "Vsrip vddb vdd dc 0\n+ AC 0.1E1 $ ac 0.5"))
        commented = "Vsrip vddb vdd dc 0\r\n* AC specifications follow\r\n+ AC 1"
        C.check_stimulus(self.cbody, self.pbody.replace(card, commented))
        conditional_dc = card + "\n.if(1)\nVsrip vddb vdd dc 0\n.endif"
        with self.assertRaisesRegex(InputError, "PSRR body: Vsrip must have unit AC magnitude"):
            C.check_stimulus(self.cbody, self.pbody.replace(card, conditional_dc))

    def test_unit_sources_must_drive_the_expected_nodes(self):
        for label, cmrr, psrr in (
            ("CMRR body: Vinp", self.cbody.replace("Vinp inpa", "Vinp inpb"), self.pbody),
            ("PSRR body: Vinp", self.cbody, self.pbody.replace("Vinp inpa", "Vinp inpb")),
            ("PSRR body: Vsrip", self.cbody, self.pbody.replace("Vsrip vddb", "Vsrip outb")),
        ):
            with self.subTest(source=label), self.assertRaisesRegex(InputError, label + " must drive"):
                C.check_stimulus(cmrr, psrr)

    def test_solver_options_in_the_netlist_and_control_commands(self):
        for card in (
            ".OPT tnom=27,RELTOL = 0.01",
            '.option "reltol"=0.01',
            ".option tnom=27 $ nominal temperature\n* continued below\n+ reltol=0.01",
            ".options tnom=27 \\\\\n reltol=0.01",
            ".subckt child a\n.opt reltol=0.01\nr1 a 0 1k\n.ends\nx1 vdd child",
            ".if (1)\n.options reltol=0.01\n.endif",
            ".control\nset r=0.01\noption reltol=$r\n.endc",
            "*# set reltol=0.01",
        ):
            with self.subTest(card=card), self.assertRaisesRegex(InputError, "CMRR body: reltol"):
                C.check_stimulus(self.cbody + card + "\n", self.pbody)
        comments = "* .options reltol=0.01\n.option tnom=27 $ reltol=0.01\n*# echo reltol=0.01\n"
        C.check_stimulus(self.cbody + comments + '*# set label="default reltol=0.001"\n', self.pbody)

    def test_input_coupling_requires_one_top_level_unit_capacitor(self):
        card = "Cinna_acgnd inna vss 1"
        for replacement in (
            card + "m $ 1 F",
            card + "\nCextra inna inpa 1",
            ".subckt unused inna vss\n" + card + "\n.ends",
            ".if (0)\n" + card + "\n.endif",
            card + "\n.if (1)\nCextra inna inpa 1\n.endif",
        ):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(InputError, "CMRR body: inna"):
                C.check_stimulus(self.cbody.replace(card, replacement), self.pbody)
        reversed_pins = "Cinna_acgnd VSS INNA\n+ 1.0E0 $ 1 F"
        C.check_stimulus(self.cbody.replace(card, reversed_pins), self.pbody)

    def test_sources_and_loads_must_be_in_the_top_level_circuit(self):
        source = "Vsrip vddb vdd dc 0 ac 1"
        load = "Cloadb outb vss 2e-12"
        for block in (".subckt unused a b\n{}\n.ends", ".control\n{}\n.endc", ".end\n{}"):
            with self.subTest(block=block):
                # Move both cards out of the circuit, keeping their text intact.
                body = self.pbody.replace(source, "").replace(load, "")
                body += block.format(source + "\n" + load) + "\n"
                with self.assertRaisesRegex(InputError, "PSRR body AC sources"):
                    C.check_stimulus(self.cbody, body)
                self.assertIsNone(C.output_load_f(body))

                # The same out-of-scope copies cannot shadow valid circuit cards.
                body = self.pbody + block.format(source + "\n" + load) + "\n"
                C.check_stimulus(self.cbody, body)
                self.assertEqual(C.output_load_f(body), C.output_load_f(self.pbody))

    def test_nested_branches_keep_the_outer_condition_until_endif(self):
        card = "Cinna_acgnd inna vss 1"
        inner = ".IF(0)\nRinner inpa 0 1k\n.ENDIF"
        for branch in (".elseif (0)", ".else"):
            with self.subTest(branch=branch):
                prefix = f".if (0)\n{inner}\n{branch}\n"
                with self.assertRaisesRegex(InputError, "CMRR body: inna"):
                    C.check_stimulus(self.cbody.replace(card, prefix + card + "\n.endif"), self.pbody)
                C.check_stimulus(self.cbody.replace(card, prefix + "Router inpa 0 1k\n.endif\n" + card), self.pbody)

    def test_swapped_stimulus_values_are_out_of_tolerance(self):
        env = copy.deepcopy(self.cmrr)
        for i, c in enumerate(env["corners"]):  # copy B excited by the supply: Acm0 reads Avs0
            avs = next(m["value"] for m in self.psrr["corners"][i]["measurements"] if m["name"] == "avs0_db")
            _meas(env, i, "acm0_db")["value"] = avs
            _meas(env, i, "cmrr_db")["value"] = _meas(env, i, "av0_db")["value"] - avs
        rep = self._compare(cmrr=env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("acm0_db" in m and "wrong common-mode stimulus" in m for m in rep["out_of_tolerance"]))

    # --- negative control: stale or misjoined Av0
    def test_misjoined_av0_point_names_the_point(self):
        env = copy.deepcopy(self.cmrr)
        env["corners"][4], env["corners"][5] = copy.deepcopy(env["corners"][5]), copy.deepcopy(env["corners"][4])
        env["corners"][4]["corner_id"], env["corners"][5]["corner_id"] = self.cmrr["corners"][4]["corner_id"], self.cmrr["corners"][5]["corner_id"]
        for i in (4, 5):
            for k in ("process", "supply_v", "temperature_c"):
                env["corners"][i][k] = self.cmrr["corners"][i][k]
        rep = self._compare(cmrr=env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("av0_db" in m and "stale or misjoined Av0" in m for m in rep["out_of_tolerance"]))

    def test_stale_av0_value_refused(self):
        env = copy.deepcopy(self.cmrr)
        _meas(env, 9, "av0_db")["value"] += 0.3
        _meas(env, 9, "cmrr_db")["value"] += 0.3
        rep = self._compare(cmrr=env)
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(len(rep["out_of_tolerance"]), 1)

    def test_inconsistent_cmrr_is_out_of_tolerance(self):
        env = copy.deepcopy(self.cmrr)
        _meas(env, 2, "cmrr_db")["value"] += 0.01
        self.assertIn("av0_db - acm0_db", self._compare(cmrr=env)["out_of_tolerance"][0])

    def test_wrong_dut_hash_refused(self):
        env = copy.deepcopy(self.cmrr)
        for c in env["environment"]["netlist_closure"]:
            if c["path"] == C.DUT:
                c["sha256"] = "0" * 64
        with self.assertRaisesRegex(InputError, "different DUT"):
            self._compare(cmrr=env)

    def test_different_engine_refused(self):
        env = copy.deepcopy(self.cmrr)
        env["environment"]["engine_version"] = "46"
        with self.assertRaisesRegex(InputError, "engine_version differs"):
            self._compare(cmrr=env)

    def test_single_job_worker_banner_is_optional_but_must_agree_when_present(self):
        env = self.cmrr["environment"]
        job = env["remote"]["fleet"][0]
        env["remote"] = job
        simulator = job["worker_environment"]["simulator"]
        del simulator["version_banner"]
        self.assertEqual(self._compare()["conditions"]["engine_version"], "47")
        simulator["version_banner"] = "** ngspice-45 and ngspice-47"
        with self.assertRaisesRegex(InputError, "worker simulator.*expected ngspice-47"):
            self._compare()

    # --- negative control: failed plateau guard is a result
    def test_plateau_miss_is_listed(self):
        env = copy.deepcopy(self.cmrr)
        m = _meas(env, 6, "cmrr_plateau_delta_db")
        m["value"], m["status"] = 0.2, "fail"
        env["corners"][6]["status"] = "fail"
        env["status"], env["passed"], env["failed"] = "fail", 44, 1
        rep = self._compare(cmrr=env)
        self.assertEqual(len(rep["plateau_guard_failures"]), 1)
        self.assertIn("0.2", rep["plateau_guard_failures"][0])
        self.assertEqual(rep["status"], "agree")  # a result, not a validation failure

    # --- negative control: an old fixed-harness record as batch evidence
    def test_harness_record_is_not_batch_evidence(self):
        with self.assertRaisesRegex(InputError, "not a klt sim envelope"):
            C.index_envelope({"rows": []})

    def test_local_run_is_not_batch_evidence(self):
        env = copy.deepcopy(self.cmrr)
        env["environment"].pop("remote")
        with self.assertRaisesRegex(InputError, "not batch evidence"):
            C.index_envelope(env)

    # --- envelope gate
    def test_missing_and_duplicate_points_refused(self):
        env = copy.deepcopy(self.cmrr)
        env["corners"].pop()
        env["corner_count"] = 44
        with self.assertRaises(InputError):
            C.index_envelope(env)
        env = copy.deepcopy(self.cmrr)
        env["corners"][1] = copy.deepcopy(env["corners"][0])
        with self.assertRaisesRegex(InputError, "duplicate"):
            C.index_envelope(env)

    def test_errored_measurement_refused(self):
        env = copy.deepcopy(self.cmrr)
        _meas(env, 0, "acm0_db")["status"] = "error"
        with self.assertRaises(InputError):
            C.index_envelope(env)

    def test_request_matches_bodies_and_guard(self):
        with open(os.path.join(HERE, "cmrr_direct.request.json")) as f:
            req = json.load(f)
        names = {m["name"]: m for m in req["measurements"]}
        self.assertEqual(names["cmrr_plateau_delta_db"]["limits"], {"max": C.PLATEAU_MAX_DB})
        self.assertNotIn("limits", names["cmrr_db"])  # superseded row: no bound is graded in the deck
        self.assertEqual(req["netlist"], "tb_cmrr_direct.body.spice")
        with open(os.path.join(HERE, "psrr_direct.request.json")) as f:
            psrr_req = json.load(f)
        for k in ("corners", "models", "analysis", "options"):  # same run conditions as the PSRR deck
            self.assertEqual(req[k], psrr_req[k], k)


if __name__ == "__main__":
    unittest.main()

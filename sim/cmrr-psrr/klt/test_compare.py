#!/usr/bin/env python3
"""Offline negative-control tests for compare.py (issue #99).

    python3 -m unittest discover -s sim/cmrr-psrr/klt -p 'test_*.py'

The synthetic envelopes below are BUILT FROM the committed harness record, so a
test that only checks "the baseline agrees" would be circular. The baseline is
the control every negative case perturbs; the tests that carry weight are the
negative controls (missing, duplicate, extra, null, NaN, errored/inconclusive
corner, nothing_checked, skipped coverage, wrong grid key, mis-biased Vcm,
perturbed value, absent Av0 or Avs, bound flip, genuine bound miss), each of
which must fail and name the point/metric. None of this is evidence about the
circuit -- a committed envelope in records/ would be.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# compare.py imports the shared envelope core from sim/tools (issue #142).
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
import compare as C  # noqa: E402

BENCH = os.path.dirname(HERE)
SIM = os.path.dirname(BENCH)
HARNESS_CSV = os.path.join(BENCH, "records", "20260921-151815-707b34c.csv")
OPENLOOP_CSV = os.path.join(SIM, "open-loop-ac", "records", "20260910-221601-22feaba.csv")
REQUEST = os.path.join(HERE, "psrr.request.json")
BODY = os.path.join(HERE, "tb_psrr.body.spice")


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _status(value, limits):
    if not limits:
        return "pass"
    lo, hi = limits.get("min"), limits.get("max")
    return "pass" if (lo is None or value >= lo) and (hi is None or value <= hi) else "fail"


def _request():
    with open(REQUEST) as f:
        return json.load(f)


def _envelope(rows):
    limits = {m["name"]: m.get("limits") for m in _request()["measurements"]}
    corners = []
    for r in rows:
        avs0 = float(r["avs0_db"])
        delta = float(r["psrr_plateau_delta_db"])
        vals = {"avs0_db": avs0, "avs_plateau_db": avs0 + delta, "avs_plateau_delta_db": delta,
                "avs_1khz_db": float(r["avs_1khz_db"])}
        vdd = float(r["vdd_v"])
        corners.append({
            "corner_id": f"{r['corner']}/vdd={vdd:.3f}/{r['temp_c']}C",
            "process": r["corner"], "temperature_c": float(r["temp_c"]),
            "supply_v": {"vdd": vdd, "vinp": vdd / 2},
            "status": "pass" if all(_status(vals[n], limits[n]) == "pass" for n in vals) else "fail",
            "measurements": [{"name": n, "value": v, "status": _status(v, limits[n]), "limits": limits[n]}
                             for n, v in vals.items()],
        })
    status = "pass" if all(c["status"] == "pass" for c in corners) else "fail"
    return {"schema_version": 1, "status": status, "corner_count": len(corners), "corners": corners,
            "measurements": [{"name": "avs_plateau_delta_db", "status": status, "limits": limits["avs_plateau_delta_db"]}],
            "coverage": {"nothing_checked": False, "skipped": [], "checked": ["x"]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.h_rows = _rows(HARNESS_CSV)
        self.env = _envelope(self.h_rows)
        self.harness = C.load_harness_csv(HARNESS_CSV)
        self.openloop = C.load_openloop_csv(OPENLOOP_CSV)

    def tool(self, env=None):
        return C.index_envelope(env if env is not None else self.env)

    def run_compare(self, env=None, harness=None, openloop=None):
        return C.compare(self.tool(env), harness or self.harness, openloop or self.openloop)

    def corner(self, env, key):
        for c in env["corners"]:
            if C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == key:
                return c
        raise KeyError(key)

    def meas(self, env, key, name):
        return next(m for m in self.corner(env, key)["measurements"] if m["name"] == name)


class TestRequest(Base):
    def test_ratified_grid(self):
        r = _request()
        self.assertEqual([p["name"] for p in r["corners"]["process"]], list(C.PROCESSES))
        for p in r["corners"]["process"]:
            self.assertEqual(p["sections"][1], {"lib": "libs.tech/ngspice/models/cornerCAP.lib", "section": "cap_typ"})
        self.assertEqual(r["corners"]["supply_v"]["vdd"], list(C.SUPPLIES))
        self.assertEqual(r["corners"]["supply_v"]["vinp"], [v / 2 for v in C.SUPPLIES])
        self.assertEqual(r["corners"]["temperature_c"], list(C.TEMPERATURES))
        self.assertEqual(r["analysis"], {"kind": "ac", "args": "dec 20 10m 1g"})

    def test_declares_every_measurement_compare_reads(self):
        self.assertEqual(tuple(m["name"] for m in _request()["measurements"]), C.MEASUREMENTS)

    def test_netlist_points_at_this_body(self):
        self.assertEqual(_request()["netlist"], os.path.basename(BODY))
        self.assertTrue(os.path.exists(os.path.join(HERE, _request()["netlist"])))

    def test_body_has_one_include_and_no_control_block(self):
        with open(BODY) as f:
            lines = [ln.strip().lower() for ln in f if not ln.lstrip().startswith("*")]
        self.assertEqual([ln for ln in lines if ln.startswith(".include")],
                         [".include ../../../design/netlist/opamp_core.spice"])
        for bad in (".control", ".endc", ".end", ".ac", ".lib"):
            self.assertNotIn(bad, [ln.split()[0] for ln in lines if ln])
        self.assertTrue(any(ln.startswith("vdd ") and " ac 1" in ln for ln in lines))
        self.assertFalse(any(ln.startswith("vinp ") and "ac" in ln.split() for ln in lines))

    def test_plateau_guard_is_the_only_limit_and_matches_the_harness(self):
        lim = {m["name"]: m.get("limits") for m in _request()["measurements"]}
        self.assertEqual({k: v for k, v in lim.items() if v}, {"avs_plateau_delta_db": {"max": C.PLATEAU_LIMIT_DB}})

    def test_ratified_bound_matches_spec(self):
        with open(os.path.join(os.path.dirname(SIM), "spec", "target-spec.md")) as f:
            spec = f.read()
        self.assertIn("Ratified bound ≥ 1.87 dB", spec)
        self.assertEqual(C.PSRR_BOUND_DB, 1.87)


class TestHarnessInputs(Base):
    def test_committed_records_are_the_full_grid(self):
        self.assertEqual(len(self.harness), 45)
        self.assertEqual(len(self.openloop), 45)

    def test_harness_psrr_is_openloop_av0_minus_avs0(self):
        for k in C.expected_keys():
            self.assertAlmostEqual(self.harness[k]["psrr_db"], self.openloop[k]["av0_db"] - self.harness[k]["avs0_db"], places=3)

    def _write(self, rows, cols):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        self.addCleanup(os.unlink, path)
        return path

    def test_duplicate_harness_row_rejected(self):
        p = self._write(self.h_rows + [self.h_rows[0]], list(self.h_rows[0]))
        with self.assertRaisesRegex(C.InputError, "duplicate row"):
            C.load_harness_csv(p)

    def test_missing_openloop_row_rejected(self):
        rows = _rows(OPENLOOP_CSV)[1:]
        p = self._write(rows, list(rows[0]))
        with self.assertRaisesRegex(C.InputError, "missing from open-loop CSV"):
            C.load_openloop_csv(p)

    def test_nonfinite_openloop_av0_rejected(self):
        rows = _rows(OPENLOOP_CSV)
        rows[3]["av0_db"] = "nan"
        p = self._write(rows, list(rows[0]))
        with self.assertRaisesRegex(C.InputError, "av0_db 'nan'"):
            C.load_openloop_csv(p)


class TestBaselineControl(Base):
    def test_identical_numbers_agree(self):
        rep = self.run_compare()
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["status"], "agree", rep["out_of_tolerance"])

    def test_binding_corner_is_ff_125_132(self):
        self.assertEqual(self.run_compare()["row"]["harness_worst"]["point"], "mos_ff_125C_1.32V")

    def test_known_plateau_guard_miss_is_preserved(self):
        rep = self.run_compare()
        p = next(p for p in rep["points"] if p["point_id"] == "mos_ss_-40C_1.08V")
        self.assertFalse(p["plateau_guard"]["tool_pass"])
        self.assertTrue(p["plateau_guard"]["agree"])
        self.assertEqual(self.env["status"], "fail")

    def test_reordered_corners_join_identically(self):
        env = copy.deepcopy(self.env)
        env["corners"].reverse()
        self.assertEqual(self.run_compare(env)["status"], "agree")


class TestEnvelopeNegativeControls(Base):
    def test_missing_corner(self):
        env = copy.deepcopy(self.env)
        env["corners"].pop()
        env["corner_count"] = 44
        with self.assertRaisesRegex(C.InputError, "mos_fs_125C_1.32V: missing from"):
            self.tool(env)

    def test_duplicate_corner(self):
        env = copy.deepcopy(self.env)
        env["corners"].append(copy.deepcopy(env["corners"][0]))
        env["corner_count"] = 46
        with self.assertRaisesRegex(C.InputError, "duplicate corner"):
            self.tool(env)

    def test_wrong_grid_key(self):
        env = copy.deepcopy(self.env)
        env["corners"][0]["supply_v"] = {"vdd": 1.10, "vinp": 0.55}
        with self.assertRaisesRegex(C.InputError, "not a point of the ratified grid"):
            self.tool(env)

    def test_wrong_temperature_key(self):
        env = copy.deepcopy(self.env)
        env["corners"][0]["temperature_c"] = 85
        with self.assertRaisesRegex(C.InputError, "mos_tt_-40C_1.08V: missing from"):
            self.tool(env)

    def test_corner_count_mismatch(self):
        env = copy.deepcopy(self.env)
        env["corner_count"] = 44
        with self.assertRaisesRegex(C.InputError, "corner_count"):
            self.tool(env)

    def test_null_measurement(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_tt", 27, 1.2), "avs0_db")["value"] = None
        with self.assertRaisesRegex(C.InputError, r"mos_tt_27C_1.20V: measurement avs0_db value None"):
            self.tool(env)

    def test_nonfinite_measurement(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_tt", 27, 1.2), "avs_1khz_db")["value"] = float("nan")
        with self.assertRaisesRegex(C.InputError, "avs_1khz_db"):
            self.tool(env)

    def test_absent_avs_measurement_fails_closed(self):
        env = copy.deepcopy(self.env)
        c = self.corner(env, ("mos_ff", 125, 1.32))
        c["measurements"] = [m for m in c["measurements"] if m["name"] != "avs0_db"]
        with self.assertRaisesRegex(C.InputError, "mos_ff_125C_1.32V: measurement avs0_db missing"):
            self.tool(env)

    def test_skipped_measurement_status(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_tt", 27, 1.2), "avs0_db")["status"] = "skipped"
        with self.assertRaisesRegex(C.InputError, "avs0_db status 'skipped'"):
            self.tool(env)

    def test_vinp_not_half_vdd(self):
        env = copy.deepcopy(self.env)
        self.corner(env, ("mos_tt", 27, 1.2))["supply_v"]["vinp"] = 0.55
        with self.assertRaisesRegex(C.InputError, "vinp 0.55 != vdd/2"):
            self.tool(env)

    def test_errored_corner_is_not_evidence(self):
        env = copy.deepcopy(self.env)
        self.corner(env, ("mos_tt", 27, 1.2))["status"] = "error"
        with self.assertRaisesRegex(C.InputError, "corner status 'error'"):
            self.tool(env)

    def test_inconclusive_corner_is_not_evidence(self):
        env = copy.deepcopy(self.env)
        self.corner(env, ("mos_tt", 27, 1.2))["status"] = "inconclusive"
        with self.assertRaisesRegex(C.InputError, "corner status 'inconclusive'"):
            self.tool(env)

    def test_inconclusive_aggregate(self):
        env = copy.deepcopy(self.env)
        env["status"] = "inconclusive"
        with self.assertRaisesRegex(C.InputError, "aggregate status"):
            self.tool(env)

    def test_nothing_checked(self):
        env = copy.deepcopy(self.env)
        env["coverage"]["nothing_checked"] = True
        with self.assertRaisesRegex(C.InputError, "nothing_checked"):
            self.tool(env)

    def test_skipped_coverage(self):
        env = copy.deepcopy(self.env)
        env["coverage"]["skipped"] = [{"id": "limit:x", "reason": "r"}]
        with self.assertRaisesRegex(C.InputError, "coverage.skipped"):
            self.tool(env)

    def test_klt_error_envelope(self):
        with self.assertRaisesRegex(C.InputError, "klt error envelope"):
            C.index_envelope({"error": {"message": "boom"}})


class TestComparisonNegativeControls(Base):
    def test_perturbed_avs0_outside_tolerance_is_named(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_sf", 125, 1.08), "avs0_db")["value"] += 0.1
        rep = self.run_compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_sf_125C_1.08V avs0_db" in s for s in rep["out_of_tolerance"]))
        self.assertTrue(any("mos_sf_125C_1.08V psrr_db" in s for s in rep["out_of_tolerance"]))

    def test_perturbation_inside_tolerance_is_accepted(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_sf", 125, 1.08), "avs0_db")["value"] += 0.01
        self.assertEqual(self.run_compare(env)["status"], "agree")

    def test_perturbed_1khz_outside_tolerance_is_named(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_tt", 27, 1.2), "avs_1khz_db")["value"] -= 0.5
        self.assertTrue(any("mos_tt_27C_1.20V avs_1khz_db" in s for s in self.run_compare(env)["out_of_tolerance"]))

    def test_dc_shelf_is_not_the_1khz_figure(self):
        # Swapping the 1 kHz Avs into the DC-shelf slot must be caught.
        env = copy.deepcopy(self.env)
        k = ("mos_tt", 27, 1.2)
        self.meas(env, k, "avs0_db")["value"] = self.meas(env, k, "avs_1khz_db")["value"]
        rep = self.run_compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V psrr_db" in s for s in rep["out_of_tolerance"]))

    def test_openloop_av0_absent_fails_closed(self):
        ol = copy.deepcopy(self.openloop)
        ol[("mos_tt", 27, 1.2)]["av0_db"] = float("nan")
        with self.assertRaisesRegex(C.InputError, "mos_tt_27C_1.20V: same-point Av0 absent"):
            self.run_compare(openloop=ol)

    def test_openloop_point_missing_fails_closed(self):
        ol = copy.deepcopy(self.openloop)
        del ol[("mos_tt", 27, 1.2)]
        with self.assertRaisesRegex(C.InputError, "missing from open-loop CSV"):
            self.run_compare(openloop=ol)

    def test_openloop_from_a_different_run_is_flagged(self):
        ol = copy.deepcopy(self.openloop)
        ol[("mos_tt", 27, 1.2)]["av0_db"] += 1.0
        rep = self.run_compare(openloop=ol)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V" in s for s in rep["join_inconsistencies"]))

    def test_plateau_flag_disagreement_is_named(self):
        env = copy.deepcopy(self.env)
        m = self.meas(env, ("mos_tt", 27, 1.2), "avs_plateau_delta_db")
        m["value"], m["status"] = 0.2, "fail"
        rep = self.run_compare(env)
        self.assertTrue(any("mos_tt_27C_1.20V plateau_guard" in s for s in rep["out_of_tolerance"]))


class TestBoundVerdicts(Base):
    def test_genuine_bound_miss_is_preserved_not_hidden(self):
        # Both paths agree the point misses: a miss is a result, no disagreement.
        k = ("mos_ff", 125, 1.32)
        h = copy.deepcopy(self.harness)
        ol = copy.deepcopy(self.openloop)
        shift = h[k]["psrr_db"] - 1.0  # drive PSRR to 1.0 dB (< 1.87)
        for d in (h, ol):
            d[k]["av0_db"] -= shift
        h[k]["psrr_db"] -= shift
        rep = C.compare(self.tool(), h, ol)
        # tool Avs unchanged, Av0 lowered -> tool PSRR = 1.0 as well.
        p = next(p for p in rep["points"] if p["point_id"] == "mos_ff_125C_1.32V")
        self.assertFalse(p["row"]["tool_pass"])
        self.assertFalse(p["row"]["harness_pass"])
        self.assertTrue(p["row"]["agree"])
        self.assertEqual(rep["row"]["tool_worst"]["verdict"], "fail")
        self.assertEqual(rep["row"]["harness_worst"]["verdict"], "fail")
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)

    def test_flip_far_from_bound_is_unexplained_and_fails(self):
        env = copy.deepcopy(self.env)
        k = ("mos_tt", 27, 1.2)  # harness PSRR 6.43 dB, 4.5 dB of margin
        self.meas(env, k, "avs0_db")["value"] += 6.0  # tool PSRR drops below 1.87
        rep = self.run_compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 1)
        self.assertEqual(rep["bound_verdict_disagreements"][0]["point"], "mos_tt_27C_1.20V")

    def test_binding_corner_margin_is_inside_the_tolerance(self):
        # Recorded fact the README discusses: the harness's worst point clears the
        # bound by far less than the comparison tolerance, so a tool/harness
        # verdict flip there is reported as 'explained', never as agreement.
        k = ("mos_ff", 125, 1.32)
        margin = self.harness[k]["psrr_db"] - C.PSRR_BOUND_DB
        self.assertGreater(margin, 0)
        self.assertLess(margin, C.TOLERANCES["psrr_db"]["abs"])

    def test_flip_within_tolerance_of_bound_is_explained_not_hidden(self):
        # Put the harness 0.005 dB above the bound; tool 0.015 dB below it.
        k = ("mos_ff", 125, 1.32)
        h = copy.deepcopy(self.harness)
        h[k]["psrr_db"] = C.PSRR_BOUND_DB + 0.005
        env = copy.deepcopy(self.env)
        tool_psrr = C.PSRR_BOUND_DB - 0.015
        self.meas(env, k, "avs0_db")["value"] = self.openloop[k]["av0_db"] - tool_psrr
        rep = C.compare(self.tool(env), h, self.openloop)
        self.assertEqual(len(rep["bound_verdict_disagreements"]), 1)
        self.assertTrue(rep["bound_verdict_disagreements"][0]["explained_by_tolerance"])
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)


class TestCli(Base):
    def _dump(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        self.addCleanup(os.unlink, path)
        return path

    def test_validate_and_compare_exit_codes(self):
        good = self._dump(self.env)
        self.assertEqual(C.main(["validate", good]), 0)
        args = ["compare", "--envelope", good, "--harness-csv", HARNESS_CSV, "--openloop-csv", OPENLOOP_CSV]
        self.assertEqual(C.main(args), 0)
        bad = copy.deepcopy(self.env)
        bad["coverage"]["nothing_checked"] = True
        self.assertEqual(C.main(["validate", self._dump(bad)]), 2)
        self.assertEqual(C.main(["compare", "--envelope", self._dump(bad)] + args[3:]), 2)
        off = copy.deepcopy(self.env)
        self.meas(off, ("mos_sf", 125, 1.08), "avs0_db")["value"] += 0.1
        self.assertEqual(C.main(["compare", "--envelope", self._dump(off)] + args[3:]), 1)


if __name__ == "__main__":
    unittest.main()

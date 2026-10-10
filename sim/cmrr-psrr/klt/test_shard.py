#!/usr/bin/env python3
"""Tests for shard.py, the per-process bridge to the klt 0.5.0 fleet runner (issue #99).

    python3 -m unittest discover -s sim/cmrr-psrr/klt -p 'test_*.py'

Synthetic shard reports are built from the committed harness record, so these
tests exercise the shard/merge logic only; none is evidence about the circuit.
The negative controls (missing shard, duplicate shard, unexpected shard, request
hash mismatch, wrong-process corner, missing/duplicate point, dirty coverage) each
must be refused, and the positive control proves the merged envelope is exactly
the 45 unique ratified points and passes compare.py's validation gate.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compare as C  # noqa: E402
import shard as S  # noqa: E402
import test_compare as T  # noqa: E402


class ShardBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.manifest = S.gen(cls.dir.name, "/opt/pdk")
        full = T._envelope(T._rows(T.HARNESS_CSV))
        cls.full = full
        cls.reports = {}
        for proc in C.PROCESSES:
            r = copy.deepcopy(full)
            r["corners"] = [c for c in full["corners"] if c["process"] == proc]
            r["corner_count"] = len(r["corners"])
            cls.reports[proc] = r

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def reps(self):
        return copy.deepcopy(self.reports)

    def digests(self):
        return {s["process"]: s["request_sha256"] for s in self.manifest["shards"]}


class TestGen(ShardBase):
    def test_shards_partition_the_45_points(self):
        keys = [k for s in self.manifest["shards"] for k in s["keys"]]
        self.assertEqual(len(keys), 45)
        self.assertEqual(sorted(keys), sorted(C.key_str(k) for k in C.expected_keys()))

    def test_shard_requests_differ_from_master_only_where_the_runner_forces_it(self):
        master = T._request()
        for s in self.manifest["shards"]:
            with open(os.path.join(self.dir.name, s["request"])) as f:
                req = json.load(f)
            self.assertEqual(req["corners"]["process"], [s["process"]])
            for axis in ("supply_v", "temperature_c"):
                self.assertEqual(req["corners"][axis], master["corners"][axis])
            self.assertEqual(req["measurements"], master["measurements"])
            self.assertEqual(req["analysis"], master["analysis"])
            self.assertEqual(req["models"]["lib"], "libs.tech/ngspice/models/cornerMOSlv.lib")
            self.assertEqual(req["backend"], "batch")
            for opt in S.RUNNER_UNKNOWN_OPTIONS:
                self.assertNotIn(opt, req["options"])
            self.assertEqual(req["options"]["timeout_s"], master["options"]["timeout_s"])

    def test_body_inlines_dut_and_selects_cap_corner(self):
        s = self.manifest["shards"][1]
        with open(os.path.join(self.dir.name, s["body"])) as f:
            lines = [ln.strip() for ln in f if not ln.startswith("*")]
        self.assertFalse([ln for ln in lines if ln.lower().startswith(".include")])
        self.assertNotIn(".end", [ln.lower() for ln in lines])
        self.assertEqual(sum(ln.startswith("XM") for ln in lines), 8)
        self.assertIn('.lib "/opt/pdk/ihp-sg13g2/libs.tech/ngspice/models/cornerCAP.lib" cap_typ', lines)
        self.assertEqual(sum(ln.startswith("pre_osdi /opt/pdk/ihp-sg13g2/libs.tech/ngspice/osdi/") for ln in lines), 4)
        self.assertEqual(sum(ln.lower() == ".control" for ln in lines), 1)
        self.assertTrue(any(ln.startswith("Vdd ") and " ac 1" in ln for ln in lines))

    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as d2:
            again = S.gen(d2, "/opt/pdk")
        self.assertEqual(again, self.manifest)

    def test_body_without_the_single_dut_include_is_refused(self):
        with self.assertRaises(S.ShardError):
            S.build_body("Vdd vdd 0 dc 1\n", "x\n", "mos_tt", "/opt/pdk", [])


class TestMerge(ShardBase):
    def test_positive_control_merges_to_the_45_point_grid_and_validates(self):
        merged = S.merge(self.manifest, self.reps(), self.digests())
        self.assertEqual(merged["corner_count"], 45)
        idx = C.index_envelope(merged)
        self.assertEqual(sorted(idx), sorted(C.expected_keys()))
        self.assertEqual([C.key_str(C.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"])) for c in merged["corners"]],
                         [C.key_str(k) for k in C.expected_keys()])
        self.assertEqual(merged["passed"] + merged["failed"], 45)

    def test_merge_edits_no_corner(self):
        merged = S.merge(self.manifest, self.reps(), self.digests())
        by_id = {c["corner_id"]: c for c in self.full["corners"]}
        for c in merged["corners"]:
            self.assertEqual(c, by_id[c["corner_id"]])

    def test_aggregates_are_recomputed_over_all_45_corners(self):
        reps = self.reps()
        for r in reps.values():
            for c in r["corners"]:
                for m in c["measurements"]:
                    if m["name"] == "avs_plateau_delta_db":
                        m["margin"] = 0.05 - m["value"]
            r["measurements"] = [{"name": n, "unit": "dB", "limits": T._request()["measurements"][i].get("limits"),
                                  "status": "pass", "worst_case": {"corner_id": "STALE", "value": 0, "margin": None}}
                                 for i, n in enumerate(C.MEASUREMENTS)]
            r["metrics"] = {"sim__corner__count": 9}
        merged = S.merge(self.manifest, reps, self.digests())
        guard = [m for m in merged["measurements"] if m["name"] == "avs_plateau_delta_db"][0]
        self.assertEqual(guard["status"], "fail")
        self.assertEqual(guard["worst_case"]["corner_id"], "mos_ss/vdd=1.080/-40C")
        self.assertNotIn("STALE", json.dumps(merged["measurements"]))
        self.assertEqual(merged["metrics"]["sim__corner__count"], 45)
        self.assertEqual(merged["metrics"]["sim__corner__failed_count"], merged["failed"])
        self.assertEqual(merged["coverage"]["corners_simulated"], 45)

    def test_shard_specific_fields_do_not_stand_for_the_grid(self):
        reps = self.reps()
        for p, r in reps.items():
            r["environment"] = {"netlist_sha256": "h-" + p, "remote": {"job_id": "j-" + p}}
            r["provenance"] = {"input": {"content_hash": "c-" + p}}
        merged = S.merge(self.manifest, reps, self.digests())
        self.assertNotIn("netlist_sha256", merged["environment"])
        self.assertNotIn("input", merged["provenance"])
        self.assertEqual(merged["environment"]["shard_netlist_sha256"]["mos_ff"], "h-mos_ff")
        self.assertEqual([f["job_id"] for f in merged["environment"]["remote"]["fleet"]], ["j-" + p for p in C.PROCESSES])
        self.assertEqual(merged["provenance"]["shard_input_content_hash"]["mos_fs"], "c-mos_fs")

    def test_shard_order_does_not_matter(self):
        reps = self.reps()
        rev = {p: reps[p] for p in reversed(list(reps))}
        a = S.merge(self.manifest, rev, self.digests())
        b = S.merge(self.manifest, self.reps(), self.digests())
        self.assertEqual(a["corners"], b["corners"])

    def test_missing_shard(self):
        reps = self.reps()
        del reps["mos_ff"]
        with self.assertRaisesRegex(S.ShardError, "missing .*mos_ff"):
            S.merge(self.manifest, reps, self.digests())

    def test_unexpected_shard(self):
        reps = self.reps()
        reps["mos_xx"] = reps["mos_tt"]
        with self.assertRaisesRegex(S.ShardError, "unexpected .*mos_xx"):
            S.merge(self.manifest, reps, self.digests())

    def test_duplicate_shard_content_is_a_wrong_process_corner(self):
        # mos_ss's report submitted under mos_tt's name.
        reps = self.reps()
        reps["mos_tt"] = reps["mos_ss"]
        with self.assertRaisesRegex(S.ShardError, "not of this shard"):
            S.merge(self.manifest, reps, self.digests())

    def test_duplicate_point_within_a_shard(self):
        reps = self.reps()
        reps["mos_tt"]["corners"][1] = copy.deepcopy(reps["mos_tt"]["corners"][0])
        with self.assertRaisesRegex(S.ShardError, "duplicate point"):
            S.merge(self.manifest, reps, self.digests())

    def test_missing_point_within_a_shard(self):
        reps = self.reps()
        reps["mos_sf"]["corners"].pop()
        with self.assertRaisesRegex(S.ShardError, "mos_sf"):
            S.merge(self.manifest, reps, self.digests())

    def test_wrong_vdd_key(self):
        reps = self.reps()
        reps["mos_fs"]["corners"][0]["supply_v"]["vdd"] = 1.5
        with self.assertRaisesRegex(S.ShardError, "mos_fs"):
            S.merge(self.manifest, reps, self.digests())

    def test_request_hash_mismatch(self):
        d = self.digests()
        d["mos_ss"] = "0" * 64
        with self.assertRaisesRegex(S.ShardError, "mos_ss: submitted request digest"):
            S.merge(self.manifest, self.reps(), d)

    def test_absent_request_hash_is_a_mismatch(self):
        d = self.digests()
        del d["mos_ff"]
        with self.assertRaisesRegex(S.ShardError, "mos_ff"):
            S.merge(self.manifest, self.reps(), d)

    def test_edited_request_changes_its_digest(self):
        with open(os.path.join(self.dir.name, "request-mos_tt.json")) as f:
            req = json.load(f)
        req["analysis"]["args"] = "dec 20 10m 100meg"
        self.assertNotEqual(S._digest(req), self.digests()["mos_tt"])

    def test_dirty_shard_coverage(self):
        for mutate in (lambda c: c.update(nothing_checked=True), lambda c: c.update(skipped=[{"m": "x"}])):
            reps = self.reps()
            mutate(reps["mos_tt"]["coverage"])
            with self.assertRaisesRegex(S.ShardError, "coverage not clean"):
                S.merge(self.manifest, reps, self.digests())

    def test_klt_error_report(self):
        reps = self.reps()
        reps["mos_tt"] = {"error": "batch submit failed"}
        with self.assertRaisesRegex(S.ShardError, "not a klt sim report"):
            S.merge(self.manifest, reps, self.digests())

    def test_errored_corner_survives_merge_but_fails_validation_gate(self):
        reps = self.reps()
        reps["mos_tt"]["corners"][0]["status"] = "error"
        merged = S.merge(self.manifest, reps, self.digests())
        self.assertEqual(merged["status"], "error")
        with self.assertRaises(C.InputError):
            C.index_envelope(merged)

    def test_manifest_that_does_not_partition_the_grid_is_refused(self):
        bad = copy.deepcopy(self.manifest)
        bad["shards"][0]["keys"].pop()
        with self.assertRaises(S.ShardError):
            S.merge(bad, self.reps(), self.digests())


RECORD = "20261010-094256-469573d"
RECORDS = os.path.join(HERE, "records")


class TestCommittedRecord(unittest.TestCase):
    """The committed evidence re-derives from its own raw shard reports."""

    def test_envelope_is_the_validated_merge_of_the_committed_shards(self):
        sd = os.path.join(RECORDS, RECORD + ".shards")
        with open(os.path.join(sd, "shards.json")) as f:
            manifest = json.load(f)
        reports, digests = {}, {}
        for s in manifest["shards"]:
            with open(os.path.join(sd, f"report-{s['process']}.json")) as f:
                reports[s["process"]] = json.load(f)
            with open(os.path.join(sd, s["request"])) as f:
                digests[s["process"]] = S._digest(json.load(f))
            with open(os.path.join(sd, s["body"]), "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), s["body_sha256"])
        with open(os.path.join(RECORDS, RECORD + ".sim.json")) as f:
            committed = json.load(f)
        self.assertEqual(S.merge(manifest, reports, digests), committed)
        self.assertEqual(len(C.index_envelope(committed)), 45)

    def test_shard_requests_are_what_gen_produces_today(self):
        with tempfile.TemporaryDirectory() as d:
            man = S.gen(d, "/opt/pdk")
        with open(os.path.join(RECORDS, RECORD + ".shards", "shards.json")) as f:
            # The master digest is historical (it moves when the master request's
            # comment is edited); what must stay is every shard request and body.
            self.assertEqual(json.load(f)["shards"], man["shards"])

    def test_committed_comparison_is_clean_and_preserves_the_plateau_miss(self):
        with open(os.path.join(RECORDS, RECORD + ".compare.json")) as f:
            rep = json.load(f)
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["status"], "agree")
        self.assertEqual(rep["out_of_tolerance"], [])
        self.assertEqual(rep["row"]["tool_worst"]["point"], "mos_ff_125C_1.32V")
        self.assertEqual(rep["row"]["tool_plateau_guard"]["status"], "fail")
        self.assertEqual(rep["row"]["tool_plateau_guard"]["worst_case"]["corner_id"], "mos_ss/vdd=1.080_vinp=0.540V/-40C")
        worst = max(abs(m["delta"]) for p in rep["points"] for m in p["metrics"].values())
        self.assertLess(worst, 1e-4)


if __name__ == "__main__":
    unittest.main()

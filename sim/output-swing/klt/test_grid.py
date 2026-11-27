"""Producer controls using the archived harness curves as test inputs."""
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compare
import grid
import two_pass

HERE = Path(__file__).resolve().parent
PID = "mos_tt_27C_1.20V"
RECORD = "20260921-151759-707b34c"


class SwingGrid(unittest.TestCase):
    def test_fine_request_uses_the_serialized_crossing_and_worker_selector(self):
        request = json.loads((HERE / "swing.request.json").read_text())
        vid, (out,) = two_pass.swing_post.parse_wrdata(
            (HERE.parent / "corners" / RECORD / f"{PID}_coarse.csv").read_text(), ("v(out)",))
        coarse = {"pid": PID, "vid": vid, "vout": out, "vcm_v": 0.6,
                  "process": "mos_tt", "temp_c": 27, "vdd_v": 1.2}
        fine = grid.fine_request(request, [coarse])
        rule, = fine["analysis_overrides"]
        self.assertEqual(rule["match"], {"process": "mos_tt", "temperature_c": 27,
                                        "supply_v": {"vdd": 1.2}})
        start, stop, _ = two_pass.fine_window(vid, out, 0.6)
        self.assertEqual(rule["args"].split()[0], "Vid")
        self.assertEqual(list(map(float, rule["args"].split()[1:])), [start, stop, 1e-5])
        self.assertEqual(request["analysis"]["args"].split(), ["Vid", "-0.1", "0.1", "0.0005"])

    def test_baseline_is_selected_by_simulated_dut(self):
        dut = compare.E.sha256_file(HERE.parent / "netlist-snapshots" / RECORD / grid.DUT.name)
        self.assertEqual(compare.swing_baseline(HERE.parent, dut).stem, RECORD)
        self.assertIsNone(compare.swing_baseline(HERE.parent, "0" * 64))


class ArchivedCurves(unittest.TestCase):
    """Exercise the producer/reader boundary with archived curves in fixture envelopes.

    The envelopes describe a historical single-pass batch run. Only their
    shape is reused here. These fixtures are never fleet evidence.
    """
    points = (compare.NOMINAL_KEY, ("mos_ss", 125, 1.08))

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        here = root / grid.BENCH.parent
        here.mkdir(parents=True)
        for name in ("swing.request.json", "swing.nominal.request.json", grid.BENCH.name):
            shutil.copyfile(HERE / name, here / name)
        (root / grid.DUT).parent.mkdir(parents=True)
        shutil.copyfile(HERE.parent / "netlist-snapshots" / RECORD / grid.DUT.name, root / grid.DUT)
        for name in ("records", "netlist-snapshots"):
            (here.parent / name).symlink_to(HERE.parent / name, target_is_directory=True)
        for name, value in (("ROOT", root), ("HERE", here), ("POINTS", self.points)):
            self.enterContext(patch.object(grid, name, value))
        self.bundle = root / "bundle"
        self.capture()

    def capture(self):
        grid.coarse_request(self.bundle)
        self.collect_fixture_jobs()

    def collect_fixture_jobs(self):
        self.submit("coarse")
        self.emit("coarse")
        passes = grid.extract(self.bundle, "coarse", grid.ROOT / "coarse")
        grid.write(self.bundle / "fine.request.json",
                   grid.fine_request(grid.read(self.bundle / "coarse.request.json"), passes))
        self.submit("fine")
        self.emit("fine")

    def submit(self, phase):
        # klt --submit-only uses the canonical request digest without capacity flags.
        req = grid.read(self.bundle / f"{phase}.request.json")
        digest = hashlib.sha256(json.dumps(req, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        out = self.bundle / phase
        out.mkdir()
        grid.write(out / "batch-receipt.json", {"job_id": f"{self.bundle.name}-{phase}", "request_sha256": digest})

    def emit(self, phase):
        req = grid.read(self.bundle / f"{phase}.request.json")
        env = grid.read(HERE / "records/20261101-010941-b7a1a86.sim.json")
        env["environment"]["netlist_sha256"] = compare.E.sha256_file(self.bundle / grid.BENCH)
        for item in env["environment"]["netlist_closure"]:
            retained = self.bundle / item["path"]
            item.update(path=str(retained.relative_to(grid.ROOT)), sha256=compare.E.sha256_file(retained))
        env["environment"]["remote"]["job_id"] = f"{self.bundle.name}-{phase}"
        corners = []
        for corner in env["corners"]:
            supply = corner["supply_v"]
            key = (corner["process"], corner["temperature_c"], supply["vdd"])
            if key not in grid.POINTS:
                continue
            pid = compare.key_str(key)
            raw = HERE.parent / "corners" / RECORD / f"{pid}_{phase}.csv"
            vectors = two_pass.swing_post.COARSE_VECTORS
            if phase == "fine":
                vectors = two_pass.swing_post.FINE_VECTORS
                match = {"process": key[0], "temperature_c": key[1], "supply_v": {"vdd": key[2]}}
                corner["analysis_args"], = [r["args"] for r in req["analysis_overrides"] if r["match"] == match]
            else:
                corner.update(status="pass", measurements=[])
            vid, cols = two_pass.swing_post.parse_wrdata(raw.read_text(), vectors)
            wf = grid.ROOT / phase / (pid + ".json")
            wf.parent.mkdir(exist_ok=True)
            grid.write(wf, {"variables": [{"name": v} for v in ("v(v-sweep)", "v(id)", *vectors)],
                            "points": list(zip(vid, vid, *cols))})
            corner["artifacts"]["waveform"] = str(wf)
            corners.append(corner)
        env.update(corner_count=len(corners), corners=corners)
        if phase == "coarse":
            env.update(status="pass", measurements=[], passed=len(corners), failed=0)
            env["coverage"]["capture_only"] = True
        grid.write(self.bundle / f"{phase}.sim.json", env)


class FullGridAdmission(ArchivedCurves):
    points = compare.POINT_SETS["grid"]

    def test_capture_compare_replay_and_admit(self):
        sys.path.insert(0, str(HERE.parents[2] / "signoff/characterization"))
        self.addCleanup(sys.path.remove, sys.path[0])
        import records

        self.assertEqual(grid.finish(self.bundle, grid.ROOT / "fine"), 0)
        report = grid.read(self.bundle / "compare.json")
        self.assertEqual(report["points_compared"], len(self.points))
        low = next(p for p in report["points"] if p["point_id"] == "mos_ss_125C_1.08V")
        self.assertEqual(low["rows"]["swing_span_v"]["tool_verdict"], "fail")
        self.assertEqual(grid.finish(self.bundle, replay=True), 0)
        spec = grid.read(self.bundle / "selection.json")
        project = HERE.parents[2]
        selection = grid.read(project / "signoff/characterization/selection.json")
        state = records.load_record(grid.ROOT, "output-swing", spec, selection["grids"]["pvt45"],
                                    {"pin": grid.read(project / "sim/pdk.json"), "ngspice": "ngspice-46"})
        self.assertEqual(state["errors"], [])
        self.assertEqual(len(state["valid_ids"]), 45)


class WorkerEnvironmentAdmission(ArchivedCurves):
    points = (("mos_tt", 27, 1.08), compare.NOMINAL_KEY)

    def setUp(self):
        super().setUp()
        project = HERE.parents[2]
        sys.path.insert(0, str(project / "signoff/characterization"))
        self.addCleanup(sys.path.remove, sys.path[0])
        self.pvt = grid.read(project / "signoff/characterization/selection.json")["grids"]["pvt45"]
        self.pvt["axes"] = {"corner": ["mos_tt"], "temp": ["27"], "vdd": ["1.08", "1.20"]}
        self.env = {"pin": grid.read(project / "sim/pdk.json"), "ngspice": "ngspice-46"}

    def load(self, spec):
        import records

        return records.load_record(grid.ROOT, "output-swing", spec, self.pvt, self.env)

    def finish_and_admit(self):
        self.assertEqual(grid.finish(self.bundle, grid.ROOT / "fine"), 0)
        spec = grid.read(self.bundle / "selection.json")
        state = self.load(spec)
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["source"]["swing_two_pass"]["status"], "verified")
        return spec

    def test_selection_from_individually_valid_bundles(self):
        # Different collecting clients can recover passes from the same worker build.
        path = self.bundle / "fine.sim.json"
        fine = grid.read(path)
        fine["environment"]["engine_build"]["binary_sha256"] = "a" * 64
        grid.write(path, fine)
        first = self.finish_and_admit()

        self.bundle = grid.ROOT / "second"
        self.capture()
        for phase in ("coarse", "fine"):
            path = self.bundle / f"{phase}.sim.json"
            result = grid.read(path)
            simulator = result["environment"]["remote"]["worker_environment"]["simulator"]
            simulator["version_banner"] = simulator["version_banner"].replace("Oct  1", "Oct  2")
            grid.write(path, result)
        second = self.finish_and_admit()

        # Swap the hash-pinned fine file, then the entire pair at the same corner.
        for phase in ("fine", "coarse"):
            with self.subTest(swapped=phase):
                first["swing_two_pass"]["files"][PID][phase] = second["swing_two_pass"]["files"][PID][phase]
                state = self.load(first)
                self.assertEqual(state["source"]["swing_two_pass"]["status"], "error")
                self.assertTrue(any(PID in e and "worker_version_banner" in e for e in state["errors"]),
                                state["errors"])

    def test_selection_rejects_a_whole_pair_from_another_bench(self):
        selected = self.finish_and_admit()
        self.bundle = grid.ROOT / "four-pf"
        grid.coarse_request(self.bundle)

        # Recreate a submission by the old producer. The 4 pF bench, request,
        # receipts and both result closures agree with one another.
        bench = self.bundle / grid.BENCH
        bench.write_text(bench.read_text().replace("Cload out vss 2e-12", "Cload out vss 4e-12"))
        req = self.bundle / "coarse.request.json"
        grid.write(req, dict(grid.read(req), _comment=grid.submission_inputs(self.bundle)))
        self.collect_fixture_jobs()

        # Replace both existing pins at the first selected corner, so using
        # the first evidence file as the reference would blame the other corner.
        pid = compare.key_str(self.points[0])
        for phase in ("coarse", "fine"):
            passes = grid.extract(self.bundle, phase, grid.ROOT / phase)
            doc, = (p for p in passes if p["pid"] == pid)
            path = self.bundle / f"{pid}_{phase}.json"
            grid.write(path, doc)
            selected["swing_two_pass"]["files"][pid][phase] = grid.pin(path)
        state = self.load(selected)
        self.assertEqual(state["source"]["swing_two_pass"]["status"], "error")
        self.assertEqual(len(state["errors"]), 1, state["errors"])
        self.assertIn(f"point {pid}:", state["errors"][0])
        self.assertIn("bench_sha256", state["errors"][0])

        with self.assertRaisesRegex(compare.InputError, "bench_sha256"):
            grid.finish(self.bundle, grid.ROOT / "fine")
        self.assertFalse((self.bundle / "record.md").exists())
        self.assertFalse((self.bundle / "selection.json").exists())
        with self.assertRaisesRegex(compare.InputError, "bench_sha256"):
            grid.finish(self.bundle, replay=True)


class SwingGridControls(ArchivedCurves):
    def test_coarse_request_rejects_unsupported_bench_before_submission(self):
        bench = grid.ROOT / grid.BENCH
        bench.write_text(bench.read_text().replace("Cload out vss 2e-12", "Cload out vss 4e-12"))
        bundle = grid.ROOT / "new-run"
        with self.assertRaisesRegex(compare.InputError, "bench_sha256"):
            grid.coarse_request(bundle)
        self.assertFalse((bundle / "coarse.request.json").exists())

    def test_changed_dut_without_a_baseline_retains_audited_results(self):
        dut = grid.ROOT / grid.DUT
        dut.write_text(dut.read_text().replace("w=3.2u", "w=6.4u", 1))
        self.bundle = grid.ROOT / "changed"
        self.capture()
        self.assertEqual(grid.finish(self.bundle, grid.ROOT / "fine"), 5)
        self.assertEqual(grid.finish(self.bundle, replay=True), 5)
        report = grid.read(self.bundle / "compare.json")
        self.assertIsNone(report["baseline"])
        self.assertFalse(report["verdicts"]["mos_ss_125C_1.08V"]["swing_span_v"])

    def test_recovery_after_dut_edit_uses_the_submitted_snapshot(self):
        (grid.ROOT / grid.DUT).write_text("* edited after submission")
        for phase in ("coarse", "fine"):
            job = f"{self.bundle.name}-{phase}"
            self.assertEqual(grid.submission_job(self.bundle, phase, job), job)
            with self.assertRaisesRegex(compare.InputError, "job ID"):
                grid.submission_job(self.bundle, phase, "another-job")
        self.assertEqual(grid.finish(self.bundle, grid.ROOT / "fine"), 0)

        # The collecting client can regenerate its closure from a changed
        # snapshot. Even a rewritten request cannot match the old receipt.
        shutil.copyfile(grid.ROOT / grid.DUT, self.bundle / grid.DUT)
        for phase in ("coarse", "fine"):
            self.emit(phase)
            with self.assertRaisesRegex(compare.InputError, "submitted bench or DUT"):
                grid.extract(self.bundle, phase)
            path = self.bundle / f"{phase}.request.json"
            grid.write(path, dict(grid.read(path), _comment=grid.submission_inputs(self.bundle)))
            with self.assertRaisesRegex(compare.InputError, "submission receipt"):
                grid.extract(self.bundle, phase)

    def test_result_job_and_submit_receipt_are_required(self):
        path = self.bundle / "fine.sim.json"
        envelope = grid.read(path)
        envelope["environment"]["remote"]["job_id"] = "another-job"
        grid.write(path, envelope)
        with self.assertRaisesRegex(compare.InputError, "job ID"):
            grid.finish(self.bundle, grid.ROOT / "fine")
        (self.bundle / "fine/batch-receipt.json").unlink()
        with self.assertRaises(FileNotFoundError):
            grid.submission_job(self.bundle, "fine")

    def test_compares_worker_build_banners_independently_of_client_digest(self):
        path = self.bundle / "fine.sim.json"
        envelope = grid.read(path)
        env = envelope["environment"]
        worker = env["remote"]["worker_environment"]["simulator"]
        banner = worker["version_banner"]
        worker["version_banner"] = banner.replace("Oct  1", "Oct  2")
        grid.write(path, envelope)
        with self.assertRaisesRegex(compare.InputError, "worker_version_banner"):
            grid.finish(self.bundle, grid.ROOT / "fine")
        worker["version_banner"] = ""
        grid.write(path, envelope)
        with self.assertRaisesRegex(compare.InputError, "worker ngspice build banner"):
            grid.finish(self.bundle, grid.ROOT / "fine")
        worker["version_banner"] = banner
        env["engine_build"]["binary_sha256"] = "a" * 64
        grid.write(path, envelope)
        self.assertEqual(grid.finish(self.bundle, grid.ROOT / "fine"), 0)
        evidence = grid.read(self.bundle / f"{PID}_fine.json")
        self.assertEqual(evidence["client_engine_sha256"], "a" * 64)
        self.assertEqual(evidence["worker_version_banner"], banner)

    def test_supporting_field_discrepancy_names_the_field_and_corner(self):
        # Give the fixture its own CSV, preserving the original snapshot and DUT.
        records = grid.HERE.parent / "records"
        records.unlink()
        records.mkdir()
        path = records / f"{RECORD}.csv"
        with (HERE.parent / "records" / path.name).open(newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
        next(row for row in rows if row["point_id"] == PID)["ivdd_center_a"] = "0.25"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, reader.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        self.assertEqual(grid.finish(self.bundle, grid.ROOT / "fine"), 5)
        deviations = grid.read(self.bundle / "compare.json")["out_of_tolerance"]
        self.assertEqual(len(deviations), 1)
        self.assertIn(f"{PID} ivdd_center_a", deviations[0])

    def test_rejects_wrong_worker_window_and_altered_waveform(self):
        path = self.bundle / "fine.sim.json"
        env = grid.read(path)
        corner = env["corners"][0]
        corner["analysis_args"] = "Vid -0.01 0.04 10e-6"
        grid.write(path, env)
        with self.assertRaisesRegex(two_pass.PairError, "point mos_.*fine sweep"):
            grid.finish(self.bundle, grid.ROOT / "fine")
        self.emit("fine")
        grid.finish(self.bundle, grid.ROOT / "fine")
        wf = self.bundle / f"{PID}_fine.waveform.json"
        doc = grid.read(wf)
        doc["points"][0][-1] += 1e-9
        grid.write(wf, doc)
        with self.assertRaisesRegex(two_pass.PairError, PID):
            grid.finish(self.bundle, replay=True)


if __name__ == "__main__":
    unittest.main()

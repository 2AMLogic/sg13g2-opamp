"""Producer controls using the archived harness curves as test inputs."""
import csv
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
        grid.coarse_request(self.bundle)
        self.emit("coarse")
        passes = grid.extract(self.bundle, "coarse", root / "coarse")
        grid.write(self.bundle / "fine.request.json",
                   grid.fine_request(grid.read(self.bundle / "coarse.request.json"), passes))
        self.emit("fine")

    def emit(self, phase):
        req = grid.read(self.bundle / f"{phase}.request.json")
        env = grid.read(HERE / "records/20261101-010941-b7a1a86.sim.json")
        for item in env["environment"]["netlist_closure"]:
            item["path"] = "bundle/" + item["path"]
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


class SwingGridControls(ArchivedCurves):
    def test_changed_dut_without_a_baseline_retains_audited_results(self):
        snapshot = self.bundle / grid.DUT
        snapshot.write_text(snapshot.read_text().replace("w=3.2u", "w=6.4u", 1))
        digest = compare.E.sha256_file(snapshot)
        self.assertNotEqual(digest, compare.E.sha256_file(grid.ROOT / grid.DUT))
        for phase in ("coarse", "fine"):
            path = self.bundle / f"{phase}.sim.json"
            envelope = grid.read(path)
            for item in envelope["environment"]["netlist_closure"]:
                if item["path"].endswith(str(grid.DUT)):
                    item["sha256"] = digest
            grid.write(path, envelope)
        self.assertEqual(grid.finish(self.bundle, grid.ROOT / "fine"), 5)
        self.assertEqual(grid.finish(self.bundle, replay=True), 5)
        report = grid.read(self.bundle / "compare.json")
        self.assertIsNone(report["baseline"])
        self.assertFalse(report["verdicts"]["mos_ss_125C_1.08V"]["swing_span_v"])

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

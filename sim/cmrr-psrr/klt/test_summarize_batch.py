"""Exercise the offline record writer with the selected, same-DUT direct envelopes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CMRR = HERE / "records/20261125-011804-02d78dd.cmrr.sim.json"
PSRR = HERE / "records/20261125-011604-02d78dd.direct.sim.json"


class BatchRecordWriter(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        bench = self.root / "sim/cmrr-psrr"
        self.inputs = bench / "klt/records"
        self.inputs.mkdir(parents=True)
        self.out = bench / "records"
        self.runner = bench / "run_klt_record.sh"
        shutil.copy(HERE.parent / self.runner.name, self.runner)
        (bench.parent / "record-paths.sh").symlink_to(HERE.parents[1] / "record-paths.sh")
        (bench.parent / "tools").symlink_to(HERE.parents[1] / "tools")
        (bench / "netlist-snapshots").symlink_to(HERE.parent / "netlist-snapshots")
        for name in ("summarize_batch.py", "compare_cmrr_direct.py",
                     "tb_cmrr_direct.body.spice", "tb_psrr_direct.body.spice"):
            shutil.copy(HERE / name, bench / "klt" / name)
        self.restore_inputs()

    def restore_inputs(self):
        for path in (CMRR, PSRR):
            shutil.copy(path, self.inputs / path.name)

    def publish(self, **env):
        return subprocess.run(["bash", self.runner], text=True, capture_output=True, timeout=20,
                              env={**os.environ, "SKIP_RUN": "1", "RECORD_ID": "test", **env})

    def test_incomplete_grids_publish_neither_file_and_can_retry(self):
        for count in (0, 1):
            with self.subTest(count=count):
                for path in (CMRR, PSRR):
                    doc = json.loads(path.read_text())
                    doc.update(corners=doc["corners"][:count], passed=count, corner_count=count)
                    (self.inputs / path.name).write_text(json.dumps(doc))
                result = self.publish()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("need all 45 corners decided", result.stderr)
                self.assertEqual(list(self.out.iterdir()), [])
        self.restore_inputs()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        csv = self.out / "test.csv"
        self.assertEqual(csv.read_bytes(), (HERE.parent / "records/20261125-103814-7fb5ff0.csv").read_bytes())
        md = self.out / "test.md"
        self.assertEqual(md.read_bytes(), (HERE.parent / "records/20261125-103814-7fb5ff0.md").read_bytes())
        before = csv.read_bytes(), md.read_bytes()
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertEqual((csv.read_bytes(), md.read_bytes()), before)

    def test_off_grid_coordinates_are_refused_before_display_rounding(self):
        for path in (CMRR, PSRR):
            for field in ("temp", "vdd"):
                with self.subTest(path=path.name, field=field):
                    self.restore_inputs()
                    doc = json.loads(path.read_text())
                    corner = doc["corners"][0]
                    if field == "temp":
                        corner["temperature_c"] += 0.1
                    else:
                        corner["supply_v"]["vdd"] += 0.0001
                        corner["supply_v"]["vinp"] = corner["supply_v"]["vdd"] / 2
                    (self.inputs / path.name).write_text(json.dumps(doc))
                    result = self.publish()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("outside the expected grid", result.stderr)
                    self.assertEqual(list(self.out.iterdir()), [])

    def assert_refused(self, doc, path, reason):
        self.restore_inputs()
        payload = json.dumps(doc).encode()
        (self.inputs / path.name).write_bytes(payload)
        record_id = hashlib.sha256(payload).hexdigest()
        result = self.publish(RECORD_ID=record_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)
        self.assertFalse((self.out / f"{record_id}.csv").exists())
        self.assertFalse((self.out / f"{record_id}.md").exists())

    def test_inconsistent_gains_publish_neither_file(self):
        for path, rejection in ((CMRR, "cmrr_db"), (PSRR, "psrr_db")):
            for shifted_av0 in (True, False):
                with self.subTest(path=path.name, shifted_av0=shifted_av0):
                    doc = json.loads(path.read_text())
                    corner = doc["corners"][-1]
                    meas = {m["name"]: m for m in corner["measurements"]}
                    meas[rejection]["value"] += 0.5
                    if shifted_av0:
                        meas["av0_db"]["value"] += 0.5
                    self.assert_refused(doc, path, "Av0" if shifted_av0 else rejection)

    def test_published_load_requires_the_simulated_bench(self):
        for path in (CMRR, PSRR):
            for field in ("all hashes", "netlist.path", "netlist_closure", "netlist_sha256", "input.content_hash"):
                with self.subTest(path=path.name, field=field):
                    doc = json.loads(path.read_text())
                    rel = doc["netlist"]["path"]
                    body = (self.root / rel).read_bytes().replace(b"vss 2e-12", b"vss 5e-12")
                    digest = hashlib.sha256(body).hexdigest()
                    env = doc["environment"]
                    if field in ("all hashes", "netlist_closure"):
                        next(e for e in env["netlist_closure"] if e["path"] == rel)["sha256"] = digest
                    if field in ("all hashes", "netlist_sha256"):
                        env["netlist_sha256"] = digest
                    if field in ("all hashes", "input.content_hash"):
                        doc["provenance"]["input"]["content_hash"] = "sha256:" + digest
                    if field == "netlist.path":
                        doc["netlist"]["path"] = "other/" + Path(rel).name
                    self.assert_refused(doc, path, "netlist_closure" if field == "all hashes" else field)

    def test_matching_body_hashes_require_two_2pf_output_loads(self):
        for path in (CMRR, PSRR):
            original = json.loads(path.read_text())["netlist"]["path"]
            body = self.root / original
            committed = body.read_text()
            for name, altered in (
                    ("both 5 pF", committed.replace("vss 2e-12", "vss 5e-12")),
                    ("copy B 5 pF", committed.replace("Cloadb outb vss 2e-12", "Cloadb outb vss 5e-12")),
                    ("duplicated A", committed.replace("Cloadb outb", "Cloada outa")),
                    ("wrong output", committed.replace("Cloadb outb", "Cloadb outa"))):
                with self.subTest(path=path.name, case=name):
                    body.write_text(altered)
                    doc = json.loads(path.read_text())
                    digest = hashlib.sha256(body.read_bytes()).hexdigest()
                    env = doc["environment"]
                    next(e for e in env["netlist_closure"] if e["path"] == original)["sha256"] = digest
                    env["netlist_sha256"] = digest
                    doc["provenance"]["input"]["content_hash"] = "sha256:" + digest
                    self.assert_refused(doc, path, "2 pF")
            body.write_text(committed)

    def test_model_input_mismatch_publishes_neither_file(self):
        for path in (CMRR, PSRR):
            for field, name in (("staged_model_inputs", "sg13g2_moslv_mod.lib"),
                                ("osdi_preload_runner_resolved", "psp103.osdi")):
                with self.subTest(path=path.name, name=name):
                    self.restore_inputs()
                    doc = json.loads(path.read_text())
                    entries = doc["environment"][field]
                    item = next(e for e in entries if Path(e.get("entry") or e["name"]).name == name)
                    item["sha256"] = "0" * 64
                    (self.inputs / path.name).write_text(json.dumps(doc))
                    result = self.publish()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(name, result.stderr)
                    self.assertEqual(list(self.out.iterdir()), [])

    def test_contradictory_simulator_banner_publishes_neither_file(self):
        for path in (CMRR, PSRR):
            for source in ("engine_build", "worker"):
                with self.subTest(path=path.name, source=source):
                    self.restore_inputs()
                    doc = json.loads(path.read_text())
                    env = doc["environment"]
                    if source == "engine_build":
                        env["engine_build"]["version_banner"] = "** ngspice-470 : build"
                    else:
                        job = env["remote"]["fleet"][-1]
                        job["worker_environment"]["simulator"]["version_banner"] = "** ngspice-45 : worker"
                    (self.inputs / path.name).write_text(json.dumps(doc))
                    result = self.publish(RECORD_ID=f"{path.stem}-{source}")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(source, result.stderr)
                    self.assertIn("ngspice-47", result.stderr)
                    self.assertEqual(list(self.out.iterdir()), [])

    def test_matching_dut_hashes_must_also_match_the_named_snapshot(self):
        for path in (CMRR, PSRR):
            doc = json.loads(path.read_text())
            dut = next(e for e in doc["environment"]["netlist_closure"] if e["path"] == "design/netlist/opamp_core.spice")
            dut["sha256"] = "a" * 64
            (self.inputs / path.name).write_text(json.dumps(doc))
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("netlist-snapshots/20260921-151815-707b34c/opamp_core.spice", result.stderr)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_duplicate_closure_path_cannot_hide_a_different_dut(self):
        doc = json.loads(CMRR.read_text())
        closure = doc["environment"]["netlist_closure"]
        dut = next(e for e in closure if e["path"] == "design/netlist/opamp_core.spice")
        closure.insert(0, dict(dut, sha256="a" * 64))
        (self.inputs / CMRR.name).write_text(json.dumps(doc))
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate file design/netlist/opamp_core.spice", result.stderr)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_extra_supply_axis_publishes_neither_file(self):
        for path in (CMRR, PSRR):
            with self.subTest(path=path.name):
                self.restore_inputs()
                doc = json.loads(path.read_text())
                doc["corners"][0]["supply_v"]["vss"] = 0.12
                (self.inputs / path.name).write_text(json.dumps(doc))
                result = self.publish(RECORD_ID=path.stem)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("vss", result.stderr)
                self.assertEqual(list(self.out.iterdir()), [])

    def test_second_publication_failure_rolls_back_only_our_csv(self):
        # Create a competing destination after the reservation and preflight.
        real_ln = shutil.which("ln")
        ln = self.root / "ln"
        ln.write_text('#!/bin/sh\ncase "$2" in *.md) echo prior > "$2";; esac\n'
                      f'exec "{real_ln}" "$@"\n')
        ln.chmod(0o755)
        result = self.publish(PATH=f"{self.root}:{os.environ['PATH']}")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.out.iterdir()), [self.out / "test.md"])
        self.assertEqual((self.out / "test.md").read_text(), "prior\n")

"""Exercise the offline record writer with the selected, same-DUT direct envelopes."""
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
        (bench / "klt/summarize_batch.py").symlink_to(HERE / "summarize_batch.py")
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
        self.assertEqual(csv.read_bytes(), (HERE.parent / "records/20261125-011804-02d78dd.csv").read_bytes())
        md = self.out / "test.md"
        self.assertIn("20261015-103521-0f41068", md.read_text())
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

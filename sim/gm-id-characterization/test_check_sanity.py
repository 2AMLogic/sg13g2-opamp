"""Offline regression tests for the gm/ID sweep's typical-corner checks."""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECORD = "20260928-161200-a6fa678"
DEVICES = ("nmos", "pmos")
LENGTHS = ("0.13u", "0.26u", "0.52u", "1.04u")


class SanityChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv_path = HERE / "records" / f"{RECORD}.csv"
        self.log = Path(self.tmp.name) / "sanity_checks.txt"

    def change_typical_rows(self, edit):
        with self.csv_path.open(newline="") as src:
            reader = csv.DictReader(src)
            self.csv_path = Path(self.tmp.name) / "variant.csv"
            with self.csv_path.open("w", newline="") as dst:
                writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
                writer.writeheader()
                for row in reader:
                    if row["corner"] == "mos_tt":
                        edit(row)
                    writer.writerow(row)

    def check_record(self, expected_rc):
        result = subprocess.run(
            [
                sys.executable,
                HERE / "check_sanity.py",
                self.csv_path,
                self.log,
                "--devices",
                *DEVICES,
                "--lengths",
                *LENGTHS,
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, expected_rc, result.stdout + result.stderr)
        self.assertEqual(self.log.read_text(), result.stdout)
        return result.stdout

    def test_committed_record_matches_all_recorded_verdicts(self):
        expected = HERE / "corners" / RECORD / "sanity_checks.txt"
        self.assertEqual(self.check_record(0), expected.read_text())

    def test_missing_all_typical_overdrives(self):
        def clear_threshold(row):
            row["vth_v"] = row["overdrive_v"] = ""

        self.change_typical_rows(clear_threshold)
        log = self.check_record(1)
        self.assertNotIn("PASS", log)
        for device in DEVICES:
            for length in LENGTHS:
                for metric in ("gm/ID", "fT"):
                    self.assertRegex(
                        log, rf"FAIL {metric} .*device={device} length={length}\b"
                    )

    def test_only_shortest_length_in_ft_window(self):
        def clear_window(row):
            if (
                row["length_um"] != LENGTHS[0]
                and 0.25 <= float(row["overdrive_v"]) <= 0.35
            ):
                row["overdrive_v"] = ""

        self.change_typical_rows(clear_window)
        log = self.check_record(1)
        self.assertEqual(log.count("PASS gm/ID"), 8)
        self.assertNotIn("PASS fT", log)
        for device in DEVICES:
            for length in LENGTHS[1:]:
                self.assertRegex(log, rf"FAIL fT .*device={device} length={length}\b")

    def test_peak_at_final_overdrive_has_no_comparison(self):
        def move_peak(row):
            if (
                row["device"] == "pmos"
                and row["length_um"] == "0.52u"
                and row["vgs_v"] == "1.1500"
            ):
                row["gm_id_per_v"] = "100"

        self.change_typical_rows(move_peak)
        log = self.check_record(1)
        self.assertRegex(log, r"FAIL gm/ID .*device=pmos length=0\.52u\b")
        self.assertEqual(log.count("PASS gm/ID"), 7)
        self.assertEqual(log.count("PASS fT"), 2)

    def test_one_length_without_finite_ft(self):
        def clear_ft(row):
            if row["device"] == "pmos" and row["length_um"] == "0.26u":
                row["ft_hz"] = "nan"

        self.change_typical_rows(clear_ft)
        log = self.check_record(1)
        self.assertRegex(log, r"FAIL fT .*device=pmos length=0\.26u\b")
        self.assertEqual(log.count("PASS gm/ID"), 8)
        self.assertRegex(log, r"PASS fT .*device=nmos")
        self.assertEqual(log.count("FAIL"), 1)

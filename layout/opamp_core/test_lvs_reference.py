"""Negative controls for lvs_reference.py's freshness check.

Run: python3 -m unittest discover -s layout/opamp_core -p 'test_lvs_reference.py' -v
Needs only the `klayout` python module (generate.py imports it); no PDK, klt
or simulator. Never writes to the repo.
"""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate as gen  # noqa: E402
import lvs_reference as lr  # noqa: E402


class ReferenceFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def mutated_netlist(self, pattern: str, repl: str) -> Path:
        text = gen.NETLIST_PATH.read_text(encoding="utf-8")
        new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        self.assertEqual(n, 1, f"mutation {pattern!r} did not apply")
        path = self.tmp / "opamp_core.spice"
        path.write_text(new, encoding="utf-8")
        return path

    def build_against(self, path: Path) -> str:
        real = lr.verify_against_netlist
        with mock.patch.object(lr, "verify_against_netlist", lambda: real(path)):
            return lr.build_reference()

    def test_committed_reference_is_current(self):
        self.assertEqual(
            lr.build_reference(), lr.REFERENCE_PATH.read_text(encoding="utf-8")
        )

    def test_unchanged_netlist_copy_builds(self):
        path = self.tmp / "copy.spice"
        shutil.copy2(gen.NETLIST_PATH, path)
        self.assertEqual(self.build_against(path), lr.build_reference())

    def test_changed_device_width_is_refused(self):
        # XM5's first `W=` value is scaled; tables/reference are untouched.
        path = self.mutated_netlist(
            r"^(XM5\b[^\n]*?\bw=)([0-9.]+)", r"\g<1>9"
        )
        with self.assertRaises(SystemExit) as cm:
            self.build_against(path)
        self.assertIn("disagree", str(cm.exception))

    def test_changed_device_net_is_refused(self):
        path = self.mutated_netlist(r"^(XM1\s+\S+\s+\S+)\s+\S+", r"\g<1> vdd")
        with self.assertRaises(SystemExit) as cm:
            self.build_against(path)
        self.assertIn("disagree", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

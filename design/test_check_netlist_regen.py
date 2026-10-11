"""Offline tests for the comparison logic of check_netlist_regen.py (no xschem)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_netlist_regen as c  # noqa: E402

BASE = """** sch_path: /a/b/opamp_core.sch
**.subckt opamp_core vdd vss inn inp out ibias

*.iopin vdd
XM1 d1 inn tail vss sg13_lv_nmos w=3.2u l=0.13u ng=1 m=1
XM3 d1 d1 vdd vdd sg13_lv_pmos w=1.04u l=0.52u ng=1 m=1
**.ends
.end
"""


class Compare(unittest.TestCase):
    def test_committed_netlist_self_matches(self):
        text = c.COMMITTED.read_text()
        self.assertEqual(c.compare(text, text), "")

    def test_comment_blank_and_path_change_pass(self):
        new = BASE.replace("/a/b", "/other/host").replace("*.iopin vdd", "* note\n\n*.iopin vdd") + "\n\n"
        self.assertEqual(c.compare(BASE, new), "")

    def test_width_change_fails_with_diff(self):
        d = c.compare(BASE, BASE.replace("w=3.2u", "w=6.4u"))
        self.assertIn("-XM1", d)
        self.assertIn("+XM1", d)
        self.assertIn("w=6.4u", d)

    def test_reconnect_fails(self):
        d = c.compare(BASE, BASE.replace("XM3 d1 d1 vdd", "XM3 d1 d2 vdd"))
        self.assertTrue(d)

    def test_statement_order_matters(self):
        lines = BASE.splitlines()
        i, j = lines.index(next(l for l in lines if l.startswith("XM1"))), lines.index(
            next(l for l in lines if l.startswith("XM3")))
        lines[i], lines[j] = lines[j], lines[i]
        self.assertTrue(c.compare(BASE, "\n".join(lines)))

    def test_removed_device_fails(self):
        self.assertTrue(c.compare(BASE, "\n".join(l for l in BASE.splitlines() if not l.startswith("XM3"))))


class ToolFailures(unittest.TestCase):
    def test_stderr_patterns(self):
        self.assertTrue(c.check_stderr("Error: symbol sg13_lv_nmos.sym not found"))
        self.assertTrue(c.check_stderr("xschemrc: no ihp-sg13g2 install found under PDK_ROOT"))
        self.assertFalse(c.check_stderr("MODELS_NGSPICE: /x/models\n"))

    def test_no_xschem(self):
        with mock.patch.object(c.shutil, "which", return_value=None):
            with self.assertRaises(c.ToolFailure):
                c.run_xschem(c.SCHEMATIC, Path("/tmp"), {"PDK_ROOT": "/x"})

    def test_no_pdk_root(self):
        with mock.patch.object(c.shutil, "which", return_value="/usr/bin/xschem"):
            with self.assertRaises(c.ToolFailure):
                c.run_xschem(c.SCHEMATIC, Path("/tmp"), {})

    def _run(self, rc, stderr, write):
        with tempfile.TemporaryDirectory() as pdk, tempfile.TemporaryDirectory() as out:
            (Path(pdk) / "ihp-sg13g2" / "libs.tech" / "xschem").mkdir(parents=True)

            def fake(cmd, **kw):
                if "--version" in cmd:
                    return mock.Mock(returncode=0, stdout="XSCHEM V0\n", stderr="")
                if write:
                    (Path(out) / "opamp_core.spice").write_text(BASE)
                return mock.Mock(returncode=rc, stdout="", stderr=stderr)

            with mock.patch.object(c.shutil, "which", return_value="/usr/bin/xschem"), \
                    mock.patch.object(c.subprocess, "run", side_effect=fake):
                return c.run_xschem(c.SCHEMATIC, Path(out), {"PDK_ROOT": pdk, "PDK": "ihp-sg13g2"})

    def test_ok(self):
        path, ver = self._run(0, "", True)
        self.assertEqual(ver, "XSCHEM V0")

    def test_nonzero_exit_fails(self):
        with self.assertRaises(c.ToolFailure):
            self._run(1, "", True)

    def test_missing_output_fails(self):
        with self.assertRaisesRegex(c.ToolFailure, "no netlist"):
            self._run(0, "", False)

    def test_xschem_error_with_zero_exit_fails(self):
        with self.assertRaises(c.ToolFailure):
            self._run(0, "Error: missing symbol foo.sym", True)


if __name__ == "__main__":
    unittest.main()

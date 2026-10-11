"""Offline controls for the cross-record AC join admission check (#224).

Fixtures only (a fake PDK install from test_env_drift_lifecycle, tiny source
records); no PDK, ngspice or klt is needed:

  python3 -m unittest discover -s sim/tools -p 'test_ac_join_admission.py' -v
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SIM_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import ac_join_admission as aj  # noqa: E402
import env_identity as ei  # noqa: E402
from test_env_drift_lifecycle import MOS_INC, NGSPICE, PDK, PIN, make_install  # noqa: E402

CORNERS, TEMPS, VDDS = ["mos_tt", "mos_ss"], ["27"], ["1.08", "1.20"]
COLS = ["av0_db", "vout_dc_v"]
HEADER = "point_id,corner,temp_c,vdd_v,vcm_v,op_pass,vout_dc_v,av0_db"
SID = "20260101-000000-aaaaaaa"
DUT = "* dut v1\n"


def row(c, t, v, vcm=None, op="1", av0="43.0"):
    vcm = vcm if vcm is not None else float(v) / 2
    return f"{c}_{t}C_{v}V,{c},{t},{v},{vcm},{op},0.5,{av0}"


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.pdk_a = root / "pdk_a"
        make_install(self.pdk_a)
        self.consumer_env = ei.capture(self.pdk_a, PDK, PIN, "consumer-1", NGSPICE)
        self.consumer_snap = root / "consumer_opamp_core.spice"
        self.consumer_snap.write_text(DUT)
        self.exp = root / "open-loop-ac"
        self.rows = [row(c, t, v) for c in CORNERS for t in TEMPS for v in VDDS]
        self.cl = "2e-12"
        self.sidecar = copy.deepcopy(ei.capture(self.pdk_a, PDK, PIN, SID, NGSPICE))
        self.dut = DUT
        self.drop_snapshot = None

    def write(self):
        rec = self.exp / "records"
        snap = self.exp / "netlist-snapshots" / SID
        rec.mkdir(parents=True, exist_ok=True)
        snap.mkdir(parents=True, exist_ok=True)
        (rec / f"{SID}.csv").write_text(HEADER + "\n" + "\n".join(self.rows) + "\n")
        (snap / "opamp_core.spice").write_text(self.dut)
        for c in CORNERS:
            for t in TEMPS:
                for v in VDDS:
                    (snap / f"{c}_{t}C_{v}V.spice").write_text(f"* x\nCload out vss {self.cl}\n.end\n")
        if self.sidecar is not None:
            (rec / f"{SID}.env.json").write_text(ei.canonical_json(self.sidecar))
        return rec / f"{SID}.csv"

    def admit(self, cl=2e-12):
        return aj.admit(self.write(), self.consumer_env, self.consumer_snap, "consumer-1", PIN, cl, 0.5,
                        CORNERS, TEMPS, VDDS, COLS)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = Fixture(Path(self._tmp.name))

    def assertRejected(self, needle, **kw):
        errs, prov = self.fx.admit(**kw)
        self.assertIsNone(prov)
        self.assertTrue(any(needle in e for e in errs), f"{needle!r} not in {errs}")
        return errs

    def test_matching_source_admitted_with_bound_hashes(self):
        errs, prov = self.fx.admit()
        self.assertEqual(errs, [])
        self.assertEqual(prov["schema"], aj.SCHEMA)
        src = prov["source"]
        self.assertEqual(src["record_id"], SID)
        csv_path = self.fx.exp / "records" / f"{SID}.csv"
        self.assertEqual(src["csv_sha256"], aj.sha256_file(csv_path))
        self.assertEqual(src["env_sidecar_sha256"], aj.sha256_file(csv_path.with_suffix(".env.json")))
        self.assertEqual(src["dut_snapshot_sha256"], prov["consumer"]["dut_snapshot_sha256"])
        self.assertEqual(src["identity_sha256"], prov["consumer"]["identity_sha256"])
        self.assertEqual(prov["basis"]["points"], 4)

    def test_host_path_only_difference_is_compatible(self):
        # Same bytes under another PDK root: identity is install-relative.
        pdk_b = self.fx.root / "elsewhere"
        make_install(pdk_b)
        self.fx.sidecar = ei.capture(pdk_b, PDK, PIN, SID, NGSPICE)
        self.assertEqual(self.fx.admit()[0], [])

    def test_changed_dut_rejected_even_when_pvt_keys_match(self):
        self.fx.dut = "* dut v0 (older)\n"
        self.assertRejected("incompatible DUT")

    def test_changed_model_bytes_rejected(self):
        pdk_b = self.fx.root / "pdk_b"
        make_install(pdk_b)
        (pdk_b / MOS_INC).write_text("* mos tt MODIFIED\n")
        self.fx.sidecar = ei.capture(pdk_b, PDK, PIN, SID, NGSPICE)
        errs = self.assertRejected("incompatible model environment")
        self.assertTrue(any("sub/mos.inc" in e for e in errs))

    def test_changed_osdi_manifest_rejected(self):
        self.fx.sidecar["osdi"]["manifest_sha256"] = "0" * 64
        self.fx.sidecar["identity_sha256"] = ei.identity_of(self.fx.sidecar["models"]["files"], self.fx.sidecar["osdi"])
        self.assertRejected("OSDI build manifest differs")

    def test_different_simulator_rejected(self):
        self.fx.sidecar["observed"]["ngspice"] = "ngspice-44"
        self.assertRejected("simulator")

    def test_tampered_sidecar_rejected(self):
        self.fx.sidecar["identity_sha256"] = "f" * 64
        self.assertRejected("identity_sha256 does not match")

    def test_legacy_source_without_identity_refused_with_rerun_hint(self):
        self.fx.sidecar = None
        self.assertRejected("LEGACY")
        self.assertFalse((self.fx.exp / "records" / f"{SID}.env.json").exists())  # nothing retrofitted

    def test_missing_source_dut_snapshot(self):
        self.fx.write()
        (self.fx.exp / "netlist-snapshots" / SID / "opamp_core.spice").unlink()
        errs, prov = aj.admit(self.fx.exp / "records" / f"{SID}.csv", self.fx.consumer_env, self.fx.consumer_snap,
                              "c", PIN, 2e-12, 0.5, CORNERS, TEMPS, VDDS, COLS)
        self.assertIsNone(prov)
        self.assertTrue(any("snapshot" in e and "missing" in e for e in errs))

    def test_duplicate_grid_row(self):
        self.fx.rows.append(self.fx.rows[0])
        self.assertRejected("2 source rows")

    def test_missing_grid_row(self):
        del self.fx.rows[1]
        self.assertRejected("no source row")

    def test_extra_grid_row(self):
        self.fx.rows.append(row("mos_ff", "27", "1.20"))
        self.assertRejected("outside the requested grid")

    def test_non_finite_gain(self):
        for bad in ("nan", "inf", "", "x"):
            with self.subTest(bad=bad):
                self.fx.rows[0] = row("mos_tt", "27", "1.08", av0=bad)
                self.assertRejected("av0_db is not finite")

    def test_failed_source_op(self):
        self.fx.rows[0] = row("mos_tt", "27", "1.08", op="0")
        self.assertRejected("operating point failed")

    def test_incompatible_load(self):
        self.fx.cl = "5e-12"
        self.assertRejected("load differs")

    def test_incompatible_common_mode(self):
        self.fx.rows[0] = row("mos_tt", "27", "1.08", vcm=0.4)
        self.assertRejected("common-mode config differs")

    def test_missing_required_column(self):
        self.fx.write()
        p = self.fx.exp / "records" / f"{SID}.csv"
        p.write_text(p.read_text().replace(",vout_dc_v", ",other"))
        errs, prov = aj.admit(p, self.fx.consumer_env, self.fx.consumer_snap, "c", PIN, 2e-12, 0.5,
                              CORNERS, TEMPS, VDDS, COLS)
        self.assertIsNone(prov)
        self.assertTrue(any("required column" in e for e in errs))


class CliAndShellTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = Fixture(Path(self._tmp.name))
        self.env_file = self.fx.root / "consumer.env.json"
        self.env_file.write_text(ei.canonical_json(self.fx.consumer_env))

    def args(self, csv: Path, out: Path):
        return [str(SIM_DIR / "tools" / "ac_join_admission.py"), "admit", "--source-csv", str(csv),
                "--consumer-env", str(self.env_file), "--consumer-snapshot", str(self.fx.consumer_snap),
                "--consumer-record-id", "c1", "--pin", str(SIM_DIR / "pdk.json"), "--cl-f", "2e-12",
                "--corners", *CORNERS, "--temps", *TEMPS, "--vdds", *VDDS, "--require-col", *COLS, "--out", str(out)]

    def test_cli_accepts_then_refuses_overwrite_and_explicit_path_is_validated_alike(self):
        csv = self.fx.write()
        out = self.fx.root / "prov.json"
        r = subprocess.run([sys.executable, *self.args(csv, out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(out.read_text())["source"]["record_id"], SID)
        r = subprocess.run([sys.executable, *self.args(csv, out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        # a rejected (legacy) source reports the rerun diagnostic and writes nothing
        (csv.parent / f"{SID}.env.json").unlink()
        out2 = self.fx.root / "prov2.json"
        r = subprocess.run([sys.executable, *self.args(csv, out2)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("LEGACY", r.stderr)
        self.assertIn("run_pvt_sweep.sh", r.stderr)
        self.assertFalse(out2.exists())

    def test_shell_admit_exits_3_before_solving_and_cleans_up(self):
        csv = self.fx.write()
        (csv.parent / f"{SID}.env.json").unlink()
        snapdir = self.fx.root / "snapshots_out"
        corners_out = self.fx.root / "corners_out"
        snapdir.mkdir(); corners_out.mkdir()
        (snapdir / "opamp_core.spice").write_text(DUT)
        script = (f'set -euo pipefail; SIM_DIR="{SIM_DIR}"; CORNERS_OUT="{corners_out}"; '
                  f'source "{SIM_DIR}/ac-join.sh"; '
                  f'sg13g2_ac_join_admit "{csv}" "{self.env_file}" "{snapdir}/opamp_core.spice" c1 '
                  f'"{self.fx.root}/p.json" 2e-12 "{" ".join(CORNERS)}" "{" ".join(TEMPS)}" "{" ".join(VDDS)}" av0_db vout_dc_v; '
                  'echo SOLVER_REACHED')
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertNotIn("SOLVER_REACHED", r.stdout)
        self.assertIn("nothing was simulated", r.stderr)
        self.assertFalse(snapdir.exists())
        self.assertFalse(corners_out.exists())

    def test_shell_admit_passes_for_matching_source(self):
        csv = self.fx.write()
        script = (f'set -euo pipefail; SIM_DIR="{SIM_DIR}"; source "{SIM_DIR}/ac-join.sh"; '
                  f'sg13g2_ac_join_admit "{csv}" "{self.env_file}" "{self.fx.consumer_snap}" c1 '
                  f'"{self.fx.root}/p.json" 2e-12 "{" ".join(CORNERS)}" "{" ".join(TEMPS)}" "{" ".join(VDDS)}" av0_db vout_dc_v; '
                  'echo OK')
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.fx.root / "p.json").is_file())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Offline tests for sim/open-loop-ac/{summarize_klt.py,run_klt_record.sh} (issue #500).

  python3 -m unittest discover -s sim/open-loop-ac -p 'test_summarize_klt.py' -v
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

_SPEC = importlib.util.spec_from_file_location("summarize_klt", HERE / "summarize_klt.py")
assert _SPEC is not None and _SPEC.loader is not None
summarize_klt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(summarize_klt)

AC_SIM = HERE / "klt" / "records" / "20261016-161057-8caa272.ac.sim.json"
OP_SIM = HERE / "klt" / "records" / "20261016-161057-8caa272.op.sim.json"
SUPERSEDED_CSV = HERE / "records" / "20260910-221601-22feaba.csv"


class SummarizeKltTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_corners(self, engine_version: str = "47") -> Path:
        cdir = self.tmp / "corners"
        cdir.mkdir(parents=True, exist_ok=True)
        dut = self.tmp / "netlist-snapshots" / "rid1" / "opamp_core.spice"
        dut.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "design" / "netlist" / "opamp_core.spice", dut)
        summarize_klt.stage(str(dut), str(cdir))
        for kind, src in (("ac", AC_SIM), ("op", OP_SIM)):
            env = json.loads(src.read_text(encoding="utf-8"))
            env["environment"]["engine_version"] = engine_version
            env["environment"]["remote"]["worker_environment"]["simulator"]["version_banner"] = (
                f"******\n** ngspice-{engine_version} : Circuit level simulation program\n******\n"
            )
            (cdir / f"{kind}.envelope.json").write_text(json.dumps(env), encoding="utf-8")
        return cdir

    def test_stage_preserves_schematic_internal_nodes_and_typical_passives(self):
        cdir = self.tmp / "staged"
        dut = self.tmp / "netlist-snapshots" / "rid1" / "opamp_core.spice"
        dut.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "design" / "netlist" / "opamp_core.spice", dut)
        summarize_klt.stage(str(dut), str(cdir))

        op_req = json.loads((cdir / "openloop_op.request.json").read_text(encoding="utf-8"))
        names = [m["name"] for m in op_req["measurements"]]
        for expected in (
            "ivdd_total_a",
            "vout_dc_v",
            "vd1_dc_v",
            "vd2_dc_v",
            "vtail_dc_v",
            "vibias_dc_v",
            "op_vcm_frac",
            "op_vout_offset_frac",
            "op_vout_rail_frac",
            "op_vd1_rail_frac",
            "op_vd2_rail_frac",
            "op_vtail_rail_frac",
        ):
            self.assertIn(expected, names)
        body = (cdir / "tb_openloop_ac.body.spice").read_text(encoding="utf-8")
        self.assertIn('.include "../netlist-snapshots/rid1/opamp_core.spice"', body)

    def test_stage_refuses_extracted_subckt_dut(self):
        sub = self.tmp / "extracted.spice"
        sub.write_text(".SUBCKT opamp_core VDD VSS INN INP OUT IBIAS\n.ENDS\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            summarize_klt.stage(str(sub), str(self.tmp / "sub-out"))
        self.assertIn(".SUBCKT", str(cm.exception))

    def test_summarize_without_superseded_csv_writes_schematic_op_columns_and_version(self):
        cdir = self.make_corners(engine_version="47")
        out_csv = self.tmp / "out.csv"
        out_md = self.tmp / "out.md"
        res = subprocess.run(
            [sys.executable, "-I", str(HERE / "summarize_klt.py"), "20261125-000000-abcdef0",
             str(cdir), str(out_csv), str(out_md)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        with out_csv.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 45)
        for col in ("av0_db", "gbw_hz", "pm_deg", "iq_a", "vout_dc_v", "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v", "op_pass"):
            self.assertIn(col, rows[0])
        self.assertTrue(all(r["op_pass"] == "1" for r in rows))
        md = out_md.read_text(encoding="utf-8")
        self.assertIn("ngspice-47", md)
        self.assertIn("CL = 2e-12 F", md)
        self.assertNotIn("Supersedes", md)
        self.assertTrue((cdir / "measurement.json").is_file())

    def test_summarize_with_superseded_csv_keeps_shift_table(self):
        cdir = self.make_corners(engine_version="47")
        out_csv = self.tmp / "out.csv"
        out_md = self.tmp / "out.md"
        res = subprocess.run(
            [sys.executable, "-I", str(HERE / "summarize_klt.py"), "20261125-000000-abcdef0",
             str(cdir), str(SUPERSEDED_CSV), str(out_csv), str(out_md)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        md = out_md.read_text(encoding="utf-8")
        self.assertIn("Shift against the superseded", md)

    def test_run_klt_record_passes_capacity_wait_and_needs_no_floating_inn_csv(self):
        fake_repo = self.tmp / "repo"
        (fake_repo / "design" / "netlist").mkdir(parents=True)
        shutil.copyfile(REPO / "design" / "netlist" / "opamp_core.spice",
                        fake_repo / "design" / "netlist" / "opamp_core.spice")
        (fake_repo / "sim" / "tools").mkdir(parents=True)
        for name in ("env.sh", "record-paths.sh"):
            shutil.copyfile(REPO / "sim" / name, fake_repo / "sim" / name)
        shutil.copyfile(REPO / "sim" / "tools" / "op_sanity.py", fake_repo / "sim" / "tools" / "op_sanity.py")
        bench = fake_repo / "sim" / "open-loop-ac"
        (bench / "klt").mkdir(parents=True)
        for name in ("run_klt_record.sh", "summarize_klt.py"):
            shutil.copy2(HERE / name, bench / name)
        for name in ("openloop_ac.request.json", "openloop_op.request.json", "tb_openloop_ac.body.spice"):
            shutil.copyfile(HERE / "klt" / name, bench / "klt" / name)

        # Notice: bench/records/20260910-221601-22feaba.csv is intentionally NOT copied!
        pdk_root = self.tmp / "pdk"
        (pdk_root / "ihp-sg13g2" / "libs.tech" / "ngspice" / "osdi").mkdir(parents=True)
        (pdk_root / "ihp-sg13g2" / "libs.tech" / "ngspice" / "osdi" / "psp103.osdi").write_bytes(b"ok")

        stub_bin = self.tmp / "bin"
        stub_bin.mkdir()
        args_log = self.tmp / "klt_args.jsonl"
        stub = stub_bin / "klt"
        stub.write_text(
            f"""#!/usr/bin/env python3
import json, sys
from pathlib import Path
with open({str(args_log)!r}, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:2] == ["--version"]:
    print("klt 0.8.0")
    sys.exit(0)
req_path = Path(sys.argv[2])
kind = "ac" if "openloop_ac" in req_path.name else "op"
src = Path({str(AC_SIM)!r} if kind == "ac" else {str(OP_SIM)!r})
env = json.loads(src.read_text(encoding="utf-8"))
env["environment"]["engine_version"] = "47"
env["environment"]["remote"]["worker_environment"]["simulator"]["version_banner"] = "ngspice-47"
sys.stdout.write(json.dumps(env))
""",
            encoding="utf-8",
        )
        stub.chmod(0o755)

        env = dict(os.environ, PDK_ROOT=str(pdk_root), PDK="ihp-sg13g2", KLT=str(stub))
        res = subprocess.run(
            ["bash", str(bench / "run_klt_record.sh")],
            cwd=str(fake_repo), env=env, capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        calls = [json.loads(line) for line in args_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        sim_calls = [c for c in calls if c and c[0] == "sim"]
        self.assertEqual(len(sim_calls), 2, calls)
        for c in sim_calls:
            self.assertIn("--wait-for-capacity", c)
            self.assertEqual(c[c.index("--wait-for-capacity") + 1], "600")
        csvs = list((bench / "records").glob("*.csv"))
        self.assertEqual(len(csvs), 1)


if __name__ == "__main__":
    unittest.main()

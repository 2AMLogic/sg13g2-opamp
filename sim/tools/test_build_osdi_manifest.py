"""Offline tests for the OSDI build manifest in sim/tools/build-osdi.sh (#182).

Everything runs against a fixture PDK tree with a stub compiler (via the
script's SG13G2_OSDI_TEST_COMPILER hook) and a stub ngspice on PATH: no PDK
download, no native compiler, no network.
"""
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest

REPO_SIM = pathlib.Path(__file__).resolve().parent.parent

STUB_COMPILER = """#!/usr/bin/env bash
[[ "$1" == "--version" ]] && { echo "stub-openvaf 0"; exit 0; }
echo "$PWD $*" >> "$STUB_LOG"
[[ -n "${STUB_FAIL_MODEL:-}" && "$*" == *"${STUB_FAIL_MODEL}.va"* ]] && exit 1
out=""
while [[ $# -gt 0 ]]; do [[ "$1" == "-o" ]] && out="$2"; shift; done
echo "osdi built $RANDOM$RANDOM" > "$out"
"""
STUB_NGSPICE = """#!/usr/bin/env bash
echo "v(d1) = 1.0"
echo "v(d2) = 1.0"
echo "v(r1b) = 0.0"
"""


def _exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.script_dir = self.tmp / "sim" / "tools"
        self.script_dir.mkdir(parents=True)
        shutil.copy(REPO_SIM / "env.sh", self.tmp / "sim" / "env.sh")
        self.script = self.script_dir / "build-osdi.sh"
        shutil.copy(REPO_SIM / "tools" / "build-osdi.sh", self.script)
        va = self.tmp / "pdk" / "ihp-sg13g2" / "libs.tech" / "verilog-a"
        self.va = va
        (self.tmp / "pdk/ihp-sg13g2/libs.tech/ngspice/models").mkdir(parents=True)
        for sub, files in {
            "psp103": ["psp103.va", "psp103_nqs.va", "PSP103_module.include"],
            "r3_cmc": ["r3_cmc.va", "r3_cmc_macros.include"],
            "mosvar": ["mosvar.va", "discipline.h", "mosvarpspMacros.va"],
        }.items():
            (va / sub).mkdir(parents=True)
            for f in files:
                (va / sub / f).write_text(f"// {f} v1\n")
        self.osdi = self.tmp / "pdk/ihp-sg13g2/libs.tech/ngspice/osdi"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        _exe(self.bin / "compiler", STUB_COMPILER)
        _exe(self.bin / "ngspice", STUB_NGSPICE)
        self.log = self.tmp / "compiler.log"
        self.log.write_text("")
        self.env = dict(
            os.environ,
            PDK_ROOT=str(self.tmp / "pdk"),
            PDK="ihp-sg13g2",
            PATH=f"{self.bin}:{os.environ['PATH']}",
            SG13G2_OSDI_TEST_COMPILER=str(self.bin / "compiler"),
            SG13G2_TOOLS_CACHE=str(self.tmp / "cache"),
            STUB_LOG=str(self.log),
        )
        self.env.pop("STUB_FAIL_MODEL", None)

    def run_script(self, *args, extra_env=None):
        env = dict(self.env, **(extra_env or {}))
        return subprocess.run(
            ["bash", str(self.script), *args],
            env=env, capture_output=True, text=True, timeout=60,
        )

    def compiles(self):
        return len([l for l in self.log.read_text().splitlines() if l])

    def build(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.compiles(), 4)
        self.assertTrue((self.osdi / ".build-manifest").is_file())

    def assert_stale(self, why=""):
        before = sorted(p.name for p in self.osdi.iterdir())
        r = self.run_script("--check")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("build-osdi.sh to rebuild", r.stderr)
        self.assertEqual(before, sorted(p.name for p in self.osdi.iterdir()),
                         "--check must not write to OSDI_DIR")
        n = self.compiles()
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreater(self.compiles(), n, f"{why}: normal build reused stale build")

    def test_unchanged_inputs_reuse(self):
        self.build()
        r = self.run_script("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.compiles(), 4)
        self.assertIn("already built", r.stdout)

    def test_force_rebuilds(self):
        self.build()
        self.assertEqual(self.run_script("--force").returncode, 0)
        self.assertEqual(self.compiles(), 8)

    def test_compiler_runs_in_model_dir_with_flag(self):
        self.build()
        self.assertIn("-D__NGSPICE__", self.log.read_text())

    def test_top_level_va_edit(self):
        self.build()
        (self.va / "r3_cmc" / "r3_cmc.va").write_text("// edited\n")
        self.assert_stale("top-level va")

    def test_included_file_edit(self):
        self.build()
        (self.va / "psp103" / "PSP103_module.include").write_text("// edited\n")
        self.assert_stale("included file")

    def test_replaced_binary(self):
        self.build()
        (self.osdi / "mosvar.osdi").write_text("tampered\n")
        self.assert_stale("binary")

    def test_missing_manifest(self):
        self.build()
        (self.osdi / ".build-manifest").unlink()
        self.assert_stale("missing manifest")

    def test_malformed_manifest(self):
        self.build()
        (self.osdi / ".build-manifest").write_text("garbage\x00\n")
        self.assert_stale("malformed")

    def test_unknown_schema(self):
        self.build()
        m = self.osdi / ".build-manifest"
        m.write_text(m.read_text().replace("schema=1", "schema=99", 1))
        self.assert_stale("schema")

    def _modified_script(self, old, new):
        text = self.script.read_text()
        self.assertIn(old, text)
        self.script.write_text(text.replace(old, new, 1))

    def test_compiler_pin_change(self):
        self.build()
        self._modified_script('OPENVAF_TAG="v24.0.1mob"', 'OPENVAF_TAG="v99.0.0"')
        self.assert_stale("tag")

    def test_asset_sha_pin_change(self):
        self.build()
        text = self.script.read_text()
        import re
        new = re.sub(r'(OPENVAF_SHA_\w+=")[0-9a-f]{64}', r'\g<1>' + "0" * 64, text)
        self.assertNotEqual(text, new)
        self.script.write_text(new)
        self.assert_stale("asset sha")

    def test_flag_change(self):
        self.build()
        self._modified_script('COMPILE_FLAGS="-D__NGSPICE__"',
                              'COMPILE_FLAGS="-D__NGSPICE__ -DEXTRA"')
        self.assert_stale("flags")

    def test_failed_compile_leaves_no_manifest(self):
        self.build()
        (self.va / "r3_cmc" / "r3_cmc.va").write_text("// edited\n")
        r = self.run_script(extra_env={"STUB_FAIL_MODEL": "r3_cmc"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.osdi / ".build-manifest").exists())
        self.assertNotEqual(self.run_script("--check").returncode, 0)

    def test_fresh_build_failed_compile_no_manifest(self):
        r = self.run_script(extra_env={"STUB_FAIL_MODEL": "mosvar"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.osdi / ".build-manifest").exists())

    def test_failed_probe_no_manifest(self):
        _exe(self.bin / "ngspice", "#!/usr/bin/env bash\necho nothing\n")
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.osdi / ".build-manifest").exists())


if __name__ == "__main__":
    unittest.main()

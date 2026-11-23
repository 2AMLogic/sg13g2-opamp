"""Offline test for the missing-dpkg-deb diagnostic in sim/tools/build-osdi.sh (#432).

Reproduces the issue's empty-cache fixture: the script's own
ensure_libllvm21 function, an empty cache directory, and a PATH holding
only cat. The diagnostic must name the missing tool, give the single
install-and-rerun instruction, and exit 3 -- with no manual-extraction
recipe that would itself need the missing dpkg-deb.
"""
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "build-osdi.sh"


def _pin(name):
    m = re.search(rf'^{name}="([^"]+)"\s*$', SCRIPT.read_text(), re.M)
    if not m:
        raise AssertionError(f"pin {name} not found in build-osdi.sh")
    return m.group(1)


class DpkgDebDiagnosticTest(unittest.TestCase):
    def test_missing_dpkg_deb_names_tool_and_reruns(self):
        text = SCRIPT.read_text()
        start = text.index("ensure_libllvm21() {")
        end = text.index("\n}\n", start) + 2  # include the closing brace line
        func = text[start:end]

        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "cache").mkdir()  # empty cache: no extracted libLLVM.so.21.1

        # PATH containing only cat, as in the issue reproduction.
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        cat = shutil.which("cat") or "/bin/cat"
        shutil.copy(cat, bin_dir / "cat")
        (bin_dir / "cat").chmod(stat.S_IRWXU)

        harness = tmp / "harness.sh"
        harness.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"OPENVAF_TAG='{_pin('OPENVAF_TAG')}'\n"
            f"LIBLLVM21_DEB_ASSET='{_pin('LIBLLVM21_DEB_ASSET')}'\n"
            f"LIBLLVM21_DEB_URL='{_pin('LIBLLVM21_DEB_URL')}'\n"
            f"LIBLLVM21_DEB_SHA256='{_pin('LIBLLVM21_DEB_SHA256')}'\n"
            f"CACHE_DIR='{tmp / 'cache'}'\n"
            f"{func}\n"
            "ensure_libllvm21\n"
            "echo 'ensure_libllvm21 unexpectedly returned' >&2\n"
            "exit 9\n"
        )

        r = subprocess.run(
            [shutil.which("bash"), str(harness)],
            env={"PATH": str(bin_dir)},
            capture_output=True, text=True, timeout=30,
        )
        err = r.stderr
        self.assertEqual(r.returncode, 3, err)
        self.assertIn("dpkg-deb", err)  # identifies the missing tool
        self.assertIn("PATH", err)
        self.assertRegex(err.lower(), "install")
        self.assertIn("rerun", err.lower())
        self.assertIn("sim/tools/build-osdi.sh", err)
        # The circular manual-extraction recipe is gone: the workaround
        # needed the very executable whose absence triggered the error.
        self.assertNotIn("dpkg-deb -x", err)
        self.assertNotIn("curl", err)
        self.assertNotIn("LD_LIBRARY_PATH", err)


if __name__ == "__main__":
    unittest.main()

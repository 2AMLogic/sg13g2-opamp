#!/usr/bin/env python3
"""Fixture tests for signoff/regenerate.sh (stdlib, offline).

  python3 -m unittest discover -s signoff -p 'test_regenerate.py' -v

The script is copied into a temp repo root next to a stub klt-pin.txt and
manifest, with fake `uvx`, `git` and `date` first on PATH. No network, PDK,
klt or SPICE. FAKE_UVX_MODE selects the fake klt behaviour.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "regenerate.sh"

FAKE_UVX = """#!/usr/bin/env bash
json=0
for a in "$@"; do [ "$a" = json ] && json=1; done
if [ "$json" -eq 0 ]; then
  echo "text report"
  [ "${FAKE_UVX_MODE}" = exit3 ] && exit 3
  exit 0
fi
case "${FAKE_UVX_MODE}" in
  ok) echo '{"block":"b","kind":"k","items":[{"id":1}],"t1_item_count":1}' ;;
  exit3) echo '{"block":"b","kind":"k","items":[{"id":1}],"t1_item_count":1}'; exit 3 ;;
  jsonfail) echo '{"block":"b","kind":"k","items":['; exit 1 ;;
  malformed) echo '{"block":"b", "items": [' ;;
  notobject) echo '[1,2]' ;;
  emptyitems) echo '{"block":"b","kind":"k","items":[],"t1_item_count":0}' ;;
  empty) : ;;
esac
exit 0
"""
FAKE_GIT = "#!/usr/bin/env bash\necho abcdef1\n"
FAKE_DATE = "#!/usr/bin/env bash\necho 20260101-000000\n"


class RegenerateTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name) / "repo"
        (self.root / "signoff" / "reports").mkdir(parents=True)
        shutil.copy(SCRIPT, self.root / "signoff" / "regenerate.sh")
        (self.root / "signoff" / "klt-pin.txt").write_text("# pin\ndeadbeef\n")
        (self.root / "signoff" / "block-manifest.json").write_text("{}")
        self.bin = Path(self._td.name) / "bin"
        self.bin.mkdir()
        for name, body in (("uvx", FAKE_UVX), ("git", FAKE_GIT), ("date", FAKE_DATE)):
            p = self.bin / name
            p.write_text(body)
            p.chmod(0o755)
        self.reports = self.root / "signoff" / "reports"
        self.final = self.reports / "20260101-000000-abcdef1.signoff.json"

    def run_script(self, mode, *args):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_UVX_MODE=mode)
        return subprocess.run(
            ["bash", str(self.root / "signoff" / "regenerate.sh"), *args],
            env=env, capture_output=True, text=True,
        )

    def listing(self):
        return sorted(p.name for p in self.reports.iterdir())

    def test_exit0_publishes(self):
        r = self.run_script("ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.listing(), [self.final.name])
        self.assertEqual(json.loads(self.final.read_text())["t1_item_count"], 1)

    def test_exit3_publishes(self):
        r = self.run_script("exit3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.listing(), [self.final.name])

    def test_text_ok_json_fails_leaves_nothing(self):
        r = self.run_script("jsonfail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("text report", r.stdout)
        self.assertEqual(self.listing(), [])

    def test_invalid_reports_refused(self):
        for mode in ("malformed", "notobject", "emptyitems", "empty"):
            with self.subTest(mode=mode):
                r = self.run_script(mode)
                self.assertEqual(r.returncode, 1)
                self.assertIn("no record written", r.stderr)
                self.assertEqual(self.listing(), [])

    def test_existing_destination_untouched(self):
        self.final.write_bytes(b"precious\n")
        r = self.run_script("ok")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual(self.final.read_bytes(), b"precious\n")
        self.assertEqual(self.listing(), [self.final.name])

    def test_concurrent_same_id_yields_one_report(self):
        with ThreadPoolExecutor(max_workers=2) as ex:
            rcs = list(ex.map(lambda _: self.run_script("ok").returncode, range(6)))
        self.assertEqual(rcs.count(0), 1, rcs)
        self.assertEqual(self.listing(), [self.final.name])
        json.loads(self.final.read_text())

    def test_dry_run_writes_nothing(self):
        r = self.run_script("ok", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.listing(), [])


if __name__ == "__main__":
    unittest.main()

"""Offline tests for store_evidence.py with a stubbed `klt` (no network)."""
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store_evidence as se  # noqa: E402

STUB = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
a = sys.argv[1:]
if a[:3] == ["artifact", "put", "--help"]:
    sys.exit(int(os.environ.get("STUB_HELP_RC", "0")))
if os.environ.get("STUB_PUT_FAIL"):
    print("broker unreachable", file=sys.stderr); sys.exit(1)
mp = a[a.index("--manifest") + 1]; name = a[a.index("--name") + 1]; f = a[-1]
d = open(f, "rb").read(); sha = hashlib.sha256(d).hexdigest()
try: m = json.load(open(mp))
except OSError: m = {"schema_version": 1, "entries": []}
m["entries"].append({"sha256": sha, "size": len(d), "kind": "evidence",
  "producer": {"tool": "klt", "version": "0", "loom.repo": "o/r", "commit": None},
  "uri": "artifact:evidence/o__r/" + sha, "name": name})
json.dump(m, open(mp, "w"))
'''


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        klt = self.bin / "klt"
        klt.write_text(STUB)
        klt.chmod(klt.stat().st_mode | stat.S_IXUSR)
        self.run_dir = self.tmp / "run"
        (self.run_dir / "sub").mkdir(parents=True)
        (self.run_dir / "a b.log").write_text("alpha\n")
        (self.run_dir / "sub" / "c.json").write_text("{}\n")
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "KLT_ARTIFACT_BROKER": "https://broker.invalid",
        }
        self._saved = dict(os.environ)
        os.environ.update(self.env)
        os.environ.pop("KLT_CMD", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        self._td.cleanup()

    def go(self, *extra, run_id="r1", paths=None):
        return se.main(["--root", str(self.root), "--bench", "b", "--run-id", run_id,
                        *map(str, paths or [self.run_dir])])

    def tracked_state(self):
        return sorted(p.relative_to(self.root).as_posix()
                      for p in self.root.rglob("*") if p.is_file() and ".git/" not in p.as_posix())

    def test_success_writes_only_manifest_and_summary(self):
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.tracked_state(), [
            "manifests/artifacts/b-r1.manifest.json", "manifests/artifacts/b-r1.md"])
        m = json.loads((self.root / "manifests/artifacts/b-r1.manifest.json").read_text())
        names = sorted(e["name"] for e in m["entries"])
        self.assertEqual(names, ["b/r1/a b.log", "b/r1/sub/c.json"])
        md = (self.root / "manifests/artifacts/b-r1.md").read_text()
        self.assertIn(hashlib.sha256(b"alpha\n").hexdigest(), md)
        self.assertFalse((self.root / se.SCRATCH_REL / "b-r1").exists())

    def test_broker_unset(self):
        del os.environ["KLT_ARTIFACT_BROKER"]
        self.assertNotEqual(self.go(), 0)
        self.assertEqual(self.tracked_state(), [])

    def test_klt_missing(self):
        os.environ["KLT_CMD"] = "klt-does-not-exist"
        self.assertNotEqual(self.go(), 0)
        self.assertEqual(self.tracked_state(), [])

    def test_klt_without_put(self):
        os.environ["STUB_HELP_RC"] = "2"
        self.assertNotEqual(self.go(), 0)
        self.assertEqual(self.tracked_state(), [])

    def test_broker_unreachable(self):
        os.environ["STUB_PUT_FAIL"] = "1"
        self.assertNotEqual(self.go(), 0)
        self.assertEqual(self.tracked_state(), [])

    def test_empty_run(self):
        (self.tmp / "empty").mkdir()
        self.assertNotEqual(self.go(paths=[self.tmp / "empty"]), 0)
        self.assertEqual(self.tracked_state(), [])

    def test_empty_file_refused(self):
        (self.run_dir / "z.txt").write_text("")
        self.assertNotEqual(self.go(), 0)
        self.assertEqual(self.tracked_state(), [])

    def test_existing_manifest_refused_and_untouched(self):
        self.assertEqual(self.go(), 0)
        p = self.root / "manifests/artifacts/b-r1.manifest.json"
        before = p.read_bytes()
        self.assertNotEqual(self.go(), 0)
        self.assertEqual(p.read_bytes(), before)

    def test_bad_ids(self):
        self.assertNotEqual(self.go(run_id="../x"), 0)
        self.assertEqual(self.tracked_state(), [])


if __name__ == "__main__":
    unittest.main()

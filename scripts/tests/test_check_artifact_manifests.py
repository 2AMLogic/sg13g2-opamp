"""Offline tests for scripts/check_artifact_manifests.py (stdlib only)."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_artifact_manifests as chk  # noqa: E402


def entry(data: bytes, **over):
    sha = hashlib.sha256(data).hexdigest()
    e = {
        "sha256": sha,
        "size": len(data),
        "kind": "evidence",
        "producer": {
            "tool": "klt",
            "version": "0.0.0",
            "loom.repo": "o/r",
            "commit": None,
        },
        "uri": f"artifact:evidence/o__r/{sha}",
        "name": "b/run/out.txt",
    }
    e.update(over)
    return e


class CheckTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        (self.root / "manifests/artifacts").mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def write(self, rel, content):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
        subprocess.run(["git", "-C", str(self.root), "add", "-f", rel], check=True)

    def manifest(self, entries, name="manifests/artifacts/b-r1.manifest.json", **over):
        doc = {"schema_version": 1, "entries": entries}
        doc.update(over)
        self.write(name, json.dumps(doc))

    def run_check(self, broker=None):
        return chk.check(self.root, broker)

    def test_clean(self):
        self.manifest([entry(b"hello")])
        self.assertEqual(self.run_check(), [])

    def test_bad_schema_version(self):
        self.manifest([entry(b"x")], schema_version=2)
        self.assertTrue(any("schema_version" in p for p in self.run_check()))

    def test_missing_and_unknown_fields(self):
        e = entry(b"x")
        del e["kind"]
        e["extra"] = 1
        self.manifest([e])
        out = " ".join(self.run_check())
        self.assertIn("missing kind", out)
        self.assertIn("unknown field", out)

    def test_non_artifact_uri(self):
        self.manifest([entry(b"x", uri="https://example.invalid/x")])
        self.assertTrue(any("artifact:" in p for p in self.run_check()))

    def test_s3_uri_rejected(self):
        self.manifest([entry(b"x", uri="s3://bucket/key")])
        out = self.run_check()
        self.assertTrue(any("s3://" in p for p in out))
        self.assertTrue(any("artifact:" in p for p in out))

    def test_s3_text_anywhere_in_manifests(self):
        self.manifest([entry(b"x")])
        self.write("manifests/README.md", "see arn:aws:s3:::bucket")
        self.assertTrue(any("arn:aws:" in p for p in self.run_check()))

    def test_uri_key_must_end_in_sha(self):
        self.manifest([entry(b"x", uri="artifact:evidence/o__r/" + "0" * 64)])
        self.assertTrue(any("sha256" in p for p in self.run_check()))

    def test_empty_entries(self):
        self.manifest([])
        self.assertTrue(any("non-empty" in p for p in self.run_check()))

    def test_duplicate_name(self):
        self.manifest([entry(b"a"), entry(b"b")])
        self.assertTrue(any("duplicate name" in p for p in self.run_check()))

    def test_invalid_json(self):
        self.write("manifests/artifacts/bad.manifest.json", "{nope")
        self.assertTrue(any("not valid JSON" in p for p in self.run_check()))

    def test_bytes_also_committed(self):
        data = b"raw evidence bytes\n"
        self.manifest([entry(data)])
        self.write("sim/x/corners/c1/out.txt", data)
        out = self.run_check()
        self.assertTrue(any("also stored as artifact" in p for p in out))

    def test_same_size_different_bytes_ok(self):
        self.manifest([entry(b"aaaa")])
        self.write("sim/x/other.txt", b"bbbb")
        self.assertEqual(self.run_check(), [])

    def test_broker_url_leak(self):
        self.manifest([entry(b"x")])
        self.write("manifests/README.md", "broker https://broker.example.invalid/")
        out = self.run_check("https://broker.example.invalid/")
        self.assertTrue(any("broker URL" in p for p in out))

    def test_no_manifests_is_clean(self):
        self.assertEqual(self.run_check(), [])

    def test_main_exit_codes(self):
        self.manifest([entry(b"x")])
        self.assertEqual(chk.main(["--root", str(self.root)]), 0)
        self.manifest([entry(b"x", uri="s3://b/k")])
        self.assertEqual(chk.main(["--root", str(self.root)]), 1)

    def test_not_a_git_repo_is_usage_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(chk.main(["--root", d]), 2)


if __name__ == "__main__":
    unittest.main()

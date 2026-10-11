#!/usr/bin/env python3
"""Tests for env_identity.py (stdlib unittest; no PDK, simulator or network).

  python3 -m unittest discover -s sim/tools -p 'test_env_identity.py' -v
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import env_identity as ei  # noqa: E402

PIN = json.loads((HERE.parent / "pdk.json").read_text(encoding="utf-8"))
RID = "20260101-000000-abcdef0"


def make_install(root: Path, marker: str = "0.3.0", mos_body: str = "* mos tt\n", manifest: str = "schema=1\n") -> Path:
    inst = root / "ihp-sg13g2"
    models = inst / ei.MODELS_SUBDIR
    models.mkdir(parents=True)
    (models / "cornerMOSlv.lib").write_text('.lib mos_tt\n.include "sub/mos.inc"\n.endl\n', encoding="utf-8")
    (models / "cornerCAP.lib").write_text("* cap\n", encoding="utf-8")
    (models / "sub").mkdir()
    (models / "sub" / "mos.inc").write_text(mos_body, encoding="utf-8")
    (inst / ".fetched-version").write_text(marker + "\n", encoding="utf-8")
    osdi = inst / "libs.tech/ngspice/osdi"
    osdi.mkdir(parents=True)
    (osdi / ".build-manifest").write_text(manifest, encoding="utf-8")
    return inst


def capture(root: Path, **kw) -> dict:
    make_install(root, **kw)
    return ei.capture(root, "ihp-sg13g2", PIN, RID, "ngspice-46")


class EnvIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def sidecar(self, **kw) -> dict:
        return capture(self.tmp / "a", **kw)

    def test_valid_sidecar_verifies_and_closure_follows_includes(self):
        s = self.sidecar()
        self.assertEqual(ei.verify(s, PIN, RID), [])
        self.assertIn("libs.tech/ngspice/models/sub/mos.inc", [f["path"] for f in s["models"]["files"]])
        self.assertEqual(s["models"]["unresolved"], [])

    def test_same_release_marker_different_model_bytes_differ(self):
        a = capture(self.tmp / "a")
        b = capture(self.tmp / "b", mos_body="* mos tt, locally modified\n")
        self.assertEqual(a["observed"]["release_marker"], b["observed"]["release_marker"])
        self.assertNotEqual(a["identity_sha256"], b["identity_sha256"])

    def test_identity_ignores_host_path(self):
        a = capture(self.tmp / "one")
        b = capture(self.tmp / "deep" / "two")
        self.assertEqual(a["identity_sha256"], b["identity_sha256"])

    def test_osdi_manifest_change_changes_identity(self):
        a = capture(self.tmp / "a")
        b = capture(self.tmp / "b", manifest="schema=1\noutput.psp103.osdi=deadbeef\n")
        self.assertNotEqual(a["identity_sha256"], b["identity_sha256"])

    def test_tampered_model_hash_is_error(self):
        s = self.sidecar()
        s["models"]["files"][0]["sha256"] = "0" * 64
        self.assertTrue(any("tampered" in e for e in ei.verify(s, PIN, RID)))

    def test_tampered_identity_is_error(self):
        s = self.sidecar()
        s["identity_sha256"] = "f" * 64
        self.assertTrue(any("tampered" in e for e in ei.verify(s, PIN, RID)))

    def test_malformed_sidecars_are_errors(self):
        self.assertTrue(ei.verify([], PIN, RID))
        self.assertTrue(ei.verify({"schema": "x"}, PIN, RID))
        s = self.sidecar()
        for mutate in (
            lambda d: d.pop("models"),
            lambda d: d["models"].update(files=[]),
            lambda d: d["models"]["files"][0].update(sha256="nothex"),
            lambda d: d.update(osdi="no"),
        ):
            bad = copy.deepcopy(s)
            mutate(bad)
            self.assertTrue(ei.verify(bad, PIN, RID))

    def test_missing_osdi_manifest_is_error(self):
        s = self.sidecar()
        s["osdi"]["manifest_sha256"] = None
        self.assertTrue(any("OSDI" in e for e in ei.verify(s, PIN, RID)))
        make_install(self.tmp / "n")
        (self.tmp / "n/ihp-sg13g2" / ei.OSDI_MANIFEST_REL).unlink()
        self.assertTrue(any("OSDI" in e for e in ei.verify(ei.capture(self.tmp / "n", "ihp-sg13g2", PIN, RID, "ngspice-46"), PIN, RID)))

    def test_unresolved_include_is_error(self):
        make_install(self.tmp / "u")
        inst = self.tmp / "u/ihp-sg13g2"
        (inst / ei.MODELS_SUBDIR / "sub/mos.inc").unlink()
        s = ei.capture(self.tmp / "u", "ihp-sg13g2", PIN, RID, "ngspice-46")
        self.assertTrue(any("unresolved" in e for e in ei.verify(s, PIN, RID)))

    def test_incompatible_release_marker_or_config_is_error(self):
        s = capture(self.tmp / "m", marker="0.2.9")
        self.assertTrue(any("observed install release" in e for e in ei.verify(s, PIN, RID)))
        s = self.sidecar()
        newer = dict(PIN, release_tag="v0.4.0")
        self.assertTrue(any("incompatible" in e for e in ei.verify(s, newer, RID)))

    def test_wrong_record_or_simulator_is_error(self):
        s = self.sidecar()
        self.assertTrue(any("bound to record" in e for e in ei.verify(s, PIN, "20260202-000000-0000abc")))
        self.assertTrue(any("simulator" in e for e in ei.verify(s, PIN, RID, ngspice="ngspice-47")))

    def test_cli_capture_refuses_overwrite_and_verify_roundtrips(self):
        make_install(self.tmp / "c")
        out = self.tmp / "side.env.json"
        argv = ["capture", "--pdk-root", str(self.tmp / "c"), "--pdk", "ihp-sg13g2", "--pin", str(HERE.parent / "pdk.json"),
                "--record-id", RID, "--ngspice", "ngspice-46", "--out", str(out)]
        self.assertEqual(ei.main(argv), 0)
        self.assertEqual(ei.main(["verify", "--sidecar", str(out), "--pin", str(HERE.parent / "pdk.json"), "--record-id", RID]), 0)
        self.assertEqual(ei.main(argv), 1)


if __name__ == "__main__":
    unittest.main()

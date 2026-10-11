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


class Compare(unittest.TestCase):
    """compare(): begin vs finalize capture of one run (#209)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        make_install(self.tmp / "a")
        self.inst = self.tmp / "a" / "ihp-sg13g2"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def cap(self, root=None, pin=PIN, rid=RID, ngspice="ngspice-46") -> dict:
        return ei.capture(root or self.tmp / "a", "ihp-sg13g2", pin, rid, ngspice)

    def test_unchanged_install_has_no_drift(self):
        self.assertEqual(ei.compare(self.cap(), self.cap()), [])

    def test_changed_used_include_byte_names_the_file(self):
        before = self.cap()
        (self.inst / ei.MODELS_SUBDIR / "sub/mos.inc").write_text("* mos tt, edited mid-run\n", encoding="utf-8")
        errs = ei.compare(before, self.cap())
        self.assertTrue(any("libs.tech/ngspice/models/sub/mos.inc" in e and "changed" in e for e in errs), errs)
        self.assertTrue(any("identity_sha256" in e for e in errs), errs)

    def test_closure_growth_and_shrink_are_drift(self):
        before = self.cap()
        (self.inst / ei.MODELS_SUBDIR / "cornerCAP.lib").write_text('.include "extra.inc"\n', encoding="utf-8")
        (self.inst / ei.MODELS_SUBDIR / "extra.inc").write_text("* extra\n", encoding="utf-8")
        after = self.cap()
        self.assertTrue(any("added to the closure" in e and "extra.inc" in e for e in ei.compare(before, after)))
        self.assertTrue(any("removed from the closure" in e and "extra.inc" in e for e in ei.compare(after, before)))

    def test_unresolved_include_change_is_drift(self):
        before = self.cap()
        (self.inst / ei.MODELS_SUBDIR / "sub/mos.inc").unlink()
        errs = ei.compare(before, self.cap())
        self.assertTrue(any("unresolved" in e for e in errs), errs)

    def test_osdi_manifest_change_is_drift(self):
        before = self.cap()
        (self.inst / ei.OSDI_MANIFEST_REL).write_text("schema=1\noutput.psp103.osdi=deadbeef\n", encoding="utf-8")
        errs = ei.compare(before, self.cap())
        self.assertTrue(any("OSDI build-manifest" in e for e in errs), errs)

    def test_release_marker_change_is_drift(self):
        before = self.cap()
        (self.inst / ".fetched-version").write_text("0.3.1\n", encoding="utf-8")
        errs = ei.compare(before, self.cap())
        self.assertTrue(any("release marker" in e for e in errs), errs)

    def test_configured_pin_change_is_drift(self):
        before = self.cap()
        for key, value in (("release_tag", "v9.9.9"), ("source", "elsewhere"), ("variant", "other")):
            errs = ei.compare(before, self.cap(pin=dict(PIN, **{key: value})))
            self.assertTrue(any(f"configured {key}" in e for e in errs), (key, errs))

    def test_ngspice_change_is_drift(self):
        errs = ei.compare(self.cap(), self.cap(ngspice="ngspice-47"))
        self.assertTrue(any("ngspice" in e for e in errs), errs)

    def test_host_path_only_change_is_not_drift(self):
        make_install(self.tmp / "elsewhere" / "deeper")
        self.assertEqual(ei.compare(self.cap(), self.cap(root=self.tmp / "elsewhere" / "deeper")), [])

    def test_record_id_alone_is_not_drift(self):
        self.assertEqual(ei.compare(self.cap(), self.cap(rid="20260202-000000-0000abc")), [])

    def test_non_object_is_error(self):
        self.assertTrue(ei.compare([], self.cap()))

    def cli(self, before: Path, root: Path | None = None) -> int:
        return ei.main(["compare", "--before", str(before), "--pdk-root", str(root or self.tmp / "a"),
                        "--pdk", "ihp-sg13g2", "--pin", str(HERE.parent / "pdk.json"), "--ngspice", "ngspice-46"])

    def test_cli_compare_passes_unchanged_and_fails_on_drift(self):
        before = self.tmp / "begin.env.json"
        before.write_text(ei.canonical_json(self.cap()), encoding="utf-8")
        self.assertEqual(self.cli(before), 0)
        make_install(self.tmp / "moved")
        self.assertEqual(self.cli(before, self.tmp / "moved"), 0)
        (self.inst / ei.MODELS_SUBDIR / "sub/mos.inc").write_text("* drifted\n", encoding="utf-8")
        self.assertEqual(self.cli(before), 1)

    def test_cli_compare_uses_begin_model_roots(self):
        side = ei.capture(self.tmp / "a", "ihp-sg13g2", PIN, RID, "ngspice-46", models=("cornerCAP.lib",))
        before = self.tmp / "begin.env.json"
        before.write_text(ei.canonical_json(side), encoding="utf-8")
        self.assertEqual(self.cli(before), 0)  # would differ under DEFAULT_MODELS

    def test_cli_compare_unreadable_before_is_error(self):
        self.assertEqual(self.cli(self.tmp / "missing.env.json"), 1)
        bad = self.tmp / "bad.env.json"
        bad.write_text("[]", encoding="utf-8")
        self.assertEqual(self.cli(bad), 1)


if __name__ == "__main__":
    unittest.main()

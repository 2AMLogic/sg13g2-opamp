#!/usr/bin/env python3
"""Tests for env_identity.py (stdlib unittest; no PDK, simulator or network).

  python3 -m unittest discover -s sim/tools -p 'test_env_identity.py' -v
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import env_identity as ei  # noqa: E402

PIN = json.loads((HERE.parent / "pdk.json").read_text(encoding="utf-8"))
RID = "20260101-000000-abcdef0"


def osdi_binary(model: str) -> bytes:
    return f"fake osdi binary for {model}\n".encode()


def osdi_manifest(extra: str = "", models=ei.REQUIRED_OSDI_MODELS) -> str:
    """A build-osdi.sh-shaped manifest whose output hashes match `osdi_binary`."""
    lines = ["schema=1", "openvaf_tag=fixture"]
    lines += [f"output.{m}.osdi={ei.sha256_bytes(osdi_binary(m))}" for m in models]
    return "\n".join(lines) + "\n" + extra


def make_install(root: Path, marker: str = "0.3.0", mos_body: str = "* mos tt\n", manifest: str | None = None) -> Path:
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
    for m in ei.REQUIRED_OSDI_MODELS:
        (osdi / f"{m}.osdi").write_bytes(osdi_binary(m))
    (osdi / ".build-manifest").write_text(osdi_manifest() if manifest is None else manifest, encoding="utf-8")
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
        b = capture(self.tmp / "b", manifest=osdi_manifest("openvaf_tag=other\n"))
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
        (self.inst / ei.OSDI_MANIFEST_REL).write_text(osdi_manifest("openvaf_tag=other\n"), encoding="utf-8")
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


class OsdiOutputValidation(unittest.TestCase):
    """#218: the manifest is accepted as identity only if the live binaries satisfy it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.inst = make_install(self.tmp)
        self.osdi = self.inst / ei.OSDI_DIR_REL

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def cap(self) -> dict:
        return ei.capture(self.tmp, "ihp-sg13g2", PIN, RID, "ngspice-46")

    def refuses(self, model: str, *needles: str) -> None:
        with self.assertRaises(ei.IdentityError) as cm:
            self.cap()
        msg = str(cm.exception)
        self.assertIn(f"{model}:", msg)
        for n in needles:
            self.assertIn(n, msg)

    def test_unchanged_install_captures_and_verifies(self):
        self.assertEqual(ei.verify(self.cap(), PIN, RID), [])

    def test_each_replaced_binary_refuses_naming_the_model(self):
        for m in ei.REQUIRED_OSDI_MODELS:
            with self.subTest(m):
                (self.osdi / f"{m}.osdi").write_bytes(b"replaced\n")
                self.refuses(m, "does not match")
                (self.osdi / f"{m}.osdi").write_bytes(osdi_binary(m))
                self.cap()

    def test_each_deleted_binary_refuses(self):
        for m in ei.REQUIRED_OSDI_MODELS:
            with self.subTest(m):
                (self.osdi / f"{m}.osdi").unlink()
                self.refuses(m, "missing")
                (self.osdi / f"{m}.osdi").write_bytes(osdi_binary(m))

    def test_unreadable_binary_refuses(self):
        (self.osdi / "r3_cmc.osdi").unlink()
        (self.osdi / "r3_cmc.osdi").mkdir()  # a directory is not a binary
        self.refuses("r3_cmc", "missing")

    def test_each_removed_entry_refuses(self):
        for m in ei.REQUIRED_OSDI_MODELS:
            with self.subTest(m):
                (self.osdi / ".build-manifest").write_text(osdi_manifest(models=[x for x in ei.REQUIRED_OSDI_MODELS if x != m]), encoding="utf-8")
                self.refuses(m, "no output")

    def test_corrupt_or_duplicate_entry_refuses(self):
        good = osdi_manifest()
        for bad in (good.replace(ei.sha256_bytes(osdi_binary("mosvar")), "MISSING"),
                    good.replace(ei.sha256_bytes(osdi_binary("mosvar")), "abc"),
                    good + f"output.mosvar.osdi={ei.sha256_bytes(osdi_binary('mosvar'))}\n"):
            with self.subTest(bad[-40:]):
                (self.osdi / ".build-manifest").write_text(bad, encoding="utf-8")
                self.refuses("mosvar", "malformed")

    def test_wrong_hash_refuses(self):
        good = osdi_manifest()
        (self.osdi / ".build-manifest").write_text(
            good.replace(ei.sha256_bytes(osdi_binary("psp103_nqs")), "0" * 64), encoding="utf-8")
        self.refuses("psp103_nqs", "does not match")

    def test_unsupported_or_missing_schema_refuses(self):
        for text in (osdi_manifest().replace("schema=1", "schema=2"), "\n".join(osdi_manifest().splitlines()[1:]) + "\n"):
            with self.subTest(text[:12]):
                (self.osdi / ".build-manifest").write_text(text, encoding="utf-8")
                with self.assertRaises(ei.IdentityError) as cm:
                    self.cap()
                self.assertIn("unsupported schema", str(cm.exception))

    def test_binary_resolving_outside_osdi_dir_refuses(self):
        outside = self.tmp / "elsewhere.osdi"
        outside.write_bytes(osdi_binary("mosvar"))
        (self.osdi / "mosvar.osdi").unlink()
        (self.osdi / "mosvar.osdi").symlink_to(outside)
        self.refuses("mosvar", "outside")

    def test_required_models_agree_with_build_script(self):
        text = (HERE / "build-osdi.sh").read_text(encoding="utf-8")
        entries = re.search(r"^MODELS=\((.*)\)\s*$", text, re.MULTILINE).group(1)
        names = [e.strip('"').split(":")[0] for e in entries.split()]
        self.assertEqual(sorted(names), sorted(ei.REQUIRED_OSDI_MODELS))
        schema = re.search(r"^MANIFEST_SCHEMA=(\S+)$", text, re.MULTILINE).group(1)
        self.assertEqual(schema, ei.OSDI_MANIFEST_SCHEMA)
        # the script renders exactly the entry shape the validator parses
        self.assertIn('echo "output.${model}.osdi=', text)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Negative controls for check_signoff.py and sync_integrator.py (stdlib, offline).

  python3 -m unittest discover -s signoff -p 'test_check_signoff.py' -v

A small fixture tree (manifest, pinned inputs, evidence artifacts, a report
and an integrator view) is built in a temp dir and passes with zero failures.
Each control then applies exactly one mutation and asserts a specific
diagnostic substring. The checkers' path globals are patched to the fixture;
the real checkout is never modified. No klt, no ngspice, no network, and the
`generate.py --check` subprocess is never run (no fixture cites item 8).
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_signoff as ck  # noqa: E402
import sync_integrator as si  # noqa: E402

REPORT_NAME = "20260101-000000-abcdef1.signoff.json"
N_ITEMS = ck.MAX_ITEM_ID
ITEM_11_PARTS = ("art/erc.txt", "art/lvs.txt")


def _dump(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

        for name, text in (("a", "alpha"), ("erc", "e"), ("lvs", "l")):
            (self.root / "art").mkdir(exist_ok=True)
            (self.root / "art" / f"{name}.txt").write_text(text)
        for name in ("e1", "e11a", "e11b"):
            _dump(self.root / "signoff" / "evidence" / f"{name}.json", {"n": name})

        def entry(env: str, artifact: str) -> dict:
            return {
                "file": f"signoff/evidence/{env}.json",
                "kind": "sim",
                "content_hash": ck.sha256_file(self.root / artifact),
            }

        # LVS reference fixture: request + reference + an envelope recording
        # the reference hash, cited as the LVS part of item 11 (and item 4 in
        # the dedicated controls).
        (self.root / "lay").mkdir(exist_ok=True)
        (self.root / "lay" / "ref.spice").write_text("* ref\n")
        _dump(self.root / "lay" / "lvs_request.json",
              {"reference": {"netlist": "ref.spice"}})
        self.lvs_env = {
            "reference": "ref.spice",
            "environment": {"reference_sha256": ck.sha256_file(
                self.root / "lay" / "ref.spice").removeprefix("sha256:")},
        }
        _dump(self.root / "signoff" / "evidence" / "e11b.json", self.lvs_env)

        self.manifest = {
            "block": "fixture",
            "kind": "analog",
            "evidence": {
                "1": entry("e1", "art/a.txt"),
                "11": [entry("e11a", ITEM_11_PARTS[0]),
                       {**entry("e11b", ITEM_11_PARTS[1]), "kind": "lvs"}],
            },
        }
        self.pins = {"inputs": {"1": "art/a.txt", "11": list(ITEM_11_PARTS)}}
        ev = self.manifest["evidence"]
        items = []
        for i in range(1, N_ITEMS + 1):
            row = {"tier": "T1", "id": i, "status": "no_evidence"}
            if i == 1:
                row.update(status="met", citation=dict(ev["1"]))
            if i == 11:
                parts = [dict(p) for p in reversed(ev["11"])]  # order is klt's
                row.update(status="met", citation={**parts[0], "parts": parts})
            items.append(row)
        self.report = {
            "block": "fixture",
            "kind": "analog",
            "tier": None,
            "t1_item_count": N_ITEMS,
            "t1_met_count": 2,
            "items": items,
        }
        self.reports_dir = self.root / "signoff" / "reports"

        # Integrator view, derived from the fixture report so it starts fresh.
        for rel_path in ("schematic.sch", "symbol.sym", "sizing.md", "net.spice",
                         si.GDS_PATH):
            p = self.root / rel_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        self.integrator_doc = None  # built lazily after report is written

        patches = [
            mock.patch.object(ck, "REPO_ROOT", self.root),
            mock.patch.object(ck, "MANIFEST", self.root / "signoff" / "block-manifest.json"),
            mock.patch.object(ck, "PINNED_INPUTS", self.root / "signoff" / "pinned-inputs.json"),
            mock.patch.object(ck, "REPORTS_DIR", self.reports_dir),
            mock.patch.object(ck, "LVS_REQUEST", self.root / "lay" / "lvs_request.json"),
            mock.patch.object(si, "REPO_ROOT", self.root),
            mock.patch.object(si, "INTEGRATOR", self.root / "spec" / "integrator.json"),
            mock.patch.object(si, "REPORTS_DIR", self.reports_dir),
            # Guard: no test may spawn generate.py or klt.
            mock.patch.object(ck.subprocess, "run", side_effect=AssertionError("subprocess")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # -- helpers ---------------------------------------------------------
    def write(self) -> None:
        _dump(self.root / "signoff" / "block-manifest.json", self.manifest)
        _dump(self.root / "signoff" / "pinned-inputs.json", self.pins)
        _dump(self.reports_dir / REPORT_NAME, self.report)

    def run_checks(self) -> list[str]:
        """Run the offline chain exactly as check_signoff.main does."""
        self.write()
        failures = ck.Failures()
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = ck.load_json(ck.MANIFEST, failures, "manifest")
            evidence = ck.check_manifest(manifest, failures)
            ck.check_pins(evidence, failures)
            ck.check_lvs_reference(evidence, failures)
            ck.check_characterization(evidence, failures)
            path = ck.latest_report(failures)
            if path is not None:
                doc = ck.load_json(path, failures, "report")
                ck.check_report(doc, manifest, evidence, failures)
        return failures.messages

    def assertFails(self, needle: str) -> None:
        messages = self.run_checks()
        self.assertTrue(
            any(needle in m for m in messages),
            f"no message containing {needle!r}; got {messages!r}",
        )

    def latest(self) -> list[str]:
        failures = ck.Failures()
        with contextlib.redirect_stdout(io.StringIO()):
            ck.latest_report(failures)
        return failures.messages

    def row(self, item_id: int) -> dict:
        return next(r for r in self.report["items"] if r["id"] == item_id)


class BaselineTest(FixtureCase):
    def test_baseline_has_zero_failures(self):
        self.assertEqual(self.run_checks(), [])


class LvsReferenceTest(FixtureCase):
    def edit_env(self, mutate) -> None:
        mutate(self.lvs_env)
        _dump(self.root / "signoff" / "evidence" / "e11b.json", self.lvs_env)

    def cite_item_4(self) -> None:
        self.manifest["evidence"]["4"] = {
            **self.manifest["evidence"]["11"][1], "file": "signoff/evidence/e4.json"}
        _dump(self.root / "signoff" / "evidence" / "e4.json", self.lvs_env)
        self.pins["inputs"]["4"] = ITEM_11_PARTS[1]

    def test_item_4_baseline(self):
        self.cite_item_4()
        self.assertEqual(self.run_checks(), [])

    def test_reference_bytes_changed_compound(self):
        (self.root / "lay" / "ref.spice").write_text("* edited\n")
        self.assertFails("ref.spice has changed since the LVS match")

    def test_reference_bytes_changed_item_4(self):
        self.cite_item_4()
        (self.root / "lay" / "ref.spice").write_text("* edited\n")
        self.assertFails("evidence['4'] was recorded")

    def test_missing_hash_compound(self):
        self.edit_env(lambda e: e["environment"].pop("reference_sha256"))
        self.assertFails("missing or malformed environment.reference_sha256")

    def test_malformed_hash_item_4(self):
        self.cite_item_4()
        self.edit_env(lambda e: e["environment"].update(reference_sha256="sha256:abc"))
        self.assertFails("missing or malformed environment.reference_sha256")

    def test_missing_reference_file(self):
        (self.root / "lay" / "ref.spice").unlink()
        self.assertFails("does not exist")

    def test_report_names_other_reference(self):
        self.edit_env(lambda e: e.update(reference="other.spice"))
        self.assertFails("records reference 'other.spice'")

    def test_lvs_part_first_in_list(self):
        self.manifest["evidence"]["11"].reverse()
        self.pins["inputs"]["11"].reverse()
        (self.root / "lay" / "ref.spice").write_text("* edited\n")
        self.assertFails("evidence['11[0]'] was recorded")


class ManifestTest(FixtureCase):
    def test_empty_block(self):
        self.manifest["block"] = "  "
        self.assertFails("`block` must be a non-empty string")

    def test_missing_block(self):
        del self.manifest["block"]
        self.assertFails("`block` must be a non-empty string")

    def test_invalid_block_kind(self):
        self.manifest["kind"] = "quantum"
        self.assertFails("`kind` must be one of")

    def test_unknown_evidence_key(self):
        self.manifest["evidence"]["12"] = copy.deepcopy(self.manifest["evidence"]["1"])
        self.assertFails("names no T1 item")

    def test_partition_key_on_non_mixed_signal_block(self):
        self.manifest["evidence"]["1.analog"] = copy.deepcopy(self.manifest["evidence"]["1"])
        self.assertFails("per-partition")

    def test_entry_without_content_hash(self):
        del self.manifest["evidence"]["1"]["content_hash"]
        self.assertFails("pins no `content_hash`")

    def test_cited_file_missing(self):
        (self.root / "signoff" / "evidence" / "e1.json").unlink()
        self.write()  # keep the unlink effective: write() does not recreate it
        self.assertFails("cites missing file signoff/evidence/e1.json")

    def test_list_on_non_compound_item(self):
        ev = self.manifest["evidence"]
        ev["1"] = [ev["1"]]
        self.assertFails("accept the compound")

    def test_empty_compound_list(self):
        self.manifest["evidence"]["11"] = []
        self.assertFails("is an empty list")

    def test_entry_neither_file_nor_command(self):
        del self.manifest["evidence"]["1"]["file"]
        self.assertFails("has neither a `file` nor a `command`")

    def test_entry_not_an_object(self):
        self.manifest["evidence"]["1"] = "signoff/evidence/e1.json"
        self.assertFails("must be an object pinning")


class PinsTest(FixtureCase):
    def test_artifact_bytes_changed(self):
        (self.root / "art" / "a.txt").write_text("changed")
        self.assertFails("has changed since evidence['1'] was pinned")

    def test_compound_part_artifact_changed(self):
        (self.root / "art" / "lvs.txt").write_text("changed")
        self.assertFails("has changed since evidence['11[1]'] was pinned")

    def test_inputs_entry_for_uncited_item(self):
        self.pins["inputs"]["5"] = "art/a.txt"
        self.assertFails("pins an artifact for an item the manifest does not cite")

    def test_cited_item_without_pinned_artifact(self):
        del self.pins["inputs"]["1"]
        self.assertFails("no artifact recorded for evidence['1']")

    def test_compound_pin_list_wrong_length(self):
        self.pins["inputs"]["11"] = [ITEM_11_PARTS[0]]
        self.assertFails("must be a list of 2 artifact path(s)")


class ReportTest(FixtureCase):
    def test_item_count_wrong(self):
        self.report["t1_item_count"] = N_ITEMS + 1
        self.assertFails(f"t1_item_count {N_ITEMS + 1} != the {N_ITEMS} T1 rows rendered")

    def test_item_count_below_expected(self):
        self.report["items"] = [r for r in self.report["items"] if r["id"] != 7]
        self.report["t1_item_count"] = N_ITEMS - 1
        self.assertFails(f"only {N_ITEMS - 1} T1 items graded")

    def test_met_count_wrong_after_status_flip(self):
        self.row(1)["status"] = "unmet"
        self.assertFails("t1_met_count 2 != the 1 T1 rows actually rendered `met`")

    def test_met_row_citation_file_differs(self):
        self.row(1)["citation"]["file"] = "signoff/evidence/other.json"
        self.assertFails("item 1 cites 'signoff/evidence/other.json'")

    def test_met_row_citation_hash_differs(self):
        self.row(1)["citation"]["content_hash"] = "sha256:" + "0" * 64
        self.assertFails("item 1 citation hash")

    def test_met_row_without_manifest_citation(self):
        self.row(2)["status"] = "met"
        self.report["t1_met_count"] = 3
        self.assertFails("item 2 is `met` but the manifest cites nothing for it")

    def test_compound_cited_set_differs(self):
        self.row(11)["citation"]["parts"][0]["content_hash"] = "sha256:" + "1" * 64
        self.assertFails("item 11 is `met` on the cited set")

    def test_report_block_mismatch(self):
        self.report["block"] = "other"
        self.assertFails("report: block 'other' != manifest block 'fixture'")

    def test_report_kind_mismatch(self):
        self.report["kind"] = "digital"
        self.assertFails("report: kind 'digital' != manifest kind 'analog'")

    def test_empty_items(self):
        self.report["items"] = []
        self.assertFails("`items` is missing or empty")

    def test_manifest_cites_item_report_does_not_render(self):
        self.report["items"] = [r for r in self.report["items"] if r["id"] != 1]
        self.assertFails("manifest cites item 1, which the report does not render")


class LatestReportTest(FixtureCase):
    def test_no_report_directory(self):
        self.assertTrue(any("no report directory" in m for m in self.latest()))

    def test_no_reports(self):
        self.reports_dir.mkdir(parents=True)
        self.assertTrue(any("holds no *.signoff.json record" in m for m in self.latest()))

    def test_bad_record_id_name(self):
        self.reports_dir.mkdir(parents=True)
        (self.reports_dir / "notarecord.signoff.json").write_text("{}")
        self.assertTrue(
            any("notarecord.signoff.json does not use the" in m for m in self.latest())
        )


class CharacterizationTest(FixtureCase):
    def test_other_item_cites_characterization_envelope(self):
        self.manifest["evidence"]["1"]["file"] = ck.CHARACTERIZATION_ENVELOPE
        self.assertFails("it is item 8 evidence only")


class IntegratorTest(FixtureCase):
    def build_integrator(self) -> dict:
        self.write()
        derived = si.derive()
        doc = {
            "artifacts": {
                "schematic": "schematic.sch",
                "symbol": "symbol.sym",
                "sizing_derivation": "sizing.md",
                "netlist": "net.spice",
                "gds": derived["gds"],
                "gds_note": derived["gds_note"],
            },
            "maturity": {
                k: derived[k]
                for k in ("tier", "t1_items_total", "t1_items_met", "statement",
                          "source_record")
            },
            "provenance": {"signoff_record": derived["signoff_record"]},
        }
        self.integrator_doc = doc
        return doc

    def check(self, doc: dict) -> list[str]:
        _dump(si.INTEGRATOR, doc)
        return si.check()

    def test_baseline_clean(self):
        self.assertEqual(self.check(self.build_integrator()), [])

    def test_stale_met_count(self):
        doc = self.build_integrator()
        doc["maturity"]["t1_items_met"] += 1
        problems = self.check(doc)
        self.assertTrue(any(p.startswith("stale t1_items_met:") for p in problems), problems)

    def test_stale_source_record(self):
        doc = self.build_integrator()
        doc["maturity"]["source_record"] = "signoff/reports/19990101-000000-0000000.signoff.json"
        problems = self.check(doc)
        self.assertTrue(any(p.startswith("stale source_record:") for p in problems), problems)

    def test_missing_artifact_path(self):
        doc = self.build_integrator()
        (self.root / "net.spice").unlink()
        problems = self.check(doc)
        self.assertTrue(
            any("artifacts.netlist 'net.spice' does not resolve" in p for p in problems),
            problems,
        )


if __name__ == "__main__":
    unittest.main()

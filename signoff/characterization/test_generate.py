#!/usr/bin/env python3
"""Negative controls and reproduction tests for generate.py (stdlib unittest).

  python3 -m unittest discover -s signoff/characterization -v

Each control copies only the inputs the committed selection names into a
throwaway repo tree, perturbs one thing, re-pins where the perturbation is a
*deliberate* re-selection (so the check under test is reached instead of the
hash pin), and asserts the verdict that perturbation must produce. Needs no
ngspice and no PDK.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402
import generate  # noqa: E402

sys.path.insert(0, str(HERE.parent.parent / "sim" / "cmrr-mismatch"))
import mc_samples  # noqa: E402

sys.path.insert(0, str(HERE.parent.parent / "sim" / "slew-rate"))
import slew_post  # noqa: E402

sys.path.insert(0, str(HERE.parent.parent / "sim" / "output-swing"))
import swing_post  # noqa: E402

sys.path.insert(0, str(HERE.parent.parent / "sim" / "input-offset" / "klt"))
import offset_post  # noqa: E402

REPO = HERE.parent.parent
SELECTION = REPO / generate.SELECTION_REL

# Every ratified bound spec/target-spec.md section 2 binds today ([DR-2] and
# the CMRR row's [DR-4]); output swing carries three bounds in one row.
# The three ratified rows whose committed raw worst case misses the literal
# DR-0002 bound and only rounds onto it at the bound's written decimals
# (spec question 2AMLogic/sg13g2-opamp#101). Compared literally, they FAIL.
# DC gain left this list when the selection moved to the corrected
# inn-AC-grounded open-loop record (worst 38.2293 dB against 37.8 dB).
LITERAL_FAIL_IDS = ["input_noise", "offset_systematic", "swing_span"]

# (record, binding point, column, raw cell exactly AT the ratified bound once
# scaled to the bound's unit) for each of the rows above.
AT_BOUND_CELLS = [
    ("input-noise", "mos_fs_125C_1.08V", "vni_int_vrms", "0.0001089"),  # <= 108.9 µVrms
    ("input-offset", "mos_fs_125C_1.08V", "vos_null_v", "0.0219"),      # <= 21.9 mV (absmax)
    ("output-swing", "mos_ss_125C_1.08V", "swing_span_v", "0.571"),     # >= 0.571 V
]

RATIFIED_IDS = {
    "dc_gain", "gbw", "phase_margin", "slew_rate", "input_noise",
    "offset_systematic", "cmrr_mismatch", "psrr", "swing_headroom_vdd",
    "swing_headroom_vss", "swing_span", "quiescent_current",
}


def rows_by_id(content: dict) -> dict:
    return {row["id"]: row for row in content["rows"]}


# The committed input-offset batch record (issue #504): the null + closed-loop
# `klt sim` envelopes and the CSV/MD derived from them, selected in place of
# the harness CSV by OffsetKltAudit's fixtures.
OFFSET_BATCH_RID = "20261124-235819-4314768"
OFFSET_BATCH_FILES = {
    "csv": f"sim/input-offset/records/{OFFSET_BATCH_RID}.csv",
    "md": f"sim/input-offset/records/{OFFSET_BATCH_RID}.md",
    "netlist_snapshot": f"sim/input-offset/netlist-snapshots/{OFFSET_BATCH_RID}/opamp_core.spice",
    "null": f"sim/input-offset/klt/records/{OFFSET_BATCH_RID}.sim.json",
    "cl": f"sim/input-offset/klt/records/{OFFSET_BATCH_RID}.cl.sim.json",
    "null_request": "sim/input-offset/klt/offset.request.json",
    "cl_request": "sim/input-offset/klt/offset_cl.request.json",
    "null_body": "sim/input-offset/klt/tb_offset.body.spice",
    "cl_body": "sim/input-offset/klt/tb_offset_cl.body.spice",
}

# One row per raw-population audit a control can detach, carrying the four
# facts the detach needs: (flag suffix, record whose rewritten CSV fires the
# detach and whose population hangs off it, population key, definition check
# to drop). Each control detaches the audit of the record it edits for the
# control's OWN purpose; the matching RawAuditCase suite tests that audit.
#
# The CMRR sample population has no row: its Av0 join reads the explicitly
# selected `open-loop-ac-floating-inn` record (issue #208), not the corrected
# open-loop record, so editing the corrected gain leaves the mismatch sample
# audit attached (issue #485).
POPULATION_AUDITS = (
    ("klt",   "open-loop-ac",  "klt_raw",    "open_loop_klt_audit"),
    ("noise", "input-noise",   "noise_raw",  "noise_raw_audit"),
    ("swing", "output-swing",  "swing_raw",  "swing_raw_audit"),
    ("cmrr_psrr", "cmrr-psrr",  "cmrr_psrr_klt", "cmrr_psrr_klt_audit"),
)


class Fixture:
    """A minimal repo tree holding exactly the inputs the selection reads."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.selection = json.loads(SELECTION.read_text(encoding="utf-8"))
        files = {self.selection[k] for k in ("spec", "inventory", "pdk_pin", "design_netlist")}
        for rec in self.selection["records"].values():
            files.update(rec[f] for f in ("csv", "md", "netlist_snapshot"))
            if "draws_csv" in rec:
                files.add(rec["draws_csv"])
            if "mc_samples" in rec:
                files.update(e["path"] for e in rec["mc_samples"]["files"].values())
            for two_level in ("noise_raw", "slew_raw", "swing_raw"):
                if two_level in rec:
                    for entry in rec[two_level]["files"].values():
                        files.update(pin["path"] for pin in entry.values())
            if "klt_raw" in rec:
                files.update(pin["path"] for pin in rec["klt_raw"]["files"].values())
            if "cmrr_psrr_klt" in rec:
                files.update(pin["path"] for pin in rec["cmrr_psrr_klt"]["files"].values())
            if "offset_klt_raw" in rec:
                files.update(pin["path"] for pin in rec["offset_klt_raw"]["files"].values())
        files.update({generate.SELECTION_REL, generate.GENERATOR_REL})
        for rel in files:
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)
        self.save_selection()

    def close(self) -> None:
        self._tmp.cleanup()

    @property
    def selection_path(self) -> Path:
        return self.root / generate.SELECTION_REL

    def save_selection(self) -> None:
        self.selection_path.write_text(json.dumps(self.selection, indent=2, ensure_ascii=False), encoding="utf-8")

    def csv_path(self, key: str) -> Path:
        return self.root / self.selection["records"][key]["csv"]

    def draws_path(self, key: str) -> Path:
        return self.root / self.selection["records"][key]["draws_csv"]

    def detach_population(self, suffix: str) -> None:
        """Drop one POPULATION_AUDITS row's raw population and its definition
        check from the selection.

        The shared body of the three named detach methods below; each of those
        records WHY its own control detaches, which is the part that differs.
        """
        _, record, population, check = next(r for r in POPULATION_AUDITS if r[0] == suffix)
        rec = self.selection["records"][record]
        rec.pop(population, None)
        rec["definition_checks"] = [c for c in rec.get("definition_checks", []) if c != check]
        self.save_selection()

    keep_klt_audit = False

    def detach_klt_population(self) -> None:
        """Controls that perturb the open-loop summary for THEIR OWN purpose
        (a bound comparison) drop the raw klt-envelope audit (issue #101);
        KltRawAudit tests that audit itself. The corrected record's prose names
        no ngspice (the envelopes do), so the detached fixture's copy states
        the pinned one, as a real legacy record's does."""
        self.detach_population("klt")
        rec = self.selection["records"]["open-loop-ac"]
        md = self.root / rec["md"]
        md.write_text(md.read_text(encoding="utf-8") + "\nRan on ngspice-46.\n", encoding="utf-8")
        rec["md_sha256"] = generate.sha256_file(md)
        self.save_selection()

    keep_cmrr_psrr_audit = False

    def detach_cmrr_psrr_population(self) -> None:
        """Controls that perturb the cmrr-psrr summary for THEIR OWN purpose
        (a bound comparison) drop the batch-envelope audit (issue #514);
        CmrrPsrrKltAudit tests that audit itself."""
        self.detach_population("cmrr_psrr")

    keep_noise_audit = False

    def detach_noise_population(self) -> None:
        """Controls that perturb the input-noise summary for THEIR OWN purpose
        (a bound comparison) drop the raw-noise audit (issue #213);
        NoiseRawAudit tests that audit itself."""
        self.detach_population("noise")

    keep_swing_audit = False

    def detach_swing_population(self) -> None:
        """Controls that perturb the output-swing summary for THEIR OWN purpose
        (a bound comparison) drop the raw-curve audit (issue #230);
        SwingRawAudit tests that audit itself."""
        self.detach_population("swing")

    def rewrite_csv(self, key: str, transform, repin: bool = True) -> None:
        for suffix, record, *_ in POPULATION_AUDITS:
            if key == record and not getattr(self, f"keep_{suffix}_audit"):
                getattr(self, f"detach_{suffix}_population")()
        path = self.csv_path(key)
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")
        if repin:
            self.selection["records"][key]["csv_sha256"] = generate.sha256_file(path)
            self.save_selection()

    def rewrite_draws(self, key: str, transform, repin: bool = True) -> None:
        """Rewrite the record's pinned draws population (deliberate re-selection)."""
        path = self.draws_path(key)
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")
        if repin:
            self.selection["records"][key]["draws_csv_sha256"] = generate.sha256_file(path)
            self.save_selection()

    def set_draw_cell(self, key: str, point_id: str, draw_index: int, column: str, value: str, repin: bool = True) -> None:
        def transform(lines):
            header = lines[0].split(",")
            idx = header.index(column)
            draw_col = header.index("draw_index")
            out = [lines[0]]
            for line in lines[1:]:
                cells = line.split(",")
                if cells[0] == point_id and cells[draw_col] == str(draw_index):
                    cells[idx] = value
                out.append(",".join(cells))
            return out

        self.rewrite_draws(key, transform, repin)

    def set_cell(self, key: str, point_id: str, column: str, value: str, repin: bool = True) -> None:
        def transform(lines):
            header = lines[0].split(",")
            idx = header.index(column)
            out = [lines[0]]
            for line in lines[1:]:
                cells = line.split(",")
                if cells[0] == point_id:
                    cells[idx] = value
                out.append(",".join(cells))
            return out

        self.rewrite_csv(key, transform, repin)

    def build(self) -> dict:
        return generate.build_content(self.root, self.selection_path)

    def select_offset_batch_record(self) -> None:
        """Swap the selected `input-offset` record from the harness CSV to the
        committed batch record (issue #504): copy its artifacts in, pin every
        hash from the real repo, and repoint the item 9 inventory line at the
        new CSV (a real flip edits the same two files; nothing else moves --
        the rows keep naming the `input-offset` key)."""
        for rel in OFFSET_BATCH_FILES.values():
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)
        self.selection["records"]["input-offset"] = {
            "csv": OFFSET_BATCH_FILES["csv"],
            "csv_sha256": generate.sha256_file(REPO / OFFSET_BATCH_FILES["csv"]),
            "md": OFFSET_BATCH_FILES["md"],
            "md_sha256": generate.sha256_file(REPO / OFFSET_BATCH_FILES["md"]),
            "netlist_snapshot": OFFSET_BATCH_FILES["netlist_snapshot"],
            "grid": "pvt45",
            "valid_when": [["op_pass", "==", "1"], ["xcheck_pass", "==", "1"]],
            "definition_checks": ["offset_magnitude", "offset_klt_audit"],
            "offset_klt_raw": {
                "av0_join": "open-loop-ac",
                "files": {k: {"path": p, "sha256": generate.sha256_file(REPO / p)}
                          for k, p in OFFSET_BATCH_FILES.items()
                          if k in {"null", "cl", "null_request", "cl_request", "null_body", "cl_body"}},
            },
        }
        self.save_selection()
        inv = self.root / "signoff" / "evidence" / "testbenches.txt"
        inv.write_text(
            inv.read_text(encoding="utf-8").replace(
                "sim/input-offset/records/20260918-203858-90844d2.csv", OFFSET_BATCH_FILES["csv"]),
            encoding="utf-8")

    def heal_precision_rows(self) -> None:
        """Set the four literal-FAIL binding points exactly AT their bound.

        Gives an all-PASS baseline (and is itself the exactly-at-bound
        control), so a control below can show that ONE perturbation is what
        moves a row or the report off PASS.
        """
        for key, pid, column, value in AT_BOUND_CELLS:
            self.set_measurement(key, pid, column, value)

    def set_measurement(self, key: str, point_id: str, column: str, value: str) -> None:
        """set_cell, keeping a record's own derived columns consistent so the
        perturbation reaches the bound comparison, not a definition check."""
        self.set_cell(key, point_id, column, value)
        if (key, column) == ("input-offset", "vos_null_v"):
            self.set_cell(key, point_id, "vos_abs_v", value.lstrip("-"))


class CommittedEvidence(unittest.TestCase):
    """The committed selection against the committed evidence."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = generate.build_content(REPO, SELECTION)

    def test_every_ratified_row_present_with_source_binding_units_verdict(self):
        rows = rows_by_id(self.content)
        self.assertEqual({rid for rid, r in rows.items() if r["class"] == "ratified"}, RATIFIED_IDS)
        for rid in RATIFIED_IDS:
            row = rows[rid]
            self.assertTrue(row["unit"], rid)
            self.assertTrue(row["load"], rid)
            self.assertTrue(row["decision_record"], rid)
            self.assertTrue(row["source"]["csv_sha256"].startswith("sha256:"), rid)
            self.assertTrue(row["measured_worst"]["point"], rid)
            self.assertEqual(row["coverage"]["valid"], row["coverage"]["expected"], rid)
            self.assertEqual(row["verdict"], "FAIL" if rid in LITERAL_FAIL_IDS else "PASS", rid)

    def test_overall_fail_and_spec_and_inventory_fully_covered(self):
        # Literal comparison: the committed evidence misses three ratified
        # bounds as written, so the report must not PASS.
        self.assertEqual(self.content["overall"]["verdict"], "FAIL")
        self.assertEqual(self.content["overall"]["ratified_pass"], len(RATIFIED_IDS) - len(LITERAL_FAIL_IDS))
        self.assertEqual(self.content["errors"], [])
        self.assertTrue(all(r["covered"] for r in self.content["spec_coverage"]))
        self.assertTrue(all(r["covered"] for r in self.content["inventory_coverage"]))

    def test_unratified_and_pending_rows_are_separate(self):
        rows = rows_by_id(self.content)
        for rid in ("offset_mc_3sigma", "offset_mc_total", "icmr_span", "icmr_lower", "icmr_upper"):
            self.assertEqual(rows[rid]["class"], "measured")
            self.assertEqual(rows[rid]["verdict"], "MEASURED")
            self.assertNotIn("bound", rows[rid])
        self.assertEqual(rows["area"]["verdict"], "PENDING")
        self.assertFalse(rows["cmrr_systematic"]["binding"])

    def test_offset_systematic_and_statistical_are_distinct_and_mc_is_fixed_supply(self):
        rows = rows_by_id(self.content)
        self.assertEqual(rows["offset_systematic"]["source"]["record"], "input-offset")
        self.assertEqual(rows["offset_mc_3sigma"]["source"]["record"], "input-offset-mc")
        self.assertEqual(rows["offset_mc_3sigma"]["coverage"]["grid"], "offset_mc15")
        self.assertTrue(rows["offset_mc_3sigma"]["measured_worst"]["point"].endswith("_1.20V"))
        self.assertTrue(any("FIXED 1.20 V" in c for c in self.content["caveats"]))

    def test_mc_summary_statistics_follow_from_the_pinned_draws(self):
        # Issue #199: the selected campaign's published statistics must be
        # derivable from its hash-pinned draws population, at the bench's
        # printf %.9g serialization, or the record is an error.
        draws = self.content["sources"]["input-offset-mc"]["draws"]
        self.assertEqual(draws["status"], "verified")
        self.assertEqual(draws["points"], 16)  # 15 mismatch points + negctrl
        self.assertEqual(draws["draws"], 4800)
        self.assertEqual(draws["passing_draws"], 4800)
        self.assertEqual(self.content["errors"], [])
        self.assertNotIn("input-offset-mc", self.content["environment"]["pdk_provenance"]["error"])

    def test_binding_points_match_spec_prose(self):
        rows = rows_by_id(self.content)
        self.assertEqual(rows["dc_gain"]["measured_worst"]["point"], "mos_fs_125C_1.08V")
        self.assertEqual(rows["cmrr_mismatch"]["measured_worst"]["point"], "mos_ss_-40C_1.08V")
        # The spec prose still names the superseded floating-inn harness corner
        # (FF / 125 C / 1.32 V); the batch record (issue #514) binds at FS / 125 C / 1.08 V.
        self.assertEqual(rows["psrr"]["measured_worst"]["point"], "mos_fs_125C_1.08V")
        self.assertEqual(rows["quiescent_current"]["measured_worst"]["point"], "mos_ss_-40C_1.32V")

    def test_literal_failures_are_graded_fail_and_disclosed(self):
        rows = rows_by_id(self.content)
        self.assertEqual(self.content["overall"]["fail_only_beyond_written_decimals"], LITERAL_FAIL_IDS)
        expected = {
            "input_noise": ("108.949", "mos_fs_125C_1.08V"),
            "offset_systematic": ("21.9273527", "mos_fs_125C_1.08V"),
            "swing_span": ("0.570957773", "mos_ss_125C_1.08V"),
        }
        for rid, (value, point) in expected.items():
            row = rows[rid]
            self.assertEqual(row["verdict"], "FAIL", rid)
            self.assertFalse(row["meets_bound"], rid)
            self.assertEqual(row["violating_points"], [point], rid)
            self.assertEqual((row["measured_worst"]["value"], row["measured_worst"]["point"]), (value, point), rid)
            self.assertTrue(row["measured_worst"]["raw_margin"].startswith("-"), rid)

    def test_comparison_rule_is_literal(self):
        rule = self.content["comparison_rule"]
        self.assertIn("compared literally", rule)
        self.assertIn("never gates a verdict", rule)
        self.assertTrue(any("#101" in c for c in self.content["caveats"]))

    def test_reproduction_is_deterministic_apart_from_metadata(self):
        again = generate.build_content(REPO, SELECTION)
        self.assertEqual(generate.canonical_json(self.content), generate.canonical_json(again))
        a = generate.make_report(self.content, "20000101-000000-aaaaaaa", REPO)
        b = generate.make_report(again, "20990101-000000-bbbbbbb", REPO)
        self.assertEqual(a["content_sha256"], b["content_sha256"])
        strip = lambda md: md.split("## Reproduce", 1)[1]  # noqa: E731
        self.assertEqual(strip(generate.render_markdown(a)), strip(generate.render_markdown(b)))

    def test_committed_report_reproduces(self):
        if generate.latest_report(REPO / generate.REPORTS_REL) is None:
            self.skipTest("no report minted yet")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = generate.check(REPO, SELECTION, None)
        self.assertEqual(rc, 0, out.getvalue())


class PdkProvenance(unittest.TestCase):
    """Issue #191: selected records pin a run-time PDK/model identity sidecar."""

    KEY = "input-noise"

    def setUp(self) -> None:
        self.fx = Fixture()
        self.pdk = tempfile.TemporaryDirectory()
        sys.path.insert(0, str(REPO / "sim" / "tools"))
        import env_identity
        import test_env_identity

        self.ei = env_identity
        test_env_identity.make_install(Path(self.pdk.name))
        self.pin = json.loads((self.fx.root / self.fx.selection["pdk_pin"]).read_text(encoding="utf-8"))
        self.rec = self.fx.selection["records"][self.KEY]
        self.record_id = Path(self.rec["csv"]).stem
        self.side_rel = str(Path(self.rec["csv"]).with_suffix(".env.json"))

    def tearDown(self) -> None:
        self.pdk.cleanup()
        self.fx.close()

    def select(self, sidecar: dict | str) -> None:
        path = self.fx.root / self.side_rel
        path.write_text(sidecar if isinstance(sidecar, str) else json.dumps(sidecar), encoding="utf-8")
        self.rec["env_sidecar"] = self.side_rel
        self.rec["env_sidecar_sha256"] = generate.sha256_file(path)
        self.fx.save_selection()

    def good(self) -> dict:
        return self.ei.capture(Path(self.pdk.name), "ihp-sg13g2", self.pin, self.record_id, "ngspice-46")

    def prov(self, content: dict, key: str | None = None) -> dict:
        return content["sources"][key or self.KEY]["pdk_provenance"]

    def test_committed_records_without_sidecar_are_visibly_legacy(self):
        content = self.fx.build()
        env = content["environment"]["pdk_provenance"]
        self.assertEqual(len(env["legacy_unverified"]), len(content["sources"]))
        self.assertFalse(env["pdk_reproducibility_verified"])
        md = generate.render_markdown(generate.make_report(content, None, self.fx.root))
        self.assertIn("legacy-unverified", md)
        self.assertIn("NOT claimed", md)
        self.assertEqual(content["overall"]["verdict"], "FAIL")  # electrical verdict unchanged

    def test_valid_sidecar_is_verified_and_shown(self):
        self.select(self.good())
        content = self.fx.build()
        self.assertEqual(self.prov(content)["status"], "verified")
        self.assertIn(self.KEY, content["environment"]["pdk_provenance"]["verified"])
        self.assertEqual(content["overall"]["verdict"], "FAIL")
        self.assertEqual(content["errors"], [])
        self.assertIn("verified 1", generate.render_markdown(generate.make_report(content, None, self.fx.root)))

    def assert_provenance_error(self, text: str) -> None:
        content = self.fx.build()
        self.assertEqual(self.prov(content)["status"], "error")
        row = rows_by_id(content)["input_noise"]
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("PDK provenance error" in e and text in e for e in row["errors"]), row["errors"])
        self.assertFalse(content["environment"]["pdk_provenance"]["pdk_reproducibility_verified"])

    def test_missing_sidecar_is_error(self):
        self.select(self.good())
        (self.fx.root / self.side_rel).unlink()
        self.assert_provenance_error("missing environment sidecar")

    def test_unpinned_change_is_error(self):
        self.select(self.good())
        path = self.fx.root / self.side_rel
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.assert_provenance_error("does not match its selection pin")

    def test_malformed_sidecar_is_error(self):
        self.select("{not json")
        self.assert_provenance_error("not valid JSON")
        self.select({"schema": self.ei.SCHEMA})
        self.assert_provenance_error("malformed")

    def test_tampered_sidecar_repinned_is_error(self):
        side = self.good()
        side["models"]["files"][0]["sha256"] = "1" * 64
        self.select(side)
        self.assert_provenance_error("tampered")

    def test_sidecar_of_another_record_is_error(self):
        side = self.good()
        side["record_id"] = "20260101-000000-0000000"
        self.select(side)
        self.assert_provenance_error("bound to record")

    def test_configuration_release_change_cannot_relabel_records_as_verified(self):
        self.select(self.good())
        pin_path = self.fx.root / self.fx.selection["pdk_pin"]
        self.pin["release_tag"] = "v0.4.0"
        pin_path.write_text(json.dumps(self.pin), encoding="utf-8")
        self.assert_provenance_error("incompatible")

    def test_incompatible_observed_install_is_error(self):
        side = self.good()
        side["observed"]["release_marker"] = "0.2.9"
        side["identity_sha256"] = self.ei.identity_of(side["models"]["files"], side["osdi"])
        self.select(side)
        self.assert_provenance_error("observed install release")

    def test_sidecar_pin_must_come_in_pairs(self):
        self.rec["env_sidecar"] = self.side_rel
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_mint_refuses_provenance_error(self):
        self.select("{not json")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(generate.mint(self.fx.root, self.fx.selection_path), 1)


class NegativeControls(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_fixture_reproduces_committed_verdict(self):
        content = self.fx.build()
        self.assertEqual(content["overall"]["verdict"], "FAIL")
        self.assertEqual(sorted(r["id"] for r in content["rows"] if r["verdict"] == "FAIL"), LITERAL_FAIL_IDS)

    def test_exactly_at_bound_passes(self):
        # Each of the four binding points set exactly to its bound (both >=
        # and <= ops, and the absmax offset row): equality meets the bound.
        self.fx.heal_precision_rows()
        content = self.fx.build()
        rows = rows_by_id(content)
        for rid in LITERAL_FAIL_IDS:
            self.assertEqual(rows[rid]["verdict"], "PASS", rid)
            self.assertEqual(Decimal(rows[rid]["measured_worst"]["raw_margin"]), 0, rid)
        self.assertEqual(content["overall"]["verdict"], "PASS")
        self.assertEqual(content["overall"]["fail_only_beyond_written_decimals"], [])

    def test_edge_of_bound_values_fail_even_if_they_round_onto_the_bound(self):
        # Values a hair past the bound -- including ones that round onto it at
        # the bound's written decimals -- must FAIL, from an all-PASS baseline.
        cases = [
            ("phase_margin", "open-loop-ac", "mos_tt_27C_1.20V", "pm_deg", "59.9"),     # >= 60
            ("phase_margin", "open-loop-ac", "mos_tt_27C_1.20V", "pm_deg", "59.5"),     # rounds to 60
            ("phase_margin", "open-loop-ac", "mos_tt_27C_1.20V", "pm_deg", "59.9999"),
            ("dc_gain", "open-loop-ac", "mos_tt_27C_1.20V", "av0_db", "37.79"),         # >= 37.8
            ("dc_gain", "open-loop-ac", "mos_tt_27C_1.20V", "av0_db", "37.75"),         # rounds to 37.8
            ("gbw", "open-loop-ac", "mos_tt_27C_1.20V", "gbw_hz", "4739999"),           # >= 4.74 MHz
            ("input_noise", "input-noise", "mos_tt_27C_1.20V", "vni_int_vrms", "0.00010890001"),  # <= 108.9 µVrms
            ("offset_systematic", "input-offset", "mos_tt_27C_1.20V", "vos_null_v", "-0.02190001"),  # |x| <= 21.9 mV
            ("swing_span", "output-swing", "mos_tt_27C_1.20V", "swing_span_v", "0.5709999"),  # >= 0.571 V
        ]
        for rid, key, pid, column, value in cases:
            with self.subTest(row=rid, value=value):
                fx = Fixture()
                try:
                    fx.heal_precision_rows()
                    self.assertEqual(rows_by_id(fx.build())[rid]["verdict"], "PASS")
                    fx.set_measurement(key, pid, column, value)
                    content = fx.build()
                    row = rows_by_id(content)[rid]
                    self.assertEqual(row["verdict"], "FAIL")
                    self.assertTrue(row["coverage"]["complete"])
                    self.assertEqual(row["violating_points"], [pid])
                    self.assertEqual(content["overall"]["verdict"], "FAIL")
                    if key == "open-loop-ac":
                        # Editing the corrected open-loop record (here: the
                        # dc_gain bound) leaves the mismatch sample audit
                        # attached and verified: the CMRR Av0 join reads
                        # `open-loop-ac-floating-inn`, not this record.
                        samples = content["sources"]["cmrr-mismatch"]["samples"]
                        self.assertEqual(samples["status"], "verified")
                        self.assertEqual((samples["files"], samples["draws"]), (45, 45 * 300))
                finally:
                    fx.close()

    def test_removed_corner_is_incomplete_not_pass(self):
        # Drop every mos_ss point from the open-loop record: the remaining
        # points all still meet their bounds, so only completeness can catch it.
        self.fx.heal_precision_rows()
        self.fx.rewrite_csv("open-loop-ac", lambda ls: [l for l in ls if not l.startswith("mos_ss_")])
        content = self.fx.build()
        row = rows_by_id(content)["dc_gain"]
        self.assertEqual(row["verdict"], "INCOMPLETE")
        self.assertTrue(row["meets_bound"])
        self.assertEqual(len(row["coverage"]["missing"]), 9)
        self.assertFalse(row["coverage"]["complete"])
        self.assertEqual(content["overall"]["verdict"], "INCOMPLETE")

    def test_injected_failing_point_is_fail_while_complete(self):
        self.fx.heal_precision_rows()
        self.assertEqual(self.fx.build()["overall"]["verdict"], "PASS")
        self.fx.set_cell("open-loop-ac", "mos_tt_27C_1.20V", "pm_deg", "55.0")
        content = self.fx.build()
        row = rows_by_id(content)["phase_margin"]
        self.assertEqual(row["verdict"], "FAIL")
        self.assertTrue(row["coverage"]["complete"])
        self.assertEqual(row["violating_points"], ["mos_tt_27C_1.20V"])
        self.assertEqual(row["measured_worst"]["point"], "mos_tt_27C_1.20V")
        self.assertEqual(content["overall"]["verdict"], "FAIL")

    def test_failed_simulation_point_cannot_pass(self):
        # A point the bench itself flagged as failed: its (good-looking)
        # value must not count, and the row must say so.
        self.fx.set_cell("slew-rate", "mos_ss_-40C_1.08V", "drive_pass", "0")
        row = rows_by_id(self.fx.build())["slew_rate"]
        self.assertEqual(row["verdict"], "INCOMPLETE")
        self.assertIn("mos_ss_-40C_1.08V", row["coverage"]["invalid"])
        self.assertNotEqual(row["measured_worst"]["point"], "mos_ss_-40C_1.08V")

    def test_failing_point_in_incomplete_grid_still_fails(self):
        self.fx.rewrite_csv("cmrr-psrr", lambda ls: [l for l in ls if not l.startswith("mos_ff_125C")])
        self.fx.set_cell("cmrr-psrr", "mos_tt_27C_1.20V", "psrr_db", "1.0")
        row = rows_by_id(self.fx.build())["psrr"]
        self.assertEqual(row["verdict"], "FAIL")
        self.assertFalse(row["coverage"]["complete"])

    def test_superseded_row_failure_does_not_fail_report(self):
        self.fx.heal_precision_rows()
        self.fx.set_cell("cmrr-psrr", "mos_tt_27C_1.20V", "cmrr_db", "10.0")
        content = self.fx.build()
        self.assertEqual(rows_by_id(content)["cmrr_systematic"]["verdict"], "FAIL")
        self.assertEqual(content["overall"]["verdict"], "PASS")

    def test_duplicate_point_id_is_error(self):
        def dup(lines):
            return lines + [next(l for l in lines if l.startswith("mos_tt_27C_1.20V,"))]

        self.fx.rewrite_csv("input-noise", dup)
        content = self.fx.build()
        row = rows_by_id(content)["input_noise"]
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("duplicate point_id" in e for e in row["errors"]))
        self.assertEqual(content["overall"]["verdict"], "ERROR")

    def test_non_finite_measurement_is_error(self):
        for bad in ("nan", "inf", "-Infinity", "", "garbage"):
            with self.subTest(value=bad):
                fx = Fixture()
                try:
                    fx.set_cell("output-swing", "mos_tt_27C_1.20V", "swing_span_v", bad)
                    row = rows_by_id(fx.build())["swing_span"]
                    self.assertEqual(row["verdict"], "ERROR")
                    self.assertTrue(any("mos_tt_27C_1.20V" in e for e in row["errors"]))
                finally:
                    fx.close()

    def test_missing_record_is_error(self):
        self.fx.csv_path("input-cmr").unlink()
        content = self.fx.build()
        self.assertEqual(rows_by_id(content)["icmr_span"]["verdict"], "ERROR")
        self.assertEqual(content["overall"]["verdict"], "ERROR")

    def test_unpinned_change_to_selected_record_is_error(self):
        self.fx.set_cell("open-loop-ac", "mos_tt_27C_1.20V", "av0_db", "50.0", repin=False)
        row = rows_by_id(self.fx.build())["dc_gain"]
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("selection pin" in e for e in row["errors"]))

    def test_point_outside_grid_is_error(self):
        def extra(lines):
            src = next(l for l in lines if l.startswith("mos_tt_27C_1.20V,"))
            return lines + [src.replace("mos_tt_27C_1.20V", "mos_tt_85C_1.20V", 1)]

        self.fx.rewrite_csv("slew-rate", extra)
        self.assertEqual(rows_by_id(self.fx.build())["slew_rate"]["verdict"], "ERROR")

    def test_point_id_disagreeing_with_its_columns_is_error(self):
        self.fx.set_cell("input-offset", "mos_tt_27C_1.20V", "temp_c", "125")
        self.assertEqual(rows_by_id(self.fx.build())["offset_systematic"]["verdict"], "ERROR")

    def test_mixed_ngspice_environment_is_error(self):
        rec = self.fx.selection["records"]["input-noise"]
        md = self.fx.root / rec["md"]
        md.write_text(md.read_text(encoding="utf-8").replace("ngspice-46", "ngspice-44"), encoding="utf-8")
        rec["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()
        row = rows_by_id(self.fx.build())["input_noise"]
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("mixed simulation environments" in e for e in row["errors"]))

    def test_different_circuit_is_error(self):
        snap = self.fx.root / self.fx.selection["records"]["cmrr-psrr"]["netlist_snapshot"]
        snap.write_text(snap.read_text(encoding="utf-8").replace("w=", "w=2*", 1), encoding="utf-8")
        row = rows_by_id(self.fx.build())["psrr"]
        self.assertEqual(row["verdict"], "ERROR")

    def test_mc_supply_axis_point_missing_is_incomplete(self):
        # Removed from summary AND draws together (a consistent re-selection):
        # what remains is missing grid coverage, i.e. INCOMPLETE, not an
        # error. (A summary-only removal is a summary/draws contradiction --
        # the error control lives in OffsetMcStatistics.)
        pid = "mos_fs_mismatch_125C_1.20V"
        self.fx.rewrite_csv("input-offset-mc", lambda ls: [l for l in ls if not l.startswith(pid)])
        self.fx.rewrite_draws("input-offset-mc", lambda ls: [l for l in ls if not l.startswith(pid)])
        rows = rows_by_id(self.fx.build())
        self.assertEqual(rows["offset_mc_3sigma"]["verdict"], "INCOMPLETE")
        self.assertIn(pid, rows["offset_mc_total"]["coverage"]["missing"])

    def test_mc_negative_control_missing_is_incomplete(self):
        self.fx.rewrite_csv("input-offset-mc", lambda ls: [l for l in ls if "negctrl" not in l])
        self.fx.rewrite_draws("input-offset-mc", lambda ls: [l for l in ls if "negctrl" not in l])
        self.assertEqual(rows_by_id(self.fx.build())["offset_mc_3sigma"]["verdict"], "INCOMPLETE")

    def test_mc_short_draw_count_is_incomplete(self):
        # One draw honestly re-classified as FAIL, and the summary repinned to
        # say so: the point fails its own validity flags (n_pass < n_draws),
        # which is INCOMPLETE coverage -- never a silent reduction.
        self.fx.set_draw_cell("input-offset-mc", "mos_ss_mismatch_27C_1.20V", 7, "status", "FAIL")
        self.fx.set_draw_cell("input-offset-mc", "mos_ss_mismatch_27C_1.20V", 7, "fail_reason", "reclassified")
        self.fx.set_cell("input-offset-mc", "mos_ss_mismatch_27C_1.20V", "n_pass", "299")
        row = rows_by_id(self.fx.build())["offset_mc_3sigma"]
        self.assertEqual(row["verdict"], "INCOMPLETE")
        self.assertIn("mos_ss_mismatch_27C_1.20V", row["coverage"]["invalid"])

    def test_cmrr_db_domain_aggregate_is_rejected(self):
        # Replace one point's ratified statistic with a dB-domain figure (the
        # mean of the per-draw dB values): the linear-domain definition check
        # must refuse it rather than aggregate it.
        lines = self.fx.csv_path("cmrr-mismatch").read_text(encoding="utf-8").splitlines()
        header = lines[0].split(",")
        cells = next(l for l in lines if l.startswith("mos_tt_27C_1.20V,")).split(",")
        db_mean = cells[header.index("cmrr_db_mean")]
        self.fx.set_cell("cmrr-mismatch", "mos_tt_27C_1.20V", "cmrr_3sigma_db", db_mean)
        row = rows_by_id(self.fx.build())["cmrr_mismatch"]
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("cmrr_linear_3sigma" in e for e in row["errors"]))

    def test_bound_must_match_ratified_spec(self):
        row = next(r for r in self.fx.selection["rows"] if r["id"] == "gbw")
        row["bound"]["value"] = "4.5"
        self.fx.save_selection()
        self.assertEqual(rows_by_id(self.fx.build())["gbw"]["verdict"], "ERROR")

    def _verdict_after(self, rid, **changes):
        row = next(r for r in self.fx.selection["rows"] if r["id"] == rid)
        for key, val in changes.items():
            (row["bound"] if key in ("op", "value") else row)[key] = val
        self.fx.save_selection()
        return rows_by_id(self.fx.build())[rid]

    def test_bound_substring_of_ratified_number_is_error(self):
        row = self._verdict_after("gbw", value="4.7")  # substring of 4.74
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("whole numeric token" in e for e in row["errors"]))

    def test_flipped_operator_is_error(self):
        row = self._verdict_after("gbw", op="<=")
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("operator" in e for e in row["errors"]))

    def test_conflicting_unit_is_error(self):
        row = self._verdict_after("gbw", unit="kHz")
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("unit" in e for e in row["errors"]))

    def test_ambiguous_or_unsupported_clause_is_error(self):
        self.assertIsNotNone(generate.parse_bound_clause("no bound here")[1])
        self.assertIsNotNone(generate.parse_bound_clause("\u2265 1 V and \u2264 2 V")[1])
        self.assertIsNotNone(generate.parse_bound_clause("\u2265 5 furlongs")[1])

    def test_valid_clauses_parse_to_selection_bounds(self):
        for r in self.fx.selection["rows"]:
            if r.get("bound"):
                text = r["spec_check"]["text"]
                parsed, problem = generate.parse_bound_clause(text)
                self.assertIsNone(problem, r["id"])
                self.assertEqual(parsed[:2], (r["bound"]["op"], r["bound"]["value"]), r["id"])

    def test_spec_text_drift_is_error(self):
        spec = self.fx.root / self.fx.selection["spec"]
        spec.write_text(spec.read_text(encoding="utf-8").replace("≥ 4.74 MHz", "≥ 4.50 MHz"), encoding="utf-8")
        self.assertEqual(rows_by_id(self.fx.build())["gbw"]["verdict"], "ERROR")

    def test_inventory_must_name_the_selected_record(self):
        inv = self.fx.root / self.fx.selection["inventory"]
        inv.write_text(
            inv.read_text(encoding="utf-8").replace(
                "sim/slew-rate/records/20260918-210216-90844d2.csv", "sim/slew-rate/records/20990101-000000-0000000.csv"
            ),
            encoding="utf-8",
        )
        self.assertEqual(rows_by_id(self.fx.build())["slew_rate"]["verdict"], "ERROR")

    def test_dropping_a_ratified_row_from_selection_is_error(self):
        self.fx.selection["rows"] = [r for r in self.fx.selection["rows"] if r["id"] != "quiescent_current"]
        self.fx.save_selection()
        content = self.fx.build()
        self.assertEqual(content["overall"]["verdict"], "ERROR")
        self.assertTrue(any("Quiescent power" in e for e in content["errors"]))

    def test_mint_of_failing_report_wraps_a_fail_envelope(self):
        # The committed evidence (four literal FAILs) must never mint a pass.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(generate.mint(self.fx.root, self.fx.selection_path), 0)
            self.assertEqual(generate.check(self.fx.root, self.fx.selection_path, None), 0)
        envelope = json.loads((self.fx.root / generate.ENVELOPE_REL).read_text(encoding="utf-8"))
        self.assertEqual(envelope["status"], "fail")
        self.assertIn("overall FAIL", envelope["summary"])

    def test_mint_is_append_only_and_check_detects_drift(self):
        self.fx.heal_precision_rows()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(generate.mint(self.fx.root, self.fx.selection_path), 0)
            self.assertEqual(generate.check(self.fx.root, self.fx.selection_path, None), 0)
        report = generate.latest_report(self.fx.root / generate.REPORTS_REL)
        envelope = json.loads((self.fx.root / generate.ENVELOPE_REL).read_text(encoding="utf-8"))
        self.assertEqual(envelope["t1_item"], 8)
        self.assertEqual(envelope["status"], "pass")
        self.assertEqual(envelope["provenance"]["input"]["content_hash"], generate.sha256_file(report))
        # evidence drift after minting -> the committed report no longer reproduces
        self.fx.set_cell("open-loop-ac", "mos_tt_27C_1.20V", "pm_deg", "55.0")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(generate.check(self.fx.root, self.fx.selection_path, report), 1)

    def test_mint_never_overwrites_a_record(self):
        class FrozenClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        clock = types.SimpleNamespace(datetime=FrozenClock, timezone=timezone)
        with mock.patch.object(generate, "_dt", clock), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(generate.mint(self.fx.root, self.fx.selection_path), 0)
            report = generate.latest_report(self.fx.root / generate.REPORTS_REL)
            self.assertTrue(report.name.startswith("20300102-030405-"))
            before = report.read_bytes()
            # same UTC second, same HEAD -> same record id -> refuse
            self.assertEqual(generate.mint(self.fx.root, self.fx.selection_path), 1)
        self.assertEqual(report.read_bytes(), before)
        self.assertEqual(len(list((self.fx.root / generate.REPORTS_REL).glob("*.json"))), 1)

    def test_mint_refuses_error_state(self):
        self.fx.csv_path("input-cmr").unlink()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(generate.mint(self.fx.root, self.fx.selection_path), 1)
        self.assertIsNone(generate.latest_report(self.fx.root / generate.REPORTS_REL))


class MintPublication(unittest.TestCase):
    """Issue #205: concurrent and part-way failing mints can never replace,
    truncate or half-publish evidence. Every control forces one record id
    (frozen clock, fixed HEAD) and synchronizes its writers explicitly --
    never by probabilistic timing."""

    HEAD = "205dead"

    def setUp(self) -> None:
        self.fx = Fixture()

    def tearDown(self) -> None:
        self.fx.close()

    def forced_id(self, clock: datetime) -> str:
        return f"{clock.strftime('%Y%m%d-%H%M%S')}-{self.HEAD}"

    def pinned(self, clock: datetime, fn):
        """Run fn with the clock and HEAD pinned, so every mint inside
        computes exactly the record id `forced_id(clock)` returns."""
        class FrozenClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock

        with mock.patch.object(generate, "_dt", types.SimpleNamespace(datetime=FrozenClock, timezone=timezone)), \
                mock.patch.object(generate, "git_head", lambda repo: self.HEAD), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return fn()

    def mint_pinned(self, clock: datetime) -> int:
        return self.pinned(clock, lambda: generate.mint(self.fx.root, self.fx.selection_path))

    def test_same_id_concurrent_mints_serialize_and_one_refuses(self):
        clock = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        record_id = self.forced_id(clock)
        reports = self.fx.root / generate.REPORTS_REL
        barrier = threading.Barrier(2)
        results = []

        def run():
            barrier.wait()  # both writers are live before either publishes
            results.append(generate.mint(self.fx.root, self.fx.selection_path))

        def orchestrate():
            threads = [threading.Thread(target=run) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.pinned(clock, orchestrate)
        self.assertEqual(sorted(results), [0, 1])
        # exactly one complete record, at the forced id
        self.assertEqual(sorted(p.name for p in reports.glob("*.json")), [f"{record_id}.json"])
        self.assertEqual(sorted(p.name for p in reports.glob("*.md")), [f"{record_id}.md"])
        committed = json.loads((reports / f"{record_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(committed["record_metadata"]["record_id"], record_id)
        self.assertEqual((reports / f"{record_id}.md").read_text(encoding="utf-8"), generate.render_markdown(committed))
        # the envelope wraps exactly the record that survived, at its hash
        envelope = json.loads((self.fx.root / generate.ENVELOPE_REL).read_text(encoding="utf-8"))
        self.assertEqual(envelope["provenance"]["input"]["path"]["path"], f"{generate.REPORTS_REL}/{record_id}.json")
        self.assertEqual(envelope["provenance"]["input"]["content_hash"], generate.sha256_file(reports / f"{record_id}.json"))
        # the lock is released, no staging file survived, the record reproduces
        self.assertFalse((reports / generate.MINT_LOCK_NAME).exists())
        self.assertEqual(list(reports.glob(".*.part")), [])
        self.assertEqual(generate.check(self.fx.root, self.fx.selection_path, None), 0)

    def test_existing_json_only_or_md_only_twin_is_preserved_and_refused(self):
        clock = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        record_id = self.forced_id(clock)
        reports = self.fx.root / generate.REPORTS_REL
        reports.mkdir(parents=True, exist_ok=True)
        json_path = reports / f"{record_id}.json"
        md_path = reports / f"{record_id}.md"
        # a JSON-only destination at the forced id is kept verbatim, refused
        json_path.write_bytes(b"earlier evidence, keep byte-for-byte\n")
        self.assertEqual(self.mint_pinned(clock), 1)
        self.assertEqual(json_path.read_bytes(), b"earlier evidence, keep byte-for-byte\n")
        self.assertFalse(md_path.exists())
        self.assertFalse((self.fx.root / generate.ENVELOPE_REL).exists())
        # the same for a Markdown-only destination
        json_path.unlink()
        md_path.write_bytes(b"earlier rendering, keep byte-for-byte\n")
        self.assertEqual(self.mint_pinned(clock), 1)
        self.assertEqual(md_path.read_bytes(), b"earlier rendering, keep byte-for-byte\n")
        self.assertFalse(json_path.exists())
        self.assertFalse((self.fx.root / generate.ENVELOPE_REL).exists())

    def test_failure_before_complete_publication_keeps_store_and_envelope_intact(self):
        first = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        self.assertEqual(self.mint_pinned(first), 0)
        reports = self.fx.root / generate.REPORTS_REL
        first_json = reports / f"{self.forced_id(first)}.json"
        first_md = reports / f"{self.forced_id(first)}.md"
        envelope_path = self.fx.root / generate.ENVELOPE_REL
        json_before, md_before, envelope_before = first_json.read_bytes(), first_md.read_bytes(), envelope_path.read_bytes()

        second = datetime(2030, 1, 2, 3, 4, 6, tzinfo=timezone.utc)
        record_id = self.forced_id(second)
        real_link = generate._link_no_clobber

        def failing_link(tmp, dest):
            if dest.suffix == ".md":
                tmp.unlink(missing_ok=True)  # the real helper always removes its staging file
                raise OSError("injected publication failure")
            return real_link(tmp, dest)

        with mock.patch.object(generate, "_link_no_clobber", failing_link):
            self.assertEqual(self.mint_pinned(second), 1)
        # the half-published record is rolled back; earlier files and the
        # envelope are untouched, byte-for-byte
        self.assertFalse((reports / f"{record_id}.json").exists())
        self.assertFalse((reports / f"{record_id}.md").exists())
        self.assertEqual(first_json.read_bytes(), json_before)
        self.assertEqual(first_md.read_bytes(), md_before)
        self.assertEqual(envelope_path.read_bytes(), envelope_before)
        self.assertEqual(list(reports.glob(".*.part")), [])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(generate.check(self.fx.root, self.fx.selection_path, None), 0)

    def test_envelope_is_swapped_atomically_never_truncated(self):
        clock = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        envelope_path = self.fx.root / generate.ENVELOPE_REL
        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        envelope_path.write_bytes(b'{"stale": "envelope a reader may be reading"}\n')
        seen = []
        real_replace = generate._replace_text_atomically

        def spy(dest, text):
            seen.append(dest.name)
            real_replace(dest, text)

        with mock.patch.object(generate, "_replace_text_atomically", spy):
            self.assertEqual(self.mint_pinned(clock), 0)
        # the envelope was published by an atomic replace, never a truncating write
        self.assertEqual(seen, [envelope_path.name])
        self.assertEqual(list(envelope_path.parent.glob(f".{envelope_path.name}.*.part")), [])
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        self.assertEqual(envelope["t1_item"], 8)

    def test_mint_refuses_while_the_store_lock_is_held_and_recovers_after(self):
        clock = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        record_id = self.forced_id(clock)
        reports = self.fx.root / generate.REPORTS_REL
        reports.mkdir(parents=True, exist_ok=True)
        lock = reports / generate.MINT_LOCK_NAME
        lock.write_bytes(b"99999\n")
        self.assertEqual(self.mint_pinned(clock), 1)
        self.assertIsNone(generate.latest_report(reports))
        self.assertFalse((self.fx.root / generate.ENVELOPE_REL).exists())
        # a lock left behind by a killed mint is recoverable: sweep its stale
        # staging file, remove the lock, and the next mint publishes cleanly
        stale = reports / f".{record_id}.json.XXXXXX.part"
        stale.write_bytes(b'{"half": ')
        lock.unlink()
        self.assertEqual(self.mint_pinned(clock), 0)
        self.assertFalse(stale.exists())
        self.assertFalse(lock.exists())
        self.assertEqual(generate.check(self.fx.root, self.fx.selection_path, None), 0)


class RawAuditCase(unittest.TestCase):
    """Shared harness for the six raw-audit suites (offset MC statistics,
    CMRR MC statistics, noise, KLT, slew, swing): the `Fixture` lifecycle
    (`setUp`/`tearDown`/`fresh`, keeping this suite's population audit
    attached via `KEEP_AUDIT`), the error assertion (`errors` collects
    report-level and row-level diagnostics; `assert_error` builds the
    report, requires the overall ERROR verdict, checks each requested text
    fragment and returns the diagnostics for further assertions), and the
    pinned-raw helpers (`raw`/`entry` selection lookups, `cell` CSV lookup,
    `_edit_pinned_lines`/`edit_raw` read-transform-write-repin,
    `definition_error`)."""

    KEEP_AUDIT: str | None = None
    RAW_KEY: str = ""
    DEFINITION_CHECK: str = ""

    def setUp(self) -> None:
        self.fx = Fixture()
        if self.KEEP_AUDIT:
            setattr(self.fx, self.KEEP_AUDIT, True)

    def tearDown(self) -> None:
        self.fx.close()

    def fresh(self) -> None:
        self.fx.close()
        self.fx = Fixture()
        if self.KEEP_AUDIT:
            setattr(self.fx, self.KEEP_AUDIT, True)

    def errors(self, content: dict) -> list:
        out = list(content["errors"])
        for row in content["rows"]:
            out.extend(row["errors"])
        return out

    def assert_error(self, *fragments: str) -> list:
        content = self.fx.build()
        errors = self.errors(content)
        self.assertEqual(content["overall"]["verdict"], "ERROR", errors)
        for fragment in fragments:
            self.assertTrue(any(fragment in e for e in errors), (fragment, errors))
        return errors

    def definition_error(self) -> list:
        return self.assert_error(f"point {self.POINT} fails definition check {self.DEFINITION_CHECK}")

    def raw(self) -> dict:
        return self.fx.selection["records"][self.RECORD][self.RAW_KEY]

    def entry(self, kind, pid=None) -> dict:
        return self.raw()["files"][pid or self.POINT][kind]

    def cell(self, column, pid=None) -> str:
        return next(r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]
                    if r["point_id"] == (pid or self.POINT))[column]

    def edit_json(self, kind, mutate, repin=True) -> None:
        pin = self.raw()["files"][kind]
        path = self.fx.root / pin["path"]
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")
        if repin:
            pin["sha256"] = generate.sha256_file(path)
            self.fx.save_selection()

    def add_klt_dut_copy(self, kind):
        def add_copy(doc):
            closure = doc["environment"]["netlist_closure"]
            dut = next(entry for entry in closure if entry["path"] == "design/netlist/opamp_core.spice")
            closure.append(dict(dut, path="copy/opamp_core.spice"))

        self.edit_json(kind, add_copy)

    def assert_malformed_klt_closure_rejected(self, kind):
        self.edit_json(kind, lambda doc: doc["environment"]["netlist_closure"].append(None))
        content = self.fx.build()
        self.assertEqual(content["sources"][self.RECORD][self.RAW_KEY]["status"], "error")
        errors = self.errors(content)
        self.assertTrue(any("malformed netlist_closure entry" in e for e in errors), errors)

    def assert_klt_optional_object(self, kind, path, invalid_string):
        *parents, field = path.split(".")

        def parent(doc):
            for key in parents:
                doc = doc.setdefault(key, {})
            return doc

        for value in (invalid_string, [], None):
            with self.subTest(kind=kind, path=path, value=value):
                self.edit_json(kind, lambda doc, value=value: parent(doc).update({field: value}))
                content = self.fx.build()
                audit = content["sources"][self.RECORD][self.RAW_KEY]
                if value is None:
                    self.assertEqual(audit["status"], "verified")
                else:
                    self.assertEqual(audit["status"], "error")
                    errors = self.errors(content)
                    self.assertTrue(any(f"{path} must be an object" in e for e in errors), errors)

        with self.subTest(kind=kind, missing=path):
            self.edit_json(kind, lambda doc: parent(doc).pop(field))
            self.assertEqual(self.fx.build()["sources"][self.RECORD][self.RAW_KEY]["status"], "verified")

    def assert_klt_worker_simulator_validation(self, kind):
        self.assert_klt_optional_object(kind, "environment.remote.worker_environment.simulator", "ngspice-460")
        self.assert_klt_optional_object(kind, "environment.remote.worker_environment", "legacy-worker")

    def _edit_pinned_lines(self, entry, transform, repin=True) -> None:
        path = self.fx.root / entry["path"]
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")
        if repin:
            entry["sha256"] = generate.sha256_file(path)
            self.fx.save_selection()

    def edit_raw(self, kind, transform, pid=None, repin=True) -> None:
        self._edit_pinned_lines(self.entry(kind, pid), transform, repin)


class PointRawPinControlMixin:
    """The seven generic per-point raw-pin negative controls shared by the
    three two-level `*_raw` families (`noise_raw`, `slew_raw`, `swing_raw`),
    whose production pin shape, grid/ownership rules, and hash/existence checks
    all live in `selection._validate_raw_pins`, `records._check_raw_pins`,
    `records._read_pinned_raw`, and `selection.load_selection` (issue #256).

    Mixed into `RawAuditCase` subclasses that set `RAW_NOUN` (`"noise"`,
    `"slew"`, `"swing"`) and `MISSING_PHRASE` (`"log/spectrum"`,
    `"waveform/netlist"`, `"curves/netlists"`). Per-kind controls restore the
    mutated bytes or pin in `finally` so every artifact kind in the family is
    exercised without extra `Fixture` copies.
    """

    RAW_NOUN: str = ""
    MISSING_PHRASE: str = ""

    def _pin_kinds(self) -> tuple:
        kinds = tuple(self.raw()["files"][self.POINT])
        self.assertTrue(kinds)
        return kinds

    def test_changed_raw_pin_without_repin_fails(self):
        for kind in self._pin_kinds():
            with self.subTest(kind=kind):
                rel = self.entry(kind)["path"]
                path = self.fx.root / rel
                orig = path.read_bytes()
                try:
                    path.write_bytes(orig + b"\n")
                    self.assert_error(f"point {self.POINT}: {rel} does not match its selection pin")
                finally:
                    path.write_bytes(orig)

    def test_missing_raw_file_fails(self):
        for kind in self._pin_kinds():
            with self.subTest(kind=kind):
                rel = self.entry(kind)["path"]
                path = self.fx.root / rel
                orig = path.read_bytes()
                try:
                    path.unlink()
                    self.assert_error(f"point {self.POINT}: missing raw {self.RAW_NOUN} {kind} {rel}")
                finally:
                    path.write_bytes(orig)

    def test_missing_point_association_fails(self):
        del self.raw()["files"][self.POINT]
        self.fx.save_selection()
        self.assert_error(f"point {self.POINT}: no pinned raw {self.RAW_NOUN} {self.MISSING_PHRASE}")

    def test_pin_outside_the_grid_fails(self):
        self.raw()["files"]["mos_tt_99C_1.20V"] = self.raw()["files"][self.POINT]
        self.fx.save_selection()
        self.assert_error(f"raw {self.RAW_NOUN} artifacts pinned for 'mos_tt_99C_1.20V', which is outside the expected grid")

    def test_duplicate_assignment_fails(self):
        other = "mos_tt_27C_1.32V"
        self.raw()["files"][other] = json.loads(json.dumps(self.raw()["files"][self.POINT]))
        self.fx.save_selection()
        errors = self.assert_error("is pinned twice", "belongs to another point")
        self.assertTrue(any(other in e for e in errors), errors)

    def test_unpinned_artifact_entry_is_rejected(self):
        for kind in self._pin_kinds():
            with self.subTest(kind=kind):
                pin = self.entry(kind)
                sha = pin.pop("sha256")
                try:
                    self.fx.save_selection()
                    with self.assertRaisesRegex(generate.SelectionError, rf"\.{kind} needs string `path` and `sha256`"):
                        self.fx.build()
                finally:
                    pin["sha256"] = sha
                    self.fx.save_selection()

    def test_audit_without_pins_is_rejected(self):
        del self.fx.selection["records"][self.RECORD][self.RAW_KEY]
        self.fx.save_selection()
        with self.assertRaisesRegex(generate.SelectionError, self.RAW_KEY):
            self.fx.build()


class OffsetMcStatistics(RawAuditCase):
    """Issue #199: the draws audit rejects fabricated statistics and broken
    draw populations, naming the point and offending field. The committed
    campaign is the positive control (CommittedEvidence); every control here
    perturbs exactly one thing against the otherwise-consistent fixture."""

    RECORD = "input-offset-mc"
    POINT = "mos_ss_mismatch_27C_1.20V"  # any ordinary mismatch point
    NEGCTRL = "mos_tt_negctrl_27C_1.20V"

    def test_baseline_has_no_audit_errors(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        self.assertEqual(content["sources"][self.RECORD]["draws"]["status"], "verified")

    def test_altered_summary_statistic_is_rejected_field_by_field(self):
        # A fresh, correctly repinned summary whose finite sigma, three-sigma,
        # mean, extrema or total no longer follows from the pinned draws is an
        # error naming the point and the offending field -- never a publishable
        # MEASURED row.
        for column, fabricated in (
            ("mean_vos_v", "0.015373984"),
            ("sigma_vos_v", "0.008956746"),
            ("three_sigma_v", "0.02687024"),
            ("min_vos_v", "-0.007416798"),
            ("max_vos_v", "0.040074417"),
            ("vos_total_wc_det_plus_3sigma_v", "0.042223313"),
        ):
            with self.subTest(field=column):
                self.fresh()
                self.fx.set_cell(self.RECORD, self.POINT, column, fabricated)
                self.assert_error(f"point {self.POINT} fails definition check offset_mc_statistics: {column}")

    def test_negative_spread_magnitude_is_rejected(self):
        for column in ("sigma_vos_v", "three_sigma_v", "vos_total_wc_det_plus_3sigma_v"):
            with self.subTest(field=column):
                self.fresh()
                self.fx.set_cell(self.RECORD, self.POINT, column, "-0.026870239")
                self.assert_error(f"{column} -0.026870239 is negative")

    def test_drifted_draws_file_is_error_even_unrepinned(self):
        self.fx.set_draw_cell(self.RECORD, self.POINT, 5, "vos_v", "0.0099999999", repin=False)
        self.assert_error("does not match its selection pin")

    def test_missing_draws_file_is_error(self):
        self.fx.draws_path(self.RECORD).unlink()
        self.assert_error("missing draws population")

    def test_duplicate_draw_is_error(self):
        def duplicate_one(lines):
            target = next(l for l in lines if l.startswith(f"{self.POINT},") and l.split(",")[6] == "5")
            return lines + [target]

        self.fx.rewrite_draws(self.RECORD, duplicate_one)
        self.assert_error("duplicate draw_index 5")

    def test_missing_draw_is_error_not_a_quiet_population_reduction(self):
        def drop_one(lines):
            return [l for l in lines if not (l.startswith(f"{self.POINT},") and l.split(",")[6] == "5")]

        self.fx.rewrite_draws(self.RECORD, drop_one)
        self.assert_error("1 of 300 expected draws missing")

    def test_non_finite_pass_draw_is_error(self):
        self.fx.set_draw_cell(self.RECORD, self.POINT, 5, "vos_v", "nan")
        self.assert_error("is not finite")

    def test_draw_seed_conflicting_with_the_campaign_is_error(self):
        self.fx.set_draw_cell(self.RECORD, self.POINT, 5, "draw_seed", "99999999")
        self.assert_error("draw_seed 99999999")

    def test_negctrl_is_audited_on_its_own_population_only(self):
        # A perturbed negctrl draw breaks exactly the negctrl point's own
        # statistics: mismatch points are never pooled with it (and vice
        # versa -- the field-by-field control above perturbs a mismatch
        # point and leaves this one alone).
        self.fx.set_draw_cell(self.RECORD, self.NEGCTRL, 5, "vos_v", "0.0160000000")
        errors = self.assert_error(f"point {self.NEGCTRL} fails definition check offset_mc_statistics")
        self.assertFalse(any(self.POINT in e for e in errors), errors)

    def test_draws_file_may_not_be_named_without_its_hash_pin(self):
        del self.fx.selection["records"][self.RECORD]["draws_csv_sha256"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_statistics_check_requires_a_draws_population(self):
        del self.fx.selection["records"][self.RECORD]["draws_csv"]
        del self.fx.selection["records"][self.RECORD]["draws_csv_sha256"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()


class CmrrMcStatistics(RawAuditCase):
    """Issue #208: the CMRR summary is audited against hash-pinned raw sample
    files, not merely against its own mean/sigma/CMRR identity."""

    RECORD = "cmrr-mismatch"
    POINT = "mos_tt_27C_1.20V"

    def entry(self, pid=None) -> dict:
        return self.fx.selection["records"][self.RECORD]["mc_samples"]["files"][pid or self.POINT]

    def edit_samples(self, transform, pid=None, repin=True) -> None:
        self._edit_pinned_lines(self.entry(pid), transform, repin)

    def test_committed_campaign_reproduces_from_pinned_samples(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        samples = content["sources"][self.RECORD]["samples"]
        self.assertEqual(samples["status"], "verified")
        self.assertEqual(samples["files"], 45)
        self.assertEqual(samples["draws"], 45 * 300)

    def test_coherent_summary_mutation_passes_the_old_identity_but_fails_the_audit(self):
        # mean, sigma and CMRR changed together keep Av0 - 20log10(mean+3s)
        # true, so the summary-only definition check is satisfied.
        rows = {r["point_id"]: r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]}
        row = dict(rows[self.POINT])
        mean, sigma, av0 = float(row["acm_lin_mean"]), float(row["acm_lin_sigma"]), float(row["av0_db"])
        new_mean = mean * 1.05
        new_cmrr = av0 - 20 * __import__("math").log10(new_mean + 3 * sigma)
        self.fx.set_cell(self.RECORD, self.POINT, "acm_lin_mean", f"{new_mean:.6g}")
        self.fx.set_cell(self.RECORD, self.POINT, "cmrr_3sigma_db", f"{new_cmrr:.6g}")
        row.update(acm_lin_mean=f"{new_mean:.6g}", cmrr_3sigma_db=f"{new_cmrr:.6g}")
        self.assertIsNone(generate._check_cmrr_linear(row, None))
        self.assert_error(f"point {self.POINT} fails definition check cmrr_mc_statistics", "acm_lin_mean")

    def test_each_serialized_statistic_is_checked_at_six_digits(self):
        rows = {r["point_id"]: r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]}
        for field in ("acm_lin_sigma", "acm_plus_3sigma_db", "cmrr_db_mean", "cmrr_db_p01",
                      "cmrr_db_min", "cmrr_1khz_3sigma_db", "plateau_max_db"):
            with self.subTest(field=field):
                self.fresh()
                old = Decimal(rows[self.POINT][field])
                bumped = old + Decimal("0.0001") if old != 0 else Decimal("0.001")
                self.fx.set_cell(self.RECORD, self.POINT, field, str(bumped))
                errors = self.assert_error()
                self.assertTrue(any(field in e and self.POINT in e for e in errors), errors)

    def test_equal_value_in_another_notation_is_accepted(self):
        old = generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]
        cell = next(r for r in old if r["point_id"] == self.POINT)["acm_lin_sigma"]
        alt = str((Decimal(cell) * 1000).normalize()) + "e-3"
        self.fx.set_cell(self.RECORD, self.POINT, "acm_lin_sigma", alt)
        self.assertEqual(self.errors(self.fx.build()), [])

    def test_wrong_sample_count_is_rejected(self):
        # drop draw 299 entirely (both records): a coherent 299-draw file, but
        # the summary still says 300 draws.
        self.edit_samples(lambda ls: [l for l in ls if not l.split()[:2] in (["OP", "299"], ["AC", "299"])])
        self.assert_error(self.POINT, "mc_n '300' != 299")

    def test_missing_ac_of_a_pair_is_rejected(self):
        self.edit_samples(lambda ls: [l for l in ls if l.split()[:2] != ["AC", "17"]])
        self.assert_error(self.POINT, "draw 17: missing AC record")

    def test_duplicated_op_is_rejected(self):
        def dup(ls):
            first = next(l for l in ls if l.startswith("OP 5 "))
            return ls + [first]
        self.edit_samples(dup)
        self.assert_error(self.POINT, "duplicate OP record for draw 5")

    def test_non_finite_sample_token_is_rejected(self):
        def poison(ls):
            out = []
            for l in ls:
                p = l.split()
                if p[:2] == ["AC", "3"]:
                    p[2] = "nan"
                    l = " ".join(p)
                out.append(l)
            return out
        self.edit_samples(poison)
        self.assert_error(self.POINT, "non-finite")

    def test_stale_population_pin_is_rejected(self):
        self.edit_samples(lambda ls: ls + [""], repin=False)  # bytes change, pin does not
        self.assert_error(self.POINT, "does not match its selection pin")

    def test_edited_sample_value_with_summary_untouched_fails_even_repinned(self):
        def tweak(ls):
            out = []
            for l in ls:
                p = l.split()
                if p[:2] == ["AC", "10"]:
                    p[2] = "30.0"
                    l = " ".join(p)
                out.append(l)
            return out
        self.edit_samples(tweak)
        self.assert_error(self.POINT)

    def test_missing_sample_file_is_rejected(self):
        (self.fx.root / self.entry()["path"]).unlink()
        self.assert_error(self.POINT, "missing sample file")

    def test_unpinned_grid_point_is_rejected(self):
        del self.fx.selection["records"][self.RECORD]["mc_samples"]["files"][self.POINT]
        self.fx.save_selection()
        self.assert_error(self.POINT, "no pinned sample file")

    def test_incorrect_av0_in_summary_is_rejected(self):
        self.fx.set_cell(self.RECORD, self.POINT, "av0_db", "41.5")
        self.assert_error(self.POINT, "av0_db")

    def test_join_record_changed_is_rejected(self):
        # Alter the joined deterministic Av0 AND re-pin it: the summary's own
        # Av0 no longer matches the explicitly selected join.
        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "av0_db", "41.5")
        self.assert_error(self.POINT, "av0_db")

    def test_join_keeps_the_provenance_the_summary_was_measured_against(self):
        # The CMRR summary states the Av0 of the superseded inn-floating
        # record; selecting the corrected open-loop record as the primary
        # open-loop source must not silently re-stamp it (issue #101).
        join = self.fx.selection["records"][self.RECORD]["mc_samples"]["av0_join"]
        self.assertEqual(join, "open-loop-ac-floating-inn")
        self.assertNotEqual(
            self.fx.selection["records"][join]["csv"], self.fx.selection["records"]["open-loop-ac"]["csv"]
        )
        self.assertEqual(self.fx.build()["errors"], [])
        # Repointing the join at the corrected record is caught: its Av0 is
        # not the one the pinned samples' summary carries.
        self.fx.selection["records"][self.RECORD]["mc_samples"]["av0_join"] = "open-loop-ac"
        self.fx.save_selection()
        self.assert_error(self.POINT, "av0_db")

    def test_join_record_must_be_a_selected_record(self):
        self.fx.selection["records"][self.RECORD]["mc_samples"]["av0_join"] = "nope"
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_sample_file_may_not_be_named_without_its_pin(self):
        del self.entry()["sha256"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_statistics_check_requires_pinned_samples(self):
        del self.fx.selection["records"][self.RECORD]["mc_samples"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()


class CmrrPointStats(unittest.TestCase):
    """The shared pure helper: acceptance rules and the linear-domain bound."""

    VDD, VCM = 1.2, 0.6

    @staticmethod
    def op(vout=0.6, vd1=0.5, vd2=0.5, vtail=0.3):
        return [vout, vd1, vd2, vtail, 0.5, 1e-4]

    def build(self, draws):
        ops = {k: d[0] for k, d in enumerate(draws)}
        acs = {k: d[1] for k, d in enumerate(draws)}
        return mc_samples.point_stats(len(draws), ops, acs, 40.0, self.VDD, self.VCM, 0.02, 0.15, 0.05)

    def test_accepts_excludes_and_counts_by_the_bench_rules(self):
        good = (self.op(), [-10.0, -10.0, -10.0])
        draws = [good, good, (self.op(), [-12.0, -12.0, -12.0]),
                 (self.op(vout=0.9), [-10.0, -10.0, -10.0]),     # |vout-vcm| > 0.15*vdd
                 (self.op(vtail=0.01), [-10.0, -10.0, -10.0]),   # inside rail margin
                 (self.op(), [-10.0, -10.2, -10.0])]             # plateau 0.2 dB > 0.05
        st = self.build(draws)
        self.assertEqual((st["mc_n"], st["mc_n_ok"], st["mc_n_excluded"]), (6, 3, 3))
        self.assertEqual((st["op_fail"], st["plateau_fail"]), (2, 1))
        self.assertAlmostEqual(st["plateau_max_db"], 0.2)

    def test_bound_is_linear_domain_sample_sigma(self):
        import math
        a = [-10.0, -12.0, -14.0]
        draws = [(self.op(), [x, x, x]) for x in a]
        lin = [10 ** (x / 20) for x in a]
        mu = sum(lin) / 3
        sd = math.sqrt(sum((v - mu) ** 2 for v in lin) / 2)
        st = self.build(draws)
        self.assertAlmostEqual(st["acm_lin_mean"], mu)
        self.assertAlmostEqual(st["acm_lin_sigma"], sd)
        self.assertAlmostEqual(st["cmrr_3sigma_db"], 40.0 - 20 * math.log10(mu + 3 * sd))
        self.assertAlmostEqual(st["cmrr_db_min"], 40.0 - (-10.0))

    def test_fewer_than_two_accepted_draws_is_an_error(self):
        with self.assertRaises(mc_samples.SampleError):
            self.build([(self.op(), [-10.0] * 3), (self.op(vout=0.9), [-10.0] * 3)])


class LoadCondition(unittest.TestCase):
    """The reported CL is validated, not copied (issue #194)."""

    def setUp(self) -> None:
        self.fx = Fixture()

    def tearDown(self) -> None:
        self.fx.close()

    def row(self, rid: str) -> dict:
        return next(r for r in self.fx.selection["rows"] if r["id"] == rid)

    def build_row(self, rid: str) -> dict:
        self.fx.save_selection()
        return rows_by_id(self.fx.build())[rid]

    def test_committed_ac_rows_are_verified_against_source(self):
        row = self.build_row("gbw")
        self.assertEqual(row["load_check"]["status"], "verified")
        self.assertIn("2e-12 F", row["load"])
        self.assertEqual(row["verdict"], "PASS")

    def test_wrong_label_is_error_not_a_verified_claim(self):
        self.row("gbw")["load_condition"]["cl"] = "200 pF"
        row = self.build_row("gbw")
        self.assertEqual(row["verdict"], "ERROR")
        self.assertEqual(row["load_check"]["status"], "contradicted")
        self.assertTrue(any("ratified" in e for e in row["errors"]))
        self.assertTrue(any("selected record" in e for e in row["errors"]))
        self.assertNotIn("verified:", row["load"])

    def test_contradiction_is_diagnosed_independent_of_electrical_pass_fail(self):
        # the load error is named whatever the electrical verdict is.
        self.row("dc_gain")["load_condition"]["cl"] = "5 pF"
        row = self.build_row("dc_gain")
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("contradicts" in e for e in row["errors"]))

    def test_equivalent_units_compare_equal(self):
        for text in ("2e-12 F", "2000 fF", "0.002 nF", "2.0 pF"):
            self.row("gbw")["load_condition"]["cl"] = text
            row = self.build_row("gbw")
            self.assertEqual(row["load_check"]["status"], "verified", text)
            self.assertEqual(row["verdict"], "PASS", text)

    def test_bad_unit_is_error(self):
        self.row("gbw")["load_condition"]["cl"] = "2 henries"
        self.assertEqual(self.build_row("gbw")["verdict"], "ERROR")

    def test_missing_source_metadata_is_disclosed_unverified(self):
        self.fx.detach_klt_population()  # this control is about the prose load statement alone
        md = self.fx.root / self.fx.selection["records"]["open-loop-ac"]["md"]
        md.write_text(md.read_text(encoding="utf-8").replace("CL = 2e-12 F", "load stated elsewhere"), encoding="utf-8")
        self.fx.selection["records"]["open-loop-ac"]["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()
        row = self.build_row("gbw")
        self.assertEqual(row["load_check"]["status"], "unverified")
        self.assertIn("UNVERIFIED", row["load"])
        self.assertEqual(row["verdict"], "PASS")

    def test_source_contradicting_ratified_load_is_error(self):
        self.fx.detach_klt_population()
        md = self.fx.root / self.fx.selection["records"]["open-loop-ac"]["md"]
        md.write_text(md.read_text(encoding="utf-8").replace("CL = 2e-12 F", "CL = 2e-10 F"), encoding="utf-8")
        self.fx.selection["records"]["open-loop-ac"]["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()
        row = self.build_row("gbw")
        self.assertEqual(row["verdict"], "ERROR")
        self.assertTrue(any("selected record" in e for e in row["errors"]))

    def test_dc_rows_claim_no_load(self):
        row = self.build_row("offset_systematic")
        self.assertEqual(row["load_check"]["status"], "not_applicable")
        self.assertIn("DC analysis", row["load"])
        self.assertNotIn("verified", row["load"])

    def test_dc_applicability_is_not_a_way_around_a_contradicting_source(self):
        row_sel = self.row("quiescent_current")
        row_sel["load_condition"]["applicability"] = "applies"
        row_sel["load_condition"]["cl"] = "9 pF"
        self.assertEqual(self.build_row("quiescent_current")["verdict"], "ERROR")

    def test_unknown_applicability_and_free_text_load_rejected(self):
        self.row("gbw")["load_condition"]["applicability"] = "whatever"
        self.assertEqual(self.build_row("gbw")["verdict"], "ERROR")
        self.row("gbw")["load_condition"]["applicability"] = "applies"
        self.row("gbw")["load"] = "CL = 200 pF"
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_conditions_prose_is_labelled_descriptive(self):
        self.assertIn("descriptive", self.build_row("gbw")["conditions_provenance"])


class NoiseRawAudit(PointRawPinControlMixin, RawAuditCase):
    """Issue #213: the input-noise summary is audited against hash-pinned raw
    logs and in-band spectra; the logged integrated figure and the
    spectrum-derived quantities are checked independently."""

    RECORD = "input-noise"
    POINT = "mos_tt_27C_1.20V"
    KEEP_AUDIT = "keep_noise_audit"
    RAW_KEY = "noise_raw"
    RAW_NOUN = "noise"
    MISSING_PHRASE = "log/spectrum"
    DEFINITION_CHECK = "noise_raw_audit"

    def only_problem(self, tag: str, other: str) -> list:
        """The point fails the audit on `tag` and NOT on `other`."""
        errors = self.definition_error()
        self.assertTrue(any(f"[{tag}]" in e for e in errors), errors)
        self.assertFalse(any(f"[{other}]" in e for e in errors), errors)
        return errors

    # --- committed evidence -------------------------------------------------

    def test_committed_population_audits_offline(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        raw = content["sources"][self.RECORD]["noise_raw"]
        self.assertEqual(raw["status"], "verified")
        self.assertEqual(raw["points"], 45)
        self.assertTrue(raw["pins_sha256"].startswith("sha256:"))
        self.assertIn("noise_raw_audit", content["sources"][self.RECORD]["definition_checks"])

    def test_report_exposes_audit_status_and_rule(self):
        content = self.fx.build()
        self.assertIn("Input-noise raw-evidence audit", content["noise_audit_rule"])
        self.assertIn("pinned log+spectrum pairs", generate.render_markdown(generate.make_report(content, "20260101-000000-abcd", self.fx.root)))

    def test_shared_module_reproduces_every_committed_cell(self):
        import noise_post
        for row in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]:
            pid = row["point_id"]
            log = (self.fx.root / self.entry("log", pid)["path"]).read_text(encoding="utf-8")
            spec = (self.fx.root / self.entry("spectrum", pid)["path"]).read_text(encoding="utf-8")
            token, value = noise_post.parse_log_total(log)
            freqs, dens = noise_post.parse_spectrum(spec)
            self.assertEqual(token, row["vni_int_vrms"], pid)
            got = [noise_post.serialize(x) for x in noise_post.derive(freqs, dens, value)]
            self.assertEqual(got, [row[f] for f in noise_post.SPECTRUM_FIELDS], pid)

    # --- integrated-log vs spectrum-derived, independently -------------------

    def test_integrated_disagreement_with_refreshed_hash_fails_only_the_log_check(self):
        self.fx.set_cell(self.RECORD, self.POINT, "vni_int_vrms", "7.5E-05")  # repinned csv
        self.only_problem("integrated-log", "spectrum")

    def test_spectrum_derived_disagreement_with_refreshed_hash_fails_only_the_spectrum_check(self):
        for field in ("vni_1khz_v_rthz", "flicker_coeff_v2", "thermal_floor_v_rthz",
                      "flicker_corner_hz", "flicker_frac_of_msq", "vni_int_crosscheck_ratio"):
            with self.subTest(field=field):
                self.fresh()
                self.fx.set_cell(self.RECORD, self.POINT, field, "1.5")
                errors = self.only_problem("spectrum", "integrated-log")
                self.assertTrue(any(field in e and self.POINT in e for e in errors), errors)

    def test_changed_log_value_fails_the_log_check_not_the_spectrum_derivation(self):
        # the raw log is re-pinned (deliberate re-selection) but disagrees with
        # the summary; the spot/fit cells still follow from the spectrum.
        tok = self.cell("vni_int_vrms")
        self.edit_raw("log", lambda ls: [l.replace(tok, "9.99999E-05") if l.startswith("NOISE_INOISE_TOTAL") else l for l in ls])
        errors = self.assert_error(f"point {self.POINT} fails definition check noise_raw_audit")
        self.assertTrue(any("[integrated-log]" in e for e in errors), errors)
        # the cross-check ratio is derived from the LOGGED total, so it moves
        # with the log -- the only spectrum-tagged complaint
        spectrum_fields = {e.split("[spectrum] ")[1].split(" ")[0] for e in errors if "[spectrum]" in e}
        self.assertEqual(spectrum_fields, {"vni_int_crosscheck_ratio"})

    def test_changed_spectrum_sample_fails_only_spectrum_derived_cells(self):
        def bump(ls):
            parts = ls[30].split()
            parts[1] = "%.8e" % (float(parts[1]) * 1.01)
            return ls[:30] + ["  " + "  ".join(parts) + " "] + ls[31:]
        self.edit_raw("spectrum", bump)
        self.only_problem("spectrum", "integrated-log")

    # --- serialization boundaries ------------------------------------------

    def test_integrated_cell_is_exact_at_the_verbatim_token(self):
        tok = Decimal(self.cell("vni_int_vrms"))
        self.fx.set_cell(self.RECORD, self.POINT, "vni_int_vrms", format(tok, "f") + "0000")  # same value, longer
        self.assertEqual(self.errors(self.fx.build()), [])
        self.fx.set_cell(self.RECORD, self.POINT, "vni_int_vrms", format(tok + Decimal("1E-10"), "f"))  # 6th sig digit +1
        self.assert_error("[integrated-log]")

    def test_spectrum_cells_accept_the_serialization_and_reject_one_ulp_of_it(self):
        old = Decimal(self.cell("vni_1khz_v_rthz"))
        step = Decimal(1).scaleb(old.adjusted() - 5)  # one unit in the 6th significant digit
        self.fx.set_cell(self.RECORD, self.POINT, "vni_1khz_v_rthz", format(old, "f") + "000")
        self.assertEqual(self.errors(self.fx.build()), [])
        self.fx.set_cell(self.RECORD, self.POINT, "vni_1khz_v_rthz", format(old + step, "f"))
        self.assert_error("[spectrum] vni_1khz_v_rthz", self.POINT)
        self.fx.set_cell(self.RECORD, self.POINT, "vni_1khz_v_rthz", format(old - step, "f"))
        self.assert_error("[spectrum] vni_1khz_v_rthz")

    def test_summary_cannot_be_blank_or_non_numeric(self):
        for column, tag in (("vni_int_vrms", "integrated-log"), ("flicker_frac_of_msq", "spectrum")):
            with self.subTest(column=column):
                self.fx.set_cell(self.RECORD, self.POINT, column, "abc")
                self.assert_error(f"[{tag}]")

    def test_undefined_quantity_must_serialize_as_nan(self):
        import noise_post
        cell = lambda c, v, **kw: generate._cell_problem("x", c, noise_post.serialize(v), "pinned spectrum", 6, **kw)
        self.assertIsNone(cell("nan", float("nan")))
        self.assertIsNotNone(cell("1.0", float("nan")))
        self.assertIsNotNone(cell("nan", 1.0))
        self.assertIsNotNone(cell("nan", float("nan"), nan_ok=False))
        self.assertEqual(noise_post.serialize(float("nan")), "nan")
        self.assertEqual(noise_post.serialize(0.1 + 0.2), "0.3")

    # --- raw artifact problems (all point-specific) -------------------------

    def test_duplicate_json_key_is_a_selection_error(self):
        text = self.fx.selection_path.read_text(encoding="utf-8")
        needle = f'"{self.POINT}": {{"log"'
        broken = text.replace(needle, f'"{self.POINT}": {{}}, ' + needle, 1) if needle in text else None
        if broken is None:  # indent=2 layout: duplicate the key by hand
            idx = text.index(f'"{self.POINT}": {{\n')
            broken = text[:idx] + f'"{self.POINT}": {{}},\n' + text[idx:]
        self.fx.selection_path.write_text(broken, encoding="utf-8")
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_duplicate_log_total_line_fails(self):
        self.edit_raw("log", lambda ls: ls + ["NOISE_INOISE_TOTAL 1.0E-04"])
        self.assert_error(f"point {self.POINT}: invalid noise log", "2 NOISE_INOISE_TOTAL lines")

    def test_missing_log_total_line_fails(self):
        self.edit_raw("log", lambda ls: [l for l in ls if not l.startswith("NOISE_INOISE_TOTAL")])
        self.assert_error(f"point {self.POINT}: invalid noise log", "no NOISE_INOISE_TOTAL line")

    def test_non_finite_log_total_fails(self):
        for bad in ("nan", "inf", "1e999", "-1.0E-05", "0"):
            with self.subTest(bad=bad):
                self.fresh()
                self.edit_raw("log", lambda ls, bad=bad: [("NOISE_INOISE_TOTAL " + bad) if l.startswith("NOISE_INOISE_TOTAL") else l for l in ls])
                self.assert_error(f"point {self.POINT}: invalid noise log")

    def test_non_finite_spectrum_sample_fails(self):
        for bad in ("nan", "inf", "1e999", "-1e-6", "0"):
            with self.subTest(bad=bad):
                self.fresh()
                def poison(ls, bad=bad):
                    parts = ls[10].split()
                    parts[1] = bad
                    return ls[:10] + [" ".join(parts)] + ls[11:]
                self.edit_raw("spectrum", poison)
                self.assert_error(f"point {self.POINT}: invalid noise spectrum")

    def test_truncated_spectrum_fails(self):
        self.edit_raw("spectrum", lambda ls: ls[:-1])
        self.assert_error(f"point {self.POINT}: invalid noise spectrum", "expected 81 swept points, got 80")

    def test_malformed_row_fails(self):
        self.edit_raw("spectrum", lambda ls: ls[:5] + [" ".join(ls[5].split()[:3])] + ls[6:])
        self.assert_error(f"point {self.POINT}: invalid noise spectrum", "expected 4")

    def test_unordered_frequency_grid_fails(self):
        self.edit_raw("spectrum", lambda ls: ls[:7] + [ls[8], ls[7]] + ls[9:])
        self.assert_error(f"point {self.POINT}: invalid noise spectrum", "not strictly increasing")

    def test_wrong_band_grid_fails(self):
        def stretch(ls):
            out = []
            for l in ls:
                p = l.split()
                p[0] = p[2] = "%.8e" % (float(p[0]) * 1.5)
                out.append(" ".join(p))
            return out
        self.edit_raw("spectrum", stretch)
        self.assert_error(f"point {self.POINT}: invalid noise spectrum", "grid point 0 is")

    def test_band_must_match_the_documented_band(self):
        self.fx.selection["records"][self.RECORD]["noise_raw"]["band"]["points"] = 41
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_runner_uses_the_shared_module(self):
        runner = (REPO / "sim" / "input-noise" / "run_noise_sweep.sh").read_text(encoding="utf-8")
        self.assertIn("noise_post.py", runner)
        self.assertNotIn("PYEOF", runner.split("noise_post.py")[1].split("done")[0])


class KltRawAudit(RawAuditCase):
    """Issue #101: the corrected open-loop record carries no `op_pass` /
    `gm_status` columns, so its four graded rows are audited against the
    hash-pinned `klt sim` envelopes (definition check open_loop_klt_audit).
    Missing legacy columns are never permission to weaken validation."""

    RECORD = "open-loop-ac"
    POINT = "mos_tt_27C_1.20V"
    KEEP_AUDIT = "keep_klt_audit"
    RAW_KEY = "klt_raw"

    def edit_text(self, kind, transform, repin=True) -> None:
        pin = self.raw()["files"][kind]
        path = self.fx.root / pin["path"]
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
        if repin:
            pin["sha256"] = generate.sha256_file(path)
            self.fx.save_selection()

    def corner(self, doc, pid=None):
        pid = pid or self.POINT
        for c in doc["corners"]:
            if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" == pid:
                return c
        raise KeyError(pid)

    def set_value(self, doc, name, value, pid=None):
        for m in self.corner(doc, pid)["measurements"]:
            if m["name"] == name:
                m["value"] = value

    # --- committed evidence -------------------------------------------------

    def test_committed_evidence_verifies_all_45_points(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        src = content["sources"][self.RECORD]
        self.assertEqual((src["klt_raw"]["status"], src["klt_raw"]["points"]), ("verified", 45))
        self.assertEqual(src["klt_raw"]["jobs"], {"ac": "klt-sim-2e841aaa76e0", "op": "klt-sim-15dd509f5239"})
        self.assertEqual((src["valid_points"], src["ngspice"]), (45, "ngspice-46"))
        self.assertEqual(src["pdk_provenance"]["status"], "legacy-unverified")

    def test_corrected_rows_are_graded_from_the_new_record(self):
        rows = rows_by_id(self.fx.build())
        self.assertEqual(rows["dc_gain"]["source"]["record"], self.RECORD)
        for rid, point, value in (
            ("dc_gain", "mos_fs_125C_1.08V", "38.2293"),
            ("gbw", "mos_ss_-40C_1.08V", "8.06239"),
            ("phase_margin", "mos_ff_125C_1.32V", "61.9872"),
            ("quiescent_current", "mos_ss_-40C_1.32V", "119.655"),
        ):
            row = rows[rid]
            self.assertEqual((row["verdict"], row["measured_worst"]["point"], row["measured_worst"]["value"]),
                             ("PASS", point, value), rid)

    def test_report_exposes_audit_rule_and_status(self):
        content = self.fx.build()
        self.assertIn("Open-loop `klt sim` raw-evidence audit", content["klt_audit_rule"])
        self.assertTrue(any("internal-node" in c for c in content["caveats"]))
        md = generate.render_markdown(generate.make_report(content, "20260101-000000-abcd", self.fx.root))
        self.assertIn("pinned klt-sim corners", md)

    def test_summary_cells_follow_the_envelopes(self):
        for column, value in (("av0_db", "41.0"), ("gbw_hz", "1.0e7"), ("pm_deg", "70.0"), ("iq_a", "0.0001")):
            with self.subTest(column=column):
                self.fresh()
                self.fx.set_cell(self.RECORD, self.POINT, column, value)
                self.assert_error(f"point {self.POINT} fails definition check open_loop_klt_audit", column)

    # --- selection shape ----------------------------------------------------

    def test_klt_raw_without_its_audit_is_refused(self):
        self.fx.selection["records"][self.RECORD]["definition_checks"] = []
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_audit_without_pinned_raw_evidence_is_refused(self):
        del self.fx.selection["records"][self.RECORD]["klt_raw"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_every_artifact_must_be_pinned(self):
        for kind in generate.KLT_RAW_REQUIRED_KINDS:
            with self.subTest(missing=kind):
                self.fresh()
                del self.raw()["files"][kind]
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()
        for kind in generate.KLT_RAW_KINDS:
            with self.subTest(unpinned=kind):
                self.fresh()
                del self.raw()["files"][kind]["sha256"]
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()

    def test_continuity_record_must_be_another_selected_record(self):
        for name in ("nope", self.RECORD):
            with self.subTest(name=name):
                self.raw()["dc_continuity"] = name
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()

    # --- tampering ----------------------------------------------------------

    def test_stale_pin_is_rejected_for_every_artifact(self):
        for kind in generate.KLT_RAW_KINDS:
            with self.subTest(kind=kind):
                self.fresh()
                path = self.fx.root / self.raw()["files"][kind]["path"]
                path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                self.assert_error("does not match its selection pin")

    def test_missing_artifact_is_rejected(self):
        (self.fx.root / self.raw()["files"]["op"]["path"]).unlink()
        self.assert_error("missing raw klt artifact op")

    def test_coherent_envelope_edit_still_fails_against_the_summary(self):
        self.edit_json("ac", lambda d: self.set_value(d, "av0_db", 41.0))
        errors = self.assert_error(f"point {self.POINT} fails definition check open_loop_klt_audit")
        self.assertTrue(any("av0_db" in e for e in errors), errors)

    def test_measurement_document_must_agree_with_the_envelopes(self):
        def tweak(doc):
            for c in doc["corners"]:
                if c["corner_id"] == "mos_tt/1.20V/27C":
                    for m in c["measurements"]:
                        if m["name"] == "pm_deg":
                            m["value"] += 0.5
        self.edit_json("measurement", tweak)
        self.assert_error("the measurement document gives")

    def test_failed_envelope_is_not_evidence(self):
        self.edit_json("op", lambda d: d.update(status="fail", failed=1, passed=44))
        self.assert_error("op envelope", "klt raw evidence")

    def test_missing_corner_is_rejected(self):
        self.edit_json("ac", lambda d: d.update(corners=[c for c in d["corners"] if c is not self.corner(d)]))
        self.assert_error("no corner for point " + self.POINT)

    def test_corner_diagnostics_are_rejected(self):
        self.edit_json("ac", lambda d: self.corner(d).update(diagnostics=[{"code": "nonconvergence"}]))
        self.assert_error("is not a decided corner")

    def test_non_finite_raw_value_is_rejected(self):
        self.edit_json("ac", lambda d: self.set_value(d, "gbw_hz", None))
        self.assert_error("missing or non-finite raw value")

    def test_engine_disagreement_is_rejected(self):
        self.edit_json("op", lambda d: d["environment"].update(engine_version="45"))
        self.assert_error("disagree on the engine")

    def test_ngspice_must_satisfy_the_pdk_policy(self):
        def set_ver(ver):
            def mut(d):
                d["environment"]["engine_version"] = str(ver)
                d["environment"]["remote"]["worker_environment"]["simulator"]["version_banner"] = f"ngspice-{ver}"
            return mut

        self.edit_json("ac", set_ver(45))
        self.edit_json("op", set_ver(45))
        self.assert_error("ngspice-45", "floor ngspice-46")

        for ok in (46, 47):
            with self.subTest(ok=ok):
                self.fresh()
                self.edit_json("ac", set_ver(ok))
                self.edit_json("op", set_ver(ok))
                content = self.fx.build()
                self.assertEqual(self.errors(content), [])
                self.assertEqual(content["sources"][self.RECORD]["ngspice"], f"ngspice-{ok}")
                md = generate.render_markdown(generate.make_report(content, None, self.fx.root))
                self.assertIn(f"| {self.RECORD} |", md)
                self.assertIn(f"| ngspice-{ok} |", md)

        # Fallback when ngspice_min_major is absent: exact match against ngspice_actually_used.
        self.fresh()
        pdk_path = self.fx.root / self.fx.selection["pdk_pin"]
        pdk = json.loads(pdk_path.read_text(encoding="utf-8"))
        del pdk["osdi_toolchain"]["ngspice_min_major"]
        pdk_path.write_text(json.dumps(pdk), encoding="utf-8")
        # The committed cmrr-psrr batch record ran ngspice-47 (issue #514), which the
        # exact-pin fallback rightly refuses; this control is about the open-loop record.
        self.assertEqual([e for e in self.errors(self.fx.build()) if not e.startswith("record cmrr-psrr:")], [])
        self.edit_json("ac", set_ver(47))
        self.edit_json("op", set_ver(47))
        self.assert_error("ngspice-47", "expected 'ngspice-46'")

    def test_wrong_model_deck_is_rejected(self):
        self.edit_json("ac", lambda d: d["environment"].update(models_lib_sha256="0" * 64))
        self.assert_error("model deck")

    def test_malformed_closure_entry_is_rejected(self):
        for kind in ("ac", "op"):
            with self.subTest(kind=kind):
                self.fresh()
                self.assert_malformed_klt_closure_rejected(kind)

    def test_engine_build_is_an_optional_object(self):
        for kind in ("ac", "op"):
            self.assert_klt_optional_object(kind, "environment.engine_build", "legacy-build")

    def test_worker_simulator_metadata_is_optional(self):
        for kind in ("ac", "op"):
            self.assert_klt_worker_simulator_validation(kind)

    def test_simulated_dut_must_be_the_selected_snapshot(self):
        snap = self.fx.root / self.fx.selection["records"][self.RECORD]["netlist_snapshot"]
        snap.write_text(snap.read_text(encoding="utf-8") + "* touched\n", encoding="utf-8")
        self.assert_error("is not the selected netlist snapshot")

    # --- the bench itself ---------------------------------------------------

    def test_inn_must_be_ac_grounded(self):
        self.edit_text("bench_body", lambda t: t.replace("Cinn_acgnd inn vss 1", "* removed"))
        errors = self.assert_error("element Cinn_acgnd")
        self.assertTrue(any("simulated bench body is not the pinned" in e for e in errors), errors)

    def test_load_must_be_one_the_record_states(self):
        self.edit_text("bench_body", lambda t: t.replace("Cload out vss 2e-12", "Cload out vss 5e-12"))
        self.assert_error("is not a CL the record's own prose states")

    def test_second_load_is_rejected(self):
        self.edit_text("bench_body", lambda t: t + "Cload out vss 2e-12\n")
        self.assert_error("2 Cload elements")

    def test_reference_current_is_checked(self):
        self.edit_text("bench_body", lambda t: t.replace("Iibias vdd ibias dc 10u", "Iibias vdd ibias dc 20u"))
        self.assert_error("element Iibias")

    def test_ac_request_must_read_av0_at_one_hertz(self):
        self.edit_json("ac_request", lambda d: d["analysis"].update(args="dec 20 10 1g"))
        self.assert_error("Av0 is read at 1 Hz")

    def test_op_measurement_definition_is_checked(self):
        def tweak(d):
            for m in d["measurements"]:
                if m["name"] == "ivdd_total_a":
                    m["expr"] = "-i(vdd) - 1e-5"
        self.edit_json("op_request", tweak)
        self.assert_error("op request: measurement ivdd_total_a")

    # --- operating-point validity (replaces op_pass) ------------------------

    def test_railed_output_is_rejected(self):
        def rail(d):
            self.set_value(d, "vout_dc_v", 0.01)
            self.set_value(d, "op_vout_rail_frac", 0.01 / 1.2)
            self.set_value(d, "op_vout_offset_frac", abs(0.01 - 0.6) / 1.2)
        self.edit_json("op", rail)
        errors = self.assert_error(f"point {self.POINT} fails definition check open_loop_klt_audit")
        self.assertTrue(any("operating point" in e for e in errors), errors)

    def test_misreported_fraction_is_rejected(self):
        self.edit_json("op", lambda d: self.set_value(d, "op_vcm_frac", 0.55))
        self.assert_error("op_vcm_frac")

    # --- the stated stand-in for the internal-node check --------------------

    def test_continuity_record_op_failure_is_carried(self):
        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "op_pass", "0")
        self.assert_error("dc_continuity record open-loop-ac-floating-inn", "op_pass")

    def test_continuity_requires_dc_agreement(self):
        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "vout_dc_v", "0.5")
        self.assert_error("differs from the dc_continuity record")


class CmrrPsrrKltAudit(RawAuditCase):
    """Issue #514: the cmrr-psrr record audited against the hash-pinned batch
    CMRR and PSRR direct-deck `klt sim` envelopes (definition check
    cmrr_psrr_klt_audit), with the harness record as the Acm0 regression
    control."""

    KEEP_AUDIT = "keep_cmrr_psrr_audit"
    RECORD = "cmrr-psrr"
    POINT = "mos_tt_27C_1.20V"
    RAW_KEY = "cmrr_psrr_klt"
    DEFINITION_CHECK = "cmrr_psrr_klt_audit"

    def edit_env(self, kind, mutate, repin=True) -> None:
        pin = self.raw()["files"][kind]
        path = self.fx.root / pin["path"]
        if kind.endswith("_body"):
            path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            doc = json.loads(path.read_text(encoding="utf-8"))
            mutate(doc)
            path.write_text(json.dumps(doc), encoding="utf-8")
        if repin:
            pin["sha256"] = generate.sha256_file(path)
            self.fx.save_selection()

    @staticmethod
    def corner(doc, pid):
        for c in doc["corners"]:
            if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" == pid:
                return c
        raise KeyError(pid)

    def meas(self, doc, name, pid=None):
        return next(m for m in self.corner(doc, pid or self.POINT)["measurements"] if m["name"] == name)

    def test_committed_selection_binds_the_batch_envelopes(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        src = content["sources"][self.RECORD]
        self.assertEqual((src["cmrr_psrr_klt"]["status"], src["cmrr_psrr_klt"]["points"]), ("verified", 45))
        self.assertEqual(src["cmrr_psrr_klt"]["control"], "cmrr-psrr-harness")
        self.assertEqual(len(src["cmrr_psrr_klt"]["jobs"]["cmrr"]), 5)
        self.assertEqual((src["valid_points"], src["ngspice"]), (45, "ngspice-47"))
        self.assertIn("CMRR/PSRR batch-envelope audit", content["cmrr_psrr_klt_audit_rule"])
        rows = rows_by_id(content)
        self.assertEqual(rows["psrr"]["verdict"], "PASS")
        self.assertNotIn("context", rows["psrr"])
        self.assertEqual(rows["cmrr_systematic"]["verdict"], "PASS")
        self.assertTrue(rows["psrr"]["load"].startswith("CL = 2 pF"), rows["psrr"]["load"])

    def test_cmrr_db_is_the_av0_minus_acm0_difference_in_db(self):
        doc = json.loads((REPO / self.raw()["files"]["cmrr_envelope"]["path"]).read_text(encoding="utf-8"))
        want = self.meas(doc, "av0_db")["value"] - self.meas(doc, "acm0_db")["value"]
        self.assertAlmostEqual(float(self.cell("cmrr_db")), want, places=6)
        self.assertAlmostEqual(float(self.cell("av0_db")) - float(self.cell("acm0_db")), want, places=6)

    def test_harness_record_stays_selected_as_the_control(self):
        self.assertIn("cmrr-psrr-harness", self.fx.selection["records"])
        self.assertEqual(self.raw()["control"], "cmrr-psrr-harness")

    def test_edited_summary_cell_is_an_error(self):
        self.fx.set_cell(self.RECORD, self.POINT, "psrr_db", "1.0")
        self.definition_error()

    def test_csv_common_mode_voltage_must_match_the_envelope(self):
        self.fx.set_cell(self.RECORD, self.POINT, "vcm_v", "0.12")
        self.assert_error(self.POINT, "vcm_v", "supply_v.vinp")

    def test_cmrr_summary_not_av0_minus_acm0_is_an_error(self):
        self.fx.set_cell(self.RECORD, self.POINT, "cmrr_db", str(float(self.cell("cmrr_db")) + 1))
        self.definition_error()

    def test_stale_dut_hash_is_an_error(self):
        def stale(doc):
            for c in doc["environment"]["netlist_closure"]:
                if c["path"].endswith("opamp_core.spice"):
                    c["sha256"] = "0" * 64

        self.edit_env("cmrr_envelope", stale)
        self.assert_error("cmrr-psrr klt evidence", "is not the selected netlist snapshot")

    def test_stale_dut_hash_in_one_deck_only_is_not_the_same_run_conditions(self):
        # the PSRR envelope keeps the right DUT; only the CMRR one is stale
        def stale(doc):
            for c in doc["environment"]["netlist_closure"]:
                if c["path"].endswith("opamp_core.spice"):
                    c["sha256"] = "1" * 64

        self.edit_env("cmrr_envelope", stale)
        errors = self.assert_error("not the selected netlist snapshot")
        self.assertTrue(any("not the same run conditions" in e for e in errors), errors)

    def test_envelope_not_matching_its_request_is_an_error(self):
        # the request's measurement definition no longer says what the envelope reports
        def swap(doc):
            for m in doc["measurements"]:
                if m["name"] == "acm0_db":
                    m["spice"] = ".meas ac acm0_db find vdb(outa) at=0.01"

        self.edit_env("cmrr_request", swap)
        self.assert_error("cmrr request: measurement acm0_db is")

    def test_relaxed_request_limit_is_an_error(self):
        def relax(doc):
            for m in doc["measurements"]:
                if m["name"] == "psrr_db":
                    m["limits"] = {"min": 0.0}

        self.edit_env("psrr_request", relax)
        self.assert_error("limits are", "a validity bound is never relaxed")

    def test_model_input_hashes_must_match_across_decks(self):
        # Keep each job consistent with its own envelope. Only the cross-deck join can fail.
        for deck in ("cmrr", "psrr"):
            for name in ("sg13g2_moslv_mod.lib", "psp103.osdi"):
                with self.subTest(deck=deck, name=name):
                    self.fresh()

                    def change_hash(doc):
                        env = doc["environment"]
                        manifests = [env["staged_model_inputs"], env["osdi_preload_runner_resolved"]]
                        for job in env["remote"]["fleet"]:
                            manifests.extend((job["runner_model_inputs"], job["worker_environment"]["model_inputs"],
                                              job["runner_osdi_preload"]))
                        for manifest in manifests:
                            for item in manifest:
                                if Path(item.get("entry") or item["name"]).name == name:
                                    item["sha256"] = "0" * 64
                                    if "source_sha256" in item:
                                        item["source_sha256"] = "1" * 64

                    self.edit_json(f"{deck}_envelope", change_hash)
                    self.assert_error("CMRR and PSRR", name)

    def test_request_must_match_the_recorded_execution(self):
        for deck in ("cmrr", "psrr"):
            body = f"tb_{deck}_direct.body.spice"
            for field, mutate in (
                ("models.lib", lambda r: r["models"].update(lib="libs.tech/ngspice/models/cornerMOShv.lib")),
                ("models.lib", lambda r: r["models"].update(lib="other/cornerMOSlv.lib")),
                ("models.pdk", lambda r: r["models"].update(pdk="other-pdk")),
                ("engine", lambda r: r.update(engine="xyce")),
                ("backend", lambda r: r.update(backend="local")),
                ("netlist_source", lambda r: r.update(netlist_source="extracted")),
                ("options.stage_model_inputs", lambda r: r["options"].update(stage_model_inputs=False)),
                ("options.osdi_preload", lambda r: r["options"]["osdi_preload"].pop()),
                ("netlist", lambda r: r.update(netlist=f"other/{body}")),
            ):
                with self.subTest(deck=deck, field=field):
                    self.fresh()
                    if field == "netlist":
                        bench = self.fx.root / self.raw()["files"][f"{deck}_body"]["path"]
                        other = bench.parent / "other" / bench.name
                        other.parent.mkdir()
                        shutil.copyfile(bench, other)
                    self.edit_json(f"{deck}_request", mutate)
                    self.assert_error(f"{deck} request", field)

    def test_request_axes_must_cover_the_envelope_grid(self):
        for deck in ("cmrr", "psrr"):
            for axis, mutate in (
                ("temperature_c", lambda c: c.update(temperature_c=[27])),
                ("process", lambda c: c["process"].pop()),
                ("supply_v", lambda c: c["supply_v"]["vinp"].reverse()),
            ):
                with self.subTest(deck=deck, axis=axis):
                    self.fresh()
                    self.edit_env(f"{deck}_request", lambda d: mutate(d["corners"]))
                    self.assert_error(f"{deck} request", axis)

    def test_request_and_reported_measurement_metadata_must_agree(self):
        for deck in ("cmrr", "psrr"):
            for side, field, value in (("request", "unit", "V"), ("envelope", "unit", "V"),
                                       ("envelope", "limits", {"max": 0.5})):
                name = f"{deck}_plateau_delta_db"

                def alter(doc):
                    m = next(m for m in doc["measurements"] if m["name"] == name)
                    m[field] = value

                with self.subTest(deck=deck, side=side, field=field):
                    self.fresh()
                    self.edit_env(f"{deck}_{side}", alter)
                    self.assert_error(name, field)

    def test_corner_measurement_unit_must_agree_with_request(self):
        self.edit_env("cmrr_envelope", lambda d: self.meas(d, "acm0_db").update(unit="V"))
        self.assert_error(self.POINT, "acm0_db", "unit")

    def test_envelope_cannot_add_a_supply_to_the_requested_grid(self):
        for deck in ("cmrr", "psrr"):
            with self.subTest(deck=deck):
                self.fresh()
                self.edit_env(f"{deck}_envelope",
                              lambda d: self.corner(d, self.POINT)["supply_v"].update(vss=0.12))
                self.assert_error("supply_v", "vss")

    def test_fractional_corner_coordinates_cannot_alias_a_selected_point(self):
        for deck in ("cmrr", "psrr"):
            for field in ("temperature_c", "vdd"):
                def alter(doc):
                    c = self.corner(doc, self.POINT)
                    if field == "temperature_c":
                        c[field] = 27.9
                    else:
                        c["supply_v"].update(vdd=1.204, vinp=0.602)

                with self.subTest(deck=deck, field=field):
                    self.fresh()
                    self.edit_env(f"{deck}_envelope", alter)
                    self.assert_error("outside the expected grid")

    def test_request_naming_another_bench_body_is_an_error(self):
        self.edit_env("cmrr_request", lambda d: d.__setitem__("netlist", "tb_psrr_direct.body.spice"))
        self.assert_error("is not the pinned bench body")

    def test_bench_body_not_the_simulated_one_is_an_error(self):
        self.edit_env("psrr_body", lambda t: t + "* edited after the run\n")
        self.assert_error("is not the pinned")

    def test_bench_load_not_stated_by_the_record_is_an_error(self):
        for load in ("5e-12", "2p"):
            with self.subTest(load=load):
                self.fresh()
                self.edit_env("cmrr_body", lambda t: t.replace("Cloada outa vss 2e-12", f"Cloada outa vss {load}"))
                self.assert_error("not one CL the record's own prose states")

    def test_pinned_envelope_edited_without_repin_is_refused(self):
        self.edit_env("psrr_envelope", lambda d: d.__setitem__("status", "fail"), repin=False)
        self.assert_error("does not match its selection pin")

    def test_missing_corner_is_an_error(self):
        self.edit_env("psrr_envelope", lambda d: d["corners"].pop(0))
        self.assert_error("no corner for point")

    def test_errored_corner_is_an_error(self):
        def err(doc):
            self.corner(doc, self.POINT)["status"] = "error"

        self.edit_env("cmrr_envelope", err)
        self.assert_error("is not a decided corner")

    def test_missing_measurement_is_an_error(self):
        def drop(doc):
            c = self.corner(doc, self.POINT)
            c["measurements"] = [m for m in c["measurements"] if m["name"] != "avs0_db"]

        self.edit_env("psrr_envelope", drop)
        self.assert_error("missing or non-finite measurement")

    def test_missing_plateau_guard_cell_is_an_error(self):
        def drop(doc):
            c = self.corner(doc, self.POINT)
            c["measurements"] = [m for m in c["measurements"] if m["name"] != "cmrr_plateau_delta_db"]

        self.edit_env("cmrr_envelope", drop)
        self.assert_error("missing or non-finite measurement")

    def test_plateau_guard_miss_is_an_error(self):
        self.edit_env("cmrr_envelope", lambda d: self.meas(d, "cmrr_plateau_delta_db").__setitem__("value", 0.2))
        errors = self.definition_error()
        self.assertTrue(any("not a flat DC shelf" in e for e in errors), errors)

    def test_av0_disagreeing_between_decks_is_an_error(self):
        self.edit_env("psrr_envelope", lambda d: self.meas(d, "av0_db").__setitem__("value", self.meas(d, "av0_db")["value"] + 0.5))
        errors = self.definition_error()
        self.assertTrue(any("differ by more than" in e for e in errors), errors)

    def test_acm0_off_the_harness_control_is_an_error(self):
        self.edit_env("cmrr_envelope", lambda d: self.meas(d, "acm0_db").__setitem__("value", self.meas(d, "acm0_db")["value"] + 0.5))
        errors = self.assert_error("disagrees with the harness regression control")
        self.assertTrue(any("regression control" in e for e in errors), errors)

    def test_control_record_edit_without_repin_is_refused(self):
        path = self.fx.root / self.fx.selection["records"]["cmrr-psrr-harness"]["csv"]
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assert_error("control record", "does not match its selection pin")

    def test_inconsistent_simulator_version_is_an_error(self):
        def ver(doc):
            doc["environment"]["engine_version"] = "46"

        self.edit_env("cmrr_envelope", ver)
        self.assert_error("not the same run conditions")

    def test_build_and_worker_banners_must_match_the_exact_ngspice_major(self):
        for deck in ("cmrr", "psrr"):
            for source in ("engine_build", "worker"):
                with self.subTest(deck=deck, source=source):
                    self.fresh()

                    def change_banner(doc):
                        env = doc["environment"]
                        if source == "engine_build":
                            env["engine_build"]["version_banner"] = "** ngspice-470 : build"
                        else:
                            job = env["remote"]["fleet"][1]
                            job["worker_environment"]["simulator"]["version_banner"] = "** ngspice-45 : worker"

                    self.edit_json(f"{deck}_envelope", change_banner)
                    self.assert_error(source, "ngspice-47")

    def test_envelope_not_from_a_batch_job_is_an_error(self):
        self.edit_env("cmrr_envelope", lambda d: d["environment"].pop("remote"))
        self.assert_error("no environment.remote batch job")

    def test_cmrr_psrr_klt_without_its_audit_is_refused(self):
        self.fx.selection["records"][self.RECORD]["definition_checks"] = []
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_control_must_name_another_selected_record(self):
        self.raw()["control"] = self.RECORD
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_unselected_report_carries_no_cmrr_psrr_rule(self):
        self.fx.selection["records"][self.RECORD].pop("cmrr_psrr_klt")
        self.fx.selection["records"][self.RECORD]["definition_checks"] = []
        self.fx.save_selection()
        self.assertNotIn("cmrr_psrr_klt_audit_rule", self.fx.build())


class OffsetKltAudit(RawAuditCase):
    """Issue #504: the input-offset batch record -- the null + closed-loop
    `klt sim` envelopes joined with the selected open-loop record's Av0 --
    is selectable in place of the harness CSV, and every published cell
    follows from the pinned artifacts (definition check offset_klt_audit,
    the shared offset_post derivation)."""

    RECORD = "input-offset"
    POINT = "mos_tt_27C_1.20V"
    RAW_KEY = "offset_klt_raw"
    DEFINITION_CHECK = "offset_klt_audit"

    def setUp(self) -> None:
        super().setUp()
        self.fx.select_offset_batch_record()

    def fresh(self) -> None:
        super().fresh()
        self.fx.select_offset_batch_record()

    def rawfile(self, kind):
        return self.fx.root / self.raw()["files"][kind]["path"]

    def edit_envelope(self, kind, pid, name, value, repin=True) -> None:
        doc = json.loads(self.rawfile(kind).read_text(encoding="utf-8"))
        for c in doc["corners"]:
            if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" == pid:
                for m in c["measurements"]:
                    if m["name"] == name:
                        m["value"] = value
        self.rawfile(kind).write_text(json.dumps(doc), encoding="utf-8")
        if repin:
            self.raw()["files"][kind]["sha256"] = generate.sha256_file(self.rawfile(kind))
            self.fx.save_selection()

    def edit_join_row(self, mutate) -> None:
        """Rewrite (and repin) one row of the joined open-loop record CSV."""
        rec = self.fx.selection["records"][self.raw()["av0_join"]]
        path = self.fx.root / rec["csv"]
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(mutate(lines)) + "\n", encoding="utf-8")
        rec["csv_sha256"] = generate.sha256_file(path)
        self.fx.save_selection()

    # --- committed evidence -------------------------------------------------

    def test_committed_batch_record_verifies_all_45_points(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        src = content["sources"][self.RECORD]
        self.assertEqual((src["offset_klt_raw"]["status"], src["offset_klt_raw"]["points"]), ("verified", 45))
        self.assertEqual(src["offset_klt_raw"]["av0_join"], "open-loop-ac")
        self.assertEqual(src["valid_points"], 45)
        self.assertEqual(src["ngspice"], "ngspice-47")
        rows = rows_by_id(content)
        self.assertEqual(rows["offset_systematic"]["source"]["csv"], OFFSET_BATCH_FILES["csv"])
        self.assertEqual(rows["offset_systematic"]["coverage"]["complete"], True)
        # The ngspice-47 fleet record reproduces the harness binding corner to
        # all nine serialized digits; the literal bound verdict is unchanged.
        self.assertEqual((rows["offset_systematic"]["verdict"], rows["offset_systematic"]["measured_worst"]["point"]),
                         ("FAIL", "mos_fs_125C_1.08V"))
        self.assertEqual(rows["offset_systematic"]["measured_worst"]["value"], "21.9273527")

    def test_report_exposes_the_audit_rule_only_when_selected(self):
        content = self.fx.build()
        self.assertIn("Input-offset `klt sim` raw-evidence audit", content["offset_klt_audit_rule"])
        md = generate.render_markdown(generate.make_report(content, "20260101-000000-abcd", self.fx.root))
        self.assertIn("Input-offset `klt sim` raw-evidence audit", md)
        # Compatibility control (issue #504 AC): the committed harness-CSV
        # selection keeps reproducing without the rule or the population.
        committed = generate.build_content(REPO, SELECTION)
        self.assertNotIn("offset_klt_audit_rule", committed)
        self.assertNotIn("offset_klt_raw", json.dumps(committed["sources"]["input-offset"]))

    def test_summary_cells_follow_the_envelopes(self):
        for column in ("vos_null_v", "vos_abs_v", "vout_cl_v", "vos_closed_loop_v"):
            with self.subTest(column=column):
                self.fresh()
                self.fx.set_cell(self.RECORD, self.POINT, column, "0.005")
                self.assert_error(f"point {self.POINT} fails definition check {self.DEFINITION_CHECK}", column)

    # --- selection shape ----------------------------------------------------

    def test_offset_klt_raw_without_its_audit_is_refused(self):
        self.fx.selection["records"][self.RECORD]["definition_checks"] = ["offset_magnitude"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_audit_without_pinned_raw_evidence_is_refused(self):
        del self.fx.selection["records"][self.RECORD]["offset_klt_raw"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_every_artifact_must_be_pinned(self):
        for kind in generate.OFFSET_KLT_RAW_KINDS:
            with self.subTest(kind=kind):
                self.fresh()
                del self.raw()["files"][kind]
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()

    def test_av0_join_must_be_another_selected_record(self):
        for name in ("nope", self.RECORD):
            with self.subTest(name=name):
                self.raw()["av0_join"] = name
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()

    # --- tampering ----------------------------------------------------------

    def test_stale_pin_is_rejected_for_every_artifact(self):
        for kind in generate.OFFSET_KLT_RAW_KINDS:
            with self.subTest(kind=kind):
                self.fresh()
                path = self.rawfile(kind)
                path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                self.assert_error("does not match its selection pin")

    def test_missing_artifact_is_rejected(self):
        self.rawfile("cl").unlink()
        self.assert_error("missing raw offset-klt artifact cl")

    def test_coherent_envelope_edit_still_fails_against_the_summary(self):
        self.edit_envelope("null", self.POINT, "vos_null_v", 0.005)
        errors = self.assert_error(f"point {self.POINT} fails definition check {self.DEFINITION_CHECK}")
        self.assertTrue(any("vos_null_v" in e for e in errors), errors)

    def test_missing_corner_is_rejected(self):
        doc = json.loads(self.rawfile("null").read_text(encoding="utf-8"))
        doc["corners"] = [c for c in doc["corners"]
                          if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" != self.POINT]
        self.rawfile("null").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["null"]["sha256"] = generate.sha256_file(self.rawfile("null"))
        self.fx.save_selection()
        self.assert_error("no corner for point " + self.POINT)

    def test_duplicate_corner_is_rejected(self):
        doc = json.loads(self.rawfile("cl").read_text(encoding="utf-8"))
        doc["corners"].append(json.loads(json.dumps(doc["corners"][0])))
        self.rawfile("cl").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["cl"]["sha256"] = generate.sha256_file(self.rawfile("cl"))
        self.fx.save_selection()
        self.assert_error("duplicate corner")

    def test_errored_corner_is_rejected(self):
        doc = json.loads(self.rawfile("null").read_text(encoding="utf-8"))
        for c in doc["corners"]:
            if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" == self.POINT:
                c["status"] = "error"
        self.rawfile("null").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["null"]["sha256"] = generate.sha256_file(self.rawfile("null"))
        self.fx.save_selection()
        self.assert_error("is not a decided corner")

    def test_non_finite_raw_value_is_rejected(self):
        self.edit_envelope("null", self.POINT, "vos_null_v", None)
        self.assert_error("missing or non-finite raw value")

    def test_engines_must_agree(self):
        doc = json.loads(self.rawfile("cl").read_text(encoding="utf-8"))
        doc["environment"]["engine_version"] = "46"
        self.rawfile("cl").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["cl"]["sha256"] = generate.sha256_file(self.rawfile("cl"))
        self.fx.save_selection()
        self.assert_error("disagree on the engine")

    def test_below_the_toolchain_floor_is_rejected(self):
        for kind in ("null", "cl"):
            doc = json.loads(self.rawfile(kind).read_text(encoding="utf-8"))
            doc["environment"]["engine_version"] = "45"
            banner = doc["environment"]["remote"]["worker_environment"]["simulator"]["version_banner"]
            doc["environment"]["remote"]["worker_environment"]["simulator"]["version_banner"] = banner.replace("ngspice-47", "ngspice-45")
            if (doc["environment"].get("engine_build") or {}).get("version_banner"):
                doc["environment"]["engine_build"]["version_banner"] = (
                    doc["environment"]["engine_build"]["version_banner"].replace("ngspice-47", "ngspice-45")
                )
            self.rawfile(kind).write_text(json.dumps(doc), encoding="utf-8")
            self.raw()["files"][kind]["sha256"] = generate.sha256_file(self.rawfile(kind))
        self.fx.save_selection()
        self.assert_error("rejected by sim/pdk.json")

    def test_missing_passed_count_is_rejected_without_crashing(self):
        doc = json.loads(self.rawfile("null").read_text(encoding="utf-8"))
        doc.pop("passed", None)
        self.rawfile("null").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["null"]["sha256"] = generate.sha256_file(self.rawfile("null"))
        self.fx.save_selection()
        self.assert_error("offset klt raw evidence", "passed=None")

    def test_version_prefix_and_engine_build_banner_mismatch_are_rejected(self):
        # Prefix match ("ngspice-470" contains "ngspice-47") must not satisfy version "47".
        doc = json.loads(self.rawfile("null").read_text(encoding="utf-8"))
        sim = doc["environment"]["remote"]["worker_environment"]["simulator"]
        sim["version_banner"] = sim["version_banner"].replace("ngspice-47", "ngspice-470")
        self.rawfile("null").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["null"]["sha256"] = generate.sha256_file(self.rawfile("null"))
        self.fx.save_selection()
        self.assert_error("worker banner does not name ngspice-47")

        # engine_build.version_banner must also agree with engine_version.
        self.fresh()
        doc = json.loads(self.rawfile("cl").read_text(encoding="utf-8"))
        doc["environment"]["engine_build"]["version_banner"] = "** ngspice-46 : mismatch"
        self.rawfile("cl").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["cl"]["sha256"] = generate.sha256_file(self.rawfile("cl"))
        self.fx.save_selection()
        self.assert_error("engine_build banner does not name ngspice-47")

    def test_malformed_closure_entry_is_rejected(self):
        for kind in ("null", "cl"):
            with self.subTest(kind=kind):
                self.fresh()
                self.assert_malformed_klt_closure_rejected(kind)

    def test_engine_build_is_an_optional_object(self):
        for kind in ("null", "cl"):
            self.assert_klt_optional_object(kind, "environment.engine_build", "legacy-build")

    def test_worker_simulator_metadata_is_optional(self):
        for kind in ("null", "cl"):
            self.assert_klt_worker_simulator_validation(kind)

    def test_bench_dut_is_verified_against_a_renamed_snapshot(self):
        record = self.fx.selection["records"][self.RECORD]
        snapshot = self.fx.root / record["netlist_snapshot"]
        renamed = snapshot.rename(snapshot.with_name("offset-snapshot.spice"))
        record["netlist_snapshot"] = renamed.relative_to(self.fx.root).as_posix()
        self.fx.save_selection()

        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        audit = content["sources"][self.RECORD][self.RAW_KEY]
        self.assertEqual((audit["status"], audit["points"]), ("verified", 45))

    def test_multiple_bench_dut_entries_are_rejected_even_with_the_same_hash(self):
        self.add_klt_dut_copy("null")
        self.assert_error("is not the selected netlist snapshot")

    def test_simulated_dut_must_be_the_selected_snapshot(self):
        # A comment-only touch leaves the normalized (design-identity) hash
        # alone, so the ONLY thing that fires is the envelope-closure binding
        # of the simulated DUT to the selected snapshot: the stale-DUT rule.
        snap = self.fx.root / self.fx.selection["records"][self.RECORD]["netlist_snapshot"]
        snap.write_text(snap.read_text(encoding="utf-8") + "* touched\n", encoding="utf-8")
        self.assert_error("is not the selected netlist snapshot")

    def test_request_measurement_definitions_are_checked(self):
        doc = json.loads(self.rawfile("null_request").read_text(encoding="utf-8"))
        doc["measurements"][0]["limits"] = {"min": -0.05, "max": 0.05}
        self.rawfile("null_request").write_text(json.dumps(doc), encoding="utf-8")
        self.raw()["files"]["null_request"]["sha256"] = generate.sha256_file(self.rawfile("null_request"))
        self.fx.save_selection()
        self.assert_error("measurement vos_null_v limits")

    def test_closed_loop_body_must_carry_the_loop_break(self):
        body = self.rawfile("cl_body")
        body.write_text(body.read_text(encoding="utf-8").replace("Lbreak inn out 1e18", "* removed"), encoding="utf-8")
        self.raw()["files"]["cl_body"]["sha256"] = generate.sha256_file(body)
        self.fx.save_selection()
        errors = self.assert_error("element Lbreak")
        self.assertTrue(any("simulated bench body is not the pinned" in e for e in errors), errors)

    # --- the derivation's own negative controls ------------------------------

    def test_multiple_crossings_fail_op_validity(self):
        self.edit_envelope("null", self.POINT, "vos_crossings_n", 3.0)
        errors = self.assert_error(f"point {self.POINT} fails definition check {self.DEFINITION_CHECK}")
        self.assertTrue(any("crossings (expected exactly 1)" in e for e in errors), errors)

    def test_zero_crossings_fail_op_validity(self):
        self.edit_envelope("null", self.POINT, "vos_crossings_n", 0.0)
        errors = self.assert_error(f"point {self.POINT} fails definition check {self.DEFINITION_CHECK}")
        self.assertTrue(any("crossings (expected exactly 1)" in e for e in errors), errors)

    def test_railed_node_fails_op_validity(self):
        self.edit_envelope("null", self.POINT, "vtail_dc_v", 1.19)
        errors = self.assert_error(f"point {self.POINT} fails definition check {self.DEFINITION_CHECK}")
        self.assertTrue(any("op_pass" in e for e in errors), errors)

    def test_method_disagreement_fails_the_cross_check(self):
        self.edit_envelope("cl", self.POINT, "vout_cl_v", 0.58)
        errors = self.assert_error(f"point {self.POINT} fails definition check {self.DEFINITION_CHECK}")
        self.assertTrue(any("xcheck_pass" in e and "tolerance" in e for e in errors), errors)

    def test_flag_flips_that_match_the_derivation_are_coverage_not_errors(self):
        """op_pass=0 in the cell AND in the derivation is an invalid point
        (counted as missing coverage), never a silently passing one."""
        self.edit_envelope("null", self.POINT, "vos_crossings_n", 3.0)
        self.fx.set_cell(self.RECORD, self.POINT, "op_pass", "0")
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        rows = rows_by_id(content)
        row = rows["offset_systematic"]
        # The still-failing binding corner keeps the row's FAIL verdict; what
        # this control pins is that the invalid point is EXCLUDED (counted as
        # missing coverage), never graded and never an error.
        self.assertEqual(row["coverage"]["valid"], 44)
        self.assertIn(self.POINT, row["coverage"]["invalid"])
        self.assertNotIn(self.POINT, row["violating_points"])
        self.assertNotIn(self.POINT, [p["point_id"] for p in []])

    # --- the Av0 join --------------------------------------------------------

    def test_av0_bound_to_a_foreign_corner_is_rejected(self):
        def swap_temp(lines):
            header = lines[0].split(",")
            i_temp, i_pid = header.index("temp_c"), header.index("point_id")
            out = [lines[0]]
            for line in lines[1:]:
                cells = line.split(",")
                if cells[i_pid] == self.POINT:
                    cells[i_temp] = "125"
                out.append(",".join(cells))
            return out
        self.edit_join_row(swap_temp)
        self.assert_error(f"point {self.POINT}: its corner/temp_c/vdd_v columns spell")

    def test_av0_without_a_finite_value_is_rejected(self):
        def blank(lines):
            header = lines[0].split(",")
            i_av0, i_pid = header.index("av0_db"), header.index("point_id")
            out = [lines[0]]
            for line in lines[1:]:
                cells = line.split(",")
                if cells[i_pid] == self.POINT:
                    cells[i_av0] = "nan"
                out.append(",".join(cells))
            return out
        self.edit_join_row(blank)
        self.assert_error(f"point {self.POINT}: no finite Av0")

    def test_av0_row_missing_for_a_corner_is_rejected(self):
        def drop(lines):
            header = lines[0].split(",")
            i_pid = header.index("point_id")
            return [lines[0]] + [l for l in lines[1:] if l.split(",")[i_pid] != self.POINT]
        self.edit_join_row(drop)
        self.assert_error(f"point {self.POINT}: no row in the joined record")

    def test_av0_from_a_different_dut_is_rejected(self):
        join = self.raw()["av0_join"]
        snap = self.fx.root / self.fx.selection["records"][join]["netlist_snapshot"]
        snap.write_text(snap.read_text(encoding="utf-8") + "\nRdifferent_dut vdd vss 1\n", encoding="utf-8")
        errors = self.assert_error(f"av0_join record {join}: simulated a different DUT")
        self.assertTrue(any("never joined silently" in e for e in errors), errors)

    # --- a new valid value is selectable --------------------------------------

    def test_a_new_valid_value_that_differs_from_the_harness_csv_selects(self):
        """The batch record's binding corner re-measured UNDER the ratified
        bound (the harness CSV says 21.9273527 mV, a FAIL): envelope + derived
        cells edited coherently -- exactly what a new DUT's own evidence would
        be -- the audit passes, all 45 points stay valid, and the row now
        PASSES on a value the old fixed harness CSV never held."""
        pid = "mos_fs_125C_1.08V"
        new_vos = 0.0151
        self.edit_envelope("null", pid, "vos_null_v", new_vos)
        # A coherent new measurement moves the closed-loop reading with the
        # null (the two methods measure one offset): choose vout_cl so the
        # referred-back vos_cl IS the new null, exactly as a re-measured
        # corner of a changed DUT would agree with itself.
        av0 = float(next(r.split(",")[4] for r in
                         (self.fx.root / self.fx.selection["records"][self.raw()["av0_join"]]["csv"]).read_text().splitlines()[1:]
                         if r.split(",")[0] == pid))
        av = 10.0 ** (av0 / 20.0)
        self.edit_envelope("cl", pid, "vout_cl_v", 1.08 / 2 - new_vos * av / (1.0 + av))
        # regenerate the CSV's derived cells for the edited corner the way the
        # bench writer does (the same shared derivation).
        doc = json.loads(self.rawfile("null").read_text(encoding="utf-8"))
        corner = next(c for c in doc["corners"]
                      if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" == pid)
        n = {m["name"]: m["value"] for m in corner["measurements"]}
        cl_doc = json.loads(self.rawfile("cl").read_text(encoding="utf-8"))
        cl_corner = next(c for c in cl_doc["corners"]
                         if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" == pid)
        vout_cl = {m["name"]: m["value"] for m in cl_corner["measurements"]}["vout_cl_v"]
        d = offset_post.derive_point(n, vout_cl, 1.08, av0)
        def rewrite(lines):
            header = lines[0].split(",")
            idx = {c: i for i, c in enumerate(header)}
            out = [lines[0]]
            for line in lines[1:]:
                cells = line.split(",")
                if cells[0] == pid:
                    cells[idx["vos_null_v"]] = offset_post.serialize(d["vos_null_v"])
                    cells[idx["vos_abs_v"]] = offset_post.serialize(d["vos_abs_v"])
                    cells[idx["vout_cl_v"]] = offset_post.serialize(vout_cl)
                    cells[idx["vout_cl_err_v"]] = offset_post.serialize(d["vout_cl_err_v"])
                    cells[idx["vos_closed_loop_v"]] = offset_post.serialize(d["vos_closed_loop_v"])
                    cells[idx["vos_method_delta_v"]] = offset_post.serialize(d["vos_method_delta_v"])
                out.append(",".join(cells))
            return out
        path = self.fx.csv_path(self.RECORD)
        path.write_text("\n".join(rewrite(path.read_text(encoding="utf-8").splitlines())) + "\n", encoding="utf-8")
        self.fx.selection["records"][self.RECORD]["csv_sha256"] = generate.sha256_file(path)
        self.fx.save_selection()
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        rows = rows_by_id(content)
        row = rows["offset_systematic"]
        self.assertEqual(row["verdict"], "PASS")
        self.assertEqual(row["violating_points"], [])
        # The row's extremum is now a DIFFERENT point at a DIFFERENT value
        # than the fixed harness CSV ever held (its worst was mos_fs_125C_1.08V
        # at 21.9273527 mV): the selection grades the batch record's own
        # numbers, not the old CSV's.
        self.assertNotEqual(row["measured_worst"]["point"], "mos_fs_125C_1.08V")
        self.assertNotEqual(row["measured_worst"]["value"], "21.9273527")
        self.assertLess(float(row["measured_worst"]["value"]), 21.9)


class SlewRawAudit(PointRawPinControlMixin, RawAuditCase):
    """Issue #227: the slew-rate summary is audited against hash-pinned
    transient waveforms and rendered netlists with the SAME measurement the
    bench runs (sim/slew-rate/slew_post.py)."""

    RECORD = "slew-rate"
    POINT = "mos_tt_27C_1.20V"
    RAW_KEY = "slew_raw"
    RAW_NOUN = "slew"
    MISSING_PHRASE = "waveform/netlist"
    DEFINITION_CHECK = "slew_raw_audit"

    # --- committed evidence -------------------------------------------------

    def test_committed_population_rederives_offline(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        raw = content["sources"][self.RECORD]["slew_raw"]
        self.assertEqual((raw["status"], raw["points"]), ("verified", 45))
        self.assertIn("slew_raw_audit", content["sources"][self.RECORD]["definition_checks"])
        self.assertEqual(len(content["sources"][self.RECORD]["definition_checks"]), 2)
        self.assertEqual(content["sources"][self.RECORD]["valid_points"], 45)

    def test_report_exposes_audit_rule_and_status(self):
        content = self.fx.build()
        self.assertIn("Slew-rate raw-evidence audit", content["slew_audit_rule"])
        md = generate.render_markdown(generate.make_report(content, "20260101-000000-abcd", self.fx.root))
        self.assertIn("pinned waveform+netlist pairs", md)

    def test_every_committed_cell_is_the_shared_serialization(self):
        for pid in sorted(self.raw()["files"]):
            path = REPO / self.raw()["files"][pid]["tran"]["path"]
            t, v = slew_post.parse_waveform(path.read_text(encoding="utf-8"), str(path))
            row = next(r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1] if r["point_id"] == pid)
            vcm = float(row["vcm_v"])
            m = slew_post.measure(t, v, vcm, 0.15, 0.075, 300e-9, 550e-9, 800e-9)
            self.assertEqual(slew_post.format_fields(m), [row[f] for f in slew_post.FIELDS], pid)
            self.assertEqual(slew_post.serialize(slew_post.worst_edge(m["sr_rise_v_per_us"], m["sr_fall_v_per_us"])),
                             row["sr_worst_v_per_us"], pid)

    # --- coherent summary tampering ----------------------------------------

    def test_coherent_summary_edit_with_refreshed_hash_fails(self):
        # rise/fall/worst moved together: the old definition check still passes,
        # the unchanged pinned waveform does not.
        self.fx.set_cell(self.RECORD, self.POINT, "sr_rise_v_per_us", "9.5")
        self.fx.set_cell(self.RECORD, self.POINT, "sr_fall_v_per_us", "9.25")
        self.fx.set_cell(self.RECORD, self.POINT, "sr_worst_v_per_us", "9.25")
        self.assertIsNone(generate._check_slew_worse_edge(
            {"sr_rise_v_per_us": "9.5", "sr_fall_v_per_us": "9.25", "sr_worst_v_per_us": "9.25"}, None))
        errors = self.definition_error()
        self.assertTrue(any("sr_rise_v_per_us 9.5 is not" in e and "recomputed from the pinned waveform" in e for e in errors), errors)
        self.assertTrue(any("sr_fall_v_per_us 9.25 is not" in e for e in errors), errors)
        self.assertTrue(any(self.entry("tran")["path"] in e for e in errors), errors)

    def test_worst_edge_alone_fails(self):
        rise = self.cell("sr_rise_v_per_us")
        self.fx.set_cell(self.RECORD, self.POINT, "sr_worst_v_per_us", rise)  # not the slower edge
        errors = self.definition_error()
        self.assertTrue(any("is not the worse" in e or "sr_worst_v_per_us" in e for e in errors), errors)

    def test_one_digit_beyond_serialization_fails(self):
        for field in ("sr_rise_inner_v_per_us", "vout_min_v", "vout_max_v", "window_lo_v", "window_hi_v"):
            with self.subTest(field=field):
                self.fresh()
                cell = self.cell(field)
                bumped = format(float(cell) * 1.00001 + (1e-7 if float(cell) == 0 else 0), ".6g")
                self.fx.set_cell(self.RECORD, self.POINT, field, bumped)
                self.assert_error(f"point {self.POINT} fails definition check slew_raw_audit", field)

    def test_vdd_and_common_mode_cells_follow_the_netlist(self):
        self.fx.set_cell(self.RECORD, self.POINT, "vcm_v", "0.61")
        self.assertTrue(any("vcm_v" in e and self.entry("netlist")["path"] in e for e in self.definition_error()))

    # --- waveform evidence ---------------------------------------------------

    def test_changed_waveform_repinned_disagrees_with_summary(self):
        # a slower rising edge: delay the output ramp by stretching v around the window
        def slow(lines):
            out = []
            for line in lines:
                t, v = line.split()[:2]
                out.append(f" {t} {v} " if float(t) < 300e-9 or float(t) > 550e-9 else f" {t} {float(v) * 0.9 + 0.05:.8e} ")
            return out
        self.edit_raw("tran", slow)
        self.definition_error()

    def test_non_finite_and_malformed_samples_fail(self):
        for bad in (" 1.0e-07 nan ", " 1.0e-07 inf ", " nan 0.5 ", " 1.0e-07 -Infinity ", " 1.0e-07 abc ", " 1.0e-07 "):
            with self.subTest(bad=bad):
                self.fresh()
                self.edit_raw("tran", lambda ls: ls[:5] + [bad] + ls[5:])
                errors = self.assert_error(f"point {self.POINT}: invalid slew waveform")
                self.assertTrue(any(f"{self.entry('tran')['path']}:6" in e for e in errors), errors)

    def test_time_order_violations_fail(self):
        def swap(lines):
            return lines[:5] + [lines[6], lines[5]] + lines[7:]
        self.edit_raw("tran", swap)
        self.assert_error(f"point {self.POINT}: invalid slew waveform", "does not increase")

    def test_duplicate_time_stamp_fails(self):
        self.edit_raw("tran", lambda ls: ls[:5] + [ls[5]] + ls[5:])
        self.assert_error(f"point {self.POINT}: invalid slew waveform", "does not increase")

    def test_empty_waveform_fails(self):
        self.edit_raw("tran", lambda ls: [])
        self.assert_error(f"point {self.POINT}: invalid slew waveform", "need at least 2")

    def test_missing_crossings_cannot_pass_even_with_nan_cells(self):
        # a flat waveform never crosses the windows; the summary is edited to
        # agree (nan) and keeps its flags: still no passing measurement.
        self.edit_raw("tran", lambda ls: [f"{l.split()[0]} 0.6" for l in ls])
        for field in ("sr_rise_v_per_us", "sr_fall_v_per_us", "sr_rise_inner_v_per_us",
                      "sr_fall_inner_v_per_us", "sr_worst_v_per_us"):
            self.fx.set_cell(self.RECORD, self.POINT, field, "nan")
        errors = self.definition_error()
        self.assertTrue(any("no window crossing inside its edge interval" in e for e in errors), errors)

    # --- flags -----------------------------------------------------------------

    def _audit_with_all_points_valid(self):
        self.fx.selection["records"][self.RECORD]["valid_when"] = []
        self.fx.save_selection()

    def test_linearity_flag_change_is_detected(self):
        self._audit_with_all_points_valid()
        self.fx.set_cell(self.RECORD, self.POINT, "linearity_pass", "0")
        errors = self.definition_error()
        self.assertTrue(any("linearity_pass 0 is not 1" in e for e in errors), errors)

    def test_traverse_flag_change_is_detected(self):
        self._audit_with_all_points_valid()
        self.fx.set_cell(self.RECORD, self.POINT, "traverse_pass", "0")
        errors = self.definition_error()
        self.assertTrue(any("traverse_pass 0 is not 1" in e for e in errors), errors)

    def test_flag_that_the_waveform_fails_cannot_be_asserted_passing(self):
        # park the output mid-window before the rising edge: traverse truly fails
        self.edit_raw("tran", lambda ls: [
            f"{l.split()[0]} 0.6" if 290e-9 <= float(l.split()[0]) < 299.5e-9 else l for l in ls])
        errors = self.definition_error()
        self.assertTrue(any("traverse_pass 1 is not 0" in e for e in errors), errors)

    # --- measurement configuration -------------------------------------------

    def test_selection_config_mismatch_is_refused(self):
        for field, value in (("t2_ns", "301"), ("t3_ns", "560"), ("tstop_ns", "900"),
                             ("win_outer_v", "0.2"), ("win_inner_v", "0.05")):
            with self.subTest(field=field):
                self.fresh()
                self.raw()["config"][field] = value
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()

    def test_missing_config_is_refused(self):
        del self.raw()["config"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_netlist_schedule_disagreeing_with_config_is_refused(self):
        self.edit_raw("netlist", lambda ls: [l.replace("300n 0.3 300.1n", "310n 0.3 310.1n") for l in ls])
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch", "t2_ns 310")

    def test_netlist_stop_time_disagreeing_with_config_is_refused(self):
        self.edit_raw("netlist", lambda ls: [("tran 1n 900n 0 0.05n" if l.startswith("tran ") else l) for l in ls])
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch", ".tran stop 900")

    def test_netlist_common_mode_not_mid_rail_is_refused(self):
        self.edit_raw("netlist", lambda ls: [l.replace("dc 0.6 pwl(0 0.6 50n 0.6", "dc 0.7 pwl(0 0.7 50n 0.7") for l in ls])
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch", "is not VDD/2")

    def test_netlist_writing_another_waveform_is_refused(self):
        self.edit_raw("netlist", lambda ls: [l.replace(f"{self.POINT}_tran.csv", "mos_tt_27C_1.32V_tran.csv") for l in ls])
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch", "wrdata target")

    def test_malformed_netlist_fails(self):
        self.edit_raw("netlist", lambda ls: [l for l in ls if not l.startswith("Vinp")])
        self.assert_error(f"point {self.POINT}: invalid rendered netlist")

    # --- the shared module -----------------------------------------------------

    def test_measure_is_nan_without_crossings_and_worst_edge_ignores_one_nan(self):
        t = [i * 1e-9 for i in range(800)]
        m = slew_post.measure(t, [0.6] * 800, 0.6, 0.15, 0.075, 300e-9, 550e-9, 800e-9)
        self.assertTrue(math.isnan(m["sr_rise_v_per_us"]) and math.isnan(m["sr_fall_v_per_us"]))
        self.assertEqual((m["linearity_pass"], m["traverse_pass"]), (0, 0))
        self.assertTrue(math.isnan(slew_post.worst_edge(float("nan"), float("nan"))))
        self.assertEqual(slew_post.worst_edge(float("nan"), 3.0), 3.0)
        self.assertEqual(slew_post.serialize(float("nan")), "nan")
        self.assertEqual(slew_post.serialize(0.1 + 0.2), "0.3")

    def test_runner_uses_the_shared_module_and_its_constants(self):
        runner = (REPO / "sim" / "slew-rate" / "run_slew_sweep.sh").read_text(encoding="utf-8")
        self.assertIn("slew_post.py", runner)
        self.assertNotIn("def cross(", runner)
        for var, key in (("WIN_OUTER", "win_outer_v"), ("WIN_INNER", "win_inner_v"), ("T2_NS", "t2_ns"),
                         ("T3_NS", "t3_ns"), ("TSTOP_NS", "tstop_ns")):
            self.assertIn(f'{var}="{slew_post.CONFIG[key]}"' if var.startswith("WIN") else f"{var}={slew_post.CONFIG[key]}\n", runner)

    def test_cli_matches_the_committed_summary(self):
        row = next(r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1] if r["point_id"] == self.POINT)
        out = subprocess.run(
            [sys.executable, "-I", str(REPO / "sim" / "slew-rate" / "slew_post.py"),
             str(REPO / self.entry("tran")["path"]), row["vcm_v"], "0.15", "0.075", "300", "550", "800"],
            capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, [row[f] for f in slew_post.FIELDS])

    def test_cli_reports_a_bad_waveform_with_no_stdout(self):
        bad = self.fx.root / "bad_tran.csv"
        bad.write_text(" 0 nan \n 1e-9 0.5 \n", encoding="utf-8")
        res = subprocess.run([sys.executable, "-I", str(REPO / "sim" / "slew-rate" / "slew_post.py"),
                              str(bad), "0.6", "0.15", "0.075", "300", "550", "800"], capture_output=True, text=True)
        self.assertEqual((res.returncode, res.stdout), (1, ""))
        self.assertIn("non-finite", res.stderr)


class SlewKltAudit(RawAuditCase):
    """Issue #501: the slew-rate summary audited against the hash-pinned batch
    `klt sim` envelope (crossings, not waveforms), definition check
    slew_klt_audit. The committed selection still pins the local waveforms;
    these tests select the committed same-DUT envelope in a fixture copy."""

    RECORD = "slew-rate"
    POINT = "mos_tt_27C_1.20V"
    RAW_KEY = "slew_klt"
    DEFINITION_CHECK = "slew_klt_audit"
    FILES = {
        "envelope": "sim/slew-rate/klt/records/20261015-063443-80878d7.sim.json",
        "request": "sim/slew-rate/klt/slew.request.json",
        "bench_body": "sim/slew-rate/klt/tb_slew.body.spice",
    }

    def setUp(self) -> None:
        super().setUp()
        rec = self.fx.selection["records"][self.RECORD]
        pins = {}
        for kind, rel in self.FILES.items():
            dst = self.fx.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)
            pins[kind] = {"path": rel, "sha256": generate.sha256_file(dst)}
        # the pure batch scenario: no local waveforms, the envelope instead
        rec.pop("slew_raw")
        rec["definition_checks"] = ["slew_worse_edge", "slew_klt_audit"]
        rec["slew_klt"] = {"files": pins}
        self.fx.save_selection()
        self.drop_waveform_only_columns()

    WAVEFORM_ONLY = ("vout_min_v", "vout_max_v", "window_lo_v", "window_hi_v")

    def drop_waveform_only_columns(self) -> None:
        """A pure-batch record cannot declare the columns only slew_raw audits
        (issue #513); the control fixture drops them from the signed-off CSV."""
        path = self.fx.csv_path(self.RECORD)
        rows = [line.split(",") for line in path.read_text(encoding="utf-8").splitlines()]
        keep = [i for i, c in enumerate(rows[0]) if c not in self.WAVEFORM_ONLY]
        path.write_text("\n".join(",".join(r[i] for i in keep) for r in rows) + "\n", encoding="utf-8")
        self.fx.selection["records"][self.RECORD]["csv_sha256"] = generate.sha256_file(path)
        self.fx.save_selection()

    def edit_env(self, mutate, kind="envelope", repin=True) -> None:
        self.edit_json(kind, mutate, repin)

    def corner(self, doc, pid=None):
        pid = pid or self.POINT
        for c in doc["corners"]:
            if f"{c['process']}_{c['temperature_c']}C_{c['supply_v']['vdd']:.2f}V" == pid:
                return c
        raise KeyError(pid)

    def meas(self, doc, name, pid=None):
        return next(m for m in self.corner(doc, pid)["measurements"] if m["name"] == name)

    # --- issue #513: item 1, columns no batch check covers ----------------------

    def test_pure_batch_record_declaring_waveform_only_columns_is_refused(self):
        self.fresh_pure_batch_with_columns()
        errors = self.assert_error("pins slew_klt without slew_raw")
        msg = next(e for e in errors if "pins slew_klt without slew_raw" in e)
        for col in self.WAVEFORM_ONLY:
            self.assertIn(col, msg)

    def fresh_pure_batch_with_columns(self) -> None:
        self.fresh()
        rec = self.fx.selection["records"][self.RECORD]
        pins = {}
        for kind, rel in self.FILES.items():
            dst = self.fx.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)
            pins[kind] = {"path": rel, "sha256": generate.sha256_file(dst)}
        rec.pop("slew_raw", None)
        rec["definition_checks"] = ["slew_worse_edge", "slew_klt_audit"]
        rec["slew_klt"] = {"files": pins}
        self.fx.save_selection()

    def test_pure_batch_record_without_those_columns_passes(self):
        self.assertEqual(self.errors(self.fx.build()), [])

    # --- issue #513: item 2, every consumed measurement is pinned ----------------

    def edit_request_spice(self, name, old, new) -> None:
        def mutate(doc):
            m = next(m for m in doc["measurements"] if m["name"] == name)
            self.assertIn(old, m["spice"])
            m["spice"] = m["spice"].replace(old, new)
        self.edit_env(mutate, kind="request")

    def test_moved_traverse_sample_time_is_refused(self):
        for name, old, new in (("pre_rise_orel_v", "at=299n", "at=399n"), ("pre_fall_orel_v", "at=549n", "at=649n")):
            with self.subTest(name=name):
                self.fx.close()
                self.setUp()
                self.edit_request_spice(name, old, new)
                self.assert_error(f"slew request: measurement {name} is")

    def test_redefined_drive_and_dc_measurements_are_refused(self):
        for name, old, new in (
            ("vinn_max_v", "max v(inn)", "min v(inn)"),
            ("vout_dc_v", "at=0", "at=1n"),
            ("op_vout_rail_frac", "v(fout)", "v(fd1)"),
            ("vibias_dc_v", "v(ibias)", "v(tail)"),
        ):
            with self.subTest(name=name):
                self.fx.close()
                self.setUp()
                self.edit_request_spice(name, old, new)
                self.assert_error(f"slew request: measurement {name} is")

    def test_every_limited_measurement_has_a_pinned_definition(self):
        self.assertLessEqual(set(common.SLEW_KLT_LIMITS), set(common.SLEW_KLT_SPICE))

    def test_record_pinning_both_waveform_and_envelope_passes(self):
        """Positive control for the `sk is not None and sr is None` guard
        (issue #532): slew_raw kept beside slew_klt, both audits declared and
        the waveform-only columns left in the CSV."""
        self.fresh()
        rec = self.fx.selection["records"][self.RECORD]
        self.assertIn("slew_raw", rec)
        pins = {}
        for kind, rel in self.FILES.items():
            dst = self.fx.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)
            pins[kind] = {"path": rel, "sha256": generate.sha256_file(dst)}
        rec["definition_checks"] = ["slew_worse_edge", "slew_raw_audit", "slew_klt_audit"]
        rec["slew_klt"] = {"files": pins}
        self.fx.save_selection()
        header = self.fx.csv_path(self.RECORD).read_text(encoding="utf-8").splitlines()[0].split(",")
        for col in self.WAVEFORM_ONLY:
            self.assertIn(col, header)
        self.assertEqual(self.errors(self.fx.build()), [])

    # --- same-DUT control ----------------------------------------------------

    def test_same_dut_envelope_reproduces_the_harness_record(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        src = content["sources"][self.RECORD]
        self.assertEqual((src["slew_klt"]["status"], src["slew_klt"]["points"]), ("verified", 45))
        self.assertEqual(src["slew_klt"]["job"], "klt-sim-9649fa050398")
        self.assertEqual((src["valid_points"], src["ngspice"]), (45, "ngspice-46"))
        self.assertIn("Slew-rate batch-envelope audit", content["slew_klt_audit_rule"])
        row = rows_by_id(content)["slew_rate"]
        self.assertEqual(row["verdict"], "PASS")
        self.assertTrue(row["load"].startswith("CL = 2 pF"), row["load"])

    # --- shared simulator admission policy (issue #519) ----------------------

    def versionless_summary(self, envelope_version: str) -> None:
        """The summary names no ngspice version, so the slew envelope is the
        only source; both inputs are re-pinned so hash errors cannot mask the
        policy outcome."""
        md_rel = self.fx.selection["records"][self.RECORD]["md"]
        md = self.fx.root / md_rel
        md.write_text(re.sub(r"ngspice-\d+", "batch-fleet", md.read_text(encoding="utf-8")), encoding="utf-8")
        self.fx.selection["records"][self.RECORD]["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()

        def set_ver(doc):
            doc["environment"]["engine_version"] = envelope_version
            banner = doc["environment"].get("engine_build", {}).get("version_banner")
            if banner:
                doc["environment"]["engine_build"]["version_banner"] = re.sub(r"ngspice-\d+", f"ngspice-{envelope_version}", banner)

        self.edit_env(set_ver)

    def edit_pdk(self, mutate) -> None:
        path = self.fx.root / self.fx.selection["pdk_pin"]
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_envelope_above_the_floor_is_admitted(self):
        self.versionless_summary("47")
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        self.assertEqual(content["sources"][self.RECORD]["ngspice"], "ngspice-47")

    def test_envelope_below_the_floor_is_rejected(self):
        self.versionless_summary("45")
        errors = self.assert_error("ran on ngspice-45", "floor ngspice-46")
        self.assertFalse(any("pins ngspice-46" in e for e in errors), errors)

    def test_envelope_must_match_the_exact_pin_when_the_floor_is_absent(self):
        self.versionless_summary("47")
        self.edit_pdk(lambda d: d["osdi_toolchain"].pop("ngspice_min_major"))
        self.assert_error("ran on ngspice-47", "expected 'ngspice-46'")

    def test_summary_and_envelope_conflict_fails_even_when_both_clear_the_floor(self):
        self.versionless_summary("47")
        md_rel = self.fx.selection["records"][self.RECORD]["md"]
        md = self.fx.root / md_rel
        md.write_text(md.read_text(encoding="utf-8") + "\nSimulator: ngspice-48\n", encoding="utf-8")
        self.fx.selection["records"][self.RECORD]["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()
        self.assert_error("ran ngspice-47 but the selected record's prose names ngspice-48")

    def test_unselected_report_carries_no_batch_rule(self):
        fx = Fixture()
        try:
            self.assertNotIn("slew_klt_audit_rule", fx.build())
        finally:
            fx.close()

    def test_tolerances_equal_the_compare_script(self):
        sys.path.insert(0, str(REPO / "sim" / "slew-rate" / "klt"))
        import compare  # noqa: E402
        import defchecks  # noqa: E402
        self.assertEqual(compare.TOLERANCES["sr_rise_v_per_us"]["rel"], defchecks.SLEW_KLT_RATE_REL)
        self.assertEqual(compare.TOLERANCES["vout_dc_v"]["abs"], defchecks.SLEW_KLT_DC_ABS)
        self.assertEqual(compare.TOLERANCES["vout_dc_v"]["rel"], defchecks.SLEW_KLT_DC_REL)

    # --- selection shape ----------------------------------------------------

    def test_envelope_without_its_audit_is_refused(self):
        self.fx.selection["records"][self.RECORD]["definition_checks"] = ["slew_worse_edge"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_audit_without_pinned_envelope_is_refused(self):
        del self.fx.selection["records"][self.RECORD]["slew_klt"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_every_artifact_must_be_pinned(self):
        for kind in self.FILES:
            with self.subTest(kind=kind):
                self.tearDown()
                self.fx.close()
                self.setUp()
                del self.raw()["files"][kind]
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()

    def test_drifted_envelope_is_refused(self):
        self.edit_env(lambda d: d.update(note="x"), repin=False)
        self.assert_error("does not match its selection pin")

    # --- tamper / missing / stale / incomplete ------------------------------

    def test_missing_crossing_names_corner_and_field(self):
        def mutate(doc):
            self.corner(doc)["measurements"] = [m for m in self.corner(doc)["measurements"] if m["name"] != "t_fall_inner_s"]
        self.edit_env(mutate)
        self.assert_error(f"point {self.POINT}: missing or non-finite measurement(s) ['t_fall_inner_s']")

    def test_nan_crossing_names_corner_and_field(self):
        self.edit_env(lambda d: self.meas(d, "t_rise_outer_s").update(value=None))
        self.assert_error(f"point {self.POINT}: missing or non-finite measurement(s) ['t_rise_outer_s']")

    def test_reported_rate_must_follow_its_crossings(self):
        self.edit_env(lambda d: self.meas(d, "sr_rise_v_per_us").update(value=20.0))
        self.assert_error(f"point {self.POINT} fails definition check slew_klt_audit", "sr_rise_v_per_us: envelope reports 20.0")

    def test_tampered_worst_edge(self):
        self.fx.set_cell(self.RECORD, self.POINT, "sr_worst_v_per_us", "9.5")
        self.assert_error(f"point {self.POINT} fails definition check slew_worse_edge")
        self.fresh()
        self.setUp()
        # rise/fall/worst moved together: only the envelope can refuse it
        for col in ("sr_rise_v_per_us", "sr_fall_v_per_us", "sr_worst_v_per_us"):
            self.fx.set_cell(self.RECORD, self.POINT, col, "9.5")
        self.assert_error(f"point {self.POINT} fails definition check slew_klt_audit", "recomputed from the pinned envelope crossings")

    def test_validity_flag_is_derived_not_trusted(self):
        # a drive excursion outside the request's limit, reported coherently
        def mutate(doc):
            self.meas(doc, "vinn_max_v")["value"] += 0.05
            self.meas(doc, "drive_pp_v")["value"] += 0.05
            self.meas(doc, "drive_centre_err_v")["value"] += 0.025
        self.edit_env(mutate)
        self.assert_error("drive_pass '1' but the pinned envelope's reported quantities")

    def test_malformed_closure_entry_is_rejected(self):
        self.assert_malformed_klt_closure_rejected("envelope")

    def test_engine_build_is_an_optional_object(self):
        self.assert_klt_optional_object("envelope", "environment.engine_build", "legacy-build")

    def test_worker_simulator_metadata_is_optional(self):
        self.assert_klt_worker_simulator_validation("envelope")

    def test_all_matching_dut_paths_must_have_the_snapshot_hash(self):
        self.add_klt_dut_copy("envelope")
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        audit = content["sources"][self.RECORD][self.RAW_KEY]
        self.assertEqual((audit["status"], audit["points"]), ("verified", 45))

        self.edit_env(lambda doc: doc["environment"]["netlist_closure"][-1].update(sha256="0" * 64))
        self.assert_error("is not the selected netlist snapshot")

    def test_stale_dut_hash(self):
        def mutate(doc):
            for c in doc["environment"]["netlist_closure"]:
                if c["path"] == "design/netlist/opamp_core.spice":
                    c["sha256"] = "0" * 64
        self.edit_env(mutate)
        self.assert_error("is not the selected netlist snapshot")

    def test_stale_bench_body(self):
        self.edit_env(lambda d: d["environment"].update(netlist_sha256="1" * 64))
        self.assert_error("simulated bench body")

    def test_incomplete_corner_set(self):
        self.edit_env(lambda d: d["corners"].pop())
        self.assert_error("no corner for point mos_fs_125C_1.32V")

    def test_duplicate_corner(self):
        self.edit_env(lambda d: d["corners"].append(json.loads(json.dumps(d["corners"][0]))))
        self.assert_error("duplicate corner mos_tt_-40C_1.08V")

    def test_errored_corner_is_not_evidence(self):
        self.edit_env(lambda d: self.corner(d).update(status="error"))
        self.assert_error(f"point {self.POINT} is not a decided corner")

    def test_contradictory_simulator_version(self):
        def mutate(doc):
            remote = doc["environment"]["remote"]
            remote.setdefault("worker_environment", {}).setdefault("simulator", {})["version_banner"] = "ngspice-45 : x"
        self.edit_env(mutate)
        self.assert_error("contradictory simulator version")

    def test_version_prefix_and_engine_build_banner_mismatch_are_rejected(self):
        # Prefix match ("ngspice-460" contains "ngspice-46") must not satisfy version "46".
        def set_prefix(doc):
            remote = doc["environment"]["remote"]
            remote.setdefault("worker_environment", {}).setdefault("simulator", {})["version_banner"] = "ngspice-460 : x"
        self.edit_env(set_prefix)
        self.assert_error("worker banner does not name ngspice-46", "contradictory simulator version")

        # engine_build.version_banner must also agree with engine_version.
        self.fx.close()
        self.setUp()
        self.edit_env(lambda d: d["environment"].update(engine_build={"version_banner": "** ngspice-45 : mismatch"}))
        self.assert_error("engine_build banner does not name ngspice-46", "contradictory simulator version")

    def test_envelope_version_must_match_the_record_prose(self):
        self.edit_env(lambda d: d["environment"].update(engine_version="45"))
        self.assert_error("ran ngspice-45 but the selected record's prose names ngspice-46")

    def test_relaxed_request_limit_is_refused(self):
        def mutate(doc):
            next(m for m in doc["measurements"] if m["name"] == "lin_rise_ratio")["limits"] = {"min": 0.5, "max": 1.5}
        self.edit_env(mutate, kind="request")
        self.assert_error("lin_rise_ratio limits are")

    def test_load_must_be_a_stated_cl(self):
        def edit(text):
            return text.replace("Cload out vss 2e-12", "Cload out vss 5e-12")
        pin = self.raw()["files"]["bench_body"]
        path = self.fx.root / pin["path"]
        path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
        pin["sha256"] = generate.sha256_file(path)
        self.fx.save_selection()
        self.assert_error("Cload 5e-12 is not a CL the record's own prose states")

    # --- limit miss is a result, not an error ---------------------------------

    def test_genuine_limit_miss_stays_a_failing_row(self):
        def mutate(doc):
            for name in ("t_rise_outer_s", "t_rise_inner_s"):
                self.meas(doc, name)["value"] *= 1.2
            for name in ("sr_rise_v_per_us", "sr_rise_inner_v_per_us"):
                self.meas(doc, name)["value"] /= 1.2
            self.meas(doc, "sr_rise_v_per_us")["status"] = "fail"
            self.corner(doc)["status"] = "fail"
            doc.update(status="fail", passed=44, failed=1)
        self.edit_env(mutate)
        rate = float(self.cell("sr_rise_v_per_us")) / 1.2
        for col, value in (("sr_rise_v_per_us", rate), ("sr_worst_v_per_us", rate),
                           ("sr_rise_inner_v_per_us", float(self.cell("sr_rise_inner_v_per_us")) / 1.2)):
            self.fx.set_cell(self.RECORD, self.POINT, col, f"{value:.6g}")
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        row = rows_by_id(content)["slew_rate"]
        self.assertEqual((row["verdict"], row["measured_worst"]["point"]), ("FAIL", self.POINT))


class PinnedPopulationNeedsItsAudit(unittest.TestCase):
    """population => check (issue #533): a record that pins a raw population
    must run the definition check that audits it, for every population in
    `selection.POPULATION_AUDITS`, not only the klt ones."""

    # (record, population, audit) for each population the committed selection pins.
    CASES = (
        ("slew-rate", "slew_raw", "slew_raw_audit"),
        ("input-noise", "noise_raw", "noise_raw_audit"),
        ("output-swing", "swing_raw", "swing_raw_audit"),
        ("cmrr-mismatch", "mc_samples", "cmrr_mc_statistics"),
        ("input-offset-mc", "draws_csv", "offset_mc_statistics"),
    )

    def test_table_covers_every_pinned_population(self):
        import selection
        self.assertEqual(
            set(selection.POPULATION_AUDITS),
            {"slew_raw", "noise_raw", "swing_raw", "mc_samples", "draws_csv",
             "slew_klt", "klt_raw", "offset_klt_raw", "cmrr_psrr_klt"},
        )
        for audit in selection.POPULATION_AUDITS.values():
            self.assertIn(audit, selection.DEFINITION_CHECKS)

    def test_population_without_its_audit_is_refused(self):
        for record, population, audit in self.CASES:
            with self.subTest(population=population):
                fx = Fixture()
                try:
                    rec = fx.selection["records"][record]
                    self.assertIn(population, rec)
                    rec["definition_checks"] = [c for c in rec["definition_checks"] if c != audit]
                    fx.save_selection()
                    with self.assertRaisesRegex(generate.SelectionError, "never pinned and then ignored"):
                        fx.build()
                finally:
                    fx.close()

    def test_one_audit_does_not_cover_a_second_population(self):
        fx = Fixture()
        try:
            slew = fx.selection["records"]["slew-rate"]
            slew["noise_raw"] = fx.selection["records"]["input-noise"]["noise_raw"]
            fx.save_selection()
            with self.assertRaisesRegex(generate.SelectionError, "noise_raw_audit"):
                fx.build()
        finally:
            fx.close()


class SwingRawAudit(PointRawPinControlMixin, RawAuditCase):
    """Issue #230: the output-swing summary is audited against hash-pinned
    coarse/fine DC transfer curves and rendered netlists with the SAME
    measurement the bench runs (sim/output-swing/swing_post.py)."""

    RECORD = "output-swing"
    POINT = "mos_tt_27C_1.20V"
    KEEP_AUDIT = "keep_swing_audit"
    RAW_KEY = "swing_raw"
    RAW_NOUN = "swing"
    MISSING_PHRASE = "curves/netlists"
    DEFINITION_CHECK = "swing_raw_audit"

    def recompute(self, pid=None):
        """The shared measurement, in-process, from the pinned artifacts."""
        pid = pid or self.POINT
        entry = self.raw()["files"][pid]
        cvid, (cvout,) = swing_post.parse_wrdata(
            (self.fx.root / entry["coarse_csv"]["path"]).read_text(encoding="utf-8"),
            swing_post.COARSE_VECTORS)
        fvid, (fvout, fivdd) = swing_post.parse_wrdata(
            (self.fx.root / entry["fine_csv"]["path"]).read_text(encoding="utf-8"),
            swing_post.FINE_VECTORS)
        rc = swing_post.rendered_config(
            (self.fx.root / entry["fine_netlist"]["path"]).read_text(encoding="utf-8"))
        coarse = swing_post.coarse_measure(cvid, cvout, rc["vcm_v"])
        fine = swing_post.fine_measure(
            fvid, fvout, fivdd, rc["vdd_v"], rc["vcm_v"],
            float(swing_post.serialize(coarse["clip_high"])),
            float(swing_post.serialize(coarse["clip_low"])),
            coarse["plateau_ok"], float(swing_post.serialize(coarse["vos"])),
            float("nan"), float("nan"), float("nan"),
            float(swing_post.CONFIG["criterion_frac"]))
        return coarse, fine, rc

    def recomputed_cells(self, coarse, fine) -> dict:
        return {
            "op_pass": str(fine["op_pass"]),
            "vout_max_track_v": swing_post.serialize(fine["vout_max_track"]),
            "vout_min_track_v": swing_post.serialize(fine["vout_min_track"]),
            "headroom_hi_v": swing_post.serialize(fine["headroom_hi"]),
            "headroom_lo_v": swing_post.serialize(fine["headroom_lo"]),
            "swing_span_v": swing_post.serialize(fine["span"]),
            "vout_clip_high_v": swing_post.serialize(coarse["clip_high"]),
            "vout_clip_low_v": swing_post.serialize(coarse["clip_low"]),
            "vos_crossing_v": swing_post.serialize(fine["vos_crossing"]),
            "peak_inc_gain_v_v": swing_post.serialize(fine["g_pk"]),
            "ivdd_center_a": swing_post.serialize(fine["ivdd_center"]),
        }

    # --- committed evidence -------------------------------------------------

    def test_committed_population_rederives_offline(self):
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        raw = content["sources"][self.RECORD]["swing_raw"]
        self.assertEqual((raw["status"], raw["points"]), ("verified", 45))
        self.assertEqual(content["sources"][self.RECORD]["definition_checks"], ["swing_raw_audit"])
        self.assertEqual(content["sources"][self.RECORD]["valid_points"], 45)

    def test_report_exposes_audit_rule_and_status(self):
        content = self.fx.build()
        self.assertIn("Output-swing raw-evidence audit", content["swing_audit_rule"])
        md = generate.render_markdown(generate.make_report(content, "20260101-000000-abcd", self.fx.root))
        self.assertIn("pinned coarse/fine curve+netlist sets", md)
        self.assertIn("swing_post.py", md)

    def test_every_committed_cell_is_the_shared_serialization(self):
        for pid in sorted(self.raw()["files"]):
            coarse, fine, _ = self.recompute(pid)
            row = next(r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]
                       if r["point_id"] == pid)
            for field, expect in self.recomputed_cells(coarse, fine).items():
                self.assertEqual(row[field], expect, (pid, field))

    def test_netlist_vdd_and_vcm_cells_follow_the_netlists(self):
        coarse, fine, rc = self.recompute()
        row = next(r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]
                   if r["point_id"] == self.POINT)
        # cells carry the runner's literal supply/common-mode strings ("1.20",
        # "0.6"); the audit compares them numerically to the netlist values
        self.assertEqual(Decimal(row["vdd_v"]), Decimal(swing_post.serialize(rc["vdd_v"])))
        self.assertEqual(Decimal(row["vcm_v"]), Decimal(swing_post.serialize(rc["vcm_v"])))

    # --- coherent summary tampering ----------------------------------------

    def test_coordinated_bounds_headroom_and_span_edit_fails(self):
        # max_track, headroom_hi and span moved together (all algebraic
        # identities preserved): the raw curve still disagrees on all three.
        vdd = float(self.cell("vdd_v"))
        old_max = float(self.cell("vout_max_track_v"))
        old_min = float(self.cell("vout_min_track_v"))
        new_max = old_max * 1.01
        self.fx.set_cell(self.RECORD, self.POINT, "vout_max_track_v", swing_post.serialize(new_max))
        self.fx.set_cell(self.RECORD, self.POINT, "headroom_hi_v", swing_post.serialize(vdd - new_max))
        self.fx.set_cell(self.RECORD, self.POINT, "swing_span_v", swing_post.serialize(new_max - old_min))
        errors = self.definition_error()
        for field in ("vout_max_track_v", "headroom_hi_v", "swing_span_v"):
            self.assertTrue(any(field in e and "recomputed from the pinned raw curves" in e for e in errors), (field, errors))
        self.assertTrue(any(self.entry("fine_csv")["path"] in e for e in errors), errors)

    def test_one_digit_beyond_serialization_fails(self):
        for field in ("vout_clip_high_v", "vout_clip_low_v", "vos_crossing_v",
                      "peak_inc_gain_v_v", "ivdd_center_a"):
            with self.subTest(field=field):
                self.fresh()
                cell = self.cell(field)
                bumped = format(float(cell) * 1.00001 + (1e-12 if float(cell) == 0 else 0), ".9g")
                self.fx.set_cell(self.RECORD, self.POINT, field, bumped)
                self.assert_error(f"point {self.POINT} fails definition check swing_raw_audit", field)

    def test_vcm_cell_disagreeing_with_netlist_fails(self):
        self.fx.set_cell(self.RECORD, self.POINT, "vcm_v", "0.61")
        errors = self.definition_error()
        self.assertTrue(any("vcm_v" in e and self.entry("fine_netlist")["path"] in e for e in errors), errors)

    def test_summary_claiming_pass_on_a_degenerate_curve_fails(self):
        # peak incremental gain squashed below the 10 V/V floor by rescaling
        # the output deviation: the recomputed measurement cannot pass, so the
        # summary's op_pass=1 cannot stand
        vcm = float(self.cell("vcm_v"))
        self.edit_raw("fine_csv", lambda ls: [
            " ".join([p[0], repr(vcm + (float(p[1]) - vcm) * 0.02)] + p[2:])
            for p in (l.split() for l in ls)])
        errors = self.definition_error()
        self.assertTrue(any("fine analysis failed: peak_gain_implausible" in e for e in errors), errors)

    # --- curve evidence -------------------------------------------------------

    def test_changed_curve_repinned_disagrees_with_summary(self):
        # compress the curve's output deviation around Vcm by 2%: the crossing
        # (and so the fine window centring) is preserved, the tracking bounds
        # are not -- a pure definition-check disagreement
        vcm = float(self.cell("vcm_v"))
        self.edit_raw("fine_csv", lambda ls: [
            " ".join([ls_part for ls_part in [p[0], repr(vcm + (float(p[1]) - vcm) * 0.98)] + p[2:]])
            for p in (l.split() for l in ls)])
        self.definition_error()

    def test_non_finite_and_malformed_samples_fail(self):
        for bad in (" 1.0e-02 nan 1.0e-02 -1.8e-05 ", " 1.0e-02 inf 1.0e-02 -1.8e-05 ",
                    " nan 0.5 nan -1.8e-05 ", " 1.0e-02 0.5 1.0e-02 -Infinity ",
                    " 1.0e-02 abc 1.0e-02 -1.8e-05 ", " 1.0e-02 0.5 "):
            with self.subTest(bad=bad):
                self.fresh()
                self.edit_raw("fine_csv", lambda ls, bad=bad: ls[:5] + [bad] + ls[5:])
                errors = self.assert_error(f"point {self.POINT}: invalid swing curve")
                self.assertTrue(any(f"{self.entry('fine_csv')['path']}:6" in e for e in errors), errors)

    def test_scale_order_violations_fail(self):
        def swap(lines):
            return lines[:5] + [lines[6], lines[5]] + lines[7:]
        self.edit_raw("fine_csv", swap)
        self.assert_error(f"point {self.POINT}: invalid swing curve", "does not increase")

    def test_duplicate_scale_stamp_fails(self):
        self.edit_raw("fine_csv", lambda ls: ls[:5] + [ls[5]] + ls[5:])
        self.assert_error(f"point {self.POINT}: invalid swing curve", "does not increase")

    def test_truncated_curve_fails_on_the_declared_sample_count(self):
        self.edit_raw("fine_csv", lambda ls: ls[:-1])
        errors = self.assert_error("measurement configuration mismatch",
                                   "fine curve has 5000 samples; the rendered sweep declares 5001")
        self.assertTrue(any(self.entry("fine_netlist")["path"] in e for e in errors), errors)

    def test_mismatched_wrdata_scales_fail(self):
        def bad_scale(lines):
            out = []
            for i, line in enumerate(lines):
                if i == 5:
                    parts = line.split()
                    parts[2] = "9.9"
                    line = " ".join(parts)
                out.append(line)
            return out
        self.edit_raw("fine_csv", bad_scale)
        self.assert_error(f"point {self.POINT}: invalid swing curve", "mismatched wrdata scales")

    def test_no_coarse_crossing_fails(self):
        self.edit_raw("coarse_csv", lambda ls: [f"{l.split()[0]} 0.2" for l in ls])
        self.assert_error(f"point {self.POINT}: coarse curve {self.entry('coarse_csv')['path']} "
                          "has 0 Vout=Vcm crossings (expected exactly 1)")

    def test_multiple_coarse_crossings_fail(self):
        import math as _math

        def wiggle(lines):
            out = [lines[0]]
            for line in lines[1:]:
                vid = float(line.split()[0])
                out.append(f"{vid!r} {0.6 + 0.001 * _math.sin(2 * _math.pi * vid / 0.002)!r}")
            return out
        self.edit_raw("coarse_csv", wiggle)
        self.assert_error(f"point {self.POINT}: coarse curve {self.entry('coarse_csv')['path']}",
                          "Vout=Vcm crossings (expected exactly 1)")

    def test_fine_window_truncating_the_region_fails(self):
        # a synthetic fine curve whose 0.5x-peak region still qualifies at both
        # window edges: the audit must refuse it as a window artifact
        coarse, _, rc = self.recompute()
        vos9 = float(swing_post.serialize(coarse["vos"]))
        half = float(swing_post.CONFIG["fine_halfspan_v"])
        step = float(swing_post.CONFIG["fine_step_v"])
        vcm = rc["vcm_v"]

        def synth(lines):
            out = []
            n = swing_post.sweep_count(vos9 - half, vos9 + half, step)
            for k in range(n):
                vid = vos9 - half + k * step
                vout = vcm + 0.35 * math.tanh((vid - vos9) / 0.03)
                out.append(f"{vid!r} {vout!r} {vid!r} -1.0e-04")
            return out
        self.edit_raw("fine_csv", synth)
        errors = self.definition_error()
        self.assertTrue(any("fine analysis failed: linear_region_touches_window_edge" in e for e in errors), errors)

    # --- measurement configuration -------------------------------------------

    def test_selection_config_mismatch_is_refused(self):
        for field, value in (("coarse_step_v", "490e-6"), ("fine_halfspan_v", "20e-3"),
                             ("fine_step_v", "5e-6"), ("criterion_frac", "0.6"),
                             ("coarse_start_v", "-0.2")):
            with self.subTest(field=field):
                self.fresh()
                self.raw()["config"][field] = value
                self.fx.save_selection()
                with self.assertRaises(generate.SelectionError):
                    self.fx.build()

    def test_missing_config_is_refused(self):
        del self.raw()["config"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_netlist_window_disagreeing_with_config_is_refused(self):
        self.edit_raw("coarse_netlist", lambda ls: [l.replace("500e-6", "490e-6") for l in ls])
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch",
                          "step 0.00049 (netlist) != -0.1..0.1 step 0.0005 (pinned configuration)")

    def test_netlist_common_mode_not_mid_rail_is_refused(self):
        self.edit_raw("fine_netlist", lambda ls: [l.replace("Vcm cm 0 dc 0.6", "Vcm cm 0 dc 0.7") for l in ls])
        self.assert_error(f"point {self.POINT}: invalid rendered netlist", "is not VDD/2")

    def test_netlist_for_another_corner_section_is_refused(self):
        self.edit_raw("coarse_netlist", lambda ls: [l.replace('cornerMOSlv.lib" mos_tt', 'cornerMOSlv.lib" mos_ff') for l in ls])
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch",
                          "cornerMOSlv.lib section mos_ff (netlist) != mos_tt (point id)")

    def test_netlist_writing_another_curve_is_refused(self):
        self.edit_raw("fine_netlist", lambda ls: [l.replace(f"{self.POINT}_fine.csv", "mos_tt_27C_1.32V_fine.csv") for l in ls])
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch", "wrdata target")

    def test_netlist_window_off_the_coarse_crossing_is_refused(self):
        # shift the fine window +100 uV, dc line and Sweep comment together:
        # self-consistent, correctly sized, but no longer centred on the
        # coarse crossing recomputed from the pinned coarse curve
        import re as _re

        def shift(lines):
            out = []
            for line in lines:
                if line.startswith("dc Vid "):
                    _, _, s, e, st = line.split()
                    out.append(f"dc Vid {float(s) + 1e-4!r} {float(e) + 1e-4!r} {st}")
                elif line.startswith("* Sweep: Vid from "):
                    m = _re.match(r"\* Sweep: Vid from (\S+) V to (\S+) V, step (\S+) V$", line)
                    out.append(f"* Sweep: Vid from {float(m.group(1)) + 1e-4!r} V to "
                               f"{float(m.group(2)) + 1e-4!r} V, step {m.group(3)} V")
                else:
                    out.append(line)
            return out
        self.edit_raw("fine_netlist", shift)
        self.assert_error(f"point {self.POINT}: measurement configuration mismatch",
                          "is not the coarse crossing")

    def test_malformed_netlist_fails(self):
        self.edit_raw("coarse_netlist", lambda ls: [l for l in ls if not l.startswith("Vdd")])
        self.assert_error(f"point {self.POINT}: invalid rendered netlist")

    # --- the shared module and runner ------------------------------------------

    def test_runner_uses_the_shared_module_and_its_constants(self):
        runner = (REPO / "sim" / "output-swing" / "run_swing_sweep.sh").read_text(encoding="utf-8")
        self.assertIn("swing_post.py", runner)
        self.assertNotIn("def seg_gain(", runner)
        self.assertNotIn("def fail(", runner)
        for var, key in (("COARSE_START", "coarse_start_v"), ("COARSE_STOP", "coarse_stop_v"),
                         ("COARSE_STEP", "coarse_step_v"), ("FINE_HALFSPAN", "fine_halfspan_v"),
                         ("FINE_STEP", "fine_step_v"), ("CRITERION_FRAC", "criterion_frac")):
            self.assertIn(f'{var}="{swing_post.CONFIG[key]}"', runner)

    def test_cli_matches_the_committed_summary(self):
        row = next(r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]
                   if r["point_id"] == self.POINT)
        coarse_csv = REPO / self.entry("coarse_csv")["path"]
        fine_csv = REPO / self.entry("fine_csv")["path"]
        out = subprocess.run(
            [sys.executable, "-I", str(REPO / "sim" / "output-swing" / "swing_post.py"),
             "coarse", str(coarse_csv), row["vcm_v"]], capture_output=True, text=True, check=True).stdout.split()
        vos, n_cross, clip_high, clip_low, plateau = out
        self.assertEqual(n_cross, "1")
        self.assertEqual([clip_high, clip_low], [row["vout_clip_high_v"], row["vout_clip_low_v"]])
        fields = subprocess.run(
            [sys.executable, "-I", str(REPO / "sim" / "output-swing" / "swing_post.py"),
             "fine", str(fine_csv), row["vdd_v"], row["vcm_v"], clip_high, clip_low, plateau, vos,
             row["av0_ac_record_db"], row["ivdd_ac_record_a"], row["vos_offset_record_v"], "0.5"],
            capture_output=True, text=True, check=True).stdout.split()
        expected_cols = ("op_pass", "vout_max_track_v", "vout_min_track_v", "headroom_hi_v",
                         "headroom_lo_v", "swing_span_v", "vout_clip_high_v", "vout_clip_low_v",
                         "vos_crossing_v", "vos_offset_record_v", "vos_delta_v", "peak_inc_gain_v_v",
                         "av0_ac_record_db", "av0_ratio", "ivdd_center_a", "ivdd_ac_record_a", "ivdd_ratio")
        self.assertEqual(fields, [row[c] for c in expected_cols])

    def test_cli_reports_a_bad_curve_with_no_stdout(self):
        bad = self.fx.root / "bad_coarse.csv"
        bad.write_text(" 0 nan \n 1e-3 0.5 \n", encoding="utf-8")
        res = subprocess.run([sys.executable, "-I", str(REPO / "sim" / "output-swing" / "swing_post.py"),
                              "coarse", str(bad), "0.6"], capture_output=True, text=True)
        self.assertEqual((res.returncode, res.stdout), (1, ""))
        self.assertIn("non-finite", res.stderr)


class SchematicOpenLoopAndVersionPolicy(RawAuditCase):
    """Issue #500: schematic open-loop OP evidence derives directly from pinned
    AC/OP requests, bench, envelopes and matching DUT across all 45 corners
    (without floating-inn CSV), and simulator version policy reuses
    sim/tools/env_identity.py across both admission paths with run-internal
    agreement checks."""

    RECORD = "open-loop-ac"
    POINT = "mos_tt_27C_1.20V"
    KEEP_AUDIT = "keep_klt_audit"
    RAW_KEY = "klt_raw"

    SCHEMATIC_AC_SIM = "sim/open-loop-ac/klt/records/20261016-161057-8caa272.ac.sim.json"
    SCHEMATIC_OP_SIM = "sim/open-loop-ac/klt/records/20261016-161057-8caa272.op.sim.json"
    SCHEMATIC_AC_REQ = "sim/open-loop-ac/klt/openloop_ac.request.json"
    SCHEMATIC_OP_REQ = "sim/open-loop-ac/klt/openloop_op.request.json"
    SCHEMATIC_BODY = "sim/open-loop-ac/klt/tb_openloop_ac.body.spice"

    def install_schematic_run(self, rid: str = "20261125-000000-abcdef0", engine_version: str = "47",
                              include_measurement: bool = False, dc_continuity: str | None = None,
                              dut_transform=None) -> dict:
        """Stage a schematic-OP open-loop record in self.fx.root with no
        dependency on open-loop-ac-floating-inn unless dc_continuity is set."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "summarize_klt", REPO / "sim" / "open-loop-ac" / "summarize_klt.py"
        )
        summarize_klt = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(summarize_klt)

        snap_rel = f"sim/open-loop-ac/netlist-snapshots/{rid}/opamp_core.spice"
        cdir_rel = f"sim/open-loop-ac/corners/{rid}"
        csv_rel = f"sim/open-loop-ac/records/{rid}.csv"
        md_rel = f"sim/open-loop-ac/records/{rid}.md"

        snap = self.fx.root / snap_rel
        snap.parent.mkdir(parents=True, exist_ok=True)
        dut_text = (self.fx.root / self.fx.selection["design_netlist"]).read_text(encoding="utf-8")
        if dut_transform is not None:
            dut_text = dut_transform(dut_text)
            (self.fx.root / self.fx.selection["design_netlist"]).write_text(dut_text, encoding="utf-8")
        snap.write_text(dut_text, encoding="utf-8")

        cdir = self.fx.root / cdir_rel
        cdir.mkdir(parents=True, exist_ok=True)
        for src_rel, dst_name in (
            (self.SCHEMATIC_AC_REQ, "openloop_ac.request.json"),
            (self.SCHEMATIC_OP_REQ, "openloop_op.request.json"),
        ):
            req = json.loads((REPO / src_rel).read_text(encoding="utf-8"))
            req.pop("_comment", None)
            req["netlist"] = "tb_openloop_ac.body.spice"
            (cdir / dst_name).write_text(json.dumps(req, indent=2) + "\n", encoding="utf-8")

        body_rel = f"{cdir_rel}/tb_openloop_ac.body.spice"
        body_text = (REPO / self.SCHEMATIC_BODY).read_text(encoding="utf-8").replace(
            ".include ../../../design/netlist/opamp_core.spice",
            f'.include "../../netlist-snapshots/{rid}/opamp_core.spice"',
        )
        body_path = self.fx.root / body_rel
        body_path.write_text(body_text, encoding="utf-8")
        body_sha = generate.sha256_file(body_path).split(":", 1)[1]
        snap_sha = generate.sha256_file(snap).split(":", 1)[1]

        for kind, src_rel in (("ac", self.SCHEMATIC_AC_SIM), ("op", self.SCHEMATIC_OP_SIM)):
            env = json.loads((REPO / src_rel).read_text(encoding="utf-8"))
            env["netlist"] = {"path": body_rel, "scope": "repo"}
            env["environment"]["engine_version"] = str(engine_version)
            env["environment"]["remote"]["worker_environment"]["simulator"]["version_banner"] = (
                f"******\n** ngspice-{engine_version} : Circuit level simulation program\n******\n"
            )
            env["environment"]["netlist_sha256"] = body_sha
            env["environment"]["netlist_closure"] = [
                {"path": body_rel, "scope": "repo", "sha256": body_sha},
                {"path": snap_rel, "scope": "repo", "sha256": snap_sha},
            ]
            (cdir / f"{kind}.envelope.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")

        out_csv = self.fx.root / csv_rel
        out_md = self.fx.root / md_rel
        summarize_klt.main(rid, str(cdir), None, str(out_csv), str(out_md))

        inv_path = self.fx.root / self.fx.selection["inventory"]
        inv_path.write_text(
            inv_path.read_text(encoding="utf-8").replace(
                "sim/open-loop-ac/records/20261015-103057-895d555.csv", csv_rel
            ),
            encoding="utf-8",
        )

        files = {
            "ac": {"path": f"{cdir_rel}/ac.envelope.json", "sha256": generate.sha256_file(cdir / "ac.envelope.json")},
            "op": {"path": f"{cdir_rel}/op.envelope.json", "sha256": generate.sha256_file(cdir / "op.envelope.json")},
            "ac_request": {"path": f"{cdir_rel}/openloop_ac.request.json", "sha256": generate.sha256_file(cdir / "openloop_ac.request.json")},
            "op_request": {"path": f"{cdir_rel}/openloop_op.request.json", "sha256": generate.sha256_file(cdir / "openloop_op.request.json")},
            "bench_body": {"path": body_rel, "sha256": generate.sha256_file(body_path)},
        }
        if include_measurement:
            mpath = cdir / "measurement.json"
            files["measurement"] = {"path": f"{cdir_rel}/measurement.json", "sha256": generate.sha256_file(mpath)}
        klt_raw: dict = {"files": files}
        if dc_continuity is not None:
            klt_raw["dc_continuity"] = dc_continuity

        rec = self.fx.selection["records"][self.RECORD]
        rec.update({
            "csv": csv_rel,
            "csv_sha256": generate.sha256_file(out_csv),
            "md": md_rel,
            "md_sha256": generate.sha256_file(out_md),
            "netlist_snapshot": snap_rel,
            "klt_raw": klt_raw,
        })
        self.fx.save_selection()
        return {"rid": rid, "cdir": cdir, "csv": out_csv, "md": out_md, "snap": snap}

    def edit_klt_json(self, kind: str, mutate, repin: bool = True) -> None:
        pin = self.raw()["files"][kind]
        path = self.fx.root / pin["path"]
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")
        if repin:
            pin["sha256"] = generate.sha256_file(path)
            self.fx.save_selection()

    def corner(self, doc: dict, pid: str | None = None) -> dict:
        pid = pid or self.POINT
        for c in doc["corners"]:
            if f"{c['process']}_{int(c['temperature_c'])}C_{float(c['supply_v']['vdd']):.2f}V" == pid:
                return c
        raise KeyError(pid)

    def set_value(self, doc: dict, name: str, value, status: str | None = None, pid: str | None = None) -> None:
        for m in self.corner(doc, pid)["measurements"]:
            if m["name"] == name:
                m["value"] = value
                if status is not None:
                    m["status"] = status

    def make_sidecar(self, record_id: str, ngspice: str) -> dict:
        sys.path.insert(0, str(REPO / "sim" / "tools"))
        import env_identity
        import test_env_identity

        with tempfile.TemporaryDirectory() as pdk_tmp:
            test_env_identity.make_install(Path(pdk_tmp))
            pin = json.loads((self.fx.root / self.fx.selection["pdk_pin"]).read_text(encoding="utf-8"))
            return env_identity.capture(Path(pdk_tmp), "ihp-sg13g2", pin, record_id, ngspice)

    def attach_sidecar(self, key: str, sidecar: dict) -> None:
        rec = self.fx.selection["records"][key]
        side_rel = str(Path(rec["csv"]).with_suffix(".env.json"))
        path = self.fx.root / side_rel
        path.write_text(json.dumps(sidecar), encoding="utf-8")
        rec["env_sidecar"] = side_rel
        rec["env_sidecar_sha256"] = generate.sha256_file(path)
        self.fx.save_selection()

    def test_schematic_op_verifies_46_and_47_without_floating_inn_csv(self):
        for ver in ("46", "47"):
            with self.subTest(ver=ver):
                self.fresh()
                self.install_schematic_run(engine_version=ver)
                # Delete the floating-inn CSV bytes unless cmrr-mismatch reads them:
                # verify open-loop-ac itself has zero dependency on floating-inn by
                # loading open-loop-ac directly when floating-inn is absent from records.
                from records import load_record
                pdk = json.loads((self.fx.root / self.fx.selection["pdk_pin"]).read_text(encoding="utf-8"))
                env = {
                    "ngspice": pdk["osdi_toolchain"]["ngspice_actually_used"],
                    "pdk": f"{pdk['source']} {pdk['release_tag']}",
                    "pin": pdk,
                    "netlist_normalized_sha256": generate.normalized_netlist_hash(
                        self.fx.root / self.fx.selection["design_netlist"]
                    ),
                }
                only_openloop = {self.RECORD: self.fx.selection["records"][self.RECORD]}
                state = load_record(
                    self.fx.root, self.RECORD, only_openloop[self.RECORD],
                    self.fx.selection["grids"]["pvt45"], env, only_openloop
                )
                self.assertEqual(state["errors"], [])
                self.assertEqual(state["valid_ids"].__len__(), 45)
                self.assertEqual(state["source"]["ngspice"], f"ngspice-{ver}")

                # Full report also builds cleanly while cmrr-mismatch keeps its av0_join provenance.
                content = self.fx.build()
                self.assertEqual(self.errors(content), [])
                self.assertEqual(content["sources"][self.RECORD]["ngspice"], f"ngspice-{ver}")
                self.assertEqual(content["sources"]["cmrr-mismatch"]["samples"]["av0_join"], "open-loop-ac-floating-inn")
                rows = rows_by_id(content)
                for rid in ("dc_gain", "gbw", "phase_margin", "quiescent_current"):
                    self.assertEqual(rows[rid]["verdict"], "PASS", rid)

    def test_markdown_admission_path_accepts_46_and_47_and_rejects_below_floor_and_floor_absent_mismatch(self):
        rec = self.fx.selection["records"]["input-noise"]
        md = self.fx.root / rec["md"]
        orig = md.read_text(encoding="utf-8")

        for ver in ("ngspice-46", "ngspice-47"):
            md.write_text(orig.replace("ngspice-46", ver), encoding="utf-8")
            rec["md_sha256"] = generate.sha256_file(md)
            self.fx.save_selection()
            content = self.fx.build()
            self.assertEqual(self.errors(content), [])
            self.assertEqual(content["sources"]["input-noise"]["ngspice"], ver)

        md.write_text(orig.replace("ngspice-46", "ngspice-45"), encoding="utf-8")
        rec["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()
        self.assert_error("input-noise", "ngspice-45", "floor ngspice-46")

        # Floor absent -> exact match against ngspice_actually_used (ngspice-46).
        pdk_path = self.fx.root / self.fx.selection["pdk_pin"]
        pdk = json.loads(pdk_path.read_text(encoding="utf-8"))
        del pdk["osdi_toolchain"]["ngspice_min_major"]
        pdk_path.write_text(json.dumps(pdk), encoding="utf-8")
        md.write_text(orig.replace("ngspice-46", "ngspice-47"), encoding="utf-8")
        rec["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()
        self.assert_error("input-noise", "ngspice-47", "expected 'ngspice-46'")

    def test_conflicting_versions_within_one_run_are_rejected(self):
        # (a) summary md (46) vs sidecar (47) on a harness record
        rec = self.fx.selection["records"]["input-noise"]
        rid = Path(rec["csv"]).stem
        self.attach_sidecar("input-noise", self.make_sidecar(rid, "ngspice-47"))
        self.assert_error("input-noise", "ngspice-46", "ngspice-47")

        # (b) summary md (46) vs klt envelopes (47)
        self.fresh()
        info = self.install_schematic_run(engine_version="47")
        info["md"].write_text(
            info["md"].read_text(encoding="utf-8").replace("ngspice-47", "ngspice-46"), encoding="utf-8"
        )
        self.fx.selection["records"][self.RECORD]["md_sha256"] = generate.sha256_file(info["md"])
        self.fx.save_selection()
        self.assert_error("ngspice-46", "ngspice-47")

        # (c) sidecar (46) vs klt envelopes (47) when md omits version
        self.fresh()
        info = self.install_schematic_run(engine_version="47")
        info["md"].write_text(
            info["md"].read_text(encoding="utf-8").replace("ngspice-47", "batch-fleet"), encoding="utf-8"
        )
        self.fx.selection["records"][self.RECORD]["md_sha256"] = generate.sha256_file(info["md"])
        self.attach_sidecar(self.RECORD, self.make_sidecar(info["rid"], "ngspice-46"))
        self.assert_error("sidecar", "ngspice-46", "ngspice-47")

        # (d) envelope engine_version (47) vs worker banner (ngspice-46)
        self.fresh()
        self.install_schematic_run(engine_version="47")
        self.edit_klt_json(
            "op",
            lambda d: d["environment"]["remote"]["worker_environment"]["simulator"].update(
                version_banner="******\n** ngspice-46 : Circuit level simulation program\n******\n"
            ),
        )
        self.assert_error("worker banner does not name ngspice-47")

        # (e) sidecar + md + envelopes all agreeing on 47 passes
        self.fresh()
        info = self.install_schematic_run(engine_version="47")
        self.attach_sidecar(self.RECORD, self.make_sidecar(info["rid"], "ngspice-47"))
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        self.assertEqual(content["sources"][self.RECORD]["ngspice"], "ngspice-47")
        self.assertEqual(content["sources"][self.RECORD]["pdk_provenance"]["status"], "verified")

    def test_slew_klt_and_klt_raw_envelopes_must_agree_on_version(self):
        """Issue #511 merge control: a record pinning BOTH slew_klt (envelope 46)
        and klt_raw (envelopes 47) whose summary md names no version must be
        rejected -- the klt_raw block may not silently overwrite the version the
        slew block established in src["ngspice"]."""
        info = self.install_schematic_run(engine_version="47")
        info["md"].write_text(
            info["md"].read_text(encoding="utf-8").replace("ngspice-47", "batch-fleet"), encoding="utf-8"
        )
        rec = self.fx.selection["records"][self.RECORD]
        rec["md_sha256"] = generate.sha256_file(info["md"])
        pins = {}
        for kind, rel in SlewKltAudit.FILES.items():
            dst = self.fx.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)
            pins[kind] = {"path": rel, "sha256": generate.sha256_file(dst)}
        rec["slew_klt"] = {"files": pins}
        rec["definition_checks"] = [*rec.get("definition_checks", []), "slew_klt_audit"]
        self.fx.save_selection()
        errors = self.assert_error("but the pinned envelopes ran ngspice-47")
        self.assertTrue(any("names ngspice-46" in e for e in errors), errors)

    def test_agreeing_sub_floor_summary_and_envelopes_are_rejected_exactly_once(self):
        """Issue #523: the summary names ngspice-45 and the klt_raw envelopes
        agree (45, below the floor). The summary site admits-as-it-sets; the
        envelope carrier must not admit again on agreement, or the same policy
        error reaches the signoff report twice."""
        self.install_schematic_run(engine_version="45")
        self.assert_error("ran on ngspice-45", "floor ngspice-46")
        content = self.fx.build()
        hit_rows = 0
        for row in content["rows"]:
            rejected = [e for e in row["errors"] if "rejected by sim/pdk.json" in e]
            self.assertLessEqual(len(rejected), 1, (row.get("id"), rejected))
            hit_rows += bool(rejected)
        self.assertGreater(hit_rows, 0)
        self.assertEqual([e for e in content["errors"] if "rejected by sim/pdk.json" in e], [])

    def test_port_only_op_without_dc_continuity_is_rejected(self):
        del self.raw()["dc_continuity"]
        self.fx.save_selection()
        self.assert_error("vd1_dc_v")

    def test_bad_internal_node_op_is_rejected(self):
        for node, frac_name, bad_v in (
            ("vd1_dc_v", "op_vd1_rail_frac", 0.01),
            ("vd2_dc_v", "op_vd2_rail_frac", 1.19),
            ("vtail_dc_v", "op_vtail_rail_frac", 0.005),
        ):
            with self.subTest(node=node):
                self.fresh()
                self.install_schematic_run(engine_version="47")
                self.fx.set_cell(self.RECORD, self.POINT, node, f"{bad_v:.6g}")

                def rail_internal(d, n=node, fn=frac_name, v=bad_v):
                    self.set_value(d, n, v)
                    self.set_value(d, fn, v / 1.2, status="fail")
                    self.corner(d)["status"] = "fail"
                    d.update(status="fail", passed=44, failed=1)

                self.edit_klt_json("op", rail_internal)
                errors = self.assert_error(f"point {self.POINT} fails definition check open_loop_klt_audit")
                self.assertTrue(any("operating point" in e for e in errors), errors)

    def test_tampered_internal_node_cell_or_fraction_is_rejected(self):
        self.install_schematic_run(engine_version="47")
        self.fx.set_cell(self.RECORD, self.POINT, "vibias_dc_v", "0.5")
        self.assert_error(f"point {self.POINT} fails definition check open_loop_klt_audit", "vibias_dc_v")

        self.fresh()
        self.install_schematic_run(engine_version="47")
        self.edit_klt_json("op", lambda d: self.set_value(d, "op_vd1_rail_frac", 0.5))
        self.assert_error("op_vd1_rail_frac")

    def test_osdi_mismatch_between_envelopes_is_rejected(self):
        self.install_schematic_run(engine_version="47")
        self.edit_klt_json("op", lambda d: d["environment"]["osdi_preload"][0].update(sha256="0" * 64))
        self.assert_error("OSDI")

        # Runner-resolved OSDI preload (klt >= 0.9 batch schema) and engine_build banner:
        self.fresh()
        self.install_schematic_run(engine_version="47")

        def to_runner_osdi(d):
            orig = d["environment"].pop("osdi_preload")
            d["environment"]["osdi_preload_runner_resolved"] = [
                {"entry": f"$PDK_ROOT/ihp-sg13g2/libs.tech/ngspice/osdi/{x['name']}", "index": i, "reason": "env_var", "sha256": x["sha256"]}
                for i, x in enumerate(orig)
            ]
            d["environment"]["engine_build"] = {"version_banner": "** ngspice-47 : Circuit level simulation program"}

        self.edit_klt_json("ac", to_runner_osdi)
        self.edit_klt_json("op", to_runner_osdi)
        self.assertEqual(self.errors(self.fx.build()), [])

        self.edit_klt_json("op", lambda d: d["environment"]["engine_build"].update(version_banner="** ngspice-46 : mismatch"))
        self.assert_error("engine_build banner does not name ngspice-47")

    def test_changed_design_requires_new_run_and_rejects_stale_dut_or_stale_continuity(self):
        # 1. Changed design netlist with stale open-loop snapshot/envelopes -> rejected.
        self.install_schematic_run(engine_version="47")
        design = self.fx.root / self.fx.selection["design_netlist"]
        design.write_text(design.read_text(encoding="utf-8") + "\nRdummy vdd vss 1e9\n", encoding="utf-8")
        self.assert_error("open-loop-ac", "not the committed design netlist")

        # 2. Updated snapshot for changed design, but stale OP envelope closure -> rejected.
        self.fresh()
        info = self.install_schematic_run(engine_version="47")
        for p in (self.fx.root / self.fx.selection["design_netlist"], info["snap"]):
            p.write_text(p.read_text(encoding="utf-8") + "\nRdummy vdd vss 1e9\n", encoding="utf-8")
        self.assert_error("is not the selected netlist snapshot")

        # 3. Changed design with fresh schematic run for open-loop-ac, but dc_continuity
        #    pointing at an older circuit's record -> rejected.
        self.fresh()
        self.install_schematic_run(
            engine_version="47",
            dc_continuity="open-loop-ac-floating-inn",
            dut_transform=lambda t: t + "\nRdummy vdd vss 1e9\n",
        )
        self.assert_error("dc_continuity record open-loop-ac-floating-inn", "same circuit")

        # 4. Changed design with its own fresh schematic-OP run (no older dc_continuity):
        #    open-loop-ac derives its OP verdict and graded rows from the new run alone.
        self.fresh()
        self.install_schematic_run(
            engine_version="47",
            dut_transform=lambda t: t + "\nRdummy vdd vss 1e9\n",
        )
        from records import load_record
        pdk = json.loads((self.fx.root / self.fx.selection["pdk_pin"]).read_text(encoding="utf-8"))
        env = {
            "ngspice": pdk["osdi_toolchain"]["ngspice_actually_used"],
            "pdk": f"{pdk['source']} {pdk['release_tag']}",
            "pin": pdk,
            "netlist_normalized_sha256": generate.normalized_netlist_hash(
                self.fx.root / self.fx.selection["design_netlist"]
            ),
        }
        only_openloop = {self.RECORD: self.fx.selection["records"][self.RECORD]}
        state = load_record(
            self.fx.root, self.RECORD, only_openloop[self.RECORD],
            self.fx.selection["grids"]["pvt45"], env, only_openloop
        )
        self.assertEqual(state["errors"], [])
        self.assertEqual(len(state["valid_ids"]), 45)

    def test_two_configuration_continuity_comparison_is_preserved_at_10uv_and_10na(self):
        # Note: 20261016-161057-8caa272 ran on batch Linux x86_64 while
        # 20260910-221601-22feaba ran on macOS aarch64 (~0.5 mV cross-host solver
        # delta), so align the reference CSV's vout_dc_v / ivdd_total_a to the
        # schematic OP envelope first, then perturb by 5 uV / 11 uV and 5 nA / 11 nA.
        info = self.install_schematic_run(engine_version="47", dc_continuity="open-loop-ac-floating-inn")
        op_doc = json.loads((info["cdir"] / "op.envelope.json").read_text(encoding="utf-8"))
        op_by_pid = {
            f"{c['process']}_{int(c['temperature_c'])}C_{float(c['supply_v']['vdd']):.2f}V": {
                m["name"]: m["value"] for m in c["measurements"]
            }
            for c in op_doc["corners"]
        }
        header, rows = generate.read_csv_rows(self.fx.csv_path("open-loop-ac-floating-inn"))
        for r in rows:
            vals = op_by_pid[r["point_id"]]
            r["vout_dc_v"] = f"{vals['vout_dc_v']:.9g}"
            r["ivdd_total_a"] = f"{vals['ivdd_total_a']:.9g}"
        cpath = self.fx.csv_path("open-loop-ac-floating-inn")
        cpath.write_text(
            ",".join(header) + "\n" + "\n".join(",".join(r[c] for c in header) for r in rows) + "\n",
            encoding="utf-8",
        )
        self.fx.selection["records"]["open-loop-ac-floating-inn"]["csv_sha256"] = generate.sha256_file(cpath)
        self.fx.save_selection()
        self.assertEqual(self.errors(self.fx.build()), [])

        base_vout = op_by_pid[self.POINT]["vout_dc_v"]
        base_ivdd = op_by_pid[self.POINT]["ivdd_total_a"]
        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "vout_dc_v", f"{base_vout + 5e-6:.9g}")
        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "ivdd_total_a", f"{base_ivdd + 5e-9:.9g}")
        self.assertEqual(self.errors(self.fx.build()), [])

        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "vout_dc_v", f"{base_vout + 1.1e-5:.9g}")
        self.assert_error("Vout", "differs from the dc_continuity record")

        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "vout_dc_v", f"{base_vout:.9g}")
        self.fx.set_cell("open-loop-ac-floating-inn", self.POINT, "ivdd_total_a", f"{base_ivdd + 1.1e-8:.9g}")
        self.assert_error("total VDD current", "differs from the dc_continuity record")

    def test_genuine_spec_limit_miss_in_envelope_grades_row_fail_not_error(self):
        self.install_schematic_run(engine_version="47")
        self.fx.set_cell(self.RECORD, self.POINT, "av0_db", "35")

        def miss_av0(d):
            self.set_value(d, "av0_db", 35.0, status="fail")
            self.corner(d)["status"] = "fail"
            d.update(status="fail", passed=44, failed=1)

        self.edit_klt_json("ac", miss_av0)
        content = self.fx.build()
        self.assertEqual(self.errors(content), [])
        row = rows_by_id(content)["dc_gain"]
        self.assertEqual(row["verdict"], "FAIL")
        self.assertEqual(row["violating_points"], [self.POINT])


if __name__ == "__main__":
    unittest.main()

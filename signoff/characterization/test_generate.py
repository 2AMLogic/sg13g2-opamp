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
import shutil
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

import generate  # noqa: E402

sys.path.insert(0, str(HERE.parent.parent / "sim" / "cmrr-mismatch"))
import mc_samples  # noqa: E402

REPO = HERE.parent.parent
SELECTION = REPO / generate.SELECTION_REL

# Every ratified bound spec/target-spec.md section 2 binds today ([DR-2] and
# the CMRR row's [DR-4]); output swing carries three bounds in one row.
# The four ratified rows whose committed raw worst case misses the literal
# DR-0002 bound and only rounds onto it at the bound's written decimals
# (spec question 2AMLogic/sg13g2-opamp#101). Compared literally, they FAIL.
LITERAL_FAIL_IDS = ["dc_gain", "input_noise", "offset_systematic", "swing_span"]

# (record, binding point, column, raw cell exactly AT the ratified bound once
# scaled to the bound's unit) for each of the four rows above.
AT_BOUND_CELLS = [
    ("open-loop-ac", "mos_fs_125C_1.08V", "av0_db", "37.8"),           # >= 37.8 dB
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
            if "noise_raw" in rec:
                for entry in rec["noise_raw"]["files"].values():
                    files.update(pin["path"] for pin in entry.values())
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

    keep_cmrr_audit = False

    def detach_cmrr_population(self) -> None:
        """The CMRR audit joins Av0 from the open-loop record (issue #208), so a
        control that perturbs open-loop Av0 for ITS OWN purpose would trip the
        join. Those controls drop the CMRR raw-sample audit; CmrrMcStatistics
        (keep_cmrr_audit) tests the join itself."""
        rec = self.selection["records"]["cmrr-mismatch"]
        rec.pop("mc_samples", None)
        rec["definition_checks"] = [c for c in rec["definition_checks"] if c != "cmrr_mc_statistics"]
        self.save_selection()

    keep_noise_audit = False

    def detach_noise_population(self) -> None:
        """Controls that perturb the input-noise summary for THEIR OWN purpose
        (a bound comparison) drop the raw-noise audit (issue #213);
        NoiseRawAudit tests that audit itself."""
        rec = self.selection["records"]["input-noise"]
        rec.pop("noise_raw", None)
        rec["definition_checks"] = [c for c in rec.get("definition_checks", []) if c != "noise_raw_audit"]
        self.save_selection()

    def rewrite_csv(self, key: str, transform, repin: bool = True) -> None:
        if key == "open-loop-ac" and not self.keep_cmrr_audit:
            self.detach_cmrr_population()
        if key == "input-noise" and not self.keep_noise_audit:
            self.detach_noise_population()
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
        # Literal comparison: the committed evidence misses four ratified
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
        self.assertEqual(rows["psrr"]["measured_worst"]["point"], "mos_ff_125C_1.32V")
        self.assertEqual(rows["quiescent_current"]["measured_worst"]["point"], "mos_ss_-40C_1.32V")

    def test_literal_failures_are_graded_fail_and_disclosed(self):
        rows = rows_by_id(self.content)
        self.assertEqual(self.content["overall"]["fail_only_beyond_written_decimals"], LITERAL_FAIL_IDS)
        expected = {
            "dc_gain": ("37.7812", "mos_fs_125C_1.08V"),
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


class OffsetMcStatistics(unittest.TestCase):
    """Issue #199: the draws audit rejects fabricated statistics and broken
    draw populations, naming the point and offending field. The committed
    campaign is the positive control (CommittedEvidence); every control here
    perturbs exactly one thing against the otherwise-consistent fixture."""

    RECORD = "input-offset-mc"
    POINT = "mos_ss_mismatch_27C_1.20V"  # any ordinary mismatch point
    NEGCTRL = "mos_tt_negctrl_27C_1.20V"

    def setUp(self) -> None:
        self.fx = Fixture()

    def tearDown(self) -> None:
        self.fx.close()

    def all_errors(self, content: dict) -> list:
        # Record errors surface on every row that cites the record.
        out = list(content["errors"])
        for row in content["rows"]:
            out.extend(row["errors"])
        return out

    def assert_audit_error(self, *fragments: str) -> None:
        content = self.fx.build()
        errors = self.all_errors(content)
        self.assertEqual(content["overall"]["verdict"], "ERROR")
        self.assertTrue(errors, "expected the audit to report a problem")
        for fragment in fragments:
            self.assertTrue(any(fragment in e for e in errors), errors)

    def test_baseline_has_no_audit_errors(self):
        content = self.fx.build()
        self.assertEqual(self.all_errors(content), [])
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
                fx = Fixture()
                try:
                    fx.set_cell(self.RECORD, self.POINT, column, fabricated)
                    content = fx.build()
                    self.assertEqual(content["overall"]["verdict"], "ERROR")
                    self.assertTrue(
                        any(
                            f"point {self.POINT} fails definition check offset_mc_statistics: {column}" in e
                            for e in self.all_errors(content)
                        ),
                        self.all_errors(content),
                    )
                finally:
                    fx.close()

    def test_negative_spread_magnitude_is_rejected(self):
        for column in ("sigma_vos_v", "three_sigma_v", "vos_total_wc_det_plus_3sigma_v"):
            with self.subTest(field=column):
                fx = Fixture()
                try:
                    fx.set_cell(self.RECORD, self.POINT, column, "-0.026870239")
                    content = fx.build()
                    self.assertEqual(content["overall"]["verdict"], "ERROR")
                    self.assertTrue(
                        any(f"{column} -0.026870239 is negative" in e for e in self.all_errors(content)),
                        self.all_errors(content),
                    )
                finally:
                    fx.close()

    def test_drifted_draws_file_is_error_even_unrepinned(self):
        self.fx.set_draw_cell(self.RECORD, self.POINT, 5, "vos_v", "0.0099999999", repin=False)
        content = self.fx.build()
        self.assertEqual(content["overall"]["verdict"], "ERROR")
        self.assertTrue(
            any("does not match its selection pin" in e for e in self.all_errors(content)),
            self.all_errors(content),
        )

    def test_missing_draws_file_is_error(self):
        self.fx.draws_path(self.RECORD).unlink()
        self.assert_audit_error("missing draws population")

    def test_duplicate_draw_is_error(self):
        def duplicate_one(lines):
            target = next(l for l in lines if l.startswith(f"{self.POINT},") and l.split(",")[6] == "5")
            return lines + [target]

        self.fx.rewrite_draws(self.RECORD, duplicate_one)
        self.assert_audit_error("duplicate draw_index 5")

    def test_missing_draw_is_error_not_a_quiet_population_reduction(self):
        def drop_one(lines):
            return [l for l in lines if not (l.startswith(f"{self.POINT},") and l.split(",")[6] == "5")]

        self.fx.rewrite_draws(self.RECORD, drop_one)
        self.assert_audit_error("1 of 300 expected draws missing")

    def test_non_finite_pass_draw_is_error(self):
        self.fx.set_draw_cell(self.RECORD, self.POINT, 5, "vos_v", "nan")
        self.assert_audit_error("is not finite")

    def test_draw_seed_conflicting_with_the_campaign_is_error(self):
        self.fx.set_draw_cell(self.RECORD, self.POINT, 5, "draw_seed", "99999999")
        self.assert_audit_error("draw_seed 99999999")

    def test_negctrl_is_audited_on_its_own_population_only(self):
        # A perturbed negctrl draw breaks exactly the negctrl point's own
        # statistics: mismatch points are never pooled with it (and vice
        # versa -- the field-by-field control above perturbs a mismatch
        # point and leaves this one alone).
        self.fx.set_draw_cell(self.RECORD, self.NEGCTRL, 5, "vos_v", "0.0160000000")
        content = self.fx.build()
        errors = self.all_errors(content)
        self.assertEqual(content["overall"]["verdict"], "ERROR")
        self.assertTrue(
            any(f"point {self.NEGCTRL} fails definition check offset_mc_statistics" in e for e in errors),
            errors,
        )
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


class CmrrMcStatistics(unittest.TestCase):
    """Issue #208: the CMRR summary is audited against hash-pinned raw sample
    files, not merely against its own mean/sigma/CMRR identity."""

    RECORD = "cmrr-mismatch"
    POINT = "mos_tt_27C_1.20V"

    def setUp(self) -> None:
        self.fx = Fixture()
        self.fx.keep_cmrr_audit = True

    def tearDown(self) -> None:
        self.fx.close()

    def errors(self, content: dict) -> list:
        out = list(content["errors"])
        for row in content["rows"]:
            out.extend(row["errors"])
        return out

    def assert_error(self, *fragments: str) -> None:
        content = self.fx.build()
        errors = self.errors(content)
        self.assertEqual(content["overall"]["verdict"], "ERROR", errors)
        for fragment in fragments:
            self.assertTrue(any(fragment in e for e in errors), errors)

    def entry(self, pid=None) -> dict:
        return self.fx.selection["records"][self.RECORD]["mc_samples"]["files"][pid or self.POINT]

    def edit_samples(self, transform, pid=None, repin=True) -> None:
        entry = self.entry(pid)
        path = self.fx.root / entry["path"]
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")
        if repin:
            entry["sha256"] = generate.sha256_file(path)
            self.fx.save_selection()

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
                fx = Fixture()
                try:
                    old = Decimal(rows[self.POINT][field])
                    bumped = old + Decimal("0.0001") if old != 0 else Decimal("0.001")
                    fx.set_cell(self.RECORD, self.POINT, field, str(bumped))
                    errors = [e for e in fx.build()["errors"] + [x for r in fx.build()["rows"] for x in r["errors"]]]
                    self.assertTrue(any(field in e and self.POINT in e for e in errors), errors)
                finally:
                    fx.close()

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
        self.fx.set_cell("open-loop-ac", self.POINT, "av0_db", "41.5")
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
        # dc_gain currently FAILs electrically; the load error must still be named.
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
        md = self.fx.root / self.fx.selection["records"]["open-loop-ac"]["md"]
        md.write_text(md.read_text(encoding="utf-8").replace("CL = 2e-12 F", "load stated elsewhere"), encoding="utf-8")
        self.fx.selection["records"]["open-loop-ac"]["md_sha256"] = generate.sha256_file(md)
        self.fx.save_selection()
        row = self.build_row("gbw")
        self.assertEqual(row["load_check"]["status"], "unverified")
        self.assertIn("UNVERIFIED", row["load"])
        self.assertEqual(row["verdict"], "PASS")

    def test_source_contradicting_ratified_load_is_error(self):
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


class NoiseRawAudit(unittest.TestCase):
    """Issue #213: the input-noise summary is audited against hash-pinned raw
    logs and in-band spectra; the logged integrated figure and the
    spectrum-derived quantities are checked independently."""

    RECORD = "input-noise"
    POINT = "mos_tt_27C_1.20V"

    def setUp(self) -> None:
        self.fx = Fixture()
        self.fx.keep_noise_audit = True

    def tearDown(self) -> None:
        self.fx.close()

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

    def entry(self, kind, pid=None) -> dict:
        return self.fx.selection["records"][self.RECORD]["noise_raw"]["files"][pid or self.POINT][kind]

    def edit_raw(self, kind, transform, pid=None, repin=True) -> None:
        entry = self.entry(kind, pid)
        path = self.fx.root / entry["path"]
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")
        if repin:
            entry["sha256"] = generate.sha256_file(path)
            self.fx.save_selection()

    def cell(self, column, pid=None) -> str:
        return next(r for r in generate.read_csv_rows(self.fx.csv_path(self.RECORD))[1]
                    if r["point_id"] == (pid or self.POINT))[column]

    def only_problem(self, tag: str, other: str) -> None:
        """The point fails the audit on `tag` and NOT on `other`."""
        errors = [e for e in self.assert_error(f"point {self.POINT} fails definition check noise_raw_audit")]
        self.assertTrue(any(f"[{tag}]" in e for e in errors), errors)
        self.assertFalse(any(f"[{other}]" in e for e in errors), errors)

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
                fx = Fixture()
                fx.keep_noise_audit = True
                try:
                    fx.set_cell(self.RECORD, self.POINT, field, "1.5")
                    self.fx, keep = fx, self.fx
                    self.only_problem("spectrum", "integrated-log")
                    errors = self.errors(fx.build())
                    self.assertTrue(any(field in e and self.POINT in e for e in errors), errors)
                    self.fx = keep
                finally:
                    fx.close()

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
        self.assertIsNone(generate._noise_cell_problem("x", "nan", float("nan")))
        self.assertIsNotNone(generate._noise_cell_problem("x", "1.0", float("nan")))
        self.assertIsNotNone(generate._noise_cell_problem("x", "nan", 1.0))
        self.assertEqual(noise_post.serialize(float("nan")), "nan")
        self.assertEqual(noise_post.serialize(0.1 + 0.2), "0.3")

    # --- raw artifact problems (all point-specific) -------------------------

    def test_changed_raw_pins_fail(self):
        for kind in ("log", "spectrum"):
            with self.subTest(kind=kind):
                fx = Fixture()
                try:
                    path = fx.root / fx.selection["records"][self.RECORD]["noise_raw"]["files"][self.POINT][kind]["path"]
                    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
                    errors = fx.build()["errors"] + [x for r in fx.build()["rows"] for x in r["errors"]]
                    self.assertTrue(any(self.POINT in e and "does not match its selection pin" in e for e in errors), errors)
                finally:
                    fx.close()

    def test_missing_point_association_fails(self):
        del self.fx.selection["records"][self.RECORD]["noise_raw"]["files"][self.POINT]
        self.fx.save_selection()
        self.assert_error(f"point {self.POINT}: no pinned raw noise log/spectrum")

    def test_pin_outside_the_grid_fails(self):
        files = self.fx.selection["records"][self.RECORD]["noise_raw"]["files"]
        files["mos_tt_99C_1.20V"] = files[self.POINT]
        self.fx.save_selection()
        self.assert_error("'mos_tt_99C_1.20V', which is outside the expected grid")

    def test_duplicate_association_fails(self):
        files = self.fx.selection["records"][self.RECORD]["noise_raw"]["files"]
        other = "mos_tt_27C_1.32V"
        files[other] = json.loads(json.dumps(files[self.POINT]))
        self.fx.save_selection()
        errors = self.assert_error("is pinned twice", "belongs to another point")
        self.assertTrue(any(other in e for e in errors), errors)

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

    def test_missing_raw_file_fails(self):
        (self.fx.root / self.entry("spectrum")["path"]).unlink()
        self.assert_error(f"point {self.POINT}: missing raw noise spectrum")

    def test_duplicate_log_total_line_fails(self):
        self.edit_raw("log", lambda ls: ls + ["NOISE_INOISE_TOTAL 1.0E-04"])
        self.assert_error(f"point {self.POINT}: invalid noise log", "2 NOISE_INOISE_TOTAL lines")

    def test_missing_log_total_line_fails(self):
        self.edit_raw("log", lambda ls: [l for l in ls if not l.startswith("NOISE_INOISE_TOTAL")])
        self.assert_error(f"point {self.POINT}: invalid noise log", "no NOISE_INOISE_TOTAL line")

    def test_non_finite_log_total_fails(self):
        for bad in ("nan", "inf", "1e999", "-1.0E-05", "0"):
            with self.subTest(bad=bad):
                fx = Fixture()
                self.fx, keep = fx, self.fx
                try:
                    self.edit_raw("log", lambda ls: [("NOISE_INOISE_TOTAL " + bad) if l.startswith("NOISE_INOISE_TOTAL") else l for l in ls])
                    self.assert_error(f"point {self.POINT}: invalid noise log")
                finally:
                    self.fx = keep
                    fx.close()

    def test_non_finite_spectrum_sample_fails(self):
        for bad in ("nan", "inf", "1e999", "-1e-6", "0"):
            with self.subTest(bad=bad):
                fx = Fixture()
                self.fx, keep = fx, self.fx
                try:
                    def poison(ls):
                        parts = ls[10].split()
                        parts[1] = bad
                        return ls[:10] + [" ".join(parts)] + ls[11:]
                    self.edit_raw("spectrum", poison)
                    self.assert_error(f"point {self.POINT}: invalid noise spectrum")
                finally:
                    self.fx = keep
                    fx.close()

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

    def test_audit_requires_pinned_raw_artifacts(self):
        del self.fx.selection["records"][self.RECORD]["noise_raw"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_band_must_match_the_documented_band(self):
        self.fx.selection["records"][self.RECORD]["noise_raw"]["band"]["points"] = 41
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_unpinned_artifact_entry_is_rejected(self):
        del self.entry("log")["sha256"]
        self.fx.save_selection()
        with self.assertRaises(generate.SelectionError):
            self.fx.build()

    def test_runner_uses_the_shared_module(self):
        runner = (REPO / "sim" / "input-noise" / "run_noise_sweep.sh").read_text(encoding="utf-8")
        self.assertIn("noise_post.py", runner)
        self.assertNotIn("PYEOF", runner.split("noise_post.py")[1].split("done")[0])


if __name__ == "__main__":
    unittest.main()

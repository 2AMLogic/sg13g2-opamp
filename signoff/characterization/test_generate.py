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

    def rewrite_csv(self, key: str, transform, repin: bool = True) -> None:
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


if __name__ == "__main__":
    unittest.main()

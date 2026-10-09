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

    def rewrite_csv(self, key: str, transform, repin: bool = True) -> None:
        path = self.csv_path(key)
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")
        if repin:
            self.selection["records"][key]["csv_sha256"] = generate.sha256_file(path)
            self.save_selection()

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
        self.fx.rewrite_csv("input-offset-mc", lambda ls: [l for l in ls if not l.startswith("mos_fs_mismatch_125C")])
        rows = rows_by_id(self.fx.build())
        self.assertEqual(rows["offset_mc_3sigma"]["verdict"], "INCOMPLETE")
        self.assertIn("mos_fs_mismatch_125C_1.20V", rows["offset_mc_total"]["coverage"]["missing"])

    def test_mc_negative_control_missing_is_incomplete(self):
        self.fx.rewrite_csv("input-offset-mc", lambda ls: [l for l in ls if "negctrl" not in l])
        self.assertEqual(rows_by_id(self.fx.build())["offset_mc_3sigma"]["verdict"], "INCOMPLETE")

    def test_mc_short_draw_count_is_incomplete(self):
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


if __name__ == "__main__":
    unittest.main()

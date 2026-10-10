"""Negative controls for signoff/check_integrator_contract.py (offline, stdlib)."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import check_integrator_contract as cic


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for rel in (cic.INTEGRATOR_REL, cic.SYMBOL_REL, cic.SPEC_REL):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(cic.REPO_ROOT / rel, self.tmp / rel)

    def edit(self, rel, old, new, count=1):
        path = self.tmp / rel
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, f"fixture anchor {old!r} vanished")
        path.write_text(text.replace(old, new, count), encoding="utf-8")

    def view(self, mutate):
        path = self.tmp / cic.INTEGRATOR_REL
        doc = json.loads(path.read_text())
        mutate(doc)
        path.write_text(json.dumps(doc))

    def fails(self, *needles):
        problems = cic.check(self.tmp)
        self.assertTrue(problems, "expected a failure, got none")
        joined = "\n".join(problems)
        for n in needles:
            self.assertIn(n, joined)


class Contract(Fixture):
    def test_repo_passes(self):
        self.assertEqual(cic.check(), [])

    def test_port_name_typo(self):
        self.edit(cic.INTEGRATOR_REL, '"name": "vdd"', '"name": "vcc"')
        self.fails("ports order/names", "vcc")

    def test_port_order_swapped(self):
        def swap(d):
            d["ports"][0], d["ports"][1] = d["ports"][1], d["ports"][0]
        self.view(swap)
        self.fails("ports order/names")

    def test_port_direction(self):
        self.edit(cic.SYMBOL_REL, "name=out dir=inout", "name=out dir=out")
        self.fails("ports[4] (out).symbol_dir")

    def test_symbol_pin_renumbered(self):
        self.edit(cic.SYMBOL_REL, "name=vdd dir=inout pinnumber=1", "name=vdd dir=inout pinnumber=9")
        self.fails("ports order/names")

    def test_ratified_number_typo(self):
        self.edit(cic.INTEGRATOR_REL, '"dc_gain_db_worst_min": 37.8', '"dc_gain_db_worst_min": 38.7')
        self.fails("spec_rows_ratified.dc_gain_db_worst_min", "38.7", "37.8")

    def test_supply_pin_bound_typo_in_cl_and_supply(self):
        self.edit(cic.INTEGRATOR_REL, '"max": 1.32', '"max": 1.23')
        self.fails("variant.supply_v.max")
        self.edit(cic.INTEGRATOR_REL, '"capacitance_pf": 2.0', '"capacitance_pf": 20.0')
        self.fails("load.capacitance_pf")

    def test_missing_required_row(self):
        self.view(lambda d: d["spec_rows_ratified"].pop("psrr_db_worst_min_dc_shelf"))
        self.fails("spec_rows_ratified.psrr_db_worst_min_dc_shelf", "missing")

    def test_extra_unmapped_row(self):
        self.view(lambda d: d["spec_rows_ratified"].__setitem__("bandwidth_x", 1))
        self.fails("spec_rows_ratified.bandwidth_x", "no source mapping")

    def test_ratification_changes_target_bound_flags_stale_view(self):
        self.edit(cic.SPEC_REL, "**Ratified bound ≥ 37.8 dB worst-case [DR-2]**", "**Ratified bound ≥ 36.0 dB worst-case [DR-2]**")
        self.fails("dc_gain_db_worst_min", "ratified bound is 36.0", "refresh")

    def test_malformed_source_bound(self):
        self.edit(cic.SPEC_REL, "**Ratified bound ≥ 4.74 MHz worst-case [DR-2]**", "**Ratified bound ≥ about 4.74 MHz [DR-2]**")
        self.fails("gbw_mhz_worst_min_into_2pf", "malformed")

    def test_wrong_direction_or_unit_in_source(self):
        self.edit(cic.SPEC_REL, "**Ratified bound ≥ 4.74 MHz worst-case", "**Ratified bound ≤ 4.74 MHz worst-case")
        self.fails("gbw_mhz_worst_min_into_2pf", "malformed")
        self.edit(cic.SPEC_REL, "**Ratified bound Iq ≤ 119.7 uA", "**Ratified bound Iq ≤ 119.7 mA")
        self.fails("iq_ua_worst_max_total_incl_ibias", "malformed")

    def test_numeric_coincidence_in_prose_cannot_satisfy_bound(self):
        # The bound moves to 36.0 while the measured-envelope prose still says
        # 37.8 dB worst: the published 37.8 must still fail.
        self.edit(cic.SPEC_REL, "**Ratified bound ≥ 37.8 dB worst-case [DR-2]**", "**Ratified bound ≥ 36.0 dB worst-case [DR-2]**")
        text = (self.tmp / cic.SPEC_REL).read_text(encoding="utf-8")
        self.assertIn("measured envelope 37.8 dB worst", text)
        self.fails("dc_gain_db_worst_min")

    def test_cmrr_superseded_floor_cannot_stand_in_for_mismatch_bound(self):
        self.edit(cic.INTEGRATOR_REL, '"cmrr_db_worst_min_mismatch_inclusive": 26.68', '"cmrr_db_worst_min_mismatch_inclusive": 30.75')
        self.fails("cmrr_db_worst_min_mismatch_inclusive", "26.68")

    def test_cmrr_basis_dropped_from_source(self):
        self.edit(cic.SPEC_REL, "worst-case — mismatch-inclusive CMRR, the +3σ-of-Acm figure [DR-4]", "worst-case [DR-2]")
        self.fails("cmrr_db_worst_min_mismatch_inclusive", "malformed")

    def test_duplicate_or_missing_spec_row(self):
        self.edit(cic.SPEC_REL, "| PSRR |", "| PSRRX |")
        self.fails("psrr_db_worst_min_dc_shelf", "need exactly 1")

    def test_load_basis_dropped_from_row_label(self):
        self.edit(cic.SPEC_REL, "| GBW (into stated CL = 2 pF [DR-1]", "| GBW (into stated CL = 5 pF [DR-1]")
        self.fails("gbw_mhz_worst_min_into_2pf")

    def test_resistive_load_statement_dropped(self):
        self.edit(cic.INTEGRATOR_REL, "no resistive load characterized", "50 ohm load characterized")
        self.fails("load.resistive")

    def test_unratified_rows_not_promoted(self):
        self.view(lambda d: d["spec_rows_ratified"].__setitem__("offset_mismatch_3sigma_mv", 27.4))
        self.fails("unratified row promoted")
        self.setUp()
        self.view(lambda d: d.__setitem__("area_mm2", 0.01))
        self.fails("area_mm2")

    def test_unratified_row_dropped_or_spec_ratified_without_update(self):
        self.view(lambda d: d["spec_rows_not_ratified"].pop("input_common_mode_range_v"))
        self.fails("input_common_mode_range_v", "dropped")
        self.setUp()
        self.edit(cic.SPEC_REL, "| Measured (not yet ratified) |", "| Ratified [DR-5] |")
        self.fails("ICMR row")

    def test_checker_is_read_only(self):
        before = {p: p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()}
        cic.check(self.tmp)
        self.assertEqual(before, {p: p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()

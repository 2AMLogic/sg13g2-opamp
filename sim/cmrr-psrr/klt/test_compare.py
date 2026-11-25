#!/usr/bin/env python3
"""Offline negative-control tests for compare.py (issue #99).

    python3 -m unittest discover -s sim/cmrr-psrr/klt -p 'test_*.py'

The synthetic envelopes below are BUILT FROM the committed harness record, so a
test that only checks "the baseline agrees" would be circular. The baseline is
the control every negative case perturbs; the tests that carry weight are the
negative controls (missing, duplicate, extra, null, NaN, errored/inconclusive
corner, nothing_checked, skipped coverage, wrong grid key, mis-biased Vcm,
perturbed value, absent Av0 or Avs, bound flip, genuine bound miss), each of
which must fail and name the point/metric. None of this is evidence about the
circuit -- a committed envelope in records/ would be.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# compare.py imports the shared envelope core from sim/tools (issue #142).
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "tools")))
import compare as C  # noqa: E402
import envelope_control_mixin as M  # noqa: E402
import envelope_fixtures as F  # noqa: E402

BENCH = os.path.dirname(HERE)
SIM = os.path.dirname(BENCH)
REPO = os.path.dirname(SIM)
HARNESS_CSV = os.path.join(BENCH, "records", "20260921-151815-707b34c.csv")
OPENLOOP_CSV = os.path.join(SIM, "open-loop-ac", "records", "20260910-221601-22feaba.csv")
OPENLOOP_REQUEST = os.path.join(SIM, "open-loop-ac", "klt", "openloop_ac.request.json")
REQUEST = os.path.join(HERE, "psrr.request.json")
BODY = os.path.join(HERE, "tb_psrr.body.spice")


def _request():
    with open(REQUEST) as f:
        return json.load(f)


def _vals(r):
    """This bench's measurement dict for one harness row."""
    avs0 = float(r["avs0_db"])
    delta = float(r["psrr_plateau_delta_db"])
    return {"avs0_db": avs0, "avs_plateau_db": avs0 + delta, "avs_plateau_delta_db": delta,
            "avs_1khz_db": float(r["avs_1khz_db"])}


def _envelope(rows):
    """A synthetic klt-sim-shaped envelope carrying the harness's own numbers,
    plus the top-level measurements[] rollup klt sim writes for the request's
    one graded limit (compare.py's tool_plateau_guard summary reads it)."""
    limits = F.request_limits(REQUEST)
    env = F.build_envelope(rows, _vals, C.make_key, limits)
    env["measurements"] = [{"name": "avs_plateau_delta_db", "status": env["status"],
                            "limits": limits["avs_plateau_delta_db"]}]
    return env


def _openloop_envelope(rows):
    """A synthetic open-loop `klt sim` AC envelope (av0_db only) built from the
    open-loop CSV rows, graded against the open-loop bench's own ratified Av0
    bound: the historical 37.78 dB miss at mos_fs_125C_1.08V stays a 'fail'
    corner, as in a real run -- a miss is a result, not a gate failure."""
    return F.build_envelope(rows, lambda r: {"av0_db": float(r["av0_db"])}, C.make_key,
                            F.request_limits(OPENLOOP_REQUEST))


class Base(unittest.TestCase):
    def setUp(self):
        self.h_rows = F.harness_rows(HARNESS_CSV)
        self.env = _envelope(self.h_rows)
        self.harness = C.load_harness_csv(HARNESS_CSV)
        self.openloop = C.load_openloop_csv(OPENLOOP_CSV)
        self.ol_env = _openloop_envelope(F.harness_rows(OPENLOOP_CSV))

    def tool(self, env=None):
        return C.index_envelope(env if env is not None else self.env)

    def run_compare(self, env=None, harness=None, openloop=None):
        return C.compare(self.tool(env), harness or self.harness, openloop or self.openloop)

    @staticmethod
    def find(env, point, name):
        return F.find(env, point, name, C.make_key)

    def meas(self, env, key, name):
        return self.find(env, key, name)[1]


class TestRequest(Base):
    def test_ratified_grid(self):
        r = _request()
        self.assertEqual([p["name"] for p in r["corners"]["process"]], list(C.PROCESSES))
        for p in r["corners"]["process"]:
            self.assertEqual(p["sections"][1], {"lib": "libs.tech/ngspice/models/cornerCAP.lib", "section": "cap_typ"})
            self.assertEqual(p["sections"][2], {"lib": "libs.tech/ngspice/models/cornerRES.lib", "section": "res_typ"})
        self.assertEqual(r["corners"]["supply_v"]["vdd"], list(C.SUPPLIES))
        self.assertEqual(r["corners"]["supply_v"]["vinp"], [v / 2 for v in C.SUPPLIES])
        self.assertEqual(r["corners"]["temperature_c"], list(C.TEMPERATURES))
        self.assertEqual(r["analysis"], {"kind": "ac", "args": "dec 20 10m 1g"})

    def test_declares_every_measurement_compare_reads(self):
        self.assertEqual(tuple(m["name"] for m in _request()["measurements"]), C.MEASUREMENTS)

    def test_netlist_points_at_this_body(self):
        self.assertEqual(_request()["netlist"], os.path.basename(BODY))
        self.assertTrue(os.path.exists(os.path.join(HERE, _request()["netlist"])))

    def test_body_has_one_include_and_no_control_block(self):
        with open(BODY) as f:
            lines = [ln.strip().lower() for ln in f if not ln.lstrip().startswith("*")]
        self.assertEqual([ln for ln in lines if ln.startswith(".include")],
                         [".include ../../../design/netlist/opamp_core.spice"])
        for bad in (".control", ".endc", ".end", ".ac", ".lib"):
            self.assertNotIn(bad, [ln.split()[0] for ln in lines if ln])
        self.assertTrue(any(ln.startswith("vdd ") and " ac 1" in ln for ln in lines))
        self.assertFalse(any(ln.startswith("vinp ") and "ac" in ln.split() for ln in lines))

    def test_plateau_guard_is_the_only_limit_and_matches_the_harness(self):
        lim = {m["name"]: m.get("limits") for m in _request()["measurements"]}
        self.assertEqual({k: v for k, v in lim.items() if v}, {"avs_plateau_delta_db": {"max": C.PLATEAU_LIMIT_DB}})

    def test_ratified_bound_matches_spec(self):
        with open(os.path.join(os.path.dirname(SIM), "spec", "target-spec.md")) as f:
            spec = f.read()
        self.assertIn("Ratified bound ≥ 1.87 dB", spec)
        self.assertEqual(C.PSRR_BOUND_DB, 1.87)


class TestHarnessInputs(M.HarnessCsvControlMixin, Base):
    harness_csv = HARNESS_CSV
    nonfinite_col = "psrr_db"

    def load_csv(self, path):
        return C.load_harness_csv(path)

    def test_committed_records_are_the_full_grid(self):
        self.assertEqual(len(self.harness), 45)
        self.assertEqual(len(self.openloop), 45)

    def test_harness_psrr_is_openloop_av0_minus_avs0(self):
        for k in C.expected_keys():
            self.assertAlmostEqual(self.harness[k]["psrr_db"], self.openloop[k]["av0_db"] - self.harness[k]["avs0_db"], places=3)


class TestOpenLoopCsvInputs(M.HarnessCsvControlMixin, Base):
    """The shared loader's four generic harness-CSV refusals, run through this
    bench's own open-loop Av0 loader (csv_label: load_openloop_csv names the
    file 'open-loop CSV', not 'harness CSV')."""

    harness_csv = OPENLOOP_CSV
    nonfinite_col = "av0_db"
    csv_label = "open-loop CSV"

    def load_csv(self, path):
        return C.load_openloop_csv(path)


class TestBaselineControl(Base):
    def test_identical_numbers_agree(self):
        rep = self.run_compare()
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["status"], "agree", rep["out_of_tolerance"])

    def test_binding_corner_is_ff_125_132(self):
        self.assertEqual(self.run_compare()["row"]["harness_worst"]["point"], "mos_ff_125C_1.32V")

    def test_known_plateau_guard_miss_is_preserved(self):
        rep = self.run_compare()
        p = next(p for p in rep["points"] if p["point_id"] == "mos_ss_-40C_1.08V")
        self.assertFalse(p["plateau_guard"]["tool_pass"])
        self.assertTrue(p["plateau_guard"]["agree"])
        self.assertEqual(self.env["status"], "fail")

    def test_reordered_corners_join_identically(self):
        env = copy.deepcopy(self.env)
        env["corners"].reverse()
        self.assertEqual(self.run_compare(env)["status"], "agree")


class TestEnvelopeNegativeControls(M.EnvelopeControlMixin, Base):
    """The shared gate's thirteen generic envelope refusals
    (envelope_control_mixin), each run through this bench's own comparator
    gate. The bench-specific grid/status refusals stay below."""

    WORST = ("mos_tt", 27, 1.2)
    null_meas = "avs0_db"
    nonfinite_meas = "avs_1khz_db"
    absent_meas = "avs0_db"

    def control(self, name):
        # Base.env is an attribute rebuilt per test, not a factory method.
        return copy.deepcopy(self.env), self.tool

    def test_wrong_temperature_key(self):
        env = copy.deepcopy(self.env)
        env["corners"][0]["temperature_c"] = 85
        with self.assertRaisesRegex(C.InputError, "mos_tt_-40C_1.08V: missing from"):
            self.tool(env)

    def test_skipped_measurement_status(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_tt", 27, 1.2), "avs0_db")["status"] = "skipped"
        with self.assertRaisesRegex(C.InputError, "avs0_db status 'skipped'"):
            self.tool(env)

    def test_inconclusive_corner_is_not_evidence(self):
        env = copy.deepcopy(self.env)
        self.find(env, ("mos_tt", 27, 1.2), "avs0_db")[0]["status"] = "inconclusive"
        with self.assertRaisesRegex(C.InputError, "corner status 'inconclusive'"):
            self.tool(env)

class TestComparisonNegativeControls(Base):
    def test_perturbed_avs0_outside_tolerance_is_named(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_sf", 125, 1.08), "avs0_db")["value"] += 0.1
        rep = self.run_compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_sf_125C_1.08V avs0_db" in s for s in rep["out_of_tolerance"]))
        self.assertTrue(any("mos_sf_125C_1.08V psrr_db" in s for s in rep["out_of_tolerance"]))

    def test_perturbation_inside_tolerance_is_accepted(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_sf", 125, 1.08), "avs0_db")["value"] += 0.01
        self.assertEqual(self.run_compare(env)["status"], "agree")

    def test_perturbed_1khz_outside_tolerance_is_named(self):
        env = copy.deepcopy(self.env)
        self.meas(env, ("mos_tt", 27, 1.2), "avs_1khz_db")["value"] -= 0.5
        self.assertTrue(any("mos_tt_27C_1.20V avs_1khz_db" in s for s in self.run_compare(env)["out_of_tolerance"]))

    def test_dc_shelf_is_not_the_1khz_figure(self):
        # Swapping the 1 kHz Avs into the DC-shelf slot must be caught.
        env = copy.deepcopy(self.env)
        k = ("mos_tt", 27, 1.2)
        self.meas(env, k, "avs0_db")["value"] = self.meas(env, k, "avs_1khz_db")["value"]
        rep = self.run_compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V psrr_db" in s for s in rep["out_of_tolerance"]))

    def test_openloop_av0_absent_fails_closed(self):
        ol = copy.deepcopy(self.openloop)
        ol[("mos_tt", 27, 1.2)]["av0_db"] = float("nan")
        with self.assertRaisesRegex(C.InputError, "mos_tt_27C_1.20V: same-point Av0 absent"):
            self.run_compare(openloop=ol)

    def test_openloop_point_missing_fails_closed(self):
        ol = copy.deepcopy(self.openloop)
        del ol[("mos_tt", 27, 1.2)]
        with self.assertRaisesRegex(C.InputError, "missing from open-loop CSV"):
            self.run_compare(openloop=ol)

    def test_openloop_from_a_different_run_is_flagged(self):
        ol = copy.deepcopy(self.openloop)
        ol[("mos_tt", 27, 1.2)]["av0_db"] += 1.0
        rep = self.run_compare(openloop=ol)
        self.assertEqual(rep["status"], "disagree")
        self.assertTrue(any("mos_tt_27C_1.20V" in s for s in rep["join_inconsistencies"]))

    def test_plateau_flag_disagreement_is_named(self):
        env = copy.deepcopy(self.env)
        m = self.meas(env, ("mos_tt", 27, 1.2), "avs_plateau_delta_db")
        m["value"], m["status"] = 0.2, "fail"
        rep = self.run_compare(env)
        self.assertTrue(any("mos_tt_27C_1.20V plateau_guard" in s for s in rep["out_of_tolerance"]))


class TestBoundVerdicts(Base):
    def test_genuine_bound_miss_is_preserved_not_hidden(self):
        # Both paths agree the point misses: a miss is a result, no disagreement.
        k = ("mos_ff", 125, 1.32)
        h = copy.deepcopy(self.harness)
        ol = copy.deepcopy(self.openloop)
        shift = h[k]["psrr_db"] - 1.0  # drive PSRR to 1.0 dB (< 1.87)
        for d in (h, ol):
            d[k]["av0_db"] -= shift
        h[k]["psrr_db"] -= shift
        rep = C.compare(self.tool(), h, ol)
        # tool Avs unchanged, Av0 lowered -> tool PSRR = 1.0 as well.
        p = next(p for p in rep["points"] if p["point_id"] == "mos_ff_125C_1.32V")
        self.assertFalse(p["row"]["tool_pass"])
        self.assertFalse(p["row"]["harness_pass"])
        self.assertTrue(p["row"]["agree"])
        self.assertEqual(rep["row"]["tool_worst"]["verdict"], "fail")
        self.assertEqual(rep["row"]["harness_worst"]["verdict"], "fail")
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)

    def test_flip_far_from_bound_is_unexplained_and_fails(self):
        env = copy.deepcopy(self.env)
        k = ("mos_tt", 27, 1.2)  # harness PSRR 6.43 dB, 4.5 dB of margin
        self.meas(env, k, "avs0_db")["value"] += 6.0  # tool PSRR drops below 1.87
        rep = self.run_compare(env)
        self.assertEqual(rep["status"], "disagree")
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 1)
        self.assertEqual(rep["bound_verdict_disagreements"][0]["point"], "mos_tt_27C_1.20V")

    def test_binding_corner_margin_is_inside_the_tolerance(self):
        # Recorded fact the README discusses: the harness's worst point clears the
        # bound by far less than the comparison tolerance, so a tool/harness
        # verdict flip there is reported as 'explained', never as agreement.
        k = ("mos_ff", 125, 1.32)
        margin = self.harness[k]["psrr_db"] - C.PSRR_BOUND_DB
        self.assertGreater(margin, 0)
        self.assertLess(margin, C.TOLERANCES["psrr_db"]["abs"])

    def test_flip_within_tolerance_of_bound_is_explained_not_hidden(self):
        # Put the harness 0.005 dB above the bound; tool 0.015 dB below it.
        k = ("mos_ff", 125, 1.32)
        h = copy.deepcopy(self.harness)
        h[k]["psrr_db"] = C.PSRR_BOUND_DB + 0.005
        env = copy.deepcopy(self.env)
        tool_psrr = C.PSRR_BOUND_DB - 0.015
        self.meas(env, k, "avs0_db")["value"] = self.openloop[k]["av0_db"] - tool_psrr
        rep = C.compare(self.tool(env), h, self.openloop)
        self.assertEqual(len(rep["bound_verdict_disagreements"]), 1)
        self.assertTrue(rep["bound_verdict_disagreements"][0]["explained_by_tolerance"])
        self.assertEqual(rep["unexplained_bound_verdict_disagreements"], 0)


class TestOpenLoopEnvelopeSource(M.EnvelopeControlMixin, Base):
    """Av0 from the open-loop `klt sim` envelope (issue #99): same gate, fail
    closed. The shared gate's thirteen generic envelope refusals
    (envelope_control_mixin) run through this bench's open-loop gate; the
    PSRR-specific join/status/bound controls stay below."""

    WORST = ("mos_tt", 27, 1.2)
    null_meas = nonfinite_meas = absent_meas = "av0_db"

    def control(self, name):
        # Base.ol_env is an attribute rebuilt per test, not a factory method.
        return copy.deepcopy(self.ol_env), self.ol

    def ol(self, env=None):
        return C.index_openloop_envelope(env if env is not None else self.ol_env)

    def run_env(self, ol_env=None, cross=True):
        return C.compare(self.tool(), self.harness, self.ol(ol_env), None, av0_source="open-loop-envelope",
                         av0_crosscheck=self.openloop if cross else None)

    def test_envelope_av0_joins_and_cross_checks_against_the_csv(self):
        rep = self.run_env()
        self.assertEqual(rep["status"], "agree")
        self.assertEqual(rep["av0_join"]["source"], "open-loop-envelope")
        self.assertEqual(rep["av0_join"]["status"], "agree")
        self.assertEqual(len(rep["av0_join"]["points"]), 45)
        self.assertLess(rep["av0_join"]["max_abs_av0_delta_db"], 1e-9)
        self.assertIn("open-loop klt sim envelope", rep["points"][0]["row"]["verdict_source"])

    def test_without_crosscheck_there_is_no_av0_join_points(self):
        self.assertNotIn("points", self.run_env(cross=False)["av0_join"])

    def test_skipped_av0_measurement(self):
        env = copy.deepcopy(self.ol_env)
        env["corners"][2]["measurements"][0]["status"] = "skipped"
        with self.assertRaisesRegex(C.InputError, "open-loop envelope:.*status 'skipped'"):
            self.ol(env)

    def test_av0_bound_miss_is_not_a_gate_failure(self):
        env = copy.deepcopy(self.ol_env)
        env["corners"][2]["measurements"][0]["status"] = "fail"
        self.assertEqual(len(self.ol(env)), 45)

    def test_perturbed_av0_moves_psrr_across_the_tolerance(self):
        env = copy.deepcopy(self.ol_env)
        env["corners"][0]["measurements"][0]["value"] += 0.5
        rep = self.run_env(env)
        self.assertEqual(rep["status"], "disagree")
        p = rep["av0_join"]["points"][0]
        self.assertFalse(p["within"])
        self.assertAlmostEqual(p["psrr_delta_db"], 0.5, places=6)
        self.assertTrue(any(p["point_id"] in s for s in rep["av0_join"]["out_of_tolerance"]))

    def test_perturbation_inside_tolerance_is_accepted(self):
        env = copy.deepcopy(self.ol_env)
        env["corners"][0]["measurements"][0]["value"] += 0.01
        self.assertEqual(self.run_env(env)["av0_join"]["status"], "agree")

    def test_bound_flip_between_the_two_joins_is_named(self):
        env = copy.deepcopy(self.ol_env)
        # Push one point's envelope-joined PSRR far below the bound.
        key = C.make_key(env["corners"][0]["process"], env["corners"][0]["temperature_c"],
                         env["corners"][0]["supply_v"]["vdd"])
        shift = C.PSRR_BOUND_DB - self.harness[key]["psrr_db"] - 1.0
        env["corners"][0]["measurements"][0]["value"] += shift
        rep = self.run_env(env)
        self.assertTrue(any("PSRR bound verdict" in s for s in rep["av0_join"]["out_of_tolerance"]))
        self.assertEqual(rep["status"], "disagree")

    def test_crosscheck_csv_missing_point_fails_closed(self):
        cross = copy.deepcopy(self.openloop)
        del cross[("mos_tt", 27, 1.2)]
        with self.assertRaisesRegex(C.InputError, "missing from open-loop CSV cross-check"):
            C.compare(self.tool(), self.harness, self.ol(), None, av0_source="open-loop-envelope", av0_crosscheck=cross)

    def test_unknown_source_refused(self):
        with self.assertRaisesRegex(C.InputError, "unknown Av0 source"):
            C.compare(self.tool(), self.harness, self.openloop, av0_source="x")


class TestCli(Base):
    def _dump(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        self.addCleanup(os.unlink, path)
        return path

    def test_validate_and_compare_exit_codes(self):
        good = self._dump(self.env)
        self.assertEqual(C.main(["validate", good]), 0)
        args = ["compare", "--envelope", good, "--harness-csv", HARNESS_CSV, "--openloop-csv", OPENLOOP_CSV]
        self.assertEqual(C.main(args), 0)
        bad = copy.deepcopy(self.env)
        bad["coverage"]["nothing_checked"] = True
        self.assertEqual(C.main(["validate", self._dump(bad)]), 2)
        self.assertEqual(C.main(["compare", "--envelope", self._dump(bad)] + args[3:]), 2)
        off = copy.deepcopy(self.env)
        self.meas(off, ("mos_sf", 125, 1.08), "avs0_db")["value"] += 0.1
        self.assertEqual(C.main(["compare", "--envelope", self._dump(off)] + args[3:]), 1)

    def test_envelope_source_exit_codes(self):
        base = ["compare", "--envelope", self._dump(self.env), "--harness-csv", HARNESS_CSV]
        good = self._dump(self.ol_env)
        self.assertEqual(C.main(base + ["--openloop-envelope", good, "--openloop-csv", OPENLOOP_CSV]), 0)
        self.assertEqual(C.main(base + ["--openloop-envelope", good]), 0)
        self.assertEqual(C.main(base), 2)  # no Av0 source at all
        bad = copy.deepcopy(self.ol_env)
        bad["coverage"]["nothing_checked"] = True
        self.assertEqual(C.main(base + ["--openloop-envelope", self._dump(bad)]), 2)
        off = copy.deepcopy(self.ol_env)
        off["corners"][0]["measurements"][0]["value"] += 0.5
        self.assertEqual(C.main(base + ["--openloop-envelope", self._dump(off), "--openloop-csv", OPENLOOP_CSV]), 1)


# ---------------------------------------------------------------------------
# run.sh: one single-request submission (issue #444)

# A stub `klt` client: `--version` answers klt_check_client; every `sim`
# invocation is logged (one line, full args) and replays the envelope the
# test parked in STUB_KLT_ENVELOPE, or exits STUB_KLT_RC to simulate a
# submission that produced no gradable envelope.
STUB_KLT = r"""#!/usr/bin/env bash
if [[ "$1" == "--version" ]]; then echo "stub-klt 0.9"; exit 0; fi
if [[ "$1" != "sim" ]]; then echo "stub klt: unexpected invocation: $*" >&2; exit 9; fi
printf '%s\n' "$*" >> "${STUB_KLT_LOG}"
if [[ -n "${STUB_KLT_RC:-}" && "${STUB_KLT_RC}" != "0" ]]; then
  echo "stub klt: simulated klt sim exit ${STUB_KLT_RC}" >&2
  exit "${STUB_KLT_RC}"
fi
cat "${STUB_KLT_ENVELOPE}"
"""

# Offline stand-in for sim/preflight.sh (the real one needs a PDK install and
# the OSDI build): no checks, and the #209 identity lifecycle becomes a no-op
# (the real one is driven against a fake PDK install by
# sim/tools/test_env_drift_lifecycle.py). PDK / PDK_ROOT / NGSPICE_VERSION
# cover the provenance variables klt_compare_and_finish reads.
STUB_PREFLIGHT = """#!/usr/bin/env bash
# shellcheck shell=bash
sg13g2_preflight_require_netlist() { :; }
sg13g2_env_identity_begin() { :; }
sg13g2_env_identity_finalize() { :; }
PDK="${PDK:-ihp-sg13g2}"
PDK_ROOT="${PDK_ROOT:-/nonexistent-pdk-root}"
NGSPICE_VERSION="${NGSPICE_VERSION:-stub-ngspice}"
"""


class RunnerFixture:
    """A throwaway repo tree that drives the real sim/cmrr-psrr/klt/run.sh
    offline (issue #444): the runner, comparator, request, shared wrappers
    and harness CSVs are the checked-out files; `klt` and sim/preflight.sh
    are stubs, so no PDK, OSDI build, ngspice or klt binary is needed. The
    synthetic envelopes come from Base (built from the committed harness and
    open-loop CSVs), so the compare step joins, agrees and exits 0, as the
    real runner would on an in-tolerance run. `date` and `git` are shadowed
    by exported bash functions (the sim/tools/test_klt_run_common.py
    pattern) so each invocation mints a deterministic record id."""

    COPIES = (
        "sim/cmrr-psrr/klt/run.sh",
        "sim/cmrr-psrr/klt/compare.py",
        "sim/cmrr-psrr/klt/psrr.request.json",
        "sim/tools/klt_run_common.sh",
        "sim/tools/klt_envelope.py",
        "sim/record-paths.sh",
        "sim/cmrr-psrr/records/20260921-151815-707b34c.csv",
        "sim/open-loop-ac/records/20260910-221601-22feaba.csv",
    )

    def __init__(self, root, psrr_env, ol_env):
        self.root = Path(root)
        for rel in self.COPIES:
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(os.path.join(REPO, rel), dst)
        (self.root / "sim" / "preflight.sh").write_text(STUB_PREFLIGHT)
        self.klt_dir = self.root / "sim" / "cmrr-psrr" / "klt"
        self.records = self.klt_dir / "records"
        self.run_sh = self.klt_dir / "run.sh"
        self.envelope = self.root / "stub-psrr.sim.json"
        self.ol_envelope = self.root / "stub-open-loop.ac.sim.json"
        self.log = self.root / "klt-sim-calls.log"
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.write_envelope(psrr_env)
        self.write_openloop(ol_env)
        self.klt = self.root / "klt"
        self.klt.write_text(STUB_KLT)
        self.klt.chmod(0o755)

    def write_envelope(self, env):
        with open(self.envelope, "w") as f:
            json.dump(env, f)

    def write_openloop(self, env):
        with open(self.ol_envelope, "w") as f:
            json.dump(env, f)

    def sim_calls(self):
        if not self.log.exists():
            return []
        return [ln.split() for ln in self.log.read_text().splitlines()]

    def published(self):
        return sorted(p.name for p in self.records.iterdir())


class TestRunnerSingleRequest(Base):
    """issue #444: run.sh submits psrr.request.json as ONE `klt sim` call
    (submit_mode=single, provenance-recorded) and publishes nothing under
    records/ when the run is not gradable. The five-job shard bridge
    (PSRR_KLT_MODE / PSRR_KLT_RESUME_DIR / PSRR_KLT_SUBMIT_TRIES /
    PSRR_KLT_RETRY_SLEEP_S / the <id>.shards/ copy) is gone from the runner;
    its replay tools, records and tests stay (test_shard.py)."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fx = RunnerFixture(tmp.name, self.env, self.ol_env)

    def invoke(self, ts, env=None):
        e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
             "KLT": str(self.fx.klt),
             "STUB_KLT_LOG": str(self.fx.log),
             "STUB_KLT_ENVELOPE": str(self.fx.envelope),
             "TMPDIR": str(self.fx.tmp),
             # Av0 fixtures consistent with the harness record (the old
             # floating-inn CSV both envelopes here are built from), so the
             # compare step itself agrees -- the join numerics have their own
             # tests above; these are runner-mechanics tests.
             "PSRR_OPENLOOP_CSV": "sim/open-loop-ac/records/20260910-221601-22feaba.csv",
             "PSRR_OPENLOOP_ENVELOPE": "stub-open-loop.ac.sim.json",
             "FAKE_TS": ts, "FAKE_SHA": "abc1234",
             "RUNNER": str(self.fx.run_sh)}
        e.update(env or {})
        wrapper = ('date() { echo "$FAKE_TS"; }\n'
                   'git() { echo "$FAKE_SHA"; }\n'
                   'export -f date git\n'
                   'exec bash "$RUNNER"\n')
        return subprocess.run(["bash", "-c", wrapper], cwd=str(self.fx.root), env=e,
                              capture_output=True, text=True)

    def compare_report(self, ts):
        with open(self.fx.records / f"{ts}-abc1234.compare.json") as f:
            return json.load(f)

    def test_one_klt_sim_call_and_published_records(self):
        r = self.invoke("20260101-000001")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.fx.sim_calls()
        self.assertEqual(len(calls), 1, calls)  # one submission, no shard loop
        self.assertEqual(calls[0][0], "sim")
        self.assertEqual(os.path.basename(calls[0][1]), "psrr.request.json")
        self.assertNotIn("--backend", calls[0])  # request field: batch
        self.assertEqual(self.fx.published(),
                         ["20260101-000001-abc1234.compare.json",
                          "20260101-000001-abc1234.sim.json"])  # no <id>.shards/, no reservation
        rep = self.compare_report("20260101-000001")
        self.assertEqual(rep["status"], "agree")
        self.assertEqual(rep["points_compared"], 45)
        self.assertEqual(rep["provenance"]["submit_mode"], "single")
        self.assertEqual(rep["provenance"]["backend_override"], "none (request field: batch)")

    def test_backend_override_forwarded_to_the_single_call(self):
        r = self.invoke("20260101-000002", {"PSRR_KLT_BACKEND": "local"})
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.fx.sim_calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0][calls[0].index("--backend") + 1], "local")
        self.assertEqual(self.compare_report("20260101-000002")["provenance"]["backend_override"], "local")

    def test_failed_klt_sim_publishes_nothing(self):
        r = self.invoke("20260101-000003", {"STUB_KLT_RC": "4"})
        self.assertEqual(r.returncode, 4)
        self.assertIn("klt sim exited 4", r.stderr)
        self.assertEqual(len(self.fx.sim_calls()), 1)  # submitted once, no retry loop
        self.assertEqual(self.fx.published(), [])  # nothing written, reservation released

    def test_44_corner_envelope_refused_and_not_published(self):
        env = copy.deepcopy(self.env)
        del env["corners"][7]
        env["corner_count"] = 44
        self.fx.write_envelope(env)
        r = self.invoke("20260101-000004")
        self.assertEqual(r.returncode, 4)
        self.assertIn("envelope failed validation", r.stderr)
        self.assertEqual(self.fx.published(), [])

    def test_errored_corner_envelope_refused_and_not_published(self):
        env = copy.deepcopy(self.env)
        env["corners"][2]["status"] = "error"
        self.fx.write_envelope(env)
        r = self.invoke("20260101-000005")
        self.assertEqual(r.returncode, 4)
        self.assertIn("envelope failed validation", r.stderr)
        self.assertEqual(self.fx.published(), [])


if __name__ == "__main__":
    unittest.main()

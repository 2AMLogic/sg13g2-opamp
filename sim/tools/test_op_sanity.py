"""Offline controls for the shared sg13g2_op_sanity gate in sim/preflight.sh.

Issue #366: the per-point DC operating-point sanity gate (`op_pass`) was
byte-identical inline `python3 -c` in four sim/*/run_*.sh runners
(open-loop-ac, slew-rate, cmrr-psrr, input-noise -- the last with an extra
closed-loop-gain band-edge guard). op_pass is an evidence-admission gate
(signoff/characterization/defchecks.py refuses a dc_continuity point whose
op_pass is not 1), so four independent copies meant four independent
definitions of "this corner counts as evidence". They are now one helper,
sg13g2_op_sanity <vdd> <vcm> <vout> <vd1> <vd2> <vtail>, echoing 1/0.

Two kinds of control here, matching the issue's Test Plan:

1. A truth table over the boundary cases, pinning the comparison operators:
   the mid-rail gap admits |Vout-Vcm| == 0.15*VDD (<=, not <), and the rail
   window admits nodes exactly at 0.02*VDD and exactly at VDD-0.02*VDD
   (inclusive both ends). The boundary values are built so the two sides of
   the comparison are the *same double* (e.g. Vcm=0 makes abs(Vout-Vcm)
   parse to exactly the 0.15*VDD product), which is what distinguishes <=
   from < in binary floating point -- a decimal "looks exact" case would
   not.

2. A replay of each bench's latest committed record: every row's node
   voltages are fed through the helper (plus, for input-noise, the bench's
   own band-edge gain guard composed exactly as run_noise_sweep.sh composes
   it at its call site) and the result must equal that record's op_pass
   column exactly. That is the issue's behaviour-preserving requirement:
   the refactor may not move a single admitted or rejected corner.

Sourcing the real sim/preflight.sh needs a resolvable PDK install, a
build-osdi.sh that passes --check, and an ngspice on PATH (it is the same
source-time environment every real runner has), so each fixture reuses
test_env_drift_lifecycle.py's Tree fake install and stubs. No ngspice
solve, no PDK content, and no committed record is touched: records are read
from the repo read-only.

Issue #380 extended both controls to the newly folded sites: the bash
helper now delegates to the importable predicate sim/tools/op_sanity.py
(the fixture copies the real module into its throwaway tree), a
truth-table test pins module and helper to identical verdicts -- including
an off-grid VDD where the old 0.98*VDD spelling the input-offset copy
carried would disagree -- and the replay set gains input-offset's committed
record and cmrr-mismatch's 13,500 committed draws.
"""
import csv
import importlib.util
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SIM_DIR = TOOLS_DIR.parent

sys.path.insert(0, str(TOOLS_DIR))
import op_sanity  # noqa: E402  -- the shared predicate under control (#380)
from test_env_drift_lifecycle import Tree, _write_exec  # noqa: E402

# The benches whose op_pass derives from the shared rule, with the record
# columns each one's op_pass was computed from. The last element is the
# bench-specific guard composed ON TOP of the shared gate at that runner's
# call site -- None, or (guard-mode, columns). input-noise gates on its
# closed-loop gain at the two band edges (clgain_100hz / clgain_1mhz =
# glo/ghi in the runner, kept within 0.9..1.1); input-offset gates on a
# real amplifying point -- the record's dB column av_local_db >= 20, the
# exact record-side form of the runner's linear av_local >= 10.0 on the
# committed record -- and the null well inside the coarse locate window
# (|vos_null_v| < 0.09, the runner's |vos| >= 0.9*0.1; every committed vos
# sits far inside both).
REPLAY_BENCHES = {
    "open-loop-ac": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                     "vtail_dc_v", None),
    "slew-rate": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                  "vtail_dc_v", None),
    "cmrr-psrr": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                  "vtail_dc_v", None),
    "input-noise": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                    "vtail_dc_v", ("clgain", ("clgain_100hz", "clgain_1mhz"))),
    "input-offset": ("vdd_v", "vcm_v", "vout_sample_v", "vd1_sample_v",
                     "vd2_sample_v", "vtail_sample_v",
                     ("offset_null", ("av_local_db", "vos_null_v"))),
}

STUB_NGSPICE = r"""#!/usr/bin/env bash
# Only the source-time `ngspice -v` probe is exercised; report the pinned
# version read from the copied pdk.json so preflight's WARN-only pin check
# stays quiet.
if [[ "$1" == "-v" ]]; then
  printf '******\n** %s : Circuit level simulation program (stub)\n' "${PINNED_NGSPICE}"
  exit 0
fi
exit 2
"""

# Sourced by driver.sh after the fixture has substituted the three literal
# paths. Reuses test_env_drift_lifecycle.py's OpenLoopRunner environment:
# the real preflight.sh runs its source-time guards against a fake install,
# then the requested mode drives the real helper.
#
# MODE=sanity      : batch of "vdd vcm vout vd1 vd2 vtail" lines -> helper.
# MODE=sanity+clgain: batch of "... vtail glo ghi" lines -> helper AND the
#                    band-edge gain guard, composed exactly as
#                    run_noise_sweep.sh composes it at its call site.
# MODE=sanity+offset_null: batch of "... vtail avdb vos" lines -> helper AND
#                    input-offset's amplifying-point guards, composed exactly
#                    as run_offset_sweep.sh composes them at its call site.
# MODE=args        : forward "$@" to one helper call (arity-check test).
SETUP_SH = r"""
set -euo pipefail
SIM_DIR="@SIM_DIR@"
export PDK="ihp-sg13g2"
export PDK_ROOT="@PDK_ROOT@"
export PATH="@BIN@:${PATH}"
PINNED_NGSPICE="$(sed -n 's/.*"ngspice_actually_used"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${SIM_DIR}/pdk.json" | head -n 1)"
export PINNED_NGSPICE
SCRIPT_DIR="${SIM_DIR}/fixture"   # error text derives from $0 = driver.sh
REPO_ROOT="${SIM_DIR}/.."
# shellcheck source=/dev/null
source "${SIM_DIR}/preflight.sh"

if [[ "${MODE:-sanity}" == "args" ]]; then
  sg13g2_op_sanity "$@"
  exit 0
fi

# env.sh's own sourcing banner (PDK_ROOT echo) goes to stdout too; mark
# where the results start so the batch reader can skip everything before.
echo "==RESULTS=="

if [[ "${MODE:-sanity}" == "sanity+clgain" ]]; then
  # input-noise's call-site composition (run_noise_sweep.sh): the shared
  # gate, then -- only if it passed -- the bench's own band-edge gain guard.
  while read -r vdd vcm vout vd1 vd2 vtail glo ghi; do
    op_pass="$(sg13g2_op_sanity "${vdd}" "${vcm}" "${vout}" "${vd1}" "${vd2}" "${vtail}")"
    if [[ "${op_pass}" == "1" ]]; then
      op_pass="$(python3 -c "
glo=${glo}; ghi=${ghi}
print('1' if all(0.9 <= g <= 1.1 for g in (glo, ghi)) else '0')
")"
    fi
    echo "${op_pass}"
  done
elif [[ "${MODE:-sanity}" == "sanity+offset_null" ]]; then
  # input-offset's call-site composition (run_offset_sweep.sh): the shared
  # rail window (the helper), then -- only if it passed -- the bench's own
  # amplifying-point guards: a real gain at the null (the record's dB form
  # of the runner's linear av_local >= 10.0) and the null well inside the
  # coarse locate window (|vos| < 0.09, the runner's |vos| >= 0.9*0.1).
  while read -r vdd vcm vout vd1 vd2 vtail avdb vos; do
    op_pass="$(sg13g2_op_sanity "${vdd}" "${vcm}" "${vout}" "${vd1}" "${vd2}" "${vtail}")"
    if [[ "${op_pass}" == "1" ]]; then
      op_pass="$(python3 -c "
import sys
av_db, vos = (float(t) for t in sys.argv[1:3])
print('1' if av_db == av_db and av_db >= 20.0 and abs(vos) < 0.09 else '0')
" "${avdb}" "${vos}")"
    fi
    echo "${op_pass}"
  done
else
  while read -r vdd vcm vout vd1 vd2 vtail; do
    sg13g2_op_sanity "${vdd}" "${vcm}" "${vout}" "${vd1}" "${vd2}" "${vtail}"
  done
fi
"""

DRIVER = r"""#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=/dev/null
source "${SETUP_SH}"
"""


def setup_script(sim_dir: Path, pdk_root: Path, bin_dir: Path) -> str:
    return (SETUP_SH
            .replace("@SIM_DIR@", str(sim_dir))
            .replace("@PDK_ROOT@", str(pdk_root))
            .replace("@BIN@", str(bin_dir)))


class Fixture:
    """A throwaway tree that can source the REAL sim/preflight.sh, built on
    the #209 lifecycle controls' Tree.setup_preflight (same fake PDK install
    and stub-solver shape as its OpenLoopRunner); the fixture tree gets the
    genuine op_sanity module, so every helper verdict below exercises the
    exact code the runners run."""

    def __init__(self, root: Path) -> None:
        self.t = Tree(str(root)).setup_preflight(stub_ngspice=STUB_NGSPICE)
        _write_exec(root / "setup.sh",
                    setup_script(self.t.sim, self.t.pdk_root, self.t.bin))
        self.driver = root / "driver.sh"
        _write_exec(self.driver, DRIVER)

    def _env(self, mode: str) -> dict:
        return self.t.env(SETUP_SH=str(self.t.root / "setup.sh"), MODE=mode)

    def run_cases(self, rows, guard=None):
        """Feed 'vdd vcm vout vd1 vd2 vtail [guard columns]' lines; get '0'/'1's.

        guard=None runs the bare helper; a guard name runs the matching
        call-site composition (clgain / offset_null), whose extra columns
        follow the six gate arguments on each line.
        """
        stdin = "".join(" ".join(str(f) for f in row) + "\n" for row in rows)
        mode = "sanity" if guard is None else f"sanity+{guard}"
        r = subprocess.run(
            ["bash", str(self.driver)], input=stdin,
            capture_output=True, text=True, timeout=60, env=self._env(mode))
        if r.returncode != 0:
            raise AssertionError(
                f"driver failed rc={r.returncode}: {r.stderr}")
        out = r.stdout.split("==RESULTS==\n", 1)
        if len(out) != 2:
            raise AssertionError(f"no results marker in driver stdout: {r.stdout!r}")
        return out[1].split()

    def run_one(self, *args):
        """One direct helper invocation; returns the CompletedProcess."""
        return subprocess.run(
            ["bash", str(self.driver)] + [str(a) for a in args],
            capture_output=True, text=True, timeout=60, env=self._env("args"))


class OpSanityTruthTable(unittest.TestCase):
    """Boundary truth table pinning the comparison operators (#366 AC 2)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_midrail_gap_boundary_is_inclusive(self):
        # |Vout-Vcm| == 0.15*VDD must ADMIT the point (<=, not <). Build the
        # edge so both sides of the comparison are the identical double:
        # with Vcm=0, abs(Vout-Vcm) parses to exactly float("0.15")*float(vdd),
        # the same product the helper computes. A strict < would reject it.
        # Row order is the helper's: vdd vcm vout vd1 vd2 vtail.
        vdd = "1.2"
        tol = repr(float("0.15") * float(vdd))
        self.assertEqual(
            self.fx.run_cases([(vdd, "0.0", tol, "0.6", "0.6", "0.6")]),
            ["1"])
        just_outside = repr(math.nextafter(float(tol), math.inf))
        self.assertEqual(
            self.fx.run_cases([(vdd, "0.0", just_outside, "0.6", "0.6",
                                "0.6")]),
            ["0"])

    def test_rail_window_boundaries_are_inclusive(self):
        # A node exactly at 0.02*VDD, and one exactly at VDD-0.02*VDD, must
        # both ADMIT (window closed at both ends). Each node is repr() of the
        # exact double the helper derives, so the comparison is equality --
        # exclusive bounds would reject these.
        vdd = "1.2"
        rail_lo = repr(float("0.02") * float(vdd))
        rail_hi = repr(float(vdd) - float("0.02") * float(vdd))
        cases = []
        # Boundary node placed one at a time in each of the four checked
        # positions, listed (vd1, vd2, vtail, vout) -- vout is checked in
        # the rail loop as well as the mid-rail gap, so its slot is the
        # row's third field, not a trailing one. When the boundary node is
        # vout itself, vcm moves onto it too (gap = 0): a vout at a rail
        # with a mid-rail vcm fails the gap check regardless of the rail
        # bounds, which would mask the inclusivity being pinned here.
        for idx in range(4):
            for boundary in (rail_lo, rail_hi):
                nodes = ["0.6", "0.6", "0.6", "0.6"]
                nodes[idx] = boundary
                vcm = boundary if idx == 3 else "0.6"
                cases.append((vdd, vcm, nodes[3], nodes[0], nodes[1],
                              nodes[2]))
        self.assertEqual(self.fx.run_cases(cases), ["1"] * len(cases))

    def test_railed_nodes_are_rejected(self):
        # One double beyond each rail end, for every checked node: outside
        # -> 0. nextafter() gives the neighbouring double, so these are as
        # tight as the operators allow.
        vdd = 1.2
        rail_lo = 0.02 * vdd
        rail_hi = vdd - 0.02 * vdd
        cases, expected = [], []
        for idx in range(4):
            for bad in (math.nextafter(rail_lo, 0.0),
                        math.nextafter(rail_hi, math.inf)):
                nodes = ["0.6", "0.6", "0.6", "0.6"]
                nodes[idx] = repr(bad)
                # Same isolation as the inclusive-boundary test: for the
                # vout slot, vcm rides along so the mid-rail gap passes and
                # the rail window alone is what rejects.
                vcm = nodes[3] if idx == 3 else "0.6"
                cases.append(("1.2", vcm, nodes[3], nodes[0], nodes[1],
                              nodes[2]))
                expected.append("0")
        self.assertEqual(self.fx.run_cases(cases), expected)

    def test_nominal_midrail_point_passes(self):
        # Values taken from a committed open-loop-ac record row.
        self.assertEqual(
            self.fx.run_cases([("1.2", "0.6", "0.524893", "0.521811",
                                "0.322482", "0.0676477")]), ["1"])

    def test_output_midrail_gap_rejected(self):
        # Vout pushed past 15% of VDD away from Vcm -> non-regulating point.
        self.assertEqual(
            self.fx.run_cases([("1.2", "0.6", "0.9", "0.521811", "0.322482",
                                "0.0676477")]), ["0"])

    def test_wrong_argument_count_exits_3(self):
        r = self.fx.run_one("1.2", "0.6", "0.6", "0.6", "0.6")
        self.assertEqual(r.returncode, 3)
        self.assertIn("sg13g2_op_sanity", r.stderr)
        self.assertIn("got 5 argument(s)", r.stderr)


class ReplayCommittedRecords(unittest.TestCase):
    """The helper reproduces each committed record's op_pass (#366 AC 1)."""

    @staticmethod
    def _replay_record(bench, columns):
        """Newest committed CSV whose header carries every needed column.

        open-loop-ac resolves to the superseded record
        (20260910-221601-22feaba): its successor (20261015-103057-895d555,
        post-#241 curation) commits only the spec-bound columns and drops
        the per-point op_pass/node voltages, so there is nothing in it to
        replay against. Both records were gated by the same runner code
        this issue refactors, so the older one is the bench's committed
        evidence of what the gate admitted.
        """
        required = set(columns)
        for path in sorted((SIM_DIR / bench / "records").glob("*.csv"),
                           reverse=True):
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []
                if not required.issubset(header):
                    continue
                return path, list(reader)
        raise AssertionError(f"{bench}: no committed record with {sorted(required)}")

    def test_committed_record_op_pass_column_is_reproduced_exactly(self):
        for bench, (cv, cm, co, c1, c2, c3, guard) in REPLAY_BENCHES.items():
            with self.subTest(bench=bench):
                guard_name, guard_cols = (None, ()) if guard is None else guard
                columns = [cv, cm, co, c1, c2, c3, "op_pass"] + list(guard_cols)
                path, rows = self._replay_record(bench, columns)
                self.assertTrue(rows, f"{bench}: {path.name} has no rows")
                with tempfile.TemporaryDirectory() as d:
                    fx = Fixture(Path(d))
                    cases = [tuple(r[c] for c in (cv, cm, co, c1, c2, c3,
                                                  *guard_cols)) for r in rows]
                    got = fx.run_cases(cases, guard=guard_name)
                want = [r["op_pass"] for r in rows]
                self.assertEqual(len(got), len(want))
                for i, (g, w) in enumerate(zip(got, want)):
                    self.assertEqual(
                        g, w,
                        f"{bench} {path.name} row {i} "
                        f"({rows[i]['point_id']}): helper said {g}, "
                        f"record has {w}")


class SharedPredicateAgreement(unittest.TestCase):
    """op_sane (the module) and sg13g2_op_sanity (the shell helper) decide
    identical verdicts on one shared case table (#380). The bash helper's
    inline python3 copy is gone; this pins the delegation to the real
    module the fixture copies, on the same boundary doubles the truth
    table uses."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _case_table():
        """(vdd, vcm, vout, vd1, vd2, vtail) rows as exact-double reprs:
        the committed nominal admit, the inclusive gap edge, rail edges on
        each of the four checked slots, and the rejects just past each."""
        vdd = "1.2"
        fd = float(vdd)
        tol = float("0.15") * fd
        rail_lo = float("0.02") * fd
        rail_hi = fd - float("0.02") * fd
        cases = [
            ("1.2", "0.6", "0.524893", "0.521811", "0.322482", "0.0676477"),
            # gap boundary == the same double, from both sides
            (vdd, "0.0", repr(tol), "0.6", "0.6", "0.6"),
            (vdd, "0.0", repr(-tol), "0.6", "0.6", "0.6"),
            (vdd, "0.0", repr(math.nextafter(tol, math.inf)),
             "0.6", "0.6", "0.6"),
        ]
        for idx in range(4):  # (vd1, vd2, vtail, vout)
            for boundary in (rail_lo, rail_hi):
                nodes = ["0.6", "0.6", "0.6", "0.6"]
                nodes[idx] = repr(boundary)
                vcm = nodes[3] if idx == 3 else "0.6"
                cases.append((vdd, vcm, nodes[3], nodes[0], nodes[1],
                              nodes[2]))
                for side in (0.0, math.inf):
                    nodes[idx] = repr(math.nextafter(boundary, side))
                    vcm = nodes[3] if idx == 3 else "0.6"
                    cases.append((vdd, vcm, nodes[3], nodes[0], nodes[1],
                                  nodes[2]))
        return cases

    def test_module_and_shell_agree_on_the_case_table(self):
        cases = self._case_table()
        shell = self.fx.run_cases(cases)
        module = ["1" if op_sanity.op_sane(*(float(c) for c in case)) else "0"
                  for case in cases]
        self.assertEqual(shell, module)
        # sanity: the table really exercises both verdicts
        self.assertIn("1", shell)
        self.assertIn("0", shell)

    def test_offgrid_vdd_pins_the_shared_spelling(self):
        # 0.98*VDD and VDD-0.02*VDD are not the same double off the project
        # grid (SG13G2_VDDS=(1.08 1.20 1.32), where they are bit-identical).
        # At VDD=1.2021 the shared edge sits ABOVE 0.98*VDD, so a node
        # exactly at the shared edge is admitted by the folded definition
        # and would have been REJECTED by the old 0.98*VDD spelling the
        # input-offset copy carried (#380). Module and helper must both
        # follow the shared spelling.
        vdd = "1.2021"
        fd = float(vdd)
        rail_hi = fd - float("0.02") * fd
        self.assertNotEqual(0.98 * fd, rail_hi)
        self.assertGreater(rail_hi, 0.98 * fd)  # old spelling would reject
        case = (vdd, "0.6", "0.6", repr(rail_hi), "0.6", "0.6")
        self.assertEqual(self.fx.run_cases([case]), ["1"])
        self.assertTrue(op_sanity.op_sane(*(float(c) for c in case)))
        # one double past the shared edge is outside for both
        past = repr(math.nextafter(rail_hi, math.inf))
        case_past = (vdd, "0.6", "0.6", past, "0.6", "0.6")
        self.assertEqual(self.fx.run_cases([case_past]), ["0"])
        self.assertFalse(op_sanity.op_sane(*(float(c) for c in case_past)))

    def test_rail_and_mid_fracs_are_live_parameters(self):
        # cmrr-mismatch passes OP_RAIL_FRAC/OP_MID_FRAC through to the
        # predicate (run_cmrr_mismatch_mc.sh); the fold (#380) must keep
        # them parameters, not literals. A node admitted at the default
        # 0.02 edge is excluded at rail_frac=0.1; likewise the gap edge.
        vdd = 1.2
        rail_hi = vdd - 0.02 * vdd
        self.assertTrue(op_sanity.op_sane(vdd, 0.6, 0.6, rail_hi, 0.6, 0.6))
        self.assertFalse(
            op_sanity.op_sane(vdd, 0.6, 0.6, rail_hi, 0.6, 0.6, rail_frac=0.1))
        gap_edge = 0.15 * vdd
        self.assertTrue(op_sanity.op_sane(vdd, 0.0, gap_edge, 0.6, 0.6, 0.6))
        self.assertFalse(
            op_sanity.op_sane(vdd, 0.0, gap_edge, 0.6, 0.6, 0.6, mid_frac=0.1))


def _load_mc_samples():
    """Load the bench's shared parser module by path (its directory is not
    a package); loading it also executes its own sim/tools sys.path wiring
    for op_sanity, the same path make_draws_csv.sh's python3 -I heredoc
    exercises."""
    spec = importlib.util.spec_from_file_location(
        "mc_samples", SIM_DIR / "cmrr-mismatch" / "mc_samples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ReplayCmrrMismatchDraws(unittest.TestCase):
    """The shared predicate reproduces the committed cmrr-mismatch campaign's
    per-draw verdicts (#380). The draws CSV carries no node voltages -- only
    status/fail_reason -- so the replay reads them from the committed
    per-point samples files via mc_samples.read_samples_raw, exactly as the
    two folded sites do."""

    STEM = "20260921-172304-65f5fb4"
    PLATEAU_TOL_DB = 0.05  # the script's PLATEAU_TOL_DB default

    @classmethod
    def setUpClass(cls):
        cls.mc = _load_mc_samples()
        rec = SIM_DIR / "cmrr-mismatch" / "records" / f"{cls.STEM}.csv"
        cls.summary = {r["point_id"]: r for r in csv.DictReader(open(rec, newline=""))}
        draws = SIM_DIR / "cmrr-mismatch" / "records" / f"{cls.STEM}-draws.csv"
        cls.rows = list(csv.DictReader(open(draws, newline="")))

    def test_every_draw_verdict_is_reproduced_exactly(self):
        self.assertEqual(len(self.rows), 13500)
        samples = {}
        for r in self.rows:
            pid = r["point_id"]
            if pid not in samples:
                path = (SIM_DIR / "cmrr-mismatch" / "corners" / self.STEM /
                        f"{pid}_mc_samples.txt")
                samples[pid] = self.mc.read_samples_raw(str(path))
            n, ops, acs, _toks = samples[pid]
            k = int(r["draw_index"])
            self.assertLess(k, n, f"{pid}: draw {k} out of range")
            vout, vd1, vd2, vtail = ops[k][:4]
            vdd = float(r["vdd_v"])
            vcm = float(self.summary[pid]["vcm_v"])
            a10, a01, _a1k = acs[k]
            if not op_sanity.op_sane(vdd, vcm, vout, vd1, vd2, vtail):
                reason = "op_fail"
            elif abs(a10 - a01) > self.PLATEAU_TOL_DB:
                reason = "plateau_fail"
            else:
                reason = ""
            with self.subTest(point_id=pid, draw=k):
                self.assertEqual(r["fail_reason"], reason)
                self.assertEqual(r["status"], "EXCLUDED" if reason else "PASS")
        # The committed campaign is all-accept (curated measurement), so
        # replay alone pins no rejection -- that half lives in the truth
        # table above. Assert it explicitly so a future divergent record
        # cannot silently weaken this control's meaning.
        self.assertTrue(all(r["status"] == "PASS" for r in self.rows))


if __name__ == "__main__":
    unittest.main()

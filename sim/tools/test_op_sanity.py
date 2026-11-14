"""Offline controls for the shared sg13g2_op_sanity gate in sim/preflight.sh.

Issue #366: the per-point DC operating-point sanity gate (`op_pass`) was
byte-identical inline `python3 -c` in four sim/*/run_*.sh runners
(open-loop-ac, slew-rate, cmrr-psrr, input-noise -- the last with an extra
closed-loop-gain band-edge guard). op_pass is an evidence-admission gate
(signoff/characterization/generate.py refuses a dc_continuity point whose
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
source-time environment every real runner has), so each fixture builds a
fake install and stubs, mirroring test_env_drift_lifecycle.py. No ngspice
solve, no PDK content, and no committed record is touched: records are read
from the repo read-only.
"""
import csv
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SIM_DIR = TOOLS_DIR.parent
REPO_ROOT = SIM_DIR.parent
PREFLIGHT = SIM_DIR / "preflight.sh"

# The four benches the duplicated gate was removed from, with the record
# columns each one's op_pass was computed from. input-noise additionally
# gates on its closed-loop gain at the two band edges (clgain_100hz /
# clgain_1mhz = glo/ghi in the runner).
REPLAY_BENCHES = {
    "open-loop-ac": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                     "vtail_dc_v", None),
    "slew-rate": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                  "vtail_dc_v", None),
    "cmrr-psrr": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                  "vtail_dc_v", None),
    "input-noise": ("vdd_v", "vcm_v", "vout_dc_v", "vd1_dc_v", "vd2_dc_v",
                    "vtail_dc_v", ("clgain_100hz", "clgain_1mhz")),
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
# paths. Mirrors test_env_drift_lifecycle.py's OpenLoopRunner environment:
# the real preflight.sh runs its source-time guards against a fake install,
# then the requested mode drives the real helper.
#
# MODE=sanity      : batch of "vdd vcm vout vd1 vd2 vtail" lines -> helper.
# MODE=sanity+clgain: batch of "... vtail glo ghi" lines -> helper AND the
#                    band-edge gain guard, composed exactly as
#                    run_noise_sweep.sh composes it at its call site.
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
    """A throwaway tree that can source the REAL sim/preflight.sh."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sim = root / "sim"
        self.sim.mkdir(parents=True)
        for name in ("preflight.sh", "env.sh", "env-identity.sh",
                     "ac-join.sh", "record-paths.sh", "pdk.json"):
            shutil.copy2(SIM_DIR / name, self.sim / name)
        tools = self.sim / "tools"
        tools.mkdir()
        self._write_exec(tools / "build-osdi.sh", "#!/usr/bin/env bash\nexit 0\n")
        # Only ${PDK}/libs.tech/ngspice must exist for the source-time guard;
        # nothing reads PDK content on this path (no solver, no OSDI load).
        # The psp103.osdi placeholder keeps env.sh's WARN-only "models not
        # built" banner quiet.
        osdi = root / "ihp-sg13g2" / "libs.tech" / "ngspice" / "osdi"
        osdi.mkdir(parents=True)
        (osdi / "psp103.osdi").write_text("", encoding="utf-8")
        self.bin = root / "bin"
        self.bin.mkdir()
        self._write_exec(self.bin / "ngspice", STUB_NGSPICE)
        self._write_exec(root / "setup.sh",
                         setup_script(self.sim, self.root, self.bin))
        self.driver = root / "driver.sh"
        self._write_exec(self.driver, DRIVER)

    @staticmethod
    def _write_exec(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def _env(self, mode: str) -> dict:
        env = dict(os.environ)
        env["SETUP_SH"] = str(self.root / "setup.sh")
        env["MODE"] = mode
        return env

    def run_cases(self, rows, clgain=False):
        """Feed 'vdd vcm vout vd1 vd2 vtail [glo ghi]' lines; get '0'/'1's."""
        stdin = "".join(" ".join(str(f) for f in row) + "\n" for row in rows)
        r = subprocess.run(
            ["bash", str(self.driver)], input=stdin,
            capture_output=True, text=True, timeout=60,
            env=self._env("sanity+clgain" if clgain else "sanity"))
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
        for bench, (cv, cm, co, c1, c2, c3, clgain) in REPLAY_BENCHES.items():
            with self.subTest(bench=bench):
                columns = [cv, cm, co, c1, c2, c3, "op_pass"]
                if clgain is not None:
                    columns += list(clgain)
                path, rows = self._replay_record(bench, columns)
                self.assertTrue(rows, f"{bench}: {path.name} has no rows")
                with tempfile.TemporaryDirectory() as d:
                    fx = Fixture(Path(d))
                    if clgain is None:
                        cases = [(r[cv], r[cm], r[co], r[c1], r[c2], r[c3])
                                 for r in rows]
                        got = fx.run_cases(cases)
                    else:
                        cases = [(r[cv], r[cm], r[co], r[c1], r[c2], r[c3],
                                  r[clgain[0]], r[clgain[1]]) for r in rows]
                        got = fx.run_cases(cases, clgain=True)
                want = [r["op_pass"] for r in rows]
                self.assertEqual(len(got), len(want))
                for i, (g, w) in enumerate(zip(got, want)):
                    self.assertEqual(
                        g, w,
                        f"{bench} {path.name} row {i} "
                        f"({rows[i]['point_id']}): helper said {g}, "
                        f"record has {w}")


if __name__ == "__main__":
    unittest.main()

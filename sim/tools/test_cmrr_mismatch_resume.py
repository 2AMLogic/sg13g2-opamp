"""Offline controls for the cmrr-mismatch campaign manifest (issue #163).

run_cmrr_mismatch_mc.sh resumes an interrupted campaign by reusing its
completed sample files, DUT snapshot and saved pilot. These controls show
that a resume is only allowed under the campaign's ORIGINAL inputs:

  * a fresh campaign publishes corners/<id>/campaign.manifest before its
    first simulation;
  * an unchanged-input resume passes and restores the saved pilot sigma;
  * a changed seed, template, DUT, joined CSV, solver version or PDK model
    library refuses (exit 3) and leaves every file byte-identical;
  * a legacy incomplete campaign without a manifest refuses with new-id
    instructions; a finalized record stays refused and untouched;
  * relocating the checkout does not change the experiment.

Each test builds a throwaway repo tree under a TemporaryDirectory and drives
the REAL sim/record-paths.sh, sim/cmrr-mismatch/campaign-guard.sh and
campaign_manifest.py from bash, with the runner's real knob defaults and
preflight.sh's real NGSPICE_VERSION normalization (both extracted from
those files) and a stub `ngspice` that only answers `-v`. No PDK, OSDI
build, ngspice run or klt is needed, and nothing under the real checkout is
written.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
BENCH = SIM_DIR / "cmrr-mismatch"
RUNNER = BENCH / "run_cmrr_mismatch_mc.sh"
GUARD = BENCH / "campaign-guard.sh"
TOOL = BENCH / "campaign_manifest.py"
RECORD_PATHS = SIM_DIR / "record-paths.sh"
PREFLIGHT = SIM_DIR / "preflight.sh"
COMMITTED_PILOT = BENCH / "records" / "20260921-172304-65f5fb4.pilot.txt"

RID = "20260101-000000-abc1234"
AC_ID = "20260910-221601-22feaba"     # ids the committed pilot names, so the
CMRR_ID = "20260921-151815-707b34c"   # committed pilot file is a valid fixture


def _runner_knob_lines():
    """The runner's own `NAME="${NAME:-default}"` knob lines, verbatim."""
    pat = re.compile(r'^((?:MC|NEGCTL|OP|PLATEAU)_[A-Z_]+)="\$\{\1:-[^}]*\}"', re.M)
    lines = [m.group(0) for m in pat.finditer(RUNNER.read_text())]
    assert len(lines) == 10, lines
    return "\n".join(lines)


def _ngspice_version_line():
    m = re.search(r'^NGSPICE_VERSION=.*$', PREFLIGHT.read_text(), re.M)
    assert m, "preflight.sh no longer sets NGSPICE_VERSION on one line"
    return m.group(0)


# Mirrors the runner's order: knobs -> latest-record resolution -> record
# paths -> guard. MODE=work then stands in for the simulation phases (a
# partial campaign); MODE=resume marks that the run got past the guard.
DRIVER = r"""
set -euo pipefail
REPO_ROOT="$1"
MODE="$2"
SCRIPT_DIR="${REPO_ROOT}/sim/cmrr-mismatch"
SIM_DIR="${REPO_ROOT}/sim"
_sg13g2_preflight_self=run_cmrr_mismatch_mc.sh
_cmrr_mc_self=run_cmrr_mismatch_mc.sh
git() { echo abc1234; }
# shellcheck source=/dev/null
source "${RECORD_PATHS}"
@@NGSPICE_VERSION_LINE@@
@@KNOBS@@
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
TEMPS=(-40 27 125)
VDDS=(1.08 1.20 1.32)
CL_F="2e-12"
DUT_NETLIST_SRC="${REPO_ROOT}/design/netlist/opamp_core.spice"
latest() { find "$1" -maxdepth 1 -name '*.csv' | sort | tail -n 1; }
AC_LATEST_CSV="$(latest "${SIM_DIR}/open-loop-ac/records")"
CMRR_LATEST_CSV="$(latest "${SIM_DIR}/cmrr-psrr/records")"
sg13g2_preflight_record_paths --resumable
DUT_NETLIST_SNAPSHOT="${SNAPSHOTS_OUT}/opamp_core.spice"
pilot_sigma_lin="unset"
MC_N_EFFECTIVE="${MC_N_FLOOR}"
# shellcheck source=/dev/null
source "${GUARD}"
cmrr_mc_campaign_guard
echo "RESUMED=${RECORD_RESUMED}"
echo "PILOT_RESTORED=${PILOT_RESTORED}"
echo "PILOT_SIGMA=${pilot_sigma_lin}"
echo "MC_N_EFFECTIVE=${MC_N_EFFECTIVE}"
echo "AC_RECORD_CSV=${AC_RECORD_CSV}"
echo "AC_RECORD_ID=${AC_RECORD_ID}"
case "${MODE}" in
  work)
    printf 'OP 0 1 2 3 4 5 6\nAC 0 -1 -1 -1\n' > "${CORNERS_OUT}/mos_tt_-40C_1.08V_mc_samples.txt"
    printf 'OP 0 1 2 3 4 5 6\n' > "${CORNERS_OUT}/mos_tt_-40C_1.20V_mc_samples.txt"
    cp "${PILOT_FIXTURE}" "${RECORDS_DIR}/${RECORD_ID}.pilot.txt"
    ;;
  resume)
    echo "past the guard" > "${CORNERS_OUT}/resumed.marker"
    ;;
esac
""".replace("@@NGSPICE_VERSION_LINE@@", _ngspice_version_line()) \
   .replace("@@KNOBS@@", _runner_knob_lines())

NGSPICE_STUB = """#!/bin/sh
printf '******\\n** %s : Circuit level simulation program\\n' "${STUB_NGSPICE_VERSION:-ngspice-46}"
"""


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.repo = self.root / "repo"
        b = self.repo / "sim" / "cmrr-mismatch"
        (b / "testbench").mkdir(parents=True)
        (b / "testbench" / "tb_cmrr_mc.spice.tmpl").write_text("* tb template v1\n")
        for sub in ("corners", "netlist-snapshots", "records"):
            (b / sub).mkdir()
        net = self.repo / "design" / "netlist"
        net.mkdir(parents=True)
        (net / "opamp_core.spice").write_text("* opamp_core v1\n")
        ac = self.repo / "sim" / "open-loop-ac" / "records"
        ac.mkdir(parents=True)
        (ac / f"{AC_ID}.csv").write_text("point_id,av0_db\nmos_tt_27C_1.20V,41.95\n")
        cm = self.repo / "sim" / "cmrr-psrr" / "records"
        cm.mkdir(parents=True)
        (cm / f"{CMRR_ID}.csv").write_text("point_id,acm0_db\nmos_tt_27C_1.20V,6.63\n")
        self.pdk_root = self.root / "pdk"
        models = self.pdk_root / "ihp-sg13g2" / "libs.tech" / "ngspice" / "models"
        models.mkdir(parents=True)
        (models / "cornerMOSlv.lib").write_text("* corners\n")
        (models / "sg13g2_moslv_mod_mismatch.lib").write_text("* agauss wrappers\n")
        (self.pdk_root / "ihp-sg13g2" / ".fetched-version").write_text("0.3.0\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        stub = self.bin / "ngspice"
        stub.write_text(NGSPICE_STUB)
        stub.chmod(0o755)
        self.driver = self.root / "driver.sh"
        self.driver.write_text(DRIVER)

    @property
    def bench(self):
        return self.repo / "sim" / "cmrr-mismatch"

    @property
    def models(self):
        return self.pdk_root / "ihp-sg13g2" / "libs.tech" / "ngspice" / "models"

    def run(self, mode, repo=None, **extra):
        env = {k: v for k, v in os.environ.items()
               if not re.match(r"^(MC_|NEGCTL_|OP_|PLATEAU_|AC_RECORD|CMRR_RECORD|RECORD_ID$)", k)}
        env.update(PATH=f"{self.bin}{os.pathsep}{env.get('PATH', '')}",
                   PDK_ROOT=str(self.pdk_root), PDK="ihp-sg13g2",
                   RECORD_ID=RID, RECORD_PATHS=str(RECORD_PATHS), GUARD=str(GUARD),
                   PILOT_FIXTURE=str(COMMITTED_PILOT))
        env.update(extra)
        return subprocess.run(["bash", str(self.driver), str(repo or self.repo), mode],
                              env=env, capture_output=True, text=True, timeout=60)

    def partial_campaign(self):
        r = self.run("work")
        assert r.returncode == 0, r.stderr
        return r

    def snapshot(self, repo=None):
        files = {}
        base = (repo or self.repo) / "sim" / "cmrr-mismatch"
        for p in sorted(base.rglob("*")):
            if p.is_file():
                files[str(p.relative_to(base))] = p.read_bytes()
        return files


def _kv(stdout):
    return dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)


class FreshCampaign(unittest.TestCase):
    def test_manifest_published_before_simulation_and_relocatable(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run("none")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(_kv(r.stdout)["RESUMED"], "0")
            man = fx.bench / "corners" / RID / "campaign.manifest"
            self.assertTrue(man.is_file())
            text = man.read_text()
            self.assertNotIn(str(fx.root), text)  # no absolute prefixes
            for line in ("dut_netlist_src: design/netlist/opamp_core.spice",
                         "testbench_template: sim/cmrr-mismatch/testbench/tb_cmrr_mc.spice.tmpl",
                         f"ac_record_csv: sim/open-loop-ac/records/{AC_ID}.csv",
                         f"cmrr_record_csv: sim/cmrr-psrr/records/{CMRR_ID}.csv",
                         "mc_seed_base: 260000", "mc_seed_alt: 990000",
                         "mc_n_floor: 300", "ngspice_version: ngspice-46",
                         "grid_corners: mos_tt mos_ss mos_ff mos_sf mos_fs",
                         "cl_f: 2e-12", "pdk_fetched_version: 0.3.0",
                         "pdk_ngspice_model_libs_count: 2"):
                self.assertIn(line + "\n", text)
            keys = [ln.split(":", 1)[0] for ln in text.splitlines()[1:]]
            self.assertEqual(keys, sorted(keys))
            snap = fx.bench / "netlist-snapshots" / RID / "opamp_core.spice"
            self.assertEqual(snap.read_text(), "* opamp_core v1\n")
            self.assertIn("dut_netlist_snapshot_sha256: ", text)
            self.assertNotIn("dut_netlist_snapshot_sha256: missing", text)

    def test_manifest_is_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            man = Path(d) / "campaign.manifest"
            man.write_text("# x\na: 1\n")
            r = subprocess.run(["python3", "-I", str(TOOL), "publish", str(man)],
                               input="# y\na: 2\n", capture_output=True, text=True)
            self.assertEqual(r.returncode, 3)
            self.assertIn("immutable", r.stderr)
            self.assertEqual(man.read_text(), "# x\na: 1\n")
            self.assertEqual(sorted(os.listdir(d)), ["campaign.manifest"])


class UnchangedResume(unittest.TestCase):
    def test_resume_passes_and_restores_pilot_sigma(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.partial_campaign()
            r = fx.run("resume")
            self.assertEqual(r.returncode, 0, r.stderr)
            kv = _kv(r.stdout)
            self.assertEqual(kv["RESUMED"], "1")
            self.assertEqual(kv["PILOT_RESTORED"], "1")
            # the committed pilot's value, not "unset"
            self.assertEqual(kv["PILOT_SIGMA"], "0.280544")
            self.assertEqual(kv["MC_N_EFFECTIVE"], "300")
            self.assertTrue((fx.bench / "corners" / RID / "resumed.marker").exists())

    def test_resume_ignores_a_newer_joined_record(self):
        # A record committed after the campaign began must not switch the
        # join: the resume uses the manifest's path.
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.partial_campaign()
            newer = fx.repo / "sim" / "open-loop-ac" / "records" / "20991231-000000-fffffff.csv"
            newer.write_text("point_id,av0_db\nmos_tt_27C_1.20V,99\n")
            r = fx.run("resume")
            self.assertEqual(r.returncode, 0, r.stderr)
            kv = _kv(r.stdout)
            self.assertEqual(kv["AC_RECORD_ID"], AC_ID)
            self.assertTrue(kv["AC_RECORD_CSV"].endswith(f"{AC_ID}.csv"))

    def test_relocated_checkout_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.partial_campaign()
            moved = fx.root / "elsewhere" / "deeper" / "repo"
            moved.parent.mkdir(parents=True)
            shutil.move(str(fx.repo), str(moved))
            before = fx.snapshot(moved)
            r = fx.run("resume", repo=moved)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(_kv(r.stdout)["PILOT_SIGMA"], "0.280544")
            after = fx.snapshot(moved)
            after.pop(f"corners/{RID}/resumed.marker")
            self.assertEqual(after, before)

    def test_relocated_pdk_install_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.partial_campaign()
            moved = fx.root / "other-pdk"
            shutil.move(str(fx.pdk_root), str(moved))
            r = fx.run("resume", PDK_ROOT=str(moved))
            self.assertEqual(r.returncode, 0, r.stderr)


class ChangedInputRefuses(unittest.TestCase):
    """Each mutation must refuse BEFORE anything is modified."""

    def _assert_refused(self, fx, r, *needles):
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn(f"refusing to resume record {RID}", r.stderr)
        self.assertIn("unset RECORD_ID", r.stderr)
        for n in needles:
            self.assertIn(n, r.stderr)
        self.assertNotIn("RESUMED=", r.stdout)

    def _check(self, mutate, *needles, **env):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.partial_campaign()
            mutate(fx)
            before = fx.snapshot()
            r = fx.run("resume", **env)
            self._assert_refused(fx, r, *needles)
            self.assertEqual(fx.snapshot(), before)  # samples/snapshot/pilot/manifest byte-identical

    def test_changed_seed_base(self):
        self._check(lambda fx: None, "mc_seed_base: stored=260000 current=260001",
                    MC_SEED_BASE="260001")

    def test_changed_alt_seed(self):
        self._check(lambda fx: None, "mc_seed_alt: stored=990000 current=1", MC_SEED_ALT="1")

    def test_changed_n_floor(self):
        self._check(lambda fx: None, "mc_n_floor: stored=300 current=500", MC_N_FLOOR="500")

    def test_changed_tolerance(self):
        self._check(lambda fx: None, "negctl_tol_db: stored=5e-3 current=1", NEGCTL_TOL_DB="1")

    def test_changed_template_bytes(self):
        self._check(lambda fx: (fx.bench / "testbench" / "tb_cmrr_mc.spice.tmpl")
                    .write_text("* tb template v2\n"), "testbench_template_sha256: stored=")

    def test_changed_dut_bytes(self):
        self._check(lambda fx: (fx.repo / "design" / "netlist" / "opamp_core.spice")
                    .write_text("* opamp_core v2\n"), "dut_netlist_src_sha256: stored=")

    def test_changed_snapshot_bytes(self):
        self._check(lambda fx: (fx.bench / "netlist-snapshots" / RID / "opamp_core.spice")
                    .write_text("* tampered\n"), "dut_netlist_snapshot_sha256: stored=")

    def test_changed_ac_csv_bytes(self):
        self._check(lambda fx: (fx.repo / "sim" / "open-loop-ac" / "records" / f"{AC_ID}.csv")
                    .write_text("point_id,av0_db\nmos_tt_27C_1.20V,40.00\n"),
                    "ac_record_csv_sha256: stored=")

    def test_changed_cmrr_csv_bytes(self):
        self._check(lambda fx: (fx.repo / "sim" / "cmrr-psrr" / "records" / f"{CMRR_ID}.csv")
                    .write_text("point_id,acm0_db\nmos_tt_27C_1.20V,7.00\n"),
                    "cmrr_record_csv_sha256: stored=")

    def test_explicit_different_joined_record(self):
        def add(fx):
            (fx.repo / "sim" / "open-loop-ac" / "records" / "20991231-000000-fffffff.csv") \
                .write_text("point_id,av0_db\nmos_tt_27C_1.20V,99\n")
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.partial_campaign()
            add(fx)
            before = fx.snapshot()
            r = fx.run("resume", AC_RECORD_CSV=str(
                fx.repo / "sim" / "open-loop-ac" / "records" / "20991231-000000-fffffff.csv"))
            self._assert_refused(fx, r, "ac_record_csv: stored=sim/open-loop-ac/records/"
                                 f"{AC_ID}.csv current=sim/open-loop-ac/records/20991231-000000-fffffff.csv")
            self.assertEqual(fx.snapshot(), before)

    def test_missing_joined_csv(self):
        self._check(lambda fx: (fx.repo / "sim" / "cmrr-psrr" / "records" / f"{CMRR_ID}.csv").unlink(),
                    "cmrr_record_csv_sha256: stored=", "current=missing")

    def test_changed_solver_version(self):
        self._check(lambda fx: None, "ngspice_version: stored=ngspice-46 current=ngspice-47",
                    STUB_NGSPICE_VERSION="ngspice-47")

    def test_changed_model_library(self):
        self._check(lambda fx: (fx.models / "sg13g2_moslv_mod_mismatch.lib")
                    .write_text("* agauss wrappers, edited\n"),
                    "pdk_ngspice_model_libs_sha256: stored=")

    def test_added_model_library(self):
        self._check(lambda fx: (fx.models / "extra.lib").write_text("* new\n"),
                    "pdk_ngspice_model_libs_count: stored=2 current=3")

    def test_tampered_pilot(self):
        def tamper(fx):
            p = fx.bench / "records" / f"{RID}.pilot.txt"
            p.write_text(p.read_text().replace("seed_base: 260000", "seed_base: 123"))
        self._check(tamper, "saved pilot does not match", "pilot seed_base: stored=123 current=260000")

    def test_pilot_without_sigma(self):
        def strip(fx):
            p = fx.bench / "records" / f"{RID}.pilot.txt"
            p.write_text("".join(ln for ln in p.read_text().splitlines(True)
                                 if not ln.startswith("pilot_acm_sigma_max_linear")))
        self._check(strip, "pilot_acm_sigma_max_linear: unparseable")


class LegacyAndFinalized(unittest.TestCase):
    def _legacy(self, fx):
        c = fx.bench / "corners" / RID
        c.mkdir()
        (c / "mos_tt_-40C_1.08V_mc_samples.txt").write_text("OP 0 1 2 3 4 5 6\n")
        s = fx.bench / "netlist-snapshots" / RID
        s.mkdir()
        (s / "opamp_core.spice").write_text("* opamp_core v1\n")
        shutil.copy(COMMITTED_PILOT, fx.bench / "records" / f"{RID}.pilot.txt")

    def test_legacy_incomplete_campaign_refuses_with_new_id_instructions(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            self._legacy(fx)
            before = fx.snapshot()
            r = fx.run("resume")
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertIn("it has no campaign manifest", r.stderr)
            self.assertIn("legacy", r.stderr)
            self.assertIn("unset RECORD_ID (a fresh run mints a new id)", r.stderr)
            self.assertEqual(fx.snapshot(), before)

    def test_finalized_record_still_refused_and_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.partial_campaign()
            (fx.bench / "records" / f"{RID}.csv").write_text("final\n")
            (fx.bench / "records" / f"{RID}.md").write_text("final\n")
            before = fx.snapshot()
            r = fx.run("resume")
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertIn("finalized", r.stderr)
            self.assertEqual(fx.snapshot(), before)


class RunnerWiring(unittest.TestCase):
    """Static checks that the runner uses the guard the tests above exercise."""

    def setUp(self):
        self.text = RUNNER.read_text()

    def test_guard_runs_before_any_simulation_or_snapshot(self):
        guard = self.text.index("\ncmrr_mc_campaign_guard\n")
        first_call = re.search(r'^\s*(?:if !? *)?run_deck "\$', self.text, re.M)
        self.assertIsNotNone(first_call)
        self.assertLess(guard, first_call.start())
        self.assertLess(self.text.index("sg13g2_preflight_record_paths --resumable"), guard)
        # the snapshot copy lives only in the guard now
        self.assertNotIn('cp "${DUT_NETLIST_SRC}"', self.text)
        # the pilot is restored by the guard, not re-read piecemeal
        self.assertNotIn("sed -n 's/^mc_n_effective: //p'", self.text)
        self.assertIn('if [[ "${PILOT_RESTORED}" != "1" ]]; then', self.text)

    def test_knob_defaults_unchanged(self):
        self.assertEqual(_runner_knob_lines().splitlines(), [
            'MC_N_FLOOR="${MC_N_FLOOR:-300}"',
            'MC_TARGET_SIGMA_RE="${MC_TARGET_SIGMA_RE:-0.05}"',
            'MC_NEGCTL_N="${MC_NEGCTL_N:-3}"',
            'MC_SEED_BASE="${MC_SEED_BASE:-260000}"',
            'MC_SEED_ALT="${MC_SEED_ALT:-990000}"',
            'NEGCTL_TOL_DB="${NEGCTL_TOL_DB:-5e-3}"',
            'NEGCTL_TOL_V="${NEGCTL_TOL_V:-5e-4}"',
            'OP_RAIL_FRAC="${OP_RAIL_FRAC:-0.02}"',
            'OP_MID_FRAC="${OP_MID_FRAC:-0.15}"',
            'PLATEAU_TOL_DB="${PLATEAU_TOL_DB:-0.05}"',
        ])

    def test_manifest_binds_every_knob(self):
        guard = GUARD.read_text()
        for line in _runner_knob_lines().splitlines():
            name = line.split("=", 1)[0]
            self.assertIn(f'="${{{name}}}"', guard, name)


if __name__ == "__main__":
    unittest.main()

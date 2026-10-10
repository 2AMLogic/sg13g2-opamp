"""Offline controls for the record-id reservation in sim/record-paths.sh.

Issue #140: sg13g2_preflight_record_paths must reserve a record id
atomically before any run-owned output is written, refuse a colliding id
without touching the existing record, and -- for the resumable
cmrr-mismatch campaign -- continue an incomplete record but refuse to
resume one whose CSV/Markdown evidence is already finalized.

Every test builds a throwaway experiment tree under a TemporaryDirectory
and drives the real sim/record-paths.sh from bash. `date` and `git` are
shadowed by bash functions inside the driver, which is how a "forced
identical timestamp and commit" is produced without a production knob.
No PDK, OSDI build, ngspice or klt is needed.
"""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
RECORD_PATHS = SIM_DIR / "record-paths.sh"

TS = "20260101-000000"
SHA = "abc1234"
RID = f"{TS}-{SHA}"

# The driver mimics a caller: source the helper, reserve, then (only if the
# reservation returned) write outputs the way run_slew_sweep.sh does --
# snapshot copy, per-corner log, CSV.raw moved onto CSV_OUT, truncating
# redirect onto MD_OUT. A refusal must therefore leave the tree untouched.
DRIVER = r"""
set -euo pipefail
SCRIPT_DIR="$1"; shift
REPO_ROOT="$1"; shift
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
tag="$1"; shift
date() { echo "${FAKE_TS}"; }
git() { echo "${FAKE_SHA}"; }
if [[ -n "${WAIT_FOR:-}" ]]; then
  while [[ ! -e "${WAIT_FOR}" ]]; do sleep 0.005; done
fi
# shellcheck source=/dev/null
source "${RECORD_PATHS}"
sg13g2_preflight_record_paths "$@"
echo "RECORD_ID=${RECORD_ID}"
echo "RECORD_RESUMED=${RECORD_RESUMED}"
[[ -n "${NO_WRITE:-}" ]] && exit 0
echo "snapshot ${tag}" > "${SNAPSHOTS_OUT}/opamp_core.spice"
echo "log ${tag}" > "${CORNERS_OUT}/p0.log"
echo "csv ${tag}" > "${CSV_OUT}.raw"
mv "${CSV_OUT}.raw" "${CSV_OUT}"
echo "md ${tag}" > "${MD_OUT}"
"""


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.bench = self.root / "sim" / "bench"
        self.bench.mkdir(parents=True)
        # Every real experiment dir already has these (empty) parents.
        for sub in ("corners", "netlist-snapshots", "records"):
            (self.bench / sub).mkdir()
        self.driver = self.root / "driver.sh"
        self.driver.write_text(DRIVER)

    def env(self, **extra):
        env = dict(os.environ)
        env.pop("RECORD_ID", None)
        env.update(FAKE_TS=TS, FAKE_SHA=SHA, RECORD_PATHS=str(RECORD_PATHS))
        env.update(extra)
        return env

    def argv(self, tag, *args):
        return ["bash", str(self.driver), str(self.bench), str(self.root),
                tag, *args]

    def run(self, tag, *args, **env):
        return subprocess.run(self.argv(tag, *args), env=self.env(**env),
                              capture_output=True, text=True, timeout=60)

    def snapshot(self):
        """Every file under the bench dir -> its bytes, plus dir list."""
        files, dirs = {}, []
        for p in sorted(self.bench.rglob("*")):
            rel = str(p.relative_to(self.bench))
            if p.is_dir():
                dirs.append(rel)
            else:
                files[rel] = p.read_bytes()
        return files, dirs


class FreshRunCollision(unittest.TestCase):
    def test_identical_timestamp_and_commit_refuses_and_preserves(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            first = fx.run("first")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn(f"RECORD_ID={RID}", first.stdout)
            before = fx.snapshot()
            self.assertIn(f"records/{RID}.csv", before[0])
            self.assertIn(f"records/{RID}.md", before[0])
            self.assertIn(f"netlist-snapshots/{RID}/opamp_core.spice",
                          before[0])

            second = fx.run("second")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("refusing", second.stderr)
            self.assertIn(RID, second.stderr)
            self.assertEqual(fx.snapshot(), before)
            for blob in before[0].values():
                self.assertNotIn(b"second", blob)

    def test_committed_record_without_corners_dir_refuses(self):
        # A fresh clone does not carry an empty corners/<id>/: the CSV/MD
        # alone must still block reuse, and the refusal must not leave a
        # reservation directory behind.
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            rec = fx.bench / "records"
            (rec / f"{RID}.csv").write_text("committed csv\n")
            (rec / f"{RID}.md").write_text("committed md\n")
            before = fx.snapshot()
            r = fx.run("second")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("refusing", r.stderr)
            self.assertEqual(fx.snapshot(), before)

    def test_sibling_sidecar_alone_refuses(self):
        # run_offset_mc.sh's records/<id>-draws.csv is run-owned evidence too.
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            rec = fx.bench / "records"
            (rec / f"mc-{RID}-draws.csv").write_text("draws\n")
            before = fx.snapshot()
            r = fx.run("second", "--prefix", "mc-")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn(f"mc-{RID}-draws.csv", r.stderr)
            self.assertEqual(fx.snapshot(), before)

    def test_distinct_ids_still_coexist(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            self.assertEqual(fx.run("a").returncode, 0)
            r = fx.run("b", FAKE_TS="20260101-000001")
            self.assertEqual(r.returncode, 0, r.stderr)


class ConcurrentReservation(unittest.TestCase):
    N = 8

    def test_exactly_one_owner(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            gun = fx.root / "go"
            procs = [subprocess.Popen(
                fx.argv(f"racer{i}"),
                env=fx.env(WAIT_FOR=str(gun), NO_WRITE="1"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for i in range(self.N)]
            time.sleep(0.3)
            gun.write_text("")
            results = [p.communicate(timeout=60) + (p.returncode,)
                       for p in procs]
            owners = [r for r in results if r[2] == 0]
            losers = [r for r in results if r[2] != 0]
            self.assertEqual(len(owners), 1, results)
            for _out, err, _rc in losers:
                self.assertIn("refusing", err)

    def test_concurrent_resume_start_of_same_new_id_has_one_minter(self):
        # Fresh (non-resumed) minting under --resumable is a fresh run too.
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            gun = fx.root / "go"
            procs = [subprocess.Popen(
                fx.argv(f"racer{i}", "--resumable"),
                env=fx.env(WAIT_FOR=str(gun), NO_WRITE="1"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for i in range(self.N)]
            time.sleep(0.3)
            gun.write_text("")
            rcs = [p.wait(timeout=60) for p in procs]
            for p in procs:
                p.stdout.close()
                p.stderr.close()
            self.assertEqual(rcs.count(0), 1, rcs)


class ResumableCampaign(unittest.TestCase):
    def _incomplete(self, fx):
        corners = fx.bench / "corners" / RID
        corners.mkdir()
        (corners / "p0_mc_samples.txt").write_text("partial\n")
        snaps = fx.bench / "netlist-snapshots" / RID
        snaps.mkdir()
        (snaps / "opamp_core.spice").write_text("snapshot\n")
        rec = fx.bench / "records"
        (rec / f"{RID}.pilot.txt").write_text("mc_n_effective: 300\n")

    def test_resume_incomplete_continues(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            self._incomplete(fx)
            r = fx.run("resume", "--resumable", RECORD_ID=RID, NO_WRITE="1")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"RECORD_ID={RID}", r.stdout)
            # issue #163: the cmrr-mismatch manifest check keys on this
            self.assertIn("RECORD_RESUMED=1", r.stdout)
            self.assertEqual(
                (fx.bench / "corners" / RID / "p0_mc_samples.txt")
                .read_text(), "partial\n")

    def test_resume_then_finalize_then_resume_again_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            self._incomplete(fx)
            r = fx.run("resume", "--resumable", RECORD_ID=RID)
            self.assertEqual(r.returncode, 0, r.stderr)
            before = fx.snapshot()
            r2 = fx.run("again", "--resumable", RECORD_ID=RID)
            self.assertNotEqual(r2.returncode, 0)
            self.assertIn("finalized", r2.stderr)
            self.assertEqual(fx.snapshot(), before)

    def test_resume_refuses_when_only_csv_or_only_md_exists(self):
        for name in (f"{RID}.csv", f"{RID}.md"):
            with self.subTest(final=name), tempfile.TemporaryDirectory() as d:
                fx = Fixture(d)
                self._incomplete(fx)
                (fx.bench / "records" / name).write_text("final\n")
                before = fx.snapshot()
                r = fx.run("again", "--resumable", RECORD_ID=RID)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("finalized", r.stderr)
                self.assertEqual(fx.snapshot(), before)

    def test_resumable_without_record_id_mints_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run("fresh", "--resumable")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"RECORD_ID={RID}", r.stdout)
            self.assertIn("RECORD_RESUMED=0", r.stdout)

    def test_resumable_with_unused_record_id_is_fresh(self):
        # Nothing on disk for the id yet: reserved like a fresh run, so the
        # cmrr-mismatch runner publishes a manifest rather than demanding one.
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run("fresh", "--resumable", RECORD_ID=RID, NO_WRITE="1")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("RECORD_RESUMED=0", r.stdout)

    def test_non_resumable_caller_ignores_env_record_id(self):
        # Without --resumable an inherited RECORD_ID is not honored (as
        # before), and the freshly minted id is still reserved exclusively.
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run("x", RECORD_ID="something-else")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"RECORD_ID={RID}", r.stdout)


if __name__ == "__main__":
    unittest.main()

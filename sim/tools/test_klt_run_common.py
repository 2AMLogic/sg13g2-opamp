"""Offline controls for the record reservation in sim/tools/klt_run_common.sh.

Issue #171: klt_begin_record must claim the record destinations (sim +
compare, honoring RECORD_SUFFIX) atomically BEFORE klt is invoked, and
envelope / comparison publication must never replace an existing file. This
is the klt-wrapper counterpart of the #140 reservation tested in
test_record_paths.py (same primitive: an atomic un-`-p` mkdir).

Every test builds a throwaway repo tree in a TemporaryDirectory and drives the
real klt_run_common.sh from bash, with a stub `klt` and a stub compare.py.
`date` and `git` are shadowed by bash functions to force an identical
timestamp and commit. No PDK, ngspice, OSDI build or klt is needed.
"""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
COMMON = TOOLS_DIR / "klt_run_common.sh"

TS = "20260101-000000"
SHA = "abc1234"
RID = f"{TS}-{SHA}"

STUB_KLT = r"""#!/usr/bin/env bash
if [[ "$1" == "--version" ]]; then echo "stub-klt 0"; exit 0; fi
echo "$$" >> "${STUB_KLT_LOG}"
echo "{\"from\": \"${TAG}\"}"
exit "${STUB_KLT_RC:-0}"
"""

# Stub compare.py: `validate` returns STUB_VALIDATE_RC; `compare` writes a
# report to --json-out (as the real one does, truncating) and returns
# STUB_COMPARE_RC.
STUB_COMPARE = r"""import os, sys
if sys.argv[1] == "validate":
    sys.exit(int(os.environ.get("STUB_VALIDATE_RC", "0")))
out = sys.argv[sys.argv.index("--json-out") + 1]
if os.environ.get("STUB_COMPARE_RC", "0") != "9":
    with open(out, "w") as f:
        f.write('{"compare": "%s"}' % os.environ["TAG"])
sys.exit(int(os.environ.get("STUB_COMPARE_RC", "0")))
"""

# Mimics a bench run.sh: reserve, run klt, gate, publish, compare.
DRIVER = r"""
set -euo pipefail
SCRIPT_DIR="$1"; REPO_ROOT="$2"; SUFFIX="${3:-}"
SIM_DIR="${REPO_ROOT}/sim"
date() { echo "${FAKE_TS}"; }
git() { echo "${FAKE_SHA}"; }
export NGSPICE_VERSION=stub PDK=pdk PDK_ROOT="${REPO_ROOT}/nopdk"
# shellcheck source=/dev/null
source "${COMMON}"
KLT="${STUB_KLT}"
klt_check_client
klt_begin_record stub "${SUFFIX}"
echo "BEGUN ${RECORD_ID}"
if [[ -n "${HOLD:-}" ]]; then
  while [[ ! -e "${HOLD}" ]]; do sleep 0.005; done
fi
out="${SCRATCH}/x.sim.json"
klt_run_request req.json "${out}" "${SCRATCH}/x.stderr"
klt_validate_envelope "${out}"
klt_require_complete
klt_write_envelope "${out}"
klt_compare_and_finish
"""


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.bench = self.root / "sim" / "bench" / "klt"
        (self.bench / "records").mkdir(parents=True)
        (self.bench / "compare.py").write_text(STUB_COMPARE)
        self.klt = self.root / "klt"
        self.klt.write_text(STUB_KLT)
        self.klt.chmod(0o755)
        self.driver = self.root / "driver.sh"
        self.driver.write_text(DRIVER)
        self.log = self.root / "klt.log"
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()

    @property
    def records(self):
        return self.bench / "records"

    def env(self, **extra):
        env = dict(os.environ)
        env.update(FAKE_TS=TS, FAKE_SHA=SHA, COMMON=str(COMMON),
                   STUB_KLT=str(self.klt), STUB_KLT_LOG=str(self.log),
                   TMPDIR=str(self.tmp), TAG="x")
        env.update(extra)
        return env

    def argv(self, suffix=""):
        return ["bash", str(self.driver), str(self.bench), str(self.root),
                suffix]

    def run(self, suffix="", **env):
        return subprocess.run(self.argv(suffix), env=self.env(**env),
                              capture_output=True, text=True, timeout=60)

    def klt_calls(self):
        return len(self.log.read_text().split()) if self.log.exists() else 0

    def snapshot(self):
        return {str(p.relative_to(self.records)): (p.read_bytes()
                if p.is_file() else None)
                for p in sorted(self.records.rglob("*"))}


class Reservation(unittest.TestCase):
    def test_first_run_publishes_and_releases(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run(TAG="first")
            self.assertEqual(r.returncode, 0, r.stderr)
            snap = fx.snapshot()
            self.assertEqual(sorted(snap),
                             [f"{RID}.compare.json", f"{RID}.sim.json"])
            self.assertEqual(snap[f"{RID}.sim.json"], b'{"from": "first"}\n')
            self.assertEqual(list(fx.tmp.iterdir()), [])

    def test_overlapping_starts_give_exactly_one_owner(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            hold = fx.root / "hold"
            procs = [subprocess.Popen(fx.argv(), env=fx.env(HOLD=str(hold)),
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True)
                     for _ in range(6)]
            # Owner blocks on HOLD; every loser must exit before it is freed.
            deadline = time.time() + 30
            while time.time() < deadline:
                if sum(p.poll() is not None for p in procs) >= 5:
                    break
                time.sleep(0.02)
            self.assertEqual(sum(p.poll() is not None for p in procs), 5)
            self.assertEqual(fx.klt_calls(), 0)  # nobody ran klt yet
            hold.write_text("go")
            results = [(p.communicate(timeout=30), p.returncode)
                       for p in procs]
            owners = [r for r in results if r[1] == 0]
            self.assertEqual(len(owners), 1, results)
            losers = [r for r in results if r[1] == 3]
            self.assertEqual(len(losers), 5, results)
            for (out, err), _ in losers:
                self.assertNotIn("BEGUN", out)
                self.assertIn("reserved by another run", err)
            self.assertEqual(fx.klt_calls(), 1)

    def test_existing_envelope_refused_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            (fx.records / f"{RID}.sim.json").write_text("old sim\n")
            (fx.records / f"{RID}.compare.json").write_text("old cmp\n")
            before = fx.snapshot()
            r = fx.run(TAG="second")
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertIn("append-only", r.stderr)
            self.assertEqual(fx.snapshot(), before)  # incl. no reservation
            self.assertEqual(fx.klt_calls(), 0)

    def test_comparison_only_destination_refused(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            (fx.records / f"{RID}.compare.json").write_text("old cmp\n")
            before = fx.snapshot()
            r = fx.run(TAG="second")
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertEqual(fx.snapshot(), before)
            self.assertEqual(fx.klt_calls(), 0)

    def test_suffix_namespaces_are_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            a = fx.run(".nominal", TAG="nom")
            self.assertEqual(a.returncode, 0, a.stderr)
            self.assertTrue((fx.records / f"{RID}.nominal.sim.json").exists())
            self.assertTrue(
                (fx.records / f"{RID}.nominal.compare.json").exists())
            # Same suffix again: refused, bytes unchanged.
            before = fx.snapshot()
            b = fx.run(".nominal", TAG="again")
            self.assertEqual(b.returncode, 3, b.stderr)
            self.assertEqual(fx.snapshot(), before)
            # Unsuffixed record of the same id is a different destination.
            c = fx.run("", TAG="plain")
            self.assertEqual(c.returncode, 0, c.stderr)
            self.assertEqual(
                (fx.records / f"{RID}.nominal.sim.json").read_bytes(),
                before[f"{RID}.nominal.sim.json"])

    def test_reservation_held_blocks_same_suffix_only(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            (fx.records / f".reserve-{RID}.nominal").mkdir()
            r = fx.run(".nominal")
            self.assertEqual(r.returncode, 3)
            self.assertIn("rmdir", r.stderr)
            self.assertTrue((fx.records / f".reserve-{RID}.nominal").is_dir())
            self.assertEqual(fx.klt_calls(), 0)
            self.assertEqual(fx.run("").returncode, 0)

    def test_failed_submission_then_fresh_invocation(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run(TAG="bad", STUB_KLT_RC="1")
            self.assertEqual(r.returncode, 4, r.stderr)
            self.assertEqual(fx.snapshot(), {})  # nothing, no reservation
            self.assertEqual(len(list(fx.tmp.iterdir())), 1)  # raw kept
            r = fx.run(TAG="good")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(
                (fx.records / f"{RID}.sim.json").read_bytes(),
                b'{"from": "good"}\n')

    def test_failed_validation_then_fresh_invocation(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run(TAG="bad", STUB_VALIDATE_RC="1")
            self.assertEqual(r.returncode, 4, r.stderr)
            self.assertEqual(fx.snapshot(), {})
            self.assertEqual(fx.run(TAG="good").returncode, 0)

    def test_compare_disagreement_exit_5_keeps_both_files(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run(TAG="t", STUB_COMPARE_RC="1")
            self.assertEqual(r.returncode, 5, r.stderr)
            self.assertEqual(sorted(fx.snapshot()),
                             [f"{RID}.compare.json", f"{RID}.sim.json"])
            # Nothing stale: reservation released, id now refused as taken.
            self.assertEqual(fx.run(TAG="again").returncode, 3)

    def test_compare_without_report_exit_5_no_compare_file(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run(TAG="t", STUB_COMPARE_RC="9")
            self.assertEqual(r.returncode, 5, r.stderr)
            self.assertEqual(sorted(fx.snapshot()), [f"{RID}.sim.json"])


class PublishNoClobber(unittest.TestCase):
    def publish(self, src, dest):
        return subprocess.run(
            ["bash", "-c", 'source "$1"; klt_publish_noclobber "$2" "$3"',
             "x", str(COMMON), str(src), str(dest)],
            capture_output=True, text=True, timeout=30)

    def test_existing_destination_untouched_even_if_appearing_late(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, dest = d / "src", d / "dest"
            src.write_text("new")
            dest.write_text("old")
            r = self.publish(src, dest)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(dest.read_text(), "old")
            self.assertEqual(sorted(p.name for p in d.iterdir()),
                             ["dest", "src"])  # no temp litter

    def test_publishes_new_destination(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "src").write_text("new")
            self.assertEqual(self.publish(d / "src", d / "dest").returncode, 0)
            self.assertEqual((d / "dest").read_text(), "new")
            self.assertEqual(sorted(p.name for p in d.iterdir()),
                             ["dest", "src"])


if __name__ == "__main__":
    unittest.main()

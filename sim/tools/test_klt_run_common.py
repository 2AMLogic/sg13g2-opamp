"""Offline controls for the record reservation in sim/tools/klt_run_common.sh.

Issue #171: klt_begin_record must claim the record destinations (sim +
compare, honoring RECORD_SUFFIX) atomically BEFORE klt is invoked, and
envelope / comparison publication must never replace an existing file. This
is the klt-wrapper counterpart of the #140 reservation tested in
test_record_paths.py (same primitive: an atomic un-`-p` mkdir). The #209
identity lifecycle is stubbed here and tested in test_env_drift_lifecycle.py.

Every test builds a throwaway repo tree in a TemporaryDirectory and drives the
real klt_run_common.sh from bash, with a stub `klt` and a stub compare.py.
`date` and `git` are shadowed by bash functions to force an identical
timestamp and commit. No PDK, ngspice, OSDI build or klt is needed.
"""
import json
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

# Issue #484: the argument tests need to see the `klt sim` argv with
# argument boundaries intact, so this stub appends one argument per line to
# STUB_KLT_ARGV_LOG (the reservation stub above logs only PIDs, and its
# tests count tokens in that log).
STUB_KLT_ARGV = r"""#!/usr/bin/env bash
if [[ "$1" == "--version" ]]; then echo "stub-klt 0"; exit 0; fi
printf '%s\n' "$@" >> "${STUB_KLT_ARGV_LOG}"
echo "{}"
exit "${STUB_KLT_RC:-0}"
"""

# Drives only klt_check_client + klt_run_request (no record lifecycle, no
# reservation): $1 = request json path, further args forward verbatim.
DRIVER_RUN = r"""
set -euo pipefail
source "${COMMON}"
KLT="${STUB_KLT}"
klt_check_client
run_dir="$(mktemp -d)"
klt_run_request "$1" "${run_dir}/x.sim.json" "${run_dir}/x.stderr" "${@:2}"
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
# preflight.sh (not sourced here: it needs a PDK) provides the identity
# lifecycle klt_begin_record / klt_write_envelope call (issues #191, #209).
# Stub it here; the real sim/env-identity.sh is driven against a fake PDK
# install by test_env_drift_lifecycle.py, env_identity.py by its own tests.
sg13g2_env_identity_begin() { printf '{"stub": "%s"}\\n' "$1" > "$2"; }
sg13g2_env_identity_finalize() {
  [[ -e "$3" ]] || sg13g2_publish_noclobber "$2" "$3" || exit 4
}
KLT="${STUB_KLT}"
klt_check_client
klt_begin_record stub "${SUFFIX}"
ino_ctime="$(stat -c '%i %z' "${KLT_RESERVATION}" 2>/dev/null || echo stat-failed)"
echo "BEGUN ${RECORD_ID} pid=$$ t=${EPOCHREALTIME:-0} reserve=${KLT_RESERVATION} inode_ctime=${ino_ctime}"
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
                             [f"{RID}.compare.json", f"{RID}.env.json", f"{RID}.sim.json"])
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
            t0 = time.monotonic()
            deadline = t0 + 30
            while time.monotonic() < deadline:
                if sum(p.poll() is not None for p in procs) >= 5:
                    break
                time.sleep(0.02)
            exited = sum(p.poll() is not None for p in procs)
            if exited != 5:
                # Self-diagnosing failure (#338): say which child is stuck.
                states = [f"child {i}: " + ("running" if p.poll() is None
                                            else f"exited rc={p.returncode}")
                          for i, p in enumerate(procs)]
                # #401: collect before freeing anything. SIGKILL runs no EXIT
                # trap, so no reservation is released here, and the hold file
                # is never written: the captured output is exactly what was on
                # the wire at the deadline, so a second BEGUN in it cannot
                # have been manufactured by this diagnostic.
                for p in procs:
                    if p.poll() is None:
                        p.kill()
                outs = [p.communicate(timeout=30) for p in procs]
                diag = [f"child {i} stdout={out!r} stderr={err!r}"
                        for i, (out, err) in enumerate(outs)]
                owners = sum("BEGUN" in out for out, _ in outs)
                # #459: settle the identical-t= question in the failure
                # message itself. One child reads EPOCHREALTIME twice around
                # a sleep, in the same process: distinct reads mean the
                # runner's bash keeps EPOCHREALTIME live (identical t=
                # across children is then real near-simultaneity); equal
                # reads mean t= is frozen there and orders nothing.
                try:
                    probe = subprocess.run(
                        ["bash", "-c",
                         'a="${EPOCHREALTIME:-0}"; sleep 0.2; '
                         'b="${EPOCHREALTIME:-0}"; '
                         'printf "BASH_VERSION=%s t1=%s t2=%s" '
                         '"${BASH_VERSION:-unknown}" "$a" "$b"'],
                        capture_output=True, text=True, timeout=30)
                    runner = (f"runner probe ({probe.stdout.strip()}); "
                              f"rc={probe.returncode} "
                              f"stderr={probe.stderr.strip()!r}")
                except Exception as e:
                    runner = f"runner probe failed: {e!r}"
                self.fail(f"{exited} != 5 children exited after "
                          f"{time.monotonic() - t0:.1f}s of a 30s deadline; "
                          f"BEGUN owners={owners}; {runner}; "
                          + "; ".join(states) + "\n" + "\n".join(diag))
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
                             [f"{RID}.compare.json", f"{RID}.env.json", f"{RID}.sim.json"])
            # Nothing stale: reservation released, id now refused as taken.
            self.assertEqual(fx.run(TAG="again").returncode, 3)

    def test_compare_without_report_exit_5_no_compare_file(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            r = fx.run(TAG="t", STUB_COMPARE_RC="9")
            self.assertEqual(r.returncode, 5, r.stderr)
            self.assertEqual(sorted(fx.snapshot()), [f"{RID}.env.json", f"{RID}.sim.json"])


class PublishNoClobber(unittest.TestCase):
    def publish(self, src, dest):
        return subprocess.run(
            ["bash", "-c", 'source "$1"; sg13g2_publish_noclobber "$2" "$3"',
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


# Two envelopes per record id, bench-specific compare args, no identity
# (issue #274: sim/open-loop-ac/klt/run.sh).
DRIVER_PAIR = DRIVER.split('klt_begin_record stub')[0].replace(
    'sg13g2_env_identity_begin()', 'sg13g2_env_identity_begin_unused()') + r"""
KLT_RECORD_EXTS=(.ac.sim.json .op.sim.json .compare.json)
KLT_IDENTITY=0
klt_begin_record stub
for kind in ac op; do
  klt_run_request req.json "${SCRATCH}/${kind}.sim.json" "${SCRATCH}/${kind}.err"
  klt_validate_envelope "${SCRATCH}/${kind}.sim.json" --kind "${kind}"
done
klt_require_complete
for kind in ac op; do
  klt_write_envelope "${SCRATCH}/${kind}.sim.json" ".${kind}.sim.json"
done
KLT_COMPARE_ENVELOPE_ARGS=(--ac a.json --op o.json)
klt_compare_and_finish
"""


class PairOfEnvelopes(unittest.TestCase):
    def fixture(self, d):
        fx = Fixture(d)
        fx.driver.write_text(DRIVER_PAIR)
        return fx

    def test_publishes_pair_and_compare_without_identity_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            fx = self.fixture(d)
            r = fx.run(TAG="pair")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(fx.snapshot()),
                             [f"{RID}.ac.sim.json", f"{RID}.compare.json",
                              f"{RID}.op.sim.json"])
            self.assertIn(f"wrote records/{RID}.ac.sim.json", r.stdout)
            self.assertIn(f"wrote records/{RID}.op.sim.json", r.stdout)
            self.assertEqual(list(fx.tmp.iterdir()), [])

    def test_any_existing_member_refuses_before_klt(self):
        for ext in (".ac.sim.json", ".op.sim.json", ".compare.json"):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as d:
                fx = self.fixture(d)
                (fx.records / f"{RID}{ext}").write_text("old")
                before = fx.snapshot()
                r = fx.run(TAG="again")
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertEqual(fx.klt_calls(), 0)
                self.assertEqual(fx.snapshot(), before)

    def test_compare_receives_bench_envelope_args_not_default(self):
        with tempfile.TemporaryDirectory() as d:
            fx = self.fixture(d)
            (fx.bench / "compare.py").write_text(
                "import sys\n"
                "if sys.argv[1] == 'validate': sys.exit(0)\n"
                "a = sys.argv\n"
                "assert '--ac' in a and '--op' in a and '--envelope' not in a, a\n"
                "open(a[a.index('--json-out') + 1], 'w').write('{}')\n")
            r = fx.run(TAG="args")
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_failed_validation_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            fx = self.fixture(d)
            r = fx.run(TAG="bad", STUB_VALIDATE_RC="1")
            self.assertEqual(r.returncode, 4, r.stderr)
            self.assertEqual(fx.snapshot(), {})


# Issue #484: a NEW batch submission must carry `--wait-for-capacity
# ${KLT_CAPACITY_WAIT_S:-600}` so a vCPU-budgeted fleet refusal is retried
# with backoff by the client; everything else (local overrides, --attach
# resumes, caller-supplied waits) must not gain or duplicate it.
class CapacityWait(unittest.TestCase):
    def run_stub(self, req_obj, extra_args=(), **env):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(d)
            fx.klt.write_text(STUB_KLT_ARGV)
            fx.driver.write_text(DRIVER_RUN)
            argvlog = fx.root / "argv.log"
            req = fx.root / "req.json"
            req.write_text(json.dumps(req_obj))
            r = subprocess.run(
                ["bash", str(fx.driver), str(req), *extra_args],
                env=fx.env(STUB_KLT_ARGV_LOG=str(argvlog), **env),
                capture_output=True, text=True, timeout=60)
            argv = (argvlog.read_text().splitlines()
                    if argvlog.exists() else [])
            return r, argv

    def assert_wait(self, argv, seconds):
        self.assertEqual(argv.count("--wait-for-capacity"), 1, argv)
        self.assertEqual(argv[argv.index("--wait-for-capacity") + 1],
                         seconds, argv)

    def test_batch_request_defaults_to_exactly_one_600s_wait(self):
        r, argv = self.run_stub({"backend": "batch"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_wait(argv, "600")
        self.assertEqual(argv[0], "sim")
        self.assertEqual(argv[-2:], ["--format", "json"])

    def test_runner_log_shows_the_capacity_arguments_sent(self):
        r, _ = self.run_stub({"backend": "batch"})
        self.assertIn("--wait-for-capacity 600", r.stdout)
        r, _ = self.run_stub({"backend": "batch"}, ["--attach", "j"])
        self.assertNotIn("--wait-for-capacity", r.stdout)

    def test_explicit_batch_backend_beats_local_request(self):
        r, argv = self.run_stub({"backend": "local"}, ["--backend", "batch"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_wait(argv, "600")

    def test_env_override_forwarded_including_literal_zero(self):
        for val in ("0", "45"):
            with self.subTest(KLT_CAPACITY_WAIT_S=val):
                r, argv = self.run_stub({"backend": "batch"},
                                        KLT_CAPACITY_WAIT_S=val)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assert_wait(argv, val)

    def test_local_overrides_of_batch_request_omit_the_wait(self):
        for backend in ("local", "local-parallel"):
            with self.subTest(backend=backend):
                r, argv = self.run_stub({"backend": "batch"},
                                        ["--backend", backend])
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("--wait-for-capacity", argv)

    def test_local_request_without_override_omits_the_wait(self):
        r, argv = self.run_stub({"backend": "local"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--wait-for-capacity", argv)

    def test_attach_resume_forwards_job_id_without_wait(self):
        r, argv = self.run_stub({"backend": "batch"},
                                ["--backend", "batch", "--attach", "job-42"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--wait-for-capacity", argv)
        self.assertEqual(argv[argv.index("--attach") + 1], "job-42")

    def test_caller_supplied_wait_forwarded_not_duplicated(self):
        r, argv = self.run_stub({"backend": "batch"},
                                ["--wait-for-capacity", "30"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_wait(argv, "30")


if __name__ == "__main__":
    unittest.main()

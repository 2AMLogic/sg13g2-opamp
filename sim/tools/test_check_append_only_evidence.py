"""Negative controls for check_append_only_evidence.py (offline).

Each test builds a throwaway Git repository, so nothing touches the real
checkout. No ngspice, PDK or klt.
"""
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "gate", Path(__file__).with_name("check_append_only_evidence.py"))
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

REC = "sim/open-loop-ac/records/20260101-000000-aaaaaaa.csv"
OLD = "sim/open-loop-ac/records/20250101-000000-bbbbbbb.csv"  # unselected
SNAP = "sim/open-loop-ac/netlist-snapshots/20260101-000000-aaaaaaa/p0.cir"
CORN = "sim/open-loop-ac/corners/20260101-000000-aaaaaaa/p0_ac.csv"
SREP = "signoff/reports/20260101-000000-aaaaaaa.signoff.json"
CREP = "signoff/characterization/reports/20260101-000000-aaaaaaa.json"
SEL = "signoff/characterization/selection.json"
GEN = "signoff/characterization/generate.py"
RUN = "sim/open-loop-ac/run_pvt_sweep.sh"
KENV = "sim/cmrr-psrr/klt/records/20261010-094256-469573d.sim.json"
KCMP = "sim/cmrr-psrr/klt/records/20261010-094256-469573d.compare.json"
KSHARD = "sim/cmrr-psrr/klt/records/20261010-094256-469573d.shards/mos_tt/report.json"
KPROTO = "sim/input-noise/klt/prototype/20261010-053635-c0c112a.tt27-1v20.sim.json"
KMUT = ("sim/cmrr-psrr/klt/psrr.request.json", "sim/cmrr-psrr/klt/compare.py",
        "sim/cmrr-psrr/klt/run.sh", "sim/cmrr-psrr/klt/shard.py",
        "sim/cmrr-psrr/klt/tb_psrr.body.spice")
KLT = (KENV, KCMP, KSHARD, KPROTO)
ALL = (REC, OLD, SNAP, CORN, SREP, CREP) + KLT


class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.g("init", "-q", "-b", "main")
        self.g("config", "user.email", "t@example.invalid")
        self.g("config", "user.name", "t")
        self.g("config", "commit.gpgsign", "false")
        # No background gc/maintenance: a detached `git gc --auto` writing
        # into .git races TemporaryDirectory cleanup (ENOTEMPTY flake).
        self.g("config", "gc.auto", "0")
        self.g("config", "maintenance.auto", "false")
        self.g("config", "gc.autoDetach", "false")

    def g(self, *a):
        p = subprocess.run(["git", "-C", str(self.root), *a],
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        return p.stdout.strip()

    def write(self, rel, text, mode=None):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if mode:
            p.chmod(mode)

    def commit(self, msg="c"):
        self.g("add", "-A")
        self.g("commit", "-q", "--allow-empty", "-m", msg)
        return self.g("rev-parse", "HEAD")


class GateTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._td.cleanup)
        self.r = Repo(self._td.name)
        for p in ALL:
            self.r.write(p, f"data {p}\n")
        for p in KMUT:
            self.r.write(p, f"mutable {p}\n")
        self.r.write(SEL, '{"sel": "a"}\n')
        self.r.write(GEN, "print(1)\n")
        self.r.write(RUN, "#!/bin/sh\n", 0o755)
        self.base = self.r.commit("base")

    def check(self, base=None, head="HEAD"):
        out, err = io.StringIO(), io.StringIO()
        rc = gate.run(str(self.r.root), base or self.base, head, out, err)
        return rc, out.getvalue(), err.getvalue()

    def assertFailsNaming(self, path, base=None, head="HEAD"):
        self.r.commit("change")
        rc, _, err = self.check(base, head)
        self.assertEqual(rc, 1, err)
        self.assertIn(path, err)

    # --- accepted ---------------------------------------------------------
    def test_new_records_pass(self):
        self.r.write("sim/open-loop-ac/records/20270101-000000-ccccccc.csv", "n\n")
        self.r.write("sim/new-bench/corners/x/y.csv", "n\n")
        self.r.write("sim/cmrr-psrr/klt/records/20270101-000000-ccccccc.sim.json", "{}\n")
        self.r.write("sim/cmrr-psrr/klt/records/20270101-000000-ccccccc.shards/a/r.json", "{}\n")
        self.r.write("signoff/reports/20270101-000000-ccccccc.signoff.json", "{}\n")
        self.r.commit()
        rc, out, err = self.check()
        self.assertEqual(rc, 0, err)
        self.assertIn("ok", out)

    def test_no_change_passes(self):
        self.assertEqual(self.check()[0], 0)

    def test_mutable_selector_and_source_edits_pass(self):
        self.r.write(SEL, '{"sel": "b"}\n')
        self.r.write(GEN, "print(2)\n")
        self.r.write(RUN, "#!/bin/sh\necho hi\n", 0o755)
        for p in KMUT:
            self.r.write(p, f"edited {p}\n")
        self.r.write("sim/open-loop-ac/README.md", "doc\n")
        self.r.write("sim/open-loop-ac/testbench/tb.spice", "tb\n")
        self.r.commit()
        rc, _, err = self.check()
        self.assertEqual(rc, 0, err)

    def test_mutable_file_deleted_and_moved_pass(self):
        self.r.g("rm", "-q", RUN)
        self.r.commit()
        self.assertEqual(self.check()[0], 0)

    # --- rejected, every protected class ----------------------------------
    def test_modify_each_protected_class(self):
        for p in ALL:
            with self.subTest(path=p):
                self.r.write(p, "tampered\n")
                self.assertFailsNaming(p, self.base)
                self.r.g("reset", "-q", "--hard", self.base)

    def test_delete_each_protected_class(self):
        for p in ALL:
            with self.subTest(path=p):
                self.r.g("rm", "-q", p)
                self.assertFailsNaming(p, self.base)
                self.r.g("reset", "-q", "--hard", self.base)

    def test_rename_fails_naming_old_path(self):
        self.r.g("mv", REC, REC + ".moved")
        self.assertFailsNaming(REC)

    def test_rename_with_identical_content_still_fails(self):
        # No rename detection: identical blob at a new path does not excuse
        # the disappearance of the old path.
        self.r.g("mv", OLD, "sim/open-loop-ac/records/renamed.csv")
        self.assertFailsNaming(OLD)

    def test_mode_change_fails(self):
        (self.r.root / REC).chmod(0o755)
        self.assertFailsNaming(REC)
        rc, _, err = self.check()
        self.assertIn("mode changed", err)

    def test_klt_envelope_rename_and_mode_change_fail(self):
        self.r.g("mv", KENV, KENV + ".moved")
        self.assertFailsNaming(KENV)
        self.r.g("reset", "-q", "--hard", self.base)
        (self.r.root / KENV).chmod(0o755)
        self.assertFailsNaming(KENV)
        _, _, err = self.check()
        self.assertIn("mode changed", err)

    def test_klt_shard_artifact_change_fails(self):
        self.r.write(KSHARD, "tampered\n")
        self.assertFailsNaming(KSHARD)

    def test_unselected_historical_record_protected(self):
        # SEL says nothing about OLD, yet it is protected.
        self.r.write(SEL, '{"sel": "b"}\n')
        self.r.write(OLD, "tampered\n")
        self.assertFailsNaming(OLD)

    def test_selector_edit_cannot_launder_record_edit(self):
        self.r.write(SEL, '{"sel": "b"}\n')
        self.r.write(REC, "tampered\n")
        self.assertFailsNaming(REC)

    def test_all_violations_reported(self):
        self.r.write(REC, "x\n")
        self.r.g("rm", "-q", OLD)
        self.r.commit()
        _, _, err = self.check()
        self.assertIn(REC, err)
        self.assertIn(OLD, err)

    # --- comparison commits -------------------------------------------------
    def test_missing_base_history_is_an_error_not_a_pass(self):
        rc, _, err = self.check(base="1234567890abcdef1234567890abcdef12345678")
        self.assertEqual(rc, 2)
        self.assertIn("cannot obtain base commit", err)
        self.assertIn("fetch-depth", err)

    def test_shallow_clone_missing_base_is_an_error(self):
        self.r.write(REC, "t\n")
        self.r.commit("second")
        self.r.write("sim/open-loop-ac/records/n.csv", "n\n")
        self.r.commit("third")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            dst = os.path.join(td, "shallow")
            subprocess.run(["git", "clone", "-q", "--depth", "1",
                            "file://" + str(self.r.root), dst],
                           check=True, capture_output=True)
            out, err = io.StringIO(), io.StringIO()
            rc = gate.run(dst, self.base, "HEAD", out, err)
            self.assertEqual(rc, 2, err.getvalue())
            self.assertIn("cannot obtain base commit", err.getvalue())

    def test_missing_head_is_an_error(self):
        rc, _, err = self.check(head="nope-branch")
        self.assertEqual(rc, 2)
        self.assertIn("head", err)

    def test_pull_request_base_vs_merge_tree(self):
        # base = main tip; head = merge commit of the PR branch.
        self.r.g("checkout", "-q", "-b", "pr")
        self.r.write("sim/open-loop-ac/records/pr-new.csv", "n\n")
        self.r.commit("pr1")
        self.r.write(REC, "tampered\n")
        self.r.commit("pr2")
        self.r.g("checkout", "-q", "main")
        self.r.write("sim/open-loop-ac/records/main-new.csv", "m\n")
        main_tip = self.r.commit("main moves")
        self.r.g("merge", "-q", "--no-ff", "-m", "merge", "pr")
        rc, _, err = self.check(base=main_tip)
        self.assertEqual(rc, 1)
        self.assertIn(REC, err)
        # An honest PR passes against the same base.
        self.r.g("reset", "-q", "--hard", main_tip)
        self.r.g("checkout", "-q", "-b", "pr-ok")
        self.r.write("sim/open-loop-ac/records/ok.csv", "n\n")
        self.r.write(SEL, '{"sel": "ok"}\n')
        self.r.commit("ok")
        self.r.g("checkout", "-q", "main")
        self.r.g("merge", "-q", "--no-ff", "-m", "merge-ok", "pr-ok")
        self.assertEqual(self.check(base=main_tip)[0], 0)

    def test_multi_commit_push_compares_before_to_after(self):
        before = self.base
        self.r.write("sim/open-loop-ac/records/p1.csv", "1\n")
        self.r.commit("p1")
        self.r.write(SEL, '{"sel": "c"}\n')
        self.r.commit("p2")
        self.r.write(REC, "tampered in the last commit\n")
        after = self.r.commit("p3")
        rc, _, err = self.check(base=before, head=after)
        self.assertEqual(rc, 1)
        self.assertIn(REC, err)
        # Tampering in an *early* commit of the push is still caught.
        self.r.g("reset", "-q", "--hard", before)
        self.r.write(REC, "early tamper\n")
        self.r.commit("q1")
        self.r.write(SEL, '{"sel": "d"}\n')
        after = self.r.commit("q2")
        rc, _, err = self.check(base=before, head=after)
        self.assertEqual(rc, 1)
        self.assertIn(REC, err)

    def test_multi_commit_push_that_only_appends_passes(self):
        before = self.base
        for i in range(3):
            self.r.write(f"sim/open-loop-ac/records/n{i}.csv", f"{i}\n")
            after = self.r.commit(f"n{i}")
        self.assertEqual(self.check(base=before, head=after)[0], 0)

    def test_first_push_all_zero_base_is_explicit_pass(self):
        zero = "0" * 40
        self.r.write(REC, "tampered\n")
        self.r.commit()
        rc, out, err = self.check(base=zero)
        self.assertEqual(rc, 0, err)
        self.assertIn("first push", out)

    def test_cli_exit_codes(self):
        script = str(Path(__file__).with_name("check_append_only_evidence.py"))

        def cli(*a):
            return subprocess.run(["python3", script, "--repo", str(self.r.root), *a],
                                  capture_output=True, text=True)
        self.assertEqual(cli("--base", self.base).returncode, 0)
        self.assertEqual(cli("--base", "0" * 40).returncode, 0)
        self.assertEqual(cli("--base", "deadbeef" * 5).returncode, 2)
        self.r.write(REC, "t\n")
        self.r.commit()
        p = cli("--base", self.base)
        self.assertEqual(p.returncode, 1)
        self.assertIn(REC, p.stderr)


class ScopeTest(unittest.TestCase):
    def test_protected_scope(self):
        prot = gate.PROTECTED
        def hit(p): return any(x.match(p) for x in prot)
        for p in ALL:
            self.assertTrue(hit(p), p)
        for p in (SEL, GEN, RUN, "sim/open-loop-ac/README.md",
                  "sim/open-loop-ac/testbench/tb.spice",
                  "signoff/block-manifest.json", "signoff/evidence/hygiene.json",
                  "signoff/characterization/README.md", "sim/README.md"):
            self.assertFalse(hit(p), p)


if __name__ == "__main__":
    unittest.main()

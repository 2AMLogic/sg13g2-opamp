#!/usr/bin/env python3
"""Negative controls for check_inventories.py (stdlib unittest, offline).

  python3 -m unittest discover -s signoff -p 'test_check_inventories.py' -v

Every control builds a throwaway fixture tree holding only what the three
inventories name (copied with modes preserved), perturbs exactly one thing,
and asserts the precise diagnostic. The real checkout is never modified.
Needs no ngspice, no PDK, no klt; the git controls need only `git`.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_inventories as ci  # noqa: E402

REPO = HERE.parent

# Copied whole: small, and every file in them is a candidate for a check.
COPY_TREES = ["design", "spec", ".github", "signoff/evidence", "sim/tools"]
COPY_FILES = ["README.md", "LICENSE", "signoff/README.md", "sim/env.sh",
              "sim/preflight.sh", "sim/pdk.json"]


def bench_rows() -> list[tuple[int, str, str, str, str]]:
    """(line, row, bench, command, record) for each testbenches.txt row."""
    out = []
    text = (REPO / ci.TESTBENCHES).read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.strip() and not raw.lstrip().startswith("#"):
            row, bench, command, record = (f.strip() for f in raw.split("|"))
            out.append((lineno, row, bench, command, record))
    return out


def inventory_line(rel: str, key: str) -> int:
    text = (REPO / rel).read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.startswith(f"{key}:"):
            return lineno
    raise AssertionError(f"{rel} has no `{key}:` line")


class InventoryControls(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="inv-fixture-")
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        for rel in COPY_TREES:
            shutil.copytree(REPO / rel, self.root / rel)
        for rel in COPY_FILES:
            self.copy(rel)
        for _line, _row, bench, command, record in bench_rows():
            self.copy(f"{bench}/README.md")
            self.copy(command)
            self.copy(record)
            self.copy(str(Path(record).with_suffix(".md")))
            if not (self.root / bench / "testbench").exists():
                shutil.copytree(REPO / bench / "testbench", self.root / bench / "testbench")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def copy(self, rel: str) -> None:
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest)

    def run_check(self) -> tuple[int, list[str]]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ci.Checker(self.root).run()
        fails = [line[len("FAIL: "):] for line in buf.getvalue().splitlines()
                 if line.startswith("FAIL: ")]
        return code, fails

    def assert_only_failure(self, expected: str) -> None:
        code, fails = self.run_check()
        self.assertEqual(code, 1, "the perturbation must fail the check")
        self.assertEqual(fails, [expected])

    def row(self, bench: str, command: str | None = None):
        for entry in bench_rows():
            if entry[2] == bench and (command is None or entry[3] == command):
                return entry
        raise AssertionError(bench)

    # -- baseline ------------------------------------------------------------
    def test_fixture_passes(self) -> None:
        code, fails = self.run_check()
        self.assertEqual((code, fails), (0, []))

    def test_real_checkout_passes(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ci.Checker(REPO).run()
        self.assertEqual(code, 0, buf.getvalue())

    # -- the acceptance-criteria controls ------------------------------------
    def test_deleted_cited_record(self) -> None:
        line, row, _bench, _cmd, record = self.row("sim/slew-rate")
        (self.root / record).unlink()
        self.assert_only_failure(
            f"{ci.TESTBENCHES}:{line}: {row}: cited record `{record}` does not exist")

    def test_runner_not_executable(self) -> None:
        line, row, _bench, command, _rec = self.row("sim/input-noise")
        path = self.root / command
        path.chmod(path.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        self.assert_only_failure(
            f"{ci.TESTBENCHES}:{line}: {row}: runner `{command}` is not executable "
            f"(mode {stat.filemode(path.stat().st_mode)})")

    def test_invalid_shell_syntax(self) -> None:
        line, row, _bench, command, _rec = self.row("sim/output-swing")
        with (self.root / command).open("a", encoding="utf-8") as fh:
            fh.write("\nif then fi (\n")
        code, fails = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(len(fails), 1, fails)
        self.assertTrue(
            fails[0].startswith(f"{ci.TESTBENCHES}:{line}: {row}: `bash -n {command}` failed: "),
            fails[0])
        self.assertIn("syntax error", fails[0])

    def test_missing_design_source(self) -> None:
        line = inventory_line(ci.DESIGN_SOURCES, "symbol")
        (self.root / "design/opamp_core.sym").unlink()
        self.assert_only_failure(
            f"{ci.DESIGN_SOURCES}:{line}: symbol: path `design/opamp_core.sym` does not exist")

    def test_missing_netlist_source(self) -> None:
        line = inventory_line(ci.DESIGN_SOURCES, "netlist")
        (self.root / "design/netlist/opamp_core.spice").unlink()
        self.assert_only_failure(
            f"{ci.DESIGN_SOURCES}:{line}: netlist: path `design/netlist/opamp_core.spice` does not exist")

    def test_missing_hygiene_artifact(self) -> None:
        line = inventory_line(ci.HYGIENE, "license")
        (self.root / "LICENSE").unlink()
        self.assert_only_failure(f"{ci.HYGIENE}:{line}: license: path `LICENSE` does not exist")

    def test_missing_ci_workflow(self) -> None:
        line = inventory_line(ci.HYGIENE, "ci-workflow")
        (self.root / ".github/workflows/signoff.yml").unlink()
        self.assert_only_failure(
            f"{ci.HYGIENE}:{line}: ci-workflow: path `.github/workflows/signoff.yml` does not exist")

    # -- further controls ------------------------------------------------------
    def test_missing_reproducibility_anchor(self) -> None:
        line = inventory_line(ci.HYGIENE, "how-to-reproduce")
        readme = self.root / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8").replace(
            "## Reproducing the results", "## Results"), encoding="utf-8")
        self.assert_only_failure(
            f"{ci.HYGIENE}:{line}: how-to-reproduce: `README.md` has no Markdown heading "
            "\"Reproducing the results\"")

    def test_cold_start_section_drops_command(self) -> None:
        _line, _row, bench, command, _rec = self.row("sim/open-loop-ac")
        readme = self.root / bench / "README.md"
        text = readme.read_text(encoding="utf-8")
        readme.write_text(re.sub(rf"(?m)^{re.escape(command)}\s*$", "", text), encoding="utf-8")
        code, fails = self.run_check()
        self.assertEqual(code, 1)
        # One diagnostic per spec row that cites this command.
        self.assertEqual(fails, [
            f"{ci.TESTBENCHES}:{line}: {row}: `{bench}/README.md` \"Cold-start invocation\" "
            f"does not name `{command}`"
            for line, row, b, c, _r in bench_rows() if (b, c) == (bench, command)
        ])
        self.assertGreater(len(fails), 1)

    def test_missing_template(self) -> None:
        line, row, bench, command, _rec = self.row("sim/slew-rate")
        (self.root / bench / "testbench/tb_slew.spice.tmpl").unlink()
        self.assert_only_failure(
            f"{ci.TESTBENCHES}:{line}: {row}: template `{bench}/testbench/tb_slew.spice.tmpl` "
            f"referenced by `{command}` does not exist")

    def test_missing_shared_harness(self) -> None:
        (self.root / "sim/preflight.sh").unlink()
        code, fails = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(len(fails), 1, fails)
        self.assertRegex(fails[0], r":\d+: shared harness: path `sim/preflight.sh` does not exist$")

    def test_pdk_pin_disagrees(self) -> None:
        pdk = self.root / "sim/pdk.json"
        pdk.write_text(pdk.read_text(encoding="utf-8").replace(
            '"release_tag": "v0.3.0"', '"release_tag": "v0.4.0"'), encoding="utf-8")
        code, fails = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(len(fails), 1, fails)
        self.assertIn("PDK pin: `sim/pdk.json` pins IHP-GmbH/IHP-Open-PDK v0.4.0, "
                      "inventory states IHP-GmbH/IHP-Open-PDK v0.3.0", fails[0])

    def test_regenerate_command_names_other_schematic(self) -> None:
        line = inventory_line(ci.DESIGN_SOURCES, "regenerate")
        inv = self.root / ci.DESIGN_SOURCES
        inv.write_text(inv.read_text(encoding="utf-8").replace(
            "./opamp_core.sch\n", "./other.sch\n"), encoding="utf-8")
        self.assert_only_failure(
            f"{ci.DESIGN_SOURCES}:{line}: regenerate: schematic argument resolves to "
            "['design/other.sch'], expected [`design/opamp_core.sch`]")

    def test_workflow_drops_validator_step(self) -> None:
        line = inventory_line(ci.HYGIENE, "ci-workflow")
        wf = self.root / ".github/workflows/signoff.yml"
        wf.write_text(wf.read_text(encoding="utf-8").replace(
            "run: python3 signoff/check_inventories.py", "run: true"), encoding="utf-8")
        self.assert_only_failure(
            f"{ci.HYGIENE}:{line}: ci-workflow: `.github/workflows/signoff.yml` lacks the "
            "`signoff/check_inventories.py` step")

    # -- git: committed state, not just the working tree ----------------------
    def git(self, *args: str) -> None:
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        subprocess.run(["git", "-C", str(self.root), *args], check=True,
                       capture_output=True, text=True, env=env)

    def init_git(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git not available")
        self.git("init", "-q")
        self.git("config", "core.fileMode", "true")
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture")

    def test_git_fixture_passes(self) -> None:
        self.init_git()
        self.assertEqual(self.run_check(), (0, []))

    def test_git_untracked_record(self) -> None:
        self.init_git()
        _line, _row, _bench, _cmd, record = self.row("sim/input-cmr")
        self.git("rm", "-q", "--cached", record)
        self.assert_only_failure(f"git: `{record}` exists but is not tracked (not committed)")

    def test_git_committed_mode_not_executable(self) -> None:
        self.init_git()
        _line, _row, _bench, command, _rec = self.row("sim/cmrr-mismatch")
        self.git("update-index", "--chmod=-x", command)
        self.assert_only_failure(f"git: runner `{command}` is committed with mode 100644, not 100755")


if __name__ == "__main__":
    unittest.main()

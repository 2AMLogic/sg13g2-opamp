#!/usr/bin/env python3
"""Append-only evidence gate: compare two Git trees, offline.

Policy (CLAUDE.md, sim/README.md): simulation and signoff evidence is
append-only. This gate compares the tree of a BASE commit with the tree of a
HEAD commit and fails if any file that exists in BASE under a protected path
is, in HEAD, missing (deleted or renamed away), has different content (blob),
or has a different mode. New paths are always allowed. Paths outside the
protected scope (selectors, manifests, generators, READMEs, run scripts, ...)
are not looked at.

Comparison is by exact path + blob + mode. There is deliberately NO rename
detection: a moved record is a deletion of the old path and is rejected.

Protected scope (every file under):
  sim/<experiment>/records/
  sim/<experiment>/netlist-snapshots/
  sim/<experiment>/corners/
  signoff/reports/
  signoff/characterization/reports/
No `corners/` directory holds intentionally mutable definitions: every file
there lives under a per-record `<record-id>/` directory written by a run.
Mutable definitions (testbench/, selection.json, generators, run_*.sh, READMEs)
are outside the scope.

Usage:
  check_append_only_evidence.py --base <rev> [--head <rev>] [--repo <dir>]

First push: a BASE that is all zeros (git's "no previous commit", the `before`
SHA of the first push of a branch) has no tree to compare against. The gate
reports that explicitly and passes; the pull-request run is the gate for such
a branch. A BASE that is not all zeros but cannot be resolved (shallow clone,
unfetched, force-pushed away) is an error (exit 2), never a silent pass.

Exit codes: 0 ok / first push, 1 protected evidence changed, 2 usage or
unobtainable revision. Stdlib + git only; no ngspice, PDK or klt.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

PROTECTED = (
    re.compile(r"^sim/[^/]+/records/"),
    re.compile(r"^sim/[^/]+/netlist-snapshots/"),
    re.compile(r"^sim/[^/]+/corners/"),
    re.compile(r"^signoff/reports/"),
    re.compile(r"^signoff/characterization/reports/"),
)
ZERO = re.compile(r"^0+$")


class GateError(Exception):
    pass


def _git(repo: str, *args: str) -> bytes:
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if p.returncode != 0:
        raise GateError(p.stderr.decode(errors="replace").strip())
    return p.stdout


def resolve(repo: str, rev: str, what: str) -> str:
    try:
        out = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    except GateError:
        out = b""
    sha = out.decode().strip()
    if not sha:
        raise GateError(
            f"cannot obtain {what} commit '{rev}': it is not in this clone "
            "(shallow checkout, unfetched ref, or force-pushed away). Fetch "
            "full history (actions/checkout fetch-depth: 0, or `git fetch "
            "origin <sha>`); the gate refuses to pass without the comparison tree."
        )
    return sha


def protected_entries(repo: str, commit: str) -> dict[str, tuple[str, str]]:
    raw = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    entries: dict[str, tuple[str, str]] = {}
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, path_b = rec.split(b"\t", 1)
        mode, _type, blob = meta.decode().split()
        path = path_b.decode("utf-8", "surrogateescape")
        if any(p.match(path) for p in PROTECTED):
            entries[path] = (mode, blob)
    return entries


def compare(repo: str, base: str, head: str) -> list[str]:
    b = protected_entries(repo, base)
    h = protected_entries(repo, head)
    problems = []
    for path in sorted(b):
        if path not in h:
            problems.append(f"{path}: deleted or renamed away")
        elif h[path][1] != b[path][1]:
            problems.append(f"{path}: content modified")
        elif h[path][0] != b[path][0]:
            problems.append(f"{path}: mode changed {b[path][0]} -> {h[path][0]}")
    return problems


def run(repo: str, base: str, head: str, out=sys.stdout, err=sys.stderr) -> int:
    if ZERO.match(base):
        print("append-only evidence: first push (all-zero base SHA); no previous "
              "tree to compare, nothing to enforce here. The pull-request run "
              "is the gate for this branch.", file=out)
        return 0
    try:
        bsha = resolve(repo, base, "base")
        hsha = resolve(repo, head, "head")
        problems = compare(repo, bsha, hsha)
    except GateError as e:
        print(f"append-only evidence: ERROR: {e}", file=err)
        return 2
    if problems:
        print(f"append-only evidence: FAIL comparing {bsha[:12]} -> {hsha[:12]}",
              file=err)
        for p in problems:
            print(f"  {p}", file=err)
        print("Committed evidence is never edited, deleted, renamed or re-moded. "
              "Append a corrected record and change the selector instead "
              "(sim/README.md, 'Superseding a mistaken record').", file=err)
        return 1
    print(f"append-only evidence: ok ({bsha[:12]} -> {hsha[:12]}); "
          "every protected base file is unchanged", file=out)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="previous commit (rev or SHA)")
    ap.add_argument("--head", default="HEAD", help="tested commit (default HEAD)")
    ap.add_argument("--repo", default=".", help="repository dir (default .)")
    a = ap.parse_args(argv)
    return run(a.repo, a.base, a.head)


if __name__ == "__main__":
    sys.exit(main())

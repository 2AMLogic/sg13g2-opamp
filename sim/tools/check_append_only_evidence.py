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
  sim/<bench>/klt/records/   (klt envelopes, comparisons, raw <id>.shards/)
  sim/<bench>/klt/prototype/ (prototype klt envelopes; not signoff evidence)
  signoff/reports/
  signoff/characterization/reports/
No `corners/` directory holds intentionally mutable definitions: every file
there lives under a per-record `<record-id>/` directory written by a run.
Mutable definitions (testbench/, selection.json, generators, run_*.sh, READMEs,
and klt request templates, comparators, runners and selectors that sit beside
-- not inside -- the klt record trees) are outside the scope. The klt rule is
explicit (`klt/records/`, `klt/prototype/`), not a blanket `klt/` freeze.

Usage:
  check_append_only_evidence.py --base <rev> [--head <rev>] [--repo <dir>]
  check_append_only_evidence.py --event <name> [--pr-base-sha <sha>]
      [--push-before-sha <sha>] [--merge-group-base-sha <sha>]
      [--merge-group-head-sha <sha>] [--fetch-missing-base] [--repo <dir>]

Event mode (--event) is what CI uses: the comparison commits are selected
from the raw GitHub event values by select_comparison(), a pure function the
selftests exercise directly:
  pull_request -> PR base SHA vs HEAD (the tested merge commit)
  push         -> event `before` vs HEAD (the whole multi-commit push); an
                  all-zero `before` (first push of a branch) has no previous
                  tree and passes with an explicit notice -- the
                  pull-request run is the gate for such a branch
  merge_group  -> the merge queue's trial merge: event
                  merge_group.base_sha (the target tip the trial merge
                  landed on) vs merge_group.head_sha (the trial-merge
                  commit). An empty or all-zero merge-group base is broken
                  event telemetry, not a first push, and fails closed.
Any event with no usable base fails with a diagnostic (exit 2), never a
silent pass. --fetch-missing-base keeps the workflow's best-effort
`git fetch --no-tags origin <base>` for a base not already in the clone
(e.g. a fork PR base); the gate still fails closed if the fetch cannot
produce it.

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
    re.compile(r"^sim/[^/]+/klt/(records|prototype)/"),
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


def select_comparison(event: str, pr_base: str = "", push_before: str = "",
                      mg_base: str = "", mg_head: str = "") -> tuple[str, str]:
    """Pure event -> (base, head) selection; raises GateError when the event
    carries no usable comparison base. No git I/O, so the selftests reach it
    without a repository."""
    if event == "merge_group":
        if not mg_base or ZERO.match(mg_base):
            raise GateError(
                "no comparison base for event merge_group "
                "(github.event.merge_group.base_sha is empty or all-zero); "
                "a merge-queue run always carries one, so this is broken "
                "event telemetry and the gate refuses to pass")
        if not mg_head:
            raise GateError(
                "no comparison head for event merge_group "
                "(github.event.merge_group.head_sha is empty); the gate "
                "refuses to pass without the comparison tree")
        return mg_base, mg_head
    if event == "pull_request":
        base = pr_base
    else:
        # push -- and any event the workflow is not configured for, which
        # falls through to the same no-base failure as the old shell step.
        base = push_before
    if not base:
        raise GateError(f"no comparison base for event {event}")
    return base, "HEAD"


def _has_commit(repo: str, rev: str) -> bool:
    p = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet",
                        f"{rev}^{{commit}}"], capture_output=True)
    return p.returncode == 0


def _try_fetch(repo: str, rev: str) -> None:
    # Belt-and-braces kept from the workflow step this selection replaced:
    # a base not already in the clone (e.g. a fork PR base) is fetched
    # best-effort; resolve() below still fails closed if it never appears.
    subprocess.run(["git", "-C", repo, "fetch", "--no-tags", "origin", rev],
                   capture_output=True)


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


def run(repo: str, base: str, head: str, out=sys.stdout, err=sys.stderr,
        fetch_missing_base: bool = False) -> int:
    if ZERO.match(base):
        print("append-only evidence: first push (all-zero base SHA); no previous "
              "tree to compare, nothing to enforce here. The pull-request run "
              "is the gate for this branch.", file=out)
        return 0
    if fetch_missing_base and not _has_commit(repo, base):
        _try_fetch(repo, base)
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
    ap.add_argument("--base", help="previous commit (rev or SHA); required "
                    "unless --event selects it")
    ap.add_argument("--head", default="HEAD", help="tested commit (default HEAD)")
    ap.add_argument("--repo", default=".", help="repository dir (default .)")
    ap.add_argument("--event", help="select the comparison commits from raw "
                    "GitHub event values (pull_request, push, merge_group)")
    ap.add_argument("--pr-base-sha", default="",
                    help="github.event.pull_request.base.sha")
    ap.add_argument("--push-before-sha", default="",
                    help="github.event.before")
    ap.add_argument("--merge-group-base-sha", default="",
                    help="github.event.merge_group.base_sha")
    ap.add_argument("--merge-group-head-sha", default="",
                    help="github.event.merge_group.head_sha")
    ap.add_argument("--fetch-missing-base", action="store_true",
                    help="best-effort `git fetch --no-tags origin <base>` when "
                    "the selected base is not in the clone (CI belt-and-braces)")
    a = ap.parse_args(argv)
    fetch = False
    if a.event is not None:
        try:
            base, head = select_comparison(
                a.event, pr_base=a.pr_base_sha, push_before=a.push_before_sha,
                mg_base=a.merge_group_base_sha, mg_head=a.merge_group_head_sha)
        except GateError as e:
            print(f"append-only evidence: ERROR: {e}", file=sys.stderr)
            return 2
        fetch = a.fetch_missing_base
    else:
        if not a.base:
            ap.error("--base is required unless --event selects it")
        base, head = a.base, a.head
    return run(a.repo, base, head, err=sys.stderr, fetch_missing_base=fetch)


if __name__ == "__main__":
    sys.exit(main())

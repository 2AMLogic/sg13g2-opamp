#!/usr/bin/env python3
"""Store a finished run's raw outputs in the artifact store; leave a manifest.

  python3 sim/tools/store_evidence.py --bench <bench> --run-id <run-id> PATH [PATH ...]

Raw outputs (files, or directories walked recursively) are staged in the
git-ignored scratch dir sim/.evidence-scratch/, stored with
`klt artifact put`, and only
  manifests/artifacts/<bench>-<run-id>.manifest.json   (klt's manifest)
  manifests/artifacts/<bench>-<run-id>.md              (name, size, sha256)
are written to tracked paths, for you to commit. See manifests/README.md.

Fail closed: $KLT_ARTIFACT_BROKER unset, no `klt artifact put`, an empty run,
an existing manifest of that name (append-only), or any failed upload exits
nonzero having written nothing to a tracked path. There is no fallback that
puts the bytes in git. $KLT_CMD overrides the `klt` executable.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SCRATCH_REL = Path("sim/.evidence-scratch")
MANIFEST_DIR = Path("manifests/artifacts")


class StoreError(Exception):
    pass


def collect(paths: list[Path]) -> list[tuple[Path, str]]:
    """(source file, relative name) pairs, sorted; directories walked."""
    found: dict[str, Path] = {}
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not f.is_symlink():
                    found[f.relative_to(p).as_posix()] = f
        elif p.is_file() and not p.is_symlink():
            found[p.name] = p
        else:
            raise StoreError(f"not a regular file or directory: {p}")
    if not found:
        raise StoreError("empty run: no files to store")
    for name, f in found.items():
        if f.stat().st_size == 0:
            raise StoreError(f"empty file cannot be stored: {name}")
    return [(f, n) for n, f in sorted(found.items())]


def preflight(klt: str) -> None:
    if not os.environ.get("KLT_ARTIFACT_BROKER"):
        raise StoreError("KLT_ARTIFACT_BROKER is not set (no default; fail closed)")
    if shutil.which(klt) is None:
        raise StoreError(f"{klt!r} not found on PATH")
    r = subprocess.run(
        [klt, "artifact", "put", "--help"], capture_output=True, check=False
    )
    if r.returncode != 0:
        raise StoreError(f"{klt!r} lacks `artifact put` (klayout-tools too old)")


def summary_md(bench: str, run_id: str, manifest: dict) -> str:
    lines = [
        f"# Stored evidence: {bench} / {run_id}",
        "",
        f"Objects live in the artifact store; `{bench}-{run_id}.manifest.json` "
        "names each by sha256. Fetch with `klt artifact get`; check with "
        "`klt artifact verify`.",
        "",
        "| name | size (bytes) | sha256 |",
        "|---|---:|---|",
    ]
    for e in manifest["entries"]:
        name = str(e.get("name", "")).replace("|", "\\|")
        lines.append(f"| {name} | {e['size']} | `{e['sha256']}` |")
    return "\n".join(lines) + "\n"


def store(root: Path, bench: str, run_id: str, paths: list[Path], klt: str) -> Path:
    for label, v in (("bench", bench), ("run-id", run_id)):
        if not ID_RE.match(v):
            raise StoreError(f"invalid {label} {v!r}")
    stem = f"{bench}-{run_id}"
    manifest_path = root / MANIFEST_DIR / f"{stem}.manifest.json"
    summary_path = root / MANIFEST_DIR / f"{stem}.md"
    preflight(klt)
    if manifest_path.exists() or summary_path.exists():
        raise StoreError(f"{manifest_path.name} already exists (append-only)")
    files = collect(paths)

    scratch = root / SCRATCH_REL / stem
    if scratch.exists():
        shutil.rmtree(scratch)
    try:
        for src, name in files:
            dst = scratch / "objects" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        tmp_manifest = scratch / "manifest.json"
        for src, name in files:
            staged = scratch / "objects" / name
            r = subprocess.run(
                [klt, "artifact", "put", "--manifest", str(tmp_manifest),
                 "--name", f"{bench}/{run_id}/{name}", str(staged)],
                capture_output=True, text=True, cwd=root, check=False,
            )
            if r.returncode != 0:
                raise StoreError(
                    f"`klt artifact put` failed for {name} (exit {r.returncode}): "
                    + (r.stderr or r.stdout).strip()
                )
        try:
            manifest = json.loads(tmp_manifest.read_text())
            if len(manifest["entries"]) != len(files):
                raise ValueError("entry count differs from file count")
        except (OSError, ValueError, KeyError) as e:
            raise StoreError(f"klt wrote no usable manifest: {e}")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("x") as f:
            f.write(tmp_manifest.read_text())
        with summary_path.open("x") as f:
            f.write(summary_md(bench, run_id, manifest))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("paths", nargs="+", type=Path, metavar="PATH")
    a = ap.parse_args(argv)
    try:
        m = store(a.root, a.bench, a.run_id, a.paths, os.environ.get("KLT_CMD", "klt"))
    except StoreError as e:
        print(f"store_evidence: {e}", file=sys.stderr)
        return 3
    print(f"stored; commit {m} and its .md summary")
    return 0


if __name__ == "__main__":
    sys.exit(main())

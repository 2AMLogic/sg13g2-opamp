#!/usr/bin/env python3
"""Offline check of the artifact manifests under manifests/ (stdlib only).

Evidence bytes for new runs live in the fleet artifact store; git keeps only a
manifest naming each object by sha256 (see manifests/README.md). This checks,
for every ``manifests/**/*.manifest.json``:

  * the schema ``klt artifact`` writes (schema_version 1; each entry carries
    exactly sha256/size/kind/producer/uri plus optional name/media_type);
  * every ``uri`` is ``artifact:<key>`` and the key's last path segment is the
    entry's sha256 (so no ``s3://`` URL or bucket name is ever committed);
  * no storage location leaks: no ``s3://`` / ``arn:aws:`` text in manifests/,
    and the broker URL ($KLT_ARTIFACT_BROKER, when set) appears in no tracked
    file under manifests/;
  * no stored object's bytes are also tracked in git (matched by sha256).

No network, no klt. Exit 0 = clean, 1 = problems, 2 = usage/environment.
Usage: python3 scripts/check_artifact_manifests.py [--root DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ENTRY_REQUIRED = ("sha256", "size", "kind", "producer", "uri")
ENTRY_OPTIONAL = ("name", "media_type")
PRODUCER_FIELDS = ("tool", "version", "loom.repo", "commit")
KINDS = ("evidence",)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URI_RE = re.compile(r"^artifact:([^/\s]\S*)$")
LEAK_RE = re.compile(r"s3://|arn:aws:")


def entry_problems(entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    out = []
    missing = [f for f in ENTRY_REQUIRED if f not in entry]
    extra = sorted(set(entry) - set(ENTRY_REQUIRED) - set(ENTRY_OPTIONAL))
    if missing:
        out.append("missing " + ", ".join(missing))
    if extra:
        out.append("unknown field(s) " + ", ".join(extra))
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        out.append("sha256 must be 64 lowercase hex digits")
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        out.append("size must be a positive integer")
    if entry.get("kind") not in KINDS:
        out.append("kind must be one of " + ", ".join(KINDS))
    prod = entry.get("producer")
    if not isinstance(prod, dict):
        out.append("producer is not an object")
    else:
        if set(prod) != set(PRODUCER_FIELDS):
            out.append("producer must carry exactly " + ", ".join(PRODUCER_FIELDS))
        for k in ("tool", "version", "loom.repo"):
            if not isinstance(prod.get(k), str) or not prod.get(k):
                out.append(f"producer.{k} must be a non-empty string")
        if prod.get("commit") is not None and not isinstance(prod.get("commit"), str):
            out.append("producer.commit must be a string or null")
    uri = entry.get("uri")
    if not isinstance(uri, str):
        out.append("uri must be a string")
    else:
        m = URI_RE.match(uri)
        if not m:
            out.append(f"uri {uri!r} must start with 'artifact:' (artifact:<key>)")
        elif m.group(1).rsplit("/", 1)[-1] != sha:
            out.append("uri key does not end in the entry's sha256")
    for k in ENTRY_OPTIONAL:
        if k in entry and not isinstance(entry[k], str):
            out.append(f"{k} must be a string")
    return out


def manifest_problems(doc: object) -> list[str]:
    if not isinstance(doc, dict):
        return ["manifest is not a JSON object"]
    out = []
    if set(doc) != {"schema_version", "entries"}:
        out.append("manifest must carry exactly schema_version, entries")
    if doc.get("schema_version") != 1:
        out.append("schema_version must be 1")
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        out.append("entries must be a non-empty list")
        return out
    names = set()
    for i, e in enumerate(entries):
        out += [f"entries[{i}]: {p}" for p in entry_problems(e)]
        n = e.get("name") if isinstance(e, dict) else None
        if isinstance(n, str):
            if n in names:
                out.append(f"entries[{i}]: duplicate name {n!r}")
            names.add(n)
    return out


def tracked_files(root: Path) -> list[Path]:
    r = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False
    )
    if r.returncode != 0:
        raise RuntimeError("git ls-files failed: " + r.stderr.decode(errors="replace"))
    return [root / p for p in r.stdout.decode().split("\0") if p]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(root: Path, broker: str | None) -> list[str]:
    problems: list[str] = []
    tracked = tracked_files(root)
    mdir = root / "manifests"
    stored: dict[str, int] = {}  # sha256 -> size
    in_mdir = [p for p in tracked if mdir in p.parents]
    for p in in_mdir:
        rel = p.relative_to(root)
        try:
            text = p.read_text(errors="replace")
        except OSError as e:
            problems.append(f"{rel}: unreadable: {e}")
            continue
        if LEAK_RE.search(text):
            problems.append(f"{rel}: contains an s3:// or arn:aws: storage location")
        if broker and broker in text:
            problems.append(f"{rel}: contains the artifact broker URL")
    for p in in_mdir:
        if not p.name.endswith(".manifest.json"):
            continue
        rel = p.relative_to(root)
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            problems.append(f"{rel}: not valid JSON: {e}")
            continue
        problems += [f"{rel}: {m}" for m in manifest_problems(doc)]
        if isinstance(doc, dict) and isinstance(doc.get("entries"), list):
            for e in doc["entries"]:
                if (
                    isinstance(e, dict)
                    and isinstance(e.get("sha256"), str)
                    and isinstance(e.get("size"), int)
                ):
                    stored[e["sha256"]] = e["size"]
    sizes = set(stored.values())
    if stored:
        for p in tracked:
            if p in in_mdir or not p.is_file() or p.is_symlink():
                continue
            if p.stat().st_size not in sizes:
                continue
            sha = sha256_of(p)
            if sha in stored:
                problems.append(
                    f"{p.relative_to(root)}: bytes are also stored as artifact "
                    f"{sha} (tracked in git as well)"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args(argv)
    try:
        problems = check(args.root, os.environ.get("KLT_ARTIFACT_BROKER") or None)
    except (RuntimeError, OSError) as e:
        print(f"check_artifact_manifests: {e}", file=sys.stderr)
        return 2
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return 1
    print("artifact manifests OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

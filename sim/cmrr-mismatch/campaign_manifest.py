#!/usr/bin/env python3
"""Campaign manifest for run_cmrr_mismatch_mc.sh's resumable campaigns (issue #163).

A resumed mismatch campaign reuses completed sample files, the DUT snapshot
and the saved pilot. That is only sound if the resumed invocation runs the
SAME experiment, so a fresh campaign publishes an immutable manifest of
every input that decides its samples, and a resume compares a freshly
rendered manifest against it before any artifact is reused.

Subcommands (stdlib only; no PDK, ngspice or klt; run with ``python3 -I``):

  render --repo-root R [--field K=V]... [--file K=PATH]... [--blob K=PATH]...
         [--libdir K=DIR]...
      Print the canonical manifest on stdout: one ``key: value`` line per
      entry, sorted by key, after one leading ``#`` comment line.
        --field K=V    literal value
        --file K=PATH  ``K: <path>`` plus ``K_sha256: <hex>``. The path is
                       recorded relative to R when it lies inside R, so
                       relocating the checkout does not change the manifest.
                       A missing file hashes as ``missing``.
        --blob K=PATH  ``K_sha256: <hex>`` only (bytes, never the location:
                       used for PDK files whose install prefix is per-host).
        --libdir K=DIR ``K_sha256``: one digest over every ``*.lib`` directly
                       under DIR (sorted ``name sha256`` lines), plus
                       ``K_count``. Any edited, added or removed model
                       library changes it.
  publish MANIFEST
      Read a rendered manifest on stdin and create MANIFEST atomically.
      Refuses (exit 3) if MANIFEST already exists: the manifest is immutable.
  compare MANIFEST
      Read the current rendered manifest on stdin and compare it to the
      stored MANIFEST. Exit 0 when identical; exit 4 with one diagnostic line
      per differing key (stored vs current value) otherwise.
  get MANIFEST KEY
      Print KEY's stored value (exit 5 if absent).
"""
import hashlib
import os
import sys

HEADER = "# cmrr-mismatch campaign manifest (issue #163), format 1 -- immutable; do not edit"
MISSING = "missing"


def _sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return MISSING


def _split(arg, opt):
    if "=" not in arg:
        sys.exit(f"campaign_manifest.py: {opt} expects KEY=VALUE, got {arg!r}")
    key, val = arg.split("=", 1)
    if not key or any(c in key for c in ": \t\n"):
        sys.exit(f"campaign_manifest.py: invalid key {key!r}")
    return key, val


def _check_value(key, val):
    if "\n" in val or "\r" in val:
        sys.exit(f"campaign_manifest.py: value for {key!r} contains a newline")
    return val


def _repo_rel(path, repo_root):
    real = os.path.realpath(path)
    root = os.path.realpath(repo_root)
    rel = os.path.relpath(real, root)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return real  # outside the checkout: recorded as-is (not relocatable)
    return rel.replace(os.sep, "/")


def _libdir_digest(d):
    try:
        names = sorted(n for n in os.listdir(d)
                       if n.endswith(".lib") and os.path.isfile(os.path.join(d, n)))
    except OSError:
        return MISSING, "0"
    h = hashlib.sha256()
    for n in names:
        h.update(f"{n} {_sha256(os.path.join(d, n))}\n".encode())
    return h.hexdigest(), str(len(names))


def render(argv):
    entries = {}
    repo_root = None
    i = 0

    def put(k, v):
        if k in entries:
            sys.exit(f"campaign_manifest.py: duplicate key {k!r}")
        entries[k] = _check_value(k, v)

    pending = []
    while i < len(argv):
        opt = argv[i]
        if i + 1 >= len(argv):
            sys.exit(f"campaign_manifest.py: {opt} needs a value")
        val = argv[i + 1]
        i += 2
        if opt == "--repo-root":
            repo_root = val
        elif opt in ("--field", "--file", "--blob", "--libdir"):
            pending.append((opt, val))
        else:
            sys.exit(f"campaign_manifest.py: render: unknown option {opt!r}")
    if repo_root is None:
        sys.exit("campaign_manifest.py: render needs --repo-root")
    for opt, arg in pending:
        k, v = _split(arg, opt)
        if opt == "--field":
            put(k, v)
        elif opt == "--file":
            put(k, _repo_rel(v, repo_root) if v else MISSING)
            put(f"{k}_sha256", _sha256(v) if v else MISSING)
        elif opt == "--blob":
            put(f"{k}_sha256", _sha256(v) if v else MISSING)
        else:
            digest, count = _libdir_digest(v)
            put(f"{k}_sha256", digest)
            put(f"{k}_count", count)
    out = [HEADER] + [f"{k}: {entries[k]}" for k in sorted(entries)]
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def parse(text):
    data = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        if ": " not in line and not line.endswith(":"):
            raise ValueError(f"line {n}: not a 'key: value' line: {line!r}")
        k, _, v = line.partition(":")
        if k in data:
            raise ValueError(f"line {n}: duplicate key {k!r}")
        data[k] = v[1:] if v.startswith(" ") else v
    return data


def publish(path):
    text = sys.stdin.read()
    try:
        parse(text)
    except ValueError as e:
        sys.exit(f"campaign_manifest.py: refusing to publish a malformed manifest: {e}")
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)  # atomic, and fails if path already exists
        except FileExistsError:
            print(f"campaign_manifest.py: {path} already exists -- the campaign manifest is immutable",
                  file=sys.stderr)
            return 3
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return 0


def compare(path):
    try:
        with open(path) as f:
            stored = parse(f.read())
    except OSError as e:
        print(f"campaign_manifest.py: cannot read stored manifest {path}: {e}", file=sys.stderr)
        return 4
    except ValueError as e:
        print(f"campaign_manifest.py: stored manifest {path} is malformed: {e}", file=sys.stderr)
        return 4
    current = parse(sys.stdin.read())
    diffs = []
    for k in sorted(set(stored) | set(current)):
        s = stored.get(k, "(absent)")
        c = current.get(k, "(absent)")
        if s != c:
            diffs.append(f"  {k}: stored={s} current={c}")
    if diffs:
        print("\n".join(diffs))
        return 4
    return 0


def get(path, key):
    with open(path) as f:
        data = parse(f.read())
    if key not in data:
        print(f"campaign_manifest.py: {path} has no key {key!r}", file=sys.stderr)
        return 5
    print(data[key])
    return 0


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "render":
        return render(rest)
    if cmd == "publish" and len(rest) == 1:
        return publish(rest[0])
    if cmd == "compare" and len(rest) == 1:
        return compare(rest[0])
    if cmd == "get" and len(rest) == 2:
        return get(rest[0], rest[1])
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

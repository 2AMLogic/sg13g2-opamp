#!/usr/bin/env python3
"""Continuously re-check the static facts the T1 item 1/9/10 inventories state.

The `generic` envelopes for T1 items 1, 9 and 10 bind the *bytes* of three
plain-text inventories (signoff/evidence/{design-sources,testbenches,
hygiene}.txt), and `check_signoff.py` re-hashes those files. A hash says the
inventory text did not move; it says nothing about whether what the text names
still exists. Deleting a cited bench record or dropping a runner's executable
bit leaves the inventory -- and so every hash -- untouched. This script closes
that gap for the cheap, objective subset of each inventory's dated audit.

It reads the inventories themselves (a documented, parseable subset of their
existing format -- see "Parseable subset" below and signoff/README.md), so a
path is checked because the inventory names it, not because a second list in
this file repeats it. Stdlib only, offline, PDK-free, no ngspice/xschem/klt.

  python3 signoff/check_inventories.py              # check this checkout
  python3 signoff/check_inventories.py --root DIR   # check another tree

Exit codes: 0 pass, 1 a check failed (every failure is printed, one per line,
as `FAIL: <inventory>:<line>: <entry>: <what failed>`).

Parseable subset
----------------
design-sources.txt, hygiene.txt -- every non-comment line is `key: value`.
  * For a *path key* (PATH_KEYS below) the value is one or more segments
    separated by top-level ` -> ` or `, `; each segment is
    `PATH [(parenthetical)]`. PATH must exist (`<bench>` expands to every
    bench directory testbenches.txt names). Inside the parenthetical, a
    `"Quoted"` string is a Markdown heading that must exist in PATH -- or in
    `X.md` when written `X.md "Quoted"` -- and `section N` requires a heading
    numbered N in PATH.
  * `netlist-origin: generated from PATH ...` must name the `schematic`.
  * `regenerate: cd DIR && xschem ... --rcfile RC -o OUT SCH` must resolve to
    the inventory's own `xschem-config`, netlist directory and `schematic`,
    and the netlist file name must be the schematic's stem + `.spice`.
  * Any other repo path (`a/b.ext`) in a non-path value must exist.
  * Key-specific: `license` naming Apache-2.0 requires LICENSE to carry the
    Apache License 2.0 header; `ci-workflow` requires the workflow to run on
    push and pull_request, to run check_signoff.py offline and with
    --run-klt, and to run this script.
testbenches.txt -- every non-comment line is
  `<spec row> | <bench dir> | <cold-start command> | <committed record>`.
  * bench dir exists under sim/; the command is a script inside it that
    exists, has the executable mode, and parses (`bash -n`); every literal
    `${EXPERIMENT_DIR}/testbench/<file>` it references exists (a `${var}`
    inside the name is matched as a glob that must hit at least one file);
    the bench README has a "Cold-start invocation" section naming the command;
  * the record exists under `<bench dir>/records/`, is non-empty and has its
    `.md` companion;
  * comment lines `# Shared harness: a, b, ...` name files that must exist
    (`.sh` ones must parse), indented comment lines that start with a
    `sim/...sh` command name a script that must also be executable, and
    `# Pinned PDK revision: FILE -> SOURCE release_tag TAG` must agree with
    FILE's `source`/`release_tag`.
In a git work tree whose top level is --root, every checked path must also be
tracked and every runner's *committed* mode must be 100755.

What this does NOT check (the dated manual audits remain the only basis):
schematic/netlist equivalence (the xschem regeneration diff), byte freshness
of any record or source, that any PVT/MC grid ran or would reproduce, that the
PDK/OSDI preflight resolves, or that README prose is accurate beyond the
presence of the named headings.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = "signoff/evidence"
DESIGN_SOURCES = f"{EVIDENCE}/design-sources.txt"
TESTBENCHES = f"{EVIDENCE}/testbenches.txt"
HYGIENE = f"{EVIDENCE}/hygiene.txt"
SELF = "signoff/check_inventories.py"

# Keys whose value is `PATH [(...)]` segments (see the module docstring).
PATH_KEYS = {
    DESIGN_SOURCES: (
        "schematic", "symbol", "netlist", "regenerate-doc", "xschem-config",
        "sizing-basis",
    ),
    HYGIENE: (
        "what-the-block-is", "spec-table", "how-to-reproduce", "license",
        "ci-workflow",
    ),
}
# Every key each inventory must carry: dropping a line is a failure here, not
# only a hash change.
REQUIRED_KEYS = {
    DESIGN_SOURCES: PATH_KEYS[DESIGN_SOURCES] + ("netlist-origin", "regenerate"),
    HYGIENE: PATH_KEYS[HYGIENE],
}
COLD_START_HEADING = "Cold-start invocation"

KV_RE = re.compile(r"^([A-Za-z][\w-]*):\s+(.*\S)\s*$")
REPO_PATH_RE = re.compile(r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.\w+)(?![\w/])")
QUOTED_RE = re.compile(r'(?:(\S+\.md)\s+)?"([^"]+)"')
SECTION_RE = re.compile(r"\bsection (\d+)\b")
TEMPLATE_RE = re.compile(r"\$\{EXPERIMENT_DIR\}/testbench/([\w.${}-]+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


class Checker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.failures: list[str] = []
        self.checks = 0
        self.tracked_paths: set[str] = set()  # paths to confirm are tracked
        self.runner_paths: set[str] = set()   # paths whose git mode must be 100755

    # -- reporting -------------------------------------------------------
    def fail(self, where: str, message: str) -> None:
        line = f"{where}: {message}"
        self.failures.append(line)
        print(f"FAIL: {line}")

    # -- primitives -------------------------------------------------------
    def need_file(self, where: str, rel: str, what: str = "path") -> bool:
        self.checks += 1
        path = self.root / rel
        if not path.exists():
            self.fail(where, f"{what} `{rel}` does not exist")
            return False
        self.tracked_paths.add(rel)
        return True

    def need_heading(self, where: str, rel: str, anchor: str) -> None:
        self.checks += 1
        path = self.root / rel
        if not path.is_file():
            return  # absence already reported by need_file
        if find_section(path.read_text(encoding="utf-8"), anchor) is None:
            self.fail(where, f"`{rel}` has no Markdown heading \"{anchor}\"")

    def need_numbered_section(self, where: str, rel: str, number: str) -> None:
        self.checks += 1
        path = self.root / rel
        if not path.is_file():
            return
        for _level, text, _body in iter_sections(path.read_text(encoding="utf-8")):
            if re.match(rf"{number}(?:\.|\s)", text):
                return
        self.fail(where, f"`{rel}` has no heading numbered \"{number}\" (section {number})")

    def need_runner(self, where: str, rel: str) -> bool:
        """Exists, executable mode, `bash -n` clean."""
        if not self.need_file(where, rel, "runner"):
            return False
        path = self.root / rel
        self.checks += 1
        mode = path.stat().st_mode
        if not mode & stat.S_IXUSR:
            self.fail(where, f"runner `{rel}` is not executable (mode {stat.filemode(mode)})")
        self.runner_paths.add(rel)
        self.need_bash_syntax(where, rel)
        return True

    def need_bash_syntax(self, where: str, rel: str) -> None:
        self.checks += 1
        proc = subprocess.run(
            ["bash", "-n", str(self.root / rel)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip().replace(str(self.root) + "/", "")
            self.fail(where, f"`bash -n {rel}` failed: {detail}")

    # -- inventories -------------------------------------------------------
    def read_inventory(self, rel: str) -> list[tuple[int, str]] | None:
        path = self.root / rel
        self.checks += 1
        if not path.is_file():
            self.fail(rel, "inventory does not exist")
            return None
        return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))

    def key_values(self, rel: str, lines) -> dict[str, tuple[int, str]]:
        found: dict[str, tuple[int, str]] = {}
        for lineno, raw in lines:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            m = KV_RE.match(raw)
            if not m:
                self.fail(f"{rel}:{lineno}", f"not a `key: value` line: {raw.strip()!r}")
                continue
            key, value = m.groups()
            if key in found:
                self.fail(f"{rel}:{lineno}", f"duplicate key `{key}`")
            found[key] = (lineno, value)
        for key in REQUIRED_KEYS[rel]:
            self.checks += 1
            if key not in found:
                self.fail(rel, f"required key `{key}:` is missing")
        return found

    def check_path_value(self, rel: str, key: str, lineno: int, value: str,
                         benches: list[str]) -> None:
        where = f"{rel}:{lineno}: {key}"
        for segment in split_top_level(value):
            m = re.match(r"^(\S+)\s*(?:\((.*)\))?\s*$", segment)
            if not m:
                self.fail(where, f"cannot parse segment {segment!r} as `PATH [(...)]`")
                continue
            target, paren = m.group(1), m.group(2) or ""
            targets = expand_bench(target, benches)
            for path in targets:
                self.need_file(where, path)
            for qm in QUOTED_RE.finditer(paren):
                doc, anchor = qm.group(1), qm.group(2)
                if doc:
                    if self.need_file(where, doc):
                        self.need_heading(where, doc, anchor)
                else:
                    for path in targets:
                        self.need_heading(where, path, anchor)
            for sm in SECTION_RE.finditer(paren):
                for path in targets:
                    self.need_numbered_section(where, path, sm.group(1))

    def check_design_sources(self, benches: list[str]) -> None:
        lines = self.read_inventory(DESIGN_SOURCES)
        if lines is None:
            return
        kv = self.key_values(DESIGN_SOURCES, lines)
        for key in PATH_KEYS[DESIGN_SOURCES]:
            if key in kv:
                self.check_path_value(DESIGN_SOURCES, key, *kv[key], benches)

        first = lambda key: kv[key][1].split()[0] if key in kv else None  # noqa: E731
        schematic, netlist, rcfile = first("schematic"), first("netlist"), first("xschem-config")

        if "netlist-origin" in kv:
            lineno, value = kv["netlist-origin"]
            where = f"{DESIGN_SOURCES}:{lineno}: netlist-origin"
            self.checks += 1
            m = re.match(r"generated from (\S+)", value)
            if not m:
                self.fail(where, "expected `generated from <schematic> ...`")
            elif m.group(1) != schematic:
                self.fail(where, f"names `{m.group(1)}`, but `schematic:` is `{schematic}`")

        if "regenerate" in kv:
            lineno, value = kv["regenerate"]
            self.check_regenerate(f"{DESIGN_SOURCES}:{lineno}: regenerate", value,
                                  schematic, netlist, rcfile)

        for key, (lineno, value) in kv.items():
            if key in PATH_KEYS[DESIGN_SOURCES] or key == "regenerate":
                continue
            for m in REPO_PATH_RE.finditer(value):
                self.need_file(f"{DESIGN_SOURCES}:{lineno}: {key}", m.group(1))

    def check_regenerate(self, where: str, value: str, schematic, netlist, rcfile) -> None:
        self.checks += 1
        try:
            argv = shlex.split(value)
        except ValueError as exc:
            self.fail(where, f"cannot tokenize command: {exc}")
            return
        if len(argv) < 4 or argv[0] != "cd" or argv[2] != "&&" or argv[3] != "xschem":
            self.fail(where, "expected `cd <dir> && xschem ...`")
            return
        cwd = PurePosixPath(argv[1])
        if not (self.root / cwd).is_dir():
            self.fail(where, f"`cd {cwd}`: directory does not exist")
        args = argv[4:]
        opts: dict[str, str] = {}
        positional: list[str] = []
        i = 0
        while i < len(args):
            if args[i] in ("--rcfile", "-o") and i + 1 < len(args):
                opts[args[i]] = args[i + 1]
                i += 2
                continue
            if not args[i].startswith("-"):
                positional.append(args[i])
            i += 1

        def resolve(arg: str) -> str:
            return norm(cwd / arg)

        if rcfile is not None:
            got = resolve(opts["--rcfile"]) if "--rcfile" in opts else None
            if got != rcfile:
                self.fail(where, f"--rcfile resolves to `{got}`, but `xschem-config:` is `{rcfile}`")
        if netlist is not None:
            got = resolve(opts["-o"]) if "-o" in opts else None
            want = str(PurePosixPath(netlist).parent)
            if got != want:
                self.fail(where, f"-o resolves to `{got}`, but `netlist:` lives in `{want}`")
        sch_args = [resolve(a) for a in positional if a.endswith(".sch")]
        if schematic is not None:
            if sch_args != [schematic]:
                self.fail(where, f"schematic argument resolves to {sch_args}, expected [`{schematic}`]")
            if netlist is not None and PurePosixPath(netlist).name != PurePosixPath(schematic).stem + ".spice":
                self.fail(where, f"xschem writes `{PurePosixPath(schematic).stem}.spice`, "
                                 f"but `netlist:` is `{netlist}`")

    def check_hygiene(self, benches: list[str]) -> None:
        lines = self.read_inventory(HYGIENE)
        if lines is None:
            return
        kv = self.key_values(HYGIENE, lines)
        for key in PATH_KEYS[HYGIENE]:
            if key in kv:
                self.check_path_value(HYGIENE, key, *kv[key], benches)

        if "license" in kv:
            lineno, value = kv["license"]
            where = f"{HYGIENE}:{lineno}: license"
            lic = value.split()[0]
            path = self.root / lic
            if "Apache-2.0" in value and path.is_file():
                self.checks += 1
                head = path.read_text(encoding="utf-8", errors="replace")[:2000]
                if "Apache License" not in head or "Version 2.0" not in head:
                    self.fail(where, f"`{lic}` does not carry the Apache License, Version 2.0 header")

        if "ci-workflow" in kv:
            lineno, value = kv["ci-workflow"]
            where = f"{HYGIENE}:{lineno}: ci-workflow"
            wf = value.split()[0]
            path = self.root / wf
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for needle, why in (
                    (r"(?m)^\s+push:", "a `push:` trigger"),
                    (r"(?m)^\s+pull_request:", "a `pull_request:` trigger"),
                    (r"(?m)^\s+run: python3 signoff/check_signoff\.py\s*$", "the offline `check_signoff.py` step"),
                    (r"check_signoff\.py --run-klt", "the `check_signoff.py --run-klt` re-grade"),
                    (rf"(?m)^\s+run: python3 {re.escape(SELF)}\s*$", f"the `{SELF}` step"),
                ):
                    self.checks += 1
                    if not re.search(needle, text):
                        self.fail(where, f"`{wf}` lacks {why}")

    def check_testbenches(self) -> list[str]:
        """Returns the bench directories named, for `<bench>` expansion."""
        lines = self.read_inventory(TESTBENCHES)
        if lines is None:
            return []
        benches: list[str] = []
        rows = 0
        for lineno, raw in lines:
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                self.check_testbench_comment(lineno, stripped)
                continue
            fields = [f.strip() for f in raw.split("|")]
            where = f"{TESTBENCHES}:{lineno}"
            if len(fields) != 4 or not all(fields):
                self.fail(where, "expected `<spec row> | <bench dir> | <command> | <record>`")
                continue
            rows += 1
            row, bench, command, record = fields
            where = f"{where}: {row}"
            if bench not in benches:
                benches.append(bench)
            self.check_bench_row(where, bench, command, record)
        self.checks += 1
        if rows == 0:
            self.fail(TESTBENCHES, "no testbench rows parsed")
        return benches

    def check_bench_row(self, where: str, bench: str, command: str, record: str) -> None:
        self.checks += 1
        if not bench.startswith("sim/") or not (self.root / bench).is_dir():
            self.fail(where, f"bench dir `{bench}` does not exist under sim/")
            return
        self.checks += 1
        if PurePosixPath(command).parent != PurePosixPath(bench):
            self.fail(where, f"command `{command}` is not a script in `{bench}`")
        elif self.need_runner(where, command):
            self.check_templates(where, bench, command)
        readme = f"{bench}/README.md"
        if self.need_file(where, readme, "bench README"):
            self.checks += 1
            body = find_section((self.root / readme).read_text(encoding="utf-8"), COLD_START_HEADING)
            if body is None:
                self.fail(where, f"`{readme}` has no \"{COLD_START_HEADING}\" heading")
            elif not re.search(rf"(?m)^\s*{re.escape(command)}(?:\s|$)", body):
                self.fail(where, f"`{readme}` \"{COLD_START_HEADING}\" does not name `{command}`")
        self.checks += 1
        if PurePosixPath(record).parent != PurePosixPath(bench) / "records":
            self.fail(where, f"record `{record}` is not under `{bench}/records/`")
        if self.need_file(where, record, "cited record"):
            self.checks += 1
            if (self.root / record).stat().st_size == 0:
                self.fail(where, f"cited record `{record}` is empty")
            companion = str(PurePosixPath(record).with_suffix(".md"))
            if companion != record:
                self.need_file(where, companion, "cited record's .md companion")

    def check_templates(self, where: str, bench: str, command: str) -> None:
        text = (self.root / command).read_text(encoding="utf-8", errors="replace")
        testbench = self.root / bench / "testbench"
        for name in sorted(set(TEMPLATE_RE.findall(text))):
            self.checks += 1
            pattern = re.sub(r"\$\{[^}]*\}", "*", name)
            hits = sorted(p.name for p in testbench.glob("*") if fnmatch.fnmatch(p.name, pattern)) \
                if testbench.is_dir() else []
            if not hits:
                self.fail(where, f"template `{bench}/testbench/{name}` referenced by `{command}` does not exist")
            else:
                for hit in hits:
                    self.tracked_paths.add(f"{bench}/testbench/{hit}")

    def check_testbench_comment(self, lineno: int, line: str) -> None:
        where = f"{TESTBENCHES}:{lineno}"
        m = re.match(r"#\s*Shared harness:\s*(.*)$", line)
        if m:
            for rel in (p.strip() for p in m.group(1).split(",")):
                if self.need_file(f"{where}: shared harness", rel) and rel.endswith(".sh"):
                    self.need_bash_syntax(f"{where}: shared harness", rel)
            return
        m = re.match(r"#\s{2,}(sim/[\w./-]+\.sh)(?:\s|$)", line)
        if m:
            self.need_runner(f"{where}: common command", m.group(1))
            return
        m = re.match(r"#\s*Pinned PDK revision:\s*(\S+)\s*->\s*(\S+)\s+release_tag\s+(\S+)", line)
        if m:
            rel, source, tag = m.groups()
            if self.need_file(f"{where}: PDK pin", rel):
                self.checks += 1
                try:
                    doc = json.loads((self.root / rel).read_text(encoding="utf-8"))
                except ValueError as exc:
                    self.fail(f"{where}: PDK pin", f"`{rel}` is not JSON: {exc}")
                    return
                if doc.get("source") != source or doc.get("release_tag") != tag:
                    self.fail(f"{where}: PDK pin",
                              f"`{rel}` pins {doc.get('source')} {doc.get('release_tag')}, "
                              f"inventory states {source} {tag}")

    # -- git -----------------------------------------------------------------
    def check_git(self) -> None:
        try:
            top = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != self.root.resolve():
            return
        paths = sorted(self.tracked_paths | self.runner_paths)
        if not paths:
            return
        listed = subprocess.run(
            ["git", "-C", str(self.root), "ls-files", "-s", "--", *paths],
            capture_output=True, text=True, check=True,
        ).stdout
        modes: dict[str, str] = {}
        for entry in listed.splitlines():
            meta, _, path = entry.partition("\t")
            modes[path] = meta.split()[0]
        tracked_dirs = {str(PurePosixPath(p).parent) for p in modes}
        for rel in paths:
            self.checks += 1
            if rel in modes:
                continue
            if (self.root / rel).is_dir() and any(d == rel or d.startswith(rel + "/") for d in tracked_dirs):
                continue
            self.fail("git", f"`{rel}` exists but is not tracked (not committed)")
        for rel in sorted(self.runner_paths):
            self.checks += 1
            if rel in modes and modes[rel] != "100755":
                self.fail("git", f"runner `{rel}` is committed with mode {modes[rel]}, not 100755")

    def run(self) -> int:
        benches = self.check_testbenches()
        self.check_design_sources(benches)
        self.check_hygiene(benches)
        self.check_git()
        if self.failures:
            print(f"inventory check: {len(self.failures)} failure(s) in {self.checks} checks")
            return 1
        print(f"inventory check: OK ({self.checks} checks over "
              f"{DESIGN_SOURCES}, {TESTBENCHES}, {HYGIENE})")
        return 0


# -- helpers -------------------------------------------------------------------

def norm(path: PurePosixPath) -> str:
    parts: list[str] = []
    for part in path.parts:
        if part == ".":
            continue
        if part == ".." and parts:
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def split_top_level(value: str) -> list[str]:
    """Split on ` -> ` and `, ` outside parentheses and double quotes."""
    out, buf, depth, quoted, i = [], [], 0, False, 0
    while i < len(value):
        ch = value[i]
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
        if depth == 0 and not quoted:
            for sep in (" -> ", ", "):
                if value.startswith(sep, i):
                    out.append("".join(buf).strip())
                    buf, i = [], i + len(sep)
                    break
            else:
                buf.append(ch)
                i += 1
            continue
        buf.append(ch)
        i += 1
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def expand_bench(target: str, benches: list[str]) -> list[str]:
    if "<bench>" not in target:
        return [target]
    return [target.replace("sim/<bench>", b) for b in benches] if target.startswith("sim/<bench>") \
        else [target]


def iter_sections(markdown: str):
    """Yield (level, heading text, body) for each heading outside code fences."""
    lines = markdown.splitlines()
    heads: list[tuple[int, int, str]] = []
    fenced = False
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = HEADING_RE.match(line)
        if m:
            heads.append((idx, len(m.group(1)), m.group(2)))
    for n, (idx, level, text) in enumerate(heads):
        end = len(lines)
        for later_idx, later_level, _ in heads[n + 1:]:
            if later_level <= level:
                end = later_idx
                break
        yield level, text, "\n".join(lines[idx + 1:end])


def find_section(markdown: str, anchor: str) -> str | None:
    """Body of the first heading equal to, or starting with, `anchor`."""
    for _level, text, body in iter_sections(markdown):
        if text == anchor or text.startswith(anchor):
            return body
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="repository root to check (default: this checkout)")
    args = parser.parse_args(argv)
    return Checker(args.root.resolve()).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

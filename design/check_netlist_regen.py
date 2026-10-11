#!/usr/bin/env python3
"""Check that design/opamp_core.sch still regenerates design/netlist/opamp_core.spice.

Closes the schematic -> netlist link of the evidence chain (the static
inventory checker explicitly excludes it). Runs the documented headless
xschem netlisting into a TEMPORARY directory, then compares the electrical
statements of the result with the committed netlist. The committed netlist
is never written in check mode.

Normalization (same rule as signoff/characterization/generate.py
normalized_netlist_hash): blank lines and full-line SPICE comments (`*...`,
which includes host-specific `** sch_path:` and `**.subckt` lines) are
dropped; trailing whitespace is stripped; everything else -- connections,
models, parameters, directives, statement order -- is compared verbatim.

The comparison logic (normalize / compare) is stdlib-only and offline; only
run_xschem() needs xschem and a resolvable SG13G2 PDK (PDK_ROOT/PDK).

Usage:
  python3 design/check_netlist_regen.py            # check (exit 0 match, 1 diff, 2 tool failure)
  python3 design/check_netlist_regen.py --update   # intentional refresh of the committed netlist
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DESIGN = Path(__file__).resolve().parent
SCHEMATIC = DESIGN / "opamp_core.sch"
COMMITTED = DESIGN / "netlist" / "opamp_core.spice"

# xschem can exit 0 while reporting unresolved symbols / bad config on stderr.
STDERR_FATAL = re.compile(
    r"(?i)\berror\b|\bcannot\b|\bcan't\b|could not|unable to|not found|"
    r"missing|no .* install found|no such file|\bfailed\b"
)


class ToolFailure(Exception):
    """xschem could not produce a trustworthy netlist (never counts as a match)."""


def normalize(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        out.append(line.rstrip())
    return out


def compare(committed: str, generated: str) -> str:
    """Return '' when the electrical netlists match, else a unified diff."""
    a, b = normalize(committed), normalize(generated)
    if a == b:
        return ""
    return "\n".join(
        difflib.unified_diff(a, b, "committed netlist", "regenerated from schematic", lineterm="")
    )


def check_stderr(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if STDERR_FATAL.search(ln)]


def run_xschem(schematic: Path, outdir: Path, env: dict) -> tuple[Path, str]:
    """Netlist `schematic` into `outdir`; return (generated path, xschem version)."""
    xschem = shutil.which("xschem")
    if not xschem:
        raise ToolFailure("xschem not found on PATH")
    if not env.get("PDK_ROOT"):
        raise ToolFailure("PDK_ROOT is not set (need an open_pdks-shaped ihp-sg13g2 install)")
    pdk = env.get("PDK", "ihp-sg13g2")
    if not (Path(env["PDK_ROOT"]) / pdk / "libs.tech" / "xschem").is_dir():
        raise ToolFailure(f"no {pdk}/libs.tech/xschem under PDK_ROOT={env['PDK_ROOT']}")
    ver = subprocess.run([xschem, "--version"], capture_output=True, text=True, env=env)
    version = (ver.stdout or ver.stderr).strip().splitlines()[0] if (ver.stdout or ver.stderr).strip() else "unknown"
    cmd = [xschem, "-n", "-x", "-q", "-r", "--rcfile", str(DESIGN / "xschemrc"),
           "-o", str(outdir), str(schematic)]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=DESIGN)
    if proc.returncode != 0:
        raise ToolFailure(f"xschem exited {proc.returncode}:\n{proc.stdout}{proc.stderr}")
    bad = check_stderr(proc.stderr)
    if bad:
        raise ToolFailure("xschem reported problems:\n" + "\n".join(bad))
    generated = outdir / (schematic.stem + ".spice")
    if not generated.is_file() or generated.stat().st_size == 0:
        raise ToolFailure(f"xschem produced no netlist at {generated}")
    return generated, version


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true",
                    help="overwrite the committed netlist with the regenerated one (intentional refresh)")
    args = ap.parse_args(argv)

    env = dict(os.environ)
    env.setdefault("PDK", "ihp-sg13g2")
    with tempfile.TemporaryDirectory(prefix="netlist-regen-") as tmp:
        try:
            generated, version = run_xschem(SCHEMATIC, Path(tmp), env)
        except ToolFailure as exc:
            print(f"FAIL (tool): {exc}", file=sys.stderr)
            return 2
        print(f"tool: {version}")
        pdk_ver = Path(env["PDK_ROOT"]) / env["PDK"] / ".fetched-version"
        if pdk_ver.is_file():
            print(f"pdk: {env['PDK']} {pdk_ver.read_text().strip()}")
        new = generated.read_text(encoding="utf-8")
        if args.update:
            COMMITTED.write_text(new, encoding="utf-8")
            print(f"updated {COMMITTED}")
            return 0
        if not COMMITTED.is_file():
            print(f"FAIL: committed netlist {COMMITTED} is missing", file=sys.stderr)
            return 1
        diff = compare(COMMITTED.read_text(encoding="utf-8"), new)
    if diff:
        print("FAIL: schematic no longer regenerates the committed netlist:\n" + diff, file=sys.stderr)
        print("If the schematic change is intentional: design/README.md 'Schematic-to-netlist "
              "regeneration check'.", file=sys.stderr)
        return 1
    print("OK: regenerated netlist matches design/netlist/opamp_core.spice (comments/blank lines ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Keep spec/integrator.json in step with the committed signoff record and layout.

The integrator view is a fixed-path consumer interface. Its graded-maturity
fields and published artifact paths are derived, not hand-edited:

  * maturity.{tier,t1_items_total,t1_items_met,statement,source_record} and
    provenance.signoff_record come from the newest committed record under
    signoff/reports/, ordered exactly as signoff/check_signoff.py orders them
    (lexicographic sort of *.signoff.json, last wins);
  * artifacts.gds is the committed layout GDS, and every published artifact
    path must exist in the tree.

Nothing here ratifies a bound or the Area row; ratified rows, ports and
consumer verdicts are never touched. Their consistency with the symbol and
the ratified table is checked read-only by signoff/check_integrator_contract.py.

  python3 signoff/sync_integrator.py --check    # offline; exit 1 on drift
  python3 signoff/sync_integrator.py --update   # rewrite managed fields in place

Stdlib-only, no klt, no network. Update mode is deterministic and edits only
the managed single-line values, leaving the rest of the file byte-identical.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATOR = REPO_ROOT / "spec" / "integrator.json"
REPORTS_DIR = REPO_ROOT / "signoff" / "reports"
GDS_PATH = "layout/opamp_core/opamp_core.gds"
GDS_NOTE = (
    "committed layout GDS (top cell opamp_core); availability only - not a "
    "foundry-signoff claim and not an Area ratification (target-spec.md row "
    "TBD-12 stays unratified, area_mm2 unset); graded maturity is in 'maturity'"
)
# artifacts.* entries that are plain repo-relative paths and must exist.
PATH_ARTIFACTS = ("schematic", "symbol", "sizing_derivation", "netlist", "gds")


def newest_record() -> Path:
    # Same ordering as signoff/check_signoff.py:latest_report.
    reports = sorted(REPORTS_DIR.glob("*.signoff.json"))
    if not reports:
        raise SystemExit(f"no *.signoff.json record under {REPORTS_DIR}")
    return reports[-1]


def derive() -> dict:
    record = newest_record()
    doc = json.loads(record.read_text())
    total, met = doc["t1_item_count"], doc["t1_met_count"]
    tier = doc.get("tier")
    rec = record.relative_to(REPO_ROOT).as_posix()
    return {
        "gds": GDS_PATH,
        "gds_note": GDS_NOTE,
        "tier": tier,
        "t1_items_total": total,
        "t1_items_met": met,
        "statement": (
            f"T1 ('sim-validated') rung: {met} of {total} checklist items met "
            f"per the newest klt signoff record; not a hand-guessed tier."
        ),
        "source_record": rec,
        "signoff_record": rec,
    }


def current(view: dict) -> dict:
    a, m, p = view["artifacts"], view["maturity"], view["provenance"]
    return {
        "gds": a.get("gds"),
        "gds_note": a.get("gds_note"),
        "tier": m.get("tier"),
        "t1_items_total": m.get("t1_items_total"),
        "t1_items_met": m.get("t1_items_met"),
        "statement": m.get("statement"),
        "source_record": m.get("source_record"),
        "signoff_record": p.get("signoff_record"),
    }


def check() -> list[str]:
    problems = []
    view = json.loads(INTEGRATOR.read_text())
    want, have = derive(), current(view)
    for key, value in want.items():
        if have[key] != value:
            problems.append(f"stale {key}: integrator has {have[key]!r}, derived {value!r}")
    for name in PATH_ARTIFACTS:
        path = view["artifacts"].get(name)
        if not isinstance(path, str) or not (REPO_ROOT / path).is_file():
            problems.append(f"artifacts.{name} {path!r} does not resolve to a committed file")
    return problems


def update() -> bool:
    text = INTEGRATOR.read_text()
    for key, value in derive().items():
        pattern = re.compile(rf'^(\s*"{key}":\s*)(.*?)(,?)$', re.M)
        matches = pattern.findall(text)
        if len(matches) != 1:
            raise SystemExit(f"expected exactly one single-line '{key}' in {INTEGRATOR}")
        text = pattern.sub(
            lambda m, v=value: f"{m.group(1)}{json.dumps(v, ensure_ascii=False)}{m.group(3)}",
            text,
        )
    changed = text != INTEGRATOR.read_text()
    json.loads(text)  # must remain valid JSON
    INTEGRATOR.write_text(text)
    return changed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--update", action="store_true")
    args = ap.parse_args(argv)
    if args.update:
        print("updated" if update() else "already up to date", INTEGRATOR.relative_to(REPO_ROOT))
        return 0
    problems = check()
    for p in problems:
        print(f"  FAIL {p}")
    if problems:
        print(f"FAIL: spec/integrator.json is stale ({len(problems)} problem(s)); "
              "run: python3 signoff/sync_integrator.py --update")
        return 1
    print("PASS: spec/integrator.json matches the newest signoff record and published artifacts.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

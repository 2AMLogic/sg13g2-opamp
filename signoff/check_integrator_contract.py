#!/usr/bin/env python3
"""Read-only contract check: spec/integrator.json against its sources.

Complements signoff/sync_integrator.py. That tool owns the *managed* fields
(maturity, GDS path, artifact existence) and deliberately never touches ports
or ratified rows. This checker owns the opposite half: it never writes
anything, and compares what the integrator view *publishes* about the
interface against the files it is derived from:

  * ports[]  -- names, order and direction against design/opamp_core.sym
                (pins ordered by `pinnumber`);
  * spec_rows_ratified -- every published number against the ratified bound
                written in spec/target-spec.md, via the explicit FIELDS table
                below (published key -> spec row, anchored bound phrase, unit,
                direction, load/measurement basis);
  * variant.supply_v / load.capacitance_pf against the section 1 rows;
  * spec_rows_not_ratified / area_mm2 -- offset 3-sigma, ICMR and Area must
                stay unratified and unnumbered, in the view and in the spec.

Each bound is read from the *Target* cell of its own row with a regex anchored
at the start of the cell on the ratification phrase, direction and unit, so a
number that merely appears elsewhere in the row's prose (measured envelope,
superseded floor, spot densities) can never satisfy a mismatched bound. A
source whose phrasing no longer matches is reported as malformed, not skipped.

A failure names the published field and the source; it never rewrites the
spec, the view, or relaxes a bound. After a ratification changes a target
bound, refresh the published value by hand (ratification stays with the keys).

  python3 signoff/check_integrator_contract.py         # exit 1 on any mismatch

Stdlib-only, offline: no PDK, simulator, klt or network.
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATOR_REL = "spec/integrator.json"
SYMBOL_REL = "design/opamp_core.sym"
SPEC_REL = "spec/target-spec.md"

NUM = r"(?P<v>\d+(?:\.\d+)?)"

# published key -> (spec row prefix, anchored Target-cell pattern, why).
# The row prefix carries the load/measurement basis where the row label states
# one (CL for GBW/slew, band for noise); the pattern carries ratification tag,
# direction and unit. Order is the published order.
FIELDS: dict[str, tuple[str, str, str]] = {
    "dc_gain_db_worst_min": (
        "| Open-loop DC gain |",
        rf"^\*\*Ratified bound ≥ {NUM} dB worst-case \[DR-2\]\*\*",
        "dB, minimum",
    ),
    "gbw_mhz_worst_min_into_2pf": (
        "| GBW (into stated CL = 2 pF [DR-1]",
        rf"^\*\*Ratified bound ≥ {NUM} MHz worst-case \[DR-2\]\*\*",
        "MHz, minimum, into CL = 2 pF",
    ),
    "phase_margin_deg_worst_min": (
        "| Phase margin (at GBW, same CL) |",
        rf"^\*\*Ratified bound ≥ {NUM}° \[DR-2\]\*\*",
        "degrees, minimum",
    ),
    "slew_v_per_us_worst_min": (
        "| Slew rate (into stated CL = 2 pF [DR-1]",
        rf"^\*\*Ratified bound ≥ {NUM} V/µs worst-case \[DR-2\]\*\*",
        "V/us, minimum, into CL = 2 pF",
    ),
    "input_noise_uv_rms_worst_max_100Hz_1MHz": (
        "| Input-referred noise (band: **100 Hz – 1 MHz integrated**",
        rf"^\*\*Ratified bound ≤ {NUM} µVrms worst-case \[DR-2\]\*\*, integrated over 100 Hz – 1 MHz",
        "uVrms, maximum, integrated 100 Hz - 1 MHz",
    ),
    "offset_systematic_mv_worst_max": (
        "| Input-referred offset |",
        rf"^\*\*Systematic \(deterministic, corner-only\): ratified bound \+{NUM} mV worst-case \[DR-2\]\*\*",
        "mV, maximum, systematic half only",
    ),
    "cmrr_db_worst_min_mismatch_inclusive": (
        "| CMRR |",
        rf"^\*\*Ratified bound ≥ {NUM} dB worst-case — mismatch-inclusive CMRR, the \+3σ-of-Acm figure \[DR-4\]\*\*",
        "dB, minimum, mismatch-inclusive (+3 sigma of Acm) basis",
    ),
    "psrr_db_worst_min_dc_shelf": (
        "| PSRR |",
        rf"^\*\*Ratified bound ≥ {NUM} dB worst-case \(DC shelf; PSRR\+\) \[DR-2\]\*\*",
        "dB, minimum, DC shelf, PSRR+",
    ),
    "output_swing_span_v_worst_min": (
        "| Output swing |",
        rf"^\*\*Ratified bound: headroom ≥ \d+(?:\.\d+)? mV from VDD and ≥ \d+(?:\.\d+)? mV from VSS "
        rf"worst-case, tracking span ≥ {NUM} V worst-case \[DR-2\]\*\*",
        "V, minimum span, unloaded (CL only)",
    ),
    "iq_ua_worst_max_total_incl_ibias": (
        "| Quiescent power |",
        rf"^\*\*Ratified bound Iq ≤ {NUM} uA worst-case \(total Vdd current, incl\. the external 10 uA "
        rf"`ibias` reference\) \[DR-2\]\*\*",
        "uA, maximum, total Vdd current including ibias",
    ),
}

# Rows that must stay unratified: view key -> why. They may not appear in
# spec_rows_ratified and the published area number must stay null.
NOT_RATIFIED = ("offset_mismatch_3sigma_mv", "input_common_mode_range_v", "area")

PIN_RE = re.compile(r"^B\s+5\s+\S+\s+\S+\s+\S+\s+\S+\s+\{([^}]*)\}\s*$", re.M)


def _dec(obj):
    return json.loads(obj, parse_float=Decimal)


def read_symbol_pins(text: str) -> list[dict]:
    pins = []
    for m in PIN_RE.finditer(text):
        attrs = dict(kv.split("=", 1) for kv in m.group(1).split() if "=" in kv)
        if {"name", "dir", "pinnumber"} <= attrs.keys():
            pins.append(attrs)
    pins.sort(key=lambda a: int(a["pinnumber"]) if a["pinnumber"].isdigit() else 10**9)
    return pins


def split_row(line: str) -> list[str]:
    # Cells separated by unescaped pipes; the spec escapes literal ones as \|.
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]


def spec_row(lines: list[str], prefix: str) -> tuple[list[str] | None, str | None]:
    hits = [ln for ln in lines if ln.startswith(prefix)]
    if len(hits) != 1:
        return None, f"{len(hits)} {SPEC_REL} rows start with {prefix!r} (need exactly 1)"
    return split_row(hits[0]), None


def check_ports(view: dict, root: Path, problems: list[str]) -> None:
    sym = root / SYMBOL_REL
    if not sym.is_file():
        problems.append(f"{SYMBOL_REL}: missing, cannot verify ports")
        return
    pins = read_symbol_pins(sym.read_text(encoding="utf-8"))
    published = view.get("ports")
    if not pins:
        problems.append(f"{SYMBOL_REL}: no pins found (symbol format changed?)")
        return
    if not isinstance(published, list):
        problems.append("ports: not a list")
        return
    want = [p["name"] for p in pins]
    have = [p.get("name") if isinstance(p, dict) else None for p in published]
    if have != want:
        problems.append(
            f"ports order/names: integrator.json publishes {have}, {SYMBOL_REL} "
            f"(pinnumber order) has {want}"
        )
        return
    for i, (pub, pin) in enumerate(zip(published, pins)):
        if pub.get("symbol_dir") != pin["dir"]:
            problems.append(
                f"ports[{i}] ({pin['name']}).symbol_dir: integrator.json has "
                f"{pub.get('symbol_dir')!r}, {SYMBOL_REL} dir={pin['dir']!r}"
            )


def check_ratified(view: dict, lines: list[str], problems: list[str]) -> None:
    pub = view.get("spec_rows_ratified")
    if not isinstance(pub, dict):
        problems.append("spec_rows_ratified: missing or not an object")
        return
    published = {k: v for k, v in pub.items() if k != "source"}
    for key in published:
        if key not in FIELDS:
            problems.append(
                f"spec_rows_ratified.{key}: no source mapping in {Path(__file__).name} FIELDS "
                "(an unmapped or unratified row may not be published as ratified)"
            )
    for key, (prefix, pattern, basis) in FIELDS.items():
        if key not in published:
            problems.append(f"spec_rows_ratified.{key}: required row missing from integrator.json")
            continue
        cells, why = spec_row(lines, prefix)
        if why:
            problems.append(f"spec_rows_ratified.{key}: {why}")
            continue
        m = re.search(pattern, cells[1]) if len(cells) > 1 else None
        if not m:
            problems.append(
                f"spec_rows_ratified.{key}: bound in {SPEC_REL} row {prefix!r} is malformed or "
                f"no longer in the expected ratified form ({basis})"
            )
            continue
        value, source = published[key], Decimal(m.group("v"))
        if isinstance(value, bool) or not isinstance(value, (Decimal, int)) or Decimal(value) != source:
            problems.append(
                f"spec_rows_ratified.{key}: integrator.json has {value!r}, {SPEC_REL} ratified "
                f"bound is {source} ({basis}); refresh the published value explicitly"
            )


def check_conditions(view: dict, lines: list[str], problems: list[str]) -> None:
    cells, why = spec_row(lines, "| Supply voltage, VDD |")
    if why:
        problems.append(f"variant.supply_v: {why}")
    else:
        m = re.search(r"^\*\*(\d+(?:\.\d+)?) V ±10% → (\d+(?:\.\d+)?)–(\d+(?:\.\d+)?) V\*\* \[DR-2\]", cells[1])
        sv = (view.get("variant") or {}).get("supply_v") or {}
        if not m:
            problems.append(f"variant.supply_v: supply row in {SPEC_REL} is malformed")
        else:
            for k, g in (("typ", 1), ("min", 2), ("max", 3)):
                if sv.get(k) != Decimal(m.group(g)):
                    problems.append(
                        f"variant.supply_v.{k}: integrator.json has {sv.get(k)!r}, "
                        f"{SPEC_REL} section 1 has {m.group(g)}"
                    )
    cells, why = spec_row(lines, "| Load capacitance, CL |")
    load = view.get("load") or {}
    if why:
        problems.append(f"load.capacitance_pf: {why}")
    else:
        m = re.search(r"^\*\*(\d+(?:\.\d+)?) pF \[DR-1\]\*\*", cells[1])
        if not m:
            problems.append(f"load.capacitance_pf: CL row in {SPEC_REL} is malformed")
        elif load.get("capacitance_pf") != Decimal(m.group(1)):
            problems.append(
                f"load.capacitance_pf: integrator.json has {load.get('capacitance_pf')!r}, "
                f"{SPEC_REL} section 1 has {m.group(1)}"
            )
    swing, _ = spec_row(lines, "| Output swing |")
    if swing and "no resistive load" in swing[1] and "no resistive load" not in str(load.get("resistive", "")):
        problems.append(
            "load.resistive: output-swing row is stated with no resistive load; "
            "integrator.json no longer says so"
        )


def check_unratified(view: dict, lines: list[str], problems: list[str]) -> None:
    ratified = view.get("spec_rows_ratified") or {}
    pending = view.get("spec_rows_not_ratified")
    if not isinstance(pending, dict):
        problems.append("spec_rows_not_ratified: missing or not an object")
        pending = {}
    for key in NOT_RATIFIED:
        if key not in pending:
            problems.append(f"spec_rows_not_ratified.{key}: row dropped from integrator.json")
        if key in ratified:
            problems.append(f"spec_rows_ratified.{key}: unratified row promoted to a ratified number")
    for key in ratified:
        if key.startswith(("area", "icmr", "input_common_mode", "offset_mismatch", "offset_3sigma")):
            problems.append(f"spec_rows_ratified.{key}: unratified row promoted to a ratified number")
    if view.get("area_mm2") is not None:
        problems.append(f"area_mm2: integrator.json publishes {view.get('area_mm2')!r}; Area is TBD-12 (unratified), must be null")
    if "UNRATIFIED" not in str((pending.get("area") or {}).get("status", "")):
        problems.append("spec_rows_not_ratified.area.status: no longer states UNRATIFIED")
    cells, why = spec_row(lines, "| Area |")
    if why or not cells[1].startswith("**[TBD-12]**"):
        problems.append(f"{SPEC_REL} Area row is no longer the unratified [TBD-12] row; ratify via decision record, then update this checker")
    cells, why = spec_row(lines, "| Input common-mode range (ICMR) |")
    if why or not cells[-1].startswith("Measured (not yet ratified)"):
        problems.append(f"{SPEC_REL} ICMR row is no longer 'Measured (not yet ratified)'; update integrator.json and this checker together")
    cells, why = spec_row(lines, "| Input-referred offset |")
    if why or "Mismatch-driven random 3σ evidence now measured [P]" not in cells[1]:
        problems.append(f"{SPEC_REL} offset row no longer shows the 3-sigma half as measured [P]; update integrator.json and this checker together")


def check(root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    try:
        view = _dec((root / INTEGRATOR_REL).read_text(encoding="utf-8"))
        lines = (root / SPEC_REL).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        return [f"cannot read sources: {exc}"]
    check_ports(view, root, problems)
    check_ratified(view, lines, problems)
    check_conditions(view, lines, problems)
    check_unratified(view, lines, problems)
    return problems


def main(argv: list[str]) -> int:
    problems = check()
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"OK: {INTEGRATOR_REL} ports and ratified rows match {SYMBOL_REL} and {SPEC_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

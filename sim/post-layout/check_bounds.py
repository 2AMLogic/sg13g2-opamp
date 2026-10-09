#!/usr/bin/env python3
"""Grade a `klt pex` report's extracted-side values against the ratified
spec/target-spec.md Sec 2 bounds (read-only: this script never edits the spec).

  python3 sim/post-layout/check_bounds.py layout/opamp_core/pex_report.json

Bounds (all DR-2 worst-case, load CL = 2 pF [DR-1]):
  av0_db >= 37.8 dB     gbw_hz >= 4.74 MHz     pm_deg >= 60 deg
  iq_a   <= 119.7 uA (total Vdd current incl. the external 10 uA ibias)

Prints one line per row-kind (worst extracted value, its corner, verdict) and
exits 0 when every extracted value of every corner meets its bound AND the
report has exactly 45 corners x 4 rows with measurement.mode == "command";
exits 1 otherwise (a failing row is a finding -- do not cite item 7 `met`).
"""
import json
import sys

BOUNDS = {  # name: (kind, limit, unit-scale label)
    "av0_db": (">=", 37.8, "dB"),
    "gbw_hz": (">=", 4.74e6, "Hz"),
    "pm_deg": (">=", 60.0, "deg"),
    "iq_a": ("<=", 119.7e-6, "A"),
}


def grade(report):
    """Return (ok, lines)."""
    lines, ok = [], True
    if (report.get("measurement") or {}).get("mode") != "command":
        lines.append("FAIL measurement.mode is not 'command'")
        ok = False
    delta = report.get("delta") or []
    corners = {r["corner_id"] for r in delta}
    if len(delta) != 180 or len(corners) != 45:
        lines.append(f"FAIL expected 180 delta rows over 45 corners, got {len(delta)} over {len(corners)}")
        ok = False
    for name, (op, limit, unit) in BOUNDS.items():
        rows = [r for r in delta if r.get("spec_row") == name]
        vals = [(r.get("extracted_value"), r["corner_id"], r.get("status")) for r in rows]
        if not vals or any(v is None or s == "error" for v, _, s in vals):
            lines.append(f"FAIL {name}: missing/unresolved extracted values")
            ok = False
            continue
        worst = min(vals) if op == ">=" else max(vals)
        bad = [c for v, c, _ in vals if (v < limit if op == ">=" else v > limit)]
        verdict = "PASS" if not bad else f"FAIL ({len(bad)} of {len(vals)} corners)"
        if bad:
            ok = False
        lines.append(f"{verdict:<8} {name}: worst extracted {worst[0]:.6g} {unit} at {worst[1]} (bound {op} {limit:g})")
        for c in bad:
            lines.append(f"           violates: {c}")
    return ok, lines


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: check_bounds.py <pex_report.json>")
    ok, lines = grade(json.load(open(sys.argv[1])))
    print("\n".join(lines))
    sys.exit(0 if ok else 1)

#!/usr/bin/env python3
"""Mechanically reshape the offset-MC draws CSV into a `klt yield` sample-set.

Input : sim/input-offset/records/<id>-draws.csv   (long format, one row per draw)
Output: a `klt yield` sample-set document
        {"measurements": [{"name", "unit", "samples", "source_corners"}]}
        with ONE measurement per mismatch `point_id`, samples = that point's
        `vos_v` column in draw order. Draws whose `status` is not PASS are
        written as `null` (klt yield counts them as `errored`).

What this deliberately does NOT do:
  * it declares NO `limits` and NO `target_yield` -- spec/target-spec.md
    ratifies neither for the offset random half (only the systematic
    +21.9 mV, [DR-2]); supply them in a separate `--limits` file once a
    decision record binds them (see signoff/yield-inputs/README.md);
  * it drops the `negctrl` (zero-spread) point: that is a different
    population, not a draw from the mismatch distribution;
  * it never summarises, resamples or synthesises a value.

  python3 signoff/yield-inputs/offset_draws_to_sampleset.py            # write
  python3 signoff/yield-inputs/offset_draws_to_sampleset.py --check    # reproduces?
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRAWS = ROOT / "sim/input-offset/records/mc-20260921-174056-0a509fb-draws.csv"
OUT = ROOT / "signoff/yield-inputs/offset-mc-20260921-174056-0a509fb.sampleset.json"


def build(draws: Path) -> dict:
    by_point: dict[str, list] = {}
    with draws.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["mode"] != "mismatch":
                continue
            ok = row["status"] == "PASS" and row["vos_v"] != ""
            by_point.setdefault(row["point_id"], []).append(
                (int(row["draw_index"]), float(row["vos_v"]) if ok else None)
            )
    meas = []
    for pid in sorted(by_point):
        ordered = [v for _, v in sorted(by_point[pid], key=lambda t: t[0])]
        meas.append({"name": pid, "unit": "V", "samples": ordered,
                     "source_corners": [pid]})
    return {"measurements": meas}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--draws", type=Path, default=DRAWS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = json.dumps(build(a.draws), indent=1) + "\n"
    if a.check:
        if not a.out.exists() or a.out.read_text() != text:
            print(f"{a.out} does not reproduce from {a.draws}", file=sys.stderr)
            return 1
        print("reproduces")
        return 0
    a.out.write_text(text)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
  * it REFUSES (exit 1, row/point diagnostics) duplicate or missing draw
    indices, point metadata or seeds conflicting with the campaign summary
    CSV, unknown mode/status, and non-finite PASS values; expected points and
    draw counts come from that committed summary, not a new policy;
  * it never summarises, resamples or synthesises a value.

  python3 signoff/yield-inputs/offset_draws_to_sampleset.py            # write
  python3 signoff/yield-inputs/offset_draws_to_sampleset.py --check    # reproduces?
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRAWS = ROOT / "sim/input-offset/records/mc-20260921-174056-0a509fb-draws.csv"
SUMMARY = ROOT / "sim/input-offset/records/mc-20260921-174056-0a509fb.csv"
OUT = ROOT / "signoff/yield-inputs/offset-mc-20260921-174056-0a509fb.sampleset.json"


class DrawValidationError(Exception):
    """The draws CSV violates the campaign contract; carries all diagnostics."""

    def __init__(self, problems: list):
        self.problems = problems
        super().__init__("; ".join(problems))


KNOWN_MODES = ("mismatch", "negctrl")
KNOWN_STATUS = ("PASS", "FAIL")  # run_offset_mc.sh emits exactly these
DRAW_COLS = ("point_id", "mode", "mos_section", "temp_c", "vdd_v",
             "draw_index", "draw_seed", "status", "vos_v")
SUMMARY_COLS = ("point_id", "mode", "mos_section", "temp_c", "vdd_v",
                "seed_base", "n_draws", "n_pass")
# Point metadata that must agree between every draw row and the campaign
# summary (same strings the harness wrote; no numeric re-interpretation).
META = ("mode", "mos_section", "temp_c", "vdd_v")


def _read(path: Path, cols: tuple) -> list:
    with path.open(newline="") as f:
        rd = csv.DictReader(f)
        missing = [c for c in cols if c not in (rd.fieldnames or [])]
        if missing:
            raise DrawValidationError([f"{path.name}: missing column(s) {missing}"])
        return list(rd)


def _int(text, what: str, where: str, problems: list):
    try:
        return int(text)
    except (TypeError, ValueError):
        problems.append(f"{where}: {what} {text!r} is not an integer")
        return None


def load_expected(summary: Path) -> dict:
    """Expected points from the committed campaign summary CSV."""
    exp, problems = {}, []
    for n, row in enumerate(_read(summary, SUMMARY_COLS), start=2):
        where = f"{summary.name} line {n} point {row['point_id']!r}"
        if row["point_id"] in exp:
            problems.append(f"{where}: duplicate summary point")
            continue
        if row["mode"] not in KNOWN_MODES:
            problems.append(f"{where}: unknown mode {row['mode']!r}")
        nd = _int(row["n_draws"], "n_draws", where, problems)
        sb = _int(row["seed_base"], "seed_base", where, problems)
        if nd is not None and nd <= 0:
            problems.append(f"{where}: n_draws {nd} is not positive")
        exp[row["point_id"]] = {"meta": {k: row[k] for k in META},
                                "n_draws": nd, "seed_base": sb,
                                "n_pass": _int(row["n_pass"], "n_pass", where, problems)}
    if problems:
        raise DrawValidationError(problems)
    if not exp:
        raise DrawValidationError([f"{summary.name}: no points"])
    return exp


def validate(rows: list, expected: dict, name: str = "draws") -> dict:
    """Return {point_id: {draw_index: value-or-None}} or raise.

    Every problem found is reported with its CSV line (header = line 1) and
    point_id. Failed draws (status FAIL) become None; PASS needs a finite
    vos_v.
    """
    problems, got = [], {}
    for n, row in enumerate(rows, start=2):
        pid = row["point_id"]
        where = f"{name} line {n} point {pid!r}"
        if row["mode"] not in KNOWN_MODES:
            problems.append(f"{where}: unknown mode {row['mode']!r}")
            continue
        if row["status"] not in KNOWN_STATUS:
            problems.append(f"{where}: unknown status {row['status']!r}")
            continue
        exp = expected.get(pid)
        if exp is None:
            problems.append(f"{where}: point not in campaign summary")
            continue
        for k in META:
            if row[k] != exp["meta"][k]:
                problems.append(f"{where}: {k} {row[k]!r} conflicts with "
                                f"campaign metadata {exp['meta'][k]!r}")
        idx = _int(row["draw_index"], "draw_index", where, problems)
        seed = _int(row["draw_seed"], "draw_seed", where, problems)
        if idx is None:
            continue
        if not 0 <= idx < exp["n_draws"]:
            problems.append(f"{where}: draw_index {idx} outside "
                            f"0..{exp['n_draws'] - 1}")
            continue
        if seed is not None and seed != exp["seed_base"] + idx:
            problems.append(f"{where}: draw {idx} draw_seed {seed} != "
                            f"seed_base+index {exp['seed_base'] + idx}")
        val = None
        if row["status"] == "PASS":
            try:
                val = float(row["vos_v"])
            except ValueError:
                problems.append(f"{where}: draw {idx} PASS vos_v "
                                f"{row['vos_v']!r} is not a number")
            else:
                if not math.isfinite(val):
                    problems.append(f"{where}: draw {idx} PASS vos_v "
                                    f"{row['vos_v']!r} is not finite")
                    val = None
        seen = got.setdefault(pid, {})
        if idx in seen:
            problems.append(f"{where}: duplicate draw_index {idx}")
            continue
        seen[idx] = val
    for pid, exp in expected.items():
        have = got.get(pid, {})
        missing = [i for i in range(exp["n_draws"]) if i not in have]
        if missing:
            shown = ", ".join(map(str, missing[:10])) + (" ..." if len(missing) > 10 else "")
            problems.append(f"{name} point {pid!r}: {len(missing)} of "
                            f"{exp['n_draws']} expected draws missing ({shown})")
        elif exp["n_pass"] is not None:
            npass = sum(v is not None for v in have.values())
            # failed draws are legal; a PASS count that disagrees with the
            # campaign summary means the CSV is not the summarised campaign.
            if npass != exp["n_pass"]:
                problems.append(f"{name} point {pid!r}: {npass} PASS draws "
                                f"but campaign summary n_pass={exp['n_pass']}")
    if problems:
        raise DrawValidationError(problems)
    return got


def build(draws: Path, summary: Path = SUMMARY) -> dict:
    expected = load_expected(summary)
    got = validate(_read(draws, DRAW_COLS), expected, draws.name)
    meas = []
    for pid in sorted(got):
        if expected[pid]["meta"]["mode"] != "mismatch":
            continue  # negctrl: different population, intentionally excluded
        by_idx = got[pid]
        meas.append({"name": pid, "unit": "V",
                     "samples": [by_idx[i] for i in sorted(by_idx)],
                     "source_corners": [pid]})
    return {"measurements": meas}


def render(doc: dict) -> str:
    # allow_nan=False: a non-finite value can never become a NaN/Infinity token.
    return json.dumps(doc, indent=1, allow_nan=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--draws", type=Path, default=DRAWS)
    ap.add_argument("--summary", type=Path, default=SUMMARY,
                    help="campaign summary CSV: expected points and draw counts")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    try:
        text = render(build(a.draws, a.summary))
    except DrawValidationError as e:
        print(f"invalid draws: {len(e.problems)} problem(s)", file=sys.stderr)
        for p in e.problems:
            print(f"  {p}", file=sys.stderr)
        return 1
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

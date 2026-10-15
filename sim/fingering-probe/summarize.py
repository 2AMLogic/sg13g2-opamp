#!/usr/bin/env python3
"""Join the five probe measurement documents into one record (issue #237).

  summarize.py <record-id> <points> <corners-dir> <out.json> <out.md>

<corners-dir>/<variant>/measurement.json is the `klt pex --measure-command`
document sim/post-layout/measure_openloop_ac.sh printed for that variant;
<corners-dir>/<variant>/{ac,op}.envelope.json are the two `klt sim` envelopes
behind it (their environment.remote names the batch job).

Steps reported (each a percent change, (b - a) / |a| * 100, the same
definition `klt pex` uses for its delta[] rows):

  representation   drawn            vs lumped           lumped -> drawn fingering
  expansion        expanded         vs drawn            ng/m form -> per-finger cards + dummies
  diffusion        extracted_nopar  vs expanded         model AS/AD -> extracted AS/AD
  parasitics       extracted        vs extracted_nopar  the R/C the extraction adds
  pex_236          extracted        vs lumped           what the #236 pex_report compared
  pex_drawn        extracted        vs drawn            what a reconciled pex would compare

Loud: a missing variant, corner or measurement exits 1 and writes nothing.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

VARIANTS = ("lumped", "drawn", "expanded", "extracted_nopar", "extracted")
ROWS = ("av0_db", "gbw_hz", "pm_deg", "iq_a")
STEPS = (
    ("representation", "lumped", "drawn"),
    ("expansion", "drawn", "expanded"),
    ("diffusion", "expanded", "extracted_nopar"),
    ("parasitics", "extracted_nopar", "extracted"),
    ("pex_236", "lumped", "extracted"),
    ("pex_drawn", "drawn", "extracted"),
)


def pct(a: float, b: float) -> float:
    return (b - a) / abs(a) * 100.0


def load(corners: Path) -> tuple[dict, dict]:
    values: dict[str, dict[str, dict[str, float]]] = {}
    jobs: dict[str, dict[str, str]] = {}
    for v in VARIANTS:
        doc = json.loads((corners / v / "measurement.json").read_text())
        values[v] = {
            c["corner_id"]: {m["name"]: float(m["value"]) for m in c["measurements"]}
            for c in doc["corners"]
        }
        jobs[v] = {}
        for kind in ("ac", "op"):
            env = json.loads((corners / v / f"{kind}.envelope.json").read_text())
            remote = env.get("environment", {}).get("remote") or {}
            jobs[v][kind] = remote.get("job_id") or "none (not a batch run)"
    ids = {frozenset(x) for x in values.values()}
    if len(ids) != 1:
        sys.exit("summarize: variants cover different corners")
    for v, per in values.items():
        for cid, rows in per.items():
            for r in ROWS:
                if r not in rows or not math.isfinite(rows[r]):
                    sys.exit(f"summarize: {v} {cid}: no finite {r}")
    return values, jobs


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        sys.exit(__doc__)
    record_id, points, corners, out_json, out_md = argv[1:]
    values, jobs = load(Path(corners))
    corner_ids = sorted(next(iter(values.values())))
    steps = {
        name: {
            cid: {r: round(pct(values[a][cid][r], values[b][cid][r]), 3) for r in ROWS}
            for cid in corner_ids
        }
        for name, a, b in STEPS
    }
    span = {
        name: {
            r: [min(steps[name][c][r] for c in corner_ids), max(steps[name][c][r] for c in corner_ids)]
            for r in ROWS
        }
        for name, _a, _b in STEPS
    }
    doc = {
        "record_id": record_id,
        "issue": 237,
        "bench": "sim/post-layout/measure_openloop_ac.sh (open-loop AC + OP, CL = 2 pF [DR-1], ibias = 10 uA external)",
        "points": points,
        "corner_ids": corner_ids,
        "variants": list(VARIANTS),
        "batch_jobs": jobs,
        "values": values,
        "steps": {name: {"from": a, "to": b} for name, a, b in STEPS},
        "delta_pct": steps,
        "delta_pct_span": span,
    }
    Path(out_json).write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")

    md = [
        f"# Device-representation probe {record_id} (issue #237)",
        "",
        "Bench: the committed post-layout open-loop AC bench "
        "(`sim/post-layout/measure_openloop_ac.sh`), CL = 2 pF [DR-1], "
        "10 uA external ibias, Iq = total Vdd current including ibias.",
        f"Grid: `{points}` ({len(corner_ids)} corners), run through `klt sim` "
        "on the batch fleet (job ids below).",
        "Variants: see `../README.md`. Netlists: "
        f"`../netlist-snapshots/{record_id}/`; envelopes: `../corners/{record_id}/`.",
        "",
        "## Values",
        "",
        "| corner | variant | Av0 (dB) | GBW (MHz) | PM (deg) | Iq (uA) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for cid in corner_ids:
        for v in VARIANTS:
            x = values[v][cid]
            md.append(
                f"| {cid} | {v} | {x['av0_db']:.3f} | {x['gbw_hz'] / 1e6:.4f} | "
                f"{x['pm_deg']:.3f} | {x['iq_a'] * 1e6:.3f} |"
            )
    md += [
        "",
        "## Step deltas (percent, min..max over the corners)",
        "",
        "| step | from -> to | Av0 | GBW | PM | Iq |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name, a, b in STEPS:
        cells = [f"{span[name][r][0]:+.2f}..{span[name][r][1]:+.2f}" for r in ROWS]
        md.append(f"| {name} | {a} -> {b} | " + " | ".join(cells) + " |")
    md += ["", "## Batch jobs", "", "| variant | AC job | OP job |", "|---|---|---|"]
    for v in VARIANTS:
        md.append(f"| {v} | {jobs[v]['ac']} | {jobs[v]['op']} |")
    Path(out_md).write_text("\n".join(md) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

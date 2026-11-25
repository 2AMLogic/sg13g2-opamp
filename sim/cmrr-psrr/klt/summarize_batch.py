#!/usr/bin/env python3
"""Produce the batch CMRR/PSRR per-point record from the two `klt sim` envelopes (#514).

  summarize_batch.py <cmrr.sim.json> <direct.sim.json> <out.csv> <out.md>

Reads the committed same-DUT envelopes (`cmrr_direct.request.json`,
`psrr_direct.request.json`; 45 corners each) and writes the record that
`signoff/characterization/selection.json` selects for `cmrr-psrr`:

  * av0_db, acm0_db, cmrr_db (= Av0 - Acm0, dB), cmrr_plateau_delta_db  <- CMRR deck
  * avs0_db, psrr_db (= Av0 - Avs0, dB), psrr_plateau_delta_db           <- PSRR deck

The CSV carries only what the envelopes measured. It has no operating-point
columns and no 1 kHz columns: neither deck measures them (see the .md).
Stdlib only; loud (exit 1, nothing written) on a missing or malformed input.
The characterization generator re-derives every cell from the envelopes
(definition check `cmrr_psrr_klt_audit`), so this script is a convenience, not
a trust anchor.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from pathlib import Path

COLUMNS = (
    "point_id", "corner", "temp_c", "vdd_v", "vcm_v",
    "av0_db", "acm0_db", "cmrr_db", "cmrr_plateau_delta_db",
    "avs0_db", "psrr_db", "psrr_plateau_delta_db",
)
CMRR_NAMES = ("av0_db", "acm0_db", "cmrr_db", "cmrr_plateau_delta_db")
PSRR_NAMES = ("av0_db", "avs0_db", "psrr_db", "psrr_plateau_delta_db")
CMRR_BOUND_DB = 30.75
PSRR_BOUND_DB = 1.87
PLATEAU_MAX_DB = 0.05


class InputError(Exception):
    pass


def _jobs(env: dict) -> list[str]:
    remote = (env.get("environment") or {}).get("remote") or {}
    ids = [remote["job_id"]] if remote.get("job_id") else []
    ids += [f["job_id"] for f in remote.get("fleet") or [] if f.get("job_id")]
    return sorted(set(ids))


def load(path: Path, names: tuple, label: str) -> tuple[dict, dict]:
    try:
        env = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"{label}: cannot read {path} ({exc})") from exc
    if not isinstance(env, dict) or not isinstance(env.get("corners"), list):
        raise InputError(f"{label}: {path} is not a klt sim envelope")
    if not _jobs(env):
        raise InputError(f"{label}: no environment.remote batch job (not batch evidence)")
    out = {}
    for corner in env["corners"]:
        try:
            pid = f"{corner['process']}_{int(corner['temperature_c'])}C_{float(corner['supply_v']['vdd']):.2f}V"
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError(f"{label}: a corner has no process/temperature/vdd identity") from exc
        if pid in out:
            raise InputError(f"{label}: duplicate corner {pid}")
        if corner.get("status") not in ("pass", "fail"):
            raise InputError(f"{label}: corner {pid} has status {corner.get('status')!r}")
        got = {m.get("name"): m.get("value") for m in corner.get("measurements") or []}
        bad = [n for n in names if not isinstance(got.get(n), (int, float)) or not math.isfinite(got[n])]
        if bad:
            raise InputError(f"{label}: corner {pid} lacks finite {bad}")
        out[pid] = {"vals": {n: float(got[n]) for n in names}, "vdd": float(corner["supply_v"]["vdd"]),
                    "vinp": float(corner["supply_v"]["vinp"]), "temp": int(corner["temperature_c"]),
                    "corner": corner["process"]}
    return env, out


def g(x: float) -> str:
    return format(x, ".9g")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        cenv, cm = load(Path(argv[1]), CMRR_NAMES, "CMRR envelope")
        penv, ps = load(Path(argv[2]), PSRR_NAMES, "PSRR envelope")
        if sorted(cm) != sorted(ps):
            raise InputError("the two envelopes do not cover the same corners")
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    version = {(e.get("environment") or {}).get("engine_version") for e in (cenv, penv)}
    banner = re.findall(r"ngspice-\d+", (cenv["environment"].get("engine_build") or {}).get("version_banner", ""))
    if len(version) != 1 or not banner:
        print("error: envelopes disagree on (or do not state) the simulator version", file=sys.stderr)
        return 1
    ngspice = f"ngspice-{next(iter(version))}"
    rows = []
    for pid in sorted(cm):
        c, p = cm[pid], ps[pid]
        rows.append({
            "point_id": pid, "corner": c["corner"], "temp_c": c["temp"], "vdd_v": f"{c['vdd']:.2f}",
            "vcm_v": g(c["vinp"]),
            **{n: g(c["vals"][n]) for n in CMRR_NAMES},
            "avs0_db": g(p["vals"]["avs0_db"]), "psrr_db": g(p["vals"]["psrr_db"]),
            "psrr_plateau_delta_db": g(p["vals"]["psrr_plateau_delta_db"]),
        })
    rows.sort(key=lambda r: r["point_id"])
    with open(argv[3], "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    def worst(name: str):
        r = min(rows, key=lambda r: float(r[name]))
        return float(r[name]), r["point_id"], max(float(x[name]) for x in rows)

    cw, cp, cb = worst("cmrr_db")
    pw, pp, pb = worst("psrr_db")
    plat = max(max(float(r["cmrr_plateau_delta_db"]), float(r["psrr_plateau_delta_db"])) for r in rows)
    md = f"""# cmrr-psrr batch record (`klt sim`, inn AC-grounded)

Produced by `sim/cmrr-psrr/klt/summarize_batch.py` (issue #514) from the same-DUT
envelopes `{Path(argv[1]).name}` (jobs {', '.join('`' + j + '`' for j in _jobs(cenv))}) and
`{Path(argv[2]).name}` (jobs {', '.join('`' + j + '`' for j in _jobs(penv))}),
45 corners each, {ngspice}, into CL = 2 pF [DR-1]. DUT: `design/netlist/opamp_core.spice`
(snapshot `sim/cmrr-psrr/netlist-snapshots/20260921-151815-707b34c/opamp_core.spice`, same sha256).

CMRR = Av0 - Acm0 and PSRR+ = Av0 - Avs0 are each ONE in-deck measurement (two DUT
copies per deck), in dB, read at the 10 mHz DC shelf. Av0 here is the AC-grounded-`inn`
gain of the same deck, not a join.

| row | bound | worst | at corner | best |
|---|---|---|---|---|
| CMRR systematic (context, superseded by DR-4) | >= {CMRR_BOUND_DB} dB | {cw:.4g} dB | {cp} | {cb:.4g} dB |
| PSRR+ (DC shelf) | >= {PSRR_BOUND_DB} dB | {pw:.4g} dB | {pp} | {pb:.4g} dB |
| plateau guard (0.1 Hz vs 10 mHz), both decks | <= {PLATEAU_MAX_DB} dB | {plat:.3g} dB | | |

## Decisions (issue #514)

- **Regression control.** `sim/cmrr-psrr/records/20260921-151815-707b34c.csv` stays selected as
  `cmrr-psrr-harness`. The audit compares Acm0 only, point by point. Its Av0, CMRR and PSRR
  are the superseded floating-`inn` figures and are never compared.
- **PSRR 1 kHz context figure: dropped from the row.** No batch deck reads 1 kHz, and the only
  1 kHz figure on file is the floating-`inn` harness one, which differs from the DC figures
  here by the ~4 dB supply zero that the AC-grounded construction removes. Showing it
  beside this record's DC figure would mix constructions, so the row carries no 1 kHz context.
- **Operating-point consistency (`op_pass`): not re-measured.** Neither deck prints an
  operating point, so this record has no `op_pass` column and no operating-point validity
  condition. The harness record's `op_pass` (45 of 45) is evidence about the superseded
  construction only. Same DUT hash and the open-loop record's operating-point audit
  (`open_loop_klt_audit`) cover the shared bias network.
"""
    Path(argv[4]).write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

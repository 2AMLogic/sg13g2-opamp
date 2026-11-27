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
from decimal import Decimal
import io
import sys
from pathlib import Path

from compare_cmrr_direct import (
    CMRR_SYSTEMATIC_BOUND_DB, DEFAULT_CMRR_BODY, DEFAULT_PSRR_BODY, DUT,
    MEASUREMENTS as CMRR_NAMES, PLATEAU_MAX_DB, PSRR_MEASUREMENTS as PSRR_NAMES,
    check_body_hash, check_conditions, check_stimulus, gain_problems, index_envelope, output_load_f,
)
from klt_envelope import (
    InputError, batch_job_ids, check_decided_counts, exact_pvt_key, expected_keys,
    key_str, read_envelope, sha256_file,
)

COLUMNS = (
    "point_id", "corner", "temp_c", "vdd_v", "vcm_v",
    "av0_db", "acm0_db", "cmrr_db", "cmrr_plateau_delta_db",
    "avs0_db", "psrr_db", "psrr_plateau_delta_db",
)
PSRR_BOUND_DB = 1.87
SNAPSHOT = Path("sim/cmrr-psrr/netlist-snapshots/20260921-151815-707b34c/opamp_core.spice")


def load(path: Path, names: tuple, label: str) -> tuple[dict, dict]:
    env = read_envelope(path)
    if not isinstance(env, dict) or not isinstance(env.get("corners"), list):
        raise InputError(f"{label}: {path} is not a klt sim envelope")
    if not batch_job_ids(env):
        raise InputError(f"{label}: no environment.remote batch job")
    check_decided_counts(env, len(expected_keys()))
    for corner in env["corners"]:
        key = exact_pvt_key(corner)
        if corner.get("diagnostics"):
            raise InputError(f"{label}: {key_str(key)} has diagnostics")
        measurements = corner.get("measurements")
        if not isinstance(measurements, list) or any(
                not isinstance(m, dict) or m.get("unit") != "dB" or m.get("status") not in ("pass", "fail")
                for m in measurements):
            raise InputError(f"{label}: {key_str(key)} requires decided measurements in dB")
    # The comparator checks counts, coverage, and exactly one finite set of
    # measurements at every required point. Keys have already passed exact_pvt_key.
    return env, index_envelope(env, label, names)


def g(x: float) -> str:
    return format(x, ".9g")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        cenv, cm = load(Path(argv[1]), CMRR_NAMES, "CMRR envelope")
        penv, ps = load(Path(argv[2]), PSRR_NAMES, "PSRR envelope")
        conditions = check_conditions(cenv, penv, require_build_banner=True)
        cmrr_body = check_body_hash(cenv, DEFAULT_CMRR_BODY, "CMRR")
        psrr_body = check_body_hash(penv, DEFAULT_PSRR_BODY, "PSRR")
        check_stimulus(cmrr_body, psrr_body)
        for label, body in (("CMRR", cmrr_body), ("PSRR", psrr_body)):
            if output_load_f(body) != Decimal("2e-12"):
                raise InputError(f"{label} bench body: expected a 2 pF load from each output to vss")
        for key in cm:
            problems = gain_problems(cm[key], ps[key])
            if problems:
                raise InputError(f"{key_str(key)}: " + "; ".join(problems))
        ngspice = f"ngspice-{conditions['engine_version']}"
        snapshot_hash = sha256_file(Path(__file__).resolve().parents[3] / SNAPSHOT)
        if conditions["dut_netlist_sha256"] != snapshot_hash:
            raise InputError(f"DUT hash {conditions['dut_netlist_sha256']} differs from snapshot {SNAPSHOT} ({snapshot_hash})")
    except (InputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rows = []
    for key in sorted(cm, key=key_str):
        process, temp, vdd = key
        c, p = cm[key], ps[key]
        rows.append({
            "point_id": key_str(key), "corner": process, "temp_c": temp, "vdd_v": f"{vdd:.2f}",
            "vcm_v": g(vdd / 2),
            **{n: g(c[n]) for n in CMRR_NAMES},
            "avs0_db": g(p["avs0_db"]), "psrr_db": g(p["psrr_db"]),
            "psrr_plateau_delta_db": g(p["psrr_plateau_delta_db"]),
        })
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(csv_text, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)

    def worst(name: str):
        r = min(rows, key=lambda r: float(r[name]))
        return float(r[name]), r["point_id"], max(float(x[name]) for x in rows)

    cw, cp, cb = worst("cmrr_db")
    pw, pp, pb = worst("psrr_db")
    plat = max(max(float(r["cmrr_plateau_delta_db"]), float(r["psrr_plateau_delta_db"])) for r in rows)
    md = f"""# cmrr-psrr batch record (`klt sim`, inn AC-grounded)

Produced by `sim/cmrr-psrr/klt/summarize_batch.py` (issue #514) from the same-DUT
envelopes `{Path(argv[1]).name}` (jobs {', '.join('`' + j + '`' for j in batch_job_ids(cenv))}) and
`{Path(argv[2]).name}` (jobs {', '.join('`' + j + '`' for j in batch_job_ids(penv))}),
45 corners each, {ngspice}, into CL = 2 pF [DR-1]. DUT: `{DUT}`
(snapshot `{SNAPSHOT.as_posix()}`, same sha256).

CMRR = Av0 - Acm0 and PSRR+ = Av0 - Avs0 are each ONE in-deck measurement (two DUT
copies per deck), in dB, read at the 10 mHz DC shelf. Av0 here is the AC-grounded-`inn`
gain of the same deck, not a join.

| row | bound | worst | at corner | best |
|---|---|---|---|---|
| CMRR systematic (context, superseded by DR-4) | >= {CMRR_SYSTEMATIC_BOUND_DB} dB | {cw:.4g} dB | {cp} | {cb:.4g} dB |
| PSRR+ (DC shelf) | >= {PSRR_BOUND_DB} dB | {pw:.4g} dB | {pp} | {pb:.4g} dB |
| plateau guard (0.1 Hz vs 10 mHz), both decks | <= {PLATEAU_MAX_DB} dB | {plat:.3g} dB | | |

## Decisions (issue #514)

- **Regression control.** `sim/cmrr-psrr/records/20260921-151815-707b34c.csv` stays selected as
  `cmrr-psrr-harness`. The audit compares Acm0 only, point by point. Its Av0, CMRR and PSRR
  are the superseded floating-`inn` figures and are never compared.
- **PSRR at 1 kHz.** The selected November direct deck measures the DC shelf and its
  plateau guard. The October AC-grounded batch record `20261015-103521-0f41068`
  measured supply gain at 1 kHz and joined Av0 from a separate open-loop run,
  giving 26.90–36.33 dB across 45 corners. The selected row uses only the November
  in-deck measurements and therefore carries no 1 kHz figure.
- **Operating-point consistency (`op_pass`): not re-measured.** Neither deck prints an
  operating point, so this record has no `op_pass` column and no operating-point validity
  condition. The harness record's `op_pass` (45 of 45) is evidence about the superseded
  construction only. Same DUT hash and the open-loop record's operating-point audit
  (`open_loop_klt_audit`) cover the shared bias network.
"""
    created = []
    try:
        for path, content in ((Path(argv[3]), csv_text.getvalue()), (Path(argv[4]), md)):
            with path.open("x", newline="", encoding="utf-8") as output:
                created.append(path)
                output.write(content)
    except OSError as exc:
        for path in created:
            path.unlink()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

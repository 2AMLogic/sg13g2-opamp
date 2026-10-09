#!/usr/bin/env python3
"""Turn measure_openloop_ac.sh's per-point ngspice output into the
`klt pex --measure-command` measurement document (stdout).

Input: a TSV of  point_id corner temp_c vdd_v ac_csv log  rows.
Metric definitions match sim/open-loop-ac/run_pvt_sweep.sh: Av0 is the 1 Hz
plateau, GBW the log-interpolated 0 dB crossing, PM = 180 + phase there, Iq the
total Vdd current at the DC operating point.

Exit 1 (no document) on any missing OP_* line or non-regulating DC point
(|Vout - Vcm| > 0.15*VDD or Vout within 2% of a rail): an unmeasured point must
not read as a measurement.
"""
import json
import math
import sys


def fmt_vdd(v):
    return f"{float(v):.2f}"


def read_log(path):
    ops = {}
    with open(path) as f:
        for line in f:
            if line.startswith("OP_"):
                k, _, v = line.partition(" ")
                ops[k.strip()] = float(v.split()[0])
    return ops


def ac_metrics(path):
    freqs, dbs, phs = [], [], []
    with open(path) as f:
        for line in f:
            p = line.split()
            if len(p) < 4:
                continue
            freqs.append(float(p[0])); dbs.append(float(p[1])); phs.append(float(p[3]))
    if not freqs:
        raise ValueError(f"{path}: no AC rows")
    av0 = dbs[0]
    gbw = pm = None
    for i in range(1, len(dbs)):
        if dbs[i - 1] >= 0.0 > dbs[i]:
            lf0, lf1 = math.log10(freqs[i - 1]), math.log10(freqs[i])
            frac = dbs[i - 1] / (dbs[i - 1] - dbs[i])
            gbw = 10 ** (lf0 + frac * (lf1 - lf0))
            pm = 180.0 + phs[i - 1] + frac * (phs[i] - phs[i - 1])
            break
    return av0, gbw, pm


def main(tsv):
    corners = []
    for raw in open(tsv):
        point_id, _corner, temp, vdd, ac_csv, log = raw.rstrip("\n").split("\t")
        vdd_f = float(vdd)
        ops = read_log(log)
        for k in ("OP_VOUT", "OP_IVDD"):
            if k not in ops:
                sys.exit(f"ac_metrics: {point_id}: missing {k} in {log}")
        vcm = vdd_f / 2
        vout = ops["OP_VOUT"]
        if abs(vout - vcm) > 0.15 * vdd_f or not (0.02 * vdd_f <= vout <= 0.98 * vdd_f):
            sys.exit(f"ac_metrics: {point_id}: non-regulating DC point (vout={vout:.4g} V, vcm={vcm:.4g} V)")
        av0, gbw, pm = ac_metrics(ac_csv)
        corners.append({
            "corner_id": f"{_corner}/{fmt_vdd(vdd_f)}V/{temp}C",
            "measurements": [
                {"name": "av0_db", "value": av0},
                {"name": "gbw_hz", "value": gbw},
                {"name": "pm_deg", "value": pm},
                {"name": "iq_a", "value": ops["OP_IVDD"]},
            ],
        })
    if not corners:
        sys.exit("ac_metrics: no points")
    json.dump({"corners": corners}, sys.stdout, indent=1, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: ac_metrics.py <points.tsv>")
    main(sys.argv[1])

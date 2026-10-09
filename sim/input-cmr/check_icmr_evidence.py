#!/usr/bin/env python3
"""Offline ICMR evidence checker (stdlib only; no ngspice, no PDK).

Reproduces the figures cited by spec/decision-records/0006 from the committed
record CSV.  Read-only: never writes under sim/.

  python3 sim/input-cmr/check_icmr_evidence.py [csv] [--candidate LO HI]

--candidate LO HI checks that [LO, HI] V lies inside the input-stage interval
at EVERY point (LO >= icmr_lo_v and HI <= icmr_hi_v everywhere).
"""
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "records", "20260921-174405-65f5fb4.csv")
NUMERIC = ("vdd_v", "vcm_v", "icmr_lo_v", "icmr_hi_v", "buffer_use_lo_v",
           "buffer_use_hi_v", "buffer_use_span_v", "icmr_span_v")


class EvidenceError(ValueError):
    pass


def load(path=DEFAULT_CSV):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    ids = set()
    for n, r in enumerate(rows, 2):
        pid = r.get("point_id") or ""
        if not pid or pid in ids:
            raise EvidenceError("line %d: missing or duplicate point_id %r" % (n, pid))
        ids.add(pid)
        for k in NUMERIC:
            try:
                v = float(r[k])
            except (KeyError, TypeError, ValueError):
                raise EvidenceError("%s: missing/non-numeric %s" % (pid, k))
            if not math.isfinite(v):
                raise EvidenceError("%s: non-finite %s" % (pid, k))
            r[k] = v
        if r.get("op_pass") != "1":
            raise EvidenceError("%s: op_pass != 1" % pid)
        if r["icmr_lo_v"] > r["icmr_hi_v"]:
            raise EvidenceError("%s: icmr_lo_v > icmr_hi_v" % pid)
        if r.get("contains_vcm") not in ("0", "1"):
            raise EvidenceError("%s: bad contains_vcm" % pid)
    return rows


def summarize(rows):
    lo = max(rows, key=lambda r: r["icmr_lo_v"])
    hi = min(rows, key=lambda r: r["icmr_hi_v"])
    span = min(rows, key=lambda r: r["icmr_span_v"])
    gap = max(rows, key=lambda r: r["icmr_lo_v"] - r["vcm_v"])
    return {
        "n": len(rows),
        "n_excl_midrail": sum(r["contains_vcm"] == "0" for r in rows),
        "lo": lo["icmr_lo_v"], "lo_id": lo["point_id"],
        "hi": hi["icmr_hi_v"], "hi_id": hi["point_id"],
        "worst_span_id": span["point_id"],
        "worst_span": (span["icmr_lo_v"], span["icmr_hi_v"], span["icmr_span_v"]),
        "max_gap": gap["icmr_lo_v"] - gap["vcm_v"], "max_gap_id": gap["point_id"],
        "buf_lo": max(r["buffer_use_lo_v"] for r in rows),
        "buf_hi": min(r["buffer_use_hi_v"] for r in rows),
        "buf_worst_span": min(r["buffer_use_span_v"] for r in rows),
    }


def check_candidate(rows, lo, hi, key="icmr"):
    """Return point_ids where [lo, hi] is NOT covered (empty list = covered)."""
    a, b = ("icmr_lo_v", "icmr_hi_v") if key == "icmr" else \
           ("buffer_use_lo_v", "buffer_use_hi_v")
    return [r["point_id"] for r in rows if lo < r[a] or hi > r[b]]


def outward_safe(lo, hi, digits=3):
    """Guaranteed interval: lower rounded up, upper rounded down."""
    f = 10 ** digits
    return math.ceil(lo * f - 1e-9) / f, math.floor(hi * f + 1e-9) / f


def main(argv):
    args = argv[1:]
    cand = None
    if "--candidate" in args:
        i = args.index("--candidate")
        cand = (float(args[i + 1]), float(args[i + 2]))
        del args[i:i + 3]
    rows = load(args[0] if args else DEFAULT_CSV)
    s = summarize(rows)
    for k, v in s.items():
        print("%s: %s" % (k, v))
    print("outward_safe_mV:", outward_safe(s["lo"], s["hi"]))
    print("outward_safe_buffer_mV:", outward_safe(s["buf_lo"], s["buf_hi"]))
    if cand:
        bad = check_candidate(rows, *cand)
        print("candidate", cand, "uncovered:", bad or "none")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

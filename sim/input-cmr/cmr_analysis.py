#!/usr/bin/env python3
"""Raw-curve analysis for run_cmr_sweep.sh (bench-local, stdlib only).

One sample reader and one fine upper-bound crossing, shared by the
runner's bound locators so the measurement and its verification cannot
drift apart. Each subcommand prints exactly the whitespace-separated line
the runner `read -r`s; the coarse/fine algorithms deliberately differ
(predicates, scan directions, neighbour sample, sentinels, formatting) and
are kept as they were, not unified.

  cmr_analysis.py coarse-bounds   <coarse.csv> <vdsat5> <vth1>
  cmr_analysis.py fp-relocate     <coarse.csv> <vth1>
  cmr_analysis.py fine-lo         <finelo.csv> <vdsat5>
  cmr_analysis.py fine-hi         <finehi.csv> <vth1>
  cmr_analysis.py fine-hi-verify  <finehi.csv> <vth1> <recorded_bound> <fine_step>

Raw curve layout (ngspice wrdata, whitespace-delimited, x/y pairs): rows
with fewer than 12 fields are skipped; column 0 is Vcm, 3 v(tail), 5 v(d1),
7 v(d2), 9 v(ibias), 11 the Vdd current.
"""
import sys

COL_VCM, COL_VTAIL, COL_VD1, COL_VD2, COL_IVDD = 0, 3, 5, 7, 11


def read_samples(path, *cols):
    """One list per requested column, over the rows with >= 12 fields.

    Only the requested columns are parsed (as each original reader did).
    """
    out = [[] for _ in cols]
    with open(path) as fh:
        for line in fh:
            p = line.split()
            if len(p) < 12:
                continue
            for lst, c in zip(out, cols):
                lst.append(float(p[c]))
    return out


def fine_hi_crossing(vcm_v, vd1_v, vth1):
    """Fine upper bound: (bound, s) or (None, None).

    y = vd1 - vcm falls through -vth1 as vcm rises; scan ascending (from
    the in-range/lo side) so a degenerate re-entry cannot widen the bound.
    s is the in-range-adjacent sample (the pair's lower-Vcm side).
    """
    for i in range(0, len(vcm_v) - 1):
        a = vd1_v[i] - vcm_v[i] + vth1
        b = vd1_v[i + 1] - vcm_v[i + 1] + vth1
        if (a >= 0 > b):
            frac = a / (a - b)
            return vcm_v[i] + frac * (vcm_v[i + 1] - vcm_v[i]), i
    return None, None


def coarse_bounds(argv):
    # Locate both bounds on the coarse curve (centre-bias first pass) and
    # read the tail bias at the provisional hi bound (fixed-point seed).
    path, level5, vth1 = argv[0], float(argv[1]), float(argv[2])
    if argv[1] == "nan" or argv[2] == "nan":
        return "nan nan nan 0 0"
    vcm_v, vtail_v, vds1_v = read_samples(path, COL_VCM, COL_VTAIL, COL_VD1)

    def crossing(xs, ys, level, side):
        # interpolated x where ys crosses `level`, scanning outward from the
        # window centre; `side` is -1 (toward lo) or +1 (toward hi). The
        # scan stops at its first crossing -- the innermost one -- so a
        # degenerate re-entry closer to the rail cannot widen the bound.
        idx = range(len(xs) - 1, 0, -1) if side < 0 else range(1, len(xs))
        for i in idx:
            a, b = ys[i - 1] - level, ys[i] - level
            if (a > 0 >= b) or (a < 0 <= b):
                frac = a / (a - b)
                return xs[i - 1] + frac * (xs[i] - xs[i - 1]), i
        return None, None

    lo_x, lo_i = crossing(vcm_v, vtail_v, level5, -1)
    y_hi = [vds1_v[k] - vcm_v[k] for k in range(len(vcm_v))]
    hi_x, hi_i = crossing(vcm_v, y_hi, -vth1, +1)

    def fmt(x):
        return "%g" % x if x is not None else "nan"
    # hi_vsb_seed: v(tail) at the in-range-adjacent coarse sample of the
    # provisional hi crossing (the sample pair's in-range side), the fixed
    # point's body-bias seed.
    vsb = vtail_v[hi_i] if hi_i is not None else float("nan")
    return f"{fmt(lo_x)} {fmt(hi_x)} {vsb:.9g} {1 if lo_x else 0} {1 if hi_x else 0}"


def fp_relocate(argv):
    # Re-locate the hi crossing on the coarse curve with this round's Vth;
    # also read the crossing's own tail bias (the next round's seed).
    path, vth1 = argv[0], float(argv[1])
    if argv[1] == "nan":
        return "nan nan 0"
    vcm_v, vtail_v, vds1_v = read_samples(path, COL_VCM, COL_VTAIL, COL_VD1)
    for i in range(1, len(vcm_v)):
        a, b = vds1_v[i - 1] - vcm_v[i - 1] + vth1, vds1_v[i] - vcm_v[i] + vth1
        if (a > 0 >= b) or (a < 0 <= b):
            frac = a / (a - b)
            return f"{vcm_v[i - 1] + frac * (vcm_v[i] - vcm_v[i - 1]):.9g} {vtail_v[i - 1]:.9g} 1"
    return "nan nan 0"


def fine_lo(argv):
    path, level = argv[0], float(argv[1])
    if argv[1] == "nan":
        return "nan nan nan nan nan 0"
    vcm_v, vtail_v, vd1_v, vd2_v, ivdd_v = read_samples(
        path, COL_VCM, COL_VTAIL, COL_VD1, COL_VD2, COL_IVDD)
    # The curve is stored in ascending Vcm; scan from the window's hi end
    # (the in-range side) DOWN so a degenerate re-entry cannot widen the
    # bound. vtail falls through the saturation level only once on this side.
    bound = None
    for i in range(len(vcm_v) - 1, 0, -1):
        a, b = vtail_v[i] - level, vtail_v[i - 1] - level
        if (a >= 0 > b):
            frac = a / (a - b)
            bound = vcm_v[i] + frac * (vcm_v[i - 1] - vcm_v[i])
            s = i
            break
    if bound is None:
        return "nan nan nan nan nan 0"
    in_window = 1 if (vcm_v[0] < bound < vcm_v[-1]) else 0
    # State at the in-range-adjacent sample (index s: the last sample at or
    # above the saturation edge -- unmodified ngspice output, same convention
    # as sim/input-offset/'s *_sample_* columns).
    return (f"{bound:.9g} {vtail_v[s]:.9g} {vd1_v[s] - vtail_v[s]:.9g} "
            f"{vd2_v[s] - vtail_v[s]:.9g} {ivdd_v[s]:.9g} {in_window}")


def fine_hi(argv):
    # Resolve the hi bound on the fine curve (bound-setting probe's Vth).
    path, vth1 = argv[0], float(argv[1])
    if argv[1] == "nan":
        return "nan nan nan nan nan nan nan 0"
    vcm_v, vtail_v, vd1_v, vd2_v, ivdd_v = read_samples(
        path, COL_VCM, COL_VTAIL, COL_VD1, COL_VD2, COL_IVDD)
    bound, s = fine_hi_crossing(vcm_v, vd1_v, vth1)
    if bound is None:
        return "nan nan nan nan nan nan nan 0"
    in_window = 1 if (vcm_v[0] < bound < vcm_v[-1]) else 0
    # State at the in-range-adjacent sample (index s).
    return (f"{bound:.9g} {vtail_v[s]:.9g} {vcm_v[s] - vtail_v[s]:.9g} {vtail_v[s]:.9g} "
            f"{vd1_v[s] - vtail_v[s]:.9g} {vd2_v[s] - vtail_v[s]:.9g} {ivdd_v[s]:.9g} {in_window}")


def fine_hi_verify(argv):
    # Fixed-point verification: re-read the bound with the verifying Vth on
    # the SAME fine curve; the shift must close within two fine steps.
    path, vth1, rec_bound, step = argv[0], float(argv[1]), float(argv[2]), float(argv[3])
    if argv[1] == "nan" or argv[2] == "nan":
        return "nan 0 nan"
    vcm_v, vd1_v = read_samples(path, COL_VCM, COL_VD1)
    bound, _ = fine_hi_crossing(vcm_v, vd1_v, vth1)
    if bound is None:
        return "nan 0 nan"
    shift = abs(bound - rec_bound)
    converged = 1 if shift <= 2 * step else 0
    return f"{bound:.9g} {converged} {shift:.9g}"


COMMANDS = {
    "coarse-bounds": (coarse_bounds, 3),
    "fp-relocate": (fp_relocate, 2),
    "fine-lo": (fine_lo, 2),
    "fine-hi": (fine_hi, 2),
    "fine-hi-verify": (fine_hi_verify, 4),
}


def main(argv):
    if len(argv) < 1 or argv[0] not in COMMANDS:
        sys.stderr.write("usage: cmr_analysis.py {%s} ARGS...\n" % "|".join(COMMANDS))
        return 2
    fn, nargs = COMMANDS[argv[0]]
    if len(argv) - 1 != nargs:
        sys.stderr.write(f"cmr_analysis.py {argv[0]}: expected {nargs} arguments\n")
        return 2
    print(fn(argv[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

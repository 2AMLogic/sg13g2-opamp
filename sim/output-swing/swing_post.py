#!/usr/bin/env python3
"""Pure, stdlib-only output-swing post-processing shared by run_swing_sweep.sh
and the offline raw-evidence audit in signoff/characterization/generate.py
(issue #230).

One definition of every curve-derived number, so the bench and the audit
cannot diverge. Nothing here touches ngspice, the PDK or the network.

Input per PVT point: the testbench's `wrdata` files. Column layout (see
sim/gm-id-characterization/README.md "wrdata column layout" for this gotcha
documented once for the whole tree): one (scale, value) pair per recorded
vector, in the order requested by the testbench's own wrdata line. The
coarse pass records v(out) alone (2 columns); the fine pass records
v(out) and i(vdd) (4 columns: v(out)'s own sweep scale, v(out), the same
sweep scale again, i(vdd) -- the two scale columns must agree, and the
strict parser enforces that).

Definitions (moved verbatim from run_swing_sweep.sh's former embedded
scripts):
  * coarse: the unique interpolated Vout = Vcm crossing (nan unless exactly
    one), both hard-clipped plateau levels (the curve's extremes), and the
    plateau flag -- both window ends must sit on parts of the curve whose
    incremental slope is <= 1% of the curve's own peak segment slope (a
    slope-ratio rule, self-calibrating per corner; an absolute mV-flatness
    rule is wrong at hot corners -- README.md "Per-point sanity checks" 2);
  * fine: the -6 dB incremental-gain region -- the contiguous block of
    sweep segments around the peak-gain segment whose two-point gain
    dVout/dVid stays >= criterion x peak (sampled convention, first maximum
    wins) -- the Vout extremes over that region's endpoint samples are the
    tracking bounds; headrooms from VDD/VSS, span, the interpolated
    Vout = Vcm crossing, the mid-swing operating point (the swept sample
    nearest the coarse crossing) and the per-point sanity flag.

Serialization the producer applies: `f"{x:.9g}"` (printf %.9g), "nan" for
NaN; flags are 0/1 integers. The audit's tolerance IS that serialization.

CLI (what the runner runs):
  swing_post.py coarse <coarse.csv> <vcm>
    prints: vos_coarse n_crossings clip_high clip_low plateau_ok
  swing_post.py fine <fine.csv> <vdd> <vcm> <clip_high> <clip_low> \
      <plateau_ok> <vos_coarse> <av0_db_ac> <ivdd_ac> <vos_off> [criterion]
    prints the 17 fields the runner writes per point (op_pass first); the
    failure reason, when the analysis cannot be made, goes to stderr.
"""
import math
import re
import sys

# Measurement configuration of the committed bench (run_swing_sweep.sh
# COARSE_START/COARSE_STOP/COARSE_STEP, FINE_HALFSPAN, FINE_STEP,
# CRITERION_FRAC). The audit refuses any other configuration.
CONFIG = {
    "coarse_start_v": "-0.1",
    "coarse_stop_v": "0.1",
    "coarse_step_v": "500e-6",
    "fine_halfspan_v": "25e-3",
    "fine_step_v": "10e-6",
    "criterion_frac": "0.5",
}

# Vectors each pass's wrdata line records, in wrdata argument order.
COARSE_VECTORS = ("v(out)",)
FINE_VECTORS = ("v(out)", "i(vdd)")

# Summary cells the audit recomputes from the pinned raw curves and rendered
# netlists. The record's remaining columns (vos_offset_record_v, vos_delta_v,
# av0_ac_record_db, av0_ratio, ivdd_ac_record_a, ivdd_ratio) are cross-bench
# joins to sim/input-offset/ and sim/open-loop-ac/ -- logged, not gated
# (README.md "Cross-checks") -- and stay outside the audit.
AUDIT_FIELDS = (
    "vdd_v", "vcm_v", "op_pass",
    "vout_max_track_v", "vout_min_track_v", "headroom_hi_v", "headroom_lo_v",
    "swing_span_v", "vout_clip_high_v", "vout_clip_low_v",
    "vos_crossing_v", "peak_inc_gain_v_v", "ivdd_center_a",
)

_NUM = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


class SwingError(Exception):
    """Malformed curve, netlist or measurement that cannot be made (names the cause)."""


def _number(tok, where):
    if not _NUM.match(tok):
        raise SwingError(f"{where}: {'non-finite' if tok.lstrip('+-').lower() in ('nan', 'inf', 'infinity') else 'non-numeric'} value {tok!r}")
    x = float(tok)
    if not math.isfinite(x):
        raise SwingError(f"{where}: non-finite value {tok!r}")
    return x


def parse_wrdata(text, vectors, name="sweep"):
    """Strictly parse a wrdata file recording `vectors` into (scale, columns).

    Every non-blank line needs exactly 2*len(vectors) finite numeric tokens;
    every vector's scale column must agree with column 0 (mismatched wrdata
    scales are an error, never silently ignored); the scale must strictly
    increase; at least two samples. columns[k] holds the values of
    vectors[k]."""
    n = len(vectors)
    scales, cols = [], [[] for _ in range(n)]
    for lineno, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        where = f"{name}:{lineno}"
        if len(parts) != 2 * n:
            raise SwingError(
                f"{where}: expected {2 * n} columns ({' '.join(vectors)}), got {len(parts)}: {line!r}")
        s = _number(parts[0], where)
        for k in range(1, n):
            other = _number(parts[2 * k], where)
            if other != s:
                raise SwingError(
                    f"{where}: scale column {2 * k} ({parts[2 * k]}) disagrees with column 0 "
                    f"({parts[0]}) -- mismatched wrdata scales")
        if scales and not s > scales[-1]:
            raise SwingError(f"{where}: sweep scale {parts[0]} does not increase (previous {scales[-1]!r})")
        scales.append(s)
        for k in range(n):
            cols[k].append(_number(parts[2 * k + 1], where))
    if len(scales) < 2:
        raise SwingError(f"{name}: {len(scales)} sample(s); need at least 2")
    return scales, cols


def sweep_count(start, stop, step):
    """Samples a rendered `dc <start> <stop> <step>` sweep produces."""
    return int(round((stop - start) / step)) + 1


def coarse_measure(vid, vout, vcm):
    """The coarse pass's measurement (README.md "Two passes", pass 1)."""
    crossings = []
    for i in range(1, len(vid)):
        a, b = vout[i - 1] - vcm, vout[i] - vcm
        if (a <= 0 < b) or (a >= 0 > b):
            frac = (vcm - vout[i - 1]) / (vout[i] - vout[i - 1])
            crossings.append(vid[i - 1] + frac * (vid[i] - vid[i - 1]))

    def seg_gain(i):
        dv = vout[i] - vout[i - 1]
        di = vid[i] - vid[i - 1]
        return dv / di if di != 0 else 0.0

    clip_high = max(vout)
    clip_low = min(vout)
    plateau_ok = 0
    flat_n = max(2, len(vid) // 50)
    peak = abs(max((seg_gain(i) for i in range(1, len(vid))), key=abs)) if len(vid) > 2 else 0.0
    if peak > 0:
        slope_lo = abs(vout[flat_n] - vout[0]) / abs(vid[flat_n] - vid[0])
        slope_hi = abs(vout[-1] - vout[-1 - flat_n]) / abs(vid[-1] - vid[-1 - flat_n])
        plateau_ok = 1 if (slope_lo <= 0.01 * peak and slope_hi <= 0.01 * peak) else 0
    return {
        "vos": crossings[0] if len(crossings) == 1 else float("nan"),
        "n_crossings": len(crossings),
        "clip_high": clip_high,
        "clip_low": clip_low,
        "plateau_ok": plateau_ok,
    }


def fine_measure(vid, vout, ivdd, vdd, vcm, clip_high, clip_low, plateau_ok,
                 vos_coarse, av0_db_ac, ivdd_ac, vos_off, criterion):
    """The fine pass's measurement (README.md "The swing criterion" and
    "Per-point sanity checks"). All times swept in Vid; voltages in volts.

    Returns a dict keyed by raw quantities with `fail` set to None (analysis
    succeeded) or the named failure reason; on failure every derived quantity
    is nan except the echoed inputs the runner still writes (the clips and
    vos_coarse land in the row's clip/crossing columns, as before)."""
    def fail(reason):
        return {
            "fail": reason, "op_pass": 0,
            "vout_max_track": float("nan"), "vout_min_track": float("nan"),
            "headroom_hi": float("nan"), "headroom_lo": float("nan"),
            "span": float("nan"),
            "vos_crossing": vos_coarse,
            "vos_delta": float("nan"), "g_pk": float("nan"),
            "av0_ratio": float("nan"), "ivdd_center": float("nan"),
            "ivdd_ratio": float("nan"),
        }

    n = len(vid)
    if n < 10:
        return fail("fine_sweep_too_short")

    idx = None
    for i in range(1, n):
        a, b = vout[i - 1] - vcm, vout[i] - vcm
        if (a <= 0 < b) or (a >= 0 > b):
            idx = i
            break
    if idx is None:
        return fail("fine_sweep_no_crossing")
    # The crossing must sit strictly inside the fine window, not on its edge --
    # an edge crossing would mean the coarse locate pass was wrong by more than
    # the fine half-span and the fine read is not trustworthy (same rule as
    # sim/input-offset/).
    if idx <= 1 or idx >= n - 1:
        return fail("fine_sweep_crossing_at_edge")

    # Monotonic S-curve check: v(out) must never decrease (beyond fp wiggle) --
    # a non-monotonic transfer curve would make "the linear region" ambiguous.
    for i in range(1, n):
        if vout[i] < vout[i - 1] - 1e-9:
            return fail("fine_sweep_non_monotonic")

    # Incremental gain per segment; peak segment and the contiguous block of
    # segments around it still above the criterion fraction of the peak (the
    # -6 dB rule -- README.md "The swing criterion").
    g = [(vout[i] - vout[i - 1]) / (vid[i] - vid[i - 1]) for i in range(1, n)]
    peak_i = max(range(len(g)), key=lambda i: g[i])
    g_pk = g[peak_i]
    if not (g_pk == g_pk and g_pk >= 10.0):
        return fail("peak_gain_implausible")
    lo = peak_i
    while lo > 0 and g[lo - 1] >= criterion * g_pk:
        lo -= 1
    hi = peak_i
    while hi < len(g) - 1 and g[hi + 1] >= criterion * g_pk:
        hi += 1
    # The -6 dB region must be strictly inside the fine window: an edge-touching
    # region means the fine window truncated the boundary and the reported
    # swing bound is an artifact of the window, not the amplifier.
    if lo <= 0 or hi >= len(g) - 1:
        return fail("linear_region_touches_window_edge")

    # Samples inside the linear region: segment i spans samples i..i+1.
    vout_region = vout[lo:hi + 2]
    vout_max_track = max(vout_region)
    vout_min_track = min(vout_region)
    headroom_hi = vdd - vout_max_track
    headroom_lo = vout_min_track
    span = vout_max_track - vout_min_track

    # Mid-swing operating point: the simulator's own solution at the swept
    # sample nearest the Vout = Vcm crossing (at most half a fine step, 5 uV
    # of Vid, away) -- unmodified ngspice output, not a derived quantity,
    # same convention as sim/input-offset/'s `*_sample_*` columns. The supply
    # current there cross-checks sim/open-loop-ac/'s per-point Iq (same bias,
    # same grid point).
    s = idx - 1 if abs(vid[idx - 1] - vos_coarse) <= abs(vid[idx] - vos_coarse) else idx
    ivdd_center = -ivdd[s]              # i(vdd) is into the source; report drawn

    # Crossing (interpolated in the fine pass) vs the offset record's own
    # null for this point -- an independent bench's measurement of the same
    # quantity (README.md "Cross-checks"). Logged, never gated.
    frac = (vcm - vout[idx - 1]) / (vout[idx] - vout[idx - 1])
    vos_crossing = vid[idx - 1] + frac * (vid[idx] - vid[idx - 1])
    vos_delta = abs(vos_crossing - vos_off) if vos_off == vos_off else float("nan")

    # Cross-check ratios (logged, never gated): peak incremental DC gain vs
    # the AC bench's 1 Hz Av0 at this point; mid-swing Iq vs the AC bench's
    # total Iq at this point.
    if av0_db_ac == av0_db_ac:
        av_ac = 10 ** (av0_db_ac / 20.0)
        av0_ratio = g_pk / av_ac
    else:
        av0_ratio = float("nan")
    ivdd_ratio = ivdd_center / ivdd_ac if ivdd_ac == ivdd_ac and ivdd_ac != 0 else float("nan")

    # --- per-point sanity rule (README.md "Per-point sanity checks") --------
    op_pass = 1
    # Coarse window must actually have clipped on both ends for the plateau
    # levels to mean anything.
    if plateau_ok != 1:
        op_pass = 0
    # Plateaus must straddle mid-rail and contain the tracking bounds.
    if not (clip_low < vcm < clip_high):
        op_pass = 0
    if not (clip_low < vout_min_track <= vout_max_track < clip_high):
        op_pass = 0
    # Headrooms must be physical: strictly positive and strictly inside the
    # supply span (a bound outside the rails is an extraction artifact).
    if not (0.0 < headroom_hi < vdd and 0.0 < headroom_lo < vdd):
        op_pass = 0
    # The tracking bounds must sit a real distance inside the hard-clip
    # plateaus -- the -6 dB boundary by construction lies before the plateau.
    if not (vout_max_track < clip_high - 1e-6 and vout_min_track > clip_low + 1e-6):
        op_pass = 0
    # Peak incremental gain must be a real amplifying point (same floor as
    # sim/input-offset/'s rule).
    if not (g_pk == g_pk and g_pk >= 10.0):
        op_pass = 0

    return {
        "fail": None, "op_pass": op_pass,
        "vout_max_track": vout_max_track, "vout_min_track": vout_min_track,
        "headroom_hi": headroom_hi, "headroom_lo": headroom_lo,
        "span": span,
        "vos_crossing": vos_crossing, "vos_delta": vos_delta,
        "g_pk": g_pk, "av0_ratio": av0_ratio,
        "ivdd_center": ivdd_center, "ivdd_ratio": ivdd_ratio,
    }


def serialize(x):
    """The runner's number format: printf %.9g, `nan` for NaN."""
    return "nan" if x != x else f"{x:.9g}"


def format_fields(m, clip_high, clip_low, av0_db_ac, ivdd_ac, vos_off):
    """Serialized cells for the 17 fields the runner writes per point, in the
    runner's own order (op_pass first)."""
    return [str(m["op_pass"]),
            serialize(m["vout_max_track"]), serialize(m["vout_min_track"]),
            serialize(m["headroom_hi"]), serialize(m["headroom_lo"]), serialize(m["span"]),
            serialize(clip_high), serialize(clip_low),
            serialize(m["vos_crossing"]), serialize(vos_off), serialize(m["vos_delta"]),
            serialize(m["g_pk"]), serialize(av0_db_ac), serialize(m["av0_ratio"]),
            serialize(m["ivdd_center"]), serialize(ivdd_ac), serialize(m["ivdd_ratio"])]


_POINT = re.compile(r"^\* Point: corner=(\S+) temp_c=(\S+) vdd_v=(\S+) pass=(\S+)$", re.M)
_SWEEP_COMMENT = re.compile(r"^\* Sweep: Vid from (\S+) V to (\S+) V, step (\S+) V$", re.M)
_VDD = re.compile(r"^Vdd vdd 0 dc (\S+)$", re.M)
_VCM = re.compile(r"^Vcm cm 0 dc (\S+)$", re.M)
_BINP = re.compile(r"^Binp inp 0 v = v\(cm\) \+ v\(id\)/2$", re.M)
_BINN = re.compile(r"^Binn inn 0 v = v\(cm\) - v\(id\)/2$", re.M)
_MOS_LIB = re.compile(r"^\.lib \"\S*cornerMOSlv\.lib\" (\S+)$", re.M)
_DC = re.compile(r"^dc Vid (\S+) (\S+) (\S+)$", re.M)
_WRDATA = re.compile(r"^wrdata (\S+)(?: (.+))?$", re.M)


def _one(pattern, text, name, what):
    hits = pattern.findall(text)
    if len(hits) != 1:
        raise SwingError(f"{name}: {len(hits)} {what} line(s) (need exactly 1)")
    return hits[0]


def rendered_config(text, name="netlist"):
    """The measurement inputs a rendered tb_swing netlist actually carries:
    corner section, temperature, supply, common mode (must be VDD/2), the
    differential-drive convention, the swept window (dc line and `* Sweep:`
    comment, which must agree), the pass label and the wrdata target and
    vectors. Raises SwingError when a line is absent, duplicated or not of
    the rendered shape."""
    out = {}
    hit = _one(_POINT, text, name, "`* Point: corner=... temp_c=... vdd_v=... pass=...`")
    out["corner"] = hit[0]
    out["temp_c"] = _number(hit[1], f"{name}: Point temp_c")
    comment_vdd = _number(hit[2], f"{name}: Point vdd_v")
    out["pass"] = hit[3]
    out["vdd_v"] = _number(_one(_VDD, text, name, "`Vdd vdd 0 dc <v>`"), f"{name}: Vdd")
    if out["vdd_v"] != comment_vdd:
        raise SwingError(
            f"{name}: Point comment vdd_v {comment_vdd!r} disagrees with the Vdd line {out['vdd_v']!r}")
    out["vcm_v"] = _number(_one(_VCM, text, name, "`Vcm cm 0 dc <v>`"), f"{name}: Vcm")
    if abs(2.0 * out["vcm_v"] - out["vdd_v"]) > 1e-9:
        raise SwingError(f"{name}: common mode {out['vcm_v']:g} V is not VDD/2 of {out['vdd_v']:g} V")
    _one(_BINP, text, name, "`Binp inp 0 v = v(cm) + v(id)/2` drive")
    _one(_BINN, text, name, "`Binn inn 0 v = v(cm) - v(id)/2` drive")
    out["mos_section"] = _one(_MOS_LIB, text, name, "cornerMOSlv.lib")
    hit = _one(_DC, text, name, "`dc Vid <start> <stop> <step>`")
    out["start"] = _number(hit[0], f"{name}: dc start")
    out["stop"] = _number(hit[1], f"{name}: dc stop")
    out["step"] = _number(hit[2], f"{name}: dc step")
    if not (out["step"] > 0 and out["stop"] > out["start"]):
        raise SwingError(
            f"{name}: dc sweep {out['start']!r}..{out['stop']!r} step {out['step']!r} "
            "is not an increasing sweep with a positive step")
    hit = _one(_SWEEP_COMMENT, text, name, "`* Sweep: Vid from ... V to ... V, step ... V`")
    comment = (_number(hit[0], f"{name}: Sweep comment"), _number(hit[1], f"{name}: Sweep comment"),
               _number(hit[2], f"{name}: Sweep comment"))
    if comment != (out["start"], out["stop"], out["step"]):
        raise SwingError(
            f"{name}: `* Sweep:` comment {comment} disagrees with the dc line "
            f"{(out['start'], out['stop'], out['step'])}")
    hit = _one(_WRDATA, text, name, "`wrdata <file> <vectors>`")
    out["wrdata"] = hit[0]
    out["vectors"] = tuple(hit[1].split()) if hit[1] else ()
    if not out["vectors"]:
        raise SwingError(f"{name}: wrdata records no vectors")
    return out


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv):
    if len(argv) >= 2 and argv[1] == "coarse" and len(argv) == 4:
        path, vcm = argv[2], float(argv[3])
        try:
            vid, (vout,) = parse_wrdata(_read(path), COARSE_VECTORS, path)
        except (OSError, UnicodeDecodeError, SwingError) as exc:
            print(f"swing_post.py: {exc}", file=sys.stderr)
            return 1
        c = coarse_measure(vid, vout, vcm)
        print(f"{serialize(c['vos'])} {c['n_crossings']} {serialize(c['clip_high'])} "
              f"{serialize(c['clip_low'])} {c['plateau_ok']}")
        return 0
    if len(argv) >= 2 and argv[1] == "fine" and len(argv) in (12, 13):
        path = argv[2]
        vdd, vcm = float(argv[3]), float(argv[4])
        clip_high, clip_low = float(argv[5]), float(argv[6])
        plateau_ok = int(argv[7])
        vos_coarse = float(argv[8])
        av0_db_ac, ivdd_ac, vos_off = float(argv[9]), float(argv[10]), float(argv[11])
        criterion = float(argv[12]) if len(argv) == 13 else float(CONFIG["criterion_frac"])
        try:
            vid, (vout, ivdd) = parse_wrdata(_read(path), FINE_VECTORS, path)
        except (OSError, UnicodeDecodeError, SwingError) as exc:
            # Keep the runner's per-point row well-formed (17 fields,
            # op_pass=0) so the grid stays complete and the point is flagged;
            # the reason goes to stderr (the bench's own fail() convention).
            print(f"swing_post.py: {exc}", file=sys.stderr)
            print(" ".join(["0"] + ["nan"] * 5
                           + [serialize(clip_high), serialize(clip_low),
                              serialize(vos_coarse), serialize(vos_off), "nan", "nan",
                              serialize(av0_db_ac), "nan", "nan",
                              serialize(ivdd_ac), "nan"]))
            return 0
        m = fine_measure(vid, vout, ivdd, vdd, vcm, clip_high, clip_low, plateau_ok,
                         vos_coarse, av0_db_ac, ivdd_ac, vos_off, criterion)
        if m["fail"] is not None:
            print(m["fail"], file=sys.stderr)
        print(" ".join(format_fields(m, clip_high, clip_low, av0_db_ac, ivdd_ac, vos_off)))
        return 0
    print("usage: swing_post.py coarse <coarse.csv> <vcm>\n"
          "       swing_post.py fine <fine.csv> <vdd> <vcm> <clip_high> <clip_low> "
          "<plateau_ok> <vos_coarse> <av0_db_ac> <ivdd_ac> <vos_off> [criterion]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

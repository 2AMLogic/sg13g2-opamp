#!/usr/bin/env python3
"""Pure, stdlib-only slew-rate post-processing shared by run_slew_sweep.sh and
the offline raw-evidence audit in signoff/characterization/generate.py
(issue #227).

One definition of every waveform-derived number, so the bench and the audit
cannot diverge. Nothing here touches ngspice, the PDK or the network.

Input per PVT point: the testbench's `wrdata` of v(out), whose columns are a
(scale, value) pair: col1 = time [s], col2 = v(out) [V].

Definitions (moved verbatim from the runner's former embedded script):
  * slew over a +/-half window centred on mid-rail (vcm), V/us, from the FIRST
    interpolated crossing of each window edge inside the edge's time interval
    (rising: [t2, t3]; falling: [t3, tstop]);
  * linearity: inner and outer window rates agree to 2% on both edges;
  * traverse: v(out) at t2-1ns is below vcm-w_out and at t3-1ns above vcm+w_out.

Serialization the producer applies: `f"{x:.6g}"` (printf %.6g), "nan" for NaN;
the two flags are 0/1 integers.

CLI (what the runner runs):
  slew_post.py <tran.csv> <vcm> <win_outer> <win_inner> <t2_ns> <t3_ns> <tstop_ns>
prints: sr_rise sr_fall sr_rise_in sr_fall_in lin_pass trav_pass vout_min vout_max win_lo win_hi
"""
import math
import re
import sys

# Measurement configuration of the committed bench (run_slew_sweep.sh WIN_OUTER,
# WIN_INNER, T2_NS, T3_NS, TSTOP_NS). The audit refuses any other configuration.
CONFIG = {
    "t2_ns": "300",
    "t3_ns": "550",
    "tstop_ns": "800",
    "win_outer_v": "0.15",
    "win_inner_v": "0.075",
}

# Order of the derived fields, as the runner writes them to the CSV.
FIELDS = (
    "sr_rise_v_per_us", "sr_fall_v_per_us", "sr_rise_inner_v_per_us",
    "sr_fall_inner_v_per_us", "linearity_pass", "traverse_pass",
    "vout_min_v", "vout_max_v", "window_lo_v", "window_hi_v",
)

_NUM = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


class SlewError(Exception):
    """Malformed waveform or measurement that cannot be made (names the cause)."""


def _number(tok, where):
    if not _NUM.match(tok):
        raise SlewError(f"{where}: {'non-finite' if tok.lstrip('+-').lower() in ('nan', 'inf', 'infinity') else 'non-numeric'} value {tok!r}")
    x = float(tok)
    if not math.isfinite(x):
        raise SlewError(f"{where}: non-finite value {tok!r}")
    return x


def parse_waveform(text, name="waveform"):
    """Strictly parse a wrdata v(out) file into (t, v).

    Every non-blank line needs at least the (time, value) pair of finite
    numbers; time must be strictly increasing; at least two samples."""
    t, v = [], []
    for n, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        where = f"{name}:{n}"
        if len(parts) < 2:
            raise SlewError(f"{where}: expected a (time, value) pair, got {line!r}")
        ti, vi = _number(parts[0], where), _number(parts[1], where)
        if t and not ti > t[-1]:
            raise SlewError(f"{where}: time {parts[0]} does not increase (previous {t[-1]!r})")
        t.append(ti)
        v.append(vi)
    if len(t) < 2:
        raise SlewError(f"{name}: {len(t)} sample(s); need at least 2")
    return t, v


def _cross(t, v, t_lo, t_hi, level, rising):
    """First interpolated crossing of `level` inside [t_lo, t_hi]."""
    for i in range(1, len(t)):
        if not (t_lo <= t[i] <= t_hi):
            continue
        a, b = v[i - 1], v[i]
        if (rising and a <= level < b) or ((not rising) and a >= level > b):
            return t[i - 1] + (level - a) / (b - a) * (t[i] - t[i - 1])
    return None


def _slew(t, v, vcm, t_lo, t_hi, half, rising):
    """V/us over the +/-half window centred on mid-rail (nan: no crossing)."""
    first = vcm - half if rising else vcm + half
    second = vcm + half if rising else vcm - half
    ta = _cross(t, v, t_lo, t_hi, first, rising)
    tb = _cross(t, v, t_lo, t_hi, second, rising)
    if ta is None or tb is None or tb == ta:
        return float("nan")
    return 2 * half / abs(tb - ta) / 1e6


def _value_at(t, v, ts):
    for i in range(len(t)):
        if t[i] >= ts:
            return v[i]
    return v[-1]


def _close(a, b):
    return a == a and b == b and abs(a - b) <= 0.02 * abs(b)


def measure(t, v, vcm, w_out, w_in, t2, t3, tstop):
    """Waveform-derived measurement; all times in seconds, voltages in volts.

    Returns a dict keyed by FIELDS with raw floats / 0-1 ints (rates are nan
    where a window edge is never crossed inside its interval)."""
    sr_rise = _slew(t, v, vcm, t2, t3, w_out, True)
    sr_fall = _slew(t, v, vcm, t3, tstop, w_out, False)
    sr_rise_in = _slew(t, v, vcm, t2, t3, w_in, True)
    sr_fall_in = _slew(t, v, vcm, t3, tstop, w_in, False)
    lin = 1 if (_close(sr_rise_in, sr_rise) and _close(sr_fall_in, sr_fall)) else 0
    trav = 1 if (_value_at(t, v, t2 - 1e-9) < vcm - w_out and _value_at(t, v, t3 - 1e-9) > vcm + w_out) else 0
    return {
        "sr_rise_v_per_us": sr_rise, "sr_fall_v_per_us": sr_fall,
        "sr_rise_inner_v_per_us": sr_rise_in, "sr_fall_inner_v_per_us": sr_fall_in,
        "linearity_pass": lin, "traverse_pass": trav,
        "vout_min_v": min(v), "vout_max_v": max(v),
        "window_lo_v": vcm - w_out, "window_hi_v": vcm + w_out,
    }


def worst_edge(rise, fall):
    """The slower of the two edges; nan only when both are undefined."""
    vals = [x for x in (rise, fall) if x == x]
    return float("nan") if not vals else min(vals)


def serialize(x):
    """The runner's number format: printf %.6g, `nan` for NaN."""
    return "nan" if x != x else f"{x:.6g}"


def format_fields(m):
    """Serialized cells for FIELDS, exactly as the runner writes them."""
    return [str(m[k]) if k in ("linearity_pass", "traverse_pass") else serialize(m[k]) for k in FIELDS]


_PWL = re.compile(r"^Vinp\s+inp\s+0\s+dc\s+(\S+)\s+pwl\(([^)]*)\)", re.M)
_VDD = re.compile(r"^Vdd\s+vdd\s+0\s+dc\s+(\S+)\s*$", re.M)
_TRAN = re.compile(r"^tran\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.M)
_WRDATA = re.compile(r"^wrdata\s+(\S+)\s+v\(out\)\s*$", re.M)


def _ns(tok, where):
    if not tok.endswith("n"):
        raise SlewError(f"{where}: time {tok!r} is not in ns")
    return _number(tok[:-1], where)


def rendered_config(text, name="netlist"):
    """The measurement inputs a rendered tb_slew netlist actually carries:
    supply, input common mode, the step schedule (t2 = rising-edge step,
    t3 = falling-edge step, tstop from the input source) and the .tran stop
    time, plus the wrdata target. Raises SlewError when a line is absent or
    not of the rendered shape."""
    out = {}
    m = _VDD.search(text)
    if not m:
        raise SlewError(f"{name}: no `Vdd vdd 0 dc <v>` line")
    out["vdd_v"] = _number(m.group(1), f"{name}: Vdd")
    m = _PWL.search(text)
    if not m:
        raise SlewError(f"{name}: no `Vinp inp 0 dc <vcm> pwl(...)` line")
    out["vcm_v"] = _number(m.group(1), f"{name}: Vinp dc")
    toks = m.group(2).split()
    if len(toks) != 16:
        raise SlewError(f"{name}: Vinp pwl has {len(toks)} tokens, expected 8 (time, value) pairs")
    times = [_ns(tok, f"{name}: Vinp pwl") if i else 0.0 for i, tok in enumerate(toks[0::2])]
    # pair 0 is time 0 (no unit), 3 = T2 hold, 5 = T3 hold, 7 = T_STOP
    out["t2_ns"], out["t3_ns"], out["tstop_ns"] = times[3], times[5], times[7]
    m = _TRAN.search(text)
    if not m:
        raise SlewError(f"{name}: no `tran <step> <stop> 0 <tmax>` line")
    out["tran_stop_ns"] = _ns(m.group(2), f"{name}: tran stop")
    m = _WRDATA.search(text)
    if not m:
        raise SlewError(f"{name}: no `wrdata <file> v(out)` line")
    out["wrdata"] = m.group(1)
    return out


def main(argv):
    path = argv[1]
    vcm, w_out, w_in = float(argv[2]), float(argv[3]), float(argv[4])
    t2, t3, tstop = (float(x) * 1e-9 for x in argv[5:8])
    try:
        with open(path, encoding="utf-8") as f:
            t, v = parse_waveform(f.read(), path)
    except (OSError, UnicodeDecodeError, SlewError) as exc:
        print(f"slew_post.py: {exc}", file=sys.stderr)
        return 1
    print(" ".join(format_fields(measure(t, v, vcm, w_out, w_in, t2, t3, tstop))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

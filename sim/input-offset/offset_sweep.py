"""Per-draw sweep parser for run_offset_mc.sh (stdlib only, no ngspice).

Classifies one draw's `Vid Vout` sweep CSV into (status, reason, vos).
Malformed numeric tokens, non-finite samples and a non-finite interpolated
offset are explicit FAIL reasons, never PASS and never an exception, so the
campaign keeps scanning later draws. Offline tests: test_offset_sweep.py.
"""
import math

WINDOW = 0.9 * 0.1  # same per-point sanity bound as run_offset_sweep.sh


def classify_sweep(sweep_path, target):
    """Return (status, reason, vos_text) for the sweep file at sweep_path."""
    vid, vout = [], []
    try:
        with open(sweep_path) as f:
            for line in f:
                p = line.split()
                if len(p) < 2:
                    continue
                try:
                    vid.append(float(p[0]))
                    vout.append(float(p[1]))
                except ValueError:
                    return "FAIL", "malformed_sweep_token", "nan"
    except OSError:
        vid, vout = [], []
    if not vid:
        return "FAIL", "no_sweep_file", "nan"
    if not all(math.isfinite(x) for x in vid + vout):
        return "FAIL", "nonfinite_sweep_data", "nan"
    crossings = []
    for i in range(1, len(vid)):
        a, b = vout[i - 1] - target, vout[i] - target
        if (a <= 0 < b) or (a >= 0 > b):
            frac = (target - vout[i - 1]) / (vout[i] - vout[i - 1])
            crossings.append(vid[i - 1] + frac * (vid[i] - vid[i - 1]))
    if len(crossings) != 1:
        return "FAIL", "crossings=%d" % len(crossings), "nan"
    if not math.isfinite(crossings[0]):
        return "FAIL", "nonfinite_offset", "nan"
    if abs(crossings[0]) >= WINDOW:
        return "FAIL", "vos_outside_window", "nan"
    return "PASS", "", "%.9g" % crossings[0]

#!/usr/bin/env python3
"""Pure, stdlib-only noise post-processing shared by run_noise_sweep.sh and the
offline raw-evidence audit in signoff/characterization/generate.py (issue #213).

One definition of every derived number, so the bench and the audit cannot
diverge. Nothing here touches ngspice, the PDK or the network.

Inputs per PVT point:
  * the in-band spectrum written by the testbench's `wrdata` (4 columns:
    freq, inoise_spectrum [V/sqrt(Hz)], freq (dup), onoise_spectrum), 81 points
    at `dec 20` from exactly 100 Hz to 1 MHz;
  * the ngspice log's `NOISE_INOISE_TOTAL <vrms>` line (ngspice's own
    integrated input noise).

Serialization the producer applies (run_noise_sweep.sh):
  * vni_int_vrms           -- the log token, copied VERBATIM (no reformatting);
  * everything else here   -- `f"{x:.6g}"` (printf %.6g), "nan" for NaN.
"""
import math
import re
import sys

BAND_LO_HZ = 100.0
BAND_HI_HZ = 1e6
POINTS_PER_DECADE = 20
N_POINTS = 81
SPOT_INDEX = ((0, 1e2), (20, 1e3), (40, 1e4), (60, 1e5), (80, 1e6))
GRID_REL_TOL = 1e-6  # spot/grid assertion tolerance of the original runner

# Order of the derived fields, as the runner writes them to the CSV.
SPECTRUM_FIELDS = (
    "vni_int_crosscheck_ratio",
    "vni_100hz_v_rthz", "vni_1khz_v_rthz", "vni_10khz_v_rthz",
    "vni_100khz_v_rthz", "vni_1mhz_v_rthz",
    "flicker_coeff_v2", "thermal_floor_v_rthz",
    "flicker_corner_hz", "flicker_frac_of_msq",
)
LOG_KEY = "NOISE_INOISE_TOTAL"

_NUM = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


class NoiseError(Exception):
    """Malformed raw noise evidence (message names file/line/field)."""


def _number(tok, where):
    if tok.lstrip("+-").lower() in ("nan", "inf", "infinity"):
        raise NoiseError(f"{where}: non-finite value {tok!r}")
    if not _NUM.match(tok):
        raise NoiseError(f"{where}: malformed numeric token {tok!r}")
    v = float(tok)
    if not math.isfinite(v):
        raise NoiseError(f"{where}: non-finite value {tok!r}")
    return v


def parse_log_total(text, name="log"):
    """(token, value) of the single NOISE_INOISE_TOTAL line of an ngspice log.

    The token is returned verbatim because the runner serializes it verbatim.
    Exactly one such line must exist and its value must be finite and > 0.
    """
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith(LOG_KEY + " "):
            hits.append((lineno, line.split()))
    if not hits:
        raise NoiseError(f"{name}: no {LOG_KEY} line")
    if len(hits) > 1:
        raise NoiseError(
            f"{name}: {len(hits)} {LOG_KEY} lines (lines "
            f"{', '.join(str(n) for n, _ in hits)}); exactly one is required"
        )
    lineno, parts = hits[0]
    if len(parts) < 2:
        raise NoiseError(f"{name}:{lineno}: {LOG_KEY} line has no value")
    value = _number(parts[1], f"{name}:{lineno}: {LOG_KEY}")
    if not value > 0:
        raise NoiseError(f"{name}:{lineno}: {LOG_KEY} {parts[1]!r} is not positive")
    return parts[1], value


def parse_spectrum(text, name="spectrum"):
    """(freqs, dens) from a wrdata in-band spectrum, strictly validated:
    4 finite columns per row, positive densities, the duplicated frequency
    column equal to the first, and the documented 81-point `dec 20` grid from
    100 Hz to 1 MHz (strictly increasing)."""
    freqs, dens = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 4:
            raise NoiseError(f"{name}:{lineno}: row has {len(parts)} columns, expected 4")
        f = _number(parts[0], f"{name}:{lineno}: frequency")
        d = _number(parts[1], f"{name}:{lineno}: inoise_spectrum")
        f2 = _number(parts[2], f"{name}:{lineno}: duplicated frequency")
        _number(parts[3], f"{name}:{lineno}: onoise_spectrum")
        if f2 != f:
            raise NoiseError(f"{name}:{lineno}: duplicated frequency column {f2!r} != {f!r}")
        if not d > 0:
            raise NoiseError(f"{name}:{lineno}: inoise_spectrum {parts[1]!r} is not positive")
        freqs.append(f)
        dens.append(d)
    if len(freqs) != N_POINTS:
        raise NoiseError(f"{name}: expected {N_POINTS} swept points, got {len(freqs)}")
    for i in range(1, len(freqs)):
        if not freqs[i] > freqs[i - 1]:
            raise NoiseError(
                f"{name}: frequency grid is not strictly increasing at point {i} "
                f"({freqs[i - 1]!r} then {freqs[i]!r})"
            )
    for i, f in enumerate(freqs):
        want = BAND_LO_HZ * 10.0 ** (i / POINTS_PER_DECADE)
        if abs(f - want) / want > GRID_REL_TOL:
            raise NoiseError(
                f"{name}: grid point {i} is {f!r} Hz, expected {want:.6g} Hz "
                f"(dec {POINTS_PER_DECADE} from {BAND_LO_HZ:g} Hz to {BAND_HI_HZ:g} Hz)"
            )
    for idx, want in SPOT_INDEX:
        if abs(freqs[idx] - want) / want > GRID_REL_TOL:
            raise NoiseError(f"{name}: spot index {idx} is {freqs[idx]!r} Hz, expected {want:g} Hz")
    return freqs, dens


def derive(freqs, dens, vni_int):
    """Spectrum-derived quantities, in SPECTRUM_FIELDS order (floats).

    Spot densities at the five stated frequencies; a weighted least-squares
    split of S(f)=dens^2 into A/f + B with relative (1/S^2) weighting; the
    flicker corner A/B; the flicker fraction of the mean square; and the
    trapezoidal cross-check sqrt(integral S df)/vni_int of ngspice's own
    integrated figure (the one quantity that also uses the logged total).
    """
    spots = [dens[idx] for idx, _ in SPOT_INDEX]
    S = [d * d for d in dens]
    sa = sb = sab = ra = rb = 0.0
    for fq, s in zip(freqs, S):
        x1, x2, w = 1.0 / fq, 1.0, 1.0 / (s * s)
        sa += w * x1 * x1
        sab += w * x1 * x2
        sb += w * x2 * x2
        ra += w * x1 * s
        rb += w * x2 * s
    det = sa * sb - sab * sab
    A = (ra * sb - rb * sab) / det
    B = (rb * sa - ra * sab) / det

    flo, fhi = freqs[0], freqs[-1]
    msq_flicker = A * math.log(fhi / flo) if A > 0 else 0.0
    msq_thermal = B * (fhi - flo) if B > 0 else 0.0
    tot = msq_flicker + msq_thermal
    ffrac = msq_flicker / tot if tot > 0 else float("nan")
    fcorner = A / B if (A > 0 and B > 0) else float("nan")
    thermal_floor = math.sqrt(B) if B > 0 else float("nan")

    msq = 0.0
    for i in range(1, len(freqs)):
        msq += 0.5 * (S[i - 1] + S[i]) * (freqs[i] - freqs[i - 1])
    cross_ratio = math.sqrt(msq) / vni_int if vni_int > 0 else float("nan")
    return [cross_ratio, *spots, A, thermal_floor, fcorner, ffrac]


def serialize(x):
    """The runner's cell format: printf %.6g, 'nan' for NaN."""
    return "nan" if x != x else f"{x:.6g}"


def main(argv):
    path, vni_int = argv[1], float(argv[2])
    try:
        with open(path) as f:
            freqs, dens = parse_spectrum(f.read(), path)
        print(" ".join(serialize(v) for v in derive(freqs, dens, vni_int)))
    except (NoiseError, OSError) as exc:
        raise SystemExit(f"noise_post.py: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

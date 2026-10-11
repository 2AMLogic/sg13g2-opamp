"""Strict parser/validator for the CMRR mismatch bench's raw sample echo files.

Shared by run_cmrr_mismatch_mc.sh (stat_point) and make_draws_csv.sh so the
campaign statistics and the per-draw conversion cannot diverge (issue #174).

File format (one record per line, whitespace separated, blank lines ignored):
    OP <k> vout vd1 vd2 vtail vibias ivdd      (exactly 8 tokens)
    AC <k> acm10m acm01 acm1k                  (exactly 5 tokens)

Every draw index 0..n-1 must have exactly one OP and exactly one AC record.
Rejected (SampleError): unknown record types, short or long records,
malformed or non-finite numeric tokens (nan, inf, 1e999, ...), malformed or
duplicate indices, missing pairs, empty files. Messages name the file, line,
draw and offending field.
"""
import math
import re

_INT = re.compile(r"[0-9]+\Z")
_NUM = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
OP_FIELDS = ("vout", "vd1", "vd2", "vtail", "vibias", "ivdd")
AC_FIELDS = ("acm10m", "acm01", "acm1k")


class SampleError(Exception):
    pass


def _num(tok, path, lineno, draw, field):
    if tok.lstrip("+-").lower() in ("nan", "inf", "infinity"):
        raise SampleError(f"{path}:{lineno}: draw {draw}: non-finite value "
                          f"{tok!r} in field {field}")
    if not _NUM.match(tok):
        raise SampleError(f"{path}:{lineno}: draw {draw}: malformed numeric token "
                          f"{tok!r} in field {field}")
    v = float(tok)
    if not math.isfinite(v):
        raise SampleError(f"{path}:{lineno}: draw {draw}: non-finite value "
                          f"{tok!r} in field {field}")
    return v


def read_samples(path):
    """Return (n, ops, acs): ops[k] = [6 floats], acs[k] = [3 floats]."""
    n, ops, acs, _ = read_samples_raw(path)
    return n, ops, acs


def read_samples_raw(path):
    """As read_samples, plus ac_tokens[k] = the 3 validated AC text tokens
    (so the draws CSV can republish them byte-for-byte)."""
    ops, acs, ac_tokens = {}, {}, {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            p = line.split()
            if not p:
                continue
            kind = p[0]
            if kind not in ("OP", "AC"):
                raise SampleError(f"{path}:{lineno}: unknown record type {kind!r}")
            fields, table = (OP_FIELDS, ops) if kind == "OP" else (AC_FIELDS, acs)
            want = 2 + len(fields)
            if len(p) != want:
                raise SampleError(f"{path}:{lineno}: {kind} record has {len(p)} "
                                  f"tokens, expected {want}")
            if not _INT.match(p[1]):
                raise SampleError(f"{path}:{lineno}: {kind} malformed draw index {p[1]!r}")
            k = int(p[1])
            if k in table:
                raise SampleError(f"{path}:{lineno}: duplicate {kind} record for draw {k}")
            table[k] = [_num(t, path, lineno, k, name) for t, name in zip(p[2:], fields)]
            if kind == "AC":
                ac_tokens[k] = tuple(p[2:])
    if not ops and not acs:
        raise SampleError(f"{path}: empty sample file")
    n = max(list(ops) + list(acs)) + 1
    for k in range(n):
        for kind, table in (("OP", ops), ("AC", acs)):
            if k not in table:
                raise SampleError(f"{path}: draw {k}: missing {kind} record "
                                  f"(truncated or non-contiguous)")
    return n, ops, acs, ac_tokens


def point_stats(n, ops, acs, av0_db, vdd, vcm, rail_frac, mid_frac, plateau_tol):
    """Pure per-point CMRR statistics from validated samples (issue #208).

    The single implementation behind run_cmrr_mismatch_mc.sh's stat_point and
    the characterization audit (signoff/characterization/generate.py), so the
    campaign record and its offline re-derivation cannot diverge. Returns a
    dict of unrounded numbers; callers serialize (the bench prints %.6g).

    Acceptance rules (per draw k): a draw is op_fail when |vout - vcm| >
    mid_frac*vdd or any of vout/vd1/vd2/vtail leaves [rail_frac*vdd,
    vdd - rail_frac*vdd]; otherwise plateau_fail when |acm10m - acm01| >
    plateau_tol; else accepted. The DR-0004 statistic is computed in the
    LINEAR Acm domain: mean + 3*sigma (sample sigma, N-1) of 10**(acm/20),
    mapped to dB once: cmrr_3sigma_db = av0_db - 20*log10(mean + 3*sigma).
    dB-domain mean / 1st percentile / minimum are context columns.
    Raises SampleError when fewer than 2 draws are accepted.
    """
    rail_lo, rail_hi = rail_frac * vdd, vdd - rail_frac * vdd
    acm_lin, acm1k_lin, cmrr_db, cmrr1k_db = [], [], [], []
    excluded = op_fail = plateau_fail = 0
    plateau_max = 0.0
    for k in range(n):
        vout, vd1, vd2, vtail = ops[k][:4]
        acm10m, acm01, acm1k = acs[k]
        ok = abs(vout - vcm) <= mid_frac * vdd
        for node in (vout, vd1, vd2, vtail):
            if not (rail_lo <= node <= rail_hi):
                ok = False
        pdelta = abs(acm10m - acm01)
        plateau_max = max(plateau_max, pdelta)
        if not ok:
            op_fail += 1
            excluded += 1
        elif pdelta > plateau_tol:
            plateau_fail += 1
            excluded += 1
        else:
            acm_lin.append(10 ** (acm10m / 20.0))
            acm1k_lin.append(10 ** (acm1k / 20.0))
            cmrr_db.append(av0_db - acm10m)
            cmrr1k_db.append(av0_db - acm1k)
    n_ok = len(acm_lin)
    if n_ok < 2:
        raise SampleError("fewer than 2 accepted draws")

    def lin_stats(v):
        mu = sum(v) / len(v)
        var = sum((x - mu) ** 2 for x in v) / (len(v) - 1)
        return mu, math.sqrt(var)

    mu_a, sd_a = lin_stats(acm_lin)
    acm_3s_db = 20 * math.log10(mu_a + 3 * sd_a)
    mu_a1k, sd_a1k = lin_stats(acm1k_lin)
    acm1k_3s_db = 20 * math.log10(mu_a1k + 3 * sd_a1k)
    sv = sorted(cmrr_db)
    pos = 0.01 * (n_ok - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n_ok - 1)
    frac = pos - lo
    return {
        "mc_n": n, "mc_n_ok": n_ok, "mc_n_excluded": excluded,
        "op_fail": op_fail, "plateau_fail": plateau_fail,
        "acm_lin_mean": mu_a, "acm_lin_sigma": sd_a,
        "acm_plus_3sigma_db": acm_3s_db,
        "cmrr_3sigma_db": av0_db - acm_3s_db,
        "cmrr_db_mean": sum(cmrr_db) / n_ok,
        "cmrr_db_p01": sv[lo] * (1 - frac) + sv[hi] * frac,
        "cmrr_db_min": sv[0],
        "cmrr_1khz_3sigma_db": av0_db - acm1k_3s_db,
        "plateau_max_db": plateau_max,
    }

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

#!/usr/bin/env python3
"""Shared numeric-CSV-column reader for the sim/*/ worst-corner summary heredocs.

Every sweep runner ends by summarising its per-point CSV into the record's
README-style worst/best-corner table. The tiny "read one column as floats,
drop the unusable values, keep the row for point_id attribution" helper behind
that summary was copied into eight runners under five names and three
signatures, and the copies had drifted (issue #373). This module is the one
copy; runners import it with PYTHONPATH="${SIM_DIR}/tools" on the summary
`python3 -` invocation. Stdlib only, offline.

Unified "unusable cell" semantics -- one value is skipped, per cell, when:

* the column is absent from the row (KeyError) -- inherited from the
  input-offset copy, which was the only one catching it; the other seven
  aborted the whole summary on a renamed/missing column;
* the string does not parse as a float (ValueError) -- covers empty cells,
  which cmrr-mismatch's copy used to pre-filter with an `if r[key]`
  truthiness test, and non-numeric junk;
* the value is NaN (`v == v` is false) -- inherited from seven of the eight
  copies; cmrr-mismatch's copy lacked the filter, so a NaN could poison its
  min()/max() and make the reported corner depend on row order.

Compared to cmrr-mismatch's copy this also drops the whole-column swallow:
one unparseable cell no longer discards the column, it skips just that cell,
like every other copy did. +-inf parses, passes the NaN filter, and is kept
-- min()/max() stay deterministic on it -- which is every inherited copy's
behaviour; the filter here is NaN-only, not a finiteness filter.

What stays per bench: the metric list, the min/max aggregation direction and
the output formatting. numeric() preserves input row order, so a value tie in
pick()/min()/max() resolves to the earliest row, deterministically.

test_csv_summary.py, beside this file, pins these semantics.
"""

from __future__ import annotations


def numeric(rows, key):
    """Return [(float(value), row), ...] for the usable cells of column `key`.

    `rows` is a list of csv.DictReader row dicts. A row whose `key` cell is
    missing, unparseable, or NaN contributes nothing; every other row
    contributes (value, the original row dict), in input order.
    """
    out = []
    for r in rows:
        try:
            v = float(r[key])
        except (ValueError, KeyError):
            continue
        if v == v:  # NaN excludes itself
            out.append((v, r))
    return out


def pick(rows, key, fn):
    """numeric() reduced to a single (value, row), or None when nothing is usable.

    `fn` is min or max (anything accepting an iterable plus a key= callable).
    The cmrr-psrr summary fused this reduction into its copy of numeric();
    callers that want the whole reduced pair use this, callers that want the
    full column call numeric() directly.
    """
    pairs = numeric(rows, key)
    return fn(pairs, key=lambda t: t[0]) if pairs else None

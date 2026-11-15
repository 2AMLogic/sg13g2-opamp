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

* the cell is None -- a short/ragged csv.DictReader row, whose missing
  field DictReader fills with None (restval); float(None) raises TypeError,
  which is skipped, so one short row cannot abort the summary (#390);
* the string does not parse as a float (ValueError) -- covers empty cells,
  which cmrr-mismatch's copy used to pre-filter with an `if r[key]`
  truthiness test, and non-numeric junk;
* the value is NaN (`v == v` is false) -- inherited from seven of the eight
  copies; cmrr-mismatch's copy lacked the filter, so a NaN could poison its
  min()/max() and make the reported corner depend on row order.

A `key` absent from the rows at all raises KeyError and aborts the summary.
csv.DictReader gives every row exactly the header's key set, so KeyError
from `r[key]` is all-or-nothing -- it fires on every row (column not in the
CSV header at all, i.e. the runner's writer and its summary disagree about
a name) or on none. Before #390 this module swallowed it per cell, which
let such a name drift render as "n/a" in the record's worst-corner table;
seven of the eight pre-#373 copies aborted on it, and that loudness is
restored. There is no ragged-row KeyError to tolerate: a genuinely short
row arrives as a None cell, covered by the TypeError skip above.

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

    `rows` is a list of csv.DictReader row dicts. A `key` absent from the
    header raises KeyError -- with DictReader that means the column is not
    in the CSV at all, a writer/summariser name drift that must be loud. A
    row whose `key` cell is None (a short row), unparseable, or NaN
    contributes nothing; every other row contributes (value, the original
    row dict), in input order.
    """
    out = []
    for r in rows:
        try:
            v = float(r[key])
        except (ValueError, TypeError):
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

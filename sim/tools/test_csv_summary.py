#!/usr/bin/env python3
"""Tests for csv_summary.py, the shared worst-corner CSV-column reader (issue #373).

    python3 -m unittest discover -s sim/tools -p 'test_*.py'

These pin the unified "unusable value" semantics the eight copied heredoc
readers were folded into (#373), refined by #390: a column absent from the
header raises KeyError -- a writer/summariser name drift must abort the
summary, not print "n/a" into the record's worst-corner table -- while a
per-cell unusable value is skipped: a DictReader short row's None cell
(TypeError), an unparseable string (ValueError), and NaN via the `v == v`
filter every inherited copy except cmrr-mismatch's carried. +-inf parses
and is KEPT -- that is the inherited behaviour too (the filter is
NaN-only), and min/max stay deterministic on it, so the test pins it
rather than "fixes" it.

The reduction-stability tests matter because these readers decide which grid
point is reported as the binding corner in every record's worst-corner table:
a value tie must resolve to the earliest row, deterministically.

Self-contained: builds its own rows rather than importing a bench. Stdlib
only, offline.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csv_summary as cs  # noqa: E402


def row(pid, **cells):
    r = {"point_id": pid}
    r.update(cells)
    return r


class NumericTests(unittest.TestCase):
    def test_plain_column_keeps_row_for_attribution(self):
        rows = [row("a", x="1.5"), row("b", x="2.5")]
        pairs = cs.numeric(rows, "x")
        self.assertEqual(pairs, [(1.5, rows[0]), (2.5, rows[1])])
        # the row dict is the ORIGINAL object, so point_id attribution works
        self.assertIs(pairs[0][1], rows[0])

    def test_short_row_none_cell_is_skipped_per_row(self):
        # Revised from test_missing_column_is_skipped_per_row (#390): the
        # hand-built dict omitting the key was a row shape DictReader never
        # produces. The real ragged shape is a short row, whose missing
        # field DictReader fills with None (restval); float(None) raises
        # TypeError, which numeric() skips -- sibling rows still contribute.
        rows = [row("a", x="1.0"), row("b", x=None), row("c", x="3.0")]
        self.assertEqual([v for v, _ in cs.numeric(rows, "x")], [1.0, 3.0])

    def test_entirely_missing_column_raises_key_error(self):
        # Revised from test_entirely_missing_column_yields_empty (#390): a
        # key absent from the header means the runner's writer and its
        # summary disagree about a column name -- abort loudly instead of
        # yielding an empty column the call site renders as "n/a".
        # DictReader gives every row exactly the header's key set, so
        # KeyError is all-or-nothing and the raise IS the absent-column test.
        self.assertRaises(KeyError, cs.numeric, [row("a"), row("b")], "nope")

    def test_empty_cell_is_skipped(self):
        rows = [row("a", x=""), row("b", x="2.0")]
        self.assertEqual([v for v, _ in cs.numeric(rows, "x")], [2.0])

    def test_non_numeric_cell_is_skipped(self):
        rows = [row("a", x="abc"), row("b", x="2.0"), row("c", x="1e-3")]
        self.assertEqual([v for v, _ in cs.numeric(rows, "x")], [2.0, 1e-3])

    def test_nan_is_skipped(self):
        rows = [row("a", x="nan"), row("b", x="NaN"), row("c", x="2.0")]
        self.assertEqual([v for v, _ in cs.numeric(rows, "x")], [2.0])

    def test_inf_is_kept(self):
        # inherited semantics: the v == v filter is NaN-only; +-inf parses,
        # compares, and flows into min/max deterministically.
        rows = [row("a", x="inf"), row("b", x="1.0")]
        pairs = cs.numeric(rows, "x")
        self.assertEqual([v for v, _ in pairs], [float("inf"), 1.0])

    def test_all_unusable_column_yields_empty(self):
        rows = [row("a", x=""), row("b", x="nan"), row("c", x="junk")]
        self.assertEqual(cs.numeric(rows, "x"), [])

    def test_empty_rows_yields_empty(self):
        self.assertEqual(cs.numeric([], "x"), [])

    def test_input_order_is_preserved(self):
        rows = [row(f"p{i}", x=str(10 - i)) for i in range(5)]
        self.assertEqual([r["point_id"] for _, r in cs.numeric(rows, "x")],
                         [f"p{i}" for i in range(5)])


class PickTests(unittest.TestCase):
    def test_min_max_pick_value_and_row(self):
        rows = [row("a", x="3.0"), row("b", x="1.0"), row("c", x="2.0")]
        self.assertIs(cs.pick(rows, "x", min)[1], rows[1])
        self.assertIs(cs.pick(rows, "x", max)[1], rows[0])

    def test_empty_or_all_unusable_yields_none(self):
        self.assertIsNone(cs.pick([], "x", min))
        self.assertIsNone(cs.pick([row("a", x="nan")], "x", min))

    def test_tie_resolves_to_earliest_row(self):
        # row-order stability: on a value tie the earliest row wins, for both
        # min and max -- the binding-corner report must not depend on dict
        # iteration luck downstream.
        rows = [row("first", x="1.0"), row("second", x="1.0"), row("third", x="1.0")]
        self.assertEqual(cs.pick(rows, "x", min)[1]["point_id"], "first")
        self.assertEqual(cs.pick(rows, "x", max)[1]["point_id"], "first")

    def test_missing_column_with_pick_raises_key_error(self):
        # Revised from test_missing_column_with_pick_yields_none (#390):
        # pick() propagates numeric()'s KeyError for an absent column too.
        self.assertRaises(KeyError, cs.pick, [row("a")], "x", max)

    def test_all_none_cells_with_pick_yields_none(self):
        # The all-cells-unusable contract (#373) is unchanged: pick() still
        # returns None when nothing is usable. The None cells here are the
        # short-row shape; an absent column raises instead (see above).
        self.assertIsNone(cs.pick([row("a", x=None), row("b", x=None)], "x", max))


if __name__ == "__main__":
    unittest.main()

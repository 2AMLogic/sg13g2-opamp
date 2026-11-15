#!/usr/bin/env python3
"""The one definition of the shared per-point DC operating-point sanity gate.

`op_pass` is an evidence-admission rule, not a cosmetic column:
signoff/characterization/defchecks.py (`_check_open_loop_klt`) refuses a
dc_continuity point whose op_pass is not 1, so every independent copy of the
predicate was an independent definition of "this corner counts as evidence".
Issues #366 and #380 reduced eight inline copies to this module. The rule:

* the output sits within 15% of VDD of mid-rail
  (|Vout-Vcm| <= mid_frac*VDD), and
* none of vd1/vd2/vtail/vout is railed to a supply -- each inside
  [rail_frac*VDD, VDD-rail_frac*VDD].

Both ends of both windows are inclusive, and the rail window's upper edge is
spelled `vdd - rail_frac*vdd`, NOT `0.98*vdd`: those are not the same double
(they disagree for ~12% of doubles off this project's grid), and the
committed records were gated with the former.

Callers:

* `sg13g2_op_sanity` (sim/preflight.sh) -- the per-point bash gate behind
  every bench's op_pass column; shells out to this module's __main__, one
  process per point, same contract as before the fold (6 args, echoes 1/0).
* `mc_samples.point_stats` (sim/cmrr-mismatch) -- the per-draw Monte Carlo
  gate imports `op_sane` directly; the campaign loop must not pay one
  process spawn per draw (>= 13,500 draws per run).
* `run_offset_sweep.sh` (sim/input-offset) -- composes `rail_ok`, the rail
  window alone, with its own bench-specific amplifying-point guards. Its
  mid-rail gap term is deliberately absent: that bench defines its
  operating point as the `Vout = Vcm` crossing, so the gap term is
  vacuously true at every point that survives to be graded (issue #380).

`rail_frac` / `mid_frac` stay parameters on purpose: cmrr-mismatch exposes
them as OP_RAIL_FRAC / OP_MID_FRAC (run_cmrr_mismatch_mc.sh), and folding
them in as literals would silently remove two working environment knobs.

The thresholds are spec-bearing: they decide which simulated corners are
admissible evidence against the ratified spec. DO NOT tune 0.15 / 0.02 in a
refactor. A threshold that looks wrong is a spec/ question with a decision
record, exactly as for any other ratified number -- and if it ever is
changed there, re-run the committed-record replay in
sim/tools/test_op_sanity.py against records re-read (not re-gated) to keep
the old and new gates honestly distinguished.

Deliberately NOT here: post-layout's vout-only DC check
(sim/post-layout/klt_measure.py) -- it sys.exit()s the whole conversion on a
non-regulating point rather than recording a 0/1, and its OP request drops
d1/d2/tail so the pre-/post-layout legs run the identical bench -- and the
bench-specific op_pass predicates of input-cmr / output-swing. Stdlib only,
offline.
"""
import sys

DEFAULT_RAIL_FRAC = 0.02
DEFAULT_MID_FRAC = 0.15


def rail_ok(vdd, nodes, rail_frac=DEFAULT_RAIL_FRAC):
    """True when every node sits inside [rail_frac*vdd, vdd-rail_frac*vdd].

    Both ends inclusive; the upper edge is `vdd - rail_frac*vdd`, not
    `0.98*vdd` -- not the same double (module docstring).
    """
    rail_lo = rail_frac * vdd
    rail_hi = vdd - rail_frac * vdd
    return all(rail_lo <= node <= rail_hi for node in nodes)


def midrail_ok(vdd, vcm, vout, mid_frac=DEFAULT_MID_FRAC):
    """True when |vout-vcm| <= mid_frac*vdd (inclusive)."""
    return abs(vout - vcm) <= mid_frac * vdd


def op_sane(vdd, vcm, vout, vd1, vd2, vtail,
            rail_frac=DEFAULT_RAIL_FRAC, mid_frac=DEFAULT_MID_FRAC):
    """The full per-point gate: mid-rail gap AND rail window.

    Node order matches sg13g2_op_sanity's argument order; vout is checked
    by the rail window as well as the gap.
    """
    return (midrail_ok(vdd, vcm, vout, mid_frac)
            and rail_ok(vdd, (vd1, vd2, vtail, vout), rail_frac))


if __name__ == "__main__":
    if len(sys.argv) != 7:
        sys.exit("op_sanity.py: expected <vdd> <vcm> <vout> <vd1> <vd2> <vtail>, "
                 f"got {len(sys.argv) - 1} argument(s)")
    _vdd, _vcm, _vout, _vd1, _vd2, _vtail = (float(a) for a in sys.argv[1:7])
    print("1" if op_sane(_vdd, _vcm, _vout, _vd1, _vd2, _vtail) else "0")

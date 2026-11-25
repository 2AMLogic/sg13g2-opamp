#!/usr/bin/env python3
"""Pure, stdlib-only pairing and audit of the two-pass output-swing batch
evidence (issue #503).

The fixed fine window of swing.request.json (-10..+40 mV) cannot show that a
changed circuit's crossing lies inside it. The harness definition centres a
+-25 mV fine sweep on the coarse pass's measured Vout = Vcm crossing; klt
cannot centre a sweep on a measured value, so the producer runs the coarse
pass first, calls `fine_window` per corner, and submits that corner's fine
request with the rendered window. This module is the offline half: given the
two passes' pinned evidence for one corner it validates that they describe
the same DUT, bench, simulator and PVT point, that the fine window is the
serialized crossing +- half-span, and then reconstructs every
`swing_post.AUDIT_FIELDS` cell with the existing definitions (never a second
copy of them). Nothing here touches ngspice, klt or the network.

A "pass" is a dict:
  pid          "<corner>_<temp>C_<vdd>V" point id
  dut_sha256   hash of the simulated circuit (netlist closure)
  bench_sha256 hash of the simulated bench body
  simulator    engine + version string
  process, temp_c, vdd_v, vcm_v   the PVT key actually simulated
  start, stop, step               the Vid sweep actually run
  vid, vout [, ivdd]              the sampled curves (ivdd: fine pass only)
`waveform_to_pass_curves` converts a klt waveform artifact into those curves.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
import swing_post  # noqa: E402

# Ratified limits (spec/target-spec.md section 2 [DR-2]); literal numbers, as
# swing.request.json carries them. Source of truth: signoff/characterization/
# selection.json rows swing_headroom_vdd / swing_headroom_vss / swing_span;
# this copy is interim until admission through selection.py/defchecks.py lands.
LIMITS = {"headroom_hi_v": 0.251, "headroom_lo_v": 0.141, "swing_span_v": 0.571}
IDENTITY_KEYS = ("dut_sha256", "bench_sha256", "simulator", "process", "temp_c", "vdd_v", "vcm_v")


class PairError(Exception):
    """A corner's evidence cannot be paired or measured; the text names the corner and reason."""

    def __init__(self, pid, reason):
        super().__init__(f"point {pid}: {reason}")
        self.pid = pid
        self.reason = reason


def waveform_to_pass_curves(wf, vectors, pid="waveform"):
    """(vid, [column per vector]) from a klt waveform JSON
    ({"variables": [...], "points": [[x, y...]...]}); the sweep variable is
    variables[0]. Every requested vector must be present, finite and the
    sweep strictly increasing -- the strict wrdata rules, via swing_post."""
    names = [v.get("name") for v in wf.get("variables") or []]
    try:
        cols = [names.index(v) for v in vectors]
    except ValueError as exc:
        raise PairError(pid, f"waveform lacks a requested vector ({exc}); has {names}") from None
    lines = []
    for p in wf.get("points") or []:
        row = []
        try:
            for c in cols:
                row += [repr(float(p[0])), repr(float(p[c]))]
        except (IndexError, TypeError, ValueError) as exc:
            raise PairError(pid, f"waveform row {len(lines)} is short or non-numeric ({exc!r}): {p!r}") from None
        lines.append(" ".join(row))
    try:
        vid, data = swing_post.parse_wrdata("\n".join(lines), tuple(vectors), pid)
    except swing_post.SwingError as exc:
        raise PairError(pid, f"invalid curve: {exc}") from None
    return vid, data


def fine_window(coarse_vid, coarse_vout, vcm, halfspan=None):
    """The fine sweep window for one corner: the serialized (%.9g) unique
    coarse crossing +- half-span, exactly the hop the harness runner makes.
    The producer must pin the returned start/stop at full float precision
    (repr): `audit_pair` compares them for exact equality, and a %.9g
    re-serialization of the window fails that check on most corners.
    Raises PairError-free ValueError when there is not exactly one crossing."""
    half = float(swing_post.CONFIG["fine_halfspan_v"]) if halfspan is None else halfspan
    c = swing_post.coarse_measure(coarse_vid, coarse_vout, vcm)
    if c["n_crossings"] != 1:
        raise ValueError(f"{c['n_crossings']} Vout=Vcm crossings (expected exactly 1)")
    vos9 = float(swing_post.serialize(c["vos"]))
    return vos9 - half, vos9 + half, vos9


def _identity(pid, label, p):
    curves = ("vid", "vout") + (("ivdd",) if label == "fine" else ())
    for k in IDENTITY_KEYS + ("start", "stop", "step") + curves:
        if k not in p:
            raise PairError(pid, f"{label} pass records no {k}")


def audit_pair(pid, coarse, fine, criterion=None):
    """Validate and measure one corner. Returns {"fields": {AUDIT_FIELD: serialized},
    "verdicts": {limit: bool}, "valid": True}; raises PairError on any
    evidence problem (the corner and reason are in the message)."""
    crit = float(swing_post.CONFIG["criterion_frac"]) if criterion is None else criterion
    for label, p in (("coarse", coarse), ("fine", fine)):
        _identity(pid, label, p)
        if p.get("pid") != pid:
            raise PairError(pid, f"{label} pass is for point {p.get('pid')!r}")
    for k in IDENTITY_KEYS:
        if coarse[k] != fine[k]:
            raise PairError(pid, f"coarse/fine passes disagree on {k} ({coarse[k]!r} vs {fine[k]!r}) -- not the same DUT/corner")
    cfg = {k: float(v) for k, v in swing_post.CONFIG.items()}
    if (coarse["start"], coarse["stop"], coarse["step"]) != (cfg["coarse_start_v"], cfg["coarse_stop_v"], cfg["coarse_step_v"]):
        raise PairError(pid, f"coarse sweep {coarse['start']}..{coarse['stop']} step {coarse['step']} is not the pinned configuration")
    if fine["step"] != cfg["fine_step_v"]:
        raise PairError(pid, f"fine step {fine['step']} is not the pinned {cfg['fine_step_v']}")
    for label, p in (("coarse", coarse), ("fine", fine)):
        want = swing_post.sweep_count(p["start"], p["stop"], p["step"])
        for k in ("vid", "vout") + (("ivdd",) if label == "fine" else ()):
            if len(p[k]) != want:
                raise PairError(pid, f"{label} curve has {len(p[k])} samples; its sweep declares {want}"
                                     + ("" if k == "vid" else f" ({k})"))
    if abs(2.0 * coarse["vcm_v"] - coarse["vdd_v"]) > 1e-9:
        raise PairError(pid, "common mode is not VDD/2")
    c = swing_post.coarse_measure(coarse["vid"], coarse["vout"], coarse["vcm_v"])
    if c["n_crossings"] != 1:
        raise PairError(pid, f"coarse sweep has {c['n_crossings']} Vout=Vcm crossings (expected exactly 1)")
    if c["plateau_ok"] != 1:
        raise PairError(pid, "coarse sweep does not clip flat on both ends (plateau check failed)")
    vos9 = float(swing_post.serialize(c["vos"]))
    if fine["start"] != vos9 - cfg["fine_halfspan_v"] or fine["stop"] != vos9 + cfg["fine_halfspan_v"]:
        raise PairError(
            pid, f"fine window {fine['start']!r}..{fine['stop']!r} is not the coarse crossing "
                 f"{swing_post.serialize(c['vos'])} +/- {cfg['fine_halfspan_v']:g} V")
    clip_high = float(swing_post.serialize(c["clip_high"]))
    clip_low = float(swing_post.serialize(c["clip_low"]))
    m = swing_post.fine_measure(
        fine["vid"], fine["vout"], fine["ivdd"], fine["vdd_v"], fine["vcm_v"],
        clip_high, clip_low, c["plateau_ok"], vos9,
        float("nan"), float("nan"), float("nan"), crit)
    if m["fail"] is not None:
        raise PairError(pid, f"fine sweep: {m['fail']}")
    if m["op_pass"] != 1:
        raise PairError(pid, "per-point sanity rule failed (op_pass=0)")
    s = swing_post.serialize
    fields = {
        "vdd_v": s(fine["vdd_v"]), "vcm_v": s(fine["vcm_v"]), "op_pass": str(m["op_pass"]),
        "vout_max_track_v": s(m["vout_max_track"]), "vout_min_track_v": s(m["vout_min_track"]),
        "headroom_hi_v": s(m["headroom_hi"]), "headroom_lo_v": s(m["headroom_lo"]),
        "swing_span_v": s(m["span"]),
        "vout_clip_high_v": s(c["clip_high"]), "vout_clip_low_v": s(c["clip_low"]),
        "vos_crossing_v": s(m["vos_crossing"]), "peak_inc_gain_v_v": s(m["g_pk"]),
        "ivdd_center_a": s(m["ivdd_center"]),
    }
    if tuple(fields) != swing_post.AUDIT_FIELDS:
        raise PairError(pid, "audit fields drifted from swing_post.AUDIT_FIELDS")
    verdicts = {name: float(fields[name]) >= lim for name, lim in LIMITS.items()}
    return {"fields": fields, "verdicts": verdicts, "valid": True}


def check_summary(pid, summary, audited):
    """Compare a summary row (field -> cell text) to the audited cells; the
    serialization IS the tolerance. Returns the problems, naming corner and field."""
    bad = []
    for f in swing_post.AUDIT_FIELDS:
        if str(summary.get(f)) != audited["fields"][f]:
            bad.append(f"point {pid}: {f} summary {summary.get(f)!r} != reproduced {audited['fields'][f]!r}")
    return bad


def audit_population(pids, coarse_passes, fine_passes):
    """Audit every expected corner. Missing, duplicate or mismatched passes
    and measurement failures are collected per corner, never abort the rest."""
    problems, out = [], {}
    index = {}
    for label, passes in (("coarse", coarse_passes), ("fine", fine_passes)):
        seen = {}
        for p in passes:
            pid = p.get("pid")
            if pid in seen:
                problems.append(f"point {pid}: duplicate {label} pass")
            seen[pid] = p
        index[label] = seen
        for pid in sorted(set(seen) - set(pids), key=str):
            problems.append(f"point {pid}: {label} pass is outside the expected grid")
    for pid in pids:
        for label in ("coarse", "fine"):
            if pid not in index[label]:
                problems.append(f"point {pid}: missing {label} pass")
        if pid in index["coarse"] and pid in index["fine"]:
            try:
                out[pid] = audit_pair(pid, index["coarse"][pid], index["fine"][pid])
            except PairError as exc:
                problems.append(str(exc))
    return out, problems


if __name__ == "__main__":
    print(__doc__)
    sys.exit(2)

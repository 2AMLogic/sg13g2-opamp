"""Definition checks: per-point identities a record's derived column must obey.

Split out of generate.py (issue #355). Each check recomputes a published cell
from the pinned raw evidence and returns a problem string (or None);
DEFINITION_CHECKS is the table `records.load_record` dispatches on.

Depends on `common` and `paths` only. Three `klt` helpers that sat inside this
section physically -- `_validate_klt_raw_selection`, `_klt_corner_ids`,
`_klt_values` -- and the `_load_klt_population` loader belong to the selection
and record families and live in `selection.py` / `records.py`; keeping them
here would make this module depend on `records` and `rows`, which both import
it. `_check_open_loop_klt` does stay here: it is this table's entry.

Stdlib only; pure functions.
"""

from __future__ import annotations

import math
from decimal import Decimal

from common import parse_decimal
from paths import mc_samples, noise_post, slew_post, swing_post

# --------------------------------------------------------------------------
# definition checks: per-point identities a record's derived column must obey


def _check_cmrr_linear(point: dict, draws) -> str | None:
    """DR-0004's definition: Av0 - 20log10(mean + 3 sigma), LINEAR domain."""
    try:
        av0 = float(point["av0_db"])
        mean = float(point["acm_lin_mean"])
        sigma = float(point["acm_lin_sigma"])
        stated = float(point["cmrr_3sigma_db"])
    except (KeyError, ValueError) as exc:
        return f"cannot evaluate ({exc})"
    plus3 = mean + 3.0 * sigma
    if not plus3 > 0:
        return "mean + 3 sigma of Acm is not positive"
    derived = av0 - 20.0 * math.log10(plus3)
    if not math.isfinite(derived) or abs(derived - stated) > 1e-3:
        return (
            f"cmrr_3sigma_db {stated} != Av0 - 20log10(mean + 3 sigma) = {derived:.6f} "
            "(the linear-domain definition DR-0004 ratifies)"
        )
    return None


def _cell_problem(
    field: str, cell: str | None, printed: str, source: str, digits: int, nan_ok: bool = True
) -> str | None:
    """Why `cell` is not `printed`, the bench's printf %.<digits>g serialization of
    the value recomputed from `source` (a noun phrase for messages). `nan_ok`:
    a recomputed `nan` is matched by a `nan` cell; otherwise it is never accepted."""
    text = (cell or "").strip()
    if nan_ok and printed == "nan":
        return None if text.lower() == "nan" else (
            f"{field} {text!r} but the {source} gives an undefined (nan) value"
        )
    value, why = parse_decimal(cell)
    if value is None:
        return f"{field}: {why}"
    if value != Decimal(printed):
        return (
            f"{field} {value} is not {printed} recomputed from the {source} "
            f"(the bench writes this quantity with printf %.{digits}g; the cell must be that "
            f"serialization, with no tolerance beyond its {digits} digits)"
        )
    return None


def _check_cmrr_mc_statistics(point: dict, pop: dict | None) -> str | None:
    """Every published CMRR mismatch statistic must follow from the pinned raw
    samples (SAMPLES_AUDIT_RULE), with Av0 joined from the pinned
    deterministic record. `pop` is the loaded population (see load_record)."""
    if pop is None:
        return "cannot evaluate (no sample population available)"
    pid = (point.get("point_id") or "").strip()
    entry = pop["points"].get(pid)
    if entry is None:
        return "cannot evaluate (no pinned sample file for this point)"
    av0 = pop["av0"].get(pid)
    if av0 is None:
        return f"cannot evaluate (no Av0 row for this point in the joined record {pop['join_csv']})"
    try:
        vdd = float(point["vdd_v"])
    except (KeyError, ValueError) as exc:
        return f"cannot evaluate ({exc})"
    acc = pop["acceptance"]
    stated_av0, why = parse_decimal(point.get("av0_db"))
    if stated_av0 is None:
        return f"av0_db: {why}"
    if stated_av0 != Decimal(format(av0, ".6g")):
        return (
            f"av0_db {stated_av0} is not the Av0 {format(av0, '.6g')} of the pinned join "
            f"record {pop['join_csv']} (the summary may not carry its own Av0)"
        )
    vcm = vdd / 2.0
    problem = _cell_problem(
        "vcm_v", point.get("vcm_v"), format(vcm, ".6g"), "pinned samples", 6, nan_ok=False
    )
    if problem:
        return problem
    try:
        st = mc_samples.point_stats(
            entry["n"], entry["ops"], entry["acs"], av0, vdd, vcm,
            acc["op_rail_frac"], acc["op_mid_frac"], acc["plateau_tol_db"],
        )
    except mc_samples.SampleError as exc:
        return f"pinned samples give no statistics ({exc})"
    for field in ("mc_n", "mc_n_ok", "mc_n_excluded", "op_fail", "plateau_fail"):
        cell = (point.get(field) or "").strip()
        if cell != str(st[field]):
            return f"{field} {cell!r} != {st[field]} counted from the pinned samples"
    for field in (
        "acm_lin_mean", "acm_lin_sigma", "acm_plus_3sigma_db", "cmrr_3sigma_db",
        "cmrr_db_mean", "cmrr_db_p01", "cmrr_db_min", "cmrr_1khz_3sigma_db",
        "plateau_max_db",
    ):
        problem = _cell_problem(
            field, point.get(field), format(st[field], ".6g"), "pinned samples", 6, nan_ok=False
        )
        if problem:
            return problem
    return None


def _check_noise_raw(point: dict, pop: dict | None) -> str | None:
    """The input-noise summary must follow from the pinned raw artifacts
    (NOISE_AUDIT_RULE). Integrated-log and spectrum-derived checks are
    independent: both run, and every disagreement is reported."""
    if pop is None:
        return "cannot evaluate (no raw noise population available)"
    pid = (point.get("point_id") or "").strip()
    raw = pop.get(pid)
    if raw is None:
        return "cannot evaluate (no pinned raw noise artifacts for this point)"
    problems = []
    # (1) integrated figure: the bench copies the log token verbatim.
    cell, why = parse_decimal(point.get("vni_int_vrms"))
    if cell is None:
        problems.append(f"[integrated-log] vni_int_vrms: {why}")
    elif cell != Decimal(raw["token"]):
        problems.append(
            f"[integrated-log] vni_int_vrms {cell} is not the {noise_post.LOG_KEY} "
            f"{raw['token']} logged in {raw['log']} (the bench copies that token verbatim)"
        )
    # (2) spectrum-derived: independent of the summary's own integrated cell
    # (the cross-check ratio uses the LOGGED total, not the summary's).
    derived = noise_post.derive(raw["freqs"], raw["dens"], raw["value"])
    for field, value in zip(noise_post.SPECTRUM_FIELDS, derived):
        problem = _cell_problem(
            field, point.get(field), noise_post.serialize(value), "pinned spectrum", 6
        )
        if problem:
            problems.append(f"[spectrum] {problem} ({raw['spectrum']})")
    return "; ".join(problems) or None


def _check_slew_worse_edge(point: dict, draws) -> str | None:
    rise, _ = parse_decimal(point.get("sr_rise_v_per_us"))
    fall, _ = parse_decimal(point.get("sr_fall_v_per_us"))
    worst, _ = parse_decimal(point.get("sr_worst_v_per_us"))
    if None in (rise, fall, worst):
        return "cannot evaluate (missing edge column)"
    if worst != min(rise, fall):
        return f"sr_worst_v_per_us {worst} is not the worse of rise {rise} / fall {fall}"
    return None


def _check_slew_raw(point: dict, pop: dict | None) -> str | None:
    """The slew summary must follow from the pinned transient waveform
    (SLEW_AUDIT_RULE): every waveform-derived cell is recomputed by the shared
    slew_post module and compared as the bench serializes it."""
    if pop is None:
        return "cannot evaluate (no raw slew population available)"
    pid = (point.get("point_id") or "").strip()
    raw = pop.get(pid)
    if raw is None:
        return "cannot evaluate (no pinned raw slew artifacts for this point)"
    where = f"({raw['tran']})"
    problems = []
    for field, expect in (("vdd_v", raw["vdd"]), ("vcm_v", raw["vcm"])):
        problem = _cell_problem(
            field, point.get(field), slew_post.serialize(expect), "pinned waveform", 6
        )
        if problem:
            problems.append(f"{problem} (pinned rendered netlist {raw['netlist']})")
    m = slew_post.measure(raw["t"], raw["v"], raw["vcm"], raw["w_out"], raw["w_in"], raw["t2"], raw["t3"], raw["tstop"])
    for edge in ("sr_rise_v_per_us", "sr_fall_v_per_us", "sr_rise_inner_v_per_us", "sr_fall_inner_v_per_us"):
        if m[edge] != m[edge]:
            problems.append(f"{edge}: no window crossing inside its edge interval in the pinned waveform, so no passing measurement exists {where}")
    worst = slew_post.worst_edge(m["sr_rise_v_per_us"], m["sr_fall_v_per_us"])
    cells = dict(zip(slew_post.FIELDS, slew_post.format_fields(m)))
    cells["sr_worst_v_per_us"] = slew_post.serialize(worst)
    for field in (*slew_post.FIELDS[:4], "sr_worst_v_per_us", *slew_post.FIELDS[4:]):
        problem = _cell_problem(field, point.get(field), cells[field], "pinned waveform", 6)
        if problem:
            problems.append(f"{problem} {where}")
    return "; ".join(problems) or None


def _check_swing_raw(point: dict, pop: dict | None) -> str | None:
    """The output-swing summary must follow from the pinned raw DC curves and
    rendered netlists (SWING_AUDIT_RULE): every curve-derived cell is
    recomputed by the shared swing_post module and compared as the bench
    serializes it."""
    if pop is None:
        return "cannot evaluate (no raw swing population available)"
    pid = (point.get("point_id") or "").strip()
    raw = pop.get(pid)
    if raw is None:
        return "cannot evaluate (no pinned raw swing artifacts for this point)"
    where = f"({raw['coarse_csv']}, {raw['fine_csv']})"
    problems = []
    for field, expect in (("vdd_v", raw["vdd"]), ("vcm_v", raw["vcm"])):
        problem = _cell_problem(
            field, point.get(field), swing_post.serialize(expect), "pinned raw curves", 9
        )
        if problem:
            problems.append(f"{problem} (pinned rendered netlist {raw['fine_netlist']})")
    fine = raw["fine"]
    if fine["fail"] is not None:
        problems.append(
            f"fine analysis failed: {fine['fail']} {where}; no passing measurement exists "
            "from the pinned curves")
        return "; ".join(problems) or None
    coarse = raw["coarse"]
    recomputed = {
        "op_pass": str(fine["op_pass"]),
        "vout_max_track_v": swing_post.serialize(fine["vout_max_track"]),
        "vout_min_track_v": swing_post.serialize(fine["vout_min_track"]),
        "headroom_hi_v": swing_post.serialize(fine["headroom_hi"]),
        "headroom_lo_v": swing_post.serialize(fine["headroom_lo"]),
        "swing_span_v": swing_post.serialize(fine["span"]),
        "vout_clip_high_v": swing_post.serialize(coarse["clip_high"]),
        "vout_clip_low_v": swing_post.serialize(coarse["clip_low"]),
        "vos_crossing_v": swing_post.serialize(fine["vos_crossing"]),
        "peak_inc_gain_v_v": swing_post.serialize(fine["g_pk"]),
        "ivdd_center_a": swing_post.serialize(fine["ivdd_center"]),
    }
    for field in swing_post.AUDIT_FIELDS:
        if field in ("vdd_v", "vcm_v"):
            continue  # compared above, against the pinned netlist
        problem = _cell_problem(field, point.get(field), recomputed[field], "pinned raw curves", 9)
        if problem:
            problems.append(f"{problem} {where}")
    return "; ".join(problems) or None


def _check_offset_magnitude(point: dict, draws) -> str | None:
    signed, _ = parse_decimal(point.get("vos_null_v"))
    magnitude, _ = parse_decimal(point.get("vos_abs_v"))
    if None in (signed, magnitude):
        return "cannot evaluate (missing vos_null_v / vos_abs_v)"
    if magnitude != abs(signed):
        return f"vos_abs_v {magnitude} != |vos_null_v| {abs(signed)}"
    return None


# run_offset_mc.sh serializes every summary statistic with printf %.9g: nine
# significant digits. The audit's tolerance IS that serialization: a committed
# cell must be the recomputed value re-serialized exactly the way the bench
# writes it -- the same nine significant digits. Anything else differs beyond
# its own serialization and is an error naming the point and the offending
# field.


def _check_offset_mc_statistics(point: dict, draws: dict | None) -> str | None:
    """The published MC statistics must follow from the pinned draws population.

    Recomputes the per-point digest exactly as sim/input-offset/run_offset_mc.sh
    computes it -- naive accumulation in draw order, mean = sum/n_pass, sample
    sigma with the N-1 denominator, three-sigma = 3 sigma, min/max over the
    passing draws, worst-case total = |vos_systematic_det_v| + three-sigma --
    and holds each committed cell to the bench's printf %.9g serialization of
    that value (DRAWS_AUDIT_RULE). Non-finite or negative spread magnitudes are
    errors in their own right.
    """
    if draws is None:
        return "cannot evaluate (no draws population available)"
    pid = (point.get("point_id") or "").strip()
    values = draws.get(pid)
    if not values:
        return "cannot evaluate (no passing draws recorded)"
    n = len(values)
    total = 0.0
    for value in values:
        total += value
    mean = total / n
    ssq = 0.0
    for value in values:
        d = value - mean
        ssq += d * d
    sigma = math.sqrt(ssq / (n - 1)) if n > 1 else 0.0
    vmin = vmax = values[0]
    for value in values:
        if value < vmin:
            vmin = value
        if value > vmax:
            vmax = value
    for field, cell, recomputed in (
        ("mean_vos_v", point.get("mean_vos_v"), mean),
        ("sigma_vos_v", point.get("sigma_vos_v"), sigma),
        ("three_sigma_v", point.get("three_sigma_v"), 3.0 * sigma),
        ("min_vos_v", point.get("min_vos_v"), vmin),
        ("max_vos_v", point.get("max_vos_v"), vmax),
    ):
        parsed, _ = parse_decimal(cell)
        if parsed is not None and field in ("sigma_vos_v", "three_sigma_v") and parsed < 0:
            return f"{field} {cell} is negative (a spread magnitude cannot be)"
        problem = _cell_problem(
            field, cell, format(recomputed, ".9g"), "pinned draws", 9, nan_ok=False
        )
        if problem:
            return problem
    det, det_why = parse_decimal(point.get("vos_systematic_det_v"))
    total_cell = point.get("vos_total_wc_det_plus_3sigma_v")
    total_value, total_why = parse_decimal(total_cell)
    if det is None:
        if total_value is not None:
            return (
                f"vos_total_wc_det_plus_3sigma_v {total_cell} must be non-finite like its "
                f"deterministic join ({det_why})"
            )
        return None
    if total_value is None:
        return f"vos_total_wc_det_plus_3sigma_v: {total_why}"
    if total_value < 0:
        return f"vos_total_wc_det_plus_3sigma_v {total_cell} is negative (|systematic| + 3 sigma cannot be)"
    return _cell_problem(
        "vos_total_wc_det_plus_3sigma_v",
        total_cell,
        format(abs(float(det)) + 3.0 * sigma, ".9g"),
        "pinned draws",
        9,
        nan_ok=False,
    )


KLT_VOUT_TOL_V = 1e-5
KLT_IVDD_TOL_A = 1e-8
KLT_VCM_FRAC_TOL = 1e-4
KLT_OFFSET_FRAC_MAX = 0.15
KLT_RAIL_FRAC = 0.02


def _check_open_loop_klt(point: dict, pop: dict | None) -> str | None:
    """The graded cells and the operating-point validity must follow from the
    pinned raw envelopes (KLT_AUDIT_RULE)."""
    if pop is None:
        return "cannot evaluate (no raw klt population available)"
    pid = (point.get("point_id") or "").strip()
    raw = pop["points"].get(pid)
    if raw is None:
        return "cannot evaluate (no pinned raw klt values for this point)"
    problems = []
    pm = 180.0 + math.degrees(raw["phase_rad"])
    want = {"av0_db": raw["av0_db"], "gbw_hz": raw["gbw_hz"], "pm_deg": pm, "iq_a": raw["ivdd"]}
    for field, value in want.items():
        problem = _cell_problem(field, point.get(field), format(value, ".6g"), "pinned klt envelopes", 6, nan_ok=False)
        if problem:
            problems.append(problem)
        meas = (raw["measurement"] or {}).get(field)
        if not isinstance(meas, (int, float)) or not math.isfinite(meas) or abs(meas - value) > 1e-9 * max(1.0, abs(value)):
            problems.append(f"{field}: the measurement document gives {meas!r}, not the envelope-derived {value!r}")
    vdd, vinp, vout = raw["vdd"], raw["vinp"], raw["vout"]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (vdd, vinp)) or vdd <= 0:
        return "; ".join(problems + ["the corner supplies are unreadable"])
    recomputed = {
        "op_vcm_frac": vinp / vdd,
        "op_vout_offset_frac": abs(vout - vdd / 2.0) / vdd,
        "op_vout_rail_frac": vout / vdd,
    }
    for name, value in recomputed.items():
        if abs(raw["reported"][name] - value) > 1e-9:
            problems.append(f"{name}: envelope reports {raw['reported'][name]!r} but the raw supplies/Vout give {value!r}")
    if abs(recomputed["op_vcm_frac"] - 0.5) > KLT_VCM_FRAC_TOL:
        problems.append(f"operating point: Vcm/VDD {recomputed['op_vcm_frac']:.6g} is not 1/2 (within {KLT_VCM_FRAC_TOL:g})")
    if recomputed["op_vout_offset_frac"] > KLT_OFFSET_FRAC_MAX:
        problems.append(f"operating point: |Vout - VDD/2| is {recomputed['op_vout_offset_frac']:.4g} VDD, beyond {KLT_OFFSET_FRAC_MAX}")
    if not (KLT_RAIL_FRAC <= recomputed["op_vout_rail_frac"] <= 1.0 - KLT_RAIL_FRAC):
        problems.append(f"operating point: Vout is {recomputed['op_vout_rail_frac']:.4g} VDD, within {KLT_RAIL_FRAC} of a rail")
    cont = raw["continuity"]
    ck = pop["continuity_record"]
    if cont is None:
        problems.append(f"dc_continuity record {ck} has no row for this point")
    else:
        if (cont.get("op_pass") or "").strip() != "1":
            problems.append(f"dc_continuity record {ck}: op_pass={cont.get('op_pass')!r} (the legacy internal-node check did not pass)")
        for name, col, tol in (("Vout", "vout_dc_v", KLT_VOUT_TOL_V), ("total VDD current", "ivdd_total_a", KLT_IVDD_TOL_A)):
            ref, why = parse_decimal(cont.get(col))
            now = raw["vout"] if col == "vout_dc_v" else raw["ivdd"]
            if ref is None:
                problems.append(f"dc_continuity record {ck}: {col}: {why}")
            elif abs(float(ref) - now) > tol:
                problems.append(f"{name} {now:.9g} differs from the dc_continuity record {ck} ({float(ref):.9g}) by more than {tol:g}")
    return "; ".join(problems) or None


# Each entry: (check(point, draws), needs a validated draws population). A
# draws check runs only where that population loaded cleanly; its load reports
# its own problems (point, line, reason) as record errors.
DEFINITION_CHECKS = {
    "cmrr_linear_3sigma": (_check_cmrr_linear, False),
    "cmrr_mc_statistics": (_check_cmrr_mc_statistics, "samples"),
    "noise_raw_audit": (_check_noise_raw, "noise"),
    "slew_worse_edge": (_check_slew_worse_edge, False),
    "slew_raw_audit": (_check_slew_raw, "slew"),
    "swing_raw_audit": (_check_swing_raw, "swing"),
    "offset_magnitude": (_check_offset_magnitude, False),
    "offset_mc_statistics": (_check_offset_mc_statistics, "draws"),
    "open_loop_klt_audit": (_check_open_loop_klt, "klt"),
}

"""Generic helpers, and the constants more than one sibling module reads.

Split out of generate.py (issue #355). This is a dependency *leaf* of
signoff/characterization/: it imports no sibling, and every other module may
import it. Nothing here knows about records, rows, checks or rendering.

Stdlib only; pure functions.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Each constant in this first group is read from two or more sibling
# modules, so it cannot sit beside its first user the way it did when the
# generator was one file (issue #355): KLT_RAW_KINDS and the three
# *_PIN_KINDS tuples are read by both the selection validators and the
# population loaders, and SELECTION_SCHEMA / ROW_CLASSES / EXTREMA /
# BOUND_OPS / VALID_OPS / NGSPICE_RE are read from the header's old place
# in generate.py, which no sibling may import.
SELECTION_SCHEMA = "sg13g2-opamp/characterization-selection/1"
NGSPICE_RE = re.compile(r"\bngspice-(\d+)\b")
ROW_CLASSES = ("ratified", "superseded", "measured", "pending")
EXTREMA = ("min", "max", "absmax")
BOUND_OPS = (">=", "<=")
VALID_OPS = ("==", ">=", "==col")
NOISE_PIN_KINDS = ("log", "spectrum")
SLEW_PIN_KINDS = ("tran", "netlist")
SWING_PIN_KINDS = ("coarse_csv", "coarse_netlist", "fine_csv", "fine_netlist")
KLT_RAW_KINDS = ("ac", "op", "measurement", "ac_request", "op_request", "bench_body")
KLT_RAW_REQUIRED_KINDS = ("ac", "op", "ac_request", "op_request", "bench_body")
# Issue #501: the slew bench's batch `klt sim` evidence (sim/slew-rate/klt/).
SLEW_KLT_KINDS = ("envelope", "request", "bench_body")
SLEW_KLT_MEASUREMENTS = (
    "t_rise_outer_s", "t_fall_outer_s", "t_rise_inner_s", "t_fall_inner_s",
    "sr_rise_v_per_us", "sr_fall_v_per_us", "sr_rise_inner_v_per_us", "sr_fall_inner_v_per_us",
    "lin_rise_ratio", "lin_fall_ratio", "pre_rise_orel_v", "pre_fall_orel_v",
    "vinn_max_v", "vinn_min_v", "vout_dc_v", "drive_pp_v", "drive_centre_err_v",
    "vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v",
    "op_vout_offset_frac", "op_vout_rail_frac", "op_vd1_rail_frac", "op_vd2_rail_frac", "op_vtail_rail_frac",
)
# The request definitions the offline derivation relies on (the `.meas` text of
# the crossings, the per-edge arithmetic) and the integrity limits the validity
# flags are derived from. The audit refuses a request that differs.
SLEW_KLT_SPICE = {
    "t_rise_outer_s": ".meas tran t_rise_outer_s trig v(orel) val=-0.15 rise=1 td=250n targ v(orel) val=0.15 rise=1 td=250n",
    "t_fall_outer_s": ".meas tran t_fall_outer_s trig v(orel) val=0.15 fall=1 td=500n targ v(orel) val=-0.15 fall=1 td=500n",
    "t_rise_inner_s": ".meas tran t_rise_inner_s trig v(orel) val=-0.075 rise=1 td=250n targ v(orel) val=0.075 rise=1 td=250n",
    "t_fall_inner_s": ".meas tran t_fall_inner_s trig v(orel) val=0.075 fall=1 td=500n targ v(orel) val=-0.075 fall=1 td=500n",
    "sr_rise_v_per_us": ".meas tran sr_rise_v_per_us param='0.3/t_rise_outer_s*1e-6'",
    "sr_fall_v_per_us": ".meas tran sr_fall_v_per_us param='0.3/t_fall_outer_s*1e-6'",
    "sr_rise_inner_v_per_us": ".meas tran sr_rise_inner_v_per_us param='0.15/t_rise_inner_s*1e-6'",
    "sr_fall_inner_v_per_us": ".meas tran sr_fall_inner_v_per_us param='0.15/t_fall_inner_s*1e-6'",
    "lin_rise_ratio": ".meas tran lin_rise_ratio param='sr_rise_inner_v_per_us/sr_rise_v_per_us'",
    "lin_fall_ratio": ".meas tran lin_fall_ratio param='sr_fall_inner_v_per_us/sr_fall_v_per_us'",
    "pre_rise_orel_v": ".meas tran pre_rise_orel_v find v(orel) at=299n",
    "pre_fall_orel_v": ".meas tran pre_fall_orel_v find v(orel) at=549n",
    "vinn_max_v": ".meas tran vinn_max_v max v(inn)",
    "vinn_min_v": ".meas tran vinn_min_v min v(inn)",
    "vout_dc_v": ".meas tran vout_dc_v find v(out) at=0",
    "drive_pp_v": ".meas tran drive_pp_v param='vinn_max_v-vinn_min_v'",
    "drive_centre_err_v": ".meas tran drive_centre_err_v param='abs((vinn_max_v+vinn_min_v)/2-vout_dc_v)'",
    "op_vout_offset_frac": ".meas tran op_vout_offset_frac find v(ofrac) at=0",
    "op_vout_rail_frac": ".meas tran op_vout_rail_frac find v(fout) at=0",
    "op_vd1_rail_frac": ".meas tran op_vd1_rail_frac find v(fd1) at=0",
    "op_vd2_rail_frac": ".meas tran op_vd2_rail_frac find v(fd2) at=0",
    "op_vtail_rail_frac": ".meas tran op_vtail_rail_frac find v(ftail) at=0",
}
# Issue #514: the cmrr-psrr batch evidence (sim/cmrr-psrr/klt/): the CMRR and
# PSRR direct decks' envelopes, requests and bench bodies.
CMRR_PSRR_KLT_KINDS = (
    "cmrr_envelope", "cmrr_request", "cmrr_body",
    "psrr_envelope", "psrr_request", "psrr_body",
)
# deck -> (measurement names, request measurement definitions that must not be edited)
CMRR_PSRR_KLT_DECKS = {
    "cmrr": {
        "names": ("av0_db", "acm0_db", "cmrr_db", "cmrr_plateau_delta_db"),
        "spice": {
            "av0_db": ".meas ac av0_db find vdb(outa) at=0.01",
            "acm0_db": ".meas ac acm0_db find vdb(outb) at=0.01",
        },
        "expr": {
            "cmrr_db": "(vdb(outa) - vdb(outb))[0]",
            "cmrr_plateau_delta_db": "abs((vdb(outa) - vdb(outb))[20] - cmrr_db)",
        },
        "limits": {"cmrr_plateau_delta_db": {"max": 0.05}},
    },
    "psrr": {
        "names": ("av0_db", "avs0_db", "psrr_db", "psrr_plateau_delta_db"),
        "spice": {
            "av0_db": ".meas ac av0_db find vdb(outa) at=0.01",
            "avs0_db": ".meas ac avs0_db find vdb(outb) at=0.01",
        },
        "expr": {
            "psrr_db": "(vdb(outa) - vdb(outb))[0]",
            "psrr_plateau_delta_db": "abs((vdb(outa) - vdb(outb))[20] - psrr_db)",
        },
        # the ratified PSRR bound is the request's own limit on psrr_db
        "limits": {"psrr_db": {"min": 1.87}, "psrr_plateau_delta_db": {"max": 0.05}},
    },
}
CMRR_PSRR_ANALYSIS = {"kind": "ac", "args": "dec 20 10m 1g"}
SLEW_KLT_LIMITS = {
    "lin_rise_ratio": {"min": 0.98, "max": 1.02}, "lin_fall_ratio": {"min": 0.98, "max": 1.02},
    "pre_rise_orel_v": {"max": -0.15}, "pre_fall_orel_v": {"min": 0.15},
    "drive_pp_v": {"min": 0.588, "max": 0.612}, "drive_centre_err_v": {"max": 0.01},
    "op_vout_offset_frac": {"max": 0.15},
    "op_vout_rail_frac": {"min": 0.02, "max": 0.98}, "op_vd1_rail_frac": {"min": 0.02, "max": 0.98},
    "op_vd2_rail_frac": {"min": 0.02, "max": 0.98}, "op_vtail_rail_frac": {"min": 0.02, "max": 0.98},
}
# The input-offset bench's own `klt sim` family (issue #504): the null-sweep
# and closed-loop envelopes, both requests and both circuit bodies.
OFFSET_KLT_RAW_KINDS = ("null", "cl", "null_request", "cl_request", "null_body", "cl_body")


# --------------------------------------------------------------------------
# small helpers


class SelectionError(Exception):
    """The selection file itself is malformed (not an evidence problem)."""


class CollisionError(Exception):
    """A report destination path already exists: the record is refused,
    never replaced (the report store is append-only)."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def fmt(value: Decimal | None) -> str | None:
    """Plain (non-exponent) decimal string, trailing zeros kept as computed."""
    if value is None:
        return None
    if value != 0 and abs(value) < Decimal("1e-6"):
        return format(value.normalize(), "E")  # e.g. a negative control's ~0 sigma
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def parse_decimal(text: str | None) -> tuple[Decimal | None, str | None]:
    """(value, None) for a finite number, (None, why) otherwise."""
    if text is None:
        return None, "empty cell"
    stripped = text.strip()
    if not stripped:
        return None, "empty cell"
    try:
        value = Decimal(stripped)
    except InvalidOperation:
        return None, f"not a number ({stripped!r})"
    if not value.is_finite():
        return None, f"non-finite value ({stripped!r})"
    return value, None


def decimals_of(literal: str) -> int:
    exponent = Decimal(literal).as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def normalized_netlist_hash(path: Path) -> str:
    """Hash of a SPICE netlist with comment (`*`) and blank lines dropped.

    The netlist snapshots each bench committed differ from the current
    design netlist only in header comments/blank lines when the circuit is
    the same, so this is the identity that matters for "same design".
    """
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        lines.append(line.rstrip())
    return sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out

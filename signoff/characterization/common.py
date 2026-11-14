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

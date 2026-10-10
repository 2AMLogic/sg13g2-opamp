"""Shared `klt sim` envelope validation core for the sim/*/klt/compare.py benches.

Stdlib only, offline: reads committed files and runs no simulator. Each bench's
compare.py imports this module (it puts sim/tools on sys.path itself) and keeps
only what is genuinely per bench: its MEASUREMENTS tuple, any extra per-corner
checks, the harness-record loader and the comparison itself.

What lives here (issue #142; previously copy-pasted into each compare.py):

* the ratified 45-point grid (PROCESSES x TEMPERATURES x SUPPLIES) and its key
  helpers expected_keys / make_key / key_str;
* InputError (the "inputs cannot be compared at all" exit-2 condition);
* read_envelope / index_envelope / check_grid -- the envelope gate the bench
  runners (sim/*/klt/run.sh) apply via `compare.py validate` before an envelope
  may enter records/;
* finite / sha256_file.

key_str is shared on purpose: every bench joins its envelope against a harness
CSV whose `point_id` column uses the same `<process>_<T>C_<VDD>V` spelling, so
the per-bench copies were byte-identical and must stay so. A bench whose harness
spelled point ids differently would need its own key_str AND its own
check_grid / index_envelope messages; none does today.

Every message string and the order in which problems are collected are kept
exactly as they were in the per-bench copies: the compare reports and the exit
status they drive are evidence (sim/ is append-only), so this refactor is
byte-neutral by construction and test_klt_envelope.py (beside this file)
pins the strings.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- the grid
# spec/target-spec.md section 1 [DR-1]/[DR-2]: cornerMOSlv.lib's five
# sections x {-40, 27, 125} C x {1.08, 1.20, 1.32} V.
PROCESSES = ("mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs")
TEMPERATURES = (-40, 27, 125)
SUPPLIES = (1.08, 1.20, 1.32)

Key = Tuple[str, int, float]

# Per-corner hook: (key, indexed values, problems) -> None. Appends any
# bench-specific problem for the corner to `problems`; runs after the declared
# measurements are indexed and before the corner is stored.
CornerCheck = Callable[[Key, Dict[str, object], List[str]], None]


def expected_keys() -> List[Key]:
    return [(p, t, v) for p in PROCESSES for t in TEMPERATURES for v in SUPPLIES]


def make_key(process: str, temp, vdd) -> Key:
    return (str(process), int(round(float(temp))), round(float(vdd), 3))


def key_str(k: Key) -> str:
    """The harness's own point_id spelling, e.g. mos_fs_125C_1.08V."""
    return f"{k[0]}_{k[1]}C_{k[2]:.2f}V"


class InputError(Exception):
    """Inputs cannot be compared at all (exit 2)."""


def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------- envelopes
def read_envelope(path: str) -> dict:
    """Parse the envelope JSON; an unreadable file is an InputError."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise InputError(f"{path}: unreadable envelope ({e})")


def check_grid(keys: Iterable[Key], label: str, problems: List[str]) -> None:
    """Append a problem for every ratified point missing from, and every
    non-grid point present in, `keys`."""
    got = set(keys)
    want = set(expected_keys())
    for k in sorted(want - got):
        problems.append(f"{key_str(k)}: missing from {label}")
    for k in sorted(got - want):
        problems.append(f"{key_str(k)}: not a point of the ratified grid")


def index_envelope(env: dict, label: str, measurements: Sequence[str], *,
                   reject_statuses: Sequence[str] = (),
                   corner_check: Optional[CornerCheck] = None) -> Dict[Key, Dict[str, object]]:
    """Validate a `klt sim` envelope and index its corners by grid key.

    Every corner must sit on the ratified grid exactly once with Vcm = VDD/2, a
    pass/fail status, and each name in `measurements` reported once with a
    finite value. `reject_statuses`: measurement statuses that make the value
    unusable regardless of its number (checked before finiteness).
    `corner_check`: optional per-bench hook, see CornerCheck.

    Returns {key: {name: value, name + "__status": status}}; raises InputError
    naming every problem found.
    """
    if not isinstance(env, dict):
        raise InputError(f"{label}: not a JSON object")
    if "error" in env:
        raise InputError(f"{label}: klt error envelope: {env['error']}")
    corners = env.get("corners")
    if not isinstance(corners, list):
        raise InputError(f"{label}: no corners[] array")
    if env.get("corner_count") != len(corners):
        raise InputError(f"{label}: corner_count {env.get('corner_count')} != len(corners) {len(corners)}")
    cov = env.get("coverage")
    if not isinstance(cov, dict):
        raise InputError(f"{label}: no coverage block")
    if cov.get("nothing_checked") is not False:
        raise InputError(f"{label}: coverage.nothing_checked is {cov.get('nothing_checked')!r}, expected false")
    if cov.get("skipped"):
        raise InputError(f"{label}: coverage.skipped is non-empty ({len(cov['skipped'])} item(s)), e.g. {cov['skipped'][0]}")
    if env.get("status") not in ("pass", "fail"):
        raise InputError(f"{label}: aggregate status {env.get('status')!r} -- only a complete pass/fail run is evidence")

    out: Dict[Key, Dict[str, object]] = {}
    problems: List[str] = []
    for c in corners:
        cid = c.get("corner_id")
        supply = c.get("supply_v") or {}
        if "vdd" not in supply or "vinp" not in supply or c.get("process") is None:
            problems.append(f"{cid}: missing process or supply_v.vdd/vinp")
            continue
        k = make_key(c["process"], c.get("temperature_c"), supply["vdd"])
        if k in out:
            problems.append(f"{key_str(k)}: duplicate corner")
            continue
        if not math.isclose(float(supply["vinp"]), float(supply["vdd"]) / 2, rel_tol=0, abs_tol=1e-9):
            problems.append(f"{key_str(k)}: vinp {supply['vinp']} != vdd/2 ({supply['vdd']}/2)")
        if c.get("status") not in ("pass", "fail"):
            problems.append(f"{key_str(k)}: corner status {c.get('status')!r}")
        vals: Dict[str, object] = {}
        by_name: Dict[object, dict] = {}
        for m in c.get("measurements") or []:
            if m.get("name") in by_name:
                problems.append(f"{key_str(k)}: measurement {m.get('name')} reported twice")
            by_name[m.get("name")] = m
        for n in measurements:
            m = by_name.get(n)
            if m is None:
                problems.append(f"{key_str(k)}: measurement {n} missing")
                continue
            if m.get("status") in reject_statuses:
                problems.append(f"{key_str(k)}: measurement {n} status {m.get('status')!r}")
                continue
            if not finite(m.get("value")):
                problems.append(f"{key_str(k)}: measurement {n} value {m.get('value')!r} is missing or non-finite")
                continue
            vals[n] = float(m["value"])
            vals[n + "__status"] = m.get("status")
        if corner_check is not None:
            corner_check(k, vals, problems)
        out[k] = vals
    check_grid(out.keys(), label, problems)
    if problems:
        raise InputError(f"{label}: " + "; ".join(problems))
    return out

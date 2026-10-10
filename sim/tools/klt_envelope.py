"""Shared `klt sim` envelope validation core for the sim/*/klt/compare.py benches.

Stdlib only, offline: reads committed files and runs no simulator. Each bench's
compare.py imports this module (it puts sim/tools on sys.path itself) and keeps
only what is genuinely per bench: its MEASUREMENTS tuple, any extra per-corner
checks, its harness column tuple and the comparison itself. The harness CSV
loader is shared too (load_harness_csv_rows, issue #181).

What lives here (issue #142; previously copy-pasted into each compare.py):

* the ratified 45-point grid (PROCESSES x TEMPERATURES x SUPPLIES) and its key
  helpers expected_keys / make_key / key_str;
* InputError (the "inputs cannot be compared at all" exit-2 condition);
* read_envelope / index_envelope / check_grid -- the envelope gate the bench
  runners (sim/*/klt/run.sh) apply via `compare.py validate` before an envelope
  may enter records/;
* finite / sha256_file;
* the CLI scaffold above them (issue #146): tol / load_envelope / summary_tail /
  run_cli -- the validate subcommand, --json-out, --provenance KEY=VALUE, the
  InputError -> stderr -> exit 2 path, the inputs sha256 stanza and the
  exit-0-iff-agree rule.

The output-swing bench (issue #176) needs a selectable point set, a `vcm`
supply key and extra envelope- and measurement-level rules; those are the
points= / supply_key= / accept_statuses= parameters, the envelope_check and
measurement_check hooks and run_cli's common_args / validate_noun. Their
defaults reproduce the behaviour every other bench already relied on.

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

import argparse
import csv
import hashlib
import json
import math
import sys
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

# Envelope-level hook: (env, label, problems) -> None. Runs once, after the
# aggregate checks and before the corners are walked; may raise InputError
# (stop at once) or append problems (collected with the per-corner ones).
EnvelopeCheck = Callable[[dict, str, List[str]], None]

# Per-measurement hook: (key, name, measurement dict, finite value, problems)
# -> keep. Runs after the status and finiteness checks on each declared
# measurement; returning False drops the value (the hook appended why).
MeasurementCheck = Callable[[Key, str, dict, float, List[str]], bool]


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


def check_grid(keys: Iterable[Key], label: str, problems: List[str],
               points: Optional[Iterable[Key]] = None) -> None:
    """Append a problem for every expected point missing from, and every
    unexpected point present in, `keys`. Expected is the ratified grid, or the
    caller's requested point set `points` when given."""
    got = set(keys)
    want = set(expected_keys() if points is None else points)
    extra = "not a point of the ratified grid" if points is None else \
        "unexpected point (not in the requested point set)"
    for k in sorted(want - got):
        problems.append(f"{key_str(k)}: missing from {label}")
    for k in sorted(got - want):
        problems.append(f"{key_str(k)}: {extra}")


def index_envelope(env: dict, label: str, measurements: Sequence[str], *,
                   reject_statuses: Sequence[str] = (),
                   accept_statuses: Optional[Sequence[str]] = None,
                   supply_key: str = "vinp",
                   points: Optional[Sequence[Key]] = None,
                   envelope_check: Optional[EnvelopeCheck] = None,
                   corner_check: Optional[CornerCheck] = None,
                   measurement_check: Optional[MeasurementCheck] = None) -> Dict[Key, Dict[str, object]]:
    """Validate a `klt sim` envelope and index its corners by grid key.

    Every corner must sit on the ratified grid exactly once with Vcm = VDD/2, a
    pass/fail status, and each name in `measurements` reported once with a
    finite value. `reject_statuses`: measurement statuses that make the value
    unusable regardless of its number (checked before finiteness);
    `accept_statuses`, when given, rejects every other status the same way.
    `supply_key`: the supply_v entry that carries Vcm ("vinp" or "vcm").
    `points`: the exact key set required instead of the ratified grid (see
    check_grid). Hooks: envelope_check, corner_check, measurement_check (see
    EnvelopeCheck / CornerCheck / MeasurementCheck).

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

    problems: List[str] = []
    if envelope_check is not None:
        envelope_check(env, label, problems)
    out: Dict[Key, Dict[str, object]] = {}
    for c in corners:
        cid = c.get("corner_id")
        supply = c.get("supply_v") or {}
        if "vdd" not in supply or supply_key not in supply or c.get("process") is None:
            problems.append(f"{cid}: missing process or supply_v.vdd/{supply_key}")
            continue
        k = make_key(c["process"], c.get("temperature_c"), supply["vdd"])
        if k in out:
            problems.append(f"{key_str(k)}: duplicate corner")
            continue
        if not math.isclose(float(supply[supply_key]), float(supply["vdd"]) / 2, rel_tol=0, abs_tol=1e-9):
            problems.append(f"{key_str(k)}: {supply_key} {supply[supply_key]} != vdd/2 ({supply['vdd']}/2)")
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
            status = m.get("status")
            if status in reject_statuses or (accept_statuses is not None and status not in accept_statuses):
                problems.append(f"{key_str(k)}: measurement {n} status {m.get('status')!r}")
                continue
            if not finite(m.get("value")):
                problems.append(f"{key_str(k)}: measurement {n} value {m.get('value')!r} is missing or non-finite")
                continue
            v = float(m["value"])
            if measurement_check is not None and not measurement_check(k, n, m, v, problems):
                continue
            vals[n] = v
            vals[n + "__status"] = status
        if corner_check is not None:
            corner_check(k, vals, problems)
        out[k] = vals
    check_grid(out.keys(), label, problems, points)
    if problems:
        raise InputError(f"{label}: " + "; ".join(problems))
    return out


# ------------------------------------------------------------- harness CSV
def load_harness_csv_rows(path: str, columns: Iterable[str], label: str, *,
                          points: Optional[Sequence[Key]] = None,
                          flag_columns: Iterable[str] = ()) -> Dict[Key, Dict[str, object]]:
    """Read a harness record CSV (issue #181; previously four per-bench loaders).

    Every row is keyed by its corner/temp_c/vdd_v columns (a malformed or short
    row is a problem, not a traceback), must be unique, must carry the
    `point_id` that key_str spells for that key, and must hold every name in
    `columns` as a finite float. `flag_columns` are read as booleans (cell
    "1"). The key set must be the ratified grid, or `points` when given: for a
    `points` set other than the full grid the rows outside it are parsed and
    checked like any other but then ignored (they are not under comparison).
    `label` names the file in messages. Any problem raises InputError naming
    all of them.
    """
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        raise InputError(f"{path}: unreadable {label} ({e})")
    columns = tuple(columns)
    flag_columns = tuple(flag_columns)
    problems: List[str] = []
    out: Dict[Key, Dict[str, object]] = {}
    for r in rows:
        try:
            k = make_key(r["corner"], r["temp_c"], r["vdd_v"])
        except (KeyError, TypeError, ValueError, OverflowError):
            problems.append(f"unparsable row {r!r}")
            continue
        if k in out:
            problems.append(f"{key_str(k)}: duplicate row")
            continue
        if r.get("point_id") != key_str(k):
            problems.append(f"{r.get('point_id')}: point_id disagrees with its corner/temp/vdd columns")
        row: Dict[str, object] = {}
        for col in columns:
            raw = r.get(col)
            try:
                v = float(raw)
            except (TypeError, ValueError):
                v = float("nan")
            if not math.isfinite(v):
                problems.append(f"{key_str(k)}: {label} {col} {raw!r} is missing or non-finite")
                continue
            row[col] = v
        for col in flag_columns:
            row[col] = str(r.get(col)).strip() == "1"
        out[k] = row
    full = set(expected_keys())
    if points is not None and set(points) != full:
        out = {k: v for k, v in out.items() if k in set(points)}
        check_grid(out.keys(), label, problems, points)
    else:
        check_grid(out.keys(), label, problems)
    if problems:
        raise InputError(f"{path}: " + "; ".join(problems))
    return out


# ------------------------------------------------------------ CLI scaffold
def tol(table: Dict[str, Dict[str, float]], metric: str, ref: float) -> float:
    """Absolute + relative tolerance for `metric` at reference value `ref`."""
    t = table[metric]
    return t["abs"] + t["rel"] * abs(ref)


def load_envelope(path: str, index_fn: Callable[..., dict], **kw) -> Tuple[dict, dict]:
    """Read the `klt sim` envelope and index its corners with the bench's gate
    (`kw` is passed through to it)."""
    env = read_envelope(path)
    return env, index_fn(env, path, **kw)


def summary_tail(lines: List[str], rep: dict) -> List[str]:
    """Append the OUT OF TOLERANCE / VERDICT DISAGREES lines every bench's
    _text_summary ends with; returns `lines`."""
    for line in rep["out_of_tolerance"]:
        lines.append(f"  OUT OF TOLERANCE: {line}")
    for d in rep["bound_verdict_disagreements"]:
        lines.append(f"  VERDICT DISAGREES: {d}")
    return lines


def run_cli(argv: Optional[List[str]], *, description: str, compare_help: str,
            harness_args: Sequence[Tuple[str, dict]],
            index_fn: Callable[[dict, str], dict],
            run: Callable[[argparse.Namespace, dict, dict], dict],
            inputs: Sequence[Tuple[str, str, bool]],
            summary: Callable[[dict], str],
            common_args: Sequence[Tuple[str, dict]] = (),
            validate_noun: str = "corners") -> int:
    """The compare.py command line shared by every bench.

    harness_args: (flag, add_argument kwargs) for the bench's harness files, added
        between --envelope and --json-out.
    index_fn(env, label): the bench's envelope gate.
    run(args, tool, env) -> report: loads the harness files named by `args` and
        compares; may raise InputError (exit 2).
    inputs: (report key, argparse dest, hash it) for each harness file; the
        envelope is always first and always hashed.
    summary(report) -> the stdout text.
    common_args: (flag, add_argument kwargs) added to BOTH subcommands; each
        parsed value is also passed to index_fn as a keyword argument named by
        its argparse dest.
    validate_noun: the word after the corner count in the validate line.
    Exit 0 iff the report's status is "agree", 1 otherwise, 2 on InputError.
    """
    ap = argparse.ArgumentParser(description=description)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="gate the envelope before it may enter records/")
    v.add_argument("envelope")
    dests = [v.add_argument(flag, **kw).dest for flag, kw in common_args]
    c = sub.add_parser("compare", help=compare_help)
    c.add_argument("--envelope", required=True)
    for flag, kw in harness_args:
        c.add_argument(flag, **kw)
    for flag, kw in common_args:
        c.add_argument(flag, **kw)
    c.add_argument("--json-out")
    c.add_argument("--provenance", action="append", default=[], metavar="KEY=VALUE")
    a = ap.parse_args(argv)
    index_kw = {d: getattr(a, d) for d in dests}

    try:
        if a.cmd == "validate":
            env, idx = load_envelope(a.envelope, index_fn, **index_kw)
            print(f"validate: {a.envelope}: {len(idx)} {validate_noun}, status {env.get('status')}, ok")
            return 0
        env, tool_idx = load_envelope(a.envelope, index_fn, **index_kw)
        rep = run(a, tool_idx, env)
    except InputError as e:
        print(f"compare.py: {e}", file=sys.stderr)
        return 2

    stanza = {"envelope": {"path": a.envelope, "sha256": sha256_file(a.envelope)}}
    for key, dest, hashed in inputs:
        path = getattr(a, dest)
        stanza[key] = {"path": path, "sha256": sha256_file(path)} if hashed else {"path": path}
    rep["inputs"] = stanza
    rep["provenance"] = dict(kv.split("=", 1) for kv in a.provenance)
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(rep, f, indent=2)
            f.write("\n")
    print(summary(rep))
    return 0 if rep["status"] == "agree" else 1

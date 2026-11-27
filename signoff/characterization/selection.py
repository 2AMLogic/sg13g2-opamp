"""The record selection file: load it, and validate every pin's shape.

Split out of generate.py (issue #355). `load_selection` is the single reader
of `signoff/characterization/selection.json`; the `_validate_*_selection`
family holds each raw-artifact pin to its bench's measurement configuration.

Depends on `common`, `paths` and `defchecks`. `_validate_klt_raw_selection`
sat inside the definition-checks banner in the single-file version but belongs
to this family.

Stdlib only; pure validation -- it reads no evidence.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path

from common import (
    BOUND_OPS,
    EXTREMA,
    KLT_RAW_KINDS,
    KLT_RAW_REQUIRED_KINDS,
    NOISE_PIN_KINDS,
    OFFSET_KLT_RAW_KINDS,
    ROW_CLASSES,
    SELECTION_SCHEMA,
    SLEW_KLT_KINDS,
    SLEW_PIN_KINDS,
    SWING_PIN_KINDS,
    SWING_TWO_PASS_KINDS,
    VALID_OPS,
    SelectionError,
    _no_duplicate_keys,
)
from defchecks import DEFINITION_CHECKS
from paths import noise_post, slew_post, swing_post


def load_selection(path: Path) -> dict:
    try:
        selection = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except OSError as exc:
        raise SelectionError(f"cannot read selection {path}: {exc}") from exc
    except ValueError as exc:
        raise SelectionError(f"selection {path} is not valid JSON: {exc}") from exc
    if not isinstance(selection, dict) or selection.get("schema") != SELECTION_SCHEMA:
        raise SelectionError(f"selection {path}: `schema` must be {SELECTION_SCHEMA!r}")
    for key in ("block", "spec", "inventory", "pdk_pin", "design_netlist"):
        if not isinstance(selection.get(key), str):
            raise SelectionError(f"selection: `{key}` must be a string")
    for key in ("grids", "records"):
        if not isinstance(selection.get(key), dict):
            raise SelectionError(f"selection: `{key}` must be an object")
    if not isinstance(selection.get("rows"), list) or not selection["rows"]:
        raise SelectionError("selection: `rows` must be a non-empty list")
    seen = set()
    for row in selection["rows"]:
        rid = row.get("id")
        if not isinstance(rid, str) or rid in seen:
            raise SelectionError(f"selection: row id {rid!r} missing or duplicated")
        seen.add(rid)
        if row.get("class") not in ROW_CLASSES:
            raise SelectionError(f"selection: row {rid}: `class` must be one of {ROW_CLASSES}")
        if row["class"] == "pending":
            continue
        if "load" in row:
            raise SelectionError(f"selection: row {rid}: free-text `load` is gone; use a structured `load_condition`")
        if not isinstance(row.get("load_condition"), dict):
            raise SelectionError(f"selection: row {rid}: needs a `load_condition` object")
        if row.get("record") not in selection["records"]:
            raise SelectionError(f"selection: row {rid} names unknown record {row.get('record')!r}")
        if row.get("extremum") not in EXTREMA:
            raise SelectionError(f"selection: row {rid}: `extremum` must be one of {EXTREMA}")
        try:
            Decimal(row.get("scale", ""))
        except InvalidOperation as exc:
            raise SelectionError(f"selection: row {rid}: bad `scale`") from exc
        bound = row.get("bound")
        if row["class"] in ("ratified", "superseded"):
            if not isinstance(bound, dict) or bound.get("op") not in BOUND_OPS:
                raise SelectionError(f"selection: row {rid}: a {row['class']} row needs a bound")
            try:
                Decimal(bound.get("value", ""))
            except InvalidOperation as exc:
                raise SelectionError(f"selection: row {rid}: bound value is not a number") from exc
        elif bound is not None:
            raise SelectionError(f"selection: row {rid}: a measured (unratified) row carries no bound")
    for key, rec in selection["records"].items():
        if rec.get("grid") not in selection["grids"]:
            raise SelectionError(f"selection: record {key} names unknown grid {rec.get('grid')!r}")
        for cond in rec.get("valid_when", []):
            if not (isinstance(cond, list) and len(cond) == 3 and cond[1] in VALID_OPS):
                raise SelectionError(f"selection: record {key}: bad valid_when entry {cond!r}")
        if ("env_sidecar" in rec) != ("env_sidecar_sha256" in rec):
            raise SelectionError(f"selection: record {key}: `env_sidecar` and `env_sidecar_sha256` go together")
        if "draws_csv_sha256" in rec and "draws_csv" not in rec:
            POPULATION_VALIDATORS["draws_csv"](key, None, rec, selection["records"])
        for population, validate in POPULATION_VALIDATORS.items():
            if population in rec:
                validate(key, rec[population], rec, selection["records"])
        for population, audit in POPULATION_AUDITS.items():
            if population in rec and audit not in rec.get("definition_checks", []):
                raise SelectionError(
                    f"selection: record {key}: `{population}` is named, so the definition check "
                    f"{audit!r} must run (raw evidence is never pinned and then ignored)"
                )
        for name in rec.get("definition_checks", []):
            if name not in DEFINITION_CHECKS:
                raise SelectionError(f"selection: record {key}: unknown definition check {name!r}")
            need = DEFINITION_CHECKS[name][1]
            if need == "slew" and rec.get("slew_raw") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies raw "
                    "transient waveforms; name hash-pinned `slew_raw` beside the summary"
                )
            if need == "slew_klt" and rec.get("slew_klt") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies the batch "
                    "`klt sim` slew envelope; name hash-pinned `slew_klt` beside the summary"
                )
            if need == "draws" and rec.get("draws_csv") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies a raw "
                    "draws population; name a hash-pinned `draws_csv` beside the summary"
                )
            if need == "samples" and rec.get("mc_samples") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies raw "
                    "CMRR samples; name hash-pinned `mc_samples` beside the summary"
                )
            if need == "noise" and rec.get("noise_raw") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies raw "
                    "noise artifacts; name hash-pinned `noise_raw` beside the summary"
                )
            if need == "klt" and rec.get("klt_raw") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies the raw "
                    "`klt sim` envelopes; name hash-pinned `klt_raw` beside the summary"
                )
            if need == "offset_klt" and rec.get("offset_klt_raw") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies the raw "
                    "input-offset `klt sim` envelopes; name hash-pinned `offset_klt_raw` "
                    "beside the summary"
                )
            if need == "swing" and rec.get("swing_raw") is None and rec.get("swing_two_pass") is None:
                raise SelectionError(
                    f"selection: record {key}: definition check {name!r} verifies raw "
                    "DC curves; name hash-pinned `swing_raw` (or batch `swing_two_pass`) beside the summary"
                )
    return selection


def _validate_draws_csv_selection(key: str, dc, rec: dict, _records: dict) -> None:
    """Shape of a record's `draws_csv` pin: a path string paired with
    `draws_csv_sha256`."""
    if ("draws_csv" in rec) != ("draws_csv_sha256" in rec):
        raise SelectionError(
            f"selection: record {key}: `draws_csv` and `draws_csv_sha256` go "
            "together; a draws population is named only with its hash pin"
        )
    if not isinstance(dc, str):
        raise SelectionError(f"selection: record {key}: `draws_csv` must be a path string")


MC_ACCEPTANCE_KEYS = ("op_rail_frac", "op_mid_frac", "plateau_tol_db")


def _validate_mc_samples_selection(key: str, ms, _rec: dict, records: dict) -> None:
    """Shape of a record's `mc_samples` pin (a pinned LIST of raw sample files,
    not the offset-specific draws CSV contract)."""
    where = f"selection: record {key}: `mc_samples`"
    if not isinstance(ms, dict):
        raise SelectionError(f"{where} must be an object")
    if ms.get("av0_join") not in records:
        raise SelectionError(f"{where}.av0_join must name a selected record")
    acc = ms.get("acceptance")
    if not isinstance(acc, dict) or sorted(acc) != sorted(MC_ACCEPTANCE_KEYS):
        raise SelectionError(f"{where}.acceptance must have exactly {list(MC_ACCEPTANCE_KEYS)}")
    for name, text in acc.items():
        try:
            if not math.isfinite(float(text)) or float(text) < 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise SelectionError(f"{where}.acceptance.{name} must be a non-negative number string") from exc
    files = ms.get("files")
    if not isinstance(files, dict) or not files:
        raise SelectionError(f"{where}.files must be a non-empty object of point_id -> pinned file")
    for pid, entry in files.items():
        if not (isinstance(entry, dict) and isinstance(entry.get("path"), str)
                and isinstance(entry.get("sha256"), str)):
            raise SelectionError(f"{where}.files[{pid!r}] needs string `path` and `sha256` (a sample file is never named without its pin)")


def _validate_raw_pins(where: str, files, kinds: tuple, shape: str) -> None:
    """Shape of a `*_raw` record's `files`: a non-empty object of point_id ->
    exactly `kinds`, each a pin with a string `path` and `sha256`. `shape` is
    the family's rendering of the entry in the "non-empty object" message."""
    if not isinstance(files, dict) or not files:
        raise SelectionError(f"{where}.files must be a non-empty object of point_id -> {shape}")
    for pid, entry in files.items():
        if not isinstance(entry, dict) or sorted(entry) != sorted(kinds):
            raise SelectionError(f"{where}.files[{pid!r}] needs exactly {list(kinds)}")
        for kind in kinds:
            pin = entry[kind]
            if not (isinstance(pin, dict) and isinstance(pin.get("path"), str) and isinstance(pin.get("sha256"), str)):
                raise SelectionError(
                    f"{where}.files[{pid!r}].{kind} needs string `path` and `sha256` "
                    "(a raw artifact is never named without its pin)"
                )


def _validate_noise_raw_selection(key: str, nr, _rec: dict, _records: dict) -> None:
    """Shape of a record's `noise_raw` pin: per point, one pinned log and one
    pinned in-band spectrum, plus the documented measurement band."""
    where = f"selection: record {key}: `noise_raw`"
    if not isinstance(nr, dict):
        raise SelectionError(f"{where} must be an object")
    band = nr.get("band")
    want = {
        "lo_hz": format(noise_post.BAND_LO_HZ, "g"),
        "hi_hz": format(noise_post.BAND_HI_HZ, "g"),
        "points": noise_post.N_POINTS,
        "points_per_decade": noise_post.POINTS_PER_DECADE,
    }
    if band != want:
        raise SelectionError(f"{where}.band must be exactly {want} (the documented band the shared post-processing enforces)")
    _validate_raw_pins(where, nr.get("files"), NOISE_PIN_KINDS, f"{{log, spectrum}}")


def _validate_slew_raw_selection(key: str, sr, _rec: dict, _records: dict) -> None:
    """Shape of a record's `slew_raw` pin: the measurement configuration, plus
    per point one pinned transient waveform and one pinned rendered netlist."""
    where = f"selection: record {key}: `slew_raw`"
    if not isinstance(sr, dict):
        raise SelectionError(f"{where} must be an object")
    if sr.get("config") != slew_post.CONFIG:
        raise SelectionError(
            f"{where}.config must be exactly {slew_post.CONFIG} (the measurement configuration of "
            "sim/slew-rate/run_slew_sweep.sh that the shared post-processing is defined for)"
        )
    _validate_raw_pins(where, sr.get("files"), SLEW_PIN_KINDS, f"{{tran, netlist}}")


def _validate_slew_klt_selection(key: str, sk, _rec: dict, _records: dict) -> None:
    """Shape of a record's `slew_klt` pin: the batch envelope, the request it
    ran and the bench body, each with its sha256 (issue #501)."""
    where = f"selection: record {key}: `slew_klt`"
    if not isinstance(sk, dict) or sorted(sk) != ["files"]:
        raise SelectionError(f"{where} must be an object with exactly `files`")
    files = sk["files"]
    if not isinstance(files, dict) or sorted(files) != sorted(SLEW_KLT_KINDS):
        raise SelectionError(f"{where}.files must have exactly {list(SLEW_KLT_KINDS)}")
    for kind, pin in files.items():
        if not (isinstance(pin, dict) and isinstance(pin.get("path"), str) and isinstance(pin.get("sha256"), str)):
            raise SelectionError(f"{where}.files.{kind} needs string `path` and `sha256` (a raw artifact is never named without its pin)")


def _validate_swing_raw_selection(key: str, sw, _rec: dict, _records: dict) -> None:
    """Shape of a record's `swing_raw` pin: the measurement configuration, plus
    per point one pinned coarse and one fine transfer curve and their rendered
    netlists."""
    where = f"selection: record {key}: `swing_raw`"
    if not isinstance(sw, dict):
        raise SelectionError(f"{where} must be an object")
    if sw.get("config") != swing_post.CONFIG:
        raise SelectionError(
            f"{where}.config must be exactly {swing_post.CONFIG} (the measurement configuration of "
            "sim/output-swing/run_swing_sweep.sh that the shared post-processing is defined for)"
        )
    _validate_raw_pins(where, sw.get("files"), SWING_PIN_KINDS, f"{list(SWING_PIN_KINDS)}")


def _validate_swing_two_pass_selection(key: str, sw, rec: dict, _records: dict) -> None:
    """Shape of a record's `swing_two_pass` pin (issue #503): per point one
    hash-pinned coarse and one hash-pinned fine pass-evidence JSON (see
    sim/output-swing/klt/two_pass.py for the pass schema)."""
    where = f"selection: record {key}: `swing_two_pass`"
    if not isinstance(sw, dict) or sorted(sw) != ["files"]:
        raise SelectionError(f"{where} must be an object with exactly `files`")
    _validate_raw_pins(where, sw.get("files"), SWING_TWO_PASS_KINDS, f"{list(SWING_TWO_PASS_KINDS)}")
    if "swing_raw" in rec:
        raise SelectionError(
            f"selection: record {key}: `swing_raw` and `swing_two_pass` are alternative "
            "evidence for the same summary; name exactly one")


def _validate_klt_raw_selection(key: str, kr, _rec: dict, records: dict) -> None:
    """Shape of a record's `klt_raw` pin: pinned AC/OP envelopes, requests and
    bench body (plus optional `measurement`, and optional `dc_continuity` when
    comparing two configurations or standing in for a legacy port-only run)."""
    where = f"selection: record {key}: `klt_raw`"
    if not isinstance(kr, dict) or "files" not in kr or set(kr) - {"files", "dc_continuity"}:
        raise SelectionError(f"{where} must be an object with `files` and optional `dc_continuity`")
    if "dc_continuity" in kr and (kr["dc_continuity"] not in records or kr["dc_continuity"] == key):
        raise SelectionError(f"{where}.dc_continuity must name another selected record")
    files = kr["files"]
    required = set(KLT_RAW_REQUIRED_KINDS)
    if not isinstance(files, dict) or not required.issubset(files) or set(files) - set(KLT_RAW_KINDS):
        raise SelectionError(f"{where}.files must have {sorted(required)} (within {list(KLT_RAW_KINDS)})")
    for kind, pin in files.items():
        if not (isinstance(pin, dict) and isinstance(pin.get("path"), str) and isinstance(pin.get("sha256"), str)):
            raise SelectionError(f"{where}.files.{kind} needs string `path` and `sha256` (a raw artifact is never named without its pin)")


def _validate_offset_klt_raw_selection(key: str, kr, _rec: dict, records: dict) -> None:
    """Shape of a record's `offset_klt_raw` pin (issue #504): one pinned file
    per kind (both envelopes, both requests, both circuit bodies), plus the
    selected same-DUT open-loop record the closed-loop referral joins Av0
    from."""
    where = f"selection: record {key}: `offset_klt_raw`"
    if not isinstance(kr, dict) or sorted(kr) != ["av0_join", "files"]:
        raise SelectionError(f"{where} must be an object with exactly `files` and `av0_join`")
    if kr["av0_join"] not in records or kr["av0_join"] == key:
        raise SelectionError(f"{where}.av0_join must name another selected record")
    files = kr["files"]
    if not isinstance(files, dict) or sorted(files) != sorted(OFFSET_KLT_RAW_KINDS):
        raise SelectionError(f"{where}.files must have exactly {list(OFFSET_KLT_RAW_KINDS)}")
    for kind, pin in files.items():
        if not (isinstance(pin, dict) and isinstance(pin.get("path"), str) and isinstance(pin.get("sha256"), str)):
            raise SelectionError(f"{where}.files.{kind} needs string `path` and `sha256` (a raw artifact is never named without its pin)")


# population key -> shape validator dispatched by `load_selection`. Every key
# admitted here must also be mapped in `POPULATION_AUDITS` so raw evidence is
# never pinned and then ignored.
POPULATION_VALIDATORS = {
    "draws_csv": _validate_draws_csv_selection,
    "mc_samples": _validate_mc_samples_selection,
    "noise_raw": _validate_noise_raw_selection,
    "slew_raw": _validate_slew_raw_selection,
    "swing_raw": _validate_swing_raw_selection,
    "swing_two_pass": _validate_swing_two_pass_selection,
    "slew_klt": _validate_slew_klt_selection,
    "klt_raw": _validate_klt_raw_selection,
    "offset_klt_raw": _validate_offset_klt_raw_selection,
}

# population key -> the definition check that audits it. A record that pins a
# population must run its audit (raw evidence is never pinned and then
# ignored); the reverse direction is the `need` tag in DEFINITION_CHECKS.
POPULATION_AUDITS = {
    "slew_raw": "slew_raw_audit",
    "noise_raw": "noise_raw_audit",
    "swing_raw": "swing_raw_audit",
    "swing_two_pass": "swing_raw_audit",
    "mc_samples": "cmrr_mc_statistics",
    "draws_csv": "offset_mc_statistics",
    "slew_klt": "slew_klt_audit",
    "klt_raw": "open_loop_klt_audit",
    "offset_klt_raw": "offset_klt_audit",
}

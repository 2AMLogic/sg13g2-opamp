#!/usr/bin/env python3
"""Per-spec-row characterization report from committed evidence (T1 item 8).

Reads the explicit record selection in `selection.json` (beside this file),
the committed `sim/*/records/*.csv` (+ `.md`) records it names, the ratified
spec text and the item 9 testbench inventory, and renders one aggregated
report: for every claimed row, its units, load and conditions, ratified bound
and decision record, measured extremum and binding point, source record and
hash, expected-versus-observed grid coverage, and verdict.

Stdlib only. Needs no ngspice, no PDK and no network: it re-reads committed
evidence, it never re-simulates. (Re-running the simulations is a different,
much more expensive operation -- each bench's README, "Cold-start
invocation", and signoff/evidence/testbenches.txt.)

  python3 signoff/characterization/generate.py            # print the report, write nothing
  python3 signoff/characterization/generate.py --format json
  python3 signoff/characterization/generate.py --mint     # append a new record under reports/
  python3 signoff/characterization/generate.py --check    # newest committed record reproduces

Exit codes: 0 report rendered, overall PASS (or --check/--mint succeeded);
3 report rendered but overall FAIL or INCOMPLETE (mirrors `klt signoff`);
1 the selected evidence is in error (or --check/--mint failed); 2 usage.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

# The generator is an eight-module package under signoff/characterization/
# (issue #355); this file is its CLI entrypoint. `paths` comes first: importing
# it IS what puts the six shared bench modules on sys.path for every sibling
# below. HERE/DEFAULT_REPO_ROOT are defined there too, so the repo-root
# derivation lives in exactly one place.
from paths import DEFAULT_REPO_ROOT, HERE  # noqa: F401
from common import (
    CollisionError,
    SelectionError,
    canonical_json,
    normalized_netlist_hash,
    sha256_bytes,
    sha256_file,
)
from records import PROV_ERROR, PROV_LEGACY, PROV_VERIFIED, load_record
from render import render_markdown
from rows import evaluate_row, parse_inventory
from selection import load_selection

# Imported SOLELY to re-export, for signoff/characterization/test_generate.py:
# it reaches for the generator's public surface as `generate.<name>`, and the
# split leaves it unmodified so it stays the refactor's regression witness.
# That surface is 22 names -- these six, plus four more the imports above
# already bring in because this file uses them too (SelectionError,
# canonical_json, sha256_file, render_markdown), plus the twelve defined here
# (SELECTION_REL, REPORTS_REL, ENVELOPE_REL, GENERATOR_REL, MINT_LOCK_NAME,
# build_content, make_report, latest_report, mint, check, _link_no_clobber,
# _replace_text_atomically).
#
# Note a re-export is NOT a usable mock.patch.object target: patching
# `generate.X` rebinds this module's name only, so a caller living in a
# sibling that holds its own `from ... import X` binding would not see it.
# The four names test_generate.py patches (_dt, git_head, _link_no_clobber,
# _replace_text_atomically) and every caller of them stay in this file.
from common import KLT_RAW_KINDS  # noqa: F401
from defchecks import (  # noqa: F401
    _cell_problem,
    _check_cmrr_linear,
    _check_slew_worse_edge,
)
from records import read_csv_rows  # noqa: F401
from rows import parse_bound_clause  # noqa: F401

SELECTION_REL = "signoff/characterization/selection.json"
REPORTS_REL = "signoff/characterization/reports"
ENVELOPE_REL = "signoff/evidence/characterization.json"
GENERATOR_REL = "signoff/characterization/generate.py"
# The generator is this entrypoint PLUS its sibling modules (issue #355), so
# the provenance stamp hashes the whole set: a single-file hash would silently
# stop covering the code the split moved out. Sorted, so the stamp does not
# depend on import order.
GENERATOR_MODULE_RELS = (
    "signoff/characterization/common.py",
    "signoff/characterization/defchecks.py",
    "signoff/characterization/generate.py",
    "signoff/characterization/paths.py",
    "signoff/characterization/records.py",
    "signoff/characterization/render.py",
    "signoff/characterization/rows.py",
    "signoff/characterization/selection.py",
)
# Existence of this file inside the report store IS the mint publication
# lock (see _acquire_mint_lock); it is created and removed by every mint.
MINT_LOCK_NAME = ".mint.lock"
REPORT_SCHEMA = "sg13g2-opamp/characterization-report/2"
RECORD_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-z]{4,40}$")
# Matches the provenance block every existing generic envelope under
# signoff/evidence/ carries (they are hand-rolled, not produced by klt).
# This is a provenance stamp, not an install pin: it stays 0.6.0 (#311) until
# those envelopes are regenerated by a newer klt, so it never asserts a
# provenance that did not happen. The install pin is signoff/klt-pin.txt.
ENVELOPE_KLT_VERSION = "0.6.0"
COMPARISON_RULE = (
    "Each ratified bound is compared literally: every valid grid point's raw "
    "measured value, scaled to the bound's unit, must satisfy the bound exactly "
    "as written in spec/target-spec.md (e.g. >= 37.8 means 37.7999 fails). No "
    "rounding, tolerance or precision convention is applied: no ratification "
    "record defines one, and choosing one is a spec decision, not the "
    "report's. The worst value rounded to the bound's written decimals is "
    "shown for information only and never gates a verdict. A point that fails "
    "its record's validity flags never contributes an extremum: it is counted "
    "as missing coverage, so a failed simulation point can only make a row "
    "INCOMPLETE, never PASS."
)

DRAWS_AUDIT_RULE = (
    "Offset Monte Carlo statistics audit (issue #199): a record that selects a "
    "raw draws population (`draws_csv`, pinned by sha256 beside its summary) has "
    "every published per-point statistic recomputed from that population exactly "
    "as sim/input-offset/run_offset_mc.sh computes it -- accumulation in draw "
    "order, mean = sum/n_pass, sample sigma with the N-1 denominator, "
    "three-sigma = 3 sigma, min/max over the passing draws, and worst-case "
    "total = |vos_systematic_det_v| + three-sigma. A committed summary cell "
    "passes only when it is that recomputed value as the bench serializes it "
    "(printf %.9g, nine significant digits), i.e. within half a unit in the 9th "
    "significant digit (5e-9 relative); a cell that differs beyond its own "
    "serialization is an error naming the point and the offending field. The "
    "draws population itself must be complete and singular: missing, duplicated, "
    "mismatched or non-finite PASS draws fail the record rather than quietly "
    "shrinking it. The negative-control (negctrl) draws are a separate "
    "population: audited on their own draws like every other point's, never "
    "pooled into the mismatch statistics."
)

SAMPLES_AUDIT_RULE = (
    "CMRR mismatch statistics audit (issue #208): a record that selects raw "
    "sample files (`mc_samples`, one sha256-pinned `<point>_mc_samples.txt` per "
    "grid point) has every published per-point statistic recomputed offline "
    "from those samples by the SAME function the bench uses "
    "(sim/cmrr-mismatch/mc_samples.py point_stats): the strict parser (exactly "
    "one finite OP and one AC record per draw), the op_fail / plateau_fail "
    "acceptance rules with the pinned thresholds, the accepted/excluded "
    "counts, the LINEAR-domain Acm mean and N-1 sample sigma, and the DR-0004 "
    "bound Av0 - 20log10(mean + 3 sigma). Each committed cell must equal the "
    "recomputed value as the bench serializes it (printf %.6g, six "
    "significant digits). Av0 is joined from the explicitly selected, "
    "hash-pinned deterministic record (`av0_join`), never taken from the "
    "summary. A summary edited coherently (mean, sigma and CMRR together) "
    "while the pinned samples stay unchanged is an error naming the point and "
    "field, as is any unparseable, truncated, duplicated or stale-pinned "
    "population."
)

NOISE_AUDIT_RULE = (
    "Input-noise raw-evidence audit (issue #213): a record that selects raw "
    "noise artifacts (`noise_raw`, one sha256-pinned ngspice log and one "
    "sha256-pinned in-band spectrum per grid point) is audited offline against "
    "them, with the post-processing in sim/input-noise/noise_post.py -- the "
    "module run_noise_sweep.sh itself runs. Two independent checks per point: "
    "(1) integrated-log: `vni_int_vrms` must be the single NOISE_INOISE_TOTAL "
    "token of the pinned log, which the bench copies verbatim (so equality is "
    "exact, not toleranced); (2) spectrum-derived: the five spot densities, "
    "the flicker (A/f) and thermal (B) weighted-least-squares split, the "
    "flicker corner and flicker fraction, and the trapezoidal cross-check "
    "ratio against the logged total are recomputed from the pinned spectrum "
    "and each cell must equal the recomputed value as the bench serializes it "
    "(printf %.6g, six significant digits; `nan` where undefined). The "
    "trapezoidal spectrum integral is the bench's cross-check of the logged "
    "figure, never a substitute for it: neither check can mask the other. The "
    "spectrum must be the documented band (100 Hz - 1 MHz, 81 points, dec 20, "
    "strictly increasing) with finite positive samples; a missing, duplicated, "
    "malformed, non-finite or stale-pinned artifact is an error naming the "
    "point and file. A summary edited with its own hash refreshed still fails "
    "while the pinned raw artifacts disagree."
)

SLEW_AUDIT_RULE = (
    "Slew-rate raw-evidence audit (issue #227): a record that selects raw "
    "transient evidence (`slew_raw`, one sha256-pinned `wrdata` v(out) "
    "waveform and one sha256-pinned rendered bench netlist per grid point, "
    "plus the measurement configuration) is audited offline against it, with "
    "the measurement in sim/slew-rate/slew_post.py -- the module "
    "run_slew_sweep.sh itself runs. The configuration (edge intervals, outer "
    "and inner windows) must be exactly the bench's, and the supply, "
    "common-mode voltage, step schedule and stop time of each pinned rendered "
    "netlist must agree with it. Per point the four edge rates (first "
    "interpolated crossing of the window edges inside the edge interval), the "
    "worse edge, the waveform extrema, the window limits and the "
    "waveform-derived linearity and traverse flags are recomputed, and each "
    "committed cell must equal the recomputed value as the bench serializes "
    "it (printf %.6g, six significant digits; flags 0/1), with no tolerance "
    "beyond that serialization. A waveform that is missing, changed, "
    "assigned to another point, non-finite, out of time order or without the "
    "needed crossings cannot yield a passing measurement. A summary edited "
    "coherently (rise, fall and worst together, hash refreshed) still fails "
    "while the pinned waveforms disagree."
)

SWING_AUDIT_RULE = (
    "Output-swing raw-evidence audit (issue #230): a record that selects raw "
    "DC evidence (`swing_raw`, one sha256-pinned coarse and one fine "
    "transfer-curve wrdata file and one sha256-pinned rendered bench netlist "
    "per pass and grid point, plus the measurement configuration) is audited "
    "offline against it, with the measurement in sim/output-swing/swing_post.py "
    "-- the module run_swing_sweep.sh itself runs. The configuration (coarse "
    "window, fine half-span and step, the 0.5 x peak criterion) must be "
    "exactly the bench's, and each pinned rendered netlist must agree with "
    "it: supply, common mode (VDD/2), corner section, temperature, sweep "
    "window, recorded vectors, wrdata target and pass label -- the fine "
    "window centred on the coarse crossing recomputed from the pinned coarse "
    "curve, and each curve exactly as many samples as its netlist's sweep "
    "declares. Per point the unique-crossing and plateau checks, the "
    "tracking bounds at the sampled 0.5-times-peak region, both headrooms, "
    "the span, the fine interpolated crossing, the peak incremental gain and "
    "the mid-swing supply current are recomputed, and each committed cell "
    "must equal the recomputed value as the bench serializes it (printf %.9g, "
    "nine significant digits; op_pass 0/1), with no tolerance beyond that "
    "serialization. Curves are strictly parsed: missing, truncated, malformed "
    "or non-finite samples, repeated or reversed sweep scales and mismatched "
    "wrdata scale columns are errors naming the point and file, as are "
    "multiple or missing coarse crossings and a fine window that truncates "
    "the accepted region. A summary edited coherently (bounds, headrooms and "
    "span together, hash refreshed) still fails while the pinned curves "
    "disagree. The record's cross-bench diagnostic columns "
    "(vos_offset_record_v, vos_delta_v, av0_ac_record_db, av0_ratio, "
    "ivdd_ac_record_a, ivdd_ratio) are logged, not gated (the bench README's "
    "\"Cross-checks\") and stay outside this audit."
)

KLT_AUDIT_RULE = (
    "Open-loop `klt sim` raw-evidence audit (issue #101): a record that "
    "selects `klt_raw` (the AC and OP `klt sim` envelopes, the "
    "`klt pex --measure-command` measurement document, both requests and the "
    "bench circuit body, each sha256-pinned) is audited offline against them "
    "in place of the legacy `op_pass` / `gm_status` validity columns it does "
    "not carry. Both envelopes must be status pass with 45 unique, "
    "diagnostic-free passing corners and agree on engine, model deck, PDK and "
    "the simulated circuit: the DUT snapshot hash recorded in the envelope "
    "must be the selected snapshot's, and the bench body must be the pinned "
    "one with exactly one CL, `Lbreak inn out 1e18`, `Cinn_acgnd inn vss 1` "
    "(inn AC-grounded), the 10 uA `Iibias` reference and a 1 V AC source on "
    "inp; CL must be a load the record's own prose states. Per point the four "
    "graded cells are recomputed from the raw envelopes -- Av0 and GBW "
    "verbatim from the AC envelope, PM as 180 + degrees(phase at the 0 dB "
    "crossing), Iq as the OP envelope's total VDD current (-i(vdd), which "
    "INCLUDES the 10 uA ibias reference) -- and must equal the committed cell "
    "as the converter serializes it (printf %.6g), and must also equal the "
    "measurement document. The operating-point sanity the legacy `op_pass` "
    "applied is recomputed from the raw OP values where they exist: Vcm = "
    "VDD/2 (within the bench's 1e-4 fraction), |Vout - VDD/2| <= 0.15 VDD, "
    "0.02 VDD <= Vout <= 0.98 VDD. The legacy check on the internal nodes "
    "(vd1, vd2, vtail) and the gain-margin `gm_status` are NOT re-measured by "
    "the corrected bench: the DC operating point does not depend on the AC "
    "ground element, so the selected `dc_continuity` record is joined as the "
    "stated evidence for them -- its point must have op_pass=1 and its Vout "
    "and total VDD current must agree with the corrected OP envelope within "
    "10 uV and 10 nA; that dependence is disclosed, never presented as a "
    "fresh internal-node measurement. A missing, changed, stale-pinned or "
    "inconsistent artifact is an error naming the point and file."
)

NOT_CLAIMED = [
    "Not item 5 or item 6 evidence: it is a generic, offline aggregation of "
    "harness-native records, not a `klt sim` or `klt yield` envelope, and the "
    "signoff manifest cites it for item 8 only.",
    "Not a re-run: regenerating this report re-reads committed records; it "
    "does not re-simulate anything. Re-running the benches is the separate "
    "cold-start procedure in each sim/ bench README.",
    "Not a claim that every T1 item is satisfied; post-layout (PEX) "
    "re-simulation does not exist yet, so every number here is pre-layout.",
]


# --------------------------------------------------------------------------
# report


def pdk_provenance_summary(records: dict) -> dict:
    by_status: dict[str, list[str]] = {}
    for key, state in sorted(records.items()):
        by_status.setdefault(state["source"]["pdk_provenance"]["status"], []).append(key)
    all_verified = bool(records) and set(by_status) == {PROV_VERIFIED}
    return {
        "verified": by_status.get(PROV_VERIFIED, []),
        "legacy_unverified": by_status.get(PROV_LEGACY, []),
        "error": by_status.get(PROV_ERROR, []),
        "pdk_reproducibility_verified": all_verified,
        "note": (
            "The configured release shown above (sim/pdk.json) is the CONFIGURED release, not run-time evidence. A record is "
            "`verified` only when its selection pins an environment sidecar (sim/tools/env_identity.py) whose "
            "model-closure and OSDI identity checks pass and whose configured release matches the current pin; "
            "`legacy-unverified` records keep their numerical results and electrical verdicts but carry NO "
            "run-time PDK provenance (it is not invented retroactively -- new runs and new records are needed)"
        ),
    }


def build_content(repo: Path, selection_path: Path) -> dict:
    repo = repo.resolve()
    selection = load_selection(selection_path)
    global_errors: list[str] = []

    def need(rel: str) -> Path | None:
        path = repo / rel
        if not path.is_file():
            global_errors.append(f"missing input {rel}")
            return None
        return path

    env: dict = {}
    pdk_path = need(selection["pdk_pin"])
    if pdk_path:
        try:
            pdk = json.loads(pdk_path.read_text(encoding="utf-8"))
            env["ngspice"] = pdk["osdi_toolchain"]["ngspice_actually_used"]
            env["pdk"] = f"{pdk['source']} {pdk['release_tag']}"
            env["pin"] = pdk
        except (ValueError, KeyError, TypeError) as exc:
            global_errors.append(f"{selection['pdk_pin']}: cannot read the ngspice/PDK pin ({exc})")
    netlist = need(selection["design_netlist"])
    if netlist:
        env["netlist_normalized_sha256"] = normalized_netlist_hash(netlist)
    spec_path = need(selection["spec"])
    spec_lines = spec_path.read_text(encoding="utf-8").splitlines() if spec_path else []
    inventory_path = need(selection["inventory"])
    inventory = parse_inventory(inventory_path) if inventory_path else {}

    records = {
        key: load_record(repo, key, spec, selection["grids"][spec["grid"]], env, selection["records"])
        for key, spec in sorted(selection["records"].items())
    }
    rows = [evaluate_row(row, records, spec_lines, inventory, selection) for row in selection["rows"]]

    # Coverage of the spec and of the item 9 inventory: no ratified row may be
    # silently absent from the selection.
    prefixes = [row["spec_check"]["row_prefix"] for row in selection["rows"]]
    spec_rows = []
    in_section = False
    for line in spec_lines:
        if line.startswith("## "):
            in_section = line.startswith("## 2.")
            continue
        if in_section and line.startswith("| ") and not line.startswith("| Parameter") and not line.startswith("|---"):
            name = line[2:].split(" | ", 1)[0].strip()
            covered = any(line.startswith(prefix) for prefix in prefixes)
            spec_rows.append({"row": name, "covered": covered})
            if not covered:
                global_errors.append(f"spec/target-spec.md section 2 row {name!r} has no row in the selection")
    if spec_path and not spec_rows:
        global_errors.append("spec/target-spec.md: found no section 2 table rows")
    labels = {row.get("inventory_label") for row in selection["rows"]}
    inventory_rows = []
    for label in sorted(inventory):
        if label in selection.get("inventory_ignore", []):
            continue
        inventory_rows.append({"row": label, "covered": label in labels})
        if label not in labels:
            global_errors.append(f"testbenches.txt row {label!r} has no row in the selection")

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    considered = [row for row in rows if row["class"] != "pending"]
    if global_errors or any(row["verdict"] == "ERROR" for row in rows):
        overall = "ERROR"
    elif any(row["verdict"] == "FAIL" and row["binding"] for row in considered):
        overall = "FAIL"
    elif any(row["verdict"] == "INCOMPLETE" for row in considered):
        overall = "INCOMPLETE"
    else:
        overall = "PASS"
    ratified = [row for row in rows if row["class"] == "ratified"]
    # Disclosure, not a gate: binding rows that FAIL literally although their
    # worst value rounds onto the bound at the decimals the bound is written
    # to. Whether such a row should pass is a spec decision for the keys.
    beyond_decimals = sorted(
        row["id"] for row in ratified if row["verdict"] == "FAIL" and row.get("fails_only_beyond_written_decimals")
    )

    return {
        "schema": REPORT_SCHEMA,
        "block": selection["block"],
        "selection": {
            "path": str(selection_path.resolve().relative_to(repo)) if selection_path.resolve().is_relative_to(repo) else selection_path.name,
            "sha256": sha256_file(selection_path),
        },
        "comparison_rule": COMPARISON_RULE,
        "draws_audit_rule": DRAWS_AUDIT_RULE,
        "samples_audit_rule": SAMPLES_AUDIT_RULE,
        "noise_audit_rule": NOISE_AUDIT_RULE,
        "slew_audit_rule": SLEW_AUDIT_RULE,
        "swing_audit_rule": SWING_AUDIT_RULE,
        "klt_audit_rule": KLT_AUDIT_RULE,
        "environment": {
            "pdk_provenance": pdk_provenance_summary(records),
            "ngspice_pin": env.get("ngspice"),
            "pdk_pin": env.get("pdk"),
            "pdk_pin_file": selection["pdk_pin"],
            "design_netlist": selection["design_netlist"],
            "design_netlist_normalized_sha256": env.get("netlist_normalized_sha256"),
            "note": "every selected record must name this ngspice and must have simulated this netlist (comment/blank lines ignored); a mismatch is an error, never a silent mix",
        },
        "sources": {key: state["source"] for key, state in records.items()},
        "rows": rows,
        "spec_coverage": spec_rows,
        "inventory_coverage": inventory_rows,
        "caveats": selection.get("caveats", []),
        "not_claimed": NOT_CLAIMED,
        "errors": sorted(global_errors),
        "overall": {
            "verdict": overall,
            "ratified_rows": len(ratified),
            "ratified_pass": sum(1 for row in ratified if row["verdict"] == "PASS"),
            "fail_only_beyond_written_decimals": beyond_decimals,
            "verdict_counts": dict(sorted(counts.items())),
            "rule": "ERROR if any input is in error; else FAIL if any ratified (binding) row fails its bound; else INCOMPLETE if any non-pending row lacks full valid grid coverage; else PASS. Superseded rows are context and never FAIL the report; measured rows carry no bound; Area is PENDING.",
        },
    }


def content_hash(content: dict) -> str:
    return sha256_bytes(canonical_json(content).encode("utf-8"))


def git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"], cwd=str(repo), capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def generator_sha256(repo: Path) -> str | None:
    """Hash of the generator MODULE SET (GENERATOR_MODULE_RELS), not one file.

    `<rel> <sha256-of-that-file>` lines in sorted path order, hashed -- so the
    stamp moves if any module of the generator changes, and `generator_modules`
    records which files it covered. None when any module is missing: an
    incomplete provenance stamp is never invented.

    This field is excluded from reproduction (see `_note` below): --check
    compares `content` and `content_sha256` only, so records minted by the
    pre-split single-file generator keep reproducing unchanged.
    """
    lines = []
    for rel in GENERATOR_MODULE_RELS:
        path = repo / rel
        if not path.is_file():
            return None
        lines.append(f"{rel} {sha256_file(path)}\n")
    return sha256_bytes("".join(lines).encode("utf-8"))


def make_report(content: dict, record_id: str | None, repo: Path) -> dict:
    head = git_head(repo)
    return {
        "record_metadata": {
            "_note": "The ONLY fields excluded from reproduction: --check compares `content` (and content_sha256) and nothing here.",
            "record_id": record_id,
            "generated_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_head": head,
            "generator": GENERATOR_REL,
            "generator_modules": list(GENERATOR_MODULE_RELS),
            "generator_sha256": generator_sha256(repo),
        },
        "content_sha256": content_hash(content),
        "content": content,
    }


# --------------------------------------------------------------------------
# minting, envelope, check


def latest_report(reports_dir: Path) -> Path | None:
    """Newest record BY NAME (the record id sorts by UTC time), never by mtime."""
    candidates = sorted(p for p in reports_dir.glob("*.json") if RECORD_ID_RE.match(p.stem))
    return candidates[-1] if candidates else None


def envelope_for(report_rel: str, report_hash: str, content: dict) -> dict:
    overall = content["overall"]
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass" if overall["verdict"] == "PASS" else "fail",
        "t1_item": 8,
        "summary": (
            f"characterization report: overall {overall['verdict']}, "
            f"{overall['ratified_pass']}/{overall['ratified_rows']} ratified spec-row bounds PASS (raw values "
            "compared against the literal ratified bound) with full "
            "expected-grid coverage; per-row units, load, bound, decision record, binding point and "
            "source-record hash; aggregated offline from committed sim/ records (no re-simulation); "
            "not item 5/6 evidence"
        ),
        "source": report_rel[: -len(".json")] + ".md",
        "provenance": {
            "klt_version": ENVELOPE_KLT_VERSION,
            "klayout_version": None,
            "pdk": None,
            "deck": None,
            "input": {
                "path": {"path": report_rel, "scope": "repo"},
                "content_hash": report_hash,
            },
        },
    }


def _stage_text(dest: Path, text: str) -> Path:
    """Write text to a unique staging file beside dest (never at dest) and
    return its path. The caller publishes or discards it."""
    fd, name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)  # mkstemp is 0600; reports and the envelope are read by others
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _link_no_clobber(tmp: Path, dest: Path) -> None:
    """Publish the staged file at dest without ever replacing or truncating
    an existing dest (the Python twin of sg13g2_publish_noclobber in
    sim/record-paths.sh). The hard link either lands whole on a free
    name or refuses with CollisionError; dest is never opened for writing.
    The staging file is always removed."""
    try:
        os.link(tmp, dest)
    except FileExistsError as exc:
        raise CollisionError(f"{dest.name} already exists") from exc
    finally:
        tmp.unlink(missing_ok=True)


def _replace_text_atomically(dest: Path, text: str) -> None:
    """Overwrite the mutable dest in one atomic step (os.replace): a reader
    sees the old contents or the new contents, never a truncated file."""
    tmp = _stage_text(dest, text)
    try:
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)  # no-op once the replace has moved it


def _acquire_mint_lock(reports: Path) -> int | None:
    """Create and hold the report store's publication lock, an O_EXCL file
    whose existence IS the lock (the reservation idiom of
    sim/tools/klt_run_common.sh). Held for the process lifetime of one mint
    and removed on exit. Returns the fd, or None when another mint holds
    the store."""
    try:
        fd = os.open(reports / MINT_LOCK_NAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None
    try:
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError:
        pass  # diagnostic only; the lock itself is the file's existence
    return fd


def _publish_mint(repo: Path, reports: Path, record_id: str, content: dict) -> int:
    """Publish one mint while the store lock is held: recheck both
    destinations, publish the complete JSON and Markdown records without
    replacing anything, and only then swap the evidence envelope atomically.
    Any failure rolls back what this call created, so the store keeps its
    earlier files byte-for-byte and the envelope is left untouched."""
    json_path = reports / f"{record_id}.json"
    md_path = reports / f"{record_id}.md"
    # Recheck under the lock: a pre-lock exists() check cannot reserve the
    # paths, so two same-id minters could otherwise both pass it.
    taken = [p for p in (json_path, md_path) if os.path.lexists(p)]
    if taken:
        print(f"refusing to overwrite existing record {record_id}", file=sys.stderr)
        return 1
    report = make_report(content, record_id, repo)
    created: list[Path] = []
    try:
        _link_no_clobber(_stage_text(json_path, canonical_json(report)), json_path)
        created.append(json_path)
        _link_no_clobber(_stage_text(md_path, render_markdown(report)), md_path)
        created.append(md_path)
        report_rel = f"{REPORTS_REL}/{record_id}.json"
        report_hash = sha256_file(json_path)
        _replace_text_atomically(repo / ENVELOPE_REL, canonical_json(envelope_for(report_rel, report_hash, content)))
    except CollisionError as exc:
        for p in created:
            p.unlink(missing_ok=True)
        print(f"refusing to overwrite existing record {record_id}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        for p in created:
            p.unlink(missing_ok=True)
        print(f"mint failed, nothing published: {exc}", file=sys.stderr)
        return 1
    except BaseException:
        for p in created:
            p.unlink(missing_ok=True)
        raise
    print(f"wrote {REPORTS_REL}/{record_id}.json and .md (overall {content['overall']['verdict']})")
    print(f"wrote {ENVELOPE_REL} (status {'pass' if content['overall']['verdict'] == 'PASS' else 'fail'})")
    print("next: pin it -- signoff/block-manifest.json evidence[\"8\"].content_hash and")
    print(f"      signoff/pinned-inputs.json inputs[\"8\"] = {report_rel!r}, both at")
    print(f"      {report_hash}; then bash signoff/regenerate.sh and")
    print("      python3 signoff/check_signoff.py --run-klt")
    return 0


def mint(repo: Path, selection_path: Path) -> int:
    content = build_content(repo, selection_path)
    if content["overall"]["verdict"] == "ERROR":
        print(render_markdown(make_report(content, None, repo)))
        print("refusing to mint a report whose inputs are in error", file=sys.stderr)
        return 1
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    record_id = f"{stamp}-{git_head(repo) or 'nogit'}"
    reports = repo / REPORTS_REL
    reports.mkdir(parents=True, exist_ok=True)
    lock_fd = _acquire_mint_lock(reports)
    if lock_fd is None:
        print(f"another --mint holds the publication lock ({REPORTS_REL}/{MINT_LOCK_NAME}) -- refusing;", file=sys.stderr)
        print("reports are append-only. If no mint is live (killed earlier), remove that lock file and re-run.", file=sys.stderr)
        return 1
    try:
        # Holding the store lock: sweep staging files a killed earlier mint
        # may have left, then publish. No other mint can be staging now.
        for p in (*reports.glob(".*.part"), *(repo / ENVELOPE_REL).parent.glob(f".{Path(ENVELOPE_REL).name}.*.part")):
            p.unlink(missing_ok=True)
        return _publish_mint(repo, reports, record_id, content)
    finally:
        os.close(lock_fd)
        (reports / MINT_LOCK_NAME).unlink(missing_ok=True)


def check(repo: Path, selection_path: Path, report_path: Path | None) -> int:
    problems: list[str] = []
    reports = repo / REPORTS_REL
    if report_path is None:
        report_path = latest_report(reports)
        if report_path is None:
            print(f"FAIL: no minted report under {REPORTS_REL}")
            return 1
    print(f"  record: {report_path.relative_to(repo) if report_path.is_relative_to(repo) else report_path}")
    try:
        committed = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FAIL: cannot read {report_path} ({exc})")
        return 1
    if not RECORD_ID_RE.match(report_path.stem) or committed.get("record_metadata", {}).get("record_id") != report_path.stem:
        problems.append("record id in the file name and in record_metadata disagree (or is malformed)")
    fresh = build_content(repo, selection_path)
    if committed.get("content") != fresh:
        old, new = committed.get("content") or {}, fresh
        for key in sorted(set(old) | set(new)):
            if old.get(key) != new.get(key):
                problems.append(f"content.{key} no longer reproduces from the selected evidence")
    if committed.get("content_sha256") != content_hash(committed.get("content") or {}):
        problems.append("content_sha256 does not match the committed content")
    md_path = report_path.with_suffix(".md")
    if not md_path.is_file():
        problems.append(f"no Markdown twin {md_path.name}")
    elif md_path.read_text(encoding="utf-8") != render_markdown(committed):
        problems.append(f"{md_path.name} is not the rendering of its JSON twin")

    envelope_path = repo / ENVELOPE_REL
    if envelope_path.is_file():
        latest = latest_report(reports)
        try:
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{ENVELOPE_REL} is not valid JSON ({exc})")
            envelope = None
        if envelope is not None and latest is not None:
            latest_rel = str(latest.relative_to(repo))
            expected = envelope_for(latest_rel, sha256_file(latest), json.loads(latest.read_text(encoding="utf-8"))["content"])
            if envelope != expected:
                problems.append(
                    f"{ENVELOPE_REL} does not wrap the newest report {latest_rel} at its current hash "
                    "with a status matching its overall verdict -- re-mint or re-wrap"
                )
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        return 1
    print(f"  ok  report reproduces (content_sha256 {committed['content_sha256']}), overall {fresh['overall']['verdict']}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--selection", type=Path, default=None, help=f"default: <repo>/{SELECTION_REL}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mint", action="store_true", help="append a new report record and re-wrap the item 8 envelope")
    mode.add_argument("--check", nargs="?", const="", default=None, metavar="REPORT", help="verify a minted record (default: newest by record id) reproduces")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    selection = (args.selection or repo / SELECTION_REL).resolve()
    try:
        if args.mint:
            return mint(repo, selection)
        if args.check is not None:
            return check(repo, selection, Path(args.check).resolve() if args.check else None)
        content = build_content(repo, selection)
    except SelectionError as exc:
        print(f"selection error: {exc}", file=sys.stderr)
        return 2
    report = make_report(content, None, repo)
    sys.stdout.write(canonical_json(report) if args.format == "json" else render_markdown(report))
    verdict = content["overall"]["verdict"]
    return 0 if verdict == "PASS" else (1 if verdict == "ERROR" else 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

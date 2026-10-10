#!/usr/bin/env python3
"""Keep this block's committed T1 signoff verdict honest.

`signoff/block-manifest.json` is what `klt signoff --manifest` grades, and
`signoff/reports/<record-id>.signoff.json` is the graded verdict of record
(see signoff/README.md). Both are static files, so both rot silently:

  * a cited envelope can be deleted or edited,
  * a pinned `content_hash` can stop describing the artifact it pins once the
    layout is regenerated, and
  * the committed report can stop matching what `klt signoff` would say today.

This script fails on all three. It is stdlib-only and, by default, offline and
PDK-free -- the checks that need neither `klt` nor a network run in the
offline half of the CI signoff job, and `--run-klt` adds the re-grade for the
same job's klt install (`.github/workflows/signoff.yml`).

  python3 signoff/check_signoff.py              # offline checks only
  python3 signoff/check_signoff.py --run-klt    # + re-grade with klt, compare

Exit codes: 0 pass, 1 a check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGNOFF_DIR = REPO_ROOT / "signoff"
MANIFEST = SIGNOFF_DIR / "block-manifest.json"
PINNED_INPUTS = SIGNOFF_DIR / "pinned-inputs.json"
KLT_PIN = SIGNOFF_DIR / "klt-pin.txt"
REPORTS_DIR = SIGNOFF_DIR / "reports"
# The committed `klt lvs` request: names the plain-element reference netlist
# (relative to the request's own directory). Every cited LVS envelope must
# have been run against exactly those reference bytes.
LVS_REQUEST = REPO_ROOT / "layout" / "opamp_core" / "lvs_request.json"
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# The T1 item 8 characterization report (signoff/characterization/README.md):
# its generic envelope, and the generator whose --check re-derives the cited
# record from the committed sim/ evidence it selects.
CHARACTERIZATION_ENVELOPE = "signoff/evidence/characterization.json"
CHARACTERIZATION_GENERATOR = SIGNOFF_DIR / "characterization" / "generate.py"
CHARACTERIZATION_ITEM = "8"

BLOCK_KINDS = ("analog", "digital", "mixed-signal")
# The T1 checklist item ids this repo's manifest may key on. 11 as of
# klayout-tools#2025 (2026-09-17); a klt pin bump that changes the count
# changes `t1_item_count` in the report, which is checked below.
MAX_ITEM_ID = 11
# T1 items whose `evidence` value may be a JSON *array* of citations rather
# than a single one. Item 11 (power delivery, structural) is the only one
# today: klayout-tools#2025 made it the first compound item, graded from a
# `klt erc` supply run plus the LVS report item 4 grades. Keeping this a set
# rather than a bare `== 11` is so a later checklist addition lands as one
# edit here instead of three scattered special cases.
COMPOUND_ITEM_IDS = frozenset({11})
RECORD_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7,40}\.signoff\.json$")
EVIDENCE_KEY_RE = re.compile(r"^(\d+)(?:\.(analog|digital))?$")

# Fields of a report citation that must survive a re-grade unchanged. Excludes
# free-form/large fields (`coverage`, `body_bias`) which are reported verbatim
# from the cited envelope and compared separately, as whole blocks.
CITATION_FIELDS = ("file", "command", "kind", "check_status", "content_hash")


class Failures:
    """Collect every failure instead of stopping at the first one."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def add(self, message: str) -> None:
        self.messages.append(message)
        print(f"FAIL: {message}")

    def __bool__(self) -> bool:
        return bool(self.messages)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def load_json(path: Path, failures: Failures, label: str):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        failures.add(f"{label}: cannot read {rel(path)} ({exc})")
    except ValueError as exc:
        failures.add(f"{label}: {rel(path)} is not valid JSON ({exc})")
    return None


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check_manifest(manifest, failures: Failures) -> dict:
    """Manifest shape, plus this repo's two stricter-than-klt rules."""
    if not isinstance(manifest, dict):
        failures.add("manifest: top level is not a JSON object")
        return {}

    block = manifest.get("block")
    if not isinstance(block, str) or not block.strip():
        # Required *here* even though klt calls it optional: it is how this
        # block's row is identified in the fleet roll-up (2AMLogic/2am#956).
        failures.add("manifest: `block` must be a non-empty string")

    kind = manifest.get("kind")
    if kind not in BLOCK_KINDS:
        failures.add(f"manifest: `kind` must be one of {BLOCK_KINDS}, got {kind!r}")

    evidence = manifest.get("evidence", {})
    if not isinstance(evidence, dict):
        failures.add("manifest: `evidence` must be an object")
        return {}

    for key, entry in evidence.items():
        match = EVIDENCE_KEY_RE.match(key)
        if match is None or not 1 <= int(match.group(1)) <= MAX_ITEM_ID:
            # klt silently ignores an unrecognised evidence key: the item it
            # was meant for renders `no_evidence`, exactly as if nothing had
            # been cited, so a typo reads as an honest gap. Catch it here.
            failures.add(
                f"manifest: evidence key {key!r} names no T1 item "
                f"(expected \"1\"..\"{MAX_ITEM_ID}\") -- klt would silently ignore it"
            )
            continue
        if match.group(2) and kind != "mixed-signal":
            failures.add(
                f"manifest: evidence key {key!r} uses the per-partition "
                f"\"<id>.<kind>\" form, which klt reads only for a mixed-signal "
                f"block (this block is {kind!r}) -- it would be silently ignored"
            )
            continue

        if isinstance(entry, list):
            # The compound form (klayout-tools#2025): T1 item 11 is the first
            # item no single artifact proves -- it needs a `klt erc` supply
            # run *and* the LVS report item 4 grades -- so klt accepts a JSON
            # array of ordinary evidence entries there. Only item 11 does:
            # klt would grade a list on any other item as a malformed entry.
            if int(match.group(1)) not in COMPOUND_ITEM_IDS:
                failures.add(
                    f"manifest: evidence[{key!r}] is a list, but only "
                    f"{sorted(COMPOUND_ITEM_IDS)} accept the compound "
                    "(multi-artifact) form"
                )
                continue
            if not entry:
                failures.add(f"manifest: evidence[{key!r}] is an empty list")
                continue
            for index, part in enumerate(entry):
                check_evidence_entry(part, f"{key}[{index}]", failures)
            continue

        check_evidence_entry(entry, key, failures)

    return evidence


def check_evidence_entry(entry, label: str, failures: Failures) -> None:
    """One evidence citation: pinned, and pointing at a readable artifact.

    `label` is how the entry is named in failure messages -- an item id for
    an ordinary citation, `"<id>[<n>]"` for one part of item 11's compound
    set.
    """
    if not isinstance(entry, dict):
        failures.add(
            f"manifest: evidence[{label!r}] must be an object pinning a "
            "`content_hash` (a bare path cannot have its freshness verified)"
        )
        return
    if not isinstance(entry.get("content_hash"), str):
        failures.add(
            f"manifest: evidence[{label!r}] pins no `content_hash` -- an "
            "unpinned citation's freshness cannot be verified at all"
        )
    cited = entry.get("file")
    if isinstance(cited, str):
        cited_path = REPO_ROOT / cited
        if not cited_path.is_file():
            failures.add(f"manifest: evidence[{label!r}] cites missing file {cited}")
        else:
            load_json(cited_path, failures, f"manifest evidence[{label!r}]")
    elif "command" not in entry:
        failures.add(
            f"manifest: evidence[{label!r}] has neither a `file` nor a `command`"
        )


def check_pins(manifest_evidence: dict, failures: Failures) -> None:
    """Every pinned hash still describes the committed artifact it pins.

    This is the half `klt signoff` structurally cannot do: it compares a pin
    against the cited envelope's own recorded input hash, never against the
    artifact in the repo. Without this check a manifest citing a layout that
    has since been regenerated keeps rendering `met` off a stale pair.
    """
    doc = load_json(PINNED_INPUTS, failures, "pinned-inputs")
    if doc is None:
        return
    inputs = doc.get("inputs")
    if not isinstance(inputs, dict):
        failures.add("pinned-inputs: `inputs` must be an object")
        return

    for key, entry in manifest_evidence.items():
        recorded = inputs.get(key)
        if isinstance(entry, list):
            # A compound citation (item 11) pins one hash per part, so it
            # records one artifact per part, in the same order. Written as a
            # list rather than collapsed to a single path even when every
            # part happens to pin the same artifact: the parts are
            # independent citations and a later one could legitimately pin
            # something else.
            if not isinstance(recorded, list) or len(recorded) != len(entry):
                failures.add(
                    f"pinned-inputs: inputs[{key!r}] must be a list of "
                    f"{len(entry)} artifact path(s), one per part of the "
                    "manifest's compound citation"
                )
                continue
            for index, (part, artifact) in enumerate(zip(entry, recorded)):
                pin = part.get("content_hash") if isinstance(part, dict) else None
                check_one_pin(pin, artifact, f"{key}[{index}]", failures)
            continue

        pinned = entry.get("content_hash") if isinstance(entry, dict) else None
        check_one_pin(pinned, recorded, key, failures)

    for key in inputs:
        if key not in manifest_evidence:
            failures.add(
                f"pinned-inputs: inputs[{key!r}] pins an artifact for an item the "
                "manifest does not cite"
            )


def check_one_pin(pinned, artifact, label: str, failures: Failures) -> None:
    """Re-hash `artifact` and compare it to the manifest's `pinned` hash."""
    if not isinstance(pinned, str):
        return  # already reported by check_manifest
    if not isinstance(artifact, str):
        failures.add(
            f"pinned-inputs: no artifact recorded for evidence[{label!r}] -- "
            "every pin must name the repo file it is the hash of"
        )
        return
    artifact_path = REPO_ROOT / artifact
    if not artifact_path.is_file():
        failures.add(f"pinned-inputs: {artifact} (evidence[{label!r}]) does not exist")
        return
    actual = sha256_file(artifact_path)
    if actual != pinned:
        failures.add(
            f"pinned-inputs: {artifact} has changed since evidence[{label!r}] "
            f"was pinned\n  pinned: {pinned}\n  actual: {actual}\n"
            "  -> re-run the cited check against current sources, then "
            "re-run signoff/regenerate.sh"
        )
    else:
        print(f"  ok  evidence[{label}] pin matches {artifact}")


def lvs_citations(manifest_evidence: dict):
    """Yield (label, entry) for every `kind: lvs` citation, item 4 and any
    LVS part of a compound item (11), independent of list order."""
    for key, entry in manifest_evidence.items():
        if isinstance(entry, list):
            for index, part in enumerate(entry):
                if isinstance(part, dict) and part.get("kind") == "lvs":
                    yield f"{key}[{index}]", part
        elif isinstance(entry, dict) and entry.get("kind") == "lvs":
            yield key, entry


def check_lvs_reference(manifest_evidence: dict, failures: Failures) -> None:
    """Each cited LVS envelope matches the committed reference netlist bytes.

    check_pins binds an LVS citation to the GDS only. The envelope also
    records `environment.reference_sha256`; if the expanded reference is
    edited (or regenerated from a changed schematic netlist) without a new
    LVS run, the recorded match is stale. Fixing that means re-running LVS and
    regenerating the signoff record -- never editing historical records.
    """
    citations = list(lvs_citations(manifest_evidence))
    if not citations:
        return
    request = load_json(LVS_REQUEST, failures, "lvs reference")
    if request is None:
        return
    ref_name = (request.get("reference") or {}).get("netlist") if isinstance(request, dict) else None
    if not isinstance(ref_name, str) or not ref_name:
        failures.add(f"lvs reference: {rel(LVS_REQUEST)} names no `reference.netlist`")
        return
    ref_path = LVS_REQUEST.parent / ref_name
    if not ref_path.is_file():
        failures.add(f"lvs reference: {rel(ref_path)} named by {rel(LVS_REQUEST)} does not exist")
        return
    actual = sha256_file(ref_path).removeprefix("sha256:")
    for label, entry in citations:
        cited = entry.get("file")
        if not isinstance(cited, str):
            continue  # reported by check_manifest
        env_path = REPO_ROOT / cited
        if not env_path.is_file():
            continue  # reported by check_manifest
        envelope = load_json(env_path, failures, f"lvs reference evidence[{label!r}]")
        if not isinstance(envelope, dict):
            continue
        recorded_name = envelope.get("reference")
        if recorded_name != ref_name:
            failures.add(
                f"lvs reference: evidence[{label!r}] ({cited}) records reference "
                f"{recorded_name!r}, but {rel(LVS_REQUEST)} names {ref_name!r}"
            )
        env = envelope.get("environment")
        recorded = env.get("reference_sha256") if isinstance(env, dict) else None
        if not isinstance(recorded, str) or not SHA256_HEX_RE.match(recorded):
            failures.add(
                f"lvs reference: evidence[{label!r}] ({cited}) has a missing or "
                f"malformed environment.reference_sha256 ({recorded!r}); "
                "expected 64 lowercase hex digits"
            )
            continue
        if recorded != actual:
            failures.add(
                f"lvs reference: {rel(ref_path)} has changed since the LVS "
                f"match cited by evidence[{label!r}] was recorded\n"
                f"  recorded: {recorded}\n  actual:   {actual}\n"
                "  -> run `python3 layout/opamp_core/lvs_reference.py` to refresh the "
                "reference, re-run `klt lvs`, then re-run signoff/regenerate.sh"
            )
        else:
            print(f"  ok  evidence[{label}] LVS match is against current {rel(ref_path)}")


def latest_report(failures: Failures) -> Path | None:
    if not REPORTS_DIR.is_dir():
        failures.add(f"no report directory at {rel(REPORTS_DIR)}")
        return None
    reports = sorted(p for p in REPORTS_DIR.glob("*.signoff.json"))
    if not reports:
        failures.add(
            f"{rel(REPORTS_DIR)} holds no *.signoff.json record -- the manifest's "
            "verdict of record is missing"
        )
        return None
    for report in reports:
        if not RECORD_ID_RE.match(report.name):
            failures.add(
                f"report {report.name} does not use the "
                "<YYYYMMDD>-<HHMMSS>-<short-sha>.signoff.json record id"
            )
    return reports[-1]


def check_report(report_doc, manifest, manifest_evidence: dict, failures: Failures) -> None:
    if not isinstance(report_doc, dict):
        failures.add("report: top level is not a JSON object")
        return

    if report_doc.get("block") != manifest.get("block"):
        failures.add(
            f"report: block {report_doc.get('block')!r} != manifest block "
            f"{manifest.get('block')!r}"
        )
    if report_doc.get("kind") != manifest.get("kind"):
        failures.add(
            f"report: kind {report_doc.get('kind')!r} != manifest kind "
            f"{manifest.get('kind')!r}"
        )

    items = report_doc.get("items")
    if not isinstance(items, list) or not items:
        failures.add("report: `items` is missing or empty")
        return

    t1_ids = {item.get("id") for item in items if item.get("tier") == "T1"}
    for key in manifest_evidence:
        item_id = int(EVIDENCE_KEY_RE.match(key).group(1)) if EVIDENCE_KEY_RE.match(key) else None
        if item_id is not None and item_id not in t1_ids:
            failures.add(
                f"report: manifest cites item {item_id}, which the report does not "
                "render -- the report was graded against a different checklist"
            )

    count = report_doc.get("t1_item_count")
    if count != len(t1_ids):
        failures.add(
            f"report: t1_item_count {count} != the {len(t1_ids)} T1 rows rendered"
        )
    if isinstance(count, int) and count < MAX_ITEM_ID:
        failures.add(
            f"report: only {count} T1 items graded, but this repo expects at least "
            f"{MAX_ITEM_ID} (item 11, power delivery (structural), was added to the "
            "checklist on 2026-09-17) -- the klt pin is behind the checklist"
        )

    # Every `met` row must be backed by a citation the manifest actually makes,
    # at the hash the manifest pins.
    for item in items:
        if item.get("status") != "met":
            continue
        citation = item.get("citation") or {}
        key = str(item.get("id"))
        entry = manifest_evidence.get(key)
        if isinstance(entry, list):
            # A compound citation (item 11): klt renders the whole cited set
            # under `citation.parts`, leading the single-citation fields with
            # one of the parts. Compare the *sets* of (file, pinned hash) --
            # klt orders parts by kind (erc, lvs, place-and-route), which need
            # not be the order the manifest lists them in, and which part
            # leads is klt's choice, not the manifest's.
            want = {
                (part.get("file"), part.get("content_hash"))
                for part in entry
                if isinstance(part, dict)
            }
            got = {
                (part.get("file"), part.get("content_hash"))
                for part in citation.get("parts") or []
                if isinstance(part, dict)
            }
            if got != want:
                failures.add(
                    f"report: item {item.get('id')} is `met` on the cited set "
                    f"{sorted(got)}, manifest cites {sorted(want)}"
                )
            elif (citation.get("file"), citation.get("content_hash")) not in want:
                failures.add(
                    f"report: item {item.get('id')}'s leading citation "
                    f"{citation.get('file')!r} is not one of the parts the "
                    "manifest cites"
                )
            continue
        if not isinstance(entry, dict):
            failures.add(
                f"report: item {item.get('id')} is `met` but the manifest cites "
                "nothing for it"
            )
            continue
        if citation.get("file") != entry.get("file"):
            failures.add(
                f"report: item {item.get('id')} cites {citation.get('file')!r}, "
                f"manifest cites {entry.get('file')!r}"
            )
        if citation.get("content_hash") != entry.get("content_hash"):
            failures.add(
                f"report: item {item.get('id')} citation hash "
                f"{citation.get('content_hash')!r} != manifest pin "
                f"{entry.get('content_hash')!r}"
            )

    met = sum(1 for item in items if item.get("tier") == "T1" and item.get("status") == "met")
    if report_doc.get("t1_met_count") != met:
        failures.add(
            f"report: t1_met_count {report_doc.get('t1_met_count')} != the {met} "
            "T1 rows actually rendered `met`"
        )
    print(f"  ok  report renders {len(t1_ids)} T1 items, {met} met")


def check_characterization(manifest_evidence: dict, failures: Failures) -> None:
    """Item 8's report is cited for item 8 only, and still reproduces.

    The characterization report aggregates harness-native records; it is not
    a `klt sim` / `klt yield` envelope and must never stand in for items 5 or
    6 (klt would render a generic citation there `wrong_kind`, but a
    mis-keyed citation is exactly what this register exists to stop before
    it reaches the grader). And because the envelope only binds the bytes of
    one minted record, the record itself is re-derived from the evidence it
    selects -- offline, no ngspice, no PDK -- so a selected record that moved
    fails here rather than leaving a stale report cited.
    """
    for key, entry in manifest_evidence.items():
        parts = entry if isinstance(entry, list) else [entry]
        for part in parts:
            cited = part.get("file") if isinstance(part, dict) else None
            if (
                isinstance(cited, str)
                and (cited == CHARACTERIZATION_ENVELOPE or cited.startswith("signoff/characterization/"))
                and key != CHARACTERIZATION_ITEM
            ):
                failures.add(
                    f"manifest: evidence[{key!r}] cites the characterization report "
                    f"({cited}); it is item {CHARACTERIZATION_ITEM} evidence only and "
                    "must not be cited for any other item (in particular not 5 or 6)"
                )
    entry = manifest_evidence.get(CHARACTERIZATION_ITEM)
    if entry is None:
        return
    if not isinstance(entry, dict) or entry.get("file") != CHARACTERIZATION_ENVELOPE:
        failures.add(
            f"manifest: evidence[{CHARACTERIZATION_ITEM!r}] must cite "
            f"{CHARACTERIZATION_ENVELOPE} (the envelope generate.py --mint writes)"
        )
        return
    try:
        completed = subprocess.run(
            [sys.executable, str(CHARACTERIZATION_GENERATOR), "--check"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        failures.add(f"characterization: could not run {rel(CHARACTERIZATION_GENERATOR)} --check ({exc})")
        return
    for line in completed.stdout.splitlines():
        print(f"  {line.strip()}")
    if completed.returncode != 0:
        failures.add(
            "characterization: the cited report does not reproduce from its selected "
            f"evidence (generate.py --check exited {completed.returncode})"
            + (f"\n{completed.stderr.strip()}" if completed.stderr.strip() else "")
        )


def klt_pin() -> str | None:
    try:
        lines = KLT_PIN.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def klt_command() -> list[str]:
    """How to invoke `klt`, pinned.

    `$KLT_SIGNOFF_CMD` (shell-style, space separated) overrides. Otherwise a
    `klt` on PATH is used when present, and failing that `uvx` runs the pinned
    revision in a throwaway environment -- the same revision CI installs, so a
    local re-grade and a CI re-grade compare the same checklist.
    """
    override = os.environ.get("KLT_SIGNOFF_CMD", "").strip()
    if override:
        return override.split()
    if _which("klt"):
        return ["klt"]
    pin = klt_pin()
    if pin and _which("uvx"):
        return [
            "uvx",
            "--from",
            f"git+https://github.com/2AMLogic/klayout-tools@{pin}",
            "klt",
        ]
    return ["klt"]


def _which(binary: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def run_klt(report_doc, failures: Failures) -> None:
    """Re-grade the manifest with klt and diff against the committed report."""
    command = klt_command() + [
        "signoff",
        "--manifest",
        str(MANIFEST.relative_to(REPO_ROOT)),
        "--format",
        "json",
    ]
    print(f"  running: {' '.join(command)}")
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),  # evidence paths resolve against the process cwd
            capture_output=True,
            text=True,
            timeout=900,
        )
    except OSError as exc:
        failures.add(f"klt re-grade: could not run {command[0]} ({exc})")
        return
    except subprocess.TimeoutExpired:
        failures.add("klt re-grade: timed out after 900s")
        return

    # Exit 3 is `tier: null` -- the report rendered, the block is simply not T1
    # yet, which is this block's current state and not an error. Only 1
    # (unreadable manifest/tier doc) and 2 (usage) mean no report was produced.
    if completed.returncode not in (0, 3):
        failures.add(
            f"klt re-grade: exited {completed.returncode}\n{completed.stderr.strip()}"
        )
        return
    try:
        fresh = json.loads(completed.stdout)
    except ValueError as exc:
        failures.add(f"klt re-grade: stdout is not valid JSON ({exc})")
        return

    for field in ("block", "kind", "tier", "t1_item_count", "t1_met_count"):
        if fresh.get(field) != report_doc.get(field):
            failures.add(
                f"klt re-grade: {field} is now {fresh.get(field)!r}, committed "
                f"report says {report_doc.get(field)!r}"
            )

    committed_items = {
        (item.get("tier"), item.get("id"), item.get("partition")): item
        for item in report_doc.get("items", [])
    }
    fresh_items = {
        (item.get("tier"), item.get("id"), item.get("partition")): item
        for item in fresh.get("items", [])
    }
    for key in sorted(set(committed_items) | set(fresh_items), key=lambda k: (k[0], k[1] or 0)):
        old = committed_items.get(key)
        new = fresh_items.get(key)
        label = f"{key[0]} item {key[1]}" + (f" ({key[2]})" if key[2] else "")
        if old is None or new is None:
            failures.add(
                f"klt re-grade: {label} is present in only one of the two reports"
            )
            continue
        for field in ("status", "reason"):
            if old.get(field) != new.get(field):
                failures.add(
                    f"klt re-grade: {label} {field} is now {new.get(field)!r}, "
                    f"committed report says {old.get(field)!r}"
                )
        old_cite = old.get("citation") or {}
        new_cite = new.get("citation") or {}
        for field in CITATION_FIELDS:
            if old_cite.get(field) != new_cite.get(field):
                failures.add(
                    f"klt re-grade: {label} citation.{field} is now "
                    f"{new_cite.get(field)!r}, committed report says "
                    f"{old_cite.get(field)!r}"
                )
        for field in ("coverage", "body_bias"):
            if old_cite.get(field) != new_cite.get(field):
                failures.add(
                    f"klt re-grade: {label} citation.{field} changed -- the cited "
                    "envelope's reported coverage no longer matches the record, "
                    "so signoff/README.md's disclosure is stale"
                )
    if not failures:
        print("  ok  klt re-grade matches the committed report verbatim")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-klt",
        action="store_true",
        help="also re-run `klt signoff --manifest` and diff it against the "
        "committed report (needs klt, or uvx + network)",
    )
    args = parser.parse_args(argv)

    failures = Failures()

    print(f"== signoff manifest ({rel(MANIFEST)}) ==")
    manifest = load_json(MANIFEST, failures, "manifest")
    manifest_evidence = check_manifest(manifest, failures) if manifest is not None else {}
    if manifest is not None and not failures:
        print(
            f"  ok  block={manifest.get('block')!r} kind={manifest.get('kind')!r}, "
            f"{len(manifest_evidence)} item(s) cited"
        )

    print(f"== pinned inputs ({rel(PINNED_INPUTS)}) ==")
    check_pins(manifest_evidence, failures)

    print("== LVS reference freshness (T1 items 4, 11) ==")
    check_lvs_reference(manifest_evidence, failures)

    print("== characterization report (T1 item 8) ==")
    check_characterization(manifest_evidence, failures)

    print(f"== verdict of record ({rel(REPORTS_DIR)}) ==")
    report_path = latest_report(failures)
    report_doc = None
    if report_path is not None:
        print(f"  record: {rel(report_path)}")
        report_doc = load_json(report_path, failures, "report")
        if report_doc is not None and manifest is not None:
            check_report(report_doc, manifest, manifest_evidence, failures)

    if args.run_klt:
        print("== klt re-grade ==")
        if report_doc is None:
            failures.add("klt re-grade: no committed report to compare against")
        else:
            run_klt(report_doc, failures)

    print()
    if failures:
        print(f"FAIL: signoff checks found {len(failures.messages)} problem(s).")
        return 1
    print("PASS: signoff manifest, pins and verdict of record are consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

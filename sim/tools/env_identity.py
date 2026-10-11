#!/usr/bin/env python3
"""Run-time PDK/model identity sidecar for finalized simulation records (#191).

Stdlib only. `capture` needs the installed PDK (it hashes the SPICE model/
include closure the run loads); `verify` and `identity_of` are pure functions
of the sidecar JSON and `sim/pdk.json` and need no PDK, simulator or network,
so offline report generation can check a committed sidecar.

Sidecar contract (`sim/<bench>/records/<record-id>.env.json`), schema
`sg13g2-opamp/env-identity/1`:

  record_id            the record this sidecar is bound to
  configured           {source, release_tag, variant}   -- what sim/pdk.json
                       ASSERTS at capture time (configuration, not evidence)
  observed             {release_marker, ngspice}        -- what the install
                       and simulator REPORTED (<PDK>/.fetched-version, ngspice -v)
  models               {roots, files: [{path, sha256}], unresolved}
                       the resolved .lib/.include closure of the SPICE model
                       files the run loads; `path` is relative to the PDK
                       install root, so host paths never define identity
  osdi                 {manifest_sha256, manifest_schema}
                       identity of the sim/tools/build-osdi.sh `.build-manifest`
                       (binds the Verilog-A inputs and compiled .osdi outputs)
  identity_sha256      sha256 over canonical JSON of {models.files, osdi}

Two installs with the same release marker but different model bytes therefore
have different `identity_sha256`. An install path alone cannot satisfy it.

CLI:
  env_identity.py capture --pdk-root R --pdk P --pin sim/pdk.json --record-id ID
                          --ngspice ngspice-46 --model cornerMOSlv.lib ... --out F
  env_identity.py verify  --sidecar F --pin sim/pdk.json [--record-id ID]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "sg13g2-opamp/env-identity/1"
SIDECAR_SUFFIX = ".env.json"
MODELS_SUBDIR = "libs.tech/ngspice/models"
OSDI_MANIFEST_REL = "libs.tech/ngspice/osdi/.build-manifest"
DEFAULT_MODELS = ("cornerMOSlv.lib", "cornerCAP.lib")
_DIRECTIVE_RE = re.compile(r'^\s*\.(lib|include|inc)\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))(\s+\S+)?', re.IGNORECASE)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class IdentityError(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def identity_of(models_files: list, osdi: dict) -> str:
    """The identity digest: model closure bytes + OSDI build manifest. No paths outside the PDK root."""
    payload = {
        "models": [[f["path"], f["sha256"]] for f in sorted(models_files, key=lambda f: f["path"])],
        "osdi_manifest_sha256": osdi.get("manifest_sha256"),
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def resolve_closure(install: Path, roots: list[str]) -> tuple[list[dict], list[str]]:
    """Follow .lib/.include directives from `roots` (names under the models dir)."""
    files: dict[str, str] = {}
    unresolved: list[str] = []
    install = install.resolve()
    queue = [(install / MODELS_SUBDIR / r) for r in roots]
    seen: set[Path] = set()
    while queue:
        path = queue.pop()
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        try:
            rel = path.relative_to(install).as_posix()
        except ValueError:
            unresolved.append(f"outside-install:{path.name}")
            continue
        if not path.is_file():
            unresolved.append(rel)
            continue
        data = path.read_bytes()
        files[rel] = sha256_bytes(data)
        for line in data.decode("utf-8", errors="replace").splitlines():
            m = _DIRECTIVE_RE.match(line)
            if not m:
                continue
            quoted = bool(m.group(2) or m.group(3))
            if m.group(1).lower() == "lib" and not quoted and not m.group(5):
                continue  # `.lib <section>` opens a section definition, it names no file
            target = m.group(2) or m.group(3) or m.group(4)
            if re.search(r"[$@{]", target):
                continue  # parameter expression, not a file
            cand = Path(target)
            queue.append(cand if cand.is_absolute() else path.parent / cand)
    return [{"path": p, "sha256": files[p]} for p in sorted(files)], sorted(set(unresolved))


def capture(pdk_root: Path, pdk: str, pin: dict, record_id: str, ngspice: str, models=DEFAULT_MODELS) -> dict:
    install = Path(pdk_root) / pdk
    if not install.is_dir():
        raise IdentityError(f"no PDK install at {install}")
    files, unresolved = resolve_closure(install, list(models))
    manifest = install / OSDI_MANIFEST_REL
    osdi: dict = {"manifest_sha256": None, "manifest_schema": None}
    if manifest.is_file():
        raw = manifest.read_bytes()
        osdi["manifest_sha256"] = sha256_bytes(raw)
        m = re.search(rb"^schema=(\S+)$", raw, re.MULTILINE)
        osdi["manifest_schema"] = m.group(1).decode() if m else None
    marker_file = install / ".fetched-version"
    marker = marker_file.read_text(encoding="utf-8").strip() if marker_file.is_file() else None
    return {
        "schema": SCHEMA,
        "record_id": record_id,
        "configured": {k: pin.get(k) for k in ("source", "release_tag", "variant")},
        "observed": {"release_marker": marker, "ngspice": ngspice},
        "models": {"roots": sorted(models), "files": files, "unresolved": unresolved},
        "osdi": osdi,
        "identity_sha256": identity_of(files, osdi),
    }


def _release_of(tag) -> str | None:
    return tag[1:] if isinstance(tag, str) and tag.startswith("v") else tag if isinstance(tag, str) else None


def verify(sidecar, pin: dict, record_id: str | None = None, ngspice: str | None = None) -> list[str]:
    """Explicit provenance errors for a sidecar; empty list means verified and compatible."""
    if not isinstance(sidecar, dict):
        return ["sidecar is not a JSON object"]
    if sidecar.get("schema") != SCHEMA:
        return [f"sidecar schema is {sidecar.get('schema')!r}, expected {SCHEMA!r}"]
    errs: list[str] = []
    cfg, obs = sidecar.get("configured"), sidecar.get("observed")
    models, osdi = sidecar.get("models"), sidecar.get("osdi")
    if not isinstance(cfg, dict) or not isinstance(obs, dict) or not isinstance(models, dict) or not isinstance(osdi, dict):
        return ["sidecar is malformed: configured/observed/models/osdi must all be objects"]
    files = models.get("files")
    if not isinstance(files, list) or not files or not all(
        isinstance(f, dict) and isinstance(f.get("path"), str) and isinstance(f.get("sha256"), str) and _SHA_RE.match(f["sha256"])
        for f in files
    ):
        return ["sidecar is malformed: models.files must be a non-empty list of {path, sha256}"]
    if any(f["path"].startswith("/") or ".." in Path(f["path"]).parts for f in files):
        errs.append("sidecar model paths must be relative to the PDK install root (host paths cannot define identity)")
    if models.get("unresolved"):
        errs.append(f"model closure has unresolved includes: {models['unresolved']}")
    if not (isinstance(osdi.get("manifest_sha256"), str) and _SHA_RE.match(osdi["manifest_sha256"])):
        errs.append("sidecar carries no OSDI build-manifest identity (osdi.manifest_sha256)")
    if not isinstance(sidecar.get("identity_sha256"), str) or sidecar["identity_sha256"] != identity_of(files, osdi):
        errs.append("identity_sha256 does not match the recorded model closure and OSDI manifest (tampered or corrupt)")
    if record_id is not None and sidecar.get("record_id") != record_id:
        errs.append(f"sidecar is bound to record {sidecar.get('record_id')!r}, not {record_id!r}")
    # compatibility with the CURRENT configured baseline
    for key in ("source", "release_tag"):
        if cfg.get(key) != pin.get(key):
            errs.append(f"incompatible: record was run against configured {key} {cfg.get(key)!r}, sim/pdk.json now says {pin.get(key)!r}")
    marker = obs.get("release_marker")
    if not marker:
        errs.append("sidecar carries no observed release marker (install .fetched-version)")
    elif marker != _release_of(pin.get("release_tag")):
        errs.append(f"incompatible: observed install release {marker!r} is not the configured release {pin.get('release_tag')!r}")
    want_ngspice = ngspice or (pin.get("osdi_toolchain") or {}).get("ngspice_actually_used")
    if want_ngspice and obs.get("ngspice") != want_ngspice:
        errs.append(f"incompatible: observed simulator {obs.get('ngspice')!r}, expected {want_ngspice!r}")
    return errs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--pdk-root", type=Path, required=True)
    c.add_argument("--pdk", required=True)
    c.add_argument("--pin", type=Path, required=True)
    c.add_argument("--record-id", required=True)
    c.add_argument("--ngspice", required=True)
    c.add_argument("--model", action="append", default=None)
    c.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--sidecar", type=Path, required=True)
    v.add_argument("--pin", type=Path, required=True)
    v.add_argument("--record-id")
    a = ap.parse_args(argv)
    try:
        pin = json.loads(a.pin.read_text(encoding="utf-8"))
        if a.cmd == "capture":
            side = capture(a.pdk_root, a.pdk, pin, a.record_id, a.ngspice, tuple(a.model or DEFAULT_MODELS))
            errs = verify(side, pin, a.record_id, a.ngspice)
            if errs:
                for e in errs:
                    print(f"env_identity: {e}", file=sys.stderr)
                return 1
            if a.out.exists():
                print(f"env_identity: refusing to overwrite {a.out}", file=sys.stderr)
                return 1
            a.out.write_text(canonical_json(side), encoding="utf-8")
            print(f"env_identity: wrote {a.out} (identity {side['identity_sha256'][:12]})")
            return 0
        errs = verify(json.loads(a.sidecar.read_text(encoding="utf-8")), pin, a.record_id)
    except (OSError, ValueError, IdentityError) as exc:
        print(f"env_identity: {exc}", file=sys.stderr)
        return 1
    for e in errs:
        print(f"env_identity: {e}", file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

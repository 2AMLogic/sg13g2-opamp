"""Records: the committed evidence loaders and their per-point validity state.

Split out of generate.py (issue #355). `load_record` reads one selected
`sim/*/records/*.csv` (+ `.md`), loads whichever raw population its definition
check needs, and returns the validity state row grading consumes.

Depends on `common`, `paths`, `defchecks` and `rows`. The relocated `klt` trio
(`_load_klt_population`, `_klt_corner_ids`, `_klt_values`) sat inside the
definition-checks banner in the single-file version but belongs to this
family -- it is a population loader, and moving it here is what keeps
`defchecks` from depending on this module and on `rows`.

Stdlib only; reads committed files, never re-simulates.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from common import (
    KLT_RAW_KINDS,
    NGSPICE_RE,
    OFFSET_KLT_RAW_KINDS,
    NOISE_PIN_KINDS,
    SLEW_KLT_KINDS,
    SLEW_KLT_LIMITS,
    SLEW_KLT_MEASUREMENTS,
    SLEW_KLT_SPICE,
    SLEW_PIN_KINDS,
    SWING_PIN_KINDS,
    canonical_json,
    normalized_netlist_hash,
    parse_decimal,
    sha256_bytes,
    sha256_file,
)
from defchecks import DEFINITION_CHECKS
from paths import (
    draws_contract,
    env_identity,
    mc_samples,
    noise_post,
    slew_post,
    swing_post,
)
from rows import parse_capacitance, source_cl_statements

KLT_AC_MEASUREMENTS = {
    "av0_db": ".meas ac av0_db find vdb(out) at=1",
    "gbw_hz": ".meas ac gbw_hz when vdb(out)=0",
    "phase_at_ugf_rad": ".meas ac phase_at_ugf_rad find vp(out) when vdb(out)=0",
}
KLT_OP_PORT_MEASUREMENTS = {
    "ivdd_total_a": "-i(vdd)",
    "vout_dc_v": "v(out)",
    "op_vcm_frac": "v(inp)/v(vdd)",
    "op_vout_offset_frac": "abs(v(out) - v(vdd)/2)/v(vdd)",
    "op_vout_rail_frac": "v(out)/v(vdd)",
}
KLT_OP_INTERNAL_MEASUREMENTS = {
    "vd1_dc_v": "v(d1)",
    "vd2_dc_v": "v(d2)",
    "vtail_dc_v": "v(tail)",
    "vibias_dc_v": "v(ibias)",
    "op_vd1_rail_frac": "v(d1)/v(vdd)",
    "op_vd2_rail_frac": "v(d2)/v(vdd)",
    "op_vtail_rail_frac": "v(tail)/v(vdd)",
}
KLT_OP_MEASUREMENTS = KLT_OP_PORT_MEASUREMENTS
# Issue #513: the slew summary columns the batch envelope cannot derive (it
# returns crossings, not a waveform); only slew_raw_audit recomputes them.
SLEW_WAVEFORM_ONLY_COLUMNS = ("vout_min_v", "vout_max_v", "window_lo_v", "window_hi_v")
KLT_REQUIRED_OSDI = ("psp103.osdi", "psp103_nqs.osdi", "mosvar.osdi", "r3_cmc.osdi")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
KLT_BENCH_ELEMENTS = {
    "Lbreak": r"Lbreak\s+inn\s+out\s+1e18",
    "Cinn_acgnd": r"Cinn_acgnd\s+inn\s+vss\s+1",
    "Iibias": r"Iibias\s+vdd\s+ibias\s+dc\s+10u",
    "Vinp": r"Vinp\s+inp\s+0\s+dc\s+\S+\s+ac\s+1",
}
_KLT_CLOAD_RE = re.compile(r"^Cload\s+out\s+vss\s+(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


def _klt_corner_ids(env: dict, label: str, expected_ids: list, problems: list) -> dict:
    """{point_id: corner} for an envelope, refusing duplicates, missing or
    extra points, and any errored, inconclusive or diagnostic-bearing corner."""
    out: dict = {}
    for corner in env.get("corners") or []:
        try:
            pid = f"{corner['process']}_{int(corner['temperature_c'])}C_{float(corner['supply_v']['vdd']):.2f}V"
        except (KeyError, TypeError, ValueError):
            problems.append(f"{label}: a corner has no process/temperature/vdd identity")
            continue
        if pid in out:
            problems.append(f"{label}: duplicate corner {pid}")
        out[pid] = corner
        if corner.get("status") not in ("pass", "fail") or corner.get("diagnostics"):
            problems.append(f"{label}: point {pid} is not a clean pass (status {corner.get('status')!r}, {len(corner.get('diagnostics') or [])} diagnostic(s))")
    for pid in expected_ids:
        if pid not in out:
            problems.append(f"{label}: no corner for point {pid}")
    for pid in sorted(set(out) - set(expected_ids)):
        problems.append(f"{label}: corner {pid} is outside the expected grid")
    return out


def _klt_values(corner: dict, wanted) -> dict:
    got = {m.get("name"): m.get("value") for m in corner.get("measurements") or []}
    return {name: got.get(name) for name in wanted}


def _klt_osdi_map(env: dict, label: str, problems: list) -> dict[str, str]:
    environment = env.get("environment") or {}
    entries = environment.get("osdi_preload")
    runner_entries = environment.get("osdi_preload_runner_resolved")
    raw_list = entries if isinstance(entries, list) else runner_entries if isinstance(runner_entries, list) else None
    if raw_list is None:
        problems.append(f"{label}: missing OSDI preload hashes (osdi_preload / osdi_preload_runner_resolved)")
        return {}
    by_name: dict[str, str] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            problems.append(f"{label}: malformed OSDI preload entry")
            continue
        name = item.get("name")
        if not isinstance(name, str) and isinstance(item.get("entry"), str):
            name = Path(item["entry"]).name
        if not isinstance(name, str) or not name:
            problems.append(f"{label}: malformed OSDI preload entry")
            continue
        sha = item.get("sha256")
        if not isinstance(sha, str) or not _HEX64_RE.match(sha):
            problems.append(f"{label}: OSDI binary {name!r} lacks a sha256")
            continue
        by_name[name] = sha
    if isinstance(entries, list) and isinstance(runner_entries, list):
        runner_map = {
            Path(i["entry"]).name: i.get("sha256")
            for i in runner_entries
            if isinstance(i, dict) and isinstance(i.get("entry"), str)
        }
        if runner_map != by_name:
            problems.append(f"{label}: osdi_preload and osdi_preload_runner_resolved disagree")
    missing = [m for m in KLT_REQUIRED_OSDI if m not in by_name]
    if missing:
        problems.append(f"{label}: missing required OSDI preload model(s) {missing}")
    return by_name


def _load_klt_population(repo: Path, key: str, kr: dict, expected: list, snapshot_rel: str,
                         md_text: str, records: dict, errors: list) -> dict | None:
    """Pin-check and strictly cross-check the open-loop `klt sim` evidence and
    return the per-point raw values (KLT_AUDIT_RULE). None when anything is
    wrong; problems name the artifact and point."""
    n_err = len(errors)
    expected_ids = [pid for pid, _ in expected]
    docs: dict = {}
    for kind in KLT_RAW_KINDS:
        if kind not in kr["files"]:
            continue
        pin = kr["files"][kind]
        path = repo / pin["path"]
        if not path.is_file():
            errors.append(f"record {key}: missing raw klt artifact {kind} {pin['path']}")
            continue
        actual = sha256_file(path)
        if actual != pin["sha256"]:
            errors.append(
                f"record {key}: {pin['path']} does not match its selection pin "
                f"(pinned {pin['sha256']}, actual {actual}) -- re-select deliberately, never re-read silently"
            )
            continue
        try:
            text = path.read_text(encoding="utf-8")
            docs[kind] = text if kind == "bench_body" else json.loads(text)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"record {key}: cannot read {pin['path']} ({exc})")
    if len(errors) > n_err:
        return None
    problems: list[str] = []
    snap = repo / snapshot_rel
    snap_hash = sha256_file(snap) if snap.is_file() else None
    snap_norm = normalized_netlist_hash(snap) if snap.is_file() else None
    body_pin = kr["files"]["bench_body"]
    envs = {}
    for kind in ("ac", "op"):
        env = docs[kind]
        label = f"{kind} envelope {kr['files'][kind]['path']}"
        if not isinstance(env, dict):
            problems.append(f"{label}: not an object")
            continue
        for field in ("errored", "inconclusive"):
            if env.get(field) != 0:
                problems.append(f"{label}: {field} = {env.get(field)!r}")
        if (env.get("diagnostic_counts") or {}).get("corners_with_diagnostics") != 0:
            problems.append(f"{label}: corners carry diagnostics")
        remote = (env.get("environment") or {}).get("remote") or {}
        if not remote.get("job_id"):
            problems.append(f"{label}: no environment.remote.job_id (not a batch run)")
        corners = _klt_corner_ids(env, label, expected_ids, problems)
        count = env.get("corner_count")
        n_pass = sum(1 for c in corners.values() if c.get("status") == "pass")
        n_fail = sum(1 for c in corners.values() if c.get("status") == "fail")
        if (
            env.get("status") not in ("pass", "fail")
            or count != len(expected_ids)
            or n_pass + n_fail != len(expected_ids)
            or env.get("passed") != n_pass
            or env.get("failed") != n_fail
            or env.get("status") != ("pass" if n_fail == 0 else "fail")
        ):
            problems.append(
                f"{label}: status {env.get('status')!r}, passed={env.get('passed')!r}, "
                f"failed={env.get('failed')!r} of {count!r} disagrees with the {len(expected_ids)}-corner grid "
                f"({n_pass} pass, {n_fail} fail)"
            )
        envs[kind] = {"env": env, "corners": corners, "label": label}
    if problems:
        errors.extend(f"record {key}: klt raw evidence: {p}" for p in problems)
        return None

    ac_env, op_env = envs["ac"]["env"], envs["op"]["env"]
    ea, eo = ac_env["environment"], op_env["environment"]
    if ea.get("engine") != "ngspice" or ea.get("engine") != eo.get("engine") or ea.get("engine_version") != eo.get("engine_version"):
        problems.append(f"the two envelopes disagree on the engine ({ea.get('engine')} {ea.get('engine_version')} vs {eo.get('engine')} {eo.get('engine_version')})")
    version = str(ea.get("engine_version") or "")
    if not re.fullmatch(r"\d+", version):
        problems.append(f"unreadable engine_version {ea.get('engine_version')!r}")
    for kind, env in (("ac", ac_env), ("op", op_env)):
        e = env["environment"]
        for b_label, banner in (
            ("worker banner", ((e.get("remote") or {}).get("worker_environment") or {}).get("simulator", {}).get("version_banner")),
            ("engine_build banner", (e.get("engine_build") or {}).get("version_banner")),
        ):
            if banner is not None and sorted(set(NGSPICE_RE.findall(banner))) != [version]:
                problems.append(f"{kind} envelope: {b_label} does not name ngspice-{version}")
    if ea.get("models_lib_sha256") != eo.get("models_lib_sha256") or not ea.get("models_lib_sha256"):
        problems.append("the two envelopes disagree on the model deck hash")
    ac_osdi = _klt_osdi_map(ac_env, "ac envelope", problems)
    op_osdi = _klt_osdi_map(op_env, "op envelope", problems)
    if ac_osdi and op_osdi and ac_osdi != op_osdi:
        problems.append("the two envelopes disagree on the preloaded OSDI binary hashes")
    ac_csl = {(x.get("name"), x.get("sha256")) for x in ea.get("corner_section_libs") or [] if isinstance(x, dict)}
    op_csl = {(x.get("name"), x.get("sha256")) for x in eo.get("corner_section_libs") or [] if isinstance(x, dict)}
    if ac_csl != op_csl:
        problems.append("the two envelopes disagree on corner_section_libs")
    for kind, env in (("ac", ac_env), ("op", op_env)):
        prov = env.get("provenance") or {}
        if (prov.get("pdk") or {}).get("name") != "ihp-sg13g2":
            problems.append(f"{kind} envelope: PDK is {(prov.get('pdk') or {}).get('name')!r}, not ihp-sg13g2")
        deck = prov.get("deck") or {}
        if deck.get("name") != "cornerMOSlv.lib" or deck.get("content_hash") != "sha256:" + str(env["environment"].get("models_lib_sha256")):
            problems.append(f"{kind} envelope: model deck identity {deck.get('name')!r} {deck.get('content_hash')!r} is not cornerMOSlv.lib at the recorded models_lib_sha256")
        closure = {c.get("path"): c.get("sha256") for c in env["environment"].get("netlist_closure") or []}
        if closure.get(snapshot_rel) is None or "sha256:" + str(closure[snapshot_rel]) != snap_hash:
            problems.append(f"{kind} envelope: simulated DUT {snapshot_rel} (closure sha256 {closure.get(snapshot_rel)}) is not the selected netlist snapshot ({snap_hash})")
        if "sha256:" + str(closure.get(body_pin["path"])) != body_pin["sha256"] or "sha256:" + str(env["environment"].get("netlist_sha256")) != body_pin["sha256"]:
            problems.append(f"{kind} envelope: simulated bench body is not the pinned {body_pin['path']}")
        if set(closure) - {body_pin["path"], snapshot_rel}:
            problems.append(f"{kind} envelope: unexpected extra netlist_closure entries {sorted(set(closure) - {body_pin['path'], snapshot_rel})}")
        if (env.get("netlist") or {}).get("path") != body_pin["path"]:
            problems.append(f"{kind} envelope: netlist path {(env.get('netlist') or {}).get('path')!r} is not the pinned bench body")
    # requests: the measurement definitions the audit relies on
    ac_req, op_req = docs["ac_request"], docs["op_request"]
    if (ac_req.get("analysis") or {}).get("kind") != "ac" or (ac_req.get("analysis") or {}).get("args") != "dec 20 1 1g":
        problems.append("ac request: analysis is not `ac dec 20 1 1g` (Av0 is read at 1 Hz)")
    if (op_req.get("analysis") or {}).get("kind") != "op":
        problems.append("op request: analysis is not `op`")
    ac_defs = {m.get("name"): m.get("spice") for m in ac_req.get("measurements") or []}
    for name, spice in KLT_AC_MEASUREMENTS.items():
        if ac_defs.get(name) != spice:
            problems.append(f"ac request: measurement {name} is {ac_defs.get(name)!r}, not {spice!r}")
    cont_key = kr.get("dc_continuity")
    op_defs = {m.get("name"): m.get("expr") for m in op_req.get("measurements") or []}
    schematic_op = (cont_key is None) or any(name in op_defs for name in KLT_OP_INTERNAL_MEASUREMENTS)
    required_op_defs = (
        {**KLT_OP_PORT_MEASUREMENTS, **KLT_OP_INTERNAL_MEASUREMENTS}
        if schematic_op
        else KLT_OP_PORT_MEASUREMENTS
    )
    for name, expr in required_op_defs.items():
        if op_defs.get(name) != expr:
            problems.append(f"op request: measurement {name} is {op_defs.get(name)!r}, not {expr!r}")
    for kind, req in (("ac", ac_req), ("op", op_req)):
        if Path(str(req.get("netlist"))).name != Path(body_pin["path"]).name:
            problems.append(f"{kind} request: netlist {req.get('netlist')!r} is not the pinned bench body")
    # bench body: load and the AC-grounded loop
    body = "\n".join(line for line in docs["bench_body"].splitlines() if not line.lstrip().startswith("*"))
    loads = _KLT_CLOAD_RE.findall(body)
    stated = {parse_capacitance(s)[0] for s in source_cl_statements(md_text)} - {None}
    if len(loads) != 1:
        problems.append(f"bench body: {len(loads)} Cload elements (need exactly one)")
    else:
        try:
            cload = Decimal(loads[0])
        except InvalidOperation:
            cload = None
        if cload is None or cload not in stated:
            problems.append(f"bench body: Cload {loads[0]} is not a CL the record's own prose states ({sorted(source_cl_statements(md_text))})")
    for name, pattern in KLT_BENCH_ELEMENTS.items():
        if len(re.findall(r"^" + pattern + r"\s*$", body, re.MULTILINE | re.IGNORECASE)) != 1:
            problems.append(f"bench body: element {name} is not present exactly once as `{pattern}`")

    # Optional DC continuity record (when comparing two configurations on the same DUT,
    # or standing in for internal-node OP on the archived port-only record).
    cont_rows: dict = {}
    if cont_key is not None:
        cont = records.get(cont_key) or {}
        cpath = repo / cont["csv"] if isinstance(cont.get("csv"), str) else None
        if cpath is None or not cpath.is_file():
            problems.append(f"dc_continuity record {cont_key}: CSV is missing")
        elif sha256_file(cpath) != cont.get("csv_sha256"):
            problems.append(f"dc_continuity record {cont_key}: {cont['csv']} does not match its selection pin")
        else:
            try:
                _, crows = read_csv_rows(cpath)
                cont_rows = {(r.get("point_id") or "").strip(): r for r in crows}
            except (OSError, UnicodeDecodeError, csv.Error) as exc:
                problems.append(f"dc_continuity record {cont_key}: cannot parse {cont['csv']} ({exc})")
        cont_snap_rel = cont.get("netlist_snapshot")
        cont_snap = repo / cont_snap_rel if isinstance(cont_snap_rel, str) else None
        if cont_snap is None or not cont_snap.is_file():
            problems.append(f"dc_continuity record {cont_key}: netlist_snapshot is missing")
        elif snap_norm is not None and normalized_netlist_hash(cont_snap) != snap_norm:
            problems.append(
                f"dc_continuity record {cont_key}: simulated netlist {cont_snap_rel} is not the same circuit as {snapshot_rel}"
            )

    has_measurement = "measurement" in docs
    measurement = {}
    if has_measurement:
        for corner in docs["measurement"].get("corners") or []:
            try:
                proc, vdd_s, temp_s = corner["corner_id"].split("/")
                pid = f"{proc}_{int(temp_s[:-1])}C_{float(vdd_s[:-1]):.2f}V"
            except (KeyError, ValueError, AttributeError):
                problems.append(f"measurement document: unreadable corner id {corner.get('corner_id')!r}")
                continue
            measurement[pid] = {m.get("name"): m.get("value") for m in corner.get("measurements") or []}
    op_wanted = tuple(required_op_defs)
    frac_keys = (
        ("op_vcm_frac", "op_vout_offset_frac", "op_vout_rail_frac", "op_vd1_rail_frac", "op_vd2_rail_frac", "op_vtail_rail_frac")
        if schematic_op
        else ("op_vcm_frac", "op_vout_offset_frac", "op_vout_rail_frac")
    )
    points: dict = {}
    for pid in expected_ids:
        a = _klt_values(envs["ac"]["corners"][pid], KLT_AC_MEASUREMENTS)
        o_corner = envs["op"]["corners"][pid]
        o = _klt_values(o_corner, op_wanted)
        bad = [n for n, v in (*a.items(), *o.items()) if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)]
        if bad:
            problems.append(f"point {pid}: missing or non-finite raw value(s) {bad}")
            continue
        sup = o_corner.get("supply_v") or {}
        if envs["ac"]["corners"][pid].get("supply_v") != sup:
            problems.append(f"point {pid}: the AC and OP envelopes use different supplies")
        op_statuses = {
            m.get("name"): m.get("status")
            for m in o_corner.get("measurements") or []
            if isinstance(m, dict) and str(m.get("name") or "").startswith("op_")
        }
        pt_entry = {
            "av0_db": a["av0_db"], "gbw_hz": a["gbw_hz"], "phase_rad": a["phase_at_ugf_rad"],
            "ivdd": o["ivdd_total_a"], "vout": o["vout_dc_v"], "vdd": sup.get("vdd"), "vinp": sup.get("vinp"),
            "schematic_op": schematic_op,
            "reported": {k: o[k] for k in frac_keys},
            "op_statuses": op_statuses,
            "has_measurement": has_measurement,
            "measurement": measurement.get(pid) if has_measurement else None,
            "continuity": cont_rows.get(pid) if cont_key is not None else None,
        }
        if schematic_op:
            pt_entry.update({
                "vout_dc_v": o["vout_dc_v"],
                "vd1_dc_v": o["vd1_dc_v"],
                "vd2_dc_v": o["vd2_dc_v"],
                "vtail_dc_v": o["vtail_dc_v"],
                "vibias_dc_v": o["vibias_dc_v"],
            })
        points[pid] = pt_entry
    if problems:
        errors.extend(f"record {key}: klt raw evidence: {p}" for p in problems)
        return None
    return {
        "points": points, "version": version, "continuity_record": cont_key,
        "schematic_op": schematic_op,
        "jobs": {k: envs[k]["env"]["environment"]["remote"]["job_id"] for k in ("ac", "op")},
        "ibias_a": 10e-6, "cload_f": float(loads[0]),
    }


# --------------------------------------------------------------------------
# records


def expected_points(grid: dict) -> list[tuple[str, dict]]:
    axes = grid["axes"]
    points = []
    for corner in axes["corner"]:
        for temp in axes["temp"]:
            for vdd in axes["vdd"]:
                values = {"corner": corner, "temp": temp, "vdd": vdd}
                points.append((grid["point_id"].format(**values), values))
    return points


def read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines) + "\n"))
    header = list(reader.fieldnames or [])
    return header, list(reader)


def point_is_valid(point: dict, conditions: list) -> str | None:
    """None when every validity flag holds, else why the point failed."""
    for column, op, operand in conditions:
        cell = (point.get(column) or "").strip()
        if op == "==":
            if cell != operand:
                return f"{column}={cell!r} (needs {operand!r})"
        elif op == "==col":
            if cell != (point.get(operand) or "").strip():
                return f"{column}={cell!r} != {operand}={point.get(operand)!r}"
        elif op == ">=":
            value, why = parse_decimal(cell)
            if value is None or value < Decimal(operand):
                return f"{column}={cell!r} (needs >= {operand})" + (f", {why}" if why else "")
    return None


PROV_LEGACY = "legacy-unverified"
PROV_VERIFIED = "verified"
PROV_ERROR = "error"
SIDECAR_OPTIONAL_KEYS = ("env_sidecar", "env_sidecar_sha256")


def check_pdk_provenance(repo: Path, key: str, spec: dict, env: dict, state: dict) -> None:
    """Bind a selected record to its pinned run-time PDK/model identity sidecar (#191).

    No sidecar selected -> the record is shown as legacy/unverified (its numbers
    and verdicts are unchanged; provenance is never invented). A sidecar that is
    selected must exist, match its pin, parse, belong to THIS record and be
    compatible with the configured baseline, or the record is an ERROR: it can
    never silently inherit the current PDK label.
    """
    prov = state["source"]["pdk_provenance"]
    errors = state["errors"]
    rel = spec.get("env_sidecar")
    if rel is None:
        if spec.get("env_sidecar_sha256") is not None:
            errors.append(f"record {key}: `env_sidecar_sha256` is set without an `env_sidecar`")
            prov["status"] = PROV_ERROR
        return
    prov.update({"status": PROV_ERROR, "sidecar": rel if isinstance(rel, str) else None})
    if not isinstance(rel, str):
        errors.append(f"record {key}: `env_sidecar` must be a path string")
        return
    path = repo / rel
    if not path.is_file():
        errors.append(f"record {key}: PDK provenance error: missing environment sidecar {rel}")
        return
    actual = sha256_file(path)
    prov["sidecar_sha256"] = actual
    if actual != spec.get("env_sidecar_sha256"):
        errors.append(
            f"record {key}: PDK provenance error: {rel} does not match its selection pin "
            f"(pinned {spec.get('env_sidecar_sha256')}, actual {actual}) -- re-select deliberately, never re-read silently"
        )
        return
    try:
        sidecar = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"record {key}: PDK provenance error: {rel} is not valid JSON ({exc})")
        return
    pin = env.get("pin")
    if not isinstance(pin, dict):
        errors.append(f"record {key}: PDK provenance error: no readable PDK pin to check {rel} against")
        return
    record_id = Path(spec["csv"]).stem
    problems = env_identity.verify(sidecar, pin, record_id, env.get("ngspice"))
    if problems:
        for problem in problems:
            errors.append(f"record {key}: PDK provenance error: {rel}: {problem}")
        return
    sidecar_ngspice = sidecar["observed"].get("ngspice")
    state["sidecar_ngspice"] = sidecar_ngspice
    if state["source"].get("ngspice") is not None and sidecar_ngspice != state["source"]["ngspice"]:
        errors.append(
            f"record {key}: {spec['md']} names {state['source']['ngspice']}, "
            f"but sidecar {rel} observed {sidecar_ngspice!r}"
        )
        return
    prov.update(
        {
            "status": PROV_VERIFIED,
            "identity_sha256": sidecar["identity_sha256"],
            "observed_release_marker": sidecar["observed"]["release_marker"],
            "configured_release": f"{sidecar['configured']['source']} {sidecar['configured']['release_tag']}",
            "model_files": len(sidecar["models"]["files"]),
            "osdi_manifest_sha256": sidecar["osdi"]["manifest_sha256"],
        }
    )


def _admit_ngspice_version(key: str, actual: str, env: dict, errors: list) -> None:
    """Apply the shared simulator policy in sim/tools/env_identity.py."""
    problem = env_identity.check_ngspice_version(actual, env.get("pin"), env.get("ngspice"))
    if problem:
        errors.append(
            f"record {key}: ran on {actual}, rejected by sim/pdk.json ({problem}) -- "
            "mixed simulation environments are not combined silently"
        )


def _carry_ngspice_version(key: str, src: dict, envelope_ngspice: str, origin_phrase: str, spec: dict, env: dict, errors: list) -> None:
    """Carry an envelope's simulator version into src["ngspice"]: establish it
    when nothing has yet (summary .md or an earlier envelope, whichever came
    first), otherwise require agreement, never overwrite. The envelope's
    version goes through the shared admission policy when it establishes or
    disagrees; on agreement the establishing site already admitted it, so a
    second admit would only duplicate the error."""
    if src["ngspice"] is None:
        src["ngspice"] = envelope_ngspice
        _admit_ngspice_version(key, envelope_ngspice, env, errors)
    elif src["ngspice"] != envelope_ngspice:
        errors.append(f"record {key}: {spec['md']} names {src['ngspice']}, but {origin_phrase} ran {envelope_ngspice}")
        _admit_ngspice_version(key, envelope_ngspice, env, errors)


def _load_sample_population(repo: Path, key: str, ms: dict, expected: list, records: dict, errors: list) -> dict | None:
    """Pin-check and strictly parse each grid point's raw sample file, and join
    Av0 from the pinned deterministic record. None when anything is wrong."""
    n_err = len(errors)
    files = ms["files"]
    expected_ids = [pid for pid, _ in expected]
    for pid in sorted(set(files) - set(expected_ids)):
        errors.append(f"record {key}: samples pinned for {pid!r}, which is outside the expected grid")
    points: dict = {}
    for pid in expected_ids:
        entry = files.get(pid)
        if entry is None:
            errors.append(f"record {key}: point {pid}: no pinned sample file (every grid point needs one)")
            continue
        path = repo / entry["path"]
        if not path.is_file():
            errors.append(f"record {key}: point {pid}: missing sample file {entry['path']}")
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            errors.append(
                f"record {key}: point {pid}: {entry['path']} does not match its selection pin "
                f"(pinned {entry['sha256']}, actual {actual}) -- re-select deliberately, "
                "never re-read silently"
            )
            continue
        try:
            n, ops, acs = mc_samples.read_samples(str(path))
        except (mc_samples.SampleError, OSError, UnicodeDecodeError) as exc:
            errors.append(f"record {key}: point {pid}: invalid sample population: {exc}")
            continue
        points[pid] = {"n": n, "ops": ops, "acs": acs}
    # Av0 join: the explicitly selected deterministic record, by pin.
    join_key = ms["av0_join"]
    join = records.get(join_key)
    av0: dict[str, float] = {}
    if join is None:
        errors.append(f"record {key}: av0_join {join_key!r} is not a selected record")
        join_csv = None
    else:
        join_csv = join.get("csv")
        jpath = repo / join_csv if isinstance(join_csv, str) else None
        if jpath is None or not jpath.is_file():
            errors.append(f"record {key}: Av0 join record {join_csv} is missing")
        elif sha256_file(jpath) != join.get("csv_sha256"):
            errors.append(f"record {key}: Av0 join record {join_csv} does not match its selection pin")
        else:
            try:
                _, jrows = read_csv_rows(jpath)
            except (OSError, UnicodeDecodeError, csv.Error) as exc:
                errors.append(f"record {key}: cannot parse Av0 join record {join_csv} ({exc})")
                jrows = []
            for row in jrows:
                jid = (row.get("point_id") or "").strip()
                try:
                    value = float(row["av0_db"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not math.isfinite(value):
                    continue
                if jid in av0:
                    errors.append(f"record {key}: Av0 join record {join_csv}: duplicate point {jid}")
                av0[jid] = value
            for pid in expected_ids:
                if pid not in av0:
                    errors.append(f"record {key}: point {pid}: no finite Av0 in the joined record {join_csv}")
    if len(errors) > n_err:
        return None
    return {
        "points": points,
        "av0": av0,
        "join_csv": join_csv,
        "acceptance": {
            "op_rail_frac": float(ms["acceptance"]["op_rail_frac"]),
            "op_mid_frac": float(ms["acceptance"]["op_mid_frac"]),
            "plateau_tol_db": float(ms["acceptance"]["plateau_tol_db"]),
        },
    }


def _check_raw_pins(key: str, noun: str, files: dict, expected_ids: list, kinds: tuple,
                    want_name, errors: list) -> None:
    """Pin-level checks shared by every raw-artifact family: no pin for a point
    outside the grid, no path pinned twice, and each filename belongs to its
    own point. `want_name(pid, kind)` is the family's filename rule."""
    for pid in sorted(set(files) - set(expected_ids)):
        errors.append(f"record {key}: raw {noun} artifacts pinned for {pid!r}, which is outside the expected grid")
    seen_paths: dict[str, str] = {}
    for pid in expected_ids:
        entry = files.get(pid)
        if entry is None:
            continue
        for kind in kinds:
            rel = entry[kind]["path"]
            owner = f"point {pid} {kind}"
            if rel in seen_paths:
                errors.append(f"record {key}: {rel} is pinned twice ({seen_paths[rel]} and {owner}); one raw artifact per point and kind")
            seen_paths[rel] = owner
            want = want_name(pid, kind)
            if Path(rel).name != want:
                errors.append(f"record {key}: point {pid}: {kind} pin names {rel}, which belongs to another point (expected file {want})")


def _read_pinned_raw(repo: Path, key: str, pid: str, noun: str, missing_phrase: str, entry,
                     kinds: tuple, errors: list) -> dict | None:
    """Read one grid point's pinned raw artifacts as UTF-8 text, refusing a
    missing file or a sha256 that does not match its selection pin. Returns
    {kind: text}, or None when the point has no pin or any artifact failed
    (problems are appended to `errors`)."""
    if entry is None:
        errors.append(f"record {key}: point {pid}: no pinned raw {noun} {missing_phrase}")
        return None
    texts = {}
    for kind in kinds:
        rel, pinned = entry[kind]["path"], entry[kind]["sha256"]
        path = repo / rel
        if not path.is_file():
            errors.append(f"record {key}: point {pid}: missing raw {noun} {kind} {rel}")
            continue
        actual = sha256_file(path)
        if actual != pinned:
            errors.append(
                f"record {key}: point {pid}: {rel} does not match its selection pin "
                f"(pinned {pinned}, actual {actual}) -- re-select deliberately, "
                "never re-read silently"
            )
            continue
        try:
            texts[kind] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"record {key}: point {pid}: cannot read {rel} ({exc})")
    return texts if len(texts) == len(kinds) else None


def _load_noise_population(repo: Path, key: str, nr: dict, expected: list, errors: list) -> dict | None:
    """Pin-check and strictly parse each grid point's raw noise log and in-band
    spectrum. None when anything is wrong; problems name point and file."""
    n_err = len(errors)
    files = nr["files"]
    expected_ids = [pid for pid, _ in expected]
    _check_raw_pins(
        key, "noise", files, expected_ids, NOISE_PIN_KINDS,
        lambda pid, kind: f"{pid}.log" if kind == "log" else f"{pid}_noise.csv",
        errors)
    points: dict = {}
    for pid in expected_ids:
        entry = files.get(pid)
        texts = _read_pinned_raw(
            repo, key, pid, "noise", "log/spectrum (every grid point needs both)", entry, NOISE_PIN_KINDS, errors)
        if texts is None:
            continue
        try:
            token, value = noise_post.parse_log_total(texts["log"], entry["log"]["path"])
        except noise_post.NoiseError as exc:
            errors.append(f"record {key}: point {pid}: invalid noise log: {exc}")
            continue
        try:
            freqs, dens = noise_post.parse_spectrum(texts["spectrum"], entry["spectrum"]["path"])
        except noise_post.NoiseError as exc:
            errors.append(f"record {key}: point {pid}: invalid noise spectrum: {exc}")
            continue
        points[pid] = {
            "token": token, "value": value, "freqs": freqs, "dens": dens,
            "log": entry["log"]["path"], "spectrum": entry["spectrum"]["path"],
        }
    return None if len(errors) > n_err else points


def _load_slew_population(repo: Path, key: str, sr: dict, expected: list, errors: list) -> dict | None:
    """Pin-check and strictly parse each grid point's transient waveform and
    rendered netlist, and refuse a netlist that disagrees with the pinned
    measurement configuration. None when anything is wrong; problems name
    point and file."""
    n_err = len(errors)
    files = sr["files"]
    cfg = {k: float(v) for k, v in sr["config"].items()}
    expected_ids = [pid for pid, _ in expected]
    _check_raw_pins(
        key, "slew", files, expected_ids, SLEW_PIN_KINDS,
        lambda pid, kind: f"{pid}_tran.csv" if kind == "tran" else f"{pid}.spice",
        errors)
    points: dict = {}
    for pid in expected_ids:
        entry = files.get(pid)
        texts = _read_pinned_raw(
            repo, key, pid, "slew", "waveform/netlist (every grid point needs both)", entry, SLEW_PIN_KINDS, errors)
        if texts is None:
            continue
        tran_rel, net_rel = entry["tran"]["path"], entry["netlist"]["path"]
        try:
            t, v = slew_post.parse_waveform(texts["tran"], tran_rel)
        except slew_post.SlewError as exc:
            errors.append(f"record {key}: point {pid}: invalid slew waveform: {exc}")
            continue
        try:
            rc = slew_post.rendered_config(texts["netlist"], net_rel)
        except slew_post.SlewError as exc:
            errors.append(f"record {key}: point {pid}: invalid rendered netlist: {exc}")
            continue
        bad = [
            f"{name} {rc[name]:g} (netlist) != {cfg[name]:g} (pinned config)"
            for name in ("t2_ns", "t3_ns", "tstop_ns") if rc[name] != cfg[name]
        ]
        if rc["tran_stop_ns"] != cfg["tstop_ns"]:
            bad.append(f".tran stop {rc['tran_stop_ns']:g} ns != tstop_ns {cfg['tstop_ns']:g} (pinned config)")
        if abs(2.0 * rc["vcm_v"] - rc["vdd_v"]) > 1e-9:
            bad.append(f"common mode {rc['vcm_v']:g} V is not VDD/2 of {rc['vdd_v']:g} V")
        if Path(rc["wrdata"]).name != Path(tran_rel).name:
            bad.append(f"wrdata target {Path(rc['wrdata']).name} is not the pinned waveform {Path(tran_rel).name}")
        if bad:
            errors.append(f"record {key}: point {pid}: measurement configuration mismatch in {net_rel}: " + "; ".join(bad))
            continue
        points[pid] = {
            "t": t, "v": v, "vdd": rc["vdd_v"], "vcm": rc["vcm_v"],
            "w_out": cfg["win_outer_v"], "w_in": cfg["win_inner_v"],
            "t2": cfg["t2_ns"] * 1e-9, "t3": cfg["t3_ns"] * 1e-9, "tstop": cfg["tstop_ns"] * 1e-9,
            "tran": tran_rel, "netlist": net_rel,
        }
    return None if len(errors) > n_err else points


def _load_slew_klt_population(repo: Path, key: str, sk: dict, expected: list, snapshot_rel: str,
                              md_text: str, errors: list) -> dict | None:
    """Pin-check and strictly cross-check the batch slew `klt sim` envelope
    (issue #501) and return the per-point raw values (SLEW_KLT_AUDIT_RULE).
    A corner that merely misses a limit is a clean (failing) corner; an
    errored/inconclusive/missing/duplicate/outside corner, a missing or
    non-finite measurement, a stale DUT or bench hash, or an inconsistent
    simulator version is an error naming the artifact, corner and field."""
    n_err = len(errors)
    expected_ids = [pid for pid, _ in expected]
    docs: dict = {}
    for kind in SLEW_KLT_KINDS:
        pin = sk["files"][kind]
        path = repo / pin["path"]
        if not path.is_file():
            errors.append(f"record {key}: missing batch slew artifact {kind} {pin['path']}")
            continue
        actual = sha256_file(path)
        if actual != pin["sha256"]:
            errors.append(
                f"record {key}: {pin['path']} does not match its selection pin "
                f"(pinned {pin['sha256']}, actual {actual}) -- re-select deliberately, never re-read silently"
            )
            continue
        try:
            text = path.read_text(encoding="utf-8")
            docs[kind] = text if kind == "bench_body" else json.loads(text)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"record {key}: cannot read {pin['path']} ({exc})")
    if len(errors) > n_err:
        return None
    env, req = docs["envelope"], docs["request"]
    label = f"envelope {sk['files']['envelope']['path']}"
    problems: list[str] = []
    if not isinstance(env, dict) or not isinstance(req, dict):
        errors.append(f"record {key}: slew klt evidence: envelope and request must be JSON objects")
        return None
    count = env.get("corner_count")
    if count != len(expected_ids) or env.get("status") not in ("pass", "fail") or (env.get("passed"), env.get("failed")) == (None, None) \
            or (env.get("passed") or 0) + (env.get("failed") or 0) != count:
        problems.append(f"{label}: status {env.get('status')!r}, {env.get('passed')} passed + {env.get('failed')} failed of {count} corners (need all {len(expected_ids)} decided)")
    for field in ("errored", "inconclusive"):
        if env.get(field) != 0:
            problems.append(f"{label}: {field} = {env.get(field)!r}")
    if (env.get("diagnostic_counts") or {}).get("corners_with_diagnostics") != 0:
        problems.append(f"{label}: corners carry diagnostics")
    e = env.get("environment") or {}
    remote = e.get("remote") or {}
    if not remote.get("job_id"):
        problems.append(f"{label}: no environment.remote.job_id (not a batch run)")
    version = e.get("engine_version")
    if e.get("engine") != "ngspice" or not version:
        problems.append(f"{label}: engine {e.get('engine')!r} {version!r} is not an identified ngspice")
    version = str(version)
    banner = ((remote.get("worker_environment") or {}).get("simulator") or {}).get("version_banner")
    if banner is not None and f"ngspice-{version}" not in banner:
        problems.append(f"{label}: worker banner does not name ngspice-{version} (contradictory simulator version)")
    stated = sorted(set(NGSPICE_RE.findall(md_text)))
    if stated and stated != [version]:
        problems.append(f"{label}: ran ngspice-{version} but the selected record's prose names {', '.join('ngspice-' + s for s in stated)}")
    prov = env.get("provenance") or {}
    if (prov.get("pdk") or {}).get("name") != "ihp-sg13g2":
        problems.append(f"{label}: PDK is {(prov.get('pdk') or {}).get('name')!r}, not ihp-sg13g2")
    deck = prov.get("deck") or {}
    if deck.get("name") != "cornerMOSlv.lib" or deck.get("content_hash") != "sha256:" + str(e.get("models_lib_sha256")):
        problems.append(f"{label}: model deck identity {deck.get('name')!r} {deck.get('content_hash')!r} is not cornerMOSlv.lib at the recorded models_lib_sha256")
    snap = repo / snapshot_rel
    snap_hash = sha256_file(snap) if snap.is_file() else None
    closure = {c.get("path"): c.get("sha256") for c in e.get("netlist_closure") or []}
    # the envelope names the DUT by its design path; match it by file name
    dut = {p: "sha256:" + str(h) for p, h in closure.items() if Path(p).name == Path(snapshot_rel).name}
    if not dut or set(dut.values()) != {snap_hash}:
        problems.append(f"{label}: simulated DUT {dut or sorted(closure)} is not the selected netlist snapshot {snapshot_rel} ({snap_hash})")
    body_pin = sk["files"]["bench_body"]
    body_path = (env.get("netlist") or {}).get("path")
    if body_path is None or "sha256:" + str(e.get("netlist_sha256")) != body_pin["sha256"] \
            or "sha256:" + str(closure.get(body_path)) != body_pin["sha256"]:
        problems.append(f"{label}: simulated bench body {body_path!r} is not the pinned {body_pin['path']}")
    if Path(str(req.get("netlist"))).name != Path(body_pin["path"]).name:
        problems.append(f"slew request: netlist {req.get('netlist')!r} is not the pinned bench body")
    if (req.get("analysis") or {}).get("kind") != "tran" or (req.get("analysis") or {}).get("args") != "1n 800n 0 0.05n":
        problems.append("slew request: analysis is not `tran 1n 800n 0 0.05n`")
    defs = {m.get("name"): m for m in req.get("measurements") or []}
    for name in SLEW_KLT_MEASUREMENTS:
        if name not in defs:
            problems.append(f"slew request: measurement {name} is not declared")
    for name, spice in SLEW_KLT_SPICE.items():
        if name in defs and defs[name].get("spice") != spice:
            problems.append(f"slew request: measurement {name} is {defs[name].get('spice')!r}, not {spice!r}")
    for name, limits in SLEW_KLT_LIMITS.items():
        if name in defs and defs[name].get("limits") != limits:
            problems.append(f"slew request: measurement {name} limits are {defs[name].get('limits')!r}, not {limits!r} (a validity bound is never relaxed)")
    body = "\n".join(line for line in docs["bench_body"].splitlines() if not line.lstrip().startswith("*"))
    loads = _KLT_CLOAD_RE.findall(body)
    cl_stated = {parse_capacitance(s)[0] for s in source_cl_statements(md_text)} - {None}
    if len(loads) != 1:
        problems.append(f"bench body: {len(loads)} Cload elements (need exactly one)")
    else:
        try:
            cload = Decimal(loads[0])
        except InvalidOperation:
            cload = None
        if cload is None or cload not in cl_stated:
            problems.append(f"bench body: Cload {loads[0]} is not a CL the record's own prose states ({sorted(source_cl_statements(md_text))})")
    # corners
    corners: dict = {}
    for corner in env.get("corners") or []:
        try:
            pid = f"{corner['process']}_{int(corner['temperature_c'])}C_{float(corner['supply_v']['vdd']):.2f}V"
        except (KeyError, TypeError, ValueError):
            problems.append(f"{label}: a corner has no process/temperature/vdd identity")
            continue
        if pid in corners:
            problems.append(f"{label}: duplicate corner {pid}")
        corners[pid] = corner
    for pid in expected_ids:
        if pid not in corners:
            problems.append(f"{label}: no corner for point {pid}")
    for pid in sorted(set(corners) - set(expected_ids)):
        problems.append(f"{label}: corner {pid} is outside the expected grid")
    points: dict = {}
    for pid in expected_ids:
        corner = corners.get(pid)
        if corner is None:
            continue
        if corner.get("status") not in ("pass", "fail") or corner.get("diagnostics"):
            problems.append(f"{label}: point {pid} is not a decided corner (status {corner.get('status')!r}, {len(corner.get('diagnostics') or [])} diagnostic(s))")
            continue
        got = {m.get("name"): m.get("value") for m in corner.get("measurements") or []}
        bad = [n for n in SLEW_KLT_MEASUREMENTS
               if not isinstance(got.get(n), (int, float)) or isinstance(got.get(n), bool) or not math.isfinite(got[n])]
        if bad:
            problems.append(f"point {pid}: missing or non-finite measurement(s) {bad} (no crossing, so no measurement exists)")
            continue
        sup = corner.get("supply_v") or {}
        vdd, vinp = sup.get("vdd"), sup.get("vinp")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (vdd, vinp)) or vdd <= 0 or abs(vinp - vdd / 2) > 1e-9:
            problems.append(f"point {pid}: supplies {sup!r} do not put Vcm at VDD/2")
            continue
        points[pid] = {"values": {n: float(got[n]) for n in SLEW_KLT_MEASUREMENTS}, "vdd": float(vdd), "vinp": float(vinp)}
    if problems:
        errors.extend(f"record {key}: slew klt evidence: {p}" for p in problems)
        return None
    return {
        "points": points, "version": version, "job": remote["job_id"],
        "envelope": sk["files"]["envelope"]["path"], "cload_f": float(loads[0]),
    }


_SWING_PID_RE = re.compile(r"^(?P<corner>.+)_(?P<temp>-?\d+(?:\.\d+)?)C_(?P<vdd>\d+(?:\.\d+)?)V$")


def _swing_pass_problems(pid: str, rc: dict, vectors: tuple, pass_label: str,
                         window: tuple, csv_rel: str) -> list[str]:
    """How one pinned rendered netlist disagrees with the pinned measurement
    configuration and the point it is pinned to."""
    parts = _SWING_PID_RE.match(pid)
    bad = []
    if parts is None:
        bad.append(f"point id {pid!r} is not <corner>_<temp>C_<vdd>V")
    else:
        if rc["corner"] != parts["corner"]:
            bad.append(f"corner {rc['corner']} (netlist) != {parts['corner']} (point id)")
        if rc["temp_c"] != float(parts["temp"]):
            bad.append(f"temperature {rc['temp_c']:g} (netlist) != {parts['temp']} (point id)")
        if rc["vdd_v"] != float(parts["vdd"]):
            bad.append(f"supply {rc['vdd_v']:g} V (netlist) != {parts['vdd']} (point id)")
        if rc["mos_section"] != parts["corner"]:
            bad.append(f"cornerMOSlv.lib section {rc['mos_section']} (netlist) != {parts['corner']} (point id)")
    if rc["pass"] != pass_label:
        bad.append(f"pass label {rc['pass']!r} (netlist) != {pass_label!r} (pinned configuration)")
    if rc["vectors"] != tuple(vectors):
        bad.append(f"recorded vectors {' '.join(rc['vectors'])} (netlist) != {' '.join(vectors)} (pinned configuration)")
    names = ("start", "stop", "step")
    got = tuple(rc[name] for name in names)
    if got != window:
        bad.append(
            f"sweep window {got[0]:g}..{got[1]:g} step {got[2]:g} (netlist) != "
            f"{window[0]:g}..{window[1]:g} step {window[2]:g} (pinned configuration)")
    if Path(rc["wrdata"]).name != Path(csv_rel).name:
        bad.append(f"wrdata target {Path(rc['wrdata']).name} is not the pinned curve {Path(csv_rel).name}")
    return bad


def _load_swing_population(repo: Path, key: str, sw: dict, expected: list, errors: list) -> dict | None:
    """Pin-check and strictly parse each grid point's coarse and fine DC
    transfer curves and rendered netlists, and refuse a netlist that
    disagrees with the pinned measurement configuration, the point it is
    pinned to, or the crossing recomputed from the pinned coarse curve.
    None when anything is wrong; problems name point and file."""
    n_err = len(errors)
    files = sw["files"]
    cfg = {k: float(v) for k, v in sw["config"].items()}
    coarse_window = (cfg["coarse_start_v"], cfg["coarse_stop_v"], cfg["coarse_step_v"])
    fine_step = cfg["fine_step_v"]
    halfspan = cfg["fine_halfspan_v"]
    expected_ids = [pid for pid, _ in expected]
    _check_raw_pins(
        key, "swing", files, expected_ids, SWING_PIN_KINDS,
        lambda pid, kind: (
            f"{pid}_{'coarse' if kind.startswith('coarse') else 'fine'}{'.csv' if kind.endswith('csv') else '.spice'}"),
        errors)
    points: dict = {}
    for pid in expected_ids:
        entry = files.get(pid)
        texts = _read_pinned_raw(
            repo, key, pid, "swing", "curves/netlists (every grid point needs all four)", entry, SWING_PIN_KINDS, errors)
        if texts is None:
            continue
        pt_err = len(errors)
        cc_rel, cn_rel = entry["coarse_csv"]["path"], entry["coarse_netlist"]["path"]
        fc_rel, fn_rel = entry["fine_csv"]["path"], entry["fine_netlist"]["path"]
        try:
            cvid, (cvout,) = swing_post.parse_wrdata(texts["coarse_csv"], swing_post.COARSE_VECTORS, cc_rel)
            fvid, (fvout, fivdd) = swing_post.parse_wrdata(texts["fine_csv"], swing_post.FINE_VECTORS, fc_rel)
        except swing_post.SwingError as exc:
            errors.append(f"record {key}: point {pid}: invalid swing curve: {exc}")
            continue
        try:
            cc = swing_post.rendered_config(texts["coarse_netlist"], cn_rel)
            fc = swing_post.rendered_config(texts["fine_netlist"], fn_rel)
        except swing_post.SwingError as exc:
            errors.append(f"record {key}: point {pid}: invalid rendered netlist: {exc}")
            continue
        for rc, net_rel, vectors, label, window, csv_rel, n_samples in (
                (cc, cn_rel, swing_post.COARSE_VECTORS, "coarse", coarse_window, cc_rel, len(cvid)),
                (fc, fn_rel, swing_post.FINE_VECTORS, "fine", (fc["start"], fc["stop"], fine_step), fc_rel, len(fvid))):
            bad = _swing_pass_problems(pid, rc, vectors, label, window, csv_rel)
            want = swing_post.sweep_count(rc["start"], rc["stop"], rc["step"])
            if n_samples != want:
                bad.append(f"{label} curve has {n_samples} samples; the rendered sweep declares {want}")
            if bad:
                errors.append(f"record {key}: point {pid}: measurement configuration mismatch in {net_rel}: " + "; ".join(bad))
        if cc["vdd_v"] != fc["vdd_v"] or cc["vcm_v"] != fc["vcm_v"]:
            errors.append(
                f"record {key}: point {pid}: measurement configuration mismatch: the coarse pass "
                f"runs {cc['vdd_v']:g} V / {cc['vcm_v']:g} V but the fine pass runs "
                f"{fc['vdd_v']:g} V / {fc['vcm_v']:g} V")
        if len(errors) > pt_err:
            continue
        coarse = swing_post.coarse_measure(cvid, cvout, fc["vcm_v"])
        if coarse["n_crossings"] != 1:
            errors.append(
                f"record {key}: point {pid}: coarse curve {cc_rel} has {coarse['n_crossings']} "
                "Vout=Vcm crossings (expected exactly 1)")
            continue
        # The fine window was rendered from the coarse crossing as the runner
        # serialized it (printf %.9g); reproduce that exact hop, then require
        # the pinned netlist's window to be the pinned half-span about it.
        vos9 = float(swing_post.serialize(coarse["vos"]))
        if fc["start"] != vos9 - halfspan or fc["stop"] != vos9 + halfspan:
            errors.append(
                f"record {key}: point {pid}: measurement configuration mismatch in {fn_rel}: "
                f"fine window {fc['start']!r}..{fc['stop']!r} is not the coarse crossing "
                f"{swing_post.serialize(coarse['vos'])} +/- {halfspan:g} V (pinned configuration)")
            continue
        fine = swing_post.fine_measure(
            fvid, fvout, fivdd, fc["vdd_v"], fc["vcm_v"],
            float(swing_post.serialize(coarse["clip_high"])),
            float(swing_post.serialize(coarse["clip_low"])),
            coarse["plateau_ok"], vos9,
            float("nan"), float("nan"), float("nan"),
            cfg["criterion_frac"])
        points[pid] = {
            "coarse": coarse, "fine": fine,
            "vdd": fc["vdd_v"], "vcm": fc["vcm_v"],
            "criterion": cfg["criterion_frac"],
            "coarse_csv": cc_rel, "coarse_netlist": cn_rel,
            "fine_csv": fc_rel, "fine_netlist": fn_rel,
        }
    return None if len(errors) > n_err else points


def load_record(repo: Path, key: str, spec: dict, grid: dict, env: dict, records: dict | None = None) -> dict:
    """Read and audit one selected record. Never raises on bad evidence."""
    state = {
        "key": key,
        "errors": [],
        "points": {},
        "valid_ids": [],
        "invalid": {},
        "missing": [],
        "unexpected": [],
        "controls": {},
        "source": {
            "csv": spec.get("csv"),
            "csv_sha256": None,
            "md": spec.get("md"),
            "md_sha256": None,
            "netlist_snapshot": spec.get("netlist_snapshot"),
            "netlist_snapshot_sha256": None,
            "ngspice": None,
            "grid": spec.get("grid"),
            "filter": spec.get("filter"),
            "valid_when": spec.get("valid_when", []),
            "definition_checks": spec.get("definition_checks", []),
            "pdk_provenance": {"status": PROV_LEGACY},
        },
    }
    errors = state["errors"]
    src = state["source"]

    # 1. presence and pins
    for field in ("csv", "md", "netlist_snapshot"):
        rel = spec.get(field)
        if not isinstance(rel, str):
            errors.append(f"record {key}: selection names no `{field}`")
            continue
        path = repo / rel
        if not path.is_file():
            errors.append(f"record {key}: missing record file {rel}")
            continue
        actual = sha256_file(path)
        src[f"{field}_sha256"] = actual
        pinned = spec.get(f"{field}_sha256")
        if field != "netlist_snapshot" and actual != pinned:
            errors.append(
                f"record {key}: {rel} does not match its selection pin "
                f"(pinned {pinned}, actual {actual}) -- re-select deliberately, "
                "never re-read silently"
            )
    draws_rel = spec.get("draws_csv")
    if draws_rel is not None:
        src["draws"] = {"csv": draws_rel, "status": "error"}
        path = repo / draws_rel
        if not path.is_file():
            errors.append(f"record {key}: missing draws population {draws_rel}")
        else:
            actual = sha256_file(path)
            src["draws"]["sha256"] = actual
            if actual != spec.get("draws_csv_sha256"):
                errors.append(
                    f"record {key}: {draws_rel} does not match its selection pin "
                    f"(pinned {spec.get('draws_csv_sha256')}, actual {actual}) -- "
                    "re-select deliberately, never re-read silently"
                )
    if errors:
        return state

    # 2. environment: simulator policy (env_identity.py), same circuit as design/
    md_text = (repo / spec["md"]).read_text(encoding="utf-8")
    state["stated_cl"] = source_cl_statements(md_text)
    versions = sorted(set(NGSPICE_RE.findall(md_text)))
    if len(versions) != 1 and not (not versions and (spec.get("klt_raw") is not None or spec.get("slew_klt") is not None or spec.get("offset_klt_raw") is not None)):
        errors.append(
            f"record {key}: {spec['md']} names {len(versions)} ngspice versions "
            f"({', '.join('ngspice-' + v for v in versions) or 'none'}) -- the "
            "simulation environment is not identifiable"
        )
    elif len(versions) == 1:
        src["ngspice"] = f"ngspice-{versions[0]}"
        _admit_ngspice_version(key, src["ngspice"], env, errors)
    check_pdk_provenance(repo, key, spec, env, state)
    snapshot_norm = normalized_netlist_hash(repo / spec["netlist_snapshot"])
    if env.get("netlist_normalized_sha256") and snapshot_norm != env["netlist_normalized_sha256"]:
        errors.append(
            f"record {key}: simulated netlist {spec['netlist_snapshot']} is not "
            f"the committed design netlist (ignoring comments/blank lines) -- "
            "this record characterizes a different circuit"
        )

    # 3. rows: parse, de-duplicate, check identity against the grid
    try:
        header, rows = read_csv_rows(repo / spec["csv"])
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        errors.append(f"record {key}: cannot parse {spec['csv']} ({exc})")
        return state
    if "point_id" not in header:
        errors.append(f"record {key}: {spec['csv']} has no point_id column")
        return state
    state["header"] = header

    all_ids: dict[str, int] = {}
    for row in rows:
        pid = (row.get("point_id") or "").strip()
        all_ids[pid] = all_ids.get(pid, 0) + 1
    for pid, count in sorted(all_ids.items()):
        if count > 1:
            errors.append(f"record {key}: duplicate point_id {pid!r} ({count} rows)")

    flt = spec.get("filter")
    controls = set(spec.get("controls", []))
    selected = []
    for row in rows:
        pid = (row.get("point_id") or "").strip()
        if pid in controls:
            state["controls"][pid] = row
            continue
        if flt and (row.get(flt["column"]) or "").strip() != flt["equals"]:
            continue
        selected.append(row)

    expected = expected_points(grid)
    expected_ids = {pid for pid, _ in expected}
    columns = grid["columns"]
    for row in selected:
        pid = row["point_id"].strip()
        if pid not in expected_ids:
            state["unexpected"].append(pid)
            continue
        state["points"][pid] = row
    for pid, values in expected:
        row = state["points"].get(pid)
        if row is None:
            state["missing"].append(pid)
            continue
        for axis, column in columns.items():
            cell = (row.get(column) or "").strip()
            if cell != values[axis]:
                errors.append(
                    f"record {key}: point {pid} says {column}={cell!r}, but its "
                    f"point_id means {axis}={values[axis]!r}"
                )
    for pid in sorted(state["unexpected"]):
        errors.append(f"record {key}: point {pid!r} is outside the expected {spec['grid']} grid")
    for pid in sorted(controls - set(state["controls"])):
        state["missing"].append(pid)

    # 3b. draws population (issue #199): identity, completeness and the raw
    # passing values the per-point statistics audit recomputes from. The
    # converter's own contract validates draw indices, seeds, metadata and
    # PASS counts against the pinned summary; it never summarizes.
    draws_pass: dict[str, list[float]] | None = None
    if draws_rel is not None:
        try:
            draws_header, draw_rows = read_csv_rows(repo / draws_rel)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            errors.append(f"record {key}: cannot parse {draws_rel} ({exc})")
        else:
            missing_cols = [c for c in draws_contract.DRAW_COLS if c not in draws_header]
            if missing_cols:
                errors.append(f"record {key}: {draws_rel} is missing column(s) {missing_cols}")
            else:
                try:
                    draws_expected = draws_contract.load_expected(repo / spec["csv"])
                    got = draws_contract.validate(draw_rows, draws_expected, draws_rel)
                except draws_contract.DrawValidationError as exc:
                    shown, rest = exc.problems[:20], exc.problems[20:]
                    errors.extend(f"record {key}: draws population {draws_rel}: {p}" for p in shown)
                    if rest:
                        errors.append(
                            f"record {key}: draws population {draws_rel}: ... and "
                            f"{len(rest)} more problem(s)"
                        )
                else:
                    draws_pass = {
                        pid: [got[pid][i] for i in sorted(got[pid]) if got[pid][i] is not None]
                        for pid in got
                    }
                    src["draws"].update(
                        {
                            "status": "verified",
                            "points": len(draws_pass),
                            "draws": len(draw_rows),
                            "passing_draws": sum(len(v) for v in draws_pass.values()),
                        }
                    )

    # 3c. raw CMRR sample population (issue #208): every grid point's sample
    # file is pinned, strictly parsed, and Av0 is joined from the pinned
    # deterministic record. Problems are point-specific record errors.
    sample_pop: dict | None = None
    ms = spec.get("mc_samples")
    if ms is not None:
        sample_pop = _load_sample_population(repo, key, ms, expected, records or {}, errors)
        src["samples"] = {
            "status": "verified" if sample_pop is not None else "error",
            "files": len(ms["files"]),
            "pins_sha256": sha256_bytes(canonical_json(ms["files"]).encode("utf-8")),
            "av0_join": ms["av0_join"],
            "acceptance": ms["acceptance"],
        }
        if sample_pop is not None:
            src["samples"]["draws"] = sum(e["n"] for e in sample_pop["points"].values())

    # 3d. raw noise artifacts (issue #213): one pinned log and one pinned
    # in-band spectrum per grid point, strictly parsed.
    noise_pop: dict | None = None
    nr = spec.get("noise_raw")
    if nr is not None:
        noise_pop = _load_noise_population(repo, key, nr, expected, errors)
        src["noise_raw"] = {
            "status": "verified" if noise_pop is not None else "error",
            "points": len(nr["files"]),
            "pins_sha256": sha256_bytes(canonical_json(nr["files"]).encode("utf-8")),
            "band": nr["band"],
        }

    # 3e. raw transient waveforms (issue #227): one pinned waveform and one
    # pinned rendered netlist per grid point, strictly parsed.
    slew_pop: dict | None = None
    sr = spec.get("slew_raw")
    if sr is not None:
        slew_pop = _load_slew_population(repo, key, sr, expected, errors)
        src["slew_raw"] = {
            "status": "verified" if slew_pop is not None else "error",
            "points": len(sr["files"]),
            "pins_sha256": sha256_bytes(canonical_json(sr["files"]).encode("utf-8")),
            "config": sr["config"],
        }

    # 3e'. batch slew `klt sim` envelope (issue #501), cross-checked.
    slew_klt_pop: dict | None = None
    sk = spec.get("slew_klt")
    if sk is not None and sr is None:
        # Issue #513: the envelope returns no waveform, so only slew_raw_audit
        # covers these columns; a pure-batch record must not declare them.
        unaudited = [c for c in SLEW_WAVEFORM_ONLY_COLUMNS if c in header]
        if unaudited:
            errors.append(
                f"record {key}: pins slew_klt without slew_raw, but {spec['csv']} declares "
                f"{', '.join(unaudited)}, which only the pinned waveform (slew_raw) audits -- "
                "pin slew_raw beside slew_klt or drop the columns"
            )
    if sk is not None:
        slew_klt_pop = _load_slew_klt_population(repo, key, sk, expected, spec["netlist_snapshot"], md_text, errors)
        src["slew_klt"] = {
            "status": "verified" if slew_klt_pop is not None else "error",
            "points": len(expected),
            "pins_sha256": sha256_bytes(canonical_json(sk["files"]).encode("utf-8")),
        }
        if slew_klt_pop is not None:
            src["slew_klt"]["job"] = slew_klt_pop["job"]
            src["slew_klt"]["cload_f"] = slew_klt_pop["cload_f"]
            envelope_ngspice = f"ngspice-{slew_klt_pop['version']}"
            # Same carrier as the klt_raw path (3g): the summary .md already went
            # through the shared policy; a versionless summary leaves the envelope
            # as the only source, so admit it here instead of exact-matching.
            _carry_ngspice_version(key, src, envelope_ngspice, "the pinned slew envelope", spec, env, errors)

    # 3f. raw DC transfer curves (issue #230): both passes' pinned wrdata
    # curves and rendered netlists per grid point, strictly parsed.
    swing_pop: dict | None = None
    swr = spec.get("swing_raw")
    if swr is not None:
        swing_pop = _load_swing_population(repo, key, swr, expected, errors)
        src["swing_raw"] = {
            "status": "verified" if swing_pop is not None else "error",
            "points": len(swr["files"]),
            "pins_sha256": sha256_bytes(canonical_json(swr["files"]).encode("utf-8")),
            "config": swr["config"],
        }

    # 3h. the input-offset `klt sim` family (issue #504): the null and
    # closed-loop envelopes, both requests and both bench bodies, joined with
    # the selected open-loop record's per-corner Av0.
    offset_klt_pop: dict | None = None
    okr = spec.get("offset_klt_raw")
    if okr is not None:
        offset_klt_pop = _load_offset_klt_population(repo, key, okr, expected, spec["netlist_snapshot"], md_text, records or {}, errors)
        src["offset_klt_raw"] = {
            "status": "verified" if offset_klt_pop is not None else "error",
            "points": len(expected),
            "pins_sha256": sha256_bytes(canonical_json(okr["files"]).encode("utf-8")),
            "av0_join": okr["av0_join"],
        }
        if offset_klt_pop is not None:
            src["offset_klt_raw"]["jobs"] = offset_klt_pop["jobs"]
            src["offset_klt_raw"]["av0_join_csv"] = offset_klt_pop["join_csv"]
            envelope_ngspice = f"ngspice-{offset_klt_pop['version']}"
            # Same carrier as 3e/3g: establish-or-agree, admitted through the
            # shared policy (floor, else legacy exact pin) in one place.
            _carry_ngspice_version(key, src, envelope_ngspice, "the pinned envelopes", spec, env, errors)

    # 3g. raw `klt sim` envelopes (issue #101 / #500): the AC and OP envelopes,
    # both requests and the bench body (plus optional measurement document), cross-checked.
    klt_pop: dict | None = None
    kr = spec.get("klt_raw")
    if kr is not None:
        klt_pop = _load_klt_population(repo, key, kr, expected, spec["netlist_snapshot"], md_text, records or {}, errors)
        src["klt_raw"] = {
            "status": "verified" if klt_pop is not None else "error",
            "points": len(expected),
            "pins_sha256": sha256_bytes(canonical_json(kr["files"]).encode("utf-8")),
        }
        if "dc_continuity" in kr:
            src["klt_raw"]["dc_continuity"] = kr["dc_continuity"]
        if klt_pop is not None:
            src["klt_raw"]["jobs"] = klt_pop["jobs"]
            src["klt_raw"]["ibias_a"] = klt_pop["ibias_a"]
            src["klt_raw"]["cload_f"] = klt_pop["cload_f"]
            if klt_pop["schematic_op"] and "dc_continuity" not in kr:
                src["klt_raw"]["schematic_op"] = True
            envelope_ngspice = f"ngspice-{klt_pop['version']}"
            # One carrier for the invariant: src["ngspice"] is set by the summary
            # .md or by the slew envelope (3e), whichever came first; every later
            # evidence kind must agree with it, never overwrite it.
            _carry_ngspice_version(key, src, envelope_ngspice, "the pinned envelopes", spec, env, errors)
            sidecar_ngspice = state.get("sidecar_ngspice")
            if sidecar_ngspice is not None and sidecar_ngspice != envelope_ngspice:
                errors.append(
                    f"record {key}: sidecar {spec.get('env_sidecar')} observed {sidecar_ngspice!r}, "
                    f"but the pinned envelopes ran {envelope_ngspice}"
                )
                src["pdk_provenance"]["status"] = PROV_ERROR

    # 4. validity flags and definitions, per point
    conditions = spec.get("valid_when", [])

    def run_definition_checks(pid: str, row: dict) -> None:
        for name in spec.get("definition_checks", []):
            check, needs = DEFINITION_CHECKS[name]
            pop = {"draws": draws_pass, "samples": sample_pop, "noise": noise_pop, "slew": slew_pop, "swing": swing_pop, "klt": klt_pop, "slew_klt": slew_klt_pop, "offset_klt": offset_klt_pop}.get(needs)
            if needs and pop is None:
                continue  # the population load above already reported why
            problem = check(row, pop)
            if problem:
                errors.append(f"record {key}: point {pid} fails definition check {name}: {problem}")

    for pid, _ in expected:
        row = state["points"].get(pid)
        if row is None:
            continue
        why = point_is_valid(row, conditions)
        if why:
            state["invalid"][pid] = why
            continue
        run_definition_checks(pid, row)
        state["valid_ids"].append(pid)
    for pid, row in sorted(state["controls"].items()):
        why = point_is_valid(row, conditions)
        if why:
            state["invalid"][pid] = why
            continue
        # Controls are audited on their own population, exactly like grid
        # points; they are never pooled into another point's statistics.
        run_definition_checks(pid, row)

    src["expected_points"] = len(expected) + len(controls)
    src["observed_points"] = len(state["points"]) + len(state["controls"])
    src["valid_points"] = len(state["valid_ids"]) + sum(
        1 for pid in state["controls"] if pid not in state["invalid"]
    )
    src["missing_points"] = sorted(state["missing"])
    src["invalid_points"] = {pid: state["invalid"][pid] for pid in sorted(state["invalid"])}
    return state


# --------------------------------------------------------------------------
# the input-offset `klt sim` family (issue #504): the null-sweep and
# closed-loop envelopes, their requests and bodies, and the Av0 join.

# The measurement definitions the audit relies on: name -> (spice | expr,
# limits). The ratified bound (vos_null_v +/- 21.9 mV [DR-2]) lives in the
# REQUEST, so a pinned request that grades anything else is refused.
OFFSET_NULL_MEASUREMENTS = {
    "vos_null_v": (".meas dc vos_null_v when v(orel)=0 rise=1", {"min": -0.0219, "max": 0.0219}),
    "vos_crossings_n": ("mean((v(orel)[1,7500]*v(orel)[0,7499]) lt 0)*7500", {"min": 0.5, "max": 1.5}),
    "gain_local_vv": ("vecmax(((v(orel)[1,7500]*v(orel)[0,7499]) lt 0)*((v(out)[1,7500]-v(out)[0,7499])/4e-6))", {"min": 10.0}),
    "vd1_dc_v": (".meas dc vd1_dc_v find v(d1) when v(orel)=0 rise=1", None),
    "vd2_dc_v": (".meas dc vd2_dc_v find v(d2) when v(orel)=0 rise=1", None),
    "vtail_dc_v": (".meas dc vtail_dc_v find v(tail) when v(orel)=0 rise=1", None),
    "vout_null_dc_v": (".meas dc vout_null_dc_v find v(out) when v(orel)=0 rise=1", None),
    "vibias_dc_v": (".meas dc vibias_dc_v find v(ibias) when v(orel)=0 rise=1", None),
    "op_vd1_rail_frac": (".meas dc op_vd1_rail_frac find v(fd1) when v(orel)=0 rise=1", {"min": 0.02, "max": 0.98}),
    "op_vd2_rail_frac": (".meas dc op_vd2_rail_frac find v(fd2) when v(orel)=0 rise=1", {"min": 0.02, "max": 0.98}),
    "op_vtail_rail_frac": (".meas dc op_vtail_rail_frac find v(ftail) when v(orel)=0 rise=1", {"min": 0.02, "max": 0.98}),
}
OFFSET_CL_MEASUREMENTS = {"vout_cl_v": ("v(out)", None)}
OFFSET_BENCH_ELEMENTS = {
    "null:Vid": r"Vid\s+id\s+0\s+dc\s+\S+",
    "null:Vinp(cm)": r"Vinp\s+cm\s+0\s+dc\s+\S+",
    "null:Binp": r"Binp\s+inp\s+0\s+v\s*=\s*v\(cm\)\s*\+\s*v\(id\)/2",
    "null:Binn": r"Binn\s+inn\s+0\s+v\s*=\s*v\(cm\)\s*-\s*v\(id\)/2",
    "null:Borel": r"Borel\s+orel\s+0\s+v\s*=\s*v\(out\)-v\(cm\)",
    "cl:Lbreak": r"Lbreak\s+inn\s+out\s+1e18",
    "cl:Vinp(inp)": r"Vinp\s+inp\s+0\s+dc\s+\S+",
    "both:Iibias": r"Iibias\s+vdd\s+ibias\s+dc\s+10u",
}


def _offset_klt_corner_ids(env: dict, label: str, expected_ids: list, problems: list) -> dict:
    """{point_id: corner} for one envelope, refusing duplicates, missing or
    extra points, errored/inconclusive corners and corner diagnostics. Unlike
    the open-loop family, a corner whose status is `fail` IS evidence here: a
    ratified-bound miss (vos_null_v outside +/- 21.9 mV) is a result the row
    grades, never a reason to refuse the envelope."""
    out: dict = {}
    for corner in env.get("corners") or []:
        try:
            pid = f"{corner['process']}_{int(corner['temperature_c'])}C_{float(corner['supply_v']['vdd']):.2f}V"
        except (KeyError, TypeError, ValueError):
            problems.append(f"{label}: a corner has no process/temperature/vdd identity")
            continue
        if pid in out:
            problems.append(f"{label}: duplicate corner {pid}")
        out[pid] = corner
        if corner.get("status") not in ("pass", "fail"):
            problems.append(f"{label}: point {pid} is not a completed run (status {corner.get('status')!r})")
        if corner.get("diagnostics"):
            problems.append(f"{label}: point {pid} carries {len(corner['diagnostics'])} diagnostic(s)")
    for pid in expected_ids:
        if pid not in out:
            problems.append(f"{label}: no corner for point {pid}")
    for pid in sorted(set(out) - set(expected_ids)):
        problems.append(f"{label}: corner {pid} is outside the expected grid")
    return out


def _load_offset_klt_population(repo: Path, key: str, kr: dict, expected: list, snapshot_rel: str,
                                md_text: str, records: dict, errors: list) -> dict | None:
    """Pin-check and strictly cross-check the input-offset `klt sim` evidence
    (both envelopes, both requests, both bodies, the Av0 join) and return the
    per-point raw values the definition check re-derives every cell from.
    None when anything is wrong; problems name the artifact and point."""
    n_err = len(errors)
    expected_ids = [pid for pid, _ in expected]
    docs: dict = {}
    for kind in OFFSET_KLT_RAW_KINDS:
        pin = kr["files"][kind]
        path = repo / pin["path"]
        if not path.is_file():
            errors.append(f"record {key}: missing raw offset-klt artifact {kind} {pin['path']}")
            continue
        actual = sha256_file(path)
        if actual != pin["sha256"]:
            errors.append(
                f"record {key}: {pin['path']} does not match its selection pin "
                f"(pinned {pin['sha256']}, actual {actual}) -- re-select deliberately, never re-read silently"
            )
            continue
        try:
            text = path.read_text(encoding="utf-8")
            docs[kind] = text if kind.endswith("_body") else json.loads(text)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"record {key}: cannot read {pin['path']} ({exc})")
    if len(errors) > n_err:
        return None
    problems: list[str] = []
    snap = repo / snapshot_rel
    snap_hash = sha256_file(snap) if snap.is_file() else None
    envs = {}
    for kind in ("null", "cl"):
        doc = docs[kind]
        label = f"{kind} envelope {kr['files'][kind]['path']}"
        if not isinstance(doc, dict):
            problems.append(f"{label}: not an object")
            continue
        count = doc.get("corner_count")
        if doc.get("status") not in ("pass", "fail"):
            problems.append(f"{label}: status {doc.get('status')!r} -- only a complete pass/fail run is evidence")
        if count != len(expected_ids) or doc.get("passed") + doc.get("failed", 0) != count:
            problems.append(f"{label}: {doc.get('passed')} passed + {doc.get('failed', 0)} failed of {count} corners (need all {len(expected_ids)} accounted for)")
        for field in ("errored", "inconclusive"):
            if doc.get(field) != 0:
                problems.append(f"{label}: {field} = {doc.get(field)!r}")
        if (doc.get("diagnostic_counts") or {}).get("corners_with_diagnostics") != 0:
            problems.append(f"{label}: corners carry diagnostics")
        remote = (doc.get("environment") or {}).get("remote") or {}
        if not remote.get("job_id"):
            problems.append(f"{label}: no environment.remote.job_id (not a batch run)")
        envs[kind] = {"env": doc, "corners": _offset_klt_corner_ids(doc, label, expected_ids, problems), "label": label}
    if problems:
        errors.extend(f"record {key}: offset klt raw evidence: {p}" for p in problems)
        return None

    null_env, cl_env = envs["null"]["env"], envs["cl"]["env"]
    en, ec = null_env["environment"], cl_env["environment"]
    if en.get("engine") != "ngspice" or en.get("engine") != ec.get("engine") or en.get("engine_version") != ec.get("engine_version"):
        problems.append(f"the two envelopes disagree on the engine ({en.get('engine')} {en.get('engine_version')} vs {ec.get('engine')} {ec.get('engine_version')})")
    version = str(en.get("engine_version"))
    for kind, doc in (("null", null_env), ("cl", cl_env)):
        e = doc["environment"]
        banner = ((e.get("remote") or {}).get("worker_environment") or {}).get("simulator", {}).get("version_banner")
        if banner is not None and f"ngspice-{version}" not in banner:
            problems.append(f"{kind} envelope: worker banner does not name ngspice-{version}")
    if en.get("models_lib_sha256") != ec.get("models_lib_sha256") or not en.get("models_lib_sha256"):
        problems.append("the two envelopes disagree on the model deck hash")
    for kind, doc in (("null", null_env), ("cl", cl_env)):
        prov = doc.get("provenance") or {}
        if (prov.get("pdk") or {}).get("name") != "ihp-sg13g2":
            problems.append(f"{kind} envelope: PDK is {(prov.get('pdk') or {}).get('name')!r}, not ihp-sg13g2")
        deck = prov.get("deck") or {}
        if deck.get("name") != "cornerMOSlv.lib" or deck.get("content_hash") != "sha256:" + str(doc["environment"].get("models_lib_sha256")):
            problems.append(f"{kind} envelope: model deck identity {deck.get('name')!r} {deck.get('content_hash')!r} is not cornerMOSlv.lib at the recorded models_lib_sha256")
        closure = {c.get("path"): c.get("sha256") for c in doc["environment"].get("netlist_closure") or []}
        # The bodies' single .include names design/netlist/opamp_core.spice,
        # so THAT closure entry is the simulated DUT; run.sh copied the same
        # bytes to the selected snapshot before publishing, so their hashes
        # must agree (the snapshot is the copy the selection pins).
        dut_entries = {p: s for p, s in closure.items() if Path(str(p)).name == "opamp_core.spice"}
        if len(dut_entries) != 1 or "sha256:" + str(next(iter(dut_entries.values()))) != snap_hash:
            problems.append(
                f"{kind} envelope: simulated DUT (closure entries {sorted(dut_entries)}) is not the "
                f"selected netlist snapshot {snapshot_rel} ({snap_hash})"
            )
        body_pin = kr["files"][f"{kind}_body"]
        if "sha256:" + str(closure.get(body_pin["path"])) != body_pin["sha256"] or "sha256:" + str(doc["environment"].get("netlist_sha256")) != body_pin["sha256"]:
            problems.append(f"{kind} envelope: simulated bench body is not the pinned {body_pin['path']}")
        if (doc.get("netlist") or {}).get("path") != body_pin["path"]:
            problems.append(f"{kind} envelope: netlist path {(doc.get('netlist') or {}).get('path')!r} is not the pinned bench body")

    # Simulator version admission (floor / exact pin) is applied by the caller
    # through _carry_ngspice_version, the one shared policy; only the version
    # is reported here.

    # requests: the measurement definitions and analyses the audit relies on
    null_req, cl_req = docs["null_request"], docs["cl_request"]
    if (null_req.get("analysis") or {}).get("kind") != "dc" or (null_req.get("analysis") or {}).get("args") != "Vid 0.004 0.034 4u":
        problems.append("null request: analysis is not `dc Vid 0.004 0.034 4u` (the 4 uV fine-step window)")
    if (cl_req.get("analysis") or {}).get("kind") != "op":
        problems.append("cl request: analysis is not `op`")
    for kind, req, defs in (("null", null_req, OFFSET_NULL_MEASUREMENTS), ("cl", cl_req, OFFSET_CL_MEASUREMENTS)):
        got = {m.get("name"): (m.get("spice") or m.get("expr"), m.get("limits")) for m in req.get("measurements") or []}
        if set(got) != set(defs):
            problems.append(f"{kind} request: measurements {sorted(got)} are not exactly {sorted(defs)}")
        else:
            for name, (definition, limits) in defs.items():
                if got[name][0] != definition:
                    problems.append(f"{kind} request: measurement {name} is {got[name][0]!r}, not {definition!r}")
                if (got[name][1] or None) != limits:
                    problems.append(f"{kind} request: measurement {name} limits {got[name][1]!r} are not the pinned {limits!r}")
        if Path(str(req.get("netlist"))).name != Path(kr["files"][f"{kind}_body"]["path"]).name:
            problems.append(f"{kind} request: netlist {req.get('netlist')!r} is not the pinned bench body")

    # bench bodies: the harness topologies, element for element
    stated = {parse_capacitance(s)[0] for s in source_cl_statements(md_text)} - {None}
    for kind in ("null", "cl"):
        body = "\n".join(line for line in docs[f"{kind}_body"].splitlines() if not line.lstrip().startswith("*"))
        loads = _KLT_CLOAD_RE.findall(body)
        if len(loads) != 1:
            problems.append(f"{kind} bench body: {len(loads)} Cload elements (need exactly one)")
        else:
            try:
                cload = Decimal(loads[0])
            except InvalidOperation:
                cload = None
            if cload is None or cload not in stated:
                problems.append(f"{kind} bench body: Cload {loads[0]} is not a CL the record's own prose states ({sorted(source_cl_statements(md_text))})")
        if sum(line.lower().startswith(".include") for line in body.splitlines()) != 1:
            problems.append(f"{kind} bench body: needs exactly one .include of the DUT netlist")
    for name, pattern in OFFSET_BENCH_ELEMENTS.items():
        scope, element = name.split(":")
        kinds = ("null", "cl") if scope == "both" else (scope,)
        for kind in kinds:
            body = "\n".join(line for line in docs[f"{kind}_body"].splitlines() if not line.lstrip().startswith("*"))
            if len(re.findall(r"^" + pattern + r"\s*$", body, re.MULTILINE | re.IGNORECASE)) != 1:
                problems.append(f"{kind} bench body: element {element} is not present exactly once as `{pattern}`")

    # the Av0 join: the explicitly selected same-DUT open-loop record, by pin
    join_key = kr["av0_join"]
    join = records.get(join_key) or {}
    av0: dict[str, float] = {}
    join_csv = join.get("csv")
    jpath = repo / join_csv if isinstance(join_csv, str) else None
    if jpath is None or not jpath.is_file():
        problems.append(f"av0_join record {join_key}: CSV is missing")
    elif sha256_file(jpath) != join.get("csv_sha256"):
        problems.append(f"av0_join record {join_key}: {join_csv} does not match its selection pin")
    else:
        join_snap = join.get("netlist_snapshot")
        if isinstance(join_snap, str) and (repo / join_snap).is_file():
            if normalized_netlist_hash(repo / join_snap) != normalized_netlist_hash(snap):
                problems.append(
                    f"av0_join record {join_key}: simulated a different DUT ({join_snap}) than "
                    f"record {key} ({snapshot_rel}) -- an Av0 from another circuit is never joined silently"
                )
        else:
            problems.append(f"av0_join record {join_key}: netlist snapshot {join_snap!r} is missing")
        try:
            _, jrows = read_csv_rows(jpath)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            problems.append(f"av0_join record {join_key}: cannot parse {join_csv} ({exc})")
            jrows = []
        for row in jrows:
            jid = (row.get("point_id") or "").strip()
            try:
                spelled = f"{(row.get('corner') or '').strip()}_{int(float(row['temp_c']))}C_{float(row['vdd_v']):.2f}V"
            except (TypeError, ValueError, OverflowError):
                problems.append(f"av0_join record {join_key}: point {jid}: unreadable corner/temp_c/vdd_v columns")
                continue
            if jid != spelled:
                problems.append(
                    f"av0_join record {join_key}: point {jid}: its corner/temp_c/vdd_v columns spell {spelled!r} "
                    "-- an Av0 bound to the wrong corner"
                )
                continue
            try:
                value = float(row["av0_db"])
            except (KeyError, TypeError, ValueError):
                value = float("nan")
            if jid in av0:
                problems.append(f"av0_join record {join_key}: duplicate point {jid}")
            av0[jid] = value
        for pid in expected_ids:
            if pid not in av0:
                problems.append(f"av0_join record {join_key}: point {pid}: no row in the joined record {join_csv}")
            elif not math.isfinite(av0[pid]):
                problems.append(f"av0_join record {join_key}: point {pid}: no finite Av0 in the joined record {join_csv}")
    if problems:
        errors.extend(f"record {key}: offset klt raw evidence: {p}" for p in problems)
        return None

    points: dict = {}
    for pid in expected_ids:
        n = _klt_values(envs["null"]["corners"][pid], OFFSET_NULL_MEASUREMENTS)
        c = _klt_values(envs["cl"]["corners"][pid], OFFSET_CL_MEASUREMENTS)
        bad = [name for name, v in (*n.items(), *c.items()) if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)]
        if bad:
            problems.append(f"point {pid}: missing or non-finite raw value(s) {bad}")
            continue
        sup = envs["null"]["corners"][pid].get("supply_v") or {}
        if envs["cl"]["corners"][pid].get("supply_v") != sup:
            problems.append(f"point {pid}: the null and cl envelopes use different supplies")
            continue
        points[pid] = {
            "null": dict(n), "vout_cl_v": c["vout_cl_v"], "vdd": sup.get("vdd"),
            "av0_db": av0.get(pid),
        }
    if problems:
        errors.extend(f"record {key}: offset klt raw evidence: {p}" for p in problems)
        return None
    return {
        "points": points, "version": version, "av0_join": join_key, "join_csv": join_csv,
        "jobs": {k: envs[k]["env"]["environment"]["remote"]["job_id"] for k in ("null", "cl")},
    }

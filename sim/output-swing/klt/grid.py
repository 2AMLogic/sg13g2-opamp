"""Prepare the batch swing requests and replay their retained evidence offline."""
import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

import compare as C
import two_pass as T

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BENCH = Path("sim/output-swing/klt/tb_swing.body.spice")
DUT = Path("design/netlist/opamp_core.spice")
POINTS = C.POINT_SETS["grid"]


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")


def pin(path):
    return {"path": str(path.relative_to(ROOT)), "sha256": "sha256:" + C.E.sha256_file(path)}


def coarse_request(bundle):
    # Keep the same relative .include and the exact bytes that both jobs stage.
    for rel in (BENCH, DUT):
        path = bundle / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, path)
    request = read(HERE / "swing.request.json")
    request["netlist"] = str(BENCH)
    write(bundle / "coarse.request.json", request)


def fine_request(coarse_request, passes):
    rules = []
    for p in passes:
        try:
            lo, hi, _ = T.fine_window(p["vid"], p["vout"], p["vcm_v"])
        except ValueError as exc:
            raise T.PairError(p["pid"], str(exc)) from exc
        rules.append({"match": {"process": p["process"], "temperature_c": p["temp_c"],
                                "supply_v": {"vdd": p["vdd_v"]}},
                      "args": f"Vid {lo!r} {hi!r} {T.swing_post.CONFIG['fine_step_v']}"})
    options = dict(coarse_request["options"], capture_only=False,
                   save_vectors=["v(id)", "v(out)", "i(vdd)", "v(vdd)", "v(vss)"])
    return dict(coarse_request, analysis={"kind": "dc", "args": rules[0]["args"]},
                _comment=["Fine DC pass. Every point has its own measured crossing."],
                analysis_overrides=rules, options=options,
                measurements=read(HERE / "swing.nominal.request.json")["measurements"])


def identity(result, bundle):
    e = result["environment"]
    remote = e["remote"]
    if (e["backend"]["resolved"] != "batch" or remote["provider"] != "aws-batch-fleet"
            or remote.get("spot") is not True or not remote.get("job_id")):
        raise C.InputError("expected a collected Spot batch job")
    bench, dut = pin(bundle / BENCH), pin(bundle / DUT)
    closure = sorted((f["path"], "sha256:" + f["sha256"]) for f in e["netlist_closure"])
    if (closure != sorted((f["path"], f["sha256"]) for f in (bench, dut))
            or "sha256:" + e["netlist_sha256"] != bench["sha256"]):
        raise C.InputError("simulated netlist closure differs from the retained bench or DUT")
    provenance = result["provenance"]
    if (provenance["pdk"]["name"] != "ihp-sg13g2" or provenance["deck"]["name"] != "cornerMOSlv.lib"
            or provenance["deck"]["content_hash"] != "sha256:" + e["models_lib_sha256"]):
        raise C.InputError("worker result does not identify the SG13G2 MOS model deck")
    if e["engine"] != "ngspice" or not e["engine_version"] or e.get("engine_host") != "worker":
        raise C.InputError("missing worker ngspice identity")
    staged = sorted((m["name"], m["sha256"]) for m in e["staged_model_inputs"])
    observed = sorted((m["name"], m["sha256"]) for m in remote["runner_model_inputs"])
    if (not staged or staged != observed or not remote.get("ami_id")
            or not re.fullmatch("[0-9a-f]{64}", e["engine_build"].get("binary_sha256") or "")):
        raise C.InputError("missing or inconsistent batch model or simulator identity")
    return {
        "bench_sha256": bench["sha256"].removeprefix("sha256:"),
        "dut_sha256": dut["sha256"].removeprefix("sha256:"),
        "simulator": "ngspice-" + str(e["engine_version"]),
        "engine_sha256": e["engine_build"]["binary_sha256"],
        "model_inputs": dict(observed),
        "ami_id": remote["ami_id"],
    }


def read_curves(path, vectors, pid, phase, start, stop, step):
    """Reconcile the actual waveform axis with the drive and requested grid."""
    wf = read(path)
    vid, (drive, *data) = T.waveform_to_pass_curves(wf, ("v(id)", *vectors), pid)
    if any(not math.isclose(x, y, abs_tol=1e-12, rel_tol=1e-10) for x, y in zip(vid, drive)):
        raise T.PairError(pid, "waveform axis differs from v(id)")
    if (not start < stop or not step > 0
            or len(vid) != T.swing_post.sweep_count(start, stop, step)
            or any(abs(x - (start + i * step)) > step * 1e-3 for i, x in enumerate(vid))):
        raise T.PairError(pid, f"{phase} waveform axis differs from requested sweep {start}..{stop} step {step}")
    return vid, data


def extract(bundle, phase, artifacts=None):
    """Read a collected envelope, or its archived waveforms during replay."""
    req_path, res_path = (bundle / f"{phase}.{suffix}.json" for suffix in ("request", "sim"))
    request, result = read(req_path), read(res_path)
    if phase == "fine":
        C.index_envelope(result, str(res_path), POINTS)
    else:
        C.E.index_envelope(result, str(res_path), (), supply_key="vcm", points=POINTS)
        if result["coverage"].get("capture_only") is not True or result["status"] != "pass":
            raise C.InputError("coarse waveform capture did not pass")
    ident = identity(result, bundle)
    sources = {"request": pin(req_path), "result": pin(res_path)}
    overrides = {}
    for rule in request.get("analysis_overrides", []):
        match = rule["match"]
        key = (match["process"], match["temperature_c"], match["supply_v"]["vdd"])
        if key in overrides:
            raise T.PairError(C.key_str(key), "duplicate fine request window")
        overrides[key] = rule["args"]

    passes = []
    vectors = T.swing_post.FINE_VECTORS if phase == "fine" else T.swing_post.COARSE_VECTORS
    seen = set()
    for corner in result["corners"]:
        process, temp, supply = corner["process"], corner["temperature_c"], corner["supply_v"]
        key = (process, temp, supply["vdd"])
        pid = C.key_str(C.make_key(*key))
        if key not in POINTS:
            raise T.PairError(pid, f"unexpected PVT key {key}")
        if phase == "fine" and (key not in overrides or overrides[key] != corner.get("analysis_args")):
            raise T.PairError(pid, "worker did not echo the requested fine sweep")
        base_args = request["analysis"]["args"]
        args = corner.get("analysis_args", base_args)
        if phase == "coarse" and (corner["status"] != "pass" or args != base_args):
            raise T.PairError(pid, "worker did not complete the requested coarse sweep")
        source, start, stop, step = args.split()
        if request["analysis"]["kind"] != "dc" or source.lower() != "vid":
            raise T.PairError(pid, f"unexpected sweep {args}")
        waveform = bundle / f"{pid}_{phase}.waveform.json"
        reported = corner["artifacts"].get("waveform")
        if not reported or reported in seen:
            raise T.PairError(pid, f"missing or duplicate {phase} waveform {reported!r}")
        seen.add(reported)
        if artifacts is not None:
            path = Path(reported).resolve()
            if not path.is_relative_to(artifacts.resolve()) or not path.is_file():
                raise T.PairError(pid, f"missing collected waveform {reported!r}")
            shutil.copyfile(path, waveform)
        start, stop, step = float(start), float(stop), float(step)
        vid, data = read_curves(waveform, vectors, pid, phase, start, stop, step)
        p = dict(ident, pid=pid, process=process, temp_c=temp, vdd_v=supply["vdd"], vcm_v=supply["vcm"],
                 start=start, stop=stop, step=step, vid=vid, vout=data[0],
                 sources=dict(sources, waveform=pin(waveform)))
        if phase == "fine":
            p["ivdd"] = data[1]
        passes.append(p)
    return passes


def selection_record(bundle, files, audited, simulator, replay):
    """Pin the audited, report-ready record and validate its CSV on replay."""
    summary = bundle / "summary.csv"
    if not replay:
        with summary.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, ["point_id", "corner", "temp_c", *T.swing_post.AUDIT_FIELDS])
            writer.writeheader()
            for key in POINTS:
                pid = C.key_str(key)
                writer.writerow(dict(audited[pid]["fields"], point_id=pid, corner=key[0],
                                     temp_c=key[1], vdd_v=f"{key[2]:.2f}"))
        (bundle / "record.md").write_text(
            f"# Output swing\n\nTwo-pass DC grid on {simulator}, CL = 2 pF. "
            f"The {len(audited)} PVT points use a crossing-centred fine sweep. "
            "The worker environment and model hashes are in the two batch results.\n")
    else:
        problems = []
        C.E.load_harness_csv_rows(summary, T.swing_post.AUDIT_FIELDS, "summary", points=POINTS)
        with summary.open(newline="") as stream:
            for row in csv.DictReader(stream):
                pid = row["point_id"]
                problems.extend(T.check_summary(pid, row, audited[pid]))
        if problems:
            raise C.InputError("\n".join(problems))
    summary_pin, md = pin(summary), pin(bundle / "record.md")
    return {
        "swing_two_pass": {"files": files}, "csv": summary_pin["path"], "csv_sha256": summary_pin["sha256"],
        "md": md["path"], "md_sha256": md["sha256"], "netlist_snapshot": str((bundle / DUT).relative_to(ROOT)),
        "grid": "pvt45", "valid_when": [["op_pass", "==", "1"]], "definition_checks": ["swing_raw_audit"],
    }


def finish(bundle, fine_artifacts=None, *, replay=False):
    if not replay and (bundle / "selection.json").exists():
        raise C.InputError("bundle already has a completed selection")
    coarse = extract(bundle, "coarse")
    fine = extract(bundle, "fine", fine_artifacts)
    pids = [C.key_str(key) for key in POINTS]
    audited, problems = T.audit_population(pids, coarse, fine)
    if problems:
        raise C.InputError("\n".join(problems))
    files = {pid: {} for pid in pids}
    for phase, passes in (("coarse", coarse), ("fine", fine)):
        for p in passes:
            pid = p["pid"]
            for field in ("model_inputs", "ami_id", "engine_sha256"):
                if p[field] != coarse[0][field]:
                    raise T.PairError(pid, f"{phase} worker differs on {field}")
            path = bundle / f"{pid}_{phase}.json"
            if replay:
                if read(path) != p:
                    raise T.PairError(pid, f"{phase} evidence differs from raw inputs")
            else:
                write(path, p)
            files[pid][phase] = pin(path)

    selection = selection_record(bundle, files, audited, coarse[0]["simulator"], replay)
    dut = coarse[0]["dut_sha256"]
    if replay:
        if read(bundle / "selection.json") != selection:
            raise C.InputError("selection pins differ from the replayed passes or summary")
        recorded = read(bundle / "compare.json")
        csv_path = ROOT / recorded["baseline"]["path"] if recorded["baseline"] else None
    else:
        csv_path = C.swing_baseline(HERE.parent, dut)
    if csv_path:
        snapshot = HERE.parent / "netlist-snapshots" / csv_path.stem / DUT.name
        if pin(snapshot)["sha256"] != "sha256:" + dut:
            raise C.InputError(f"{csv_path}: harness snapshot differs from the simulated DUT")
        report = C.compare_pairs(audited, csv_path, POINTS)
        report.update(baseline=pin(csv_path), baseline_snapshot=pin(snapshot))
    else:
        report = {"status": "no_same_dut_baseline", "baseline": None, "points_compared": 0,
                  "verdicts": {pid: a["verdicts"] for pid, a in audited.items()}}
    report["dut_sha256"] = dut
    if replay:
        if recorded != report:
            raise C.InputError("comparison or baseline pins differ from offline replay")
    else:
        write(bundle / "compare.json", report)
        write(bundle / "selection.tmp", selection)
        os.replace(bundle / "selection.tmp", bundle / "selection.json")
    for discrepancy in report.get("out_of_tolerance", []):
        print(discrepancy, file=sys.stderr)
    print(f"{len(audited)} coarse/fine pairs, comparison {report['status']}: {bundle}")
    return 0 if report["status"] == "agree" else 5


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest="command", required=True)
    for name in ("coarse-request", "fine-request", "finish", "replay"):
        sub = commands.add_parser(name)
        sub.add_argument("bundle", type=Path)
        if name in ("fine-request", "finish"):
            sub.add_argument("artifacts", type=Path)
    args = ap.parse_args()
    bundle = args.bundle.resolve()
    if args.command == "coarse-request":
        coarse_request(bundle)
    elif args.command == "fine-request":
        passes = extract(bundle, "coarse", args.artifacts)
        write(bundle / "fine.request.json", fine_request(read(bundle / "coarse.request.json"), passes))
    elif args.command == "finish":
        return finish(bundle, args.artifacts)
    else:
        return finish(bundle, replay=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (C.InputError, T.PairError, ValueError, KeyError, TypeError, OSError) as exc:
        sys.exit(f"grid.py: {exc}")

#!/usr/bin/env python3
"""Issue #430 drawn-candidate tool: build and grade the `klt sim` legs.

  rz_candidate.py bench   <dut-netlist> <out-dir>
  rz_candidate.py control <dut-netlist> <schematic-netlist> <out-dir>
  rz_candidate.py grade   <dir>

`bench` builds the committed-bench legs for the extracted netlist of the
drawn nulling-resistor candidate: four single-corner AC legs, the binding
single-corner slew leg, the three 45-point grids, and DR-0012's nine
resistor x capacitor sections at the nominal point and at each binding
corner. 44 requests, each one corner unless it is a grid.

`control` builds the diagnostic controls of the record, none of which is
the committed bench: the same DUT with its `rppd` card swapped for an ideal
resistor, the schematic netlist with the `rppd` card, `method=gear` variants,
and the `rppd` model alone in a transient. They are evidence for a cause,
never for a bound.

`grade` reads every `klt sim` envelope (`*.json` with a `corners` list)
under a directory and prints the worst value of each graded measurement with
its corner, status and fleet job.

Every entry built from a DUT (kinds `ac`, `op` and `slew`) records
`deck_content_sha256`, klt_measure.py's path-independent digest of the deck
(issue #460), taken from the builder's summary; a `gear` leg's is recomputed
from the deck after its rewrite. The `probe` legs include no DUT and record
none.

A batch request gets `batch.capacity_wait_s = 600` unless it already sets
one, so a submit waits with backoff instead of failing on batch_no_capacity.
SG13G2_PEX_POINTS and KLT_PEX_SIM_BACKEND are read exactly as
klt_measure.py reads them.
"""
import argparse
import glob
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import klt_measure as km  # noqa: E402
import rz_screen as rz  # noqa: E402

#: The one definition lives in klt_measure (issue #468); re-exported so this
#: module's callers and tests keep `rz_candidate.sha256_file`.
sha256_file = km.sha256_file

CAP_LIB = "libs.tech/ngspice/models/cornerCAP.lib"
RES_LIB = "libs.tech/ngspice/models/cornerRES.lib"
RES_SECTIONS = ("res_bcs", "res_typ", "res_wcs")
CAP_SECTIONS = ("cap_bcs", "cap_typ", "cap_wcs")

#: Single corners, `process:temperature:vdd`. The phase-margin, GBW and
#: slew points are the ratified binding corners of spec/target-spec.md
#: section 2; `sf` is the second-tightest phase-margin corner of PR #439's
#: grid and `tt` the corner PR #431's TT diagnosis named.
AC_POINTS = {
    "ff": "mos_ff:125:1.32",
    "fs": "mos_fs:125:1.08",
    "sf": "mos_sf:125:1.32",
    "tt": "mos_tt:27:1.08",
}
SLEW_POINTS = {"ss": "mos_ss:-40:1.08"}

#: DR-0012's supplementary sweep: nine passive sections at nominal and at
#: each binding PVT corner for the rows the drawn resistor can move.
PASSIVE_AC_POINTS = {
    "ff": "mos_ff:125:1.32",
    "fs": "mos_fs:125:1.08",
    "tt27": "mos_tt:27:1.20",
}
PASSIVE_SLEW_POINTS = {"ss": "mos_ss:-40:1.08"}

#: Signed margin is taken against the request's own lower limit.
PM_LIMIT_RAD = -2.0943951023931953
GEAR_OPTION = "method=gear"
GEAR = ".options " + GEAR_OPTION
RPPD_CARD = re.compile(r"^(X\S+\s+\S+\s+\S+\s+\S+\s+rppd)(\s.*)$")
IDEAL_OHMS = 2000.6
PROBE_BODY = """* r3_cmc transient probe: the rppd model alone (issue #430 control)
* One PDK rppd (l=7.47u w=1u, the drawn nulling resistor's dimensions) driven
* by a voltage step through 2 pF: RC = 2 kOhm x 2 pF = 4 ns. No op-amp.
* vdd is the supply key the request alters per corner; it drives nothing.
vdd vddp 0 dc 1.08
Vstep in 0 pwl(0 0 50n 0 50.1n 1 300n 1 300.1n 0 800n 0)
XR1 in out 0 rppd l=7.47u w=1u
C1 out 0 2e-12
.options tnom=27 interp
"""
PROBE_MEASUREMENTS = (
    {"name": "vout_final_v", "spice": ".meas tran vout_final_v find v(out) at=800n", "unit": "V"},
    {"name": "t_10_90_s", "spice": ".meas tran t_10_90_s trig v(out) val=0.1 rise=1 targ v(out) val=0.9 rise=1", "unit": "s"},
)


def set_passives(req, res, cap):
    """Point the request's capacitor and resistor sections at `cap`/`res`."""
    hits = 0
    for proc in req["corners"]["process"]:
        sections = [proc["sections"][0]]
        for sec in proc["sections"][1:]:
            sec = dict(sec)
            if sec.get("lib") == CAP_LIB:
                sec["section"] = cap
                hits += 1
            if sec.get("lib") == RES_LIB:
                sec["section"] = res
                hits += 1
            sections.append(sec)
        proc["sections"] = sections
    return hits


def insert_options(body, option):
    """Return `body` with `.options <option>` after its last .options line."""
    lines = body.split("\n")
    last = max(i for i, line in enumerate(lines) if line.lower().startswith(".options"))
    lines.insert(last + 1, ".options " + option)
    return "\n".join(lines)


def insert_gear(body):
    """Return `body` with `.options method=gear` after its last .options line."""
    return insert_options(body, GEAR_OPTION)


def rewrite_rppd(text, rewrite):
    """Return `text` with its one `rppd` card rewritten by `rewrite(match)`.

    Loud: anything but exactly one `rppd` card exits 1.
    """
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if RPPD_CARD.match(line)]
    if len(hits) != 1:
        sys.exit(f"rz_candidate: expected exactly one rppd card, found {len(hits)}")
    i = hits[0]
    lines[i] = rewrite(RPPD_CARD.match(lines[i]))
    return "\n".join(lines)


def body_on_hub(text):
    """Move the `rppd` card's body terminal onto the `vss` hub (the #430
    `bodyhub` control's edit, applied to the extraction)."""
    return rewrite_rppd(text, lambda m: " ".join(m.group(1).split()[:3] + ["vss", "rppd"]) + m.group(2))


def ideal_swap(text, ohms=IDEAL_OHMS):
    """Return `text` with its one `rppd` card replaced by an ideal resistor.

    Loud: anything but exactly one `rppd` card exits 1 and writes nothing.
    """
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if RPPD_CARD.match(line)]
    if len(hits) != 1:
        sys.exit(f"rz_candidate: expected exactly one rppd card, found {len(hits)}")
    i = hits[0]
    toks = lines[i].split()
    lines[i] = f"Rz_cc {toks[1]} {toks[2]} {ohms:g}"
    return "\n".join(lines)


def _write_req(req, path):
    req.setdefault("batch", {}).setdefault("capacity_wait_s", 600)
    json.dump(req, open(path, "w"), indent=1)
    return dict(request=path, request_sha256=sha256_file(path))


def _ac(dut, out, name, point, res=None, cap=None):
    art = os.path.join(out, name)
    os.environ["SG13G2_PEX_POINTS"] = point
    b = km.build(dut, art)
    path = os.path.join(art, f"{name}.request.json")
    os.replace(os.path.join(art, "openloop_ac.request.json"), path)
    os.remove(os.path.join(art, "openloop_op.request.json"))
    req = json.load(open(path))
    req.pop("_comment", None)
    rewritten = set_passives(req, res, cap) if res else 0
    entry = dict(name=name, kind="ac", point=point, res=res, cap=cap, passive_sections_rewritten=rewritten,
                 deck_content_sha256=b["deck_content_sha256"])
    entry.update(_write_req(req, path))
    cs = req["corners"]
    entry["corners"] = len(cs["process"]) * len(cs["temperature_c"]) * len(cs["supply_v"]["vdd"])
    return entry


def _grid(dut, out, kind):
    art = os.path.join(out, f"grid_{kind}")
    os.environ.pop("SG13G2_PEX_POINTS", None)
    name = f"grid_{kind}"
    if kind == "slew":
        b = rz.slew_build(dut, art)
        path = os.path.join(art, f"{name}.request.json")
        os.replace(os.path.join(art, "slew.request.json"), path)
        measurements = b["measurements"]
    else:
        b = km.build(dut, art)
        path = os.path.join(art, f"{name}.request.json")
        os.replace(os.path.join(art, f"openloop_{kind}.request.json"), path)
        other = os.path.join(art, f"openloop_{'op' if kind == 'ac' else 'ac'}.request.json")
        if os.path.exists(other):
            os.remove(other)
        measurements = None
    req = json.load(open(path))
    req.pop("_comment", None)
    entry = dict(name=name, kind=kind, point=None, res=None, cap=None, passive_sections_rewritten=0, measurements=measurements,
                 deck_content_sha256=b["deck_content_sha256"])
    entry.update(_write_req(req, path))
    cs = req["corners"]
    entry["corners"] = len(cs["process"]) * len(cs["temperature_c"]) * len(cs["supply_v"]["vdd"])
    return entry


def slew_leg(dut, out, name, point, options=None):
    """The core of one slew-bench leg, shared with rz_solver: `rz.slew_build`
    into `<out>/<name>/`, the request renamed to `<name>.request.json`, and
    the optional `.options` rewrite of the bench body (with the deck digest
    recomputed from the rewritten deck). Returns `(summary, request,
    request_path, body_path, deck_content_sha256)`."""
    art = os.path.join(out, name)
    if point:
        os.environ["SG13G2_PEX_POINTS"] = point
    else:
        os.environ.pop("SG13G2_PEX_POINTS", None)
    b = rz.slew_build(dut, art)
    body = os.path.join(art, "tb_slew.body.spice")
    path = os.path.join(art, f"{name}.request.json")
    os.replace(os.path.join(art, "slew.request.json"), path)
    deck_content_sha256 = b["deck_content_sha256"]
    if options:
        rewritten = insert_options(open(body).read(), options)
        open(body, "w").write(rewritten)
        deck_content_sha256 = km.deck_content_sha256(rewritten, b["dut"])
    req = json.load(open(path))
    return b, req, path, body, deck_content_sha256


def _slew(dut, out, name, point, res=None, cap=None, gear=False, control=False, note=""):
    b, req, path, body, deck_content_sha256 = slew_leg(
        dut, out, name, point, options=GEAR_OPTION if gear else None)
    rewritten = set_passives(req, res, cap) if res else 0
    if control:
        req["_comment"] = ("issue #430 CONTROL, not the committed bench: "
                           + ("method=gear added; " if gear else "")
                           + (f"passive sections {res}/{cap}; " if res else "")
                           + (note + "; " if note else "")
                           + "otherwise sim/slew-rate/klt/slew.request.json unchanged")
    entry = dict(name=name, kind="slew", point=point, res=res, cap=cap, gear=bool(gear),
                 passive_sections_rewritten=rewritten, measurements=b["measurements"],
                 dut=dut, dut_sha256=sha256_file(dut), body_sha256=sha256_file(body),
                 deck_content_sha256=deck_content_sha256)
    entry.update(_write_req(req, path))
    entry["corners"] = b["corners"] if b["corners"] else len(req["corners"]["process"]) * len(
        req["corners"]["temperature_c"]) * len(req["corners"]["supply_v"]["vdd"])
    return entry


def bench(dut, out):
    """The 44 committed-bench legs. Returns the manifest list."""
    dut = os.path.abspath(dut)
    os.makedirs(out, exist_ok=True)
    manifest = []
    for tag, point in AC_POINTS.items():
        manifest.append(_ac(dut, out, f"cand_{tag}", point))
    for tag, point in SLEW_POINTS.items():
        manifest.append(_slew(dut, out, f"cand_{tag}_slew", point))
    for kind in ("ac", "op", "slew"):
        manifest.append(_grid(dut, out, kind))
    for tag, point in PASSIVE_AC_POINTS.items():
        for res in RES_SECTIONS:
            for cap in CAP_SECTIONS:
                manifest.append(_ac(dut, out, f"pass_{tag}_{res}_{cap}", point, res, cap))
    for tag, point in PASSIVE_SLEW_POINTS.items():
        for res in RES_SECTIONS:
            for cap in CAP_SECTIONS:
                manifest.append(_slew(dut, out, f"pass_{tag}_{res}_{cap}_slew", point, res, cap))
    _manifest(manifest, out)
    return manifest


def control(dut, schematic, out):
    """The diagnostic controls. Returns the manifest list.

    The uppercase `_comment` is written only on the gear legs and the ideal
    and single schematic legs because that is exactly the set that carried
    it in the requests submitted for the #430 record; the two probes carry
    their own lowercase comment (see `probe`) and the other 20 legs carry
    none. The split is deliberate and must stay as submitted: widening it
    would change the generated request bytes and break the record's
    byte-for-byte regeneration of the 35 committed controls
    (rz-layout-430 README section 2).
    """
    dut = os.path.abspath(dut)
    os.makedirs(out, exist_ok=True)
    point = SLEW_POINTS["ss"]
    manifest = []
    ideal = os.path.join(out, "opamp_core_pex_ideal_rz.spice")
    text = open(dut).read()
    open(ideal, "w").write(ideal_swap(text))
    entry = _slew(ideal, out, "ctl_ideal_ss_slew", point, control=True)
    entry["swap"] = "rppd card -> ideal resistor, 2000.6 ohm"
    manifest.append(entry)
    manifest.append(_slew(schematic, out, "ctl_sch_ss_slew", point, control=True))
    manifest.append(_slew(schematic, out, "ctl_sch_grid_slew", None))
    for res in RES_SECTIONS:
        for cap in CAP_SECTIONS:
            manifest.append(_slew(schematic, out, f"ctl_sch_ss_{res}_{cap}_slew", point, res, cap))
    for name, pt in (("ctl_gear_ss_slew", point), ("ctl_gear_grid_slew", None)):
        manifest.append(_slew(dut, out, name, pt, gear=True, control=True))
    for res in RES_SECTIONS:
        for cap in CAP_SECTIONS:
            manifest.append(_slew(dut, out, f"ctl_gear_ss_{res}_{cap}_slew", point, res, cap, gear=True,
                                  control=True))
    manifest += variants(dut, out)
    manifest += probe(out)
    _manifest(manifest, out)
    return manifest


def variants(dut, out):
    """Instance-parameter variants of the `rppd` card on the same extraction.

    `sw_et=1` switches the model's self-heating on, which replaces its
    1e6 S thermal tie with the physical thermal conductance; `bodyhub` moves
    the card's body terminal from its parasitic star node onto the `vss` hub
    (`body_on_hub`, shared with rz_solver).
    """
    point = SLEW_POINTS["ss"]
    text = open(dut).read()
    manifest = []
    swet1 = os.path.join(out, "opamp_core_pex_swet1.spice")
    open(swet1, "w").write(rewrite_rppd(text, lambda m: f"{m.group(1)}{m.group(2)} sw_et=1"))
    for res, cap in [(r, c) for r in RES_SECTIONS for c in CAP_SECTIONS]:
        manifest.append(_slew(swet1, out, f"ctl_swet1_ss_{res}_{cap}_slew", point, res, cap))
    bodyhub = os.path.join(out, "opamp_core_pex_bodyhub.spice")
    open(bodyhub, "w").write(body_on_hub(text))
    manifest.append(_slew(bodyhub, out, "ctl_bodyhub_ss_res_typ_cap_typ_slew", point, "res_typ", "cap_typ"))
    return manifest


def probe_request():
    """The `rppd`-alone probes' request base, shared with rz_solver: the
    committed slew.request.json restricted to the single binding slew corner
    (`mos_ss` / `1.08 V` / `-40 C`), pointing at `probe.body.spice`, with
    PROBE_MEASUREMENTS. The caller appends its own `_comment`: rz_candidate's
    probes set `batch` first, so their key order (`batch` before `_comment`)
    stays as the #430 record submitted it."""
    slew_req = json.load(open(os.path.join(rz.SLEW_DIR, "slew.request.json")))
    req = {k: v for k, v in slew_req.items() if k != "_comment"}
    req["netlist"] = "probe.body.spice"
    ss = next(p for p in slew_req["corners"]["process"] if p["name"] == "mos_ss")
    req["corners"] = {"process": [ss], "supply_v": {"vdd": [1.08]}, "temperature_c": [-40]}
    req["measurements"] = [dict(m) for m in PROBE_MEASUREMENTS]
    return req


def probe(out):
    """The `rppd` model alone in a transient, default method and `method=gear`."""
    manifest = []
    for tag, gear in (("default", False), ("gear", True)):
        name = f"probe_r_{tag}"
        art = os.path.join(out, name)
        os.makedirs(art, exist_ok=True)
        body = PROBE_BODY + (GEAR + "\n" if gear else "")
        open(os.path.join(art, "probe.body.spice"), "w").write(body)
        req = probe_request()
        req.setdefault("batch", {}).setdefault("capacity_wait_s", 600)
        req["_comment"] = ("issue #430 control: rppd model alone in transient, same "
                           "analysis/options/osdi preload as the slew bench"
                           + (" plus method=gear" if gear else ""))
        path = os.path.join(art, f"{name}.request.json")
        entry = dict(name=name, kind="probe", point="mos_ss:-40:1.08", gear=gear)
        entry.update(_write_req(req, path))
        entry["corners"] = 1
        manifest.append(entry)
    return manifest


def _manifest(manifest, out):
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)


def grade(directory):
    """Print the worst value of every graded measurement over a directory's envelopes."""
    rows = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            env = json.load(open(path))
        except ValueError:
            continue
        if not isinstance(env, dict) or "corners" not in env or "status" not in env:
            continue
        job = (env.get("environment", {}).get("remote") or {}).get("job_id")
        for corner in env["corners"]:
            for m in corner["measurements"]:
                v = m.get("value")
                if v is None or not math.isfinite(v):
                    continue
                key = m["name"]
                pick = max if key in ("ivdd_total_a", "vout_dc_v", "op_vout_offset_frac", "op_vout_rail_frac") else min
                row = rows.setdefault(key, [v, corner["corner_id"], m["status"], job])
                if (pick is max and v > row[0]) or (pick is min and v < row[0]):
                    rows[key] = [v, corner["corner_id"], m["status"], job]
    for key in sorted(rows):
        v, corner, status, job = rows[key]
        extra = f" PM={180 + math.degrees(v):.4f} margin={v - PM_LIMIT_RAD:+.9f}" if key == "phase_at_ugf_rad" else ""
        print(f"{key:22s} {v!r}{extra} at {corner} [{status}] job {job}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("bench")
    p.add_argument("dut")
    p.add_argument("out")
    p = sub.add_parser("control")
    p.add_argument("dut")
    p.add_argument("schematic")
    p.add_argument("out")
    p = sub.add_parser("grade")
    p.add_argument("directory")
    args = ap.parse_args(argv)
    os.environ.setdefault("KLT_PEX_SIM_BACKEND", "batch")
    if args.cmd == "bench":
        manifest = bench(args.dut, args.out)
    elif args.cmd == "control":
        manifest = control(args.dut, args.schematic, args.out)
    else:
        grade(args.directory)
        return 0
    for entry in manifest:
        print(entry["kind"].ljust(4), entry["name"].ljust(36), entry["point"], entry["corners"],
              entry["request_sha256"][:12])
    print(len(manifest), "requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Issue #451 diagnostic tool: build the `klt sim` legs that name the cause.

  rz_solver.py controls <dut-netlist> <schematic-netlist> <out-dir>
  rz_solver.py grade   <dir>

`controls` builds the issue #451 legs from the issue #430 candidate: the
committed slew bench re-run on the extraction, the star-surgery controls
that isolate the trigger (leaf merges, body-resistance ladder, body-on-hub),
the schematic-leg body-resistor control, the `rppd`-model-alone probe, the
solver-option ladder that separates Newton non-convergence from LTE step
collapse, and the 45-corner grids of the committed bench, the body-hub DUT
and the schematic netlist. 17 requests: 14 single-corner legs at
`mos_ss:-40:1.08` (the binding slew corner) plus three grids. Every leg is
a CONTROL of the solver investigation -- none of them grades a spec row on
its own; the body-hub and schematic grids bracket what the extracted-leg
slew row would read once the extraction-side cause is fixed.

`grade` is rz_candidate.py's grade: the worst value of every graded
measurement in a directory of envelopes.

Every entry built from a DUT (kinds `slew` and `slew-grid`) records
`deck_content_sha256`, klt_measure.py's path-independent digest of the deck
(issue #460), taken from the builder's summary; an `options` leg's is
recomputed from the deck after its rewrite. The `probe` leg includes no DUT
and records none.

A batch request gets `batch.capacity_wait_s = 600` unless it already sets
one. SG13G2_PEX_POINTS and KLT_PEX_SIM_BACKEND are read exactly as
klt_measure.py reads them.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import klt_measure as km  # noqa: E402
import rz_candidate as rzc  # noqa: E402
import rz_screen as rz  # noqa: E402

#: The binding slew corner (spec/target-spec.md section 2): where the
#: committed bench aborts on the extraction (issue #430 record, section 5).
SS_POINT = "mos_ss:-40:1.08"

#: The star leaf the klt 0.9.0 extraction gives the `rppd` card's body
#: terminal: `X$39 $5__t4 $8__t1 vss__t23 rppd l=7.47U w=1U`.
BODY_LEAF_NET = "vss"
BODY_LEAF = "vss__t23"
#: The star resistance of that leaf as extracted (`Rvss_t23`).
BODY_LEAF_OHMS = "6.06319582466"
#: A second vss star leaf, of the all-vss-device `X$1` (drain `vss__t1`,
#: gate `vss__t2`, source `vss__t0`, bulk `vss__t24`): keeping the body
#: leaf plus this leaf reproduces the abort when the rest of the vss star
#: is merged.
COMPANION_LEAF = "vss__t0"

#: The ladder rungs of the body star resistance: the abort survives all of
#: them, so it is the extra node, not the ohms, that matters.
BODY_R_RUNGS = (("1m", "1e-3"), ("6meg", "6.06319582466e6"))

#: Solver-option ladder: `itl4` rungs separate Newton non-convergence from
#: LTE step collapse (the fatal timestep cut is iteration-limited), and
#: `reltol`/`noopiter` show it is not a tolerance question. Names outside
#: klt's `options.ngspice_options` allow-list ride the circuit body, after
#: its last `.options` line, exactly as the gear controls of #430 did.
SOLVER_LADDER = (
    ("itl4_100", "itl4=100"),
    ("itl4_500", "itl4=500"),
    ("reltol_1e2", "reltol=1e-2"),
    ("noopiter", "noopiter"),
)

RPPD_CARD = rzc.RPPD_CARD
STAR_R = re.compile(r"^R(\S+?)_t(\d+)\s+(\S+?)__t\d+\s+(\S+)\s+(\S+)\s*$")
SCH_CARD = re.compile(r"^(X\S+\s+\S+\s+\S+\s+)vss(\s+rppd\s+.*)$", re.M)


def _net_key(node):
    r"""`vss`, `\$3` and `3` all key to `vss` and `3`."""
    return node.lstrip("\\").lstrip("$")


def leaf_node_names(text, net):
    """The `NET__tK` star-leaf node names of `net`, in deck order.

    `net` may be spelled with or without the extractor's `\\$` escaping.
    """
    names = []
    for line in text.split("\n"):
        m = STAR_R.match(line)
        if m and _net_key(m.group(3)) == _net_key(net):
            names.append(m.group(3) + "__t" + m.group(2))
    return names


def merge_leaves(text, pairs):
    """Merge each `(net, NET__tK)` leaf onto its hub: the star resistor goes
    and every reference to the leaf node is renamed to the hub, spelled as
    the deck spells it (`\\$3` for the escaped nets).

    Loud: a leaf that is not a star leaf of its net is an error, and so is
    a drop/rename count mismatch. Returns (text, n_dropped).
    """
    want = {}
    for net, leaf in pairs:
        if _net_key(leaf.split("__t")[0]) != _net_key(net):
            sys.exit(f"rz_solver: leaf {leaf!r} is not a leaf of net {net!r}")
        want[leaf] = None
    hubs = {}
    for line in text.split("\n"):
        m = STAR_R.match(line)
        if m and m.group(3) + "__t" + m.group(2) in want:
            want[m.group(3) + "__t" + m.group(2)] = m.group(4)
    missing = [leaf for leaf, hub in want.items() if hub is None]
    if missing:
        sys.exit(f"rz_solver: not star leaves of this extraction: {missing}")
    out = []
    dropped = 0
    for line in text.split("\n"):
        m = STAR_R.match(line)
        if m and m.group(3) + "__t" + m.group(2) in want:
            dropped += 1
            continue
        for leaf, hub in want.items():
            line = re.sub(r"(?<![A-Za-z0-9_])\\?" + re.escape(leaf) + r"\b",
                          lambda m, h=hub: h, line)
        out.append(line)
    if dropped != len(want):
        sys.exit(f"rz_solver: dropped {dropped} star resistors, expected {len(want)}")
    return "\n".join(out), dropped


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def set_leaf_resistance(text, leaf, ohms):
    """Rewrite the star resistor of `leaf` (`NET__tK`) to `ohms`."""
    net = _net_key(leaf.split("__t")[0])
    pat = re.compile(r"^(R\S*?" + re.escape(net) + r"_t\d+\s+\\?" + re.escape(leaf)
                     + r"\s+\\?" + re.escape(net) + r"\s+)\S+$", re.M)
    new, n = pat.subn(lambda m: m.group(1) + str(ohms), text, count=1)
    if n != 1:
        sys.exit(f"rz_solver: no star resistor for leaf {leaf!r}")
    return new


def body_on_hub(text):
    """Move the `rppd` card's body terminal onto the `vss` hub (the #430
    `bodyhub` control's edit, applied to the extraction)."""
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if RPPD_CARD.match(line)]
    if len(hits) != 1:
        sys.exit(f"rz_solver: expected exactly one rppd card, found {len(hits)}")
    i = hits[0]
    card = RPPD_CARD.match(lines[i])
    lines[i] = " ".join(card.group(1).split()[:3] + ["vss", "rppd"]) + card.group(2)
    return "\n".join(lines)


def sch_body_resistor(text, ohms=BODY_LEAF_OHMS):
    """The schematic netlist with the `rppd` body terminal behind the
    extraction's body-star resistance: `XRz ... vss rppd` becomes
    `XRz ... rzbody rppd` plus `Rrzbody rzbody vss <ohms>`."""
    new, n = SCH_CARD.subn(lambda m: m.group(1) + "rzbody" + m.group(2)
                           + "\nRrzbody rzbody vss " + str(ohms), text, count=1)
    if n != 1:
        sys.exit("rz_solver: schematic netlist has no single `... vss rppd` card")
    return new


def insert_options(body, option):
    """Return `body` with `.options <option>` after its last .options line."""
    lines = body.split("\n")
    last = max(i for i, line in enumerate(lines) if line.lower().startswith(".options"))
    lines.insert(last + 1, ".options " + option)
    return "\n".join(lines)


def probe_body(ohms=BODY_LEAF_OHMS):
    """The `rppd` model alone in a transient, body terminal behind `ohms`."""
    return ("* issue #451 probe: the rppd model alone, body behind its\n"
            "* extraction star resistance (no amplifier, no star network).\n"
            "vdd vddp 0 dc 1.08\n"
            "Vstep in 0 pwl(0 0 50n 0 50.1n 1 300n 1 300.1n 0 800n 0)\n"
            "XR1 in out rzbody rppd l=7.47u w=1u\n"
            f"Rrzbody rzbody 0 {ohms}\n"
            "C1 out 0 2e-12\n"
            ".options tnom=27 interp\n")


def _write_req(req, path):
    req.setdefault("batch", {}).setdefault("capacity_wait_s", 600)
    json.dump(req, open(path, "w"), indent=1)
    return dict(request=path, request_sha256=sha256_file(path))


def _leg(dut, out, name, point, options=None, note=""):
    """One slew leg of the investigation on `dut`; `options` names a solver
    `.options` line to insert into the bench body after its last .options."""
    art = os.path.join(out, name)
    os.environ["SG13G2_PEX_POINTS"] = point if point else ""
    if not point:
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
    req.pop("_comment", None)
    req["_comment"] = ("issue #451 CONTROL, not the committed bench: " + note
                       + "; otherwise sim/slew-rate/klt/slew.request.json unchanged")
    entry = dict(name=name, kind="slew", point=point, options=options, note=note,
                 measurements=b["measurements"], dut=os.path.abspath(dut),
                 dut_sha256=sha256_file(dut), body_sha256=sha256_file(body),
                 deck_content_sha256=deck_content_sha256)
    entry.update(_write_req(req, path))
    entry["corners"] = b["corners"] if b["corners"] else len(req["corners"]["process"]) * len(
        req["corners"]["temperature_c"]) * len(req["corners"]["supply_v"]["vdd"])
    return entry


def _grid(dut, out, name, note):
    art = os.path.join(out, name)
    os.environ.pop("SG13G2_PEX_POINTS", None)
    b = rz.slew_build(dut, art)
    path = os.path.join(art, f"{name}.request.json")
    os.replace(os.path.join(art, "slew.request.json"), path)
    req = json.load(open(path))
    req.pop("_comment", None)
    req["_comment"] = ("issue #451 CONTROL, not the committed bench: " + note
                       + "; otherwise sim/slew-rate/klt/slew.request.json unchanged")
    entry = dict(name=name, kind="slew-grid", point=None, options=None, note=note,
                 measurements=b["measurements"], dut=os.path.abspath(dut),
                 dut_sha256=sha256_file(dut), deck_content_sha256=b["deck_content_sha256"])
    entry.update(_write_req(req, path))
    cs = req["corners"]
    entry["corners"] = len(cs["process"]) * len(cs["temperature_c"]) * len(cs["supply_v"]["vdd"])
    return entry


def controls(dut, schematic, out):
    """The 17 issue-#451 legs. Returns the manifest list."""
    dut = os.path.abspath(dut)
    schematic = os.path.abspath(schematic)
    os.makedirs(out, exist_ok=True)
    text = open(dut).read()
    manifest = []

    def write_variant(tag, body_text):
        path = os.path.join(out, f"opamp_core_pex_{tag}.spice")
        open(path, "w").write(body_text)
        return path

    manifest.append(_leg(dut, out, "c451_ss_slew", SS_POINT,
                         note="the committed bench, the #430 extraction, unchanged"))
    for tag, option in SOLVER_LADDER:
        manifest.append(_leg(dut, out, f"c451_ss_slew_{tag}", SS_POINT, options=option,
                             note=f"solver ladder: .options {option} in the bench body"))
    merge23, _ = merge_leaves(text, [(BODY_LEAF_NET, BODY_LEAF)])
    leaf_only, n_leaf_only = merge_leaves(
        text, [(n, leaf) for n in ("3", "5", "6", "8", "ibias", "inn", "inp", "out", "vdd")
               for leaf in leaf_node_names(text, n)]
        + [(BODY_LEAF_NET, leaf) for leaf in leaf_node_names(text, BODY_LEAF_NET)
           if leaf != BODY_LEAF])
    rest_merged, n_rest = merge_leaves(
        text, [(BODY_LEAF_NET, leaf) for leaf in leaf_node_names(text, BODY_LEAF_NET)
               if leaf != BODY_LEAF])
    keep23t0, n_keep = merge_leaves(
        text, [(BODY_LEAF_NET, leaf) for leaf in leaf_node_names(text, BODY_LEAF_NET)
               if leaf not in (BODY_LEAF, COMPANION_LEAF)])
    for tag, body_text, dropped, note in (
        ("merge23", merge23, 1,
         f"star surgery: the {BODY_LEAF} body leaf alone merged onto the vss hub"),
        ("bodyleaf_only", leaf_only, n_leaf_only,
         f"star surgery: every star leaf merged except the {BODY_LEAF} body leaf"),
        ("vss_rest_merged", rest_merged, n_rest,
         f"star surgery: the vss star merged except the {BODY_LEAF} body leaf"),
        ("keep23t0", keep23t0, n_keep,
         f"star surgery: vss star reduced to the {BODY_LEAF} body leaf plus the "
         f"{COMPANION_LEAF} leaf of X$1"),
    ):
        manifest.append(_leg(write_variant(tag, body_text), out, f"c451_{tag}_ss_slew",
                             SS_POINT, note=note + f" ({dropped} star resistors dropped)"))
    for tag, ohms in BODY_R_RUNGS:
        manifest.append(_leg(write_variant(f"bodyR{tag}", set_leaf_resistance(text, BODY_LEAF, ohms)),
                             out, f"c451_bodyR{tag}_ss_slew", SS_POINT,
                             note=f"the {BODY_LEAF} star resistance set to {ohms} ohm"))
    manifest.append(_leg(write_variant("bodyhub", body_on_hub(text)), out,
                         "c451_bodyhub_ss_slew", SS_POINT,
                         note="the rppd card's body terminal moved onto the vss hub"))
    sch_body = os.path.join(out, "opamp_core_sch_bodyR.spice")
    open(sch_body, "w").write(sch_body_resistor(open(schematic).read()))
    manifest.append(_leg(sch_body, out, "c451_sch_bodyR_ss_slew", SS_POINT,
                         note=f"the schematic netlist, rppd body behind {BODY_LEAF_OHMS} ohm"))

    art = os.path.join(out, "c451_probe_r_bodyR")
    os.makedirs(art, exist_ok=True)
    open(os.path.join(art, "probe.body.spice"), "w").write(probe_body())
    slew_req = json.load(open(os.path.join(rz.SLEW_DIR, "slew.request.json")))
    req = {k: v for k, v in slew_req.items() if k != "_comment"}
    req["netlist"] = "probe.body.spice"
    ss = next(p for p in slew_req["corners"]["process"] if p["name"] == "mos_ss")
    req["corners"] = {"process": [ss], "supply_v": {"vdd": [1.08]}, "temperature_c": [-40]}
    req["measurements"] = [dict(m) for m in rzc.PROBE_MEASUREMENTS]
    req["_comment"] = ("issue #451 CONTROL, not the committed bench: the rppd model "
                       "alone in a transient, body behind its extraction star "
                       "resistance, same analysis/options/osdi preload as the slew bench")
    path = os.path.join(art, "c451_probe_r_bodyR.request.json")
    entry = dict(name="c451_probe_r_bodyR", kind="probe", point=SS_POINT, options=None,
                 note="the rppd model alone, body behind 6.06 ohm")
    entry.update(_write_req(req, path))
    entry["corners"] = 1
    manifest.append(entry)

    manifest.append(_grid(dut, out, "c451_grid_slew",
                          note="the committed bench, the #430 extraction, unchanged (45 corners)"))
    manifest.append(_grid(write_variant("bodyhub", body_on_hub(text)), out,
                          "c451_bodyhub_grid_slew",
                          note="the rppd card's body terminal moved onto the vss hub"))
    manifest.append(_grid(schematic, out, "c451_sch_grid_slew",
                          note="the schematic netlist with its rppd card"))

    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("controls")
    p.add_argument("dut")
    p.add_argument("schematic")
    p.add_argument("out")
    p = sub.add_parser("grade")
    p.add_argument("directory")
    args = ap.parse_args(argv)
    os.environ.setdefault("KLT_PEX_SIM_BACKEND", "batch")
    if args.cmd == "controls":
        manifest = controls(args.dut, args.schematic, args.out)
    else:
        rzc.grade(args.directory)
        return 0
    for entry in manifest:
        print(entry["kind"].ljust(9), entry["name"].ljust(28), entry["point"],
              entry["corners"], entry["request_sha256"][:12])
    print(len(manifest), "requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())

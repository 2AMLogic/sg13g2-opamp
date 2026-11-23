#!/usr/bin/env python3
"""Issue #430 screening tool: a nulling resistor in series with the Miller cap.

  rz_screen.py dut        <extracted-netlist> <out-spice> --rz OHMS [--bare]
  rz_screen.py slew-build <dut-netlist> <artifacts-dir>

`dut` derives a screening DUT from a `klt pex` extraction. The capacitor's
d2-side terminal is lifted onto a new node (`cc_rz`) and an ideal resistor
(`Rz_cc`, OHMS) is inserted between that node and the original terminal. The
`out`-side plate is untouched. `--bare` first builds the drawn-device DUT of
sim/post-layout/cc-sizing-430/README.md section 1: every extracted parasitic
`R`/`C` card is dropped and each `<net>__tN` terminal node is collapsed onto
its hub net. Loud: anything but exactly one `cap_cmim` card between `out` and
one other net, or a resistance below 0.01 ohm, exits 1 and writes nothing
(ngspice clamps an exact 0 ohm card with a warning, and the 1e9 S
conductance of a 1e-9 ohm card ill-conditions the matrix: av0 then reads
0.21 dB low). Prints a JSON summary on stdout.

`slew-build` is klt_measure.py `build`'s counterpart for the slew bench
(sim/slew-rate/klt): the committed body's DUT include is re-pointed at the
DUT (a `.SUBCKT` DUT is instantiated as `Xdut`, pins matched by name), and
the six measurements and three B-sources that read the d1/d2/tail internal
nodes are dropped, because a `.SUBCKT` DUT hides them. Everything else --
drive, load, analysis, the edge, linearity, pre-edge and drive-integrity
measurements and their ratified limits -- is the committed bench.
SG13G2_PEX_POINTS and KLT_PEX_SIM_BACKEND are read exactly as klt_measure.py
reads them. A batch request gets `batch.capacity_wait_s = 600` unless it
already sets one: the fleet is vCPU-budgeted, so a submit waits with backoff
instead of failing on batch_no_capacity. Prints a JSON summary on stdout:
`netlist_sha256` is the deck digest klt records as
`provenance.input.content_hash` (the deck embeds the DUT's absolute path, so
it reproduces only from the checkout that built it), `deck_content_sha256` is
the path-independent digest of the same deck (issue #460).
"""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import klt_measure as km  # noqa: E402

#: The one definition lives in klt_measure (issue #468); re-exported so this
#: module's callers and tests keep `rz_screen.sha256_file`.
sha256_file = km.sha256_file

CAP_MODEL = "cap_cmim"
OUT_PIN = "out"
RZ_NODE = "cc_rz"
RZ_NAME = "Rz_cc"
CAP_CARD = re.compile(r"^X\S+\s+(\S+)\s+(\S+)\s+" + CAP_MODEL + r"(\s|$)")
PARASITIC_CARD = re.compile(r"^(R\S*_t\d+|Rvsubs_dctie|C\S+)\s")
TERMINAL_NODE = re.compile(r"__t\d+\b")
INTERNAL_NODES = ("d1", "d2", "tail", "fd1", "fd2", "ftail")
INTERNAL_SOURCES = ("Bfd1", "Bfd2", "Bftail")
DROPPED_MEASUREMENTS = 6
MIN_OHMS = 0.01
SLEW_DIR = os.path.join(HERE, "..", "slew-rate", "klt")


def hub(node):
    return re.sub(r"__t\d+$", "", node)


def bare(text):
    """Return the drawn-device DUT: no parasitic cards, no `<net>__tN` nodes."""
    out, dropped = [], 0
    for line in text.split("\n"):
        if PARASITIC_CARD.match(line):
            dropped += 1
            continue
        out.append(line if line.startswith("*") else TERMINAL_NODE.sub("", line))
    if dropped == 0:
        sys.exit("rz_screen: no parasitic star network found to strip")
    if any("__t" in l for l in out if not l.startswith("*")):
        sys.exit("rz_screen: a `<net>__tN` node survived the collapse")
    return "\n".join(out)


def insert_rz(text, ohms, side=None):
    """Return (netlist text, summary) with Rz in series with the cap's non-`out` plate.

    `side` (um, optional) also resizes the square capacitor: the card's `l=` and
    `w=` are both rewritten, the way cc-sizing-430 screened its candidate sides.
    """
    if not math.isfinite(ohms) or ohms < MIN_OHMS:
        sys.exit(f"rz_screen: --rz must be a finite ohms value >= {MIN_OHMS:g}, got {ohms!r}: "
                 "ngspice warns on an exact 0 ohm card and clamps it, and a near-zero "
                 "card such as 1e-9 ohm is accepted but its 1e9 S conductance ill-conditions "
                 "the matrix (measured: av0 reads 0.21 dB low). Use 0.1 ohm for a transform "
                 "control.")
    if side is not None and not (math.isfinite(side) and side > 0):
        sys.exit(f"rz_screen: --cap-side must be a finite length in um > 0, got {side!r}")
    lines = text.split("\n")
    hits = [(i, m) for i, l in enumerate(lines) for m in [CAP_CARD.match(l)] if m]
    if len(hits) != 1:
        sys.exit(f"rz_screen: expected exactly one {CAP_MODEL} card, found {len(hits)}")
    i, m = hits[0]
    plates = (m.group(1), m.group(2))
    out_side = [k for k in (0, 1) if hub(plates[k]).lower() == OUT_PIN]
    if len(out_side) != 1:
        sys.exit(f"rz_screen: {CAP_MODEL} card is not between {OUT_PIN} and one other net: {lines[i]!r}")
    d2_side = 1 - out_side[0]
    d2_terminal = plates[d2_side]
    original = lines[i]
    toks = original.split()
    if side is not None:
        params = " ".join(toks[4:])
        dims = re.findall(r"([lw])=(\S+)", params)
        if sorted(k for k, _ in dims) != ["l", "w"] or len(params.split()) != 2:
            sys.exit(f"rz_screen: {CAP_MODEL} card has no l=/w= pair to resize: {original!r}")
        toks = toks[:4] + [f"l={side:g}U", f"w={side:g}U"]
    toks[1 + d2_side] = RZ_NODE
    lines[i] = " ".join(toks)
    j = i + 1
    while j < len(lines) and lines[j].startswith("+"):
        j += 1
    rz_card = f"{RZ_NAME} {RZ_NODE} {d2_terminal} {ohms:g}"
    lines.insert(j, rz_card)
    summary = {"cap_card": lines[i], "rz_card": rz_card, "d2_terminal": d2_terminal,
               "out_terminal": plates[out_side[0]], "cap_card_before": original}
    return "\n".join(lines), summary


def dut(src, dst, ohms, is_bare, side=None):
    if not os.path.isfile(src) or os.path.getsize(src) == 0:
        sys.exit(f"rz_screen: extraction netlist not found/empty: {src}")
    text = open(src).read()
    if is_bare:
        text = bare(text)
    new, summary = insert_rz(text, ohms, side)
    with open(dst, "w") as f:
        f.write(new)
    summary.update(out=os.path.abspath(dst), sha256=sha256_file(dst), rz_ohms=ohms,
                   cap_side_um=side, bare=is_bare, source=os.path.abspath(src),
                   source_sha256=sha256_file(src))
    return summary


def restrict(req, spec):
    """Keep only the grid axes SG13G2_PEX_POINTS names; return the corner count."""
    return km.restrict_corners(req, spec, caller="rz_screen")


def reads_internal(spice):
    return any(re.search(r"\bv\(" + n + r"\)", spice) for n in INTERNAL_NODES)


def slew_build(dut_path, art):
    dut_path = os.path.abspath(dut_path)
    if not os.path.isfile(dut_path) or os.path.getsize(dut_path) == 0:
        sys.exit(f"rz_screen: DUT netlist not found/empty: {dut_path}")
    os.makedirs(art, exist_ok=True)
    body_path = os.path.join(art, "tb_slew.body.spice")
    body = open(os.path.join(SLEW_DIR, "tb_slew.body.spice")).read()
    new, n = re.subn(r"^\.include\s+\S*opamp_core\.spice\s*$",
                     "\n".join(km.dut_lines(dut_path)), body, flags=re.M)
    if n != 1:
        sys.exit("rz_screen: slew bench body has no single DUT .include line")
    kept, dropped = [], []
    for line in new.split("\n"):
        (dropped if line.split(" ")[0] in INTERNAL_SOURCES else kept).append(line)
    if len(dropped) != len(INTERNAL_SOURCES):
        sys.exit(f"rz_screen: expected {len(INTERNAL_SOURCES)} internal-node B-sources, dropped {len(dropped)}")
    deck = "\n".join(kept)
    open(body_path, "w").write(deck)

    req = json.load(open(os.path.join(SLEW_DIR, "slew.request.json")))
    req.pop("_comment", None)
    req["netlist"] = "tb_slew.body.spice"
    if "KLT_PEX_SIM_BACKEND" in os.environ:
        req["backend"] = os.environ["KLT_PEX_SIM_BACKEND"]
    if req.get("backend") == "batch":
        req.setdefault("batch", {}).setdefault("capacity_wait_s", 600)
    before = len(req["measurements"])
    req["measurements"] = [m for m in req["measurements"] if not reads_internal(m["spice"])]
    if before - len(req["measurements"]) != DROPPED_MEASUREMENTS:
        sys.exit(f"rz_screen: expected to drop {DROPPED_MEASUREMENTS} internal-node "
                 f"measurements, dropped {before - len(req['measurements'])}")
    corners = restrict(req, os.environ["SG13G2_PEX_POINTS"]) if os.environ.get("SG13G2_PEX_POINTS") else None
    req_path = os.path.join(art, "slew.request.json")
    json.dump(req, open(req_path, "w"), indent=1)
    return {"netlist": body_path, "netlist_sha256": sha256_file(body_path),
            "deck_content_sha256": km.deck_content_sha256(deck, dut_path), "request": req_path,
            "dut": dut_path, "dut_sha256": sha256_file(dut_path), "backend": req.get("backend"),
            "corners": corners, "measurements": len(req["measurements"])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dut", help="derive a screening DUT with Rz in series with the Miller cap")
    d.add_argument("src", help="extracted (.SUBCKT or flat) netlist")
    d.add_argument("dst", help="screening DUT to write")
    d.add_argument("--rz", type=float, required=True,
                   help=f"nulling resistance in ohms (>= {MIN_OHMS:g}; 0.1 ohm is a transform control)")
    d.add_argument("--bare", action="store_true",
                   help="strip the extracted parasitics first (drawn-device DUT)")
    d.add_argument("--cap-side", type=float, default=None, dest="cap_side",
                   help="also resize the square Miller capacitor to this side in um")
    s = sub.add_parser("slew-build", help="build the slew-bench body and request for a DUT")
    s.add_argument("dut", help="DUT netlist the slew bench measures")
    s.add_argument("art", help="artifacts directory for the body and the request")
    a = ap.parse_args(argv)
    summary = (dut(a.src, a.dst, a.rz, a.bare, a.cap_side) if a.cmd == "dut"
               else slew_build(a.dut, a.art))
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

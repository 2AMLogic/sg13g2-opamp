#!/usr/bin/env python3
"""Build and read the `klt sim` requests behind measure_openloop_ac.sh.

  klt_measure.py build   <dut-netlist> <artifacts-dir>
  klt_measure.py convert <ac-envelope.json> <op-envelope.json>   -> stdout

`build` writes, into <artifacts-dir>, a circuit body (the committed open-loop
AC bench, sim/post-layout/klt/tb_openloop_ac.body.spice, with its DUT include
re-pointed at <dut-netlist>) and the AC and OP `klt sim` requests next to it.
A flat DUT is included as-is; a `.SUBCKT` DUT (the netlist `klt pex` extracts)
is included and instantiated as `Xdut` with pins matched BY NAME to the bench
nodes (vdd vss inn inp out ibias). Internal-node measurements (d1/d2/tail) are
dropped from the OP request so BOTH legs run the identical bench.

`convert` joins the two envelopes on (process, vdd, temperature) and prints the
measurement document `klt pex --measure-command` expects. Loud, never partial:
any corner that is not graded pass/fail, any missing or non-finite value, a
corner-count mismatch, or a non-regulating DC point exits 1 with no document.

Environment (optional): SG13G2_PEX_POINTS="mos_tt:27:1.20" restricts the grid to
those points (debug probe). KLT_PEX_SIM_BACKEND overrides the requests' own
`"backend": "batch"` (the shared-host rule is that grids go to the batch fleet).
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KLT_DIR = os.path.join(HERE, "klt")
PINS = ("vdd", "vss", "inn", "inp", "out", "ibias")
DROP_NODES = re.compile(r"\bv\((d1|d2|tail)\)")
# The ratified grid axes (spec/target-spec.md Sec 1); the requests carry them.
EXPECTED_CORNERS = 45


def fmt_vdd(v):
    return f"{float(v):.2f}"


def parse_points(spec):
    pts = set()
    for tok in spec.split():
        c, t, v = tok.split(":")
        pts.add((c, float(t), round(float(v), 4)))
    return pts


def dut_lines(dut):
    """Return (include+instance lines, pin list or None)."""
    text = open(dut).read()
    m = re.search(r"^\s*\.subckt\s+(\S+)\s+(.*)$", text, re.I | re.M)
    inc = f'.include "{dut}"'
    if not m:
        return [inc]
    name, pins = m.group(1), m.group(2).split()
    low = [p.lower() for p in pins]
    missing = [p for p in PINS if p not in low]
    if missing:
        sys.exit(f"klt_measure: .SUBCKT {name} has no pin(s) {missing} (pins: {pins})")
    return [inc, "Xdut " + " ".join(low) + " " + name]


def build(dut, art):
    dut = os.path.abspath(dut)
    if not os.path.isfile(dut) or os.path.getsize(dut) == 0:
        sys.exit(f"klt_measure: DUT netlist not found/empty: {dut}")
    os.makedirs(art, exist_ok=True)
    body = open(os.path.join(KLT_DIR, "tb_openloop_ac.body.spice")).read()
    new, n = re.subn(r"^\.include\s+\S*opamp_core\.spice\s*$",
                     "\n".join(dut_lines(dut)), body, flags=re.M)
    if n != 1:
        sys.exit("klt_measure: bench body has no single DUT .include line")
    open(os.path.join(art, "tb_openloop_ac.body.spice"), "w").write(new)

    pts = parse_points(os.environ["SG13G2_PEX_POINTS"]) if os.environ.get("SG13G2_PEX_POINTS") else None
    for fname in ("openloop_ac.request.json", "openloop_op.request.json"):
        req = json.load(open(os.path.join(KLT_DIR, fname)))
        req.pop("_comment", None)
        req["netlist"] = "tb_openloop_ac.body.spice"
        if "KLT_PEX_SIM_BACKEND" in os.environ:
            req["backend"] = os.environ["KLT_PEX_SIM_BACKEND"]
        if fname.startswith("openloop_op"):
            req["measurements"] = [
                m for m in req["measurements"]
                if not DROP_NODES.search(m["expr"])
                and m["name"] not in ("vd1_dc_v", "vd2_dc_v", "vtail_dc_v", "vibias_dc_v")]
            # Iq is graded by check_bounds.py against the ratified bound, not here.
            for m in req["measurements"]:
                if m["name"] == "ivdd_total_a":
                    m.pop("limits", None)
        if pts is not None:
            cs = req["corners"]
            vdds, vinps = cs["supply_v"]["vdd"], cs["supply_v"]["vinp"]
            keep_v = [i for i, v in enumerate(vdds) if any(round(v, 4) == p[2] for p in pts)]
            keep_t = [t for t in cs["temperature_c"] if any(float(t) == p[1] for p in pts)]
            keep_p = [p for p in cs["process"] if any(p["name"] == q[0] for q in pts)]
            if not (keep_v and keep_t and keep_p):
                sys.exit(f"klt_measure: SG13G2_PEX_POINTS={os.environ['SG13G2_PEX_POINTS']!r} matches no grid axis")
            cs["supply_v"] = {"vdd": [vdds[i] for i in keep_v], "vinp": [vinps[i] for i in keep_v]}
            cs["temperature_c"], cs["process"] = keep_t, keep_p
        json.dump(req, open(os.path.join(art, fname), "w"), indent=1)


def _corners(path, what):
    env = json.load(open(path))
    if "error" in env:
        sys.exit(f"klt_measure: {what} klt sim error: {env['error'].get('message')}")
    out = {}
    for c in env.get("corners", []):
        if c.get("status") not in ("pass", "fail"):
            diag = "; ".join(d.get("message", "") for d in c.get("diagnostics", []))[:300]
            sys.exit(f"klt_measure: {what} corner {c.get('corner_id')} status={c.get('status')}: {diag}")
        key = (c["process"], round(c["supply_v"]["vdd"], 4), float(c["temperature_c"]))
        vals = {}
        for m in c["measurements"]:
            v = m.get("value")
            if v is None or not math.isfinite(v):
                sys.exit(f"klt_measure: {what} corner {c['corner_id']}: {m['name']} has no finite value ({m.get('status')})")
            vals[m["name"]] = v
        out[key] = vals
    return env, out


def convert(ac_path, op_path, out=sys.stdout):
    ac_env, ac = _corners(ac_path, "AC")
    op_env, op = _corners(op_path, "OP")
    if set(ac) != set(op) or not ac:
        sys.exit(f"klt_measure: AC and OP envelopes cover different corners ({len(ac)} vs {len(op)})")
    expected = os.environ.get("KLT_MEASURE_EXPECTED_CORNERS")
    expected = int(expected) if expected else (EXPECTED_CORNERS if "SG13G2_PEX_POINTS" not in os.environ else None)
    if expected is not None and len(ac) != expected:
        sys.exit(f"klt_measure: {len(ac)} corners measured, expected {expected}")
    corners = []
    for key in sorted(ac):
        proc, vdd, temp = key
        a, o = ac[key], op[key]
        vcm = vdd / 2
        vout = o["vout_dc_v"]
        if abs(vout - vcm) > 0.15 * vdd or not (0.02 * vdd <= vout <= 0.98 * vdd):
            sys.exit(f"klt_measure: {proc}/{vdd}V/{temp}C: non-regulating DC point (vout={vout:.4g} V, vcm={vcm:.4g} V)")
        pm = 180.0 + math.degrees(a["phase_at_ugf_rad"])
        corners.append({
            "corner_id": f"{proc}/{fmt_vdd(vdd)}V/{int(temp)}C",
            "measurements": [
                {"name": "av0_db", "value": a["av0_db"]},
                {"name": "gbw_hz", "value": a["gbw_hz"]},
                {"name": "pm_deg", "value": pm},
                {"name": "iq_a", "value": o["ivdd_total_a"]},
            ],
        })
    json.dump({"corners": corners}, out, indent=1, allow_nan=False)
    out.write("\n")
    remote = [e.get("environment", {}).get("remote") for e in (ac_env, op_env)]
    for r in remote:
        if r:
            sys.stderr.write(f"klt_measure: batch job {r.get('job_id')} ({r.get('state')})\n")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == "convert":
        convert(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)

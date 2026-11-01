#!/usr/bin/env python3
"""Generate the ICMR `klt sim` requests (issue #325).

The measurement expressions are long and mechanical; they are generated here
so the committed *.request.json files can be diffed against this source
(test_compare.py does that) instead of being hand-maintained.

  make_requests.py            write icmr.request.json and icmr.nominal.request.json
  make_requests.py --check    exit 1 if either committed file differs
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STEP = 250e-6          # sweep step: the harness's fine-pass step
VCM_STOP = 1.32        # top of the supply axis; 0 .. 1.32 V covers every VDD
NS = 5281              # samples: 0 .. 1.32 V at 250 uV
NM = NS - 1            # adjacent-sample segments
I_CC = 100e-9 * 3.2 / 0.13   # gm/ID constant-current Vth criterion at M1/M2 geometry
SLOPE_FRAC = 0.10      # M5 knee rule, as the harness

PROCESSES = ("mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs")
TEMPS = (-40, 27, 125)
SUPPLIES = (1.08, 1.2, 1.32)


def seg(vec: str, lo: int, hi: int) -> str:
    return f"{vec}[{lo},{hi}]"


def build_measurements():
    a = lambda v: seg(v, 0, NM - 1)    # sample j        (segment lower end)
    b = lambda v: seg(v, 1, NM)        # sample j + 1    (segment upper end)
    seg_idx = f"vector({NM})"
    m = []

    def add(name, expr, unit, **limits):
        d = {"name": name, "expr": expr, "unit": unit}
        if limits:
            d["limits"] = limits
        m.append(d)

    # ---- grid indices ---------------------------------------------------
    add("nc_idx", f"floor(v(vdd)[0]/{2 * STEP!r}+0.5)", "index")
    add("nv_idx", f"floor(v(vdd)[0]/{STEP!r}+0.5)", "index")

    # ---- integrity: the replicas and the bias really are what the harness probes
    add("vibias_spread_v", "vecmax(v(ibias))-vecmin(v(ibias))", "V", max=1e-3)
    add("probe_bias_err_v", "abs(v(rbx)[0]-v(ibias)[0])", "V", max=1e-3)

    # ---- M5 saturation knee from the replica Id5(Vds) curve (Vds = v(inp)) --
    g5 = f"(({a('i(Bd5)')}-{b('i(Bd5)')})/{STEP!r})"      # dId5/dVds, Id5 = -i(Bd5)
    add("m5_gmax_sv", f"vecmax({g5})", "S", min=0)
    add("m5_k", f"vecmin({seg_idx}+{NM}*({g5} gt {SLOPE_FRAC}*m5_gmax_sv))", "index")
    add("vdsat5_v", "v(inp)[m5_k+1]", "V", min=0)
    add("vdsat5_frac", "vdsat5_v/v(vdd)[0]", "ratio", min=0, max=0.5)

    # ---- lower bound: v(tail) falls through Vdsat5 as Vcm drops --------------
    s_lo, t_lo = f"({a('v(tail)')}-vdsat5_v)", f"({b('v(tail)')}-vdsat5_v)"
    in_sat = f"({seg_idx}+1 le nv_idx)"
    add("lo_j", f"vecmax(({t_lo} ge 0)*({s_lo} lt 0)*{in_sat}*({seg_idx}+1))-1", "index", min=0)
    add("lo_crossings", f"{NM}*mean(({t_lo} ge 0)*({s_lo} lt 0)*{in_sat})", "count", min=0.99, max=1.01)
    add("lo_frac", "(vdsat5_v-v(tail)[lo_j])/(v(tail)[lo_j+1]-v(tail)[lo_j])", "ratio")
    add("icmr_lo_v", "v(inp)[lo_j]+lo_frac*(v(inp)[lo_j+1]-v(inp)[lo_j])", "V")

    # ---- upper bound: y = v(d1) - Vcm + Vth(CC) falls through 0 as Vcm rises ----
    ya = f"({a('v(d1)')}-{a('v(inp)')}+{a('v(vthp)')})"
    yb = f"({b('v(d1)')}-{b('v(inp)')}+{b('v(vthp)')})"
    from_centre = f"({seg_idx} ge nc_idx)*{in_sat}"
    cross_hi = f"({ya} ge 0)*({yb} lt 0)*{from_centre}"
    add("hi_j", f"vecmin({seg_idx}+{NM}*(1-{cross_hi}))", "index", max=NM - 1)
    add("hi_crossings", f"{NM}*mean({cross_hi})", "count", min=0.99, max=1.01)
    add("hi_ya_v", "v(d1)[hi_j]-v(inp)[hi_j]+v(vthp)[hi_j]", "V")
    add("hi_yb_v", "v(d1)[hi_j+1]-v(inp)[hi_j+1]+v(vthp)[hi_j+1]", "V")
    add("icmr_hi_v", "v(inp)[hi_j]+hi_ya_v/(hi_ya_v-hi_yb_v)*(v(inp)[hi_j+1]-v(inp)[hi_j])", "V")
    add("icmr_span_v", "icmr_hi_v-icmr_lo_v", "V", min=0.05)

    # ---- state at the in-range-adjacent sample of each bound (harness convention) --
    add("vtail_lo_v", "v(tail)[lo_j+1]", "V")
    add("vds1_lo_v", "v(d1)[lo_j+1]-v(tail)[lo_j+1]", "V")
    add("vds2_lo_v", "v(d2)[lo_j+1]-v(tail)[lo_j+1]", "V")
    add("ivdd_lo_a", "-i(vdd)[lo_j+1]", "A")
    add("vtail_hi_v", "v(tail)[hi_j]", "V")
    add("vgs1_hi_v", "v(inp)[hi_j]-v(tail)[hi_j]", "V")
    add("vds1_hi_v", "v(d1)[hi_j]-v(tail)[hi_j]", "V")
    add("vds2_hi_v", "v(d2)[hi_j]-v(tail)[hi_j]", "V")
    add("ivdd_hi_a", "-i(vdd)[hi_j]", "A")
    add("vth_pair_cc_v", "v(vthp)[hi_j]", "V")

    # ---- centre operating point (Vcm = VDD/2), for the record joins ----------
    add("op_vout_v", "v(out)[nc_idx]", "V")
    add("op_vtail_v", "v(tail)[nc_idx]", "V")
    add("op_vd1_v", "v(d1)[nc_idx]", "V")
    add("op_vd2_v", "v(d2)[nc_idx]", "V")
    add("op_vibias_v", "v(ibias)[nc_idx]", "V")
    add("op_ivdd_a", "-i(vdd)[nc_idx]", "A")
    return m


def build_request(points: str):
    if points == "grid":
        procs, temps, supplies, backend = PROCESSES, TEMPS, SUPPLIES, "batch"
    else:
        procs, temps, supplies, backend = ("mos_tt",), (27,), (1.2,), "local"
    cap = {"lib": "libs.tech/ngspice/models/cornerCAP.lib", "section": "cap_typ"}
    comment = [
        "sim/input-cmr as a `klt sim` request (issue #325). Generated by make_requests.py; do not edit by hand.",
        "Grid: cornerMOSlv.lib mos_tt/ss/ff/sf/fs (each with cornerCAP.lib cap_typ) x -40/27/125 C x VDD 1.08/1.20/1.32 V = 45 points." if points == "grid"
        else "One point: mos_tt / 27 C / 1.20 V (single unit, local backend).",
        "Circuit: tb_cmr.body.spice -- the harness DUT circuit plus an M5 replica and a constant-current Vth servo replica for the pair, both driven by the same swept source, so ONE dc sweep (Vcsw 0..1.32 V at 250 uV, 5281 samples) carries every curve the harness gets from separate probe runs. See that file's header.",
        "Bounds are read at the 250 uV sample grid with linear interpolation across the bracketing pair, as the harness fine pass (same 250 uV step). Lower bound: highest Vcm (within VDD) where v(tail) crosses the replica-measured Vdsat5 upward. Upper bound: first Vcm at or above VDD/2 where v(d1)-Vcm+Vth(CC) crosses zero downward, Vth taken at that sample's own body bias.",
        "No ratified limit is applied: the ICMR row is Measured (not yet ratified). The `limits` below are integrity checks only (bound located exactly once, bias replica matches the DUT, knee in the harness's plausible band, span > 50 mV); they keep coverage.nothing_checked false.",
        "vcm sweeps WITH vdd by index (klt supply_v semantics), so the centre bias is VDD/2 at every corner; the source it alters (Vcm) is a reference only -- the swept source is Vcsw.",
        "Solver tolerance: ngspice default (DR-0005). Comparisons use lt/gt/ge since < and > are I/O redirection in ngspice's command line (klayout-tools#2940).",
        "backend: batch for the grid -- a grid does not run on a shared dispatch host. If the batch submit fails, report it; there is no local fallback.",
    ]
    return {
        "_comment": comment,
        "netlist": "tb_cmr.body.spice",
        "netlist_source": "schematic",
        "engine": "ngspice",
        "backend": backend,
        "models": {"pdk": "ihp-sg13g2", "lib": "libs.tech/ngspice/models/cornerMOSlv.lib"},
        "corners": {
            "process": [{"name": p, "sections": [p, cap]} for p in procs],
            "supply_v": {"vdd": list(supplies), "vcm": [v / 2 for v in supplies]},
            "temperature_c": list(temps),
        },
        "analysis": {"kind": "dc", "args": f"Vcsw 0 {VCM_STOP} 250u"},
        "measurements": build_measurements(),
        "options": {
            "timeout_s": 300,
            "keep_artifacts": False,
            "osdi_preload": [f"$PDK_ROOT/ihp-sg13g2/libs.tech/ngspice/osdi/{o}.osdi"
                             for o in ("psp103", "psp103_nqs", "mosvar", "r3_cmc")],
            "stage_model_inputs": True,
            "fail_on_diagnostic": ["singular_matrix", "nonconvergence"],
            "ngspice_init": ["set measureprec=12", "set numdgt=12"],
        },
    }


FILES = {"icmr.request.json": "grid", "icmr.nominal.request.json": "nominal"}


def render(points: str) -> str:
    return json.dumps(build_request(points), indent=2) + "\n"


def main(argv):
    check = "--check" in argv
    bad = 0
    for name, points in FILES.items():
        path = os.path.join(HERE, name)
        text = render(points)
        if check:
            if not os.path.exists(path) or open(path).read() != text:
                print(f"{name}: differs from make_requests.py output", file=sys.stderr)
                bad = 1
        else:
            with open(path, "w") as fh:
                fh.write(text)
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

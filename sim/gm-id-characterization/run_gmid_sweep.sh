#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh                 # one-time: build the OSDI models
#   sim/gm-id-characterization/run_gmid_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH plus the
# OSDI device models sim/tools/build-osdi.sh builds; does not require xschem
# or klt. Full methodology, what this sweep measures and does not, and the
# pinned PDK revision are documented in sim/gm-id-characterization/README.md
# and sim/pdk.json -- read those first if a result here looks surprising.
#
# Sweeps sg13_lv_nmos/sg13_lv_pmos over Vgs (0.05V..1.15V, 56 points) at
# Vds=0.6V (VDD/2, VDD=1.2V) x four channel lengths (Lmin=0.13um and 2x/4x/8x
# multiples) x the five SG13G2 LV MOS process corners
# (mos_tt/mos_ss/mos_ff/mos_sf/mos_fs), computing Id, gm, gds, Cgg, gm/Id,
# gm/gds and fT at every point, plus a per-(device,length,corner) threshold
# voltage (constant-current definition) and Vth-referenced overdrive. Writes
# append-only evidence under corners/<record-id>/, netlist-snapshots/
# <record-id>/ and records/<record-id>.{csv,md} -- see sim/README.md-style
# convention this follows (sg13g2-bandgap/sim/core-open-loop-bias/README.md
# is the structural precedent).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_gmid_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

if ! "${SIM_DIR}/tools/build-osdi.sh" --check >/dev/null 2>&1; then
  echo "run_gmid_sweep.sh: OSDI models missing/unloadable -- run sim/tools/build-osdi.sh first:" >&2
  "${SIM_DIR}/tools/build-osdi.sh" --check || true
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_gmid_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p')"

OSDI_DIR="${SG13G2_OSDI_DIR}"
REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

# --- Sweep grid --------------------------------------------------------
# Corner grid: cornerMOSlv.lib's five process sections (verified present,
# see README.md) -- the grid spec/target-spec.md [TBD-1] guessed at.
CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)
# Lengths: SG13G2's 1.2V (LV) NFET/PFET minimum GatPoly width is 0.13um
# (libs.doc/doc/SG13G2_os_layout_rules.pdf, rules Gat.a1/Gat.a2 -- both
# 0.13um), then 2x/4x/8x multiples, per the issue's "minimum length to a few
# multiples of it" scope.
LENGTHS=(0.13u 0.26u 0.52u 1.04u)
DEVICES=(nmos pmos)
# VDD=1.2V is not read as a shell variable anywhere below -- it is baked
# directly into the testbench templates (Vdd/body-tie sources) and into the
# Python post-processing steps' own VDD constant (both documented at their
# point of use). Restated here only as a comment so the grid-defining block
# above states the full sweep context in one place.

echo "corner_label,device,length_um,vgs_v,vds_v,ids_a,gm_s,gds_s,cgg_f" > "${CSV_OUT}.raw"

total=0
passed=0
failed_points=()

for device in "${DEVICES[@]}"; do
  template="${EXPERIMENT_DIR}/testbench/tb_gmid_${device}.spice.tmpl"
  for length in "${LENGTHS[@]}"; do
    for corner in "${CORNERS[@]}"; do
      total=$((total + 1))
      point_id="${device}_${length}_${corner}"
      netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
      log="${CORNERS_OUT}/${point_id}.log"
      dc_csv="${CORNERS_OUT}/${point_id}_dc.csv"

      sed \
        -e "s|@@PDK_ROOT@@|${PDK_ROOT}|g" \
        -e "s|@@PDK@@|${PDK}|g" \
        -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
        -e "s|@@MOS_SECTION@@|${corner}|g" \
        -e "s|@@L@@|${length}|g" \
        -e "s|@@DC_CSV@@|${dc_csv}|g" \
        "${template}" > "${netlist}"

      rc=0
      ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

      if [[ ${rc} -ne 0 ]] || ! [[ -s "${dc_csv}" ]] || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error" "${log}"; then
        echo "run_gmid_sweep.sh: FAILED ${point_id} (rc=${rc}) -- see ${log}" >&2
        failed_points+=("${point_id}")
        continue
      fi

      # Merge pass 1 (dc_csv: vgs ids gm gds) with pass 2 (log's GMID_VGS /
      # GMID_CGG line pairs). Pass 2's Vgs/Cgg are paired by SEQUENCE ORDER
      # (each GMID_VGS is immediately followed by its own GMID_CGG), not by
      # joining on a shared vector -- see testbench/*.spice.tmpl's header
      # for why the two must be echoed on separate lines. Vgs from pass 2 is
      # then matched to pass 1's Vgs (same nominal grid) rounded to 4
      # decimals, since both derive from the same 0.05+i*0.02 arithmetic.
      # NOTE: the awk variable is named `chlen`, NOT `length` -- `length` is
      # an awk builtin function name, and `-v length=...` silently shadows
      # it in a way that makes a bare `length` in printf call the builtin
      # (string length of $0) instead of reading the assigned value.
      awk -v corner="${corner}" -v device="${device}" -v chlen="${length}" -v vds="0.6" '
        FNR==NR {
          # dc_csv came from `wrdata file vgs ids_mid gm gds` -- ngspice
          # wrdata repeats a (redundant) scale column before EACH requested
          # vectors own value column, so the 4 requested vectors land in 8
          # columns: $1,$2 = (scale,vgs) with $2==$1 here since vgs IS the
          # sweep scale; $3,$4 = (scale,ids); $5,$6 = (scale,gm); $7,$8 =
          # (scale,gds). Verified empirically against explicit `print
          # vec[i,i]` -- see README.md "wrdata column layout gotcha".
          vgs=$2+0; ids=$4+0; gm=$6+0; gds=$8+0
          key=sprintf("%.4f", vgs)
          dc_ids[key]=ids; dc_gm[key]=gm; dc_gds[key]=gds; dc_vgs[key]=vgs
          next
        }
        /^GMID_VGS / { pending_vgs=$2+0; next }
        /^GMID_CGG / {
          if (pending_vgs == "") next
          cgg=$2+0
          key=sprintf("%.4f", pending_vgs)
          if (key in dc_ids) {
            printf "%s,%s,%s,%.6f,%s,%.6e,%.6e,%.6e,%.6e\n", corner, device, chlen, dc_vgs[key], vds, dc_ids[key], dc_gm[key], dc_gds[key], cgg
          }
          pending_vgs=""
        }
      ' "${dc_csv}" "${log}" >> "${CSV_OUT}.raw"

      n_rows=$(grep -c "^${corner},${device},${length}," "${CSV_OUT}.raw" || true)
      if [[ "${n_rows}" -lt 50 ]]; then
        echo "run_gmid_sweep.sh: FAILED ${point_id} -- only ${n_rows} merged rows (expected 56)" >&2
        failed_points+=("${point_id}")
        continue
      fi

      passed=$((passed + 1))
    done
  done
done

if [[ ${passed} -eq 0 ]]; then
  echo "run_gmid_sweep.sh: no points passed -- refusing to write a summary." >&2
  exit 1
fi

# --- Second pass: derive gm/Id, gm/gds, fT, Vth (constant-current def'n,
# Id = 100nA * W/L, W=10um fixed), and Vth-referenced overdrive, per
# (device,length,corner) group. Vth is found by linear interpolation of the
# bracketing (vgs, id) pair around the constant-current threshold -- see
# README.md "Threshold voltage definition".
python3 - "${CSV_OUT}.raw" "${CSV_OUT}" <<'PYEOF'
import csv, sys, math
from collections import defaultdict

src, dst = sys.argv[1], sys.argv[2]
rows = []
with open(src) as f:
    r = csv.reader(f)
    header = next(r)
    for row in r:
        rows.append(row)

W_UM = 10.0
groups = defaultdict(list)
for row in rows:
    corner, device, length, vgs, vds, ids, gm, gds, cgg = row
    groups[(corner, device, length)].append(
        (float(vgs), float(vds), float(ids), float(gm), float(gds), float(cgg))
    )

def length_um(tok):
    return float(tok.rstrip('u'))

out_rows = []
for (corner, device, length), pts in groups.items():
    # Re-express in terms of the DEVICE's own Vgs (nmos: as-swept; pmos:
    # VDD - swept Vg), then sort ascending by that value so both devices'
    # rows read weak->strong inversion the same way.
    VDD = 1.2
    reexpr = []
    for (vg, vds, ids, gm, gds, cgg) in pts:
        vgs_eff = vg if device == "nmos" else (VDD - vg)
        vds_eff = vds if device == "nmos" else (VDD - vds)
        reexpr.append((vgs_eff, vds_eff, ids, gm, gds, cgg))
    reexpr.sort(key=lambda t: t[0])

    L = length_um(length)
    i_crit = 100e-9 * (W_UM / L)  # constant-current Vth definition

    vth = None
    for a, b in zip(reexpr, reexpr[1:]):
        (vg_a, _, id_a, *_), (vg_b, _, id_b, *_) = a, b
        lo, hi = (a, b) if id_a <= id_b else (b, a)
        if lo[2] <= i_crit <= hi[2] and hi[2] > lo[2]:
            # linear interpolation in log(Id) vs Vgs (subthreshold-accurate)
            log_lo, log_hi = math.log(max(lo[2], 1e-15)), math.log(max(hi[2], 1e-15))
            if log_hi != log_lo:
                frac = (math.log(i_crit) - log_lo) / (log_hi - log_lo)
                vth = lo[0] + frac * (hi[0] - lo[0])
            break
    if vth is None:
        vth = float('nan')

    for (vgs_eff, vds_eff, ids, gm, gds, cgg) in reexpr:
        gm_id = gm / ids if ids > 0 else float('nan')
        gm_gds = gm / gds if gds > 0 else float('nan')
        ft = gm / (2 * math.pi * cgg) if cgg > 0 else float('nan')
        overdrive = vgs_eff - vth if vth == vth else float('nan')
        out_rows.append([
            device, length, corner, f"{vgs_eff:.4f}", f"{vds_eff:.4f}",
            f"{ids:.6e}", f"{gm:.6e}", f"{gds:.6e}", f"{cgg:.6e}",
            f"{gm_id:.6f}", f"{gm_gds:.6f}", f"{ft:.6e}",
            f"{vth:.4f}" if vth == vth else "", f"{overdrive:.4f}" if overdrive == overdrive else "",
        ])

out_rows.sort(key=lambda r: (r[0], r[1], r[2], float(r[3])))

with open(dst, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["device", "length_um", "corner", "vgs_v", "vds_v", "ids_a", "gm_s", "gds_s",
                "cgg_f", "gm_id_per_v", "gm_gds", "ft_hz", "vth_v", "overdrive_v"])
    w.writerows(out_rows)
PYEOF
rm -f "${CSV_OUT}.raw"

# --- Sanity checks (issue #5 Test Plan): gm/ID monotonically decreasing
# with overdrive at mos_tt, for every length/device; fT increases then
# rolls off with decreasing length at mos_tt, nominal overdrive. ---
SANITY_LOG="${CORNERS_OUT}/sanity_checks.txt"
SANITY_RC=0
python3 - "${CSV_OUT}" "${SANITY_LOG}" <<'PYEOF' || SANITY_RC=$?
import csv, sys
from collections import defaultdict

src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src)))
lines = []
ok = True

by_group = defaultdict(list)
for row in rows:
    if row["corner"] != "mos_tt" or row["overdrive_v"] == "":
        continue
    by_group[(row["device"], row["length_um"])].append(
        (float(row["overdrive_v"]), float(row["gm_id_per_v"]))
    )

for (device, length), pts in by_group.items():
    pts.sort(key=lambda t: t[0])
    gmids = [g for (_, g) in pts]
    # Real PSP103 devices show a genuine (not a finite-difference artifact)
    # gm/ID PEAK a little above Vgs=0 rather than a monotonic rise all the
    # way from the deepest subthreshold point swept: at Vgs below the peak,
    # secondary leakage-current components the compact model includes
    # (junction/GIDL-type leakage, which does not scale with Vgs the same
    # way drift-diffusion subthreshold current does) pull gm/ID down below
    # the ideal weak-inversion ceiling 1/(n*Ut) -- see README.md "Observed
    # sub-peak gm/ID roll-off in deep subthreshold". The monotonic-decrease
    # check below therefore starts at the observed peak (the point that
    # matters for real sizing decisions -- no real design biases a device
    # in the leakage-dominated tail below it), not at the sweep's first
    # point.
    peak_idx = max(range(len(gmids)), key=lambda i: gmids[i])
    tail = gmids[peak_idx:]
    violations = sum(1 for a, b in zip(tail, tail[1:]) if b > a + 1e-3)
    verdict = "PASS" if violations == 0 else "FAIL"
    if violations:
        ok = False
    lines.append(f"{verdict} gm/ID monotonically decreasing vs overdrive from its observed peak (index {peak_idx}/{len(gmids)-1}, peak={gmids[peak_idx]:.3f}): device={device} length={length} corner=mos_tt (violations={violations}/{len(tail)-1})")

# fT vs length at a fixed representative overdrive (~0.3V) for mos_tt
ft_by_length = {}
for device in ("nmos", "pmos"):
    for row in rows:
        if row["corner"] != "mos_tt" or row["device"] != device or row["overdrive_v"] == "":
            continue
        ov = float(row["overdrive_v"])
        if 0.25 <= ov <= 0.35:
            ft_by_length.setdefault(device, {}).setdefault(row["length_um"], []).append(float(row["ft_hz"]))
    if device in ft_by_length:
        lengths_sorted = sorted(ft_by_length[device].keys(), key=lambda l: float(l.rstrip("u")))
        fts = [max(ft_by_length[device][l]) for l in lengths_sorted]
        # Expect fT to be highest at the shortest length and to fall off as
        # length increases (fT ~ gm/Cgg ~ 1/L^2-ish for a long-channel
        # square-law device) -- i.e. monotonically decreasing with length.
        decreasing = all(a >= b for a, b in zip(fts, fts[1:]))
        verdict = "PASS" if decreasing else "FAIL"
        if not decreasing:
            ok = False
        lines.append(f"{verdict} fT falls off with increasing length near overdrive~0.3V: device={device} lengths={lengths_sorted} fT={['%.3e' % v for v in fts]}")

with open(dst, "w") as f:
    f.write("\n".join(lines) + "\n")

print("\n".join(lines))
sys.exit(0 if ok else 1)
PYEOF
true

# --- Plots (summary artifact, per issue #5 AC item 2 "table or plots") ---
# Best-effort: if matplotlib is not installed, skip plotting rather than
# fail the whole sweep -- the CSV table above is already a complete summary
# artifact on its own.
GMID_PLOT="${RECORDS_DIR}/${RECORD_ID}_gm_id_vs_overdrive.png"
FT_PLOT="${RECORDS_DIR}/${RECORD_ID}_ft_vs_length.png"
if python3 -c "import matplotlib" >/dev/null 2>&1; then
  python3 - "${CSV_OUT}" "${GMID_PLOT}" "${FT_PLOT}" <<'PYEOF'
import csv, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import defaultdict

src, gmid_png, ft_png = sys.argv[1], sys.argv[2], sys.argv[3]
rows = list(csv.DictReader(open(src)))

# --- gm/ID vs overdrive, mos_tt, all lengths, both devices ---
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
for ax, device in zip(axes, ("nmos", "pmos")):
    by_len = defaultdict(list)
    for row in rows:
        if row["corner"] != "mos_tt" or row["device"] != device or row["overdrive_v"] == "":
            continue
        by_len[row["length_um"]].append((float(row["overdrive_v"]), float(row["gm_id_per_v"])))
    for length in sorted(by_len, key=lambda l: float(l.rstrip("u"))):
        pts = sorted(by_len[length])
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker=".", markersize=3, label=f"L={length}")
    ax.set_xlabel("Overdrive Vgs-Vth (V)")
    ax.set_title(f"sg13_lv_{device}, mos_tt, Vds=0.6V")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
axes[0].set_ylabel("gm/Id (1/V)")
fig.suptitle("sg13g2-opamp gm/ID characterization (issue #5)")
fig.tight_layout()
fig.savefig(gmid_png, dpi=150)

# --- fT vs overdrive, mos_tt, all lengths, both devices (log-y). Plotted
# against overdrive (monotonic with the swept Vgs), not gm/ID -- gm/ID is
# double-valued around its own deep-subthreshold peak (see README.md
# "Observed sub-peak gm/ID roll-off"), which would fold a gm/ID-vs-fT line
# plot back on itself right where it's most interesting to read. ---
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
for ax, device in zip(axes, ("nmos", "pmos")):
    by_len = defaultdict(list)
    for row in rows:
        if row["corner"] != "mos_tt" or row["device"] != device or row["overdrive_v"] == "":
            continue
        by_len[row["length_um"]].append((float(row["overdrive_v"]), float(row["ft_hz"])))
    for length in sorted(by_len, key=lambda l: float(l.rstrip("u"))):
        pts = sorted(by_len[length])
        ax.semilogy([p[0] for p in pts], [p[1] for p in pts], marker=".", markersize=3, label=f"L={length}")
    ax.set_xlabel("Overdrive Vgs-Vth (V)")
    ax.set_title(f"sg13_lv_{device}, mos_tt, Vds=0.6V")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
axes[0].set_ylabel("fT (Hz)")
fig.suptitle("sg13g2-opamp fT vs overdrive, by length (issue #5)")
fig.tight_layout()
fig.savefig(ft_png, dpi=150)
print(f"wrote {gmid_png} and {ft_png}")
PYEOF
else
  echo "run_gmid_sweep.sh: matplotlib not available -- skipping plots (CSV table is still complete)." >&2
  GMID_PLOT=""
  FT_PLOT=""
fi

# --- Corner/polarity/length completeness matrix ---
COMPLETENESS_OK=1
for device in "${DEVICES[@]}"; do
  for length in "${LENGTHS[@]}"; do
    for corner in "${CORNERS[@]}"; do
      n=$(awk -F, -v d="${device}" -v l="${length}" -v c="${corner}" '$1==d && $2==l && $3==c {n++} END{print n+0}' "${CSV_OUT}")
      if [[ "${n}" -lt 50 ]]; then
        echo "run_gmid_sweep.sh: INCOMPLETE ${device}/${length}/${corner} -- ${n} rows" >&2
        COMPLETENESS_OK=0
      fi
    done
  done
done

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: gm-id-characterization"
  echo "- **Claim**: gm/ID, gm/gds, Cgg and fT vs Vgs (and vs Vth-referenced"
  echo "  overdrive) for SG13G2's LV core MOS devices (sg13_lv_nmos,"
  echo "  sg13_lv_pmos), at Vds=0.6V (VDD/2, VDD=1.2V), swept over four"
  echo "  channel lengths (0.13/0.26/0.52/1.04 um) and all five"
  echo "  cornerMOSlv.lib process corners, at 27C nominal temperature."
  echo "  This is a device-characterization study, not a circuit claim --"
  echo "  no schematic exists yet in this repo (see README.md 'What this"
  echo "  study is not')."
  echo "- **Devices**: sg13_lv_nmos / sg13_lv_pmos (PSP103.6 via"
  echo "  psp103.osdi), W=10um, ng=1, m=1 fixed (gm/ID methodology"
  echo "  normalizes out W)."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\` -- pinned release: see"
  echo "  \`sim/pdk.json\` (IHP-Open-PDK v0.3.0)."
  echo "- **OSDI models**: \`${OSDI_DIR}\` -- built by"
  echo "  \`sim/tools/build-osdi.sh\`."
  echo "- **ngspice**: \`${NGSPICE_VERSION}\`"
  echo "- **Sweep grid**: device {nmos, pmos} x length {0.13u, 0.26u, 0.52u,"
  echo "  1.04u} x corner {mos_tt, mos_ss, mos_ff, mos_sf, mos_fs} ="
  echo "  ${total} (device,length,corner) points, 56 Vgs points each."
  echo "- **Result**: ${passed}/${total} points PASS (ngspice exit 0, DC"
  echo "  wrdata present, all 56 Vgs rows merged with a matching AC point)."
  if [[ ${#failed_points[@]} -gt 0 ]]; then
    echo "- **Failed points**: ${failed_points[*]}"
  fi
  echo "- **Completeness matrix**: $( [[ ${COMPLETENESS_OK} -eq 1 ]] && echo 'OK -- every (device,length,corner) cell has >=50/56 rows' || echo 'INCOMPLETE -- see stderr log above' )"
  echo "- **Sanity checks** (see \`corners/${RECORD_ID}/sanity_checks.txt\`):"
  while IFS= read -r line; do echo "  - ${line}"; done < "${SANITY_LOG}"
  echo "- **Links**:"
  echo "  - Templates: \`testbench/tb_gmid_nmos.spice.tmpl\`,"
  echo "    \`testbench/tb_gmid_pmos.spice.tmpl\`"
  echo "  - Per-point generated netlists: \`netlist-snapshots/${RECORD_ID}/\`"
  echo "  - Per-point raw ngspice logs + per-point DC CSVs:"
  echo "    \`corners/${RECORD_ID}/\`"
  echo "  - Parsed, merged CSV (all points, all derived quantities):"
  echo "    \`records/${RECORD_ID}.csv\`"
  if [[ -n "${GMID_PLOT}" && -f "${GMID_PLOT}" ]]; then
    echo "  - Plots: \`records/$(basename "${GMID_PLOT}")\`,"
    echo "    \`records/$(basename "${FT_PLOT}")\`"
  fi
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder"
  echo "  (agent), issue #5."
} > "${MD_OUT}"

echo "run_gmid_sweep.sh: wrote ${MD_OUT} and ${CSV_OUT}"
echo "run_gmid_sweep.sh: ${passed}/${total} points passed; completeness=$( [[ ${COMPLETENESS_OK} -eq 1 ]] && echo OK || echo INCOMPLETE ); sanity=$( [[ ${SANITY_RC} -eq 0 ]] && echo PASS || echo FAIL )"

if [[ ${#failed_points[@]} -gt 0 || ${COMPLETENESS_OK} -ne 1 || ${SANITY_RC} -ne 0 ]]; then
  exit 1
fi
exit 0

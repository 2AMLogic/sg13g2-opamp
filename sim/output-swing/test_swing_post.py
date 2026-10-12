#!/usr/bin/env python3
"""Negative controls and golden checks for swing_post.py (stdlib unittest).

  python3 -m unittest discover -s sim/output-swing -p 'test_*.py' -v

Covers the strict wrdata parser (column count, non-finite and malformed
samples, repeated/reversed scales, mismatched wrdata scale columns), the
coarse and fine estimators (every named failure, the sampled 0.5x-peak
region, the sanity flag), the rendered-netlist reader, the CLI the runner
calls, and the committed record as a golden result. Needs no ngspice, no
PDK, no network.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import swing_post  # noqa: E402

REPO = HERE.parent.parent
RECORD = "20260921-151759-707b34c"

VCM = 0.6
VDD = 1.2
VOS = -0.1 + 224 * 5e-4  # an exact coarse-grid sample: 0.012


def synth_coarse(vos=VOS, vcm=VCM, gain=150.0, reach=0.5, start=-0.1, stop=0.1, step=5e-4, flat=None):
    """A saturating S-curve through (vos, vcm) on the coarse grid; `flat`
    replaces the output column entirely (a constant when given a float)."""
    lines = []
    n = swing_post.sweep_count(start, stop, step)
    for k in range(n):
        vid = start + k * step
        vout = vcm + reach * math.tanh(gain * (vid - vos)) if flat is None else flat
        lines.append(f"{vid!r} {vout!r}")
    return "\n".join(lines) + "\n"


def synth_fine(vos=VOS, vcm=VCM, vdd=VDD, half=25e-3, step=1e-5, w=4e-3, reach=0.35, ivdd=-1e-4):
    """A clean fine S-curve centred on vos: peak gain reach/w >> 10, the
    0.5x-peak region well inside the window, monotonic, single crossing."""
    lines = []
    n = swing_post.sweep_count(vos - half, vos + half, step)
    for k in range(n):
        vid = vos - half + k * step
        vout = vcm + reach * math.tanh((vid - vos) / w)
        lines.append(f"{vid!r} {vout!r} {vid!r} {ivdd!r}")
    return "\n".join(lines) + "\n"


def netlist(corner="mos_tt", temp="-40", vdd="1.2", vcm=None, label="fine",
            start="-0.012", stop="0.038", step="10e-6", vectors="v(out) i(vdd)",
            target="x_fine.csv"):
    vcm = vcm if vcm is not None else {  # VDD/2 as the runner prints it
        "1.08": "0.54", "1.2": "0.6", "1.20": "0.6", "1.32": "0.66"}[vdd]
    return (
        f"* Point: corner={corner} temp_c={temp} vdd_v={vdd} pass={label}\n"
        f"* Sweep: Vid from {start} V to {stop} V, step {step} V\n"
        f'.lib "/pdk/cornerCAP.lib" cap_typ\n'
        f'.lib "/pdk/cornerMOSlv.lib" {corner}\n'
        f".options temp={temp} tnom=27\n"
        f"Vdd vdd 0 dc {vdd}\n"
        f"Vss vss 0 dc 0\n"
        f"Vcm cm 0 dc {vcm}\n"
        f"Vid id 0 dc 0\n"
        f"Binp inp 0 v = v(cm) + v(id)/2\n"
        f"Binn inn 0 v = v(cm) - v(id)/2\n"
        f".control\n"
        f"dc Vid {start} {stop} {step}\n"
        f"wrdata {target} {vectors}\n"
        f".endc\n"
        f".end\n"
    )


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name, text) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path


class ParseWrdata(TempCase):
    def test_coarse_and_fine_happy_paths(self):
        scale, cols = swing_post.parse_wrdata(" 0 1 \n 0.5 2 \n", ("v(out)",))
        self.assertEqual((scale, cols), ([0.0, 0.5], [[1.0, 2.0]]))
        scale, cols = swing_post.parse_wrdata(
            " 0 1 0 -2 \n 0.5 2 0.5 -3 \n", ("v(out)", "i(vdd)"))
        self.assertEqual(cols, [[1.0, 2.0], [-2.0, -3.0]])

    def test_blank_lines_are_skipped_and_two_samples_is_the_floor(self):
        swing_post.parse_wrdata("\n 0 1 \n\n 0.5 2 \n \n", ("v(out)",))
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.parse_wrdata(" 0 1 \n", ("v(out)",))
        self.assertIn("need at least 2", str(cm.exception))

    def test_column_count_is_exact(self):
        for line in (" 0 1 2 \n", " 0 \n", "no columns here\n"):
            with self.subTest(line=line):
                with self.assertRaises(swing_post.SwingError) as cm:
                    swing_post.parse_wrdata(" 0 1 \n" + line, ("v(out)",))
                self.assertIn("expected 2 columns", str(cm.exception))
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.parse_wrdata(" 0 1 0 \n 0.5 2 0.5 \n", ("v(out)", "i(vdd)"))
        self.assertIn("expected 4 columns", str(cm.exception))

    def test_non_finite_and_malformed_tokens_are_named_with_their_line(self):
        for line in (" 2 nan \n", " 2 inf \n", " nan 1 \n", " 2 -Infinity \n", " 2 abc \n"):
            with self.subTest(line=line):
                with self.assertRaises(swing_post.SwingError) as cm:
                    swing_post.parse_wrdata(" 0 1 \n" + line, ("v(out)",))
                self.assertIn(":2:", str(cm.exception))
                self.assertIn("non-", str(cm.exception))

    def test_repeated_scale_is_refused(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.parse_wrdata(" 0 1 \n 0 2 \n", ("v(out)",))
        self.assertIn("does not increase", str(cm.exception))

    def test_reversed_scale_is_refused(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.parse_wrdata(" 0 1 \n -0.5 2 \n", ("v(out)",))
        self.assertIn("does not increase", str(cm.exception))

    def test_mismatched_wrdata_scales_are_refused(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.parse_wrdata(" 0 1 0 -2 \n 0.5 2 9.9 -3 \n", ("v(out)", "i(vdd)"))
        self.assertIn("mismatched wrdata scales", str(cm.exception))
        self.assertIn("column 2", str(cm.exception))


class SweepCount(unittest.TestCase):
    def test_the_benchs_windows(self):
        self.assertEqual(swing_post.sweep_count(-0.1, 0.1, 5e-4), 401)
        self.assertEqual(swing_post.sweep_count(-0.025, 0.025, 1e-5), 5001)


class CoarseMeasure(TempCase):
    def test_unique_crossing_clip_levels_and_plateau_flag(self):
        vid, (vout,) = swing_post.parse_wrdata(synth_coarse(), ("v(out)",))
        c = swing_post.coarse_measure(vid, vout, VCM)
        self.assertEqual(c["n_crossings"], 1)
        self.assertAlmostEqual(c["vos"], VOS, places=12)
        self.assertAlmostEqual(c["clip_high"], VCM + 0.5, delta=1e-9)
        self.assertAlmostEqual(c["clip_low"], VCM - 0.5, delta=1e-9)
        self.assertEqual(c["plateau_ok"], 1)

    def test_crossing_interpolates_inside_its_segment(self):
        # put the crossing strictly between two samples
        vos = -0.1 + 224 * 5e-4 + 1.23e-4
        vid, (vout,) = swing_post.parse_wrdata(synth_coarse(vos=vos), ("v(out)",))
        c = swing_post.coarse_measure(vid, vout, VCM)
        self.assertGreater(c["vos"], -0.1 + 224 * 5e-4)
        self.assertLess(c["vos"], -0.1 + 225 * 5e-4)

    def test_zero_and_multiple_crossings(self):
        vid, (vout,) = swing_post.parse_wrdata(synth_coarse(flat=0.2), ("v(out)",))
        c = swing_post.coarse_measure(vid, vout, VCM)
        self.assertEqual(c["n_crossings"], 0)
        self.assertTrue(math.isnan(c["vos"]))
        vid, (vout,) = swing_post.parse_wrdata(
            "\n".join(f"{-0.1 + k * 5e-4!r} {0.6 + 0.01 * math.sin(2 * math.pi * (-0.1 + k * 5e-4) / 0.004)!r}"
                      for k in range(401)) + "\n", ("v(out)",))
        c = swing_post.coarse_measure(vid, vout, VCM)
        self.assertGreater(c["n_crossings"], 2)
        self.assertTrue(math.isnan(c["vos"]))

    def test_unclipped_window_ends_fail_the_plateau_rule(self):
        # gain so low the curve is still amplifying at both window ends
        vid, (vout,) = swing_post.parse_wrdata(synth_coarse(gain=5.0), ("v(out)",))
        c = swing_post.coarse_measure(vid, vout, VCM)
        self.assertEqual(c["n_crossings"], 1)
        self.assertEqual(c["plateau_ok"], 0)


class FineMeasure(TempCase):
    def measure(self, text):
        vid, (vout, ivdd) = swing_post.parse_wrdata(text, ("v(out)", "i(vdd)"))
        clip_high, clip_low = max(vout) + 0.2, min(vout) - 0.2
        return swing_post.fine_measure(vid, vout, ivdd, VDD, VCM, clip_high, clip_low, 1,
                                       0.0, float("nan"), float("nan"), float("nan"),
                                       float(swing_post.CONFIG["criterion_frac"])), vid, vout, ivdd

    def test_clean_curve_passes_every_sanity_rule(self):
        m, vid, vout, ivdd = self.measure(synth_fine())
        self.assertIsNone(m["fail"])
        self.assertEqual(m["op_pass"], 1)
        # region: sech^2((vid-vos)/w) >= 0.5 out to |vid-vos| <= w*0.88137..
        edge = 4e-3 * math.acosh(math.sqrt(2.0))
        lo = int(((-edge) - (-25e-3)) / 1e-5)
        hi = int(((edge) - (-25e-3)) / 1e-5)
        self.assertAlmostEqual(m["vout_max_track"], max(vout[lo:hi + 2]), places=15)
        self.assertAlmostEqual(m["vout_min_track"], min(vout[lo:hi + 2]), places=15)
        self.assertAlmostEqual(m["headroom_hi"], VDD - m["vout_max_track"], places=15)
        self.assertAlmostEqual(m["headroom_lo"], m["vout_min_track"], places=15)
        self.assertAlmostEqual(m["span"], m["vout_max_track"] - m["vout_min_track"], places=15)
        self.assertAlmostEqual(m["vos_crossing"], VOS, places=12)
        self.assertAlmostEqual(m["g_pk"], 0.35 / 4e-3, delta=1.0)
        self.assertAlmostEqual(m["ivdd_center"], 1e-4, places=15)

    def test_mid_swing_sample_is_the_one_nearest_the_coarse_crossing(self):
        # the runner feeds the coarse crossing (as serialized) back in; the
        # reported mid-swing current is the swept sample nearest to it
        text = "\n".join(
            f"{(-25e-3 + k * 1e-5)!r} {0.6 + 0.35 * math.tanh((-25e-3 + k * 1e-5) / 4e-3)!r} "
            f"{(-25e-3 + k * 1e-5)!r} {(-2e-4 - k * 1e-9)!r}" for k in range(5001)) + "\n"
        vid, (vout, ivdd) = swing_post.parse_wrdata(text, ("v(out)", "i(vdd)"))
        target = vid[2500] + 2e-6  # strictly nearer sample 2500 than 2501
        m = swing_post.fine_measure(vid, vout, ivdd, VDD, VCM, 1.5, -0.3, 1, target,
                                    float("nan"), float("nan"), float("nan"), 0.5)
        self.assertEqual(m["ivdd_center"], -(-2e-4 - 2500 * 1e-9))

    def test_named_failures(self):
        cases = {
            "fine_sweep_too_short": swing_post.fine_measure([0, 1], [0.6, 0.7], [0, 0], VDD, VCM, 1.5, -0.3, 1, 0.0, float("nan"), float("nan"), float("nan"), 0.5),
        }
        m = cases["fine_sweep_too_short"]
        self.assertEqual((m["fail"], m["op_pass"]), ("fine_sweep_too_short", 0))
        self.assertTrue(math.isnan(m["vout_max_track"]))

    def test_no_crossing_and_edge_crossing(self):
        vid, (vout, ivdd) = swing_post.parse_wrdata(synth_fine(), ("v(out)", "i(vdd)"))
        flat = [0.2] * len(vout)
        m = swing_post.fine_measure(vid, flat, ivdd, VDD, VCM, 1.5, -0.3, 1, 0.0, float("nan"), float("nan"), float("nan"), 0.5)
        self.assertEqual(m["fail"], "fine_sweep_no_crossing")
        # a curve whose first Vout = Vcm crossing lands on the window's second
        # sample (idx == 1): the fine read is not trustworthy
        vids = [k * 1e-5 for k in range(10)]
        vouts = [0.5999, 0.6000001, 0.61, 0.62, 0.63, 0.64, 0.65, 0.66, 0.67, 0.68]
        m = swing_post.fine_measure(vids, vouts, [-1e-4] * 10, VDD, VCM, 1.5, -0.3, 1, 0.0,
                                    float("nan"), float("nan"), float("nan"), 0.5)
        self.assertEqual(m["fail"], "fine_sweep_crossing_at_edge")

    def test_non_monotonic_curve_is_refused(self):
        vid, (vout, ivdd) = swing_post.parse_wrdata(synth_fine(), ("v(out)", "i(vdd)"))
        vout[100] = vout[99] - 1e-3
        m = swing_post.fine_measure(vid, vout, ivdd, VDD, VCM, 1.5, -0.3, 1, 0.0, float("nan"), float("nan"), float("nan"), 0.5)
        self.assertEqual(m["fail"], "fine_sweep_non_monotonic")

    def test_weak_peak_gain_is_refused(self):
        vid, (vout, ivdd) = swing_post.parse_wrdata(synth_fine(w=0.2, reach=1.0), ("v(out)", "i(vdd)"))
        m = swing_post.fine_measure(vid, vout, ivdd, VDD, VCM, 1.5, -0.3, 1, 0.0, float("nan"), float("nan"), float("nan"), 0.5)
        self.assertEqual(m["fail"], "peak_gain_implausible")

    def test_window_truncating_the_region_is_refused(self):
        # w wide enough that the 0.5x-peak region still qualifies at both
        # window edges: the bounds would be a window artifact
        vid, (vout, ivdd) = swing_post.parse_wrdata(synth_fine(w=3e-2, reach=0.35), ("v(out)", "i(vdd)"))
        m = swing_post.fine_measure(vid, vout, ivdd, VDD, VCM, 1.5, -0.3, 1, 0.0, float("nan"), float("nan"), float("nan"), 0.5)
        self.assertEqual(m["fail"], "linear_region_touches_window_edge")

    def test_fail_rows_echo_the_runner_inputs(self):
        vid, (vout, ivdd) = swing_post.parse_wrdata(synth_fine(), ("v(out)", "i(vdd)"))
        flat = [0.2] * len(vout)
        m = swing_post.fine_measure(vid, flat, ivdd, VDD, VCM, 1.1, 0.05, 1, 0.012, 43.0, 1.1e-4, 0.0121, 0.5)
        self.assertEqual(m["vos_crossing"], 0.012)  # the echoed coarse crossing
        self.assertTrue(math.isnan(m["g_pk"]))
        fields = swing_post.format_fields(m, 1.1, 0.05, 43.0, 1.1e-4, 0.0121)
        self.assertEqual(fields, ["0", "nan", "nan", "nan", "nan", "nan",
                                  "1.1", "0.05", "0.012", "0.0121", "nan", "nan",
                                  "43", "nan", "nan", "0.00011", "nan"])


class Serialize(unittest.TestCase):
    def test_nine_significant_digits_and_nan(self):
        self.assertEqual(swing_post.serialize(float("nan")), "nan")
        self.assertEqual(swing_post.serialize(0.1 + 0.2), "0.3")
        self.assertEqual(swing_post.serialize(1.00403206), "1.00403206")
        self.assertEqual(swing_post.serialize(-1.82837907e-05), "-1.82837907e-05")


class RenderedConfig(unittest.TestCase):
    def test_fine_and_coarse_netlists(self):
        rc = swing_post.rendered_config(netlist())
        self.assertEqual(rc["corner"], "mos_tt")
        self.assertEqual(rc["temp_c"], -40.0)
        self.assertEqual(rc["vdd_v"], 1.2)
        self.assertEqual(rc["vcm_v"], 0.6)
        self.assertEqual(rc["pass"], "fine")
        self.assertEqual((rc["start"], rc["stop"], rc["step"]), (-0.012, 0.038, 1e-5))
        self.assertEqual(rc["vectors"], ("v(out)", "i(vdd)"))
        self.assertEqual(Path(rc["wrdata"]).name, "x_fine.csv")
        rc = swing_post.rendered_config(netlist(label="coarse", start="-0.1", stop="0.1",
                                                step="500e-6", vectors="v(out)", target="x_coarse.csv"))
        self.assertEqual((rc["start"], rc["stop"], rc["step"]), (-0.1, 0.1, 5e-4))

    def test_each_missing_or_duplicated_line_is_named(self):
        whole = netlist()
        def is_mos_lib(line):
            return line.startswith('.lib "') and "cornerMOSlv.lib" in line
        cases = {
            "Point comment": lambda l: l.startswith("* Point:"),
            "Vdd line": lambda l: l.startswith("Vdd vdd 0 dc"),
            "Vcm line": lambda l: l.startswith("Vcm cm 0 dc"),
            "Binp drive": lambda l: l.startswith("Binp inp 0"),
            "Binn drive": lambda l: l.startswith("Binn inn 0"),
            "MOS lib": is_mos_lib,
            "dc line": lambda l: l.startswith("dc Vid "),
            "Sweep comment": lambda l: l.startswith("* Sweep: Vid from"),
            "wrdata line": lambda l: l.startswith("wrdata "),
        }
        for what, drop in cases.items():
            with self.subTest(missing=what):
                text = "\n".join(l for l in whole.splitlines() if not drop(l)) + "\n"
                with self.assertRaises(swing_post.SwingError) as cm:
                    swing_post.rendered_config(text)
                self.assertIn("0", str(cm.exception))
            with self.subTest(duplicated=what):
                text = whole + next(l for l in whole.splitlines() if drop(l)) + "\n"
                with self.assertRaises(swing_post.SwingError) as cm:
                    swing_post.rendered_config(text)
                self.assertIn("2", str(cm.exception))

    def test_point_comment_and_vdd_line_must_agree(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.rendered_config(netlist().replace("Vdd vdd 0 dc 1.2", "Vdd vdd 0 dc 1.08"))
        self.assertIn("disagrees with the Vdd line", str(cm.exception))

    def test_common_mode_must_be_vdd_over_two(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.rendered_config(netlist(vcm="0.7"))
        self.assertIn("is not VDD/2", str(cm.exception))

    def test_sweep_comment_must_agree_with_the_dc_line(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.rendered_config(netlist().replace("* Sweep: Vid from -0.012 V to 0.038 V, step 10e-6 V",
                                                         "* Sweep: Vid from -0.012 V to 0.038 V, step 5e-6 V"))
        self.assertIn("disagrees with the dc line", str(cm.exception))

    def test_decreasing_sweep_is_refused(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.rendered_config(netlist(start="0.038", stop="-0.012"))
        self.assertIn("increasing sweep", str(cm.exception))

    def test_wrdata_without_vectors_is_refused(self):
        with self.assertRaises(swing_post.SwingError) as cm:
            swing_post.rendered_config(netlist().replace(" v(out) i(vdd)", ""))
        self.assertIn("records no vectors", str(cm.exception))


class GoldenRecord(TempCase):
    """The committed record as a golden result: the module reproduces every
    committed cell of three representative points from the pinned curves."""

    POINTS = ("mos_tt_27C_1.08V", "mos_tt_27C_1.20V", "mos_fs_125C_1.32V")
    COLUMNS = ("op_pass", "vout_max_track_v", "vout_min_track_v", "headroom_hi_v",
               "headroom_lo_v", "swing_span_v", "vout_clip_high_v", "vout_clip_low_v",
               "vos_crossing_v", "peak_inc_gain_v_v", "ivdd_center_a")

    def committed_row(self, pid):
        with open(REPO / f"sim/output-swing/records/{RECORD}.csv", encoding="utf-8") as f:
            return next(r for r in csv.DictReader(f) if r["point_id"] == pid)

    def test_committed_cells_reproduce_from_the_curves(self):
        for pid in self.POINTS:
            with self.subTest(point=pid):
                row = self.committed_row(pid)
                cvid, (cvout,) = swing_post.parse_wrdata(
                    (REPO / f"sim/output-swing/corners/{RECORD}/{pid}_coarse.csv").read_text(encoding="utf-8"),
                    ("v(out)",))
                fvid, (fvout, fivdd) = swing_post.parse_wrdata(
                    (REPO / f"sim/output-swing/corners/{RECORD}/{pid}_fine.csv").read_text(encoding="utf-8"),
                    ("v(out)", "i(vdd)"))
                rc = swing_post.rendered_config(
                    (REPO / f"sim/output-swing/netlist-snapshots/{RECORD}/{pid}_fine.spice").read_text(encoding="utf-8"))
                coarse = swing_post.coarse_measure(cvid, cvout, rc["vcm_v"])
                fine = swing_post.fine_measure(
                    fvid, fvout, fivdd, rc["vdd_v"], rc["vcm_v"],
                    float(swing_post.serialize(coarse["clip_high"])),
                    float(swing_post.serialize(coarse["clip_low"])),
                    coarse["plateau_ok"], float(swing_post.serialize(coarse["vos"])),
                    float("nan"), float("nan"), float("nan"), 0.5)
                self.assertEqual(fine["fail"], None, pid)
                got = {
                    "op_pass": str(fine["op_pass"]),
                    "vout_max_track_v": swing_post.serialize(fine["vout_max_track"]),
                    "vout_min_track_v": swing_post.serialize(fine["vout_min_track"]),
                    "headroom_hi_v": swing_post.serialize(fine["headroom_hi"]),
                    "headroom_lo_v": swing_post.serialize(fine["headroom_lo"]),
                    "swing_span_v": swing_post.serialize(fine["span"]),
                    "vout_clip_high_v": swing_post.serialize(coarse["clip_high"]),
                    "vout_clip_low_v": swing_post.serialize(coarse["clip_low"]),
                    "vos_crossing_v": swing_post.serialize(fine["vos_crossing"]),
                    "peak_inc_gain_v_v": swing_post.serialize(fine["g_pk"]),
                    "ivdd_center_a": swing_post.serialize(fine["ivdd_center"]),
                }
                for column in self.COLUMNS:
                    self.assertEqual(Decimal(row[column]), Decimal(got[column]), (pid, column))

    def test_committed_curves_match_their_netlists_declared_windows(self):
        for pid in self.POINTS:
            with self.subTest(point=pid):
                for kind, vectors in (("coarse", ("v(out)",)), ("fine", ("v(out)", "i(vdd)"))):
                    rc = swing_post.rendered_config(
                        (REPO / f"sim/output-swing/netlist-snapshots/{RECORD}/{pid}_{kind}.spice").read_text(encoding="utf-8"))
                    text = (REPO / f"sim/output-swing/corners/{RECORD}/{pid}_{kind}.csv").read_text(encoding="utf-8")
                    vid, _ = swing_post.parse_wrdata(text, vectors)
                    self.assertEqual(len(vid), swing_post.sweep_count(rc["start"], rc["stop"], rc["step"]), (pid, kind))


class Cli(TempCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(HERE / "swing_post.py"), *args],
                              capture_output=True, text=True)

    def test_coarse_output_shape(self):
        path = self.write("c.csv", synth_coarse())
        res = self.run_cli("coarse", str(path), str(VCM))
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        vos, n_cross, clip_high, clip_low, plateau = res.stdout.split()
        self.assertEqual(n_cross, "1")
        self.assertEqual(plateau, "1")
        self.assertEqual(float(vos), float(swing_post.serialize(VOS)))

    def test_fine_output_matches_format_fields(self):
        coarse = self.write("c.csv", synth_coarse())
        fine = self.write("f.csv", synth_fine())
        vos, _, clip_high, clip_low, plateau = self.run_cli("coarse", str(coarse), str(VCM)).stdout.split()
        res = self.run_cli("fine", str(fine), str(VDD), str(VCM), clip_high, clip_low, plateau, vos,
                           "42.9", "1.1e-4", "0.0121", "0.5")
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        vid, (vout, ivdd) = swing_post.parse_wrdata(synth_fine(), ("v(out)", "i(vdd)"))
        m = swing_post.fine_measure(vid, vout, ivdd, VDD, VCM, float(clip_high), float(clip_low),
                                    int(plateau), float(vos), 42.9, 1.1e-4, 0.0121, 0.5)
        self.assertEqual(res.stdout.split(),
                         swing_post.format_fields(m, float(clip_high), float(clip_low), 42.9, 1.1e-4, 0.0121))

    def test_fine_default_criterion_comes_from_the_pinned_config(self):
        fine = self.write("f.csv", synth_fine())
        a = self.run_cli("fine", str(fine), str(VDD), str(VCM), "1.5", "-0.3", "1", "0", "nan", "nan", "nan")
        b = self.run_cli("fine", str(fine), str(VDD), str(VCM), "1.5", "-0.3", "1", "0", "nan", "nan", "nan",
                         swing_post.CONFIG["criterion_frac"])
        self.assertEqual(a.stdout, b.stdout)

    def test_bad_coarse_curve_exits_nonzero_with_no_stdout(self):
        path = self.write("bad.csv", " 0 1 \n 1e-3 nan \n")
        res = self.run_cli("coarse", str(path), "0.6")
        self.assertEqual((res.returncode, res.stdout), (1, ""))
        self.assertIn("non-finite", res.stderr)

    def test_bad_fine_curve_keeps_the_row_well_formed(self):
        path = self.write("bad.csv", " 0 1 0 -1 \n 1e-3 nan 1e-3 -1 \n")
        res = self.run_cli("fine", str(path), "1.2", "0.6", "1.1", "0.05", "1", "0.012", "42.9", "1.1e-4", "0.0121")
        self.assertEqual(res.returncode, 0)
        self.assertIn("non-finite", res.stderr)
        self.assertEqual(len(res.stdout.split()), 17)
        self.assertEqual(res.stdout.split()[0], "0")

    def test_usage_error(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("nope", "x").returncode, 2)


class SelectionConfig(unittest.TestCase):
    def test_config_is_json_clean_and_matches_the_committed_bench(self):
        runner = (HERE / "run_swing_sweep.sh").read_text(encoding="utf-8")
        for var, key in (("COARSE_START", "coarse_start_v"), ("COARSE_STOP", "coarse_stop_v"),
                         ("COARSE_STEP", "coarse_step_v"), ("FINE_HALFSPAN", "fine_halfspan_v"),
                         ("FINE_STEP", "fine_step_v"), ("CRITERION_FRAC", "criterion_frac")):
            self.assertIn(f'{var}="{swing_post.CONFIG[key]}"', runner)
        pins = json.loads((REPO / "signoff/characterization/selection.json").read_text(encoding="utf-8"))
        self.assertEqual(pins["records"]["output-swing"]["swing_raw"]["config"], swing_post.CONFIG)


if __name__ == "__main__":
    unittest.main()

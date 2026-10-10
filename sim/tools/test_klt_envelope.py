"""Negative controls for klt_envelope.py, the shared envelope gate (offline).

    python3 -m unittest discover -s sim/tools -p 'test_klt_envelope.py' -v

The fixtures are minimal synthetic `klt sim`-shaped envelopes on the ratified
grid; nothing here is evidence about the circuit. Each bench's own
sim/*/klt/test_compare.py still drives this gate through its compare.py with
fixtures built from that bench's committed harness record; this file pins the
shared behaviour once -- in particular the exact message strings, since
compare.py's stderr and exit status are what the bench runners act on.
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klt_envelope as E  # noqa: E402

MEAS = ("a", "b")


def _envelope(keys=None, values=None):
    corners = []
    for p, t, v in keys if keys is not None else E.expected_keys():
        corners.append({
            "corner_id": f"{p}/vdd={v:.3f}/{t}C", "process": p, "temperature_c": float(t),
            "supply_v": {"vdd": v, "vinp": v / 2}, "status": "pass",
            "measurements": [{"name": n, "value": (values or {}).get(n, 1.0), "status": "pass"}
                             for n in MEAS],
        })
    return {"status": "pass", "corner_count": len(corners), "corners": corners,
            "coverage": {"nothing_checked": False, "skipped": []}}


TT = ("mos_tt", 27, 1.2)


def _corner(env, key=TT):
    for c in env["corners"]:
        if E.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == key:
            return c
    raise KeyError(key)


class TestGrid(unittest.TestCase):
    def test_grid_is_45_unique_points(self):
        keys = E.expected_keys()
        self.assertEqual(len(keys), 45)
        self.assertEqual(len(set(keys)), 45)
        self.assertEqual(keys[0], ("mos_tt", -40, 1.08))

    def test_make_key_normalises(self):
        self.assertEqual(E.make_key("mos_ss", "-40.0", "1.0800000001"), ("mos_ss", -40, 1.08))
        self.assertEqual(E.make_key("mos_ff", 124.6, 1.32), ("mos_ff", 125, 1.32))

    def test_key_str_is_the_harness_point_id(self):
        self.assertEqual(E.key_str(("mos_fs", 125, 1.08)), "mos_fs_125C_1.08V")
        self.assertEqual(E.key_str(("mos_ss", -40, 1.2)), "mos_ss_-40C_1.20V")

    def test_check_grid_names_missing_and_extra(self):
        keys = [k for k in E.expected_keys() if k != TT] + [("mos_xx", 27, 1.2)]
        problems = []
        E.check_grid(keys, "lbl", problems)
        self.assertEqual(problems, ["mos_tt_27C_1.20V: missing from lbl",
                                    "mos_xx_27C_1.20V: not a point of the ratified grid"])

    def test_finite(self):
        self.assertTrue(E.finite(1) and E.finite(-2.5))
        for x in (None, True, False, float("nan"), float("inf"), "1.0"):
            self.assertFalse(E.finite(x), x)

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"abc")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(E.sha256_file(f.name),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class TestIndexEnvelope(unittest.TestCase):
    def index(self, env, **kw):
        return E.index_envelope(env, "lbl", MEAS, **kw)

    def fails(self, env, msg, **kw):
        with self.assertRaises(E.InputError) as cm:
            self.index(env, **kw)
        self.assertEqual(str(cm.exception), msg)

    def test_baseline_indexes_every_point(self):
        out = self.index(_envelope())
        self.assertEqual(set(out), set(E.expected_keys()))
        self.assertEqual(out[TT], {"a": 1.0, "a__status": "pass", "b": 1.0, "b__status": "pass"})

    def test_reordered_is_equivalent(self):
        env = _envelope()
        env["corners"].reverse()
        self.assertEqual(self.index(env), self.index(_envelope()))

    def test_envelope_level_refusals(self):
        self.fails([], "lbl: not a JSON object")
        env = _envelope(); env["error"] = "boom"
        self.fails(env, "lbl: klt error envelope: boom")
        env = _envelope(); del env["corners"]
        self.fails(env, "lbl: no corners[] array")
        env = _envelope(); env["corner_count"] = 44
        self.fails(env, "lbl: corner_count 44 != len(corners) 45")
        env = _envelope(); del env["coverage"]
        self.fails(env, "lbl: no coverage block")
        env = _envelope(); env["coverage"]["nothing_checked"] = None
        self.fails(env, "lbl: coverage.nothing_checked is None, expected false")
        env = _envelope(); env["coverage"]["skipped"] = ["x", "y"]
        self.fails(env, "lbl: coverage.skipped is non-empty (2 item(s)), e.g. x")
        env = _envelope(); env["status"] = "inconclusive"
        self.fails(env, "lbl: aggregate status 'inconclusive' -- only a complete pass/fail run is evidence")

    def test_missing_duplicate_extra_point(self):
        env = _envelope([k for k in E.expected_keys() if k != TT])
        self.fails(env, "lbl: mos_tt_27C_1.20V: missing from lbl")
        env = _envelope(E.expected_keys() + [TT])
        self.fails(env, "lbl: mos_tt_27C_1.20V: duplicate corner")
        env = _envelope(E.expected_keys() + [("mos_tt", 27, 1.5)])
        self.fails(env, "lbl: mos_tt_27C_1.50V: not a point of the ratified grid")

    def test_corner_level_refusals_are_collected_in_order(self):
        env = _envelope()
        c = _corner(env)
        c["supply_v"]["vinp"] = 0.5
        c["status"] = "error"
        c["measurements"][1]["value"] = float("nan")
        c["measurements"].append(copy.deepcopy(c["measurements"][0]))
        self.fails(env, "lbl: mos_tt_27C_1.20V: vinp 0.5 != vdd/2 (1.2/2); "
                        "mos_tt_27C_1.20V: corner status 'error'; "
                        "mos_tt_27C_1.20V: measurement a reported twice; "
                        "mos_tt_27C_1.20V: measurement b value nan is missing or non-finite")

    def test_missing_supply_and_measurement(self):
        env = _envelope()
        del _corner(env)["supply_v"]["vinp"]
        self.fails(env, "lbl: mos_tt/vdd=1.200/27C: missing process or supply_v.vdd/vinp; "
                        "mos_tt_27C_1.20V: missing from lbl")
        env = _envelope()
        _corner(env)["measurements"].pop()
        self.fails(env, "lbl: mos_tt_27C_1.20V: measurement b missing")
        env = _envelope()
        _corner(env)["measurements"][0]["value"] = None
        self.fails(env, "lbl: mos_tt_27C_1.20V: measurement a value None is missing or non-finite")

    def test_reject_statuses_hook(self):
        env = _envelope()
        _corner(env)["measurements"][0]["status"] = "skipped"
        # Without the hook a finite value with any status is indexed as-is.
        self.assertEqual(self.index(env)[TT]["a__status"], "skipped")
        self.fails(env, "lbl: mos_tt_27C_1.20V: measurement a status 'skipped'",
                   reject_statuses=("skipped", "error"))

    def test_corner_check_hook(self):
        seen = []

        def check(k, vals, problems):
            seen.append(k)
            if vals.get("a", 0) > 1:
                problems.append(f"{E.key_str(k)}: a too big")

        self.index(_envelope(), corner_check=check)
        self.assertEqual(len(seen), 45)
        env = _envelope()
        _corner(env)["measurements"][0]["value"] = 2.0
        self.fails(env, "lbl: mos_tt_27C_1.20V: a too big", corner_check=check)

    def test_accept_statuses(self):
        env = _envelope()
        _corner(env)["measurements"][0]["status"] = None
        self.assertIsNone(self.index(env)[TT]["a__status"])
        self.fails(env, "lbl: mos_tt_27C_1.20V: measurement a status None", accept_statuses=("pass", "fail"))
        _corner(env)["measurements"][0]["status"] = "fail"
        self.assertEqual(self.index(env, accept_statuses=("pass", "fail"))[TT]["a__status"], "fail")

    def test_supply_key(self):
        env = _envelope()
        for c in env["corners"]:
            c["supply_v"]["vcm"] = c["supply_v"].pop("vinp")
        self.assertEqual(len(self.index(env, supply_key="vcm")), 45)
        _corner(env)["supply_v"]["vcm"] = 0.5
        self.fails(env, "lbl: mos_tt_27C_1.20V: vcm 0.5 != vdd/2 (1.2/2)", supply_key="vcm")
        del _corner(env)["supply_v"]["vcm"]
        self.fails(env, "lbl: mos_tt/vdd=1.200/27C: missing process or supply_v.vdd/vcm; "
                        "mos_tt_27C_1.20V: missing from lbl", supply_key="vcm")

    def test_points(self):
        nominal = [TT]
        self.assertEqual(list(self.index(_envelope(nominal), points=nominal)), nominal)
        self.fails(_envelope(), "lbl: " + "; ".join(
            f"{E.key_str(k)}: unexpected point (not in the requested point set)"
            for k in sorted(set(E.expected_keys()) - {TT})), points=nominal)
        self.fails(_envelope([]), "lbl: mos_tt_27C_1.20V: missing from lbl", points=nominal)

    def test_envelope_check_hook(self):
        def check(env, label, problems):
            if env.get("x") == "raise":
                raise E.InputError(f"{label}: x raised")
            if env.get("x"):
                problems.append(f"x is {env['x']}")

        env = _envelope()
        self.assertEqual(len(self.index(env, envelope_check=check)), 45)
        env["x"] = "raise"
        self.fails(env, "lbl: x raised", envelope_check=check)
        # Appended problems come before every per-corner problem.
        env["x"] = "set"
        _corner(env)["status"] = "error"
        self.fails(env, "lbl: x is set; mos_tt_27C_1.20V: corner status 'error'", envelope_check=check)

    def test_measurement_check_hook(self):
        seen = []

        def check(k, n, m, v, problems):
            seen.append((k, n, v))
            if v > 1:
                problems.append(f"{E.key_str(k)}: {n} too big")
                return False
            return True

        self.index(_envelope(), measurement_check=check)
        self.assertEqual(len(seen), 90)
        env = _envelope()
        c = _corner(env)
        c["measurements"][0]["value"] = 2.0
        c["measurements"][1]["value"] = float("nan")  # finiteness is checked before the hook
        self.fails(env, "lbl: mos_tt_27C_1.20V: a too big; "
                        "mos_tt_27C_1.20V: measurement b value nan is missing or non-finite",
                   measurement_check=check)


class TestReadEnvelope(unittest.TestCase):
    def test_read_and_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.json")
            with open(good, "w") as f:
                json.dump(_envelope(), f)
            self.assertEqual(E.read_envelope(good)["corner_count"], 45)
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as f:
                f.write("{")
            with self.assertRaises(E.InputError) as cm:
                E.read_envelope(bad)
            self.assertTrue(str(cm.exception).startswith(f"{bad}: unreadable envelope ("))
            with self.assertRaises(E.InputError):
                E.read_envelope(os.path.join(d, "absent.json"))


class TestCliScaffold(unittest.TestCase):
    TABLE = {"m": {"abs": 0.5, "rel": 0.1}}

    def test_tol(self):
        self.assertEqual(E.tol(self.TABLE, "m", -10.0), 0.5 + 0.1 * 10.0)
        with self.assertRaises(KeyError):
            E.tol(self.TABLE, "x", 1.0)

    def test_summary_tail(self):
        rep = {"out_of_tolerance": ["p1", "p2"], "bound_verdict_disagreements": [{"k": 1}]}
        self.assertEqual(E.summary_tail(["head"], rep),
                         ["head", "  OUT OF TOLERANCE: p1", "  OUT OF TOLERANCE: p2",
                          "  VERDICT DISAGREES: {'k': 1}"])
        self.assertEqual(E.summary_tail([], {"out_of_tolerance": [], "bound_verdict_disagreements": []}), [])

    def _index(self, env, label):
        return E.index_envelope(env, label, MEAS)

    def _cli(self, argv, status="agree"):
        def run(a, tool, env):
            if a.extra == "boom":
                raise E.InputError("boom")
            return {"status": status}
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = E.run_cli(argv, description="d", compare_help="h",
                           harness_args=(("--extra", {"required": True}),),
                           index_fn=self._index, run=run,
                           inputs=(("extra", "extra", False),),
                           summary=lambda rep: f"S {rep['status']}")
        return rc, out.getvalue(), err.getvalue()

    def _good(self, d):
        good = os.path.join(d, "good.json")
        with open(good, "w") as f:
            json.dump(_envelope(), f)
        return good

    def test_load_envelope(self):
        with tempfile.TemporaryDirectory() as d:
            env, idx = E.load_envelope(self._good(d), self._index)
            self.assertEqual(env["corner_count"], 45)
            self.assertEqual(len(idx), 45)

    def test_validate_and_compare(self):
        with tempfile.TemporaryDirectory() as d:
            good = self._good(d)
            rc, out, _ = self._cli(["validate", good])
            self.assertEqual((rc, out), (0, f"validate: {good}: 45 corners, status {_envelope().get('status')}, ok\n"))
            rep_path = os.path.join(d, "r.json")
            argv = ["compare", "--envelope", good, "--extra", "x"]
            rc, out, _ = self._cli(argv + ["--json-out", rep_path, "--provenance", "k=v", "--provenance", "a=b=c"])
            self.assertEqual((rc, out), (0, "S agree\n"))
            with open(rep_path) as f:
                text = f.read()
            rep = json.loads(text)
            self.assertEqual(text, json.dumps(rep, indent=2) + "\n")
            self.assertEqual(rep["provenance"], {"k": "v", "a": "b=c"})
            self.assertEqual(list(rep["inputs"]), ["envelope", "extra"])
            self.assertEqual(rep["inputs"]["envelope"], {"path": good, "sha256": E.sha256_file(good)})
            self.assertEqual(rep["inputs"]["extra"], {"path": "x"})
            self.assertEqual(self._cli(argv, status="disagree")[0], 1)

    def test_input_error_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = self._cli(["compare", "--envelope", self._good(d), "--extra", "boom"])
            self.assertEqual((rc, out, err), (2, "", "compare.py: boom\n"))
            absent = os.path.join(d, "absent.json")
            rc, out, err = self._cli(["validate", absent])
            self.assertEqual((rc, out), (2, ""))
            self.assertTrue(err.startswith(f"compare.py: {absent}: unreadable envelope ("))

    def test_common_args_reach_both_subcommands_and_the_gate(self):
        sets = {"all": None, "tt": [TT]}

        def index(env, label, points):
            return E.index_envelope(env, label, MEAS, points=sets[points])

        def cli(argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = E.run_cli(argv, description="d", compare_help="h",
                               harness_args=(("--extra", {"required": True}),),
                               common_args=(("--points", {"choices": sorted(sets), "default": "all"}),),
                               index_fn=index, run=lambda a, tool, env: {"status": "agree", "n": len(tool)},
                               inputs=(), summary=lambda rep: f"S {rep['n']}", validate_noun="corner(s)")
            return rc, out.getvalue(), err.getvalue()

        with tempfile.TemporaryDirectory() as d:
            one = os.path.join(d, "one.json")
            with open(one, "w") as f:
                json.dump(_envelope([TT]), f)
            self.assertEqual(cli(["validate", one, "--points", "tt"])[:2], (0, f"validate: {one}: 1 corner(s), status pass, ok\n"))
            self.assertEqual(cli(["validate", one])[0], 2)
            self.assertEqual(cli(["compare", "--envelope", one, "--extra", "x", "--points", "tt"])[:2], (0, "S 1\n"))


if __name__ == "__main__":
    unittest.main()

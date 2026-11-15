#!/usr/bin/env python3
"""The generic `klt sim` envelope-refusal controls, written once (issue #370).

Every sim/*/klt/test_compare.py carried its own transcription of the same
thirteen negative controls -- refusals that all live in the SHARED gate
klt_envelope.index_envelope, not in any bench. This mixin holds the thirteen
bodies once; each bench's negative-control class mixes it in and still runs
every control through ITS OWN comparator gate, so per-bench coverage and the
per-bench test count are unchanged (a reworded refusal or a new `coverage`
key now lands here instead of being chased through six files).

Contract with the bench class that mixes this in (its Base supplies most of
it; see test_envelope_control_mixin.py beside this file for a minimal
conforming bench):

* gate(env)      -- this bench's envelope gate; must raise
                    klt_envelope.InputError on refusal. Default: self.tool(env).
* env()          -- a fresh, valid envelope dict. Only the default control()
                    calls it, and it must come from the bench's own Base (the
                    mixin deliberately does not define it, so it cannot
                    shadow the bench's); a bench with more than one envelope
                    kind overrides control() instead.
* control(name)  -- the (env, gate) pair that control `name` runs against.
                    Default: (self.env(), self.gate). open-loop-ac overrides
                    it to alternate the ac/op envelopes as before;
                    output-swing overrides it to gate the committed point set.
* WORST          -- grid key (process, temperature_c, vdd) of the corner the
                    measurement controls tamper with.
* null_meas / nonfinite_meas / absent_meas -- declared measurement names at
                    WORST for the null / non-finite / absent controls.
* supply_key     -- the supply_v entry that carries Vcm ("vinp"; output-swing
                    uses "vcm").
* points         -- the point set the gate requires, when it is NOT the
                    ratified grid (output-swing). Only the extra-corner
                    message differs ("unexpected point" vs "not a point of
                    the ratified grid").

The expected-refusal fragments are derived from klt_envelope's message
formats plus the tampered key/name, so every assertion is at least as
specific as the per-bench transcriptions were (and stricter where those
named only a substring).
"""

from __future__ import annotations

import copy
from typing import Callable, Dict, Optional, Sequence, Tuple

import klt_envelope as K


class EnvelopeControlMixin:
    """The thirteen generic envelope refusals; see the module docstring."""

    # -- contract (set by the bench class) --------------------------------
    WORST: K.Key
    null_meas: str
    nonfinite_meas: str
    absent_meas: str
    supply_key: str = "vinp"
    points: Optional[Sequence[K.Key]] = None

    def gate(self, env: Dict) -> None:
        """The bench's envelope gate; raises klt_envelope.InputError."""
        self.tool(env)

    def control(self, name: str) -> Tuple[Dict, Callable[[Dict], None]]:
        """The (env, gate) pair that control `name` runs against."""
        return self.env(), self.gate

    # -- helpers -----------------------------------------------------------
    def _corner_at(self, env: Dict, key: K.Key) -> Dict:
        for c in env["corners"]:
            if K.make_key(c["process"], c["temperature_c"], c["supply_v"]["vdd"]) == key:
                return c
        raise KeyError(key)

    def _meas_at(self, env: Dict, key: K.Key, name: str) -> Dict:
        return next(m for m in self._corner_at(env, key)["measurements"] if m["name"] == name)

    # -- the thirteen controls ---------------------------------------------
    def test_missing_corner(self):
        env, gate = self.control("test_missing_corner")
        gone = env["corners"].pop(len(env["corners"]) // 2)
        env["corner_count"] = len(env["corners"])
        gone_key = K.make_key(gone["process"], gone["temperature_c"], gone["supply_v"]["vdd"])
        with self.assertRaisesRegex(K.InputError, rf"{K.key_str(gone_key)}: missing from"):
            gate(env)

    def test_duplicate_corner(self):
        env, gate = self.control("test_duplicate_corner")
        twin = copy.deepcopy(env["corners"][0])
        env["corners"].append(twin)
        env["corner_count"] += 1
        twin_key = K.make_key(twin["process"], twin["temperature_c"], twin["supply_v"]["vdd"])
        with self.assertRaisesRegex(K.InputError, rf"{K.key_str(twin_key)}: duplicate corner"):
            gate(env)

    def test_extra_off_grid_corner(self):
        env, gate = self.control("test_extra_off_grid_corner")
        extra = copy.deepcopy(env["corners"][0])
        vdd = float(extra["supply_v"]["vdd"]) + 0.02   # off every ratified supply rail
        extra["supply_v"] = {"vdd": vdd, self.supply_key: vdd / 2}
        env["corners"].append(extra)
        env["corner_count"] += 1
        extra_key = K.make_key(extra["process"], extra["temperature_c"], vdd)
        not_on = ("not a point of the ratified grid" if self.points is None
                  else "unexpected point")
        with self.assertRaisesRegex(K.InputError, rf"{K.key_str(extra_key)}: {not_on}"):
            gate(env)

    def test_corner_count_mismatch(self):
        env, gate = self.control("test_corner_count_mismatch")
        n = len(env["corners"])
        env["corner_count"] = n - 1
        with self.assertRaisesRegex(K.InputError, rf"corner_count {n - 1} != len\(corners\) {n}"):
            gate(env)

    def test_null_measurement(self):
        env, gate = self.control("test_null_measurement")
        self._meas_at(env, self.WORST, self.null_meas)["value"] = None
        with self.assertRaisesRegex(
                K.InputError, rf"{K.key_str(self.WORST)}: measurement {self.null_meas} value None"):
            gate(env)

    def test_nonfinite_measurement(self):
        env, gate = self.control("test_nonfinite_measurement")
        self._meas_at(env, self.WORST, self.nonfinite_meas)["value"] = float("nan")
        with self.assertRaisesRegex(
                K.InputError,
                rf"{K.key_str(self.WORST)}: measurement {self.nonfinite_meas} value nan"):
            gate(env)

    def test_absent_measurement(self):
        env, gate = self.control("test_absent_measurement")
        corner = self._corner_at(env, self.WORST)
        corner["measurements"] = [m for m in corner["measurements"] if m["name"] != self.absent_meas]
        with self.assertRaisesRegex(
                K.InputError, rf"{K.key_str(self.WORST)}: measurement {self.absent_meas} missing"):
            gate(env)

    def test_vcm_not_half_vdd(self):
        env, gate = self.control("test_vcm_not_half_vdd")
        self._corner_at(env, self.WORST)["supply_v"][self.supply_key] = 0.55
        with self.assertRaisesRegex(
                K.InputError, rf"{K.key_str(self.WORST)}: {self.supply_key} 0.55 != vdd/2"):
            gate(env)

    def test_errored_corner_is_not_evidence(self):
        env, gate = self.control("test_errored_corner_is_not_evidence")
        self._corner_at(env, self.WORST)["status"] = "error"
        with self.assertRaisesRegex(
                K.InputError, rf"{K.key_str(self.WORST)}: corner status 'error'"):
            gate(env)

    def test_inconclusive_run_is_not_evidence(self):
        env, gate = self.control("test_inconclusive_run_is_not_evidence")
        env["status"] = "inconclusive"
        with self.assertRaisesRegex(K.InputError, r"aggregate status 'inconclusive'"):
            gate(env)

    def test_nothing_checked(self):
        env, gate = self.control("test_nothing_checked")
        env["coverage"]["nothing_checked"] = True
        with self.assertRaisesRegex(
                K.InputError, r"coverage.nothing_checked is True, expected false"):
            gate(env)

    def test_skipped_coverage(self):
        env, gate = self.control("test_skipped_coverage")
        env["coverage"]["skipped"] = [{"id": "limit:x", "reason": "r"}]
        with self.assertRaisesRegex(K.InputError, r"coverage.skipped is non-empty"):
            gate(env)

    def test_klt_error_envelope(self):
        _, gate = self.control("test_klt_error_envelope")
        with self.assertRaisesRegex(K.InputError, r"klt error envelope"):
            gate({"error": {"code": "negative_control"}})

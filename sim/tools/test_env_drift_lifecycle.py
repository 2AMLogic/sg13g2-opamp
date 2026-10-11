"""Offline lifecycle controls for the #209 model-identity drift check.

A record's run-time PDK/model identity (sim/tools/env_identity.py, #191) is
captured BEFORE the first solver (sg13g2_env_identity_begin) and rechecked
against a fresh capture immediately before the record is finalized
(sg13g2_env_identity_finalize, sim/env-identity.sh). These tests drive the
REAL lifecycle helpers through three representative runners against a fake
PDK install, with stub solvers that can change the install mid-run:

  * KltRunner     -- the real sim/tools/klt_run_common.sh (the four
                     sim/*/klt/run.sh wrappers' shared lifecycle) with a
                     stub `klt` and a stub compare.py;
  * OpenLoopRunner -- the real sim/open-loop-ac/run_pvt_sweep.sh, copied
                     with its real sim/preflight.sh, env.sh, record-paths.sh
                     and env-identity.sh into a throwaway tree, with a stub
                     `ngspice` and a stub sim/tools/build-osdi.sh;
  * NativeNoiseRunner -- the real sim/input-noise/run_noise_sweep.sh, the
                     same throwaway-tree setup, with a stub `ngspice` that
                     can drift the install at the units check or at a DUT
                     solve (issue #214).

No PDK download, ngspice, OSDI build or klt is needed; `date` and `git` are
shadowed so record ids are deterministic. Stdlib unittest:

  python3 -m unittest discover -s sim/tools -p 'test_env_drift_lifecycle.py' -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SIM_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import env_identity as ei  # noqa: E402

PDK = "ihp-sg13g2"
NGSPICE = "ngspice-46"
TS = "20260101-000000"
SHA = "abc1234"
RID = f"{TS}-{SHA}"
PIN_TEXT = (SIM_DIR / "pdk.json").read_text(encoding="utf-8")
PIN = json.loads(PIN_TEXT)

MOS_INC = f"{PDK}/{ei.MODELS_SUBDIR}/sub/mos.inc"
OSDI_MANIFEST = f"{PDK}/{ei.OSDI_MANIFEST_REL}"
MARKER = f"{PDK}/.fetched-version"


def make_install(pdk_root: Path) -> None:
    inst = pdk_root / PDK
    models = inst / ei.MODELS_SUBDIR
    (models / "sub").mkdir(parents=True)
    (models / "cornerMOSlv.lib").write_text(
        '.lib mos_tt\n.include "sub/mos.inc"\n.endl mos_tt\n', encoding="utf-8")
    (models / "cornerCAP.lib").write_text("* cap\n", encoding="utf-8")
    (models / "sub" / "mos.inc").write_text("* mos tt\n", encoding="utf-8")
    (inst / ".fetched-version").write_text("0.3.0\n", encoding="utf-8")
    osdi = inst / "libs.tech/ngspice/osdi"
    osdi.mkdir(parents=True)
    (osdi / ".build-manifest").write_text("schema=1\n", encoding="utf-8")


# The stub solver. If MUTATE_FILE is set, every invocation (over)writes
# MUTATE_TEXT into it -- a persistent change to the environment made while
# the run is in flight. If RELINK is set, the install is moved to a new host
# path (same bytes) and the PDK_ROOT symlink repointed: a host-path-only
# change, which must NOT count as drift.
MUTATE_SH = r"""
if [[ -n "${MUTATE_FILE:-}" ]]; then printf '%s' "${MUTATE_TEXT}" > "${MUTATE_FILE}"; fi
if [[ -n "${RELINK:-}" && ! -e "${RELINK}" ]]; then
  cp -R "$(readlink -f "${PDK_ROOT}")" "${RELINK}"
  ln -sfn "${RELINK}" "${PDK_ROOT}"
fi
"""

STUB_KLT = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "--version" ]]; then echo "stub-klt 0"; exit 0; fi
echo "$$" >> "${STUB_KLT_LOG}"
""" + MUTATE_SH + r"""
echo "{\"from\": \"${TAG}\"}"
exit 0
"""

STUB_COMPARE = r"""import os, sys
if sys.argv[1] == "validate":
    sys.exit(0)
out = sys.argv[sys.argv.index("--json-out") + 1]
with open(out, "w") as f:
    f.write('{"compare": "%s"}' % os.environ["TAG"])
sys.exit(0)
"""

# Mimics a bench sim/*/klt/run.sh: preflight.sh would provide the identity
# lifecycle; here the REAL sim/env-identity.sh is sourced directly.
KLT_DRIVER = r"""
set -euo pipefail
SCRIPT_DIR="$1"; REPO_ROOT="$2"; SUFFIX="${3:-}"
SIM_DIR="${REPO_ROOT}/sim"
date() { echo "${FAKE_TS}"; }
git() { echo "${FAKE_SHA}"; }
# shellcheck source=/dev/null
source "${COMMON}"
# shellcheck source=/dev/null
source "${LIFECYCLE}"
KLT="${STUB_KLT}"
klt_check_client
klt_begin_record stub "${SUFFIX}"
out="${SCRATCH}/x.sim.json"
klt_run_request req.json "${out}" "${SCRATCH}/x.stderr"
klt_validate_envelope "${out}"
klt_require_complete
klt_write_envelope "${out}"
klt_compare_and_finish
"""

STUB_NGSPICE = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
""" + MUTATE_SH + r"""
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
ac_csv="$(awk '/^wrdata /{print $2}' "${netlist}")"
half="$(awk -v v="${vdd}" 'BEGIN{print v/2}')"
printf '1 60 1 -10\n1e6 20 1e6 -100\n1e9 -20 1e9 -170\n' > "${ac_csv}"
echo "OP_VOUT ${half}"
echo "OP_VD1 ${half}"
echo "OP_VD2 ${half}"
echo "OP_VTAIL ${half}"
echo "OP_VIBIAS ${half}"
echo "OP_IVDD 2e-05"
exit 0
"""

# The input-noise bench's stub solver. Deck layout the real runner relies
# on, mirrored by NOISE_TMPL below: the units-check deck (named
# *tb_noise_units_check*) is the FIRST `-b` invocation, each DUT point is a
# rendered template carrying one `Vdd` line and two `wrdata` lines whose
# first output path is the in-band spectrum CSV the sweep post-processes
# (81 swept points, (scale,value) column pairs).
#
# MUTATE_UNITS_FILE/TEXT mutate the install at the units check only;
# MUTATE_FILE/TEXT (the shared MUTATE_SH) at a DUT solve only. NGSPICE_LOG
# records every `-b` deck path, so a test can prove a solver never ran.
STUB_NOISE_NGSPICE = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
echo "${netlist}" >> "${NGSPICE_LOG}"
if [[ "${netlist}" == *tb_noise_units_check* ]]; then
  if [[ -n "${MUTATE_UNITS_FILE:-}" ]]; then printf '%s' "${MUTATE_UNITS_TEXT}" > "${MUTATE_UNITS_FILE}"; fi
  echo "UNITS_INOISE_SPECTRUM 4.0704e-09"
  echo "UNITS_ONOISE_SPECTRUM 4.0704e-07"
  echo "UNITS_INOISE_TOTAL 3.86146e-07"
  exit 0
fi
""" + MUTATE_SH + r"""
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
noise_csv="$(awk '/^wrdata /{print $2; exit}' "${netlist}")"
half="$(awk -v v="${vdd}" 'BEGIN{print v/2}')"
awk 'BEGIN{for(i=0;i<81;i++){f=100*10^(i/20); printf "%.12g %g %.12g %g\n", f, 1e-6, f, 1e-6}}' > "${noise_csv}"
echo "OP_VOUT ${half}"
echo "OP_VD1 ${half}"
echo "OP_VD2 ${half}"
echo "OP_VTAIL ${half}"
echo "OP_VIBIAS ${half}"
echo "OP_IVDD 2e-05"
echo "NOISE_INOISE_TOTAL 9.9995e-04"
echo "AC_CLGAIN_100HZ 1.0"
echo "AC_CLGAIN_1MHZ 1.0"
exit 0
"""

# Minimal stand-in for testbench/tb_noise.spice.tmpl: the runner only
# renders it (shared sed substitutions plus @@NOISE_CSV@@/@@NOISE_WIDE_CSV@@)
# and hands the result to the stub solver, which reads the two lines above.
NOISE_TMPL = """\
* stub noise testbench (offline lifecycle test)
Vdd vdd 0 dc @@VDD_V@@
wrdata @@NOISE_CSV@@ inoise_spectrum onoise_spectrum
wrdata @@NOISE_WIDE_CSV@@ inoise_spectrum onoise_spectrum
"""


STUB_BIN = {
    # Deterministic record ids for the real record-paths.sh.
    "date": '#!/usr/bin/env bash\nif [[ -n "${FAKE_TS:-}" ]]; then echo "${FAKE_TS}"; else exec /usr/bin/date "$@"; fi\n',
    "git": '#!/usr/bin/env bash\necho "${FAKE_SHA}"\n',
}


def _write_exec(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class Tree:
    """A throwaway repo root with a fake PDK install behind a symlinked PDK_ROOT."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.sim = self.root / "sim"
        (self.sim / "tools").mkdir(parents=True)
        (self.sim / "pdk.json").write_text(PIN_TEXT, encoding="utf-8")
        shutil.copy2(TOOLS_DIR / "env_identity.py", self.sim / "tools" / "env_identity.py")
        self.install_a = self.root / "pdk-a"
        make_install(self.install_a)
        self.pdk_root = self.root / "pdk"
        self.pdk_root.symlink_to(self.install_a)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # The lifecycle calls `python3`; pin it to this interpreter.
        (self.bin / "python3").symlink_to(sys.executable)
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()

    def env(self, **extra) -> dict:
        env = dict(os.environ)
        env.update(PATH=f"{self.bin}:{env.get('PATH', '/usr/bin:/bin')}",
                   PDK_ROOT=str(self.pdk_root), PDK=PDK, NGSPICE_VERSION=NGSPICE,
                   FAKE_TS=TS, FAKE_SHA=SHA, TMPDIR=str(self.tmp), TAG="x")
        env.update(extra)
        return env

    def live(self, rel: str) -> Path:
        return self.pdk_root.resolve() / rel

    def capture(self, record_id: str = RID, pin: dict = PIN) -> str:
        """What a begin capture of the CURRENT install says, byte for byte."""
        return ei.canonical_json(ei.capture(self.pdk_root, PDK, pin, record_id, NGSPICE))


def mutations(tree: Tree) -> dict:
    """Name -> (file, new text) for each persistent drift the check must catch."""
    pin = dict(PIN, release_tag="v0.3.1")
    return {
        "used model include": (tree.live(MOS_INC), "* mos tt, edited mid-run\n", "sub/mos.inc"),
        "OSDI manifest": (tree.live(OSDI_MANIFEST), "schema=1\noutput.psp103.osdi=deadbeef\n", "OSDI build-manifest"),
        "release marker": (tree.live(MARKER), "0.3.1\n", "release marker"),
        "configured pin": (tree.sim / "pdk.json", json.dumps(pin, indent=2) + "\n", "configured release_tag"),
    }


class KltRunner(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.build(self._tmp.name)

    def build(self, root: str) -> None:
        self.t = Tree(root)
        self.bench = self.t.sim / "bench" / "klt"
        (self.bench / "records").mkdir(parents=True)
        (self.bench / "compare.py").write_text(STUB_COMPARE, encoding="utf-8")
        self.klt = self.t.root / "klt"
        _write_exec(self.klt, STUB_KLT)
        self.driver = self.t.root / "driver.sh"
        self.driver.write_text(KLT_DRIVER, encoding="utf-8")
        self.log = self.t.root / "klt.log"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @property
    def records(self) -> Path:
        return self.bench / "records"

    def run_bench(self, suffix: str = "", **env) -> subprocess.CompletedProcess:
        e = self.t.env(COMMON=str(TOOLS_DIR / "klt_run_common.sh"),
                       LIFECYCLE=str(SIM_DIR / "env-identity.sh"),
                       STUB_KLT=str(self.klt), STUB_KLT_LOG=str(self.log), **env)
        return subprocess.run(["bash", str(self.driver), str(self.bench), str(self.t.root), suffix],
                              env=e, capture_output=True, text=True, timeout=60)

    def snapshot(self) -> dict:
        return {p.name: p.read_bytes() for p in sorted(self.records.iterdir())}

    def klt_calls(self) -> int:
        return len(self.log.read_text().split()) if self.log.exists() else 0

    def test_unchanged_install_publishes_the_begin_capture(self):
        r = self.run_bench(TAG="ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        snap = self.snapshot()
        self.assertEqual(sorted(snap), [f"{RID}.compare.json", f"{RID}.env.json", f"{RID}.sim.json"])
        self.assertEqual(snap[f"{RID}.env.json"].decode(), self.t.capture())
        self.assertEqual(list(self.t.tmp.iterdir()), [])  # scratch cleaned on success

    def test_host_path_only_change_is_not_drift(self):
        before = self.t.capture()
        r = self.run_bench(RELINK=str(self.t.root / "pdk-b"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.t.pdk_root.resolve(), (self.t.root / "pdk-b").resolve())
        self.assertEqual((self.records / f"{RID}.env.json").read_text(), before)

    def test_each_persistent_drift_refuses_finalization(self):
        for name in mutations(self.t):
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                self.build(d)  # a fresh tree per drift kind
                path, text, needle = mutations(self.t)[name]
                begin = self.t.capture()
                r = self.run_bench(MUTATE_FILE=str(path), MUTATE_TEXT=text)
                self.assertEqual(r.returncode, 4, r.stderr)
                self.assertIn("DRIFTED", r.stderr)
                self.assertIn(needle, r.stderr)
                self.assertIn("refusing to finalize", r.stderr)
                # Nothing finalized-looking: no sidecar, envelope, comparison
                # or leftover reservation.
                self.assertEqual(self.snapshot(), {})
                # Incomplete artifacts kept for inspection in scratch: the raw
                # envelope and the begin capture, which describes the bytes the
                # run started with.
                scratch = list(self.t.tmp.iterdir())
                self.assertEqual(len(scratch), 1)
                self.assertTrue((scratch[0] / "x.sim.json").is_file())
                self.assertEqual((scratch[0] / f"{RID}.env.json").read_text(), begin)

    def test_rerun_after_drift_finalizes_under_the_new_identity(self):
        path, text, _ = mutations(self.t)["used model include"]
        old = self.t.capture()
        self.assertEqual(self.run_bench(MUTATE_FILE=str(path), MUTATE_TEXT=text).returncode, 4)
        self.assertEqual(self.snapshot(), {})
        r = self.run_bench(TAG="again")
        self.assertEqual(r.returncode, 0, r.stderr)
        side = (self.records / f"{RID}.env.json").read_text()
        self.assertEqual(side, self.t.capture())
        self.assertNotEqual(side, old)

    def test_suffixed_record_reuses_a_matching_sidecar(self):
        self.assertEqual(self.run_bench("").returncode, 0)
        before = self.snapshot()
        r = self.run_bench(".nominal", TAG="nom")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.snapshot()
        self.assertEqual(after[f"{RID}.env.json"], before[f"{RID}.env.json"])
        self.assertIn(f"{RID}.nominal.sim.json", after)

    def test_existing_sidecar_from_another_identity_is_never_clobbered(self):
        self.assertEqual(self.run_bench("").returncode, 0)
        before = self.snapshot()
        # The install changes BETWEEN runs (not during one): the suffixed run
        # is internally consistent but disagrees with the record's sidecar.
        self.t.live(MOS_INC).write_text("* changed between runs\n", encoding="utf-8")
        r = self.run_bench(".nominal", TAG="nom")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("append-only", r.stderr)
        self.assertEqual(self.snapshot(), before)  # no .nominal.sim.json, sidecar intact

    def test_failed_begin_capture_aborts_before_any_solver(self):
        r = self.run_bench(PDK_ROOT=str(self.t.root / "no-such-pdk"))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("nothing was simulated", r.stderr)
        self.assertEqual(self.klt_calls(), 0)
        self.assertEqual(self.snapshot(), {})  # reservation released too


class OpenLoopRunner(unittest.TestCase):
    """The real sim/open-loop-ac/run_pvt_sweep.sh with a stub ngspice."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        for name in ("preflight.sh", "env.sh", "record-paths.sh", "env-identity.sh"):
            shutil.copy2(SIM_DIR / name, self.t.sim / name)
        _write_exec(self.t.sim / "tools" / "build-osdi.sh", "#!/usr/bin/env bash\nexit 0\n")
        self.bench = self.t.sim / "open-loop-ac"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "open-loop-ac" / "run_pvt_sweep.sh", self.bench / "run_pvt_sweep.sh")
        shutil.copy2(SIM_DIR / "open-loop-ac" / "testbench" / "tb_openloop_ac.spice.tmpl",
                     self.bench / "testbench" / "tb_openloop_ac.spice.tmpl")
        (self.t.root / "design" / "netlist").mkdir(parents=True)
        (self.t.root / "design" / "netlist" / "opamp_core.spice").write_text("* stub DUT\n", encoding="utf-8")
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE)
        for name, text in STUB_BIN.items():
            _write_exec(self.t.bin / name, text)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_sweep(self, ts: str = TS, **env) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.bench / "run_pvt_sweep.sh")],
                              env=self.t.env(FAKE_TS=ts, **env),
                              capture_output=True, text=True, timeout=300)

    def record_files(self, rid: str) -> list[str]:
        return sorted(p.name for p in (self.bench / "records").glob(f"{rid}*"))

    def test_stable_drift_and_rerun(self):
        # (a) unchanged install: the sidecar is published and equals the
        # begin capture; the record is finalized (.csv + .md).
        r = self.run_sweep()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record_files(RID), [f"{RID}.csv", f"{RID}.env.json", f"{RID}.md"])
        self.assertEqual((self.bench / "records" / f"{RID}.env.json").read_text(), self.t.capture())
        self.assertEqual(list(self.t.tmp.iterdir()), [])

        # (b) a used model include changes mid-sweep: exit 4, nothing that
        # looks finalized -- no .csv/.md/.env.json -- while the raw results
        # (corners/<id>/, records/<id>.csv.raw) and the begin capture stay.
        ts2 = "20260101-000100"
        rid2 = f"{ts2}-{SHA}"
        path, text, _ = mutations(self.t)["used model include"]
        begin = self.t.capture(rid2)
        r = self.run_sweep(ts2, MUTATE_FILE=str(path), MUTATE_TEXT=text)
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("DRIFTED", r.stderr)
        self.assertIn("sub/mos.inc", r.stderr)
        self.assertEqual(self.record_files(rid2), [f"{rid2}.csv.raw"])
        self.assertTrue(any((self.bench / "corners" / rid2).glob("*.log")))
        scratch = list(self.t.tmp.iterdir())
        self.assertEqual(len(scratch), 1)
        self.assertEqual((scratch[0] / f"{rid2}.env.json").read_text(), begin)

        # (c) the drifted id is never reused or clobbered: the same id is
        # refused before anything runs, and a fresh id finalizes under the
        # identity it actually started with.
        r = self.run_sweep(ts2)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(self.record_files(rid2), [f"{rid2}.csv.raw"])
        ts3 = "20260101-000200"
        rid3 = f"{ts3}-{SHA}"
        r = self.run_sweep(ts3)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record_files(rid3), [f"{rid3}.csv", f"{rid3}.env.json", f"{rid3}.md"])
        self.assertEqual((self.bench / "records" / f"{rid3}.env.json").read_text(), self.t.capture(rid3))
        # The first record is untouched throughout.
        self.assertEqual(self.record_files(RID), [f"{RID}.csv", f"{RID}.env.json", f"{RID}.md"])


class NativeNoiseRunner(unittest.TestCase):
    """The real sim/input-noise/run_noise_sweep.sh with a stub ngspice."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        for name in ("preflight.sh", "env.sh", "record-paths.sh", "env-identity.sh"):
            shutil.copy2(SIM_DIR / name, self.t.sim / name)
        _write_exec(self.t.sim / "tools" / "build-osdi.sh", "#!/usr/bin/env bash\nexit 0\n")
        self.bench = self.t.sim / "input-noise"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "input-noise" / "run_noise_sweep.sh", self.bench / "run_noise_sweep.sh")
        # The per-point post-processing the runner shells out to (#213): it
        # validates the stub solver's spectrum like the real one.
        shutil.copy2(SIM_DIR / "input-noise" / "noise_post.py", self.bench / "noise_post.py")
        (self.bench / "testbench" / "tb_noise.spice.tmpl").write_text(NOISE_TMPL, encoding="utf-8")
        (self.bench / "testbench" / "tb_noise_units_check.spice").write_text(
            "* stub units-check deck -- the stub solver answers for it\n", encoding="utf-8")
        (self.t.root / "design" / "netlist").mkdir(parents=True)
        (self.t.root / "design" / "netlist" / "opamp_core.spice").write_text("* stub DUT\n", encoding="utf-8")
        _write_exec(self.t.bin / "ngspice", STUB_NOISE_NGSPICE)
        for name, text in STUB_BIN.items():
            _write_exec(self.t.bin / name, text)
        self.log = self.t.root / "ngspice.log"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_sweep(self, ts: str = TS, **env) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.bench / "run_noise_sweep.sh")],
                              env=self.t.env(FAKE_TS=ts, NGSPICE_LOG=str(self.log), **env),
                              capture_output=True, text=True, timeout=300)

    def record_files(self, rid: str) -> list[str]:
        return sorted(p.name for p in (self.bench / "records").glob(f"{rid}*"))

    def solver_calls(self) -> int:
        return len(self.log.read_text().splitlines()) if self.log.exists() else 0

    def test_stable_run_publishes_the_begin_capture(self):
        r = self.run_sweep()
        self.assertEqual(r.returncode, 0, r.stderr)
        # One units check + one DUT solve per grid point (5 x 3 x 3).
        self.assertEqual(self.solver_calls(), 46)
        # The record is finalized: csv + md + the sidecar, which is the
        # ORIGINAL begin capture byte for byte.
        self.assertEqual(self.record_files(RID), [f"{RID}.csv", f"{RID}.env.json", f"{RID}.md"])
        self.assertEqual((self.bench / "records" / f"{RID}.env.json").read_text(), self.t.capture())
        self.assertIn(f"{RID}.env.json", (self.bench / "records" / f"{RID}.md").read_text())
        self.assertEqual(list(self.t.tmp.iterdir()), [])  # scratch cleaned on success

    def test_failed_begin_capture_aborts_before_any_solver(self):
        # An install whose model closure cannot be resolved: preflight's own
        # guards pass, but the begin capture refuses -- so the units check
        # and every DUT solve must be skipped and nothing finalized.
        self.t.live(MOS_INC).unlink()
        r = self.run_sweep()
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("refusing to start", r.stderr)
        self.assertIn("nothing was simulated", r.stderr)
        self.assertEqual(self.solver_calls(), 0)
        self.assertEqual(self.record_files(RID), [])

    def test_units_check_drift_refuses_finalization(self):
        path, text, needle = mutations(self.t)["used model include"]
        begin = self.t.capture()
        r = self.run_sweep(MUTATE_UNITS_FILE=str(path), MUTATE_UNITS_TEXT=text)
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("DRIFTED", r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertIn("refusing to finalize", r.stderr)
        # Nothing finalized-looking: the raw results stay provisional and
        # the corners/ inspection artifacts (units check + point logs) are
        # kept, but no .csv / .md / .env.json exists.
        self.assertEqual(self.record_files(RID), [f"{RID}.csv.raw"])
        corners = self.bench / "corners" / RID
        self.assertTrue((corners / "units_check.log").is_file())
        self.assertTrue(any(corners.glob("mos_*_noise.csv")))
        scratch = list(self.t.tmp.iterdir())
        self.assertEqual(len(scratch), 1)
        self.assertEqual((scratch[0] / f"{RID}.env.json").read_text(), begin)

    def test_dut_solve_drift_refuses_finalization(self):
        path, text, needle = mutations(self.t)["OSDI manifest"]
        r = self.run_sweep(MUTATE_FILE=str(path), MUTATE_TEXT=text)
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("DRIFTED", r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertEqual(self.record_files(RID), [f"{RID}.csv.raw"])
        self.assertEqual(self.solver_calls(), 46)  # every point ran; publication is what was refused
        scratch = list(self.t.tmp.iterdir())
        self.assertEqual(len(scratch), 1)  # begin capture kept for inspection

    def test_rerun_after_refusal_finalizes_under_the_new_identity(self):
        path, text, _ = mutations(self.t)["used model include"]
        old = self.t.capture()
        self.assertEqual(self.run_sweep(MUTATE_FILE=str(path), MUTATE_TEXT=text).returncode, 4)
        rid2_files = self.record_files(RID)
        self.assertEqual(rid2_files, [f"{RID}.csv.raw"])  # the refusal left only inspection artifacts
        # A fresh id, run once the environment is stable again, finalizes
        # under the identity it actually started with -- and never touches
        # the refused run's artifacts.
        ts2 = "20260101-000100"
        rid2 = f"{ts2}-{SHA}"
        r = self.run_sweep(ts2)
        self.assertEqual(r.returncode, 0, r.stderr)
        side = (self.bench / "records" / f"{rid2}.env.json").read_text()
        self.assertEqual(side, self.t.capture(rid2))
        self.assertNotEqual(side, old)
        self.assertEqual(self.record_files(RID), rid2_files)


if __name__ == "__main__":
    unittest.main()

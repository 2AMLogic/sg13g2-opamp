"""Offline controls for the shared per-point log-field reader (issue #471).

Four sweep runners each read their bench's per-point measurement markers
(OP_*/TR_*/NOISE_*/AC_* lines) out of one ngspice log per grid point.
Before the shared reader, every field was its own `grep '^MARKER ' | awk
'{print $2}'` pipeline; under the runners' `set -euo pipefail` a marker
missing from ONE log exited the whole sweep before the per-point failure
branch could record the point and continue -- one degraded corner killed
all 45 cells of the grid.

sg13g2_read_log_fields (sim/preflight.sh) reads every field a bench needs
in a single scan of one log and reports missing values through its exit
status, so a missing marker reaches the runner's existing SIM FAILED
accounting. These controls pin that contract:

  * CommittedLogParity -- against the newest committed corners/<id>/
    evidence of each of the four benches, the reader returns exactly the
    values the old per-field grep|awk pipelines returned, byte for byte,
    for exactly the marker set each runner requests (parsed from the
    runner's own call site, so a marker added there is covered here
    without an edit), and returns success on complete logs;
  * a missing-marker copy control -- one marker deleted from a copy of a
    committed log flips the status to failure with that field empty and
    every other field intact;
  * MissingMarkerRegression -- the REAL sim/open-loop-ac/run_pvt_sweep.sh
    over a two-point grid (the fixture PDK declares 1 corner x 1 temp x 2
    supplies) whose FIRST point's stub-solver log is missing OP_VD1: the
    sweep must record exactly one simulation failure, process the complete
    second point, and finalize the record (exit 0). Before the shared
    reader this exited 1 mid-sweep with no record at all.

Everything runs offline against committed evidence and copies of it; no
PDK download, ngspice run or OSDI build is needed.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SIM_DIR = TOOLS_DIR.parent

# The throwaway-tree fixture, stub binaries and deterministic record-id
# constants are shared with the #209 lifecycle controls: same fake PDK
# install shape, same stub-solver conventions.
from test_env_drift_lifecycle import RID, SHA, STUB_NGSPICE, TS, Tree, _write_exec  # noqa: E402

PREFLIGHT = SIM_DIR / "preflight.sh"

# bench dir -> runner name. The log each reader call scans is taken from the
# call site itself ("${log}" vs "..._cmrr.log" / "..._psrr.log").
BENCHES = {

    "open-loop-ac": "run_pvt_sweep.sh",
    "slew-rate": "run_slew_sweep.sh",
    "input-noise": "run_noise_sweep.sh",
    "cmrr-psrr": "run_cmrr_psrr_sweep.sh",
}

# One reader call site: sg13g2_read_log_fields <map> <log> MARKER [MARKER...]
CALL_RE = re.compile(r"sg13g2_read_log_fields (\S+) (\S+) ([A-Z][A-Z0-9_ ]*)")
# One downstream field read: ${<map>[<MARKER>]}
READ_RE = re.compile(r"\$\{(\w+)\[([A-Z0-9_]+)\]\}")


def reader_calls(runner: Path) -> list[tuple[str, str, list[str]]]:
    """(map name, log suffix, markers) for every sg13g2_read_log_fields call
    a runner makes.

    The suffix maps the call's <log> expression onto the per-point evidence
    file: "${log}" is <point_id>.log, the cmrr-psrr bench's two calls name
    .../<point_id>_cmrr.log and .../<point_id>_psrr.log explicitly (the PSRR
    cross-check stays tied to its own log).
    """
    calls = []
    for line in runner.read_text(encoding="utf-8").splitlines():
        m = CALL_RE.search(line)
        if not m:
            continue
        log_expr = m.group(2).strip('"')
        if "_psrr.log" in log_expr:
            suffix = "_psrr.log"
        elif "_cmrr.log" in log_expr:
            suffix = "_cmrr.log"
        else:
            suffix = ".log"
        calls.append((m.group(1), suffix, m.group(3).split()))
    return calls


def grid_from_preflight() -> tuple[list[str], list[str], list[str]]:
    """The declared PVT grid (corners, temps, vdds) straight from the real
    sim/preflight.sh, so the per-point log names the parity check expects
    track the grid definition instead of restating it."""
    text = (SIM_DIR / "preflight.sh").read_text(encoding="utf-8")

    def arr(name: str) -> list[str]:
        m = re.search(rf"^{name}=\(([^)]*)\)$", text, re.M)
        assert m, f"preflight.sh no longer declares {name}"
        return m.group(1).split()

    return arr("SG13G2_MOS_CORNERS"), arr("SG13G2_TEMPS"), arr("SG13G2_VDDS")


def point_logs(record: Path, suffix: str) -> list[Path]:
    """Every per-point log of one record for one reader suffix, derived from
    the declared grid -- never the units-check deck or other non-per-point
    logs sharing the directory (the runners read only <point_id><suffix>)."""
    corners, temps, vdds = grid_from_preflight()
    logs = []
    for corner in corners:
        for temp in temps:
            for vdd in vdds:
                log = record / f"{corner}_{temp}C_{vdd}V{suffix}"
                assert log.is_file(), f"committed record {record.name} lacks {log.name}"
                logs.append(log)
    return logs


def newest_corners(bench: str) -> Path:
    """The newest committed corners/<id>/ record of a bench that actually
    holds raw per-point solver logs (record ids sort lexicographically
    chronological, the same rule sg13g2_latest_record_csv uses; a bench's
    newest corners dir can also be a klt-envelope record with no logs)."""
    records = sorted((SIM_DIR / bench / "corners").iterdir(), reverse=True)
    assert records, f"no committed corners record under sim/{bench}"
    for record in records:
        if any(p.name.endswith(".log") for p in record.iterdir()):
            return record
    raise AssertionError(f"no committed solver logs under sim/{bench}/corners")


def old_pipeline(log: Path, marker: str) -> str:
    """What `grep '^MARKER ' log | awk '{print $2}'` printed into a command
    substitution: every match's second whitespace field, newline-joined,
    trailing newline stripped."""
    vals = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.startswith(marker + " "):
            fields = line.split()
            vals.append(fields[1] if len(fields) > 1 else "")
    return "\n".join(vals)


# Sources the REAL fixture-tree preflight.sh (fake PDK install, stub
# build-osdi.sh, stub ngspice -- the OpenLoopRunner setup shape) and runs the
# real reader over a manifest of <log>\t<comma-separated markers> lines,
# emitting one block per line:
#   LOG <path>
#   STATUS <0|1>
#   FIELD <marker> <value>
# so every log is checked in one bash process instead of one per log.
DRIVER = r"""
set -euo pipefail
REPO="$1"
MANIFEST="$2"
SIM_DIR="${REPO}/sim"
REPO_ROOT="${REPO}"
export PDK PDK_ROOT
[[ "$(command -v ngspice || true)" == "${REPO}/bin/ngspice" ]] || {
  echo "read-fields.sh: expected stub ${REPO}/bin/ngspice first on PATH" >&2
  exit 3
}
# shellcheck source=/dev/null
source "${SIM_DIR}/preflight.sh"
declare -A fld
while IFS=$'\t' read -r log markers; do
  [[ -n "${log}" ]] || continue
  IFS=',' read -r -a marks <<< "${markers}"
  echo "LOG ${log}"
  if sg13g2_read_log_fields fld "${log}" "${marks[@]}"; then
    echo "STATUS 0"
  else
    echo "STATUS 1"
  fi
  for m in "${marks[@]}"; do
    printf 'FIELD %s %s\n' "${m}" "${fld[${m}]:-}"
  done
done < "${MANIFEST}"
"""


class ReaderFixture:
    """A throwaway tree whose sim/ can source the real preflight.sh offline."""

    def __init__(self, root: str):
        self.t = Tree(root)
        for name in ("preflight.sh", "env.sh", "record-paths.sh", "env-identity.sh", "ac-join.sh"):
            shutil.copy2(SIM_DIR / name, self.t.sim / name)
        _write_exec(self.t.sim / "tools" / "build-osdi.sh", "#!/usr/bin/env bash\nexit 0\n")
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE)
        self.driver = self.t.root / "read-fields.sh"
        self.driver.write_text(DRIVER, encoding="utf-8")

    def read(self, manifest_lines: list[str]) -> dict:
        """Run the reader over the manifest; {log: {'status': int,
        'fields': {marker: value}}}."""
        manifest = self.t.root / "manifest.tsv"
        manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        r = subprocess.run(["bash", str(self.driver), str(self.t.root), str(manifest)],
                           env=self.t.env(), capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        out: dict = {}
        log = None
        for line in r.stdout.splitlines():
            if line.startswith("LOG "):
                log = line[4:]
                out[log] = {"status": None, "fields": {}}
            elif line.startswith("STATUS ") and log is not None:
                out[log]["status"] = int(line[7:])
            elif line.startswith("FIELD ") and log is not None:
                _, marker, value = line.split(" ", 2)
                out[log]["fields"][marker] = value
        return out


class CommittedLogParity(unittest.TestCase):
    """Reader vs the old per-field pipelines, on committed evidence."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = ReaderFixture(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_every_bench_log_matches_the_old_pipelines_byte_for_byte(self):
        for bench, runner_name in BENCHES.items():
            with self.subTest(bench):
                calls = reader_calls(SIM_DIR / bench / runner_name)
                self.assertTrue(calls, f"{runner_name} has no reader call to check")
                by_suffix: dict[str, list[str]] = {}
                for _map, suffix, markers in calls:
                    self.assertGreater(len(markers), 0)
                    want = by_suffix.setdefault(suffix, [])
                    by_suffix[suffix] = want + [m for m in markers if m not in want]
                corners = newest_corners(bench)
                matched = [(log, suffix) for suffix in sorted(by_suffix)
                           for log in point_logs(corners, suffix)]
                self.assertGreater(len(matched), 0)
                manifest = [f"{log}\t{','.join(by_suffix[suffix])}"
                            for log, suffix in matched]
                got = self.fx.read(manifest)
                for log, suffix in matched:
                    block = got[str(log)]
                    self.assertEqual(block["status"], 0,
                                     f"{log}: complete committed log must pass")
                    for marker in by_suffix[suffix]:
                        with self.subTest(f"{bench}:{log.name}:{marker}"):
                            self.assertEqual(block["fields"][marker],
                                             old_pipeline(log, marker))


    def test_python_oracle_is_the_real_grep_awk(self):
        # The parity oracle above is a Python re-implementation; pin it to
        # the actual pipeline it stands in for, on one log per bench.
        for bench, runner_name in BENCHES.items():
            with self.subTest(bench):
                suffix = reader_calls(SIM_DIR / bench / runner_name)[0][1]
                log = point_logs(newest_corners(bench), suffix)[0]
                for marker in ("OP_VOUT", "OP_IVDD"):
                    pipe = subprocess.run(
                        ["bash", "-c",
                         f"grep '^{marker} ' \"$1\" | awk '{{print $2}}'",
                         "oracle", str(log)],
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(pipe.returncode, 0)
                    self.assertEqual(pipe.stdout.rstrip("\n"), old_pipeline(log, marker))

    def test_every_map_read_is_a_requested_marker_and_vice_versa(self):
        # The extraction lines after each reader call read ${map[MARKER]};
        # under the runners' set -u a key no call requested would crash the
        # sweep as an unbound variable, and a requested-but-never-read
        # marker is a stale call. Both directions, for all four runners.
        for bench, runner_name in BENCHES.items():
            with self.subTest(bench):
                text = (SIM_DIR / bench / runner_name).read_text(encoding="utf-8")
                requested: dict[str, set[str]] = {}
                for map_name, _suffix, markers in reader_calls(SIM_DIR / bench / runner_name):
                    requested.setdefault(map_name, set()).update(markers)
                self.assertTrue(requested)
                read: dict[str, set[str]] = {}
                for m in READ_RE.finditer(text):
                    if m.group(1) not in requested:
                        continue  # e.g. ${BASH_SOURCE[0]} boilerplate
                    read.setdefault(m.group(1), set()).add(m.group(2))
                self.assertEqual(read, requested)


class MissingMarkerControl(unittest.TestCase):
    """One deleted marker: failure status, that field empty, others intact."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = ReaderFixture(self._tmp.name)
        self.log = Path(self._tmp.name) / "broken-copy.log"
        self.after = Path(self._tmp.name) / "broken-after-complete.log"
        src = point_logs(newest_corners("open-loop-ac"), ".log")[0]
        lines = "".join(l for l in src.read_text(encoding="utf-8").splitlines(True)
                        if not l.startswith("OP_VD1 "))
        self.log.write_text(lines, encoding="utf-8")
        self.after.write_text(lines, encoding="utf-8")
        self.complete = src

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_deleted_marker_fails_and_names_only_that_field(self):
        markers = ["OP_VOUT", "OP_VD1", "OP_VD2", "OP_VTAIL", "OP_VIBIAS", "OP_IVDD"]
        got = self.fx.read([f"{self.log}\t{','.join(markers)}",
                            f"{self.complete}\t{','.join(markers)}",
                            f"{self.after}\t{','.join(markers)}"])
        for broken in (got[str(self.log)], got[str(self.after)]):
            self.assertEqual(broken["status"], 1)
            self.assertEqual(broken["fields"]["OP_VD1"], "")
            for marker in ("OP_VOUT", "OP_VD2", "OP_VTAIL", "OP_VIBIAS", "OP_IVDD"):
                self.assertEqual(broken["fields"][marker], old_pipeline(self.complete, marker))
        self.assertEqual(got[str(self.complete)]["status"], 0)


# The stub solver: the #209 lifecycle shape (markers from the rendered deck's
# own Vdd line, a wrdata AC csv), except the 1.08 V point's log omits OP_VD1
# -- the degraded corner whose markers must not kill the sweep (issue #471).
STUB_NGSPICE_ONE_GAP = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
ac_csv="$(awk '/^wrdata /{print $2}' "${netlist}")"
half="$(awk -v v="${vdd}" 'BEGIN{print v/2}')"
printf '1 60 1 -10\n1e6 20 1e6 -100\n1e9 -20 1e9 -170\n' > "${ac_csv}"
echo "OP_VOUT ${half}"
if [[ "${vdd}" != "1.08" ]]; then echo "OP_VD1 ${half}"; fi
echo "OP_VD2 ${half}"
echo "OP_VTAIL ${half}"
echo "OP_VIBIAS ${half}"
echo "OP_IVDD 2e-05"
exit 0
"""


def shrink_grid(preflight: Path) -> None:
    """Declare a two-point PVT grid in the FIXTURE's preflight copy: the
    runner's sweep logic is untouched (it still copies SG13G2_* verbatim);
    only the fake PDK's declared grid shrinks, so the regression is exactly
    one degraded point followed by one complete point."""
    text = preflight.read_text(encoding="utf-8")
    for old, new in (
        ("SG13G2_MOS_CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)", "SG13G2_MOS_CORNERS=(mos_tt)"),
        ("SG13G2_TEMPS=(-40 27 125)", "SG13G2_TEMPS=(27)"),
        ("SG13G2_VDDS=(1.08 1.20 1.32)", "SG13G2_VDDS=(1.08 1.20)"),
    ):
        assert text.count(old) == 1, f"fixture preflight no longer declares: {old}"
        text = text.replace(old, new)
    preflight.write_text(text, encoding="utf-8")


class MissingMarkerRegression(unittest.TestCase):
    """The real open-loop sweep over one degraded point + one complete point."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        for name in ("preflight.sh", "env.sh", "record-paths.sh", "env-identity.sh", "ac-join.sh"):
            shutil.copy2(SIM_DIR / name, self.t.sim / name)
        _write_exec(self.t.sim / "tools" / "build-osdi.sh", "#!/usr/bin/env bash\nexit 0\n")
        shutil.copy2(TOOLS_DIR / "op_sanity.py", self.t.sim / "tools" / "op_sanity.py")
        shrink_grid(self.t.sim / "preflight.sh")
        self.bench = self.t.sim / "open-loop-ac"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "open-loop-ac" / "run_pvt_sweep.sh", self.bench / "run_pvt_sweep.sh")
        shutil.copy2(SIM_DIR / "open-loop-ac" / "testbench" / "tb_openloop_ac.spice.tmpl",
                     self.bench / "testbench" / "tb_openloop_ac.spice.tmpl")
        (self.t.root / "design" / "netlist").mkdir(parents=True)
        (self.t.root / "design" / "netlist" / "opamp_core.spice").write_text("* stub DUT\n", encoding="utf-8")
        shutil.copy2(TOOLS_DIR / "csv_summary.py", self.t.sim / "tools" / "csv_summary.py")
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE_ONE_GAP)
        for name, text in (("date", '#!/usr/bin/env bash\necho "${FAKE_TS}"\n'),
                           ("git", '#!/usr/bin/env bash\necho "${FAKE_SHA}"\n')):
            _write_exec(self.t.bin / name, text)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_sweep(self) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.bench / "run_pvt_sweep.sh")],
                              env=self.t.env(FAKE_TS=TS, FAKE_SHA=SHA),
                              capture_output=True, text=True, timeout=300)

    def test_degraded_point_recorded_and_complete_point_processed(self):
        r = self.run_sweep()
        self.assertEqual(r.returncode, 0, r.stderr)
        # Exactly one simulation failure, named on stderr with the log.
        self.assertIn("SIM FAILED mos_tt_27C_1.08V -- missing OP_* line(s)", r.stderr)
        self.assertEqual(r.stderr.count("SIM FAILED"), 1)
        # The degraded point's raw log stays as evidence; the complete point
        # is the only CSV row.
        corners = self.bench / "corners" / RID
        self.assertTrue((corners / "mos_tt_27C_1.08V.log").is_file())
        self.assertTrue((corners / "mos_tt_27C_1.08V_ac.csv").is_file())
        csv = (self.bench / "records" / f"{RID}.csv").read_text(encoding="utf-8")
        lines = csv.splitlines()
        self.assertEqual(len(lines), 2)  # header + the complete point
        self.assertEqual(lines[1].split(",")[0], "mos_tt_27C_1.20V")
        # Field order and exact values: the DC columns still carry each
        # marker's own value, in the header's order, exactly as the old
        # per-field pipelines wrote them (stub: every node = VDD/2).
        cells = lines[1].split(",")
        for col, value in (("vout_dc_v", "0.6"), ("vd1_dc_v", "0.6"),
                           ("vd2_dc_v", "0.6"), ("vtail_dc_v", "0.6"),
                           ("vibias_dc_v", "0.6"), ("ivdd_total_a", "2e-05")):
            idx = lines[0].split(",").index(col)
            self.assertEqual(cells[idx], value, col)
        # The failure accounting the sweep reports at the end.
        sanity = (corners / "sanity_checks.txt").read_text(encoding="utf-8")
        self.assertIn("sim_fail_count,1 (mos_tt_27C_1.08V)", sanity)
        self.assertIn("op_pass_count,1 of 2", sanity)
        md = (self.bench / "records" / f"{RID}.md").read_text(encoding="utf-8")
        md_flat = " ".join(md.split())  # the heredoc wraps prose lines
        self.assertIn("1 simulation failure(s) (mos_tt_27C_1.08V)", md_flat)


# The stub solver for the slew bench: the same marker convention, plus a
# synthetic v(out) waveform slew_post.py can actually measure -- park at the
# low rail until T2, ramp rail-to-rail over [T2, T3], ramp back over
# [T3, TSTOP] -- with the antiphase drive's own echo markers (inn excursion
# 2*VSTEP_V centred on the DC bias). The 1.08 V point omits OP_VD1.
STUB_NGSPICE_SLEW_GAP = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
tran_csv="$(awk '/^wrdata /{print $2}' "${netlist}")"
half="$(awk -v v="${vdd}" 'BEGIN{print v/2}')"
awk -v vdd="${vdd}" 'BEGIN{
  t2=300e-9; t3=550e-9; tstop=800e-9
  for (i = 0; i <= 800; i++) {
    t = i * 1e-9
    if (t <= t2) v = 0
    else if (t <= t3) v = vdd * (t - t2) / (t3 - t2)
    else v = vdd * (1 - (t - t3) / (tstop - t3))
    printf "%.12g %.12g\n", t, v
  }
}' > "${tran_csv}"
echo "OP_VOUT ${half}"
if [[ "${vdd}" != "1.08" ]]; then echo "OP_VD1 ${half}"; fi
echo "OP_VD2 ${half}"
echo "OP_VTAIL ${half}"
echo "OP_VIBIAS ${half}"
echo "OP_IVDD 2e-05"
echo "TR_VINN_MAX $(awk -v h="${half}" 'BEGIN{print h+0.3}')"
echo "TR_VINN_MIN $(awk -v h="${half}" 'BEGIN{print h-0.3}')"
exit 0
"""

# Minimal stand-in for testbench/tb_slew.spice.tmpl: the runner renders it
# (its extra @@VP_*@@/@@T*@@ edits are no-ops on a template without them)
# and the stub solver reads the two lines below.
SLEW_TMPL = """\
* stub slew testbench (offline log-field-reader regression)
Vdd vdd 0 dc @@VDD_V@@
wrdata @@TRAN_CSV@@ v(out)
"""


class MissingMarkerSlewRegression(unittest.TestCase):
    """The real slew sweep over one degraded point + one complete point."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        for name in ("preflight.sh", "env.sh", "record-paths.sh", "env-identity.sh", "ac-join.sh"):
            shutil.copy2(SIM_DIR / name, self.t.sim / name)
        _write_exec(self.t.sim / "tools" / "build-osdi.sh", "#!/usr/bin/env bash\nexit 0\n")
        shutil.copy2(TOOLS_DIR / "op_sanity.py", self.t.sim / "tools" / "op_sanity.py")
        shrink_grid(self.t.sim / "preflight.sh")
        self.bench = self.t.sim / "slew-rate"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "slew-rate" / "run_slew_sweep.sh", self.bench / "run_slew_sweep.sh")
        shutil.copy2(SIM_DIR / "slew-rate" / "slew_post.py", self.bench / "slew_post.py")
        (self.bench / "testbench" / "tb_slew.spice.tmpl").write_text(SLEW_TMPL, encoding="utf-8")
        (self.t.root / "design" / "netlist").mkdir(parents=True)
        (self.t.root / "design" / "netlist" / "opamp_core.spice").write_text("* stub DUT\n", encoding="utf-8")
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE_SLEW_GAP)
        for name, text in (("date", '#!/usr/bin/env bash\necho "${FAKE_TS}"\n'),
                           ("git", '#!/usr/bin/env bash\necho "${FAKE_SHA}"\n')):
            _write_exec(self.t.bin / name, text)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_sweep(self) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.bench / "run_slew_sweep.sh")],
                              env=self.t.env(FAKE_TS=TS, FAKE_SHA=SHA),
                              capture_output=True, text=True, timeout=300)

    def test_degraded_point_recorded_and_complete_point_processed(self):
        r = self.run_sweep()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SIM FAILED mos_tt_27C_1.08V -- missing OP_*/TR_* line(s)", r.stderr)
        self.assertEqual(r.stderr.count("SIM FAILED"), 1)
        corners = self.bench / "corners" / RID
        self.assertTrue((corners / "mos_tt_27C_1.08V.log").is_file())
        self.assertTrue((corners / "mos_tt_27C_1.08V_tran.csv").is_file())
        csv = (self.bench / "records" / f"{RID}.csv").read_text(encoding="utf-8")
        lines = csv.splitlines()
        self.assertEqual(len(lines), 2)  # header + the complete point
        self.assertEqual(lines[1].split(",")[0], "mos_tt_27C_1.20V")
        sanity = (corners / "sanity_checks.txt").read_text(encoding="utf-8")
        self.assertIn("sim_fail_count,1 (mos_tt_27C_1.08V)", sanity)
        self.assertIn("op_pass_count,1 of 2", sanity)


if __name__ == "__main__":
    unittest.main()

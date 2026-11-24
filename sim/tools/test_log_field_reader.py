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

  * CommittedLogParity -- against the pinned complete committed corners/<id>/
    and records/<id>.csv evidence of each of the four benches, the reader
    returns the exact values the old per-field grep|awk pipelines returned
    and the committed CSV columns recorded, for an independently specified
    (log_suffix, marker -> csv_column) contract per bench;
  * MissingMarkerControl -- one marker deleted from a copy of a committed
    log (both before and after a complete read into the same associative
    array) flips the status to failure with that field empty and every
    other field intact;
  * End-to-end sweep regressions across all four runners (open-loop-ac,
    slew-rate, input-noise, cmrr-psrr) with pairwise-distinct marker values
    and distinct CMRR vs PSRR logs: missing markers record SIM FAILED per
    point without aborting the sweep, every marker lands in its own CSV
    column, and the PSRR cross-check fails if CMRR and PSRR inputs are
    equated or interchanged.

Everything runs offline against committed evidence and copies of it; no
PDK download, ngspice run or OSDI build is needed.
"""
import csv
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
import env_identity as ei  # noqa: E402
from test_env_drift_lifecycle import (  # noqa: E402
    NGSPICE,
    PDK,
    PIN,
    RID,
    SHA,
    STUB_NGSPICE,
    TS,
    Tree,
    _write_exec,
)

OP_MARKERS = ("OP_VOUT", "OP_VD1", "OP_VD2", "OP_VTAIL", "OP_VIBIAS", "OP_IVDD")
DC_CSV_COLUMNS = (
    ("vout_dc_v", "OP_VOUT"),
    ("vd1_dc_v", "OP_VD1"),
    ("vd2_dc_v", "OP_VD2"),
    ("vtail_dc_v", "OP_VTAIL"),
    ("vibias_dc_v", "OP_VIBIAS"),
    ("ivdd_total_a", "OP_IVDD"),
)

# Independently specified per-bench contract and pinned complete committed
# evidence record: never derived solely from the runner under test, and
# never selected by scanning corners/ for the newest directory (which an
# incomplete local sweep would shadow).
BENCH_SPECS = {
    "open-loop-ac": {
        "runner": "run_pvt_sweep.sh",
        "record_id": "20260910-221601-22feaba",
        "calls": [(".log", OP_MARKERS)],
        "csv_columns": [(".log", col, mark) for col, mark in DC_CSV_COLUMNS],
    },
    "slew-rate": {
        "runner": "run_slew_sweep.sh",
        "record_id": "20260918-210216-90844d2",
        "calls": [(".log", OP_MARKERS + ("TR_VINN_MAX", "TR_VINN_MIN"))],
        "csv_columns": [(".log", col, mark) for col, mark in DC_CSV_COLUMNS],
    },
    "input-noise": {
        "runner": "run_noise_sweep.sh",
        "record_id": "20260918-203850-90844d2",
        "calls": [(".log", OP_MARKERS + ("NOISE_INOISE_TOTAL", "AC_CLGAIN_100HZ", "AC_CLGAIN_1MHZ"))],
        "csv_columns": [(".log", col, mark) for col, mark in DC_CSV_COLUMNS] + [
            (".log", "clgain_100hz", "AC_CLGAIN_100HZ"),
            (".log", "clgain_1mhz", "AC_CLGAIN_1MHZ"),
            (".log", "vni_int_vrms", "NOISE_INOISE_TOTAL"),
        ],
    },
    "cmrr-psrr": {
        "runner": "run_cmrr_psrr_sweep.sh",
        "record_id": "20260921-151815-707b34c",
        "calls": [("_cmrr.log", OP_MARKERS), ("_psrr.log", ("OP_VOUT",))],
        "csv_columns": [("_cmrr.log", col, mark) for col, mark in DC_CSV_COLUMNS],
    },
}

# Distinct DC operating-point values at VDD=1.20 V (from committed
# mos_ff_-40C_1.20V.log; op_sane == 1 at VDD=1.20, Vcm=0.60) so swapping
# any two marker assignments in a runner fails its CSV column check.
DISTINCT_1P20_DC = (
    ("vout_dc_v", "OP_VOUT", "0.587154"),
    ("vd1_dc_v", "OP_VD1", "0.667411"),
    ("vd2_dc_v", "OP_VD2", "0.492996"),
    ("vtail_dc_v", "OP_VTAIL", "0.16793"),
    ("vibias_dc_v", "OP_VIBIAS", "0.368739"),
    ("ivdd_total_a", "OP_IVDD", "0.000115032"),
)

# Distinct DC operating-point values at VDD=1.32 V (from committed
# mos_ff_-40C_1.32V.log; op_sane == 1 at VDD=1.32, Vcm=0.66) for CMRR/PSRR.
DISTINCT_1P32_CMRR_DC = (
    ("vout_dc_v", "OP_VOUT", "0.648044"),
    ("vd1_dc_v", "OP_VD1", "0.78222"),
    ("vd2_dc_v", "OP_VD2", "0.60983"),
    ("vtail_dc_v", "OP_VTAIL", "0.224565"),
    ("vibias_dc_v", "OP_VIBIAS", "0.368739"),
    ("ivdd_total_a", "OP_IVDD", "0.000118012"),
)

# One reader call site: sg13g2_read_log_fields <map> <log> MARKER [MARKER...]
CALL_RE = re.compile(r"sg13g2_read_log_fields (\S+) (\S+) ([A-Z][A-Z0-9_ ]*)")
# One downstream field read: ${<map>[<MARKER>]}
READ_RE = re.compile(r"\$\{(\w+)\[([A-Z0-9_]+)\]\}")


def reader_calls(runner: Path) -> list[tuple[str, str, list[str]]]:
    """(map name, log suffix, markers) for every sg13g2_read_log_fields call
    a runner makes."""
    calls = []
    for line in runner.read_text(encoding="utf-8").splitlines():
        m = CALL_RE.search(line)
        if not m:
            continue
        log_expr = m.group(2).strip('"')
        if log_expr.endswith("_psrr.log"):
            suffix = "_psrr.log"
        elif log_expr.endswith("_cmrr.log"):
            suffix = "_cmrr.log"
        elif log_expr == "${log}" or log_expr.endswith(".log"):
            suffix = ".log"
        else:
            raise AssertionError(f"unrecognized log expression in {runner}: {log_expr}")
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


def pinned_corners(bench: str, sim_dir: Path = SIM_DIR) -> Path:
    """The pinned complete committed corners/<id>/ record of <bench>.

    Pinned directly by committed record ID rather than scanning corners/ for
    the newest directory, so an incomplete or failed local sweep under
    corners/ never shadows the known-complete parity fixture.
    """
    record = sim_dir / bench / "corners" / BENCH_SPECS[bench]["record_id"]
    assert record.is_dir(), f"missing pinned corners record: {record}"
    return record


def pinned_record_csv(bench: str, sim_dir: Path = SIM_DIR) -> Path:
    """The pinned committed records/<id>.csv matching pinned_corners(bench)."""
    csv_path = sim_dir / bench / "records" / f"{BENCH_SPECS[bench]['record_id']}.csv"
    assert csv_path.is_file(), f"missing pinned CSV record: {csv_path}"
    return csv_path


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
    """Reader vs the old per-field pipelines and committed CSVs, against
    independently specified bench contracts and pinned complete records."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = ReaderFixture(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_every_bench_log_matches_the_old_pipelines_byte_for_byte(self):
        for bench, spec in BENCH_SPECS.items():
            with self.subTest(bench):
                corners = pinned_corners(bench)
                matched = [(log, suffix, markers)
                           for suffix, markers in spec["calls"]
                           for log in point_logs(corners, suffix)]
                self.assertGreater(len(matched), 0)
                manifest = [f"{log}\t{','.join(markers)}"
                            for log, _suffix, markers in matched]
                got = self.fx.read(manifest)
                for log, _suffix, markers in matched:
                    block = got[str(log)]
                    self.assertEqual(block["status"], 0,
                                     f"{log}: complete committed log must pass")
                    for marker in markers:
                        with self.subTest(f"{bench}:{log.name}:{marker}"):
                            self.assertEqual(block["fields"][marker],
                                             old_pipeline(log, marker))

                # Sanity on the fixture itself: mos_ff_-40C_1.08V carries
                # pairwise-distinct DC voltages (e.g. VD1=0.5544 vs
                # VD2=0.376318), and every row of the pinned committed CSV
                # matches each marker's independently expected column.
                ff_suffix = spec["calls"][0][0]
                ff_fields = got[str(corners / f"mos_ff_-40C_1.08V{ff_suffix}")]["fields"]
                self.assertEqual(ff_fields["OP_VD1"], "0.5544")
                self.assertEqual(ff_fields["OP_VD2"], "0.376318")
                self.assertEqual(len({ff_fields[m] for m in OP_MARKERS}), len(OP_MARKERS))

                with pinned_record_csv(bench).open(newline="", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                self.assertEqual(len(rows), 45)
                for row in rows:
                    pid = row["point_id"]
                    for suffix, col, marker in spec["csv_columns"]:
                        log_path = str(corners / f"{pid}{suffix}")
                        self.assertEqual(
                            row[col],
                            got[log_path]["fields"][marker],
                            f"{bench} {pid} column {col} != {suffix}:{marker}",
                        )

    def test_python_oracle_is_the_real_grep_awk(self):
        # The parity oracle above is a Python re-implementation; pin it to
        # the actual pipeline it stands in for, on mos_ff_-40C_1.08V per bench.
        for bench, spec in BENCH_SPECS.items():
            with self.subTest(bench):
                suffix = spec["calls"][0][0]
                log = pinned_corners(bench) / f"mos_ff_-40C_1.08V{suffix}"
                for marker in ("OP_VOUT", "OP_VD1", "OP_VD2", "OP_IVDD"):
                    pipe = subprocess.run(
                        ["bash", "-c",
                         f"grep '^{marker} ' \"$1\" | awk '{{print $2}}'",
                         "oracle", str(log)],
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(pipe.returncode, 0)
                    self.assertEqual(pipe.stdout.rstrip("\n"), old_pipeline(log, marker))

    def test_runner_calls_and_map_reads_match_independent_spec(self):
        # Each runner's reader calls must match the independently specified
        # (log_suffix, markers) list -- so changing cmrr-psrr's PSRR read to
        # open _cmrr.log or dropping a marker fails immediately -- and each
        # call in a multi-log runner must populate its own associative array.
        for bench, spec in BENCH_SPECS.items():
            with self.subTest(bench):
                runner = SIM_DIR / bench / spec["runner"]
                calls = reader_calls(runner)
                self.assertEqual(
                    [(suffix, tuple(markers)) for _map, suffix, markers in calls],
                    spec["calls"],
                )
                self.assertEqual(
                    len({map_name for map_name, _s, _m in calls}),
                    len(calls),
                    f"{bench}: each reader call must use a distinct map",
                )
                text = runner.read_text(encoding="utf-8")
                requested = {map_name: set(markers) for map_name, _s, markers in calls}
                read: dict[str, set[str]] = {}
                for m in READ_RE.finditer(text):
                    if m.group(1) not in requested:
                        continue
                    read.setdefault(m.group(1), set()).add(m.group(2))
                self.assertEqual(read, requested)

    def test_pinned_corners_ignores_newer_incomplete_local_record(self):
        # Regression for Finding 2: if a newer corners/<id>/ directory exists
        # with a missing marker (e.g. from a local sweep), pinned_corners
        # still selects the pinned complete committed record and parity passes.
        fake_sim = Path(self._tmp.name) / "fake_sim"
        src = pinned_corners("open-loop-ac")
        pinned_dst = fake_sim / "open-loop-ac" / "corners" / src.name
        newer_dst = fake_sim / "open-loop-ac" / "corners" / "99999999-999999-fffffff"
        shutil.copytree(src, pinned_dst)
        shutil.copytree(src, newer_dst)
        degraded = newer_dst / "mos_ff_-40C_1.08V.log"
        degraded.write_text(
            "".join(
                line for line in degraded.read_text(encoding="utf-8").splitlines(True)
                if not line.startswith("OP_VD1 ")
            ),
            encoding="utf-8",
        )
        selected = pinned_corners("open-loop-ac", sim_dir=fake_sim)
        self.assertEqual(selected, pinned_dst)
        manifest = [f"{log}\t{','.join(OP_MARKERS)}"
                    for log in point_logs(selected, ".log")]
        got = self.fx.read(manifest)
        for log in point_logs(selected, ".log"):
            self.assertEqual(got[str(log)]["status"], 0)


class MissingMarkerControl(unittest.TestCase):
    """One deleted marker: failure status, that field empty, others intact."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = ReaderFixture(self._tmp.name)
        self.log = Path(self._tmp.name) / "broken-copy.log"
        self.after = Path(self._tmp.name) / "broken-after-complete.log"
        src = pinned_corners("open-loop-ac") / "mos_ff_-40C_1.08V.log"
        lines = "".join(l for l in src.read_text(encoding="utf-8").splitlines(True)
                        if not l.startswith("OP_VD1 "))
        self.log.write_text(lines, encoding="utf-8")
        self.after.write_text(lines, encoding="utf-8")
        self.complete = src

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_deleted_marker_fails_and_names_only_that_field(self):
        markers = list(OP_MARKERS)
        got = self.fx.read([f"{self.log}\t{','.join(markers)}",
                            f"{self.complete}\t{','.join(markers)}",
                            f"{self.after}\t{','.join(markers)}"])
        for broken in (got[str(self.log)], got[str(self.after)]):
            self.assertEqual(broken["status"], 1)
            self.assertEqual(broken["fields"]["OP_VD1"], "")
            for marker in ("OP_VOUT", "OP_VD2", "OP_VTAIL", "OP_VIBIAS", "OP_IVDD"):
                self.assertEqual(broken["fields"][marker], old_pipeline(self.complete, marker))
        self.assertEqual(got[str(self.complete)]["status"], 0)


def shrink_grid(preflight: Path, vdds: str = "1.08 1.20") -> None:
    """Declare a compact PVT grid in the FIXTURE's preflight copy: the
    runner's sweep logic is untouched (it still copies SG13G2_* verbatim);
    only the fake PDK's declared grid shrinks."""
    text = preflight.read_text(encoding="utf-8")
    for old, new in (
        ("SG13G2_MOS_CORNERS=(mos_tt mos_ss mos_ff mos_sf mos_fs)", "SG13G2_MOS_CORNERS=(mos_tt)"),
        ("SG13G2_TEMPS=(-40 27 125)", "SG13G2_TEMPS=(27)"),
        ("SG13G2_VDDS=(1.08 1.20 1.32)", f"SG13G2_VDDS=({vdds})"),
    ):
        assert text.count(old) == 1, f"fixture preflight no longer declares: {old}"
        text = text.replace(old, new)
    preflight.write_text(text, encoding="utf-8")


def setup_runner_tree(root: str, vdds: str = "1.08 1.20") -> Tree:
    """Shared throwaway repo setup for running a real sweep script offline."""
    t = Tree(root)
    for name in ("preflight.sh", "env.sh", "record-paths.sh", "env-identity.sh", "ac-join.sh"):
        shutil.copy2(SIM_DIR / name, t.sim / name)
    _write_exec(t.sim / "tools" / "build-osdi.sh", "#!/usr/bin/env bash\nexit 0\n")
    for tool in ("op_sanity.py", "csv_summary.py", "ac_join_admission.py"):
        shutil.copy2(TOOLS_DIR / tool, t.sim / "tools" / tool)
    shrink_grid(t.sim / "preflight.sh", vdds=vdds)
    (t.root / "design" / "netlist").mkdir(parents=True)
    (t.root / "design" / "netlist" / "opamp_core.spice").write_text("* stub DUT\n", encoding="utf-8")
    for name, text in (("date", '#!/usr/bin/env bash\necho "${FAKE_TS}"\n'),
                       ("git", '#!/usr/bin/env bash\necho "${FAKE_SHA}"\n')):
        _write_exec(t.bin / name, text)
    return t


# Open-loop stub solver: 1.08 V omits OP_VD1; 1.20 V emits pairwise-distinct
# OP_* values so swapping any two assignments in run_pvt_sweep.sh fails.
STUB_NGSPICE_ONE_GAP = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
ac_csv="$(awk '/^wrdata /{print $2}' "${netlist}")"
printf '1 60 1 -10\n1e6 20 1e6 -100\n1e9 -20 1e9 -170\n' > "${ac_csv}"
echo "OP_VOUT 0.587154"
if [[ "${vdd}" != "1.08" ]]; then echo "OP_VD1 0.667411"; fi
echo "OP_VD2 0.492996"
echo "OP_VTAIL 0.16793"
echo "OP_VIBIAS 0.368739"
echo "OP_IVDD 0.000115032"
exit 0
"""


class MissingMarkerRegression(unittest.TestCase):
    """The real open-loop sweep over one degraded point + one complete point."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = setup_runner_tree(self._tmp.name)
        self.bench = self.t.sim / "open-loop-ac"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "open-loop-ac" / "run_pvt_sweep.sh", self.bench / "run_pvt_sweep.sh")
        shutil.copy2(SIM_DIR / "open-loop-ac" / "testbench" / "tb_openloop_ac.spice.tmpl",
                     self.bench / "testbench" / "tb_openloop_ac.spice.tmpl")
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE_ONE_GAP)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_sweep(self) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.bench / "run_pvt_sweep.sh")],
                              env=self.t.env(FAKE_TS=TS, FAKE_SHA=SHA),
                              capture_output=True, text=True, timeout=300)

    def test_degraded_point_recorded_and_complete_point_processed(self):
        r = self.run_sweep()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SIM FAILED mos_tt_27C_1.08V -- missing OP_* line(s)", r.stderr)
        self.assertEqual(r.stderr.count("SIM FAILED"), 1)
        corners = self.bench / "corners" / RID
        self.assertTrue((corners / "mos_tt_27C_1.08V.log").is_file())
        self.assertTrue((corners / "mos_tt_27C_1.08V_ac.csv").is_file())
        with (self.bench / "records" / f"{RID}.csv").open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["point_id"], "mos_tt_27C_1.20V")
        self.assertEqual(row["op_pass"], "1")
        for col, _marker, want in DISTINCT_1P20_DC:
            self.assertEqual(row[col], want, col)
        sanity = (corners / "sanity_checks.txt").read_text(encoding="utf-8")
        self.assertIn("sim_fail_count,1 (mos_tt_27C_1.08V)", sanity)
        self.assertIn("op_pass_count,1 of 2", sanity)
        md = (self.bench / "records" / f"{RID}.md").read_text(encoding="utf-8")
        md_flat = " ".join(md.split())
        self.assertIn("1 simulation failure(s) (mos_tt_27C_1.08V)", md_flat)


# Slew stub solver: 1.08 V omits OP_VD1; 1.20 V emits pairwise-distinct OP_*
# and TR_VINN_{MAX,MIN} centred on OP_VOUT=0.587154 (+/- 0.3 V), so swapping
# any two DC columns or swapping TR_VINN_MAX/MIN fails.
STUB_NGSPICE_SLEW_GAP = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
tran_csv="$(awk '/^wrdata /{print $2}' "${netlist}")"
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
echo "OP_VOUT 0.587154"
if [[ "${vdd}" != "1.08" ]]; then echo "OP_VD1 0.667411"; fi
echo "OP_VD2 0.492996"
echo "OP_VTAIL 0.16793"
echo "OP_VIBIAS 0.368739"
echo "OP_IVDD 0.000115032"
echo "TR_VINN_MAX 0.887154"
echo "TR_VINN_MIN 0.287154"
exit 0
"""

SLEW_TMPL = """\
* stub slew testbench (offline log-field-reader regression)
Vdd vdd 0 dc @@VDD_V@@
wrdata @@TRAN_CSV@@ v(out)
"""


class MissingMarkerSlewRegression(unittest.TestCase):
    """The real slew sweep over one degraded point + one complete point."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = setup_runner_tree(self._tmp.name)
        self.bench = self.t.sim / "slew-rate"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "slew-rate" / "run_slew_sweep.sh", self.bench / "run_slew_sweep.sh")
        shutil.copy2(SIM_DIR / "slew-rate" / "slew_post.py", self.bench / "slew_post.py")
        (self.bench / "testbench" / "tb_slew.spice.tmpl").write_text(SLEW_TMPL, encoding="utf-8")
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE_SLEW_GAP)

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
        with (self.bench / "records" / f"{RID}.csv").open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["point_id"], "mos_tt_27C_1.20V")
        self.assertEqual(row["op_pass"], "1")
        self.assertEqual(row["drive_pass"], "1")
        for col, _marker, want in DISTINCT_1P20_DC:
            self.assertEqual(row[col], want, col)
        sanity = (corners / "sanity_checks.txt").read_text(encoding="utf-8")
        self.assertIn("sim_fail_count,1 (mos_tt_27C_1.08V)", sanity)
        self.assertIn("op_pass_count,1 of 2", sanity)


# Input-noise stub solver: answers the units check, omits OP_VD1 at 1.08 V,
# and emits 9 pairwise-distinct marker values at 1.20 V (including distinct
# AC_CLGAIN_100HZ vs AC_CLGAIN_1MHZ).
STUB_NGSPICE_NOISE_GAP = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
if [[ "${netlist}" == *tb_noise_units_check* ]]; then
  echo "UNITS_INOISE_SPECTRUM 4.0704e-09"
  echo "UNITS_ONOISE_SPECTRUM 4.0704e-07"
  echo "UNITS_INOISE_TOTAL 3.86146e-07"
  exit 0
fi
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
noise_csv="$(awk '/^wrdata /{print $2; exit}' "${netlist}")"
awk 'BEGIN{for(i=0;i<81;i++){f=100*10^(i/20); printf "%.12g %g %.12g %g\n", f, 1e-6, f, 1e-6}}' > "${noise_csv}"
echo "OP_VOUT 0.587154"
if [[ "${vdd}" != "1.08" ]]; then echo "OP_VD1 0.667411"; fi
echo "OP_VD2 0.492996"
echo "OP_VTAIL 0.16793"
echo "OP_VIBIAS 0.368739"
echo "OP_IVDD 0.000115032"
echo "NOISE_INOISE_TOTAL 9.9995e-04"
echo "AC_CLGAIN_100HZ 0.981212"
echo "AC_CLGAIN_1MHZ 0.981094"
exit 0
"""

NOISE_TMPL = """\
* stub noise testbench (offline log-field-reader regression)
Vdd vdd 0 dc @@VDD_V@@
wrdata @@NOISE_CSV@@ inoise_spectrum onoise_spectrum
wrdata @@NOISE_WIDE_CSV@@ inoise_spectrum onoise_spectrum
"""


class MissingMarkerNoiseRegression(unittest.TestCase):
    """The real input-noise sweep over one degraded point + one complete point."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = setup_runner_tree(self._tmp.name)
        self.bench = self.t.sim / "input-noise"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "input-noise" / "run_noise_sweep.sh", self.bench / "run_noise_sweep.sh")
        shutil.copy2(SIM_DIR / "input-noise" / "noise_post.py", self.bench / "noise_post.py")
        (self.bench / "testbench" / "tb_noise.spice.tmpl").write_text(NOISE_TMPL, encoding="utf-8")
        (self.bench / "testbench" / "tb_noise_units_check.spice").write_text(
            "* stub units-check deck\n", encoding="utf-8"
        )
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE_NOISE_GAP)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_sweep(self) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.bench / "run_noise_sweep.sh")],
                              env=self.t.env(FAKE_TS=TS, FAKE_SHA=SHA),
                              capture_output=True, text=True, timeout=300)

    def test_degraded_point_recorded_and_complete_point_processed(self):
        r = self.run_sweep()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SIM FAILED mos_tt_27C_1.08V -- missing OP_*/NOISE_*/AC_* line(s)", r.stderr)
        self.assertEqual(r.stderr.count("SIM FAILED"), 1)
        corners = self.bench / "corners" / RID
        self.assertTrue((corners / "mos_tt_27C_1.08V.log").is_file())
        with (self.bench / "records" / f"{RID}.csv").open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["point_id"], "mos_tt_27C_1.20V")
        self.assertEqual(row["op_pass"], "1")
        for col, _marker, want in DISTINCT_1P20_DC:
            self.assertEqual(row[col], want, col)
        self.assertEqual(row["clgain_100hz"], "0.981212")
        self.assertEqual(row["clgain_1mhz"], "0.981094")
        self.assertEqual(row["vni_int_vrms"], "9.9995e-04")
        sanity = (corners / "sanity_checks.txt").read_text(encoding="utf-8")
        self.assertIn("sim_fail_count,1 (mos_tt_27C_1.08V)", sanity)
        self.assertIn("op_pass_count,1 of 2", sanity)


# CMRR/PSRR stub solver over {1.08, 1.20, 1.32} V:
#   - 1.08 V: _cmrr.log omits OP_VD1 (_psrr.log is complete) -> SIM FAILED
#   - 1.20 V: _psrr.log omits OP_VOUT (_cmrr.log is complete) -> SIM FAILED
#             (fails to trigger if PSRR mistakenly reads _cmrr.log)
#   - 1.32 V: both complete, with pairwise-distinct CMRR OP_* values AND
#             completely different PSRR OP_* values (OP_VOUT delta = 0.0125 V),
#             so equating OR interchanging _cmrr.log and _psrr.log fails.
STUB_NGSPICE_CMRR_PSRR = "#!/usr/bin/env bash\n" + r"""
if [[ "$1" == "-v" ]]; then
  printf '******\n** ngspice-46 : Circuit level simulation program (stub)\n'
  exit 0
fi
[[ "$1" == "-b" ]] || exit 2
netlist="$2"
vdd="$(awk '/^Vdd /{print $5}' "${netlist}")"
ac_csv="$(awk '/^wrdata /{print $2}' "${netlist}")"
if [[ "${netlist}" == *_cmrr.spice ]]; then
  printf '0.01 -10 0.01 0\n0.1 -10 0.1 0\n1000 -12 1000 0\n' > "${ac_csv}"
  echo "OP_VOUT 0.648044"
  if [[ "${vdd}" != "1.08" ]]; then echo "OP_VD1 0.78222"; fi
  echo "OP_VD2 0.60983"
  echo "OP_VTAIL 0.224565"
  echo "OP_VIBIAS 0.368739"
  echo "OP_IVDD 0.000118012"
else
  printf '0.01 20 0.01 0\n0.1 20 0.1 0\n1000 25 1000 0\n' > "${ac_csv}"
  if [[ "${vdd}" != "1.20" ]]; then echo "OP_VOUT 0.635544"; fi
  echo "OP_VD1 0.700001"
  echo "OP_VD2 0.500002"
  echo "OP_VTAIL 0.200003"
  echo "OP_VIBIAS 0.300004"
  echo "OP_IVDD 0.000199999"
fi
exit 0
"""


class MissingMarkerCmrrPsrrRegression(unittest.TestCase):
    """The real CMRR/PSRR sweep over CMRR-gap, PSRR-gap, and complete points."""

    AC_SID = "20251231-235959-aaaaaaa"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = setup_runner_tree(self._tmp.name, vdds="1.08 1.20 1.32")
        # Admissible 3-point open-loop-ac source record for sg13g2_ac_join_admit:
        # vout_dc_v matches _cmrr.log's 0.648044 at 1.32 V (not _psrr.log's
        # 0.635544), so interchanging CMRR and PSRR also trips ol_vout_delta_v.
        ol = self.t.sim / "open-loop-ac"
        ol_rec = ol / "records"
        ol_snap = ol / "netlist-snapshots" / self.AC_SID
        ol_rec.mkdir(parents=True)
        ol_snap.mkdir(parents=True)
        (ol_snap / "opamp_core.spice").write_text("* stub DUT\n", encoding="utf-8")
        ol_rows = ["point_id,corner,temp_c,vdd_v,vcm_v,op_pass,vout_dc_v,av0_db"]
        for vdd, vcm, vout in (("1.08", "0.54", "0.54"),
                               ("1.20", "0.6", "0.6"),
                               ("1.32", "0.66", "0.648044")):
            pid = f"mos_tt_27C_{vdd}V"
            ol_rows.append(f"{pid},mos_tt,27,{vdd},{vcm},1,{vout},43.0")
            (ol_snap / f"{pid}.spice").write_text("* x\nCload out vss 2e-12\n.end\n",
                                                  encoding="utf-8")
        (ol_rec / f"{self.AC_SID}.csv").write_text("\n".join(ol_rows) + "\n", encoding="utf-8")
        sidecar = ei.capture(self.t.pdk_root, PDK, PIN, self.AC_SID, NGSPICE)
        (ol_rec / f"{self.AC_SID}.env.json").write_text(ei.canonical_json(sidecar),
                                                        encoding="utf-8")

        self.bench = self.t.sim / "cmrr-psrr"
        (self.bench / "testbench").mkdir(parents=True)
        shutil.copy2(SIM_DIR / "cmrr-psrr" / "run_cmrr_psrr_sweep.sh",
                     self.bench / "run_cmrr_psrr_sweep.sh")
        for harness in ("cmrr", "psrr"):
            shutil.copy2(SIM_DIR / "cmrr-psrr" / "testbench" / f"tb_{harness}.spice.tmpl",
                         self.bench / "testbench" / f"tb_{harness}.spice.tmpl")
        _write_exec(self.t.bin / "ngspice", STUB_NGSPICE_CMRR_PSRR)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_sweep(self) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.bench / "run_cmrr_psrr_sweep.sh")],
                              env=self.t.env(FAKE_TS=TS, FAKE_SHA=SHA),
                              capture_output=True, text=True, timeout=300)

    def test_cmrr_and_psrr_logs_checked_independently_and_columns_verified(self):
        r = self.run_sweep()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SIM FAILED mos_tt_27C_1.08V -- missing OP_* line(s)", r.stderr)
        self.assertIn("SIM FAILED mos_tt_27C_1.20V -- missing OP_* line(s)", r.stderr)
        self.assertEqual(r.stderr.count("SIM FAILED"), 2)
        with (self.bench / "records" / f"{RID}.csv").open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["point_id"], "mos_tt_27C_1.32V")
        self.assertEqual(row["op_pass"], "1")
        for col, _marker, want in DISTINCT_1P32_CMRR_DC:
            self.assertEqual(row[col], want, col)
        # PSRR cross-check reads _psrr.log's OP_VOUT (0.635544), not _cmrr.log's
        # (0.648044): |0.648044 - 0.635544| = 0.0125 V, while ol_vout_delta_v is 0.
        self.assertEqual(row["op_xcheck_psrr_delta_v"], "0.0125")
        self.assertEqual(row["ol_vout_delta_v"], "0")
        self.assertEqual(row["cmrr_db"], "53")
        self.assertEqual(row["psrr_db"], "23")
        corners = self.bench / "corners" / RID
        sanity = (corners / "sanity_checks.txt").read_text(encoding="utf-8")
        self.assertIn("sim_fail_count,2 (mos_tt_27C_1.08V mos_tt_27C_1.20V)", sanity)
        self.assertIn("op_pass_count,1 of 3", sanity)
        self.assertIn("psrr_xcheck_failures (>1e-3 V),1 (mos_tt_27C_1.32V)", sanity)
        self.assertIn("ol_vout_xcheck_failures (>1e-3 V),0 (none)", sanity)


if __name__ == "__main__":
    unittest.main()

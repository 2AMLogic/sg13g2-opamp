"""Check the typical-corner gm/ID and fT trends on the sweep's declared grid."""

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


def typical_points(csv_path):
    groups = defaultdict(list)
    with csv_path.open(newline="") as src:
        for row in csv.DictReader(src):
            if row["corner"] != "mos_tt":
                continue
            overdrive = float(row["overdrive_v"] or "nan")
            if math.isfinite(overdrive):
                groups[row["device"], row["length_um"]].append(
                    (
                        overdrive,
                        float(row["gm_id_per_v"] or "nan"),
                        float(row["ft_hz"] or "nan"),
                    )
                )
    return groups


def check_gmid(points, device, length):
    group = f"device={device} length={length} corner=mos_tt"
    ordered = sorted(points, key=lambda p: p[0])
    gmids = [gmid for _, gmid, _ in ordered if math.isfinite(gmid)]
    if not gmids:
        return False, f"gm/ID has no usable overdrive samples: {group}"

    # Leakage can depress gm/ID in deep subthreshold (see README). Only the
    # region from the observed peak toward stronger inversion tests this trend.
    peak_idx = gmids.index(max(gmids))
    tail = gmids[peak_idx:]
    if len(tail) < 2:
        return False, f"gm/ID has no overdrive sample after its observed peak: {group}"

    violations = sum(b > a + 1e-3 for a, b in zip(tail, tail[1:]))
    return violations == 0, (
        f"gm/ID monotonically decreasing vs overdrive from its observed peak "
        f"(index {peak_idx}/{len(gmids) - 1}, peak={tail[0]:.3f}): {group} "
        f"(violations={violations}/{len(tail) - 1})"
    )


def check_ft(groups, device, lengths):
    peaks = []
    for length in lengths:
        peak = max(
            (
                ft
                for ov, _, ft in groups[device, length]
                if 0.25 <= ov <= 0.35 and math.isfinite(ft)
            ),
            default=None,
        )
        if peak is None:
            yield (
                False,
                (
                    "fT has no usable sample in the 0.25-0.35 V overdrive window: "
                    f"device={device} length={length} corner=mos_tt"
                ),
            )
        else:
            peaks.append(peak)

    if len(peaks) == len(lengths):
        decreasing = len(peaks) >= 2 and all(a >= b for a, b in zip(peaks, peaks[1:]))
        peak_values = [f"{value:.3e}" for value in peaks]
        yield (
            decreasing,
            (
                "fT falls off with increasing length near overdrive~0.3V: "
                f"device={device} lengths={lengths} fT={peak_values}"
            ),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("log", type=Path)
    parser.add_argument("--devices", nargs="+", required=True)
    parser.add_argument("--lengths", nargs="+", required=True)
    args = parser.parse_args()

    groups = typical_points(args.csv_path)
    lengths = sorted(args.lengths, key=lambda length: float(length.rstrip("u")))
    verdicts = [
        check_gmid(groups[device, length], device, length)
        for device in args.devices
        for length in lengths
    ]
    for device in args.devices:
        verdicts.extend(check_ft(groups, device, lengths))

    report = "".join(
        f"{'PASS' if ok else 'FAIL'} {message}\n" for ok, message in verdicts
    )
    args.log.write_text(report)
    print(report, end="")
    return 0 if all(ok for ok, _ in verdicts) else 1


if __name__ == "__main__":
    raise SystemExit(main())

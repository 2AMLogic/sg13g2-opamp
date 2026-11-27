"""Shared scratch netlists for the offline Rz tests."""

import os
import tempfile


def make_scratch(case, extracted, schematic):
    directory = tempfile.TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    dut = os.path.join(directory.name, "pex.spice")
    sch = os.path.join(directory.name, "opamp_core.spice")
    with open(dut, "w") as f:
        f.write(extracted)
    with open(sch, "w") as f:
        f.write(schematic)

    key = "SG13G2_PEX_POINTS"
    previous = os.environ.pop(key, None)
    if previous is None:
        case.addCleanup(os.environ.pop, key, None)
    else:
        case.addCleanup(os.environ.__setitem__, key, previous)
    return directory.name, dut, sch

"""Replay a halved AC excitation on scratch copies of the direct-deck evidence."""
import hashlib
import json
import math


def halve_stimulus(root, envelope, source):
    doc = json.loads(envelope.read_bytes())
    rel = doc["netlist"]["path"]
    body = root / rel
    lines = body.read_text().splitlines(keepends=True)
    index, = (i for i, line in enumerate(lines) if line.split()[:1] == [source])
    assert lines[index].endswith(" ac 1\n")
    lines[index] = lines[index].replace(" ac 1\n", " ac 0.5\n")
    body.write_text("".join(lines))

    digest = hashlib.sha256(body.read_bytes()).hexdigest()
    env = doc["environment"]
    next(e for e in env["netlist_closure"] if e["path"] == rel)["sha256"] = digest
    env["netlist_sha256"] = digest
    doc["provenance"]["input"]["content_hash"] = "sha256:" + digest

    # In a linear AC solve the driven output moves by 20 log10(0.5) dB.
    # Recompute the in-deck subtraction, leaving the plateau delta intact.
    delta = 20 * math.log10(0.5)
    for corner in doc["corners"]:
        m = {item["name"]: item for item in corner["measurements"]}
        operand, rejection = ("avs0_db", "psrr_db") if "psrr_db" in m else ("acm0_db", "cmrr_db")
        m["av0_db" if source == "Vinp" else operand]["value"] += delta
        result = m[rejection]
        value = m["av0_db"]["value"] - m[operand]["value"]
        if result["margin"] is not None:
            result["margin"] += value - result["value"]
        result["value"] = value
    envelope.write_text(json.dumps(doc))

"""The six shared-module `sys.path` hops, in exactly one place.

Split out of generate.py (issue #355), where these hops sat at the top of a
2,972-line module and so coupled every import in the file to all six. Each
sibling that needs a shared module imports it from here instead.

These are the SAME modules the benches themselves run -- not copies of their
logic -- so the generator re-derives each published cell with the bench's own
post-processing. The hops stay unconditional, as they were: a full report
needs all six.

Load-order note: the six hops insert at position 0, i.e. AHEAD of this
directory, so a same-named module added to one of them later (a `sim/tools/
common.py`, `records.py`, `rows.py`, ...) would shadow a sibling of this
package. `HERE` is therefore re-inserted at 0 after them, which makes this
directory win regardless. No such collision exists today.

Stdlib only; the `sys.path` edits these imports need are its only effect.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = HERE.parent.parent
# Shared sidecar contract/helper (issue #191); pure functions, stdlib only.
sys.path.insert(0, str(DEFAULT_REPO_ROOT / "sim" / "tools"))
import env_identity  # noqa: E402
# Shared draws-population contract (issue #141); pure functions, stdlib only.
sys.path.insert(0, str(DEFAULT_REPO_ROOT / "signoff" / "yield-inputs"))
import offset_draws_to_sampleset as draws_contract  # noqa: E402
# Shared CMRR sample parser + statistics (issue #174 / #208); stdlib only.
sys.path.insert(0, str(DEFAULT_REPO_ROOT / "sim" / "cmrr-mismatch"))
import mc_samples  # noqa: E402
# Shared noise post-processing (issue #213): the SAME module run_noise_sweep.sh runs.
sys.path.insert(0, str(DEFAULT_REPO_ROOT / "sim" / "input-noise"))
import noise_post  # noqa: E402
# Shared slew post-processing (issue #227): the SAME module run_slew_sweep.sh runs.
sys.path.insert(0, str(DEFAULT_REPO_ROOT / "sim" / "slew-rate"))
import slew_post  # noqa: E402
# Shared output-swing post-processing (issue #230): the SAME module run_swing_sweep.sh runs.
sys.path.insert(0, str(DEFAULT_REPO_ROOT / "sim" / "output-swing"))
import swing_post  # noqa: E402

# The six hops above each insert at position 0, ahead of this directory. Put
# this package back in front of them so no shared directory can shadow a
# sibling module (common.py, defchecks.py, records.py, render.py, rows.py,
# selection.py) by gaining a file of the same name later.
sys.path.insert(0, str(HERE))

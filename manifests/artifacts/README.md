# manifests/artifacts/

One `<bench>-<run-id>.manifest.json` (plus a `.md` summary) per stored run,
written by `sim/tools/store_evidence.py`. Committed files here are append-only:
never edit or replace one; mint a new run id. Format and flow:
[`../README.md`](../README.md).

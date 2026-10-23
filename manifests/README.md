# manifests/ — pointers to run output kept outside git

Run output (raw ngspice logs, waveforms, corner dumps) is bytes, and bytes in
git are permanent weight. For **new** runs the bytes go to the fleet artifact
store through its broker; git keeps a **manifest** naming each object by
sha256 plus a Markdown summary. Existing evidence under `sim/` stays exactly
where it is (append-only; `sim/tools/check_append_only_evidence.py` is
unchanged) — this is manifest-forward, with no history rewrite.

## Flow

1. Run a bench as usual. Its raw outputs land in a scratch location.
2. Store them (needs `$KLT_ARTIFACT_BROKER` and a `klt` with `artifact put`):

   ```bash
   python3 sim/tools/store_evidence.py --bench <bench> --run-id <run-id> <path> [<path> ...]
   ```

   Directories are walked recursively. Files are staged in the git-ignored
   `sim/.evidence-scratch/`, uploaded with `klt artifact put`, and the scratch
   copy is removed.
3. Commit the two files it wrote:
   - `manifests/artifacts/<bench>-<run-id>.manifest.json` — klt's manifest
     (`schema_version` 1; per object: `sha256`, `size`, `kind`, `producer`,
     `uri` = `artifact:<key>`, `name`);
   - `manifests/artifacts/<bench>-<run-id>.md` — name, size, sha256 per object.
4. Anyone with broker access can check or fetch:

   ```bash
   klt artifact verify manifests/artifacts/<bench>-<run-id>.manifest.json
   klt artifact get ...        # see `klt artifact get --help`
   ```

## Rules

- **Fail closed.** Broker unset, `klt` without `artifact put`, an unreachable
  broker, an empty run or an empty file: the writer exits nonzero and writes
  nothing to a tracked path. There is no fallback that commits the bytes.
  (The store cannot hold zero-byte objects; leave an empty file out.)
- **Append-only.** A manifest name that already exists is refused; a re-run
  needs a new `--run-id`.
- **No storage location in the repo.** `uri` is the logical `artifact:<key>`;
  no bucket URL, bucket name, ARN or broker URL ever appears under
  `manifests/` (the checker rejects the `s3` URL scheme and AWS ARNs). The broker URL comes only from `$KLT_ARTIFACT_BROKER`.
- **Not in git as well.** A file tracked in git whose sha256 matches a stored
  object fails the check.

## Check

```bash
python3 -I scripts/check_artifact_manifests.py
```

Offline and stdlib-only: validates manifest schema, `artifact:` URIs, the
no-leak rule and the not-also-in-git rule. It runs in `pnpm test` and in
`.github/workflows/signoff.yml`. It does not contact the store;
`klt artifact verify` does, and needs the broker.

## klt version

`artifact` verbs arrived in klayout-tools `7e3561f`. `signoff/klt-pin.txt`
(`44cc423…`) predates it (checked against the klayout-tools history) and is
deliberately not bumped by this: only the writer and
`klt artifact verify` use the verbs, not the re-grade.

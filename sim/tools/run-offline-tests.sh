#!/usr/bin/env bash
# Run every offline test_*.py under the given roots, one `unittest discover`
# per directory holding a test (bench dirs have hyphens and are not packages,
# so a single top-level discover cannot import them). New tests are picked up
# with no workflow edit. Stdlib + bash only; no klt, ngspice or PDK.
#
# Usage: sim/tools/run-offline-tests.sh <root> [<root> ...]   (from repo root)
#
# Fail-closed: enumeration runs to a temp file first under pipefail (a find
# failure aborts before any test runs; a process substitution would swallow
# it), and an empty selection fails.
set -euo pipefail

[ "$#" -gt 0 ] || { echo "usage: $0 <root> [<root> ...]" >&2; exit 2; }

list="$(mktemp)"
trap 'rm -f "${list}"' EXIT
for root in "$@"; do
  [ -d "${root}" ] || { echo "no such test root: ${root}" >&2; exit 2; }
  find "${root}" -type f -name 'test_*.py' -printf '%h\n' | sort -u > "${list}.root"
  [ -s "${list}.root" ] || { echo "no ${root}/ test dirs found" >&2; rm -f "${list}.root"; exit 1; }
  cat "${list}.root" >> "${list}"
  rm -f "${list}.root"
done

n=0
while IFS= read -r d; do
  echo "== unittest: ${d}"
  python3 -m unittest discover -s "${d}" -p 'test_*.py' -v
  n=$((n + 1))
done < "${list}"
[ "${n}" -gt 0 ] || { echo "no test dirs run" >&2; exit 1; }
echo "== ${n} test dir(s) passed"

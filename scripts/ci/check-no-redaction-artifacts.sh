#!/usr/bin/env bash
# Fail if a redaction placeholder reached source. A '***REMOVED***' token in code
# is never intentional: it replaces real values and breaks the parse (task 87).
# Usage: scripts/ci/check-no-redaction-artifacts.sh [dir]   (default: repo root)
set -euo pipefail
ROOT="${1:-$(git rev-parse --show-toplevel)}"
hits=$(grep -rIn --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.cde-test \
  --exclude-dir=.nava-cde --exclude-dir=marketing --exclude-dir=docs \
  --exclude=check-no-redaction-artifacts.sh --exclude='*.lock' \
  -e '\*\*\*REMOVED\*\*\*' "$ROOT" || true)
if [ -n "$hits" ]; then
  echo "REDACTION ARTIFACT(S) FOUND:" >&2
  echo "$hits" | head -20 >&2
  exit 1
fi
# Every Python module must still parse.
bad=0
while IFS= read -r f; do
  python3 -m py_compile "$f" 2>/dev/null || { echo "does not parse: $f" >&2; bad=1; }
done < <(git -C "$ROOT" ls-files 'backend/**/*.py' 'scripts/**/*.py' 2>/dev/null | sed "s#^#$ROOT/#")
[ "$bad" = 0 ] && echo "no redaction artifacts; python modules parse"
exit "$bad"

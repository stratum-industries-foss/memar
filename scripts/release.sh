#!/usr/bin/env bash
# Bump VERSION + BUILD_ID, commit, tag, push to origin + GitHub.
# Usage: ./scripts/release.sh 1.1.0
# Does NOT push to GitHub unless MEMAR_GITHUB_REMOTE is set and PUBLIC=1.
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>  (e.g. 1.1.0)" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Validate version format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "ERROR: version must be X.Y.Z" >&2
  exit 1
fi

echo "==> Bumping to v${VERSION}"
echo "$VERSION" > VERSION
date -u +"%Y%m%d%H%M%S" > BUILD_ID

git add VERSION BUILD_ID
git commit -m "chore(release): v${VERSION}"
git tag -a "v${VERSION}" -m "v${VERSION}"

echo "==> Pushing to origin"
git push origin main
git push origin "v${VERSION}"

if [[ "${PUBLIC:-0}" == "1" && -n "${MEMAR_GITHUB_REMOTE:-}" ]]; then
  echo "==> Pushing to GitHub (${MEMAR_GITHUB_REMOTE})"
  git push "$MEMAR_GITHUB_REMOTE" main
  git push "$MEMAR_GITHUB_REMOTE" "v${VERSION}"
else
  echo "    (Skipping GitHub push — set PUBLIC=1 and MEMAR_GITHUB_REMOTE to push)"
fi

echo "==> Released v${VERSION}"

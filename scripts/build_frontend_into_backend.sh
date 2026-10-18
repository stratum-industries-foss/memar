#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
TARGET_DIR="$REPO_ROOT/frontend_dist"

if [ -f "$TARGET_DIR/index.html" ] && [ "${FARMDASH_REBUILD_FRONTEND:-0}" != "1" ]; then
  echo "[OK] using packaged frontend at $TARGET_DIR"
  exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found and no packaged frontend is available"
  exit 1
fi

cd "$FRONTEND_DIR"
# The lockfile is resolved with legacy peer deps (same as the Dockerfile).
if [ -f package-lock.json ]; then
  npm ci --legacy-peer-deps --no-audit --no-fund
else
  npm install --legacy-peer-deps --no-audit --no-fund
fi
npm run build
# vite.config sets outDir to ../frontend_dist; older configs wrote to dist/.
if [ -f dist/index.html ]; then
  rm -rf "$TARGET_DIR"; mkdir -p "$TARGET_DIR"; cp -a dist/. "$TARGET_DIR/"
fi
[ -f "$TARGET_DIR/index.html" ] || { echo "frontend build produced no index.html"; exit 1; }

echo "[OK] built frontend into $TARGET_DIR"

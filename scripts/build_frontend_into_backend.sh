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
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
npm run build
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -a dist/. "$TARGET_DIR/"

echo "[OK] built frontend into $TARGET_DIR"

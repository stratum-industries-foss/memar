#!/usr/bin/env bash
# Roll back to a previous release tag.
# Usage: ./scripts/rollback.sh v1.0.0
# Restarts memar and verifies health.
set -euo pipefail

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
  echo "Usage: $0 <tag>  (e.g. v1.0.0)" >&2
  echo "Available tags:"
  git tag --sort=-creatordate | head -10
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEALTH_URL="${MEMAR_HEALTH_URL:-http://localhost:9000/api/healthz}"
TIMEOUT=60

echo "==> Rolling back to ${TAG}"
git checkout "$TAG"

echo "==> Restarting memar service"
sudo systemctl restart memar

echo "==> Polling ${HEALTH_URL} (up to ${TIMEOUT}s)"
END=$((SECONDS + TIMEOUT))
until curl -sf "$HEALTH_URL" > /dev/null 2>&1; do
  if [[ $SECONDS -ge $END ]]; then
    echo "ERROR: health check timed out after ${TIMEOUT}s" >&2
    sudo journalctl -u memar -n 50 --no-pager >&2
    exit 1
  fi
  sleep 2
done

echo "==> Running on ${TAG} and healthy"

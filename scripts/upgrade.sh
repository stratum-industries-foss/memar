#!/usr/bin/env bash
# Pull latest code, run migrations, restart memar, poll health.
# Run as root or a user with sudo systemctl privileges.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEALTH_URL="${MEMAR_HEALTH_URL:-http://localhost:9000/api/healthz}"
TIMEOUT=60

echo "==> Pulling latest code"
git pull --ff-only

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

echo "==> MEMAR is healthy"
curl -s "$HEALTH_URL" | python3 -m json.tool || true

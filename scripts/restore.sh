#!/usr/bin/env bash
# Restore a MEMAR SQLite DB from a backup file.
# Usage: ./scripts/restore.sh /var/lib/memar/backups/memar_20260701_030000.db.gz
# Stops memar, replaces DB, restarts, verifies health.
set -euo pipefail

BACKUP_FILE="${1:-}"
if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: $0 <backup.db.gz>" >&2
  echo "Available backups:"
  ls -lh "${MEMAR_BACKUP_DIR:-/var/lib/memar/backups}/memar_"*.db.gz 2>/dev/null || echo "  (none found)"
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file not found: ${BACKUP_FILE}" >&2
  exit 1
fi

DB_PATH="${MEMAR_DB_PATH:-/opt/memar/current/data/memar.db}"
HEALTH_URL="${MEMAR_HEALTH_URL:-http://localhost:9000/api/healthz}"
TIMEOUT=60

echo "==> Stopping memar"
sudo systemctl stop memar

echo "==> Saving current DB as ${DB_PATH}.pre-restore"
cp "$DB_PATH" "${DB_PATH}.pre-restore" 2>/dev/null || true

echo "==> Restoring from ${BACKUP_FILE}"
if [[ "$BACKUP_FILE" == *.gz ]]; then
  gunzip -c "$BACKUP_FILE" > "$DB_PATH"
else
  cp "$BACKUP_FILE" "$DB_PATH"
fi

echo "==> Starting memar"
sudo systemctl start memar

echo "==> Polling ${HEALTH_URL} (up to ${TIMEOUT}s)"
END=$((SECONDS + TIMEOUT))
until curl -sf "$HEALTH_URL" > /dev/null 2>&1; do
  if [[ $SECONDS -ge $END ]]; then
    echo "ERROR: health check failed; reverting DB" >&2
    sudo systemctl stop memar
    cp "${DB_PATH}.pre-restore" "$DB_PATH"
    sudo systemctl start memar
    exit 1
  fi
  sleep 2
done

echo "==> Restore complete and healthy"

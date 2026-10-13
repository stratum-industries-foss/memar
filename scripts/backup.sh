#!/usr/bin/env bash
# Back up the MEMAR SQLite DB to a local archive directory.
# Usage: ./scripts/backup.sh [/path/to/backup/dir]
# Intended to be run via cron: 0 3 * * * /opt/memar/current/scripts/backup.sh
set -euo pipefail

DB_PATH="${MEMAR_DB_PATH:-/opt/memar/current/data/memar.db}"
BACKUP_DIR="${1:-/var/lib/memar/backups}"
KEEP_DAYS="${MEMAR_BACKUP_KEEP_DAYS:-30}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "ERROR: DB not found at ${DB_PATH}" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

STAMP="$(date -u +"%Y%m%d_%H%M%S")"
OUT="${BACKUP_DIR}/memar_${STAMP}.db"
GZ="${OUT}.gz"

echo "==> Backing up ${DB_PATH} → ${GZ}"
# sqlite3 .backup is atomic (uses the SQLite backup API; safe under active writes)
sqlite3 "$DB_PATH" ".backup '${OUT}'"
gzip -9 "$OUT"

echo "==> Pruning backups older than ${KEEP_DAYS} days"
find "$BACKUP_DIR" -name "memar_*.db.gz" -mtime "+${KEEP_DAYS}" -delete

echo "==> Done: ${GZ}"
ls -lh "${BACKUP_DIR}/memar_"*.db.gz | tail -5

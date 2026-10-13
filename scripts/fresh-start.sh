#!/bin/bash
# Fresh start: kill old servers, clean database, start fresh

set -e

PORT=${PORT:-8765}
PASSWORD=${MEMAR_ADMIN_PASSWORD:-testpass123}
DB_PATH="${MEMAR_DB_PATH:-.memar.db}"

echo "🔥 Killing old servers..."
pkill -9 -f "uvicorn backend.app.main" 2>/dev/null || true
sleep 1

echo "🗑️  Cleaning database..."
rm -f "$DB_PATH" "$DB_PATH-shm" "$DB_PATH-wal"

echo "🚀 Starting fresh MEMAR server on port $PORT..."
export MEMAR_ADMIN_PASSWORD="$PASSWORD"
export MEMAR_DB_PATH="$DB_PATH"

cd "$(dirname "$0")/.."
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
"$PY" -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$PORT" --log-level info 2>&1 &

sleep 8

if curl -s http://localhost:$PORT/api/healthz | grep -q "ok"; then
    echo "✅ Server ready on port $PORT"
    echo "Admin password: $PASSWORD"
    exit 0
else
    echo "❌ Server failed to start"
    exit 1
fi

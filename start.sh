#!/usr/bin/env bash
# MEMAR backend startup script
# Usage: ./start.sh [--port PORT] [--no-auth] [--reload]
set -euo pipefail

MEMAR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${MEMAR_PORT:-8099}"
NO_AUTH=0
RELOAD_FLAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --no-auth) NO_AUTH=1; shift ;;
        --reload) RELOAD_FLAG="--reload"; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Find a 64-bit libstdc++ on FHS systems
LIBSTDCXX=""
for candidate in \
    /usr/lib/libstdc++.so.6 \
    /usr/lib/x86_64-linux-gnu/libstdc++.so.6 \
    /usr/lib64/libstdc++.so.6
do
    # Skip 32-bit libs
    resolved="$(readlink -f "$candidate" 2>/dev/null || true)"
    if [[ -f "$resolved" ]] && file "$resolved" 2>/dev/null | grep -q "64-bit"; then
        LIBSTDCXX="$(dirname "$resolved")"
        break
    fi
done

if [[ -z "$LIBSTDCXX" ]]; then
    echo "WARNING: Could not locate 64-bit libstdc++.so.6 — greenlet may fail" >&2
fi

export PYTHONPATH="$MEMAR_ROOT/backend"
export MEMAR_DB_PATH="$MEMAR_ROOT/backend/memar.db"
[[ -n "$LIBSTDCXX" ]] && export LD_LIBRARY_PATH="$LIBSTDCXX${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
[[ "$NO_AUTH" -eq 1 ]] && export MEMAR_NO_AUTH=1

PYTHON="$MEMAR_ROOT/.venv/bin/python3"
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: .venv not found at $MEMAR_ROOT/.venv — run: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt" >&2
    exit 1
fi

echo "Starting MEMAR on http://127.0.0.1:$PORT (db: $MEMAR_DB_PATH)"
exec "$PYTHON" -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --log-level warning \
    $RELOAD_FLAG

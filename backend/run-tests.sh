#!/usr/bin/env bash
# Reproducible test runner for MEMAR backend.
#
# Runs the backend suite with ./.venv if present, else python3 on PATH. The old NixOS
# libstdc++ LD_LIBRARY_PATH workaround was removed: on FHS systems (and in the
# dev shell) greenlet finds libstdc++ normally.
#
# Usage: ./run-tests.sh [pytest args...]
#   ./run-tests.sh                      # full suite
#   ./run-tests.sh tests/test_billing.py -v
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$HERE/../.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$(command -v python3)"

export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"

exec "$VENV_PY" -m pytest "$@"

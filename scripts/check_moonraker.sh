#!/usr/bin/env bash
set -euo pipefail

echo '== Moonraker listening ports =='
ss -ltnp | egrep '712[0-9]|713[0-9]' || true

echo
echo '== Printer info =='
for p in 7125 7126 7127 7128 7129 7130 7131 7132 7133 7134 7135 7136; do
  r="$(curl -s --max-time 2 "http://127.0.0.1:$p/printer/info" || true)"
  [ -n "$r" ] || continue
  echo "=== port $p ==="
  echo "$r"
  echo
 done

#!/usr/bin/env bash
# Removes a native (systemd) MEMAR install.
#
#   sudo ./scripts/uninstall.sh            remove the service, releases and the memar command.
#                                          Keeps /var/lib/memar (data) and /etc/memar.env (secrets).
#   sudo ./scripts/uninstall.sh --purge    also remove /var/lib/memar, /etc/memar.env and the memar user.
#   sudo ./scripts/uninstall.sh --yes      do not prompt.
#
# Docker installs: docker compose down (add -v to delete the memar-data volume).
set -Eeuo pipefail

PURGE=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then exec sudo -- "$0" "$@"; fi
  echo "run as root: sudo $0" >&2
  exit 2
fi

UNIT=/etc/systemd/system/memar.service
removed=()
kept=()

if [ "$ASSUME_YES" = 0 ] && [ -t 0 ]; then
  echo "This removes the MEMAR service and /opt/memar$( [ "$PURGE" = 1 ] && echo ', /var/lib/memar and /etc/memar.env (data and secrets)' )."
  read -r -p "Continue? [y/N] " reply
  case "$reply" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 1 ;; esac
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now memar.service >/dev/null 2>&1 || true
  if [ -f "$UNIT" ]; then rm -f "$UNIT"; removed+=("$UNIT"); fi
  systemctl daemon-reload >/dev/null 2>&1 || true
fi

if [ -d /opt/memar ]; then rm -rf /opt/memar; removed+=("/opt/memar"); fi
if [ -f /usr/local/bin/memar ]; then rm -f /usr/local/bin/memar; removed+=("/usr/local/bin/memar"); fi

if [ "$PURGE" = 1 ]; then
  if [ -d /var/lib/memar ]; then rm -rf /var/lib/memar; removed+=("/var/lib/memar"); fi
  if [ -f /etc/memar.env ]; then rm -f /etc/memar.env; removed+=("/etc/memar.env"); fi
  if id memar >/dev/null 2>&1; then userdel memar >/dev/null 2>&1 && removed+=("user memar"); fi
else
  [ -d /var/lib/memar ] && kept+=("/var/lib/memar (data; add --purge to delete)")
  [ -f /etc/memar.env ] && kept+=("/etc/memar.env (secrets; add --purge to delete)")
fi

echo "Removed:"
if [ "${#removed[@]}" -eq 0 ]; then echo "  (nothing)"; fi
for r in "${removed[@]+"${removed[@]}"}"; do echo "  $r"; done
if [ "${#kept[@]}" -gt 0 ]; then
  echo "Kept:"
  for k in "${kept[@]}"; do echo "  $k"; done
fi
echo "[OK] MEMAR uninstalled"

#!/bin/sh
# MEMAR container entrypoint.
#
# Starts as root only to make the data directory writable (a bind mount such as
# -v ./memar-data:/app/data is created root-owned by Docker; volumes from older
# images belong to a different uid), then runs MEMAR as an unprivileged user.
#
# Optional: MEMAR_UID / MEMAR_GID to run as a specific host user (NAS setups).
# If the container is started with --user, nothing is changed.
set -eu

DATA="${MEMAR_DATA_DIR:-/app/data}"

if [ "$(id -u)" != "0" ]; then
  exec "$@"
fi

PUID="${MEMAR_UID:-10001}"
PGID="${MEMAR_GID:-10001}"
case "$PUID$PGID" in
  *[!0-9]*) echo "MEMAR: MEMAR_UID and MEMAR_GID must be numbers" >&2; exit 2 ;;
esac

if [ -L "$DATA" ]; then
  echo "MEMAR: refusing to start: data dir $DATA is a symlink (would chown/write through it). Mount the real directory instead." >&2
  exit 3
fi
mkdir -p "$DATA"
if [ "$(stat -c %u "$DATA")" != "$PUID" ] || [ "$(stat -c %g "$DATA")" != "$PGID" ]; then
  echo "MEMAR: giving uid $PUID ownership of $DATA"
  if ! chown -hR "$PUID:$PGID" "$DATA" 2>/dev/null; then
    echo "MEMAR: could not change the owner of $DATA (network share?)." >&2
    echo "MEMAR: set MEMAR_UID and MEMAR_GID to the folder's owner, or make it writable." >&2
  fi
fi

export HOME=/home/memar
exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --no-new-privs -- "$@"

#!/usr/bin/env bash
# Every file the image copies must be readable by the non-root runtime user
# (uid 10001). A 0600 file copied in from a private edit makes the app fail at
# import inside the container while the source tree still works (task 84 found this).
# Usage: scripts/ci/check-image-readable.sh <image>
set -euo pipefail
IMG="${1:?usage: check-image-readable.sh <image>}"
bad=$(docker run --rm --entrypoint sh "$IMG" -c \
  'find /app/backend /app/frontend_dist /app/scripts -type f ! -perm -004 2>/dev/null | head -20' || true)
if [ -n "$bad" ]; then
  echo "NOT READABLE BY uid 10001 in $IMG:" >&2
  echo "$bad" >&2
  exit 1
fi
echo "image readable by uid 10001: $IMG"

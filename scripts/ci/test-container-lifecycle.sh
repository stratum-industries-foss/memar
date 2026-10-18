#!/bin/sh
# Container lifecycle tests: (1) SIGTERM => clean, fast exit; (2) symlinks in the
# data dir are never followed by the root entrypoint.
# Usage: scripts/ci/test-container-lifecycle.sh <image-tag>
# To test local entrypoint edits without a rebuild, set ENTRYPOINT_OVERRIDE=<path>.
set -eu

IMAGE="${1:?usage: $0 <image-tag>}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/memar-lifecycle.XXXXXX")"
NAME="memar-lc-$$"
FAILS=0
CLEANUP_CONTAINERS="$NAME"

cleanup() {
  for c in $CLEANUP_CONTAINERS; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  docker run --rm -v "$WORK:/w" --entrypoint sh "$IMAGE" -c 'rm -rf /w/* /w/.[!.]*' >/dev/null 2>&1 || true
  rm -rf "$WORK" 2>/dev/null || true
}
trap cleanup EXIT

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }

EP_ARGS=""
if [ -n "${ENTRYPOINT_OVERRIDE:-}" ]; then
  EP_ARGS="-v $ENTRYPOINT_OVERRIDE:/usr/local/bin/docker-entrypoint:ro"
fi
ENVS="-e MEMAR_JWT_SECRET=lifecycle-test-secret-0123456789abcdef -e MEMAR_ADMIN_PASSWORD=lifecycle-test-pass-123"

wait_ready() { # container, seconds
  i=0
  while [ "$i" -lt "$2" ]; do
    ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1" 2>/dev/null || true)"
    if [ -n "$ip" ] && [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://$ip:8000/api/readyz" || true)" = "200" ]; then
      return 0
    fi
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ] || return 1
    sleep 1; i=$((i + 1))
  done
  return 1
}

# ---------- (1) SIGTERM / docker stop ----------
mkdir -p "$WORK/data1"
# shellcheck disable=SC2086
docker run -d --name "$NAME" $ENVS $EP_ARGS -v "$WORK/data1:/app/data" "$IMAGE" >/dev/null
if wait_ready "$NAME" 90; then
  pass "container became ready (/api/readyz 200)"
  t0="$(date +%s%3N)"
  docker stop -t 10 "$NAME" >/dev/null
  t1="$(date +%s%3N)"
  elapsed_ms=$((t1 - t0))
  elapsed="$((elapsed_ms / 1000)).$(printf %03d $((elapsed_ms % 1000)))"
  code="$(docker inspect -f '{{.State.ExitCode}}' "$NAME")"
  echo "stop took ${elapsed}s, exit code ${code}"
  if [ "$code" = "0" ]; then pass "clean exit code 0 after SIGTERM"; else fail "exit code $code (expected 0; 137 = SIGKILLed)"; fi
  if [ "$elapsed_ms" -lt 10000 ]; then pass "stopped in ${elapsed}s (< 10s, SIGTERM handled)"; else fail "stop took ${elapsed}s (SIGKILL timeout)"; fi
else
  fail "container never became ready"; docker logs --tail 30 "$NAME" 2>&1 | sed 's/^/  | /'
fi
docker rm -f "$NAME" >/dev/null 2>&1 || true

# ---------- (2) symlinks ----------
# Victim dir is mounted at /victim; owned by the invoking host user, content known.
mkdir -p "$WORK/victim" "$WORK/data2"
echo "precious" > "$WORK/victim/target.txt"
mkdir -p "$WORK/victim/dir"
chmod 0644 "$WORK/victim/target.txt"
before="$(stat -c '%u:%g:%a' "$WORK/victim/target.txt" "$WORK/victim/dir")"
sum_before="$(sha256sum "$WORK/victim/target.txt" | cut -d' ' -f1)"
# Symlinks planted INSIDE the data dir (host side, relative-free absolute targets).
ln -s /victim/target.txt "$WORK/data2/jwt-secret"
ln -s /victim/dir "$WORK/data2/logs"
ln -s /etc/passwd "$WORK/data2/devices.yaml"

N2="$NAME-b"; CLEANUP_CONTAINERS="$CLEANUP_CONTAINERS $N2"
# Force the chown path (data dir not owned by 10001): host dir is owned by the host user.
# shellcheck disable=SC2086
docker run -d --name "$N2" $ENVS $EP_ARGS -v "$WORK/data2:/app/data" -v "$WORK/victim:/victim" "$IMAGE" >/dev/null
sleep 8
docker stop -t 10 "$N2" >/dev/null 2>&1 || true
after="$(stat -c '%u:%g:%a' "$WORK/victim/target.txt" "$WORK/victim/dir")"
sum_after="$(sha256sum "$WORK/victim/target.txt" | cut -d' ' -f1)"
if [ "$before" = "$after" ]; then pass "chown did not follow in-tree symlinks (owner/mode unchanged)"; else fail "symlink target metadata changed: '$before' -> '$after'"; fi
if [ "$sum_before" = "$sum_after" ]; then pass "symlink target content unchanged"; else fail "symlink target content modified"; fi

# Data dir itself is a symlink: create it inside the container, pointing at /victim.
N3="$NAME-c"; CLEANUP_CONTAINERS="$CLEANUP_CONTAINERS $N3"
# shellcheck disable=SC2086
docker run --name "$N3" $ENVS $EP_ARGS -v "$WORK/victim:/victim" -e MEMAR_DATA_DIR=/app/link \
  --entrypoint sh "$IMAGE" -c 'ln -s /victim /app/link && exec /usr/local/bin/docker-entrypoint true' >"$WORK/c.log" 2>&1 || true
code3="$(docker inspect -f '{{.State.ExitCode}}' "$N3")"
after3="$(stat -c '%u:%g:%a' "$WORK/victim/target.txt" "$WORK/victim/dir" "$WORK/victim")"
echo "symlinked-data-dir: exit $code3; log: $(tr '\n' ' ' < "$WORK/c.log")"
if [ "$code3" != "0" ] && grep -q "symlink" "$WORK/c.log"; then pass "symlinked data dir refused with clear log line"; else fail "symlinked data dir not refused (exit $code3)"; fi
if [ "$(echo "$after3" | head -2)" = "$(echo "$before" | head -2)" ]; then pass "victim files untouched by symlinked data dir"; else fail "victim changed via symlinked data dir"; fi
[ "$(stat -c %u "$WORK/victim")" = "$(id -u)" ] && pass "victim dir owner unchanged" || fail "victim dir owner changed"

echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]

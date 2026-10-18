#!/usr/bin/env bash
# Installs or upgrades the memar systemd service from this checkout (blue/green, with rollback).
# install.sh calls this; it also runs directly: sudo ./scripts/install_systemd_service.sh
#
# Layout:
#   /opt/memar/releases/<BUILD_ID>   root-owned, read-only to the service (keeps the last 3)
#   /opt/memar/shared/config         devices.yaml (owned by memar, 0600)
#   /var/lib/memar                   database, logs, setup state (owned by memar)
#   /etc/memar.env                   root-only environment file
set -Eeuo pipefail

PHASE="starting"
say() { PHASE="$*"; echo "== $*"; }
trap 'printf "[FAIL] during %s\n" "$PHASE" >&2' ERR

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  command -v sudo >/dev/null 2>&1 || { echo "run as root or install sudo" >&2; exit 1; }
  SUDO="sudo"
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cat "$REPO_ROOT/VERSION")"
# BUILD_ID is written by scripts/release.sh and is not part of the public export;
# a plain clone derives one from git, or the time, so install never aborts here.
BUILD_ID="$(cat "$REPO_ROOT/BUILD_ID" 2>/dev/null | tr -d '[:space:]')"
if [[ -z "$BUILD_ID" ]]; then
  BUILD_ID="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"
fi
SERVICE_NAME="memar.service"
APP_ROOT="/opt/memar"
RELEASES_DIR="$APP_ROOT/releases"
SHARED_DIR="$APP_ROOT/shared"
CURRENT_LINK="$APP_ROOT/current"
NEXT_LINK="$APP_ROOT/.next"
RUNTIME_USER="memar"
DATA_DIR="/var/lib/memar"
ENV_FILE="/etc/memar.env"
KEEP_RELEASES=3
PY="${MEMAR_PY:-python3}"
PORT_REQUESTED="${MEMAR_PORT:-}"   # set by install.sh; empty when run directly
FINAL_RELEASE="$RELEASES_DIR/$BUILD_ID"
UNIT_DST="/etc/systemd/system/$SERVICE_NAME"
PREUPGRADE_UNIT_BACKUP="$SHARED_DIR/systemd-backups/$SERVICE_NAME.preupgrade.bak"
LEGACY_UNIT_BACKUP="$SHARED_DIR/systemd-backups/$SERVICE_NAME.legacy.bak"
PREV_TARGET=""
LEGACY_ROOT=""

if [ -L "$CURRENT_LINK" ]; then
  target="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
  if [ -n "$target" ] && [ -d "$target/backend" ] && [ -f "$target/frontend_dist/index.html" ] && [ -x "$target/backend/.venv/bin/python3" ]; then
    PREV_TARGET="$target"
  fi
fi
if [ -d "$APP_ROOT/backend" ] && [ -x "$APP_ROOT/backend/.venv/bin/python3" ]; then
  LEGACY_ROOT="$APP_ROOT"
fi
# A first install has no unit, no previous release and no legacy layout.
FIRST_INSTALL=0
if [ ! -f "$UNIT_DST" ] && [ -z "$PREV_TARGET" ] && [ -z "$LEGACY_ROOT" ]; then FIRST_INSTALL=1; fi

validate_release() {
  local port url_base="" _
  port="$($SUDO sed -n 's/^MEMAR_PORT=//p' "$ENV_FILE" 2>/dev/null | tail -n1 || true)"
  port="${port:-8000}"
  url_base="http://127.0.0.1:$port"
  sleep 1
  for _ in $(seq 1 90); do
    if curl -fsS "$url_base/api/healthz" >/dev/null 2>&1 && \
       curl -fsS "$url_base/api/readyz" >/dev/null 2>&1 && \
       curl -fsS "$url_base/api/version" >/dev/null 2>&1 && \
       curl -fsS "$url_base/" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

stage_release() {
  local stage_dir
  stage_dir="$($SUDO mktemp -d "$RELEASES_DIR/.incoming.${BUILD_ID}.XXXXXX")"
  $SUDO chown -R "$(id -u)":"$(id -g)" "$stage_dir"

  rsync -a --delete \
    --exclude '.venv' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '.env' \
    --exclude 'frontend/node_modules' \
    --exclude '__pycache__' \
    "$REPO_ROOT/" "$stage_dir/"

  cd "$stage_dir/backend"
  "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip wheel
  .venv/bin/pip install -q --no-cache-dir -r requirements.txt

  cd "$stage_dir"
  ./scripts/build_frontend_into_backend.sh

  if [ -e "$FINAL_RELEASE" ] && [ "$PREV_TARGET" != "$FINAL_RELEASE" ]; then
    $SUDO rm -rf "$FINAL_RELEASE"
  fi

  if [ ! -e "$FINAL_RELEASE" ]; then
    $SUDO mv "$stage_dir" "$FINAL_RELEASE"
  else
    rm -rf "$stage_dir"
  fi
  # The service must not modify its own code: root owns the release, everyone reads it.
  $SUDO chown -R root:root "$FINAL_RELEASE"
  $SUDO chmod -R a+rX "$FINAL_RELEASE"
  $SUDO chmod -R go-w "$FINAL_RELEASE"
}

# Keep the newest $KEEP_RELEASES release directories. Runs only after a validated start.
prune_releases() {
  local d
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    [ "$d" = "$FINAL_RELEASE" ] && continue
    $SUDO rm -rf -- "$d"
    echo "pruned old release $d"
  done < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -name 'current-dir.backup.*' \
             -printf '%T@ %p\n' 2>/dev/null | sort -rn | awk -v k="$KEEP_RELEASES" 'NR > k { sub(/^[^ ]+ /, ""); print }')
}

# Set KEY in the env file. mode=replace overwrites; mode=default adds the key only when absent.
env_file_set() {
  local k="$1" v="$2" mode="$3" tmp
  tmp="$(mktemp)"
  $SUDO cat "$ENV_FILE" > "$tmp"
  if grep -q "^$k=" "$tmp"; then
    if [ "$mode" = replace ]; then
      grep -v "^$k=" "$tmp" > "$tmp.new" || true
      printf '%s=%s\n' "$k" "$v" >> "$tmp.new"
      mv "$tmp.new" "$tmp"
    fi
  else
    printf '%s=%s\n' "$k" "$v" >> "$tmp"
  fi
  $SUDO install -m 0600 -o root -g root "$tmp" "$ENV_FILE"
  rm -f "$tmp" "$tmp.new"
}

rollback_to_previous() {
  echo "== validation failed =="
  $SUDO systemctl --no-pager --full status "$SERVICE_NAME" || true
  journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true

  if [ -n "$PREV_TARGET" ] && [ -d "$PREV_TARGET" ]; then
    echo "Rolling back to previous release: $PREV_TARGET"
    $SUDO ln -sfn "$PREV_TARGET" "$NEXT_LINK"
    $SUDO mv -Tf "$NEXT_LINK" "$CURRENT_LINK"
    if [ -f "$PREUPGRADE_UNIT_BACKUP" ]; then $SUDO install -D -m 0644 "$PREUPGRADE_UNIT_BACKUP" "$UNIT_DST" || true; fi
    $SUDO systemctl daemon-reload || true
    $SUDO systemctl restart "$SERVICE_NAME" || true
    return
  fi

  if [ -n "$LEGACY_ROOT" ] && [ -f "$LEGACY_UNIT_BACKUP" ]; then
    echo "Rolling back to legacy service/unit"
    $SUDO install -D -m 0644 "$LEGACY_UNIT_BACKUP" "$UNIT_DST"
    $SUDO systemctl daemon-reload
    $SUDO systemctl restart "$SERVICE_NAME" || true
    return
  fi

  echo "No rollback target was available."
}

echo "== version =="
echo "$VERSION ($BUILD_ID)"
echo

$SUDO useradd --system --create-home --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$RUNTIME_USER" 2>/dev/null || true
$SUDO mkdir -p "$RELEASES_DIR" "$SHARED_DIR/config" "$SHARED_DIR/systemd-backups" "$DATA_DIR/logs"
$SUDO chown root:root "$APP_ROOT" "$RELEASES_DIR" "$SHARED_DIR"
$SUDO chmod 0755 "$APP_ROOT" "$RELEASES_DIR" "$SHARED_DIR"
$SUDO chown "$RUNTIME_USER:$RUNTIME_USER" "$DATA_DIR" "$DATA_DIR/logs" "$SHARED_DIR/config"
$SUDO chmod 0750 "$DATA_DIR" "$DATA_DIR/logs"
$SUDO chmod 0755 "$SHARED_DIR/config"

if [ -f "$UNIT_DST" ]; then
  $SUDO cp -a "$UNIT_DST" "$PREUPGRADE_UNIT_BACKUP"
fi
if [ -f "$UNIT_DST" ] && [ ! -f "$LEGACY_UNIT_BACKUP" ] && [ -n "$LEGACY_ROOT" ]; then
  $SUDO cp -a "$UNIT_DST" "$LEGACY_UNIT_BACKUP"
fi

if [ "$PREV_TARGET" = "$FINAL_RELEASE" ] && [ -x "$FINAL_RELEASE/backend/.venv/bin/python3" ] && [ -f "$FINAL_RELEASE/frontend_dist/index.html" ]; then
  echo "== release =="
  echo "Same release already staged at $FINAL_RELEASE"
else
  say "Staging release $BUILD_ID (Python dependencies and UI build can take several minutes)"
  stage_release
fi

echo
if [ ! -f "$SHARED_DIR/config/devices.example.yaml" ] && [ -f "$FINAL_RELEASE/config/devices.example.yaml" ]; then
  $SUDO install -D -m 0644 "$FINAL_RELEASE/config/devices.example.yaml" "$SHARED_DIR/config/devices.example.yaml"
fi

say "Writing $ENV_FILE"
if ! $SUDO test -f "$ENV_FILE"; then
  # No secrets here: MEMAR creates its own JWT secret and setup code on first start.
  printf 'MEMAR_ENV=production\nMEMAR_CONFIG_PATH=%s\nMEMAR_DB_PATH=%s/memar.db\nMEMAR_DATA_DIR=%s\nMEMAR_LOG_DIR=%s/logs\nMEMAR_PORT=%s\n' \
    "$SHARED_DIR/config/devices.yaml" "$DATA_DIR" "$DATA_DIR" "$DATA_DIR" "${PORT_REQUESTED:-8000}" \
    | $SUDO install -D -m 0600 -o root -g root /dev/stdin "$ENV_FILE"
  echo "created $ENV_FILE"
else
  env_file_set MEMAR_ENV production replace
  env_file_set MEMAR_LOG_DIR "$DATA_DIR/logs" default
  env_file_set MEMAR_DATA_DIR "$DATA_DIR" default
  env_file_set MEMAR_DB_PATH "$DATA_DIR/memar.db" default
  env_file_set MEMAR_CONFIG_PATH "$SHARED_DIR/config/devices.yaml" default
  if [ -n "$PORT_REQUESTED" ]; then
    env_file_set MEMAR_PORT "$PORT_REQUESTED" replace
  else
    env_file_set MEMAR_PORT 8000 default
  fi
  echo "updated $ENV_FILE (existing secrets kept)"
fi

# devices.yaml holds device credentials: the service user owns it, nobody else reads it.
if $SUDO test -f "$SHARED_DIR/config/devices.yaml"; then
  $SUDO chown "$RUNTIME_USER:$RUNTIME_USER" "$SHARED_DIR/config/devices.yaml"
  $SUDO chmod 0600 "$SHARED_DIR/config/devices.yaml"
fi

# Optional license key (install.sh --license / --license-file). Replaces any existing line.
if [ -n "${MEMAR_LICENSE_FILE:-}" ]; then
  [ -r "$MEMAR_LICENSE_FILE" ] || { echo "license file not readable" >&2; exit 1; }
  lic="$(cat -- "$MEMAR_LICENSE_FILE")"
  lic_tmp="$(mktemp)"
  chmod 600 "$lic_tmp"
  $SUDO cat "$ENV_FILE" 2>/dev/null | grep -v '^MEMAR_LICENSE_KEY=' > "$lic_tmp" || true
  printf 'MEMAR_LICENSE_KEY=%s\n' "$lic" >> "$lic_tmp"
  $SUDO install -m 0600 -o root -g root "$lic_tmp" "$ENV_FILE"
  rm -f "$lic_tmp"
  echo "license key written to $ENV_FILE (value not shown)"
fi

say "Installing $SERVICE_NAME"
$SUDO install -D -m 0644 "$FINAL_RELEASE/deploy/systemd/$SERVICE_NAME" "$UNIT_DST"
$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true

if [ -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then
  $SUDO mv "$CURRENT_LINK" "$RELEASES_DIR/current-dir.backup.$(date +%Y%m%d-%H%M%S)"
fi

$SUDO ln -sfn "$FINAL_RELEASE" "$NEXT_LINK"
$SUDO mv -Tf "$NEXT_LINK" "$CURRENT_LINK"
$SUDO systemctl restart "$SERVICE_NAME"

if validate_release; then
  prune_releases
  echo "== release active =="
  readlink -f "$CURRENT_LINK"
  $SUDO systemctl --no-pager --full status "$SERVICE_NAME" || true
  echo "[OK] installed $SERVICE_NAME"
  exit 0
fi

if [ "$FIRST_INSTALL" = 1 ]; then
  $SUDO systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
  echo "[FAIL] the first start failed. The service is disabled so it does not restart in a loop." >&2
  echo "Next: read the log with  journalctl -u memar -n 80 , fix the cause, then re-run ./install.sh" >&2
  exit 1
fi

rollback_to_previous
exit 1

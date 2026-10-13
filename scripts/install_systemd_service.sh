#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cat "$REPO_ROOT/VERSION")"
BUILD_ID="$(cat "$REPO_ROOT/BUILD_ID")"
SERVICE_NAME="memar.service"
APP_ROOT="/opt/memar"
RELEASES_DIR="$APP_ROOT/releases"
SHARED_DIR="$APP_ROOT/shared"
CURRENT_LINK="$APP_ROOT/current"
NEXT_LINK="$APP_ROOT/.next"
RUNTIME_USER="memar"
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

validate_release() {
  local url_base="http://127.0.0.1:9000"
  sleep 1
  for _ in $(seq 1 30); do
    if curl -fsS "$url_base/api/healthz" >/dev/null 2>&1 && \
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
  stage_dir="$(sudo mktemp -d "$RELEASES_DIR/.incoming.${BUILD_ID}.XXXXXX")"
  sudo chown -R "$USER":"$USER" "$stage_dir"

  rsync -a --delete \
    --exclude '.venv' \
    --exclude 'frontend/node_modules' \
    --exclude '__pycache__' \
    "$REPO_ROOT/" "$stage_dir/"

  cd "$stage_dir/backend"
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -r requirements.txt

  cd "$stage_dir"
  ./scripts/build_frontend_into_backend.sh

  if [ -e "$FINAL_RELEASE" ] && [ "$PREV_TARGET" != "$FINAL_RELEASE" ]; then
    sudo rm -rf "$FINAL_RELEASE"
  fi

  if [ ! -e "$FINAL_RELEASE" ]; then
    sudo mv "$stage_dir" "$FINAL_RELEASE"
  else
    rm -rf "$stage_dir"
  fi
}

rollback_to_previous() {
  echo "== validation failed =="
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
  journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true

  if [ -n "$PREV_TARGET" ] && [ -d "$PREV_TARGET" ]; then
    echo "Rolling back to previous release: $PREV_TARGET"
    sudo ln -sfn "$PREV_TARGET" "$NEXT_LINK"
    sudo mv -Tf "$NEXT_LINK" "$CURRENT_LINK"
    sudo install -D -m 0644 "$PREUPGRADE_UNIT_BACKUP" "$UNIT_DST" || true
    sudo systemctl daemon-reload || true
    sudo systemctl restart "$SERVICE_NAME" || true
    return
  fi

  if [ -n "$LEGACY_ROOT" ] && [ -f "$LEGACY_UNIT_BACKUP" ]; then
    echo "Rolling back to legacy service/unit"
    sudo install -D -m 0644 "$LEGACY_UNIT_BACKUP" "$UNIT_DST"
    sudo systemctl daemon-reload
    sudo systemctl restart "$SERVICE_NAME" || true
    return
  fi

  echo "No rollback target was available."
}

echo "== version =="
echo "$VERSION ($BUILD_ID)"
echo

sudo useradd --system --create-home --home-dir /var/lib/memar --shell /usr/sbin/nologin "$RUNTIME_USER" 2>/dev/null || true
sudo mkdir -p "$RELEASES_DIR" "$SHARED_DIR/config" "$SHARED_DIR/systemd-backups"

if [ -f "$UNIT_DST" ]; then
  sudo cp -a "$UNIT_DST" "$PREUPGRADE_UNIT_BACKUP"
fi

if [ -f "$UNIT_DST" ] && [ ! -f "$LEGACY_UNIT_BACKUP" ] && [ -n "$LEGACY_ROOT" ]; then
  sudo cp -a "$UNIT_DST" "$LEGACY_UNIT_BACKUP"
fi

if [ "$PREV_TARGET" = "$FINAL_RELEASE" ] && [ -x "$FINAL_RELEASE/backend/.venv/bin/python3" ] && [ -f "$FINAL_RELEASE/frontend_dist/index.html" ]; then
  echo "== release =="
  echo "Same release already staged at $FINAL_RELEASE"
else
  echo "== staging release =="
  stage_release
fi

echo
sudo chown -R "$RUNTIME_USER":"$RUNTIME_USER" "$FINAL_RELEASE"

if [ ! -f "$SHARED_DIR/config/printers.example.yaml" ]; then
  echo "== seed shared config =="
  sudo install -D -m 0644 "$FINAL_RELEASE/config/printers.example.yaml" "$SHARED_DIR/config/printers.example.yaml"
fi

sudo chown -R "$RUNTIME_USER":"$RUNTIME_USER" "$SHARED_DIR/config"
sudo chmod 755 "$SHARED_DIR" "$SHARED_DIR/config"
if [ -f "$SHARED_DIR/config/printers.example.yaml" ]; then
  sudo chmod 644 "$SHARED_DIR/config/printers.example.yaml"
fi

if [ -z "${MEMAR_JWT_SECRET:-}" ]; then
  MEMAR_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "== generated new MEMAR_JWT_SECRET (written to /etc/memar.env) =="
fi
# Write env file securely without echoing secret to console
cat > /tmp/memar.env <<ENVEOF
MEMAR_CONFIG_PATH=$SHARED_DIR/config/devices.example.yaml
MEMAR_JWT_SECRET=$MEMAR_JWT_SECRET
MEMAR_DB_PATH=/var/lib/memar/memar.db
MEMAR_DATA_DIR=/var/lib/memar
ENVEOF
sudo install -D -m 0600 /tmp/memar.env /etc/memar.env
sudo chown root:root /etc/memar.env
rm -f /tmp/memar.env
unset MEMAR_JWT_SECRET

sudo install -D -m 0644 "$FINAL_RELEASE/deploy/systemd/$SERVICE_NAME" "$UNIT_DST"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true

if [ -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then
  sudo mv "$CURRENT_LINK" "$RELEASES_DIR/current-dir.backup.$(date +%Y%m%d-%H%M%S)"
fi

sudo ln -sfn "$FINAL_RELEASE" "$NEXT_LINK"
sudo mv -Tf "$NEXT_LINK" "$CURRENT_LINK"
sudo systemctl restart "$SERVICE_NAME"

if validate_release; then
  echo "== release active =="
  readlink -f "$CURRENT_LINK"
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
  echo "[OK] installed $SERVICE_NAME"
  exit 0
fi

rollback_to_previous
exit 1

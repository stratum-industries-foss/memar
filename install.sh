#!/usr/bin/env bash
# MEMAR universal installer.
#
#   git clone https://github.com/stratum-industries-foss/memar && cd memar && bash install.sh
#
# Modes:
#   bash install.sh               native install (Python venv + systemd). Default. No Docker needed.
#   bash install.sh --docker      install Docker from the distro, then `docker compose up -d`
#   bash install.sh --no-service  native build only; prints the command to run MEMAR in the foreground
#
# Options:
#   --port N        port MEMAR listens on (default 8000; an existing install keeps its port on re-run)
#   --yes           do not prompt
#   --help
#
# Nothing is required to start MEMAR and no admin password is generated. On first start MEMAR
# prints a one-time setup link; the installer prints it at the end.
#
# Supported: Debian/Ubuntu/Raspberry Pi OS/Armbian, Fedora/RHEL/Rocky/Alma, Arch/Manjaro,
# openSUSE, Alpine (docker or --no-service). Architectures: x86_64, aarch64/arm64, armv7l.
# Klipper hosts (KIAUH printer_N_data dirs) are auto-discovered on native installs.

# Bash-only from here on. Fail early and clearly under sh/dash.
if [ -z "${BASH_VERSION:-}" ]; then
  echo 'Please run: bash install.sh' >&2
  exit 2
fi
set -Eeuo pipefail

MODE=native
PORT=8000
PORT_EXPLICIT=0
LICENSE_KEY=""
LICENSE_FROM=""          # "" (none), "arg" (--license) or "file" (--license-file)
LICENSE_FILE=""
PY_MIN_MINOR=11          # Python 3.11+ (asyncio.timeout). No upper cap: CI tests the newest Python.
MANAGED_PY=3.13          # fetched with uv only if the system Python is too old or cannot build the deps
NODE_DEFAULT=24.11.1     # used only if nodejs.org/dist/index.json is unreachable
PHASE="starting"

say()  { PHASE="$*"; printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
trap 'printf "[FAIL] during %s\n" "$PHASE" >&2' ERR

usage() { sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

SELF="${BASH_SOURCE[0]:-}"
if [ -z "$SELF" ] || [ ! -f "$SELF" ]; then
  echo "install.sh must run from a cloned checkout. Clone first:" >&2
  echo "  git clone https://github.com/stratum-industries-foss/memar && cd memar && bash install.sh" >&2
  exit 2
fi
REPO_ROOT="$(cd "$(dirname "$SELF")" && pwd)"
[ -f "$REPO_ROOT/VERSION" ] || die "$REPO_ROOT is not a MEMAR checkout (no VERSION file)"
INVOKING_USER="${SUDO_USER:-$(id -un)}"
INVOKING_HOME="$(getent passwd "$INVOKING_USER" 2>/dev/null | cut -d: -f6 || true)"
INVOKING_HOME="${INVOKING_HOME:-$HOME}"

while [ $# -gt 0 ]; do
  case "$1" in
    --docker) MODE=docker ;;
    --native) MODE=native ;;
    --no-service) MODE=noservice ;;
    --port)
      [ $# -ge 2 ] && [ -n "$2" ] || die "--port needs a value, for example: --port 8080"
      PORT="$2"; PORT_EXPLICIT=1; shift ;;
    --port=*) PORT="${1#*=}"; PORT_EXPLICIT=1 ;;
    --license)
      [ $# -ge 2 ] || die "--license needs the license key"
      [ -z "$LICENSE_FROM" ] || die "give --license or --license-file, not both"
      LICENSE_KEY="$2"; LICENSE_FROM="arg"; shift ;;
    --license=*)
      [ -z "$LICENSE_FROM" ] || die "give --license or --license-file, not both"
      LICENSE_KEY="${1#*=}"; LICENSE_FROM="arg" ;;
    --license-file)
      [ $# -ge 2 ] || die "--license-file needs a path"
      [ -z "$LICENSE_FROM" ] || die "give --license or --license-file, not both"
      LICENSE_FILE="$2"; LICENSE_FROM="file"; shift ;;
    --license-file=*)
      [ -z "$LICENSE_FROM" ] || die "give --license or --license-file, not both"
      LICENSE_FILE="${1#*=}"; LICENSE_FROM="file" ;;
    -y|--yes) : ;;   # accepted for compatibility; the installer never prompts
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

# License key: read it, trim surrounding whitespace, and refuse anything else.
# The key is never printed, not even in error messages.
if [ "$LICENSE_FROM" = file ]; then
  [ -r "$LICENSE_FILE" ] || die "cannot read license file: $LICENSE_FILE"
  LICENSE_KEY="$(cat -- "$LICENSE_FILE")"
fi
if [ -n "$LICENSE_FROM" ]; then
  LICENSE_KEY="${LICENSE_KEY#"${LICENSE_KEY%%[![:space:]]*}"}"
  LICENSE_KEY="${LICENSE_KEY%"${LICENSE_KEY##*[![:space:]]}"}"
  [ -n "$LICENSE_KEY" ] || die "the license key is empty"
  case "$LICENSE_KEY" in
    *[[:space:]]*) die "the license key contains spaces or line breaks. Paste it as one line." ;;
  esac
fi

case "$PORT" in ''|*[!0-9]*) die "--port must be a number from 1 to 65535" ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "--port must be a number from 1 to 65535"

# Every download gets a connect timeout, a total cap and retries.
fetch() { curl -fsSL --connect-timeout 15 --max-time 900 --retry 3 "$@"; }
APT_OPT=(-o DPkg::Lock::Timeout=600)

# ---------------------------------------------------------------- privileges
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  say "Checking privileges"
  command -v sudo >/dev/null 2>&1 || die "run as root or install sudo"
  if ! sudo -n true 2>/dev/null; then
    if [ -t 0 ]; then
      sudo -v || die "sudo password was not accepted"
    else
      die "sudo needs a password and no terminal is attached. Run 'sudo -v' first, then re-run ./install.sh"
    fi
  fi
  SUDO="sudo"
fi

# ---------------------------------------------------------------- platform
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) NODE_ARCH=x64 ;;
  aarch64|arm64) NODE_ARCH=arm64 ;;
  armv7l|armv7*) NODE_ARCH=armv7l ;;
  *) NODE_ARCH="" ; warn "untested architecture $ARCH" ;;
esac
[ -r /etc/os-release ] && . /etc/os-release
OS_ID="${ID:-unknown}"

PKG=""
for pm in apt-get dnf yum pacman zypper apk; do
  if command -v "$pm" >/dev/null 2>&1; then PKG="$pm"; break; fi
done
[ -n "$PKG" ] || die "no supported package manager found (apt, dnf, yum, pacman, zypper, apk)"

HAS_SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then HAS_SYSTEMD=1; fi

say "MEMAR $(cat "$REPO_ROOT/VERSION") installer"
echo "  OS: ${PRETTY_NAME:-$OS_ID}   arch: $ARCH   pkg: $PKG   systemd: $HAS_SYSTEMD   mode: $MODE   port: $PORT"

if [ "$MODE" = native ] && [ "$HAS_SYSTEMD" = 0 ]; then
  warn "systemd not running here; switching to --no-service (foreground run command will be printed)"
  MODE=noservice
fi

has_klipper() {
  ls -d "$INVOKING_HOME"/printer_*_data >/dev/null 2>&1 || [ -d "$INVOKING_HOME/printer_data" ]
}

# ---------------------------------------------------------------- packages
APT_UPDATED=0
pkg_install() {
  [ $# -gt 0 ] || return 0
  case "$PKG" in
    apt-get)
      if [ "$APT_UPDATED" = 0 ]; then $SUDO apt-get "${APT_OPT[@]}" update -qq; APT_UPDATED=1; fi
      $SUDO env DEBIAN_FRONTEND=noninteractive apt-get "${APT_OPT[@]}" install -y -qq --no-install-recommends "$@" ;;
    dnf|yum) $SUDO "$PKG" install -y -q "$@" ;;
    pacman)  $SUDO pacman -S --needed --noconfirm "$@" ;;
    zypper)  $SUDO zypper --non-interactive install -y "$@" ;;
    apk)     $SUDO apk add --no-cache "$@" ;;
  esac
}
pkg_available() {   # best-effort check, used to pick between alternative package names
  case "$PKG" in
    apt-get) [ "$APT_UPDATED" = 1 ] || { $SUDO apt-get "${APT_OPT[@]}" update -qq; APT_UPDATED=1; }
             apt-cache show "$1" >/dev/null 2>&1 ;;
    dnf|yum) "$PKG" -q info "$1" >/dev/null 2>&1 ;;
    pacman)  pacman -Si "$1" >/dev/null 2>&1 ;;
    zypper)  zypper -q info "$1" 2>/dev/null | grep -q "^Name" ;;
    apk)     apk info -e "$1" >/dev/null 2>&1 || apk search -x "$1" 2>/dev/null | grep -q . ;;
  esac
}

rand_hex() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }

# ---------------------------------------------------------------- env file helpers (checkout .env)
env_set() {      # $1 file, $2 KEY, $3 VALUE: replace the key or append it
  local f="$1" k="$2" v="$3" tmp
  touch "$f"
  tmp="$(mktemp)"
  grep -v "^$k=" "$f" > "$tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$tmp"
  cat "$tmp" > "$f"
  rm -f "$tmp"
}
env_default() {  # $1 file, $2 KEY, $3 VALUE: append only if the key is absent
  touch "$1"
  if ! grep -q "^$2=" "$1"; then printf '%s=%s\n' "$2" "$3" >> "$1"; fi
}

# ---------------------------------------------------------------- host info and links
lan_ip() {       # source address of the default route (hostname -I can list docker bridges first)
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit } }' || true)"
  fi
  if [ -z "$ip" ] && command -v python3 >/dev/null 2>&1; then
    # No iproute2 (minimal images, docker mode): ask the kernel the same question.
    ip="$(python3 -c 'import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("1.1.1.1", 80)); print(s.getsockname()[0])' 2>/dev/null || true)"
  fi
  if [ -z "$ip" ]; then
    # Last resort: first address that is not loopback or a docker bridge.
    ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -Ev '^(127\.|172\.1[7-9]\.|$)' | head -n 1 || true)"
  fi
  printf '%s\n' "$ip"
}
host_urls() {    # sets BASE_URL and MDNS_URL from the current PORT
  local ip; ip="$(lan_ip)"; ip="${ip:-localhost}"
  BASE_URL="http://$ip:$PORT"
  MDNS_URL="http://$(hostname -s 2>/dev/null || echo localhost).local:$PORT"
}

# Print the setup link (or the sign-in URL if already set up).
# $1 = base URL, rest = command that runs the memar CLI. Returns non-zero if no link yet.
show_link() {
  local base="$1"; shift
  local out rc=0 link="" path=""
  out="$("$@" setup-link 2>&1)" || rc=$?
  if [ "$rc" -eq 3 ]; then
    echo "MEMAR is already set up. Sign in at: $base"
    return 0
  fi
  [ "$rc" -eq 0 ] || return 1
  # The CLI prints localhost and a placeholder for the LAN address. Keep its /setup path
  # and put our detected LAN address in front of it.
  path="$(printf '%s\n' "$out" | grep -Eo '/setup\?code=[^[:space:]]+' | awk 'NR == 1' || true)"
  [ -n "$path" ] || return 1
  link="$base$path"
  echo "Open this link to finish setup: $link"
  echo "  The link carries a one-time setup code. Whoever opens it first can claim this instance."
  return 0
}

# Wait until the running service answers /api/readyz on this host. $1 = port.
wait_ready() {
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 3 "http://127.0.0.1:$1/api/readyz" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

# Refuse to start on a port something else holds, and name the holder.
check_port() {
  if [ "$HAS_SYSTEMD" = 1 ] && systemctl is-active --quiet memar 2>/dev/null; then return 0; fi
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx memar; then return 0; fi
  command -v ss >/dev/null 2>&1 || return 0
  local listing hit who
  listing="$($SUDO ss -ltnp 2>/dev/null || true)"
  hit="$(printf '%s\n' "$listing" | awk -v p=":$PORT" '$4 ~ (p "$") { print; exit }')"
  [ -n "$hit" ] || return 0
  who="$(printf '%s\n' "$hit" | grep -o 'users:(([^)]*))' | awk 'NR == 1' || true)"
  die "port $PORT is already in use${who:+ by $who}. Pick a free port, for example: --port 8080"
}

# Keep the port of an existing install on re-run, unless --port was given.
resolve_port() {
  [ "$PORT_EXPLICIT" = 1 ] && return 0
  local existing=""
  case "$MODE" in
    docker)
      if has_klipper; then
        existing="$(sed -n 's/^MEMAR_PORT=//p' "$REPO_ROOT/.env" 2>/dev/null | tail -n1 || true)"
      else
        existing="$(sed -n 's/^MEMAR_HOST_PORT=//p' "$REPO_ROOT/.env" 2>/dev/null | tail -n1 || true)"
      fi ;;
    noservice) existing="$(sed -n 's/^MEMAR_PORT=//p' "$REPO_ROOT/.env" 2>/dev/null | tail -n1 || true)" ;;
    native)    existing="$($SUDO sed -n 's/^MEMAR_PORT=//p' /etc/memar.env 2>/dev/null | tail -n1 || true)" ;;
  esac
  case "$existing" in ''|*[!0-9]*) ;; *) PORT="$existing" ;; esac
}

# ---------------------------------------------------------------- discovery (native only)
# Writes printer config from KIAUH printer_N_data dirs. Skips quietly when httpx is missing
# or no Klipper home exists; the setup wizard's network scan covers the rest.
discover_config() {  # $1 = python, $2 = output path
  local py="$1" out="$2"
  has_klipper || return 0
  "$py" -c 'import httpx, yaml' >/dev/null 2>&1 || return 0
  echo "Discovering Klipper/Moonraker instances in $INVOKING_HOME"
  ( cd "$REPO_ROOT/backend" && "$py" - "$INVOKING_HOME" "$out" <<'PY'
import sys, yaml
from pathlib import Path
from app.config_discovery import generate_config
home, out = Path(sys.argv[1]), Path(sys.argv[2])
cfg = generate_config(home)
if not cfg.get("printers") and (home / "printer_data").is_dir():
    # single-instance KIAUH layout: ~/printer_data, Moonraker on 7125
    cfg["printers"] = [{"id": "printer-1", "name": "Printer 1",
                        "base_url": "http://127.0.0.1:7125",
                        "ws_url": "ws://127.0.0.1:7125/websocket"}]
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(yaml.safe_dump(cfg, sort_keys=False))
n = len(cfg["printers"])
print(f"Found {n} printers")
if n > 5:
    print("The Free plan monitors 5. You choose which in the setup wizard.")
PY
  ) || warn "auto-discovery failed; the setup wizard can scan for printers"
}

# ---------------------------------------------------------------- docker mode
install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "docker + compose already installed"; return
  fi
  say "Installing Docker from the distro repositories"
  case "$PKG" in
    apt-get)
      # Debian/Ubuntu call the engine "docker.io"; plain "docker" is an unrelated package.
      # Debian 13 ships the CLI separately (docker-cli is only a Recommends of docker.io,
      # and we install without recommends), and TLS pulls need ca-certificates.
      local pk="docker.io ca-certificates"
      pkg_available docker-cli && pk="$pk docker-cli"
      if pkg_available docker-compose-v2; then pk="$pk docker-compose-v2"     # Ubuntu
      elif pkg_available docker-compose-plugin; then pk="$pk docker-compose-plugin"
      else pk="$pk docker-compose"; fi                                        # Debian 13+: v2 plugin
      pkg_available docker-buildx && pk="$pk docker-buildx"
      # shellcheck disable=SC2086
      pkg_install $pk ;;
    dnf|yum)
      if pkg_available moby-engine; then pkg_install moby-engine docker-compose
      else pkg_install docker docker-compose; fi ;;
    pacman) pkg_install docker docker-compose docker-buildx ;;
    zypper) pkg_install docker docker-compose ;;
    apk)    pkg_install docker docker-cli-compose docker-cli-buildx ;;
  esac
  if [ "$HAS_SYSTEMD" = 1 ]; then $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
  elif command -v rc-service >/dev/null 2>&1; then $SUDO rc-update add docker default >/dev/null 2>&1 || true; $SUDO rc-service docker start || true; fi
  docker_cmd compose version >/dev/null 2>&1 || die "docker compose v2 is not available after install. Install the compose plugin for your distro, then re-run with --docker."
  ok "docker installed"
}
docker_cmd() { if docker info >/dev/null 2>&1; then docker "$@"; else $SUDO docker "$@"; fi; }

run_docker() {
  install_docker
  # The readiness check and the setup link use curl; minimal systems may not have it.
  command -v curl >/dev/null 2>&1 || pkg_install curl
  cd "$REPO_ROOT"
  # No secrets are needed. .env only holds the port settings.
  touch .env; chmod 600 .env
  local files=(-f docker-compose.yml)
  if has_klipper; then
    files+=(-f docker-compose.host-network.yml)   # Moonraker on 127.0.0.1 and the LAN
    env_set .env MEMAR_PORT "$PORT"
    warn "Klipper host detected: using host networking; MEMAR listens on port $PORT"
  else
    env_set .env MEMAR_HOST_PORT "$PORT"
  fi
  if [ -n "$LICENSE_FROM" ]; then
    env_set .env MEMAR_LICENSE_KEY "$LICENSE_KEY"
    ok "license key saved to .env (mode 600, value not shown)"
  fi
  say "Starting MEMAR (the first pull can take a few minutes)"
  if ! docker_cmd compose "${files[@]}" up -d; then
    warn "could not pull the image; building it from this checkout (slow on SBCs)"
    docker_cmd compose "${files[@]}" -f docker-compose.build.yml up -d --build
  fi
  host_urls
  say "Checking health and getting the setup link"
  if ! wait_ready "$PORT"; then
    warn "MEMAR is not ready yet. Check: docker logs memar"
  elif ! show_link "$BASE_URL" docker_cmd exec memar memar; then
    warn "could not read the setup link yet. Run: docker exec memar memar setup-link"
  fi
  finish_common "docker compose logs -f memar" "docker exec memar memar setup-link"
}

# ---------------------------------------------------------------- native mode
python_ok() { "$1" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $PY_MIN_MINOR) else 1)" 2>/dev/null; }

managed_python() {   # fetch a standalone CPython with uv into /opt/memar/python
  say "Fetching a managed Python $MANAGED_PY with uv"
  $SUDO mkdir -p /opt/memar/bin /opt/memar/python
  $SUDO chown "$(id -u):$(id -g)" /opt/memar/bin /opt/memar/python
  if [ ! -x /opt/memar/bin/uv ]; then
    fetch https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/opt/memar/bin UV_NO_MODIFY_PATH=1 sh >/dev/null
  fi
  UV_PYTHON_INSTALL_DIR=/opt/memar/python /opt/memar/bin/uv python install -q "$MANAGED_PY"
  PY="$(UV_PYTHON_INSTALL_DIR=/opt/memar/python /opt/memar/bin/uv python find "$MANAGED_PY")"
  chmod -R a+rX /opt/memar/python
  python_ok "$PY" || die "could not obtain Python 3.$PY_MIN_MINOR+. Use --docker instead."
  MANAGED=1
}

install_native_deps() {
  say "Installing system packages"
  case "$PKG" in
    apt-get) pkg_install python3 python3-venv python3-pip python3-dev curl rsync ca-certificates build-essential libffi-dev libssl-dev xz-utils iproute2 ;;
    dnf|yum) pkg_install python3 python3-pip python3-devel curl rsync gcc gcc-c++ make libffi-devel openssl-devel xz iproute ;;
    pacman)  pkg_install python python-pip curl rsync base-devel libffi openssl xz iproute2 ;;
    zypper)  pkg_install python3 python3-pip python3-devel curl rsync gcc gcc-c++ make libffi-devel libopenssl-devel xz iproute2 ;;
    apk)     pkg_install python3 py3-pip python3-dev curl rsync build-base libffi-dev openssl-dev xz bash iproute2 ;;
  esac
  PY=""
  MANAGED=0
  local c
  for c in python3 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$c" >/dev/null 2>&1 && python_ok "$c"; then PY="$(command -v "$c")"; break; fi
  done
  if [ -z "$PY" ]; then warn "system Python ($(python3 --version 2>&1)) is older than 3.$PY_MIN_MINOR"; managed_python; fi
  "$PY" -m venv --help >/dev/null 2>&1 || die "$PY has no venv module"
  ok "python: $("$PY" --version)"
}

node_ok() {   # Vite 8 needs Node ^20.19 or >=22.12
  command -v node >/dev/null 2>&1 || return 1
  local v ma mi
  v="$(node -v 2>/dev/null | sed 's/^v//')"
  ma="${v%%.*}"; mi="$(echo "$v" | cut -d. -f2)"
  [ "$ma" -gt 22 ] 2>/dev/null && return 0
  [ "$ma" -eq 22 ] && [ "$mi" -ge 12 ] && return 0
  [ "$ma" -eq 20 ] && [ "$mi" -ge 19 ] && return 0
  return 1
}

ensure_node() {   # only needed when no prebuilt frontend_dist exists
  if [ -f "$REPO_ROOT/frontend_dist/index.html" ]; then ok "using prebuilt frontend"; return; fi
  if ! node_ok; then pkg_install nodejs npm || true; hash -r; fi
  if ! node_ok; then
    [ -n "$NODE_ARCH" ] || die "Node.js 20.19+/22.12+ is required to build the UI and no official build exists for $ARCH"
    local ver nd="/opt/memar/node"
    ver="$(fetch https://nodejs.org/dist/index.json 2>/dev/null | "$PY" -c 'import json,sys; print(next(r["version"].lstrip("v") for r in json.load(sys.stdin) if r.get("lts")))' 2>/dev/null)" || true
    ver="${ver:-$NODE_DEFAULT}"
    say "Distro Node.js is missing or too old; fetching Node $ver (current LTS) from nodejs.org"
    $SUDO rm -rf "$nd"; $SUDO mkdir -p "$nd"
    fetch "https://nodejs.org/dist/v$ver/node-v$ver-linux-$NODE_ARCH.tar.xz" | $SUDO tar -xJ -C "$nd" --strip-components=1
    export PATH="$nd/bin:$PATH"
    node_ok || die "Node.js install failed"
  fi
  ok "node: $(node -v)"
}

build_venv() {   # $1 = dir containing backend/
  local dir="$1"
  "$PY" -m venv "$dir/backend/.venv"
  "$dir/backend/.venv/bin/pip" install -q --upgrade pip wheel
  if ! "$dir/backend/.venv/bin/pip" install -q -r "$dir/backend/requirements.txt"; then
    [ "$MANAGED" = 1 ] && die "pip install failed (see output above)"
    warn "dependencies did not install on $("$PY" --version); retrying with a managed Python"
    managed_python
    rm -rf "$dir/backend/.venv"
    build_venv "$dir"
  fi
}

run_native() {
  install_native_deps
  ensure_node
  say "Building the web UI"
  ( cd "$REPO_ROOT" && ./scripts/build_frontend_into_backend.sh )

  if [ "$MODE" = noservice ]; then
    say "Installing Python dependencies into $REPO_ROOT/backend/.venv"
    build_venv "$REPO_ROOT"
    local envf="$REPO_ROOT/.env"
    mkdir -p "$REPO_ROOT/data"
    env_default "$envf" MEMAR_ENV production
    env_default "$envf" MEMAR_CONFIG_PATH "$REPO_ROOT/config/devices.yaml"
    env_default "$envf" MEMAR_DATA_DIR "$REPO_ROOT/data"
    env_default "$envf" MEMAR_DB_PATH "$REPO_ROOT/data/memar.db"
    env_default "$envf" MEMAR_LOG_DIR "$REPO_ROOT/data/logs"
    if [ "$PORT_EXPLICIT" = 1 ]; then env_set "$envf" MEMAR_PORT "$PORT"; else env_default "$envf" MEMAR_PORT "$PORT"; fi
    chmod 600 "$envf"
    if [ -n "$LICENSE_FROM" ]; then
      env_set "$envf" MEMAR_LICENSE_KEY "$LICENSE_KEY"
      ok "license key saved to .env (mode 600, value not shown)"
    fi
    if [ ! -f "$REPO_ROOT/config/devices.yaml" ]; then
      discover_config "$REPO_ROOT/backend/.venv/bin/python" "$REPO_ROOT/config/devices.yaml"
    fi
    host_urls
    finish_noservice
    return
  fi

  # systemd install: versioned releases under /opt/memar, config in /opt/memar/shared/config,
  # environment in /etc/memar.env (root, 0600), data in /var/lib/memar.
  # scripts/install_systemd_service.sh owns /etc/memar.env and the service.
  $SUDO mkdir -p /opt/memar/shared/config
  if ! $SUDO test -f /opt/memar/shared/config/devices.yaml; then
    local tmpcfg; tmpcfg="$(mktemp -d)/devices.yaml"
    say "Preparing discovery environment"
    build_venv "$REPO_ROOT"
    discover_config "$REPO_ROOT/backend/.venv/bin/python" "$tmpcfg"
    if [ -f "$tmpcfg" ]; then $SUDO install -m 0600 "$tmpcfg" /opt/memar/shared/config/devices.yaml; fi
    rm -rf "$REPO_ROOT/backend/.venv"
  fi
  say "Installing systemd service"
  # The key travels in a 0600 temp file, not in argv or the environment of sudo.
  local licf="" rc=0
  if [ -n "$LICENSE_FROM" ]; then
    licf="$(mktemp)"; chmod 600 "$licf"; printf '%s' "$LICENSE_KEY" > "$licf"
  fi
  MEMAR_PY="$PY" MEMAR_PORT="$PORT" MEMAR_LICENSE_FILE="$licf" "$REPO_ROOT/scripts/install_systemd_service.sh" || rc=$?
  [ -z "$licf" ] || rm -f "$licf"
  [ "$rc" -eq 0 ] || die "systemd install failed (see the output above)"
  # The service script keeps an existing port unless one was given; read the port in use.
  PORT="$($SUDO sed -n 's/^MEMAR_PORT=//p' /etc/memar.env 2>/dev/null | tail -n1 || true)"
  case "$PORT" in ''|*[!0-9]*) PORT=8000 ;; esac
  say "Installing the memar command"
  $SUDO install -m 0755 "$REPO_ROOT/scripts/memar" /usr/local/bin/memar
  host_urls
  say "Checking health and getting the setup link"
  if ! wait_ready "$PORT"; then
    warn "MEMAR is not ready yet. Check: journalctl -u memar -n 80"
  elif ! show_link "$BASE_URL" $SUDO /usr/local/bin/memar; then
    warn "could not read the setup link. Run: sudo memar setup-link"
  fi
  finish_common "journalctl -u memar -f" "sudo memar setup-link"
}

# Shared closing summary. $1 = how to follow logs, $2 = how to get the link again.
finish_common() {
  say "Done"
  echo "  Open:        $BASE_URL"
  echo "  Also:        $MDNS_URL"
  echo "  Logs:        $1"
  echo "  Setup link:  $2"
  if [ -n "$LICENSE_FROM" ]; then echo "  License:     saved to the MEMAR config (value not shown)"; fi
  echo "  Nothing else is needed. Secrets are created by MEMAR on first start."
}

finish_noservice() {
  say "Done"
  echo "  Start MEMAR in the foreground:"
  echo "    cd $REPO_ROOT/backend && set -a && . ../.env && set +a && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT"
  echo "  Then open: $BASE_URL"
  echo "  The setup link is printed at startup. To show it again, run the same command with:"
  echo "    .venv/bin/python -m app.admin_cli setup-link"
}

# ---------------------------------------------------------------- run
resolve_port
check_port
if [ "$MODE" = docker ]; then run_docker; else run_native; fi

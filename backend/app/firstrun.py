"""First-run state: persisted JWT secret, setup code, setup window, setup link.

Lets a fresh install start with zero configuration:
- the JWT signing key is generated once and kept in the data directory;
- with no users and no MEMAR_ADMIN_PASSWORD, the instance is "unclaimed"
  and the owner creates the first admin in the browser (see setup_routes.py).

Policy (MEMAR_SETUP_MODE):
  auto (default) first visitor may claim without a code for MEMAR_SETUP_WINDOW_MIN
                 minutes after each process start; after that the code is required.
  open           first visitor may claim (home lab, or behind a platform login).
  code           the setup code is always required.

The setup code/link is printed to stdout only (docker logs / journalctl), never to
the rotating backend.log, because support-info tails that file.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import secrets
import socket
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_PROCESS_START = time.monotonic()
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
_CODE_LEN = 8
_SECRET_FILE = "jwt-secret"
_CODE_FILE = "setup-code"
_WINDOW_FILE = "setup-window-start"
_VALID_MODES = ("auto", "open", "code")

# Networks whose clients may use the no-code window in auto mode: the owner's
# LAN, the machine itself, and tailnet/CGNAT ranges. Anything else (a public
# address reaching an exposed instance) must present the code.
_PRIVATE_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def is_private_client(ip: str | None) -> bool:
    """True for loopback, RFC1918, link-local, CGNAT/tailnet and IPv6 ULA clients.
    Unknown or unparseable addresses count as public (fail closed)."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip.strip().split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in net for net in _PRIVATE_NETS)


# ── Data directory ────────────────────────────────────────────────────────────

def data_dir() -> Path:
    """Directory for persistent state. MEMAR_DATA_DIR, else the DB's directory, else ./data."""
    env = os.getenv("MEMAR_DATA_DIR")
    if env:
        return Path(env)
    db = os.getenv("MEMAR_DB_PATH", "")
    if db and db != ":memory:":
        return Path(db).expanduser().resolve().parent
    return Path("data").resolve()


def ensure_data_dir() -> Path:
    d = data_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"MEMAR cannot create its data directory {d}: {e}. "
            "Make sure the directory exists and is writable by the MEMAR user."
        ) from e
    return d


def _write_private(path: Path, text: str) -> None:
    """Create/replace a file readable only by the owner (0600), atomically."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


# ── JWT secret ────────────────────────────────────────────────────────────────

def load_or_create_jwt_secret() -> str:
    """MEMAR_JWT_SECRET if set; else a key generated once and kept in <data>/jwt-secret.

    A persisted key keeps sessions valid across restarts and upgrades. If the data
    directory is not writable, production refuses to start with a clear message;
    dev/test falls back to a per-process key.
    """
    env = os.getenv("MEMAR_JWT_SECRET")
    if env:
        return env
    production = os.getenv("MEMAR_ENV", "").lower() in ("production", "prod")
    try:
        path = ensure_data_dir() / _SECRET_FILE
        if path.exists():
            value = path.read_text(encoding="ascii").strip()
            if len(value) >= 32:
                return value
        value = secrets.token_hex(32)
        _write_private(path, value)
        logger.info("Generated a new signing key in %s", path)
        return value
    except (OSError, RuntimeError) as e:
        if production:
            raise RuntimeError(
                f"MEMAR could not store its signing key in {data_dir()}: {e}. "
                "Make the data directory writable, or set MEMAR_JWT_SECRET."
            ) from e
        logger.warning("Using a temporary signing key (%s); sessions end on restart.", e)
        return secrets.token_hex(32)


# ── Setup mode and window ─────────────────────────────────────────────────────

def setup_mode() -> str:
    raw = os.getenv("MEMAR_SETUP_MODE")
    if raw is None or not raw.strip():
        # Air-gap licences (defense / regulated sites) always require the code.
        try:
            from .license import get_license
            if str(get_license().tier).startswith("airgap"):
                return "code"
        except Exception:  # noqa: BLE001 - licence state unavailable: use the normal default
            pass
        return "auto"
    mode = raw.strip().lower()
    if mode not in _VALID_MODES:
        logger.warning("Unknown MEMAR_SETUP_MODE=%r; using 'code'", mode)
        return "code"
    return mode


def _window_seconds() -> int:
    try:
        minutes = float(os.getenv("MEMAR_SETUP_WINDOW_MIN", "10"))
    except ValueError:
        minutes = 10.0
    return max(0, int(minutes * 60))


def _window_start() -> float:
    """When the no-code window opened: persisted on the first unclaimed start so a
    restart (or a crash loop) does not hand out a fresh window. Falls back to
    this process's start when the data directory cannot be used."""
    path = data_dir() / _WINDOW_FILE
    try:
        value = float(path.read_text(encoding="ascii").strip())
        if 0 < value <= time.time() + 60:
            return value
    except (OSError, ValueError):
        pass
    value = time.time()
    try:
        ensure_data_dir()
        _write_private(path, f"{value:.0f}")
    except (OSError, RuntimeError):
        pass
    return value


def window_seconds_left() -> int:
    return max(0, int(_window_seconds() - (time.time() - _window_start())))


def code_required(client_ip: str | None = None) -> bool:
    """Whether this claim must carry the setup code.

    `client_ip` is the caller's address as seen by the server (trusted-proxy
    aware). In auto mode only private/loopback/tailnet clients may use the
    no-code window; a public client always needs the code. Callers that have
    no address (CLI, tests) are treated as public when one is required."""
    mode = setup_mode()
    if mode == "open":
        return False
    if mode == "code":
        return True
    if window_seconds_left() <= 0:
        return True
    return not is_private_client(client_ip)


# ── Setup code ────────────────────────────────────────────────────────────────

def normalize_code(code: str | None) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _code_path() -> Path:
    return data_dir() / _CODE_FILE


def get_or_create_setup_code() -> str:
    path = _code_path()
    try:
        if path.exists():
            value = normalize_code(path.read_text(encoding="ascii"))
            if len(value) == _CODE_LEN and all(c in _CODE_ALPHABET for c in value):
                return value
    except OSError:
        pass
    value = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
    ensure_data_dir()
    _write_private(path, value)
    return value


def new_setup_code() -> str:
    clear_setup_code()
    return get_or_create_setup_code()


def clear_setup_code() -> None:
    for name in (_CODE_FILE, _WINDOW_FILE):
        try:
            (data_dir() / name).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def verify_setup_code(candidate: str | None) -> bool:
    path = _code_path()
    try:
        stored = normalize_code(path.read_text(encoding="ascii"))
    except OSError:
        return False
    given = normalize_code(candidate)
    if not stored or not given:
        return False
    return hmac.compare_digest(stored.encode(), given.encode())


# ── Setup link ────────────────────────────────────────────────────────────────

def in_container() -> bool:
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    try:
        cg = Path("/proc/1/cgroup").read_text(errors="replace")
        return any(k in cg for k in ("docker", "containerd", "kubepods", "libpod"))
    except OSError:
        return False


def _primary_ip() -> str | None:
    """IP of the interface that carries the default route (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def port() -> str:
    """Port for links shown to people. In a container that is the host-side port
    (MEMAR_HOST_PORT, as in docker-compose.yml), not the one MEMAR listens on."""
    if in_container() and os.getenv("MEMAR_HOST_PORT", "").strip().isdigit():
        return os.environ["MEMAR_HOST_PORT"].strip()
    return os.getenv("MEMAR_PORT", "8000")


def public_base_url() -> str:
    """Base URL for links MEMAR sends (reset, invites, SSO callbacks).

    MEMAR_PUBLIC_URL when set; otherwise this host's LAN address and MEMAR_PORT
    (inside a container the host address is unknown, so localhost).
    """
    public = os.getenv("MEMAR_PUBLIC_URL", "").strip().rstrip("/")
    if public:
        return public
    ip = None if in_container() else _primary_ip()
    return f"http://{ip or 'localhost'}:{port()}"


def setup_links(code: str) -> list[tuple[str, str]]:
    """(label, url) pairs to show the owner. Several when we can't know the host address."""
    path = f"/setup?code={format_code(code)}"
    public = os.getenv("MEMAR_PUBLIC_URL", "").strip().rstrip("/")
    if public:
        return [("Open", public + path)]
    if in_container():
        return [
            ("On this computer", f"http://localhost:{port()}{path}"),
            ("From another device", f"http://<this-computer's-address>:{port()}{path}"),
        ]
    ip = _primary_ip()
    links = []
    if ip:
        links.append(("Open", f"http://{ip}:{port()}{path}"))
    host = socket.gethostname()
    if host and host != "localhost":
        links.append(("Or", f"http://{host}.local:{port()}{path}"))
    return links or [("Open", f"http://localhost:{port()}{path}")]


def print_setup_banner(code: str) -> None:
    """Print the setup link to stdout (docker logs / journalctl), never to the log file."""
    mode = setup_mode()
    lines = ["", "=" * 66, "  MEMAR is ready. Finish setup in your browser:", ""]
    for label, url in setup_links(code):
        lines.append(f"  {label}: {url}")
    lines += ["", f"  Setup code: {format_code(code)}"]
    if mode == "auto":
        lines.append(f"  (Code not needed for the first {_window_seconds() // 60} minutes after start.)")
    lines += ["  Lost this? Run: memar setup-link", "=" * 66, ""]
    print("\n".join(lines), file=sys.stdout, flush=True)

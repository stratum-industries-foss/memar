from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .models import FarmConfig, PrinterConfig

logger = logging.getLogger(__name__)

_config_lock = asyncio.Lock()


def _read_config_file_locked(path: Path) -> dict:
    """Read and return config dict, holding an exclusive file lock for the operation.

    H3 BUG FIX: Serializes config reads across multiple uvicorn workers. The asyncio.Lock
    only protects within a single process; fcntl.flock() serializes at the OS level.
    Used to close the TOCTOU window in read-modify-write cycles — readers hold the lock
    briefly to get a consistent view of the file.
    """
    with open(path, 'r') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return yaml.safe_load(f.read()) or {}
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _write_config_file_locked(path: Path, data: dict) -> None:
    """Write config dict with atomic rename, holding an exclusive file lock.

    H3 BUG FIX: Serializes config writes across multiple uvicorn workers via fcntl.flock.
    Writes to a temp file first, then atomically renames (single syscall, no window for
    partial writes to be read). The lock is held around both the write and rename so
    no reader can see an inconsistent state.
    """
    # Use exclusive lock for writes (LOCK_EX)
    lock_path = path.with_suffix('.lock')
    with open(lock_path, 'a') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            tmp = path.with_suffix('.tmp')
            _write_private_text(tmp, yaml.safe_dump(data, sort_keys=False))
            os.replace(tmp, path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_private_text(path: Path, text: str) -> None:
    """Write a config file readable only by MEMAR (0600): it can hold device API keys."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _REPO_ROOT / "config"
VERSION_FILE = _REPO_ROOT / "VERSION"
BUILD_ID_FILE = _REPO_ROOT / "BUILD_ID"


def get_config_path() -> Path:
    """Get config path: prefer devices.yaml, fall back to env var or default."""
    env_path = os.getenv("MEMAR_CONFIG_PATH")
    if env_path:
        return Path(env_path).resolve()
    return (_CONFIG_DIR / "devices.yaml").resolve()


@lru_cache(maxsize=1)
def get_config() -> FarmConfig:
    config_path = get_config_path()
    if not config_path.exists():
        _generate_config_from_discovery(config_path)
    data = yaml.safe_load(config_path.read_text()) or {}
    config = FarmConfig.model_validate(data)

    # T37: Fail-closed device limit enforcement at config load time.
    # If more printers are enabled than the license allows, disable the excess
    # (in-memory only — YAML is NOT modified). This ensures we never poll more
    # devices than the license permits, even if the config file was edited manually.
    from .license import get_license
    license_state = get_license()
    enabled = [p for p in config.printers if p.enabled]
    if len(enabled) > license_state.device_limit:
        logger.error(
            "License device limit exceeded: %d printers enabled but limit is %d. "
            "Excess printers will not be polled.",
            len(enabled), license_state.device_limit
        )
        # Mark excess printers as disabled (in-memory only)
        excess_count = len(enabled) - license_state.device_limit
        for printer in reversed(enabled):
            if excess_count <= 0:
                break
            printer.enabled = False
            excess_count -= 1

    return config


def _generate_config_from_discovery(config_path: Path) -> None:
    """Auto-discover printers and generate config file."""
    from .config_discovery import generate_config

    logger.info(f"Auto-generating config from discovered printers → {config_path}")
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = generate_config()
    _write_private_text(config_path, yaml.safe_dump(data, sort_keys=False))
    logger.info(f"Generated config with {len(data.get('printers', []))} printers")


def get_version() -> tuple[str, str]:
    version = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "0.0.0"
    build_id = BUILD_ID_FILE.read_text().strip() if BUILD_ID_FILE.exists() else "dev"
    return version, build_id


def reload_config_cache() -> None:
    get_config.cache_clear()


def _prune_backups(config_path: Path, keep: int = 10) -> None:
    """Delete old .bak-* backups, keeping the newest `keep` (lexical sort = chronological)."""
    backups = sorted(config_path.parent.glob(f"{config_path.name}.bak-*"))
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass


async def update_printer_fields(printer_id: str, updates: dict[str, Any], device_limit: int | None = None) -> tuple[dict[str, Any], Path, Path]:
    """Update printer config fields. Optionally enforce device-limit check on enable transition.

    H3 + H4 BUG FIX: File-level locking (fcntl) + asyncio.Lock serializes read-modify-write
    across all uvicorn workers. fcntl (OS-level) closes the multi-worker TOCTOU window; asyncio
    protects within a single worker. Device-limit check is done inside the lock (atomically
    with the write) to prevent concurrent enable requests from bypassing the limit.
    """
    async with _config_lock:
        config_path = get_config_path()
        loop = asyncio.get_running_loop()

        def _do_update():
            if not config_path.exists():
                raise FileNotFoundError(f"Device config not found: {config_path}")

            # H3 FIX: Read under file lock (exclusive access prevents concurrent reads/writes)
            data = _read_config_file_locked(config_path)
            printers = data.get("printers") or []
            target = None
            for printer in printers:
                if isinstance(printer, dict) and printer.get("id") == printer_id:
                    target = printer
                    break
            if target is None:
                raise KeyError(f"Printer not found in config: {printer_id}")

            # H4 FIX: Device-limit check inside the lock (atomically with the write)
            if device_limit is not None and updates.get('enabled') is True and not target.get('enabled', True):
                enabled_count = sum(
                    1 for p in printers if isinstance(p, dict) and p.get('enabled', True)
                )
                if enabled_count >= device_limit:
                    raise DeviceLimitReached(enabled_count, device_limit)

            target.update(updates)

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            backup_path = config_path.with_name(f"{config_path.name}.bak-{timestamp}")
            shutil.copy2(config_path, backup_path)
            _prune_backups(config_path)
            # H3 FIX: Write under file lock
            _write_config_file_locked(config_path, data)
            reload_config_cache()
            return target, config_path, backup_path

        target, config_path, backup_path = await loop.run_in_executor(None, _do_update)
        return target, config_path, backup_path


async def update_farm_fields(updates: dict[str, Any]) -> tuple[dict[str, Any], Path, Path]:
    """Update farm-level config fields (dashboard, presets, etc.).

    H3 BUG FIX: File-level locking (fcntl) + asyncio.Lock serializes across all uvicorn workers.
    """
    async with _config_lock:
        config_path = get_config_path()
        loop = asyncio.get_running_loop()

        def _do_update():
            if not config_path.exists():
                raise FileNotFoundError(f"Device config not found: {config_path}")

            # H3 FIX: Read under file lock
            data = _read_config_file_locked(config_path)
            data.update(updates)

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            backup_path = config_path.with_name(f"{config_path.name}.bak-{timestamp}")
            shutil.copy2(config_path, backup_path)
            _prune_backups(config_path)
            # H3 FIX: Write under file lock
            _write_config_file_locked(config_path, data)
            reload_config_cache()
            return data, config_path, backup_path

        data, config_path, backup_path = await loop.run_in_executor(None, _do_update)
        return data, config_path, backup_path


class DeviceLimitReached(Exception):
    """Raised when adding a device would exceed the license device limit."""

    def __init__(self, enabled_count: int, device_limit: int):
        self.enabled_count = enabled_count
        self.device_limit = device_limit
        super().__init__(
            f"Device limit reached ({enabled_count}/{device_limit})"
        )


class DuplicateDeviceId(Exception):
    """Raised when a device with the same id already exists."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        super().__init__(f"Device id already exists: {device_id}")


async def add_printer_to_config(printer: dict[str, Any], device_limit: int) -> int:
    """
    Atomically append a fully-formed printer dict to the config, enforcing the
    license device limit and id-uniqueness under a single lock hold.

    The count-check and the append MUST happen under the same _config_lock
    acquisition — otherwise two concurrent adds can both observe count < limit
    and both append (TOCTOU), exceeding the licensed seat count. This function
    is the single writer for new devices; callers pass the license device_limit.

    Returns the new enabled-device count. Raises DeviceLimitReached or
    DuplicateDeviceId (caller maps these to HTTP responses).
    """
    async with _config_lock:
        config_path = get_config_path()
        if not config_path.exists():
            raise FileNotFoundError(f"Device config not found: {config_path}")

        # H3 FIX: Read under file lock for multi-worker consistency
        data = _read_config_file_locked(config_path)
        printers = data.get("printers") or []

        # Uniqueness check (inside the lock).
        new_id = printer.get("id")
        if any(isinstance(p, dict) and p.get("id") == new_id for p in printers):
            raise DuplicateDeviceId(str(new_id))

        # Seat-limit check (inside the lock, against the same data we will write).
        enabled_count = sum(
            1 for p in printers if isinstance(p, dict) and p.get("enabled", True)
        )
        if printer.get("enabled", True) and enabled_count >= device_limit:
            raise DeviceLimitReached(enabled_count, device_limit)

        printers.append(printer)
        data["printers"] = printers

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = config_path.with_name(f"{config_path.name}.bak-{timestamp}")
        shutil.copy2(config_path, backup_path)
        _prune_backups(config_path)
        # H3 FIX: Write under file lock for multi-worker consistency
        _write_config_file_locked(config_path, data)
        reload_config_cache()

        new_enabled = sum(
            1 for p in printers if isinstance(p, dict) and p.get("enabled", True)
        )
        return new_enabled

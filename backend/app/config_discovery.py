"""Auto-discover Klipper/Moonraker installations and generate device config."""

import asyncio
import httpx
import logging
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def parse_printer_cfg(cfg_path: Path) -> dict[str, Any]:
    """Parse a Klipper printer.cfg and return structured hardware data.

    Returns a dict compatible with the KlipperConfig model fields.
    Only parses *active* (non-commented) config lines.
    """
    result: dict[str, Any] = {
        "kinematics": None,
        "max_velocity": None, "max_accel": None,
        "max_z_velocity": None, "max_z_accel": None,
        "square_corner_velocity": None,
        "x_max": None, "y_max": None, "z_max": None,
        "nozzle_diameter": None, "filament_diameter": None,
        "nozzle_max_temp": None, "nozzle_sensor_type": None,
        "pressure_advance": None, "gear_ratio": None,
        "rotation_distance": None, "microsteps_e": None,
        "bed_max_temp": None, "bed_sensor_type": None,
        "has_probe": False, "probe_type": None,
        "has_bed_mesh": False, "has_z_tilt": False,
        "has_quad_gantry_level": False,
        "has_safe_z_home": False, "has_homing_override": False,
        "sensorless_x": False, "sensorless_y": False,
        "mcu_serial": None,
        "tmc_drivers": [], "fan_count": 0, "heater_fan_count": 0,
        "controller_fan_count": 0,
        "include_files": [], "macro_names": [],
        "temperature_sensors": [], "parse_notes": [],
    }

    try:
        if not cfg_path.exists():
            result["parse_notes"].append(f"Config file not found: {cfg_path}")
            return result
        text = cfg_path.read_text(errors="replace")
    except Exception as e:
        result["parse_notes"].append(f"Read error: {e}")
        return result

    # --- helpers ---
    def _float(val: str) -> float | None:
        try:
            return float(val.strip())
        except (ValueError, AttributeError):
            return None

    def _int(val: str) -> int | None:
        try:
            return int(val.strip())
        except (ValueError, AttributeError):
            return None

    # Strip comments and split into sections.
    # A section header looks like [section_name] on its own line.
    sections: dict[str, dict[str, str]] = {}
    current_section: str | None = None
    for raw_line in text.splitlines():
        # Drop inline comments but preserve the rest
        line = re.sub(r'\s*#.*$', '', raw_line).strip()
        if not line:
            continue
        m = re.match(r'^\[([^\]]+)\]$', line)
        if m:
            current_section = m.group(1).strip()
            if current_section not in sections:
                sections[current_section] = {}
            continue
        if current_section is None:
            continue
        kv = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+)$', line)
        if kv:
            sections[current_section][kv.group(1)] = kv.group(2).strip()

    # --- [include ...] lines (handled separately — they don't have kv pairs) ---
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith('#'):
            continue
        m = re.match(r'^\[include\s+(.+)\]', stripped)
        if m:
            result["include_files"].append(m.group(1).strip())

    # --- [printer] ---
    printer_sec = sections.get("printer", {})
    result["kinematics"] = printer_sec.get("kinematics")
    result["max_velocity"] = _float(printer_sec.get("max_velocity", ""))
    result["max_accel"] = _float(printer_sec.get("max_accel", ""))
    result["max_z_velocity"] = _float(printer_sec.get("max_z_velocity", ""))
    result["max_z_accel"] = _float(printer_sec.get("max_z_accel", ""))
    result["square_corner_velocity"] = _float(printer_sec.get("square_corner_velocity", ""))

    # --- build volume from stepper position_max ---
    for axis, section_name in [("x", "stepper_x"), ("y", "stepper_y"), ("z", "stepper_z")]:
        sec = sections.get(section_name, {})
        v = _float(sec.get("position_max", ""))
        if v is not None:
            result[f"{axis}_max"] = v

    # --- [extruder] ---
    ext = sections.get("extruder", {})
    result["nozzle_diameter"] = _float(ext.get("nozzle_diameter", ""))
    result["filament_diameter"] = _float(ext.get("filament_diameter", ""))
    result["nozzle_max_temp"] = _float(ext.get("max_temp", ""))
    result["nozzle_sensor_type"] = ext.get("sensor_type")
    result["pressure_advance"] = _float(ext.get("pressure_advance", ""))
    result["gear_ratio"] = ext.get("gear_ratio")
    result["rotation_distance"] = _float(ext.get("rotation_distance", ""))
    result["microsteps_e"] = _int(ext.get("microsteps", ""))

    # --- [heater_bed] ---
    bed = sections.get("heater_bed", {})
    result["bed_max_temp"] = _float(bed.get("max_temp", ""))
    result["bed_sensor_type"] = bed.get("sensor_type")

    # --- probing ---
    for probe_sec in ["probe", "bltouch", "smart_effector", "dockable_probe"]:
        if probe_sec in sections:
            result["has_probe"] = True
            result["probe_type"] = probe_sec
            break
    result["has_bed_mesh"] = "bed_mesh" in sections
    result["has_z_tilt"] = "z_tilt" in sections
    result["has_quad_gantry_level"] = "quad_gantry_level" in sections
    result["has_safe_z_home"] = "safe_z_home" in sections
    result["has_homing_override"] = "homing_override" in sections

    # --- sensorless homing detection ---
    sx = sections.get("stepper_x", {})
    sy = sections.get("stepper_y", {})
    result["sensorless_x"] = "virtual_endstop" in sx.get("endstop_pin", "")
    result["sensorless_y"] = "virtual_endstop" in sy.get("endstop_pin", "")

    # --- [mcu] ---
    mcu_sec = sections.get("mcu", {})
    result["mcu_serial"] = mcu_sec.get("serial") or mcu_sec.get("canbus_uuid")

    # --- TMC drivers ---
    tmc_drivers = [s for s in sections if re.match(r'^tmc\d+\s+stepper_', s)]
    result["tmc_drivers"] = sorted(tmc_drivers)

    # --- fans ---
    result["fan_count"] = sum(1 for s in sections if s == "fan" or re.match(r'^fan\s+', s))
    result["heater_fan_count"] = sum(1 for s in sections if re.match(r'^heater_fan', s))
    result["controller_fan_count"] = sum(1 for s in sections if re.match(r'^controller_fan', s))

    # --- macros ---
    result["macro_names"] = sorted(
        re.sub(r'^gcode_macro\s+', '', s, flags=re.IGNORECASE)
        for s in sections if re.match(r'^gcode_macro\s+', s, re.IGNORECASE)
    )

    # --- temperature sensors ---
    result["temperature_sensors"] = sorted(
        re.sub(r'^temperature_sensor\s+', '', s, flags=re.IGNORECASE)
        for s in sections if re.match(r'^temperature_sensor\s+', s, re.IGNORECASE)
    )

    return result


def _is_systemd_service_enabled(printer_num: int) -> bool:
    """Check if moonraker-N.service is enabled in systemd."""
    try:
        result = subprocess.run(
            ["systemctl", "is-enabled", f"moonraker-{printer_num}.service"],
            capture_output=True,
            timeout=2,
        )
        is_enabled = result.returncode == 0
        return is_enabled
    except Exception as e:
        logger.warning(f"Failed to check systemd status for printer-{printer_num}: {e}")
        return False


def _fetch_printer_name_from_moonraker(port: int, printer_num: int) -> str | None:
    """Fetch printer name from Moonraker API.

    Priority:
    1. Fluidd uiSettings.general.instanceName (user-set in UI)
    2. /server/info machine_name / hostname / name fields
    3. None (falls through to config comment or default)
    """
    with httpx.Client(timeout=2) as client:
        # First, try Fluidd database for user-set name (highest priority)
        try:
            response = client.get(
                f"http://127.0.0.1:{port}/server/database/item?namespace=fluidd",
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 200:
                data = response.json()
                if "result" in data and isinstance(data["result"], dict):
                    result = data["result"]
                    if isinstance(result.get("value"), dict):
                        ui_settings = result["value"].get("uiSettings", {})
                        instance_name = ui_settings.get("general", {}).get("instanceName")
                        if instance_name:
                            name = str(instance_name).strip()
                            logger.debug(f"Found Fluidd instanceName for printer-{printer_num}: {name}")
                            return name
        except Exception as e:
            logger.debug(f"Could not fetch Fluidd instanceName for printer-{printer_num}: {e}")

        # Fall back to server/info fields
        try:
            response = client.get(
                f"http://127.0.0.1:{port}/server/info",
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 200:
                data = response.json()
                if "result" in data and isinstance(data["result"], dict):
                    result = data["result"]
                    for key in ["machine_name", "hostname", "name", "printer_name"]:
                        if key in result and result[key]:
                            name = str(result[key]).strip()
                            logger.debug(f"Found {key} for printer-{printer_num}: {name}")
                            return name
        except Exception as e:
            logger.debug(f"Could not fetch server/info for printer-{printer_num} on port {port}: {e}")

    return None


def _extract_printer_name_from_config(printer_cfg: Path) -> str | None:
    """Extract printer name from printer.cfg comment."""
    try:
        if not printer_cfg.exists():
            return None

        content = printer_cfg.read_text()

        # Look for explicit name comments
        # Patterns: # Name: Printer X, # Printer: X, # Machine: X
        for pattern in [
            r'#\s*(?:Name|Machine|Printer):\s*([^\n]+)',
            r'#\s*(?:Name|Machine|Printer)\s*=\s*([^\n]+)',
        ]:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if name and name != "":
                    return name

    except Exception as e:
        logger.debug(f"Failed to parse {printer_cfg}: {e}")

    return None


def discover_printer_instances(base_path: Path = None) -> list[dict[str, Any]]:
    """
    Discover Moonraker printer instances by scanning ~/printer_N_data directories.

    Fetches real printer names from Moonraker API, falls back to config files,
    then to printer_N naming. Only includes printers with enabled systemd services.
    """
    if base_path is None:
        base_path = Path.home()

    printers = []

    # Scan for printer_N_data directories
    for printer_dir in sorted(base_path.glob("printer_*_data")):
        if not printer_dir.is_dir():
            continue

        config_dir = printer_dir / "config"
        moonraker_conf = config_dir / "moonraker.conf"
        printer_cfg = config_dir / "printer.cfg"

        if not moonraker_conf.exists():
            continue

        # Extract printer number
        try:
            printer_num = int(printer_dir.name.split("_")[1])
        except (IndexError, ValueError):
            continue

        # Skip if systemd service is disabled
        if not _is_systemd_service_enabled(printer_num):
            logger.info(f"Skipping printer-{printer_num} (moonraker service disabled)")
            continue

        # Get port from moonraker.conf
        port = _extract_moonraker_port(moonraker_conf)
        if not port:
            continue

        # Fetch printer name with fallback chain:
        # 1. Query Moonraker API (real runtime name)
        # 2. Check printer.cfg comments
        # 3. Default to "Printer N"
        printer_name = (
            _fetch_printer_name_from_moonraker(port, printer_num)
            or _extract_printer_name_from_config(printer_cfg)
            or f"Printer {printer_num}"
        )

        # Parse printer.cfg for real hardware values
        hw = parse_printer_cfg(printer_cfg) if printer_cfg.exists() else {}

        # Build volume from stepper position_max (fall back to 0 if unknown)
        bv_x = hw.get("x_max") or 0
        bv_y = hw.get("y_max") or 0
        bv_z = hw.get("z_max") or 0

        # Nozzle diameter from extruder section
        nozzle_dia = hw.get("nozzle_diameter") or 0.4

        # Probe/filament sensor presence
        has_probe = hw.get("has_probe", False)
        # Filament sensor: check for [filament_switch_sensor *] or [filament_motion_sensor *]
        # (those sections are in the text; we re-scan quickly)
        has_filament_sensor = False
        try:
            cfg_text = printer_cfg.read_text(errors="replace") if printer_cfg.exists() else ""
            has_filament_sensor = bool(re.search(
                r'^\[filament_(?:switch|motion)_sensor', cfg_text, re.MULTILINE
            ))
        except Exception:
            pass

        # Safe max temps
        safe_nozzle_max = hw.get("nozzle_max_temp") or 300
        safe_bed_max = hw.get("bed_max_temp") or 120

        printer_config = {
            "id": f"printer-{printer_num}",
            "name": printer_name,
            "base_url": f"http://127.0.0.1:{port}",
            "ws_url": f"ws://127.0.0.1:{port}/websocket",
            "fluidd_url": f"http://printer-host:{4400 + printer_num}",
            "auth_mode": "trusted_local",
            "tags": ["printer-host", "core"],
            "compatibility_profile": None,
            "nozzle_diameter_mm": round(nozzle_dia, 3),
            "build_volume": {"x": bv_x, "y": bv_y, "z": bv_z},
            "supported_materials": ["PLA", "PETG", "ABS"],
            "current_material": "PLA",
            "current_spool_name": "Generic PLA White",
            "spool_remaining_g": 120 + (printer_num * 130) % 880,  # staggered so demo spools vary (RAG colors)
            "spool_capacity_g": 1000,
            "maintenance_state": "production",
            "maintenance_interval_hours": 120,
            "maintenance_interval_jobs": 80,
            "maintenance_interval_filament_g": 4000,
            # Staggered relative to today so a fresh demo shows a realistic mix
            # (some due, some upcoming) instead of a hardcode that goes stale.
            "last_service_at": (date.today() + timedelta(days=printer_num * 15 - 90)).isoformat(),
            "next_service_due": (date.today() + timedelta(days=printer_num * 15 - 30)).isoformat(),
            "filament_sensor": has_filament_sensor,
            "probe": has_probe,
            "webcam_expected": False,
            "safe_nozzle_max_c": safe_nozzle_max,
            "safe_bed_max_c": safe_bed_max,
            "enabled": True,
            "camera_url": None,
            "timelapse_dir": None,
            "maintenance_lockout": False,
            "maintenance_due": False,
            "jog_enabled": True,
            "motion_check_required": True,
            "notes": [],
            "maintenance_notes": [],
            "ui_targets": [],
            "api_key": None,
            "ui_label": "Open UI",
        }

        printers.append(printer_config)
        logger.info(f"Discovered {printer_name} at {printer_config['base_url']}")

    return printers


def _extract_moonraker_port(moonraker_conf: Path) -> int | None:
    """Extract port from [server] section of moonraker.conf."""
    try:
        content = moonraker_conf.read_text()
        match = re.search(r'\[server\].*?port:\s*(\d+)', content, re.DOTALL)
        if match:
            return int(match.group(1))
    except Exception as e:
        logger.warning(f"Failed to parse {moonraker_conf}: {e}")
    return None


def generate_config(base_path: Path = None) -> dict[str, Any]:
    """
    Generate complete MEMAR config by auto-discovering printers.

    Returns FarmConfig-compatible dictionary.
    """
    printers = discover_printer_instances(base_path)

    if not printers:
        logger.warning("No printer instances discovered. Using empty config.")
    else:
        logger.info(f"Discovered {len(printers)} printer instances")

    return {
        "printers": printers,
        "dashboard_settings": {
            "card_layout": "horizontal",
            "card_density": "comfortable",
            "show_card_preview": True,
            "show_metrics_strip": True,
            "show_oee": True,
            "show_empty_capability_tiles": False,
            "default_drawer_section": "overview",
            "metrics_history_limit": 50,
            "metrics_refresh_seconds": 15,
        },
        "material_presets": [],
    }

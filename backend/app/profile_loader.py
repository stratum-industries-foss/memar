"""
Printer profile loader for farm-mode deployments.

Profiles define machine-specific hardware constraints (build volume, heating limits,
probe type) and protocol-specific G-code sequences (start/end macros). MEMAR does
not generate G-code but uses profile macros as preambles/postambles when sending
commands to machines.

Profiles are loaded from YAML in /memar/profiles/ and can be assigned to printers
via the compatibility_profile field in devices.yaml.
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class PrinterProfile:
    """Represents a printer hardware profile."""

    def __init__(self, profile_id: str, profile_data: dict):
        self.id = profile_id
        self.machine_type = profile_data.get("machine_type", "fdm")
        self.protocol = profile_data.get("protocol", "moonraker")
        self.nozzle_diameter_mm = profile_data.get("nozzle_diameter_mm", 0.4)
        self.filament_diameter_mm = profile_data.get("filament_diameter_mm", 1.75)
        self.build_volume = profile_data.get("build_volume", {})
        self.probe = profile_data.get("probe", False)
        self.probe_type = profile_data.get("probe_type")
        self.filament_sensor = profile_data.get("filament_sensor", False)
        self.webcam_expected = profile_data.get("webcam_expected", False)
        self.safe_nozzle_max_c = profile_data.get("safe_nozzle_max_c")
        self.safe_bed_max_c = profile_data.get("safe_bed_max_c")
        self.maintenance_interval_hours = profile_data.get("maintenance_interval_hours")
        self.maintenance_interval_jobs = profile_data.get("maintenance_interval_jobs")
        self.maintenance_interval_filament_g = profile_data.get("maintenance_interval_filament_g")
        self.capabilities = profile_data.get("capabilities", {})
        self.start_gcode = profile_data.get("start_gcode", "")
        self.end_gcode = profile_data.get("end_gcode", "")
        self.notes = profile_data.get("notes", [])

    def to_printer_config_dict(self) -> dict:
        """Convert profile to printer config fields for merging into PrinterConfig."""
        return {
            "nozzle_diameter_mm": self.nozzle_diameter_mm,
            "filament_diameter_mm": self.filament_diameter_mm,
            "build_volume": self.build_volume,
            "probe": self.probe,
            "filament_sensor": self.filament_sensor,
            "webcam_expected": self.webcam_expected,
            "safe_nozzle_max_c": self.safe_nozzle_max_c,
            "safe_bed_max_c": self.safe_bed_max_c,
            "maintenance_interval_hours": self.maintenance_interval_hours,
            "maintenance_interval_jobs": self.maintenance_interval_jobs,
            "maintenance_interval_filament_g": self.maintenance_interval_filament_g,
        }


class ProfileLoader:
    """Loads printer profiles from disk and caches them."""

    def __init__(self, profiles_dir: Path = None):
        if profiles_dir is None:
            profiles_dir = Path(__file__).parent.parent.parent / "profiles"
        self.profiles_dir = profiles_dir
        self._cache: dict[str, PrinterProfile] = {}

    def list_profiles(self) -> list[str]:
        """List available profile IDs."""
        if not self.profiles_dir.exists():
            return []
        profile_files = list(self.profiles_dir.glob("*.yaml"))
        return [f.stem for f in profile_files]

    def load_profile(self, profile_id: str) -> Optional[PrinterProfile]:
        """Load a profile by ID (e.g., 'ender3' → loads ender3.yaml)."""
        if profile_id in self._cache:
            return self._cache[profile_id]

        profile_path = self.profiles_dir / f"{profile_id}.yaml"
        if not profile_path.exists():
            logger.warning(f"Profile not found: {profile_id}")
            return None

        try:
            with open(profile_path) as f:
                data = yaml.safe_load(f)
            profile = PrinterProfile(profile_id, data)
            self._cache[profile_id] = profile
            logger.info(f"Loaded profile: {profile_id}")
            return profile
        except Exception as e:
            logger.error(f"Failed to load profile {profile_id}: {e}")
            return None


# Singleton instance
_loader: Optional[ProfileLoader] = None


def get_profile_loader() -> ProfileLoader:
    """Get the global profile loader instance."""
    global _loader
    if _loader is None:
        _loader = ProfileLoader()
    return _loader


def get_profile(profile_id: str) -> Optional[PrinterProfile]:
    """Convenience function to load a profile."""
    return get_profile_loader().load_profile(profile_id)

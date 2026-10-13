"""Validation for printer settings and write operations."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SettingsValidator:
    """Validate changes before writing to Moonraker."""

    # Machine-type-agnostic safe ranges
    SAFE_RANGES = {
        "nozzle_temp": (150, 300),      # °C
        "bed_temp": (0, 120),           # °C
        "speed_factor": (0.1, 2.0),     # 10%-200%
        "extrude_factor": (0.5, 1.5),   # 50%-150%
        "nozzle_diameter_mm": (0.2, 1.0),  # mm
    }

    @classmethod
    def validate_temperature(
        cls,
        temp: float,
        temp_type: str = "nozzle",
    ) -> tuple[bool, str]:
        """Validate temperature is in safe range.

        Args:
            temp: Temperature value in Celsius
            temp_type: "nozzle" or "bed"

        Returns:
            (is_valid, error_message)
        """
        key = f"{temp_type}_temp"
        if key not in cls.SAFE_RANGES:
            return False, f"Unknown temperature type: {temp_type}"

        if temp is None:
            return True, ""  # None means "don't set"

        if not isinstance(temp, (int, float)):
            return False, f"Temperature must be a number, got {type(temp).__name__}"

        min_val, max_val = cls.SAFE_RANGES[key]

        if temp < min_val or temp > max_val:
            return False, f"{temp_type} temperature {temp}°C outside safe range {min_val}-{max_val}°C"

        return True, ""

    @classmethod
    def validate_speed_factor(cls, factor: float) -> tuple[bool, str]:
        """Validate speed factor is in safe range."""
        if factor is None:
            return True, ""

        if not isinstance(factor, (int, float)):
            return False, f"Speed factor must be a number, got {type(factor).__name__}"

        min_val, max_val = cls.SAFE_RANGES["speed_factor"]
        if factor < min_val or factor > max_val:
            return False, f"Speed factor {factor} outside safe range {min_val}-{max_val}"

        return True, ""

    @classmethod
    def validate_extrude_factor(cls, factor: float) -> tuple[bool, str]:
        """Validate extrude factor is in safe range."""
        if factor is None:
            return True, ""

        if not isinstance(factor, (int, float)):
            return False, f"Extrude factor must be a number, got {type(factor).__name__}"

        min_val, max_val = cls.SAFE_RANGES["extrude_factor"]
        if factor < min_val or factor > max_val:
            return False, f"Extrude factor {factor} outside safe range {min_val}-{max_val}"

        return True, ""

    @classmethod
    def validate_nozzle_diameter(cls, diameter_mm: float) -> tuple[bool, str]:
        """Validate nozzle diameter is in safe range."""
        if diameter_mm is None:
            return True, ""

        if not isinstance(diameter_mm, (int, float)):
            return False, f"Nozzle diameter must be a number, got {type(diameter_mm).__name__}"

        min_val, max_val = cls.SAFE_RANGES["nozzle_diameter_mm"]
        if diameter_mm < min_val or diameter_mm > max_val:
            return False, f"Nozzle diameter {diameter_mm}mm outside safe range {min_val}-{max_val}mm"

        return True, ""

    @classmethod
    def validate_settings_dict(cls, settings: dict) -> tuple[bool, list[str]]:
        """Validate a settings dictionary for batch updates.

        Args:
            settings: Dictionary with optional keys: nozzle_preset, bed_preset, speed_factor, extrude_factor, nozzle_diameter_mm

        Returns:
            (all_valid, list_of_errors)
        """
        errors = []

        if settings.get("nozzle_preset") is not None:
            valid, msg = cls.validate_temperature(settings["nozzle_preset"], "nozzle")
            if not valid:
                errors.append(msg)

        if settings.get("bed_preset") is not None:
            valid, msg = cls.validate_temperature(settings["bed_preset"], "bed")
            if not valid:
                errors.append(msg)

        if settings.get("speed_factor") is not None:
            valid, msg = cls.validate_speed_factor(settings["speed_factor"])
            if not valid:
                errors.append(msg)

        if settings.get("extrude_factor") is not None:
            valid, msg = cls.validate_extrude_factor(settings["extrude_factor"])
            if not valid:
                errors.append(msg)

        if settings.get("nozzle_diameter_mm") is not None:
            valid, msg = cls.validate_nozzle_diameter(settings["nozzle_diameter_mm"])
            if not valid:
                errors.append(msg)

        return len(errors) == 0, errors

    @classmethod
    def validate_temperature_set_request(cls, request: Any) -> tuple[bool, list[str]]:
        """Validate TemperatureSetRequest before sending to printer.

        Args:
            request: TemperatureSetRequest object

        Returns:
            (all_valid, list_of_errors)
        """
        errors = []

        if hasattr(request, "nozzle_target") and request.nozzle_target is not None:
            valid, msg = cls.validate_temperature(request.nozzle_target, "nozzle")
            if not valid:
                errors.append(msg)

        if hasattr(request, "bed_target") and request.bed_target is not None:
            valid, msg = cls.validate_temperature(request.bed_target, "bed")
            if not valid:
                errors.append(msg)

        if hasattr(request, "t1_nozzle") and request.t1_nozzle is not None:
            valid, msg = cls.validate_temperature(request.t1_nozzle, "nozzle")
            if not valid:
                errors.append(f"T1 nozzle: {msg}")

        return len(errors) == 0, errors

    @classmethod
    def validate_printer_settings_request(cls, request: Any) -> tuple[bool, list[str]]:
        """Validate PrinterSettingsUpdateRequest before saving.

        Args:
            request: PrinterSettingsUpdateRequest object

        Returns:
            (all_valid, list_of_errors)
        """
        errors = []

        if hasattr(request, "nozzle_diameter_mm") and request.nozzle_diameter_mm is not None:
            valid, msg = cls.validate_nozzle_diameter(request.nozzle_diameter_mm)
            if not valid:
                errors.append(msg)

        if hasattr(request, "safe_nozzle_max_c") and request.safe_nozzle_max_c is not None:
            valid, msg = cls.validate_temperature(request.safe_nozzle_max_c, "nozzle")
            if not valid:
                errors.append(f"Safe nozzle max: {msg}")

        if hasattr(request, "safe_bed_max_c") and request.safe_bed_max_c is not None:
            valid, msg = cls.validate_temperature(request.safe_bed_max_c, "bed")
            if not valid:
                errors.append(f"Safe bed max: {msg}")

        return len(errors) == 0, errors

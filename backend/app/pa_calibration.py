"""Pressure Advance calibration sweep generation.

Pure functions for creating deterministic PA sweep patterns.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class PABand:
    """Single band in PA calibration sweep."""
    band_index: int  # 0, 1, 2, ...
    pa_value: float  # e.g., 0.0, 0.05, 0.10
    z_height_mm: float | None = None  # Z after band (for visual reference)
    x_start_mm: float | None = None  # Band X extents (if side-by-side layout)
    x_end_mm: float | None = None
    y_start_mm: float | None = None  # Band Y extents
    y_end_mm: float | None = None


@dataclass
class PACalibrationModel:
    """Complete PA sweep metadata."""
    nozzle_diameter_mm: float
    filament_diameter_mm: float
    pa_start: float  # 0.0
    pa_end: float  # 0.15
    pa_step: float  # 0.01
    band_count: int  # computed: len(bands)
    bands: list[PABand] = field(default_factory=list)
    print_time_min: float | None = None
    filament_weight_g: float | None = None
    layout: Literal["vertical", "side_by_side", "spiral"] = "vertical"


def generate_pa_sweep_gcode(
    nozzle_diameter_mm: float = 0.4,
    filament_diameter_mm: float = 1.75,
    pa_start: float = 0.0,
    pa_end: float = 0.15,
    pa_step: float = 0.01,
    bed_x_max: float = 220.0,
    bed_y_max: float = 220.0,
    bed_z_max: float = 250.0,
    pattern: Literal["line", "box", "tower"] = "line",
) -> tuple[str, PACalibrationModel]:
    """Generate PA sweep G-code with labeled bands.

    Each band contains alternating fast/slow segments to expose PA artifacts
    (ghosting, underextrusion, corner bulge) at acceleration transitions.

    Args:
        nozzle_diameter_mm: Nozzle size (used for extrusion width calculation)
        filament_diameter_mm: Filament diameter (for extrusion calc)
        pa_start: PA value to start
        pa_end: PA value to end
        pa_step: Increment between bands
        bed_x_max, bed_y_max, bed_z_max: Build volume
        pattern: sweep pattern (line = X-axis bands, box = spiral, tower = vertical)

    Returns:
        (gcode: str, metadata: PACalibrationModel)

    Physics: PA artifacts only appear at velocity transitions and sharp corners.
    Pattern: 100 mm/s (fast) → 20 mm/s (slow) → 100 mm/s, repeated per band.
    """
    # Compute PA bands using integer arithmetic to avoid float accumulation
    if pa_step <= 0:
        raise ValueError("pa_step must be positive")
    band_count = int(round((pa_end - pa_start) / pa_step)) + 1
    pa_values = [round(pa_start + i * pa_step, 4) for i in range(band_count)]

    # Calculate extrusion per segment (layer height = nozzle_diameter * 0.75)
    layer_height_mm = nozzle_diameter_mm * 0.75
    filament_radius_mm = filament_diameter_mm / 2.0
    filament_area_mm2 = 3.14159 * (filament_radius_mm ** 2)
    nozzle_area_mm2 = 3.14159 * ((nozzle_diameter_mm / 2.0) ** 2)

    # Segment dimensions: 30 mm length, extrusion width = nozzle
    segment_length_mm = 30.0
    segment_extrusion_mm3 = segment_length_mm * nozzle_diameter_mm * layer_height_mm
    extrusion_mm = segment_extrusion_mm3 / filament_area_mm2

    bands = []
    band_y_pos = 30.0  # Start Y position (leave margin)
    # Calculate optimal spacing to fit all bands on bed with margins
    available_y = bed_y_max - 2 * band_y_pos  # Leave 30mm on each side
    band_y_spacing = available_y / band_count if band_count > 0 else 10.0
    band_y_spacing = max(8.0, band_y_spacing)  # Minimum 8mm spacing

    for i, pa_val in enumerate(pa_values):
        band = PABand(
            band_index=i,
            pa_value=pa_val,
            z_height_mm=layer_height_mm + i * layer_height_mm,  # Stack by layer height
            y_start_mm=band_y_pos + i * band_y_spacing,
            y_end_mm=band_y_pos + (i + 1) * band_y_spacing,
        )
        bands.append(band)

    metadata = PACalibrationModel(
        nozzle_diameter_mm=nozzle_diameter_mm,
        filament_diameter_mm=filament_diameter_mm,
        pa_start=pa_start,
        pa_end=pa_end,
        pa_step=pa_step,
        band_count=band_count,
        bands=bands,
        layout="vertical",
    )

    # Generate G-code
    gcode_lines = [
        "; === PA Calibration Sweep ===",
        f"; Nozzle: {nozzle_diameter_mm}mm, Filament: {filament_diameter_mm}mm",
        f"; Layer height: {layer_height_mm:.2f}mm, Extrusion/segment: {extrusion_mm:.3f}mm",
        f"; PA Range: {pa_start} → {pa_end} (step {pa_step})",
        f"; Band Count: {band_count}",
        "",
        "G21 ; metric",
        "G90 ; absolute positioning",
        "M104 S200 ; set hotend temp",
        "M140 S60 ; set bed temp",
        "M109 S200 ; wait for hotend",
        "M190 S60 ; wait for bed",
        "G28 ; home",
        "G29 ; mesh probe (if configured)",
        "G0 Z5 F1000 ; raise to print height",
        "",
    ]

    # Print each band: alternating fast/slow segments expose PA
    x_fast_mm = 100.0
    x_slow_mm = x_fast_mm + segment_length_mm + 5.0  # Gap between fast/slow segments
    x_return_mm = x_slow_mm + segment_length_mm + 5.0  # Return segment

    for band in bands:
        gcode_lines.append(f"; === Band {band.band_index}: PA={band.pa_value} ===")
        gcode_lines.append(f"SET_PRESSURE_ADVANCE ADVANCE={band.pa_value}")
        gcode_lines.append(f"G0 Z{band.z_height_mm:.2f} F1000")
        gcode_lines.append("")

        y_pos = band.y_start_mm
        # Fast segment (100 mm/s) → detects ghosting with high PA
        gcode_lines.append(f"G0 X{x_fast_mm} Y{y_pos} F3000 ; move to fast segment")
        gcode_lines.append(
            f"G1 X{x_fast_mm + segment_length_mm} Y{y_pos} F6000 E{extrusion_mm:.4f}"
        )
        gcode_lines.append("")

        # Slow segment (20 mm/s) → baseline for comparison
        gcode_lines.append(f"G0 X{x_slow_mm} Y{y_pos} F3000")
        gcode_lines.append(
            f"G1 X{x_slow_mm + segment_length_mm} Y{y_pos} F1200 E{extrusion_mm:.4f}"
        )
        gcode_lines.append("")

        # Return at fast speed (exposes underextrusion after direction reversal)
        gcode_lines.append(f"G0 X{x_return_mm} Y{y_pos} F3000")
        gcode_lines.append(
            f"G1 X{x_return_mm - segment_length_mm} Y{y_pos} F6000 E{extrusion_mm:.4f}"
        )
        gcode_lines.append("")

    # End sequence
    gcode_lines.extend([
        "G0 Z20 F1000",
        "M104 S0 ; turn off hotend",
        "M140 S0 ; turn off bed",
        "M84 ; motors off",
        "",
    ])

    gcode = "\n".join(gcode_lines)
    return gcode, metadata

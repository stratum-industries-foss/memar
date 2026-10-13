"""Spool / consumable deduction logic for all machine types.

Consumption model by machine type:
  FDM / IDEX  — filament_used_mm from Moonraker print_stats.
                length → mass: π × (d/2)² × L × density / 1000  (mm³ × g/cm³ / 1000 → g)
                filament diameter defaults to 1.75 mm if not known.
                density defaults per material keyword in current_material.

  SLA         — no per-mm length from Moonraker; estimate from layer count × layer_height
                × build_plate_area × fill_fraction × resin_density (1.1 g/cm³).
                Returns None if layer/volume data unavailable.

  Laser/Plasma/CNC/Waterjet/Vinyl/PnP/Embroidery/WireEDM
              — no mass consumption model applicable; returns (None, 'not_applicable').

The function returns (grams_used: float | None, method: str) where method describes
how the value was derived (for logging/audit trail).
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Material density table (g/cm³) — matched against current_material substring
# ---------------------------------------------------------------------------
_MATERIAL_DENSITY: list[tuple[str, float]] = [
    # FDM thermoplastics
    ("pla",     1.24),
    ("petg",    1.27),
    ("abs",     1.05),
    ("asa",     1.07),
    ("tpu",     1.21),
    ("tpe",     1.20),
    ("nylon",   1.13),
    ("pa",      1.13),
    ("pc",      1.20),
    ("pei",     1.27),
    ("ultem",   1.27),
    ("hips",    1.04),
    ("pva",     1.23),
    ("peek",    1.32),
    ("cf",      1.30),   # carbon-fibre composites
    ("carbon",  1.30),
    ("metal",   4.00),   # metal-fill / colorfabb stainless rough estimate
    ("wood",    1.15),
    # Wire EDM
    ("brass wire", 8.50),
    ("wire",    8.50),
]

_DEFAULT_FDM_DENSITY = 1.24   # PLA as safe default
_RESIN_DENSITY = 1.10          # typical photopolymer resin


def _material_density(material: str | None) -> float:
    if not material:
        return _DEFAULT_FDM_DENSITY
    m = material.lower()
    for keyword, density in _MATERIAL_DENSITY:
        if keyword in m:
            return density
    return _DEFAULT_FDM_DENSITY


def fdm_mm_to_grams(
    filament_used_mm: float,
    filament_diameter_mm: float = 1.75,
    material: str | None = None,
) -> float:
    """Convert extruded filament length (mm) to mass (g)."""
    radius_mm = filament_diameter_mm / 2.0
    volume_mm3 = math.pi * radius_mm ** 2 * filament_used_mm
    density = _material_density(material)          # g/cm³
    return round(volume_mm3 * density / 1000.0, 2) # mm³ → cm³ → g


def sla_layers_to_grams(
    layer_count: int,
    layer_height_mm: float,
    build_x_mm: float,
    build_y_mm: float,
    fill_fraction: float = 0.15,   # typical solid fraction of a layer
    resin_density: float = _RESIN_DENSITY,
) -> float:
    """Estimate resin consumed (g) from layer count + build volume."""
    volume_mm3 = layer_count * layer_height_mm * build_x_mm * build_y_mm * fill_fraction
    return round(volume_mm3 * resin_density / 1000.0, 2)


def compute_consumption(
    machine_type: str,
    *,
    filament_used_mm: float | None = None,
    filament_diameter_mm: float = 1.75,
    material: str | None = None,
    # SLA fields
    layer_count: int | None = None,
    layer_height_mm: float | None = None,
    build_x_mm: float | None = None,
    build_y_mm: float | None = None,
    # Wire EDM
    wire_used_mm: float | None = None,
    wire_diameter_mm: float = 0.25,
) -> tuple[float | None, str]:
    """
    Returns (grams_consumed, method_description).
    grams_consumed is None when the machine type has no mass model.
    """
    mt = (machine_type or "fdm").lower()

    # --- FDM / IDEX ---
    if mt in ("fdm", "idex", "marlin", "moonraker"):
        if filament_used_mm and filament_used_mm > 0:
            g = fdm_mm_to_grams(filament_used_mm, filament_diameter_mm, material)
            density = _material_density(material)
            return g, f"fdm_length: {filament_used_mm:.0f}mm × ø{filament_diameter_mm}mm × {density}g/cm³"
        return None, "fdm_no_length_data"

    # --- SLA / MSLA ---
    if mt in ("sla", "msla", "dlp", "lcd"):
        if layer_count and layer_height_mm and build_x_mm and build_y_mm:
            g = sla_layers_to_grams(layer_count, layer_height_mm, build_x_mm, build_y_mm)
            return g, f"sla_estimate: {layer_count}layers × {layer_height_mm}mm × {build_x_mm}×{build_y_mm}mm bed"
        return None, "sla_insufficient_data"

    # --- Wire EDM ---
    if mt in ("wire_edm",):
        if wire_used_mm and wire_used_mm > 0:
            g = fdm_mm_to_grams(wire_used_mm, wire_diameter_mm, "brass wire")
            return g, f"wire_edm: {wire_used_mm:.0f}mm × ø{wire_diameter_mm}mm brass"
        return None, "wire_edm_no_length_data"

    # --- Everything else: no mass model ---
    return None, "not_applicable"

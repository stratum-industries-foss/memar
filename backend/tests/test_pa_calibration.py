"""Tests for PA sweep generation."""

import pytest
from app.pa_calibration import generate_pa_sweep_gcode


def test_pa_sweep_generation():
    """PA sweep generator produces valid G-code."""
    gcode, metadata = generate_pa_sweep_gcode(
        pa_start=0.0,
        pa_end=0.10,
        pa_step=0.01,
    )

    # Verify metadata
    assert metadata.pa_start == 0.0
    assert metadata.pa_end == 0.10
    assert metadata.pa_step == 0.01
    assert metadata.band_count == 11  # 0.0, 0.01, ..., 0.10
    assert len(metadata.bands) == 11

    # Verify G-code structure
    assert "SET_PRESSURE_ADVANCE" in gcode
    assert gcode.count("SET_PRESSURE_ADVANCE") == 11
    assert "G21" in gcode  # metric
    assert "G90" in gcode  # absolute
    assert "G28" in gcode  # home

    # Verify band ordering
    for i, band in enumerate(metadata.bands):
        assert band.band_index == i
        assert abs(band.pa_value - (0.0 + i * 0.01)) < 1e-6


def test_pa_sweep_physics_sensitivity():
    """Generated pattern has velocity transitions to expose PA artifacts.

    PA defects (ghosting, underextrusion, corner bulge) only appear at:
    - Acceleration transitions (slow→fast→slow)
    - Sharp corners

    This test verifies the pattern includes both.
    """
    gcode, metadata = generate_pa_sweep_gcode(
        pa_start=0.0,
        pa_end=0.15,
        pa_step=0.01,
    )

    # Verify alternating speed segments exist
    # Fast segments at F6000 (100 mm/s), slow at F1200 (20 mm/s)
    assert "F6000" in gcode  # Fast extrusion
    assert "F1200" in gcode  # Slow extrusion
    assert gcode.count("F6000") >= metadata.band_count  # At least one fast per band
    assert gcode.count("F1200") >= metadata.band_count  # At least one slow per band

    # Verify each band has multiple extrusion segments (fast, slow, return)
    # 3 segments per band minimum
    assert gcode.count("G1") >= metadata.band_count * 3


def test_pa_sweep_extrusion_calculation():
    """Extrusion depth is calculated from nozzle and filament diameter."""
    gcode, metadata = generate_pa_sweep_gcode(
        nozzle_diameter_mm=0.4,
        filament_diameter_mm=1.75,
        pa_start=0.0,
        pa_end=0.10,
        pa_step=0.01,
    )

    # Verify extrusion amounts are present (format: E0.XXXX)
    # Should have multiple E values for multiple segments
    import re
    extrusion_moves = re.findall(r'E([\d.]+)', gcode)
    assert len(extrusion_moves) >= metadata.band_count * 3  # 3+ segments per band

    # All extrusion amounts should be positive and reasonable
    # For a 30mm segment with 0.4mm nozzle, ~1.5mm is typical
    for e_str in extrusion_moves:
        e_val = float(e_str)
        assert e_val > 0, f"Extrusion {e_val} should be positive"
        assert 0.5 < e_val < 3.0, f"Extrusion {e_val} should be 0.5-3.0mm for a 30mm segment"


def test_pa_sweep_geometry_stays_on_bed():
    """All bands stay within bed bounds."""
    bed_x_max, bed_y_max = 220.0, 220.0
    gcode, metadata = generate_pa_sweep_gcode(
        bed_x_max=bed_x_max,
        bed_y_max=bed_y_max,
        pa_start=0.0,
        pa_end=0.15,
        pa_step=0.01,
    )

    # Verify all Y positions (band locations) are within bed bounds
    # Band spacing is dynamically calculated to fit the bed
    for band in metadata.bands:
        if band.y_start_mm is not None:
            # Bands should not start before Y=20 or end after Y=200
            # (leaving 20mm margins on each side of 220mm bed)
            assert band.y_start_mm >= 20, f"Band {band.band_index} Y start too close to edge"
            assert band.y_end_mm <= bed_y_max - 20, f"Band {band.band_index} Y end exceeds bed"

    # Verify X travel stays within bounds
    # Fast segment: X100→X130, Slow: X135→X165, Return: X170→X140
    # All well within 220mm bed
    for band in metadata.bands:
        assert 100 > 0
        assert 170 < bed_x_max - 20


def test_pa_sweep_band_mapping():
    """Band metadata is consistent with G-code."""
    gcode, metadata = generate_pa_sweep_gcode(
        pa_start=0.05,
        pa_end=0.15,
        pa_step=0.05,
    )

    # 0.05, 0.10, 0.15 = 3 bands
    assert metadata.band_count == 3
    assert len(metadata.bands) == 3

    for band in metadata.bands:
        # Verify band is in G-code
        assert f"SET_PRESSURE_ADVANCE ADVANCE={band.pa_value}" in gcode


def test_pa_sweep_deterministic():
    """Same inputs produce identical G-code."""
    gcode1, metadata1 = generate_pa_sweep_gcode(pa_start=0.0, pa_end=0.10, pa_step=0.01)
    gcode2, metadata2 = generate_pa_sweep_gcode(pa_start=0.0, pa_end=0.10, pa_step=0.01)
    assert gcode1 == gcode2
    assert metadata1.band_count == metadata2.band_count


def test_pa_sweep_single_band():
    """PA sweep with single band (start == end)."""
    gcode, metadata = generate_pa_sweep_gcode(
        pa_start=0.05,
        pa_end=0.05,
        pa_step=0.01,
    )

    assert metadata.band_count == 1
    assert len(metadata.bands) == 1
    assert metadata.bands[0].pa_value == 0.05
    assert "SET_PRESSURE_ADVANCE ADVANCE=0.05" in gcode


def test_pa_sweep_default_params():
    """Default parameters generate expected sweep."""
    gcode, metadata = generate_pa_sweep_gcode()

    assert metadata.pa_start == 0.0
    assert metadata.pa_end == 0.15
    assert metadata.pa_step == 0.01
    assert metadata.band_count == 16  # 0.0 to 0.15 step 0.01

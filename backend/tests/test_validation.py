"""Tests for validation module (E5)."""

import pytest
from app.validation import SettingsValidator


# --- Temperature ---

def test_nozzle_temp_valid():
    ok, msg = SettingsValidator.validate_temperature(200, "nozzle")
    assert ok

def test_nozzle_temp_too_low():
    ok, msg = SettingsValidator.validate_temperature(100, "nozzle")
    assert not ok
    assert "150" in msg

def test_nozzle_temp_too_high():
    ok, msg = SettingsValidator.validate_temperature(400, "nozzle")
    assert not ok
    assert "300" in msg

def test_bed_temp_valid():
    ok, msg = SettingsValidator.validate_temperature(60, "bed")
    assert ok

def test_bed_temp_too_high():
    ok, msg = SettingsValidator.validate_temperature(130, "bed")
    assert not ok

def test_bed_temp_zero_ok():
    ok, msg = SettingsValidator.validate_temperature(0, "bed")
    assert ok

def test_unknown_temp_type():
    ok, msg = SettingsValidator.validate_temperature(200, "chamber")
    assert not ok

# --- Speed factor ---

def test_speed_factor_valid():
    ok, msg = SettingsValidator.validate_speed_factor(1.0)
    assert ok

def test_speed_factor_too_low():
    ok, msg = SettingsValidator.validate_speed_factor(0.05)
    assert not ok

def test_speed_factor_max_ok():
    ok, msg = SettingsValidator.validate_speed_factor(2.0)
    assert ok

def test_speed_factor_above_max():
    ok, msg = SettingsValidator.validate_speed_factor(2.5)
    assert not ok

# --- Extrude factor ---

def test_extrude_factor_valid():
    ok, msg = SettingsValidator.validate_extrude_factor(1.0)
    assert ok

def test_extrude_factor_too_low():
    ok, msg = SettingsValidator.validate_extrude_factor(0.3)
    assert not ok

def test_extrude_factor_too_high():
    ok, msg = SettingsValidator.validate_extrude_factor(2.0)
    assert not ok

# --- Nozzle diameter ---

def test_nozzle_diameter_valid():
    ok, msg = SettingsValidator.validate_nozzle_diameter(0.4)
    assert ok

def test_nozzle_diameter_common_sizes():
    for size in [0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]:
        ok, msg = SettingsValidator.validate_nozzle_diameter(size)
        assert ok, f"Expected {size}mm to be valid, got: {msg}"

def test_nozzle_diameter_too_small():
    ok, msg = SettingsValidator.validate_nozzle_diameter(0.1)
    assert not ok

def test_nozzle_diameter_too_large():
    ok, msg = SettingsValidator.validate_nozzle_diameter(1.5)
    assert not ok

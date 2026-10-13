"""
Tests for printer profiles.

Verifies that profile-declared G-code sequences differ only by expected kinematics
and offset values, not in incompatible ways (e.g., Ender 3's manual leveling macro
won't appear in Voron's QGL requirement).
"""

import pytest
from pathlib import Path

from app.profile_loader import ProfileLoader


class TestProfileLoading:

    @pytest.fixture
    def loader(self):
        profiles_dir = Path(__file__).parent.parent / "profiles"
        return ProfileLoader(profiles_dir)

    def test_load_ender3(self, loader):
        profile = loader.load_profile("ender3")
        assert profile is not None
        assert profile.machine_type == "fdm"
        assert profile.protocol == "moonraker"
        assert profile.build_volume == {"x": 235.0, "y": 235.0, "z": 250.0}
        assert profile.probe is False
        assert profile.safe_nozzle_max_c == 250.0
        assert profile.safe_bed_max_c == 100.0

    def test_load_prusa_mk3s_plus(self, loader):
        profile = loader.load_profile("prusa-mk3s-plus")
        assert profile is not None
        assert profile.machine_type == "fdm"
        assert profile.protocol == "prusa_connect"
        assert profile.build_volume == {"x": 250.0, "y": 210.0, "z": 210.0}
        assert profile.probe is True
        assert profile.probe_type == "pinda"
        assert profile.safe_nozzle_max_c == 280.0
        assert profile.safe_bed_max_c == 110.0

    def test_load_voron24(self, loader):
        profile = loader.load_profile("voron24")
        assert profile is not None
        assert profile.machine_type == "fdm"
        assert profile.protocol == "moonraker"
        assert profile.build_volume == {"x": 250.0, "y": 250.0, "z": 250.0}
        assert profile.probe is True
        assert profile.capabilities.get("quad_gantry_level") is True
        assert profile.safe_nozzle_max_c == 300.0

    def test_list_profiles(self, loader):
        profiles = loader.list_profiles()
        assert "ender3" in profiles
        assert "prusa-mk3s-plus" in profiles
        assert "voron24" in profiles


class TestGCodeDifferences:
    """
    Verify that G-code sequences differ only by kinematics and offsets,
    not in fundamentally incompatible ways.
    """

    @pytest.fixture
    def loader(self):
        profiles_dir = Path(__file__).parent.parent / "profiles"
        return ProfileLoader(profiles_dir)

    def test_start_gcode_kinematics_differences(self, loader):
        """
        Start sequences differ by:
        - Ender 3: No probe, manual leveling possible
        - Prusa: G80 mesh leveling (Prusa-specific)
        - Voron: QUAD_GANTRY_LEVEL then mesh (Klipper-specific)
        """
        ender3 = loader.load_profile("ender3")
        prusa = loader.load_profile("prusa-mk3s-plus")
        voron = loader.load_profile("voron24")

        # Allowed differences (kinematic groups):
        # Ender 3: no probe → no G80 or QGL
        assert "G80" not in ender3.start_gcode
        assert "QUAD_GANTRY_LEVEL" not in ender3.start_gcode
        assert "G29" in ender3.start_gcode  # Manual probe

        # Prusa: probe + Marlin → G80
        assert "G80" in prusa.start_gcode
        assert "QUAD_GANTRY_LEVEL" not in prusa.start_gcode  # Not Klipper

        # Voron: Klipper + moving gantry → QUAD_GANTRY_LEVEL
        assert "QUAD_GANTRY_LEVEL" in voron.start_gcode
        assert "G80" not in voron.start_gcode  # Not Prusa-specific

    def test_end_gcode_offset_differences(self, loader):
        """End sequences may differ in Z park height, but all turn off heaters."""
        ender3 = loader.load_profile("ender3")
        prusa = loader.load_profile("prusa-mk3s-plus")
        voron = loader.load_profile("voron24")

        for profile in [ender3, prusa, voron]:
            # All must disable heaters
            assert "M104 S0" in profile.end_gcode or "TURN_OFF_HEATERS" in profile.end_gcode
            assert "M140 S0" in profile.end_gcode or "TURN_OFF_HEATERS" in profile.end_gcode

    def test_temperature_limits_reasonable(self, loader):
        """Nozzle max temps must be realistic for hotend type."""
        ender3 = loader.load_profile("ender3")
        prusa = loader.load_profile("prusa-mk3s-plus")
        voron = loader.load_profile("voron24")

        # Stock Ender 3 heater (stock hotend max ~250°C)
        assert 200 <= ender3.safe_nozzle_max_c <= 270

        # Prusa with higher-end hotend (E3D Volcano, up to 280°C)
        assert 250 <= prusa.safe_nozzle_max_c <= 300

        # Voron with all-metal hotend (300°C capable)
        assert 280 <= voron.safe_nozzle_max_c <= 350

    def test_build_volume_ordering(self, loader):
        """Build volumes must have positive dimensions."""
        for profile_id in ["ender3", "prusa-mk3s-plus", "voron24"]:
            profile = loader.load_profile(profile_id)
            assert profile.build_volume.get("x") > 0
            assert profile.build_volume.get("y") > 0
            assert profile.build_volume.get("z") > 0

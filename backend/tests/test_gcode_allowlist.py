import pytest
from app.gcode_allowlist import validate_console_script


class TestValidateConsoleScript:
    def test_accepts_g28(self):
        assert validate_console_script("G28") == "G28"

    def test_accepts_g1_with_params(self):
        assert validate_console_script("G1 X100 Y50 F3000") == "G1 X100 Y50 F3000"

    def test_accepts_macro_with_params(self):
        assert validate_console_script("BED_MESH_CALIBRATE PROFILE=default") == "BED_MESH_CALIBRATE PROFILE=default"

    def test_strips_whitespace(self):
        assert validate_console_script("  G28  ") == "G28"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_console_script("")

    def test_rejects_multiline(self):
        with pytest.raises(ValueError, match="single line"):
            validate_console_script("G28\nM112")

    def test_rejects_semicolon(self):
        with pytest.raises(ValueError, match="semicolons"):
            validate_console_script("G28 ; comment")

    def test_rejects_save_config(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_console_script("SAVE_CONFIG")

    def test_rejects_m112(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_console_script("M112")

    def test_rejects_firmware_restart(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_console_script("FIRMWARE_RESTART")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="240"):
            validate_console_script("G1 " + "X1 " * 100)

    def test_rejects_invalid_pattern(self):
        with pytest.raises(ValueError, match="rejected"):
            validate_console_script("not a gcode command!")

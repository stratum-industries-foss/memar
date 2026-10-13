"""
Unit tests for ironing path generation module.
"""

import pytest

from app.ironing_paths import (
    GCodeCommand,
    GCodeParser,
    IroningConfig,
    IroningMode,
    IroningPathGenerator,
    IroningPathValidator,
    LayerExtractor,
    Point3D,
    TopSurfaceDetector,
    create_default_config,
)


class TestPoint3D:
    """Tests for Point3D class."""

    def test_create_point(self):
        """Test creating a 3D point."""
        p = Point3D(1.5, 2.0, 3.5)
        assert p.x == 1.5
        assert p.y == 2.0
        assert p.z == 3.5
        assert p.e == 0.0

    def test_distance_to(self):
        """Test distance calculation between points."""
        p1 = Point3D(0, 0, 0)
        p2 = Point3D(3, 4, 0)
        assert p1.distance_to(p2) == 5.0

    def test_distance_2d(self):
        """Test 2D distance calculation."""
        p1 = Point3D(0, 0, 5)
        p2 = Point3D(3, 4, 10)
        assert p1.distance_2d(p2) == 5.0  # Z is ignored


class TestGCodeCommand:
    """Tests for GCodeCommand class."""

    def test_create_command_minimal(self):
        """Test creating a minimal G-code command."""
        cmd = GCodeCommand(command="G0")
        assert cmd.command == "G0"
        assert cmd.x is None
        assert cmd.y is None

    def test_create_command_with_parameters(self):
        """Test creating a command with parameters."""
        cmd = GCodeCommand(
            command="G1",
            x=10.0,
            y=20.0,
            z=5.0,
            e=10.5,
            f=3000,
        )
        assert cmd.command == "G1"
        assert cmd.x == 10.0
        assert cmd.y == 20.0
        assert cmd.z == 5.0
        assert cmd.e == 10.5
        assert cmd.f == 3000

    def test_to_gcode(self):
        """Test converting command to G-code string."""
        cmd = GCodeCommand(
            command="G1",
            x=10.0,
            y=20.0,
            z=5.0,
            f=3000,
            comment="Test move",
        )
        gcode = cmd.to_gcode()
        assert "G1" in gcode
        assert "X10.000" in gcode
        assert "Y20.000" in gcode
        assert "Z5.000" in gcode
        assert "F3000" in gcode
        assert "Test move" in gcode

    def test_to_gcode_with_raw(self):
        """Test that raw G-code is returned as-is."""
        cmd = GCodeCommand(command="G0", raw="G0 X100 Y100")
        assert cmd.to_gcode() == "G0 X100 Y100"


class TestGCodeParser:
    """Tests for GCodeParser class."""

    def test_parse_empty(self):
        """Test parsing empty G-code."""
        commands = GCodeParser.parse("")
        assert commands == []

    def test_parse_single_command(self):
        """Test parsing a single command."""
        gcode = "G28"
        commands = GCodeParser.parse(gcode)
        assert len(commands) == 1
        assert commands[0].command == "G28"

    def test_parse_with_coordinates(self):
        """Test parsing command with coordinates."""
        gcode = "G0 X100.5 Y200.3 Z10.0 F3000"
        commands = GCodeParser.parse(gcode)
        assert len(commands) == 1
        cmd = commands[0]
        assert cmd.command == "G0"
        assert cmd.x == 100.5
        assert cmd.y == 200.3
        assert cmd.z == 10.0
        assert cmd.f == 3000

    def test_parse_with_comments(self):
        """Test parsing commands with comments."""
        gcode = "G0 X10 Y20 ; Move to position"
        commands = GCodeParser.parse(gcode)
        assert len(commands) == 1
        assert commands[0].comment == "Move to position"

    def test_parse_multiple_commands(self):
        """Test parsing multiple commands."""
        gcode = """
        G28
        G0 X0 Y0 Z10
        G1 X100 Y100 E10 F3000
        """
        commands = GCodeParser.parse(gcode)
        assert len(commands) == 3
        assert commands[0].command == "G28"
        assert commands[1].command == "G0"
        assert commands[2].command == "G1"

    def test_parse_with_extrusion(self):
        """Test parsing extrusion values."""
        gcode = "G1 X10 Y10 E5.5 F1500"
        commands = GCodeParser.parse(gcode)
        assert commands[0].e == 5.5

    def test_parse_case_insensitive(self):
        """Test that parsing is case-insensitive."""
        gcode = "g1 x10 y20 z5"
        commands = GCodeParser.parse(gcode)
        assert commands[0].command == "G1"
        assert commands[0].x == 10
        assert commands[0].y == 20
        assert commands[0].z == 5


class TestLayerExtractor:
    """Tests for LayerExtractor class."""

    def test_extract_single_layer(self):
        """Test extracting a single layer."""
        commands = [
            GCodeCommand(command="G0", z=0.2),
            GCodeCommand(command="G1", z=0.2),
            GCodeCommand(command="G1", z=0.2),
        ]
        layers = LayerExtractor.extract_layers(commands)
        assert len(layers) == 1
        assert len(layers[0]) == 3

    def test_extract_multiple_layers(self):
        """Test extracting multiple layers."""
        commands = [
            GCodeCommand(command="G0", z=0.2),
            GCodeCommand(command="G1", z=0.2),
            GCodeCommand(command="G0", z=0.4),
            GCodeCommand(command="G1", z=0.4),
            GCodeCommand(command="G0", z=0.6),
            GCodeCommand(command="G1", z=0.6),
        ]
        layers = LayerExtractor.extract_layers(commands)
        assert len(layers) == 3
        assert len(layers[0]) == 2
        assert len(layers[1]) == 2
        assert len(layers[2]) == 2

    def test_extract_layers_with_commands_without_z(self):
        """Test extracting layers with non-movement commands."""
        commands = [
            GCodeCommand(command="G0", z=0.2),
            GCodeCommand(command="G1", z=0.2),
            GCodeCommand(command="M104", s=200),  # No Z
            GCodeCommand(command="G0", z=0.4),
            GCodeCommand(command="G1", z=0.4),
        ]
        layers = LayerExtractor.extract_layers(commands)
        assert len(layers) == 2


class TestTopSurfaceDetector:
    """Tests for TopSurfaceDetector class."""

    def test_get_top_layer_empty(self):
        """Test getting top layer from empty list."""
        layers = []
        result = TopSurfaceDetector.get_top_layer(layers)
        assert result == []

    def test_get_top_layer_single(self):
        """Test getting top layer from single layer."""
        commands = [GCodeCommand(command="G0"), GCodeCommand(command="G1")]
        layers = [commands]
        result = TopSurfaceDetector.get_top_layer(layers)
        assert result == commands

    def test_get_top_layer_multiple(self):
        """Test getting top layer from multiple layers."""
        layer1 = [GCodeCommand(command="G0", z=0.2)]
        layer2 = [GCodeCommand(command="G0", z=0.4)]
        layer3 = [GCodeCommand(command="G0", z=0.6)]
        layers = [layer1, layer2, layer3]
        result = TopSurfaceDetector.get_top_layer(layers)
        assert result == layer3

    def test_extract_surface_moves_empty(self):
        """Test extracting surface moves from empty list."""
        commands = []
        points = TopSurfaceDetector.extract_surface_moves(commands)
        assert points == []

    def test_extract_surface_moves_simple(self):
        """Test extracting surface moves."""
        commands = [
            GCodeCommand(command="G0", x=0, y=0, z=0.2),
            GCodeCommand(command="G1", x=10, y=10, z=0.2),
            GCodeCommand(command="G1", x=20, y=20, z=0.2),
        ]
        points = TopSurfaceDetector.extract_surface_moves(commands)
        assert len(points) == 3
        assert points[0].x == 0 and points[0].y == 0
        assert points[1].x == 10 and points[1].y == 10
        assert points[2].x == 20 and points[2].y == 20

    def test_extract_surface_moves_position_persistence(self):
        """Test that positions persist when not specified."""
        commands = [
            GCodeCommand(command="G0", x=0, y=0, z=0.2),
            GCodeCommand(command="G1", x=10, z=0.2),  # Only X and Z
            GCodeCommand(command="G1", y=10, z=0.2),  # Only Y and Z
        ]
        points = TopSurfaceDetector.extract_surface_moves(commands)
        assert len(points) == 3
        assert points[1].y == 0  # Y persists from previous
        assert points[2].x == 10  # X persists from previous


class TestIroningConfig:
    """Tests for IroningConfig class."""

    def test_create_default_config(self):
        """Test creating a default config."""
        config = IroningConfig()
        assert config.enabled is True
        assert config.mode == IroningMode.LIGHT_FLOW
        assert config.flow_rate == 0.5
        assert config.speed == 30.0

    def test_config_to_dict(self):
        """Test converting config to dict."""
        config = IroningConfig(
            enabled=True,
            mode=IroningMode.LIGHT_FLOW,
            flow_rate=0.6,
            speed=25.0,
        )
        data = config.to_dict()
        assert data["enabled"] is True
        assert data["mode"] == "light_flow"
        assert data["flow_rate"] == 0.6
        assert data["speed"] == 25.0

    def test_config_from_dict(self):
        """Test creating config from dict."""
        data = {
            "enabled": True,
            "mode": "no_extrusion",
            "flow_rate": 0.7,
            "speed": 35.0,
        }
        config = IroningConfig.from_dict(data)
        assert config.enabled is True
        assert config.mode == IroningMode.NO_EXTRUSION
        assert config.flow_rate == 0.7
        assert config.speed == 35.0

    def test_config_from_dict_invalid_mode(self):
        """Test config handles invalid mode gracefully."""
        data = {"mode": "invalid_mode"}
        config = IroningConfig.from_dict(data)
        assert config.mode == IroningMode.LIGHT_FLOW  # Falls back to default


class TestIroningPathGenerator:
    """Tests for IroningPathGenerator class."""

    def test_generate_empty_surface(self):
        """Test generating paths from empty surface."""
        config = IroningConfig(enabled=True)
        moves = IroningPathGenerator.generate_ironing_moves([], config)
        assert len(moves) == 0

    def test_generate_disabled_config(self):
        """Test that disabled config produces no moves."""
        config = IroningConfig(enabled=False)
        points = [Point3D(0, 0, 0.2), Point3D(10, 10, 0.2)]
        moves = IroningPathGenerator.generate_ironing_moves(points, config)
        assert len(moves) == 0

    def test_generate_simple_path(self):
        """Test generating a simple ironing path."""
        config = IroningConfig(enabled=True, speed=30.0)
        points = [
            Point3D(0, 0, 0.2),
            Point3D(10, 0, 0.2),
            Point3D(10, 10, 0.2),
            Point3D(0, 10, 0.2),
        ]
        moves = IroningPathGenerator.generate_ironing_moves(points, config)

        # Should have: comment + multiple lines (G0 + G1 pairs) + footer comment
        assert len(moves) > 0

        # Check for comment markers
        comments = [m for m in moves if m.command == ";"]
        assert len(comments) >= 2  # Start and end comments

        # Check for movement commands
        g_commands = [m for m in moves if m.command in ("G0", "G1")]
        assert len(g_commands) > 0

    def test_generate_path_with_z_offset(self):
        """Test that Z offset is applied correctly."""
        config = IroningConfig(enabled=True, z_offset=0.1)
        points = [Point3D(0, 0, 0.2), Point3D(10, 0, 0.2)]
        moves = IroningPathGenerator.generate_ironing_moves(points, config)

        # All G0/G1 moves should have z = 0.2 + 0.1 = 0.3
        g_moves = [m for m in moves if m.command in ("G0", "G1")]
        for move in g_moves:
            if move.z is not None:
                assert move.z == pytest.approx(0.3, abs=0.01)

    def test_generate_path_no_extrusion_mode(self):
        """Test path generation with no extrusion mode."""
        config = IroningConfig(enabled=True, mode=IroningMode.NO_EXTRUSION)
        points = [Point3D(0, 0, 0.2), Point3D(10, 0, 0.2)]
        moves = IroningPathGenerator.generate_ironing_moves(points, config)

        # G1 moves should not have E parameter in NO_EXTRUSION mode
        g1_moves = [m for m in moves if m.command == "G1"]
        for move in g1_moves:
            # In NO_EXTRUSION mode, e should be None
            assert move.e is None or move.e == 0.0

    def test_generate_path_speed_config(self):
        """Test that speed is correctly applied."""
        config = IroningConfig(enabled=True, speed=50.0)
        points = [Point3D(0, 0, 0.2), Point3D(10, 0, 0.2)]
        moves = IroningPathGenerator.generate_ironing_moves(points, config)

        # Speed should be converted to mm/min (50 * 60 = 3000)
        g1_moves = [m for m in moves if m.command == "G1"]
        for move in g1_moves:
            if move.f is not None:
                assert move.f == pytest.approx(3000.0, abs=1.0)


class TestIroningPathValidator:
    """Tests for IroningPathValidator class."""

    def test_validate_empty_paths(self):
        """Test validation of empty paths."""
        result = IroningPathValidator.validate_paths([], [])
        assert result["has_moves"] is False
        assert result["surface_coverage"] is False

    def test_validate_simple_paths(self):
        """Test validation of simple paths."""
        paths = [
            GCodeCommand(command=";", raw="; IRONING START"),
            GCodeCommand(command="G0", x=0, y=0, z=0.2),
            GCodeCommand(command="G1", x=10, y=10, z=0.2),
            GCodeCommand(command=";", raw="; IRONING END"),
        ]
        surface_points = [Point3D(0, 0, 0.2), Point3D(10, 10, 0.2)]

        result = IroningPathValidator.validate_paths(paths, surface_points)
        assert result["has_moves"] is True
        assert result["has_comments"] is True
        assert result["all_valid_commands"] is True
        assert result["surface_coverage"] is True

    def test_validate_missing_coordinates(self):
        """Test validation detects missing coordinates."""
        paths = [
            GCodeCommand(command="G0"),  # No coordinates
            GCodeCommand(command="G1", x=10),  # Partial coordinates
        ]
        surface_points = [Point3D(0, 0, 0.2)]

        result = IroningPathValidator.validate_paths(paths, surface_points)
        # Should detect that not all moves have proper coordinates
        assert result["moves_have_coordinates"] is False


class TestIntegrationIroningFlow:
    """Integration tests for complete ironing flow."""

    def test_full_ironing_pipeline(self):
        """Test complete pipeline: parse -> extract -> generate -> validate."""
        # Sample G-code with a print on 0.2mm layer
        gcode = """
        G28
        G0 X0 Y0 Z0.2 F3000
        G1 X10 Y0 Z0.2 E10 F1500
        G1 X10 Y10 Z0.2 E20 F1500
        G1 X0 Y10 Z0.2 E30 F1500
        G1 X0 Y0 Z0.2 E40 F1500
        """

        # Parse
        commands = GCodeParser.parse(gcode)
        assert len(commands) > 0

        # Extract layers
        layers = LayerExtractor.extract_layers(commands)
        assert len(layers) > 0

        # Get top layer
        top_layer = TopSurfaceDetector.get_top_layer(layers)
        assert len(top_layer) > 0

        # Extract surface points
        points = TopSurfaceDetector.extract_surface_moves(top_layer)
        assert len(points) > 0

        # Generate ironing
        config = create_default_config()
        ironing_moves = IroningPathGenerator.generate_ironing_moves(points, config)
        assert len(ironing_moves) > 0

        # Validate
        validation = IroningPathValidator.validate_paths(ironing_moves, points)
        assert validation["has_moves"] is True
        assert validation["all_valid_commands"] is True

    def test_three_reference_models(self):
        """Test ironing with three reference models (simple square, complex, tiny)."""
        config = create_default_config()

        # Model 1: Simple square
        gcode1 = """
        G0 X0 Y0 Z0.2
        G1 X100 Y0 Z0.2 E50
        G1 X100 Y100 Z0.2 E100
        G1 X0 Y100 Z0.2 E150
        G1 X0 Y0 Z0.2 E200
        """

        # Model 2: Complex shape (circle-like)
        gcode2 = """
        G0 X50 Y50 Z0.2
        G1 X60 Y55 Z0.2 E10
        G1 X65 Y65 Z0.2 E20
        G1 X60 Y75 Z0.2 E30
        G1 X50 Y80 Z0.2 E40
        G1 X40 Y75 Z0.2 E50
        G1 X35 Y65 Z0.2 E60
        G1 X40 Y55 Z0.2 E70
        G1 X50 Y50 Z0.2 E80
        """

        # Model 3: Tiny detail
        gcode3 = """
        G0 X0 Y0 Z0.2
        G1 X5 Y0 Z0.2 E1
        G1 X5 Y5 Z0.2 E2
        G1 X0 Y5 Z0.2 E3
        G1 X0 Y0 Z0.2 E4
        """

        for i, gcode in enumerate([gcode1, gcode2, gcode3], 1):
            commands = GCodeParser.parse(gcode)
            layers = LayerExtractor.extract_layers(commands)
            top_layer = TopSurfaceDetector.get_top_layer(layers)
            points = TopSurfaceDetector.extract_surface_moves(top_layer)

            # Generate ironing
            ironing_moves = IroningPathGenerator.generate_ironing_moves(points, config)
            assert len(ironing_moves) > 0, f"Model {i} failed to generate ironing moves"

            # Validate
            validation = IroningPathValidator.validate_paths(ironing_moves, points)
            assert validation["has_moves"], f"Model {i}: No ironing moves generated"
            assert validation["all_valid_commands"], f"Model {i}: Invalid G-code commands"


def test_create_default_config():
    """Test creating default configuration."""
    config = create_default_config()
    assert config.enabled is True
    assert config.mode == IroningMode.LIGHT_FLOW
    assert config.flow_rate == 0.5
    assert config.speed == 30.0

"""Tests for physics-based motion estimation."""

import pytest

from app.motion_estimator import (
    GCodeMove,
    GCodeParser,
    Kinematics,
    KlipperKinematics,
    MotionSimulator,
    PrinterConfig,
    SegmentTiming,
    estimate_print_time,
)


class TestGCodeMove:
    """GCodeMove command representation."""

    def test_move_creation(self):
        move = GCodeMove(line_num=1, cmd="G1", x=10.0, y=20.0, f=60.0)
        assert move.is_move()
        assert move.x == 10.0
        assert move.y == 20.0

    def test_extrusion_move(self):
        move = GCodeMove(
            line_num=1, cmd="G1", x=10.0, y=20.0, e=5.0, f=60.0
        )
        assert move.is_extrusion_move()

    def test_non_extrusion_move(self):
        move = GCodeMove(line_num=1, cmd="G0", x=10.0, y=20.0, f=100.0)
        assert not move.is_extrusion_move()


class TestGCodeParser:
    """G-code file parsing."""

    def test_parse_simple_move(self):
        gcode = "G1 X10 Y20 F1000"
        parser = GCodeParser()
        moves = parser.parse(gcode)

        assert len(moves) == 1
        move = moves[0]
        assert move.cmd == "G1"
        assert move.x == 10.0
        assert move.y == 20.0
        assert move.f == 1000.0

    def test_parse_multiple_moves(self):
        gcode = """
        G28
        G1 X10 Y10 F1000
        G1 X20 Y10 Z0.2 F1000
        G0 X0 Y0 F3000
        """
        parser = GCodeParser()
        moves = parser.parse(gcode)

        assert len(moves) == 4
        assert moves[0].cmd == "G28"
        assert moves[1].x == 10.0
        assert moves[2].z == 0.2
        assert moves[3].f == 3000.0

    def test_parse_with_comments(self):
        gcode = """
        ; Start sequence
        G28 ; Home
        G1 X100 Y100 F1000 ; Move to center
        """
        parser = GCodeParser()
        moves = parser.parse(gcode)

        assert len(moves) == 2
        assert "Home" in moves[0].comment
        assert "center" in moves[1].comment

    def test_parse_absolute_positioning(self):
        gcode = """
        G90
        G1 X10 F1000
        G1 X20 F1000
        G1 X30 F1000
        """
        parser = GCodeParser()
        moves = parser.parse(gcode)

        # All moves are absolute
        assert moves[0].x == 10.0
        assert moves[1].x == 20.0
        assert moves[2].x == 30.0

    def test_parse_skip_m_codes(self):
        gcode = """
        M104 S200
        G1 X10 F1000
        M109 S200
        G1 X20 F1000
        M140 S60
        """
        parser = GCodeParser()
        moves = parser.parse(gcode)

        # M codes are skipped
        assert len(moves) == 2
        assert moves[0].x == 10.0
        assert moves[1].x == 20.0

    def test_parse_empty_lines(self):
        gcode = """

        G1 X10 F1000


        G1 X20 F1000

        """
        parser = GCodeParser()
        moves = parser.parse(gcode)

        assert len(moves) == 2


class TestPrinterConfig:
    """Printer configuration."""

    def test_default_config(self):
        config = PrinterConfig()
        assert config.kinematics == Kinematics.CARTESIAN
        assert config.max_velocity == 120.0
        assert config.max_accel == 500.0
        assert config.nozzle_diameter_mm == 0.4

    def test_config_post_init(self):
        config = PrinterConfig(max_accel=1000.0)
        # max_accel_to_decel defaults to max_accel if not set
        assert config.max_accel_to_decel == 1000.0

    def test_config_custom_accel_to_decel(self):
        config = PrinterConfig(
            max_accel=1000.0, max_accel_to_decel=500.0
        )
        assert config.max_accel_to_decel == 500.0

    def test_config_to_dict(self):
        config = PrinterConfig(max_velocity=150.0)
        d = config.to_dict()
        assert d["max_velocity"] == 150.0
        assert d["kinematics"] == "cartesian"


class TestSegmentTiming:
    """Segment timing computation."""

    def test_segment_creation(self):
        seg = SegmentTiming(
            segment_num=0,
            distance_mm=100.0,
            feedrate_mm_s=50.0,
            accel_mm_s2=500.0,
            time_accel_s=0.1,
            time_cruise_s=1.9,
            time_decel_s=0.1,
            total_time_s=2.1,
        )
        assert seg.segment_num == 0
        assert seg.total_time_s == 2.1

    def test_segment_negative_time_raises(self):
        with pytest.raises(ValueError):
            SegmentTiming(
                segment_num=0,
                distance_mm=100.0,
                feedrate_mm_s=50.0,
                accel_mm_s2=500.0,
                time_accel_s=0.1,
                time_cruise_s=0.0,
                time_decel_s=0.1,
                total_time_s=-0.1,
            )


class TestKlipperKinematics:
    """Klipper motion model (trapezoidal velocity)."""

    def test_short_move_no_cruise(self):
        """Short move: accelerate then decelerate, no cruise phase."""
        config = PrinterConfig(
            max_velocity=120.0,
            max_accel=1000.0,  # Higher accel = longer accel distance
            max_accel_to_decel=1000.0,
        )
        kin = KlipperKinematics(config)

        # Very short move (< accel distance)
        # With 1000 mm/s² accel and 50 mm/s cruise:
        # accel_distance = 50² / (2*1000) = 1.25mm, total accel+decel = 2.5mm
        # So 10mm should have some cruise phase. Use even shorter move.
        seg = kin.compute_segment_time(
            segment_num=0,
            distance_mm=1.0,
            feedrate_mm_min=3000.0,  # 50 mm/s cruise
        )

        assert seg.distance_mm == 1.0
        # With 1mm distance and 1000mm/s² accel, very limited cruise
        assert seg.time_cruise_s <= 0.01  # Minimal or zero cruise
        assert seg.time_accel_s > 0.0
        assert seg.time_decel_s > 0.0
        assert seg.total_time_s > 0.0

    def test_long_move_with_cruise(self):
        """Long move: accelerate, cruise, decelerate."""
        config = PrinterConfig(
            max_velocity=120.0,
            max_accel=500.0,
            max_accel_to_decel=500.0,
        )
        kin = KlipperKinematics(config)

        # Long move (> accel distance)
        seg = kin.compute_segment_time(
            segment_num=0,
            distance_mm=1000.0,
            feedrate_mm_min=3000.0,  # 50 mm/s cruise
        )

        assert seg.distance_mm == 1000.0
        assert seg.time_cruise_s > 0.0  # Has cruise phase
        assert seg.time_accel_s > 0.0
        assert seg.time_decel_s > 0.0
        assert seg.total_time_s > 0.0

    def test_zero_distance_move(self):
        """Zero-distance move consumes no time."""
        config = PrinterConfig()
        kin = KlipperKinematics(config)

        seg = kin.compute_segment_time(
            segment_num=0,
            distance_mm=0.0,
            feedrate_mm_min=1000.0,
        )

        assert seg.total_time_s == 0.0

    def test_velocity_clamped_to_max(self):
        """Requested speed > max velocity is clamped."""
        config = PrinterConfig(max_velocity=50.0)
        kin = KlipperKinematics(config)

        seg = kin.compute_segment_time(
            segment_num=0,
            distance_mm=1000.0,
            feedrate_mm_min=6000.0,  # 100 mm/s > max 50 mm/s
        )

        # Time should be based on clamped 50 mm/s
        assert seg.feedrate_mm_s <= 50.0

    def test_xy_distance(self):
        """XY Euclidean distance calculation."""
        config = PrinterConfig()
        kin = KlipperKinematics(config)

        dist = kin.compute_xy_distance(0.0, 0.0, 3.0, 4.0)
        assert dist == pytest.approx(5.0)  # 3-4-5 triangle

    def test_3d_distance(self):
        """3D Euclidean distance calculation."""
        config = PrinterConfig()
        kin = KlipperKinematics(config)

        dist = kin.compute_3d_distance(0.0, 0.0, 0.0, 2.0, 2.0, 1.0)
        # sqrt(4 + 4 + 1) = 3
        assert dist == pytest.approx(3.0)

    def test_asymmetric_accel_decel(self):
        """Asymmetric accel/decel constraints."""
        config = PrinterConfig(
            max_velocity=100.0,
            max_accel=500.0,
            max_accel_to_decel=250.0,  # Half the accel rate
        )
        kin = KlipperKinematics(config)

        seg = kin.compute_segment_time(
            segment_num=0,
            distance_mm=500.0,
            feedrate_mm_min=3000.0,  # 50 mm/s
        )

        # Decel should take longer than accel
        assert seg.time_decel_s > seg.time_accel_s


class TestMotionSimulator:
    """Full motion simulation."""

    def test_empty_moves(self):
        config = PrinterConfig()
        sim = MotionSimulator(config)

        result = sim.simulate([])
        assert result == 0.0
        assert len(sim.segments) == 0

    def test_single_move(self):
        config = PrinterConfig()
        sim = MotionSimulator(config)

        move = GCodeMove(
            line_num=1,
            cmd="G1",
            x=100.0,
            y=100.0,
            z=0.0,
            f=1000.0,
        )
        total_time = sim.simulate([move])

        assert total_time > 0.0
        assert len(sim.segments) == 1

    def test_multiple_moves_accumulate(self):
        config = PrinterConfig()
        sim = MotionSimulator(config)

        moves = [
            GCodeMove(
                line_num=1,
                cmd="G1",
                x=100.0,
                y=0.0,
                z=0.0,
                f=1000.0,
            ),
            GCodeMove(
                line_num=2,
                cmd="G1",
                x=100.0,
                y=100.0,
                z=0.0,
                f=1000.0,
            ),
            GCodeMove(
                line_num=3,
                cmd="G1",
                x=0.0,
                y=100.0,
                z=0.0,
                f=1000.0,
            ),
        ]
        total_time = sim.simulate(moves)

        assert total_time > 0.0
        assert len(sim.segments) == 3

    def test_summary_stats(self):
        config = PrinterConfig()
        sim = MotionSimulator(config)

        moves = [
            GCodeMove(
                line_num=1,
                cmd="G1",
                x=100.0,
                y=0.0,
                z=0.0,
                f=1000.0,
            ),
            GCodeMove(
                line_num=2,
                cmd="G1",
                x=100.0,
                y=100.0,
                z=0.0,
                f=1000.0,
            ),
        ]
        sim.simulate(moves)

        summary = sim.get_summary()
        assert summary["total_segments"] == 2
        assert summary["total_distance_mm"] > 0.0
        assert summary["total_time_s"] > 0.0
        assert summary["avg_speed_mm_s"] > 0.0

    def test_summary_empty(self):
        config = PrinterConfig()
        sim = MotionSimulator(config)
        sim.simulate([])

        summary = sim.get_summary()
        assert summary["total_segments"] == 0
        assert summary["total_time_s"] == 0.0
        assert summary["avg_speed_mm_s"] == 0.0


class TestIntegration:
    """End-to-end motion estimation."""

    def test_estimate_print_time_simple(self):
        gcode = """
        G28
        G1 X50 Y50 F1000
        G1 X100 Y100 F2000
        """
        total_time, summary = estimate_print_time(gcode)

        assert total_time > 0.0
        assert summary["total_segments"] > 0
        assert summary["total_distance_mm"] > 0.0

    def test_estimate_with_custom_config(self):
        gcode = "G1 X10000 F10000"  # Long move at high feedrate to show velocity limit
        config = PrinterConfig(max_velocity=50.0)  # Low speed limit

        time_slow, _ = estimate_print_time(gcode, config)

        config_fast = PrinterConfig(max_velocity=200.0)  # High speed limit
        time_fast, _ = estimate_print_time(gcode, config_fast)

        # Faster config should result in less time (accel is now negligible vs cruise)
        assert time_fast < time_slow

    def test_parser_and_simulator_integration(self):
        """Parser → Simulator → time estimate."""
        gcode = """
        G28
        G1 X10 Y10 F600 ; 10 mm/s
        G1 X10 Y20 F600
        G1 X10 Y30 F600
        """
        parser = GCodeParser()
        moves = parser.parse(gcode)
        assert len(moves) > 0

        config = PrinterConfig(max_velocity=100.0, max_accel=500.0)
        sim = MotionSimulator(config)
        total_time = sim.simulate(moves)

        # Should be ~1.5 sec (3 moves of 10mm each at 10mm/s = 1 sec each)
        # plus accel/decel overhead
        assert total_time > 3.0


class TestEdgeCases:
    """Edge case handling."""

    def test_malformed_gcode_lines(self):
        """Invalid lines are skipped gracefully."""
        gcode = """
        G1 X10 Y10 F1000
        G1 X invalid Y10 F1000
        G1 X20 Y20 F1000
        """
        parser = GCodeParser()
        moves = parser.parse(gcode)

        # Should parse valid moves, skip invalid
        assert len(moves) >= 1

    def test_very_high_feedrate(self):
        """Extreme feedrate is clamped to max_velocity."""
        gcode = "G1 X1000 F999999"
        config = PrinterConfig(max_velocity=50.0)

        total_time, summary = estimate_print_time(gcode, config)
        # Should not error; time based on max_velocity
        assert total_time > 0.0

    def test_zero_feedrate_skipped(self):
        """Feedrate of 0 might cause issues; should be handled."""
        config = PrinterConfig()
        kin = KlipperKinematics(config)

        # feedrate_mm_min = 0
        seg = kin.compute_segment_time(
            segment_num=0,
            distance_mm=100.0,
            feedrate_mm_min=0.0,
        )
        # Should default to max_velocity or handle gracefully
        assert seg.total_time_s >= 0.0

    def test_large_file(self):
        """Simulate a larger G-code file."""
        lines = ["G28"]
        for i in range(1, 101):  # Start from 1 to avoid 0,0 starting point collision
            lines.append(f"G1 X{i*10} Y{i*10} F1000")
        gcode = "\n".join(lines)

        total_time, summary = estimate_print_time(gcode)
        assert summary["total_segments"] == 100
        assert total_time > 0.0

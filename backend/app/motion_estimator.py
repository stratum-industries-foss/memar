"""Physics-based print-time estimation using Klipper motion model.

Implements trapezoidal velocity profile simulation for FDM printers.
Kinematics: Cartesian (XY gantry) + CoreXY support.
Calibration: empirical from job_log data.

References:
  - Klipper stepper.c: (velocity, accel) → time per segment
  - RepRap wiki: G-code, motion planning
  - Real-world farm data: job_log (predicted vs actual)
"""

import dataclasses
import logging
import math
import re
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Kinematics(str, Enum):
    """Supported kinematic systems."""
    CARTESIAN = "cartesian"  # Standard XY gantry
    COREXYZ = "corexyz"      # CoreXY (dual belt)
    DELTA = "delta"          # Delta (deferred phase 2)


class GCodeMove:
    """Single G-code move command parsed from gcode."""

    def __init__(
        self,
        line_num: int,
        cmd: str,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        e: float | None = None,
        f: float | None = None,  # feedrate mm/min
        comment: str = "",
    ):
        self.line_num = line_num
        self.cmd = cmd  # "G1", "G0", "G28", etc
        self.x = x
        self.y = y
        self.z = z
        self.e = e
        self.f = f
        self.comment = comment

    def is_move(self) -> bool:
        """True if this is a linear move (G1 or G0)."""
        return self.cmd in ("G1", "G0")

    def is_extrusion_move(self) -> bool:
        """True if E axis changes (active extrusion)."""
        return self.e is not None and self.e != 0

    def __repr__(self) -> str:
        parts = [f"G{self.cmd[-1]}"]
        if self.x is not None:
            parts.append(f"X{self.x:.2f}")
        if self.y is not None:
            parts.append(f"Y{self.y:.2f}")
        if self.z is not None:
            parts.append(f"Z{self.z:.2f}")
        if self.e is not None:
            parts.append(f"E{self.e:.3f}")
        if self.f is not None:
            parts.append(f"F{self.f:.1f}")
        return f"<{' '.join(parts)}>"


@dataclasses.dataclass
class PrinterConfig:
    """Printer hardware constraints extracted from Klipper config."""
    kinematics: Kinematics = Kinematics.CARTESIAN
    max_velocity: float = 120.0  # mm/s
    max_accel: float = 500.0     # mm/s²
    max_accel_to_decel: float | None = None  # if None, use max_accel
    square_corner_velocity: float = 5.0      # mm/s, junction decel
    # Extruder constraints
    max_e_velocity: float = 25.0  # mm/s
    max_e_accel: float = 300.0    # mm/s²
    # Nozzle/filament
    nozzle_diameter_mm: float = 0.4
    filament_diameter_mm: float = 1.75

    def __post_init__(self):
        if self.max_accel_to_decel is None:
            self.max_accel_to_decel = self.max_accel

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for calibration logging."""
        return {
            "kinematics": self.kinematics.value,
            "max_velocity": self.max_velocity,
            "max_accel": self.max_accel,
            "max_accel_to_decel": self.max_accel_to_decel,
            "square_corner_velocity": self.square_corner_velocity,
            "max_e_velocity": self.max_e_velocity,
            "max_e_accel": self.max_e_accel,
            "nozzle_diameter_mm": self.nozzle_diameter_mm,
            "filament_diameter_mm": self.filament_diameter_mm,
        }


@dataclasses.dataclass
class SegmentTiming:
    """Computed segment time using trapezoidal profile."""
    segment_num: int
    distance_mm: float
    feedrate_mm_s: float  # cruise speed after accel
    accel_mm_s2: float
    time_accel_s: float   # time in acceleration phase
    time_cruise_s: float  # time at cruise speed
    time_decel_s: float   # time in deceleration phase
    total_time_s: float

    def __post_init__(self):
        """Validate computed fields."""
        if self.total_time_s < 0:
            raise ValueError(f"Negative segment time: {self.total_time_s}s")

    def __repr__(self) -> str:
        return (
            f"<Segment #{self.segment_num}: "
            f"{self.distance_mm:.2f}mm @ {self.feedrate_mm_s:.1f}mm/s, "
            f"t={self.total_time_s:.3f}s>"
        )


class GCodeParser:
    """Parse G-code file into moves."""

    def __init__(self):
        self.moves: list[GCodeMove] = []
        self._current_x: float = 0.0
        self._current_y: float = 0.0
        self._current_z: float = 0.0
        self._current_e: float = 0.0
        self._current_f: float = 60.0  # default 60 mm/min

    def parse(self, gcode_text: str) -> list[GCodeMove]:
        """Parse gcode string into move list.

        Handles:
          - G0/G1 (rapid/linear move)
          - G28/G29 (homing, probing; counted as moves for time budget)
          - M104/M109/M140/M190 (thermal, no time)
          - Comments (stripped)
        """
        self.moves.clear()
        lines = gcode_text.strip().split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Strip comments
            comment = ""
            if ";" in line:
                line, comment = line.split(";", 1)
                comment = comment.strip()

            line = line.strip()
            if not line:
                continue

            # Parse command
            move = self._parse_line(line, line_num, comment)
            if move:
                self.moves.append(move)

        logger.info(f"Parsed {len(self.moves)} moves from {len(lines)} lines")
        return self.moves

    def _parse_line(self, line: str, line_num: int, comment: str) -> GCodeMove | None:
        """Parse single G-code line."""
        tokens = line.split()
        if not tokens:
            return None

        cmd = tokens[0].upper()

        # Skip non-move commands
        if cmd.startswith("M"):
            # M codes (motors, heater, fan) don't consume time
            return None

        # Extract move parameters
        x, y, z, e, f = None, None, None, None, None
        for token in tokens[1:]:
            if token.startswith("X"):
                try:
                    x = float(token[1:])
                except ValueError:
                    pass
            elif token.startswith("Y"):
                try:
                    y = float(token[1:])
                except ValueError:
                    pass
            elif token.startswith("Z"):
                try:
                    z = float(token[1:])
                except ValueError:
                    pass
            elif token.startswith("E"):
                try:
                    e = float(token[1:])
                except ValueError:
                    pass
            elif token.startswith("F"):
                try:
                    f = float(token[1:])
                except ValueError:
                    pass

        # Update current position (absolute positioning assumed)
        if x is not None:
            self._current_x = x
        if y is not None:
            self._current_y = y
        if z is not None:
            self._current_z = z
        if e is not None:
            self._current_e = e
        if f is not None:
            self._current_f = f

        if cmd in ("G0", "G1", "G28", "G29"):
            return GCodeMove(
                line_num=line_num,
                cmd=cmd,
                x=self._current_x,
                y=self._current_y,
                z=self._current_z,
                e=self._current_e,
                f=self._current_f,
                comment=comment,
            )

        return None


class KlipperKinematics:
    """Compute segment timing using Klipper motion model."""

    def __init__(self, config: PrinterConfig):
        self.config = config

    def compute_segment_time(
        self,
        segment_num: int,
        distance_mm: float,
        feedrate_mm_min: float,
    ) -> SegmentTiming:
        """Compute time for one segment using trapezoidal velocity profile.

        Klipper motion planning:
          1. Cruise speed = feedrate (mm/min) → (mm/s)
          2. Accel/decel = max_accel
          3. If distance < accel distance, ramp up then down with no cruise

        Args:
            segment_num: Sequential segment ID
            distance_mm: XY/Z distance for this segment
            feedrate_mm_min: Requested feedrate (mm/min)

        Returns:
            SegmentTiming with accel/cruise/decel phases
        """
        if distance_mm <= 0.0001:
            # Zero-distance moves consume no time
            return SegmentTiming(
                segment_num=segment_num,
                distance_mm=distance_mm,
                feedrate_mm_s=0.0,
                accel_mm_s2=0.0,
                time_accel_s=0.0,
                time_cruise_s=0.0,
                time_decel_s=0.0,
                total_time_s=0.0,
            )

        # Convert feedrate to mm/s
        cruise_speed_mm_s = feedrate_mm_min / 60.0
        cruise_speed_mm_s = min(cruise_speed_mm_s, self.config.max_velocity)

        accel = self.config.max_accel
        decel = self.config.max_accel_to_decel

        # Distance needed to reach cruise speed (half accel, half decel)
        accel_distance = cruise_speed_mm_s ** 2 / (2.0 * accel)
        decel_distance = cruise_speed_mm_s ** 2 / (2.0 * decel)
        min_distance = accel_distance + decel_distance

        if distance_mm < min_distance:
            # Ramp up then down; never reach cruise speed
            # Solve: accel_dist + decel_dist = distance
            # (v_peak^2 / (2*a)) + (v_peak^2 / (2*d)) = distance
            # v_peak^2 * (1/(2*a) + 1/(2*d)) = distance
            # v_peak = sqrt(distance / (1/(2*a) + 1/(2*d)))
            v_peak_sq = distance_mm / (1.0 / (2.0 * accel) + 1.0 / (2.0 * decel))
            if v_peak_sq < 0:
                v_peak_sq = 0
            v_peak = math.sqrt(v_peak_sq)

            time_accel_s = v_peak / accel if accel > 0 else 0.0
            time_decel_s = v_peak / decel if decel > 0 else 0.0
            time_cruise_s = 0.0
        else:
            # Reach cruise speed, maintain, then decel
            time_accel_s = cruise_speed_mm_s / accel if accel > 0 else 0.0
            time_decel_s = cruise_speed_mm_s / decel if decel > 0 else 0.0
            cruise_distance = distance_mm - accel_distance - decel_distance
            time_cruise_s = cruise_distance / cruise_speed_mm_s if cruise_speed_mm_s > 0 else 0.0
            v_peak = cruise_speed_mm_s

        total_time_s = time_accel_s + time_cruise_s + time_decel_s

        return SegmentTiming(
            segment_num=segment_num,
            distance_mm=distance_mm,
            feedrate_mm_s=v_peak,
            accel_mm_s2=accel,
            time_accel_s=time_accel_s,
            time_cruise_s=time_cruise_s,
            time_decel_s=time_decel_s,
            total_time_s=total_time_s,
        )

    def compute_xy_distance(
        self, x0: float, y0: float, x1: float, y1: float
    ) -> float:
        """Compute XY plane distance (Euclidean)."""
        dx = x1 - x0
        dy = y1 - y0
        return math.sqrt(dx * dx + dy * dy)

    def compute_3d_distance(
        self, x0: float, y0: float, z0: float, x1: float, y1: float, z1: float
    ) -> float:
        """Compute 3D Euclidean distance."""
        dx = x1 - x0
        dy = y1 - y0
        dz = z1 - z0
        return math.sqrt(dx * dx + dy * dy + dz * dz)


class MotionSimulator:
    """Simulate print motion and compute total time."""

    def __init__(self, config: PrinterConfig):
        self.config = config
        self.kinematics = KlipperKinematics(config)
        self.segments: list[SegmentTiming] = []

    def simulate(self, moves: list[GCodeMove]) -> float:
        """Simulate motion and return estimated total time (seconds).

        Ignores thermal time (M104 S200, M190 S60) — only motion.
        """
        self.segments.clear()
        total_time_s = 0.0

        x_prev, y_prev, z_prev = 0.0, 0.0, 0.0
        segment_num = 0

        for move in moves:
            if not move.is_move():
                continue

            x_curr = move.x if move.x is not None else x_prev
            y_curr = move.y if move.y is not None else y_prev
            z_curr = move.z if move.z is not None else z_prev
            feedrate_mm_min = move.f if move.f is not None else 60.0

            # Distance (XYZ)
            distance = self.kinematics.compute_3d_distance(
                x_prev, y_prev, z_prev, x_curr, y_curr, z_curr
            )

            if distance > 0.0001:  # Only time moves with real distance
                segment = self.kinematics.compute_segment_time(
                    segment_num=segment_num,
                    distance_mm=distance,
                    feedrate_mm_min=feedrate_mm_min,
                )
                self.segments.append(segment)
                total_time_s += segment.total_time_s
                segment_num += 1

            x_prev, y_prev, z_prev = x_curr, y_curr, z_curr

        logger.info(
            f"Simulated {len(self.segments)} segments, "
            f"total time: {total_time_s:.1f}s ({total_time_s/60:.1f}min)"
        )
        return total_time_s

    def get_summary(self) -> dict[str, Any]:
        """Return timing summary."""
        if not self.segments:
            return {
                "total_segments": 0,
                "total_time_s": 0.0,
                "avg_speed_mm_s": 0.0,
                "total_distance_mm": 0.0,
            }

        total_time = sum(s.total_time_s for s in self.segments)
        total_distance = sum(s.distance_mm for s in self.segments)

        return {
            "total_segments": len(self.segments),
            "total_time_s": total_time,
            "total_distance_mm": total_distance,
            "avg_speed_mm_s": total_distance / total_time if total_time > 0 else 0.0,
            "avg_accel_phase_pct": (
                100.0
                * sum(s.time_accel_s for s in self.segments)
                / total_time
                if total_time > 0
                else 0.0
            ),
        }


def estimate_print_time(
    gcode_text: str,
    config: PrinterConfig = None,
) -> tuple[float, dict[str, Any]]:
    """Estimate print time from G-code text.

    Args:
        gcode_text: Full G-code file as string
        config: PrinterConfig; if None, uses defaults

    Returns:
        (total_time_s, summary_dict)
    """
    if config is None:
        config = PrinterConfig()

    parser = GCodeParser()
    moves = parser.parse(gcode_text)

    simulator = MotionSimulator(config)
    total_time_s = simulator.simulate(moves)

    return total_time_s, simulator.get_summary()

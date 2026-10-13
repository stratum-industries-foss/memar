"""
Ironing path generation for 3D printing.

Ironing is a technique that runs a non-extruding or low-flow pass over the
top surface of a print to flatten and smooth the layer. This module handles:
- Top surface path detection and extraction
- Flow/speed configuration for ironing passes
- Path optimization and smoothing
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class IroningMode(Enum):
    """Ironing modes controlling extrusion behavior."""
    NO_EXTRUSION = "no_extrusion"  # Don't extrude during ironing (pure pressing)
    LIGHT_FLOW = "light_flow"  # Extrude at reduced flow rate
    MEDIUM_FLOW = "medium_flow"  # Extrude at medium reduced flow rate


@dataclass
class IroningConfig:
    """Configuration for ironing passes."""
    enabled: bool = True
    mode: IroningMode = IroningMode.LIGHT_FLOW
    flow_rate: float = 0.5  # Fraction of normal flow (0.0-1.0)
    speed: float = 30.0  # mm/s
    z_offset: float = 0.0  # mm offset from top surface
    pattern_spacing: float = 1.0  # mm between parallel ironing lines
    reverse_direction: bool = False  # Reverse ironing direction

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "enabled": self.enabled,
            "mode": self.mode.value,
            "flow_rate": self.flow_rate,
            "speed": self.speed,
            "z_offset": self.z_offset,
            "pattern_spacing": self.pattern_spacing,
            "reverse_direction": self.reverse_direction,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IroningConfig:
        """Deserialize from dictionary."""
        mode_str = data.get("mode", "light_flow")
        try:
            mode = IroningMode(mode_str)
        except ValueError:
            mode = IroningMode.LIGHT_FLOW

        return cls(
            enabled=data.get("enabled", True),
            mode=mode,
            flow_rate=float(data.get("flow_rate", 0.5)),
            speed=float(data.get("speed", 30.0)),
            z_offset=float(data.get("z_offset", 0.0)),
            pattern_spacing=float(data.get("pattern_spacing", 1.0)),
            reverse_direction=bool(data.get("reverse_direction", False)),
        )


@dataclass
class Point3D:
    """3D point with X, Y, Z coordinates."""
    x: float
    y: float
    z: float
    e: float = 0.0  # Extrusion amount

    def distance_to(self, other: Point3D) -> float:
        """Calculate Euclidean distance to another point."""
        return math.sqrt(
            (self.x - other.x) ** 2 +
            (self.y - other.y) ** 2 +
            (self.z - other.z) ** 2
        )

    def distance_2d(self, other: Point3D) -> float:
        """Calculate 2D distance (ignoring Z)."""
        return math.sqrt(
            (self.x - other.x) ** 2 +
            (self.y - other.y) ** 2
        )


@dataclass
class GCodeCommand:
    """Represents a single G-code command."""
    command: str  # e.g., "G0", "G1", "M109"
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    e: Optional[float] = None
    f: Optional[float] = None  # Feed rate
    t: Optional[int] = None  # Tool number
    s: Optional[float] = None  # S parameter (e.g., temperature)
    raw: str = ""  # Raw G-code line
    comment: str = ""  # Comment portion

    def to_gcode(self) -> str:
        """Convert back to G-code string."""
        if self.raw:
            return self.raw

        parts = [self.command]
        if self.x is not None:
            parts.append(f"X{self.x:.3f}")
        if self.y is not None:
            parts.append(f"Y{self.y:.3f}")
        if self.z is not None:
            parts.append(f"Z{self.z:.3f}")
        if self.e is not None:
            parts.append(f"E{self.e:.5f}")
        if self.f is not None:
            parts.append(f"F{self.f:.1f}")
        if self.t is not None:
            parts.append(f"T{self.t}")
        if self.s is not None:
            parts.append(f"S{self.s:.1f}")

        line = " ".join(parts)
        if self.comment:
            line += f" ; {self.comment}"
        return line


class GCodeParser:
    """Parse G-code into structured commands."""

    @staticmethod
    def parse(gcode_content: str) -> list[GCodeCommand]:
        """Parse G-code content into a list of commands."""
        commands: list[GCodeCommand] = []

        for line in gcode_content.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Split comment
            comment = ""
            if ";" in line:
                line, comment = line.split(";", 1)
                line = line.strip()
                comment = comment.strip()

            if not line:
                continue

            # Parse command and parameters
            parts = line.split()
            if not parts:
                continue

            cmd = GCodeCommand(
                command=parts[0].upper(),
                raw=line,
                comment=comment,
            )

            # Parse parameters
            for part in parts[1:]:
                param = part.upper()
                if len(param) < 2:
                    continue

                letter = param[0]
                try:
                    value_str = param[1:]

                    if letter == "X":
                        cmd.x = float(value_str)
                    elif letter == "Y":
                        cmd.y = float(value_str)
                    elif letter == "Z":
                        cmd.z = float(value_str)
                    elif letter == "E":
                        cmd.e = float(value_str)
                    elif letter == "F":
                        cmd.f = float(value_str)
                    elif letter == "T":
                        cmd.t = int(value_str)
                    elif letter == "S":
                        cmd.s = float(value_str)
                except (ValueError, IndexError):
                    pass

            commands.append(cmd)

        return commands


class LayerExtractor:
    """Extract layers from G-code commands."""

    @staticmethod
    def extract_layers(commands: list[GCodeCommand]) -> list[list[GCodeCommand]]:
        """
        Extract layers from G-code commands.
        Layers are detected by Z height changes.
        """
        layers: list[list[GCodeCommand]] = []
        current_layer: list[GCodeCommand] = []
        current_z: Optional[float] = None

        for cmd in commands:
            # Detect Z changes (layer boundaries)
            if cmd.z is not None and cmd.z != current_z:
                if current_layer:
                    layers.append(current_layer)
                current_layer = []
                current_z = cmd.z

            current_layer.append(cmd)

        if current_layer:
            layers.append(current_layer)

        return layers


class TopSurfaceDetector:
    """Detect and extract top surface paths."""

    @staticmethod
    def get_top_layer(layers: list[list[GCodeCommand]]) -> list[GCodeCommand]:
        """Get the topmost layer from a list of layers."""
        if not layers:
            return []
        return layers[-1]

    @staticmethod
    def extract_surface_moves(commands: list[GCodeCommand]) -> list[Point3D]:
        """
        Extract surface moves (G0/G1 moves with Z position).
        Returns list of 3D points representing the top surface path.
        """
        points: list[Point3D] = []
        current_pos = Point3D(0, 0, 0)

        for cmd in commands:
            # Track movement commands
            if cmd.command in ("G0", "G1"):
                x = cmd.x if cmd.x is not None else current_pos.x
                y = cmd.y if cmd.y is not None else current_pos.y
                z = cmd.z if cmd.z is not None else current_pos.z
                e = cmd.e if cmd.e is not None else current_pos.e

                current_pos = Point3D(x, y, z, e)

                # Only include points with position changes
                if (cmd.x is not None or cmd.y is not None or cmd.z is not None):
                    points.append(current_pos)

        return points


class IroningPathGenerator:
    """Generate ironing paths for top surface."""

    @staticmethod
    def generate_ironing_moves(
        surface_points: list[Point3D],
        config: IroningConfig,
    ) -> list[GCodeCommand]:
        """
        Generate ironing moves based on surface path.

        Args:
            surface_points: List of 3D points representing the surface
            config: Ironing configuration

        Returns:
            List of G-code commands for ironing
        """
        if not surface_points or not config.enabled:
            return []

        moves: list[GCodeCommand] = []

        # Add header comment
        moves.append(GCodeCommand(
            command=";",
            raw=f"; IRONING START - Mode: {config.mode.value}, Flow: {config.flow_rate*100:.0f}%",
        ))

        # Generate parallel lines for ironing
        # Extract X, Y bounds from surface path
        xs = [p.x for p in surface_points]
        ys = [p.y for p in surface_points]

        if not xs or not ys:
            return moves

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        # Use the average Z from surface points
        surface_z = sum(p.z for p in surface_points) / len(surface_points) if surface_points else 0
        ironing_z = surface_z + config.z_offset

        # Generate parallel lines
        num_lines = max(2, int((max_y - min_y) / config.pattern_spacing) + 1)

        for i in range(num_lines):
            y = min_y + (max_y - min_y) * i / (num_lines - 1) if num_lines > 1 else min_y

            # Alternate direction for each line
            if i % 2 == 0:
                x_start, x_end = min_x, max_x
            else:
                x_start, x_end = max_x, min_x

            if config.reverse_direction and i == 0:
                x_start, x_end = x_end, x_start

            # Move to start position (rapid, no extrusion)
            moves.append(GCodeCommand(
                command="G0",
                x=x_start,
                y=y,
                z=ironing_z,
                comment=f"Iron line {i+1} start",
            ))

            # Linear move with ironing
            feed_rate = config.speed * 60  # Convert mm/s to mm/min
            e_param = None

            if config.mode == IroningMode.NO_EXTRUSION:
                # Don't include E parameter
                e_param = None
            else:
                # Calculate E value based on flow rate
                # This is a simplified calculation
                distance = abs(x_end - x_start)
                e_param = distance * config.flow_rate * 0.1  # Simplified extrusion

            cmd = GCodeCommand(
                command="G1",
                x=x_end,
                y=y,
                z=ironing_z,
                f=feed_rate,
            )
            if e_param is not None:
                cmd.e = e_param
            cmd.comment = f"Iron line {i+1}"

            moves.append(cmd)

        # Add footer comment
        moves.append(GCodeCommand(
            command=";",
            raw="; IRONING END",
        ))

        return moves


class IroningPathValidator:
    """Validate ironing paths for correctness."""

    @staticmethod
    def validate_paths(
        paths: list[GCodeCommand],
        surface_points: list[Point3D],
    ) -> dict[str, bool]:
        """
        Validate ironing paths.

        Returns:
            Dictionary with validation results
        """
        results = {
            "has_moves": len(paths) > 0,
            "has_comments": any(cmd.command == ";" for cmd in paths),
            "all_valid_commands": all(
                cmd.command in ("G0", "G1", ";") for cmd in paths
            ),
            "moves_have_coordinates": all(
                (cmd.x is not None or cmd.y is not None or cmd.z is not None)
                for cmd in paths if cmd.command in ("G0", "G1")
            ),
            "surface_coverage": len(surface_points) > 0,
        }

        return results


def create_default_config() -> IroningConfig:
    """Create a default ironing configuration."""
    return IroningConfig(
        enabled=True,
        mode=IroningMode.LIGHT_FLOW,
        flow_rate=0.5,
        speed=30.0,
        z_offset=0.0,
        pattern_spacing=1.0,
        reverse_direction=False,
    )

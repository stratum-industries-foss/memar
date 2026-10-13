"""
Abstract base protocol for all CNC machine adapters.

All adapters (GRBL, LinuxCNC, MACH3, OPC-UA, Sinumerik) must implement
these 8 methods to ensure consistency, modularity, and forward extensibility.

Pattern: Subclass CNCAdapter and override async methods.
"""
from abc import ABC, abstractmethod
from pydantic import BaseModel


class CNCAdapterStatus(BaseModel):
    """Standard status response from any CNC adapter."""
    online: bool
    state: str  # "ready", "printing", "paused", "error", "offline"
    position_xyz: dict = {"x": 0.0, "y": 0.0, "z": 0.0}
    feed_rate_mm_min: float | None = None
    spindle_rpm_current: int | None = None
    tool_id: str | None = None
    coolant_active: bool = False


class CNCAdapter(ABC):
    """Abstract base class for CNC machine adapters.

    Subclasses must implement all abstract methods.
    This ensures new adapters (MACH3, OPC-UA, Sinumerik, etc.) are
    drop-in compatible with the fleet manager and webhook system.
    """

    @abstractmethod
    async def connect(self) -> dict:
        """Test connection to CNC machine.

        Returns:
            {"ok": bool, "message": str, "state": str}
        """
        pass

    @abstractmethod
    async def disconnect(self) -> dict:
        """Close CNC connection.

        Returns:
            {"ok": bool, "message": str}
        """
        pass

    @abstractmethod
    async def get_status(self) -> dict:
        """Poll CNC status (minimal: state + position + spindle).

        Returns:
            {
                "online": bool,
                "state": str,
                "position_xyz": dict,
                "feed_rate_mm_min": float | None,
                "spindle_rpm_current": int | None
            }
        """
        pass

    @abstractmethod
    async def get_machine_state(self) -> CNCAdapterStatus:
        """Detailed machine state (includes tool, coolant, etc.).

        Returns:
            CNCAdapterStatus with full machine snapshot
        """
        pass

    @abstractmethod
    async def send_gcode(self, gcode: str) -> dict:
        """Send G-code command to machine.

        Args:
            gcode: G-code string (e.g., "G0 X10 Y20 Z5" or "M3 S1000")

        Returns:
            {"ok": bool, "response": str, "error": str | None}
        """
        pass

    @abstractmethod
    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home specified axes.

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "response": str}
        """
        pass

    @abstractmethod
    async def set_feed_rate(self, rate_mm_min: float) -> dict:
        """Set feed rate override.

        Args:
            rate_mm_min: Feed rate in mm/min (0.0 - 500.0 typical range)

        Returns:
            {"ok": bool, "new_rate_mm_min": float | None}

        Shared caveat: the Fadal/FANUC/HAAS/Mach4 adapters target hypothetical
        vendor REST bridges that have not been verified against real hardware
        (unlike Sinumerik and LinuxCNC/GRBL, which implement documented
        protocols directly). Whether those bridges actually accept an
        absolute mm/min setpoint per this contract, or only a percentage
        override, is unconfirmed — see each adapter's own docstring.
        """
        pass

    @abstractmethod
    async def emergency_stop(self) -> dict:
        """Trigger emergency stop (ESTOP).

        Returns:
            {"ok": bool, "state": str}
        """
        pass

    @abstractmethod
    async def list_files(self, path: str = "/") -> list:
        """List G-code files (if available on machine).

        Args:
            path: Directory path to list (default: root)

        Returns:
            list of {"name": str, "path": str}
        """
        pass

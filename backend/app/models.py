from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class MachineType(str, Enum):
    FDM = "fdm"
    SLA = "sla"
    IDEX = "idex"
    CNC_MILL = "cnc_mill"
    CNC_LATHE = "cnc_lathe"
    CNC_ROUTER = "cnc_router"
    LASER = "laser"
    PLASMA = "plasma"
    WATERJET = "waterjet"
    VINYL = "vinyl"
    PICK_AND_PLACE = "pick_and_place"
    EMBROIDERY = "embroidery"
    WIRE_EDM = "wire_edm"


class Protocol(str, Enum):
    MOONRAKER = "moonraker"
    OCTOPRINT = "octoprint"
    DUET = "duet"
    FLUIDNC = "fluidnc"
    BAMBU_MQTT = "bambu_mqtt"
    PRUSA_CONNECT = "prusa_connect"
    OPENPCB = "openpcb"
    GRBL = "grbl"
    LINUXCNC = "linuxcnc"
    MACH3 = "mach3"
    OPCUA = "opcua"
    SINUMERIK = "sinumerik"
    HAAS = "haas"
    FANUC = "fanuc"
    FADAL = "fadal"
    MACH4 = "mach4"
    MQTT = "mqtt"
    MODBUS = "modbus"
    MARLIN = "marlin"


# Adapters that self-document as untested against real hardware (see haas.py,
# fanuc.py, fadal.py, mach4.py docstrings: "UNVERIFIED AGAINST REAL HARDWARE").
# Single source of truth for the alpha-control liability gate — LinuxCNC/Mach3/
# Sinumerik/OPC-UA/GRBL/FluidNC are NOT included here; they implement real
# protocols directly and only need an external bridge, a different (already
# disclosed) caveat, not an unverified-command-semantics one.
ALPHA_PROTOCOLS: frozenset[Protocol] = frozenset({
    Protocol.HAAS, Protocol.FANUC, Protocol.FADAL, Protocol.MACH4,
    Protocol.MACH3, Protocol.SINUMERIK,
})


class UiTarget(BaseModel):
    provider: str = "other"
    label: str
    url: str
    mode: Literal["direct", "bootstrap"] | str = "direct"
    primary: bool = False


UITarget = UiTarget


class PrinterCapability(BaseModel):
    machine_type: MachineType = MachineType.FDM
    profile: str | None = None
    nozzle_diameter_mm: float | None = None
    build_volume: dict[str, float] = Field(default_factory=dict)
    supported_materials: list[str] = Field(default_factory=list)
    current_material: str | None = None
    current_spool_name: str | None = None
    spool_remaining_g: float | None = None
    spool_capacity_g: float | None = 1000.0
    filament_sensor: bool = False
    probe: bool = False
    webcam_expected: bool = False
    fluidd_url: str | None = None
    camera_url: str | None = None
    model_url: str | None = None  # optional 3D model (GLB) URL rendered on the fleet card
    ui_label: str | None = "Open UI"
    ui_targets: list[UiTarget] = Field(default_factory=list)
    maintenance_lockout: bool = False
    maintenance_state: str | None = None
    maintenance_due: bool = False
    maintenance_interval_hours: float | None = None
    maintenance_interval_jobs: int | None = None
    maintenance_interval_filament_g: float | None = None
    last_service_at: str | None = None
    next_service_due: str | None = None
    jog_enabled: bool = True
    safe_nozzle_max_c: float | None = None
    safe_bed_max_c: float | None = None
    motion_check_required: bool = True
    notes: list[str] = Field(default_factory=list)
    maintenance_notes: list[str] = Field(default_factory=list)
    # CNC / Router
    spindle_rpm_max: int | None = None
    spindle_rpm_current: int | None = None
    feed_rate_mm_min: float | None = None
    work_envelope_mm: dict[str, float] | None = None
    tool_id: str | None = None
    coolant_active: bool | None = None
    coolant_psi: float | None = None  # coolant pressure, if the adapter/sensor reports it
    # Laser
    laser_power_pct: float | None = None
    air_assist_active: bool | None = None
    # Plasma
    torch_voltage: float | None = None
    arc_ok: bool | None = None
    thc_active: bool | None = None
    # Waterjet
    pump_psi: float | None = None
    # All non-thermal machines
    position_xyz: dict[str, float] | None = None


class PrinterConfig(BaseModel):
    id: str
    name: str
    base_url: str
    machine_type: MachineType = MachineType.FDM
    protocol: Protocol = Protocol.MOONRAKER
    ws_url: str | None = None
    auth_mode: str = "trusted_local"
    api_key: str | None = None
    serial: str | None = None  # device serial — used by Bambu MQTT (topic + identity)
    mqtt_topic: str | None = None  # generic MQTT: status topic to subscribe to
    mqtt_field_mapping: dict[str, str] | None = None  # generic MQTT: {memar_status_key: payload_key}
    opcua_nodes: dict[str, str] | None = None  # OPC-UA: {role: NodeId str, e.g. "state": "ns=2;s=Machine.State"} — server-specific, overrides opcua.py defaults
    tags: list[str] = Field(default_factory=list)
    compatibility_profile: str | None = None
    timelapse_dir: str | None = None
    fluidd_url: str | None = None
    camera_url: str | None = None
    model_url: str | None = None  # optional 3D model (GLB) URL rendered on the fleet card
    ui_label: str | None = "Open UI"
    ui_targets: list[UiTarget] = Field(default_factory=list)
    enabled: bool = True
    nozzle_diameter_mm: float | None = 0.4
    filament_diameter_mm: float | None = None   # filament strand diameter; None = use Klipper cfg or default 1.75mm
    wire_used_mm_per_job: float | None = None   # Wire EDM: fixed wire consumed per job (mm); no Moonraker equivalent
    build_volume: dict[str, float] = Field(default_factory=dict)
    supported_materials: list[str] = Field(default_factory=list)
    current_material: str | None = None
    current_spool_name: str | None = None
    spool_remaining_g: float | None = None
    spool_capacity_g: float | None = 1000.0
    filament_sensor: bool = False
    probe: bool = False
    webcam_expected: bool = False
    maintenance_lockout: bool = False
    maintenance_state: str | None = None
    maintenance_due: bool = False
    maintenance_interval_hours: float | None = None
    maintenance_interval_jobs: int | None = None
    maintenance_interval_filament_g: float | None = None
    last_service_at: str | None = None
    next_service_due: str | None = None
    jog_enabled: bool = True
    safe_nozzle_max_c: float | None = 300.0
    safe_bed_max_c: float | None = 120.0
    motion_check_required: bool = True
    notes: list[str] = Field(default_factory=list)
    maintenance_notes: list[str] = Field(default_factory=list)
    # CNC-specific safety bounds
    spindle_rpm_max: int | None = None  # Max safe spindle speed (e.g., 10000 for mill)
    feed_rate_mm_min: float | None = None  # Max safe feed rate (e.g., 500.0 mm/min)

    def capability(self) -> PrinterCapability:
        return PrinterCapability(
            machine_type=self.machine_type,
            profile=self.compatibility_profile,
            nozzle_diameter_mm=self.nozzle_diameter_mm,
            build_volume=self.build_volume,
            supported_materials=self.supported_materials,
            current_material=self.current_material,
            current_spool_name=self.current_spool_name,
            spool_remaining_g=self.spool_remaining_g,
            spool_capacity_g=self.spool_capacity_g,
            filament_sensor=self.filament_sensor,
            probe=self.probe,
            webcam_expected=self.webcam_expected,
            fluidd_url=self.fluidd_url,
            camera_url=self.camera_url,
            model_url=self.model_url,
            ui_label=self.ui_label,
            ui_targets=self.ui_targets,
            maintenance_lockout=self.maintenance_lockout,
            maintenance_state=self.maintenance_state,
            maintenance_due=self.maintenance_due,
            maintenance_interval_hours=self.maintenance_interval_hours,
            maintenance_interval_jobs=self.maintenance_interval_jobs,
            maintenance_interval_filament_g=self.maintenance_interval_filament_g,
            last_service_at=self.last_service_at,
            next_service_due=self.next_service_due,
            jog_enabled=self.jog_enabled,
            safe_nozzle_max_c=self.safe_nozzle_max_c,
            safe_bed_max_c=self.safe_bed_max_c,
            motion_check_required=self.motion_check_required,
            notes=self.notes,
            maintenance_notes=self.maintenance_notes,
        )


class MaterialPreset(BaseModel):
    label: str = Field(max_length=100)
    nozzle: float = Field(ge=0, le=400)
    bed: float = Field(ge=0, le=200)
    builtin: bool = False


class KlipperConfig(BaseModel):
    """Structured hardware spec parsed directly from printer.cfg."""  # noqa: E501

    # Kinematics
    kinematics: str | None = None          # cartesian / corexy / delta / etc.
    max_velocity: float | None = None      # mm/s
    max_accel: float | None = None         # mm/s²
    max_z_velocity: float | None = None
    max_z_accel: float | None = None
    square_corner_velocity: float | None = None

    # Build volume derived from stepper position_max values
    x_max: float | None = None
    y_max: float | None = None
    z_max: float | None = None

    # Extruder
    nozzle_diameter: float | None = None
    filament_diameter: float | None = None
    nozzle_max_temp: float | None = None
    nozzle_sensor_type: str | None = None
    pressure_advance: float | None = None
    gear_ratio: str | None = None
    rotation_distance: float | None = None
    microsteps_e: int | None = None

    # Heated bed
    bed_max_temp: float | None = None
    bed_sensor_type: str | None = None

    # Probing
    has_probe: bool = False
    probe_type: str | None = None         # bltouch / probe / smart_effector
    has_bed_mesh: bool = False
    has_z_tilt: bool = False
    has_quad_gantry_level: bool = False
    # Motion / homing
    has_safe_z_home: bool = False
    has_homing_override: bool = False
    sensorless_x: bool = False
    sensorless_y: bool = False
    # MCU / stepper drivers
    mcu_serial: str | None = None
    tmc_drivers: list[str] = Field(default_factory=list)  # e.g. ["tmc2209 stepper_x", ...]
    # Fans
    fan_count: int = 0
    heater_fan_count: int = 0
    controller_fan_count: int = 0
    # Macros & includes
    include_files: list[str] = Field(default_factory=list)
    macro_names: list[str] = Field(default_factory=list)
    # Temperature sensors (non-heater)
    temperature_sensors: list[str] = Field(default_factory=list)
    # Raw parse warnings (sections that looked malformed)
    parse_notes: list[str] = Field(default_factory=list)


class DashboardSettings(BaseModel):
    card_layout: Literal["auto", "horizontal", "stacked"] = "horizontal"
    card_density: Literal["compact", "cozy", "comfortable"] = "cozy"
    show_card_preview: bool = True
    show_metrics_strip: bool = True
    show_oee: bool = True
    show_empty_capability_tiles: bool = False
    default_drawer_section: str = "overview"
    metrics_history_limit: int = Field(default=50, ge=5, le=500)
    metrics_refresh_seconds: int = Field(default=15, ge=5, le=3600)
    spoolman_url: str | None = Field(default=None, max_length=512)
    demo_mode_auto_login: bool = True


class FarmConfig(BaseModel):
    printers: list[PrinterConfig] = Field(default_factory=list)
    dashboard_settings: DashboardSettings = Field(default_factory=DashboardSettings)
    material_presets: list[MaterialPreset] = Field(default_factory=list)


class HeaterStatus(BaseModel):
    temperature: float | None = None
    target: float | None = None


class JobStatus(BaseModel):
    filename: str | None = None
    state: str | None = None
    progress: float | None = None
    print_duration: float | None = None
    total_duration: float | None = None
    estimated_total_duration: float | None = None
    remaining_duration: float | None = None
    message: str | None = None
    eta_seconds: float | None = None
    filament_used_mm: float | None = None
    current_layer: int | None = None
    total_layer: int | None = None


class CNCPosition(BaseModel):
    """3D machine position (XYZ)."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class CNCMetrics(BaseModel):
    """Real-time metrics for CNC machines (GRBL, LinuxCNC, etc.)."""
    spindle_rpm: int | None = None
    feed_rate_mm_min: float | None = None
    position_xyz: CNCPosition = Field(default_factory=CNCPosition)
    machine_state: str = "offline"  # idle, ready, printing/running, paused, error, offline
    tool_id: str | None = None
    coolant_active: bool = False


class SpindleConfig(BaseModel):
    """Spindle RPM configuration bounds."""
    min_rpm: int = 0
    max_rpm: int = 24000


class FeedRateConfig(BaseModel):
    """Feed rate configuration bounds."""
    min_mm_min: float = 0.0
    max_mm_min: float = 500.0


class Anomaly(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    message: str
    acked: bool = False


class FleetPrinterStatus(BaseModel):
    id: str
    name: str
    base_url: str
    enabled: bool
    online: bool
    state: str
    state_message: str | None = None
    nozzle: HeaterStatus = Field(default_factory=HeaterStatus)
    bed: HeaterStatus = Field(default_factory=HeaterStatus)
    nozzle_diameter_mm: float | None = None
    job: JobStatus = Field(default_factory=JobStatus)
    warnings: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    ui_targets: list[UiTarget] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    attention_needed: bool = False
    anomalies: list[Anomaly] = Field(default_factory=list)
    macros_count: int = 0
    webcams_count: int = 0
    capability: PrinterCapability = Field(default_factory=PrinterCapability)
    idle_state: str | None = None
    idle_since_s: float | None = None
    speed_factor: float | None = None
    flow_factor: float | None = None
    mcu_temp: float | None = None
    protocol: Protocol | None = None
    is_alpha_protocol: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class BatchActionRequest(BaseModel):
    printer_ids: list[str]
    mode: Literal["standard", "conservative"] = "standard"


class BatchActionResult(BaseModel):
    printer_id: str
    name: str
    allowed: bool
    status: Literal["ok", "blocked", "error"]
    message: str


class BatchActionResponse(BaseModel):
    action: str
    results: list[BatchActionResult]


class DryRunRequest(BaseModel):
    printer_ids: list[str]
    mode: Literal["standard", "conservative"] = "standard"
    macro_name: str | None = None
    nozzle_target: float | None = None
    bed_target: float | None = None


class DryRunResult(BaseModel):
    printer_id: str
    name: str
    eligible: bool
    would_execute: bool
    current_state: str | None = None
    required_state: str | None = None
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    motion_summary: str | None = None


class DryRunResponse(BaseModel):
    action: str
    mode: str = "dry_run"
    results: list[DryRunResult] = Field(default_factory=list)


class MotionCheckRequest(BaseModel):
    intent: Literal["home", "jog", "park", "macro", "mesh", "unknown"] = "home"
    macro_name: str | None = None


class MotionCheckResponse(BaseModel):
    printer_id: str
    name: str
    ok: bool
    homed_axes: str = ""
    current_state: str | None = None
    checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)


class DispatchDryRunRequest(BaseModel):
    filename: str
    printer_ids: list[str] = Field(default_factory=list)
    material: str | None = None
    nozzle_diameter_mm: float | None = None
    allow_busy_queue: bool = False


class DispatchDryRunResult(BaseModel):
    printer_id: str
    name: str
    eligible: bool
    would_queue: bool
    score: float = 0.0
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendation: str | None = None


class DispatchDryRunResponse(BaseModel):
    filename: str
    requested_material: str | None = None
    requested_nozzle_diameter_mm: float | None = None
    results: list[DispatchDryRunResult] = Field(default_factory=list)
    recommended_printer_ids: list[str] = Field(default_factory=list)


class PrinterDiagnostics(BaseModel):
    printer_id: str
    name: str
    online: bool
    state: str
    state_message: str | None = None
    base_url: str
    tags: list[str] = Field(default_factory=list)
    ui_targets: list[UiTarget] = Field(default_factory=list)
    nozzle_diameter_mm: float | None = None
    available_actions: list[str] = Field(default_factory=list)
    attention_needed: bool = False
    anomalies: list[Anomaly] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    config_file: str | None = None
    log_file: str | None = None
    process_id: int | None = None
    moonraker_version: str | None = None
    api_version_string: str | None = None
    klippy_connected: bool | None = None
    components: list[str] = Field(default_factory=list)
    failed_components: list[str] = Field(default_factory=list)
    suggested_checks: list[str] = Field(default_factory=list)
    recent_log_lines: list[str] = Field(default_factory=list)
    capability: PrinterCapability = Field(default_factory=PrinterCapability)
    homed_axes: str = ""
    toolhead_position: dict[str, float] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
    klipper_config: "KlipperConfig | None" = None


class TemperatureSetRequest(BaseModel):
    nozzle_target: float | None = Field(default=None, ge=0, le=400)
    bed_target: float | None = Field(default=None, ge=0, le=200)
    t1_nozzle: float | None = Field(default=None, ge=0, le=400)  # IDEX second toolhead (T1)


class NozzleUpdateRequest(BaseModel):
    nozzle_diameter_mm: float = Field(gt=0, le=2.0)


class NozzleUpdateResponse(BaseModel):
    printer_id: str
    nozzle_diameter_mm: float
    config_path: str
    backup_path: str


class PrinterSettingsUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    nozzle_diameter_mm: float | None = Field(default=None, gt=0, le=2.0)
    filament_diameter_mm: float | None = Field(default=None, gt=0, le=5.0)
    wire_used_mm_per_job: float | None = Field(default=None, ge=0, le=1_000_000)
    compatibility_profile: str | None = Field(default=None, max_length=128)
    build_volume: dict[str, float] | None = None
    supported_materials: list[str] | None = Field(default=None, max_length=50)
    current_material: str | None = Field(default=None, max_length=255)
    current_spool_name: str | None = Field(default=None, max_length=255)
    spool_remaining_g: float | None = Field(default=None, ge=0, le=20000)
    spool_capacity_g: float | None = Field(default=None, ge=0, le=20000)
    filament_sensor: bool | None = None
    probe: bool | None = None
    webcam_expected: bool | None = None
    camera_url: str | None = Field(default=None, max_length=512)
    timelapse_dir: str | None = Field(default=None, max_length=512)
    maintenance_lockout: bool | None = None
    maintenance_state: str | None = Field(default=None, max_length=255)
    maintenance_due: bool | None = None
    maintenance_interval_hours: float | None = Field(default=None, ge=0, le=100_000)
    maintenance_interval_jobs: int | None = Field(default=None, ge=0, le=1_000_000)
    maintenance_interval_filament_g: float | None = Field(default=None, ge=0, le=10_000_000)
    last_service_at: str | None = Field(default=None, max_length=64)
    next_service_due: str | None = Field(default=None, max_length=64)
    jog_enabled: bool | None = None
    safe_nozzle_max_c: float | None = Field(default=None, ge=0, le=500)
    safe_bed_max_c: float | None = Field(default=None, ge=0, le=200)
    motion_check_required: bool | None = None
    notes: list[str] | None = Field(default=None, max_length=100)
    maintenance_notes: list[str] | None = Field(default=None, max_length=100)
    ui_targets: list[UiTarget] | None = Field(default=None, max_length=20)
    base_url: str | None = Field(default=None, max_length=512)
    ws_url: str | None = Field(default=None, max_length=512)
    auth_mode: str | None = Field(default=None, max_length=64)
    api_key: str | None = Field(default=None, max_length=512)
    serial: str | None = Field(default=None, max_length=128)  # Bambu MQTT topic/identity
    mqtt_topic: str | None = Field(default=None, max_length=512)  # generic MQTT status topic
    mqtt_field_mapping: dict[str, str] | None = None             # generic MQTT field map
    ui_label: str | None = Field(default=None, max_length=100)
    fluidd_url: str | None = Field(default=None, max_length=512)


class PrinterSettingsSaveResponse(BaseModel):
    printer_id: str
    config_path: str
    backup_path: str
    printer: PrinterConfig


class FleetSettingsUpdateRequest(BaseModel):
    dashboard_settings: DashboardSettings | None = None
    material_presets: list[MaterialPreset] | None = None


class FleetSettingsResponse(BaseModel):
    dashboard_settings: DashboardSettings = Field(default_factory=DashboardSettings)
    material_presets: list[MaterialPreset] = Field(default_factory=list)
    config_path: str | None = None
    backup_path: str | None = None


class JogRequest(BaseModel):
    axis: Literal['X', 'Y', 'Z', 'E']
    distance: float = Field(..., gt=-500, lt=500)
    feedrate: float | None = Field(default=None, gt=0, le=50000)
    relative: bool = True


class MacroParam(BaseModel):
    """One inferred input of a Klipper macro.

    Klipper declares nothing about its macro parameters, so this is derived from
    the macro body by `app.macro_params` and is best-effort: `type` falls back to
    "string" (free text) whenever inference cannot prove a number, and `default`
    is None when the macro's default is computed rather than literal.
    """

    type: Literal["int", "float", "string"] = "string"
    default: Any | None = None


class MacroEntry(BaseModel):
    name: str
    full_object: str
    # Empty (not None) when a macro takes no parameters, or when the printer's
    # configfile could not be read — callers treat both as "render free text".
    params: dict[str, MacroParam] = Field(default_factory=dict)
    category: str | None = None
    color: str | None = None


class MacroRunRequest(BaseModel):
    """Optional body for POST /api/printers/{id}/macros/{name}.

    `params` are Klipper-style KEY=VALUE macro arguments. They are NOT validated
    here on purpose — `fleet.build_macro_command` owns that, so a rejected
    parameter returns the documented 400 rather than Pydantic's 422.
    """

    params: dict[str, str] = Field(default_factory=dict)


class FileEntry(BaseModel):
    name: str
    path: str
    kind: Literal["file", "dir"]
    size: int | None = None
    modified: float | None = None
    permissions: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FileBrowserResponse(BaseModel):
    printer_id: str
    path: str
    root: str = "gcodes"
    dirs: list[FileEntry] = Field(default_factory=list)
    files: list[FileEntry] = Field(default_factory=list)
    disk_usage: dict[str, Any] = Field(default_factory=dict)
    root_info: dict[str, Any] = Field(default_factory=dict)


class NormalizedFileMetadata(BaseModel):
    filename: str
    path: str
    size: int | None = None
    modified: float | None = None
    estimated_time_s: float | None = None
    filament_mm: float | None = None
    filament_g: float | None = None
    layer_height_mm: float | None = None
    object_height_mm: float | None = None
    slicer: str | None = None
    thumbnail_url: str | None = None
    thumbnails: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class FileDetailResponse(BaseModel):
    printer_id: str
    file: FileEntry
    metadata: NormalizedFileMetadata
    compatibility_hints: list[str] = Field(default_factory=list)


class CurrentFileResponse(BaseModel):
    printer_id: str
    filename: str | None = None
    detail: FileDetailResponse | None = None


class StartPrintRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=1024)


class UploadResponse(BaseModel):
    printer_id: str
    filename: str
    path: str | None = None
    size: int | None = None
    started_print: bool = False
    warnings: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)


class DispatchUploadItem(BaseModel):
    printer_id: str
    filename: str
    path: str | None = None
    size: int | None = None
    started_print: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DispatchUploadResponse(BaseModel):
    filename: str
    size: int
    results: list[DispatchUploadItem] = Field(default_factory=list)


class WebcamEntry(BaseModel):
    uid: str
    name: str
    enabled: bool = True
    stream_url: str | None = None
    snapshot_url: str | None = None
    location: str | None = None
    service: str | None = None
    aspect_ratio: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class WebcamListResponse(BaseModel):
    printer_id: str
    webcams: list[WebcamEntry] = Field(default_factory=list)


class HistoryJob(BaseModel):
    job_id: str | None = None
    filename: str | None = None
    status: str | None = None
    exists: bool | None = None
    filament_used: float | None = None
    print_duration: float | None = None
    total_duration: float | None = None
    start_time: float | None = None
    end_time: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HistoryTotals(BaseModel):
    total_jobs: int = 0
    total_time: float = 0.0
    total_print_time: float = 0.0
    total_filament_used: float = 0.0
    longest_job: float = 0.0
    longest_print: float = 0.0


class HistoryResponse(BaseModel):
    printer_id: str
    jobs: list[HistoryJob] = Field(default_factory=list)
    totals: HistoryTotals = Field(default_factory=HistoryTotals)


class FleetMetricCard(BaseModel):
    printer_id: str
    name: str
    online: bool = True
    state: str | None = None
    success_rate: float | None = None
    completed_jobs: int = 0
    failed_jobs: int = 0
    cancelled_jobs: int = 0
    total_print_time: float = 0.0
    total_filament_used: float = 0.0
    avg_print_time: float = 0.0
    spool_remaining_g: float | None = None
    nozzle_diameter_mm: float | None = None
    current_material: str | None = None
    last_job_end_time: float | None = None


class FleetMetricsSummary(BaseModel):
    printer_count: int = 0
    online_count: int = 0
    active_prints: int = 0
    paused_count: int = 0
    attention_count: int = 0
    maintenance_due_count: int = 0
    total_jobs_window: int = 0
    completed_jobs_window: int = 0
    failed_jobs_window: int = 0
    cancelled_jobs_window: int = 0
    success_rate_window: float | None = None
    total_print_time_window: float = 0.0
    total_filament_used_window: float = 0.0
    total_spool_remaining_g: float = 0.0
    avg_print_time_window: float = 0.0
    hottest_printer_name: str | None = None
    hottest_printer_temp: float | None = None


class FleetMetricsResponse(BaseModel):
    generated_at: str
    window_limit: int = 50
    summary: FleetMetricsSummary
    printers: list[FleetMetricCard] = Field(default_factory=list)


class TimelapseEntry(BaseModel):
    id: str
    name: str
    path: str
    size: int | None = None
    modified: float | None = None
    kind: Literal["video", "image"] = "video"


class TimelapseListResponse(BaseModel):
    printer_id: str
    source_dir: str | None = None
    configured: bool = False
    entries: list[TimelapseEntry] = Field(default_factory=list)


class CommandResult(BaseModel):
    result: str


class AppVersion(BaseModel):
    version: str
    build_id: str


class TemperaturePoint(BaseModel):
    time: float
    temperature: float
    target: float | None = None


class TemperatureHistory(BaseModel):
    extruder: list[TemperaturePoint] = Field(default_factory=list)
    bed: list[TemperaturePoint] = Field(default_factory=list)
    mcu: list[float] = Field(default_factory=list)


class HostStats(BaseModel):
    cpu_temp: float | None = None
    cpu_usage: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    uptime_s: float | None = None
    network_rx_mb: float | None = None
    network_tx_mb: float | None = None
    websocket_count: int = 0


class QueuedJob(BaseModel):
    job_id: str
    filename: str
    time_added: float


class PrintQueue(BaseModel):
    state: str  # "paused" | "ready"
    jobs: list[QueuedJob] = Field(default_factory=list)


class ComponentUpdate(BaseModel):
    name: str
    version: str
    commits_behind: int = 0
    is_dirty: bool = False


class UpdateStatus(BaseModel):
    components: list[ComponentUpdate] = Field(default_factory=list)
    system_packages_pending: int = 0


class FirmwareComponent(BaseModel):
    """Single firmware component version."""
    name: str  # "klipper", "moonraker", "mcu"
    version: str  # "v0.13.0-688-gb7c0329f"
    branch: str | None = None  # "master", "dev"
    commits_behind: int = 0  # How many commits behind latest
    is_dirty: bool = False  # Local changes not committed
    git_hash: str | None = None  # Current commit hash
    remote_url: str | None = None  # Git remote URL


class FirmwareState(BaseModel):
    """Current firmware state of a printer."""
    printer_id: str
    components: list[FirmwareComponent] = Field(default_factory=list)
    mcu_board: str | None = None  # "stm32f401", "rp2040", etc
    mcu_firmware: str | None = None  # Board firmware version
    last_updated: str | None = None  # ISO timestamp
    update_available: bool = False  # Any updates pending


class FirmwareHistoryEntry(BaseModel):
    """Single firmware change in history."""
    timestamp: str  # ISO
    action: str  # "flash", "rollback", "update_check"
    component: str  # "klipper", "moonraker", etc
    from_version: str | None = None
    to_version: str | None = None
    status: str  # "success", "failed", "pending"
    notes: str | None = None


class FirmwareHistory(BaseModel):
    """Firmware change history."""
    printer_id: str
    entries: list[FirmwareHistoryEntry] = Field(default_factory=list)
    total_count: int = 0


class PACalibrationJob(BaseModel):
    """Queued or completed PA calibration job."""
    job_id: str
    printer_id: str
    created_at: str  # ISO timestamp
    status: str  # "queued", "printing", "completed", "failed"
    pa_start: float
    pa_end: float
    pa_step: float
    band_count: int
    image_path: str | None = None
    result_pa: float | None = None
    result_confidence: float | None = None


class PABandScore(BaseModel):
    """Single band quality score from vision analysis."""
    band_index: int
    pa_value: float
    quality_score: float
    defects: list[str] = Field(default_factory=list)
    edge_sharpness: float
    line_uniformity: float
    surface_finish: float


class PACalibrationAnalysis(BaseModel):
    """Complete analysis of a PA calibration print."""
    job_id: str
    printer_id: str
    analysis_timestamp: str  # ISO
    bands: list[PABandScore] = Field(default_factory=list)
    recommended_pa: float
    confidence: float
    notes: str | None = None

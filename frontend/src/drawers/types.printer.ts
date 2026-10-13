/**
 * Shared printer and fleet data types
 * Extracted from App.tsx for use across components and hooks
 */

export type HeaterStatus = {
  temperature: number | null
  target: number | null
}

export type JobStatus = {
  filename: string | null
  state: string | null
  progress: number | null
  print_duration?: number | null
  total_duration?: number | null
  message?: string | null
  eta_seconds?: number | null
}

export type Anomaly = {
  code: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  acked?: boolean
}

export type UiTarget = {
  provider: string
  label: string
  url: string
  mode: 'direct' | 'bootstrap'
  primary?: boolean
}

export type MachineTypeValue = 'fdm' | 'sla' | 'idex' | 'cnc_mill' | 'cnc_lathe' | 'cnc_router' | 'laser' | 'plasma' | 'waterjet' | 'vinyl' | 'pick_and_place' | 'embroidery' | 'wire_edm'

export type PrinterCapability = {
  machine_type?: MachineTypeValue
  profile: string | null
  nozzle_diameter_mm: number | null
  build_volume: Record<string, number>
  supported_materials: string[]
  current_material: string | null
  current_spool_name: string | null
  spool_remaining_g: number | null
  spool_capacity_g: number | null
  filament_sensor: boolean
  probe: boolean
  webcam_expected: boolean
  fluidd_url: string | null
  camera_url: string | null
  model_url?: string | null
  ui_label?: string | null
  ui_targets?: UiTarget[]
  maintenance_lockout: boolean
  maintenance_state: string | null
  maintenance_due: boolean
  maintenance_interval_hours: number | null
  maintenance_interval_jobs: number | null
  maintenance_interval_filament_g: number | null
  last_service_at: string | null
  next_service_due: string | null
  jog_enabled: boolean
  safe_nozzle_max_c: number | null
  safe_bed_max_c: number | null
  motion_check_required: boolean
  notes: string[]
  maintenance_notes: string[]
  spindle_rpm_max?: number | null
  spindle_rpm_current?: number | null
  feed_rate_mm_min?: number | null
  work_envelope_mm?: { x: number; y: number; z: number } | null
  tool_id?: string | null
  coolant_active?: boolean | null
  laser_power_pct?: number | null
  air_assist_active?: boolean | null
  torch_voltage?: number | null
  arc_ok?: boolean | null
  thc_active?: boolean | null
  pump_psi?: number | null
  position_xyz?: { x: number; y: number; z: number } | null
}

export type Printer = {
  id: string
  name: string
  base_url: string
  online: boolean
  state: string
  state_message: string | null
  nozzle: HeaterStatus
  nozzle2?: HeaterStatus
  bed: HeaterStatus
  job: JobStatus
  warnings: string[]
  tags: string[]
  available_actions: string[]
  attention_needed: boolean
  anomalies: Anomaly[]
  macros_count: number
  webcams_count: number
  capability: PrinterCapability
  ui_targets?: UiTarget[]
  nozzle_diameter_mm?: number | null
  speed_factor?: number | null
  flow_factor?: number | null
  protocol?: string | null
  is_alpha_protocol?: boolean
}

export type KlipperConfig = {
  kinematics: string | null
  max_velocity: number | null
  max_accel: number | null
  max_z_velocity: number | null
  max_z_accel: number | null
  square_corner_velocity: number | null
  x_max: number | null
  y_max: number | null
  z_max: number | null
  nozzle_diameter: number | null
  filament_diameter: number | null
  nozzle_max_temp: number | null
  nozzle_sensor_type: string | null
  pressure_advance: number | null
  gear_ratio: string | null
  rotation_distance: number | null
  microsteps_e: number | null
  bed_max_temp: number | null
  bed_sensor_type: string | null
  has_probe: boolean
  probe_type: string | null
  has_bed_mesh: boolean
  has_z_tilt: boolean
  has_quad_gantry_level: boolean
  has_safe_z_home: boolean
  has_homing_override: boolean
  sensorless_x: boolean
  sensorless_y: boolean
  mcu_serial: string | null
  tmc_drivers: string[]
  fan_count: number
  heater_fan_count: number
  controller_fan_count: number
  include_files: string[]
  macro_names: string[]
  temperature_sensors: string[]
  parse_notes: string[]
}

export type Diagnostics = {
  printer_id: string
  name: string
  online: boolean
  state: string
  state_message: string | null
  base_url: string
  tags: string[]
  available_actions: string[]
  attention_needed: boolean
  anomalies: Anomaly[]
  warnings: string[]
  config_file: string | null
  log_file: string | null
  process_id: number | null
  moonraker_version: string | null
  api_version_string: string | null
  klippy_connected: boolean | null
  components: string[]
  failed_components: string[]
  suggested_checks: string[]
  recent_log_lines: string[]
  capability: PrinterCapability
  ui_targets?: UiTarget[]
  nozzle_diameter_mm?: number | null
  homed_axes: string
  toolhead_position?: Record<string, number>
  klipper_config?: KlipperConfig | null
}

export type FileEntry = {
  name: string
  path: string
  kind: 'file' | 'dir'
  size: number | null
  modified: number | null
  permissions: string | null
  metadata: Record<string, unknown>
}

export type NormalizedFileMetadata = {
  first_layer_height?: number | null
  layer_height?: number | null
  nozzle_diameter?: number | null
  filament_total?: number | null
  estimated_time?: number | null
  estimated_time_formatted?: string | null
  filament_weight_total?: number | null
  chamber_temperature?: number | null
  bed_temperature?: number | null
  bed_temperature_first_layer?: number | null
  extruder_temperature?: number | null
  extruder_temperature_first_layer?: number | null
  max_layer_z?: number | null
}

export type FileDetailResponse = {
  printer_id: string
  file: FileEntry
  metadata: NormalizedFileMetadata
  compatibility_hints: string[]
}

export type CurrentFileResponse = {
  printer_id: string
  filename: string | null
  detail: FileDetailResponse | null
}

export type FleetMetricCard = {
  printer_id: string
  name: string
  online: boolean
  state: string | null
  success_rate: number | null
  completed_jobs: number
  failed_jobs: number
  cancelled_jobs: number
  total_print_time: number
  total_filament_used: number
  avg_print_time: number
  last_job_end_time: number | null
}

export type OeeDevice = {
  device_id: string
  oee: number | null
  availability: number | null
  performance: number | null
  quality: number | null
  sample_jobs: number
}

export type CvAnomaly = {
  type: string
  confidence: 'high' | 'low'
  score: number
  reasoning: string
}

export type ExcludeObjectsPayload = {
  supported: boolean
  objects: Array<{ name: string; polygon?: Array<[number, number]> }>
  excluded: string[]
  current_object: string | null
}

export type SpoolLogEntry = {
  id: string
  created_at: string | null
  job_name: string | null
  filament_used_g: number | null
  spool_after_g: number | null
  source: 'manual' | 'auto'
}

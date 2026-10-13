import React, { useCallback, useEffect, useMemo, useRef, useState, Suspense } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { info, error, debug } from './logging'
import { apiFetch, authState, initializeAuth, setTokens, clearTokens, refreshAccessToken, requireOk } from './api'
import {
  handleConsoleKey,
  loadConsoleHistory,
  saveConsoleHistory,
  appendConsoleHistory,
  NO_COMPLETION_CYCLE,
  type CompletionCycle,
} from './consoleInput'
import { FloorPlan2D, DevicePosition } from './FloorPlan2D'
import { FloorPlanEditor } from './FloorPlanEditor'
import { FleetToolsModal, QueuePanel, MaintenancePanel, HealthPanel } from './FleetTools'
import { CoolantMetricsPanel } from './CoolantMetricsPanel'
import { CNCMetricsPanel } from './CNCMetricsPanel'
import { ShimmerLoader } from './components/ShimmerLoader'
import { useFocusTrap } from './hooks/useFocusTrap'
// Lazy-loaded: AnalyticsDashboard pulls in recharts (~75KB). Code-splitting it
// keeps recharts out of the initial bundle until the analytics view is opened.
const AnalyticsDashboard = React.lazy(() => import('./AnalyticsDashboard').then((m) => ({ default: m.AnalyticsDashboard })))
// Lazy-loaded: ThreeDViewer + three.js (~121KB gzip). Only load when 3D model view is needed.
const ThreeDViewer = React.lazy(() => import('./ThreeDViewer'))
import { ConfirmDialog } from './ConfirmDialog'
import { AlphaAcknowledgeModal } from './AlphaAcknowledgeModal'
import { AdminPanel } from './AdminPanel'
import { SetupWizard } from './SetupWizard'
import { ExcludeObjectsMap, hasPolygonData } from './ExcludeObjectsMap'
import { BedMeshPanel } from './BedMeshPanel'
import { OverviewGraphs } from './drawers/OverviewGraphs'
import { MaterialSelector } from './drawers/MaterialSelector'
import SystemSettingsDrawer from './drawers/SystemSettingsDrawer'
// SECURITY: Passkey login hidden until backend verifies assertions
// import WebAuthnAuth from './components/WebAuthnAuth'
import PasskeyManager from './components/PasskeyManager'
import type { DrawerProps } from './types/drawer-props'

type HeaterStatus = {
  temperature: number | null
  target: number | null
}

type JobStatus = {
  filename: string | null
  state: string | null
  progress: number | null
  print_duration?: number | null
  total_duration?: number | null
  message?: string | null
  eta_seconds?: number | null
}

type Anomaly = {
  code: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  acked?: boolean
}

// Map an anomaly code to its one-click recovery action (operator/admin only).
// `kind` 'maintenance' hits maintenance/complete; the rest are printer actions.
function quickActionFor(code?: string): { label: string; kind: string } | null {
  switch (code) {
    case 'maintenance_due': return { label: 'Mark serviced', kind: 'maintenance' }
    case 'state_error':
    case 'klippy_disconnected': return { label: 'FW Restart', kind: 'firmware_restart' }
    case 'idle_nozzle_warm':
    case 'idle_bed_warm': return { label: 'Cooldown', kind: 'cooldown' }
    case 'job_paused': return { label: 'Resume', kind: 'resume' }
    case 'spool_low':
    case 'spool_critical': return { label: 'Refill', kind: 'refill' }
    default: return null
  }
}

type UiTarget = {
  provider: string
  label: string
  url: string
  mode: 'direct' | 'bootstrap'
  primary?: boolean
}

// A machine's launchable UIs arrive in two places: capability.ui_targets is
// only populated by the backend's online status path, while the top-level
// ui_targets is populated for online AND offline printers. A bare
// `capability.ui_targets || ui_targets` can't express that fallback — an empty
// array is truthy, so offline printers (capability.ui_targets: []) masked
// their real targets and the Open UI button vanished / silently did nothing.
function printerUiTargets(printer: { ui_targets?: UiTarget[]; capability: { ui_targets?: UiTarget[] } }): UiTarget[] {
  const cap = printer.capability.ui_targets
  if (cap && cap.length > 0) return cap
  return printer.ui_targets || []
}

// T75: Allowlist https: URLs for ui_targets to prevent XSS/phishing attacks
function safeUiUrl(url: string): string | null {
  return /^https:\/\//.test(url) ? url : null
}

type TempPreset = {
  label: string
  nozzle: number
  bed: number
  builtin?: boolean
}

type MachineTypeValue = 'fdm' | 'sla' | 'idex' | 'cnc_mill' | 'cnc_lathe' | 'cnc_router' | 'laser' | 'plasma' | 'waterjet' | 'vinyl' | 'pick_and_place' | 'embroidery' | 'wire_edm'

type DrawerMessage = {
  text: string
  severity: 'success' | 'error' | 'info' | 'warning'
}

// Machine types that actually have CNC/coolant metrics (spindle, feed, coolant PSI).
// 3D printers (fdm/sla/idex) and the like do not — the Coolant tab is hidden for them.
const CNC_MACHINE_TYPES = new Set<MachineTypeValue>(['cnc_mill', 'cnc_lathe', 'cnc_router', 'laser', 'plasma', 'waterjet', 'wire_edm'])
const isCncMachine = (mt?: MachineTypeValue): boolean => !!mt && CNC_MACHINE_TYPES.has(mt)

// Utility function to describe errors for user-facing messages
function describeError(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

type PrinterCapability = {
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

type Printer = {
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

type FleetPayload = {
  generated_at: string
  printers: Printer[]
}

type KlipperConfig = {
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

type Diagnostics = {
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

// `params` is inferred server-side from the Klipper macro body and is
// best-effort: it is `{}` for a macro that takes no parameters AND for one
// whose config could not be read, so an empty map always means "fall back to
// the free-text field". `type` is never null — untyped params arrive as
// "string".
type MacroParam = {
  type: 'int' | 'float' | 'string'
  default: number | string | boolean | null
}

type MacroEntry = {
  name: string
  full_object: string
  params?: Record<string, MacroParam>
  category?: string | null
  color?: string | null
}

/** Parse a free-text `KEY=VALUE KEY2=VALUE2` box into the request-body map.
 *
 * Returns null on a malformed token so the caller can refuse the whole run.
 * Silently dropping a token would send a DIFFERENT command than the operator
 * typed — on a machine with heaters and motion, that is the worst outcome
 * available, so a bad token aborts rather than degrades.
 */
function parseRawMacroParams(raw: string): Record<string, string> | null {
  const trimmed = raw.trim()
  if (!trimmed) return {}
  const out: Record<string, string> = {}
  for (const token of trimmed.split(/\s+/)) {
    const eq = token.indexOf('=')
    if (eq <= 0 || eq === token.length - 1) return null
    out[token.slice(0, eq)] = token.slice(eq + 1)
  }
  return out
}

/** Klipper convention: a macro whose name starts with `_` is a private helper
 * that is not meant to be called directly from a UI. */
function isPrivateMacro(name: string): boolean {
  return name.startsWith('_')
}

type FileEntry = {
  name: string
  path: string
  kind: 'file' | 'dir'
  size: number | null
  modified: number | null
  permissions: string | null
  metadata: Record<string, unknown>
}

type FileBrowserResponse = {
  printer_id: string
  path: string
  root: string
  dirs: FileEntry[]
  files: FileEntry[]
}

type PrintCountRow = {
  job_name: string
  count: number
}

type NormalizedFileMetadata = {
  filename: string
  path: string
  size: number | null
  modified: number | null
  estimated_time_s: number | null
  filament_mm: number | null
  filament_g: number | null
  layer_height_mm: number | null
  object_height_mm: number | null
  slicer: string | null
  thumbnail_url: string | null
  thumbnails: Record<string, unknown>[]
  raw: Record<string, unknown>
}

type FileDetailResponse = {
  printer_id: string
  file: FileEntry
  metadata: NormalizedFileMetadata
  compatibility_hints: string[]
}

type CurrentFileResponse = {
  printer_id: string
  filename: string | null
  detail: FileDetailResponse | null
}

type WebcamEntry = {
  uid: string
  name: string
  enabled: boolean
  stream_url: string | null
  snapshot_url: string | null
  location: string | null
  service: string | null
  aspect_ratio: string | null
}

type HistoryJob = {
  job_id: string | null
  filename: string | null
  status: string | null
  exists: boolean | null
  filament_used: number | null
  print_duration: number | null
  total_duration: number | null
  start_time: number | null
  end_time: number | null
  metadata: Record<string, unknown>
}

type HistoryResponse = {
  printer_id: string
  jobs: HistoryJob[]
  totals: {
    total_jobs: number
    total_time: number
    total_print_time: number
    total_filament_used: number
    longest_job: number
    longest_print: number
  }
}

type TimelapseEntry = {
  id: string
  name: string
  path: string
  size: number | null
  modified: number | null
  kind: 'video' | 'image'
}

type TimelapseResponse = {
  printer_id: string
  source_dir: string | null
  configured: boolean
  entries: TimelapseEntry[]
}

type DispatchUploadResponse = {
  filename: string
  size: number
  results: Array<{
    printer_id: string
    filename: string
    path: string | null
    size: number | null
    started_print: boolean
    warnings: string[]
    errors: string[]
  }>
}

type NozzleSaveResponse = {
  printer_id: string
  nozzle_diameter_mm: number
  config_path: string
  backup_path: string
}

type FleetMetricCard = {
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
  spool_remaining_g: number | null
  nozzle_diameter_mm: number | null
  current_material: string | null
  last_job_end_time: number | null
}

type MetricsResponse = {
  generated_at: string
  window_limit: number
  summary: {
    printer_count: number
    online_count: number
    active_prints: number
    paused_count: number
    attention_count: number
    maintenance_due_count: number
    total_jobs_window: number
    completed_jobs_window: number
    failed_jobs_window: number
    cancelled_jobs_window: number
    success_rate_window: number | null
    total_print_time_window: number
    total_filament_used_window: number
    total_spool_remaining_g: number
    avg_print_time_window: number
    hottest_printer_name: string | null
    hottest_printer_temp: number | null
  }
  printers: FleetMetricCard[]
}

type DryRunResult = {
  printer_id: string
  name: string
  eligible: boolean
  would_execute: boolean
  current_state: string | null
  required_state: string | null
  blocking_reasons: string[]
  warnings: string[]
  motion_summary?: string | null
}

type DryRunResponse = {
  action: string
  mode: string
  results: DryRunResult[]
}

type MotionCheckResponse = {
  printer_id: string
  name: string
  ok: boolean
  homed_axes: string
  current_state: string | null
  checks: string[]
  warnings: string[]
  blocking_reasons: string[]
}

type DispatchDryRunResult = {
  printer_id: string
  name: string
  eligible: boolean
  would_queue: boolean
  score: number
  blocking_reasons: string[]
  warnings: string[]
  recommendation: string | null
}

type DispatchDryRunResponse = {
  filename: string
  requested_material: string | null
  requested_nozzle_diameter_mm: number | null
  recommended_printer_ids: string[]
  results: DispatchDryRunResult[]
}

type GroupBy = 'none' | 'state' | 'tag'
type StateFilter = 'all' | 'ready' | 'printing' | 'paused' | 'offline' | 'attention'
type SortBy = 'attention' | 'name' | 'temperature' | 'success'
type DrawerSection = 'overview' | 'temperature' | 'jog' | 'macros' | 'files' | 'history' | 'webcams' | 'timelapse' | 'dryrun' | 'settings' | 'console' | 'bedmesh' | 'queue' | 'maintenance' | 'health' | 'cnc' | 'coolant' | 'analytics' | 'system-settings'

type VersionInfo = {
  version: string
  build_id: string
}

type LicenseStatus = { tier: string; days_remaining: number | null; device_limit: number | null }
type LicensePlan = { tier: string; price_per_month: number; device_limit: number; features: string[] }

type DashboardSettings = {
  card_layout: 'auto' | 'horizontal' | 'stacked'
  card_density: 'compact' | 'cozy' | 'comfortable'
  show_card_preview: boolean
  show_metrics_strip: boolean
  show_oee: boolean
  show_empty_capability_tiles: boolean
  default_drawer_section: DrawerSection
  metrics_history_limit: number
  metrics_refresh_seconds: number
  demo_mode_auto_login: boolean
  spoolman_url?: string | null
}

type FleetSettingsResponse = {
  dashboard_settings: DashboardSettings
  material_presets: TempPreset[]
  config_path?: string | null
  backup_path?: string | null
}

type UiTargetDraft = {
  provider: string
  label: string
  url: string
  mode: 'direct' | 'bootstrap'
  primary: boolean
}

type PrinterSettingsPayload = {
  id: string
  name: string
  enabled: boolean
  base_url: string
  ws_url: string | null
  auth_mode: string
  api_key_set: boolean
  serial: string | null
  tags: string[]
  compatibility_profile: string | null
  timelapse_dir: string | null
  fluidd_url: string | null
  camera_url: string | null
  ui_label: string | null
  ui_targets: UiTarget[]
  nozzle_diameter_mm: number | null
  filament_diameter_mm: number | null
  wire_used_mm_per_job: number | null
  build_volume: Record<string, number>
  supported_materials: string[]
  current_material: string | null
  current_spool_name: string | null
  spool_remaining_g: number | null
  spool_capacity_g: number | null
  filament_sensor: boolean
  probe: boolean
  webcam_expected: boolean
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
}

type PrinterSettingsDraft = {
  name: string
  enabled: boolean
  tagsText: string
  nozzleDiameter: string
  filamentDiameterMm: string
  wireUsedMmPerJob: string
  compatibilityProfile: string
  buildVolumeX: string
  buildVolumeY: string
  buildVolumeZ: string
  supportedMaterialsText: string
  currentMaterial: string
  currentSpoolName: string
  spoolRemainingG: string
  spoolCapacityG: string
  filamentSensor: boolean
  probe: boolean
  webcamExpected: boolean
  cameraUrl: string
  timelapseDir: string
  maintenanceLockout: boolean
  maintenanceState: string
  maintenanceDue: boolean
  maintenanceIntervalHours: string
  maintenanceIntervalJobs: string
  maintenanceIntervalFilamentG: string
  lastServiceAt: string
  nextServiceDue: string
  jogEnabled: boolean
  safeNozzleMaxC: string
  safeBedMaxC: string
  motionCheckRequired: boolean
  notesText: string
  maintenanceNotesText: string
  baseUrl: string
  wsUrl: string
  authMode: string
  apiKey: string
  apiKeySet: boolean
  apiKeyClear: boolean
  serial: string
  uiLabel: string
  fluiddUrl: string
  uiTargets: UiTargetDraft[]
}

// Protocols offered in the Add-device modal — mirrors the backend Protocol enum.
const DEVICE_PROTOCOLS: { value: string; label: string }[] = [
  { value: 'moonraker', label: 'Klipper / Moonraker' },
  { value: 'octoprint', label: 'OctoPrint' },
  { value: 'duet', label: 'Duet' },
  { value: 'prusa_connect', label: 'Prusa Connect' },
  { value: 'marlin', label: 'Marlin' },
  { value: 'fluidnc', label: 'FluidNC' },
  { value: 'grbl', label: 'GRBL' },
  { value: 'linuxcnc', label: 'LinuxCNC' },
  { value: 'mach3', label: 'Mach3' },
  { value: 'mach4', label: 'Mach4' },
  { value: 'opcua', label: 'OPC-UA' },
  { value: 'sinumerik', label: 'Siemens Sinumerik' },
  { value: 'haas', label: 'Haas' },
  { value: 'fanuc', label: 'Fanuc' },
  { value: 'fadal', label: 'Fadal' },
  { value: 'openpcb', label: 'OpenPnP' },
  { value: 'bambu_mqtt', label: 'Bambu Lab (local MQTT, beta)' },
  { value: 'mqtt', label: 'Generic MQTT' },
]
// Protocols that authenticate with an access code / API key.
const PROTOCOLS_WITH_API_KEY = new Set(['octoprint', 'duet', 'prusa_connect', 'bambu_mqtt'])

type AddDeviceDraft = {
  id: string
  name: string
  protocol: string
  base_url: string
  enabled: boolean
  serial: string
  apiKey: string
  mqttTopic: string
  mqttFieldMapping: string
}

const EMPTY_ADD_DEVICE_DRAFT: AddDeviceDraft = {
  id: '', name: '', protocol: 'moonraker', base_url: '', enabled: true,
  serial: '', apiKey: '', mqttTopic: '', mqttFieldMapping: '',
}

type JogAxis = 'X' | 'Y' | 'Z' | 'E' | 'A' | 'B' | 'C'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const QUICK_ACTIONS = ['pause', 'resume', 'cancel', 'home', 'cooldown', 'motors_off', 'firmware_restart'] as const

function printerType(p: Printer): MachineTypeValue {
  if (p.capability.machine_type && p.capability.machine_type !== 'fdm') return p.capability.machine_type
  if (!p.capability.safe_nozzle_max_c) return 'sla'
  if ((p.capability.current_material || '').includes(' / ')) return 'idex'
  return 'fdm'
}
const BATCH_ACTIONS = ['home', 'motors_off', 'cooldown', 'pause', 'resume', 'cancel', 'firmware_restart'] as const
const BUILTIN_TEMP_PRESETS: TempPreset[] = [
  { label: 'ABS',      nozzle: 250, bed: 100, builtin: true },
  { label: 'ABS-CF',   nozzle: 260, bed: 110, builtin: true },
  { label: 'ASA',      nozzle: 255, bed: 100, builtin: true },
  { label: 'Cool',     nozzle: 0,   bed: 0,   builtin: true },
  { label: 'FLEX',     nozzle: 230, bed: 45,  builtin: true },
  { label: 'HIPS',     nozzle: 240, bed: 95,  builtin: true },
  { label: 'Nylon',    nozzle: 255, bed: 90,  builtin: true },
  { label: 'Nylon-CF', nozzle: 270, bed: 100, builtin: true },
  { label: 'PA12',     nozzle: 260, bed: 95,  builtin: true },
  { label: 'PC',       nozzle: 270, bed: 110, builtin: true },
  { label: 'PC-ABS',   nozzle: 265, bed: 110, builtin: true },
  { label: 'PET',      nozzle: 245, bed: 80,  builtin: true },
  { label: 'PETG',     nozzle: 240, bed: 80,  builtin: true },
  { label: 'PETG-CF',  nozzle: 250, bed: 85,  builtin: true },
  { label: 'PLA',      nozzle: 210, bed: 60,  builtin: true },
  { label: 'PLA+',     nozzle: 215, bed: 65,  builtin: true },
  { label: 'PLA-CF',   nozzle: 220, bed: 65,  builtin: true },
  { label: 'PLA-HF',   nozzle: 220, bed: 60,  builtin: true },
  { label: 'PP',       nozzle: 230, bed: 85,  builtin: true },
  { label: 'PVA',      nozzle: 205, bed: 55,  builtin: true },
  { label: 'TPE',      nozzle: 225, bed: 45,  builtin: true },
  { label: 'TPU',      nozzle: 225, bed: 50,  builtin: true },
]
const MATERIAL_PRESET_STORAGE_KEY = 'memar-material-presets-v2'
const DEFAULT_DASHBOARD_SETTINGS: DashboardSettings = {
  card_layout: 'horizontal',
  card_density: 'cozy',
  show_card_preview: true,
  show_metrics_strip: true,
  show_oee: true,
  show_empty_capability_tiles: false,
  default_drawer_section: 'overview',
  metrics_history_limit: 50,
  metrics_refresh_seconds: 15,
  demo_mode_auto_login: true,
  spoolman_url: null,
}

function generateMockPrinters(): Printer[] {
  const base: PrinterCapability = {
    profile: 'Generic FDM', nozzle_diameter_mm: 0.4,
    build_volume: { x_mm: 200, y_mm: 200, z_mm: 200 },
    supported_materials: ['PLA', 'PETG', 'ABS', 'TPU', 'FLEX'],
    current_material: 'PLA', current_spool_name: null, spool_remaining_g: 1000, spool_capacity_g: 1000,
    filament_sensor: true, probe: true, webcam_expected: true,
    fluidd_url: null, camera_url: null, ui_label: null, ui_targets: [],
    maintenance_lockout: false, maintenance_state: null, maintenance_due: false,
    maintenance_interval_hours: null, maintenance_interval_jobs: null,
    maintenance_interval_filament_g: null, last_service_at: null, next_service_due: null,
    jog_enabled: true, safe_nozzle_max_c: 300, safe_bed_max_c: 120,
    motion_check_required: false, notes: [], maintenance_notes: [],
  }

  // One printer per combo: state × webcam coverage
  // i=0 printing+cam  i=1 printing+no-cam  i=2 paused+cam    i=3 ready+cam
  // i=4 ready+no-cam  i=5 error+cam        i=6 offline+cam   i=7 offline+no-cam
  type MC = { name: string; online: boolean; state: string; webcams: number; nozzle: number | null; nozzle2?: number | null; bed: number | null; nozzleTarget: number | null; nozzle2Target?: number | null; bedTarget: number | null; material: string; spool: number | null; nozzleDia: number | null; maintDue: boolean; file: string | null; progress: number | null; eta: number | null; actions: string[]; anomalies: Anomaly[]; attention: boolean; machineType?: MachineTypeValue; capExtra?: Partial<PrinterCapability> }
  const configs: MC[] = [
    { name: 'Bambu X1',             online: true,  state: 'printing', webcams: 1, nozzle: 183, bed: 58,  nozzleTarget: 215, bedTarget: 60,  material: 'PLA',   spool: 85,   nozzleDia: 0.4, maintDue: false, file: 'bracket_assy_01.gcode',  progress: 52.1, eta: 2760, actions: ['pause','cancel','home','cooldown'], anomalies: [], attention: false },
    { name: 'Prusa i3 MK4',         online: true,  state: 'printing', webcams: 0, nozzle: 214, bed: 65,  nozzleTarget: 215, bedTarget: 65,  material: 'PETG',  spool: 420,  nozzleDia: 0.4, maintDue: false, file: 'hull_bracket_v3.gcode',  progress: 34.2, eta: 4320, actions: ['pause','cancel','home','cooldown'], anomalies: [], attention: false },
    { name: 'Creality Ender 5 Plus', online: true,  state: 'paused',   webcams: 1, nozzle: 238, bed: 80,  nozzleTarget: 235, bedTarget: 80,  material: 'PETG',  spool: 420,  nozzleDia: 0.6, maintDue: false, file: 'exhaust_manifold.gcode', progress: 78.9, eta: 890,  actions: ['resume','cancel'], anomalies: [{ code: 'PAUSE', severity: 'warning', message: 'Filament runout detected — waiting for reload' }], attention: true },
    { name: 'Formlabs Form 3',       online: true,  state: 'ready',    webcams: 1, nozzle: 26,  bed: 24,  nozzleTarget: null, bedTarget: null, material: 'ABS',   spool: 1000, nozzleDia: 0.4, maintDue: false, file: null, progress: null, eta: null, actions: ['home','cooldown'], anomalies: [], attention: false },
    { name: 'Formlabs Form 4',       online: true,  state: 'ready',    webcams: 0, nozzle: 22,  bed: 20,  nozzleTarget: null, bedTarget: null, material: 'FLEX',  spool: 750,  nozzleDia: 0.8, maintDue: true,  file: null, progress: null, eta: null, actions: ['home','cooldown'], anomalies: [], attention: true },
    { name: 'Prusa MK4S',            online: true,  state: 'error',    webcams: 1, nozzle: 22,  bed: 22,  nozzleTarget: null, bedTarget: null, material: 'PLA',   spool: 1000, nozzleDia: 0.4, maintDue: true,  file: null, progress: null, eta: null, actions: [], anomalies: [{ code: 'E_TEMP', severity: 'critical', message: 'Thermal runaway detected — extruder heater' }], attention: true },
    { name: 'Sonic Mega 8K',         online: false, state: 'offline',  webcams: 1, nozzle: null, bed: null, nozzleTarget: null, bedTarget: null, material: 'PLA',   spool: 1000, nozzleDia: 0.4, maintDue: false, file: null, progress: null, eta: null, actions: [], anomalies: [{ code: 'CONN', severity: 'critical', message: 'Printer offline — no response for 3 minutes' }], attention: true },
    { name: 'Ultimaker S5 Pro',      online: false, state: 'offline',  webcams: 0, nozzle: null, bed: null,  nozzleTarget: null, bedTarget: null, material: 'TPU',            spool: 320,  nozzleDia: 0.4, maintDue: false, file: null,                    progress: null, eta: null, actions: [], anomalies: [{ code: 'CONN', severity: 'critical', message: 'Printer offline — no response for 5 minutes' }], attention: true },
    { name: 'RatRig V-Core 4 IDEX',  online: true,  state: 'printing', webcams: 1, nozzle: 220, nozzle2: 218, bed: 70, nozzleTarget: 220, nozzle2Target: 220, bedTarget: 70, material: 'PLA / PETG', spool: 680,  nozzleDia: 0.4, maintDue: false, file: 'dual_housing_assy.gcode', progress: 61.4, eta: 3180, actions: ['pause','cancel','home','cooldown'], anomalies: [], attention: false },
    { name: 'Elegoo Mars 4 Ultra',   online: true,  state: 'printing', webcams: 0, nozzle: null, bed: 28,   nozzleTarget: null, bedTarget: null, material: 'ABS Resin', spool: null, nozzleDia: null, maintDue: false, file: 'bracket_resin_v1.stl',    progress: 38.7, eta: 5400, actions: ['pause','cancel'], anomalies: [], attention: false },
    { name: 'Shapeoko 5 Pro',        online: true,  state: 'printing', webcams: 1, nozzle: null, bed: null,  nozzleTarget: null, bedTarget: null, material: 'Birch Plywood', spool: null, nozzleDia: null, maintDue: false, file: 'front_panel_v3.nc',        progress: 47.2, eta: 2100, actions: ['pause','cancel'], anomalies: [], attention: false, machineType: 'cnc_router', capExtra: { safe_nozzle_max_c: 0, spindle_rpm_max: 24000, spindle_rpm_current: 18000, feed_rate_mm_min: 2800, work_envelope_mm: { x: 838, y: 838, z: 140 }, coolant_active: false, position_xyz: { x: 212.4, y: 305.1, z: -8.3 } } },
    { name: 'OMTech 60W CO2 Laser',  online: true,  state: 'printing', webcams: 0, nozzle: null, bed: null,  nozzleTarget: null, bedTarget: null, material: 'Acrylic 6mm',  spool: null, nozzleDia: null, maintDue: false, file: 'logo_cut_v2.lbrn2',        progress: 83.1, eta: 480,  actions: ['pause','cancel'], anomalies: [], attention: false, machineType: 'laser',      capExtra: { safe_nozzle_max_c: 0, laser_power_pct: 72, feed_rate_mm_min: 3600, air_assist_active: true, work_envelope_mm: { x: 600, y: 400, z: 0 }, position_xyz: { x: 498.2, y: 132.7, z: 0 } } },
    { name: 'Hypertherm Powermax 45', online: true,  state: 'printing', webcams: 0, nozzle: null, bed: null,  nozzleTarget: null, bedTarget: null, material: 'Mild Steel 6mm', spool: null, nozzleDia: null, maintDue: true,  file: 'brackets_plasma.nc',     progress: 29.8, eta: 1620, actions: ['pause','cancel'], anomalies: [], attention: true,  machineType: 'plasma',     capExtra: { safe_nozzle_max_c: 0, torch_voltage: 128.4, arc_ok: true, thc_active: true, feed_rate_mm_min: 1200, work_envelope_mm: { x: 1500, y: 3000, z: 0 }, position_xyz: { x: 445.0, y: 1102.3, z: 0 } } },
    { name: 'Creality Ender 3 S1 Pro', online: true, state: 'printing', webcams: 1, nozzle: 200, bed: 55, nozzleTarget: 200, bedTarget: 55, material: 'PLA', spool: 680, nozzleDia: 0.4, maintDue: false, file: 'figurine_base.gcode', progress: 71.2, eta: 1440, actions: ['pause','cancel','home','cooldown'], anomalies: [], attention: false, machineType: 'fdm', capExtra: { machine_type: 'fdm' } },
    { name: 'Liteplacer v2',             online: true,  state: 'printing', webcams: 1, nozzle: null, bed: null,  nozzleTarget: null, bedTarget: null, material: 'SMD Components', spool: null, nozzleDia: null, maintDue: false, file: 'rev2_board.job',           progress: 55.3, eta: 900,  actions: ['pause','cancel'], anomalies: [], attention: false, machineType: 'pick_and_place', capExtra: { safe_nozzle_max_c: 0, work_envelope_mm: { x: 300, y: 250, z: 0 }, position_xyz: { x: 142.3, y: 88.7, z: 0 } } },
  ]

  return configs.map((c, i) => ({
    id: `mock-${i}`,
    name: c.name,
    base_url: `http://mock-${i}.local`,
    online: c.online,
    state: c.state,
    state_message: c.state === 'error' ? 'Check printer' : c.state === 'offline' ? 'Connection lost' : null,
    nozzle: { temperature: c.nozzle, target: c.nozzleTarget },
    ...(c.nozzle2 != null ? { nozzle2: { temperature: c.nozzle2, target: c.nozzle2Target ?? null } } : {}),
    bed:    { temperature: c.bed,    target: c.bedTarget },
    job: { filename: c.file, state: c.file ? c.state : (c.online ? 'idle' : 'offline'), progress: c.progress, eta_seconds: c.eta, message: null },
    anomalies: c.anomalies,
    warnings: [],
    attention_needed: c.attention,
    tags: [],
    available_actions: c.actions,
    webcams_count: c.webcams,
    macros_count: 2,
    capability: { ...base, nozzle_diameter_mm: c.nozzleDia ?? base.nozzle_diameter_mm, current_material: c.material, spool_remaining_g: c.spool ?? 0, maintenance_due: c.maintDue, safe_nozzle_max_c: c.nozzleDia == null ? 0 : base.safe_nozzle_max_c, machine_type: c.machineType ?? 'fdm', ...(c.capExtra ?? {}) },
  }))
}

const SelectionTray = React.memo(function SelectionTray({ selected, printers, expanded, onToggle, onRemove, onClearAll }: {
  selected: Set<string>
  printers: Printer[]
  expanded: boolean
  onToggle: () => void
  onRemove: (id: string) => void
  onClearAll: () => void
}) {
  const getName = (id: string) => printers.find((p) => p.id === id)?.name ?? id
  const count = selected.size

  if (count === 0) return <span className="tray-empty">None selected</span>

  const INLINE_MAX = 5

  const pills = Array.from(selected).map((id) => (
    <span key={id} className="selection-pill">
      {getName(id)}
      <button onClick={() => onRemove(id)} aria-label={`Deselect ${getName(id)}`} title={`Deselect ${getName(id)}`}>×</button>
    </span>
  ))

  if (count <= INLINE_MAX) {
    return <>{pills}<button className="tray-clear" onClick={onClearAll} title="Deselect all devices">Clear all</button></>
  }

  const visible = expanded ? pills : pills.slice(0, 3)
  const overflow = count - 3

  return (
    <>
      {visible}
      {!expanded && <button className="tray-more" onClick={onToggle} title={`Show ${overflow} more selected device${overflow === 1 ? '' : 's'}`}>+{overflow} more</button>}
      {expanded && <button className="tray-more" onClick={onToggle} title="Collapse the selection list">▲ collapse</button>}
      <button className="tray-clear" onClick={onClearAll} title="Deselect all devices">Clear all</button>
    </>
  )
})

const MOCK_PRINTERS = generateMockPrinters()
const DEMO_DEVICE_PHOTO: Record<string, string> = {
  'mock-1': '/demo-devices/prusa-i3-mk4.glb',
  'mock-4': '/demo-devices/formlabs-form-4.glb',
  'mock-7': '/demo-devices/ultimaker-s5-pro.glb',
  'mock-9': '/demo-devices/elegoo-mars-4-ultra.glb',
  'mock-11': '/demo-devices/omtech-60w-laser.glb',
  'mock-12': '/demo-devices/hypertherm-powermax-45.glb',
}
// Real devices whose compatibility_profile (or name) matches one of the 6 shipped
// GLBs get a 3D model on the fleet card, same as the demo fleet. Keyed by the
// exact compatibility_profile string an operator sets in device config.
const REAL_DEVICE_PHOTOS: Record<string, string> = {
  'Prusa i3 MK4': '/demo-devices/prusa-i3-mk4.glb',
  'Formlabs Form 4': '/demo-devices/formlabs-form-4.glb',
  'Ultimaker S5 Pro': '/demo-devices/ultimaker-s5-pro.glb',
  'Elegoo Mars 4 Ultra': '/demo-devices/elegoo-mars-4-ultra.glb',
  'OMTech 60W CO2 Laser': '/demo-devices/omtech-60w-laser.glb',
  'Hypertherm Powermax 45': '/demo-devices/hypertherm-powermax-45.glb',
}
// Resolve a GLB for a real device: explicit capability.model_url wins, else match
// the device's compatibility_profile, else its name, against the shipped GLBs.
function getDevicePhotoUrl(printer: Printer): string | null {
  const explicit = printer.capability?.model_url
  if (explicit) return explicit
  const profile = printer.capability?.profile
  if (profile && REAL_DEVICE_PHOTOS[profile]) return REAL_DEVICE_PHOTOS[profile]
  if (printer.name && REAL_DEVICE_PHOTOS[printer.name]) return REAL_DEVICE_PHOTOS[printer.name]
  return null
}
// Only substitute mock printers when the session came from demo auto-login —
// real deployments with an empty fleet must show an empty fleet, not fakes.
const demoModeRef = { current: false }
// True once the user has established a genuine (credentialed / SSO / restored)
// session. Used to decide, on a dead session (memar:unauthorized), whether to
// route to the login screen (real operator) vs. re-auth as the read-only demo
// account (fresh first-visit preview). demoModeRef is sticky across
// demo→logout→real-login, so it can't be used for this — we need a positive
// "this was a real session" signal instead.
const hadRealSession = { current: false }

const SIM_SCENARIOS: (Partial<Printer> & { capOverrides?: Partial<PrinterCapability> })[] = [
  { online: true, state: 'printing', state_message: null, nozzle: { temperature: 214, target: 215 }, bed: { temperature: 65, target: 65 }, job: { filename: 'hull_bracket_v3.gcode', state: 'printing', progress: 34.2, eta_seconds: 4320 }, anomalies: [], attention_needed: false, capOverrides: { current_material: 'PLA', spool_remaining_g: 750 } },
  { online: true, state: 'printing', state_message: null, nozzle: { temperature: 238, target: 240 }, bed: { temperature: 80, target: 80 }, job: { filename: 'exhaust_manifold.gcode', state: 'printing', progress: 78.9, eta_seconds: 890 }, anomalies: [], attention_needed: false, capOverrides: { current_material: 'PETG', spool_remaining_g: 420 } },
  { online: true, state: 'paused',   state_message: null, nozzle: { temperature: 183, target: 210 }, bed: { temperature: 58, target: 65  }, job: { filename: 'bracket_assy_01.gcode', state: 'paused',   progress: 52.1, eta_seconds: null }, anomalies: [{ code: 'PAUSE', severity: 'warning', message: 'Filament runout detected — waiting for reload' }], attention_needed: true, capOverrides: { current_material: 'PLA', spool_remaining_g: 85, maintenance_due: false } },
  { online: true, state: 'ready',    state_message: null, nozzle: { temperature: 26,  target: null  }, bed: { temperature: 24, target: null  }, job: { filename: null, state: 'idle', progress: null, eta_seconds: null }, anomalies: [], attention_needed: false, capOverrides: { current_material: 'ABS', spool_remaining_g: 1000, maintenance_due: false } },
  { online: true, state: 'error',    state_message: 'Thermal runaway on extruder heater', nozzle: { temperature: 22, target: null }, bed: { temperature: 22, target: null }, job: { filename: null, state: 'error', progress: null, eta_seconds: null }, anomalies: [{ code: 'E_TEMP', severity: 'critical', message: 'Thermal runaway detected — extruder heater' }], attention_needed: true, capOverrides: { current_material: null, maintenance_due: true } },
  { online: false, state: 'offline',  state_message: 'Connection lost', nozzle: { temperature: null, target: null }, bed: { temperature: null, target: null }, job: { filename: null, state: 'offline', progress: null, eta_seconds: null }, anomalies: [{ code: 'CONN', severity: 'critical', message: 'Printer offline — no response for 3 minutes' }], attention_needed: true, capOverrides: { current_material: 'PLA' } },
  { online: true, state: 'printing', state_message: null, nozzle: { temperature: 200, target: 200 }, bed: { temperature: 55, target: 55 }, job: { filename: 'nozzle_spacer_x4.gcode', state: 'printing', progress: 88.3, eta_seconds: 240 }, anomalies: [], attention_needed: false, capOverrides: { current_material: 'TPU', spool_remaining_g: 320 } },
]

export default function App() {
  const [fleet, setFleet] = useState<FleetPayload>(() => ({ generated_at: '', printers: [] }))
  const [fleetLoaded, setFleetLoaded] = useState<boolean>(false)
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [fleetKpi, setFleetKpi] = useState<FleetKpi | null>(null)
  const [oeeByDevice, setOeeByDevice] = useState<Map<string, OeeDevice | null>>(new Map())
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [actionMessage, setActionMessage] = useState<string>('')
  const [search, setSearch] = useState<string>('')
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [tagFilter, setTagFilter] = useState<string>('all')
  const [groupBy, setGroupBy] = useState<GroupBy>('none')
  const [sortBy, setSortBy] = useState<SortBy>('attention')
  const [detailsOpen, setDetailsOpen] = useState<boolean>(false)
  const [analyticsOpen, setAnalyticsOpen] = useState<boolean>(false)
  const [serviceOpen, setServiceOpen] = useState<boolean>(false)
  const [detailsPrinterId, setDetailsPrinterId] = useState<string>('')
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null)
  const [editingPrinterId, setEditingPrinterId] = useState<string | null>(null)
  const [editingPrinterName, setEditingPrinterName] = useState<string>('')
  const [macros, setMacros] = useState<MacroEntry[]>([])
  const [macroSearch, setMacroSearch] = useState<string>('')
  const [savePresetLabel, setSavePresetLabel] = useState<string | null>(null)
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [fileBrowser, setFileBrowser] = useState<FileBrowserResponse | null>(null)
  // filename (gcodes-relative) -> times run on THIS device, from JobLog.
  const [printCounts, setPrintCounts] = useState<Map<string, number>>(new Map())
  const [currentFileDetail, setCurrentFileDetail] = useState<CurrentFileResponse | null>(null)
  const [selectedFileDetail, setSelectedFileDetail] = useState<FileDetailResponse | null>(null)
  const [webcams, setWebcams] = useState<WebcamEntry[]>([])
  const [timelapse, setTimelapse] = useState<TimelapseResponse | null>(null)
  const [drawerLoading, setDrawerLoading] = useState<boolean>(false)
  const [drawerMessage, setDrawerMessage] = useState<DrawerMessage>({ text: '', severity: 'info' })
  // Toast notification queue
  const [toasts, setToasts] = useState<Array<{id: number; type: 'info' | 'warning' | 'error' | 'success'; text: string}>>([])
  const toastIdRef = React.useRef(0)
  const wsReconnectAttemptRef = React.useRef(0)
  const wsCurrentRef = React.useRef<WebSocket | null>(null)
  const accessTokenRef = React.useRef<string | null>(null)
  const consoleScrollRef = React.useRef<HTMLDivElement>(null)
  const workspaceCtrlRef = useRef<AbortController | null>(null)
  const bedMeshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const drawerWorkspaceRef = useRef<HTMLElement>(null)
  const drawerFleetSettingsRef = useRef<HTMLElement>(null)
  const previousActiveElementRef = useRef<HTMLElement | null>(null)
  const pushToast = React.useCallback((text: string, type: 'info' | 'warning' | 'error' | 'success' = 'info') => {
    const id = ++toastIdRef.current
    setToasts((prev) => [...prev.slice(-4), {id, type, text}])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5000)
  }, [])

  const setDrawerMsg = React.useCallback((text: string, severity: 'success' | 'error' | 'info' | 'warning' = 'info') => {
    setDrawerMessage({ text, severity })
  }, [])

  const [filePath, setFilePath] = useState<string>('gcodes')
  const [fileSort, setFileSort] = useState<'name' | 'size' | 'modified' | 'last_printed'>('name')
  const [fileSearchTerm, setFileSearchTerm] = useState<string>('')
  const [historyStatusFilter, setHistoryStatusFilter] = useState<string>('all')
  const [historySort, setHistorySort] = useState<'date' | 'filament' | 'duration'>('date')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadAutoPrint, setUploadAutoPrint] = useState<boolean>(false)
  const [customNozzle, setCustomNozzle] = useState<string>('0')
  const [customBed, setCustomBed] = useState<string>('0')
  const [settingsNozzle, setSettingsNozzle] = useState<string>('0.4')
  const [dashboardUploadFile, setDashboardUploadFile] = useState<File | null>(null)
  const [dashboardUploadAutoPrint, setDashboardUploadAutoPrint] = useState<boolean>(false)
  const [dashboardUploadTargetId, setDashboardUploadTargetId] = useState<string>('')
  const [dashboardUseSelected, setDashboardUseSelected] = useState<boolean>(true)
  const [uploadPanelOpen, setUploadPanelOpen] = useState(false)
  const [dashboardUploadMessage, setDashboardUploadMessage] = useState<string>('')
  const [version, setVersion] = useState<VersionInfo | null>(null)
  const [dashboardSettings, setDashboardSettings] = useState<DashboardSettings>(DEFAULT_DASHBOARD_SETTINGS)
  const [activeSection, setActiveSection] = useState<DrawerSection>(DEFAULT_DASHBOARD_SETTINGS.default_drawer_section)
  const [fleetSettingsOpen, setFleetSettingsOpen] = useState<boolean>(false)
  const [fleetToolsOpen, setFleetToolsOpen] = useState<boolean>(false)
  const [addDeviceOpen, setAddDeviceOpen] = useState<boolean>(false)
  const [addDeviceDraft, setAddDeviceDraft] = useState<AddDeviceDraft>(EMPTY_ADD_DEVICE_DRAFT)
  const [addDeviceMessage, setAddDeviceMessage] = useState<string>('')
  const [setupWizardOpen, setSetupWizardOpen] = useState(false)
  const setupWizardShownThisSession = useRef(false)
  // In-flight guards for submit actions (prevent double-submit on double-click / Enter).
  // Ref gives a synchronous early-return; the state flag drives the button disabled/label.
  const [addDeviceBusy, setAddDeviceBusy] = useState(false)
  const addDeviceBusyRef = React.useRef(false)
  const [uploadBusy, setUploadBusy] = useState(false)
  const uploadBusyRef = React.useRef(false)
  const [dashboardUploadBusy, setDashboardUploadBusy] = useState(false)
  const dashboardUploadBusyRef = React.useRef(false)
  const [loginBusy, setLoginBusy] = useState(false)
  const loginBusyRef = React.useRef(false)
  const [fleetSettingsDraft, setFleetSettingsDraft] = useState<DashboardSettings>(DEFAULT_DASHBOARD_SETTINGS)
  const [fleetSettingsMessage, setFleetSettingsMessage] = useState<string>('')
  const [attentionDropdownOpen, setAttentionDropdownOpen] = useState<boolean>(false)
  const attentionDropdownRef = useRef<HTMLDivElement>(null)
  const [tempHistory, setTempHistory] = useState<Map<string, { nozzle: number[]; bed: number[] }>>(() => new Map())
  const [wsConnected, setWsConnected] = useState<boolean>(false)
  const [matrixSortCol, setMatrixSortCol] = useState<string>('name')
  const [matrixSortDir, setMatrixSortDir] = useState<'asc' | 'desc'>('asc')
  const [simMode, setSimMode] = useState<boolean>(false)
  const [printerSettingsDraft, setPrinterSettingsDraft] = useState<PrinterSettingsDraft | null>(null)
  const [printerSettingsMessage, setPrinterSettingsMessage] = useState<string>('')
  const [materialPresetEditLabel, setMaterialPresetEditLabel] = useState<string>('PLA')
  const [materialPresetEditNozzle, setMaterialPresetEditNozzle] = useState<string>('210')
  const [materialPresetEditBed, setMaterialPresetEditBed] = useState<string>('60')
  const [drawerDryRunAction, setDrawerDryRunAction] = useState<string>('home')
  const [dryRunPayload, setDryRunPayload] = useState<DryRunResponse | null>(null)
  const [motionIntent, setMotionIntent] = useState<'home' | 'jog' | 'park' | 'macro' | 'mesh' | 'unknown'>('home')
  const [motionCheckPayload, setMotionCheckPayload] = useState<MotionCheckResponse | null>(null)
  const [dispatchFilename, setDispatchFilename] = useState<string>('')
  const [dispatchMaterial, setDispatchMaterial] = useState<string>('')
  const [dispatchNozzle, setDispatchNozzle] = useState<string>('0.4')
  const [dispatchDryRunPayload, setDispatchDryRunPayload] = useState<DispatchDryRunResponse | null>(null)
  const [jogAxis, setJogAxis] = useState<JogAxis>('X')
  const [jogDistance, setJogDistance] = useState<string>('1')
  const [jogFeedrate, setJogFeedrate] = useState<string>('3000')
  const [customPresets, setCustomPresets] = useState<TempPreset[]>([])
  const batchPresetLabel = useMemo(() => {
    const counts = new Map<string, number>()
    for (const p of fleet.printers) {
      const m = p.capability.current_material
      if (m) counts.set(m, (counts.get(m) || 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'PLA'
  }, [fleet.printers])
  const [selectionTrayExpanded, setSelectionTrayExpanded] = useState(false)
  const [cardPresetByPrinter, setCardPresetByPrinter] = useState<Record<string, string>>({})
  const [uiMenuPrinterId, setUiMenuPrinterId] = useState<string | null>(null)
  const [snapTs, setSnapTs] = useState(Date.now())
  const [macroParams, setMacroParams] = useState<Record<string, string>>({})
  // Per-macro, per-param values for macros whose parameters the backend could
  // type. Kept separate from macroParams (the free-text fallback) so an untyped
  // macro keeps working exactly as before.
  const [macroTypedParams, setMacroTypedParams] = useState<Record<string, Record<string, string>>>({})
  const [showPrivateMacros, setShowPrivateMacros] = useState<boolean>(false)
  const [confirmState, setConfirmState] = useState<{ message: string; onConfirm: () => void } | null>(null)
  // Shown when a CNC control action 403s with alpha_ack_required (see
  // require_alpha_ack in deps.py). retry re-runs the exact action that
  // triggered the modal once the user acknowledges — never shown for
  // 3D-printer routes, which never carry the alpha flag.
  const [alphaAckPending, setAlphaAckPending] = useState<{ printer: Printer; retry: () => void } | null>(null)
  const [macroExpanded, setMacroExpanded] = useState<string | null>(null)
  // Persist the device-limit upgrade-hint dismissal so it doesn't re-nag on every
  const [activeWebcam, setActiveWebcam] = useState<Record<string, string>>({})
  const [cardMacros, setCardMacros] = useState<Record<string, MacroEntry[]>>({})
  const [cardMacroPins, setCardMacroPins] = useState<Record<string, string[]>>(() => {
    try { return JSON.parse(localStorage.getItem('memar-macro-pins') || '{}') } catch { return {} }
  })
  const [cardLog, setCardLog] = useState<Record<string, {msg: string, ok: boolean}[]>>({})

  // Console tab state
  const [consoleLog, setConsoleLog] = useState<Array<{type: 'sent' | 'recv' | 'error'; text: string}>>([])
  const [consoleInput, setConsoleInput] = useState<string>('')
  // Commands the operator typed, oldest first — distinct from consoleLog, which
  // is the printer's own gcode transcript pulled from /gcode/history. Persisted
  // per printer in localStorage so it survives closing the drawer.
  const [consoleHistory, setConsoleHistory] = useState<string[]>([])
  // Cursor into consoleHistory for up/down browsing. Equal to the array length
  // means "not browsing" — the input holds whatever the user is typing.
  const [consoleHistoryIndex, setConsoleHistoryIndex] = useState<number>(0)
  // TAB-completion cycle. A ref, not state: it's transient bookkeeping that must
  // be readable and writable within a single keydown, and it never renders.
  const consoleCycleRef = useRef<CompletionCycle>(NO_COMPLETION_CYCLE)

  useEffect(() => {
    if (consoleScrollRef.current) consoleScrollRef.current.scrollTop = consoleScrollRef.current.scrollHeight
  }, [consoleLog])
  const [consoleSending, setConsoleSending] = useState<boolean>(false)
  // Temperature history detail (fetched on demand from /api/.../temperature-history)
  const [tempHistoryDetail, setTempHistoryDetail] = useState<{extruder: Array<{time: number; temperature: number; target: number | null}>; bed: Array<{time: number; temperature: number; target: number | null}>} | null>(null)
  // Bed mesh state
  const [bedMesh, setBedMesh] = useState<{supported: boolean; profile: string; mesh_matrix: number[][]; x_count: number; y_count: number; min_z: number; max_z: number} | null>(null)
  // Exclude objects state
  const [excludeObjects, setExcludeObjects] = useState<{supported: boolean; objects: Array<{name: string; polygon?: number[][]}>; excluded: string[]; current_object?: string | null} | null>(null)
  // Filament quick-edit state (overview tab)
  const [quickMaterial, setQuickMaterial] = useState<string>('')
  const [quickRemaining, setQuickRemaining] = useState<string>('')
  const [quickFilamentSaving, setQuickFilamentSaving] = useState(false)
  const [spoolEstimating, setSpoolEstimating] = useState(false)
  const [spoolEstimateResult, setSpoolEstimateResult] = useState<{estimated_g: number, fill_pct: number, confidence: string, reasoning: string, model_used: string} | null>(null)
  // Spool log state
  type SpoolLogEntry = { id: number; job_name: string | null; filament_used_mm: number | null; filament_used_g: number | null; spool_before_g: number | null; spool_after_g: number | null; material: string | null; source: string; note: string | null; created_at: string | null }
  const [spoolLog, setSpoolLog] = useState<SpoolLogEntry[]>([])
  const [spoolLogLoading, setSpoolLogLoading] = useState(false)
  const [spoolLogOpen, setSpoolLogOpen] = useState(false)
  // CV anomaly state
  const [cvAnomalies, setCvAnomalies] = useState<Record<string, {type: string, score: number, confidence: string, reasoning: string, ts?: string}[]>>({})
  // Batch preheat state
  const [batchPreheatLabel, setBatchPreheatLabel] = useState<string>('PLA')
  const [batchCustomNozzle, setBatchCustomNozzle] = useState<string>('')
  const [batchCustomBed, setBatchCustomBed] = useState<string>('')

  function pushCardLog(printerId: string, msg: string, ok: boolean) {
    setCardLog(prev => ({ ...prev, [printerId]: [...(prev[printerId] || []), {msg, ok}].slice(-8) }))
    if (!ok) pushToast(msg, 'error')
  }
  function clearCardLog(printerId: string) {
    setCardLog(prev => ({ ...prev, [printerId]: [] }))
  }
  const [hiddenPresets, setHiddenPresets] = useState<Set<string>>(() => {
    try { return new Set<string>(JSON.parse(localStorage.getItem('memar-hidden-presets') || '[]')) } catch { return new Set() }
  })

  useEffect(() => {
    const t = setInterval(() => setSnapTs(Date.now()), 8000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!attentionDropdownOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (attentionDropdownRef.current && !attentionDropdownRef.current.contains(e.target as Node)) {
        setAttentionDropdownOpen(false)
      }
    }
    const handleEscKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setAttentionDropdownOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscKey)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscKey)
    }
  }, [attentionDropdownOpen])

  useEffect(() => {
    if (!detailsOpen && !fleetSettingsOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (fleetSettingsOpen) setFleetSettingsOpen(false)
      if (detailsOpen) { closeWorkspace() }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [detailsOpen, fleetSettingsOpen])

  // Body scroll lock when drawers are open
  useEffect(() => {
    const drawerOpen = detailsOpen || fleetSettingsOpen
    if (drawerOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [detailsOpen, fleetSettingsOpen])

  // Focus management and trap for workspace drawer
  useEffect(() => {
    if (!detailsOpen || !drawerWorkspaceRef.current) return

    // Store previous focus for restoration
    previousActiveElementRef.current = document.activeElement as HTMLElement

    // Set initial focus to first focusable element or close button
    const closeButton = drawerWorkspaceRef.current.querySelector<HTMLElement>(
      'button[onClick]'
    )
    if (closeButton?.textContent?.includes('Close')) {
      closeButton.focus()
    } else {
      const focusableElements = drawerWorkspaceRef.current.querySelectorAll<HTMLElement>(
        'a, button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (focusableElements.length > 0) {
        focusableElements[0].focus()
      }
    }

    // Focus trap on Tab/Shift+Tab
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return

      const focusableElements = drawerWorkspaceRef.current!.querySelectorAll<HTMLElement>(
        'a, button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (focusableElements.length === 0) return

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault()
          lastElement.focus()
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault()
          firstElement.focus()
        }
      }
    }

    drawerWorkspaceRef.current.addEventListener('keydown', handleKeyDown)
    return () => {
      drawerWorkspaceRef.current?.removeEventListener('keydown', handleKeyDown)
      // Restore focus when drawer closes
      if (previousActiveElementRef.current?.focus) {
        previousActiveElementRef.current.focus()
      }
    }
  }, [detailsOpen])

  // Focus management and trap for fleet settings drawer
  useEffect(() => {
    if (!fleetSettingsOpen || !drawerFleetSettingsRef.current) return

    // Store previous focus for restoration
    previousActiveElementRef.current = document.activeElement as HTMLElement

    // Set initial focus to first focusable element or close button
    const closeButton = drawerFleetSettingsRef.current.querySelector<HTMLElement>(
      'button'
    )
    if (closeButton) {
      closeButton.focus()
    } else {
      const focusableElements = drawerFleetSettingsRef.current.querySelectorAll<HTMLElement>(
        'a, button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (focusableElements.length > 0) {
        focusableElements[0].focus()
      }
    }

    // Focus trap on Tab/Shift+Tab
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return

      const focusableElements = drawerFleetSettingsRef.current!.querySelectorAll<HTMLElement>(
        'a, button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (focusableElements.length === 0) return

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault()
          lastElement.focus()
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault()
          firstElement.focus()
        }
      }
    }

    drawerFleetSettingsRef.current.addEventListener('keydown', handleKeyDown)
    return () => {
      drawerFleetSettingsRef.current?.removeEventListener('keydown', handleKeyDown)
      // Restore focus when drawer closes
      if (previousActiveElementRef.current?.focus) {
        previousActiveElementRef.current.focus()
      }
    }
  }, [fleetSettingsOpen])

  // Escape closes the analytics / service drill-down modals (keyboard a11y).
  useEffect(() => {
    if (!analyticsOpen && !serviceOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setAnalyticsOpen(false)
      setServiceOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [analyticsOpen, serviceOpen])

  // Lazy-load section-specific data when drawer section changes
  useEffect(() => {
    if (!detailsPrinterId) return
    if (activeSection === 'console') {
      void loadGcodeHistory()
      // Command history is per printer, so re-read whenever either the printer
      // or the section changes.
      const saved = loadConsoleHistory(detailsPrinterId)
      setConsoleHistory(saved)
      setConsoleHistoryIndex(saved.length)
      consoleCycleRef.current = NO_COMPLETION_CYCLE
      // Macros normally arrive with the rest of the workspace payload
      // (openPrinterWorkspace), but that fetch can reject — GRBL has no macro
      // endpoint — leaving TAB with nothing but the static vocabulary. Refetch
      // once if we came up empty. `macros` is deliberately NOT in the dep array:
      // this must not re-run when the fetch below lands.
      if (macros.length === 0) void ensureMacrosLoaded(detailsPrinterId)
    }
    else if (activeSection === 'temperature') void loadTempHistoryDetail()
    else if (activeSection === 'bedmesh') void loadBedMesh()
    // Counts are per-device and path-independent, so one fetch per (printer,
    // tab-open) covers every directory reloadFiles later browses into.
    else if (activeSection === 'files') void loadPrintCounts()
    else if (activeSection === 'settings') {
      apiFetch('/api/billing/my-subscription').then(r => { if (r.ok) r.json().then(setMySubscription) }).catch(() => {})
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection, detailsPrinterId])

  // Login state
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(false)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  // Keep ref in sync for use in WS reconnect closure (avoids stale closure bug)
  React.useEffect(() => { accessTokenRef.current = accessToken }, [accessToken])
  const [loginUsername, setLoginUsername] = useState('')
  const [currentUsername, setCurrentUsername] = useState<string>('')  // Persists after login (for PasskeyManager)
  const [loginPassword, setLoginPassword] = useState('')
  const [loginError, setLoginError] = useState('')
  // Forced password change (shipped default admin/admin must be changed on first login)
  const [mustChangePassword, setMustChangePassword] = useState(false)
  const [pwChangeCurrent, setPwChangeCurrent] = useState('')
  const [pwChangeNew, setPwChangeNew] = useState('')
  const [pwChangeConfirm, setPwChangeConfirm] = useState('')
  const [pwChangeError, setPwChangeError] = useState('')
  const [pwChangeBusy, setPwChangeBusy] = useState(false)
  const [ssoConfig, setSsoConfig] = useState<{ oidc: boolean; ldap: boolean }>({ oidc: false, ldap: false })
  const [branding, setBranding] = useState<{ company_name: string; logo_url: string | null; primary_color: string }>({ company_name: 'MEMAR', logo_url: null, primary_color: '#00a046' })

  // License and billing state
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null)
  const [showUpgradeModal, setShowUpgradeModal] = useState(false)
  const [upgradeModalTab, setUpgradeModalTab] = useState<'plans' | 'history'>('plans')
  const [showAdminModal, setShowAdminModal] = useState(false)
  const [userRole, setUserRole] = useState('')
  // Writer roles can mutate/control machines; everyone else (incl. demo 'viewer')
  // is read-only. Backend already 403s writes — this hides the controls in the UI.
  const canWrite = userRole === 'admin' || userRole === 'operator'
  // Theme: light/dark/system (system follows OS). Persisted; applied to <html data-theme>.
  const [theme, setTheme] = useState<'system' | 'light' | 'dark'>(() => {
    try {
      const s = localStorage.getItem('memar-theme')
      if (s === 'light' || s === 'dark') return s
    } catch { /* ignore */ }
    return 'system'
  })
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    const apply = () => {
      const light = theme === 'light' || (theme === 'system' && mq.matches)
      document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark')
    }
    apply()
    try { localStorage.setItem('memar-theme', theme) } catch { /* ignore */ }
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [theme])
  // Close the upgrade modal on Escape (a11y).
  useEffect(() => {
    if (!showUpgradeModal) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowUpgradeModal(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [showUpgradeModal])
  // Kiosk mode: distraction-free full-screen fleet matrix for production-floor
  // displays. Adds .kiosk to <html> (CSS hides chrome), requests fullscreen, exits on Escape.
  const [kioskMode, setKioskMode] = useState(false)
  useEffect(() => {
    document.documentElement.classList.toggle('kiosk', kioskMode)
    if (kioskMode) { try { void document.documentElement.requestFullscreen?.() } catch { /* fullscreen may be blocked */ } }
    else if (document.fullscreenElement) { try { void document.exitFullscreen?.() } catch { /* ignore */ } }
    if (!kioskMode) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setKioskMode(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [kioskMode])
  const [checkoutStatus, setCheckoutStatus] = useState<'success' | 'cancelled' | null>(null)
  const [licensePlans, setLicensePlans] = useState<LicensePlan[]>([])
  const [activationLicenseKey, setActivationLicenseKey] = useState('')
  const [activationLoading, setActivationLoading] = useState(false)
  const [activationError, setActivationError] = useState('')
  const [mySubscription, setMySubscription] = useState<{tier:string;status:string;expires_at:string|null;device_limit:number|null;cancel_at_period_end:boolean;stripe_customer_id:string|null}|null>(null)
  const [cancelSubLoading, setCancelSubLoading] = useState(false)
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const [renewalWarning, setRenewalWarning] = useState<{warning:boolean;days_remaining?:number;message?:string}|null>(null)
  const [upgradeHintData, setUpgradeHintData] = useState<{show:boolean;current?:number;limit?:number;next_tier?:string;next_limit?:number;next_price_monthly?:number}|null>(null)
  const [invoices, setInvoices] = useState<Array<{id:string;amount_paid:number;currency:string;status:string;created:number;hosted_invoice_url:string|null;invoice_pdf:string|null}>>([])
  const [invoicesLoading, setInvoicesLoading] = useState(false)
  const [showForgotModal, setShowForgotModal] = useState(false)
  const [forgotUsername, setForgotUsername] = useState('')
  const [forgotLoading, setForgotLoading] = useState(false)
  const [forgotMsg, setForgotMsg] = useState('')
  const [forgotResetLink, setForgotResetLink] = useState<string | null>(null)
  const [resetTokenFromUrl, setResetTokenFromUrl] = useState<string | null>(null)
  const [resetNewPassword, setResetNewPassword] = useState('')
  const [resetLoading, setResetLoading] = useState(false)
  const [resetMsg, setResetMsg] = useState('')
  const [resetSuccess, setResetSuccess] = useState(false)

  const [isDemoMode, setIsDemoMode] = useState(false)
  const [showAccountSettings, setShowAccountSettings] = useState(false)
  const [acctPwCurrent, setAcctPwCurrent] = useState('')
  const [acctPwNew, setAcctPwNew] = useState('')
  const [acctPwConfirm, setAcctPwConfirm] = useState('')
  const [acctPwError, setAcctPwError] = useState('')
  const [acctPwSuccess, setAcctPwSuccess] = useState(false)
  const [acctPwLoading, setAcctPwLoading] = useState(false)

  // Focus trap refs for modal overlays
  const forgotModalRef = useFocusTrap<HTMLDivElement>(showForgotModal)
  const accountSettingsRef = useFocusTrap<HTMLDivElement>(showAccountSettings)

  // Floor plan state

  const [floorPlanLayout, setFloorPlanLayout] = useState<Array<{ device_id: string; x: number; y: number; rotation: number; status?: 'printing' | 'error' | 'paused' | 'idle' | 'offline' }>>([])
  const [floorPlanImageUrl, setFloorPlanImageUrl] = useState<string | null>(null)
  const [floorPlanLoaded, setFloorPlanLoaded] = useState(false)
  // The AI 3D render is an optional feature (needs the Higgsfield CLI on the
  // server) — the 2D floor plan works regardless. Hides the "Generate 3D
  // Layout" button entirely rather than showing one that's guaranteed to
  // fail on any install without it configured.
  const [higgsfield3DAvailable, setHiggsfield3DAvailable] = useState(false)

  useEffect(() => {
    return () => {
      if (floorPlanImageUrl && floorPlanImageUrl.startsWith('blob:')) URL.revokeObjectURL(floorPlanImageUrl)
    }
  }, [floorPlanImageUrl])

  useEffect(() => {
    apiFetch('/api/version').then((res) => res.ok ? res.json() : null).then((data) => { if (data?.version) setVersion(data as VersionInfo) }).catch(() => undefined)
    apiFetch('/api/settings/fleet')
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!data) return
        const payload = data as FleetSettingsResponse
        if (payload.dashboard_settings) {
          setDashboardSettings({ ...DEFAULT_DASHBOARD_SETTINGS, ...payload.dashboard_settings })
          setFleetSettingsDraft({ ...DEFAULT_DASHBOARD_SETTINGS, ...payload.dashboard_settings })
        }
        if (Array.isArray(payload.material_presets) && payload.material_presets.length > 0) {
          setCustomPresets(payload.material_presets.filter((item) => !item.builtin))
        }
      })
      .catch(() => undefined)
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = import.meta.env.VITE_API_BASE_URL ? new URL(import.meta.env.VITE_API_BASE_URL).host : window.location.host
    let stopped = false
    let lastMsg = Date.now()

    if (!accessToken) return

    let httpFallbackFired = false
    let pollInterval: number | null = null
    let httpAlive = true
    const doHttpFetch = () => {
      if (stopped) return
      apiFetch('/api/printers')
        .then((res) => res.ok ? res.json() : null)
        .then((data) => {
          if (!httpAlive) return
          if (!data) { setFleetLoaded(true); return }
          const printers = demoModeRef.current
            ? MOCK_PRINTERS
            : (data && Array.isArray(data.printers) && data.printers.length > 0 ? data.printers : [])
          setFleet({ generated_at: new Date().toISOString(), printers })
          setFleetLoaded(true)
          // Trigger setup wizard for admins with zero devices (once per session)
          if (
            !setupWizardShownThisSession.current &&
            !demoModeRef.current &&
            userRole === 'admin' &&
            printers.length === 0
          ) {
            setupWizardShownThisSession.current = true
            setSetupWizardOpen(true)
          }
        })
        .catch(() => {
          if (!httpAlive) return
          setFleet({ generated_at: new Date().toISOString(), printers: demoModeRef.current ? MOCK_PRINTERS : [] })
          setFleetLoaded(true)
        })
    }
    const httpFallback = () => {
      if (httpFallbackFired || stopped) return
      httpFallbackFired = true
      doHttpFetch()
      pollInterval = window.setInterval(doHttpFetch, 15000)
    }

    // Schedule a reconnect with capped exponential backoff. Each reconnect goes
    // back through connect(), which fetches a FRESH single-use ticket — a ticket
    // can never be reused across connections.
    const scheduleReconnect = () => {
      if (stopped) return
      const delay = Math.min(1000 * Math.pow(2, wsReconnectAttemptRef.current), 30000)
      wsReconnectAttemptRef.current += 1
      debug('WS', `Reconnecting in ${delay}ms (attempt ${wsReconnectAttemptRef.current})`)
      setTimeout(() => { if (!stopped) void connect() }, delay)
    }

    const attachHandlers = (ws: WebSocket) => {
      ws.onopen = () => {
        setWsConnected(true)
        lastMsg = Date.now()
        wsReconnectAttemptRef.current = 0
        // Clear HTTP poll when WS reconnects
        if (pollInterval !== null) {
          window.clearInterval(pollInterval)
          pollInterval = null
          httpFallbackFired = false
        }
        info('WS', 'Fleet WebSocket connected')
      }
      ws.onmessage = (event) => {
        lastMsg = Date.now()
        try {
          const parsed = JSON.parse(event.data)
          if (parsed && Array.isArray(parsed.printers)) {
            const printers = demoModeRef.current ? MOCK_PRINTERS : (parsed.printers.length > 0 ? parsed.printers : [])
            setFleet({ ...parsed, printers })
            setFleetLoaded(true)
            // Trigger setup wizard for admins with zero devices (once per session)
            if (
              !setupWizardShownThisSession.current &&
              !demoModeRef.current &&
              userRole === 'admin' &&
              printers.length === 0
            ) {
              setupWizardShownThisSession.current = true
              setSetupWizardOpen(true)
            }
            setTempHistory((prevHistory) => {
              const updated = new Map(prevHistory)
              for (const printer of printers) {
                const prev = updated.get(printer.id) || { nozzle: [], bed: [] }
                updated.set(printer.id, {
                  nozzle: [...prev.nozzle.slice(-39), printer.nozzle?.temperature ?? 0],
                  bed:    [...prev.bed.slice(-39),    printer.bed?.temperature ?? 0],
                })
              }
              return updated
            })
          }
        } catch { /* ignore malformed frame */ }
      }
      ws.onclose = () => {
        setWsConnected(false)
        if (stopped) return
        // A 4001 (bad/expired ticket) is now indistinguishable from any other
        // close, and no longer needs a manual token-refresh dance: the next
        // connect() calls apiFetch('/api/ws/ticket'), which transparently
        // refreshes an expired access token (and logs out on hard auth failure).
        debug('WS', 'Fleet WebSocket closed, falling back to HTTP poll')
        httpFallback()
        scheduleReconnect()
      }
      ws.onerror = () => {
        error('WS', 'Fleet WebSocket error')
        httpFallback()
      }
    }

    // Open a fresh WS: fetch a single-use ticket (Bearer via apiFetch — keeps the
    // JWT out of the URL), then connect with ?ticket=. On ticket failure, keep
    // data flowing over HTTP poll and retry with backoff rather than crashing.
    const connect = async () => {
      if (stopped) return
      let ticket: string | undefined
      try {
        const res = await apiFetch('/api/ws/ticket', { method: 'POST' })
        if (!res.ok) throw new Error(`ticket ${res.status}`)
        ticket = (await res.json()).ticket
      } catch {
        if (stopped) return
        httpFallback()
        scheduleReconnect()
        return
      }
      if (stopped || !ticket) return
      // Close any existing WS before opening a new one
      wsCurrentRef.current?.close()
      const ws = new WebSocket(`${proto}://${host}/ws/fleet?ticket=${ticket}`)
      wsCurrentRef.current = ws
      attachHandlers(ws)
    }

    void connect()

    const heartbeat = window.setInterval(() => {
      if (!stopped && Date.now() - lastMsg > 10000) setWsConnected(false)
    }, 5000)

    return () => {
      stopped = true
      httpAlive = false
      window.clearInterval(heartbeat)
      if (pollInterval !== null) window.clearInterval(pollInterval)
      if (wsCurrentRef.current) wsCurrentRef.current.close()
      wsCurrentRef.current = null
    }
  }, [accessToken, userRole])

  useEffect(() => {
    if (!accessToken) return
    const historyLimit = Math.max(5, Math.min(dashboardSettings.metrics_history_limit || 50, 200))
    const refreshSeconds = Math.max(5, Math.min(dashboardSettings.metrics_refresh_seconds || 15, 120))
    const refreshMetrics = () => {
      apiFetch(`/api/metrics?history_limit=${historyLimit}`).then((res) => res.ok ? res.json() : null).then((data) => { if (data?.summary) setMetrics(data as MetricsResponse) }).catch(() => undefined)
    }
    refreshMetrics()
    const interval = window.setInterval(refreshMetrics, refreshSeconds * 1000)
    return () => window.clearInterval(interval)
  }, [dashboardSettings.metrics_history_limit, dashboardSettings.metrics_refresh_seconds, accessToken])

  // Fleet KPI strip + per-printer OEE — fail-soft (gated 402 / error → hide, never banner).
  // Keyed on accessToken so it (re)fires once login lands — avoids the mount-time
  // 401 race the metrics poll otherwise rides out on its interval.
  useEffect(() => {
    if (!accessToken) return
    const refreshSeconds = Math.max(5, Math.min(dashboardSettings.metrics_refresh_seconds || 15, 120))
    const refresh = () => {
      apiFetch('/api/analytics/fleet-kpi').then((r) => r.ok ? r.json() : null).then((d) => setFleetKpi(d as FleetKpi | null)).catch(() => setFleetKpi(null))
      apiFetch('/api/oee').then((r) => r.ok ? r.json() : null).then((d) => {
        if (d?.devices) setOeeByDevice(new Map((d.devices as OeeDevice[]).map((x) => [x.device_id, x])))
      }).catch(() => undefined)
    }
    refresh()
    const interval = window.setInterval(refresh, refreshSeconds * 1000)
    return () => window.clearInterval(interval)
  }, [dashboardSettings.metrics_refresh_seconds, accessToken])

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(MATERIAL_PRESET_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as TempPreset[]
      if (Array.isArray(parsed)) setCustomPresets(parsed.filter((item) => item && item.label))
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(MATERIAL_PRESET_STORAGE_KEY, JSON.stringify(customPresets))
    } catch {
      // ignore
    }
  }, [customPresets])

  const tempPresets = useMemo(() => [...BUILTIN_TEMP_PRESETS, ...customPresets].sort((a, b) => a.label.localeCompare(b.label)), [customPresets])
  const visiblePresets = useMemo(() => tempPresets.filter(p => !hiddenPresets.has(p.label)), [tempPresets, hiddenPresets])

  function toggleHiddenPreset(label: string) {
    setHiddenPresets(prev => {
      const next = new Set(prev)
      next.has(label) ? next.delete(label) : next.add(label)
      localStorage.setItem('memar-hidden-presets', JSON.stringify([...next]))
      return next
    })
  }

  const allTags = useMemo(() => Array.from(new Set(fleet.printers.flatMap((printer) => printer.tags))).sort((a, b) => a.localeCompare(b)), [fleet])
  const metricsByPrinter = useMemo(() => new Map((metrics?.printers || []).map((item) => [item.printer_id, item])), [metrics])

  const summary = useMemo(() => {
    const online = fleet.printers.filter((p) => p.online).length
    const printing = fleet.printers.filter((p) => p.online && p.job.state === 'printing').length
    const attention = fleet.printers.filter((p) => p.attention_needed).length
    const paused = fleet.printers.filter((p) => p.online && p.job.state === 'paused').length
    const ready = fleet.printers.filter((p) => p.online && p.state === 'ready' && p.job.state !== 'printing' && p.job.state !== 'paused').length
    const webcamsCount = fleet.printers.reduce((acc, printer) => acc + printer.webcams_count, 0)
    return { total: fleet.printers.length, online, printing, paused, ready, attention, webcamsCount }
  }, [fleet])

  const filteredPrinters = useMemo(() => {
    const term = search.trim().toLowerCase()
    const matches = fleet.printers.filter((printer) => {
      const haystack = [printer.name, printer.id, printer.state, printer.job.filename || '', printer.state_message || '', printer.tags.join(' ')].join(' ').toLowerCase()
      if (term && !haystack.includes(term)) return false
      if (tagFilter !== 'all' && !printer.tags.includes(tagFilter)) return false
      if (stateFilter !== 'all') {
        if (stateFilter === 'attention' && !printer.attention_needed) return false
        if (stateFilter === 'offline' && printer.online) return false
        if (stateFilter === 'printing' && printer.job.state !== 'printing') return false
        if (stateFilter === 'paused' && printer.job.state !== 'paused') return false
        if (stateFilter === 'ready' && !(printer.online && printer.state === 'ready' && printer.job.state !== 'printing')) return false
      }
      return true
    })

    return matches.sort((left, right) => {
      if (sortBy === 'name') return left.name.localeCompare(right.name, undefined, { numeric: true })
      if (sortBy === 'temperature') return hottestTemperature(right) - hottestTemperature(left)
      if (sortBy === 'success') {
        return (metricsByPrinter.get(right.id)?.success_rate || -1) - (metricsByPrinter.get(left.id)?.success_rate || -1)
      }
      return attentionRank(right) - attentionRank(left) || hottestTemperature(right) - hottestTemperature(left) || left.name.localeCompare(right.name, undefined, { numeric: true })
    })
  }, [fleet, search, tagFilter, stateFilter, sortBy, metricsByPrinter])

  const visibleIds = useMemo(() => filteredPrinters.map((printer) => printer.id), [filteredPrinters])
  const groupedPrinters = useMemo(() => {
    const groups = new Map<string, Printer[]>()
    for (const printer of filteredPrinters) {
      let key = 'All printers'
      if (groupBy === 'state') key = prettyStateGroup(printer)
      if (groupBy === 'tag') key = printer.tags[0] || 'untagged'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)?.push(printer)
    }
    return Array.from(groups.entries()).map(([label, printers]) => ({ label, printers }))
  }, [filteredPrinters, groupBy])

  const attentionItems = useMemo(() => {
    const severityOrder = { critical: 0, high: 1, medium: 2, low: 3, warning: 4 }
    return fleet.printers
      .filter((printer) => printer.attention_needed || printer.anomalies.length > 0 || !printer.online || (cvAnomalies[printer.id]?.length ?? 0) > 0)
      .map((printer) => {
        // Acknowledged anomalies are hidden until they auto-clear and recur.
        const sorted = [...printer.anomalies].filter((a) => !a.acked).sort((a, b) => (severityOrder[a.severity as keyof typeof severityOrder] ?? 5) - (severityOrder[b.severity as keyof typeof severityOrder] ?? 5))
        // Include CV anomalies with their mapped codes
        const cvItems = (cvAnomalies[printer.id] ?? []).map(a => ({
          code: 'CV_' + a.type.toUpperCase(),
          severity: (a.confidence === 'high' ? 'critical' : 'warning') as 'critical' | 'warning',
          message: a.reasoning || `CV: ${a.type}`,
        }))
        const seen = new Set<string>()
        const warnings: { severity: string; message: string; code?: string }[] = sorted.length > 0 || cvItems.length > 0
          ? [...sorted.map((a) => ({ severity: a.severity, message: a.message.split('\n')[0].trim(), code: a.code })), ...cvItems]
              .filter((w) => { if (seen.has(w.message)) return false; seen.add(w.message); return true })
          : (!printer.online ? [{ severity: 'warning', message: (printer.state_message || 'Needs attention').split('\n')[0].trim() }] : [])
        return {
          id: printer.id,
          name: printer.name,
          severity: sorted[0]?.severity || 'warning',
          message: sorted[0]?.message || printer.state_message || 'Needs attention',
          warnings,
        }
      })
      .filter((it) => it.warnings.length > 0)
      .sort((a, b) => (severityOrder[a.severity as keyof typeof severityOrder] ?? 99) - (severityOrder[b.severity as keyof typeof severityOrder] ?? 99))
  }, [fleet, cvAnomalies])

  const selectedVisibleCount = useMemo(() => visibleIds.filter((id) => selected.has(id)).length, [visibleIds, selected])

  function handleMatrixSort(col: string) {
    if (matrixSortCol === col) {
      setMatrixSortDir(matrixSortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setMatrixSortCol(col)
      setMatrixSortDir('asc')
    }
  }

  // Keyboard-operable + screen-reader-friendly props for the matrix sort headers
  // (they're styled <div>s, not <th>/<button>, so they need explicit a11y).
  const sortProps = (col: string) => {
    const ariaSort: 'ascending' | 'descending' | 'none' =
      matrixSortCol === col ? (matrixSortDir === 'asc' ? 'ascending' : 'descending') : 'none'
    return {
      role: 'columnheader' as const,
      tabIndex: 0,
      'aria-sort': ariaSort,
      onClick: () => handleMatrixSort(col),
      onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleMatrixSort(col) }
      },
    }
  }

  const sortedMatrixPrinters = useMemo(() => {
    const sorted = [...filteredPrinters]
    const dir = matrixSortDir === 'asc' ? 1 : -1
    switch (matrixSortCol) {
      case 'name': return sorted.sort((a, b) => dir * a.name.localeCompare(b.name))
      case 'state': return sorted.sort((a, b) => dir * displayPrinterState(a).localeCompare(displayPrinterState(b)))
      case 'job': return sorted.sort((a, b) => dir * (a.job.filename || '').localeCompare(b.job.filename || ''))
      case 'nozzle': return sorted.sort((a, b) => dir * ((a.nozzle.temperature ?? 0) - (b.nozzle.temperature ?? 0)))
      case 'bed': return sorted.sort((a, b) => dir * ((a.bed.temperature ?? 0) - (b.bed.temperature ?? 0)))
      case 'progress': return sorted.sort((a, b) => dir * ((a.job.progress ?? 0) - (b.job.progress ?? 0)))
      case 'spool': return sorted.sort((a, b) => dir * ((a.capability.spool_remaining_g ?? 0) - (b.capability.spool_remaining_g ?? 0)))
      case 'material': return sorted.sort((a, b) => dir * (a.capability.current_material || '').localeCompare(b.capability.current_material || ''))
      case 'alerts': return sorted.sort((a, b) => dir * ((b.anomalies.length + (b.capability.maintenance_due ? 1 : 0)) - (a.anomalies.length + (a.capability.maintenance_due ? 1 : 0))))
      case 'eta': return sorted.sort((a, b) => dir * ((a.job.eta_seconds ?? 0) - (b.job.eta_seconds ?? 0)))
      default: return sorted
    }
  }, [filteredPrinters, matrixSortCol, matrixSortDir])

  const displayMatrixPrinters = useMemo(() => {
    if (!simMode) return sortedMatrixPrinters
    return sortedMatrixPrinters.map((printer, i) => {
      const scenario = SIM_SCENARIOS[i % SIM_SCENARIOS.length]
      const { capOverrides, ...scenarioRest } = scenario
      const cap = { ...printer.capability, ...capOverrides }
      return { ...printer, ...scenarioRest, capability: cap }
    })
  }, [sortedMatrixPrinters, simMode])

  function presetForLabel(label: string) {
    return tempPresets.find((preset) => preset.label === label) || tempPresets[0] || BUILTIN_TEMP_PRESETS[0]
  }

  async function applyBatchPreset() {
    if (selected.size === 0) return
    const preset = presetForLabel(batchPresetLabel)
    setActionMessage(`Applying ${preset.label} to ${selected.size} printer(s)...`)
    const results = await Promise.allSettled(Array.from(selected).map(async (printerId) => {
      const res = await apiFetch(`/api/printers/${printerId}/temperature`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nozzle_target: preset.nozzle, bed_target: preset.bed }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    }))
    const okCount = results.filter((item) => item.status === 'fulfilled').length
    setActionMessage(`Applied ${preset.label}: ${okCount}/${selected.size} ok`)
  }

  async function applyCardPreset(printer: Printer) {
    const label = cardPresetByPrinter[printer.id] || printer.capability.current_material || batchPresetLabel || 'PLA'
    const preset = presetForLabel(label)
    setActionMessage(`Applying ${preset.label} on ${printer.name}...`)
    try {
      const res = await apiFetch(`/api/printers/${printer.id}/temperature`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nozzle_target: preset.nozzle, bed_target: preset.bed }),
      })
      if (!res.ok) { setActionMessage(`Failed to apply ${preset.label} on ${printer.name}`); return }
      setActionMessage(`Applied ${preset.label} on ${printer.name}`)
    } catch { setActionMessage(`Failed to apply ${preset.label} on ${printer.name}`) }
  }

  async function applyBatchPresetFor(label: string) {
    if (selected.size === 0) return
    const preset = presetForLabel(label)
    setActionMessage(`Preheating ${selected.size} printer(s) to ${preset.label}...`)
    const results = await Promise.allSettled(Array.from(selected).map(async (id) => {
      const res = await apiFetch(`/api/printers/${id}/temperature`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nozzle_target: preset.nozzle, bed_target: preset.bed }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    }))
    const ok = results.filter((r) => r.status === 'fulfilled').length
    setActionMessage(`Preheat ${preset.label}: ${ok}/${selected.size} ok`)
  }

  async function applyBatchCustomTemp() {
    if (selected.size === 0) return
    const nozzle = batchCustomNozzle !== '' ? Number(batchCustomNozzle) : null
    const bed = batchCustomBed !== '' ? Number(batchCustomBed) : null
    if (nozzle === null && bed === null) return
    setActionMessage(`Setting temps on ${selected.size} printer(s)...`)
    const results = await Promise.allSettled(Array.from(selected).map(async (id) => {
      const res = await apiFetch(`/api/printers/${id}/temperature`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nozzle_target: nozzle, bed_target: bed }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    }))
    const ok = results.filter((r) => r.status === 'fulfilled').length
    setActionMessage(`Set temps: ${ok}/${selected.size} ok`)
  }

  async function saveQuickFilament() {
    if (!detailsPrinterId) return
    setQuickFilamentSaving(true)
    try {
      await requireOk(await apiFetch(`/api/printers/${detailsPrinterId}/spool`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ remaining_g: parseFloat(quickRemaining) || 0, material: quickMaterial || undefined }),
      }))
      pushToast('Filament updated', 'success')
    } catch (e) {
      pushToast(e instanceof Error ? e.message : 'Failed to update filament', 'error')
    } finally {
      setQuickFilamentSaving(false)
    }
  }

  async function estimateSpoolFromPhoto(file: File) {
    if (!detailsPrinterId) return
    setSpoolEstimating(true)
    setSpoolEstimateResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('full_spool_g', '1000')
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/spool/estimate`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText)
        pushToast(`Estimate failed: ${errText}`, 'error')
        return
      }
      const data = await res.json() as {estimated_g: number, fill_pct: number, confidence: string, reasoning: string, model_used: string}
      setSpoolEstimateResult(data)
      setQuickRemaining(String(data.estimated_g))
      pushToast(`Estimated ${data.estimated_g}g (${Math.round(data.fill_pct * 100)}% full)`, 'success')
    } catch (e) {
      pushToast(`Estimate error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error')
    } finally {
      setSpoolEstimating(false)
    }
  }

  async function fetchSpoolLog(printerId: string) {
    setSpoolLogLoading(true)
    try {
      const res = await apiFetch(`/api/printers/${printerId}/spool/log?limit=30`)
      if (res.ok) {
        const data = await res.json() as { entries: SpoolLogEntry[] }
        setSpoolLog(data.entries || [])
      }
    } catch { /* silent */ } finally {
      setSpoolLogLoading(false)
    }
  }

  async function saveQuickFilamentWithLog() {
    if (!detailsPrinterId) return
    setQuickFilamentSaving(true)
    try {
      // Use log endpoint so it records the manual adjust
      await requireOk(await apiFetch(`/api/printers/${detailsPrinterId}/spool/log`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          remaining_g: parseFloat(quickRemaining) || 0,
          material: quickMaterial || undefined,
          note: 'manual adjust',
        }),
      }))
      pushToast('Filament updated', 'success')
      void fetchSpoolLog(detailsPrinterId)
    } catch (e) {
      pushToast(e instanceof Error ? e.message : 'Failed to update filament', 'error')
    } finally {
      setQuickFilamentSaving(false)
    }
  }

  function saveCurrentPreset() {
    const label = savePresetLabel?.trim()
    if (!label) return
    const nozzle = Number(customNozzle)
    const bed = Number(customBed)
    if (Number.isNaN(nozzle) || Number.isNaN(bed)) return
    setCustomPresets((current) => {
      const rest = current.filter((item) => item.label !== label)
      return [...rest, { label, nozzle, bed }].sort((a, b) => a.label.localeCompare(b.label))
    })
    setSavePresetLabel(null)
  }

  function openPrimaryUi(printer: Printer) {
    const targets = printerUiTargets(printer)
    if (targets.length === 1) {
      // T75: Only open https: URLs to prevent XSS/phishing via injected ui_targets
      const safeUrl = safeUiUrl(targets[0].url)
      if (!safeUrl) {
        pushToast('Cannot open UI — only HTTPS URLs are allowed', 'warning')
        return
      }
      // window.open with 'noopener' in the features string returns null even on
      // SUCCESS (per spec), so the old `!w` check fired a false "Pop-up blocked"
      // toast on every successful open. Open without features and sever the
      // opener manually — null now genuinely means the popup was blocked.
      const w = window.open(safeUrl, '_blank')
      if (w) w.opener = null
      else pushToast('Pop-up blocked — allow pop-ups for this site to open the printer UI', 'warning')
      return
    }
    setUiMenuPrinterId((current) => current === printer.id ? null : printer.id)
  }

  const currentPrinter = fleet.printers.find((item) => item.id === detailsPrinterId) || null
  const currentMetric = currentPrinter ? metricsByPrinter.get(currentPrinter.id) || null : null
  const filteredMacros = useMemo(() => macros.filter((item) => item.name.toLowerCase().includes(macroSearch.trim().toLowerCase())), [macros, macroSearch])
  // Autocomplete vocabulary for the g-code console: this printer's own macros,
  // merged with the static command list inside completionCandidates().
  const macroNames = useMemo(() => macros.map((item) => item.name), [macros])
  // Private (`_`-prefixed) macros are hidden behind a toggle rather than
  // dropped: Klipper treats them as internal helpers, but an operator
  // debugging a macro chain still needs to reach them.
  const privateMacroCount = useMemo(() => filteredMacros.filter((item) => isPrivateMacro(item.name)).length, [filteredMacros])
  const visibleMacros = useMemo(
    () => (showPrivateMacros ? filteredMacros : filteredMacros.filter((item) => !isPrivateMacro(item.name))),
    [filteredMacros, showPrivateMacros],
  )
  /** Macros bucketed by `variable_category`, uncategorised last under ''. */
  const macroGroups = useMemo(() => {
    const groups = new Map<string, MacroEntry[]>()
    for (const macro of visibleMacros) {
      const key = macro.category?.trim() || ''
      const bucket = groups.get(key)
      if (bucket) bucket.push(macro)
      else groups.set(key, [macro])
    }
    return [...groups.entries()].sort(([a], [b]) => {
      if (a === b) return 0
      if (a === '') return 1   // uncategorised sinks to the bottom
      if (b === '') return -1
      return a.localeCompare(b)
    })
  }, [visibleMacros])

  useEffect(() => {
    setDashboardUploadTargetId((current) => {
      // Don't override an explicit, still-valid operator selection on every
      // websocket frame — only auto-pick when there is no valid current target.
      if (current && fleet.printers.some(p => p.id === current && p.online && p.state !== 'error')) return current
      const best = fleet.printers
        .filter(p => p.online && p.state !== 'error')
        .sort((a, b) => {
          const score = (p: Printer) =>
            (p.state === 'ready' ? 100 : p.state === 'paused' ? 40 : 10)
            + ((p.capability.spool_remaining_g ?? 0) / 20)
          return score(b) - score(a)
        })[0]
      return best ? best.id : current
    })
  }, [fleet.printers])

  function updatePrinterSettingsDraft(patch: Partial<PrinterSettingsDraft>) {
    setPrinterSettingsDraft((current) => current ? { ...current, ...patch } : current)
  }

  function updateUiTargetDraft(index: number, patch: Partial<UiTargetDraft>) {
    setPrinterSettingsDraft((current) => {
      if (!current) return current
      const uiTargets = current.uiTargets.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)
      return { ...current, uiTargets }
    })
  }

  function addUiTargetDraft() {
    setPrinterSettingsDraft((current) => current ? { ...current, uiTargets: [...current.uiTargets, { provider: 'other', label: 'UI', url: '', mode: 'direct', primary: current.uiTargets.length === 0 }] } : current)
  }

  function removeUiTargetDraft(index: number) {
    setPrinterSettingsDraft((current) => {
      if (!current) return current
      const uiTargets = current.uiTargets.filter((_, itemIndex) => itemIndex !== index)
      if (uiTargets.length > 0 && !uiTargets.some((item) => item.primary)) uiTargets[0] = { ...uiTargets[0], primary: true }
      return { ...current, uiTargets }
    })
  }

  const toggle = useCallback((printerId: string) => {
    setSelected((current) => { const next = new Set(current); next.has(printerId) ? next.delete(printerId) : next.add(printerId); return next })
  }, [])

  const openConfirm = useCallback((message: string, onConfirm: () => void) => {
    setConfirmState({ message, onConfirm })
  }, [])

  function toggleAllVisible() {
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))
    setSelected((current) => {
      const next = new Set(current)
      if (allVisibleSelected) { visibleIds.forEach(id => next.delete(id)) } else { visibleIds.forEach(id => next.add(id)) }
      return next
    })
  }

  const runBatchAction = useCallback(async (action: string, ids: string[], opts?: { skipConfirm?: boolean }) => {
    if (ids.length === 0) return null
    const doRun = async () => {
      setActionMessage(`Running ${labelForAction(action)}...`)
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 15000)
      let response: Response
      try {
        response = await apiFetch(`/api/printers/actions/${action}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ printer_ids: ids, mode: 'standard' }),
          signal: controller.signal,
        })
        clearTimeout(timeout)
      } catch (e) {
        clearTimeout(timeout)
        const msg = e instanceof Error && e.name === 'AbortError' ? 'timed out' : 'network error'
        setActionMessage(`${labelForAction(action)} failed: ${msg}`)
        return []
      }
      if (!response.ok) {
        const errText = await response.text().catch(() => response.statusText)
        setActionMessage(`${labelForAction(action)} failed: ${errText}`)
        return []
      }
      const payload = await response.json()
      const results: {printer_id: string, status: string, message?: string}[] = payload.results || []
      const okCount = results.filter((r) => r.status === 'ok').length
      setActionMessage(`${labelForAction(action)}: ${okCount}/${ids.length} ok`)
      return results
    }
    // T93: Confirm dangerous operations: cancel, emergency_stop, home, firmware_restart, spindle on/off
    const dangerousOps = ['cancel', 'emergency_stop', 'home', 'firmware_restart', 'spindle_on', 'spindle_off']
    if (!opts?.skipConfirm && dangerousOps.includes(action)) {
      openConfirm(`Run ${labelForAction(action)} on ${ids.length} printer(s)?`, () => void doRun())
      return null
    }
    return await doRun()
  }, [openConfirm])

  const runSingleAction = useCallback(async (printer: Printer, action: string) => {
    const results = await runBatchAction(action, [printer.id])
    if (results) {
      const r = results.find(item => item.printer_id === printer.id)
      const ok = r?.status === 'ok'
      pushCardLog(printer.id, `${ok ? '✓' : '✗'} ${labelForAction(action)}${ok ? '' : `: ${r?.message || 'failed'}`}`, ok)
    }
  }, [runBatchAction])

  // CNC-specific commands: the generic /api/printers/actions/{action} path only
  // dispatches to MoonrakerClient (FDM), so CNC control has its own endpoints.
  // E-Stop goes through the dedicated cnc/estop route; spindle/coolant have no
  // dedicated route yet, so they're sent as standard G-code M-codes (M3/M5
  // spindle, M8/M9 coolant) through the existing admin-only cnc/gcode route.
  const runCncCommand = useCallback(async (printer: Printer, kind: 'estop' | 'home' | 'spindle_on' | 'spindle_off' | 'coolant_toggle'): Promise<boolean> => {
    const label = kind === 'estop' ? 'E-Stop' : kind === 'home' ? 'Home' : kind === 'spindle_on' ? 'Spindle On' : kind === 'spindle_off' ? 'Spindle Off' : 'Coolant'
    try {
      const res = kind === 'estop'
        ? await apiFetch(`/api/devices/${printer.id}/cnc/estop`, { method: 'POST' })
        : kind === 'home'
        ? await apiFetch(`/api/devices/${printer.id}/cnc/home`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ axes: null }),
          })
        : await apiFetch(`/api/devices/${printer.id}/cnc/gcode`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: kind === 'spindle_on' ? 'M3' : kind === 'spindle_off' ? 'M5' : (printer.capability.coolant_active ? 'M9' : 'M8') }),
          })
      if (res.ok) {
        const data = await res.json().catch(() => null) as { ok?: boolean; alpha_warning?: string } | null
        // T92: Backend may return HTTP 200 with { ok: false } on soft failure
        if (data?.ok === false) {
          pushCardLog(printer.id, `✗ ${label}: command rejected`, false)
          return false
        }
        pushCardLog(printer.id, data?.alpha_warning ? `✓ ${label} (⚠ ${data.alpha_warning})` : `✓ ${label}`, true)
        return true
      }
      // estop is never alpha-gated (see cnc_emergency_stop's own docstring),
      // so this only ever fires for home/spindle/coolant on an unacked alpha
      // device — home/gcode both carry Depends(require_alpha_ack).
      if (res.status === 403) {
        const body = await res.json().catch(() => null) as { detail?: string } | null
        if (body?.detail === 'alpha_ack_required') {
          setAlphaAckPending({ printer, retry: () => { void runCncCommand(printer, kind) } })
          return false
        }
      }
      const errText = await res.text().catch(() => res.statusText)
      pushCardLog(printer.id, `✗ ${label}: ${errText || 'failed'}`, false)
      return false
    } catch (e) {
      pushCardLog(printer.id, `✗ ${label}: ${e instanceof Error ? e.message : 'failed'}`, false)
      return false
    }
  }, [])

  // Toolbar multi-select E-Stop: selection is machine-type-agnostic (any mix
  // of FDM/CNC/laser/plasma/etc. can be checked at once), but dispatch isn't
  // — the generic batch endpoint only actually stops MoonrakerClient (FDM)
  // devices and 'blocks' everything else (see run_batch_action's
  // isinstance(client, MoonrakerClient) gate). Split the selection and route
  // each half through the path that actually halts it, under a single
  // confirm and one aggregate result message.
  const runToolbarEmergencyStop = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return
    const targets = ids
      .map((id) => fleet.printers.find((p) => p.id === id))
      .filter((p): p is Printer => !!p)
    const cncTargets = targets.filter((p) => isCncMachine(p.capability.machine_type))
    const fdmIds = targets.filter((p) => !isCncMachine(p.capability.machine_type)).map((p) => p.id)

    const doRun = async () => {
      setActionMessage('Running E-Stop...')
      const [cncOks, fdmResults] = await Promise.all([
        Promise.all(cncTargets.map((p) => runCncCommand(p, 'estop'))),
        fdmIds.length > 0 ? runBatchAction('emergency_stop', fdmIds, { skipConfirm: true }) : Promise.resolve([]),
      ])
      const okCount = cncOks.filter(Boolean).length + (fdmResults || []).filter((r) => r.status === 'ok').length
      setActionMessage(`E-Stop: ${okCount}/${ids.length} ok`)
    }
    openConfirm(`Emergency stop ${ids.length} printer(s)?`, () => void doRun())
  }, [fleet.printers, runCncCommand, runBatchAction, openConfirm])

  // Refetch macros without ever clearing them: this runs opportunistically
  // alongside the workspace load, and an empty/failed response must not wipe a
  // list that arrived successfully from the other request.
  const ensureMacrosLoaded = useCallback(async (printerId: string) => {
    try {
      const res = await apiFetch(`/api/printers/${printerId}/macros`)
      if (!res.ok) return
      const data = await res.json() as { macros?: MacroEntry[] }
      if (data.macros && data.macros.length > 0) setMacros(data.macros)
    } catch { /* autocomplete falls back to the static vocabulary */ }
  }, [])

  async function sendGcodeCommand(script: string) {
    if (!detailsPrinterId || !script.trim()) return
    if (!currentPrinter) return
    const trimmed = script.trim()
    // Record history here rather than in the input's keydown handler: both the
    // Enter key and the Send button funnel through this function, and only this
    // path knows the command was actually dispatched.
    const nextHistory = appendConsoleHistory(consoleHistory, trimmed)
    setConsoleHistory(nextHistory)
    setConsoleHistoryIndex(nextHistory.length)
    saveConsoleHistory(detailsPrinterId, nextHistory)
    consoleCycleRef.current = NO_COMPLETION_CYCLE
    setConsoleLog((prev) => [...prev, {type: 'sent', text: trimmed}])
    setConsoleInput('')
    setConsoleSending(true)
    try {
      const endpoint = isCncMachine(currentPrinter.capability.machine_type) ? `/api/devices/${detailsPrinterId}/cnc/gcode` : `/api/printers/${detailsPrinterId}/gcode`
      const body = isCncMachine(currentPrinter.capability.machine_type) ? {code: trimmed} : {script: trimmed}
      const res = await apiFetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText)
        setConsoleLog((prev) => [...prev, {type: 'error', text: errText || 'Command failed'}])
        return
      }
      const data = await res.json()
      if (data.ok) {
        setConsoleLog((prev) => [...prev, {type: 'recv', text: data.response || data.result || 'ok'}])
      } else {
        setConsoleLog((prev) => [...prev, {type: 'error', text: data.error || 'Command failed'}])
      }
    } catch (e) {
      setConsoleLog((prev) => [...prev, {type: 'error', text: String(e)}])
    } finally {
      setConsoleSending(false)
    }
  }

  async function loadGcodeHistory() {
    if (!detailsPrinterId) return
    try {
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/gcode/history`)
      if (!res.ok) return
      const data = await res.json()
      if (data.supported && Array.isArray(data.commands)) {
        setConsoleLog(data.commands.map((c: {message: string; type: string}) => ({
          type: c.type === 'response' ? 'recv' : c.type === 'command' ? 'sent' : 'recv',
          text: c.message,
        })))
      }
    } catch { /* ignore */ }
  }

  async function loadTempHistoryDetail() {
    if (!detailsPrinterId) return
    try {
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/temperature-history`)
      if (!res.ok) return
      const data = await res.json()
      setTempHistoryDetail(data)
    } catch { /* ignore */ }
  }

  async function loadBedMesh() {
    if (!detailsPrinterId) return
    setBedMesh(null)
    try {
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/bed-mesh`)
      if (!res.ok) return
      const data = await res.json()
      setBedMesh(data)
    } catch { /* ignore */ }
  }

  async function loadPrintCounts() {
    if (!detailsPrinterId) return
    try {
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/files/print-counts`)
      if (!res.ok) return
      const rows = await res.json() as PrintCountRow[]
      setPrintCounts(new Map(rows.map((row) => [normalizeJobKey(row.job_name), row.count])))
    } catch { /* non-critical: the column falls back to '—' */ }
  }

  async function loadExcludeObjects() {
    if (!detailsPrinterId) return
    try {
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/exclude-objects`)
      if (!res.ok) return
      const data = await res.json()
      setExcludeObjects(data)
    } catch { /* ignore */ }
  }

  async function doExcludeObject(name: string) {
    if (!detailsPrinterId) return
    try {
      await requireOk(await apiFetch(`/api/printers/${detailsPrinterId}/exclude-objects/${encodeURIComponent(name)}`, {method: 'POST'}))
      await loadExcludeObjects()
    } catch (err) { 
      console.error('Failed to exclude object:', err)
    }
  }

  // One-click recovery for an alert: POST the matching action, then optimistically
  // hide the anomaly (the underlying condition clearing is what really resolves it;
  // the next poll reconciles — it reappears if it didn't clear).
  async function runQuickAction(printerId: string, code: string, qa: { label: string; kind: string }) {
    // Refill = swap to a fresh spool: set remaining to the configured full capacity.
    const cap = fleet.printers.find((p) => p.id === printerId)?.capability.spool_capacity_g ?? 1000
    const previousFleet = fleet
    setFleet((f) => ({ ...f, printers: f.printers.map((p) => {
      if (p.id !== printerId) return p
      const anomalies = p.anomalies.map((a) => a.code === code ? { ...a, acked: true } : a)
      return qa.kind === 'refill'
        ? { ...p, anomalies, capability: { ...p.capability, spool_remaining_g: cap } }
        : { ...p, anomalies }
    }) }))
    try {
      if (qa.kind === 'refill') {
        await requireOk(await apiFetch(`/api/printers/${printerId}/spool`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ remaining_g: cap }),
        }))
        return
      }
      const url = qa.kind === 'maintenance'
        ? `/api/printers/${printerId}/maintenance/complete`
        : `/api/printers/${printerId}/actions/${qa.kind}`
      await requireOk(await apiFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }))
    } catch (err) { 
      // Rollback optimistic update on failure
      setFleet(previousFleet)
      console.error('Quick action failed:', err)
    }
  }

  // Acknowledge an anomaly (operator/admin) — hides it until it auto-clears and
  // recurs. Optimistic; the next fleet poll reconciles with the server.
  async function ackAnomaly(printerId: string, code?: string) {
    if (!code) return
    setFleet((f) => ({ ...f, printers: f.printers.map((p) => p.id === printerId
      ? { ...p, anomalies: p.anomalies.map((a) => a.code === code ? { ...a, acked: true } : a) }
      : p) }))
    try {
      await apiFetch(`/api/printers/${printerId}/anomalies/ack`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
      })
    } catch { /* optimistic — poll reconciles */ }
  }

  async function openPrinterWorkspace(printer: Printer, section: DrawerSection = dashboardSettings.default_drawer_section || 'overview') {
    workspaceCtrlRef.current?.abort()
    const ctrl = new AbortController()
    workspaceCtrlRef.current = ctrl
    // The cnc + coolant tabs are hidden for non-CNC machines — don't open onto them.
    if ((section === 'coolant' || section === 'cnc') && !isCncMachine(printer.capability.machine_type)) section = 'overview'
    // Files/Macros/Bedmesh are hidden for GRBL (no filesystem, no macros, no leveling mesh).
    if ((section === 'files' || section === 'macros' || section === 'bedmesh') && printer.protocol === 'grbl') section = 'overview'
    // Webcams tab requires at least one configured webcam.
    if (section === 'webcams' && printer.webcams_count === 0) section = 'overview'
    setDetailsOpen(true)
    setDetailsPrinterId(printer.id)
    setActiveSection(section)
    setDiagnostics(null)
    setMacros([])
    setHistory(null)
    setFileBrowser(null)
    setPrintCounts(new Map())   // counts are per-device — never show the last printer's
    setCurrentFileDetail(null)
    setSelectedFileDetail(null)
    setWebcams([])
    setTimelapse(null)
    setDrawerMsg('', 'info')
    setDrawerLoading(true)
    setFilePath('gcodes')
    setJogAxis('X')
    setJogDistance('1')
    setSpoolLog([])
    setSpoolLogOpen(false)
    void fetchSpoolLog(printer.id)
    setJogFeedrate('3000')
    setUploadFile(null)
    setUploadAutoPrint(false)
    setMacroSearch('')
    // Param values are per-machine — carrying a TEMP typed for one printer over
    // to the next machine's macro of the same name would be a real hazard.
    setMacroTypedParams({})
    setMacroParams({})
    setMacroExpanded(null)
    setCardMacros(prev => { const next = {...prev}; delete next[printer.id]; return next })
    try {
      const results = await Promise.allSettled([
        apiFetch(`/api/printers/${printer.id}/diagnostics`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
        apiFetch(`/api/printers/${printer.id}/macros`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
        apiFetch(`/api/printers/${printer.id}/history?limit=18`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
        apiFetch(`/api/printers/${printer.id}/files?path=gcodes`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
        apiFetch(`/api/printers/${printer.id}/current-file`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
        apiFetch(`/api/printers/${printer.id}/webcams`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
        apiFetch(`/api/printers/${printer.id}/timelapse?limit=12`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
        apiFetch(`/api/printers/${printer.id}/settings`, { signal: ctrl.signal }).then((res) => { if (!res.ok) throw new Error(res.statusText); return res.json() }),
      ])
      if (ctrl.signal.aborted) return
      const freshDiag = results[0].status === 'fulfilled' ? (results[0].value as Diagnostics) : null
      if (freshDiag) {
        setDiagnostics(freshDiag)
        setQuickMaterial(freshDiag.capability?.current_material ?? '')
        setQuickRemaining(String(freshDiag.capability?.spool_remaining_g ?? ''))
      }
      if (results[1].status === 'fulfilled') setMacros(((results[1].value as { macros?: MacroEntry[] }).macros) || [])
      if (results[2].status === 'fulfilled') setHistory(results[2].value as HistoryResponse)
      if (results[3].status === 'fulfilled') setFileBrowser(results[3].value as FileBrowserResponse)
      if (results[4].status === 'fulfilled') setCurrentFileDetail(results[4].value as CurrentFileResponse)
      if (results[5].status === 'fulfilled') setWebcams(((results[5].value as { webcams?: WebcamEntry[] }).webcams) || [])
      if (results[6].status === 'fulfilled') setTimelapse(results[6].value as TimelapseResponse)
      if (results[7].status === 'fulfilled') setPrinterSettingsDraft(toPrinterSettingsDraft(results[7].value as PrinterSettingsPayload))
      else setPrinterSettingsDraft(toPrinterSettingsDraft(printer))
      const nozzleTarget = printer.nozzle.target == null ? 0 : printer.nozzle.target
      const bedTarget = printer.bed.target == null ? 0 : printer.bed.target
      setCustomNozzle(String(nozzleTarget))
      setCustomBed(String(bedTarget))
      setSettingsNozzle(String(printer.capability?.nozzle_diameter_mm ?? printer.nozzle_diameter_mm ?? freshDiag?.nozzle_diameter_mm ?? 0.4))
      setDispatchFilename(printer.job.filename || '')
      setDispatchMaterial('')
      setDispatchNozzle(String(printer.capability?.nozzle_diameter_mm ?? printer.nozzle_diameter_mm ?? 0.4))
      setDryRunPayload(null)
      setMotionCheckPayload(null)
      setDispatchDryRunPayload(null)
      setConsoleLog([])
      setConsoleInput('')
      setTempHistoryDetail(null)
      setBedMesh(null)
      setExcludeObjects(null)
      if (results.some((item) => item.status === 'rejected')) setDrawerMsg('Some workspace sections could not be loaded.', 'warning')
      setPrinterSettingsMessage('')
    } finally {
      setDrawerLoading(false)
      if (workspaceCtrlRef.current === ctrl) workspaceCtrlRef.current = null
    }
  }

  function closeWorkspace() {
    workspaceCtrlRef.current?.abort()
    workspaceCtrlRef.current = null
    setDetailsOpen(false)
  }

  async function reloadFiles(path: string) {
    if (!detailsPrinterId || !currentPrinter) return
    setDrawerMsg(`Loading ${path}...`, 'info')
    const endpoint = isCncMachine(currentPrinter.capability.machine_type)
      ? `/api/devices/${detailsPrinterId}/cnc/files?path=${encodeURIComponent(path)}`
      : `/api/printers/${detailsPrinterId}/files?path=${encodeURIComponent(path)}`
    const res = await apiFetch(endpoint)
    if (!res.ok) { setDrawerMsg(`Failed to load ${path}: ${res.status}`, 'error'); return }
    const data = await res.json()
    // CNC endpoint returns {files: [...]}, normalize to FileBrowserResponse
    const browser: FileBrowserResponse = isCncMachine(currentPrinter.capability.machine_type)
      ? {
          printer_id: detailsPrinterId,
          path: path || '/',
          root: '/',
          dirs: [],
          files: (data.files || []).map((f: any) => ({
            name: typeof f === 'string' ? f : f.name,
            path: typeof f === 'string' ? f : f.path,
            kind: 'file' as const,
            size: typeof f === 'string' ? 0 : f.size,
            modified: typeof f === 'string' ? new Date().toISOString() : f.modified,
            permissions: 'r',
            metadata: {},
          })),
          disk_usage: 0,
          root_info: {},
        }
      : data
    setFileBrowser(browser)
    setFilePath(path)
    setDrawerMsg(`Loaded ${path}`, 'success')
  }

  async function inspectFile(filename: string) {
    if (!detailsPrinterId) return
    setDrawerMsg(`Loading detail for ${filename}...`, 'info')
    const res = await apiFetch(`/api/printers/${detailsPrinterId}/files/detail?filename=${encodeURIComponent(filename)}`)
    if (!res.ok) { setDrawerMsg(`Failed to load detail for ${filename}: ${res.status}`, 'error'); return }
    setSelectedFileDetail(await res.json() as FileDetailResponse)
    setDrawerMsg(`Loaded detail for ${filename}`, 'success')
  }

  async function uploadFromDashboard() {
    if (!dashboardUploadFile) return
    if (dashboardUploadBusyRef.current) return
    const targetIds = dashboardUseSelected && selected.size > 0 ? Array.from(selected) : dashboardUploadTargetId ? [dashboardUploadTargetId] : []
    if (targetIds.length === 0) {
      setDashboardUploadMessage('Choose at least one target printer.')
      return
    }
    dashboardUploadBusyRef.current = true
    setDashboardUploadBusy(true)
    try {
      const form = new FormData()
      targetIds.forEach((id) => form.append('printer_ids', id))
      form.append('file', dashboardUploadFile)
      form.append('auto_print', String(dashboardUploadAutoPrint))
      setDashboardUploadMessage(`Uploading ${dashboardUploadFile.name} to ${targetIds.length} printer(s)...`)
      const response = await apiFetch('/api/files/upload', { method: 'POST', body: form })
      if (!response.ok) {
        const errText = await response.text().catch(() => response.statusText)
        setDashboardUploadMessage(`Upload failed: ${errText}`)
        return
      }
      const payload = await response.json() as DispatchUploadResponse
      const okCount = payload.results.filter((item) => item.errors.length === 0).length
      const startedCount = payload.results.filter((item) => item.started_print).length
      setDashboardUploadMessage(`Uploaded ${payload.filename}: ${okCount}/${payload.results.length} ok${startedCount > 0 ? `, ${startedCount} started` : ''}`)
      setDashboardUploadFile(null)
      if (detailsPrinterId && targetIds.includes(detailsPrinterId)) await reloadFiles(filePath)
    } finally {
      dashboardUploadBusyRef.current = false
      setDashboardUploadBusy(false)
    }
  }

  async function uploadSelectedFile() {
    if (!detailsPrinterId || !uploadFile) return
    if (uploadBusyRef.current) return
    uploadBusyRef.current = true
    setUploadBusy(true)
    try {
      const form = new FormData()
      form.append('file', uploadFile)
      form.append('relative_path', normalizeRelativeUploadPath(filePath))
      form.append('auto_print', String(uploadAutoPrint))
      setDrawerMsg(`Uploading ${uploadFile.name}...`, 'info')
      const response = await apiFetch(`/api/printers/${detailsPrinterId}/files/upload`, { method: 'POST', body: form })
      if (!response.ok) {
        const errText = await response.text().catch(() => response.statusText)
        setDrawerMsg(`Upload failed: ${errText}`, 'error')
        return
      }
      const payload = await response.json()
      setDrawerMsg(`Uploaded ${payload.filename}${payload.started_print ? ' and started print' : ''}`, 'success')
      setUploadFile(null)
      await reloadFiles(filePath)
    } finally {
      uploadBusyRef.current = false
      setUploadBusy(false)
    }
  }

  async function startSelectedFile(filename: string) {
    if (!detailsPrinterId) return
    openConfirm(`Start ${filename}?`, async () => {
      setDrawerMsg(`Starting ${filename}...`, 'info')
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/files/print`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      setDrawerMsg(res.ok ? `Started ${filename}` : `Failed to start ${filename}`, res.ok ? 'success' : 'error')
    })
  }

  async function applyPreset(nozzle: number, bed: number) {
    if (!detailsPrinterId) return
    setCustomNozzle(String(nozzle))
    setCustomBed(String(bed))
    await applyCustomTemperatures(nozzle, bed)
  }

  async function applyCustomTemperatures(nozzleValue?: number, bedValue?: number) {
    if (!detailsPrinterId || !currentPrinter) return
    // Temperature control is only for thermal machines (FDM/IDEX/SLA); gate strictly to prevent sending heating commands to non-thermal machines
    const thermalTypes = ['fdm', 'idex', 'sla']
    if (!currentPrinter.capability.machine_type || !thermalTypes.includes(currentPrinter.capability.machine_type)) {
      setDrawerMsg('Temperature control not available for this machine type.', 'warning')
      return
    }
    const nozzleTarget = nozzleValue ?? Number(customNozzle)
    const bedTarget = bedValue ?? Number(customBed)
    setDrawerMsg('Applying temperatures...', 'info')
    const res = await apiFetch(`/api/printers/${detailsPrinterId}/temperature`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nozzle_target: nozzleTarget, bed_target: bedTarget }),
    })
    setDrawerMsg(res.ok ? `Applied ${nozzleTarget} / ${bedTarget}` : `Failed to apply temperatures`, res.ok ? 'success' : 'error')
  }

  async function saveNozzleDiameter() {
    if (!detailsPrinterId) return
    const value = Number(settingsNozzle)
    if (!Number.isFinite(value) || value <= 0) {
      setDrawerMsg('Enter a valid nozzle diameter.', 'warning')
      return
    }
    setDrawerMsg(`Saving nozzle ${value.toFixed(2)} mm...`, 'info')
    const response = await apiFetch(`/api/printers/${detailsPrinterId}/settings/nozzle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nozzle_diameter_mm: value }),
    })
    if (!response.ok) {
      const errText = await response.text().catch(() => response.statusText)
      setDrawerMsg(`Failed to save nozzle: ${errText}`, 'error')
      return
    }
    const payload = await response.json() as NozzleSaveResponse
    setDrawerMsg(`Saved ${payload.nozzle_diameter_mm != null ? payload.nozzle_diameter_mm.toFixed(2) : '—'} mm nozzle. Backup: ${payload.backup_path}`, 'success')
    setDiagnostics((current) => current ? { ...current, nozzle_diameter_mm: payload.nozzle_diameter_mm, capability: { ...current.capability, nozzle_diameter_mm: payload.nozzle_diameter_mm } } : current)
    setFleet((current) => ({ ...current, printers: current.printers.map((printer) => printer.id === detailsPrinterId ? { ...printer, nozzle_diameter_mm: payload.nozzle_diameter_mm, capability: { ...printer.capability, nozzle_diameter_mm: payload.nozzle_diameter_mm } } : printer) }))
    setPrinterSettingsDraft((current) => current ? { ...current, nozzleDiameter: payload.nozzle_diameter_mm != null ? payload.nozzle_diameter_mm.toFixed(2) : '0.4' } : current)
    const refreshedPrinter = currentPrinter || fleet.printers.find((printer) => printer.id === detailsPrinterId)
    if (refreshedPrinter) {
      void openPrinterWorkspace({
        ...refreshedPrinter,
        nozzle_diameter_mm: payload.nozzle_diameter_mm,
        capability: { ...refreshedPrinter.capability, nozzle_diameter_mm: payload.nozzle_diameter_mm },
      }, activeSection)
    }
  }

  function patchFleetSetting(patch: Partial<DashboardSettings>) {
    setFleetSettingsDraft(cur => ({ ...cur, ...patch }))
    setDashboardSettings(cur => ({ ...cur, ...patch }))
  }

  async function saveFleetSettings() {
    try {
      setFleetSettingsMessage('Saving…')
      const payload = {
        dashboard_settings: {
          ...fleetSettingsDraft,
          metrics_history_limit: Math.max(5, Math.min(Number(fleetSettingsDraft.metrics_history_limit) || 50, 200)),
          metrics_refresh_seconds: Math.max(5, Math.min(Number(fleetSettingsDraft.metrics_refresh_seconds) || 15, 120)),
        },
        material_presets: customPresets.map((item) => ({ label: item.label, nozzle: item.nozzle, bed: item.bed, builtin: false })),
      }
      const response = await apiFetch('/api/settings/fleet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) throw new Error(await response.text().catch(() => response.statusText))
      const saved = await response.json() as FleetSettingsResponse
      const merged = { ...DEFAULT_DASHBOARD_SETTINGS, ...saved.dashboard_settings }
      setDashboardSettings(merged)
      setFleetSettingsDraft(merged)
      setFleetSettingsMessage('Saved ✓')
      setTimeout(() => { setFleetSettingsMessage(''); setFleetSettingsOpen(false) }, 1200)
    } catch {
      setFleetSettingsMessage('Save failed')
      setTimeout(() => setFleetSettingsMessage(''), 4000)
    }
  }

  function updateAddDeviceDraft(patch: Partial<AddDeviceDraft>) {
    setAddDeviceDraft((d) => ({ ...d, ...patch }))
  }

  async function addDevice() {
    const d = addDeviceDraft
    if (!d.id.trim() || !d.name.trim() || !d.base_url.trim()) {
      setAddDeviceMessage('ID, name, and base URL are required.')
      return
    }
    const payload: Record<string, unknown> = {
      id: d.id.trim(), name: d.name.trim(), protocol: d.protocol,
      base_url: d.base_url.trim(), enabled: d.enabled,
    }
    if (d.serial.trim()) payload.serial = d.serial.trim()
    if (d.apiKey.trim()) payload.api_key = d.apiKey.trim()
    if (d.protocol === 'mqtt') {
      if (d.mqttTopic.trim()) payload.mqtt_topic = d.mqttTopic.trim()
      if (d.mqttFieldMapping.trim()) {
        try {
          const m = JSON.parse(d.mqttFieldMapping)
          if (m && typeof m === 'object' && !Array.isArray(m)) payload.mqtt_field_mapping = m
          else throw new Error('not an object')
        } catch {
          setAddDeviceMessage('Field mapping must be valid JSON, e.g. {"state":"st","progress":"pct"}')
          return
        }
      }
    }
    if (addDeviceBusyRef.current) return
    addDeviceBusyRef.current = true
    setAddDeviceBusy(true)
    setAddDeviceMessage('Adding device…')
    try {
      const response = await apiFetch('/api/printers/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const result = await response.json().catch(() => ({})) as { success?: boolean; message?: string }
      if (!response.ok || result.success === false) {
        setAddDeviceMessage(`Add failed: ${result.message || response.statusText}`)
        return
      }
      // Refresh the fleet so the new device shows immediately (the WS would also pick it up).
      try {
        const fresh = await apiFetch('/api/printers')
        if (fresh.ok) {
          const parsed = await fresh.json()
          setFleet({ generated_at: new Date().toISOString(), printers: parsed.printers || [] })
        }
      } catch { /* WS will catch up */ }
      setAddDeviceDraft(EMPTY_ADD_DEVICE_DRAFT)
      setAddDeviceMessage('')
      setAddDeviceOpen(false)
    } finally {
      addDeviceBusyRef.current = false
      setAddDeviceBusy(false)
    }
  }

  async function savePrinterSettings() {
    if (!detailsPrinterId || !printerSettingsDraft) return
    setPrinterSettingsMessage('Saving printer settings...')
    const payload = serializePrinterSettingsDraft(printerSettingsDraft)
    const response = await apiFetch(`/api/printers/${detailsPrinterId}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      const errText = await response.text().catch(() => response.statusText)
      setPrinterSettingsMessage(`Save failed: ${errText}`)
      return
    }
    const saved = await response.json() as { printer: PrinterSettingsPayload; backup_path: string }
    setPrinterSettingsDraft(toPrinterSettingsDraft(saved.printer))
    setPrinterSettingsMessage(`Saved printer settings. Backup: ${saved.backup_path || 'updated config'}`)
    setFleet((current) => ({
      ...current,
      printers: current.printers.map((printer) => printer.id === detailsPrinterId ? mergePrinterWithSettings(printer, saved.printer) : printer),
    }))
    if (diagnostics && diagnostics.printer_id === detailsPrinterId) {
      setDiagnostics((current) => current ? {
        ...current,
        name: saved.printer.name,
        base_url: saved.printer.base_url,
        nozzle_diameter_mm: saved.printer.nozzle_diameter_mm,
        ui_targets: saved.printer.ui_targets,
        capability: {
          ...current.capability,
          profile: saved.printer.compatibility_profile,
          nozzle_diameter_mm: saved.printer.nozzle_diameter_mm,
          build_volume: saved.printer.build_volume,
          supported_materials: saved.printer.supported_materials,
          current_material: saved.printer.current_material,
          current_spool_name: saved.printer.current_spool_name,
          spool_remaining_g: saved.printer.spool_remaining_g,
          filament_sensor: saved.printer.filament_sensor,
          probe: saved.printer.probe,
          webcam_expected: saved.printer.webcam_expected,
          fluidd_url: saved.printer.fluidd_url,
          camera_url: saved.printer.camera_url,
          ui_label: saved.printer.ui_label,
          ui_targets: saved.printer.ui_targets,
          maintenance_lockout: saved.printer.maintenance_lockout,
          maintenance_state: saved.printer.maintenance_state,
          maintenance_due: saved.printer.maintenance_due,
          maintenance_interval_hours: saved.printer.maintenance_interval_hours,
          maintenance_interval_jobs: saved.printer.maintenance_interval_jobs,
          maintenance_interval_filament_g: saved.printer.maintenance_interval_filament_g,
          last_service_at: saved.printer.last_service_at,
          next_service_due: saved.printer.next_service_due,
          jog_enabled: saved.printer.jog_enabled,
          safe_nozzle_max_c: saved.printer.safe_nozzle_max_c,
          safe_bed_max_c: saved.printer.safe_bed_max_c,
          motion_check_required: saved.printer.motion_check_required,
          notes: saved.printer.notes,
          maintenance_notes: saved.printer.maintenance_notes,
        },
      } : current)
    }
  }

  function addMaterialPresetFromEditor() {
    const label = materialPresetEditLabel.trim()
    const nozzle = Number(materialPresetEditNozzle)
    const bed = Number(materialPresetEditBed)
    if (!label || !Number.isFinite(nozzle) || !Number.isFinite(bed)) return
    setCustomPresets((current) => {
      const rest = current.filter((item) => item.label !== label)
      return [...rest, { label, nozzle, bed }].sort((a, b) => a.label.localeCompare(b.label))
    })
    setMaterialPresetEditLabel('')
    setMaterialPresetEditNozzle('210')
    setMaterialPresetEditBed('60')
  }

  function removeMaterialPreset(label: string) {
    setCustomPresets((current) => current.filter((item) => item.label !== label))
  }

  async function loadCardMacros(printerId: string, _force = false) {
    try {
      const res = await apiFetch(`/api/printers/${printerId}/macros`)
      if (res.ok) {
        const data = await res.json() as { macros: MacroEntry[] }
        setCardMacros(prev => ({ ...prev, [printerId]: data.macros }))
      }
    } catch(e) { console.warn('loadCardMacros', e) }
  }

  async function runCardMacro(printerId: string, macroName: string, params: string) {
    const parsed = parseRawMacroParams(params)
    if (parsed === null) {
      pushCardLog(printerId, `✗ ${macroName}: parameters must be KEY=VALUE`, false)
      return
    }
    const cmd = params.trim() ? `${macroName} ${params.trim()}` : macroName
    try {
      const res = await apiFetch(`/api/printers/${printerId}/macros/${encodeURIComponent(macroName)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: parsed }),
      })
      if (res.ok) {
        pushCardLog(printerId, `✓ ${cmd}`, true)
      } else {
        const data = await res.json().catch(() => ({} as {detail?: string}))
        pushCardLog(printerId, `✗ ${cmd}: ${(data as {detail?: string}).detail || res.status}`, false)
      }
    } catch {
      pushCardLog(printerId, `✗ ${cmd}: network error`, false)
    }
  }

  function toggleMacroPin(printerId: string, macroName: string) {
    setCardMacroPins(prev => {
      const pins = prev[printerId] || []
      const next = pins.includes(macroName) ? pins.filter(n => n !== macroName) : [...pins, macroName]
      const updated = { ...prev, [printerId]: next }
      localStorage.setItem('memar-macro-pins', JSON.stringify(updated))
      return updated
    })
  }

  async function runMacro(name: string) {
    if (!detailsPrinterId) return
    setDrawerMsg(`Running ${name}...`, 'info')
    try {
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/macros/${encodeURIComponent(name)}`, { method: 'POST' })
      if (!res.ok) { pushToast('Macro failed', 'error'); setDrawerMsg('', 'info'); return }
      setDrawerMsg(`Ran ${name}`, 'success')
    } catch { pushToast('Macro failed', 'error'); setDrawerMsg('', 'info') }
  }

  async function runMacroWithParams(name: string) {
    if (!detailsPrinterId) return
    const macro = macros.find((item) => item.name === name)
    const typed = macro?.params && Object.keys(macro.params).length > 0

    // Typed macros read their per-field state; untyped ones keep the free-text
    // box. Either way params travel in the request BODY as a KEY=VALUE map —
    // appending them to the macro name in the URL is what the backend rejects
    // with a 400, since a macro name may not contain a space.
    let params: Record<string, string>
    if (typed) {
      params = Object.fromEntries(
        Object.entries(macroTypedParams[name] || {})
          .map(([key, value]) => [key, value.trim()])
          .filter(([, value]) => value !== ''),
      )
    } else {
      const parsed = parseRawMacroParams(macroParams[name] || '')
      if (parsed === null) {
        pushToast('Parameters must be KEY=VALUE, space separated', 'error')
        return
      }
      params = parsed
    }

    const summary = Object.entries(params).map(([key, value]) => `${key}=${value}`).join(' ')
    const cmd = summary ? `${name} ${summary}` : name
    setDrawerMsg(`Running ${cmd}...`, 'info')
    try {
      const res = await apiFetch(`/api/printers/${detailsPrinterId}/macros/${encodeURIComponent(name)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({} as {detail?: string}))
        pushToast((data as {detail?: string}).detail || 'Macro failed', 'error')
        setDrawerMsg('', 'info')
        return
      }
      setDrawerMsg(`Ran ${cmd}`, 'success')
      setMacroExpanded(null)
    } catch { pushToast('Macro failed', 'error'); setDrawerMsg('', 'info') }
  }

  async function runJogNow(distanceOverride?: number) {
    if (!detailsPrinterId || !currentPrinter) return
    const distance = distanceOverride ?? Number(jogDistance)
    if (!Number.isFinite(distance) || distance === 0) {
      setDrawerMsg('Enter a non-zero jog distance.', 'warning')
      return
    }
    setDrawerMsg(`Running motion check for ${jogAxis}${distance}...`, 'info')
    try {
      const checkResponse = await apiFetch(`/api/printers/${detailsPrinterId}/motion-check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent: isCncMachine(currentPrinter.capability.machine_type) ? 'jog' : jogAxis === 'E' ? 'macro' : 'jog' }),
      })
      if (!checkResponse.ok) {
        const errText = await checkResponse.text().catch(() => checkResponse.statusText)
        setDrawerMsg(`Motion check failed: ${errText}`, 'error')
        return
      }
      const checkPayload = await checkResponse.json() as MotionCheckResponse
      setMotionCheckPayload(checkPayload)
      if (!checkPayload.ok) {
        setDrawerMsg(`Jog blocked: ${checkPayload.blocking_reasons.join('; ')}`, 'warning')
        return
      }
      setDrawerMsg(`Jogging ${jogAxis}${distance}...`, 'info')
      const endpoint = isCncMachine(currentPrinter.capability.machine_type) ? `/api/devices/${detailsPrinterId}/cnc/jog` : `/api/printers/${detailsPrinterId}/jog`
      const jogRes = await apiFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ axis: jogAxis, distance, feedrate: Number(jogFeedrate) || undefined, relative: true }),
      })
      setDrawerMsg(jogRes.ok ? `Jogged ${jogAxis}${distance}` : `Jog failed`, jogRes.ok ? 'success' : 'error')
    } finally {
      setDrawerMsg('', 'info')
    }
  }

  async function runDrawerDryRun() {
    if (!detailsPrinterId) return
    setDrawerMsg(`Dry-running ${labelForAction(drawerDryRunAction)}...`, 'info')
    const body: Record<string, unknown> = { printer_ids: [detailsPrinterId], mode: 'standard' }
    if (drawerDryRunAction === 'macro' && macroSearch.trim()) body.macro_name = macroSearch.trim()
    if (drawerDryRunAction === 'temperature') {
      body.nozzle_target = Number(customNozzle)
      body.bed_target = Number(customBed)
    }
    const response = await apiFetch(`/api/dry-run/actions/${drawerDryRunAction}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      const errText = await response.text().catch(() => response.statusText)
      setDrawerMsg(`Dry-run failed: ${errText}`, 'error')
      return
    }
    const payload = await response.json() as DryRunResponse
    setDryRunPayload(payload)
    setDrawerMsg(`Dry-run complete for ${labelForAction(drawerDryRunAction)}`, 'success')
  }

  async function runMotionCheckNow() {
    if (!detailsPrinterId) return
    setDrawerMsg(`Running motion check...`, 'info')
    const response = await apiFetch(`/api/printers/${detailsPrinterId}/motion-check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent: motionIntent, macro_name: macroSearch.trim() || undefined }),
    })
    if (!response.ok) {
      const errText = await response.text().catch(() => response.statusText)
      setDrawerMsg(`Motion check failed: ${errText}`, 'error')
      return
    }
    const payload = await response.json() as MotionCheckResponse
    setMotionCheckPayload(payload)
    setDrawerMsg(`Motion check ${payload.ok ? 'passed' : 'blocked'}`, payload.ok ? 'success' : 'warning')
  }

  async function runHomeNow(axes: string) {
    if (!detailsPrinterId || !currentPrinter) return
    setDrawerMsg(`Homing ${axes}...`, 'info')
    try {
      const motionCheckResponse = await apiFetch(`/api/printers/${detailsPrinterId}/motion-check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent: isCncMachine(currentPrinter.capability.machine_type) ? 'home' : 'jog' }),
      })
      if (!motionCheckResponse.ok) {
        const errText = await motionCheckResponse.text().catch(() => motionCheckResponse.statusText)
        setDrawerMsg(`Motion check failed: ${errText}`, 'error')
        return
      }
      const endpoint = isCncMachine(currentPrinter.capability.machine_type) ? `/api/devices/${detailsPrinterId}/cnc/home` : `/api/printers/${detailsPrinterId}/home`
      const homeRes = await apiFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ axes }),
      })
      setDrawerMsg(homeRes.ok ? `Homed ${axes}` : `Home failed`, homeRes.ok ? 'success' : 'error')
    } catch (err) {
      setDrawerMsg(`Home failed: ${describeError(err)}`, 'error')
    }
  }

  async function runDispatchDryRunNow() {
    if (!dispatchFilename.trim()) {
      setDrawerMsg('Enter a filename for dispatch preflight.', 'warning')
      return
    }
    const candidateIds = fleet.printers.filter(p => p.online).map(p => p.id)
    setDrawerMsg('Running dispatch dry-run...', 'info')
    const response = await apiFetch('/api/dispatch/dry-run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: dispatchFilename.trim(),
        printer_ids: candidateIds,
        material: dispatchMaterial.trim() || undefined,
        nozzle_diameter_mm: Number(dispatchNozzle),
      }),
    })
    if (!response.ok) {
      setDrawerMsg(`Dispatch dry-run failed: ${response.statusText}`, 'error')
      return
    }
    const payload = await response.json() as DispatchDryRunResponse
    setDispatchDryRunPayload(payload)
    setDrawerMsg(`Dispatch dry-run complete: ${payload.recommended_printer_ids.length} recommended target(s)`, 'success')
  }

  // Login effect: restore stored tokens, then fetch demo token and mark logged-in
  useEffect(() => {
    // SSO callback: adopt tokens the IdP returned in the URL fragment, then clean it.
    const ssoFrag = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const ssoAccess = ssoFrag.get('sso_access')
    if (ssoAccess) {
      setTokens(ssoAccess, ssoFrag.get('sso_refresh') || '')
      hadRealSession.current = true
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
    }
    const params = new URLSearchParams(window.location.search)
    // Read reset token synchronously before any async work so the IIFE can gate on it
    const rt = params.get('reset_token')
    if (rt) {
      setResetTokenFromUrl(rt)
      window.history.replaceState(null, '', window.location.pathname)
    }
    initializeAuth()
    let mounted = true

    ;(async () => {
      // If initializeAuth() restored a real token, skip demo auto-login
      if (authState.accessToken) {
        if (!mounted) return
        // A restored token means the user had a real session (a fresh visitor
        // has nothing to restore). If it turns out to be a stale restored demo
        // token, routing a dead session to login is still safe — the login
        // screen offers demo — and it never silently downgrades an operator.
        hadRealSession.current = true
        setAccessToken(authState.accessToken)
        setIsLoggedIn(true)
        return
      }
      // Skip demo auto-login when a password reset token is present in the URL
      if (rt) return
      try {
        const res = await apiFetch('/api/auth/demo')
        if (!mounted) return
        if (res.ok) {
          const data = await res.json() as { access_token: string; refresh_token: string }
          if (!mounted) return
          demoModeRef.current = true
          setIsDemoMode(true)
          setTokens(data.access_token, data.refresh_token)
          setAccessToken(data.access_token)
          setIsLoggedIn(true)
          setLoginError('')
        }
      } catch (err) {
        if (!mounted) return
        console.error('Failed to get demo token:', err)
      }
    })()

    // Check for checkout status from URL; strip param so a refresh doesn't re-trigger
    if (params.get('checkout') === 'success') {
      // Verify subscription is active before showing success
      apiFetch('/api/billing/my-subscription').then(async (res) => {
        if (res.ok) {
          const sub = await res.json()
          if (sub?.status === 'active' || sub?.status === 'trialing') {
            setCheckoutStatus('success')
            setMySubscription(sub)
          }
        }
      }).catch(() => {})
      window.history.replaceState(null, '', window.location.pathname)
    } else if (params.get('checkout') === 'cancelled') {
      setCheckoutStatus('cancelled')
      window.history.replaceState(null, '', window.location.pathname)
    }

    // Re-auth on 401 events
    const handleUnauthorized = () => {
      // A real operator whose session died must go to the login screen — never
      // get silently downgraded into the read-only demo/viewer account. Only
      // fresh first-visit / demo-preview sessions fall back to demo auth.
      if (hadRealSession.current) {
        clearTokens()
        setAccessToken(null)
        setIsLoggedIn(false)
        return
      }
      apiFetch('/api/auth/demo').then(async (res) => {
        if (res.ok) {
          const data = await res.json() as { access_token: string; refresh_token: string }
          demoModeRef.current = true
          setIsDemoMode(true)
          setTokens(data.access_token, data.refresh_token)
          setAccessToken(data.access_token)
          setIsLoggedIn(true)
        } else {
          // Demo re-auth rejected: fall through to the real login screen instead of a stale logged-in state
          setAccessToken(null)
          setIsLoggedIn(false)
        }
      }).catch(() => {
        // Demo re-auth request failed: fall through to the real login screen instead of a stale logged-in state
        setAccessToken(null)
        setIsLoggedIn(false)
      })
    }
    window.addEventListener('memar:unauthorized', handleUnauthorized)

    // T74: Handle forced password change when backend returns 403 with password_change_required
    const handlePasswordChangeRequired = () => {
      setMustChangePassword(true)
    }
    window.addEventListener('memar:password_change_required', handlePasswordChangeRequired)

    // T77: Handle 402 payment required — show detail in toast
    const handlePaymentRequired = (e: Event) => {
      const detail = (e as CustomEvent).detail || 'Payment required'
      pushToast(detail, 'error')
    }
    window.addEventListener('memar:payment_required', handlePaymentRequired)

    return () => {
      mounted = false
      window.removeEventListener('memar:unauthorized', handleUnauthorized)
      window.removeEventListener('memar:password_change_required', handlePasswordChangeRequired)
      window.removeEventListener('memar:payment_required', handlePaymentRequired)
    }
  }, [])

  // License status effect: fetch license status and plans after login
  useEffect(() => {
    if (!isLoggedIn) return
    const fetchLicenseData = async () => {
      try {
        const [licenseRes, plansRes, warningRes, hintRes] = await Promise.all([
          apiFetch('/api/license/status'),
          apiFetch('/api/billing/plans'),
          apiFetch('/api/license/renewal-warning'),
          apiFetch('/api/license/upgrade-hint'),
        ])
        if (licenseRes.ok) {
          setLicenseStatus(await licenseRes.json())
        }
        if (plansRes.ok) {
          setLicensePlans(await plansRes.json())
        }
        if (warningRes.ok) {
          setRenewalWarning(await warningRes.json())
        }
        if (hintRes.ok) {
          setUpgradeHintData(await hintRes.json())
        }
      } catch (err) {
        debug('License', `Failed to fetch license data: ${err}`)
      }
    }
    fetchLicenseData()
  }, [isLoggedIn])

  useEffect(() => {
    if (!showUpgradeModal || upgradeModalTab !== 'history') return
    setInvoicesLoading(true)
    apiFetch('/api/billing/invoices')
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => setInvoices(Array.isArray(rows) ? rows : []))
      .catch(() => setInvoices([]))
      .finally(() => setInvoicesLoading(false))
  }, [showUpgradeModal, upgradeModalTab])

  // Branding effect: apply white-label (tab title + primary colour) from the
  // server. Public endpoint, runs once; fails silently and keeps MEMAR defaults.
  useEffect(() => {
    let cancelled = false
    apiFetch('/api/branding')
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (cancelled || !b) return
        setBranding({ company_name: b.company_name || 'MEMAR', logo_url: b.logo_url || null, primary_color: b.primary_color || '#00a046' })
        if (b.company_name) document.title = b.company_name
        if (b.primary_color) document.documentElement.style.setProperty('--brand-primary', b.primary_color)
      })
      .catch(() => { /* keep MEMAR defaults */ })
    return () => { cancelled = true }
  }, [])

  // SSO config: which login methods are configured + licensed (public endpoint).
  useEffect(() => {
    apiFetch('/api/auth/sso/config')
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => { if (c) setSsoConfig({ oidc: !!c.oidc, ldap: !!c.ldap }) })
      .catch(() => { /* no SSO configured */ })
  }, [])

  // Current user's role (gates the Admin button).
  useEffect(() => {
    if (!isLoggedIn) return
    apiFetch('/api/auth/me').then((r) => (r.ok ? r.json() : null)).then((u) => {
      if (!u) return
      setUserRole(u.role || '')
      setCurrentUsername(u.username || '')  // T73: populate username from /api/auth/me on boot
      setMustChangePassword(Boolean(u.must_change_password))
    }).catch(() => {})
  }, [isLoggedIn])

  // Initial CV anomaly state: the SSE stream below only carries events from
  // the moment it connects, so without this fetch the anomaly badges are
  // empty until the next live detection — stale data on every page load.
  useEffect(() => {
    if (!isLoggedIn) return
    apiFetch('/api/monitor/state').then((r) => (r.ok ? r.json() : null)).then((data) => {
      if (data?.ok && data.anomalies) setCvAnomalies(data.anomalies)
    }).catch(() => { /* SSE stream will still populate state as events arrive */ })
  }, [isLoggedIn])

  // CV anomaly SSE stream effect
  useEffect(() => {
    if (!isLoggedIn) return
    const token = accessToken
    if (!token) return
    const url = `/api/monitor/events`
    // Use fetch-based SSE with auth header (EventSource doesn't support headers)
    let cancelled = false
    const controller = new AbortController()
    ;(async () => {
      try {
        const res = await apiFetch(url, { signal: controller.signal })
        if (!res.ok || !res.body) return
        const stream = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        while (!cancelled) {
          const { done, value } = await stream.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() ?? ''
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const ev = JSON.parse(line.slice(6))
                if (ev.type === 'cv_anomaly' && ev.printer_id && ev.data?.anomaly) {
                  const d = ev.data
                  const label = d.type?.replace(/_/g, ' ') ?? 'anomaly'
                  pushToast(`⚠ ${ev.printer_id}: ${label} detected (${Math.round((d.score ?? 0) * 100)}% score)`, 'warning')
                  setCvAnomalies(prev => ({
                    ...prev,
                    [ev.printer_id]: [...(prev[ev.printer_id] ?? []).slice(-9), {
                      type: d.type ?? 'unknown',
                      score: d.score ?? 0,
                      confidence: d.confidence ?? 'medium',
                      reasoning: d.reasoning ?? '',
                      ts: new Date().toISOString(),
                    }]
                  }))
                }
              } catch { /* ignore parse errors */ }
            }
          }
        }
      } catch { /* stream error — silently ignore */ }
    })()
    return () => { cancelled = true; controller.abort() }
  }, [isLoggedIn, accessToken])

  // Floor plan data effect: fetch layout and image when view opens, and update live with fleet status
  useEffect(() => {
    if (!isLoggedIn) return
    // Wait for the fleet to load before reconciling the saved layout. If this runs
    // while fleet.printers is empty (the layout HTTP response can beat the first WS
    // fleet frame at login), realIds is empty, every saved position is filtered out,
    // and the plan is wiped — which the sync effect then re-seeds at default grid
    // positions and the next drag PUTs, permanently overwriting the saved layout.
    // Keyed on fleet readiness (below) so it re-runs once the fleet arrives.
    if (fleet.printers.length === 0) return
    // This effect can re-fire mid-session (e.g. the 401 re-auth flow resets
    // accessToken), so an in-flight image fetch from a prior run can resolve
    // after a newer one has already started. `cancelled` prevents that
    // stale response from overwriting the fresher image.
    let cancelled = false
    const fetchFloorPlanData = async () => {
      try {
        const layoutRes = await apiFetch('/api/floorplan/layout')
        if (layoutRes.ok) {
          const data = await layoutRes.json()
          // Only update if backend has saved data
          if (data.devices && data.devices.length > 0) {
            const printerStatus = (p: Printer): DevicePosition['status'] =>
              p.job?.state === 'printing' ? 'printing' :
              p.job?.state === 'paused'   ? 'paused'   :
              p.state === 'error'         ? 'error'    :
              !p.online                   ? 'offline'  : 'idle'
            // Merge fetched positions with live status.
            // Only keep entries that match a real fleet printer — orphaned layout
            // entries (stale demo devices, deleted printers) are discarded.
            const realIds = new Set(fleet.printers.map(p => p.id))
            const layoutWithStatus: DevicePosition[] = data.devices
              .filter((pos: DevicePosition) => realIds.has(pos.device_id))
              .map((pos: DevicePosition) => {
                const printer = fleet.printers.find(p => p.id === pos.device_id)!
                return { ...pos, label: printer.name, status: printerStatus(printer), type: printerType(printer) }
              })
            // Auto-add any fleet printers not in the saved layout
            const savedIds = new Set(layoutWithStatus.map(p => p.device_id))
            const missing = fleet.printers.filter(p => !savedIds.has(p.id))
            if (missing.length > 0) {
              const maxX = Math.max(0, ...layoutWithStatus.map(p => p.x))
              missing.forEach((p, i) => layoutWithStatus.push({
                device_id: p.id,
                label: p.name,
                x: maxX + 70 + (i % 3) * 70,
                y: 20 + Math.floor(i / 3) * 70,
                rotation: 0,
                status: printerStatus(p),
                type: printerType(p),
              }))
            }
            setFloorPlanLayout(layoutWithStatus)
          }
          setHiggsfield3DAvailable(Boolean(data.higgsfield_available))
          if (data.image_set) {
            // GET /api/floorplan/image requires a Bearer token, which a bare
            // URL used as a CSS background-image can't carry — fetch it via
            // apiFetch (which attaches the auth header) and use a blob URL
            // instead, or every real (non-dev-bypass) session gets a 401.
            apiFetch('/api/floorplan/image').then(async (res) => {
              if (!res.ok || cancelled) return
              const blob = await res.blob()
              if (cancelled) return
              // Revocation is centralized in the effect below (keyed on
              // floorPlanImageUrl), which fires on every replacement AND on
              // unmount.
              setFloorPlanImageUrl(URL.createObjectURL(blob))
            }).catch(() => undefined)
          }
        }
      } catch (err) {
        debug('FloorPlan', `Failed to fetch floor plan data: ${err}`)
      } finally {
        setFloorPlanLoaded(true)
      }
    }
    fetchFloorPlanData()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, fleet.printers.length > 0])

  // Keep floor plan device statuses in sync with live fleet data.
  // Evict all mock-N entries the moment any real printer appears.
  useEffect(() => {
    if (fleet.printers.length === 0) return

    const statusFor = (p: Printer): DevicePosition['status'] =>
      p.job?.state === 'printing' ? 'printing' :
      p.job?.state === 'paused'   ? 'paused'   :
      p.state === 'error'         ? 'error'    :
      !p.online                   ? 'offline'  : 'idle'

    setFloorPlanLayout(prev => {
      const hasRealPrinter = fleet.printers.some(p => !p.id.startsWith('mock-'))
      const hasMockInLayout = prev.some(pos => pos.device_id.startsWith('mock-'))

      // If real printers exist AND layout has mocks, evict all mocks
      if (hasRealPrinter && hasMockInLayout) {
        const realIds = new Set(fleet.printers.map(p => p.id))
        const kept = prev
          .filter(pos => !pos.device_id.startsWith('mock-') && realIds.has(pos.device_id))
          .map(pos => {
            const p = fleet.printers.find(pr => pr.id === pos.device_id)
            return p ? { ...pos, label: p.name, status: statusFor(p), type: printerType(p) } : pos
          })
        const keptIds = new Set(kept.map(pos => pos.device_id))
        const missing = fleet.printers.filter(p => !keptIds.has(p.id))
        const maxX = kept.length > 0 ? Math.max(...kept.map(p => p.x)) : -80
        const added: DevicePosition[] = missing.map((p, i) => ({
          device_id: p.id,
          label: p.name,
          x: maxX + 80 + (i % 3) * 80,
          y: 40 + Math.floor(i / 3) * 80,
          rotation: 0,
          status: statusFor(p),
          type: printerType(p),
        }))
        return [...kept, ...added]
      }

      // Normal sync: update statuses for real printers, drop orphans, append missing
      const fleetIds = new Set(fleet.printers.map(p => p.id))
      const updated = prev
        .filter(pos => fleetIds.has(pos.device_id))
        .map(pos => {
          const p = fleet.printers.find(pr => pr.id === pos.device_id)
          return p ? { ...pos, label: p.name, status: statusFor(p), type: printerType(p) } : pos
        })
      const existingIds = new Set(updated.map(pos => pos.device_id))
      const missing = fleet.printers.filter(p => !existingIds.has(p.id))
      if (missing.length === 0) {
        const changed = updated.some((d, i) => d.status !== prev[i]?.status || (d as {label?: string}).label !== (prev[i] as {label?: string})?.label)
        return changed ? updated : prev
      }
      const maxX = updated.length > 0 ? Math.max(...updated.map(p => p.x)) : -80
      const added: DevicePosition[] = missing.map((p, i) => ({
        device_id: p.id,
        label: p.name,
        x: maxX + 80 + (i % 3) * 80,
        y: 40 + Math.floor(i / 3) * 80,
        rotation: 0,
        status: statusFor(p),
        type: printerType(p),
      }))
      return [...updated, ...added]
    })
  }, [fleet.printers])

  // Login handler
  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    if (loginBusyRef.current) return
    loginBusyRef.current = true
    setLoginBusy(true)
    setLoginError('')
    try {
      // Trim whitespace from password to prevent common input errors
      const trimmedPassword = loginPassword.trim()
      const res = await apiFetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsername.trim(), password: trimmedPassword }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({})) as { detail?: string }
        setLoginError(errData.detail || 'Invalid username or password. Make sure caps lock is off.')
        return
      }
      const data = await res.json() as { access_token: string; refresh_token?: string; must_change_password?: boolean }
      setTokens(data.access_token, data.refresh_token || '')
      hadRealSession.current = true
      setAccessToken(data.access_token)
      setCurrentUsername(loginUsername.trim())  // Preserve username for PasskeyManager before clearing form
      // Carry the trimmed password into the change form so the user isn't asked
      // to re-enter the credential they just used, then clear login inputs.
      if (data.must_change_password) setPwChangeCurrent(trimmedPassword)
      setMustChangePassword(Boolean(data.must_change_password))
      setLoginUsername('')
      setLoginPassword('')
      demoModeRef.current = false
      setIsLoggedIn(true)
    } catch (err) {
      setLoginError('Connection error')
    } finally {
      loginBusyRef.current = false
      setLoginBusy(false)
    }
  }

  async function handleLdapLogin() {
    setLoginError('')
    try {
      const res = await apiFetch('/api/auth/sso/ldap/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      })
      if (!res.ok) { setLoginError('LDAP sign-in failed'); return }
      const data = await res.json() as { access_token: string; refresh_token?: string }
      setTokens(data.access_token, data.refresh_token || '')
      hadRealSession.current = true
      setAccessToken(data.access_token)
      setLoginUsername(''); setLoginPassword('')
      demoModeRef.current = false
      setIsLoggedIn(true)
    } catch (err) {
      setLoginError('Connection error')
    }
  }

  // Forced password change handler (shipped default admin/admin → new password)
  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    setPwChangeError('')
    if (pwChangeNew.length < 8) {
      setPwChangeError('New password must be at least 8 characters.')
      return
    }
    if (pwChangeNew !== pwChangeConfirm) {
      setPwChangeError('New passwords do not match.')
      return
    }
    setPwChangeBusy(true)
    try {
      const res = await apiFetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: pwChangeCurrent, new_password: pwChangeNew }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => null) as { detail?: string } | null
        setPwChangeError(body?.detail || 'Could not change password.')
        return
      }
      const data = await res.json() as { access_token: string; refresh_token?: string }
      // Adopt the fresh token pair (the default-cred session was rotated out).
      setTokens(data.access_token, data.refresh_token || '')
      setAccessToken(data.access_token)
      setPwChangeCurrent(''); setPwChangeNew(''); setPwChangeConfirm('')
      setMustChangePassword(false)
    } catch (err) {
      setPwChangeError('Connection error')
    } finally {
      setPwChangeBusy(false)
    }
  }

  async function handleForgotPassword(e: React.FormEvent) {
    e.preventDefault()
    setForgotLoading(true); setForgotMsg(''); setForgotResetLink(null)
    try {
      const r = await apiFetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: forgotUsername }),
      })
      if (r.ok) {
        const data = await r.json() as { detail?: string; reset_link?: string }
        setForgotMsg(data.detail || 'If that username exists, a reset link has been sent.')
        // If reset_link is in response (dev mode, SMTP not configured), show it directly
        if (data.reset_link) {
          setForgotResetLink(data.reset_link)
        }
      } else {
        setForgotMsg('Something went wrong. Please try again.')
      }
    } catch {
      setForgotMsg('Connection error. Please try again.')
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleResetPassword(e: React.FormEvent) {
    e.preventDefault()
    if (!resetTokenFromUrl) return
    const trimmedPassword = resetNewPassword.trim()
    if (trimmedPassword.length < 8) { setResetMsg('Password must be at least 8 characters.'); return }
    if (!/[A-Z]/.test(trimmedPassword) || !/[0-9]/.test(trimmedPassword)) {
      setResetMsg('Password must include at least one uppercase letter and one number.')
      return
    }
    setResetLoading(true); setResetMsg('')
    try {
      const r = await apiFetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: resetTokenFromUrl, new_password: trimmedPassword }),
      })
      if (r.ok) {
        setResetSuccess(true)
        setResetMsg('')
        setResetNewPassword('')
        // Auto-redirect to login after 1.5s so user can see success modal
        setTimeout(() => {
          setResetTokenFromUrl(null)
          setResetSuccess(false)
        }, 1500)
      } else {
        const d = await r.json().catch(() => ({})) as { detail?: string }
        setResetMsg(d.detail || 'Reset link expired or invalid. Request a new one.')
      }
    } catch {
      setResetMsg('Connection error. Please try again.')
    } finally {
      setResetLoading(false)
    }
  }

  // Login gate: show login screen if not authenticated
  if (!isLoggedIn) {
    // If a reset token is in the URL, show the reset form instead of login
    if (resetTokenFromUrl) {
      // Success state: show prominent success modal that auto-disappears
      if (resetSuccess) {
        return (
          <main className="login-screen">
            <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10000 }}>
              <div style={{ background: 'var(--surface-l1)', border: '2px solid var(--color-success)', borderRadius: 12, padding: '32px', width: '100%', maxWidth: 320, textAlign: 'center', boxShadow: '0 8px 32px rgba(0,0,0,0.2)' }}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>✓</div>
                <h2 style={{ margin: '0 0 8px', fontSize: 18, color: 'var(--color-success)' }}>Password Reset</h2>
                <p style={{ color: 'var(--text-secondary)', fontSize: 13, margin: '0 0 16px' }}>
                  Your password has been successfully reset. You can now sign in with your new password.
                </p>
                <p style={{ color: 'var(--text-secondary)', fontSize: 12, fontStyle: 'italic', margin: 0 }}>
                  Redirecting to login…
                </p>
              </div>
            </div>
          </main>
        )
      }

      // Normal reset form
      return (
        <main className="login-screen">
          <form onSubmit={handleResetPassword} aria-label="Reset password">
            <h1>{branding.logo_url ? <img src={branding.logo_url} alt={branding.company_name} style={{ maxHeight: 40 }} /> : branding.company_name}</h1>
            <p style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 13, margin: '0 0 8px' }}>
              Enter a new password for your account.
            </p>
            <input
              type="password"
              value={resetNewPassword}
              onChange={e => setResetNewPassword(e.target.value)}
              placeholder="New password (min 8 characters)"
              aria-label="New password"
              autoComplete="new-password"
              minLength={8}
              autoFocus
              required
              disabled={resetLoading}
            />
            {resetMsg && (
              <div style={{ fontSize: 13, color: 'var(--color-danger)', textAlign: 'center' }}>
                {resetMsg}
              </div>
            )}
            <button type="submit" disabled={resetLoading}>{resetLoading ? 'Resetting…' : 'Set new password'}</button>
            <button type="button" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: 13, cursor: 'pointer', marginTop: 4 }} onClick={() => setResetTokenFromUrl(null)}>
              Back to sign in
            </button>
          </form>
        </main>
      )
    }

    return (
      <main className="login-screen">
        {showForgotModal && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }} onClick={() => setShowForgotModal(false)}>
            <div ref={forgotModalRef} role="dialog" aria-modal="true" aria-label="Forgot password" style={{ background: 'var(--surface-l1)', border: '1px solid var(--border-default)', borderRadius: 10, padding: '28px 24px', width: '100%', maxWidth: 360 }} onClick={e => e.stopPropagation()}>
              <h2 style={{ margin: '0 0 12px', fontSize: 16 }}>Reset password</h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: 13, margin: '0 0 14px' }}>
                Enter your username and we'll send a reset link (valid 15 minutes).
              </p>
              <form onSubmit={handleForgotPassword} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <input
                  type="text"
                  value={forgotUsername}
                  onChange={e => setForgotUsername(e.target.value)}
                  placeholder="Username"
                  aria-label="Username for password reset"
                  autoFocus
                  required
                />
                {forgotMsg && (
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'center' }}>{forgotMsg}</div>
                )}
                {forgotResetLink && (
                  <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border-default)', borderRadius: 6, padding: 12, marginTop: 8 }}>
                    <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '0 0 8px' }}>📧 SMTP not configured. Use this link to reset your password:</p>
                    <a
                      href={forgotResetLink}
                      style={{ display: 'block', fontSize: 11, color: '#2563eb', wordBreak: 'break-all', padding: 8, background: 'rgba(37,99,235,0.1)', borderRadius: 4, textDecoration: 'none', marginBottom: 8 }}
                      onClick={() => { setShowForgotModal(false); setForgotMsg(''); setForgotUsername(''); setForgotResetLink(null) }}
                    >
                      {forgotResetLink}
                    </a>
                    <p style={{ fontSize: 11, color: 'var(--text-secondary)', margin: 0 }}>Link expires in 15 minutes.</p>
                  </div>
                )}
                {!forgotResetLink && (
                  <>
                    <button type="submit" disabled={forgotLoading}>{forgotLoading ? 'Sending…' : 'Send reset link'}</button>
                    <button type="button" style={{ background: 'none', border: '1px solid var(--border-default)', color: 'var(--text-secondary)', borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 13 }} onClick={() => { setShowForgotModal(false); setForgotMsg(''); setForgotUsername('') }}>
                      Cancel
                    </button>
                  </>
                )}
              </form>
            </div>
          </div>
        )}
        <form onSubmit={handleLogin}>
          <h1>{branding.logo_url ? <img src={branding.logo_url} alt={branding.company_name} style={{ maxHeight: 40 }} /> : branding.company_name}</h1>
          {/* SECURITY: Passkey login hidden until backend verifies assertions
          <WebAuthnAuth
            onSuccess={(accessToken, refreshToken) => {
              setTokens(accessToken, refreshToken)
              setAccessToken(accessToken)
              setIsLoggedIn(true)
              setLoginUsername('')
              setLoginPassword('')
            }}
            onError={(err) => setLoginError(err)}
          />

          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 13, marginBottom: 12 }}>or</div>
          */}

          <input
            type="text"
            value={loginUsername}
            onChange={e => setLoginUsername(e.target.value)}
            placeholder="Username"
            aria-label="Username"
            autoFocus
            required
          />
          <input
            type="password"
            value={loginPassword}
            onChange={e => setLoginPassword(e.target.value)}
            placeholder="Password"
            aria-label="Password"
            required
          />
          {loginError && <div className="login-error">{loginError}</div>}
          <button type="submit" disabled={loginBusy}>{loginBusy ? 'Signing in…' : 'Sign in'}</button>
          <button
            type="button"
            aria-label="Forgot password"
            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: 13, cursor: 'pointer', marginTop: 4, textDecoration: 'underline' }}
            onClick={() => { setShowForgotModal(true); setForgotMsg(''); setForgotUsername('') }}
          >Forgot password?</button>
        </form>
        {(ssoConfig.oidc || ssoConfig.ldap) && (
          <div className="sso-options" style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 13 }}>or</div>
            {ssoConfig.oidc && (
              <button type="button" onClick={() => { window.location.href = '/api/auth/sso/oidc/login' }}>
                Sign in with SSO
              </button>
            )}
            {ssoConfig.ldap && (
              <button type="button" onClick={handleLdapLogin}>
                Sign in with LDAP
              </button>
            )}
          </div>
        )}
        <p style={{ margin: '20px 0 0', textAlign: 'center', fontSize: 12, color: 'var(--text-secondary)' }}>
          <a href="/privacy.html" target="_blank" rel="noopener" style={{ color: 'inherit' }}>Privacy</a>
          {' · '}
          <a href="/terms.html" target="_blank" rel="noopener" style={{ color: 'inherit' }}>Terms</a>
        </p>
      </main>
    )
  }

  // Forced password change gate: the shipped default admin/admin must be replaced
  // before the app is reachable. Enforced server-side too — this screen is the UX.
  if (mustChangePassword) {
    return (
      <main className="login-screen">
        <form onSubmit={handleChangePassword} aria-label="Set a new password">
          <h1>{branding.logo_url ? <img src={branding.logo_url} alt={branding.company_name} style={{ maxHeight: 40 }} /> : branding.company_name}</h1>
          <p style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 13, margin: '0 0 4px' }}>
            Set a new password to finish setup. The default password can't be kept.
          </p>
          <input
            type="password"
            value={pwChangeCurrent}
            onChange={e => setPwChangeCurrent(e.target.value)}
            placeholder="Current password"
            aria-label="Current password"
            autoComplete="current-password"
            autoFocus
            required
          />
          <input
            type="password"
            value={pwChangeNew}
            onChange={e => setPwChangeNew(e.target.value)}
            placeholder="New password (min 8 characters)"
            aria-label="New password"
            autoComplete="new-password"
            minLength={8}
            required
          />
          <input
            type="password"
            value={pwChangeConfirm}
            onChange={e => setPwChangeConfirm(e.target.value)}
            placeholder="Confirm new password"
            aria-label="Confirm new password"
            autoComplete="new-password"
            minLength={8}
            required
          />
          {pwChangeError && <div className="login-error" role="alert" aria-live="polite">{pwChangeError}</div>}
          <button type="submit" disabled={pwChangeBusy}>{pwChangeBusy ? 'Saving…' : 'Set password & continue'}</button>
        </form>
      </main>
    )
  }

  return (
    <div className={["page", `layout-${dashboardSettings.card_layout}`, `density-${dashboardSettings.card_density}`, dashboardSettings.show_card_preview ? "show-preview" : "hide-preview"].join(" ")}>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <header className="topbar" role="banner">
        <div className="topbar-title-column">
          <h1>{branding.logo_url ? <img src={branding.logo_url} alt={branding.company_name} style={{ maxHeight: 36 }} /> : branding.company_name}</h1>
          <p>Universal equipment fleet monitor</p>
          <span className="topbar-meta">
            Updated {formatTimestamp(fleet.generated_at)}
            {version && <> · v{version.version} · {version.build_id}</>}
            {metrics && <> · Window: {metrics.window_limit} jobs</>}
            {' '}· Layout {dashboardSettings.card_layout} · {dashboardSettings.card_density} · {dashboardSettings.metrics_refresh_seconds}s
          </span>
        </div>
        <div className="inline-actions topbar-actions">
          {userRole === 'admin' && (
            <button type="button" onClick={() => setShowAdminModal(true)} title="Admin settings">Admin</button>
          )}
          {licenseStatus && (
            <button
              className={`license-badge ${licenseStatus.tier === 'free' ? 'free-tier' : ''}`}
              onClick={() => setShowUpgradeModal(true)}
              title={`License: ${licenseStatus.tier} tier`}
            >
              {licenseStatus.tier === 'free'
                ? '⚠ Free — Upgrade'
                : `✓ ${licenseStatus.tier.charAt(0).toUpperCase() + licenseStatus.tier.slice(1)}${licenseStatus.days_remaining != null ? ` · ${licenseStatus.days_remaining}d` : ' · Perpetual'}`}
            </button>
          )}
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setTheme((t) => (t === 'system' ? 'light' : t === 'light' ? 'dark' : 'system'))}
            title={`Theme: ${theme} — click to change`}
            aria-label={`Theme: ${theme}. Click to cycle system, light, dark.`}
          >{theme === 'light' ? '☀' : theme === 'dark' ? '☾' : '◑'}</button>
          <button
            type="button"
            className="kiosk-toggle"
            onClick={() => setKioskMode(true)}
            title="Kiosk / floor display — full-screen, distraction-free (Esc to exit)"
            aria-label="Enter kiosk mode"
          >⛶</button>
          <button onClick={() => { setFleetSettingsDraft(dashboardSettings); setFleetSettingsOpen(true); }}>Fleet settings</button>
          {/* POST /api/printers/add is admin-only (main.py); operators see canWrite,
              not isAdmin, and would always 403 on submit. */}
          {userRole === 'admin' && <button onClick={() => { setAddDeviceDraft(EMPTY_ADD_DEVICE_DRAFT); setAddDeviceMessage(''); setAddDeviceOpen(true); }}>+ Add device</button>}
          <button onClick={() => setFleetToolsOpen(true)}>Fleet tools</button>
          <button onClick={() => setShowAccountSettings(true)} aria-label="Account settings">Account</button>
          <button onClick={() => { void apiFetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined); clearTokens(); setIsLoggedIn(false) }} style={{marginLeft: 4}} aria-label="Log out">Log out</button>
        </div>
        {attentionItems.length > 0 && (
          <div className="attention-dropdown-wrapper" ref={attentionDropdownRef}>
            <button
              className={`attention-bell-btn ${attentionItems.some(i => i.severity === 'critical') ? 'severity-critical' : 'severity-warning'}`}
              onClick={() => setAttentionDropdownOpen((v) => !v)}
              title="Attention needed"
              aria-haspopup="true"
              aria-expanded={attentionDropdownOpen}
            >
              🔔
              <span className="attention-bell-count">{attentionItems.length}</span>
            </button>
            {attentionDropdownOpen && (
              <div className="attention-dropdown" role="menu">
                <div className="attention-dropdown-header">
                  <span>🔔 Attention needed</span>
                  <span className="attention-dropdown-count">{attentionItems.length} printer{attentionItems.length !== 1 ? 's' : ''}</span>
                </div>
                {attentionItems.map((item) => (
                  <div key={item.id} className="attention-dropdown-group">
                    <div className="attention-dropdown-printer">{item.name}</div>
                    {item.warnings.map((w, wi) => (
                      <div key={wi} className={`attention-dropdown-row severity-${w.severity}`}>
                        <button
                          className="attention-row-open"
                          role="menuitem"
                          title={w.message}
                          onClick={() => {
                            setAttentionDropdownOpen(false)
                            const printer = fleet.printers.find((entry) => entry.id === item.id)
                            if (printer) void openPrinterWorkspace(printer, w.code === 'maintenance_due' ? 'maintenance' : 'overview')
                          }}
                        >
                          <span className={`attention-dot severity-${w.severity}`} />
                          <span>{w.message}</span>
                        </button>
                        {(userRole === 'admin' || userRole === 'operator') && (() => {
                          const qa = quickActionFor(w.code)
                          return qa ? <button className="attention-act-btn" title={`${qa.label} — one-click`} onClick={() => w.code && void runQuickAction(item.id, w.code, qa)}>{qa.label}</button> : null
                        })()}
                        {w.code && (userRole === 'admin' || userRole === 'operator') && (
                          <button className="attention-ack" title="Acknowledge — hides until it clears and recurs" onClick={() => void ackAnomaly(item.id, w.code)}>Ack</button>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </header>

      {!wsConnected && fleetLoaded && fleet.printers.length > 0 && (
        <div className="connection-banner">
          ⚠ Connection lost — showing last known state
        </div>
      )}

      {renewalWarning?.warning && (
        <div style={{ background: 'color-mix(in srgb, var(--color-warning) 20%, var(--surface-l1))', color: 'var(--text-primary)', borderLeft: '3px solid var(--color-warning)', padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.9rem', fontWeight: 500 }}>
          <span>⚠️ {renewalWarning.message}</span>
          <button onClick={() => setRenewalWarning(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem', color: 'var(--text-primary)', marginLeft: 16 }} aria-label="Dismiss renewal warning">✕</button>
        </div>
      )}

      {upgradeHintData?.show && (
        <div role="alert" style={{ background: 'color-mix(in srgb, var(--color-danger) 12%, var(--surface-l1))', color: 'var(--text-primary)', borderLeft: '3px solid var(--color-danger)', padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.9rem', fontWeight: 500 }}>
          <span>⚠ Device limit: {upgradeHintData.current}/{upgradeHintData.limit} used — approaching your {upgradeHintData.limit}-device cap.</span>
          {userRole === 'admin' && (
            <button
              aria-label="Upgrade plan to increase device limit"
              onClick={() => setShowUpgradeModal(true)}
              style={{ background: 'var(--color-danger)', color: '#fff', border: 'none', borderRadius: 4, padding: '3px 12px', fontSize: 13, cursor: 'pointer', marginLeft: 16, fontWeight: 600 }}
            >Upgrade</button>
          )}
        </div>
      )}

      <FleetSummary kpi={fleetKpi} m={metrics?.summary} showMetrics={dashboardSettings.show_metrics_strip} onOpenAnalytics={() => setAnalyticsOpen(true)} onOpenService={() => setServiceOpen(true)} />

      <section className="dash-filters" aria-label="Fleet filters and actions">
          <div className="filter-row">
              <input className="search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search printers, jobs, tags, messages" aria-label="Search printers" />
              <select aria-label="Filter by state" value={stateFilter} onChange={(event) => setStateFilter(event.target.value as StateFilter)}>
                <option value="all">All states</option>
                <option value="ready">Ready</option>
                <option value="printing">Printing</option>
                <option value="paused">Paused</option>
                <option value="offline">Offline</option>
                <option value="attention">Attention</option>
              </select>
              <select aria-label="Filter by tag" value={tagFilter} onChange={(event) => setTagFilter(event.target.value)}>
                <option value="all">All tags</option>
                {allTags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
              </select>
              <select aria-label="Group by" value={groupBy} onChange={(event) => setGroupBy(event.target.value as GroupBy)}>
                <option value="none">No grouping</option>
                <option value="state">Group by state</option>
                <option value="tag">Group by tag</option>
              </select>
              <select aria-label="Sort by" value={sortBy} onChange={(event) => setSortBy(event.target.value as SortBy)}>
                <option value="attention">Attention</option>
                <option value="name">Name</option>
                <option value="temperature">Temperature</option>
                <option value="success">Success rate</option>
              </select>
            </div>

          <div className="dashboard-upload-grid">
            {canWrite && (
            <button className="upload-toggle-btn" onClick={() => setUploadPanelOpen(v => !v)} aria-expanded={uploadPanelOpen}>
              {uploadPanelOpen ? '▲ Hide upload' : '▼ Upload file'}
            </button>
            )}
            {uploadPanelOpen && (
              <div className="dashboard-upload-main">
                <div className="control-title">Main dashboard upload</div>
                <div className="upload-toolbar">
                  <input type="file" aria-label="Upload dashboard file" onChange={(event) => setDashboardUploadFile(event.target.files?.[0] || null)} />
                  <select value={dashboardUploadTargetId} onChange={(event) => setDashboardUploadTargetId(event.target.value)} disabled={dashboardUseSelected && selected.size > 0}>
                    {fleet.printers.map((printer) => <option key={printer.id} value={printer.id}>{printer.name}</option>)}
                  </select>
                  {!dashboardUseSelected && dashboardUploadTargetId && (() => {
                    const p = fleet.printers.find(pr => pr.id === dashboardUploadTargetId)
                    if (!p) return null
                    const score = (p.state === 'ready' ? 100 : p.state === 'paused' ? 40 : 10) + ((p.capability.spool_remaining_g ?? 0) / 20)
                    return (
                      <div className="upload-score-hint">
                        Auto-selected: {p.state} · {p.capability.spool_remaining_g ?? 0}g spool · score {score.toFixed(0)}
                      </div>
                    )
                  })()}
                  <label className="checkbox-line"><input type="checkbox" checked={dashboardUseSelected} onChange={(event) => setDashboardUseSelected(event.target.checked)} /> Use selected printers</label>
                  <label className="checkbox-line"><input type="checkbox" checked={dashboardUploadAutoPrint} onChange={(event) => setDashboardUploadAutoPrint(event.target.checked)} /> Auto print</label>
                  <button onClick={() => void uploadFromDashboard()} disabled={!dashboardUploadFile || dashboardUploadBusy}>{dashboardUploadBusy ? 'Uploading…' : 'Upload'}</button>
                </div>
                <div className="subtle small">Choose one target printer, or use the current card selection for multi-printer dispatch.</div>
                <div className="action-message" aria-live="polite" aria-atomic="true">{dashboardUploadMessage}</div>
              </div>
            )}
          </div>

          <div className="quick-actions">
            <button onClick={toggleAllVisible} disabled={visibleIds.length === 0} title={selected.size > 0 ? 'Deselect all visible devices' : 'Select all visible devices'}>
              {selected.size > 0 ? `Deselect all (${selected.size})` : 'Select all'}
            </button>
            {/* T91: Always-visible fleet E-stop — targets selected OR all printing/paused if none selected */}
            {canWrite && (() => {
              const activePrinterIds = fleet.printers
                .filter((p) => p.online && (p.job.state === 'printing' || p.job.state === 'paused'))
                .map((p) => p.id)
              const estopTargets = selected.size > 0 ? Array.from(selected) : activePrinterIds
              const targetCount = estopTargets.length
              return (
                <button
                  onClick={() => {
                    if (targetCount === 0) return
                    openConfirm(`E-stop ${targetCount} machine${targetCount === 1 ? '' : 's'}?`, () => void runToolbarEmergencyStop(estopTargets))
                  }}
                  className="danger-btn"
                  disabled={targetCount === 0}
                  title={selected.size > 0
                    ? `Immediately halt all ${selected.size} selected device${selected.size === 1 ? '' : 's'}`
                    : targetCount > 0
                    ? `Immediately halt all ${targetCount} printing/paused device${targetCount === 1 ? '' : 's'}`
                    : 'No active jobs to stop'}
                >
                  E-Stop{targetCount > 0 ? ` (${targetCount})` : ''}
                </button>
              )
            })()}
            {selected.size > 0 && canWrite && (
              <>
                {['home', 'cooldown', 'motors_off', 'pause', 'resume'].map((action) => (
                  <button key={action} onClick={() => void runBatchAction(action, Array.from(selected))} className="action-btn" title={`${descriptionForAction(action)} on all ${selected.size} selected device${selected.size === 1 ? '' : 's'}`}>
                    {action.replace(/_/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                  </button>
                ))}
                <button onClick={() => void runBatchAction('firmware_restart', Array.from(selected))} className="action-btn" title={`Restart firmware on all ${selected.size} selected device${selected.size === 1 ? '' : 's'}`}>Firmware Restart</button>
                <button onClick={() => void runBatchAction('cancel', Array.from(selected))} className="danger-btn" title={`Cancel the job on all ${selected.size} selected device${selected.size === 1 ? '' : 's'}`}>Cancel</button>
                <div className="batch-preheat-row" style={{display:'flex', gap:6, alignItems:'center', flexWrap:'wrap', marginTop:4}}>
                  <span className="subtle small">Preheat:</span>
                  <select value={batchPreheatLabel} onChange={e => setBatchPreheatLabel(e.target.value)} style={{fontSize:'0.8rem'}} title="Select a preheat preset to apply">
                    {tempPresets.map(p => <option key={p.label} value={p.label}>{p.label}</option>)}
                  </select>
                  <button onClick={() => void applyBatchPresetFor(batchPreheatLabel)} className="action-btn" title={`Apply the "${batchPreheatLabel}" preset to all selected devices`}>Apply Preset</button>
                  <span className="subtle small">or</span>
                  <input type="number" placeholder="Nozzle °C" value={batchCustomNozzle} onChange={e => setBatchCustomNozzle(e.target.value)} style={{width:80, fontSize:'0.8rem'}} min={0} max={350} title="Custom nozzle target temperature" />
                  <input type="number" placeholder="Bed °C" value={batchCustomBed} onChange={e => setBatchCustomBed(e.target.value)} style={{width:72, fontSize:'0.8rem'}} min={0} max={150} title="Custom bed target temperature" />
                  <button onClick={() => void applyBatchCustomTemp()} className="action-btn" disabled={!batchCustomNozzle && !batchCustomBed} title="Apply the custom nozzle/bed temperatures to all selected devices">Set Temps</button>
                </div>
              </>
            )}
            {actionMessage && <div className="action-message" aria-live="polite" aria-atomic="true">{actionMessage}</div>}
          </div>

          <div className="selection-info">
            {visibleIds.length > 0 && <span className="subtle small">{visibleIds.length} visible</span>}
            <SelectionTray
              selected={selected}
              printers={fleet.printers}
              expanded={selectionTrayExpanded}
              onToggle={() => setSelectionTrayExpanded(v => !v)}
              onRemove={(id) => setSelected(current => { const next = new Set(current); next.delete(id); return next })}
              onClearAll={() => setSelected(new Set())}
            />
          </div>
      </section>

        <div className="dash-rail">
        <section className="controls-sidebar">
          {floorPlanLoaded && (
            <section className="floorplan-widget-section">
              <FloorPlanEditor
                devices={floorPlanLayout.filter(d => new Set(filteredPrinters.map(p => p.id)).has(d.device_id))}
                imageUrl={floorPlanImageUrl}
                canEdit={canWrite}
                show3DGenerate={higgsfield3DAvailable}
                selectedIds={Array.from(selected)}
                onDeviceClick={toggle}
                onUploadImage={async (file) => {
                  const body = new FormData()
                  body.append('file', file)
                  const res = await apiFetch('/api/floorplan/image', { method: 'POST', body })
                  if (!res.ok) {
                    const errText = await res.text().catch(() => res.statusText)
                    const detail = (() => { try { return JSON.parse(errText)?.detail } catch { return undefined } })()
                    throw new Error(detail || errText || `Upload failed (HTTP ${res.status})`)
                  }
                  // The backend writes the uploaded bytes to disk unmodified (no
                  // resize/transcode), so the local file is already byte-identical
                  // to what a re-fetch would return — skip the redundant round-trip.
                  setFloorPlanImageUrl(URL.createObjectURL(file))
                }}
                legend={
                  <div className="status-chips">
                    <span className="status-chip"><b>{summary.online}</b>/{summary.total} online</span>
                    <span className="status-chip chip-ready"><i />Ready <b>{summary.ready}</b></span>
                    <span className="status-chip chip-printing"><i />Printing <b>{summary.printing}</b></span>
                    {summary.paused > 0 && <span className="status-chip chip-paused"><i />Paused <b>{summary.paused}</b></span>}
                    {summary.total - summary.online > 0 && <span className="status-chip chip-offline"><i />Offline <b>{summary.total - summary.online}</b></span>}
                    {summary.attention > 0 && <span className="status-chip chip-error"><i />Attention <b>{summary.attention}</b></span>}
                    <span className="status-chip">📷 <b>{summary.webcamsCount}</b></span>
                  </div>
                }
                onLayoutUpdate={async (devices) => {
                  // Always persist to local state + localStorage so edit mode works in demo
                  setFloorPlanLayout(devices)
                  try {
                    localStorage.setItem('memar-floorplan-layout', JSON.stringify(devices))
                  } catch (_) { /* quota exceeded — ignore */ }
                  let res: Response
                  try {
                    const body = JSON.stringify({ devices })
                    debug('FloorPlan', `Saving layout: ${body.substring(0, 100)}...`)
                    res = await apiFetch('/api/floorplan/layout', {
                      method: 'PUT',
                      headers: { 'Content-Type': 'application/json' },
                      body,
                    })
                  } catch (err) {
                    // In demo/standalone (no real login, no backend by design) the local
                    // save is authoritative → treat unreachable as success. But for a REAL
                    // logged-in session the backend SHOULD be reachable, so a network failure
                    // means the layout did NOT persist server-side — surface it instead of a
                    // false "✓ saved" (the operator would otherwise trust an unsaved layout).
                    if (hadRealSession.current) {
                      debug('Floor Plan', `Backend unreachable during real session: ${err}`)
                      throw new Error('Save failed — could not reach the server')
                    }
                    debug('Floor Plan', `Backend unreachable, layout saved locally: ${err}`)
                    return
                  }
                  if (res.ok) {
                    info('Floor Plan', 'Layout saved successfully')
                    return
                  }
                  // A real HTTP rejection (e.g. 403 for a viewer) must surface to the
                  // editor so it shows an error instead of a false "✓ saved".
                  const errText = await res.text().catch(() => res.statusText)
                  debug('Floor Plan', `Backend save rejected ${res.status}: ${errText}`)
                  throw new Error(`Save rejected (${res.status})`)
                }}
              />
            </section>
          )}
        </section>

        <div className="dash-main">

      {filteredPrinters.length === 0 && fleetLoaded && (
        <section className="fleet-matrix-section">
          <div className="fleet-matrix-header"><h3>Fleet Matrix</h3></div>
          <div className="subtle" style={{ textAlign: 'center', padding: '40px', fontSize: '0.9rem' }}>
            {fleet.printers.length === 0 ? 'No printers yet — add a device.' : 'No printers match your current filters.'}
          </div>
        </section>
      )}

      {filteredPrinters.length > 0 && (
        <section className="fleet-matrix-section">
          <div className="fleet-matrix-header">
            <h3>Fleet Matrix</h3>
            {canWrite && <button title="Simulate printer activity for testing" className={`matrix-sim-toggle ${simMode ? 'active' : ''}`} onClick={() => setSimMode((v) => !v)}>{simMode ? 'Sim ON' : 'Sim'}</button>}
          </div>
          <div className="fleet-matrix-scroll">
          <div className={`fleet-matrix${dashboardSettings.show_oee ? '' : ' oee-hidden'}${simMode ? ' sim-watermark' : ''}`} role="grid" aria-label="Fleet machine matrix">
            <div className="fleet-matrix-row fleet-matrix-header-row" role="row">
              <div className="matrix-col-select" onClick={(e) => e.stopPropagation()} role="columnheader">
                <input
                  type="checkbox"
                  title="Select all visible"
                  aria-label="Select all visible printers"
                  checked={selectedVisibleCount === visibleIds.length && visibleIds.length > 0}
                  ref={(el) => { if (el) el.indeterminate = selectedVisibleCount > 0 && selectedVisibleCount < visibleIds.length }}
                  onChange={toggleAllVisible}
                />
              </div>
              <div className="matrix-col-status"></div>
              <div className="matrix-col-name matrix-header-cell" {...sortProps('name')}>Printer {matrixSortCol === 'name' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-state matrix-header-cell" {...sortProps('state')}>State {matrixSortCol === 'state' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-job matrix-header-cell" {...sortProps('job')}>Job {matrixSortCol === 'job' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-temps matrix-header-cell" {...sortProps('nozzle')}>Nozzle {matrixSortCol === 'nozzle' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-temps matrix-header-cell" {...sortProps('bed')}>Bed {matrixSortCol === 'bed' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-progress matrix-header-cell" {...sortProps('progress')}>Prog {matrixSortCol === 'progress' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-oee">OEE</div>
              <div className="matrix-col-spool matrix-header-cell" {...sortProps('spool')}>Spool {matrixSortCol === 'spool' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-material matrix-header-cell" {...sortProps('material')}>Material {matrixSortCol === 'material' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-alerts matrix-header-cell" {...sortProps('alerts')}>Alerts {matrixSortCol === 'alerts' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
              <div className="matrix-col-eta matrix-header-cell" {...sortProps('eta')}>ETA {matrixSortCol === 'eta' ? (matrixSortDir === 'asc' ? '↑' : '↓') : ''}</div>
            </div>
            {displayMatrixPrinters.map((printer) => (
              <MatrixRow
                key={printer.id}
                printer={printer}
                isSelected={selected.has(printer.id)}
                onToggle={() => toggle(printer.id)}
                onOpen={() => void openPrinterWorkspace(printer, 'overview')}
                oee={oeeByDevice.get(printer.id)?.oee ?? null}
              />
            ))}
          </div>
          </div>
        </section>
      )}
        </div>
      </div>

      {!fleetLoaded && (
        <main id="main-content" className="group-stack" aria-busy="true">
          <section className="group">
            <div className="subtle" style={{ textAlign: 'center', marginBottom: 12 }}>Connecting to fleet…</div>
            <div className="grid">
              {Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton skeleton-card" aria-hidden="true" />)}
            </div>
          </section>
        </main>
      )}

      {fleetLoaded && (
        <main id="main-content" className="group-stack">
          {groupedPrinters.length === 0 && (
            <section className="group">
              <div className="subtle" style={{ textAlign: 'center', padding: '60px 20px', fontSize: '0.95rem' }}>
                {fleet.printers.length === 0 ? 'No printers yet — add a device.' : 'No printers match your current filters.'}
              </div>
            </section>
          )}
          {groupedPrinters.map((group) => (
          <section key={group.label} className="group">
            {groupBy !== 'none' && (
              <div className="group-header">
                <h2>{group.label}</h2>
                <span>{group.printers.length}</span>
              </div>
            )}
            <div className="grid">
              {group.printers.map((printer) => {
                const cardAnomalies = [
                  ...(printer.anomalies ?? []),
                  ...(cvAnomalies[printer.id] ?? []).slice(-1).map(a => ({
                    code: 'CV_' + a.type.toUpperCase(),
                    severity: (a.confidence === 'high' ? 'critical' : 'warning') as 'critical' | 'warning',
                    message: a.type.replace(/_/g, ' ') + ': ' + a.reasoning.slice(0, 60)
                  }))
                ]
                const printerWithCvAnomalies = cardAnomalies.length !== printer.anomalies.length
                  ? { ...printer, anomalies: cardAnomalies }
                  : printer
                return (
                <PrinterCard
                  key={printer.id}
                  printer={printerWithCvAnomalies}
                  canWrite={canWrite}
                  isAdmin={userRole === 'admin'}
                  isSelected={selected.has(printer.id)}
                  metric={metricsByPrinter.get(printer.id)}
                  oee={oeeByDevice.get(printer.id)}
                  showOee={dashboardSettings.show_oee}
                  showCardPreview={dashboardSettings.show_card_preview}
                  cardPreset={cardPresetByPrinter[printer.id] || printer.capability.current_material || batchPresetLabel || 'PLA'}
                  activeWebcamKey={activeWebcam[printer.id] || 'default'}
                  snapTs={snapTs}
                  tempData={tempHistory.get(printer.id)}
                  uiMenuOpen={uiMenuPrinterId === printer.id}
                  tempPresets={tempPresets}
                  editingPrinterId={editingPrinterId}
                  editingPrinterName={editingPrinterName}
                  onToggle={() => toggle(printer.id)}
                  onOpenWorkspace={(s) => void openPrinterWorkspace(printer, s)}
                  onRunAction={(a) => void runSingleAction(printer, a)}
                  onRunCncCommand={(kind) => void runCncCommand(printer, kind)}
                  onApplyPreset={() => void applyCardPreset(printer)}
                  onSetCardPreset={(label) => setCardPresetByPrinter(cur => ({ ...cur, [printer.id]: label }))}
                  onCycleWebcam={() => setActiveWebcam(prev => {
                    const cur = prev[printer.id] || 'default'
                    const curIdx = cur === 'default' ? 0 : parseInt(cur)
                    const nextIdx = (curIdx + 1) % printer.webcams_count
                    return { ...prev, [printer.id]: nextIdx === 0 ? 'default' : String(nextIdx) }
                  })}
                  onToggleUiMenu={() => openPrimaryUi(printer)}
                  onCloseUiMenu={() => setUiMenuPrinterId(null)}
                  onRequestConfirm={openConfirm}
                  onEditPrinterName={(printerId, name) => {
                    apiFetch(`/api/printers/${printerId}/name`, {
                      method: 'PUT',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ name }),
                    }).then((res) => {
                      setEditingPrinterId(null)
                      // Only apply the rename to local state if the backend accepted it —
                      // otherwise the UI would show a name the server rejected (e.g. 403).
                      if (!res.ok) return
                      setFleet(f => ({
                        ...f,
                        printers: f.printers.map(p => p.id === printerId ? { ...p, name } : p),
                      }))
                    }).catch(() => setEditingPrinterId(null))
                  }}
                  onSetEditingPrinterId={setEditingPrinterId}
                  onSetEditingPrinterName={setEditingPrinterName}
                  onSetFleet={setFleet}
                  cardVisiblePresets={visiblePresets.filter(p => !printer.capability.supported_materials?.length || printer.capability.supported_materials.includes(p.label))}
                  cardMacros={cardMacros[printer.id]}
                  cardMacroPins={cardMacroPins[printer.id] || []}
                  onLoadMacros={() => void loadCardMacros(printer.id)}
                  onRunCardMacro={(name, params) => void runCardMacro(printer.id, name, params)}
                  onSetSpeedFactor={async (f) => { const res = await apiFetch(`/api/printers/${printer.id}/speed-factor`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ factor: f }) }); pushCardLog(printer.id, res.ok ? `✓ Speed → ${Math.round(f*100)}%` : '✗ speed failed', res.ok) }}
                  onSetFlowFactor={async (f) => { const res = await apiFetch(`/api/printers/${printer.id}/extrude-factor`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ factor: f }) }); pushCardLog(printer.id, res.ok ? `✓ Flow → ${Math.round(f*100)}%` : '✗ flow failed', res.ok) }}
                  onSetTempTarget={async (target, val) => { const res = await apiFetch(`/api/printers/${printer.id}/temperature`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(target === 'nozzle' ? { nozzle_target: val } : { bed_target: val }) }); pushCardLog(printer.id, res.ok ? `✓ ${target === 'nozzle' ? 'Nozzle' : 'Bed'} → ${val}°` : '✗ temp failed', res.ok) }}
                  onSetFeedRate={async (rate) => {
                    const res = await apiFetch(`/api/devices/${printer.id}/feed-rate/${encodeURIComponent(String(rate))}`, { method: 'PUT' })
                    if (res.ok) { pushCardLog(printer.id, `✓ Feed rate → ${rate} mm/min`, true); return }
                    if (res.status === 403) {
                      const body = await res.json().catch(() => null) as { detail?: string } | null
                      if (body?.detail === 'alpha_ack_required') {
                        setAlphaAckPending({ printer, retry: () => {
                          void (async () => {
                            const retryRes = await apiFetch(`/api/devices/${printer.id}/feed-rate/${encodeURIComponent(String(rate))}`, { method: 'PUT' })
                            pushCardLog(printer.id, retryRes.ok ? `✓ Feed rate → ${rate} mm/min` : `✗ Feed rate: ${await retryRes.text().catch(() => retryRes.statusText)}`, retryRes.ok)
                          })()
                        } })
                        return
                      }
                    }
                    const errText = await res.text().catch(() => res.statusText)
                    pushCardLog(printer.id, `✗ Feed rate: ${errText || 'failed'}`, false)
                  }}
                  onToggleMacroPin={(name) => toggleMacroPin(printer.id, name)}
                  cardLog={cardLog[printer.id] || []}
                  onClearCardLog={() => clearCardLog(printer.id)}
                />
              ) })}
            </div>
          </section>
        ))}

      {setupWizardOpen && (
        <SetupWizard isOpen={setupWizardOpen} onClose={() => setSetupWizardOpen(false)} />
      )}
        </main>
      )}

      {fleetSettingsOpen && (
        <div className="drawer-backdrop fleet-settings-backdrop" onClick={() => setFleetSettingsOpen(false)}>
          <aside className="drawer fleet-settings-drawer" role="dialog" aria-modal="true" aria-label="Fleet settings" ref={drawerFleetSettingsRef} tabIndex={-1} onClick={(event) => event.stopPropagation()}>
            <div className="drawer-header">
              <div>
                <h2>Fleet settings</h2>
                <div className="subtle">Configure dashboard layout, refresh behavior, and shared presets.</div>
              </div>
              <div className="drawer-actions">
                <button onClick={() => { setFleetSettingsDraft(dashboardSettings); setFleetSettingsOpen(false) }}>Close</button>
              </div>
            </div>
            <section className="drawer-section">
              <h3>Layout and refresh</h3>
              <div className="settings-grid three-col">
                <label>
                  <span>Card layout</span>
                  <select value={fleetSettingsDraft.card_layout} onChange={(e) => patchFleetSetting({ card_layout: e.target.value as DashboardSettings['card_layout'] })}>
                    <option value="horizontal">horizontal</option>
                    <option value="stacked">stacked</option>
                    <option value="auto">auto</option>
                  </select>
                </label>
                <label>
                  <span>Card density</span>
                  <select value={fleetSettingsDraft.card_density} onChange={(e) => patchFleetSetting({ card_density: e.target.value as DashboardSettings['card_density'] })}>
                    <option value="compact">compact</option>
                    <option value="cozy">cozy</option>
                    <option value="comfortable">comfortable</option>
                  </select>
                </label>
                <label>
                  <span>Default drawer section</span>
                  <select value={fleetSettingsDraft.default_drawer_section} onChange={(e) => patchFleetSetting({ default_drawer_section: e.target.value as DrawerSection })}>
                    {(['overview', 'temperature', 'jog', 'macros', 'files', 'history', 'webcams', 'timelapse', 'dryrun', 'settings', 'console', 'bedmesh', 'queue', 'maintenance', 'health', 'analytics'] as DrawerSection[]).map((section) => <option key={section} value={section}>{section}</option>)}
                  </select>
                </label>
                <label>
                  <span>Metrics history window <small style={{color:'var(--text-secondary)',fontWeight:400}}>(jobs)</small></span>
                  <input type="number" min={5} max={200} value={fleetSettingsDraft.metrics_history_limit} onChange={(e) => patchFleetSetting({ metrics_history_limit: Number(e.target.value) || 50 })} />
                </label>
                <label>
                  <span>Metrics refresh seconds</span>
                  <input type="number" min={5} max={120} value={fleetSettingsDraft.metrics_refresh_seconds} onChange={(e) => patchFleetSetting({ metrics_refresh_seconds: Number(e.target.value) || 15 })} />
                </label>
                <label>
                  <span>Spoolman URL</span>
                  <input type="url" placeholder="http://spoolman:7912" value={fleetSettingsDraft.spoolman_url || ''} onChange={(e) => patchFleetSetting({ spoolman_url: e.target.value || null })} />
                </label>
              </div>
              <div className="inline-actions settings-actions-row">
                <label className="checkbox-line"><input type="checkbox" checked={fleetSettingsDraft.show_card_preview} onChange={(e) => patchFleetSetting({ show_card_preview: e.target.checked })} /> Show card previews</label>
                <label className="checkbox-line"><input type="checkbox" checked={fleetSettingsDraft.show_metrics_strip} onChange={(e) => patchFleetSetting({ show_metrics_strip: e.target.checked })} /> Show metrics strip</label>
                <label className="checkbox-line"><input type="checkbox" checked={fleetSettingsDraft.show_oee} onChange={(e) => patchFleetSetting({ show_oee: e.target.checked })} /> Show OEE (matrix · cards · detail)</label>
                <label className="checkbox-line"><input type="checkbox" checked={fleetSettingsDraft.show_empty_capability_tiles} onChange={(e) => patchFleetSetting({ show_empty_capability_tiles: e.target.checked })} /> Show empty capability tiles</label>
              </div>
            </section>
            <section className="drawer-section">
              <h3>Material preset library</h3>
              <div className="settings-grid three-col">
                <label>
                  <span>Preset label</span>
                  <input value={materialPresetEditLabel} onChange={(event) => setMaterialPresetEditLabel(event.target.value)} placeholder="PETG-CF" />
                </label>
                <label>
                  <span>Nozzle target</span>
                  <input type="number" value={materialPresetEditNozzle} onChange={(event) => setMaterialPresetEditNozzle(event.target.value)} />
                </label>
                <label>
                  <span>Bed target</span>
                  <input type="number" value={materialPresetEditBed} onChange={(event) => setMaterialPresetEditBed(event.target.value)} />
                </label>
              </div>
              <div className="inline-actions settings-actions-row">
                <button onClick={addMaterialPresetFromEditor}>Add/update preset</button>
              </div>
              <div className="subtle small" style={{ marginBottom: 8 }}>All presets (builtin + custom). Toggle 👁 to hide from card; trash to delete custom ones.</div>
              <div className="preset-editor-list">
                {tempPresets.map((preset) => (
                  <div key={preset.label} className="settings-target-row preset-editor-row">
                    <strong>{preset.label}</strong>
                    <span>{preset.nozzle}/{preset.bed}</span>
                    <button title={hiddenPresets.has(preset.label) ? 'Show on card' : 'Hide from card'} onClick={() => toggleHiddenPreset(preset.label)}>
                      {hiddenPresets.has(preset.label) ? '🚫' : '👁'}
                    </button>
                    {!preset.builtin && <button onClick={() => removeMaterialPreset(preset.label)} aria-label={`Delete preset ${preset.label}`}>🗑</button>}
                  </div>
                ))}
              </div>
            </section>
            <div className="inline-actions settings-actions-row">
              {canWrite && <button className="btn btn-primary" onClick={() => void saveFleetSettings()}>Save &amp; Close</button>}
              <button onClick={() => { setFleetSettingsDraft(dashboardSettings); setDashboardSettings(dashboardSettings) }}>Revert changes</button>
            </div>
            <div className="action-message" aria-live="polite" aria-atomic="true">{fleetSettingsMessage}</div>
            <div className="settings-export-import">
              <button onClick={() => {
                const data = JSON.stringify({dashboard_settings: fleetSettingsDraft, material_presets: customPresets}, null, 2)
                const blob = new Blob([data], {type: 'application/json'})
                const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
                a.download = 'memar-settings.json'; a.click()
              }}>&#x2B07; Export Settings</button>
              <input type="file" accept=".json" style={{display:'none'}} id="import-settings-input"
                onChange={e => {
                  const file = e.target.files?.[0]; if (!file) return
                  void file.text().then(text => {
                    try {
                      const data = JSON.parse(text) as { dashboard_settings?: Partial<DashboardSettings>; material_presets?: TempPreset[] }
                      if (data.dashboard_settings) setFleetSettingsDraft(d => ({...d, ...data.dashboard_settings}))
                      if (Array.isArray(data.material_presets)) {
                        const valid = data.material_presets.filter((p): p is TempPreset => !!p && typeof p.label === 'string' && typeof p.nozzle === 'number' && typeof p.bed === 'number')
                        setCustomPresets(valid)
                      }
                    } catch { alert('Invalid settings file') }
                  })
                  // reset so same file can be re-imported
                  e.target.value = ''
                }}
              />
              <button onClick={() => document.getElementById('import-settings-input')?.click()}>&#x2B06; Import Settings</button>
            </div>
          </aside>
        </div>
      )}

      {detailsOpen && (
        <div className="drawer-backdrop" onClick={closeWorkspace}>
          <aside className="drawer" role="dialog" aria-modal="true" aria-label="Printer workspace" ref={drawerWorkspaceRef} tabIndex={-1} onClick={(event) => event.stopPropagation()}>
            <div className="drawer-header">
              <div>
                <h2>{currentPrinter?.name || detailsPrinterId}</h2>
                <div className="subtle">{diagnostics?.base_url || 'Loading...'}</div>
              </div>
              <div className="drawer-actions">
                <button onClick={() => currentPrinter && openPrinterWorkspace(currentPrinter, activeSection)}>Refresh</button>
                {currentPrinter && (printerUiTargets(currentPrinter).length > 0) && (
                  <UiTargetMenu
                    printerId={currentPrinter.id}
                    label={currentPrinter.capability.ui_label || 'Open UI'}
                    targets={printerUiTargets(currentPrinter)}
                    open={uiMenuPrinterId === currentPrinter.id}
                    onToggle={() => openPrimaryUi(currentPrinter)}
                    onClose={() => setUiMenuPrinterId(null)}
                  />
                )}
                <button onClick={closeWorkspace}>Close</button>
              </div>
            </div>

            <div
              className="drawer-tabs"
              role="tablist"
              aria-label="Drawer sections"
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '8px',
                overflowX: 'visible',
                overflowY: 'visible',
              }}
            >
              {(['overview', 'temperature', 'jog', 'macros', 'files', 'history', 'webcams', 'timelapse', 'dryrun', 'settings', 'console', 'bedmesh', 'queue', 'maintenance', 'health', 'cnc', 'coolant', 'analytics', 'system-settings'] as DrawerSection[])
                .filter((section) => (section !== 'coolant' && section !== 'cnc') || isCncMachine(currentPrinter?.capability.machine_type))
                // Files/Macros/Bedmesh are unsupported by GRBL (no filesystem/macros/leveling).
                .filter((section) => !(['files', 'macros', 'bedmesh'].includes(section) && currentPrinter?.protocol === 'grbl'))
                // Webcams require at least one configured camera.
                .filter((section) => section !== 'webcams' || (currentPrinter?.webcams_count ?? 0) > 0)
                // Pure-control tabs are hidden for read-only viewers (jog/console move
                // or command the machine; bed-mesh calibrates). Read tabs stay.
                .filter((section) => canWrite || !['jog', 'console', 'bedmesh'].includes(section))
                .map((section) => (
                <button key={section} className={activeSection === section ? 'tab-active' : ''} aria-current={activeSection === section ? 'page' : undefined} onClick={() => setActiveSection(section)}>{capitalize(section)}</button>
              ))}
            </div>

            {drawerLoading && <div className="drawer-section">Loading workspace…</div>}
            {!drawerLoading && (
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeSection}
                  initial={{ x: 400, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  exit={{ x: 400, opacity: 0 }}
                  transition={{
                    duration: 0.3,
                    ease: 'easeOut',
                    type: 'tween',
                  }}
                >
                  <div className={`drawer-message drawer-message-${drawerMessage.severity}`} aria-live="polite" aria-atomic="true">{drawerMessage.text}</div>

                {activeSection === 'overview' && dashboardSettings.show_oee && currentPrinter && oeeByDevice.get(currentPrinter.id) && (
                  <section className="drawer-section"><MachineOee variant="full" oee={oeeByDevice.get(currentPrinter.id)} /></section>
                )}

                {activeSection === 'overview' && currentMetric && (
                  <section className="drawer-section">
                    <OverviewGraphs currentMetric={currentMetric} printerId={detailsPrinterId || ''} />
                  </section>
                )}

                {activeSection === 'overview' && diagnostics && (
                  <>
                    <section className="drawer-section">
                      <h3>State</h3>
                      <div className="kv-grid">
                        <div><span>Status</span><strong>{diagnostics.state}</strong></div>
                        <div><span>Klippy connected</span><strong>{String(diagnostics.klippy_connected)}</strong></div>
                        <div><span>Moonraker</span><strong>{diagnostics.moonraker_version || '—'}</strong></div>
                        <div><span>API</span><strong>{diagnostics.api_version_string || '—'}</strong></div>
                        <div><span>PID</span><strong>{diagnostics.process_id ?? '—'}</strong></div>
                        <div><span>Attention</span><strong>{diagnostics.attention_needed ? 'Yes' : 'No'}</strong></div>
                      </div>
                    </section>
                    <section className="drawer-section">
                      <h3>Current file</h3>
                      {currentFileDetail?.detail ? <FileDetailCard detail={currentFileDetail.detail} /> : <div className="subtle">No active or selected file.</div>}
                    </section>
                    <section className="drawer-section">
                      <h3>Printer metrics</h3>
                      <div className="kv-grid">
                        <div><span>Success rate</span><strong>{currentMetric?.success_rate == null ? '—' : `${currentMetric.success_rate.toFixed(1)}%`}</strong></div>
                        <div><span>Completed</span><strong>{currentMetric?.completed_jobs ?? 0}</strong></div>
                        <div><span>Failed</span><strong>{currentMetric?.failed_jobs ?? 0}</strong></div>
                        <div><span>Cancelled</span><strong>{currentMetric?.cancelled_jobs ?? 0}</strong></div>
                        <div><span>Total print time</span><strong>{formatDuration(currentMetric?.total_print_time)}</strong></div>
                        <div><span>Filament used</span><strong>{formatMillimeters(currentMetric?.total_filament_used)}</strong></div>
                        <div><span>Average print</span><strong>{formatDuration(currentMetric?.avg_print_time)}</strong></div>
                        <div><span>Last job</span><strong>{formatTimestamp(currentMetric?.last_job_end_time)}</strong></div>
                      </div>
                    </section>
                    {cvAnomalies[detailsPrinterId ?? '']?.length > 0 && (
                      <section className="drawer-section">
                        <h3>CV Monitor</h3>
                        <div style={{display:'flex', flexDirection:'column', gap:6}}>
                          {[...(cvAnomalies[detailsPrinterId ?? ''] ?? [])].reverse().slice(0, 5).map((a, i) => (
                            <div key={i} className="subtle small" style={{display:'flex', gap:8, alignItems:'center'}}>
                              <span style={{color: a.confidence === 'high' ? 'var(--color-error, #e53)' : 'var(--color-warning, #f90)'}}>
                                ⚠ {a.type.replace(/_/g, ' ')}
                              </span>
                              <span>{Math.round(a.score * 100)}%</span>
                              <span className="subtle">{a.reasoning}</span>
                            </div>
                          ))}
                        </div>
                      </section>
                    )}
                    <section className="drawer-section">
                      <h3>Filament</h3>
                      <div style={{display:'flex', flexDirection:'column', gap:8}}>
                        {canWrite && (
                        <div style={{display:'flex', gap:8, alignItems:'center', flexWrap:'wrap'}}>
                          <input
                            type="text"
                            placeholder="Material (e.g. PLA)"
                            value={quickMaterial}
                            onChange={e => setQuickMaterial(e.target.value)}
                            style={{flex:'1 1 100px', minWidth:80}}
                          />
                          <input
                            type="number"
                            placeholder="Remaining (g)"
                            value={quickRemaining}
                            onChange={e => setQuickRemaining(e.target.value)}
                            style={{flex:'1 1 80px', minWidth:70}}
                            min={0}
                          />
                          <button onClick={() => void saveQuickFilamentWithLog()} disabled={quickFilamentSaving} className="action-btn">
                            {quickFilamentSaving ? 'Saving\u2026' : 'Update'}
                          </button>
                        </div>
                        )}
                        {canWrite && (
                        <div style={{display:'flex', gap:8, alignItems:'center'}}>
                          <label className="action-btn" style={{cursor:'pointer', opacity: spoolEstimating ? 0.6 : 1}}>
                            {spoolEstimating ? '\u23f3 Estimating\u2026' : '\uD83D\uDCF7 Estimate from photo'}
                            <input
                              type="file"
                              accept="image/*"
                              capture="environment"
                              style={{display:'none'}}
                              disabled={spoolEstimating}
                              onChange={e => { const f = e.target.files?.[0]; if (f) void estimateSpoolFromPhoto(f); e.target.value = '' }}
                            />
                          </label>
                          {spoolEstimateResult && (
                            <span className="subtle small">
                              {Math.round(spoolEstimateResult.fill_pct * 100)}% · {spoolEstimateResult.confidence} · {spoolEstimateResult.model_used}
                            </span>
                          )}
                        </div>
                        )}
                        {spoolEstimateResult?.reasoning && (
                          <div className="subtle small" style={{fontStyle:'italic'}}>{spoolEstimateResult.reasoning}</div>
                        )}
                        {diagnostics.capability.spool_remaining_g != null && (
                          <div className="subtle small">{diagnostics.capability.spool_remaining_g}g remaining · {diagnostics.capability.current_material || 'no material set'}</div>
                        )}
                        {/* Spool depletion log */}
                        <div style={{marginTop:8}}>
                          <button
                            className="action-btn"
                            style={{fontSize:'0.8rem', padding:'3px 10px'}}
                            onClick={() => { setSpoolLogOpen(v => !v); if (!spoolLogOpen && detailsPrinterId) void fetchSpoolLog(detailsPrinterId) }}
                          >
                            {spoolLogOpen ? '\u25b4 Hide log' : '\u25be Depletion log'}{spoolLog.length > 0 ? ` (${spoolLog.length})` : ''}
                          </button>
                          {spoolLogOpen && (
                            <div style={{marginTop:6, overflowX:'auto'}}>
                              {spoolLogLoading ? (
                                <span className="subtle small">Loading\u2026</span>
                              ) : spoolLog.length === 0 ? (
                                <span className="subtle small">No entries yet — deductions are recorded automatically on job completion.</span>
                              ) : (
                                <table style={{width:'100%', fontSize:'0.78rem', borderCollapse:'collapse'}}>
                                  <thead>
                                    <tr style={{opacity:0.55}}>
                                      <th style={{textAlign:'left', paddingBottom:4}}>Date</th>
                                      <th style={{textAlign:'left', paddingBottom:4}}>Job</th>
                                      <th style={{textAlign:'right', paddingBottom:4}}>Used (g)</th>
                                      <th style={{textAlign:'right', paddingBottom:4}}>After (g)</th>
                                      <th style={{textAlign:'left', paddingBottom:4}}>Src</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {spoolLog.map(entry => (
                                      <tr key={entry.id} style={{borderTop:'1px solid var(--color-border, #333)'}}>
                                        <td style={{padding:'3px 6px 3px 0', whiteSpace:'nowrap'}}>
                                          {entry.created_at ? new Date(entry.created_at).toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—'}
                                        </td>
                                        <td style={{padding:'3px 6px', maxWidth:140, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}} title={entry.job_name ?? undefined}>
                                          {entry.job_name ?? <span style={{opacity:0.4}}>—</span>}
                                        </td>
                                        <td style={{textAlign:'right', padding:'3px 6px', color: (entry.filament_used_g ?? 0) > 0 ? 'var(--color-warning, #f90)' : undefined}}>
                                          {entry.filament_used_g != null ? `-${entry.filament_used_g}` : '—'}
                                        </td>
                                        <td style={{textAlign:'right', padding:'3px 6px', fontWeight:600}}>
                                          {entry.spool_after_g ?? '—'}
                                        </td>
                                        <td style={{padding:'3px 0 3px 6px', opacity:0.5}}>
                                          {entry.source === 'manual' ? '✏' : '⚙'}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </section>

                    {canWrite && (
                      <section className="drawer-section">
                        <MaterialSelector onApply={(name: string) => setQuickMaterial(name)} />
                      </section>
                    )}

                    <section className="drawer-section">
                      <h3>Capability profile</h3>
                      <div className="kv-grid">
                        {capabilityOverviewItems(diagnostics.capability, diagnostics.homed_axes, dashboardSettings.show_empty_capability_tiles).map((item) => (
                          <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>
                        ))}
                      </div>
                    </section>
                    {diagnostics.klipper_config && (
                      <section className="drawer-section">
                        <h3>Hardware config <span className="subtle small">(printer.cfg)</span></h3>
                        <KlipperConfigPanel cfg={diagnostics.klipper_config} />
                      </section>
                    )}
                    <section className="drawer-section">
                      <h3>Suggested checks</h3>
                      <ul>{diagnostics.suggested_checks.map((item) => <li key={item}>{item}</li>)}</ul>
                    </section>
                    <section className="drawer-section">
                      <h3>Paths</h3>
                      <div className="path-list">
                        <code>{diagnostics.config_file || '—'}</code>
                        <code>{diagnostics.log_file || '—'}</code>
                      </div>
                    </section>
                    <section className="drawer-section">
                      <h3>Recent log lines</h3>
                      <pre className="log-box">{diagnostics.recent_log_lines.length > 0 ? diagnostics.recent_log_lines.join('\n') : 'No log lines available to the service user.'}</pre>
                    </section>
                    {currentPrinter?.state === 'printing' && (
                      <section className="drawer-section">
                        <h3>Exclude objects</h3>
                        {excludeObjects === null && (
                          <button onClick={() => void loadExcludeObjects()} className="action-btn">Load objects</button>
                        )}
                        {excludeObjects !== null && !excludeObjects.supported && (
                          <div className="subtle">Not available. Add <code>[exclude_object]</code> to printer.cfg to enable.</div>
                        )}
                        {excludeObjects?.supported && (
                          <>
                            {excludeObjects.objects.length === 0 && <div className="subtle">No named objects in current print.</div>}
                            {/* Slicers that emit POLYGON data with EXCLUDE_OBJECT_DEFINE get the
                                bed map; the rest keep the flat button list, which is the only
                                affordance available when we have names but no geometry. */}
                            {hasPolygonData(excludeObjects.objects) ? (
                              <ExcludeObjectsMap
                                objects={excludeObjects.objects}
                                excluded={excludeObjects.excluded}
                                currentObject={excludeObjects.current_object}
                                canWrite={canWrite}
                                onExclude={(name) => setConfirmState({message: `Exclude "${name}" from print?`, onConfirm: () => void doExcludeObject(name)})}
                              />
                            ) : (
                            <div style={{display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4}}>
                              {excludeObjects.objects.map((obj) => {
                                const isExcluded = excludeObjects.excluded.includes(obj.name)
                                const isCurrent = excludeObjects.current_object === obj.name
                                return (
                                  <button
                                    key={obj.name}
                                    onClick={() => canWrite && !isExcluded && setConfirmState({message: `Exclude "${obj.name}" from print?`, onConfirm: () => void doExcludeObject(obj.name)})}
                                    style={{
                                      opacity: isExcluded ? 0.45 : 1,
                                      textDecoration: isExcluded ? 'line-through' : 'none',
                                      border: isCurrent ? '1px solid var(--accent-solid)' : undefined,
                                      cursor: isExcluded || !canWrite ? 'default' : 'pointer',
                                      fontSize: 11,
                                    }}
                                    disabled={isExcluded || !canWrite}
                                    title={isExcluded ? 'Already excluded' : !canWrite ? 'Requires operator or admin role' : `Exclude ${obj.name}`}
                                  >
                                    {obj.name}{isCurrent ? ' ●' : ''}
                                  </button>
                                )
                              })}
                            </div>
                            )}
                            <button onClick={() => void loadExcludeObjects()} style={{marginTop: 8, fontSize: 11}} className="action-btn">Refresh</button>
                          </>
                        )}
                      </section>
                    )}
                  </>
                )}

                {activeSection === 'temperature' && (
                  <section className="drawer-section">
                    <h3>Temperature controls</h3>
                    <div className="kv-grid compact-grid">
                      <div><span>Current nozzle</span><strong>{fmtTemp(currentPrinter?.nozzle.temperature ?? null, currentPrinter?.nozzle.target ?? null)}</strong></div>
                      <div><span>Current bed</span><strong>{fmtTemp(currentPrinter?.bed.temperature ?? null, currentPrinter?.bed.target ?? null)}</strong></div>
                    </div>
                    {canWrite && <div className="preset-row drawer-preset-row">
                      {tempPresets.map((preset) => <button key={preset.label} onClick={() => void applyPreset(preset.nozzle, preset.bed)}>{preset.label} {preset.nozzle}/{preset.bed}</button>)}
                    </div>}
                    <div className="temp-grid">
                      <label>
                        <span>Nozzle target</span>
                        <input type="number" value={customNozzle} onChange={(event) => setCustomNozzle(event.target.value)} />
                      </label>
                      <label>
                        <span>Bed target</span>
                        <input type="number" value={customBed} onChange={(event) => setCustomBed(event.target.value)} />
                      </label>
                    </div>
                    {canWrite && <div className="inline-actions">
                      <button onClick={() => void applyCustomTemperatures()}>Apply temperatures</button>
                      {savePresetLabel === null ? (
                        <button onClick={() => setSavePresetLabel('')}>Save preset</button>
                      ) : (
                        <>
                          <input
                            autoFocus
                            value={savePresetLabel}
                            onChange={(e) => setSavePresetLabel(e.target.value)}
                            placeholder="Preset name"
                            style={{ width: 110 }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') { saveCurrentPreset(); e.preventDefault() }
                              if (e.key === 'Escape') { setSavePresetLabel(null); e.preventDefault() }
                            }}
                          />
                          <button onClick={saveCurrentPreset}>Save</button>
                          <button onClick={() => setSavePresetLabel(null)}>Cancel</button>
                        </>
                      )}
                    </div>}
                    {tempHistoryDetail && (() => {
                      const extData = tempHistoryDetail.extruder
                      const bedData = tempHistoryDetail.bed
                      if (!extData.length && !bedData.length) return null
                      const allTemps = [...extData.map((d) => d.temperature), ...bedData.map((d) => d.temperature)]
                      const minT = Math.floor(Math.min(...allTemps) - 5)
                      const maxT = Math.ceil(Math.max(...allTemps) + 5)
                      const W = 320, H = 100
                      const n = Math.max(extData.length, bedData.length)
                      const xOf = (i: number, len: number) => Math.round((i / Math.max(len - 1, 1)) * W)
                      const yOf = (t: number) => Math.round(H - ((t - minT) / (maxT - minT)) * H)
                      const toPath = (pts: Array<{temperature: number}>) =>
                        pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(i, pts.length)},${yOf(p.temperature)}`).join(' ')
                      return (
                        <div style={{marginTop: 12}}>
                          <div className="subtle small" style={{marginBottom: 4}}>Temperature history ({extData.length} points)</div>
                          <svg
                            viewBox={`0 0 ${W} ${H}`}
                            width="100%"
                            style={{background: 'var(--bg-2,#1a1a1a)', borderRadius: 4, display: 'block'}}
                            role="img"
                            aria-label="Temperature chart showing nozzle and bed temperature history"
                          >
                            {extData.length > 1 && <path d={toPath(extData)} fill="none" stroke="var(--temperature-hot)" strokeWidth={1.5} />}
                            {bedData.length > 1 && <path d={toPath(bedData)} fill="none" stroke="var(--temperature-cold)" strokeWidth={1.5} />}
                          </svg>
                          <div className="subtle small" style={{display: 'flex', gap: 10, marginTop: 4}}>
                            <span style={{color: 'var(--temperature-hot)'}}>— nozzle</span>
                            <span style={{color: 'var(--temperature-cold)'}}>— bed</span>
                            <span>{minT}°C – {maxT}°C</span>
                          </div>
                        </div>
                      )
                    })()}
                  </section>
                )}

                {activeSection === 'jog' && canWrite && (
                  <section className="drawer-section">
                    <h3>Jog controls</h3>
                    <div style={{display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap'}}>
                      <input
                        type="number"
                        step="0.1"
                        value={jogDistance}
                        onChange={(event) => setJogDistance(event.target.value)}
                        placeholder="distance"
                        style={{flex: 1, minWidth: 80}}
                        aria-label="Jog distance (mm)"
                      />
                      <input
                        type="number"
                        step="10"
                        value={jogFeedrate}
                        onChange={(event) => setJogFeedrate(event.target.value)}
                        placeholder="feedrate"
                        style={{flex: 1, minWidth: 100}}
                        aria-label="Jog feedrate (mm/min)"
                      />
                      <button onClick={() => void runMotionCheckNow()} style={{minWidth: 100}} aria-label="Run motion check">Motion check</button>
                    </div>
                    <div style={{display: 'flex', gap: 12, marginBottom: 12}}>
                      {/* X/Y D-pad */}
                      <div style={{display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center'}} role="group" aria-label="X/Y axis control (D-pad)">
                        <div style={{fontSize: '0.75rem', marginBottom: 4, textAlign: 'center', color: 'var(--text-secondary)'}}>X / Y</div>
                        <button onClick={() => { setJogAxis('Y'); void runJogNow(Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1.5rem'}} aria-label="Jog Y+ (forward)" title="Jog Y+ (forward)">↑</button>
                        <div style={{display: 'flex', gap: 4}}>
                          <button onClick={() => { setJogAxis('X'); void runJogNow(-Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1.5rem'}} aria-label="Jog X- (left)" title="Jog X- (left)">←</button>
                          <button onClick={() => void runHomeNow('xy')} style={{width: 50, height: 50, fontSize: '1rem', fontWeight: 500}} aria-label="Home XY" title="Home XY">HOME</button>
                          <button onClick={() => { setJogAxis('X'); void runJogNow(Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1.5rem'}} aria-label="Jog X+ (right)" title="Jog X+ (right)">→</button>
                        </div>
                        <button onClick={() => { setJogAxis('Y'); void runJogNow(-Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1.5rem'}} aria-label="Jog Y- (back)" title="Jog Y- (back)">↓</button>
                      </div>
                      {/* Z axis buttons */}
                      <div style={{display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center'}} role="group" aria-label="Z axis control">
                        <div style={{fontSize: '0.75rem', marginBottom: 4, textAlign: 'center', color: 'var(--text-secondary)'}}>Z</div>
                        <button onClick={() => { setJogAxis('Z'); void runJogNow(Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1.5rem'}} aria-label="Jog Z+ (up)" title="Jog Z+ (up)">↑</button>
                        <button onClick={() => void runHomeNow('z')} style={{width: 50, height: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.8rem', fontWeight: 500}} aria-label="Home Z" title="Home Z">HOME</button>
                        <button onClick={() => { setJogAxis('Z'); void runJogNow(-Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1.5rem'}} aria-label="Jog Z- (down)" title="Jog Z- (down)">↓</button>
                      </div>
                      {/* Extruder or other axes */}
                      {!isCncMachine(currentPrinter?.capability.machine_type) && (
                        <div style={{display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center'}} role="group" aria-label="Extruder control">
                          <div style={{fontSize: '0.75rem', marginBottom: 4, textAlign: 'center', color: 'var(--text-secondary)'}}>E</div>
                          <button onClick={() => { setJogAxis('E'); void runJogNow(Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1rem', fontWeight: 500}} aria-label="Extrude (E+)" title="Extrude">+E</button>
                          <div style={{width: 50, height: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontSize: '0.75rem'}}>Extrude</div>
                          <button onClick={() => { setJogAxis('E'); void runJogNow(-Number(jogDistance)) }} style={{width: 50, height: 50, fontSize: '1rem', fontWeight: 500}} aria-label="Retract (E-)" title="Retract">-E</button>
                        </div>
                      )}
                    </div>
                    <div style={{display: 'flex', gap: 4, marginBottom: 12}}>
                      <div style={{fontSize: '0.75rem', color: 'var(--text-secondary)'}}>Quick distances:</div>
                      {[0.1, 1, 10].map((dist) => (
                        <button key={dist} onClick={() => { setJogDistance(String(dist)); void runJogNow(dist) }} style={{fontSize: '0.8rem', padding: '4px 8px', minWidth: 'auto'}} aria-label={`Jog ${dist}mm`} title={`Quick set to ${dist}mm`}>
                          {dist}mm
                        </button>
                      ))}
                    </div>
                    <div className="subtle small">Jogging runs a motion check first. Extruder jog should only be used when hot.</div>
                    {motionCheckPayload && (
                      <pre className="log-box">{JSON.stringify(motionCheckPayload, null, 2)}</pre>
                    )}
                  </section>
                )}

                {activeSection === 'macros' && (
                  <section className="drawer-section">
                    <h3>Macros</h3>
                    <div className="file-toolbar">
                      <input value={macroSearch} onChange={(event) => setMacroSearch(event.target.value)} placeholder="Filter macros" />
                    </div>
                    {privateMacroCount > 0 && (
                      <label className="subtle small macro-private-toggle">
                        <input
                          type="checkbox"
                          checked={showPrivateMacros}
                          onChange={(event) => setShowPrivateMacros(event.target.checked)}
                        />
                        Show {privateMacroCount} private macro{privateMacroCount === 1 ? '' : 's'} (_ prefix)
                      </label>
                    )}
                    {visibleMacros.length === 0 && <div className="subtle">No macros detected.</div>}
                    {macroGroups.map(([category, groupMacros]) => (
                      <div key={category || '__uncategorised'} className="macro-group">
                        {/* Only label a group when the config actually named one —
                            a lone "Uncategorised" header on a stock printer.cfg is noise. */}
                        {category && macroGroups.length > 1 && (
                          <div className="macro-group-title subtle small">{category}</div>
                        )}
                        <div className="macro-grid">
                          {groupMacros.map((macro) => {
                            const paramSpecs = Object.entries(macro.params || {})
                            const expanded = macroExpanded === macro.name
                            return (
                              <div className="macro-row" key={macro.name}>
                                <button
                                  className="macro-button"
                                  aria-expanded={expanded}
                                  // Colour comes from variable_color and is allowlisted
                                  // server-side (hex or bare keyword) before it reaches here.
                                  style={macro.color ? { borderLeft: `3px solid ${macro.color}` } : undefined}
                                  onClick={() => setMacroExpanded(expanded ? null : macro.name)}
                                >
                                  {macro.name}
                                </button>
                                {expanded && (
                                  <div className="macro-params">
                                    {paramSpecs.length === 0 ? (
                                      <input
                                        placeholder="params (optional, e.g. TEMP=230)"
                                        value={macroParams[macro.name] || ''}
                                        onChange={e => setMacroParams(p => ({...p, [macro.name]: e.target.value}))}
                                        onKeyDown={e => { if (e.key === 'Enter') { void runMacroWithParams(macro.name); e.preventDefault() } }}
                                        autoFocus
                                      />
                                    ) : (
                                      paramSpecs.map(([paramName, spec], index) => {
                                        const inputId = `macro-${macro.name}-${paramName}`
                                        const numeric = spec.type === 'int' || spec.type === 'float'
                                        return (
                                          <span className="macro-param-field" key={paramName}>
                                            <label htmlFor={inputId} className="subtle small">{paramName}</label>
                                            <input
                                              id={inputId}
                                              type={numeric ? 'number' : 'text'}
                                              step={spec.type === 'int' ? 1 : spec.type === 'float' ? 0.1 : undefined}
                                              // The default is a placeholder, not a value: leaving
                                              // the field blank omits the param so Klipper applies
                                              // the macro's own default rather than our guess at it.
                                              placeholder={spec.default === null || spec.default === undefined ? spec.type : String(spec.default)}
                                              value={macroTypedParams[macro.name]?.[paramName] ?? ''}
                                              onChange={e => setMacroTypedParams(p => ({
                                                ...p,
                                                [macro.name]: { ...(p[macro.name] || {}), [paramName]: e.target.value },
                                              }))}
                                              onKeyDown={e => { if (e.key === 'Enter') { void runMacroWithParams(macro.name); e.preventDefault() } }}
                                              autoFocus={index === 0}
                                            />
                                          </span>
                                        )
                                      })
                                    )}
                                    {canWrite && <button onClick={() => void runMacroWithParams(macro.name)}>&#9654; Run</button>}
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </section>
                )}

                {activeSection === 'files' && (
                  <section className="drawer-section">
                    <h3>Files</h3>
                    <div className="file-toolbar">
                      <input value={filePath} onChange={(event) => setFilePath(event.target.value)} />
                      <button onClick={() => void reloadFiles(filePath)}>Open path</button>
                    </div>
                    {fileBrowser && (
                      <div style={{display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center'}}>
                        <select value={fileSort} onChange={(e) => setFileSort(e.target.value as typeof fileSort)} style={{flex: 1}}>
                          <option value="name">Sort: Name</option>
                          <option value="size">Sort: Size</option>
                          <option value="modified">Sort: Modified</option>
                          <option value="last_printed">Sort: Last Printed</option>
                        </select>
                        <input type="text" placeholder="Search files..." value={fileSearchTerm} onChange={(e) => setFileSearchTerm(e.target.value)} style={{flex: 1}} />
                      </div>
                    )}
                    <div className="upload-toolbar">
                      <input type="file" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} />
                      <label className="checkbox-line"><input type="checkbox" checked={uploadAutoPrint} onChange={(event) => setUploadAutoPrint(event.target.checked)} /> Auto print</label>
                      {canWrite && <button onClick={() => void uploadSelectedFile()} disabled={!uploadFile || uploadBusy}>{uploadBusy ? 'Uploading…' : 'Upload'}</button>}
                    </div>
                    {fileBrowser && (() => {
                      const filtered = fileBrowser.files.filter(f => f.name.toLowerCase().includes(fileSearchTerm.toLowerCase()))
                      const sorted = [...filtered].sort((a, b) => {
                        if (fileSort === 'name') return a.name.localeCompare(b.name)
                        if (fileSort === 'size') return (b.size ?? 0) - (a.size ?? 0)
                        if (fileSort === 'modified') return new Date(b.modified ?? 0).getTime() - new Date(a.modified ?? 0).getTime()
                        if (fileSort === 'last_printed') {
                          const aTime = (a.metadata as any)?.print_start_time ? new Date((a.metadata as any).print_start_time).getTime() : 0
                          const bTime = (b.metadata as any)?.print_start_time ? new Date((b.metadata as any).print_start_time).getTime() : 0
                          return bTime - aTime
                        }
                        return 0
                      })
                      return (
                        <div className="file-list">
                          {parentPath(fileBrowser.path) && <button className="file-row dir-row" onClick={() => void reloadFiles(parentPath(fileBrowser.path) || 'gcodes')}>..</button>}
                          {fileBrowser.dirs.map((entry) => <button key={entry.path} className="file-row dir-row" onClick={() => void reloadFiles(entry.path)}>{entry.name}/</button>)}
                          {sorted.length === 0 && fileSearchTerm && (
                            <div className="subtle" style={{ textAlign: 'center', padding: '24px 16px' }}>No files match "{fileSearchTerm}"</div>
                          )}
                          {sorted.map((entry) => (
                          <div key={entry.path} className="file-row file-row-flex">
                            <div>
                              <strong>{entry.name}</strong>
                              <div className="subtle small">{formatBytes(entry.size)} • {formatTimestamp(entry.modified)}</div>
                            </div>
                            <div
                              className="file-print-count"
                              title="Times MEMAR has run this file on this machine — completed, failed and cancelled runs all count. Covers only what MEMAR has observed, plus a 30-day import of the printer's own history, so it reads lower than the printer's native job history."
                            >
                              <span className="subtle small">Times printed</span>
                              <strong>{printCounts.get(normalizeJobKey(entry.path)) ?? '—'}</strong>
                            </div>
                            <div className="inline-actions">
                              {canWrite && <button onClick={() => { setDispatchFilename(relativeFilename(entry.path)); void startSelectedFile(relativeFilename(entry.path)) }}>Print</button>}
                              <button onClick={() => void inspectFile(relativeFilename(entry.path))}>Inspect</button>
                            </div>
                          </div>
                        ))}
                        </div>
                      )
                    })()}
                    {selectedFileDetail && (
                      <div className="file-detail-wrapper">
                        <h3>Selected file detail</h3>
                        <FileDetailCard detail={selectedFileDetail} />
                      </div>
                    )}
                  </section>
                )}

                {activeSection === 'settings' && diagnostics && printerSettingsDraft && (
                  <>
                    {/* Current Plan */}
                    <div style={{background:'var(--surface-l2)',border:'1px solid var(--border-default)',borderRadius:8,padding:'16px 20px',marginBottom:16}}>
                      <div style={{fontWeight:600,marginBottom:10,color:'var(--text-primary)'}}>Current Plan</div>
                      {mySubscription && mySubscription.status !== 'none' ? (
                        <>
                          <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:8}}>
                            <span style={{background:'#2563eb',color:'#fff',borderRadius:4,padding:'2px 10px',fontWeight:700,fontSize:'0.82rem',letterSpacing:'0.05em'}}>{mySubscription.tier.toUpperCase()}</span>
                            <span style={{
                              color: mySubscription.cancel_at_period_end ? 'var(--color-warning)' : mySubscription.status === 'active' ? 'var(--color-success)' : 'var(--color-danger)',
                              fontSize:'0.85rem',fontWeight:500
                            }}>
                              {mySubscription.cancel_at_period_end ? '⚠ Cancels at period end' : mySubscription.status === 'active' ? '✓ Active' : '✗ Expired'}
                            </span>
                          </div>
                          {mySubscription.expires_at && (
                            <div style={{color:'var(--text-secondary)',fontSize:'0.82rem',marginBottom:6}}>
                              Expires: {new Date(mySubscription.expires_at).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}
                            </div>
                          )}
                          {mySubscription.device_limit && (
                            <div style={{color:'var(--text-secondary)',fontSize:'0.82rem',marginBottom:10}}>Up to {mySubscription.device_limit} devices</div>
                          )}
                          {mySubscription.status === 'active' && !mySubscription.cancel_at_period_end && (
                            <>
                              {showCancelConfirm && (
                                <ConfirmDialog
                                  message="Cancel your subscription? It stays active until the end of the billing period."
                                  onConfirm={async () => {
                                    setShowCancelConfirm(false)
                                    setCancelSubLoading(true)
                                    try {
                                      const r = await apiFetch('/api/billing/my-subscription', {method:'DELETE'})
                                      if (r.ok) setMySubscription(s => s ? {...s, cancel_at_period_end:true} : s)
                                      else pushToast('Failed to cancel subscription', 'error')
                                    } catch { pushToast('Failed to cancel subscription', 'error') }
                                    finally { setCancelSubLoading(false) }
                                  }}
                                  onCancel={() => setShowCancelConfirm(false)}
                                />
                              )}
                              <button
                                style={{background:'transparent',border:'1px solid var(--color-danger)',color:'var(--color-danger)',borderRadius:4,padding:'5px 14px',cursor:'pointer',fontSize:'0.82rem'}}
                                disabled={cancelSubLoading}
                                aria-label="Cancel subscription"
                                onClick={() => setShowCancelConfirm(true)}
                              >{cancelSubLoading ? 'Cancelling...' : 'Cancel Subscription'}</button>
                            </>
                          )}
                        </>
                      ) : (
                        <div style={{color:'var(--text-secondary)',fontSize:'0.85rem'}}>Free tier — no active subscription.{userRole === 'admin' && <> <button style={{background:'none',border:'none',color:'var(--accent-solid)',cursor:'pointer',padding:0,textDecoration:'underline'}} onClick={() => setShowUpgradeModal(true)}>Upgrade</button></>}</div>
                      )}
                    </div>

                    <section className="drawer-section">
                      <h3>Quick settings</h3>
                      <div className="preset-row drawer-preset-row">
                        {[0.25, 0.4, 0.6, 0.8, 1.0].map((preset) => <button key={preset} onClick={() => { setSettingsNozzle(String(preset)); updatePrinterSettingsDraft({ nozzleDiameter: preset.toFixed(2) }) }}>{preset.toFixed(2)} mm</button>)}
                      </div>
                      <div className="settings-grid two-col">
                        <label>
                          <span>Printer name</span>
                          <input value={printerSettingsDraft.name} onChange={(event) => updatePrinterSettingsDraft({ name: event.target.value })} />
                        </label>
                        <label>
                          <span>Configured nozzle (mm)</span>
                          <input type="number" step="0.01" value={printerSettingsDraft.nozzleDiameter} onChange={(event) => { setSettingsNozzle(event.target.value); updatePrinterSettingsDraft({ nozzleDiameter: event.target.value }) }} />
                        </label>
                        <label>
                          <span>Filament diameter (mm)</span>
                          <input type="number" step="0.01" placeholder="1.75" value={printerSettingsDraft.filamentDiameterMm} onChange={(event) => updatePrinterSettingsDraft({ filamentDiameterMm: event.target.value })} />
                        </label>
                        <label>
                          <span>Wire per job (mm) — EDM only</span>
                          <input type="number" step="1" placeholder="e.g. 50000" value={printerSettingsDraft.wireUsedMmPerJob} onChange={(event) => updatePrinterSettingsDraft({ wireUsedMmPerJob: event.target.value })} />
                        </label>
                      </div>
                      <div className="inline-actions settings-actions-row">
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.enabled} onChange={(event) => updatePrinterSettingsDraft({ enabled: event.target.checked })} /> Enabled</label>
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.maintenanceDue} onChange={(event) => updatePrinterSettingsDraft({ maintenanceDue: event.target.checked })} /> Maintenance due</label>
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.maintenanceLockout} onChange={(event) => updatePrinterSettingsDraft({ maintenanceLockout: event.target.checked })} /> Maintenance lockout</label>
                        {canWrite && <button onClick={() => void saveNozzleDiameter()}>Save nozzle only</button>}
                        {canWrite && <button onClick={() => void savePrinterSettings()}>Save printer settings</button>}
                      </div>
                      <div className="subtle small">Nozzle changes should now propagate to the card, profile label, current-file compatibility view, and saved config.</div>
                      <div className="action-message" aria-live="polite" aria-atomic="true">{printerSettingsMessage}</div>
                    </section>

                    <section className="drawer-section">
                      <h3>Identity and material</h3>
                      <div className="settings-grid three-col">
                        <label>
                          <span>Tags</span>
                          <input value={printerSettingsDraft.tagsText} onChange={(event) => updatePrinterSettingsDraft({ tagsText: event.target.value })} placeholder="klipper, core, 0.6nozzle" />
                        </label>
                        <label>
                          <span>Profile</span>
                          <input value={printerSettingsDraft.compatibilityProfile} onChange={(event) => updatePrinterSettingsDraft({ compatibilityProfile: event.target.value })} placeholder="octopus-350" />
                        </label>
                        <label>
                          <span>Supported materials</span>
                          <input value={printerSettingsDraft.supportedMaterialsText} onChange={(event) => updatePrinterSettingsDraft({ supportedMaterialsText: event.target.value })} placeholder="PLA, PETG, ASA" />
                        </label>
                        <label>
                          <span>Current material</span>
                          <input value={printerSettingsDraft.currentMaterial} onChange={(event) => updatePrinterSettingsDraft({ currentMaterial: event.target.value })} />
                        </label>
                        <label>
                          <span>Current spool</span>
                          <input value={printerSettingsDraft.currentSpoolName} onChange={(event) => updatePrinterSettingsDraft({ currentSpoolName: event.target.value })} />
                        </label>
                        <label>
                          <span>Spool remaining (g)</span>
                          <input type="number" value={printerSettingsDraft.spoolRemainingG} onChange={(event) => updatePrinterSettingsDraft({ spoolRemainingG: event.target.value })} />
                        </label>
                        <label>
                          <span>Full spool capacity (g)</span>
                          <input type="number" value={printerSettingsDraft.spoolCapacityG} onChange={(event) => updatePrinterSettingsDraft({ spoolCapacityG: event.target.value })} placeholder="1000" />
                        </label>
                      </div>
                    </section>

                    <section className="drawer-section">
                      <h3>Hardware and behavior</h3>
                      <div className="settings-grid three-col">
                        <label>
                          <span>Build volume X</span>
                          <input type="number" value={printerSettingsDraft.buildVolumeX} onChange={(event) => updatePrinterSettingsDraft({ buildVolumeX: event.target.value })} />
                        </label>
                        <label>
                          <span>Build volume Y</span>
                          <input type="number" value={printerSettingsDraft.buildVolumeY} onChange={(event) => updatePrinterSettingsDraft({ buildVolumeY: event.target.value })} />
                        </label>
                        <label>
                          <span>Build volume Z</span>
                          <input type="number" value={printerSettingsDraft.buildVolumeZ} onChange={(event) => updatePrinterSettingsDraft({ buildVolumeZ: event.target.value })} />
                        </label>
                        <label>
                          <span>Safe nozzle max (C)</span>
                          <input type="number" value={printerSettingsDraft.safeNozzleMaxC} onChange={(event) => updatePrinterSettingsDraft({ safeNozzleMaxC: event.target.value })} />
                        </label>
                        <label>
                          <span>Safe bed max (C)</span>
                          <input type="number" value={printerSettingsDraft.safeBedMaxC} onChange={(event) => updatePrinterSettingsDraft({ safeBedMaxC: event.target.value })} />
                        </label>
                        <label>
                          <span>Timelapse dir</span>
                          <input value={printerSettingsDraft.timelapseDir} onChange={(event) => updatePrinterSettingsDraft({ timelapseDir: event.target.value })} />
                        </label>
                      </div>
                      <div className="inline-actions settings-actions-row">
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.probe} onChange={(event) => updatePrinterSettingsDraft({ probe: event.target.checked })} /> Probe installed</label>
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.filamentSensor} onChange={(event) => updatePrinterSettingsDraft({ filamentSensor: event.target.checked })} /> Filament sensor</label>
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.webcamExpected} onChange={(event) => updatePrinterSettingsDraft({ webcamExpected: event.target.checked })} /> Webcam expected</label>
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.jogEnabled} onChange={(event) => updatePrinterSettingsDraft({ jogEnabled: event.target.checked })} /> Jog enabled</label>
                        <label className="checkbox-line"><input type="checkbox" checked={printerSettingsDraft.motionCheckRequired} onChange={(event) => updatePrinterSettingsDraft({ motionCheckRequired: event.target.checked })} /> Motion check required</label>
                      </div>
                    </section>

                    <section className="drawer-section">
                      <h3>Maintenance</h3>
                      <div className="settings-grid three-col">
                        <label>
                          <span>Maintenance state</span>
                          <input value={printerSettingsDraft.maintenanceState} onChange={(event) => updatePrinterSettingsDraft({ maintenanceState: event.target.value })} placeholder="ok / due / service" />
                        </label>
                        <label>
                          <span>Next service due</span>
                          <input value={printerSettingsDraft.nextServiceDue} onChange={(event) => updatePrinterSettingsDraft({ nextServiceDue: event.target.value })} placeholder="2026-05-01" />
                        </label>
                        <label>
                          <span>Last service</span>
                          <input value={printerSettingsDraft.lastServiceAt} onChange={(event) => updatePrinterSettingsDraft({ lastServiceAt: event.target.value })} placeholder="2026-04-10" />
                        </label>
                        <label>
                          <span>Interval hours</span>
                          <input type="number" value={printerSettingsDraft.maintenanceIntervalHours} onChange={(event) => updatePrinterSettingsDraft({ maintenanceIntervalHours: event.target.value })} />
                        </label>
                        <label>
                          <span>Interval jobs</span>
                          <input type="number" value={printerSettingsDraft.maintenanceIntervalJobs} onChange={(event) => updatePrinterSettingsDraft({ maintenanceIntervalJobs: event.target.value })} />
                        </label>
                        <label>
                          <span>Interval filament (g)</span>
                          <input type="number" value={printerSettingsDraft.maintenanceIntervalFilamentG} onChange={(event) => updatePrinterSettingsDraft({ maintenanceIntervalFilamentG: event.target.value })} />
                        </label>
                      </div>
                      <div className="settings-grid two-col">
                        <label>
                          <span>Operator notes</span>
                          <textarea value={printerSettingsDraft.notesText} onChange={(event) => updatePrinterSettingsDraft({ notesText: event.target.value })} rows={4} />
                        </label>
                        <label>
                          <span>Maintenance notes</span>
                          <textarea value={printerSettingsDraft.maintenanceNotesText} onChange={(event) => updatePrinterSettingsDraft({ maintenanceNotesText: event.target.value })} rows={4} />
                        </label>
                      </div>
                    </section>

                    <details className="drawer-section collapsible-panel" open>
                      <summary>UI and integrations</summary>
                      <div className="details-body">
                        <div className="settings-grid two-col">
                          <label>
                            <span>UI button label</span>
                            <input value={printerSettingsDraft.uiLabel} onChange={(event) => updatePrinterSettingsDraft({ uiLabel: event.target.value })} />
                          </label>
                          <label>
                            <span>Camera URL</span>
                            <input value={printerSettingsDraft.cameraUrl} onChange={(event) => updatePrinterSettingsDraft({ cameraUrl: event.target.value })} />
                          </label>
                        </div>
                        <div className="settings-targets">
                          {printerSettingsDraft.uiTargets.map((target, index) => (
                            <div key={index} className="settings-target-row">
                              <input value={target.label} onChange={(event) => updateUiTargetDraft(index, { label: event.target.value })} placeholder="Label" />
                              <input value={target.provider} onChange={(event) => updateUiTargetDraft(index, { provider: event.target.value })} placeholder="Provider" />
                              <input value={target.url} onChange={(event) => updateUiTargetDraft(index, { url: event.target.value })} placeholder="URL" />
                              <select value={target.mode} onChange={(event) => updateUiTargetDraft(index, { mode: event.target.value as 'direct' | 'bootstrap' })}>
                                <option value="direct">direct</option>
                                <option value="bootstrap">bootstrap</option>
                              </select>
                              <label className="checkbox-line compact-check"><input type="checkbox" checked={target.primary} onChange={(event) => setPrinterSettingsDraft((current) => {
                                if (!current) return current
                                const uiTargets = current.uiTargets.map((item, itemIndex) => ({ ...item, primary: itemIndex === index ? event.target.checked : false }))
                                if (uiTargets.length > 0 && !uiTargets.some((item) => item.primary)) uiTargets[0] = { ...uiTargets[0], primary: true }
                                return { ...current, uiTargets }
                              })} /> Primary</label>
                              <button onClick={() => removeUiTargetDraft(index)}>Remove</button>
                            </div>
                          ))}
                          <button onClick={addUiTargetDraft}>Add UI target</button>
                        </div>
                      </div>
                    </details>

                    <details className="drawer-section collapsible-panel">
                      <summary>Advanced connection settings</summary>
                      <div className="details-body settings-grid two-col">
                        <label>
                          <span>Base URL</span>
                          <input value={printerSettingsDraft.baseUrl} onChange={(event) => updatePrinterSettingsDraft({ baseUrl: event.target.value })} />
                        </label>
                        <label>
                          <span>WebSocket URL</span>
                          <input value={printerSettingsDraft.wsUrl} onChange={(event) => updatePrinterSettingsDraft({ wsUrl: event.target.value })} />
                        </label>
                        <label>
                          <span>Auth mode</span>
                          <input value={printerSettingsDraft.authMode} onChange={(event) => updatePrinterSettingsDraft({ authMode: event.target.value })} />
                        </label>
                        <label>
                          <span>Serial</span>
                          <input value={printerSettingsDraft.serial} onChange={(event) => updatePrinterSettingsDraft({ serial: event.target.value })} placeholder="Bambu printer serial (MQTT)" />
                        </label>
                        <label>
                          <span>Access code{printerSettingsDraft.apiKeySet ? ' (configured)' : ''}</span>
                          <input type="password" autoComplete="new-password" value={printerSettingsDraft.apiKey} disabled={printerSettingsDraft.apiKeyClear} onChange={(event) => updatePrinterSettingsDraft({ apiKey: event.target.value })} placeholder={printerSettingsDraft.apiKeyClear ? 'Will be removed on save' : printerSettingsDraft.apiKeySet ? 'Leave blank to keep current' : 'Bambu LAN access code / API key'} />
                        </label>
                        {printerSettingsDraft.apiKeySet && (
                          <label className="checkbox-line">
                            <input type="checkbox" checked={printerSettingsDraft.apiKeyClear} onChange={(event) => updatePrinterSettingsDraft({ apiKeyClear: event.target.checked })} /> Clear access code
                          </label>
                        )}
                        <label>
                          <span>Fluidd fallback URL</span>
                          <input value={printerSettingsDraft.fluiddUrl} onChange={(event) => updatePrinterSettingsDraft({ fluiddUrl: event.target.value })} />
                        </label>
                      </div>
                    </details>

                    <section className="drawer-section">
                      <h3>Macro pins</h3>
                      <div className="subtle small" style={{ marginBottom: 8 }}>Pinned macros appear first on the card with a star highlight.</div>
                      {!cardMacros[detailsPrinterId] ? (
                        <button onClick={() => void loadCardMacros(detailsPrinterId, true)}>Load macros</button>
                      ) : cardMacros[detailsPrinterId].length === 0 ? (
                        <div className="subtle small">No macros detected for this printer.</div>
                      ) : (
                        <div className="settings-grid two-col">
                          {cardMacros[detailsPrinterId].map(macro => (
                            <label key={macro.name} className="checkbox-line">
                              <input type="checkbox"
                                checked={(cardMacroPins[detailsPrinterId] || []).includes(macro.name)}
                                onChange={() => toggleMacroPin(detailsPrinterId, macro.name)}
                              />
                              {macro.name}
                            </label>
                          ))}
                        </div>
                      )}
                    </section>
                  </>
                )}

                {activeSection === 'history' && history && (
                  <>
                    <section className="drawer-section">
                      <h3>History totals</h3>
                      <div className="kv-grid">
                        <div><span>Total jobs</span><strong>{history.totals.total_jobs}</strong></div>
                        <div><span>Total print time</span><strong>{formatDuration(history.totals.total_print_time)}</strong></div>
                        <div><span>Total work time</span><strong>{formatDuration(history.totals.total_time)}</strong></div>
                        <div><span>Longest print</span><strong>{formatDuration(history.totals.longest_print)}</strong></div>
                        <div><span>Longest job</span><strong>{formatDuration(history.totals.longest_job)}</strong></div>
                        <div><span>Filament used</span><strong>{formatMillimeters(history.totals.total_filament_used)}</strong></div>
                      </div>
                    </section>
                    <section className="drawer-section">
                      <h3>Recent jobs</h3>
                      <div style={{display: 'flex', gap: 8, marginBottom: 12}}>
                        <select value={historyStatusFilter} onChange={(e) => setHistoryStatusFilter(e.target.value)} style={{flex: 1}}>
                          <option value="all">All statuses</option>
                          <option value="completed">Completed only</option>
                          <option value="failed">Failed only</option>
                          <option value="cancelled">Cancelled only</option>
                        </select>
                        <select value={historySort} onChange={(e) => setHistorySort(e.target.value as typeof historySort)} style={{flex: 1}}>
                          <option value="date">Sort: Date</option>
                          <option value="filament">Sort: Filament</option>
                          <option value="duration">Sort: Duration</option>
                        </select>
                      </div>
                      <div className="history-list">
                        {history.jobs.length === 0 && <div className="subtle">No history yet.</div>}
                        {(() => {
                          const filtered = history.jobs.filter(job => historyStatusFilter === 'all' || job.status === historyStatusFilter)
                          const sorted = [...filtered].sort((a, b) => {
                            if (historySort === 'date') return (b.end_time ?? b.start_time ?? 0) - (a.end_time ?? a.start_time ?? 0)
                            if (historySort === 'filament') return (b.filament_used ?? 0) - (a.filament_used ?? 0)
                            if (historySort === 'duration') return (b.print_duration ?? 0) - (a.print_duration ?? 0)
                            return 0
                          })
                          return sorted.map((job, idx) => (
                          <div key={`${job.job_id ?? idx}-${job.filename ?? idx}`} className="history-row">
                            <div>
                              <strong>{job.filename || 'Unknown file'}</strong>
                              <div className="subtle small">{job.status || 'unknown'} • print {formatDuration(job.print_duration)} • total {formatDuration(job.total_duration)} • {formatMillimeters(job.filament_used)}</div>
                            </div>
                            <div className="inline-actions" style={{display: 'flex', gap: 6, alignItems: 'center', marginLeft: 'auto'}}>
                              {canWrite && job.filename && job.exists !== false && <button onClick={() => { setDispatchFilename(job.filename ?? ''); void startSelectedFile(job.filename ?? '') }} style={{whiteSpace: 'nowrap'}}>Reprint</button>}
                              <div className="subtle small" style={{whiteSpace: 'nowrap'}}>{formatTimestamp(job.end_time || job.start_time)}</div>
                            </div>
                          </div>
                        ))
                        })()}
                      </div>
                    </section>
                  </>
                )}

                {activeSection === 'webcams' && (
                  <section className="drawer-section">
                    <h3>Webcams</h3>
                    <div className="webcam-grid">
                      {webcams.length === 0 && <div className="subtle">No webcams reported by Moonraker.</div>}
                      {webcams.map((cam) => (
                        <div key={cam.uid} className="webcam-card">
                          <div className="webcam-title">{cam.name}</div>
                          <WebcamImage printerId={detailsPrinterId ?? ''} camUid={cam.uid} snapTs={snapTs} alt={cam.name} />
                          <div className="subtle small">{cam.location || cam.service || 'camera'}</div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {activeSection === 'dryrun' && (
                  <>
                    <section className="drawer-section">
                      <h3>Action dry-run</h3>
                      <div className="file-toolbar">
                        <select value={drawerDryRunAction} onChange={(event) => setDrawerDryRunAction(event.target.value)}>
                          {['home', 'cooldown', 'motors_off', 'pause', 'resume', 'cancel', 'firmware_restart', 'macro', 'temperature'].map((action) => <option key={action} value={action}>{labelForAction(action)}</option>)}
                        </select>
                        <button onClick={() => void runDrawerDryRun()}>Run dry-run</button>
                      </div>
                      {dryRunPayload && (
                        <DryRunMatrix results={dryRunPayload.results} />
                      )}
                    </section>
                    {canWrite && (
                    <section className="drawer-section">
                      <h3>Motion check</h3>
                      <div className="file-toolbar">
                        <select value={motionIntent} onChange={(event) => setMotionIntent(event.target.value as 'home' | 'jog' | 'park' | 'macro' | 'mesh' | 'unknown')}>
                          {['home', 'jog', 'park', 'macro', 'mesh', 'unknown'].map((intent) => <option key={intent} value={intent}>{capitalize(intent)}</option>)}
                        </select>
                        <button onClick={() => void runMotionCheckNow()}>Run motion check</button>
                      </div>
                      {motionCheckPayload && (
                        <pre className="log-box">{JSON.stringify(motionCheckPayload, null, 2)}</pre>
                      )}
                    </section>
                    )}
                    <section className="drawer-section">
                      <h3>Dispatch preflight</h3>
                      <div className="temp-grid">
                        <label>
                          <span>Filename</span>
                          <input value={dispatchFilename} onChange={(event) => setDispatchFilename(event.target.value)} placeholder="gcodes/example.gcode" />
                        </label>
                        <label>
                          <span>Material</span>
                          <input value={dispatchMaterial} onChange={(event) => setDispatchMaterial(event.target.value)} placeholder="PLA" />
                        </label>
                        <label>
                          <span>Nozzle mm</span>
                          <input type="number" step="0.05" value={dispatchNozzle} onChange={(event) => setDispatchNozzle(event.target.value)} />
                        </label>
                      </div>
                      <button onClick={() => void runDispatchDryRunNow()}>Run dispatch dry-run</button>
                      {dispatchDryRunPayload && (
                        <DispatchMatrix payload={dispatchDryRunPayload} />
                      )}
                    </section>
                  </>
                )}

                {activeSection === 'timelapse' && (
                  <section className="drawer-section">
                    <h3>Timelapse hooks</h3>
                    {timelapse === null && <div className="subtle">Could not fetch timelapse status.</div>}
                    {timelapse !== null && !timelapse.configured && <div className="subtle">No timelapse directory is configured for this printer yet.</div>}
                    {timelapse?.configured && (
                      <>
                        <div className="subtle">Source directory: {timelapse.source_dir || '—'}</div>
                        <div className="file-list timelapse-list">
                          {timelapse.entries.length === 0 && <div className="subtle">No recent timelapse artifacts found.</div>}
                          {timelapse.entries.map((entry) => (
                            <div key={entry.id} className="file-row file-row-flex">
                              <div style={{flex: 1}}>
                                <strong>{entry.name}</strong>
                                <div className="subtle small">{entry.kind} • {formatBytes(entry.size)} • {formatTimestamp(entry.modified)}</div>
                              </div>
                              <TimelapseMedia printerId={detailsPrinterId ?? ''} name={entry.name} showVideo={entry.kind === 'video'} />
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </section>
                )}

                                {activeSection === 'console' && canWrite && (
                                  <section className="drawer-section">
                                    <h3>{isCncMachine(currentPrinter?.capability.machine_type) ? 'MDI' : 'G-code console'}</h3>
                                    {detailsPrinterId && (
                      <>
                        <div
                          className="console-log"
                          style={{height: 260, overflowY: 'auto', background: 'var(--bg-2, #1a1a1a)', borderRadius: 4, padding: '8px 10px', fontFamily: 'monospace', fontSize: 12, marginBottom: 8}}
                          ref={consoleScrollRef}
                        >
                          {consoleLog.length === 0 && <div className="subtle">No history. Type a command below.</div>}
                          {consoleLog.map((entry, i) => (
                            <div key={i} style={{color: entry.type === 'sent' ? 'var(--text-secondary)' : entry.type === 'error' ? 'var(--color-danger)' : 'var(--text-primary)', marginBottom: 2}}>
                              {entry.type === 'sent' ? '> ' : entry.type === 'error' ? '! ' : ''}{entry.text}
                            </div>
                          ))}
                        </div>
                        <div className="file-toolbar">
                          <input
                            style={{flex: 1, fontFamily: 'monospace'}}
                            value={consoleInput}
                            onChange={(e) => {
                              setConsoleInput(e.target.value)
                              // Typing ends any TAB cycle, so the next TAB
                              // starts fresh from the new prefix.
                              consoleCycleRef.current = NO_COMPLETION_CYCLE
                            }}
                            onKeyDown={(e) => {
                              const next = handleConsoleKey(
                                e,
                                { input: consoleInput, history: consoleHistory, historyIndex: consoleHistoryIndex, cycle: consoleCycleRef.current },
                                macroNames,
                              )
                              if (next) {
                                setConsoleInput(next.input)
                                setConsoleHistoryIndex(next.historyIndex)
                                consoleCycleRef.current = next.cycle
                                return
                              }
                              if (e.key === 'Enter' && consoleInput.trim()) void sendGcodeCommand(consoleInput)
                            }}
                            placeholder={isCncMachine(currentPrinter?.capability.machine_type) ? 'G0 X0 F200' : 'G28 / M104 S200 / BED_MESH_CALIBRATE…'}
                            disabled={consoleSending}
                            aria-label="G-code command"
                          />
                          <button onClick={() => void sendGcodeCommand(consoleInput)} disabled={consoleSending || !consoleInput.trim()}>
                            Send
                          </button>
                          <button onClick={() => setConsoleLog([])} title="Clear log">Clear</button>
                        </div>
                        <div className="subtle small" style={{marginTop: 4}}>Enter to send &bull; ↑/↓ for previous commands &bull; Tab to complete</div>
                      </>
                    )}
                  </section>
                )}

                {activeSection === 'bedmesh' && canWrite && (
                  <section className="drawer-section">
                    <h3>Bed mesh</h3>
                    <div className="file-toolbar" style={{marginBottom: 8}}>
                      <button onClick={() => void loadBedMesh()}>Refresh</button>
                      <button onClick={() => void (async () => { await apiFetch(`/api/printers/${detailsPrinterId}/macros/BED_MESH_CALIBRATE`, {method: 'POST'}); if (bedMeshTimerRef.current) clearTimeout(bedMeshTimerRef.current); bedMeshTimerRef.current = setTimeout(() => void loadBedMesh(), 3000) })()}>Calibrate</button>
                    </div>
                    {bedMesh === null && <div className="subtle">Loading…</div>}
                    {bedMesh !== null && !bedMesh.supported && (
                      <div className="subtle">Bed mesh not available. Ensure <code>[bed_mesh]</code> is in printer.cfg and a mesh has been calibrated.</div>
                    )}
                    {bedMesh?.supported && <BedMeshPanel data={bedMesh} />}
                  </section>
                )}
                {['jog', 'console', 'bedmesh'].includes(activeSection) && !canWrite && (
                  <section className="drawer-section">
                    <h3>{capitalize(activeSection)}</h3>
                    <div className="subtle">This control requires an operator or admin role. You have read-only access.</div>
                  </section>
                )}
                {activeSection === 'queue' && detailsPrinterId && (
                  <QueuePanel printerId={detailsPrinterId} canWrite={canWrite} />
                )}
                {activeSection === 'maintenance' && detailsPrinterId && (
                  <MaintenancePanel printerId={detailsPrinterId} canWrite={canWrite} onDone={() => { void apiFetch(`/api/printers/${detailsPrinterId}/diagnostics`).then(r => r.ok ? r.json() : null).then(d => { if (d) setDiagnostics(d as Diagnostics) }) }} />
                )}
                {activeSection === 'health' && detailsPrinterId && (
                  <HealthPanel printerId={detailsPrinterId} />
                )}
                {activeSection === 'cnc' && detailsPrinterId && (
                  <CNCMetricsPanel deviceId={detailsPrinterId} />
                )}
                {activeSection === 'coolant' && detailsPrinterId && (
                  <CoolantMetricsPanel deviceId={detailsPrinterId} />
                )}
                {activeSection === 'analytics' && currentMetric && (
                  <section className="drawer-section">
                    <h3>Device Analytics</h3>
                    <div className="kv-grid" style={{marginBottom: 20}}>
                      <div><span>Total Jobs</span><strong>{currentMetric.completed_jobs + currentMetric.failed_jobs + currentMetric.cancelled_jobs}</strong></div>
                      <div><span>Success Rate</span><strong>{currentMetric.success_rate != null ? `${currentMetric.success_rate.toFixed(1)}%` : '—'}</strong></div>
                      <div><span>Completed</span><strong>{currentMetric.completed_jobs}</strong></div>
                      <div><span>Failed</span><strong>{currentMetric.failed_jobs}</strong></div>
                      <div><span>Cancelled</span><strong>{currentMetric.cancelled_jobs}</strong></div>
                      <div><span>OEE</span><strong>{(() => { const oee = oeeByDevice.get(detailsPrinterId ?? ''); return oee?.oee != null ? `${(oee.oee * 100).toFixed(1)}%` : '—' })()}</strong></div>
                    </div>
                    <div className="subtle" style={{fontSize: '0.85rem'}}>Data from last 24 hours</div>
                  </section>
                )}

                {activeSection === 'system-settings' && (
                  <SystemSettingsDrawer printerId={detailsPrinterId} currentPrinter={currentPrinter} canWrite={canWrite} onMessage={setDrawerMsg} token={accessToken || ''} username={currentUsername} />
                )}
                </motion.div>
              </AnimatePresence>
            )}
          </aside>
        </div>
      )}

      {/* Fleet tools modal */}
      {fleetToolsOpen && <FleetToolsModal onClose={() => setFleetToolsOpen(false)} canWrite={canWrite} />}

      {/* Add device modal */}
      {addDeviceOpen && (
        <div className="modal-overlay" onClick={() => setAddDeviceOpen(false)}>
          <div className="modal-content" role="dialog" aria-modal="true" aria-label="Add device" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setAddDeviceOpen(false)} aria-label="Close add device" autoFocus>✕</button>
            <h2>Add device</h2>
            <div className="settings-grid">
              <label>
                <span>Protocol</span>
                <select value={addDeviceDraft.protocol} onChange={(e) => updateAddDeviceDraft({ protocol: e.target.value })}>
                  {DEVICE_PROTOCOLS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </select>
              </label>
              <label>
                <span>Device ID</span>
                <input value={addDeviceDraft.id} onChange={(e) => updateAddDeviceDraft({ id: e.target.value })} placeholder="unique-id (e.g. bambu-x1c-1)" />
              </label>
              <label>
                <span>Name</span>
                <input value={addDeviceDraft.name} onChange={(e) => updateAddDeviceDraft({ name: e.target.value })} placeholder="Display name" />
              </label>
              <label>
                <span>{addDeviceDraft.protocol === 'bambu_mqtt' ? 'Printer LAN IP' : 'Base URL'}</span>
                <input value={addDeviceDraft.base_url} onChange={(e) => updateAddDeviceDraft({ base_url: e.target.value })} placeholder={addDeviceDraft.protocol === 'bambu_mqtt' ? '192.168.1.50' : 'http://host:port'} />
              </label>
              {addDeviceDraft.protocol === 'bambu_mqtt' && (
                <label>
                  <span>Serial</span>
                  <input value={addDeviceDraft.serial} onChange={(e) => updateAddDeviceDraft({ serial: e.target.value })} placeholder="Bambu printer serial" />
                </label>
              )}
              {PROTOCOLS_WITH_API_KEY.has(addDeviceDraft.protocol) && (
                <label>
                  <span>{addDeviceDraft.protocol === 'bambu_mqtt' ? 'Access code' : 'API key'}</span>
                  <input type="password" autoComplete="new-password" value={addDeviceDraft.apiKey} onChange={(e) => updateAddDeviceDraft({ apiKey: e.target.value })} placeholder="optional" />
                </label>
              )}
              {addDeviceDraft.protocol === 'mqtt' && (
                <>
                  <label>
                    <span>MQTT topic</span>
                    <input value={addDeviceDraft.mqttTopic} onChange={(e) => updateAddDeviceDraft({ mqttTopic: e.target.value })} placeholder="machines/{id}/status" />
                  </label>
                  <label>
                    <span>Field mapping (JSON)</span>
                    <textarea rows={3} value={addDeviceDraft.mqttFieldMapping} onChange={(e) => updateAddDeviceDraft({ mqttFieldMapping: e.target.value })} placeholder='{"state":"st","progress":"pct"}' />
                  </label>
                </>
              )}
              <label className="checkbox-line">
                <input type="checkbox" checked={addDeviceDraft.enabled} onChange={(e) => updateAddDeviceDraft({ enabled: e.target.checked })} /> Enabled
              </label>
            </div>
            {addDeviceMessage && <p className="subtle small" role="status">{addDeviceMessage}</p>}
            <div className="modal-actions">
              <button className="btn btn-secondary" onClick={() => setAddDeviceOpen(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={() => { void addDevice() }} disabled={addDeviceBusy}>{addDeviceBusy ? 'Adding…' : 'Add device'}</button>
            </div>
          </div>
        </div>
      )}

      {kioskMode && (
        <button className="kiosk-exit" onClick={() => setKioskMode(false)} aria-label="Exit kiosk mode">Exit kiosk ✕</button>
      )}

      {/* Fleet analytics modal — opened from the summary cards */}
      {analyticsOpen && (
        <div className="modal-overlay" onClick={() => setAnalyticsOpen(false)}>
          <div className="modal-content modal-analytics" role="dialog" aria-modal="true" aria-label="Fleet analytics" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setAnalyticsOpen(false)} aria-label="Close analytics" autoFocus>✕</button>
            <React.Suspense fallback={<div className="subtle small">Loading analytics…</div>}><AnalyticsDashboard /></React.Suspense>
          </div>
        </div>
      )}

      {/* Service & consumables drill-down — opened from the Consumables card */}
      {serviceOpen && <ServiceModal
        printers={fleet.printers}
        onClose={() => setServiceOpen(false)}
        canAct={userRole === 'admin' || userRole === 'operator'}
        onServiced={(id) => setFleet((f) => ({ ...f, printers: f.printers.map((p) => {
          if (p.id !== id) return p
          const ih = p.capability.maintenance_interval_hours
          const next = ih && ih > 0 ? new Date(Date.now() + ih * 3600 * 1000).toISOString().slice(0, 10) : null
          const todayStr = new Date().toISOString().slice(0, 10)
          return { ...p, capability: { ...p.capability, maintenance_due: false, last_service_at: todayStr, next_service_due: next } }
        }) }))}
      />}

      {/* Upgrade Modal */}
      {showUpgradeModal && (
        <div className="modal-overlay" onClick={() => setShowUpgradeModal(false)}>
          <div className="modal-content" role="dialog" aria-modal="true" aria-label="Upgrade license" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setShowUpgradeModal(false)} aria-label="Close upgrade dialog">✕</button>
            <h2>Upgrade Your License</h2>

            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <button
                type="button"
                aria-label="Plans tab"
                disabled={upgradeModalTab === 'plans'}
                onClick={() => setUpgradeModalTab('plans')}
              >Plans</button>
              <button
                type="button"
                aria-label="Billing history tab"
                disabled={upgradeModalTab === 'history'}
                onClick={() => setUpgradeModalTab('history')}
              >Billing History</button>
            </div>

            {upgradeModalTab === 'history' && (
              <div>
                {invoicesLoading ? (
                  <div style={{ color: 'var(--text-secondary)', fontSize: 13, padding: 8 }}>Loading…</div>
                ) : invoices.length === 0 ? (
                  <div style={{ color: 'var(--text-secondary)', fontSize: 13, padding: 8 }}>No invoices found.</div>
                ) : (
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          {['Date', 'Amount', 'Status', 'Links'].map((h) => (
                            <th key={h} style={{ textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--border-default)' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {invoices.map((inv) => (
                          <tr key={inv.id} style={{ borderBottom: '1px solid var(--border-default)' }}>
                            <td style={{ padding: '5px 8px' }}>{new Date(inv.created * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</td>
                            <td style={{ padding: '5px 8px', fontFamily: 'monospace' }}>{(inv.amount_paid / 100).toFixed(2)} {inv.currency.toUpperCase()}</td>
                            <td style={{ padding: '5px 8px', color: inv.status === 'paid' ? 'var(--color-success)' : inv.status === 'open' ? 'var(--color-warning)' : 'var(--color-danger)' }}>{inv.status}</td>
                            <td style={{ padding: '5px 8px', display: 'flex', gap: 6 }}>
                              {inv.hosted_invoice_url && (
                                <a href={inv.hosted_invoice_url} target="_blank" rel="noreferrer" aria-label="View invoice" style={{ fontSize: 12, color: 'var(--accent-solid)' }}>View</a>
                              )}
                              {inv.invoice_pdf && (
                                <a href={inv.invoice_pdf} target="_blank" rel="noreferrer" aria-label="Download invoice PDF" style={{ fontSize: 12, color: 'var(--accent-solid)' }}>PDF</a>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {upgradeModalTab === 'plans' && checkoutStatus === 'success' && (
              <div className="checkout-success-banner" role="alert">
                <div>✓ Payment successful! Check your email for your license key, then activate below:</div>
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <input
                    className="license-key-input"
                    placeholder="Paste license key from email"
                    value={activationLicenseKey}
                    onChange={(e) => setActivationLicenseKey(e.target.value)}
                    aria-label="License key from email"
                    style={{ flex: 1 }}
                  />
                  <button
                    className="activation-button"
                    disabled={!activationLicenseKey || activationLoading}
                    onClick={async () => {
                      setActivationLoading(true)
                      setActivationError('')
                      try {
                        const res = await apiFetch('/api/license/activate', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ license_key: activationLicenseKey }),
                        })
                        if (res.ok) {
                          setActivationLicenseKey('')
                          setCheckoutStatus(null)
                          setShowUpgradeModal(false)
                          const statusRes = await apiFetch('/api/license/status')
                          if (statusRes.ok) setLicenseStatus(await statusRes.json())
                        } else {
                          setActivationError('Invalid or expired license key')
                        }
                      } catch (err) {
                        setActivationError(`Activation failed: ${err}`)
                      } finally {
                        setActivationLoading(false)
                      }
                    }}
                  >
                    {activationLoading ? 'Activating…' : 'Activate'}
                  </button>
                </div>
                {activationError && <div className="activation-error" role="alert">{activationError}</div>}
              </div>
            )}
            {upgradeModalTab === 'plans' && checkoutStatus === 'cancelled' && (
              <div className="checkout-cancelled-banner" role="status">
                Checkout cancelled. Feel free to try again.
              </div>
            )}

            {upgradeModalTab === 'plans' && <div className="tier-grid">
              {licensePlans.map((plan) => (
                <div key={plan.tier} className={`tier-card ${licenseStatus?.tier === plan.tier ? 'current-tier' : ''}`}>
                  <h3>{plan.tier.charAt(0).toUpperCase() + plan.tier.slice(1)}</h3>
                  <div className="tier-price">${plan.price_per_month}/mo</div>
                  <div className="tier-devices">{plan.device_limit} devices</div>
                  <ul className="tier-features">
                    {plan.features.map((feature: string) => (
                      <li key={String(feature)}>{String(feature).replace(/^[✓✔]\s*/, '')}</li>
                    ))}
                  </ul>
                  {licenseStatus?.tier === plan.tier ? (
                    <button className="tier-button current" disabled>Current Plan</button>
                  ) : (
                    <button
                      className="tier-button upgrade"
                      onClick={async () => {
                        try {
                          const res = await apiFetch('/api/billing/checkout', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ tier: plan.tier }),
                          })
                          if (res.ok) {
                            const data = await res.json() as { checkout_url: string }
                            window.location.href = data.checkout_url
                          }
                        } catch (err) {
                          error('Billing', `Checkout failed: ${err}`)
                        }
                      }}
                    >
                      Upgrade
                    </button>
                  )}
                </div>
              ))}
            </div>}

            {upgradeModalTab === 'plans' && <div className="license-activation">
              <h3>Already have a license key?</h3>
              <input
                className="license-key-input"
                placeholder="Paste your license key here..."
                value={activationLicenseKey}
                onChange={(e) => setActivationLicenseKey(e.target.value)}
              />
              {activationError && <div className="activation-error">{activationError}</div>}
              <button
                className="activation-button"
                disabled={!activationLicenseKey || activationLoading}
                onClick={async () => {
                  setActivationLoading(true)
                  setActivationError('')
                  try {
                    const res = await apiFetch('/api/license/activate', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ license_key: activationLicenseKey }),
                    })
                    if (res.ok) {
                      setActivationLicenseKey('')
                      setShowUpgradeModal(false)
                      // Refresh license status
                      const statusRes = await apiFetch('/api/license/status')
                      if (statusRes.ok) {
                        setLicenseStatus(await statusRes.json())
                      }
                    } else {
                      setActivationError('Invalid or expired license key')
                    }
                  } catch (err) {
                    setActivationError(`Activation failed: ${err}`)
                  } finally {
                    setActivationLoading(false)
                  }
                }}
              >
                {activationLoading ? 'Activating...' : 'Activate'}
              </button>
            </div>}
          </div>
        </div>
      )}

      {confirmState && (
        <ConfirmDialog
          message={confirmState.message}
          onConfirm={() => {
            const cb = confirmState.onConfirm
            setConfirmState(null)
            try {
              const result = cb() as unknown
              if (result instanceof Promise) result.catch((err) => error('Confirm', String(err)))
            } catch (err) {
              error('Confirm', String(err))
            }
          }}
          onCancel={() => setConfirmState(null)}
        />
      )}

      {alphaAckPending && (
        <AlphaAcknowledgeModal
          deviceId={alphaAckPending.printer.id}
          deviceName={alphaAckPending.printer.name}
          protocol={alphaAckPending.printer.protocol || 'this adapter'}
          onAcknowledged={() => {
            const retry = alphaAckPending.retry
            setAlphaAckPending(null)
            retry()
          }}
          onCancel={() => setAlphaAckPending(null)}
        />
      )}

      {/* Toast notification overlay */}
      {toasts.length > 0 && (
        <div style={{position: 'fixed', bottom: 20, right: 20, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none'}}>
          {toasts.map((t) => (
            <div
              key={t.id}
              style={{
                padding: '8px 14px',
                borderRadius: 6,
                fontSize: 13,
                color: '#fff',
                pointerEvents: 'auto',
                maxWidth: 320,
                background: t.type === 'error' ? '#c33' : t.type === 'warning' ? '#a60' : t.type === 'success' ? '#1a7a3a' : '#333',
                boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
                cursor: 'pointer',
              }}
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            >
              {t.text}
            </div>
          ))}
        </div>
      )}

      {showAdminModal && <AdminPanel onClose={() => setShowAdminModal(false)} />}

      {/* Post-payment license activation overlay — auto-shown on Stripe return */}
      {checkoutStatus === 'success' && !showUpgradeModal && (
        <div className="modal-overlay" onClick={() => { setCheckoutStatus(null); setActivationLicenseKey(''); setActivationError('') }}>
          <div className="modal-content" role="dialog" aria-modal="true" aria-label="Activate license" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
            <button className="modal-close" onClick={() => { setCheckoutStatus(null); setActivationLicenseKey(''); setActivationError('') }} aria-label="Close activation dialog">✕</button>
            <h2>Activate Your License</h2>
            <div className="checkout-success-banner" role="status" style={{ marginBottom: 16 }}>
              ✓ Payment successful! Check your email for your license key.
            </div>
            <label htmlFor="standalone-license-key" style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>License key</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                id="standalone-license-key"
                className="license-key-input"
                placeholder="Paste license key from email"
                value={activationLicenseKey}
                onChange={(e) => setActivationLicenseKey(e.target.value)}
                aria-label="License key from email"
                style={{ flex: 1 }}
                autoFocus
              />
              <button
                className="activation-button"
                disabled={!activationLicenseKey || activationLoading}
                onClick={async () => {
                  setActivationLoading(true)
                  setActivationError('')
                  try {
                    const res = await apiFetch('/api/license/activate', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ license_key: activationLicenseKey }),
                    })
                    if (res.ok) {
                      setActivationLicenseKey('')
                      setCheckoutStatus(null)
                      const statusRes = await apiFetch('/api/license/status')
                      if (statusRes.ok) setLicenseStatus(await statusRes.json())
                    } else {
                      setActivationError('Invalid or expired license key')
                    }
                  } catch (err) {
                    setActivationError(`Activation failed: ${err}`)
                  } finally {
                    setActivationLoading(false)
                  }
                }}
              >
                {activationLoading ? 'Activating…' : 'Activate'}
              </button>
            </div>
            {activationError && <div className="activation-error" role="alert" style={{ marginTop: 8 }}>{activationError}</div>}
            <div style={{ marginTop: 16, fontSize: 12, color: 'var(--text-secondary)' }}>
              No key yet? Check your spam folder or{' '}
              <button
                type="button"
                style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', padding: 0, fontSize: 12 }}
                onClick={() => { setCheckoutStatus(null); setShowUpgradeModal(true) }}
                aria-label="Open upgrade panel"
              >open the upgrade panel</button>.
            </div>
          </div>
        </div>
      )}

      {/* Account settings modal */}
      {showAccountSettings && (
        <div
          className="modal-overlay"
          onClick={() => { setShowAccountSettings(false); setAcctPwCurrent(''); setAcctPwNew(''); setAcctPwConfirm(''); setAcctPwError(''); setAcctPwSuccess(false) }}
        >
          <div ref={accountSettingsRef} className="modal-content" role="dialog" aria-modal="true" aria-label="Account settings" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
            <button
              className="modal-close"
              onClick={() => { setShowAccountSettings(false); setAcctPwCurrent(''); setAcctPwNew(''); setAcctPwConfirm(''); setAcctPwError(''); setAcctPwSuccess(false) }}
              aria-label="Close account settings"
            >✕</button>
            <h2>Account Settings</h2>

            <section style={{ marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--border-default)' }}>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>Current plan</div>
              <div style={{ fontSize: 15, fontWeight: 600, textTransform: 'capitalize' }}>
                {licenseStatus?.tier ?? 'Free'}
              </div>
              {licenseStatus?.days_remaining != null && (
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                  {licenseStatus.days_remaining} day{licenseStatus.days_remaining !== 1 ? 's' : ''} remaining
                </div>
              )}
              {licenseStatus?.device_limit != null && (
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                  {licenseStatus.device_limit} device limit
                </div>
              )}
            </section>

            {!isDemoMode && <section style={{ marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--border-default)' }}>
              <div style={{ fontWeight: 600, marginBottom: 10, fontSize: 14 }}>Change Password</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <label htmlFor="acct-pw-current" style={{ display: 'block', fontSize: 12, marginBottom: 2 }}>Current password</label>
                  <input
                    id="acct-pw-current"
                    type="password"
                    value={acctPwCurrent}
                    onChange={(e) => setAcctPwCurrent(e.target.value)}
                    aria-label="Current password"
                    autoComplete="current-password"
                    style={{ width: '100%', boxSizing: 'border-box' }}
                  />
                </div>
                <div>
                  <label htmlFor="acct-pw-new" style={{ display: 'block', fontSize: 12, marginBottom: 2 }}>New password</label>
                  <input
                    id="acct-pw-new"
                    type="password"
                    value={acctPwNew}
                    onChange={(e) => setAcctPwNew(e.target.value)}
                    aria-label="New password"
                    autoComplete="new-password"
                    style={{ width: '100%', boxSizing: 'border-box' }}
                  />
                </div>
                <div>
                  <label htmlFor="acct-pw-confirm" style={{ display: 'block', fontSize: 12, marginBottom: 2 }}>Confirm new password</label>
                  <input
                    id="acct-pw-confirm"
                    type="password"
                    value={acctPwConfirm}
                    onChange={(e) => setAcctPwConfirm(e.target.value)}
                    aria-label="Confirm new password"
                    autoComplete="new-password"
                    style={{ width: '100%', boxSizing: 'border-box' }}
                  />
                </div>
                {acctPwError && <div role="alert" style={{ color: 'var(--color-error, #e05)', fontSize: 13 }}>{acctPwError}</div>}
                {acctPwSuccess && <div role="status" style={{ color: 'var(--color-success, #2a7)', fontSize: 13 }}>Password changed successfully.</div>}
                <button
                  type="button"
                  disabled={acctPwLoading || !acctPwCurrent || !acctPwNew || !acctPwConfirm}
                  onClick={async () => {
                    if (acctPwNew !== acctPwConfirm) { setAcctPwError('Passwords do not match'); return }
                    if (acctPwNew.length < 8) { setAcctPwError('Password must be at least 8 characters'); return }
                    setAcctPwLoading(true)
                    setAcctPwError('')
                    setAcctPwSuccess(false)
                    try {
                      const res = await apiFetch('/api/auth/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ current_password: acctPwCurrent, new_password: acctPwNew }),
                      })
                      const data = await res.json() as { access_token?: string; refresh_token?: string; detail?: string }
                      if (res.ok && data.access_token && data.refresh_token) {
                        setTokens(data.access_token, data.refresh_token)
                        setAccessToken(data.access_token)
                        setAcctPwCurrent('')
                        setAcctPwNew('')
                        setAcctPwConfirm('')
                        setAcctPwSuccess(true)
                      } else {
                        setAcctPwError(data.detail ?? 'Failed to change password')
                      }
                    } catch (err) {
                      setAcctPwError(`Error: ${err}`)
                    } finally {
                      setAcctPwLoading(false)
                    }
                  }}
                  aria-label="Change password"
                >
                  {acctPwLoading ? 'Saving…' : 'Change Password'}
                </button>
              </div>
            </section>}

            <section>
              <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 14 }}>Sessions</div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 10 }}>
                Revokes all active sessions on all devices.
              </div>
              <button
                type="button"
                style={{ background: 'var(--color-error, #c0392b)', color: '#fff', border: 'none' }}
                onClick={() => {
                  void apiFetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
                  clearTokens()
                  setIsLoggedIn(false)
                  setShowAccountSettings(false)
                }}
                aria-label="Log out all sessions"
              >
                Log out all sessions
              </button>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}

const FileDetailCard = React.memo(function FileDetailCard({ detail }: { detail: FileDetailResponse }) {
  return (
    <div className="file-detail-card">
      <div className="file-detail-header">
        <div>
          <strong>{detail.file.name}</strong>
          <div className="subtle small">{detail.metadata.path}</div>
        </div>
        <div className="subtle small">{formatBytes(detail.metadata.size)} • {formatTimestamp(detail.metadata.modified)}</div>
      </div>
      {detail.metadata.thumbnail_url && <img className="file-thumbnail" src={detail.metadata.thumbnail_url} alt={detail.file.name} loading="lazy" />}
      <div className="kv-grid compact-kv-grid">
        <div><span>Estimated time</span><strong>{formatDuration(detail.metadata.estimated_time_s)}</strong></div>
        <div><span>Filament</span><strong>{formatMillimeters(detail.metadata.filament_mm)}</strong></div>
        <div><span>Filament g</span><strong>{detail.metadata.filament_g == null ? '—' : `${detail.metadata.filament_g.toFixed(1)} g`}</strong></div>
        <div><span>Layer height</span><strong>{detail.metadata.layer_height_mm == null ? '—' : `${detail.metadata.layer_height_mm.toFixed(2)} mm`}</strong></div>
        <div><span>Object height</span><strong>{detail.metadata.object_height_mm == null ? '—' : `${detail.metadata.object_height_mm.toFixed(2)} mm`}</strong></div>
        <div><span>Slicer</span><strong>{detail.metadata.slicer || '—'}</strong></div>
      </div>
      <div className="hint-list">
        {detail.compatibility_hints.map((hint) => <div key={hint} className="hint-chip">{hint}</div>)}
      </div>
    </div>
  )
})

const UiTargetMenu = React.memo(function UiTargetMenu({ printerId, label, targets, open, onToggle, onClose }: { printerId: string; label: string; targets: UiTarget[]; open: boolean; onToggle: () => void; onClose: () => void }) {
  // T75: Filter to only https: URLs to prevent XSS/phishing via injected ui_targets
  const safeTargets = targets.filter((t) => safeUiUrl(t.url))
  return (
    <div className="ui-launcher">
      <button className="action-link action-link-fluidd" onClick={onToggle}>{label} ▾</button>
      {open && safeTargets.length > 0 && (
        <div className="ui-menu">
          {safeTargets.map((target) => (
            <a key={`${printerId}-${target.provider}-${target.url}`} className="ui-menu-item" href={target.url} target="_blank" rel="noreferrer" onClick={onClose}>{target.label}</a>
          ))}
        </div>
      )}
    </div>
  )
})

// ─── Fleet KPI types + shared bits (consumed by the fleet summary) ──────────────
type FleetKpi = {
  oee: {
    fleet_oee: number | null; availability: number | null; performance: number | null
    quality: number | null; teep?: number | null; sample_jobs: number
    devices_with_data: number; devices_without_perf: number
  } | null
  utilization_pct: number | null
  error_rate_pct: number | null
  throughput: { jobs: number; jobs_per_day: number } | null
  reliability: { mtbf_hours: number | null; mttr_minutes: number | null; failures: number; uptime_hours?: number; downtime_minutes?: number } | null
  cost: { cost_per_day: number; cost_per_part: number | null; price_per_kg: number } | null
  downtime_pareto: { mode: string; count: number }[]
  oee_trend: { date: string; oee: number; job_count?: number }[]
}

// RAG (red-amber-green) banding per ISO/OEE convention. `value` is a 0-100 number.
function ragColor(value: number | null | undefined, opts: { green: number; amber: number; inverse?: boolean }): string {
  if (value == null) return 'var(--text-secondary)'
  const ok = opts.inverse ? value <= opts.green : value >= opts.green
  const mid = opts.inverse ? value <= opts.amber : value >= opts.amber
  return ok ? 'var(--color-success)' : mid ? 'var(--color-warning)' : 'var(--color-danger)'
}

function MiniSparkline({ data, width = 92, height = 22, color = 'var(--color-success)' }: { data: number[]; width?: number; height?: number; color?: string }) {
  if (!data || data.length < 2) return null
  const max = Math.max(...data), min = Math.min(...data), span = (max - min) || 1
  const pts = data.map((v, i) => `${((i / (data.length - 1)) * width).toFixed(1)},${(height - ((v - min) / span) * height).toFixed(1)}`).join(' ')
  return (
    <svg className="kpi-spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

// ─── Grouped fleet summary (status bar + themed metric groups) ──────────────
// Hover/focus tooltip — plain-language definition of a metric (definitions only,
// no fabricated data). Keyboard-accessible via tabIndex + :focus-within.
function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <span className="tip" tabIndex={0}>
      {children}
      <span className="tip-pop" role="tooltip">{text}</span>
    </span>
  )
}

function GroupCard({ title, accent, children, onClick }: {
  title: string; accent?: string; children: React.ReactNode; onClick?: () => void
}) {
  const clickable = !!onClick
  return (
    <div
      className={`group-card${clickable ? ' clickable' : ''}`}
      style={accent ? { borderTopColor: accent } : undefined}
      onClick={onClick}
      role={clickable ? 'button' : undefined}
      aria-label={clickable ? `View ${title} details` : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick!() } } : undefined}
    >
      <div className="group-title">
        <span>{title}</span>
        {clickable && <span className="group-more" aria-hidden="true">Details ›</span>}
      </div>
      {children}
    </div>
  )
}

function GRow({ k, v, color, tip }: { k: string; v: React.ReactNode; color?: string; tip?: string }) {
  return <div className="group-row"><span className="group-k">{tip ? <Tip text={tip}>{k}</Tip> : k}</span><span className="group-v" style={color ? { color } : undefined}>{v}</span></div>
}

function FleetSummary({ kpi, m, showMetrics = true, onOpenAnalytics, onOpenService }: {
  kpi: FleetKpi | null
  m: MetricsResponse['summary'] | null | undefined
  showMetrics?: boolean
  onOpenAnalytics?: () => void
  onOpenService?: () => void
}) {
  const pct = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
  const oee = kpi?.oee
  const trend = (kpi?.oee_trend || []).map((t) => t.oee).filter((v): v is number => v != null)
  // Daily job throughput trend (jobs/day per day) — already carried on oee_trend.
  const jobsTrend = (kpi?.oee_trend || []).map((t) => t.job_count).filter((v): v is number => v != null)
  const rel = kpi?.reliability, cost = kpi?.cost, pareto = kpi?.downtime_pareto || []
  // Errors derived from the SAME population as Success (recent job history),
  // so they can't contradict (e.g. 83% success but 0% errors from a 24h window).
  const errPct = m && m.total_jobs_window > 0 ? (m.failed_jobs_window / m.total_jobs_window) * 100 : null
  return (
    <div className="kpi-section">
      <div className="summary-groups">
        <GroupCard title="Effectiveness" accent="var(--color-success)" onClick={onOpenAnalytics}>
          {oee ? (
            <>
              <div className="group-feature" style={{ color: ragColor(oee.fleet_oee == null ? null : oee.fleet_oee * 100, { green: 85, amber: 60 }) }}>{pct(oee.fleet_oee, 1)}<Tip text="Overall Equipment Effectiveness = Availability × Performance × Quality. The TPM standard; ~85% is world-class."><span className="group-feature-lbl">OEE</span></Tip></div>
              <div className="kpi-sublines">
                <Tip text="Availability — share of planned time the machines were actually running."><span><b>A</b> {pct(oee.availability)}</span></Tip>
                <Tip text="Performance — actual run rate vs. the machine's ideal rate."><span><b>P</b> {pct(oee.performance)}</span></Tip>
                <Tip text="Quality — share of jobs completed without failure."><span><b>Q</b> {pct(oee.quality)}</span></Tip>
              </div>
              <GRow k="TEEP" v={pct(oee.teep, 0)} tip="Total Effective Equipment Performance = OEE × Utilization — effectiveness against all calendar time." />
              <GRow k="Utilization" v={kpi?.utilization_pct == null ? '—' : `${kpi.utilization_pct.toFixed(0)}%`} tip="Share of calendar time the fleet was in use (last 24h)." />
              {trend.length > 1 && <MiniSparkline data={trend} color="var(--color-success)" />}
            </>
          ) : <div className="group-empty">OEE unavailable</div>}
        </GroupCard>
        {showMetrics && <GroupCard title="Production · recent" accent="var(--accent-solid)" onClick={onOpenAnalytics}>
          {m ? (
            <>
              <GRow k="Jobs" v={<>{m.total_jobs_window} <span className="muted">({m.completed_jobs_window}✓)</span></>} tip="Jobs in recent history (up to 50 per printer; ✓ = completed)." />
              <GRow k="Success" v={m.success_rate_window == null ? '—' : `${m.success_rate_window.toFixed(1)}%`} color={ragColor(m.success_rate_window, { green: 95, amber: 80 })} tip="Share of those recent finished jobs that completed successfully." />
              <GRow k="Throughput" v={`${kpi?.throughput?.jobs_per_day ?? 0}/d`} tip="Completed jobs per day, measured over the last 24h." />
              <GRow k="Errors" v={errPct == null ? '—' : `${errPct.toFixed(1)}%`} color={ragColor(errPct, { green: 5, amber: 15, inverse: true })} tip="Share of those recent jobs that ended in failure (same population as Success)." />
              <GRow k="Print time" v={formatDuration(m.total_print_time_window)} tip="Total print time across those recent jobs." />
              {jobsTrend.length > 1 && jobsTrend.some((v) => v > 0) && <MiniSparkline data={jobsTrend} color="var(--accent-solid)" />}
            </>
          ) : <div className="group-empty">—</div>}
        </GroupCard>}
        {showMetrics && <GroupCard title="Consumables + Svc" accent="var(--color-warning)" onClick={onOpenService}>
          {m ? (
            <>
              <GRow k="Spool" v={formatGrams(m.total_spool_remaining_g)} tip="Total filament remaining across configured spools." />
              <GRow k="Filament" v={formatMillimeters(m.total_filament_used_window)} tip="Total filament length consumed in the window." />
              <GRow k="Maint due" v={m.maintenance_due_count} color={m.maintenance_due_count > 0 ? 'var(--color-warning)' : undefined} tip="Printers past their service date. Click the card for the full service list." />
              <GRow k="Hottest" v={<>{m.hottest_printer_name || '—'} {m.hottest_printer_temp != null && <span className="muted">{m.hottest_printer_temp.toFixed(0)}°</span>}</>} tip="Printer reporting the highest current temperature." />
            </>
          ) : <div className="group-empty">—</div>}
        </GroupCard>}
        {showMetrics && (
          <GroupCard title="Reliability · 7d" accent="#e06c75" onClick={onOpenAnalytics}>
            <GRow k="MTBF" v={rel?.mtbf_hours == null ? '—' : `${rel.mtbf_hours}h`} tip="Mean Time Between Failures = uptime ÷ failures (7d). '—' means no failures recorded." />
            <GRow k="MTTR" v={rel?.mttr_minutes == null ? '—' : `${rel.mttr_minutes}m`} tip="Mean Time To Repair = downtime ÷ failures (7d)." />
            <GRow k="Failures" v={rel?.failures ?? 0} color={(rel?.failures ?? 0) > 0 ? 'var(--color-warning)' : 'var(--color-success)'} tip="Device down-transitions in the last 7 days (from the status-log stream)." />
            <GRow k="Uptime" v={rel?.uptime_hours == null ? '—' : `${Math.round(rel.uptime_hours)}h`} tip="Total device-hours online over the last 7 days." />
            {(cost?.cost_per_day ?? 0) > 0 && <GRow k="Cost/day" v={`$${cost!.cost_per_day.toFixed(2)}`} tip="Estimated filament cost per day = filament used × price per kg." />}
            {cost?.cost_per_part != null && <GRow k="Cost/part" v={`$${cost.cost_per_part.toFixed(2)}`} tip="Estimated filament cost per completed job (last 24h)." />}
            {pareto.length > 0 && <GRow k="Top fail" v={pareto[0].mode} tip="Most frequent failure reason (last 7d)." />}
          </GroupCard>
        )}
      </div>
    </div>
  )
}

// Service & consumables drill-down — per-printer maintenance status, service
// dates, and spool remaining. All from the live fleet payload (capability.*).
function ServiceModal({ printers, onClose, canAct, onServiced }: {
  printers: Printer[]; onClose: () => void; canAct: boolean; onServiced: (id: string) => void
}) {
  const today = new Date().toISOString().slice(0, 10)
  const [acting, setActing] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const isDue = (p: Printer) => {
    const due = p.capability.next_service_due
    if (due) return due <= today
    return !!p.capability.maintenance_due
  }
  const markServiced = async (id: string) => {
    if (!canAct || acting.has(id)) return
    setActing((s) => new Set(s).add(id)); setError(null)
    try {
      // Empty body — the backend stamps last_service_at=now and computes the next
      // due date from the printer's maintenance interval.
      const res = await apiFetch(`/api/printers/${id}/maintenance/complete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      })
      if (!res.ok) { setError(res.status === 403 ? 'Marking serviced needs an operator/admin login.' : `Couldn't update (HTTP ${res.status}).`); return }
      onServiced(id)  // optimistic fleet update → row flips to OK
    } catch { setError('Request failed — check the connection.') }
    finally { setActing((s) => { const n = new Set(s); n.delete(id); return n }) }
  }
  const rows = [...printers].sort((a, b) => (isDue(b) ? 1 : 0) - (isDue(a) ? 1 : 0) || a.name.localeCompare(b.name))
  const dueCount = rows.filter(isDue).length
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-service" role="dialog" aria-modal="true" aria-label="Service and consumables" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close service list" autoFocus>✕</button>
        <h2>Service &amp; Consumables</h2>
        <p className="subtle small" style={{ marginTop: -8 }}>{dueCount} of {rows.length} printers due for service</p>
        {error && <div className="svc-error" role="alert">{error}</div>}
        <div className="svc-table svc-table-act">
          <div className="svc-row svc-head"><span>Printer</span><span>Status</span><span>Last service</span><span>Next due</span><span>Spool</span><span>Action</span></div>
          {rows.map((p) => {
            const due = isDue(p)
            return (
              <div key={p.id} className="svc-row">
                <span className="svc-name">{p.name}</span>
                <span style={{ color: due ? 'var(--color-warning)' : 'var(--color-success)', fontWeight: 600 }}>{due ? 'Due' : 'OK'}</span>
                <span>{p.capability.last_service_at || '—'}</span>
                <span style={{ color: due ? 'var(--color-warning)' : undefined }}>{p.capability.next_service_due || '—'}</span>
                <span>{formatGrams(p.capability.spool_remaining_g)}</span>
                <span>
                  {due ? (
                    <button
                      className="svc-action"
                      disabled={!canAct || acting.has(p.id)}
                      title={canAct ? 'Record service — resets the maintenance clock' : 'Log in as operator/admin to mark serviced'}
                      onClick={() => markServiced(p.id)}
                    >{acting.has(p.id) ? '…' : 'Mark serviced'}</button>
                  ) : <span className="svc-okmark" aria-label="up to date">✓</span>}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// Per-machine OEE (from /api/oee). Shown in the matrix (% only), on cards
// (compact), and in the workspace detail (full breakdown) — gated by show_oee.
type OeeDevice = {
  device_id: string
  oee: number | null
  availability: number | null
  performance: number | null
  quality: number | null
  sample_jobs: number
}

function MachineOee({ oee, variant = 'compact' }: { oee: OeeDevice | null | undefined; variant?: 'compact' | 'full' }) {
  if (!oee) return null
  const pct = (v: number | null, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
  const oeeC = ragColor(oee.oee == null ? null : oee.oee * 100, { green: 85, amber: 60 })
  if (variant === 'compact') {
    return (
      <div className="machine-oee machine-oee-compact">
        <span className="machine-oee-val" style={{ color: oeeC }}>OEE {pct(oee.oee)}</span>
        <span className="machine-oee-apq">A {pct(oee.availability)} · P {pct(oee.performance)} · Q {pct(oee.quality)}</span>
      </div>
    )
  }
  return (
    <div className="machine-oee machine-oee-full" style={{ borderLeftColor: oeeC }}>
      <div className="metric-label">Overall Equipment Effectiveness</div>
      <div className="machine-oee-big" style={{ color: oeeC }}>{pct(oee.oee, 1)}</div>
      <div className="machine-oee-grid">
        <div><span className="moe-k">Availability</span><span className="moe-v" style={{ color: ragColor(oee.availability == null ? null : oee.availability * 100, { green: 90, amber: 75 }) }}>{pct(oee.availability)}</span></div>
        <div><span className="moe-k">Performance</span><span className="moe-v" style={{ color: ragColor(oee.performance == null ? null : oee.performance * 100, { green: 90, amber: 75 }) }}>{pct(oee.performance)}</span></div>
        <div><span className="moe-k">Quality</span><span className="moe-v" style={{ color: ragColor(oee.quality == null ? null : oee.quality * 100, { green: 95, amber: 85 }) }}>{pct(oee.quality)}</span></div>
      </div>
      <div className="metric-note">{oee.sample_jobs} jobs sampled{oee.performance == null ? ' · performance n/a (no slicer estimate)' : ''}</div>
    </div>
  )
}

const DryRunMatrix = React.memo(function DryRunMatrix({ results }: { results: DryRunResult[] }) {
  return <div className="matrix-list">{results.map((result) => <div key={result.printer_id} className={`matrix-row ${result.eligible ? 'matrix-ok' : 'matrix-blocked'}`}><div><strong>{result.name}</strong><div className="subtle small">{result.motion_summary || result.current_state || '—'}</div></div><div>{result.eligible ? 'Eligible' : 'Blocked'}</div><div className="subtle small">{[...result.blocking_reasons, ...result.warnings].join(' • ') || 'No issues'}</div></div>)}</div>
})

const DispatchMatrix = React.memo(function DispatchMatrix({ payload }: { payload: DispatchDryRunResponse }) {
  return <div className="matrix-list">{payload.results.map((result) => <div key={result.printer_id} className={`matrix-row ${result.eligible ? 'matrix-ok' : 'matrix-blocked'}`}><div><strong>{result.name}</strong><div className="subtle small">score {result.score != null ? result.score.toFixed(1) : '—'}</div></div><div>{result.recommendation || (result.eligible ? 'Eligible' : 'Blocked')}</div><div className="subtle small">{[...result.blocking_reasons, ...result.warnings].join(' • ') || 'No issues'}</div></div>)}</div>
})

function attentionRank(printer: Printer) {
  if (!printer.online) return 100
  if (printer.anomalies.some((item) => item.severity === 'critical')) return 90
  if (printer.nozzle.temperature !== null &&
      printer.nozzle.temperature > (printer.capability.safe_nozzle_max_c ?? 300) * 0.95) return 88
  if (printer.capability.maintenance_due) return 85
  if (printer.anomalies.some((item) => item.severity === 'warning')) return 80
  if (printerType(printer) !== 'sla' &&
      (printer.capability.spool_remaining_g ?? Infinity) < 50) return 78
  if (printer.job.state === 'paused') return 70
  if (printer.job.state === 'printing') return 50
  return 0
}

function hottestTemperature(printer: Printer) {
  return Math.max(printer.nozzle.temperature || 0, printer.bed.temperature || 0)
}

function prettyStateGroup(printer: Printer) {
  if (!printer.online) return 'offline'
  if (printer.job.state === 'printing') return 'printing'
  if (printer.job.state === 'paused') return 'paused'
  if (printer.attention_needed) return 'attention'
  return printer.state || 'unknown'
}

function displayPrinterState(printer: Printer) {
  if (!printer.online) return 'offline'
  if (printer.job.state === 'printing') return 'printing'
  if (printer.job.state === 'paused') return 'paused'
  return printer.state
}

function labelForAction(action: string) {
  const overrides: Record<string, string> = { motors_off: 'Motors Off', firmware_restart: 'FW Restart' }
  return overrides[action] ?? action.split('_').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
}

// Tooltip text for the quick-action buttons — same labels as labelForAction,
// but full sentences since compact/cramped card density can shrink the
// button down to just the icon-sized label.
function descriptionForAction(action: string): string {
  const descriptions: Record<string, string> = {
    pause: 'Pause the current job',
    resume: 'Resume the paused job',
    cancel: 'Cancel the current job',
    home: 'Home all axes',
    cooldown: 'Turn off nozzle and bed heaters',
    motors_off: 'Disengage stepper motors',
    firmware_restart: 'Restart printer firmware',
  }
  return descriptions[action] ?? labelForAction(action)
}

function fmtTemp(current: number | null, target: number | null) {
  if (current == null && target == null) return '—'
  const cur = current == null ? '—' : `${current.toFixed(1)} C`
  const tgt = target == null ? '—' : `${target.toFixed(1)} C`
  return `${cur} / ${tgt}`
}

function formatDuration(value: number | null | undefined) {
  if (value == null || value <= 0) return '—'
  const totalSeconds = Math.floor(value)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function formatTimestamp(value: string | number | null | undefined) {
  if (value == null || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

function formatBytes(value: number | null | undefined) {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatGrams(value: number | null | undefined) {
  if (value == null) return '—'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} kg`
  return `${value.toFixed(0)} g`
}

function formatMillimeters(value: number | null | undefined) {
  if (value == null || value <= 0) return '—'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} m`
  return `${value.toFixed(0)} mm`
}

function parentPath(path: string) {
  const clean = path.replace(/\/$/, '')
  const idx = clean.lastIndexOf('/')
  if (idx <= 0) return null
  return clean.slice(0, idx)
}

function normalizeRelativeUploadPath(path: string) {
  const clean = path.trim().replace(/^\/+/, '').replace(/\/+$/, '')
  if (clean === 'gcodes') return ''
  return clean.startsWith('gcodes/') ? clean.slice('gcodes/'.length) : clean
}

function relativeFilename(path: string) {
  return path.replace(/^gcodes\//, '')
}

/** Join key between a browsed file and its JobLog history.
 *
 * FileEntry.path is prefixed (`gcodes/a/b.gcode`) while JobLog.job_name is stored
 * gcodes-relative (`a/b.gcode`) — Moonraker reports both `print_stats.filename`
 * and `history.filename` without the root. Note this keys on the PATH, not
 * entry.name: the name is only a basename, so keying on it would miss every file
 * in a subdirectory and silently render '—'. Applied to BOTH sides of the lookup
 * so the two can never drift apart. */
function normalizeJobKey(path: string) {
  return path.trim().replace(/^\/+/, '').replace(/^gcodes\//, '')
}

function formatBuildVolume(volume: Record<string, number> | undefined) {
  if (!volume || Object.keys(volume).length === 0) return '—'
  const x = volume.x ?? volume.X
  const y = volume.y ?? volume.Y
  const z = volume.z ?? volume.Z
  if (x == null && y == null && z == null) return '—'
  return `${x ?? '—'} x ${y ?? '—'} x ${z ?? '—'} mm`
}

function baseProfileLabel(profile: string | null | undefined) {
  if (!profile) return '—'
  return profile.replace(/([_-])?nozzle[-_]?\d+(?:p\d+)?$/i, '').replace(/[-_]+$/g, '') || profile
}

function KlipperConfigPanel({ cfg }: { cfg: KlipperConfig }) {
  const yn = (v: boolean) => v ? 'Yes' : 'No'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Kinematics & motion */}
      <div>
        <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Kinematics &amp; motion</div>
        <div className="kv-grid">
          <div><span>Type</span><strong>{cfg.kinematics ?? '—'}</strong></div>
          {cfg.max_velocity != null && <div><span>Max velocity</span><strong>{cfg.max_velocity} mm/s</strong></div>}
          {cfg.max_accel != null && <div><span>Max accel</span><strong>{cfg.max_accel} mm/s²</strong></div>}
          {cfg.max_z_velocity != null && <div><span>Max Z velocity</span><strong>{cfg.max_z_velocity} mm/s</strong></div>}
          {cfg.max_z_accel != null && <div><span>Max Z accel</span><strong>{cfg.max_z_accel} mm/s²</strong></div>}
          {cfg.square_corner_velocity != null && <div><span>Square corner vel</span><strong>{cfg.square_corner_velocity} mm/s</strong></div>}
        </div>
      </div>

      {/* Build volume */}
      {(cfg.x_max != null || cfg.y_max != null || cfg.z_max != null) && (
        <div>
          <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Build volume</div>
          <div className="kv-grid">
            {cfg.x_max != null && <div><span>X</span><strong>{cfg.x_max} mm</strong></div>}
            {cfg.y_max != null && <div><span>Y</span><strong>{cfg.y_max} mm</strong></div>}
            {cfg.z_max != null && <div><span>Z</span><strong>{cfg.z_max} mm</strong></div>}
          </div>
        </div>
      )}

      {/* Extruder */}
      <div>
        <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Extruder</div>
        <div className="kv-grid">
          {cfg.nozzle_diameter != null && <div><span>Nozzle</span><strong>{cfg.nozzle_diameter} mm</strong></div>}
          {cfg.filament_diameter != null && <div><span>Filament</span><strong>{cfg.filament_diameter} mm</strong></div>}
          {cfg.nozzle_max_temp != null && <div><span>Max temp</span><strong>{cfg.nozzle_max_temp} °C</strong></div>}
          {cfg.nozzle_sensor_type && <div><span>Thermistor</span><strong>{cfg.nozzle_sensor_type}</strong></div>}
          {cfg.pressure_advance != null && <div><span>Pressure advance</span><strong>{cfg.pressure_advance}</strong></div>}
          {cfg.gear_ratio && <div><span>Gear ratio</span><strong>{cfg.gear_ratio}</strong></div>}
          {cfg.rotation_distance != null && <div><span>Rotation distance</span><strong>{cfg.rotation_distance.toFixed(4)}</strong></div>}
          {cfg.microsteps_e != null && <div><span>Microsteps</span><strong>{cfg.microsteps_e}</strong></div>}
        </div>
      </div>

      {/* Heated bed */}
      {(cfg.bed_max_temp != null || cfg.bed_sensor_type) && (
        <div>
          <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Heated bed</div>
          <div className="kv-grid">
            {cfg.bed_max_temp != null && <div><span>Max temp</span><strong>{cfg.bed_max_temp} °C</strong></div>}
            {cfg.bed_sensor_type && <div><span>Thermistor</span><strong>{cfg.bed_sensor_type}</strong></div>}
          </div>
        </div>
      )}

      {/* Probing & leveling */}
      <div>
        <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Probing &amp; leveling</div>
        <div className="kv-grid">
          <div><span>Probe</span><strong>{cfg.has_probe ? (cfg.probe_type ?? 'Yes') : 'No'}</strong></div>
          <div><span>Bed mesh</span><strong>{yn(cfg.has_bed_mesh)}</strong></div>
          <div><span>Z tilt</span><strong>{yn(cfg.has_z_tilt)}</strong></div>
          <div><span>Quad gantry</span><strong>{yn(cfg.has_quad_gantry_level)}</strong></div>
          <div><span>Safe Z home</span><strong>{yn(cfg.has_safe_z_home)}</strong></div>
          <div><span>Homing override</span><strong>{yn(cfg.has_homing_override)}</strong></div>
          <div><span>Sensorless X</span><strong>{yn(cfg.sensorless_x)}</strong></div>
          <div><span>Sensorless Y</span><strong>{yn(cfg.sensorless_y)}</strong></div>
        </div>
      </div>

      {/* Stepper drivers */}
      {cfg.tmc_drivers.length > 0 && (
        <div>
          <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Stepper drivers ({cfg.tmc_drivers.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {cfg.tmc_drivers.map(d => (
              <span key={d} className="tag-chip">{d}</span>
            ))}
          </div>
        </div>
      )}

      {/* Fans */}
      <div>
        <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Fans</div>
        <div className="kv-grid">
          <div><span>Part cooling fans</span><strong>{cfg.fan_count}</strong></div>
          <div><span>Heater fans</span><strong>{cfg.heater_fan_count}</strong></div>
          <div><span>Controller fans</span><strong>{cfg.controller_fan_count}</strong></div>
        </div>
      </div>

      {/* Temperature sensors */}
      {cfg.temperature_sensors.length > 0 && (
        <div>
          <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Temp sensors</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {cfg.temperature_sensors.map(s => (
              <span key={s} className="tag-chip">{s}</span>
            ))}
          </div>
        </div>
      )}

      {/* MCU */}
      {cfg.mcu_serial && (
        <div>
          <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>MCU</div>
          <code className="subtle small" style={{ wordBreak: 'break-all' }}>{cfg.mcu_serial}</code>
        </div>
      )}

      {/* Macros */}
      {cfg.macro_names.length > 0 && (
        <div>
          <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>G-code macros ({cfg.macro_names.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {cfg.macro_names.map(m => (
              <span key={m} className="tag-chip">{m}</span>
            ))}
          </div>
        </div>
      )}

      {/* Includes */}
      {cfg.include_files.length > 0 && (
        <div>
          <div className="subtle small" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Includes</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {cfg.include_files.map(f => (
              <span key={f} className="tag-chip">{f}</span>
            ))}
          </div>
        </div>
      )}

      {/* Parse notes / warnings */}
      {cfg.parse_notes.length > 0 && (
        <div className="subtle small" style={{ color: 'var(--color-warning, #f90)' }}>
          {cfg.parse_notes.map((n, i) => <div key={i}>⚠ {n}</div>)}
        </div>
      )}
    </div>
  )
}

function displayProfileLabel(profile: string | null | undefined, nozzleDiameterMm: number | null | undefined) {
  const base = baseProfileLabel(profile)
  if (base === '—') return base
  if (nozzleDiameterMm == null) return base
  return `${base} · ${nozzleDiameterMm.toFixed(2)} nozzle`
}

function hasBuildVolume(volume: Record<string, number> | undefined) {
  if (!volume) return false
  return ['x', 'y', 'z', 'X', 'Y', 'Z'].some((key) => Number.isFinite(volume[key]))
}

function capabilityOverviewItems(capability: PrinterCapability, homedAxes?: string | null, showEmpty = false) {
  const items: Array<{ label: string; value: string }> = []
  const nozzleValue = capability.nozzle_diameter_mm == null ? '—' : `${capability.nozzle_diameter_mm.toFixed(2)} mm`
  items.push({ label: 'Profile', value: displayProfileLabel(capability.profile, capability.nozzle_diameter_mm) })
  if (showEmpty || capability.nozzle_diameter_mm != null) items.push({ label: 'Nozzle', value: nozzleValue })
  if (showEmpty || capability.probe) items.push({ label: 'Probe', value: capability.probe ? 'Yes' : 'No' })
  if (showEmpty || capability.filament_sensor) items.push({ label: 'Filament sensor', value: capability.filament_sensor ? 'Yes' : 'No' })
  if (showEmpty || capability.webcam_expected) items.push({ label: 'Webcam expected', value: capability.webcam_expected ? 'Yes' : 'No' })
  if (hasBuildVolume(capability.build_volume)) items.push({ label: 'Build volume', value: formatBuildVolume(capability.build_volume) })
  if (capability.supported_materials.length > 0) items.push({ label: 'Materials', value: capability.supported_materials.join(', ') })
  if (capability.current_material) items.push({ label: 'Current material', value: capability.current_material })
  if (capability.current_spool_name) items.push({ label: 'Spool', value: capability.current_spool_name })
  else if (capability.spool_remaining_g != null) items.push({ label: 'Spool remaining', value: formatGrams(capability.spool_remaining_g) })
  else if (showEmpty) items.push({ label: 'Spool remaining', value: '—' })
  if (capability.maintenance_due || capability.maintenance_state) items.push({ label: 'Maintenance', value: capability.maintenance_due ? 'Due' : capability.maintenance_state || '—' })
  if (capability.next_service_due) items.push({ label: 'Next service', value: capability.next_service_due })
  if (homedAxes && homedAxes !== 'none') items.push({ label: 'Homed axes', value: homedAxes })
  return items
}

function toPrinterSettingsDraft(source: Partial<PrinterSettingsPayload> & Partial<Printer> & { capability?: PrinterCapability }) : PrinterSettingsDraft {
  const capability = source.capability || ({} as PrinterCapability)
  const nozzleValue = source.nozzle_diameter_mm ?? capability.nozzle_diameter_mm ?? null
  const buildVolume = source.build_volume || capability.build_volume || {}
  const uiTargets = (source.ui_targets || capability.ui_targets || []).map((item) => ({
    provider: item.provider || 'other',
    label: item.label || 'UI',
    url: item.url || '',
    mode: item.mode || 'direct',
    primary: Boolean(item.primary),
  }))
  if (uiTargets.length > 0 && !uiTargets.some((item) => item.primary)) uiTargets[0].primary = true
  return {
    name: source.name || '',
    enabled: source.enabled ?? true,
    tagsText: (source.tags || []).join(', '),
    nozzleDiameter: nozzleValue == null ? '' : String(nozzleValue),
    filamentDiameterMm: source.filament_diameter_mm == null ? '' : String(source.filament_diameter_mm),
    wireUsedMmPerJob: source.wire_used_mm_per_job == null ? '' : String(source.wire_used_mm_per_job),
    compatibilityProfile: source.compatibility_profile || capability.profile || '',
    buildVolumeX: buildVolume.x == null ? '' : String(buildVolume.x),
    buildVolumeY: buildVolume.y == null ? '' : String(buildVolume.y),
    buildVolumeZ: buildVolume.z == null ? '' : String(buildVolume.z),
    supportedMaterialsText: (source.supported_materials || capability.supported_materials || []).join(', '),
    currentMaterial: source.current_material || capability.current_material || '',
    currentSpoolName: source.current_spool_name || capability.current_spool_name || '',
    spoolRemainingG: source.spool_remaining_g == null && capability.spool_remaining_g == null ? '' : String(source.spool_remaining_g ?? capability.spool_remaining_g ?? ''),
    spoolCapacityG: source.spool_capacity_g == null && capability.spool_capacity_g == null ? '' : String(source.spool_capacity_g ?? capability.spool_capacity_g ?? ''),
    filamentSensor: source.filament_sensor ?? capability.filament_sensor ?? false,
    probe: source.probe ?? capability.probe ?? false,
    webcamExpected: source.webcam_expected ?? capability.webcam_expected ?? false,
    cameraUrl: source.camera_url || capability.camera_url || '',
    timelapseDir: source.timelapse_dir || '',
    maintenanceLockout: source.maintenance_lockout ?? capability.maintenance_lockout ?? false,
    maintenanceState: source.maintenance_state || capability.maintenance_state || '',
    maintenanceDue: source.maintenance_due ?? capability.maintenance_due ?? false,
    maintenanceIntervalHours: source.maintenance_interval_hours == null && capability.maintenance_interval_hours == null ? '' : String(source.maintenance_interval_hours ?? capability.maintenance_interval_hours ?? ''),
    maintenanceIntervalJobs: source.maintenance_interval_jobs == null && capability.maintenance_interval_jobs == null ? '' : String(source.maintenance_interval_jobs ?? capability.maintenance_interval_jobs ?? ''),
    maintenanceIntervalFilamentG: source.maintenance_interval_filament_g == null && capability.maintenance_interval_filament_g == null ? '' : String(source.maintenance_interval_filament_g ?? capability.maintenance_interval_filament_g ?? ''),
    lastServiceAt: source.last_service_at || capability.last_service_at || '',
    nextServiceDue: source.next_service_due || capability.next_service_due || '',
    jogEnabled: source.jog_enabled ?? capability.jog_enabled ?? true,
    safeNozzleMaxC: source.safe_nozzle_max_c == null && capability.safe_nozzle_max_c == null ? '' : String(source.safe_nozzle_max_c ?? capability.safe_nozzle_max_c ?? ''),
    safeBedMaxC: source.safe_bed_max_c == null && capability.safe_bed_max_c == null ? '' : String(source.safe_bed_max_c ?? capability.safe_bed_max_c ?? ''),
    motionCheckRequired: source.motion_check_required ?? capability.motion_check_required ?? true,
    notesText: (source.notes || capability.notes || []).join('\n'),
    maintenanceNotesText: (source.maintenance_notes || capability.maintenance_notes || []).join('\n'),
    baseUrl: source.base_url || '',
    wsUrl: source.ws_url || '',
    authMode: source.auth_mode || 'trusted_local',
    apiKey: '',  // secret is never returned by the API; blank means "keep current"
    apiKeySet: Boolean(source.api_key_set),
    apiKeyClear: false,
    serial: source.serial || '',
    uiLabel: source.ui_label || capability.ui_label || 'Open UI',
    fluiddUrl: source.fluidd_url || capability.fluidd_url || '',
    uiTargets,
  }
}

function serializePrinterSettingsDraft(draft: PrinterSettingsDraft) {
  return {
    name: draft.name.trim(),
    enabled: draft.enabled,
    tags: splitCommaList(draft.tagsText),
    nozzle_diameter_mm: numberOrNull(draft.nozzleDiameter),
    filament_diameter_mm: numberOrNull(draft.filamentDiameterMm),
    wire_used_mm_per_job: numberOrNull(draft.wireUsedMmPerJob),
    compatibility_profile: draft.compatibilityProfile.trim() || null,
    build_volume: {
      x: numberOrUndefined(draft.buildVolumeX),
      y: numberOrUndefined(draft.buildVolumeY),
      z: numberOrUndefined(draft.buildVolumeZ),
    },
    supported_materials: splitCommaList(draft.supportedMaterialsText),
    current_material: draft.currentMaterial.trim() || null,
    current_spool_name: draft.currentSpoolName.trim() || null,
    spool_remaining_g: numberOrNull(draft.spoolRemainingG),
    spool_capacity_g: numberOrNull(draft.spoolCapacityG),
    filament_sensor: draft.filamentSensor,
    probe: draft.probe,
    webcam_expected: draft.webcamExpected,
    camera_url: draft.cameraUrl.trim() || null,
    timelapse_dir: draft.timelapseDir.trim() || null,
    maintenance_lockout: draft.maintenanceLockout,
    maintenance_state: draft.maintenanceState.trim() || null,
    maintenance_due: draft.maintenanceDue,
    maintenance_interval_hours: numberOrNull(draft.maintenanceIntervalHours),
    maintenance_interval_jobs: numberOrNull(draft.maintenanceIntervalJobs),
    maintenance_interval_filament_g: numberOrNull(draft.maintenanceIntervalFilamentG),
    last_service_at: draft.lastServiceAt.trim() || null,
    next_service_due: draft.nextServiceDue.trim() || null,
    jog_enabled: draft.jogEnabled,
    safe_nozzle_max_c: numberOrNull(draft.safeNozzleMaxC),
    safe_bed_max_c: numberOrNull(draft.safeBedMaxC),
    motion_check_required: draft.motionCheckRequired,
    notes: splitLineList(draft.notesText),
    maintenance_notes: splitLineList(draft.maintenanceNotesText),
    base_url: draft.baseUrl.trim() || null,
    ws_url: draft.wsUrl.trim() || null,
    auth_mode: draft.authMode.trim() || 'trusted_local',
    // Write-only access code: explicit clear → null (revokes); a typed value →
    // set/rotate; blank → undefined → dropped by JSON.stringify → preserved.
    api_key: draft.apiKeyClear ? null : (draft.apiKey.trim() || undefined),
    serial: draft.serial.trim() || null,
    ui_label: draft.uiLabel.trim() || 'Open UI',
    fluidd_url: draft.fluiddUrl.trim() || null,
    ui_targets: ensurePrimaryUiTarget(
      draft.uiTargets
        .map((item) => ({ ...item, label: item.label.trim(), provider: item.provider.trim() || 'other', url: item.url.trim() }))
        .filter((item) => item.label && item.url),
    ),
  }
}

function ensurePrimaryUiTarget(targets: UiTargetDraft[]) {
  if (targets.length === 0) return []
  if (!targets.some((item) => item.primary)) return [{ ...targets[0], primary: true }, ...targets.slice(1).map((item) => ({ ...item, primary: false }))]
  let seenPrimary = false
  return targets.map((item) => {
    if (!item.primary || seenPrimary) return { ...item, primary: false }
    seenPrimary = true
    return item
  })
}

function mergePrinterWithSettings(printer: Printer, saved: PrinterSettingsPayload): Printer {
  const capability: PrinterCapability = {
    ...printer.capability,
    profile: saved.compatibility_profile,
    nozzle_diameter_mm: saved.nozzle_diameter_mm,
    build_volume: saved.build_volume,
    supported_materials: saved.supported_materials,
    current_material: saved.current_material,
    current_spool_name: saved.current_spool_name,
    spool_remaining_g: saved.spool_remaining_g,
    filament_sensor: saved.filament_sensor,
    probe: saved.probe,
    webcam_expected: saved.webcam_expected,
    fluidd_url: saved.fluidd_url,
    camera_url: saved.camera_url,
    ui_label: saved.ui_label,
    ui_targets: saved.ui_targets,
    maintenance_lockout: saved.maintenance_lockout,
    maintenance_state: saved.maintenance_state,
    maintenance_due: saved.maintenance_due,
    maintenance_interval_hours: saved.maintenance_interval_hours,
    maintenance_interval_jobs: saved.maintenance_interval_jobs,
    maintenance_interval_filament_g: saved.maintenance_interval_filament_g,
    last_service_at: saved.last_service_at,
    next_service_due: saved.next_service_due,
    jog_enabled: saved.jog_enabled,
    safe_nozzle_max_c: saved.safe_nozzle_max_c,
    safe_bed_max_c: saved.safe_bed_max_c,
    motion_check_required: saved.motion_check_required,
    notes: saved.notes,
    maintenance_notes: saved.maintenance_notes,
  }
  return {
    ...printer,
    name: saved.name,
    base_url: saved.base_url,
    tags: saved.tags,
    ui_targets: saved.ui_targets,
    nozzle_diameter_mm: saved.nozzle_diameter_mm,
    capability,
  }
}

function splitCommaList(value: string) {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function splitLineList(value: string) {
  return value.split(/\n+/).map((item) => item.trim()).filter(Boolean)
}

function numberOrNull(value: string) {
  if (value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function numberOrUndefined(value: string) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function capitalize(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

// ─── MatrixRow ────────────────────────────────────────────────────────────────

type MatrixRowProps = {
  printer: Printer
  isSelected: boolean
  onToggle: () => void
  onOpen: () => void
  oee: number | null
}

const MatrixRow = React.memo(function MatrixRow({ printer, isSelected, onToggle, onOpen, oee }: MatrixRowProps) {
  return (
    <div
      role="row"
      aria-selected={isSelected}
      className={`fleet-matrix-row ${!printer.online ? 'offline' : printer.job.state === 'printing' ? 'printing' : printer.job.state === 'paused' ? 'paused' : printer.attention_needed ? 'attention' : ''}${isSelected ? ' matrix-row-selected' : ''}`}
      onClick={onOpen}
      style={{ cursor: 'pointer' }}
    >
      <div className="matrix-col-select" onClick={(e) => e.stopPropagation()} role="gridcell">
        <input type="checkbox" checked={isSelected} onChange={onToggle} aria-label={`Select ${printer.name}`} />
      </div>
      <div className="matrix-col-status">{!printer.online ? '●' : printer.job.state === 'printing' ? '▶' : printer.job.state === 'paused' ? '⏸' : printer.attention_needed ? '⚠' : '○'}</div>
      <div className="matrix-col-name">{printer.name}</div>
      <div className="matrix-col-state"><span className={`state-badge state-${!printer.online ? 'offline' : printer.state}`}>{displayPrinterState(printer)}</span></div>
      <div className="matrix-col-job">{printer.job.filename || '—'}</div>
      <div className="matrix-col-temps"><ArcBar value={printer.nozzle.temperature} max={printer.capability.safe_nozzle_max_c || 300} size={44} color="oklch(0.75 0.16 84)" label="N" target={printer.nozzle.target ?? null} /></div>
      <div className="matrix-col-temps"><ArcBar value={printer.bed.temperature} max={printer.capability.safe_bed_max_c || 120} size={44} color="oklch(0.70 0.14 200)" label="B" target={printer.bed.target ?? null} /></div>
      <div className="matrix-col-progress"><ProgressRing progress={printer.job.progress} size={40} state={printer.job.state || 'idle'} /></div>
      <div className="matrix-col-oee" style={{ color: ragColor(oee == null ? null : oee * 100, { green: 85, amber: 60 }) }}>{oee == null ? '—' : `${(oee * 100).toFixed(0)}%`}</div>
      <div className="matrix-col-spool"><SpoolBar remaining={printer.capability.spool_remaining_g} max={printer.capability.spool_capacity_g ?? 1000} width={40} /></div>
      <div className="matrix-col-material">{printer.capability.current_material || '—'}</div>
      <div className="matrix-col-alerts">
        {printer.anomalies.length > 0 && <span className={`alert-badge severity-${printer.anomalies[0].severity}`}>{printer.anomalies.length}</span>}
        {printer.capability.maintenance_due && <span className="alert-badge severity-warning">svc</span>}
        {printer.online && printer.anomalies.length === 0 && !printer.capability.maintenance_due ? '—' : null}
      </div>
      <div className="matrix-col-eta">{printer.job.eta_seconds != null && printer.job.state === 'printing' ? formatDuration(printer.job.eta_seconds) : '—'}</div>
    </div>
  )
}, (prev, next) =>
  prev.printer === next.printer &&
  prev.isSelected === next.isSelected &&
  prev.oee === next.oee
)

// ─── PrinterCard ──────────────────────────────────────────────────────────────

type PrinterCardProps = {
  printer: Printer
  isSelected: boolean
  metric: FleetMetricCard | null | undefined
  oee: OeeDevice | null | undefined
  showOee: boolean
  showCardPreview: boolean
  cardPreset: string
  activeWebcamKey: string
  snapTs: number
  tempData: { nozzle: number[]; bed: number[] } | undefined
  uiMenuOpen: boolean
  tempPresets: TempPreset[]
  editingPrinterId: string | null
  editingPrinterName: string
  onToggle: () => void
  onOpenWorkspace: (section?: DrawerSection) => void
  onRunAction: (action: string) => void
  onRunCncCommand: (kind: 'estop' | 'home' | 'spindle_on' | 'spindle_off' | 'coolant_toggle') => void
  onApplyPreset: () => void
  onSetCardPreset: (label: string) => void
  onCycleWebcam: () => void
  onToggleUiMenu: () => void
  onCloseUiMenu: () => void
  onRequestConfirm: (message: string, onConfirm: () => void) => void
  onEditPrinterName: (printerId: string, name: string) => void
  onSetEditingPrinterId: (id: string | null) => void
  onSetEditingPrinterName: (name: string) => void
  onSetFleet: (fleet: FleetPayload) => void
  cardVisiblePresets: TempPreset[]
  cardMacros: MacroEntry[] | undefined
  cardMacroPins: string[]
  onLoadMacros: () => void
  onRunCardMacro: (macroName: string, params: string) => void
  onSetSpeedFactor: (factor: number) => void
  onSetFlowFactor: (factor: number) => void
  onSetTempTarget: (target: 'nozzle' | 'bed', value: number) => void
  onSetFeedRate: (rate: number) => void
  onToggleMacroPin: (macroName: string) => void
  cardLog: {msg: string, ok: boolean}[]
  onClearCardLog: () => void
  canWrite: boolean
  isAdmin: boolean
}

const PrinterCard = React.memo(function PrinterCard({
  printer, canWrite, isAdmin, isSelected, metric, oee, showOee, showCardPreview, cardPreset,
  activeWebcamKey, snapTs, tempData, uiMenuOpen, tempPresets,
  editingPrinterId, editingPrinterName,
  onToggle, onOpenWorkspace, onRunAction, onRunCncCommand, onApplyPreset,
  onSetCardPreset, onCycleWebcam, onToggleUiMenu, onCloseUiMenu, onRequestConfirm,
  onEditPrinterName, onSetEditingPrinterId, onSetEditingPrinterName, onSetFleet,
  cardVisiblePresets, cardMacros, cardMacroPins, onLoadMacros, onRunCardMacro,
  onSetSpeedFactor, onSetFlowFactor, onSetTempTarget, onSetFeedRate, onToggleMacroPin,
  cardLog, onClearCardLog,
}: PrinterCardProps) {
  const [macroOpen, setMacroOpen] = React.useState(false)
  const [localMacroParams, setLocalMacroParams] = React.useState<Record<string, string>>({})
  const [tempEditTarget, setTempEditTarget] = React.useState<'nozzle' | 'bed' | null>(null)
  const [tempInputValue, setTempInputValue] = React.useState('')
  // Live drag value for the speed/flow sliders. null = not dragging (show the live
  // printer value); a number = mid-drag (show the thumb position). Committed on release.
  const [speedDrag, setSpeedDrag] = React.useState<number | null>(null)
  const [flowDrag, setFlowDrag] = React.useState<number | null>(null)
  const [feedRateInput, setFeedRateInput] = React.useState('')
  const ptype = printerType(printer)
  const cardUiTargets = printerUiTargets(printer)
  const cardNozzleDiameter = printer.capability.nozzle_diameter_mm ?? printer.nozzle_diameter_mm ?? null
  return (
    <article className={[
        'card',
        !printer.online ? 'offline' : '',
        printer.job.state === 'printing' ? 'card-printing' : '',
        printer.job.state === 'paused' ? 'card-paused' : '',
        printer.attention_needed && printer.job.state !== 'printing' ? 'card-attention' : '',
        isSelected ? 'card-selected' : '',
      ].filter(Boolean).join(' ')}>
      <div className="card-header">
        <button
          className={`card-select-btn${isSelected ? ' card-select-btn--on' : ''}`}
          onClick={(e) => { e.stopPropagation(); onToggle() }}
          aria-label={isSelected ? 'Deselect' : 'Select'}
          aria-pressed={isSelected}
          title={isSelected ? 'Deselect this device' : 'Select this device'}
        />
        <label>
          {editingPrinterId === printer.id ? (
            <input
              type="text"
              className="printer-name-edit"
              value={editingPrinterName}
              onChange={(e) => onSetEditingPrinterName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  onEditPrinterName(printer.id, editingPrinterName)
                } else if (e.key === 'Escape') {
                  onSetEditingPrinterId(null)
                }
              }}
              onBlur={() => onSetEditingPrinterId(null)}
              autoFocus
            />
          ) : (
            <span
              className="printer-name"
              title={canWrite ? undefined : 'Rename requires operator or admin role'}
              onDoubleClick={() => {
                if (!canWrite) return
                onSetEditingPrinterId(printer.id)
                onSetEditingPrinterName(printer.name)
              }}
            >{printer.name}</span>
          )}
        </label>
        <div className="card-header-tags">
          {printer.tags.map((tag) => <span key={tag} className="tag tag-custom">{tag}</span>)}
          {printer.webcams_count > 0 && <span className="tag tag-cam">📷 Cam</span>}
          {printer.macros_count > 0 && <span className="tag tag-macro">⚡ Macros</span>}
          {ptype === 'idex' && <span className="tag tag-idex">⊕ IDEX</span>}
          {ptype === 'sla' && <span className="tag tag-sla">💧 SLA</span>}
          {(ptype === 'cnc_mill' || ptype === 'cnc_lathe' || ptype === 'cnc_router') && <span className="tag tag-cnc">⚙ CNC</span>}
          {printer.is_alpha_protocol && <span className="tag tag-alpha" title="Unverified against real hardware — control commands require a one-time liability acknowledgment">⚠ ALPHA</span>}
          {ptype === 'laser' && <span className="tag tag-laser">🔆 Laser</span>}
          {ptype === 'plasma' && <span className="tag tag-plasma">⚡ Plasma</span>}
          {ptype === 'waterjet' && <span className="tag tag-waterjet">💧 Waterjet</span>}
          {ptype === 'wire_edm' && <span className="tag tag-wire-edm">⚡ Wire EDM</span>}
          {ptype === 'vinyl' && <span className="tag tag-vinyl">🎨 Vinyl</span>}
          {ptype === 'embroidery' && <span className="tag tag-embroidery">🪡 Embroidery</span>}
          {ptype === 'pick_and_place' && <span className="tag tag-pnp">🔩 PnP</span>}
          {cardNozzleDiameter != null && ['fdm','idex'].includes(ptype) && <span className="tag tag-nozzle">⌀ {cardNozzleDiameter.toFixed(2)}</span>}
          {(printer.capability.maintenance_due || (printer.attention_needed && !printer.capability.maintenance_due && printer.anomalies.length > 0)) && <span className="tag-status-divider" aria-hidden="true" />}
          {printer.capability.maintenance_due && <span className="tag tag-service">🔧 Service</span>}
          {printer.attention_needed && !printer.capability.maintenance_due && printer.anomalies.length > 0 && <span className="tag tag-attn">⚠ Alert</span>}
        </div>
        <span className={`pill state-${printer.state}`}>{displayPrinterState(printer)}</span>
      </div>
      {printer.anomalies.length > 0 && <div role="alert" className={`warning severity-${printer.anomalies[0].severity}`}>{printer.anomalies[0].message.split('\n')[0].trim()}</div>}
      <div className={`card-body card-body-grid${showCardPreview && printer.webcams_count > 0 ? '' : ' card-body-grid--no-webcam'}`}>
        {(() => {
          const stateIconLabel = (
            <div className="card-state-panel">
              <div className="card-state-panel-icon">
                {!printer.online ? '○' : printer.job.state === 'printing' ? '▶' : printer.job.state === 'paused' ? '⏸' : printer.state === 'error' ? '✕' : '○'}
              </div>
              <div className="card-state-panel-label">{displayPrinterState(printer)}</div>
            </div>
          )
          if (showCardPreview && printer.webcams_count > 0) {
            return (
              <button
                className="card-preview card-preview-full"
                onClick={() => { if (printer.webcams_count > 1) { onCycleWebcam() } else { onOpenWorkspace('webcams') } }}
                title={printer.webcams_count > 1 ? 'Cycle to next webcam' : 'Open webcam view'}
              >
                <WebcamImage
                  printerId={printer.id}
                  camUid={activeWebcamKey}
                  snapTs={snapTs}
                  alt={`${printer.name} webcam`}
                />
                {printer.webcams_count > 1 && (
                  <div className="webcam-cycle-hint">
                    {(() => { const idx = activeWebcamKey === 'default' ? 1 : parseInt(activeWebcamKey) + 1; return `📷 ${idx}/${printer.webcams_count} — click to cycle` })()}
                  </div>
                )}
              </button>
            )
          }
          const devicePhoto = showCardPreview
            ? (DEMO_DEVICE_PHOTO[printer.id] || getDevicePhotoUrl(printer))
            : null
          if (devicePhoto) {
            return (
              <button className="card-preview card-preview-full" onClick={() => onOpenWorkspace()} title="Open device workspace">
                <Suspense fallback={<ShimmerLoader rows={1} height="200px" />}>
                  <ThreeDViewer src={devicePhoto} alt={`${printer.name} 3D model`} fallback={stateIconLabel} />
                </Suspense>
              </button>
            )
          }
          return stateIconLabel
        })()}
        <div className="card-thermal-compact">
          {(() => {
            const pt = ptype
            return (
              <div className={`thermal-gauges-compact${pt === 'idex' ? ' thermal-gauges-idex' : ''}`}>
                {pt === 'idex' ? (<>
                  <div className="thermal-unit-compact"><ArcBar value={printer.nozzle.temperature ?? 0} max={printer.capability.safe_nozzle_max_c || 300} size={48} color="oklch(0.75 0.16 84)" label="" /><span className="gauge-lbl">T0</span></div>
                  <div className="thermal-unit-compact"><ArcBar value={printer.nozzle2?.temperature ?? 0} max={printer.capability.safe_nozzle_max_c || 300} size={48} color="oklch(0.82 0.12 55)" label="" /><span className="gauge-lbl">T1</span></div>
                  <div className="thermal-unit-compact"><ArcBar value={printer.bed.temperature ?? 0} max={printer.capability.safe_bed_max_c || 120} size={48} color="oklch(0.70 0.14 200)" label="" /><span className="gauge-lbl">Bed</span></div>
                </>) : pt === 'sla' ? (
                  <div className="thermal-unit-compact"><ArcBar value={printer.bed.temperature ?? 0} max={printer.capability.safe_bed_max_c || 120} size={48} color="oklch(0.70 0.14 200)" label="" /><span className="gauge-lbl">Resin</span></div>
                ) : (pt === 'cnc_mill' || pt === 'cnc_lathe' || pt === 'cnc_router') ? (<>
                  <div className="thermal-unit-compact"><ArcBar value={printer.capability.spindle_rpm_current ?? 0} max={printer.capability.spindle_rpm_max || 24000} size={48} color="oklch(0.75 0.14 270)" label="" unit="" /><span className="gauge-lbl">Spindle</span></div>
                  <div className="thermal-unit-compact"><ArcBar value={printer.capability.feed_rate_mm_min ?? 0} max={6000} size={48} color="oklch(0.70 0.12 180)" label="" unit="" /><span className="gauge-lbl">Feed</span></div>
                </>) : pt === 'laser' ? (<>
                  <div className="thermal-unit-compact"><ArcBar value={printer.capability.laser_power_pct ?? 0} max={100} size={48} color="oklch(0.82 0.18 60)" label="" unit="%" /><span className="gauge-lbl">Power</span></div>
                  <div className="thermal-unit-compact"><ArcBar value={printer.capability.feed_rate_mm_min ?? 0} max={6000} size={48} color="oklch(0.70 0.12 180)" label="" unit="" /><span className="gauge-lbl">Feed</span></div>
                </>) : pt === 'plasma' ? (<>
                  <div className="thermal-unit-compact"><ArcBar value={printer.capability.torch_voltage ?? 0} max={200} size={48} color="oklch(0.75 0.18 200)" label="" unit="V" /><span className="gauge-lbl">Torch V</span></div>
                  <div className="thermal-unit-compact"><ArcBar value={printer.capability.feed_rate_mm_min ?? 0} max={3000} size={48} color="oklch(0.70 0.12 180)" label="" unit="" /><span className="gauge-lbl">Feed</span></div>
                </>) : pt === 'fdm' ? (<>
                  <div className="thermal-unit-compact">
                    <ArcBar value={!printer.online || printer.nozzle.temperature === 0 ? null : printer.nozzle.temperature ?? null} max={printer.capability.safe_nozzle_max_c || 300} size={48} color="oklch(0.75 0.16 84)" label="" target={printer.nozzle.target ?? null} />
                    <button className="gauge-lbl gauge-lbl-edit" disabled={!canWrite} title={canWrite ? `Target: ${printer.nozzle.target ?? 0}°. Click to edit.` : 'Requires operator or admin role'} onClick={() => { if (!canWrite) return; setTempEditTarget(tempEditTarget === 'nozzle' ? null : 'nozzle'); setTempInputValue(String(printer.nozzle.target ?? 0)) }}>
                      {(printer.nozzle.target ?? 0) > 5 ? `→ ${Math.round(printer.nozzle.target!)}°` : 'Nozzle'}{tempEditTarget === 'nozzle' ? ' ▲' : ' ▾'}
                    </button>
                    {canWrite && tempEditTarget === 'nozzle' && <input type="number" className="card-temp-input" min="0" max="300" step="5" value={tempInputValue} onChange={e => setTempInputValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { onSetTempTarget('nozzle', Number(tempInputValue)); setTempEditTarget(null) } if (e.key === 'Escape') setTempEditTarget(null) }} autoFocus />}
                  </div>
                  <div className="thermal-unit-compact">
                    <ArcBar value={!printer.online || printer.bed.temperature === 0 ? null : printer.bed.temperature ?? null} max={printer.capability.safe_bed_max_c || 120} size={48} color="oklch(0.70 0.14 200)" label="" target={printer.bed.target ?? null} />
                    <button className="gauge-lbl gauge-lbl-edit" disabled={!canWrite} title={canWrite ? `Target: ${printer.bed.target ?? 0}°. Click to edit.` : 'Requires operator or admin role'} onClick={() => { if (!canWrite) return; setTempEditTarget(tempEditTarget === 'bed' ? null : 'bed'); setTempInputValue(String(printer.bed.target ?? 0)) }}>
                      {(printer.bed.target ?? 0) > 5 ? `→ ${Math.round(printer.bed.target!)}°` : 'Bed'}{tempEditTarget === 'bed' ? ' ▲' : ' ▾'}
                    </button>
                    {canWrite && tempEditTarget === 'bed' && <input type="number" className="card-temp-input" min="0" max="120" step="5" value={tempInputValue} onChange={e => setTempInputValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { onSetTempTarget('bed', Number(tempInputValue)); setTempEditTarget(null) } if (e.key === 'Escape') setTempEditTarget(null) }} autoFocus />}
                  </div>
                </>) : null}
                <div className="thermal-unit-compact"><ProgressRing progress={printer.job.progress} size={48} state={printer.job.state || 'idle'} /><span className="gauge-lbl">Progress</span></div>
              </div>
            )
          })()}
          {['fdm','idex'].includes(ptype) ? (
            <div className="spool-compact">
              <SpoolBar remaining={printer.capability.spool_remaining_g} max={printer.capability.spool_capacity_g ?? 1000} width={100} hideLabel={true} />
              <div className="spool-meta-compact">
                <span>{formatGrams(printer.capability.spool_remaining_g)}</span>
                {printer.capability.current_material && <span className="spool-material-tag">{printer.capability.current_material}</span>}
              </div>
            </div>
          ) : (
            <div className="spool-meta-compact" style={{ justifyContent: 'center', paddingTop: '6px' }}>
              <span>Resin vat</span>
              {printer.capability.current_material && <span className="spool-material-tag">{printer.capability.current_material}</span>}
            </div>
          )}
          {canWrite && ['fdm','idex','sla'].includes(ptype) && cardVisiblePresets.length > 0 && (
            <div className="card-preheat-row">
              <select className="card-preheat-select" aria-label="Preheat preset" value={cardPreset} onChange={e => onSetCardPreset(e.target.value)}>
                {cardVisiblePresets.map(p => <option key={p.label} value={p.label}>{p.label} {p.nozzle}/{p.bed}</option>)}
              </select>
              <button className="card-preheat-btn" onClick={onApplyPreset} title={`Heat to the selected preset (${cardPreset})`}>Heat</button>
            </div>
          )}
        </div>
        <div className="card-info-section">
          {showOee && <MachineOee variant="compact" oee={oee} />}
          {printer.job.filename && (
            <div className="job-header-row">
              <span className="job-name-display">{printer.job.filename}</span>
              <span className="job-eta-display">{printer.job.eta_seconds != null && printer.job.state === 'printing' ? formatDuration(printer.job.eta_seconds) : ''}</span>
            </div>
          )}
          <div className="card-info-grouped">
            {(() => {
              const pt2 = ptype
              const jobCount = metric ? `${metric.completed_jobs}/${metric.completed_jobs + metric.failed_jobs + metric.cancelled_jobs}` : '—'
              const success = metric?.success_rate == null ? '—' : `${metric.success_rate.toFixed(1)}%`
              const maint = printer.capability.maintenance_due ? 'Due' : 'OK'
              const cncMill = pt2 === 'cnc_mill' || pt2 === 'cnc_lathe' || pt2 === 'cnc_router'
              const tiles: [string, string][] =
                pt2 === 'sla' ? [['Resin', printer.capability.current_material || '—'], ['Jobs', jobCount], ['Success', success], ['Maintenance', maint]]
                : cncMill ? [['Tool', printer.capability.tool_id || '—'], ['Material', printer.capability.current_material || '—'], ['Jobs', jobCount], ['Maintenance', maint]]
                : pt2 === 'laser' ? [['Material', printer.capability.current_material || '—'], ['Air Assist', printer.capability.air_assist_active ? 'On' : 'Off'], ['Jobs', jobCount], ['Maintenance', maint]]
                : pt2 === 'plasma' ? [['Material', printer.capability.current_material || '—'], ['THC', printer.capability.thc_active ? 'Active' : 'Off'], ['Jobs', jobCount], ['Maintenance', maint]]
                : pt2 === 'pick_and_place' ? [['Material', printer.capability.current_material || '—'], ['Jobs', jobCount], ['Success', success], ['Maintenance', maint]]
                : pt2 === 'waterjet' || pt2 === 'wire_edm' || pt2 === 'vinyl' || pt2 === 'embroidery' ? [['Material', printer.capability.current_material || '—'], ['Jobs', jobCount], ['Success', success], ['Maintenance', maint]]
                : [['Profile', displayProfileLabel(printer.capability.profile, cardNozzleDiameter)], ['Jobs', jobCount], ['Success', success], ['Maintenance', maint]]
              return tiles
            })().map(([label, value]) => (
              <div key={label} className="info-grouped-item"><span>{label}</span><strong>{value}</strong></div>
            ))}
          </div>
          <div className="printer-controls">
            {canWrite && ['fdm','idex'].includes(ptype) && (
              <div className="card-tuning-row">
                <span>Spd</span>
                <input type="range" min="50" max="150" step="5"
                  value={speedDrag ?? Math.round((printer.speed_factor ?? 1) * 100)}
                  onChange={e => setSpeedDrag(Number(e.target.value))}
                  onMouseUp={e => { onSetSpeedFactor(Number(e.currentTarget.value) / 100); setSpeedDrag(null) }}
                  onTouchEnd={e => { onSetSpeedFactor(Number(e.currentTarget.value) / 100); setSpeedDrag(null) }}
                />
                <span>{speedDrag ?? Math.round((printer.speed_factor ?? 1) * 100)}%</span>
              </div>
            )}
            {canWrite && ['fdm','idex'].includes(ptype) && (
              <div className="card-tuning-row">
                <span>Flw</span>
                <input type="range" min="50" max="150" step="5"
                  value={flowDrag ?? Math.round((printer.flow_factor ?? 1) * 100)}
                  onChange={e => setFlowDrag(Number(e.target.value))}
                  onMouseUp={e => { onSetFlowFactor(Number(e.currentTarget.value) / 100); setFlowDrag(null) }}
                  onTouchEnd={e => { onSetFlowFactor(Number(e.currentTarget.value) / 100); setFlowDrag(null) }}
                />
                <span>{flowDrag ?? Math.round((printer.flow_factor ?? 1) * 100)}%</span>
              </div>
            )}
            {canWrite && ptype === 'idex' && (
              <div className="idex-t1-control">
                <label className="idex-t1-label">T1 Target</label>
                <input type="number" className="idex-t1-input" placeholder="T1 °C" min="0" max="300" step="5"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      const temp = parseFloat((e.target as HTMLInputElement).value)
                      if (!isNaN(temp)) void apiFetch(`/api/printers/${printer.id}/temperature`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ t1_nozzle: temp }) })
                    }
                  }}
                />
              </div>
            )}
            {canWrite && QUICK_ACTIONS.filter((a) => printer.available_actions.includes(a)).map((a) => (
              <button key={a} className={`action-${a}`} onClick={() => onRunAction(a)} title={descriptionForAction(a)}>{labelForAction(a)}</button>
            ))}
            {/* Home routes through the dedicated /cnc/home endpoint (admin-only,
                matches its backend role gate — homing initiates motion, same class
                as spindle/coolant below) rather than the generic quick-action path,
                which _available_actions no longer even offers for CNC-class types. */}
            {isAdmin && isCncMachine(ptype) && (
              <button className="action-cnc" onClick={() => onRequestConfirm(`Home all axes on ${printer.name}?`, () => onRunCncCommand('home'))} title="Home all axes (move to machine origin)">⌂ Home</button>
            )}
            {/* PUT /api/devices/{id}/feed-rate/{rate} — admin+operator, matching
                its backend require_role. Adapters with unverified mm/min-vs-%
                semantics (FANUC/Fadal/Haas/Mach4) are denylisted server-side and
                surface their own clear error via the card log on submit. */}
            {canWrite && isCncMachine(ptype) && (
              <span className="feed-rate-control" style={{display:'flex', gap:4, alignItems:'center'}}>
                <input
                  type="number"
                  placeholder="Feed mm/min"
                  value={feedRateInput}
                  onChange={(e) => setFeedRateInput(e.target.value)}
                  style={{width:90, fontSize:'0.8rem'}}
                  min={0}
                  max={500}
                />
                <button
                  className="action-cnc"
                  disabled={!feedRateInput}
                  onClick={() => { const rate = Number(feedRateInput); if (!isNaN(rate)) onSetFeedRate(rate) }}
                  title="Set the feed rate override (mm/min)"
                >Set Feed</button>
              </span>
            )}
            {/* Spindle/coolant route through /cnc/gcode (raw MDI G-code), which the
                backend intentionally restricts to admin only — unlike E-Stop, which
                is deliberately opened to operator too. Gate on userRole directly
                (not canWrite) so operators don't see a button that always 403s. */}
            {isAdmin && (ptype === 'cnc_mill' || ptype === 'cnc_router' || ptype === 'cnc_lathe') && (<>
              <button className="action-cnc" onClick={() => onRunCncCommand('spindle_on')} title="Turn the spindle on">⚙ Spindle On</button>
              <button className="action-cnc" onClick={() => onRunCncCommand('spindle_off')} title="Turn the spindle off">⚙ Spindle Off</button>
              {printer.capability.coolant_active !== null && printer.capability.coolant_active !== undefined && (
                <button className="action-cnc" onClick={() => onRunCncCommand('coolant_toggle')} title={printer.capability.coolant_active ? 'Turn coolant off' : 'Turn coolant on'}>💧 Coolant</button>
              )}
            </>)}
            {/* Laser Test Fire/Frame and plasma Test Arc were removed (not
                wired to a working backend, and "working" would mean guessing
                at unverified real-hardware command sequences — energizing a
                cutting tool on a guess is a fire/eye hazard, not just a
                cosmetic bug). Re-add once verified command sequences exist. */}
            {canWrite && <button className="action-jog" onClick={() => onOpenWorkspace('jog')} title="Open manual axis jog controls">Jog</button>}
            {canWrite && <button className="action-dryrun" onClick={() => onOpenWorkspace('dryrun')} title="Run a dry run (motion without extrusion/cutting)">Dry Run</button>}
            {canWrite && <button className="action-files" onClick={() => onOpenWorkspace('files')} title="Browse and manage job files">Files</button>}
            {canWrite && <button className="action-settings" onClick={() => onOpenWorkspace('settings')} title="Open device settings">Settings</button>}
            {canWrite && (
              // E-Stop must route through the dedicated CNC endpoint for every
              // adapter-backed machine type, not just mill/router/lathe — laser,
              // plasma, waterjet, and wire_edm all run the same GRBL/LinuxCNC/etc.
              // adapters (see isCncMachine) and hit the same 404 via the
              // generic Moonraker-only /actions/emergency_stop path otherwise.
              //
              // pick_and_place is deliberately excluded: OpenPnPClient has no
              // emergency_stop implementation at all (not even a stub), and its
              // openpcb protocol isn't handled by _get_cnc_client either, so
              // there is currently no code path that can actually stop one of
              // these machines. Showing an E-Stop button that silently does
              // nothing is worse than showing none — pull it until a real,
              // verified stop exists on the adapter.
              ptype !== 'pick_and_place' && (
                <button
                  className="action-estop"
                  onClick={() => onRequestConfirm(
                    `Emergency stop ${printer.name}?`,
                    isCncMachine(ptype) ? () => onRunCncCommand('estop') : () => onRunAction('emergency_stop'),
                  )}
                  title="Immediately halt this device"
                >E-Stop</button>
              )
            )}
            {cardUiTargets.length > 0 && (
              <UiTargetMenu printerId={printer.id} label={printer.capability.ui_label || 'Open UI'} targets={cardUiTargets} open={uiMenuOpen} onToggle={onToggleUiMenu} onClose={onCloseUiMenu} />
            )}
          </div>
          {/* ── Inline macros ── */}
          {canWrite && (
          <div className="card-macros-section">
            <button className="card-macros-toggle" onClick={() => {
              if (!macroOpen) onLoadMacros()
              setMacroOpen(v => !v)
            }} title={macroOpen ? 'Collapse macros list' : 'Expand macros list'}>
              ⚡ Macros {macroOpen ? '▲' : '▼'}
              {!macroOpen && cardMacroPins.length > 0 && <span className="card-macros-pin-count"> · {cardMacroPins.length} pinned</span>}
            </button>
            {macroOpen && (
              <div className="card-macros-body">
                {!cardMacros && <div className="subtle small">Loading…</div>}
                {cardMacros && cardMacros.length === 0 && <div className="subtle small">No macros detected.</div>}
                {cardMacros && [...cardMacros].sort((a, b) => {
                  const ap = cardMacroPins.includes(a.name), bp = cardMacroPins.includes(b.name)
                  return ap === bp ? a.name.localeCompare(b.name) : ap ? -1 : 1
                }).map(macro => (
                  <div key={macro.name} className={`card-macro-row${cardMacroPins.includes(macro.name) ? ' pinned' : ''}`}>
                    <button className="card-macro-btn" onClick={() => void onRunCardMacro(macro.name, localMacroParams[macro.name] || '')} title={macro.name}>
                      {macro.name}
                    </button>
                    <input
                      className="card-macro-params"
                      placeholder="params"
                      value={localMacroParams[macro.name] || ''}
                      onChange={e => setLocalMacroParams(p => ({ ...p, [macro.name]: e.target.value }))}
                      onKeyDown={e => { if (e.key === 'Enter') { void onRunCardMacro(macro.name, localMacroParams[macro.name] || ''); e.preventDefault() } }}
                    />
                    <button className={`card-macro-pin${cardMacroPins.includes(macro.name) ? ' pinned' : ''}`} title={cardMacroPins.includes(macro.name) ? 'Unpin' : 'Pin'} onClick={() => onToggleMacroPin(macro.name)}>
                      {cardMacroPins.includes(macro.name) ? '★' : '☆'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          )}
        </div>
        {cardLog.length > 0 && (
          <div className="card-output-log">
            <div className="card-log-header">
              <span>Output</span>
              <button className="card-log-clear" onClick={onClearCardLog} title="Clear">✕</button>
            </div>
            {cardLog.map((entry, i) => (
              <div key={i} className={`card-log-entry${entry.ok ? '' : ' log-error'}`}>{entry.msg}</div>
            ))}
          </div>
        )}
        {(tempData?.nozzle?.length ?? 0) > 0 && printer.job.state === 'printing' && (
          <div className="card-sparkline-row">
            <Sparkline nozzle={tempData?.nozzle || []} bed={tempData?.bed || []} id={printer.id} height={24} />
          </div>
        )}
      </div>
    </article>
  )
}, (prev, next) =>
  prev.printer === next.printer &&
  prev.isSelected === next.isSelected &&
  prev.metric === next.metric &&
  prev.oee === next.oee &&
  prev.showOee === next.showOee &&
  prev.showCardPreview === next.showCardPreview &&
  prev.cardPreset === next.cardPreset &&
  prev.activeWebcamKey === next.activeWebcamKey &&
  prev.snapTs === next.snapTs &&
  prev.tempData === next.tempData &&
  prev.uiMenuOpen === next.uiMenuOpen &&
  prev.tempPresets === next.tempPresets &&
  prev.cardMacros === next.cardMacros &&
  prev.cardMacroPins === next.cardMacroPins &&
  prev.editingPrinterId === next.editingPrinterId &&
  prev.editingPrinterName === next.editingPrinterName
)

const ArcBar = React.memo(function ArcBar({ value, max, size = 56, color = 'var(--accent-solid)', label, unit = '°', target }: { value: number | null, max: number, size?: number, color?: string, label: string, unit?: string, target?: number | null }) {
  if (value === null || value === undefined) return <div style={{ height: size, textAlign: 'center', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>—</div>
  const r = (size - 8) / 2
  const circumference = Math.PI * r
  const currentF = max > 0 ? Math.min(value / max, 1) : 0
  const strokeDashoffset = circumference * (1 - currentF)
  const fmt = unit === '°' ? `${Math.round(value)}°` : value >= 1000 ? `${(value / 1000).toFixed(1)}k${unit}` : `${Math.round(value)}${unit}`
  const base = r + 4
  const w = base + 6
  // Target indicator: draw dim gap-arc from current to target + tick at target
  const targetF = (max > 0 && target != null && target > 5) ? Math.min(target / max, 1) : null
  const heating = targetF != null && targetF > currentF + 0.01
  const cooling = targetF != null && targetF < currentF - 0.01
  // Gap arc covers current→target (heating) or target→current (cooling)
  const gapStart = heating ? currentF : (cooling ? targetF! : null)
  const gapEnd   = heating ? targetF! : (cooling ? currentF : null)
  const gapLen   = gapStart != null ? (gapEnd! - gapStart) * circumference : 0
  const skipLen  = gapStart != null ? gapStart * circumference : 0
  // Tick position on arc
  const cx = size / 2, cy = base
  const tickX = targetF != null ? cx - r * Math.cos(Math.PI * targetF) : null
  const tickY = targetF != null ? cy - r * Math.sin(Math.PI * targetF) : null
  return (
    <svg viewBox={`0 0 ${size} ${w}`} width={size} height={w}>
      <path d={`M 4 ${base} A ${r} ${r} 0 0 1 ${size - 4} ${base}`} stroke="var(--border-default)" strokeWidth="2.5" fill="none" />
      <path d={`M 4 ${base} A ${r} ${r} 0 0 1 ${size - 4} ${base}`} stroke={color} strokeWidth="2.5" fill="none" strokeDasharray={circumference} strokeDashoffset={strokeDashoffset} strokeLinecap="round" />
      {gapStart != null && gapLen > 0 && (
        <path d={`M 4 ${base} A ${r} ${r} 0 0 1 ${size - 4} ${base}`}
          stroke={heating ? 'oklch(0.78 0.14 55 / 0.55)' : 'oklch(0.60 0.10 220 / 0.45)'}
          strokeWidth="2" fill="none"
          strokeDasharray={`0 ${skipLen} ${gapLen} 9999`}
        />
      )}
      {tickX != null && tickY != null && (
        <circle cx={tickX} cy={tickY} r="2.5"
          fill={heating ? 'oklch(0.85 0.16 55)' : 'oklch(0.65 0.12 220)'}
          stroke="var(--surface-base)" strokeWidth="1"
        />
      )}
      <text x={size / 2} y={base} textAnchor="middle" dominantBaseline="auto" style={{ fontSize: `${size * 0.28}px`, fontWeight: 700, fill: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
        {fmt}
      </text>
    </svg>
  )
})

const ProgressRing = React.memo(function ProgressRing({ progress, size = 52, state = 'idle' }: { progress: number | null, size?: number, state?: string }) {
  if (progress === null || progress === undefined) progress = 0
  const r = (size - 8) / 2
  const circumference = Math.PI * r
  const strokeDashoffset = circumference * (1 - Math.min(progress / 100, 1))
  const color = state === 'printing' ? 'var(--color-success)' : state === 'paused' ? 'var(--color-warning)' : 'var(--surface-l3)'
  const base = r + 4
  const h = base + 6
  return (
    <svg viewBox={`0 0 ${size} ${h}`} width={size} height={h}>
      <path d={`M 4 ${base} A ${r} ${r} 0 0 1 ${size - 4} ${base}`} stroke="var(--border-default)" strokeWidth="2.5" fill="none" />
      <path d={`M 4 ${base} A ${r} ${r} 0 0 1 ${size - 4} ${base}`} stroke={color} strokeWidth="2.5" fill="none" strokeDasharray={circumference} strokeDashoffset={strokeDashoffset} strokeLinecap="round" />
      <text x={size / 2} y={base} textAnchor="middle" dominantBaseline="auto" style={{ fontSize: `${size * 0.28}px`, fontWeight: 700, fill: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
        {progress.toFixed(0)}%
      </text>
    </svg>
  )
})

const SpoolBar = React.memo(function SpoolBar({ remaining, max = 1000, width = 120, hideLabel = false }: { remaining: number | null, max?: number, width?: number, hideLabel?: boolean }) {
  if (remaining === null || remaining === undefined) return <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>—</div>
  const pct = max > 0 ? Math.min(remaining / max, 1) : 0
  const color = remaining > 400 ? 'var(--color-success)' : remaining > 100 ? 'var(--color-warning)' : 'var(--color-danger)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem' }}>
      <svg viewBox={`0 0 ${width} 10`} width={width} height="10" style={{ flexShrink: 0 }}>
        <rect x="1" y="1" width={width - 2} height="8" stroke="var(--border-default)" fill="none" rx="2" />
        <rect x="1" y="1" width={(width - 2) * pct} height="8" fill={color} rx="2" />
      </svg>
      {!hideLabel && <strong>{remaining.toFixed(0)}g</strong>}
    </div>
  )
})

/** Try MJPEG stream first; fall back to snapshot polling on error. Retries stream after 15s. */
const TimelapseMedia = React.memo(function TimelapseMedia({ printerId, name, showVideo }: { printerId: string; name: string; showVideo: boolean }) {
  const [blobUrl, setBlobUrl] = React.useState<string | null>(null)
  const [downloading, setDownloading] = React.useState(false)
  const [loading, setLoading] = React.useState(false)

  // /timelapse/{name} requires a Bearer header, which neither <video src> nor
  // <a href download> can carry — fetch once via apiFetch and reuse the blob URL
  // for both playback and download. Fetched ON DEMAND (button click), NOT on
  // mount, so opening the timelapse tab doesn't download every video in full.
  const ensureBlob = React.useCallback(async (): Promise<string | null> => {
    if (blobUrl) return blobUrl
    setLoading(true)
    try {
      const res = await apiFetch(`/api/printers/${printerId}/timelapse/${encodeURIComponent(name)}`)
      if (!res.ok) return null
      const url = URL.createObjectURL(await res.blob())
      setBlobUrl(url)
      return url
    } catch {
      return null
    } finally {
      setLoading(false)
    }
  }, [printerId, name, blobUrl])

  React.useEffect(() => {
    return () => { if (blobUrl) URL.revokeObjectURL(blobUrl) }
  }, [blobUrl])

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const url = await ensureBlob()
      if (!url) return
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
    } finally {
      setDownloading(false)
    }
  }

  return (
    <>
      {showVideo && (blobUrl
        ? <video src={blobUrl} controls style={{width:'100%',maxHeight:200,marginTop:6}} />
        : <button onClick={() => { void ensureBlob() }} disabled={loading} className="action-btn">{loading ? 'Loading…' : '▶ Load video'}</button>
      )}
      <button onClick={() => { void handleDownload() }} disabled={downloading} className="action-btn">⬇ Download</button>
    </>
  )
})

const WebcamImage = React.memo(function WebcamImage({ printerId, camUid, snapTs, alt }: { printerId: string; camUid: string; snapTs: number; alt: string }) {
  const [streamTicketUrl, setStreamTicketUrl] = React.useState<string | null>(null)
  const [snapshotBlobUrl, setSnapshotBlobUrl] = React.useState<string | null>(null)
  const [useFallback, setUseFallback] = React.useState(false)
  const retryTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  // The MJPEG stream is a bare <img src> target, which can't carry a Bearer
  // header — mint a single-use ticket (same mechanism /ws/fleet uses) and
  // put it in the query string instead. Re-minted on mount and on every
  // stream-error retry, since each is a fresh connection attempt.
  React.useEffect(() => {
    let cancelled = false
    const mintStream = async () => {
      try {
        const res = await apiFetch('/api/ws/ticket', { method: 'POST' })
        if (!res.ok || cancelled) return
        const data = await res.json()
        if (cancelled) return
        setStreamTicketUrl(`${API_BASE}/api/printers/${printerId}/webcams/${encodeURIComponent(camUid)}/stream?ticket=${encodeURIComponent(data.ticket)}`)
      } catch {
        // leave streamTicketUrl unset; snapshot fallback still covers it
      }
    }
    void mintStream()
    return () => { cancelled = true }
  }, [printerId, camUid])

  const mintStreamUrl = React.useCallback(async () => {
    try {
      const res = await apiFetch('/api/ws/ticket', { method: 'POST' })
      if (!res.ok) return
      const data = await res.json()
      setStreamTicketUrl(`${API_BASE}/api/printers/${printerId}/webcams/${encodeURIComponent(camUid)}/stream?ticket=${encodeURIComponent(data.ticket)}`)
    } catch {
      // leave streamTicketUrl unset; snapshot fallback still covers it
    }
  }, [printerId, camUid])

  const handleStreamError = React.useCallback(() => {
    setUseFallback(true)
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    retryTimerRef.current = setTimeout(() => { setUseFallback(false); void mintStreamUrl() }, 15000)
  }, [mintStreamUrl])
  React.useEffect(() => () => { if (retryTimerRef.current) clearTimeout(retryTimerRef.current) }, [])

  // Snapshot fallback: same auth problem, same fix already used for the
  // floorplan image — fetch via apiFetch (Bearer header) and swap in a blob
  // URL. Revocation centralized in the effect below (fires on replacement
  // and unmount), matching floorplan's pattern.
  React.useEffect(() => {
    let cancelled = false
    apiFetch(`/api/printers/${printerId}/webcams/${encodeURIComponent(camUid)}/snapshot?ts=${encodeURIComponent(String(snapTs))}`)
      .then(async (res) => {
        if (!res.ok || cancelled) return
        const blob = await res.blob()
        if (cancelled) return
        setSnapshotBlobUrl(URL.createObjectURL(blob))
      }).catch(() => undefined)
    return () => { cancelled = true }
  }, [printerId, camUid, snapTs])

  React.useEffect(() => {
    return () => { if (snapshotBlobUrl) URL.revokeObjectURL(snapshotBlobUrl) }
  }, [snapshotBlobUrl])

  if (useFallback || !streamTicketUrl) {
    return snapshotBlobUrl
      ? <img src={snapshotBlobUrl} alt={alt} loading="lazy" />
      : <div className="webcam-placeholder subtle small">Loading…</div>
  }
  return <img src={streamTicketUrl} alt={alt} loading="lazy" onError={handleStreamError} />
})

const Sparkline = React.memo(function Sparkline({ nozzle, bed, width = 160, height = 44, id }: { nozzle: number[], bed: number[], width?: number, height?: number, id?: string }) {
  if (!nozzle.length || !bed.length) return <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>—</div>
  const maxTemp = 300
  const pointSpacing = width / Math.max(nozzle.length - 1, 1)
  const yScale = (temp: number) => height - (temp / maxTemp) * height
  const nozzlePath = nozzle.map((t, i) => `${i * pointSpacing},${yScale(t)}`).join('L')
  const bedPath = bed.map((t, i) => `${i * pointSpacing},${yScale(t)}`).join('L')
  const nozzleLastX = (nozzle.length - 1) * pointSpacing
  const bedLastX = (bed.length - 1) * pointSpacing
  const nozzleGradId = `nozzleGrad-${id ?? '0'}`
  const bedGradId = `bedGrad-${id ?? '0'}`
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={nozzleGradId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="oklch(0.75 0.16 84 / 0.3)" />
          <stop offset="100%" stopColor="oklch(0.75 0.16 84 / 0.01)" />
        </linearGradient>
        <linearGradient id={bedGradId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="oklch(0.70 0.14 200 / 0.3)" />
          <stop offset="100%" stopColor="oklch(0.70 0.14 200 / 0.01)" />
        </linearGradient>
      </defs>
      <path d={`M ${nozzlePath} L ${nozzleLastX},${height} L 0,${height} Z`} stroke="oklch(0.75 0.16 84)" strokeWidth="1.5" fill={`url(#${nozzleGradId})`} />
      <path d={`M ${bedPath} L ${bedLastX},${height} L 0,${height} Z`} stroke="oklch(0.70 0.14 200)" strokeWidth="1.5" fill={`url(#${bedGradId})`} />
    </svg>
  )
})


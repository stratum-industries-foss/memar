/**
 * Predefined metadata for Klipper built-in calibration and tuning functions.
 * These are not user-defined [gcode_macro] entries but Klipper command objects
 * created by config sections like [bed_mesh], [z_tilt], etc.
 *
 * Backend support status:
 * - ✅ Fully parsed (config_discovery.py): z_tilt, bed_mesh, quad_gantry_level, probe
 * - ❌ Requires backend addition: delta_calibrate, axis_twist_compensation, screws_tilt_adjust
 * - ✅ Always available: pid_calibrate (universal Klipper command, no section required)
 *
 * TODO(post-launch): Update config_discovery.py to parse [delta_calibrate],
 * [axis_twist_compensation], and [screws_tilt_adjust] sections. Track in:
 * https://github.com/stratum-industries/memar/issues/XXXX
 */

export type BuiltInMacroDefinition = {
  name: string
  icon: string
  description: string
  category: string
  configSection: string | null // null if always available or requires backend update
  params?: Record<string, { type: 'int' | 'float' | 'string'; default?: string | number | null; description?: string }>
  destructive: boolean
  requiresInteractiveMode?: boolean
  backendParsed: boolean // true if config section is currently parsed by backend
  machineTypes?: string[]
}

export const BUILTIN_MACROS: Record<string, BuiltInMacroDefinition> = {
  Z_TILT_ADJUST: {
    name: 'Z_TILT_ADJUST',
    icon: '🔧',
    description: 'Adjust Z stepper motor positions to compensate for an uneven bed. Requires probe and multiple Z motors.',
    category: 'Calibration',
    configSection: 'z_tilt',
    params: {
      RETRY_TOLERANCE: { type: 'float', default: 0.0075, description: 'Allowable deviation from mean (mm)' },
      RETRIES: { type: 'int', default: 0, description: 'Number of retry attempts' },
    },
    destructive: false,
    backendParsed: true,
    machineTypes: ['CartesianXY', 'CoreXY'],
  },
  BED_MESH_CALIBRATE: {
    name: 'BED_MESH_CALIBRATE',
    icon: '📊',
    description: 'Perform automatic bed mesh probing to map surface contours and enable mesh compensation during printing.',
    category: 'Calibration',
    configSection: 'bed_mesh',
    params: {
      PROFILE: { type: 'string', description: 'Mesh profile name (default: current)' },
      METHOD: { type: 'string', description: 'Probing method (automatic)' },
    },
    destructive: false,
    backendParsed: true,
    machineTypes: ['CartesianXY', 'CoreXY', 'Delta'],
  },
  QUAD_GANTRY_LEVEL: {
    name: 'QUAD_GANTRY_LEVEL',
    icon: '🔧',
    description: 'Level gantry by adjusting four independent Z stepper motors (CoreXY printers with Z axis on four corners).',
    category: 'Calibration',
    configSection: 'quad_gantry_level',
    params: {
      RETRY_TOLERANCE: { type: 'float', default: 0.0075, description: 'Allowable deviation from mean (mm)' },
      RETRIES: { type: 'int', default: 0, description: 'Number of retry attempts' },
    },
    destructive: false,
    backendParsed: true,
    machineTypes: ['CoreXY'],
  },
  PROBE_CALIBRATE: {
    name: 'PROBE_CALIBRATE',
    icon: '📍',
    description: 'Interactive Z-offset probe calibration. Enters manual probe mode—requires TESTZ, ACCEPT, or ABORT commands. Do not use as fire-and-forget.',
    category: 'Probing',
    configSection: 'probe',
    destructive: false,
    backendParsed: true,
    requiresInteractiveMode: true,
  },
  PID_CALIBRATE: {
    name: 'PID_CALIBRATE',
    icon: '⚙️',
    description: 'Auto-tune proportional-integral-derivative (PID) values for extruder and bed heaters. Takes 5–10 minutes.',
    category: 'Tuning',
    configSection: null,
    params: {
      HEATER: { type: 'string', description: 'Heater name: extruder, heater_bed, or custom', default: 'extruder' },
      TARGET: { type: 'float', description: 'Target temperature (°C)', default: 210 },
      WRITE_FILE: { type: 'int', description: 'Write results to printer.cfg (0=no, 1=yes)', default: 0 },
    },
    destructive: false,
    backendParsed: true, // Always available, not section-dependent
  },
  DELTA_CALIBRATE: {
    name: 'DELTA_CALIBRATE',
    icon: '🔺',
    description: 'Calibrate arm length offsets for Delta printers. Requires probe and proper [delta_calibrate] configuration.',
    category: 'Calibration',
    configSection: 'delta_calibrate',
    destructive: false,
    backendParsed: false, // Backend not yet parsing this section
    machineTypes: ['Delta'],
  },
  AXIS_TWIST_COMPENSATION_CALIBRATE: {
    name: 'AXIS_TWIST_COMPENSATION_CALIBRATE',
    icon: '📐',
    description: 'Calibrate linear sensor offset caused by frame twist (e.g., from gantry sag). Probes points across X axis at varying Y positions.',
    category: 'Calibration',
    configSection: 'axis_twist_compensation',
    destructive: false,
    backendParsed: false, // Backend not yet parsing this section
  },
  SCREWS_TILT_ADJUST: {
    name: 'SCREWS_TILT_ADJUST',
    icon: '🔩',
    description: 'Interactive manual bed leveling. Probes bed screw positions and reports how many turns to adjust each screw. Requires operator feedback.',
    category: 'Calibration',
    configSection: 'screws_tilt_adjust',
    destructive: false,
    backendParsed: false, // Backend not yet parsing this section
    requiresInteractiveMode: true,
  },
}

/**
 * Determine which built-in macros are available based on Klipper config capabilities.
 *
 * Maps backend config flags (has_<section>) to macro definitions. Returns all 8 macros,
 * but only those with backendParsed=true are conditionally enabled/disabled. The three
 * with backendParsed=false will always appear but show a "requires backend update" note.
 *
 * @param config - The klipper_config object from /api/printers/{id}/klipper-config
 * @returns Array of available BuiltInMacroDefinition objects, sorted by name
 */
export function getAvailableBuiltins(config: Record<string, unknown>): BuiltInMacroDefinition[] {
  const available: BuiltInMacroDefinition[] = []

  // Map config flags (backend-parsed sections) to macro definitions
  const configToMacro: Record<string, string> = {
    has_z_tilt: 'Z_TILT_ADJUST',
    has_bed_mesh: 'BED_MESH_CALIBRATE',
    has_quad_gantry_level: 'QUAD_GANTRY_LEVEL',
    has_probe: 'PROBE_CALIBRATE',
  }

  // Add backend-parsed functions if their config sections exist
  for (const [configKey, macroName] of Object.entries(configToMacro)) {
    if (config[configKey] === true) {
      const def = BUILTIN_MACROS[macroName]
      if (def) available.push(def)
    }
  }

  // PID_CALIBRATE is always available (universal Klipper command, no section required)
  available.push(BUILTIN_MACROS.PID_CALIBRATE)

  // Add three macros pending backend updates
  // These will appear but show "requires backend update" status in the UI
  available.push(BUILTIN_MACROS.DELTA_CALIBRATE)
  available.push(BUILTIN_MACROS.AXIS_TWIST_COMPENSATION_CALIBRATE)
  available.push(BUILTIN_MACROS.SCREWS_TILT_ADJUST)

  return available.sort((a, b) => a.name.localeCompare(b.name))
}

/**
 * Check if a built-in function requires backend config parsing before use.
 * @param macroName - The name of the built-in macro
 * @returns true if the backend has parsed the required config section
 */
export function isBackendParsed(macroName: string): boolean {
  return BUILTIN_MACROS[macroName]?.backendParsed ?? false
}

/**
 * Get human-readable status message for a built-in function.
 * @param macro - The BuiltInMacroDefinition
 * @returns Status message, or null if fully supported
 */
export function getBuiltinStatus(macro: BuiltInMacroDefinition): string | null {
  if (!macro.backendParsed && macro.configSection) {
    return `Requires backend update to parse [${macro.configSection}] config section. See TODO in code.`
  }
  if (macro.requiresInteractiveMode) {
    return 'Interactive mode required—enters manual probe/adjustment state. Requires user commands to complete.'
  }
  return null
}

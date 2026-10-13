// G-code console input behaviour: command history (shell-style up/down) and
// TAB autocompletion against the printer's macros plus a static command list.
//
// Kept out of App.tsx deliberately: the logic is pure and worth unit-testing,
// and App.tsx is a 7k-line component that can't be rendered in jsdom without
// standing up auth, WebSockets and the whole fleet-poll machinery.

/**
 * Static autocomplete vocabulary. Klipper/Marlin commands that are safe to
 * *suggest* — suggesting is not sending, so including e.g. EMERGENCY_STOP is
 * fine (the user still has to hit Enter).
 *
 * Macros reported by the printer are merged in at match time, so this list
 * only needs to cover what the macro endpoint doesn't return: raw G/M codes
 * and built-in Klipper extended commands.
 */
export const GCODE_COMMANDS: readonly string[] = [
  // Motion / positioning
  'G0', 'G1', 'G28', 'G29', 'G30', 'G32', 'G80', 'G81', 'G90', 'G91', 'G92',
  // Temperature
  'M104', 'M109', 'M140', 'M190', 'M191',
  // Fans
  'M106', 'M107',
  // Limits / tuning
  'M203', 'M204', 'M205', 'M207', 'M208', 'M209', 'M220', 'M221', 'M290',
  // Misc Marlin-flavoured
  'M105', 'M112', 'M114', 'M115', 'M117', 'M300', 'M400', 'M500', 'M503',
  'M600', 'M900',
  // Klipper extended commands
  'ACCELEROMETER_QUERY',
  'BED_MESH_CALIBRATE',
  'BED_MESH_CLEAR',
  'BED_MESH_OUTPUT',
  'BED_MESH_PROFILE',
  'CANCEL_PRINT',
  'EMERGENCY_STOP',
  'FIRMWARE_RESTART',
  'GET_POSITION',
  'HELP',
  'MEASURE_AXES_NOISE',
  'PAUSE',
  'PID_CALIBRATE',
  'PROBE',
  'PROBE_ACCURACY',
  'PROBE_CALIBRATE',
  'QUAD_GANTRY_LEVEL',
  'QUERY_ENDSTOPS',
  'QUERY_PROBE',
  'RESPOND',
  'RESTART',
  'RESUME',
  'SAVE_CONFIG',
  'SCREWS_TILT_CALCULATE',
  'SDCARD_PRINT_FILE',
  'SDCARD_RESET_FILE',
  'SET_FAN_SPEED',
  'SET_GCODE_OFFSET',
  'SET_HEATER_TEMPERATURE',
  'SET_PRESSURE_ADVANCE',
  'SET_VELOCITY_LIMIT',
  'SHAPER_CALIBRATE',
  'STATUS',
  'STEPPER_BUZZ',
  'TEST_RESONANCES',
  'TURN_OFF_HEATERS',
  'Z_ENDSTOP_CALIBRATE',
  'Z_TILT_ADJUST',
]

/** Cap on persisted history so localStorage can't grow without bound. */
export const CONSOLE_HISTORY_LIMIT = 100

export function consoleHistoryKey(printerId: string): string {
  return `memar_console_history_${printerId}`
}

/** Read a printer's console history from localStorage. Never throws. */
export function loadConsoleHistory(printerId: string): string[] {
  if (!printerId) return []
  try {
    const raw = localStorage.getItem(consoleHistoryKey(printerId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is string => typeof item === 'string').slice(-CONSOLE_HISTORY_LIMIT)
  } catch {
    return []
  }
}

/** Write a printer's console history to localStorage. Never throws. */
export function saveConsoleHistory(printerId: string, history: string[]): void {
  if (!printerId) return
  try {
    localStorage.setItem(consoleHistoryKey(printerId), JSON.stringify(history.slice(-CONSOLE_HISTORY_LIMIT)))
  } catch {
    /* quota exceeded / storage disabled — history is a convenience, not state we owe the user */
  }
}

/**
 * Append a command, deduping against the most recent entry only (so a repeated
 * command doesn't pile up, but A B A stays A B A). Returns a new array; the
 * input is not mutated.
 */
export function appendConsoleHistory(history: string[], command: string): string[] {
  const trimmed = command.trim()
  if (!trimmed) return history
  if (history.length > 0 && history[history.length - 1] === trimmed) return history
  return [...history, trimmed].slice(-CONSOLE_HISTORY_LIMIT)
}

/**
 * Commands matching `prefix`, case-insensitively, sorted for stable cycling.
 * An empty prefix matches nothing — TAB on an empty input should do nothing
 * rather than dump the entire vocabulary into the field.
 *
 * A prefix containing whitespace also matches nothing: by then the user is
 * typing arguments (`M104 S200`), not a command name.
 */
export function completionCandidates(prefix: string, macroNames: readonly string[] = []): string[] {
  const needle = prefix.trim()
  if (!needle || /\s/.test(needle)) return []
  const lower = needle.toLowerCase()
  const seen = new Set<string>()
  const out: string[] = []
  for (const name of [...macroNames, ...GCODE_COMMANDS]) {
    if (!name) continue
    const key = name.toLowerCase()
    if (!key.startsWith(lower)) continue
    if (seen.has(key)) continue
    seen.add(key)
    out.push(name)
  }
  return out.sort((a, b) => a.localeCompare(b))
}

/** Transient TAB-cycle bookkeeping. `index` of -1 means "no cycle in progress". */
export type CompletionCycle = { prefix: string; index: number }

export const NO_COMPLETION_CYCLE: CompletionCycle = { prefix: '', index: -1 }

export type ConsoleKeyState = {
  input: string
  history: string[]
  /** Cursor into `history`. Equal to `history.length` means "not browsing". */
  historyIndex: number
  cycle: CompletionCycle
}

export type ConsoleKeyResult = {
  input: string
  historyIndex: number
  cycle: CompletionCycle
}

/**
 * Pure keydown reducer for the console input. Returns `null` for keys it does
 * not own (the caller then handles Enter etc. as before), and calls
 * `preventDefault()` for the keys it does — TAB would otherwise move focus out
 * of the field, and the arrows would jump the caret to the start/end of the
 * line.
 */
export function handleConsoleKey(
  event: { key: string; preventDefault: () => void },
  state: ConsoleKeyState,
  macroNames: readonly string[] = [],
): ConsoleKeyResult | null {
  const { key } = event

  if (key === 'ArrowUp' || key === 'ArrowDown') {
    event.preventDefault()
    const { history } = state
    if (history.length === 0) {
      return { input: state.input, historyIndex: 0, cycle: NO_COMPLETION_CYCLE }
    }
    // historyIndex is clamped into [0, history.length]; the upper bound is the
    // "past the newest entry" sentinel that shows an empty input.
    const current = Math.min(Math.max(state.historyIndex, 0), history.length)
    const next = key === 'ArrowUp'
      ? Math.max(0, current - 1)
      : Math.min(history.length, current + 1)
    return {
      input: next === history.length ? '' : history[next],
      historyIndex: next,
      cycle: NO_COMPLETION_CYCLE,
    }
  }

  if (key === 'Tab') {
    const cycling = state.cycle.index >= 0 && state.cycle.prefix !== ''
    const prefix = cycling ? state.cycle.prefix : state.input
    const candidates = completionCandidates(prefix, macroNames)
    if (candidates.length === 0) {
      return { input: state.input, historyIndex: state.historyIndex, cycle: NO_COMPLETION_CYCLE }
    }
    event.preventDefault()
    const index = cycling ? (state.cycle.index + 1) % candidates.length : 0
    return {
      input: candidates[index],
      historyIndex: state.historyIndex,
      cycle: { prefix, index },
    }
  }

  return null
}

/**
 * Temperature utilities and types.
 *
 * Extracted from App.tsx to support modular temperature management.
 * Provides:
 *  - Type definitions for temperature presets and printer state
 *  - Parsing logic for temperature input validation
 *  - Machine type classification for thermal control gating
 */

import type { PrinterCapability, HeaterStatus } from './types.printer'

/**
 * Temperature preset definition.
 *
 * Used to store and retrieve commonly-used nozzle/bed combinations.
 * builtin is true for factory presets (e.g., "PLA", "ABS"), false for user-created ones.
 */
export type TempPreset = {
  label: string
  nozzle: number
  bed: number
  builtin?: boolean
}

/**
 * Minimal printer interface for the Temperature drawer.
 *
 * Extracted from the full Printer type to keep the drawer's dependency surface small.
 * Includes:
 *  - Machine type classification (for thermal gating)
 *  - Current and target heater state
 *  - Capability metadata (safe limits)
 */
export type TemperatureDrawerPrinter = {
  id: string
  name: string
  nozzle: HeaterStatus
  nozzle2?: HeaterStatus
  bed: HeaterStatus
  capability: PrinterCapability
}

/**
 * Machine types that support thermal control (heaters).
 *
 * Excludes:
 *  - CNC machines (no thermal control)
 *  - Non-thermal 3D printers (SLA, Resin, StereoLith)
 *  - Pick-and-place, embroidery, etc. (no heaters)
 *
 * Includes:
 *  - FDM, IDEX (dual extrusion)
 *  - Anything else that has nozzle/bed heaters
 *
 * Used to gate temperature controls in the UI: a laser cutter's drawer shouldn't
 * show a "Set nozzle temperature" button.
 */
export const THERMAL_MACHINE_TYPES: readonly string[] = [
  'fdm',
  'sla', // Actually has heated build platform; included for completeness
  'idex', // Dual extrusion, same thermal profile as FDM
] as const

/**
 * Check if a machine type supports thermal control.
 *
 * @param machineType - Machine type from printer.capability.machine_type
 * @returns true if this machine type has heaters
 */
export function isThermalMachine(machineType?: string): boolean {
  return !!machineType && (THERMAL_MACHINE_TYPES as readonly string[]).includes(machineType)
}

/**
 * Parse a temperature input string into a numeric value.
 *
 * Handles:
 *  - Valid numbers: "210" → 210
 *  - Floats: "210.5" → 210.5
 *  - Whitespace: "  210  " → 210
 *  - Empty string: "" → 0 (user cleared the field, treat as intent to cool)
 *  - Invalid input: "abc" → NaN (caller must gate with Number.isFinite)
 *
 * The NaN case is intentional — it forces the caller to explicitly handle invalid input
 * rather than silently falling back to 0 or 300.
 *
 * @param target - Input value to parse
 * @returns Parsed number or NaN if unparseable
 */
export function parseTarget(target: unknown): number {
  if (typeof target === 'number') return target
  if (typeof target === 'string') return Number(target.trim())
  return NaN
}

/**
 * Format a temperature reading for display.
 *
 * Shows current temperature and target in the format:
 *  - "210 / 60" if both are known
 *  - "210 / —" if target is null
 *  - "— / 60" if current is null
 *  - "— / —" if both are null
 *
 * @param current - Current heater temperature in °C (or null if unknown)
 * @param target - Target temperature in °C (or null if not set)
 * @returns Formatted string suitable for display
 */
export function formatTemperature(current: number | null, target: number | null): string {
  const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
  return `${fmt(current)} / ${fmt(target)}`
}

/**
 * Calculate the range for a temperature graph.
 *
 * Given a set of temperature data points, expand the range slightly to avoid
 * graphing edge-to-edge (axis ticks need breathing room).
 *
 * @param temperatures - Array of temperature values in °C
 * @returns [minTemp, maxTemp] suitable for SVG viewBox or axis scaling
 */
export function calculateTempRange(temperatures: number[]): [min: number, max: number] {
  if (temperatures.length === 0) return [0, 100]
  const min = Math.min(...temperatures)
  const max = Math.max(...temperatures)
  return [Math.floor(min - 5), Math.ceil(max + 5)]
}

/**
 * Spool management utilities and types
 * Handles filament tracking, weight calculation, and object exclusion
 */

/**
 * Filament density values in g/cm³
 */
export const FILAMENT_DENSITIES: Record<string, number> = {
  PLA: 1.25,
  PETG: 1.27,
  ABS: 1.05,
  TPU: 1.21,
  NYLON: 1.14,
  ASA: 1.07,
  PC: 1.2,
  UNKNOWN: 1.25, // Default to PLA
}

/**
 * A single spool adjustment log entry
 */
export type SpoolLogEntry = {
  timestamp: string | number
  material: string
  lengthMm: number
  weight: number
  reason: 'print' | 'adjustment' | 'refill' | 'measurement'
}

/**
 * Tracked object in an exclude-objects scenario
 */
export type ObjectEntry = {
  name: string
  status: 'included' | 'excluded'
  excludable: boolean
  index?: number
}

/**
 * Response from the spool log API
 */
export type SpoolLogResponse = {
  printer_id: string
  entries: SpoolLogEntry[]
  totalUsed: number
  currentRemaining: number
}

/**
 * Response from the exclude-objects list API
 */
export type ExcludeObjectsResponse = {
  printer_id: string
  available_objects: ObjectEntry[]
  excluded_objects: string[]
}

/**
 * Calculate filament weight from length, diameter, and material density.
 *
 * Formula: weight(g) = π × (diameter/2)² × length × density / 1000
 * Diameter is in mm, length is in mm, density is in g/cm³
 *
 * @param lengthMm - Filament length in millimeters
 * @param filamentDiameter - Filament diameter in millimeters (typically 1.75 or 2.85)
 * @param densityGcm3 - Material density in g/cm³
 * @returns Weight in grams
 */
export function calculateWeight(
  lengthMm: number,
  filamentDiameter: number,
  densityGcm3: number
): number {
  const radiusCm = (filamentDiameter / 10) / 2
  const lengthCm = lengthMm / 10
  const volume = Math.PI * radiusCm * radiusCm * lengthCm
  return volume * densityGcm3
}

/**
 * Get the density for a material type (with fallback to default).
 *
 * @param material - Material name (e.g., "PLA", "PETG")
 * @returns Density in g/cm³
 */
export function getDensityForMaterial(material: string): number {
  const normalized = (material || 'UNKNOWN').toUpperCase().trim()
  return FILAMENT_DENSITIES[normalized] || FILAMENT_DENSITIES.UNKNOWN
}

/**
 * Format a spool log entry into a human-readable summary.
 *
 * Examples:
 *   "PLA: +250mm (25g) — Refill at 2024-01-15 14:30"
 *   "PETG: -1500mm (-38g) — Print completed"
 *
 * @param entry - SpoolLogEntry to format
 * @returns Human-readable string
 */
export function formatSpoolEntry(entry: SpoolLogEntry): string {
  const material = entry.material || 'UNKNOWN'
  const length = entry.lengthMm.toFixed(0)
  const weight = entry.weight.toFixed(1)

  const timestamp = typeof entry.timestamp === 'number'
    ? new Date(entry.timestamp * 1000).toLocaleString()
    : new Date(entry.timestamp).toLocaleString()

  const reasonLabel: Record<string, string> = {
    print: 'Print completed',
    adjustment: 'Manual adjustment',
    refill: 'Refill',
    measurement: 'Measurement update',
  }

  const reason = reasonLabel[entry.reason] || 'Unknown'

  return `${material}: ${entry.lengthMm >= 0 ? '+' : ''}${length}mm (${entry.weight >= 0 ? '+' : ''}${weight}g) — ${reason} at ${timestamp}`
}

/**
 * Format a spool log entry into a short inline display.
 *
 * @param entry - SpoolLogEntry to format
 * @returns Short human-readable string (e.g., "PLA +250mm")
 */
export function formatSpoolEntryShort(entry: SpoolLogEntry): string {
  const material = entry.material || 'UNKNOWN'
  const length = entry.lengthMm.toFixed(0)
  return `${material} ${entry.lengthMm >= 0 ? '+' : ''}${length}mm`
}

/**
 * Estimate remaining filament based on current weight.
 *
 * Returns a percentage (0–100) assuming a typical spool capacity.
 *
 * @param remainingGrams - Current remaining weight in grams
 * @param estimatedCapacity - Estimated full spool weight (default 1000g)
 * @returns Percentage 0–100
 */
export function estimateSpoolPercentage(
  remainingGrams: number,
  estimatedCapacity: number = 1000
): number {
  const percent = (remainingGrams / estimatedCapacity) * 100
  return Math.max(0, Math.min(100, percent))
}

/**
 * Format remaining filament as a human-readable string with percentage.
 *
 * @param remainingGrams - Remaining weight in grams
 * @param estimatedCapacity - Full spool capacity in grams
 * @returns String like "234g (23%)" or "Empty"
 */
export function formatRemainingFilament(
  remainingGrams: number,
  estimatedCapacity: number = 1000
): string {
  if (remainingGrams <= 0) return 'Empty'
  const percent = estimateSpoolPercentage(remainingGrams, estimatedCapacity)
  return `${remainingGrams.toFixed(0)}g (${percent.toFixed(0)}%)`
}

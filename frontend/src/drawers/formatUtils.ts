/**
 * Formatting utilities for human-readable string conversion
 * Extracted from App.tsx for reusability across components
 */

/**
 * Format bytes to human-readable string (B, KB, MB, GB)
 */
export function formatBytes(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

/**
 * Format grams to human-readable string (g or kg)
 */
export function formatGrams(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} kg`
  return `${value.toFixed(0)} g`
}

/**
 * Format millimeters to human-readable string (mm or m)
 */
export function formatMillimeters(value: number | null | undefined): string {
  if (value == null || value <= 0) return '—'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} m`
  return `${value.toFixed(0)} mm`
}

/**
 * Format duration in seconds to human-readable string (h/m/s)
 */
export function formatDuration(value: number | null | undefined): string {
  if (value == null || value <= 0) return '—'
  const totalSeconds = Math.floor(value)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

/**
 * Format timestamp to locale-specific string
 * Accepts Unix timestamp (seconds) or ISO date string
 */
export function formatTimestamp(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

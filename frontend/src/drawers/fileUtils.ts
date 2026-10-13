/**
 * File utilities for the file browser drawer.
 * Extracted from App.tsx to support modular file operations.
 */

/**
 * A single file or directory entry in the browser.
 */
export type FileEntry = {
  name: string
  path: string
  kind: 'file' | 'dir'
  size: number | null
  modified: number | null
  permissions: string | null
  metadata: Record<string, unknown>
}

/**
 * Response from the file browser API endpoint.
 */
export type FileBrowserResponse = {
  printer_id: string
  path: string
  root: string
  dirs: FileEntry[]
  files: FileEntry[]
}

/**
 * Sort keys for file browser sorting.
 */
export type FileSortKey = 'name' | 'size' | 'modified' | 'last_printed'

/**
 * Format a byte size into human-readable units (B, KB, MB, GB).
 * Returns '—' for null or undefined values.
 */
export function formatBytes(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

/**
 * Format a timestamp (Unix seconds or ISO string) into locale-specific string.
 * Returns '—' for null, undefined, or invalid values.
 *
 * @param value - Unix timestamp in seconds (number) or ISO 8601 string
 */
export function formatTimestamp(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

/**
 * Normalize a file path for use as a job key in print history lookups.
 *
 * FileEntry.path is prefixed with `gcodes/` (e.g., `gcodes/a/b.gcode`).
 * JobLog.job_name is stored gcodes-relative (e.g., `a/b.gcode`).
 * This function strips the prefix and leading slashes to make them match.
 *
 * Applied to BOTH sides of the lookup so the two can never drift apart.
 *
 * @param path - File path, possibly with `gcodes/` prefix
 */
export function normalizeJobKey(path: string): string {
  return path.trim().replace(/^\/+/, '').replace(/^gcodes\//, '')
}

/**
 * Get the parent directory path.
 *
 * Returns null if the path has no parent (root or single level).
 * Handles trailing slashes.
 *
 * @param path - Directory path (e.g., `gcodes/a/b`)
 */
export function parentPath(path: string): string | null {
  const clean = path.replace(/\/$/, '')
  const idx = clean.lastIndexOf('/')
  if (idx <= 0) return null
  return clean.slice(0, idx)
}

/**
 * Strip the `gcodes/` prefix from a file path.
 *
 * Used to convert full browser paths to relative filenames for API calls.
 * For example: `gcodes/a/b.gcode` → `a/b.gcode`
 *
 * @param path - Full file path with potential `gcodes/` prefix
 */
export function relativeFilename(path: string): string {
  return path.replace(/^gcodes\//, '')
}

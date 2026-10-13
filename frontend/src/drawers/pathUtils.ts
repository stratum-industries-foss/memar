/**
 * Path normalization utilities for Files drawer
 * Extracted from App.tsx for reusability across components
 */

/**
 * Get the parent directory of a path
 * Returns null if path is root or only one level deep
 */
export function parentPath(path: string): string | null {
  const clean = path.replace(/\/$/, '')
  const idx = clean.lastIndexOf('/')
  if (idx <= 0) return null
  return clean.slice(0, idx)
}

/**
 * Strip 'gcodes/' prefix from a file path
 * Used to display relative filenames in the UI
 */
export function relativeFilename(path: string): string {
  return path.replace(/^gcodes\//, '')
}

/**
 * Normalize a path for use as a join key between FileEntry and JobLog
 *
 * FileEntry.path is prefixed with 'gcodes/' (e.g., 'gcodes/a/b.gcode')
 * JobLog.job_name is stored gcodes-relative (e.g., 'a/b.gcode')
 * Moonraker reports both without the root prefix.
 *
 * This function removes all leading slashes and 'gcodes/' prefix
 * to create a consistent key for lookups on both sides.
 *
 * Applied to BOTH sides of the lookup so the two can never drift apart.
 */
export function normalizeJobKey(path: string): string {
  return path.trim().replace(/^\/+/, '').replace(/^gcodes\//, '')
}

/**
 * Normalize a relative upload path for use as a directory target
 *
 * - Removes leading/trailing slashes
 * - Strips 'gcodes/' prefix if present
 * - Returns empty string if path is just 'gcodes' (root directory)
 *
 * Used when uploading files to determine the target subdirectory
 */
export function normalizeRelativeUploadPath(path: string): string {
  const clean = path.trim().replace(/^\/+/, '').replace(/\/+$/, '')
  if (clean === 'gcodes') return ''
  return clean.startsWith('gcodes/') ? clean.slice('gcodes/'.length) : clean
}

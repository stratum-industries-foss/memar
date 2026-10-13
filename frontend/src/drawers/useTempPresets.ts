/**
 * useTempPresets — Custom hook for managing temperature presets.
 *
 * Encapsulates:
 *  - In-memory preset array (custom presets only, not built-ins)
 *  - localStorage persistence (load on mount, save on change)
 *  - Add/remove/apply operations
 *
 * Follows the same architecture as App.tsx's preset management, but extracted
 * to a reusable hook for drawer-scoped state.
 */

import { useEffect, useState } from 'react'

export type TempPreset = {
  label: string
  nozzle: number
  bed: number
  builtin?: boolean
}

const STORAGE_KEY = 'memar-material-presets-v2'

/**
 * Custom hook: useTempPresets
 *
 * Manages a list of custom temperature presets with localStorage persistence.
 *
 * On first mount:
 *  - Loads from localStorage if available
 *  - Falls back to initialPresets (typically loaded from the backend)
 *
 * On change:
 *  - Persists custom presets to localStorage immediately
 *
 * @param initialPresets - Array of presets (typically from FleetSettingsResponse)
 * @returns Object with:
 *   - presets: current preset array
 *   - addPreset: (label, nozzle, bed) => void
 *   - removePreset: (label) => void
 *   - applyPreset: (label) => {nozzle, bed} | null
 */
export function useTempPresets(initialPresets: TempPreset[] = []) {
  const [presets, setPresets] = useState<TempPreset[]>(() => {
    // Load from localStorage on first mount
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored) as TempPreset[]
        // Validate: each item must have label (string), nozzle (number), bed (number)
        return parsed.filter(
          (p): p is TempPreset =>
            !!p &&
            typeof p.label === 'string' &&
            typeof p.nozzle === 'number' &&
            typeof p.bed === 'number'
        )
      }
    } catch {
      // Silently ignore parse errors — fall through to initialPresets
    }
    return initialPresets.filter((p) => !p.builtin)
  })

  // Persist to localStorage whenever presets change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(presets))
    } catch {
      // Silently ignore storage quota exceeded or other write errors
      // The presets are still in memory; next session may lose them.
    }
  }, [presets])

  /**
   * Add a new custom preset.
   *
   * If a preset with the same label already exists, it is replaced.
   *
   * @param label - Preset name (e.g., "My ABS Mix")
   * @param nozzle - Nozzle temperature in °C
   * @param bed - Bed temperature in °C
   */
  function addPreset(label: string, nozzle: number, bed: number): void {
    setPresets((prev) => {
      // Remove any existing preset with the same label
      const filtered = prev.filter((p) => p.label !== label)
      return [...filtered, { label, nozzle, bed }]
    })
  }

  /**
   * Remove a preset by label.
   *
   * No-op if the label doesn't exist.
   *
   * @param label - Preset name to remove
   */
  function removePreset(label: string): void {
    setPresets((prev) => prev.filter((p) => p.label !== label))
  }

  /**
   * Look up a preset by label and return its temperatures.
   *
   * Returns null if the label doesn't exist.
   *
   * @param label - Preset name to look up
   * @returns { nozzle, bed } or null
   */
  function applyPreset(label: string): { nozzle: number; bed: number } | null {
    const preset = presets.find((p) => p.label === label)
    return preset ? { nozzle: preset.nozzle, bed: preset.bed } : null
  }

  return {
    presets,
    addPreset,
    removePreset,
    applyPreset,
  }
}

/**
 * useTemperatureState — Encapsulates all Temperature drawer state and logic.
 *
 * Extracted from TemperatureDrawer.tsx component to separate UI concerns from
 * state management. Handles:
 *  - Input field state (customNozzle, customBed)
 *  - Save-preset tri-state (savePresetLabel)
 *  - Temperature history (via useTempHistoryDetail hook)
 *  - Temperature presets (via useTempPresets hook)
 *  - Async operations (applyCustomTemperatures, applyPreset, saveCurrentPreset)
 */

import { useState } from 'react'
import { useTempHistoryDetail } from './useTempHistoryDetail'
import type { Fetcher, TempHistoryPoint, TempHistoryDetail } from './useTempHistoryDetail'
import { useTempPresets } from './useTempPresets'
import { parseTarget, THERMAL_MACHINE_TYPES, formatTemperature } from './tempUtils'
import type { TempPreset, TemperatureDrawerPrinter } from './tempUtils'
import { apiFetch } from '../api'

export interface TemperatureState {
  // Input fields
  customNozzle: string
  setCustomNozzle: (value: string) => void
  customBed: string
  setCustomBed: (value: string) => void

  // Save-preset tri-state
  savePresetLabel: string | null
  setSavePresetLabel: (value: string | null) => void

  // History data
  tempHistoryDetail: TempHistoryDetail | null

  // Presets
  tempPresets: TempPreset[]

  // Formatting helper
  fmtTemp: (current: number | null, target: number | null) => string

  // Operations
  applyCustomTemperatures: (nozzleValue?: number, bedValue?: number) => Promise<void>
  applyPreset: (nozzle: number, bed: number) => Promise<void>
  saveCurrentPreset: () => void
}

export function useTemperatureState(
  printerId: string | undefined,
  printer: TemperatureDrawerPrinter | null | undefined,
  presets: TempPreset[] = [],
  onSavePreset?: (preset: TempPreset) => void,
  onStatus?: (message: string) => void,
  fetcher: Fetcher = apiFetch,
): TemperatureState {
  const [customNozzle, setCustomNozzle] = useState<string>('0')
  const [customBed, setCustomBed] = useState<string>('0')
  const [savePresetLabel, setSavePresetLabel] = useState<string | null>(null)

  const { data: tempHistoryDetail } = useTempHistoryDetail(printerId || '', fetcher)
  const { presets: tempPresets, addPreset } = useTempPresets(presets)

  async function applyCustomTemperatures(nozzleValue?: number, bedValue?: number) {
    if (!printerId || !printer) return

    // Gate BEFORE any status message, exactly as the original did — a CNC/laser
    // must never see "Applying temperatures...".
    const machineType = printer.capability.machine_type
    if (!machineType || !(THERMAL_MACHINE_TYPES as readonly string[]).includes(machineType)) {
      onStatus?.('Temperature control not available for this machine type.')
      return
    }

    const nozzleTarget = nozzleValue ?? parseTarget(customNozzle)
    const bedTarget = bedValue ?? parseTarget(customBed)

    // FIX vs. original: App.tsx posted the parsed values unguarded. Two bugs:
    //   - a non-numeric field produced NaN, and JSON.stringify turns NaN into
    //     `null`, so the backend received {nozzle_target: null};
    //   - a *cleared* field produced Number('') === 0, silently commanding a
    //     cooldown the user never asked for.
    // Refuse to send in both cases. (saveCurrentPreset had a NaN guard already;
    // apply did not.)
    if (!Number.isFinite(nozzleTarget) || !Number.isFinite(bedTarget)) {
      onStatus?.('Enter a valid nozzle and bed temperature.')
      return
    }

    onStatus?.('Applying temperatures...')
    try {
      const res = await fetcher(`/api/printers/${printerId}/temperature`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nozzle_target: nozzleTarget, bed_target: bedTarget }),
      })
      onStatus?.(res.ok ? `Applied ${nozzleTarget} / ${bedTarget}` : 'Failed to apply temperatures')
    } catch {
      // The original let a network rejection escape as an unhandled rejection
      // (the call site used `void`), leaving the status stuck on "Applying...".
      onStatus?.('Failed to apply temperatures')
    }
  }

  async function applyPreset(nozzle: number, bed: number) {
    if (!printerId) return
    // Inputs update first so the user sees the preset values even if the apply
    // is subsequently rejected by the thermal gate — original ordering.
    setCustomNozzle(String(nozzle))
    setCustomBed(String(bed))
    await applyCustomTemperatures(nozzle, bed)
  }

  function saveCurrentPreset() {
    const label = savePresetLabel?.trim()
    if (!label) return
    const nozzle = parseTarget(customNozzle)
    const bed = parseTarget(customBed)
    if (!Number.isFinite(nozzle) || !Number.isFinite(bed)) return
    addPreset(label, nozzle, bed)
    onSavePreset?.({ label, nozzle, bed })
    setSavePresetLabel(null)
  }

  return {
    customNozzle,
    setCustomNozzle,
    customBed,
    setCustomBed,
    savePresetLabel,
    setSavePresetLabel,
    tempHistoryDetail,
    tempPresets,
    fmtTemp: formatTemperature,
    applyCustomTemperatures,
    applyPreset,
    saveCurrentPreset,
  }
}

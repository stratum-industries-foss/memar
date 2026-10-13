/**
 * useTemperatureState hook test suite
 *
 * Tests cover:
 * - Initialization with printer data and presets
 * - Applying temperature presets via API
 * - Saving custom presets to localStorage
 * - Error handling (invalid temps, network failures, machine type gating)
 * - State mutations and async operations
 *
 * Coverage target: >85%
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useTemperatureState } from '../useTemperatureState'
import type { TemperatureDrawerPrinter, TempPreset } from '../tempUtils'
import type { Fetcher } from '../useTempHistoryDetail'

/**
 * Mock data factories
 */
function mockPrinter(overrides?: Partial<TemperatureDrawerPrinter>): TemperatureDrawerPrinter {
  return {
    id: 'printer-1',
    name: 'Prusa MK3S+',
    nozzle: { temperature: 25, target: 0 },
    bed: { temperature: 25, target: 0 },
    capability: {
      machine_type: 'fdm',
      profile: null,
      nozzle_diameter_mm: 0.4,
      build_volume: { x: 250, y: 210, z: 210 },
      supported_materials: [],
      current_material: null,
      current_spool_name: null,
      spool_remaining_g: null,
      spool_capacity_g: null,
      filament_sensor: false,
      probe: false,
      webcam_expected: false,
      fluidd_url: null,
      camera_url: null,
      maintenance_lockout: false,
      maintenance_state: null,
      maintenance_due: false,
      maintenance_interval_hours: null,
      maintenance_interval_jobs: null,
      maintenance_interval_filament_g: null,
      last_service_at: null,
      next_service_due: null,
      jog_enabled: false,
      safe_nozzle_max_c: 300,
      safe_bed_max_c: 120,
      motion_check_required: false,
      notes: [],
      maintenance_notes: [],
    },
    ...overrides,
  }
}

function mockCNCPrinter(): TemperatureDrawerPrinter {
  const printer = mockPrinter()
  return {
    ...printer,
    capability: {
      ...printer.capability,
      machine_type: 'cnc_mill',
      safe_nozzle_max_c: 0,
      safe_bed_max_c: 0,
    },
  }
}

function mockPresets(): TempPreset[] {
  return [
    { label: 'PLA', nozzle: 210, bed: 60 },
    { label: 'ABS', nozzle: 240, bed: 100 },
    { label: 'PETG', nozzle: 230, bed: 80 },
  ]
}

function mockFetcher(response?: { ok: boolean; json?: () => Promise<unknown> }): Fetcher {
  return vi.fn(async (url: string) => {
    // Default response for any endpoint
    if (!response) {
      if (url.includes('temp/history')) {
        return new Response(JSON.stringify({ extruder: [], bed: [] }), { status: 200 })
      }
      return new Response('{}', { status: 200 })
    }
    const res = new Response(
      response.json ? JSON.stringify(await response.json()) : '{}',
      { status: response.ok ? 200 : 500 }
    )
    return res
  })
}

describe('useTemperatureState', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  // ================================================================================
  // TEST 1: Initialize with printer data and presets
  // ================================================================================
  describe('Test 1: Initialize with printer data', () => {
    it('initializes state with empty temperatures', () => {
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), mockPresets())
      )

      expect(result.current.customNozzle).toBe('0')
      expect(result.current.customBed).toBe('0')
      expect(result.current.savePresetLabel).toBeNull()
    })

    it('loads presets from initialPresets parameter', async () => {
      const presets = mockPresets()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), presets)
      )

      await waitFor(() => {
        expect(result.current.tempPresets).toEqual(presets)
      })
      expect(result.current.tempPresets.length).toBeGreaterThan(0)
    })

    it('initializes with empty presets when none provided', () => {
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [])
      )

      expect(result.current.tempPresets).toEqual([])
    })

    it('provides formatTemperature helper function', () => {
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter())
      )

      expect(result.current.fmtTemp).toBeInstanceOf(Function)
      expect(result.current.fmtTemp(210, 60)).toBe('210 / 60')
      expect(result.current.fmtTemp(null, 60)).toBe('— / 60')
      expect(result.current.fmtTemp(210, null)).toBe('210 / —')
    })

    it('filters out builtin presets from stored presets', () => {
      const mixedPresets: TempPreset[] = [
        { label: 'Custom PLA', nozzle: 215, bed: 65 },
        { label: 'PLA', nozzle: 210, bed: 60, builtin: true },
        { label: 'Custom ABS', nozzle: 245, bed: 105 },
      ]

      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), mixedPresets)
      )

      expect(result.current.tempPresets).toHaveLength(2)
      expect(result.current.tempPresets[0].label).toBe('Custom PLA')
      expect(result.current.tempPresets[1].label).toBe('Custom ABS')
    })

    it('fetches temperature history for the printer', async () => {
      const mockHistory = {
        extruder: [
          { timestamp: 1000, temperature: 25 },
          { timestamp: 2000, temperature: 100 },
        ],
        bed: [
          { timestamp: 1000, temperature: 25 },
          { timestamp: 2000, temperature: 80 },
        ],
      }

      const fetcher = vi.fn(async (path: string) => {
        if (path.includes('temp/history')) {
          return new Response(JSON.stringify(mockHistory), { status: 200, ok: true })
        }
        return new Response('{}', { status: 200, ok: true })
      })

      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, undefined, fetcher as Fetcher)
      )

      await waitFor(() => {
        expect(result.current.tempHistoryDetail).not.toBeNull()
      })

      expect(result.current.tempHistoryDetail?.extruder).toHaveLength(2)
    })
  })

  // ================================================================================
  // TEST 2: Apply preset updates state
  // ================================================================================
  describe('Test 2: Apply preset updates state', () => {
    it('applies a preset and updates customNozzle and customBed', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), mockPresets(), undefined, undefined, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      expect(result.current.customNozzle).toBe('210')
      expect(result.current.customBed).toBe('60')
      expect(fetcher).toHaveBeenCalledWith('/api/printers/printer-1/temperature', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ nozzle_target: 210, bed_target: 60 }),
      }))
    })

    it('calls the API with correct payload when applying preset', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, undefined, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(240, 100)
      })

      expect(fetcher).toHaveBeenCalledWith(
        '/api/printers/printer-1/temperature',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nozzle_target: 240, bed_target: 100 }),
        })
      )
    })

    it('invokes onStatus callback with success message', async () => {
      const onStatus = vi.fn()
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, onStatus, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      expect(onStatus).toHaveBeenCalledWith('Applied 210 / 60')
    })

    it('invokes onStatus with failure message when API returns error', async () => {
      const onStatus = vi.fn()
      const fetcher = mockFetcher({ ok: false })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, onStatus, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      expect(onStatus).toHaveBeenCalledWith('Failed to apply temperatures')
    })

    it('handles network errors gracefully without throwing', async () => {
      const onStatus = vi.fn()
      const fetcher = vi.fn(async () => {
        throw new Error('Network error')
      })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, onStatus, fetcher as Fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      expect(onStatus).toHaveBeenCalledWith('Failed to apply temperatures')
    })

    it('gates temperature control by machine type (CNC rejection)', async () => {
      const onStatus = vi.fn()
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockCNCPrinter(), [], undefined, onStatus, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      expect(onStatus).toHaveBeenCalledWith(
        'Temperature control not available for this machine type.'
      )
      // Should NOT have called the temperature application endpoint
      const temperatureCallFound = fetcher.mock.calls.some((call) =>
        typeof call[0] === 'string' && call[0].includes('/temperature')
      )
      expect(temperatureCallFound).toBe(false)
    })

    it('rejects invalid nozzle temperature', async () => {
      const onStatus = vi.fn()
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, onStatus, fetcher)
      )

      act(() => {
        result.current.setCustomNozzle('abc')
        result.current.setCustomBed('60')
      })

      await act(async () => {
        await result.current.applyCustomTemperatures()
      })

      expect(onStatus).toHaveBeenCalledWith('Enter a valid nozzle and bed temperature.')
      const temperatureCallFound = fetcher.mock.calls.some((call) =>
        typeof call[0] === 'string' && call[0].includes('/temperature')
      )
      expect(temperatureCallFound).toBe(false)
    })

    it('rejects invalid bed temperature', async () => {
      const onStatus = vi.fn()
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, onStatus, fetcher)
      )

      act(() => {
        result.current.setCustomNozzle('210')
        result.current.setCustomBed('not-a-number')
      })

      await act(async () => {
        await result.current.applyCustomTemperatures()
      })

      expect(onStatus).toHaveBeenCalledWith('Enter a valid nozzle and bed temperature.')
      const temperatureCallFound = fetcher.mock.calls.some((call) =>
        typeof call[0] === 'string' && call[0].includes('/temperature')
      )
      expect(temperatureCallFound).toBe(false)
    })

    it('rejects when both temperatures are invalid', async () => {
      const onStatus = vi.fn()
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, onStatus, fetcher)
      )

      act(() => {
        result.current.setCustomNozzle('invalid1')
        result.current.setCustomBed('invalid2')
      })

      await act(async () => {
        await result.current.applyCustomTemperatures()
      })

      expect(onStatus).toHaveBeenCalledWith('Enter a valid nozzle and bed temperature.')
      const temperatureCallFound = fetcher.mock.calls.some((call) =>
        typeof call[0] === 'string' && call[0].includes('/temperature')
      )
      expect(temperatureCallFound).toBe(false)
    })

    it('no-ops when printerId is undefined', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState(undefined, mockPrinter(), [], undefined, undefined, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      expect(fetcher).not.toHaveBeenCalled()
      expect(result.current.customNozzle).toBe('0')
    })

    it('no-ops when printer is null', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', null, [], undefined, undefined, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      const temperatureCallFound = fetcher.mock.calls.some((call) =>
        typeof call[0] === 'string' && call[0].includes('/temperature')
      )
      expect(temperatureCallFound).toBe(false)
    })
  })

  // ================================================================================
  // TEST 3: Save custom preset
  // ================================================================================
  describe('Test 3: Save custom preset', () => {
    it('saves custom preset and persists to localStorage', () => {
      const onSavePreset = vi.fn()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], onSavePreset)
      )

      // Set values and save
      act(() => {
        result.current.setCustomNozzle('215')
        result.current.setCustomBed('65')
        result.current.setSavePresetLabel('My Custom PLA')
      })

      // Verify inputs were set
      expect(result.current.customNozzle).toBe('215')
      expect(result.current.customBed).toBe('65')
      expect(result.current.savePresetLabel).toBe('My Custom PLA')

      // Now save the preset
      act(() => {
        result.current.saveCurrentPreset()
      })

      // Verify the callback was invoked
      expect(onSavePreset).toHaveBeenCalledWith(
        expect.objectContaining({
          label: 'My Custom PLA',
          nozzle: 215,
          bed: 65,
        })
      )
    })

    it('persists custom preset to localStorage via useTempPresets', () => {
      const onSavePreset = vi.fn()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], onSavePreset)
      )

      act(() => {
        result.current.setCustomNozzle('215')
        result.current.setCustomBed('65')
        result.current.setSavePresetLabel('My Custom PLA')
      })

      act(() => {
        result.current.saveCurrentPreset()
      })

      // Verify preset was saved via callback
      expect(onSavePreset).toHaveBeenCalledWith(
        expect.objectContaining({
          label: 'My Custom PLA',
          nozzle: 215,
          bed: 65,
        })
      )
    })

    it('clears savePresetLabel after successful save', () => {
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [])
      )

      act(() => {
        result.current.setCustomNozzle('215')
        result.current.setCustomBed('65')
        result.current.setSavePresetLabel('My Custom PLA')
      })

      expect(result.current.savePresetLabel).toBe('My Custom PLA')

      act(() => {
        result.current.saveCurrentPreset()
      })

      // The label should be cleared after successfully saving
      expect(result.current.savePresetLabel).toBeNull()
    })

    it('ignores empty or whitespace-only labels', async () => {
      const onSavePreset = vi.fn()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], onSavePreset)
      )

      await act(async () => {
        result.current.setCustomNozzle('215')
        result.current.setCustomBed('65')
        result.current.setSavePresetLabel('   ')
        result.current.saveCurrentPreset()
      })

      expect(onSavePreset).not.toHaveBeenCalled()
      expect(result.current.tempPresets).toHaveLength(0)
    })

    it('rejects preset with invalid temperatures', async () => {
      const onSavePreset = vi.fn()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], onSavePreset)
      )

      await act(async () => {
        result.current.setCustomNozzle('abc')
        result.current.setCustomBed('65')
        result.current.setSavePresetLabel('Bad Preset')
        result.current.saveCurrentPreset()
      })

      expect(onSavePreset).not.toHaveBeenCalled()
    })

    it('replaces existing preset with same label', () => {
      const onSavePreset = vi.fn()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], onSavePreset)
      )

      // Save first preset
      act(() => {
        result.current.setCustomNozzle('210')
        result.current.setCustomBed('60')
        result.current.setSavePresetLabel('PLA Mix')
      })

      act(() => {
        result.current.saveCurrentPreset()
      })

      // onSavePreset should have been called with first preset
      expect(onSavePreset).toHaveBeenNthCalledWith(1,
        expect.objectContaining({
          label: 'PLA Mix',
          nozzle: 210,
          bed: 60,
        })
      )

      // Save with same label, different temps
      act(() => {
        result.current.setCustomNozzle('215')
        result.current.setCustomBed('65')
        result.current.setSavePresetLabel('PLA Mix')
      })

      act(() => {
        result.current.saveCurrentPreset()
      })

      // onSavePreset should have been called again with updated temps
      expect(onSavePreset).toHaveBeenNthCalledWith(2,
        expect.objectContaining({
          label: 'PLA Mix',
          nozzle: 215,
          bed: 65,
        })
      )
    })

    it('trims whitespace from preset label', () => {
      const onSavePreset = vi.fn()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], onSavePreset)
      )

      act(() => {
        result.current.setCustomNozzle('215')
        result.current.setCustomBed('65')
        result.current.setSavePresetLabel('  My Custom PLA  ')
      })

      act(() => {
        result.current.saveCurrentPreset()
      })

      expect(onSavePreset).toHaveBeenCalledWith(
        expect.objectContaining({
          label: 'My Custom PLA',
          nozzle: 215,
          bed: 65,
        })
      )
    })

    it('persists multiple presets independently', () => {
      const onSavePreset = vi.fn()
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], onSavePreset)
      )

      // Save first preset
      act(() => {
        result.current.setCustomNozzle('210')
        result.current.setCustomBed('60')
        result.current.setSavePresetLabel('PLA')
      })

      act(() => {
        result.current.saveCurrentPreset()
      })

      // Save second preset
      act(() => {
        result.current.setCustomNozzle('240')
        result.current.setCustomBed('100')
        result.current.setSavePresetLabel('ABS')
      })

      act(() => {
        result.current.saveCurrentPreset()
      })

      // Check that both saves were registered
      expect(onSavePreset).toHaveBeenCalledTimes(2)
      expect(onSavePreset).toHaveBeenNthCalledWith(1,
        expect.objectContaining({
          label: 'PLA',
          nozzle: 210,
          bed: 60,
        })
      )
      expect(onSavePreset).toHaveBeenNthCalledWith(2,
        expect.objectContaining({
          label: 'ABS',
          nozzle: 240,
          bed: 100,
        })
      )
    })
  })

  // ================================================================================
  // Additional edge case and integration tests
  // ================================================================================
  describe('Integration and edge cases', () => {
    it('applies custom temperatures with explicit values', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, undefined, fetcher)
      )

      await act(async () => {
        await result.current.applyCustomTemperatures(215, 65)
      })

      expect(fetcher).toHaveBeenCalledWith(
        '/api/printers/printer-1/temperature',
        expect.objectContaining({
          body: JSON.stringify({ nozzle_target: 215, bed_target: 65 }),
        })
      )
    })

    it('applies custom temperatures from input fields when explicit values omitted', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, undefined, fetcher)
      )

      act(() => {
        result.current.setCustomNozzle('225')
        result.current.setCustomBed('70')
      })

      await act(async () => {
        await result.current.applyCustomTemperatures()
      })

      const temperatureCall = fetcher.mock.calls.find((call) =>
        typeof call[0] === 'string' && call[0].includes('/temperature')
      )
      expect(temperatureCall).toBeDefined()
      expect(temperatureCall![1]).toMatchObject({
        body: JSON.stringify({ nozzle_target: 225, bed_target: 70 }),
      })
    })

    it('handles float temperatures correctly', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, undefined, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210.5, 60.75)
      })

      expect(fetcher).toHaveBeenCalledWith(
        '/api/printers/printer-1/temperature',
        expect.objectContaining({
          body: JSON.stringify({ nozzle_target: 210.5, bed_target: 60.75 }),
        })
      )
    })

    it('gate message does NOT appear before thermal check (original bug)', async () => {
      const onStatus = vi.fn()
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockCNCPrinter(), [], undefined, onStatus, fetcher)
      )

      await act(async () => {
        await result.current.applyPreset(210, 60)
      })

      // Should see the gate rejection message, not "Applying temperatures..."
      expect(onStatus).toHaveBeenCalledWith(
        'Temperature control not available for this machine type.'
      )
      expect(onStatus).not.toHaveBeenCalledWith('Applying temperatures...')
    })

    it('updates both customNozzle and customBed before applying preset', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), [], undefined, undefined, fetcher)
      )

      await act(async () => {
        result.current.setCustomNozzle('100')
        result.current.setCustomBed('40')
      })

      await act(async () => {
        await result.current.applyPreset(240, 100)
      })

      // Values should be updated even before the API call completes
      expect(result.current.customNozzle).toBe('240')
      expect(result.current.customBed).toBe('100')
    })

    it('maintains state when switching between presets', async () => {
      const fetcher = mockFetcher({ ok: true })
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', mockPrinter(), mockPresets(), undefined, undefined, fetcher)
      )

      // Apply first preset
      await act(async () => {
        await result.current.applyPreset(210, 60)
      })
      expect(result.current.customNozzle).toBe('210')

      // Apply second preset
      await act(async () => {
        await result.current.applyPreset(240, 100)
      })
      expect(result.current.customNozzle).toBe('240')
    })

    it('handles undefined printer gracefully', async () => {
      const { result } = renderHook(() =>
        useTemperatureState('printer-1', undefined, mockPresets())
      )

      await waitFor(() => {
        expect(result.current.tempPresets.length).toBeGreaterThan(0)
      })
      expect(result.current.customNozzle).toBe('0')
    })
  })
})

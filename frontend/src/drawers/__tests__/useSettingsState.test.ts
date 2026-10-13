import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSettingsState } from '../useSettingsState'

describe('useSettingsState', () => {
  let mockFetcher: any

  beforeEach(() => {
    mockFetcher = vi.fn()
  })

  it('initializes with null settings when printer is not provided', () => {
    mockFetcher.mockResolvedValueOnce({ ok: false })
    const { result } = renderHook(() => useSettingsState(undefined, null, mockFetcher))
    expect(result.current.settingsDraft).toBeNull()
  })

  it('initializes settings draft from printer data', () => {
    mockFetcher.mockResolvedValueOnce({ ok: false })
    const mockPrinter = {
      id: 'printer1',
      name: 'Test Printer',
      enabled: true,
      nozzle_diameter_mm: 0.6,
      filament_diameter_mm: 1.75,
      tags: ['test', 'core'],
      build_volume: { x: 200, y: 200, z: 200 },
      supported_materials: ['PLA', 'PETG'],
      current_material: 'PLA',
      current_spool_name: 'Spool-1',
      spool_remaining_g: 500,
      spool_capacity_g: 1000,
      filament_sensor: true,
      probe: true,
      webcam_expected: true,
      capability: {
        nozzle_diameter_mm: 0.6,
        build_volume: { x_mm: 200, y_mm: 200, z_mm: 200 },
      },
    }

    const { result } = renderHook(() => useSettingsState('printer1', mockPrinter, mockFetcher))
    expect(result.current.settingsDraft).not.toBeNull()
    expect(result.current.settingsDraft?.name).toBe('Test Printer')
    expect(result.current.settingsDraft?.nozzleDiameter).toBe('0.6')
    expect(result.current.settingsDraft?.tagsText).toBe('test, core')
    expect(result.current.settingsDraft?.supportedMaterialsText).toBe('PLA, PETG')
  })

  it('updates settings draft with partial patch', () => {
    mockFetcher.mockResolvedValueOnce({ ok: false })
    const mockPrinter = { id: 'p1', name: 'Printer', enabled: true, capability: {} }
    const { result } = renderHook(() => useSettingsState('p1', mockPrinter, mockFetcher))

    act(() => {
      result.current.updateSettingsDraft({ name: 'Updated Name' })
    })

    expect(result.current.settingsDraft?.name).toBe('Updated Name')
  })

  it('sets nozzle quick-select value', () => {
    mockFetcher.mockResolvedValueOnce({ ok: false })
    const mockPrinter = { id: 'p1', name: 'Printer', enabled: true, capability: {} }
    const { result } = renderHook(() => useSettingsState('p1', mockPrinter, mockFetcher))

    act(() => {
      result.current.setSettingsNozzle('0.8')
    })

    expect(result.current.settingsNozzle).toBe('0.8')
  })

  it('adds UI target to draft', () => {
    mockFetcher.mockResolvedValueOnce({ ok: false })
    const mockPrinter = { id: 'p1', name: 'Printer', enabled: true, ui_targets: [], capability: {} }
    const { result } = renderHook(() => useSettingsState('p1', mockPrinter, mockFetcher))

    act(() => {
      result.current.addUiTargetDraft()
    })

    expect(result.current.settingsDraft?.uiTargets.length).toBe(1)
    expect(result.current.settingsDraft?.uiTargets[0].primary).toBe(true)
  })

  it('removes UI target from draft', () => {
    mockFetcher.mockResolvedValueOnce({ ok: false })
    const mockPrinter = {
      id: 'p1',
      name: 'Printer',
      enabled: true,
      ui_targets: [
        { label: 'Fluidd', provider: 'fluidd', url: 'http://localhost', mode: 'direct', primary: true },
        { label: 'Mainsail', provider: 'mainsail', url: 'http://localhost:8000', mode: 'direct', primary: false },
      ],
      capability: {},
    }
    const { result } = renderHook(() => useSettingsState('p1', mockPrinter, mockFetcher))

    act(() => {
      result.current.removeUiTargetDraft(0)
    })

    expect(result.current.settingsDraft?.uiTargets.length).toBe(1)
    expect(result.current.settingsDraft?.uiTargets[0].label).toBe('Mainsail')
  })

  it('updates UI target at index', () => {
    mockFetcher.mockResolvedValueOnce({ ok: false })
    const mockPrinter = {
      id: 'p1',
      name: 'Printer',
      enabled: true,
      ui_targets: [{ label: 'Old', provider: 'old', url: 'http://old', mode: 'direct', primary: true }],
      capability: {},
    }
    const { result } = renderHook(() => useSettingsState('p1', mockPrinter, mockFetcher))

    act(() => {
      result.current.updateUiTargetDraft(0, { label: 'New', url: 'http://new' })
    })

    expect(result.current.settingsDraft?.uiTargets[0].label).toBe('New')
    expect(result.current.settingsDraft?.uiTargets[0].url).toBe('http://new')
  })

  it('handles save errors gracefully', async () => {
    mockFetcher.mockResolvedValueOnce({ ok: false }) // for subscription load
    mockFetcher.mockRejectedValueOnce(new Error('Network error'))

    const mockPrinter = { id: 'p1', name: 'Printer', enabled: true, capability: {} }
    const { result } = renderHook(() => useSettingsState('p1', mockPrinter, mockFetcher))

    await act(async () => {
      await result.current.savePrinterSettings()
    })

    expect(result.current.settingsMessage).toContain('Error')
  })
})

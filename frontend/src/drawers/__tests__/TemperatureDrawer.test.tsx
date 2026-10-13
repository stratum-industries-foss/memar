import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TemperatureDrawer from '../TemperatureDrawer'
import type { DrawerProps } from '../../types/drawer-props'
import type { TemperatureDrawerPrinter, TempPreset } from '../tempUtils'

// Mock the useTemperatureState hook
vi.mock('../useTemperatureState', () => ({
  useTemperatureState: vi.fn(),
}))

import { useTemperatureState } from '../useTemperatureState'

/**
 * Fixture: FDM printer with thermal capability.
 */
function createThermalPrinter(overrides?: Partial<TemperatureDrawerPrinter>): TemperatureDrawerPrinter {
  return {
    id: 'printer-1',
    name: 'Prusa i3 MK3S+',
    nozzle: {
      temperature: 200,
      target: 210,
    },
    bed: {
      temperature: 60,
      target: 65,
    },
    capability: {
      machine_type: 'fdm',
      profile: 'default',
      nozzle_diameter_mm: 0.4,
      build_volume: { x: 250, y: 210, z: 210 },
      supported_materials: ['PLA', 'PETG', 'ABS'],
      current_material: 'PLA',
      current_spool_name: 'Prusament PLA',
      spool_remaining_g: 850,
      spool_capacity_g: 1000,
      filament_sensor: true,
      probe: true,
      webcam_expected: true,
      fluidd_url: 'http://192.168.1.100',
      camera_url: null,
      maintenance_lockout: false,
      maintenance_state: null,
      maintenance_due: false,
      maintenance_interval_hours: 500,
      maintenance_interval_jobs: null,
      maintenance_interval_filament_g: null,
      last_service_at: null,
      next_service_due: null,
      jog_enabled: true,
      safe_nozzle_max_c: 300,
      safe_bed_max_c: 120,
      motion_check_required: false,
      notes: [],
      maintenance_notes: [],
    },
    ...overrides,
  }
}

/**
 * Fixture: CNC laser (no thermal capability).
 */
function createNonThermalPrinter(overrides?: Partial<TemperatureDrawerPrinter>): TemperatureDrawerPrinter {
  return {
    id: 'laser-1',
    name: 'xTool M1',
    nozzle: { temperature: null, target: null },
    bed: { temperature: null, target: null },
    capability: {
      machine_type: 'laser',
      profile: 'xtools-m1',
      nozzle_diameter_mm: null,
      build_volume: { x: 500, y: 300, z: 0 },
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
      safe_nozzle_max_c: null,
      safe_bed_max_c: null,
      motion_check_required: false,
      notes: [],
      maintenance_notes: [],
    },
    ...overrides,
  }
}

/**
 * Fixture: Built-in and user-defined temperature presets.
 */
const PRESET_FIXTURES: TempPreset[] = [
  { label: 'PLA', nozzle: 210, bed: 65, builtin: true },
  { label: 'PETG', nozzle: 235, bed: 80, builtin: true },
  { label: 'ABS', nozzle: 240, bed: 100, builtin: true },
]

/**
 * Helper: Render TemperatureDrawer with props.
 */
function renderTemperatureDrawer(props: Partial<DrawerProps> = {}) {
  const defaultProps: DrawerProps = {
    printerId: 'printer-1',
    currentPrinter: createThermalPrinter(),
    canWrite: true,
    ...props,
  }
  return render(<TemperatureDrawer {...defaultProps} />)
}

describe('TemperatureDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('renders current temperatures', () => {
    it('displays current nozzle and bed temperatures in current/target format', () => {
      const printer = createThermalPrinter({
        nozzle: { temperature: 205, target: 210 },
        bed: { temperature: 62, target: 65 },
      })

      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ currentPrinter: printer })

      // Verify header
      expect(screen.getByText('Temperature controls')).toBeInTheDocument()

      // Verify current/target display
      expect(screen.getByText('205 / 210')).toBeInTheDocument() // nozzle
      expect(screen.getByText('62 / 65')).toBeInTheDocument() // bed
    })

    it('formats null temperatures as — (em dash)', () => {
      const printer = createThermalPrinter({
        nozzle: { temperature: null, target: null },
        bed: { temperature: null, target: null },
      })

      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ currentPrinter: printer })

      const tempDisplays = screen.getAllByText('— / —')
      expect(tempDisplays.length).toBeGreaterThan(0)
    })
  })

  describe('renders temperature presets', () => {
    it('displays all presets when canWrite is true', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Verify all presets are rendered with their temperatures
      expect(screen.getByText('PLA 210/65')).toBeInTheDocument()
      expect(screen.getByText('PETG 235/80')).toBeInTheDocument()
      expect(screen.getByText('ABS 240/100')).toBeInTheDocument()
    })

    it('hides presets when canWrite is false', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: false })

      // Presets should not be rendered at all
      expect(screen.queryByText('PLA 210/65')).not.toBeInTheDocument()
      expect(screen.queryByText('PETG 235/80')).not.toBeInTheDocument()
    })
  })

  describe('apply preset button', () => {
    it('calls applyPreset when a preset button is clicked', async () => {
      const applyPresetMock = vi.fn()

      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: applyPresetMock,
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Click the PLA preset
      const plaButton = screen.getByText('PLA 210/65')
      fireEvent.click(plaButton)

      await waitFor(() => {
        expect(applyPresetMock).toHaveBeenCalledWith(210, 65)
      })
    })

    it('applies multiple presets independently', async () => {
      const applyPresetMock = vi.fn()

      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: applyPresetMock,
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Click PLA
      fireEvent.click(screen.getByText('PLA 210/65'))
      await waitFor(() => {
        expect(applyPresetMock).toHaveBeenCalledWith(210, 65)
      })

      // Click ABS
      fireEvent.click(screen.getByText('ABS 240/100'))
      await waitFor(() => {
        expect(applyPresetMock).toHaveBeenCalledWith(240, 100)
      })

      expect(applyPresetMock).toHaveBeenCalledTimes(2)
    })
  })

  describe('custom temperature input', () => {
    it('allows entering custom nozzle and bed temperatures', () => {
      const setCustomNozzleMock = vi.fn()
      const setCustomBedMock = vi.fn()

      const mockState = {
        customNozzle: '0',
        setCustomNozzle: setCustomNozzleMock,
        customBed: '0',
        setCustomBed: setCustomBedMock,
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      const { container } = renderTemperatureDrawer()

      // Find input fields by their labels - find all number inputs
      const numberInputs = container.querySelectorAll('input[type="number"]')
      const nozzleInput = numberInputs[0]
      const bedInput = numberInputs[1]

      // Simulate typing in nozzle field
      fireEvent.change(nozzleInput, { target: { value: '220' } })
      expect(setCustomNozzleMock).toHaveBeenCalledWith('220')

      // Simulate typing in bed field
      fireEvent.change(bedInput, { target: { value: '75' } })
      expect(setCustomBedMock).toHaveBeenCalledWith('75')
    })

    it('calls applyCustomTemperatures when Apply button is clicked', async () => {
      const applyCustomMock = vi.fn()

      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: applyCustomMock,
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Click the Apply button
      const applyButton = screen.getByText('Apply temperatures')
      fireEvent.click(applyButton)

      await waitFor(() => {
        expect(applyCustomMock).toHaveBeenCalled()
      })
    })

    it('hides Apply button when canWrite is false', () => {
      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: false })

      // Apply button should not be present
      expect(screen.queryByText('Apply temperatures')).not.toBeInTheDocument()
    })
  })

  describe('save preset workflow', () => {
    it('shows Save preset button initially', () => {
      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      expect(screen.getByText('Save preset')).toBeInTheDocument()
    })

    it('shows input field when Save preset button is clicked', async () => {
      const setSavePresetLabelMock = vi.fn()

      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: setSavePresetLabelMock,
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Click Save preset
      fireEvent.click(screen.getByText('Save preset'))

      await waitFor(() => {
        expect(setSavePresetLabelMock).toHaveBeenCalledWith('')
      })
    })

    it('calls saveCurrentPreset when Save button is clicked in input mode', async () => {
      const saveCurrentPresetMock = vi.fn()
      const setSavePresetLabelMock = vi.fn()

      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: 'My Custom PLA', // already in edit mode
        setSavePresetLabel: setSavePresetLabelMock,
        saveCurrentPreset: saveCurrentPresetMock,
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Find the Save button in the input mode
      const saveButton = screen.getByText('Save')
      fireEvent.click(saveButton)

      await waitFor(() => {
        expect(saveCurrentPresetMock).toHaveBeenCalled()
      })
    })

    it('cancels preset save when Cancel button is clicked', async () => {
      const setSavePresetLabelMock = vi.fn()

      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: 'My Custom PLA',
        setSavePresetLabel: setSavePresetLabelMock,
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Find the Cancel button
      const cancelButton = screen.getByText('Cancel')
      fireEvent.click(cancelButton)

      await waitFor(() => {
        expect(setSavePresetLabelMock).toHaveBeenCalledWith(null)
      })
    })

    it('saves preset when Enter key is pressed in input field', async () => {
      const saveCurrentPresetMock = vi.fn()

      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: 'My Custom PLA',
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: saveCurrentPresetMock,
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Find the preset name input
      const presetInput = screen.getByPlaceholderText('Preset name')

      // Simulate Enter key
      fireEvent.keyDown(presetInput, { key: 'Enter' })

      await waitFor(() => {
        expect(saveCurrentPresetMock).toHaveBeenCalled()
      })
    })

    it('cancels preset save when Escape key is pressed in input field', async () => {
      const setSavePresetLabelMock = vi.fn()

      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: 'My Custom PLA',
        setSavePresetLabel: setSavePresetLabelMock,
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      const presetInput = screen.getByPlaceholderText('Preset name')

      // Simulate Escape key
      fireEvent.keyDown(presetInput, { key: 'Escape' })

      await waitFor(() => {
        expect(setSavePresetLabelMock).toHaveBeenCalledWith(null)
      })
    })

    it('updates preset label when input value changes', () => {
      const setSavePresetLabelMock = vi.fn()

      const mockState = {
        customNozzle: '220',
        setCustomNozzle: vi.fn(),
        customBed: '75',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: 'My Custom PLA',
        setSavePresetLabel: setSavePresetLabelMock,
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      const presetInput = screen.getByPlaceholderText('Preset name')

      // Type a new label
      fireEvent.change(presetInput, { target: { value: 'Updated Label' } })

      expect(setSavePresetLabelMock).toHaveBeenCalledWith('Updated Label')
    })
  })

  describe('temperature history visualization', () => {
    it('renders SVG chart when history data is present', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: {
          extruder: [
            { temperature: 200, timestamp: 1000 },
            { temperature: 205, timestamp: 2000 },
            { temperature: 210, timestamp: 3000 },
          ],
          bed: [
            { temperature: 60, timestamp: 1000 },
            { temperature: 62, timestamp: 2000 },
            { temperature: 65, timestamp: 3000 },
          ],
        },
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      const { container } = renderTemperatureDrawer()

      // Verify the history section is rendered
      expect(screen.getByText(/Temperature history/)).toBeInTheDocument()

      // Verify SVG is present
      const svg = container.querySelector('svg')
      expect(svg).toBeInTheDocument()
    })

    it('displays temperature range labels in history', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: {
          extruder: [
            { temperature: 200, timestamp: 1000 },
            { temperature: 210, timestamp: 2000 },
          ],
          bed: [
            { temperature: 60, timestamp: 1000 },
            { temperature: 70, timestamp: 2000 },
          ],
        },
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer()

      // Should show temperature range (55°C – 75°C covers 60-70 with padding)
      expect(screen.getByText(/°C – \d+°C/)).toBeInTheDocument()
    })

    it('does not render history when no data is present', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer()

      expect(screen.queryByText(/Temperature history/)).not.toBeInTheDocument()
    })

    it('does not render history when both extruder and bed data are empty', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: {
          extruder: [],
          bed: [],
        },
        tempPresets: PRESET_FIXTURES,
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer()

      expect(screen.queryByText(/Temperature history/)).not.toBeInTheDocument()
    })
  })

  describe('edge cases', () => {
    it('handles missing printer gracefully', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: [],
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ currentPrinter: null })

      // Should still render title and inputs, just with null temps
      expect(screen.getByText('Temperature controls')).toBeInTheDocument()
      const tempDisplays = screen.getAllByText('— / —')
      expect(tempDisplays.length).toBeGreaterThan(0)
    })

    it('handles empty preset list', () => {
      const mockState = {
        customNozzle: '0',
        setCustomNozzle: vi.fn(),
        customBed: '0',
        setCustomBed: vi.fn(),
        applyPreset: vi.fn(),
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: [],
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      renderTemperatureDrawer({ canWrite: true })

      // Preset row should be empty but exist
      expect(screen.getByText('Temperature controls')).toBeInTheDocument()
      // No preset buttons should appear
      expect(screen.queryByText(/\d+\/\d+/)).not.toBeInTheDocument()
    })

    it('uses hook values for all state and operations', () => {
      const applyPresetMock = vi.fn()
      const setCustomNozzleMock = vi.fn()

      const mockState = {
        customNozzle: '210',
        setCustomNozzle: setCustomNozzleMock,
        customBed: '60',
        setCustomBed: vi.fn(),
        applyPreset: applyPresetMock,
        applyCustomTemperatures: vi.fn(),
        savePresetLabel: null,
        setSavePresetLabel: vi.fn(),
        saveCurrentPreset: vi.fn(),
        tempHistoryDetail: null,
        tempPresets: [],
        fmtTemp: (current: number | null, target: number | null) => {
          const fmt = (t: number | null) => (t !== null ? String(Math.round(t)) : '—')
          return `${fmt(current)} / ${fmt(target)}`
        },
      }

      vi.mocked(useTemperatureState).mockReturnValue(mockState)

      const { container } = render(
        <TemperatureDrawer
          printerId="test-id"
          currentPrinter={createThermalPrinter()}
          canWrite={true}
        />,
      )

      // Verify hook was called with correct params
      expect(useTemperatureState).toHaveBeenCalledWith('test-id', expect.any(Object))

      // Verify input fields display hook values
      const inputs = container.querySelectorAll('input[type="number"]')
      expect(inputs[0]).toHaveValue(210)
      expect(inputs[1]).toHaveValue(60)
    })
  })
})

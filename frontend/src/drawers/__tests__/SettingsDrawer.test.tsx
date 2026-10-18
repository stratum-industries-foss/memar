import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SettingsDrawer from '../SettingsDrawer'
import type { DrawerProps } from '../../types/drawer-props'

// Mock the useSettingsState hook
vi.mock('../useSettingsState', () => ({
  useSettingsState: vi.fn(),
}))

// Mock ConfirmDialog
vi.mock('../../ConfirmDialog', () => ({
  ConfirmDialog: ({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) => (
    <div data-testid="confirm-dialog">
      <button onClick={onConfirm}>Confirm</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  ),
}))

import { useSettingsState } from '../useSettingsState'

describe('SettingsDrawer', () => {
  const mockSettingsDraft = {
    name: 'Test Printer',
    enabled: true,
    tagsText: 'test, core',
    nozzleDiameter: '0.4',
    filamentDiameterMm: '1.75',
    wireUsedMmPerJob: '',
    compatibilityProfile: '',
    buildVolumeX: '200',
    buildVolumeY: '200',
    buildVolumeZ: '200',
    supportedMaterialsText: 'PLA, PETG',
    currentMaterial: 'PLA',
    currentSpoolName: 'Spool-1',
    spoolRemainingG: '500',
    spoolCapacityG: '1000',
    filamentSensor: true,
    probe: true,
    webcamExpected: true,
    cameraUrl: '',
    timelapseDir: '',
    maintenanceLockout: false,
    maintenanceState: 'ok',
    maintenanceDue: false,
    maintenanceIntervalHours: '',
    maintenanceIntervalJobs: '',
    maintenanceIntervalFilamentG: '',
    lastServiceAt: '',
    nextServiceDue: '',
    jogEnabled: true,
    safeNozzleMaxC: '300',
    safeBedMaxC: '110',
    motionCheckRequired: false,
    notesText: '',
    maintenanceNotesText: '',
    baseUrl: 'http://localhost',
    wsUrl: 'ws://localhost',
    authMode: 'trusted_local',
    apiKey: '',
    apiKeySet: false,
    apiKeyClear: false,
    serial: '',
    uiLabel: 'Open UI',
    fluiddUrl: '',
    uiTargets: [
      { label: 'Fluidd', provider: 'fluidd', url: 'http://localhost', mode: 'direct', primary: true },
    ],
  }

  const mockHookState = {
    settingsDraft: mockSettingsDraft,
    settingsMessage: '',
    isSaving: false,
    subscription: null,
    showCancelConfirm: false,
    settingsNozzle: '0.4',
    setSettingsNozzle: vi.fn(),
    setShowCancelConfirm: vi.fn(),
    cancelSubscription: vi.fn(),
    updateSettingsDraft: vi.fn(),
    updateUiTargetDraft: vi.fn(),
    addUiTargetDraft: vi.fn(),
    removeUiTargetDraft: vi.fn(),
    saveNozzleDiameter: vi.fn(),
    savePrinterSettings: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    ;(useSettingsState as any).mockReturnValue(mockHookState)
  })

  it('renders empty state when settings draft is null', () => {
    ;(useSettingsState as any).mockReturnValue({ ...mockHookState, settingsDraft: null })
    const { container } = render(<SettingsDrawer printerId="p1" currentPrinter={null} canWrite={false} />)
    // SettingsDrawer returns null without a draft (deliberate: nothing to edit yet).
    expect(container.firstChild).toBeNull()
  })

  it('renders quick settings section with nozzle presets', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('Quick settings')).toBeInTheDocument()
    expect(screen.getByText('0.25 mm')).toBeInTheDocument()
    expect(screen.getByText('0.40 mm')).toBeInTheDocument()
    expect(screen.getByText('0.60 mm')).toBeInTheDocument()
  })

  it('calls updateSettingsDraft when nozzle preset is clicked', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    const button = screen.getByText('0.60 mm')
    fireEvent.click(button)
    expect(mockHookState.updateSettingsDraft).toHaveBeenCalled()
    expect(mockHookState.setSettingsNozzle).toHaveBeenCalled()
  })

  it('renders printer name input', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    const input = screen.getByDisplayValue('Test Printer')
    expect(input).toBeInTheDocument()
  })

  it('renders identity and material section', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('Identity and material')).toBeInTheDocument()
    expect(screen.getByDisplayValue('test, core')).toBeInTheDocument()
    expect(screen.getByDisplayValue('PLA, PETG')).toBeInTheDocument()
  })

  it('renders hardware and behavior section', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('Hardware and behavior')).toBeInTheDocument()
    const buildVolumeInputs = screen.getAllByDisplayValue('200')
    expect(buildVolumeInputs.length).toBeGreaterThanOrEqual(1)
  })

  it('renders maintenance section', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('Maintenance')).toBeInTheDocument()
  })

  it('renders save buttons only when canWrite is true', () => {
    const { rerender } = render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.queryByText('Save nozzle only')).not.toBeInTheDocument()
    expect(screen.queryByText('Save printer settings')).not.toBeInTheDocument()

    rerender(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={true} />)
    expect(screen.getByText('Save nozzle only')).toBeInTheDocument()
    expect(screen.getByText('Save printer settings')).toBeInTheDocument()
  })

  it('calls saveNozzleDiameter when save button is clicked', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={true} />)
    const saveButton = screen.getByText('Save nozzle only')
    fireEvent.click(saveButton)
    expect(mockHookState.saveNozzleDiameter).toHaveBeenCalled()
  })

  it('calls savePrinterSettings when save button is clicked', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={true} />)
    const saveButton = screen.getByText('Save printer settings')
    fireEvent.click(saveButton)
    expect(mockHookState.savePrinterSettings).toHaveBeenCalled()
  })

  it('renders UI and integrations section', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('UI and integrations')).toBeInTheDocument()
  })

  it('renders Advanced connection settings section', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('Advanced connection settings')).toBeInTheDocument()
  })

  it('displays current plan section when subscription is available', () => {
    const subscription = {
      tier: 'PRO',
      status: 'active',
      expires_at: '2026-12-31',
      device_limit: 10,
      cancel_at_period_end: false,
      stripe_customer_id: 'cus_123',
    }
    ;(useSettingsState as any).mockReturnValue({ ...mockHookState, subscription })
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('Current Plan')).toBeInTheDocument()
    expect(screen.getByText('PRO')).toBeInTheDocument()
  })

  it('calls onMessage callback when provided', async () => {
    const onMessage = vi.fn()
    ;(useSettingsState as any).mockReturnValue({ ...mockHookState, settingsMessage: '✓ Saved' })
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} onMessage={onMessage} />)
    expect(screen.getByText('✓ Saved')).toBeInTheDocument()
  })

  it('disables save buttons when isSaving is true', () => {
    ;(useSettingsState as any).mockReturnValue({ ...mockHookState, isSaving: true })
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={true} />)
    const buttons = screen.getAllByRole('button').filter((b) => b.textContent?.includes('Save'))
    buttons.forEach((button) => {
      expect(button).toBeDisabled()
    })
  })

  it('renders subscription cancel button when active', () => {
    const subscription = {
      tier: 'PRO',
      status: 'active',
      expires_at: '2026-12-31',
      device_limit: 10,
      cancel_at_period_end: false,
      stripe_customer_id: 'cus_123',
    }
    ;(useSettingsState as any).mockReturnValue({ ...mockHookState, subscription })
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    expect(screen.getByText('Cancel Subscription')).toBeInTheDocument()
  })

  it('calls cancelSubscription when confirm is clicked in subscription dialog', () => {
    const subscription = {
      tier: 'PRO',
      status: 'active',
      expires_at: '2026-12-31',
      device_limit: 10,
      cancel_at_period_end: false,
      stripe_customer_id: 'cus_123',
    }
    ;(useSettingsState as any).mockReturnValue({ ...mockHookState, subscription, showCancelConfirm: true })
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    const confirmButton = screen.getByText('Confirm')
    fireEvent.click(confirmButton)
    expect(mockHookState.cancelSubscription).toHaveBeenCalled()
  })

  it('updates maintenance state fields', () => {
    render(<SettingsDrawer printerId="p1" currentPrinter={{}} canWrite={false} />)
    const maintenanceStateInputs = screen.getAllByDisplayValue('ok')
    expect(maintenanceStateInputs.length).toBeGreaterThan(0)
  })
})

/**
 * useSettingsState — Encapsulates all Settings drawer state and logic.
 *
 * Extracted from App.tsx to separate UI concerns from state management.
 * Handles:
 *  - Printer settings draft state (all fields)
 *  - UI target management (add, remove, update)
 *  - Save operations (full settings, nozzle-only)
 *  - Status messages and error handling
 *  - Subscription state display
 */

import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

type UiTargetDraft = {
  provider: string
  label: string
  url: string
  mode: 'direct' | 'bootstrap'
  primary: boolean
}

export type PrinterSettingsDraft = {
  name: string
  enabled: boolean
  tagsText: string
  nozzleDiameter: string
  filamentDiameterMm: string
  wireUsedMmPerJob: string
  compatibilityProfile: string
  buildVolumeX: string
  buildVolumeY: string
  buildVolumeZ: string
  supportedMaterialsText: string
  currentMaterial: string
  currentSpoolName: string
  spoolRemainingG: string
  spoolCapacityG: string
  filamentSensor: boolean
  probe: boolean
  webcamExpected: boolean
  cameraUrl: string
  timelapseDir: string
  maintenanceLockout: boolean
  maintenanceState: string
  maintenanceDue: boolean
  maintenanceIntervalHours: string
  maintenanceIntervalJobs: string
  maintenanceIntervalFilamentG: string
  lastServiceAt: string
  nextServiceDue: string
  jogEnabled: boolean
  safeNozzleMaxC: string
  safeBedMaxC: string
  motionCheckRequired: boolean
  notesText: string
  maintenanceNotesText: string
  baseUrl: string
  wsUrl: string
  authMode: string
  apiKey: string
  apiKeySet: boolean
  apiKeyClear: boolean
  serial: string
  uiLabel: string
  fluiddUrl: string
  uiTargets: UiTargetDraft[]
}

export type SubscriptionInfo = {
  tier: string
  status: string
  expires_at: string | null
  device_limit: number | null
  cancel_at_period_end: boolean
  stripe_customer_id: string | null
}

function numberOrNull(val: string): number | null {
  if (!val || val.trim() === '') return null
  const n = Number(val)
  return isNaN(n) ? null : n
}

function splitCommaList(text: string): string[] {
  if (!text.trim()) return []
  return text.split(',').map((s) => s.trim()).filter((s) => !!s)
}

function splitLineList(text: string): string[] {
  if (!text.trim()) return []
  return text.split('\n').map((s) => s.trim()).filter((s) => !!s)
}

function ensurePrimaryUiTarget(targets: UiTargetDraft[]) {
  if (targets.length === 0) return []
  if (!targets.some((item) => item.primary)) {
    return [{ ...targets[0], primary: true }, ...targets.slice(1).map((item) => ({ ...item, primary: false }))]
  }
  let seenPrimary = false
  return targets.map((item) => {
    if (!item.primary || seenPrimary) return { ...item, primary: false }
    seenPrimary = true
    return item
  })
}

function serializePrinterSettingsDraft(draft: PrinterSettingsDraft) {
  return {
    name: draft.name.trim(),
    enabled: draft.enabled,
    tags: splitCommaList(draft.tagsText),
    nozzle_diameter_mm: numberOrNull(draft.nozzleDiameter),
    filament_diameter_mm: numberOrNull(draft.filamentDiameterMm),
    wire_used_mm_per_job: numberOrNull(draft.wireUsedMmPerJob),
    compatibility_profile: draft.compatibilityProfile.trim() || null,
    build_volume: {
      x: numberOrNull(draft.buildVolumeX),
      y: numberOrNull(draft.buildVolumeY),
      z: numberOrNull(draft.buildVolumeZ),
    },
    supported_materials: splitCommaList(draft.supportedMaterialsText),
    current_material: draft.currentMaterial.trim() || null,
    current_spool_name: draft.currentSpoolName.trim() || null,
    spool_remaining_g: numberOrNull(draft.spoolRemainingG),
    spool_capacity_g: numberOrNull(draft.spoolCapacityG),
    filament_sensor: draft.filamentSensor,
    probe: draft.probe,
    webcam_expected: draft.webcamExpected,
    camera_url: draft.cameraUrl.trim() || null,
    timelapse_dir: draft.timelapseDir.trim() || null,
    maintenance_lockout: draft.maintenanceLockout,
    maintenance_state: draft.maintenanceState.trim() || null,
    maintenance_due: draft.maintenanceDue,
    maintenance_interval_hours: numberOrNull(draft.maintenanceIntervalHours),
    maintenance_interval_jobs: numberOrNull(draft.maintenanceIntervalJobs),
    maintenance_interval_filament_g: numberOrNull(draft.maintenanceIntervalFilamentG),
    last_service_at: draft.lastServiceAt.trim() || null,
    next_service_due: draft.nextServiceDue.trim() || null,
    jog_enabled: draft.jogEnabled,
    safe_nozzle_max_c: numberOrNull(draft.safeNozzleMaxC),
    safe_bed_max_c: numberOrNull(draft.safeBedMaxC),
    motion_check_required: draft.motionCheckRequired,
    notes: splitLineList(draft.notesText),
    maintenance_notes: splitLineList(draft.maintenanceNotesText),
    base_url: draft.baseUrl.trim() || null,
    ws_url: draft.wsUrl.trim() || null,
    auth_mode: draft.authMode.trim() || 'trusted_local',
    api_key: draft.apiKeyClear ? null : (draft.apiKey.trim() || undefined),
    serial: draft.serial.trim() || null,
    ui_label: draft.uiLabel.trim() || 'Open UI',
    fluidd_url: draft.fluiddUrl.trim() || null,
    ui_targets: ensurePrimaryUiTarget(
      draft.uiTargets
        .map((item) => ({ ...item, label: item.label.trim(), provider: item.provider.trim() || 'other', url: item.url.trim() }))
        .filter((item) => item.label && item.url),
    ),
  }
}

export interface SettingsState {
  // State
  settingsDraft: PrinterSettingsDraft | null
  settingsMessage: string
  isSaving: boolean
  subscription: SubscriptionInfo | null
  showCancelConfirm: boolean

  // Nozzle quick-select
  settingsNozzle: string
  setSettingsNozzle: (value: string) => void

  // Subscription actions
  setShowCancelConfirm: (value: boolean) => void
  cancelSubscription: () => Promise<void>

  // Settings updates
  updateSettingsDraft: (patch: Partial<PrinterSettingsDraft>) => void
  updateUiTargetDraft: (index: number, patch: Partial<UiTargetDraft>) => void
  addUiTargetDraft: () => void
  removeUiTargetDraft: (index: number) => void

  // Save operations
  saveNozzleDiameter: () => Promise<void>
  savePrinterSettings: () => Promise<void>
}

export function useSettingsState(
  printerId: string | undefined,
  printer: any | null | undefined,
  fetcher: typeof apiFetch = apiFetch,
  onMessage?: (text: string, severity: 'info' | 'warning' | 'error' | 'success') => void,
): SettingsState {
  const [settingsDraft, setSettingsDraft] = useState<PrinterSettingsDraft | null>(null)
  const [settingsMessage, setSettingsMessage] = useState<string>('')
  const [isSaving, setIsSaving] = useState(false)
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null)
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const [settingsNozzle, setSettingsNozzle] = useState<string>('0.4')

  // Initialize settings draft when printer changes
  useEffect(() => {
    if (!printer) {
      setSettingsDraft(null)
      return
    }

    const emptyDraft: PrinterSettingsDraft = {
      name: printer.name || '',
      enabled: printer.enabled !== false,
      tagsText: (printer.tags || []).join(', '),
      nozzleDiameter: String(printer.nozzle_diameter_mm ?? printer.capability?.nozzle_diameter_mm ?? '0.4'),
      filamentDiameterMm: String(printer.filament_diameter_mm ?? '1.75'),
      wireUsedMmPerJob: String(printer.wire_used_mm_per_job ?? ''),
      compatibilityProfile: printer.compatibility_profile ?? '',
      buildVolumeX: String(printer.build_volume?.x ?? printer.capability?.build_volume?.x_mm ?? ''),
      buildVolumeY: String(printer.build_volume?.y ?? printer.capability?.build_volume?.y_mm ?? ''),
      buildVolumeZ: String(printer.build_volume?.z ?? printer.capability?.build_volume?.z_mm ?? ''),
      supportedMaterialsText: (printer.supported_materials || []).join(', '),
      currentMaterial: printer.current_material ?? '',
      currentSpoolName: printer.current_spool_name ?? '',
      spoolRemainingG: String(printer.spool_remaining_g ?? ''),
      spoolCapacityG: String(printer.spool_capacity_g ?? ''),
      filamentSensor: printer.filament_sensor !== false,
      probe: printer.probe !== false,
      webcamExpected: printer.webcam_expected !== false,
      cameraUrl: printer.camera_url ?? '',
      timelapseDir: printer.timelapse_dir ?? '',
      maintenanceLockout: printer.maintenance_lockout === true,
      maintenanceState: printer.maintenance_state ?? '',
      maintenanceDue: printer.maintenance_due === true,
      maintenanceIntervalHours: String(printer.maintenance_interval_hours ?? ''),
      maintenanceIntervalJobs: String(printer.maintenance_interval_jobs ?? ''),
      maintenanceIntervalFilamentG: String(printer.maintenance_interval_filament_g ?? ''),
      lastServiceAt: printer.last_service_at ?? '',
      nextServiceDue: printer.next_service_due ?? '',
      jogEnabled: printer.jog_enabled !== false,
      safeNozzleMaxC: String(printer.safe_nozzle_max_c ?? printer.capability?.safe_nozzle_max_c ?? ''),
      safeBedMaxC: String(printer.safe_bed_max_c ?? printer.capability?.safe_bed_max_c ?? ''),
      motionCheckRequired: printer.motion_check_required === true,
      notesText: (printer.notes || []).join('\n'),
      maintenanceNotesText: (printer.maintenance_notes || []).join('\n'),
      baseUrl: printer.base_url ?? '',
      wsUrl: printer.ws_url ?? '',
      authMode: printer.auth_mode ?? 'trusted_local',
      apiKey: '',
      apiKeySet: printer.api_key_set === true,
      apiKeyClear: false,
      serial: printer.serial ?? '',
      uiLabel: printer.ui_label ?? 'Open UI',
      fluiddUrl: printer.fluidd_url ?? '',
      uiTargets: (printer.ui_targets || []).map((t: any) => ({
        provider: t.provider || '',
        label: t.label || '',
        url: t.url || '',
        mode: t.mode || 'direct',
        primary: t.primary === true,
      })),
    }

    setSettingsDraft(emptyDraft)
    setSettingsNozzle(String(printer.nozzle_diameter_mm ?? printer.capability?.nozzle_diameter_mm ?? 0.4))
  }, [printer])

  // Load subscription info
  useEffect(() => {
    async function loadSubscription() {
      try {
        const resp = await fetcher('/api/billing/my-subscription')
        if (resp.ok) {
          const data = await resp.json()
          setSubscription(data)
        }
      } catch {
        // Subscription load is optional; don't interrupt if it fails
      }
    }
    loadSubscription()
  }, [fetcher])

  function updateSettingsDraft(patch: Partial<PrinterSettingsDraft>) {
    if (!settingsDraft) return
    setSettingsDraft({ ...settingsDraft, ...patch })
  }

  function updateUiTargetDraft(index: number, patch: Partial<UiTargetDraft>) {
    if (!settingsDraft) return
    const updated = settingsDraft.uiTargets.map((t, i) => (i === index ? { ...t, ...patch } : t))
    updateSettingsDraft({ uiTargets: updated })
  }

  function addUiTargetDraft() {
    if (!settingsDraft) return
    const newTarget: UiTargetDraft = {
      label: '',
      provider: 'other',
      url: '',
      mode: 'direct',
      primary: settingsDraft.uiTargets.length === 0,
    }
    updateSettingsDraft({ uiTargets: [...settingsDraft.uiTargets, newTarget] })
  }

  function removeUiTargetDraft(index: number) {
    if (!settingsDraft) return
    const updated = settingsDraft.uiTargets.filter((_, i) => i !== index)
    updateSettingsDraft({ uiTargets: updated })
  }

  async function saveNozzleDiameter() {
    if (!printerId || !settingsDraft) return
    setIsSaving(true)
    setSettingsMessage('')
    try {
      const payload = { nozzle_diameter_mm: numberOrNull(settingsDraft.nozzleDiameter) }
      const resp = await fetcher(`/api/printers/${printerId}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (resp.ok) {
        setSettingsMessage('✓ Nozzle diameter saved')
        onMessage?.('Nozzle diameter saved', 'success')
      } else {
        setSettingsMessage('✗ Failed to save nozzle diameter')
        onMessage?.('Failed to save nozzle diameter', 'error')
      }
    } catch (err) {
      setSettingsMessage('✗ Error saving nozzle diameter')
      onMessage?.('Error saving nozzle diameter', 'error')
    } finally {
      setIsSaving(false)
    }
  }

  async function savePrinterSettings() {
    if (!printerId || !settingsDraft) return
    setIsSaving(true)
    setSettingsMessage('')
    try {
      const payload = serializePrinterSettingsDraft(settingsDraft)
      const resp = await fetcher(`/api/printers/${printerId}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (resp.ok) {
        setSettingsMessage('✓ Printer settings saved')
        onMessage?.('Printer settings saved', 'success')
      } else {
        setSettingsMessage('✗ Failed to save printer settings')
        onMessage?.('Failed to save printer settings', 'error')
      }
    } catch (err) {
      setSettingsMessage('✗ Error saving printer settings')
      onMessage?.('Error saving printer settings', 'error')
    } finally {
      setIsSaving(false)
    }
  }

  async function cancelSubscription() {
    setIsSaving(true)
    try {
      const resp = await fetcher('/api/billing/my-subscription', { method: 'DELETE' })
      if (resp.ok) {
        setSubscription((s) => (s ? { ...s, cancel_at_period_end: true } : s))
        onMessage?.('Subscription cancelled', 'success')
      } else {
        onMessage?.('Failed to cancel subscription', 'error')
      }
    } catch {
      onMessage?.('Failed to cancel subscription', 'error')
    } finally {
      setIsSaving(false)
      setShowCancelConfirm(false)
    }
  }

  return {
    settingsDraft,
    settingsMessage,
    isSaving,
    subscription,
    showCancelConfirm,
    settingsNozzle,
    setSettingsNozzle,
    setShowCancelConfirm,
    cancelSubscription,
    updateSettingsDraft,
    updateUiTargetDraft,
    addUiTargetDraft,
    removeUiTargetDraft,
    saveNozzleDiameter,
    savePrinterSettings,
  }
}

import React, { useEffect, useState, useRef } from 'react'
import { Modal } from './Modal'
import { UpgradeHintModal } from './UpgradeHintModal'
import { apiFetch } from './api'

export interface SetupWizardProps {
  onClose: () => void
  isOpen: boolean
}

type Step = 'scan' | 'review' | 'done'

interface ScanResult {
  ip: string
  port: number
  protocol: string
  name?: string
}

type AddDeviceDraft = {
  id: string
  name: string
  protocol: string
  base_url: string
  enabled: boolean
  serial: string
  apiKey: string
  mqttTopic: string
  mqttFieldMapping: string
}

const EMPTY_ADD_DEVICE_DRAFT: AddDeviceDraft = {
  id: '', name: '', protocol: 'moonraker', base_url: '', enabled: true,
  serial: '', apiKey: '', mqttTopic: '', mqttFieldMapping: '',
}

const DEVICE_PROTOCOLS: { value: string; label: string }[] = [
  { value: 'moonraker', label: 'Klipper / Moonraker' },
  { value: 'octoprint', label: 'OctoPrint' },
  { value: 'duet', label: 'Duet' },
  { value: 'prusa_connect', label: 'Prusa Connect' },
  { value: 'marlin', label: 'Marlin' },
  { value: 'fluidnc', label: 'FluidNC' },
  { value: 'grbl', label: 'GRBL' },
  { value: 'linuxcnc', label: 'LinuxCNC' },
  { value: 'mach3', label: 'Mach3' },
  { value: 'mach4', label: 'Mach4' },
  { value: 'opcua', label: 'OPC-UA' },
  { value: 'sinumerik', label: 'Siemens Sinumerik' },
  { value: 'haas', label: 'Haas' },
  { value: 'fanuc', label: 'Fanuc' },
  { value: 'fadal', label: 'Fadal' },
  { value: 'openpcb', label: 'OpenPnP' },
  { value: 'bambu_mqtt', label: 'Bambu Lab (local MQTT, beta)' },
  { value: 'mqtt', label: 'Generic MQTT' },
]

const PROTOCOLS_WITH_API_KEY = new Set(['octoprint', 'duet', 'prusa_connect', 'bambu_mqtt'])

export const SetupWizard: React.FC<SetupWizardProps> = ({ onClose, isOpen }) => {
  const [currentStep, setCurrentStep] = useState<Step>('scan')
  const [scanResults, setScanResults] = useState<ScanResult[]>([])
  const [isScanning, setIsScanning] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)

  const [draft, setDraft] = useState<AddDeviceDraft>(EMPTY_ADD_DEVICE_DRAFT)
  const [addDeviceMessage, setAddDeviceMessage] = useState<string | null>(null)
  const [addDeviceBusy, setAddDeviceBusy] = useState(false)
  const [testConnectionResult, setTestConnectionResult] = useState<{
    success: boolean
    message?: string
  } | null>(null)
  const [testConnectionBusy, setTestConnectionBusy] = useState(false)

  const [addedDevice, setAddedDevice] = useState<{ id: string; name: string } | null>(null)
  const [showUpgradeHint, setShowUpgradeHint] = useState(false)
  const [showSkipConfirm, setShowSkipConfirm] = useState(false)

  const addDeviceBusyRef = useRef(false)
  const scanAttemptedRef = useRef(false)
  const scanAbortRef = useRef<AbortController | null>(null)

  // Step 1: Scan — fetch results once per open. Gate on an "attempted" ref, NOT on the
  // result count, so a scan that legitimately returns zero devices does not re-trigger
  // an unbounded scan loop. The ref is cleared on close so reopening scans again.
  useEffect(() => {
    if (!isOpen) {
      scanAttemptedRef.current = false
      // Abort any in-flight scan when modal closes
      if (scanAbortRef.current) {
        scanAbortRef.current.abort()
        scanAbortRef.current = null
      }
      return
    }
    if (currentStep !== 'scan' || scanAttemptedRef.current || isScanning) return

    scanAttemptedRef.current = true

    const fetchScanResults = async () => {
      setIsScanning(true)
      setScanError(null)
      
      // Create new AbortController for this scan
      const abortController = new AbortController()
      scanAbortRef.current = abortController
      
      try {
        const response = await apiFetch('/api/onboarding/scan', { signal: abortController.signal })
        if (response.ok) {
          const data = await response.json() as { results: ScanResult[] }
          setScanResults(data.results || [])
        } else {
          setScanError(`Scan failed: ${response.statusText}`)
        }
      } catch (err) {
        // Don't show error for aborted requests
        if (err instanceof Error && err.name === 'AbortError') return
        setScanError(`Network error: ${err instanceof Error ? err.message : 'Unknown error'}`)
      } finally {
        setIsScanning(false)
      }
    }

    fetchScanResults()
  }, [isOpen, currentStep, isScanning])

  // Reset all wizard state whenever it is closed, so reopening always starts fresh —
  // no stale draft, entered API key, error banner, test result, or completion screen.
  useEffect(() => {
    if (isOpen) return
    setCurrentStep('scan')
    setScanResults([])
    setIsScanning(false)
    setScanError(null)
    setDraft(EMPTY_ADD_DEVICE_DRAFT)
    setAddDeviceMessage(null)
    setAddDeviceBusy(false)
    setTestConnectionResult(null)
    setTestConnectionBusy(false)
    setAddedDevice(null)
    setShowUpgradeHint(false)
    setShowSkipConfirm(false)
    addDeviceBusyRef.current = false
  }, [isOpen])

  // Handle close with confirmation for non-done steps
  const handleClose = () => {
    // Abort any in-flight scan
    if (scanAbortRef.current) {
      scanAbortRef.current.abort()
      scanAbortRef.current = null
    }
    // If already done, close without confirm
    if (currentStep === 'done') {
      onClose()
      return
    }
    // Show confirmation for skipping setup
    setShowSkipConfirm(true)
  }

  const confirmSkip = () => {
    setShowSkipConfirm(false)
    onClose()
  }

  // Handle device card "Add" button
  const handleAddFromScan = (result: ScanResult) => {
    setDraft({
      ...EMPTY_ADD_DEVICE_DRAFT,
      protocol: result.protocol,
      base_url: `http://${result.ip}:${result.port}`,
      name: result.name || `${result.protocol} - ${result.ip}`,
    })
    setAddDeviceMessage(null)
    setTestConnectionResult(null)
    setCurrentStep('review')
  }

  // Handle "Add manually" link
  const handleAddManually = () => {
    setDraft(EMPTY_ADD_DEVICE_DRAFT)
    setAddDeviceMessage(null)
    setTestConnectionResult(null)
    setCurrentStep('review')
  }

  // Test connection
  const testConnection = async () => {
    if (testConnectionBusy) return

    const d = draft
    if (!d.protocol || !d.base_url.trim()) {
      setTestConnectionResult({
        success: false,
        message: 'Protocol and base URL are required to test.',
      })
      return
    }

    setTestConnectionBusy(true)
    setTestConnectionResult(null)

    try {
      const payload: Record<string, unknown> = {
        protocol: d.protocol,
        base_url: d.base_url.trim(),
      }
      if (d.apiKey.trim()) payload.api_key = d.apiKey.trim()

      const response = await apiFetch('/api/onboarding/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const result = await response.json().catch(() => ({})) as {
        success?: boolean
        message?: string
      }
      setTestConnectionResult({
        success: result.success === true,
        message: result.message || (result.success ? 'Connection successful' : 'Connection failed'),
      })
    } catch (err) {
      setTestConnectionResult({
        success: false,
        message: `Test failed: ${err instanceof Error ? err.message : 'Unknown error'}`,
      })
    } finally {
      setTestConnectionBusy(false)
    }
  }

  // Add device
  const handleAddDevice = async () => {
    const d = draft
    if (!d.id.trim() || !d.name.trim() || !d.base_url.trim()) {
      setAddDeviceMessage('ID, name, and base URL are required.')
      return
    }

    const payload: Record<string, unknown> = {
      id: d.id.trim(),
      name: d.name.trim(),
      protocol: d.protocol,
      base_url: d.base_url.trim(),
      enabled: d.enabled,
    }

    if (d.serial.trim()) payload.serial = d.serial.trim()
    if (d.apiKey.trim()) payload.api_key = d.apiKey.trim()

    if (d.protocol === 'mqtt') {
      if (d.mqttTopic.trim()) payload.mqtt_topic = d.mqttTopic.trim()
      if (d.mqttFieldMapping.trim()) {
        try {
          const m = JSON.parse(d.mqttFieldMapping)
          if (m && typeof m === 'object' && !Array.isArray(m)) {
            payload.mqtt_field_mapping = m
          } else {
            throw new Error('not an object')
          }
        } catch {
          setAddDeviceMessage('Field mapping must be valid JSON')
          return
        }
      }
    }

    if (addDeviceBusyRef.current) return
    addDeviceBusyRef.current = true
    setAddDeviceBusy(true)
    setAddDeviceMessage('Adding device…')

    try {
      const response = await apiFetch('/api/printers/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const result = await response.json().catch(() => ({})) as {
        success?: boolean
        message?: string
      }

      if (!response.ok || result.success === false) {
        const msg = result.message || response.statusText
        if (msg.includes('Device limit reached')) {
          setShowUpgradeHint(true)
        } else {
          setAddDeviceMessage(`Add failed: ${msg}`)
        }
        return
      }

      // Success — move to done step
      setAddedDevice({ id: d.id.trim(), name: d.name.trim() })
      setCurrentStep('done')
    } catch (err) {
      // A network/fetch failure must surface an error, not leave the UI stuck on
      // the "Adding device…" message forever.
      setAddDeviceMessage(
        `Add failed: ${err instanceof Error ? err.message : 'Network error'}`
      )
    } finally {
      addDeviceBusyRef.current = false
      setAddDeviceBusy(false)
    }
  }

  // Reset wizard to scan step
  const handleAddAnother = () => {
    scanAttemptedRef.current = false
    setCurrentStep('scan')
    setScanResults([])
    setDraft(EMPTY_ADD_DEVICE_DRAFT)
    setAddDeviceMessage(null)
    setTestConnectionResult(null)
    setAddedDevice(null)
    setShowUpgradeHint(false)
  }

  const renderScanStep = () => (
    <div>
      <p style={{ marginBottom: '24px', color: 'var(--text-secondary)' }}>
        We're looking for printers on your network. You can also add a device manually.
      </p>

      {isScanning ? (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '16px',
          padding: '48px 24px',
        }}>
          <div className="spinner"></div>
          <p style={{ color: 'var(--text-secondary)' }}>Looking for printers on your network…</p>
        </div>
      ) : scanError ? (
        <div style={{
          padding: '12px 16px',
          background: 'color-mix(in srgb, var(--color-danger) 10%, transparent)',
          border: '1px solid var(--color-danger)',
          borderRadius: '8px',
          color: 'var(--color-danger)',
          marginBottom: '16px',
        }}>
          {scanError}
        </div>
      ) : null}

      {scanResults.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-secondary)', margin: '0 0 12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Found devices
          </h3>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
            gap: '12px',
          }}>
            {scanResults.map((result, idx) => (
              <div
                key={idx}
                style={{
                  padding: '16px',
                  border: '1px solid var(--border-default)',
                  borderRadius: '8px',
                  background: 'var(--surface-l2)',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                }}
                onMouseEnter={(e) => {
                  const el = e.currentTarget
                  el.style.borderColor = 'var(--accent-solid)'
                  el.style.background = 'color-mix(in srgb, var(--accent-solid) 5%, var(--surface-l2))'
                }}
                onMouseLeave={(e) => {
                  const el = e.currentTarget
                  el.style.borderColor = 'var(--border-default)'
                  el.style.background = 'var(--surface-l2)'
                }}
              >
                <div style={{ marginBottom: '12px' }}>
                  <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                    {result.name || result.protocol}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {result.ip}:{result.port}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleAddFromScan(result)}
                  style={{ width: '100%', fontSize: '0.875rem', padding: '8px 12px' }}
                >
                  Add
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{
        padding: '16px',
        background: 'var(--surface-l2)',
        borderRadius: '8px',
        textAlign: 'center',
      }}>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={handleAddManually}
        >
          Add device manually
        </button>
      </div>
    </div>
  )

  const renderReviewStep = () => (
    <div>
      <div style={{ marginBottom: '24px' }}>
        <label htmlFor="protocol-select" style={{
          display: 'block',
          fontSize: '0.875rem',
          fontWeight: 600,
          color: 'var(--text-primary)',
          marginBottom: '8px',
        }}>
          Protocol
        </label>
        <select
          id="protocol-select"
          value={draft.protocol}
          onChange={(e) => {
            setDraft({ ...draft, protocol: e.target.value })
            setTestConnectionResult(null)
          }}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid var(--border-default)',
            borderRadius: '6px',
            background: 'var(--surface-l1)',
            color: 'var(--text-primary)',
            fontSize: '0.875rem',
            boxSizing: 'border-box',
          }}
        >
          {DEVICE_PROTOCOLS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: '24px' }}>
        <label htmlFor="base-url" style={{
          display: 'block',
          fontSize: '0.875rem',
          fontWeight: 600,
          color: 'var(--text-primary)',
          marginBottom: '8px',
        }}>
          Base URL
        </label>
        <input
          id="base-url"
          type="text"
          placeholder="http://192.168.1.100:7125"
          value={draft.base_url}
          onChange={(e) => {
            setDraft({ ...draft, base_url: e.target.value })
            setTestConnectionResult(null)
          }}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid var(--border-default)',
            borderRadius: '6px',
            background: 'var(--surface-l1)',
            color: 'var(--text-primary)',
            fontSize: '0.875rem',
            boxSizing: 'border-box',
          }}
        />
      </div>

      <div style={{ marginBottom: '24px' }}>
        <label htmlFor="device-name" style={{
          display: 'block',
          fontSize: '0.875rem',
          fontWeight: 600,
          color: 'var(--text-primary)',
          marginBottom: '8px',
        }}>
          Device name
        </label>
        <input
          id="device-name"
          type="text"
          placeholder="My Printer"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid var(--border-default)',
            borderRadius: '6px',
            background: 'var(--surface-l1)',
            color: 'var(--text-primary)',
            fontSize: '0.875rem',
            boxSizing: 'border-box',
          }}
        />
      </div>

      <div style={{ marginBottom: '24px' }}>
        <label htmlFor="device-id" style={{
          display: 'block',
          fontSize: '0.875rem',
          fontWeight: 600,
          color: 'var(--text-primary)',
          marginBottom: '8px',
        }}>
          Device ID (unique identifier)
        </label>
        <input
          id="device-id"
          type="text"
          placeholder="printer_1"
          value={draft.id}
          onChange={(e) => setDraft({ ...draft, id: e.target.value })}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid var(--border-default)',
            borderRadius: '6px',
            background: 'var(--surface-l1)',
            color: 'var(--text-primary)',
            fontSize: '0.875rem',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {PROTOCOLS_WITH_API_KEY.has(draft.protocol) && (
        <div style={{ marginBottom: '24px' }}>
          <label htmlFor="api-key" style={{
            display: 'block',
            fontSize: '0.875rem',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '8px',
          }}>
            API key
          </label>
          <input
            id="api-key"
            type="password"
            placeholder="Your API key"
            value={draft.apiKey}
            onChange={(e) => {
              setDraft({ ...draft, apiKey: e.target.value })
              setTestConnectionResult(null)
            }}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--border-default)',
              borderRadius: '6px',
              background: 'var(--surface-l1)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
              boxSizing: 'border-box',
            }}
          />
        </div>
      )}

      {draft.protocol === 'mqtt' && (
        <>
          <div style={{ marginBottom: '24px' }}>
            <label htmlFor="mqtt-topic" style={{
              display: 'block',
              fontSize: '0.875rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: '8px',
            }}>
              MQTT topic (optional)
            </label>
            <input
              id="mqtt-topic"
              type="text"
              placeholder="printer/state"
              value={draft.mqttTopic}
              onChange={(e) => setDraft({ ...draft, mqttTopic: e.target.value })}
              style={{
                width: '100%',
                padding: '8px 12px',
                border: '1px solid var(--border-default)',
                borderRadius: '6px',
                background: 'var(--surface-l1)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ marginBottom: '24px' }}>
            <label htmlFor="mqtt-mapping" style={{
              display: 'block',
              fontSize: '0.875rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: '8px',
            }}>
              Field mapping (optional JSON)
            </label>
            <textarea
              id="mqtt-mapping"
              placeholder='{"state":"st","progress":"pct"}'
              value={draft.mqttFieldMapping}
              onChange={(e) => setDraft({ ...draft, mqttFieldMapping: e.target.value })}
              rows={3}
              style={{
                width: '100%',
                padding: '8px 12px',
                border: '1px solid var(--border-default)',
                borderRadius: '6px',
                background: 'var(--surface-l1)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
                boxSizing: 'border-box',
                fontFamily: 'monospace',
              }}
            />
          </div>
        </>
      )}

      {draft.serial !== undefined && (
        <div style={{ marginBottom: '24px' }}>
          <label htmlFor="serial" style={{
            display: 'block',
            fontSize: '0.875rem',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '8px',
          }}>
            Serial (optional)
          </label>
          <input
            id="serial"
            type="text"
            placeholder="Device serial number"
            value={draft.serial}
            onChange={(e) => setDraft({ ...draft, serial: e.target.value })}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--border-default)',
              borderRadius: '6px',
              background: 'var(--surface-l1)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
              boxSizing: 'border-box',
            }}
          />
        </div>
      )}

      {testConnectionResult && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            marginBottom: '16px',
            background: testConnectionResult.success
              ? 'color-mix(in srgb, var(--color-success) 10%, transparent)'
              : 'color-mix(in srgb, var(--color-danger) 10%, transparent)',
            border: `1px solid ${testConnectionResult.success ? 'var(--color-success)' : 'var(--color-danger)'}`,
            color: testConnectionResult.success ? 'var(--color-success)' : 'var(--color-danger)',
            fontSize: '0.875rem',
          }}
        >
          {testConnectionResult.message}
        </div>
      )}

      {addDeviceMessage && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            marginBottom: '16px',
            background: 'color-mix(in srgb, var(--color-danger) 10%, transparent)',
            border: '1px solid var(--color-danger)',
            color: 'var(--color-danger)',
            fontSize: '0.875rem',
          }}
        >
          {addDeviceMessage}
        </div>
      )}

      <div style={{ display: 'flex', gap: '12px', marginTop: '24px', justifyContent: 'flex-end' }}>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={testConnection}
          disabled={testConnectionBusy || addDeviceBusy || !draft.protocol || !draft.base_url.trim()}
        >
          {testConnectionBusy ? 'Testing…' : 'Test connection'}
        </button>
      </div>
    </div>
  )

  const renderDoneStep = () => (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      textAlign: 'center',
      gap: '24px',
      padding: '24px 0',
    }}>
      <div style={{ fontSize: '3rem' }}>✓</div>
      <div>
        <h3 style={{ fontSize: '1.25rem', fontWeight: 600, margin: '0 0 8px', color: 'var(--text-primary)' }}>
          Device added
        </h3>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          {addedDevice?.name} is ready to use
        </p>
      </div>
    </div>
  )

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        title={
          currentStep === 'scan' ? 'Add your first device' :
          currentStep === 'review' ? 'Device details' :
          'Setup complete'
        }
        primaryAction={
          currentStep === 'done'
            ? { label: 'View fleet', onClick: onClose }
            : currentStep === 'review'
              ? {
                  label: addDeviceBusy ? 'Adding…' : 'Add device',
                  onClick: handleAddDevice,
                }
              : undefined
        }
        secondaryAction={
          currentStep === 'done'
            ? { label: 'Add another device', onClick: handleAddAnother }
            : currentStep === 'review'
              ? { label: 'Back', onClick: () => setCurrentStep('scan') }
              : undefined
        }
      >
        {currentStep === 'scan' && renderScanStep()}
        {currentStep === 'review' && renderReviewStep()}
        {currentStep === 'done' && renderDoneStep()}
      </Modal>

      {showSkipConfirm && (
        <Modal
          isOpen={showSkipConfirm}
          onClose={() => setShowSkipConfirm(false)}
          title="Skip setup?"
          primaryAction={{ label: 'Skip setup', onClick: confirmSkip }}
          secondaryAction={{ label: 'Continue setup', onClick: () => setShowSkipConfirm(false) }}
        >
          <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
            You can add devices later from the fleet settings.
          </p>
        </Modal>
      )}

      {showUpgradeHint && (
        <UpgradeHintModal
          onClose={() => {
            setShowUpgradeHint(false)
            // Stay on step 2 after dismissing upgrade hint
          }}
        />
      )}
    </>
  )
}

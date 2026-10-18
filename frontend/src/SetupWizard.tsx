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
  already_added?: boolean
  suggested_id?: string
}

interface ScanMeta {
  subnet?: string
  subnet_source?: string
  in_container?: boolean
  scan_capped?: boolean
}

type RowState = {
  state: 'adding' | 'added' | 'failed' | 'skipped'
  message?: string
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

const protocolLabel = (protocol: string): string =>
  DEVICE_PROTOCOLS.find((p) => p.value === protocol)?.label ?? protocol

const rowKey = (r: ScanResult): string => `${r.ip}:${r.port}`

// People type "192.168.2.x" (or "192.168.2"); the API wants a CIDR.
export const toSubnet = (raw: string): string => {
  const t = raw.trim()
  const m = t.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\.(?:x|\*|0|\d{1,3}))?$/i)
  if (!m || t.includes('/')) return t
  // Each octet must be 0-255. Without this, 999.1.1.x built a non-address that the scanner
  // then rejected with an unclear error. Returning the input unchanged lets the user see it.
  const octets = [m[1], m[2], m[3]].map(Number)
  if (octets.some((o) => o > 255)) return t
  return `${m[1]}.${m[2]}.${m[3]}.0/24`
}

// Display title: a found device without a name of its own reads as "OctoPrint printer";
// the address goes in the line below. The saved device name keeps the address.
const rowTitle = (r: ScanResult): string =>
  r.name && r.name.trim() && !r.name.includes(r.ip) ? r.name.trim() : `${protocolLabel(r.protocol)} printer`

const displayName = (r: ScanResult): string =>
  r.name && r.name.trim() ? r.name.trim() : `${protocolLabel(r.protocol)} ${r.ip}:${r.port}`

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 12px',
  border: '1px solid var(--border-default)',
  borderRadius: '6px',
  background: 'var(--surface-l1)',
  color: 'var(--text-primary)',
  fontSize: '0.875rem',
  boxSizing: 'border-box',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '0.875rem',
  fontWeight: 600,
  color: 'var(--text-primary)',
  marginBottom: '8px',
}

const errorBoxStyle: React.CSSProperties = {
  padding: '12px 16px',
  background: 'color-mix(in srgb, var(--color-danger) 10%, transparent)',
  border: '1px solid var(--color-danger)',
  borderRadius: '8px',
  color: 'var(--color-danger)',
  fontSize: '0.875rem',
  marginBottom: '16px',
}

const noteBoxStyle: React.CSSProperties = {
  padding: '12px 16px',
  background: 'var(--surface-l2)',
  border: '1px solid var(--border-default)',
  borderRadius: '8px',
  color: 'var(--text-secondary)',
  fontSize: '0.875rem',
  marginBottom: '16px',
}

export const SetupWizard: React.FC<SetupWizardProps> = ({ onClose, isOpen }) => {
  const [currentStep, setCurrentStep] = useState<Step>('scan')

  // Scan state
  const [scanResults, setScanResults] = useState<ScanResult[]>([])
  const [scanMeta, setScanMeta] = useState<ScanMeta | null>(null)
  const [activeSubnet, setActiveSubnet] = useState<string | undefined>(undefined)
  const [subnetInput, setSubnetInput] = useState('')
  const [isScanning, setIsScanning] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)

  // Licence / device-limit state
  const [licenseLimit, setLicenseLimit] = useState<number | null>(null)
  const [showSubnetInput, setShowSubnetInput] = useState(false)
  const [currentCount, setCurrentCount] = useState(0)

  // Multi-select state (row keys are "ip:port")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [rowApiKeys, setRowApiKeys] = useState<Record<string, string>>({})
  const [rowStatus, setRowStatus] = useState<Record<string, RowState>>({})
  const [batchBusy, setBatchBusy] = useState(false)
  const [batchMessage, setBatchMessage] = useState<string | null>(null)
  const [addedNames, setAddedNames] = useState<string[]>([])

  // Manual add state
  const [draft, setDraft] = useState<AddDeviceDraft>(EMPTY_ADD_DEVICE_DRAFT)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [addDeviceMessage, setAddDeviceMessage] = useState<string | null>(null)
  const [addDeviceBusy, setAddDeviceBusy] = useState(false)
  const [testConnectionResult, setTestConnectionResult] = useState<{
    success: boolean
    message?: string
  } | null>(null)
  const [testConnectionBusy, setTestConnectionBusy] = useState(false)

  const [showUpgradeHint, setShowUpgradeHint] = useState(false)
  const [showSkipConfirm, setShowSkipConfirm] = useState(false)

  const addDeviceBusyRef = useRef(false)
  const batchBusyRef = useRef(false)
  const scanAttemptedRef = useRef(false)
  const scanAbortRef = useRef<AbortController | null>(null)

  const remainingSlots: number | null =
    licenseLimit === null ? null : Math.max(0, licenseLimit - currentCount)

  const isRowAdded = (r: ScanResult): boolean =>
    r.already_added === true || rowStatus[rowKey(r)]?.state === 'added'

  // Keys of rows that are still waiting to be added, in selection order.
  const pendingKeys = (sel: Set<string>): string[] => {
    const addedKeys = new Set(scanResults.filter(isRowAdded).map(rowKey))
    return [...sel].filter((k) => !addedKeys.has(k))
  }

  useEffect(() => {
    setSelected((prev) => {
      const pending = pendingKeys(prev)
      const cap = remainingSlots === null ? pending.length : Math.max(remainingSlots, 0)
      const next = pending.slice(0, cap)
      return next.length === prev.size && next.every((k) => prev.has(k)) ? prev : new Set(next)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remainingSlots, scanResults, rowStatus])

  // Load the device limit and the current device count (best effort; no limit on failure).
  const loadLicenseAndCount = async () => {
    try {
      const [licenseRes, printersRes] = await Promise.all([
        apiFetch('/api/license/status'),
        apiFetch('/api/printers'),
      ])
      if (licenseRes.ok) {
        const lic = await licenseRes.json().catch(() => ({})) as { device_limit?: number | null }
        setLicenseLimit(typeof lic.device_limit === 'number' ? lic.device_limit : null)
      }
      if (printersRes.ok) {
        const list = await printersRes.json().catch(() => null)
        setCurrentCount(Array.isArray(list) ? list.length : 0)
      }
    } catch {
      // Best effort: without the limit the chooser simply does not cap selection.
    }
  }

  // Scan the network. `subnet` is an optional user-supplied private CIDR.
  const runScan = async (subnet?: string) => {
    if (scanAbortRef.current) scanAbortRef.current.abort()
    const abortController = new AbortController()
    scanAbortRef.current = abortController

    setIsScanning(true)
    setScanError(null)
    setBatchMessage(null)

    const url = subnet
      ? `/api/onboarding/scan?subnet=${encodeURIComponent(subnet)}`
      : '/api/onboarding/scan'

    try {
      const response = await apiFetch(url, { signal: abortController.signal })
      if (abortController.signal.aborted) return
      if (response.ok) {
        const data = await response.json().catch(() => ({})) as ScanMeta & { results?: ScanResult[] }
        setScanResults(Array.isArray(data.results) ? data.results : [])
        setScanMeta({
          subnet: data.subnet,
          subnet_source: data.subnet_source,
          in_container: data.in_container,
          scan_capped: data.scan_capped,
        })
        setActiveSubnet(subnet)
        const found: ScanResult[] = Array.isArray(data.results) ? data.results : []
        setSelected(new Set(found.filter((r) => r.protocol === 'moonraker' && r.already_added !== true).map(rowKey)))
        setShowSubnetInput(false)
        setRowStatus({})
      } else if (response.status === 401 || response.status === 403) {
        setScanError('Please log in as an admin to scan your network.')
      } else if (response.status === 422) {
        const body = await response.json().catch(() => ({})) as { detail?: unknown }
        setScanError(
          typeof body.detail === 'string'
            ? body.detail
            : 'Enter a private network such as 192.168.1.0/24.',
        )
      } else {
        setScanError(`Scan failed: ${response.statusText || `HTTP ${response.status}`}`)
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return
      setScanError(`Network error: ${err instanceof Error ? err.message : 'Unknown error'}`)
    } finally {
      if (scanAbortRef.current === abortController) {
        setIsScanning(false)
        scanAbortRef.current = null
      }
    }
  }

  // Scan once per open. Gated on an "attempted" ref (not the result count) so a
  // zero-device scan never re-triggers. The ref is cleared on close.
  useEffect(() => {
    if (!isOpen) {
      scanAttemptedRef.current = false
      if (scanAbortRef.current) {
        scanAbortRef.current.abort()
        scanAbortRef.current = null
      }
      return
    }
    if (currentStep !== 'scan' || scanAttemptedRef.current) return
    scanAttemptedRef.current = true
    void runScan(undefined)
    void loadLicenseAndCount()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, currentStep])

  // Reset all wizard state whenever it is closed, so reopening starts fresh.
  useEffect(() => {
    if (isOpen) return
    setCurrentStep('scan')
    setScanResults([])
    setScanMeta(null)
    setActiveSubnet(undefined)
    setSubnetInput('')
    setIsScanning(false)
    setScanError(null)
    setLicenseLimit(null)
    setCurrentCount(0)
    setSelected(new Set())
    setRowApiKeys({})
    setRowStatus({})
    setBatchBusy(false)
    setBatchMessage(null)
    setAddedNames([])
    setDraft(EMPTY_ADD_DEVICE_DRAFT)
    setShowAdvanced(false)
    setAddDeviceMessage(null)
    setAddDeviceBusy(false)
    setTestConnectionResult(null)
    setTestConnectionBusy(false)
    setShowUpgradeHint(false)
    setShowSkipConfirm(false)
    addDeviceBusyRef.current = false
    batchBusyRef.current = false
  }, [isOpen])

  const handleClose = () => {
    if (scanAbortRef.current) {
      scanAbortRef.current.abort()
      scanAbortRef.current = null
    }
    if (currentStep === 'done') {
      onClose()
      return
    }
    setShowSkipConfirm(true)
  }

  const confirmSkip = () => {
    setShowSkipConfirm(false)
    onClose()
  }

  const toggleRow = (r: ScanResult) => {
    const key = rowKey(r)
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        if (remainingSlots !== null && pendingKeys(next).length >= remainingSlots) return prev
        next.add(key)
      }
      return next
    })
    setBatchMessage(null)
  }

  // Add every selected row sequentially. Partial failures stay on the scan step with retry.
  const addSelected = async (only?: ScanResult[]) => {
    if (batchBusyRef.current) return
    const rows = only ?? scanResults.filter((r) => selected.has(rowKey(r)) && !isRowAdded(r))
    if (rows.length === 0) return

    const needsKey = rows.find(
      (r) => r.protocol === 'octoprint' && !(rowApiKeys[rowKey(r)] || '').trim(),
    )
    if (needsKey) {
      setBatchMessage(`Enter the OctoPrint API key for ${displayName(needsKey)}.`)
      return
    }

    batchBusyRef.current = true
    setBatchBusy(true)
    setBatchMessage(null)

    const outcome: Record<string, RowState> = {}
    const record = (key: string, state: RowState) => {
      outcome[key] = state
      setRowStatus((prev) => ({ ...prev, [key]: state }))
    }

    let limitHit = false
    let addedOk = 0

    for (const r of rows) {
      const key = rowKey(r)
      if (limitHit) {
        record(key, { state: 'skipped', message: 'Not added: device limit reached' })
        continue
      }
      record(key, { state: 'adding' })

      const payload: Record<string, unknown> = {
        name: displayName(r),
        protocol: r.protocol,
        base_url: `http://${r.ip}:${r.port}`,
        enabled: true,
      }
      const apiKey = (rowApiKeys[key] || '').trim()
      if (apiKey) payload.api_key = apiKey

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
          const msg = result.message || response.statusText || `HTTP ${response.status}`
          if (msg.includes('Device limit reached')) {
            limitHit = true
            setShowUpgradeHint(true)
            record(key, { state: 'failed', message: 'Device limit reached' })
          } else {
            record(key, { state: 'failed', message: msg })
          }
        } else {
          addedOk += 1
          record(key, { state: 'added' })
        }
      } catch (err) {
        record(key, {
          state: 'failed',
          message: `Network error: ${err instanceof Error ? err.message : 'Unknown error'}`,
        })
      }
    }

    batchBusyRef.current = false
    setBatchBusy(false)
    if (addedOk > 0) setCurrentCount((c) => c + addedOk)

    const allAdded = rows.every((r) => outcome[rowKey(r)]?.state === 'added')
    if (allAdded) {
      // Report everything added in this session, including earlier batches.
      const addedAll = scanResults.filter(
        (r) => outcome[rowKey(r)]?.state === 'added' || rowStatus[rowKey(r)]?.state === 'added',
      )
      setAddedNames((addedAll.length ? addedAll : rows).map((r) => displayName(r)))
      setCurrentStep('done')
      return
    }
    const failed = rows.filter((r) => outcome[rowKey(r)]?.state === 'failed').length
    setBatchMessage(
      `Added ${addedOk} of ${rows.length}.` +
        (failed > 0 ? ` ${failed} failed. See the rows below, then retry.` : ''),
    )
  }

  const retryFailed = () =>
    addSelected(scanResults.filter((r) => rowStatus[rowKey(r)]?.state === 'failed' && !isRowAdded(r)))

  // Finish after a partial success: report only what was actually added.
  const finishWithAdded = () => {
    const names = scanResults
      .filter((r) => rowStatus[rowKey(r)]?.state === 'added')
      .map((r) => displayName(r))
    setAddedNames(names)
    setCurrentStep('done')
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
        ok?: boolean
        success?: boolean
        message?: string
        name?: string | null
      }
      const ok = (result.ok ?? result.success) === true
      setTestConnectionResult({
        success: ok,
        message: result.message || (ok ? 'Connection successful' : 'Connection failed'),
      })
      if (ok && result.name) {
        const suggested = result.name
        setDraft((prev) => (prev.name.trim() ? prev : { ...prev, name: suggested }))
      }
    } catch (err) {
      setTestConnectionResult({
        success: false,
        message: `Test failed: ${err instanceof Error ? err.message : 'Unknown error'}`,
      })
    } finally {
      setTestConnectionBusy(false)
    }
  }

  // Add a single device manually. The id is optional: the server generates one.
  const handleAddDevice = async () => {
    const d = draft
    if (!d.name.trim() || !d.base_url.trim()) {
      setAddDeviceMessage('Name and base URL are required.')
      return
    }

    const payload: Record<string, unknown> = {
      name: d.name.trim(),
      protocol: d.protocol,
      base_url: d.base_url.trim(),
      enabled: d.enabled,
    }
    if (d.id.trim()) payload.id = d.id.trim()
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
          setAddDeviceMessage(null)
        } else {
          setAddDeviceMessage(`Add failed: ${msg}`)
        }
        return
      }

      setAddedNames([d.name.trim()])
      setCurrentStep('done')
    } catch (err) {
      // A network failure must surface an error, not leave the UI on "Adding device…".
      setAddDeviceMessage(
        `Add failed: ${err instanceof Error ? err.message : 'Network error'}`
      )
    } finally {
      addDeviceBusyRef.current = false
      setAddDeviceBusy(false)
    }
  }

  const handleAddManually = () => {
    setDraft(EMPTY_ADD_DEVICE_DRAFT)
    setShowAdvanced(false)
    setAddDeviceMessage(null)
    setTestConnectionResult(null)
    setCurrentStep('review')
  }

  // Reset wizard to scan step and rescan
  const handleAddAnother = () => {
    scanAttemptedRef.current = false
    setCurrentStep('scan')
    setScanResults([])
    setScanMeta(null)
    setActiveSubnet(undefined)
    setSelected(new Set())
    setRowStatus({})
    setRowApiKeys({})
    setBatchMessage(null)
    setAddedNames([])
    setDraft(EMPTY_ADD_DEVICE_DRAFT)
    setAddDeviceMessage(null)
    setTestConnectionResult(null)
    setShowUpgradeHint(false)
  }

  const pendingCount = scanResults.filter((r) => selected.has(rowKey(r)) && !isRowAdded(r)).length
  const selectableCount = scanResults.filter((r) => !isRowAdded(r)).length
  const limitNote = remainingSlots !== null && selectableCount > remainingSlots
  const failedCount = scanResults.filter((r) => rowStatus[rowKey(r)]?.state === 'failed').length
  const addedCount = scanResults.filter((r) => rowStatus[rowKey(r)]?.state === 'added').length

  const renderRow = (r: ScanResult) => {
    const key = rowKey(r)
    const st = rowStatus[key]
    const alreadyAdded = r.already_added === true
    const added = isRowAdded(r)
    const checked = selected.has(key)
    const capReached = remainingSlots !== null && pendingKeys(selected).length >= remainingSlots
    const disabled = added || batchBusy || isScanning || (!checked && capReached)
    const name = displayName(r)
    const title = rowTitle(r)
    const badge = alreadyAdded
      ? 'Already added'
      : st?.state === 'added'
        ? 'Added'
        : st?.state === 'adding'
          ? 'Adding…'
          : st?.state === 'failed'
            ? 'Failed'
            : st?.state === 'skipped'
              ? 'Not added'
              : null

    return (
      <div
        key={key}
        style={{
          padding: '12px 16px',
          border: '1px solid var(--border-default)',
          borderRadius: '8px',
          background: 'var(--surface-l2)',
          marginBottom: '8px',
        }}
      >
        <label
          style={{
            display: 'flex',
            gap: '12px',
            alignItems: 'flex-start',
            cursor: disabled ? 'default' : 'pointer',
            opacity: alreadyAdded ? 0.7 : 1,
          }}
        >
          <input
            type="checkbox"
            checked={checked || added}
            disabled={disabled}
            onChange={() => toggleRow(r)}
            aria-label={`Select ${title}`}
            style={{ marginTop: '2px', width: 20, height: 20, flexShrink: 0, accentColor: 'var(--accent-solid)' }}
          />
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: 'block', fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              {title}
            </span>
            <span style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              {protocolLabel(r.protocol)}
              {` · ${r.ip}${scanResults.filter((o) => o.ip === r.ip).length > 1 || r.protocol !== 'moonraker' ? `:${r.port}` : ''}`}
            </span>
            {r.protocol === 'octoprint' && !checked && !added && (
              <span style={{ display: 'block', fontSize: '0.9rem', fontWeight: 500, color: 'var(--text-primary)', marginTop: 2 }}>
                Needs an access key. Tick to enter it.
              </span>
            )}
          </span>
          {badge && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
              {badge}
            </span>
          )}
        </label>

        {checked && !added && r.protocol === 'octoprint' && (
          <div style={{ marginTop: '12px' }}>
            <label htmlFor={`octo-key-${key}`} style={{ ...labelStyle, fontSize: '0.8rem', marginBottom: '4px' }}>
              API key
            </label>
            <input
              id={`octo-key-${key}`}
              type="password"
              placeholder="Your OctoPrint API key"
              value={rowApiKeys[key] || ''}
              onChange={(e) => {
                const value = e.target.value
                setRowApiKeys((prev) => ({ ...prev, [key]: value }))
              }}
              style={inputStyle}
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              OctoPrint → Settings → Application Keys
            </div>
          </div>
        )}

        {st?.state === 'failed' && st.message && (
          <div role="alert" style={{ ...errorBoxStyle, marginTop: '8px', marginBottom: 0 }}>
            {st.message}
          </div>
        )}
      </div>
    )
  }

  const renderScanStep = () => (
    <div>
      <p style={{ marginBottom: '8px', color: 'var(--text-primary)' }}>
        {isScanning || !scanMeta
          ? 'Looking for printers on your network. You can also add a device by its address.'
          : scanResults.length > 0
            ? `Found ${scanResults.length} device${scanResults.length === 1 ? '' : 's'} on your network. The ticked ones will be added.`
            : 'No printers found yet.'}
      </p>

      {scanMeta?.subnet && !isScanning && (
        <p style={{ margin: '0 0 12px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Searched {scanMeta.subnet.endsWith('.0/24') ? `addresses ${scanMeta.subnet.replace(/\.0\/24$/, '.x')}` : scanMeta.subnet}
          {!(scanMeta.subnet_source === 'fallback' || scanResults.length === 0 || showSubnetInput) && (
            <>
              {' · '}
              <button
                type="button"
                onClick={() => setShowSubnetInput(true)}
                style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent-text)', textDecoration: 'underline', cursor: 'pointer', fontSize: 'inherit' }}
              >
                Printers on a different network?
              </button>
            </>
          )}
        </p>
      )}

      {!isScanning && scanMeta && (scanMeta.subnet_source === 'fallback' || scanResults.length === 0 || showSubnetInput) && (
        <div style={{ marginBottom: '16px' }}>
          <label htmlFor="scan-subnet" style={{ ...labelStyle, marginBottom: '6px' }}>
            Search another network
          </label>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              id="scan-subnet"
              type="text"
              placeholder="for example 192.168.2.x"
              value={subnetInput}
              onChange={(e) => setSubnetInput(e.target.value)}
              aria-describedby="scan-subnet-hint"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              type="button"
              className="btn btn-ghost"
              disabled={isScanning}
              onClick={() => void runScan(subnetInput.trim() ? toSubnet(subnetInput) : undefined)}
            >
              Search this network
            </button>
          </div>
          <div id="scan-subnet-hint" style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '6px' }}>
            Type the first three numbers of a printer's address, for example 192.168.2.x.
          </div>
        </div>
      )}

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
        <div role="alert" style={errorBoxStyle}>{scanError}</div>
      ) : null}

      {!isScanning && scanMeta?.scan_capped && (
        <div role="status" style={noteBoxStyle}>
          Scan incomplete — add missing machines manually.
        </div>
      )}

      {!isScanning && !scanError && scanResults.length === 0 && (
        <div style={{ textAlign: 'center', padding: '16px 0 24px' }}>
          <p style={{ color: 'var(--text-secondary)', margin: '0 0 16px' }}>
            We didn't find any printers on your network yet. Check that the printer is powered on and on the same network, or add it by address.
          </p>
          <button type="button" className="btn btn-primary" onClick={handleAddManually}>
            Add device manually
          </button>
        </div>
      )}

      {!isScanning && scanResults.length > 0 && (
        <div style={{ marginBottom: '16px' }}>

          {limitNote && (
            <div role="status" style={noteBoxStyle}>
              {remainingSlots && remainingSlots > 0 ? (
                <>
                  Your plan monitors {licenseLimit} devices. Choose which {remainingSlots} to add, or{' '}
                  <button type="button" className="btn btn-ghost" onClick={() => setShowUpgradeHint(true)}>
                    upgrade
                  </button>.
                </>
              ) : (
                <>
                  Your plan monitors {licenseLimit} devices and all of them are in use.{' '}
                  <button type="button" className="btn btn-ghost" onClick={() => setShowUpgradeHint(true)}>
                    Upgrade
                  </button>{' '}
                  to add more.
                </>
              )}
            </div>
          )}

          {scanResults.map((r) => renderRow(r))}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', alignItems: 'stretch', marginTop: '12px' }}>
            <button
              type="button"
              className="btn btn-primary"
              style={{ width: '100%' }}
              disabled={pendingCount === 0 || batchBusy || isScanning}
              onClick={() => void addSelected()}
            >
              {batchBusy ? 'Adding…' : `Add selected (${pendingCount})`}
            </button>
            <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', justifyContent: 'flex-start' }}>
            {failedCount > 0 && !batchBusy && (
              <button type="button" className="btn btn-ghost" onClick={() => void retryFailed()}>
                Retry failed ({failedCount})
              </button>
            )}
            {addedCount > 0 && !batchBusy && (
              <button type="button" className="btn btn-ghost" onClick={finishWithAdded}>
                Finish ({addedCount} added)
              </button>
            )}
            </div>
          </div>
          {batchMessage && (
            <div role="status" style={{ ...noteBoxStyle, marginTop: '12px', marginBottom: 0 }}>
              {batchMessage}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: '20px', justifyContent: 'flex-start', flexWrap: 'wrap', marginTop: '16px' }}>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={isScanning || batchBusy}
          onClick={() => void runScan(activeSubnet)}
        >
          Scan again
        </button>
        {scanResults.length > 0 && (
          <button type="button" className="btn btn-ghost" onClick={handleAddManually}>
            Add device manually
          </button>
        )}
      </div>
    </div>
  )

  const renderReviewStep = () => (
    <div>
      <div style={{ marginBottom: '24px' }}>
        <label htmlFor="protocol-select" style={labelStyle}>
          Protocol
        </label>
        <select
          id="protocol-select"
          value={draft.protocol}
          onChange={(e) => {
            setDraft({ ...draft, protocol: e.target.value })
            setTestConnectionResult(null)
          }}
          style={inputStyle}
        >
          {DEVICE_PROTOCOLS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: '24px' }}>
        <label htmlFor="base-url" style={labelStyle}>
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
          style={inputStyle}
        />
      </div>

      <div style={{ marginBottom: '24px' }}>
        <label htmlFor="device-name" style={labelStyle}>
          Device name
        </label>
        <input
          id="device-name"
          type="text"
          placeholder="My Printer"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          style={inputStyle}
        />
      </div>

      {PROTOCOLS_WITH_API_KEY.has(draft.protocol) && (
        <div style={{ marginBottom: '24px' }}>
          <label htmlFor="api-key" style={labelStyle}>
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
            style={inputStyle}
          />
          {draft.protocol === 'octoprint' && (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              OctoPrint → Settings → Application Keys
            </div>
          )}
        </div>
      )}

      {draft.protocol === 'mqtt' && (
        <>
          <div style={{ marginBottom: '24px' }}>
            <label htmlFor="mqtt-topic" style={labelStyle}>
              MQTT topic (optional)
            </label>
            <input
              id="mqtt-topic"
              type="text"
              placeholder="printer/state"
              value={draft.mqttTopic}
              onChange={(e) => setDraft({ ...draft, mqttTopic: e.target.value })}
              style={inputStyle}
            />
          </div>

          <div style={{ marginBottom: '24px' }}>
            <label htmlFor="mqtt-mapping" style={labelStyle}>
              Field mapping (optional JSON)
            </label>
            <textarea
              id="mqtt-mapping"
              placeholder='{"state":"st","progress":"pct"}'
              value={draft.mqttFieldMapping}
              onChange={(e) => setDraft({ ...draft, mqttFieldMapping: e.target.value })}
              rows={3}
              style={{ ...inputStyle, fontFamily: 'monospace' }}
            />
          </div>
        </>
      )}

      <div style={{ marginBottom: '24px' }}>
        <button
          type="button"
          className="btn btn-ghost"
          aria-expanded={showAdvanced}
          aria-controls="setup-advanced"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? 'Hide advanced' : 'Advanced'}
        </button>
        {showAdvanced && (
          <div id="setup-advanced" style={{ marginTop: '16px' }}>
            <div style={{ marginBottom: '16px' }}>
              <label htmlFor="device-id" style={labelStyle}>
                Device ID (optional)
              </label>
              <input
                id="device-id"
                type="text"
                placeholder="printer_1"
                value={draft.id}
                onChange={(e) => setDraft({ ...draft, id: e.target.value })}
                style={inputStyle}
              />
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                Leave blank and MEMAR generates one.
              </div>
            </div>
            <div style={{ marginBottom: '16px' }}>
              <label htmlFor="serial" style={labelStyle}>
                Serial (optional)
              </label>
              <input
                id="serial"
                type="text"
                placeholder="Device serial number"
                value={draft.serial}
                onChange={(e) => setDraft({ ...draft, serial: e.target.value })}
                style={inputStyle}
              />
            </div>
          </div>
        )}
      </div>

      {testConnectionResult && (
        <div
          role="status"
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
        <div role="alert" style={errorBoxStyle}>
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
      <div aria-hidden="true" style={{ fontSize: '3rem', color: 'var(--color-success)', fontWeight: 700 }}>✓</div>
      <div>
        <h3 style={{ fontSize: '1.25rem', fontWeight: 600, margin: '0 0 8px', color: 'var(--text-primary)' }}>
          {addedNames.length === 1 ? 'Device added' : `${addedNames.length} devices added`}
        </h3>
        <p style={{ margin: 0, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
          {addedNames.join(', ')} {addedNames.length === 1 ? 'is' : 'are'} ready to use
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
            // Stay on the current step after dismissing the upgrade hint
          }}
        />
      )}
    </>
  )
}

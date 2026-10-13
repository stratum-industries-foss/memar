import React, { useState } from 'react'
import { apiFetch } from './api'

interface AlphaAcknowledgeModalProps {
  deviceId: string
  deviceName: string
  protocol: string
  onAcknowledged: () => void
  onCancel: () => void
}

// Shown the first time a control action (feed-rate, gcode, home, jog) hits
// the backend's alpha_ack_required 403 — see require_alpha_ack in deps.py.
// Never shown for 3D-printer routes, which never carry the alpha flag.
export const AlphaAcknowledgeModal = React.memo(function AlphaAcknowledgeModal({
  deviceId, deviceName, protocol, onAcknowledged, onCancel,
}: AlphaAcknowledgeModalProps) {
  const [checked, setChecked] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Block Escape until the checkbox is checked
      if (e.key === 'Escape' && checked) onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel, checked])

  async function handleAcknowledge() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await apiFetch(`/api/devices/${deviceId}/cnc/alpha-ack`, { method: 'POST' })
      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText)
        setError(errText || `Failed to acknowledge (HTTP ${res.status})`)
        return
      }
      onAcknowledged()
    } catch (e) {
      setError(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="confirm-overlay" role="presentation">
      <div
        className="confirm-dialog alpha-ack-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label="Alpha adapter — use at your own risk"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="confirm-message alpha-ack-title">⚠ Alpha adapter — use at your own risk</p>
        <p className="confirm-message">
          <strong>{deviceName}</strong> runs the <strong>{protocol}</strong> adapter. This adapter can send commands
          to your machine (jog, feed-rate, spindle, e-stop) as well as monitor it. It's real, working code, but not
          yet verified against every real {protocol} setup the way MEMAR's 3D-printing adapters are. Bugs can
          happen. You are responsible for your machine's physical safety — verify behavior on your hardware before
          trusting it unattended.
        </p>
        <label className="alpha-ack-checkbox-row">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          I understand and accept responsibility.
        </label>
        {error && <p className="confirm-message alpha-ack-error">⚠ {error}</p>}
        <div className="confirm-actions">
          <button className="confirm-cancel" onClick={onCancel} autoFocus>Cancel</button>
          <button className="confirm-ok" onClick={() => void handleAcknowledge()} disabled={!checked || submitting}>
            {submitting ? 'Acknowledging…' : 'Acknowledge & Continue'}
          </button>
        </div>
      </div>
    </div>
  )
})

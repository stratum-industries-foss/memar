import React, { useState, useEffect } from 'react'
import { Button, Badge } from './primitives'

interface RecoveryCodesProps {
  token: string
}

type RecoveryState = 'not-generated' | 'generating' | 'generated' | 'acknowledged'

export const RecoveryCodes: React.FC<RecoveryCodesProps> = ({ token }) => {
  const [state, setState] = useState<RecoveryState>('not-generated')
  const [codes, setCodes] = useState<string[]>([])
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  const generateCodes = async () => {
    setError('')
    try {
      setState('generating')
      const res = await fetch('/api/auth/recovery-codes/generate', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Failed to generate recovery codes')
      }

      const data = await res.json()
      setCodes(data.codes || [])
      setState('generated')
    } catch (err) {
      setState('not-generated')
      setError(err instanceof Error ? err.message : 'Failed to generate codes')
    }
  }

  const downloadCodes = () => {
    const text = `Recovery Codes\n\nGenerated: ${new Date().toISOString()}\n\n${codes.join('\n')}\n\nSave these codes in a secure location. Each code can be used once to regain access to your account.`
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `memar-recovery-codes-${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const copyCodes = () => {
    const text = codes.join('\n')
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handleAcknowledge = () => {
    setState('acknowledged')
  }

  const handleRegenerate = () => {
    setCodes([])
    setState('not-generated')
  }

  if (state === 'not-generated') {
    return (
      <div style={{ padding: '20px 0', maxWidth: '400px' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: '14px', fontWeight: 600 }}>Recovery Codes</h3>
        <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--text-secondary)' }}>
          Generate one-time recovery codes to regain access if you lose your passkey or password.
        </p>
        {error && (
          <div
            role="alert"
            style={{ fontSize: '12px', color: 'var(--color-danger)', marginBottom: '12px', padding: '8px' }}
          >
            {error}
          </div>
        )}
        <Button variant="primary" onClick={generateCodes}>
          Generate recovery codes
        </Button>
      </div>
    )
  }

  if (state === 'generating') {
    return (
      <div style={{ padding: '20px 0', textAlign: 'center' }}>
        <div
          style={{
            display: 'inline-block',
            width: '16px',
            height: '16px',
            border: '2px solid var(--border-default)',
            borderTop: '2px solid var(--color-primary)',
            borderRadius: '50%',
            animation: 'spin 0.8s linear infinite',
          }}
        />
        <p style={{ margin: '8px 0 0', fontSize: '13px' }}>Generating codes...</p>
        <style>{`
          @keyframes spin {
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    )
  }

  if (state === 'generated') {
    return (
      <div style={{ padding: '20px 0', maxWidth: '500px' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: '14px', fontWeight: 600 }}>Your Recovery Codes</h3>
        <div
          style={{
            background: 'rgba(220, 38, 38, 0.05)',
            border: '1px solid rgba(220, 38, 38, 0.2)',
            borderRadius: '6px',
            padding: '12px',
            marginBottom: '16px',
          }}
        >
          <p style={{ margin: '0', fontSize: '12px', color: 'var(--text-secondary)' }}>
            ⚠️ Save these codes in a secure location. Each code can only be used once.
          </p>
        </div>

        {/* Codes Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: '8px',
            marginBottom: '16px',
            padding: '12px',
            background: 'var(--surface-overlay)',
            borderRadius: '6px',
            fontFamily: 'monospace',
            fontSize: '12px',
          }}
        >
          {codes.map((code, idx) => (
            <div
              key={idx}
              style={{
                padding: '8px',
                background: 'var(--surface-l0)',
                border: '1px solid var(--border-default)',
                borderRadius: '4px',
                textAlign: 'center',
                userSelect: 'all',
              }}
              title={code}
            >
              {code}
            </div>
          ))}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={copyCodes}
            aria-label={copied ? 'Copied to clipboard' : 'Copy all codes'}
          >
            {copied ? '✓ Copied' : 'Copy all'}
          </Button>
          <Button variant="secondary" size="sm" onClick={downloadCodes} aria-label="Download codes as file">
            Download
          </Button>
        </div>

        {/* Confirmation */}
        <div
          style={{
            background: 'rgba(34, 197, 94, 0.05)',
            border: '1px solid rgba(34, 197, 94, 0.2)',
            borderRadius: '6px',
            padding: '12px',
            marginBottom: '16px',
          }}
        >
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', margin: 0 }}>
            <input
              type="checkbox"
              onChange={(e) => {
                if (e.target.checked) {
                  handleAcknowledge()
                }
              }}
              aria-label="I have saved my recovery codes"
            />
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              I have saved these codes in a safe place
            </span>
          </label>
        </div>
      </div>
    )
  }

  // Acknowledged state
  return (
    <div style={{ padding: '20px 0', maxWidth: '400px' }}>
      <div
        style={{
          background: 'rgba(34, 197, 94, 0.1)',
          border: '1px solid var(--color-success)',
          borderRadius: '6px',
          padding: '12px',
          textAlign: 'center',
          marginBottom: '16px',
        }}
      >
        <p style={{ margin: '0 0 4px', fontSize: '13px', fontWeight: 500, color: 'var(--color-success)' }}>
          ✓ Recovery codes active
        </p>
        <p style={{ margin: '0', fontSize: '12px', color: 'var(--text-secondary)' }}>
          You can now use recovery codes to sign in if needed.
        </p>
      </div>

      <button
        onClick={handleRegenerate}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--color-primary)',
          cursor: 'pointer',
          fontSize: '12px',
          textDecoration: 'underline',
          padding: 0,
        }}
        aria-label="Generate new recovery codes"
      >
        Generate new codes
      </button>
    </div>
  )
}

export default RecoveryCodes

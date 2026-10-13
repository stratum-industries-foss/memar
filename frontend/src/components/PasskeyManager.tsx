import React, { useState, useEffect } from 'react'
import { WebAuthnRegister } from './WebAuthnRegister'
import { Button } from './primitives'

interface Credential {
  id: number
  name: string
  created_at: string
  last_used: string | null
}

interface PasskeyManagerProps {
  token: string
  username: string
}

export const PasskeyManager: React.FC<PasskeyManagerProps> = ({ token, username }) => {
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [loading, setLoading] = useState(true)
  const [showRegister, setShowRegister] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    loadCredentials()
  }, [token])

  const loadCredentials = async () => {
    try {
      setLoading(true)
      const res = await fetch('/api/auth/webauthn/credentials', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })

      if (!res.ok) throw new Error('Failed to load credentials')
      const data = await res.json()
      setCredentials(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load credentials')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Delete passkey "${name}"? You'll need another passkey to login.`)) {
      return
    }

    try {
      const res = await fetch(`/api/auth/webauthn/credentials/${id}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })

      if (!res.ok) throw new Error('Failed to delete credential')
      setSuccess(`Deleted "${name}"`)
      await loadCredentials()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete credential')
    }
  }

  const handleRegisterSuccess = (credentialName: string) => {
    setShowRegister(false)
    setSuccess(`✅ Passkey "${credentialName}" registered successfully!`)
    loadCredentials()
  }

  const handleRegisterError = (message: string) => {
    setError(`Registration failed: ${message}`)
  }

  return (
    <div style={{ padding: 'var(--spacing-lg) 0' }}>
      <div style={{ marginBottom: 'var(--spacing-lg)' }}>
        <h3 style={{ margin: `0 0 var(--spacing-xs) 0`, fontSize: 'var(--font-size-h4)' }}>
          🔑 Your Passkeys
        </h3>
        <p style={{ margin: 0, fontSize: 'var(--font-size-body-sm)', color: 'var(--text-secondary)' }}>
          Register passkeys for Face ID, Touch ID, or hardware security keys
        </p>
      </div>

      {error && (
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          style={{
            padding: 'var(--spacing-sm)',
            background: 'var(--color-danger)',
            color: '#fff',
            borderRadius: 'var(--radius-md)',
            fontSize: 'var(--font-size-body-sm)',
            marginBottom: 'var(--spacing-md)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 'var(--spacing-sm)',
          }}
        >
          <span>{error}</span>
          <button
            onClick={() => setError('')}
            aria-label="Dismiss error message"
            style={{
              background: 'none',
              border: 'none',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '16px',
              padding: '0 var(--spacing-xs)',
              flexShrink: 0,
              outline: 'none',
            }}
            onFocus={(e) => {
              e.currentTarget.style.boxShadow = '0 0 0 3px rgba(255,255,255,0.4)'
            }}
            onBlur={(e) => {
              e.currentTarget.style.boxShadow = 'none'
            }}
          >
            ✕
          </button>
        </div>
      )}

      {success && (
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          style={{
            padding: 'var(--spacing-sm)',
            background: 'var(--color-success)',
            color: '#fff',
            borderRadius: 'var(--radius-md)',
            fontSize: 'var(--font-size-body-sm)',
            marginBottom: 'var(--spacing-md)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 'var(--spacing-sm)',
          }}
        >
          <span>{success}</span>
          <button
            onClick={() => setSuccess('')}
            aria-label="Dismiss success message"
            style={{
              background: 'none',
              border: 'none',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '16px',
              padding: '0 var(--spacing-xs)',
              flexShrink: 0,
              outline: 'none',
            }}
            onFocus={(e) => {
              e.currentTarget.style.boxShadow = '0 0 0 3px rgba(255,255,255,0.4)'
            }}
            onBlur={(e) => {
              e.currentTarget.style.boxShadow = 'none'
            }}
          >
            ✕
          </button>
        </div>
      )}

      {showRegister ? (
        <div
          style={{
            background: 'var(--surface-l2)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-lg)',
            marginBottom: 'var(--spacing-md)',
          }}
        >
          <WebAuthnRegister
            token={token}
            username={username}
            onSuccess={handleRegisterSuccess}
            onError={handleRegisterError}
            onClose={() => setShowRegister(false)}
          />
        </div>
      ) : (
        <div style={{ marginBottom: 'var(--spacing-lg)' }}>
          <Button
            onClick={() => setShowRegister(true)}
            variant="primary"
            size="md"
            style={{ width: '100%' }}
          >
            + Add Passkey
          </Button>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 'var(--font-size-body-sm)' }}>
          Loading passkeys...
        </div>
      ) : credentials.length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 'var(--font-size-body-sm)', padding: 'var(--spacing-md) 0' }}>
          No passkeys registered yet. Click "Add Passkey" to create one.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-sm)' }}>
          {credentials.map((cred) => (
            <div
              key={cred.id}
              style={{
                padding: 'var(--spacing-md)',
                background: 'var(--surface-l2)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-lg)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div>
                <div style={{ fontWeight: 500, fontSize: 'var(--font-size-body-md)', marginBottom: 'var(--spacing-xs)' }}>
                  🔐 {cred.name}
                </div>
                <div style={{ fontSize: 'var(--font-size-body-sm)', color: 'var(--text-secondary)' }}>
                  Created: {new Date(cred.created_at).toLocaleDateString()}
                  {cred.last_used && ` • Last used: ${new Date(cred.last_used).toLocaleDateString()}`}
                </div>
              </div>
              <Button
                onClick={() => handleDelete(cred.id, cred.name)}
                variant="primary"
                size="sm"
              >
                Delete
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default PasskeyManager

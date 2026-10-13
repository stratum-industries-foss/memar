import React, { useState } from 'react'
import { startRegistration, isWebAuthnSupported, isPlatformAuthenticatorAvailable } from '../webauthn-utils'
import { Input, Button } from './primitives'

interface WebAuthnRegisterProps {
  token: string
  username: string
  onSuccess: (credentialName: string) => void
  onError: (message: string) => void
  onClose: () => void
}

export const WebAuthnRegister: React.FC<WebAuthnRegisterProps> = ({
  token,
  username,
  onSuccess,
  onError,
  onClose,
}) => {
  const [loading, setLoading] = useState(false)
  const [credentialName, setCredentialName] = useState('')
  const [step, setStep] = useState<'name' | 'registering'>('name')
  const [supported] = useState(isWebAuthnSupported())

  const handleRegister = async () => {
    if (!credentialName.trim()) {
      onError('Please enter a name for your passkey')
      return
    }

    if (!supported) {
      onError('WebAuthn is not supported in your browser')
      return
    }

    setLoading(true)
    setStep('registering')

    try {
      await startRegistration(
        token,
        credentialName,
        'localhost',
        'MEMAR',
        'user:1', // In production, this would come from the user object
        username
      )
      onSuccess(credentialName)
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Registration failed')
      setStep('name')
    } finally {
      setLoading(false)
    }
  }

  if (!supported) {
    return (
      <div style={{ padding: 'var(--spacing-2xl)', textAlign: 'center', color: 'var(--color-danger)' }}>
        <p>❌ WebAuthn is not supported in your browser</p>
        <p style={{ fontSize: 'var(--font-size-body-sm)', color: 'var(--text-secondary)', marginBottom: 'var(--spacing-md)' }}>
          Please use a modern browser (Chrome 90+, Safari 15.1+, Edge 90+)
        </p>
        <Button onClick={onClose} variant="secondary" size="md">
          Close
        </Button>
      </div>
    )
  }

  return (
    <div style={{ padding: 'var(--spacing-2xl)' }}>
      <h3 style={{ margin: `0 0 var(--spacing-lg) 0`, fontSize: 'var(--font-size-h4)' }}>Register a Passkey</h3>

      {step === 'name' && (
        <>
          <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-size-body-sm)', marginBottom: 'var(--spacing-lg)' }}>
            Give your passkey a friendly name so you can remember it later.
            Examples: "iPhone Face ID", "MacBook Touch ID", "YubiKey"
          </p>

          <div style={{ marginBottom: 'var(--spacing-lg)' }}>
            <Input
              type="text"
              value={credentialName}
              onChange={(e) => setCredentialName(e.target.value)}
              placeholder="e.g., iPhone Face ID"
              disabled={loading}
              autoFocus
              size="md"
            />
          </div>

          <div style={{ display: 'flex', gap: 'var(--spacing-md)' }}>
            <Button
              onClick={handleRegister}
              disabled={loading || !credentialName.trim()}
              variant="primary"
              size="md"
              style={{ flex: 1 }}
            >
              {loading ? '🔐 Setting up...' : '🔑 Create Passkey'}
            </Button>
            <Button
              onClick={onClose}
              disabled={loading}
              variant="secondary"
              size="md"
              style={{ flex: 0.5 }}
            >
              Cancel
            </Button>
          </div>
        </>
      )}

      {step === 'registering' && (
        <div style={{ textAlign: 'center', padding: 'var(--spacing-2xl) 0' }}>
          <div style={{ fontSize: '32px', marginBottom: 'var(--spacing-lg)' }}>🔐</div>
          <p style={{ color: 'var(--text-secondary)', marginBottom: 'var(--spacing-md)' }}>
            {credentialName && `Creating passkey: ${credentialName}`}
          </p>
          <p style={{ fontSize: 'var(--font-size-body-sm)', color: 'var(--text-secondary)' }}>
            Follow the prompts on your device to authenticate
          </p>
        </div>
      )}
    </div>
  )
}

export default WebAuthnRegister

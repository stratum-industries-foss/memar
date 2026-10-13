import React, { useState } from 'react'
import { startAuthentication, isWebAuthnSupported } from '../webauthn-utils'

interface WebAuthnAuthProps {
  onSuccess: (accessToken: string, refreshToken: string) => void
  onError: (message: string) => void
}

export const WebAuthnAuth: React.FC<WebAuthnAuthProps> = ({ onSuccess, onError }) => {
  const [loading, setLoading] = useState(false)
  const [supported, setSupported] = useState(isWebAuthnSupported())

  const handleSignIn = async () => {
    if (!supported) {
      onError('WebAuthn is not supported in your browser')
      return
    }

    setLoading(true)
    try {
      const result = await startAuthentication('localhost')
      onSuccess(result.access_token, result.refresh_token)
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  if (!supported) {
    return null
  }

  return (
    <button
      onClick={handleSignIn}
      disabled={loading}
      style={{
        width: '100%',
        padding: '10px 16px',
        marginBottom: 12,
        background: '#2563eb',
        color: '#fff',
        border: 'none',
        borderRadius: 6,
        fontSize: 14,
        fontWeight: 600,
        cursor: loading ? 'not-allowed' : 'pointer',
        opacity: loading ? 0.7 : 1,
      }}
      title="Sign in with your Face ID, Touch ID, or security key"
    >
      {loading ? '🔐 Authenticating...' : '🔑 Sign in with passkey'}
    </button>
  )
}

export default WebAuthnAuth

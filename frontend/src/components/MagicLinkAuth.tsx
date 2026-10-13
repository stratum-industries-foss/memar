import React, { useState } from 'react'
import { Button, Input } from './primitives'

interface MagicLinkAuthProps {
  token: string
}

type RequestState = 'idle' | 'pending' | 'success'

export const MagicLinkAuth: React.FC<MagicLinkAuthProps> = ({ token }) => {
  const [email, setEmail] = useState('')
  const [state, setState] = useState<RequestState>('idle')
  const [error, setError] = useState('')
  const [countdown, setCountdown] = useState(0)

  const handleSendLink = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!email.trim()) {
      setError('Please enter an email address')
      return
    }

    try {
      setState('pending')
      const res = await fetch('/api/auth/magic-link', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ email: email.trim() }),
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Failed to send magic link')
      }

      setState('success')
      setCountdown(60)
      const timer = setInterval(() => {
        setCountdown((c) => {
          if (c <= 1) {
            clearInterval(timer)
            setState('idle')
            return 0
          }
          return c - 1
        })
      }, 1000)

      // Reset form after 2 seconds
      setTimeout(() => {
        setEmail('')
      }, 2000)
    } catch (err) {
      setState('idle')
      setError(err instanceof Error ? err.message : 'Failed to send magic link')
    }
  }

  const handleResend = async () => {
    if (countdown > 0) return
    setState('idle')
    setEmail('')
  }

  return (
    <div style={{ padding: '20px 0', maxWidth: '400px' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: '14px', fontWeight: 600 }}>Passwordless Sign-in</h3>
      <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--text-secondary)' }}>
        Request a sign-in link via email as an alternative to passkeys or passwords.
      </p>

      {state === 'idle' && (
        <form onSubmit={handleSendLink} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Input
            type="email"
            placeholder="Enter email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-label="Email for magic link"
            required
          />
          {error && (
            <div
              role="alert"
              aria-live="polite"
              style={{ fontSize: '12px', color: 'var(--color-danger)', padding: '8px 0' }}
            >
              {error}
            </div>
          )}
          <Button variant="primary" type="submit">
            Send magic link
          </Button>
        </form>
      )}

      {state === 'pending' && (
        <div style={{ textAlign: 'center', padding: '12px 0' }}>
          <p style={{ margin: '0 0 8px', fontSize: '13px' }}>Sending link to {email}...</p>
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
        </div>
      )}

      {state === 'success' && (
        <div
          role="status"
          aria-live="polite"
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
            ✓ Link sent to {email}
          </p>
          <p style={{ margin: '0', fontSize: '12px', color: 'var(--text-secondary)' }}>
            Check your inbox (valid for 15 minutes)
          </p>
          {countdown > 0 && (
            <p style={{ margin: '8px 0 0', fontSize: '11px', color: 'var(--text-secondary)' }}>
              Resend in {countdown}s
            </p>
          )}
          {countdown === 0 && (
            <button
              onClick={handleResend}
              style={{
                marginTop: '8px',
                background: 'none',
                border: 'none',
                color: 'var(--color-primary)',
                cursor: 'pointer',
                fontSize: '12px',
                textDecoration: 'underline',
              }}
              aria-label="Request another magic link"
            >
              Send another link
            </button>
          )}
        </div>
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

export default MagicLinkAuth

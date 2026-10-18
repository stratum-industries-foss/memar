import React, { useState } from 'react'
import { setTokens } from './api'

// Contract: docs/internal/FIRSTRUN_CONTRACT.md. Setup endpoints are unauthenticated,
// so they use plain fetch (no token attach, no 401 refresh).
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export interface FirstRunStatus {
  claimed: boolean
  mode?: string
  code_required?: boolean
  window_seconds_left?: number
  where_is_the_code?: string[]
}

// Unauthenticated. Returns null if the status cannot be read, so the caller
// falls back to the normal login screen instead of blocking the app.
export async function fetchSetupStatus(): Promise<FirstRunStatus | null> {
  try {
    const res = await fetch(`${API_BASE}/api/setup/status`)
    if (!res.ok) return null
    const data = await res.json() as FirstRunStatus
    return typeof data?.claimed === 'boolean' ? data : null
  } catch {
    return null
  }
}

export interface FirstRunSetupProps {
  status: FirstRunStatus
  onClaimed: (username: string) => void
  onAlreadyClaimed: () => void
}

// Paid plans: a licence key can be entered during setup. It is activated with the
// new admin's token right after the account exists; a rejected key never blocks
// account creation (it can be added later in Settings -> License).
const tierLabel = (tier: string): string =>
  tier
    .replace(/^airgap_?/, 'Air-Gap ')
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')

type LicenseOutcome = { ok: boolean; message: string }

export async function activateLicense(key: string, accessToken: string): Promise<LicenseOutcome> {
  const rejected = 'License key not accepted.'
  // A network failure or server error is not a bad key: say so, so the user retries
  // instead of believing a valid key was refused.
  const unreachable =
    'Could not reach MEMAR to check the license key. Check the connection and try again. Your setup code is unchanged.'
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/license/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ license_key: key }),
    })
  } catch {
    return { ok: false, message: unreachable }
  }
  if (res.status >= 500) return { ok: false, message: unreachable }
  if (!res.ok) return { ok: false, message: rejected }
  try {
    const st = await fetch(`${API_BASE}/api/license/status`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    if (st.ok) {
      const info = (await st.json()) as { tier?: string; device_limit?: number }
      if (info.tier) {
        const limit =
          typeof info.device_limit === 'number' ? ` — up to ${info.device_limit.toLocaleString()} devices` : ''
        return { ok: true, message: `${tierLabel(info.tier)} plan active${limit}` }
      }
    }
    return { ok: true, message: 'License activated.' }
  } catch {
    // The key was accepted; only the status read failed. Do not call that a rejection.
    return { ok: true, message: 'License activated.' }
  }
}

const MIN_PASSWORD = 10
const MIN_USERNAME = 3

// Setup code is 8 chars from an unambiguous alphabet, shown XXXX-XXXX. Input is
// case- and dash-insensitive, so normalise to the canonical display form.
export const normalizeSetupCode = (raw: string): string => {
  const bare = raw.toUpperCase().replace(/[^A-Z0-9]/g, '')
  return bare.length === 8 ? `${bare.slice(0, 4)}-${bare.slice(4)}` : bare
}

const codeFromLocation = (): string => {
  try {
    return new URLSearchParams(window.location.search).get('code') ?? ''
  } catch {
    return ''
  }
}

const fieldStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '10px 12px',
  borderRadius: 6,
  border: '1px solid var(--border-default)',
  background: 'var(--surface-l1)',
  color: 'var(--text-primary)',
  fontSize: 15,
}

const labelStyle: React.CSSProperties = { display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 6 }

// Helper text: 13px and close to the body colour (the theme's secondary grey is too faint at this size).
const hintStyle: React.CSSProperties = {
  color: 'var(--text-primary)',
  opacity: 0.82,
  fontSize: 14,
  lineHeight: 1.45,
  margin: '6px 0 0',
}

const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  margin: 0,
  width: 'auto',
  alignSelf: 'flex-start',
  color: 'var(--accent-text)',
  fontFamily: 'var(--font-sans)',
  fontSize: 14,
  fontWeight: 500,
  whiteSpace: 'nowrap',
  cursor: 'pointer',
  textDecoration: 'underline',
  textUnderlineOffset: 3,
}

// Wider than the sign-in card so the setup fields and help text do not wrap awkwardly.
const formStyle: React.CSSProperties = { maxWidth: 420, gap: 12, padding: '20px 28px' }

export const FirstRunSetup: React.FC<FirstRunSetupProps> = ({ status, onClaimed, onAlreadyClaimed }) => {
  const urlCode = codeFromLocation()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [code, setCode] = useState(() => (urlCode ? normalizeSetupCode(urlCode) : ''))
  const [showCode, setShowCode] = useState<boolean>(() => Boolean(status.code_required) || urlCode !== '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showLicense, setShowLicense] = useState(false)
  const [licenseKey, setLicenseKey] = useState('')
  const [licenseResult, setLicenseResult] = useState<LicenseOutcome | null>(null)
  const [claimedName, setClaimedName] = useState('')
  const [codeRejected, setCodeRejected] = useState(false)
  const [showPasswords, setShowPasswords] = useState(false)

  const hints = status.where_is_the_code ?? []

  const fail = (message: string) => {
    setError(message)
    setBusy(false)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setError('')

    const name = username.trim()
    if (name.length < MIN_USERNAME) {
      setError(`Username must be at least ${MIN_USERNAME} characters.`)
      return
    }
    if (password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters.`)
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    const normalizedCode = showCode ? normalizeSetupCode(code) : ''
    if (showCode && !normalizedCode) {
      setError('Enter the setup code. It is printed in the MEMAR log, or in the setup link.')
      return
    }

    setBusy(true)
    try {
      const res = await fetch(`${API_BASE}/api/setup/claim`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: name,
          password,
          code: normalizedCode || null,
        }),
      })

      if (res.status === 201) {
        const data = await res.json() as { access_token: string; refresh_token?: string }
        // Same token storage the login handler uses.
        setTokens(data.access_token, data.refresh_token || '')
        // Keep the code out of the address bar and history once used.
        if (window.location.search) {
          window.history.replaceState(null, '', window.location.pathname)
        }
        const key = licenseKey.replace(/\s+/g, '')
        if (showLicense && key) {
          // Activate before continuing so the device wizard sees the paid limit.
          const outcome = await activateLicense(key, data.access_token)
          setBusy(false)
          setClaimedName(name)
          setLicenseResult(outcome)
          return
        }
        setBusy(false)
        onClaimed(name)
        return
      }

      if (res.status === 409) {
        setBusy(false)
        onAlreadyClaimed()
        return
      }

      if (res.status === 403) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        if (body.detail === 'code_invalid') {
          fail('That setup code is not right. Check it and try again.')
          setCodeRejected(true)
          setShowCode(true)
        } else {
          // code_required (or any other 403): reveal the code field.
          setShowCode(true)
          fail('Enter the setup code to continue.')
        }
        return
      }

      if (res.status === 429) {
        fail('Too many tries. Wait a minute.')
        return
      }

      if (res.status === 422) {
        const body = await res.json().catch(() => ({})) as { detail?: unknown }
        let message = 'Check the details and try again.'
        if (typeof body.detail === 'string') {
          message = body.detail
        } else if (Array.isArray(body.detail) && body.detail.length > 0) {
          const first = body.detail[0] as { msg?: unknown }
          if (typeof first?.msg === 'string') message = first.msg
        }
        fail(message)
        return
      }

      fail(`Setup failed (HTTP ${res.status}). Try again.`)
    } catch {
      fail('Could not reach MEMAR. Check the connection and try again.')
    }
  }

  if (licenseResult) {
    return (
      <main className="login-screen">
        <form
          style={formStyle}
          aria-label="First-run setup complete"
          onSubmit={(e) => { e.preventDefault(); onClaimed(claimedName) }}
        >
          <h1 style={{ marginBottom: 4 }}>Account created</h1>
          {licenseResult.ok ? (
            <div role="status" style={{ fontSize: 16, lineHeight: 1.5, textAlign: 'center', fontWeight: 600, color: 'var(--color-success)' }}>
              {'\u2713 '}{licenseResult.message}
            </div>
          ) : (
            <div role="status" style={{ fontSize: 16, lineHeight: 1.5, textAlign: 'left', color: 'var(--text-primary)', marginBottom: 10 }}>
              <div style={{ fontWeight: 700, color: 'color-mix(in oklch, var(--color-warning) 70%, var(--text-primary))', marginBottom: 8 }}>{'\u26a0 '}License key not accepted</div>
              <div>You are on the Free plan for now.</div>
              <div style={{ marginTop: 8 }}>
                To try again, use <strong>Free plan {'\u00b7'} Upgrade</strong> at the top of the next screen.
              </div>
            </div>
          )}
          <button type="submit" autoFocus>Continue to add devices</button>
        </form>
      </main>
    )
  }

  const codeFromLink = urlCode !== '' && normalizeSetupCode(code) === normalizeSetupCode(urlCode) && !codeRejected

  return (
    <main className="login-screen">
      <form onSubmit={submit} aria-label="First-run setup" style={formStyle}>
        <div>
          <h1 style={{ marginBottom: 6 }}>Welcome to MEMAR</h1>
          <p style={{ textAlign: 'center', color: 'var(--text-primary)', opacity: 0.8, fontSize: 15, margin: 0 }}>
            Create the admin account for this MEMAR.
          </p>
        </div>

        <div>
          <label htmlFor="firstrun-username" style={labelStyle}>Username</label>
          <input
            id="firstrun-username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={fieldStyle}
          />
        </div>

        <div>
          <label htmlFor="firstrun-password" style={labelStyle}>Password</label>
          <input
            id="firstrun-password"
            type={showPasswords ? 'text' : 'password'}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby="firstrun-password-hint"
            style={fieldStyle}
          />
          <p id="firstrun-password-hint" style={hintStyle}>At least {MIN_PASSWORD} characters.</p>
        </div>

        <div>
          <label htmlFor="firstrun-confirm" style={labelStyle}>Confirm password</label>
          <input
            id="firstrun-confirm"
            type={showPasswords ? 'text' : 'password'}
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            style={fieldStyle}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, fontSize: 14, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={showPasswords}
              onChange={(e) => setShowPasswords(e.target.checked)}
              style={{ width: 18, height: 18, margin: 0, accentColor: 'var(--accent-solid)' }}
            />
            Show passwords
          </label>
        </div>

        {showCode && (
          <div>
            <label htmlFor="firstrun-code" style={labelStyle}>Setup code</label>
            <input
              id="firstrun-code"
              type="text"
              autoComplete="off"
              spellCheck={false}
              placeholder="XXXX-XXXX"
              value={code}
              onChange={(e) => { setCode(e.target.value); setCodeRejected(false) }}
              aria-describedby="firstrun-code-hint"
              style={{ ...fieldStyle, letterSpacing: '0.1em', fontFamily: 'var(--font-mono)' }}
            />
            {codeFromLink ? (
              <p id="firstrun-code-hint" style={{ ...hintStyle, color: 'var(--color-success)', opacity: 1, fontWeight: 600, fontSize: 14 }}>
                {'✓'} Filled in from your setup link.
              </p>
            ) : hints.length > 0 && (
              <details id="firstrun-code-hint" style={hintStyle} open={codeRejected || code.trim() === ''}>
                <summary style={{ cursor: 'pointer', color: 'var(--accent-text)' }}>Where do I find the code?</summary>
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                  {hints.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {!showLicense ? (
          <button type="button" onClick={() => setShowLicense(true)} style={linkButtonStyle}>
            Paid plan? Add your license key
          </button>
        ) : (
          <div>
            <label htmlFor="firstrun-license" style={labelStyle}>License key (optional)</label>
            <textarea
              id="firstrun-license"
              rows={2}
              spellCheck={false}
              autoComplete="off"
              value={licenseKey}
              onChange={(e) => setLicenseKey(e.target.value)}
              aria-describedby="firstrun-license-hint"
              style={{ ...fieldStyle, fontFamily: 'var(--font-mono)', fontSize: 13, minHeight: 0, resize: 'vertical', wordBreak: 'break-all' }}
            />
            <p id="firstrun-license-hint" style={hintStyle}>
              {licenseKey.trim()
                ? `Key pasted (${licenseKey.replace(/\s+/g, '').length} characters, ends …${licenseKey.replace(/\s+/g, '').slice(-6)}).`
                : 'Paste the key from your purchase email. You can also add it later.'}
            </p>
          </div>
        )}

        {error && <div role="alert" className="login-error">{error}</div>}

        <button type="submit" disabled={busy}>
          {busy ? 'Creating account…' : 'Create admin account'}
        </button>
      </form>
    </main>
  )
}

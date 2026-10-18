/**
 * AdminPanel — self-contained admin modal: white-label branding form (PUT
 * /api/admin/branding) + audit-log viewer (GET /api/admin/audit). Both are
 * backend-gated (admin role + tier); this UI degrades gracefully on 402/403.
 */
import { useEffect, useState } from 'react'

import { apiFetch } from './api'
import { useFocusTrap } from './hooks/useFocusTrap'

interface Branding {
  company_name: string
  logo_url: string | null
  primary_color: string
  support_email: string | null
  custom: boolean
}

interface AuditRow {
  id: number
  username: string | null
  action: string
  resource: string | null
  created_at: string | null
  ip_address: string | null
}

interface UserRow {
  id: number
  username: string
  role: string
  is_active: boolean
  created_at: string | null
}

interface MessagingAdapter {
  name: string
  enabled: boolean
  bidirectional: boolean
  ok: boolean | null
  ts: string | null
  error: string | null
}

interface MessagingIdentity {
  id: number
  platform: string
  platform_user_id: string
  username: string | null
  memar_role: string | null
}

interface SsoEnvDefaults {
  oidc_issuer_set: boolean
  oidc_client_id_set: boolean
  oidc_client_secret_set: boolean
  ldap_server_set: boolean
  ldap_user_dn_template_set: boolean
}

interface SsoSettings {
  oidc_issuer: string
  oidc_client_id: string
  oidc_client_secret_set: boolean
  oidc_redirect_uri: string
  ldap_server: string
  ldap_user_dn_template: string
  ldap_default_role: string
  sso_default_role: string
  saml_idp_entity_id: string
  saml_idp_sso_url: string
  saml_idp_cert_pem: string
  saml_sp_entity_id: string
  saml_configured: boolean
  env_defaults: SsoEnvDefaults
}

interface SsoDraft {
  oidcIssuer: string
  oidcClientId: string
  oidcRedirectUri: string
  oidcClientSecret: string
  oidcClientSecretDirty: boolean
  oidcClientSecretClear: boolean
  oidcClientSecretSet: boolean
  ldapServer: string
  ldapUserDnTemplate: string
  ldapDefaultRole: string
  ssoDefaultRole: string
  samlIdpEntityId: string
  samlIdpSsoUrl: string
  samlIdpCertPem: string
  samlSpEntityId: string
  envDefaults: SsoEnvDefaults
}

const ROLE_OPTIONS = ['viewer', 'operator', 'admin'] as const

function ssoDraftFromSettings(s: SsoSettings): SsoDraft {
  return {
    oidcIssuer: s.oidc_issuer,
    oidcClientId: s.oidc_client_id,
    oidcRedirectUri: s.oidc_redirect_uri,
    oidcClientSecret: '',
    oidcClientSecretDirty: false,
    oidcClientSecretClear: false,
    oidcClientSecretSet: s.oidc_client_secret_set,
    ldapServer: s.ldap_server,
    ldapUserDnTemplate: s.ldap_user_dn_template,
    ldapDefaultRole: s.ldap_default_role || 'viewer',
    ssoDefaultRole: s.sso_default_role || 'viewer',
    samlIdpEntityId: s.saml_idp_entity_id,
    samlIdpSsoUrl: s.saml_idp_sso_url,
    samlIdpCertPem: s.saml_idp_cert_pem,
    samlSpEntityId: s.saml_sp_entity_id,
    envDefaults: s.env_defaults,
  }
}

export function AdminPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'branding' | 'audit' | 'notifications' | 'users' | 'sso'>('branding')
  const [branding, setBranding] = useState<Branding | null>(null)
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [msgAdapters, setMsgAdapters] = useState<MessagingAdapter[]>([])
  const [msgIdentities, setMsgIdentities] = useState<MessagingIdentity[]>([])
  const [msgTestStatus, setMsgTestStatus] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  // Focus trap for modal
  const adminPanelRef = useFocusTrap<HTMLDivElement>(true)

  // Users tab
  const [users, setUsers] = useState<UserRow[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersErr, setUsersErr] = useState('')
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState('viewer')
  const [createBusy, setCreateBusy] = useState(false)
  const [createMsg, setCreateMsg] = useState('')

  // SSO tab
  const [sso, setSso] = useState<SsoDraft | null>(null)
  const [ssoLoading, setSsoLoading] = useState(false)
  const [ssoBusy, setSsoBusy] = useState(false)
  const [ssoMsg, setSsoMsg] = useState('')
  const [ssoErr, setSsoErr] = useState('')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    apiFetch('/api/branding').then((r) => (r.ok ? r.json() : null)).then((b) => b && setBranding(b)).catch(() => {})
  }, [])

  useEffect(() => {
    if (tab !== 'audit') return
    apiFetch('/api/admin/audit?limit=200')
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => setAudit(Array.isArray(rows) ? rows : []))
      .catch(() => setAudit([]))
  }, [tab])

  useEffect(() => {
    if (tab !== 'users') return
    setUsersLoading(true)
    setUsersErr('')
    apiFetch('/api/admin/users')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((rows) => setUsers(Array.isArray(rows) ? rows : []))
      .catch(() => setUsersErr('Failed to load users'))
      .finally(() => setUsersLoading(false))
  }, [tab])

  async function reloadUsers() {
    const r = await apiFetch('/api/admin/users')
    if (r.ok) setUsers(await r.json())
  }

  async function changeRole(userId: number, role: string) {
    const r = await apiFetch(`/api/admin/users/${userId}/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    })
    if (r.ok) await reloadUsers()
    else setUsersErr('Role update failed')
  }

  async function toggleSuspend(userId: number, isActive: boolean) {
    const endpoint = isActive ? 'suspend' : 'unsuspend'
    const r = await apiFetch(`/api/admin/users/${userId}/${endpoint}`, { method: 'POST' })
    if (r.ok) await reloadUsers()
    else setUsersErr(`${endpoint} failed`)
  }

  async function deleteUser(userId: number, username: string) {
    if (!window.confirm(`Delete user "${username}"? This cannot be undone.`)) return
    const r = await apiFetch(`/api/admin/users/${userId}`, { method: 'DELETE' })
    if (r.ok) await reloadUsers()
    else setUsersErr('Delete failed')
  }

  async function adminResetPassword(userId: number) {
    const r = await apiFetch(`/api/admin/users/${userId}/reset-password`, { method: 'POST' })
    if (r.ok) {
      const d = await r.json() as { reset_url: string }
      window.prompt('Share this reset link with the user (expires in 15 min):', d.reset_url)
    } else {
      setUsersErr('Reset password failed')
    }
  }

  async function createUser() {
    setCreateMsg(''); setUsersErr('')
    if (!newUsername || !newPassword) { setCreateMsg('Username and password required'); return }
    setCreateBusy(true)
    try {
      const r = await apiFetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: newUsername, password: newPassword, role: newRole }),
      })
      if (r.ok) {
        setNewUsername(''); setNewPassword(''); setNewRole('viewer')
        setCreateMsg('User created')
        await reloadUsers()
      } else {
        const d = await r.json().catch(() => ({})) as { detail?: string }
        setCreateMsg(d.detail || 'Create failed')
      }
    } finally { setCreateBusy(false) }
  }

  useEffect(() => {
    if (tab !== 'sso') return
    setSsoLoading(true)
    setSsoErr('')
    apiFetch('/api/admin/sso/settings')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: SsoSettings) => setSso(ssoDraftFromSettings(d)))
      .catch(() => setSsoErr('Failed to load SSO settings'))
      .finally(() => setSsoLoading(false))
  }, [tab])

  const updSso = (patch: Partial<SsoDraft>) => sso && setSso({ ...sso, ...patch })

  async function saveSso() {
    setSsoMsg(''); setSsoErr('')
    if (!sso) return
    setSsoBusy(true)
    try {
      const body: Record<string, string> = {
        oidc_issuer: sso.oidcIssuer,
        oidc_client_id: sso.oidcClientId,
        oidc_redirect_uri: sso.oidcRedirectUri,
        ldap_server: sso.ldapServer,
        ldap_user_dn_template: sso.ldapUserDnTemplate,
        ldap_default_role: sso.ldapDefaultRole,
        sso_default_role: sso.ssoDefaultRole,
        saml_idp_entity_id: sso.samlIdpEntityId,
        saml_idp_sso_url: sso.samlIdpSsoUrl,
        saml_idp_cert_pem: sso.samlIdpCertPem,
        saml_sp_entity_id: sso.samlSpEntityId,
      }
      if (sso.oidcClientSecretClear) {
        body.oidc_client_secret = ''
      } else if (sso.oidcClientSecretDirty) {
        body.oidc_client_secret = sso.oidcClientSecret
      }
      const r = await apiFetch('/api/admin/sso/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (r.ok) {
        const d = await r.json() as SsoSettings
        setSso(ssoDraftFromSettings(d))
        setSsoMsg('SSO settings saved.')
      } else {
        const d = await r.json().catch(() => ({})) as { detail?: string }
        setSsoErr(d.detail || 'Save failed.')
      }
    } finally { setSsoBusy(false) }
  }

  useEffect(() => {
    if (tab !== 'notifications') return
    apiFetch('/api/admin/messaging/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d?.adapters && setMsgAdapters(d.adapters))
      .catch(() => setMsgAdapters([]))
    apiFetch('/api/admin/messaging/identities')
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => setMsgIdentities(Array.isArray(rows) ? rows : []))
      .catch(() => setMsgIdentities([]))
  }, [tab])

  async function sendTestAlert() {
    setMsgTestStatus('')
    const res = await apiFetch('/api/admin/messaging/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
    setMsgTestStatus(res.ok ? 'Test alert sent.' : 'Failed.')
  }

  async function saveBranding() {
    setMsg(''); setErr('')
    if (!branding) return
    const res = await apiFetch('/api/admin/branding', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_name: branding.company_name,
        logo_url: branding.logo_url,
        primary_color: branding.primary_color,
        support_email: branding.support_email,
      }),
    })
    if (res.ok) { setBranding(await res.json()); setMsg('Saved — reload to apply everywhere.') }
    else if (res.status === 402) setErr('White-label requires an active license.')
    else setErr('Save failed.')
  }

  const upd = (patch: Partial<Branding>) => branding && setBranding({ ...branding, ...patch })

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div ref={adminPanelRef} className="modal-content" role="dialog" aria-modal="true" aria-label="Admin" onClick={(e) => e.stopPropagation()}
           style={{ maxWidth: 720, width: '90%' }}>
        <button className="modal-close" onClick={onClose} aria-label="Close admin settings">✕</button>
        <h2>Admin</h2>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          <button type="button" onClick={() => setTab('branding')} disabled={tab === 'branding'}>Branding</button>
          <button type="button" onClick={() => setTab('users')} disabled={tab === 'users'}>Users</button>
          <button type="button" onClick={() => setTab('audit')} disabled={tab === 'audit'}>Audit log</button>
          <button type="button" onClick={() => setTab('notifications')} disabled={tab === 'notifications'}>Notifications</button>
          <button type="button" onClick={() => setTab('sso')} disabled={tab === 'sso'}>SSO</button>
        </div>

        {tab === 'branding' && branding && (
          <div className="admin-branding-form" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <label>Company name
              <input value={branding.company_name} onChange={(e) => upd({ company_name: e.target.value })} />
            </label>
            <label>Logo URL
              <input value={branding.logo_url || ''} onChange={(e) => upd({ logo_url: e.target.value })} placeholder="https://…/logo.png" />
            </label>
            <label>Primary colour
              <input type="color" value={branding.primary_color} onChange={(e) => upd({ primary_color: e.target.value })} />
            </label>
            <label>Support email
              <input value={branding.support_email || ''} onChange={(e) => upd({ support_email: e.target.value })} />
            </label>
            <button type="button" onClick={saveBranding}>Save branding</button>
            {msg && <div style={{ color: 'var(--color-success)' }}>{msg}</div>}
            {err && <div style={{ color: 'var(--color-danger)' }}>{err}</div>}
            {!branding.custom && (
              <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                White-label takes effect while your license is active — changes save either way.
              </div>
            )}
          </div>
        )}

        {tab === 'users' && (
          <div>
            {usersErr && <div style={{ color: 'var(--color-danger)', marginBottom: 8, fontSize: 13 }}>{usersErr}</div>}
            {usersLoading ? (
              <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>Loading…</div>
            ) : (
              <div style={{ maxHeight: 300, overflow: 'auto', marginBottom: 16 }}>
                <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {['Username', 'Role', 'Status', 'Actions'].map((h) => (
                        <th key={h} style={{ textAlign: 'left', padding: '4px 8px' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {users.length === 0 && (
                      <tr><td colSpan={4} style={{ color: 'var(--text-secondary)', padding: 8 }}>No users found.</td></tr>
                    )}
                    {users.map((u) => (
                      <tr key={u.id} style={{ borderTop: '1px solid var(--border-default)' }}>
                        <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{u.username}</td>
                        <td style={{ padding: '4px 8px' }}>
                          <select
                            value={u.role}
                            aria-label={`Role for ${u.username}`}
                            style={{ fontSize: 13, background: 'var(--surface-l1, #1a1a1a)', color: 'inherit', border: '1px solid var(--border-default)', borderRadius: 4, padding: '2px 6px' }}
                            onChange={(e) => void changeRole(u.id, e.target.value)}
                          >
                            <option value="viewer">viewer</option>
                            <option value="operator">operator</option>
                            <option value="admin">admin</option>
                          </select>
                        </td>
                        <td style={{ padding: '4px 8px', color: u.is_active ? 'var(--color-success)' : 'var(--color-danger)' }}>
                          {u.is_active ? 'active' : 'suspended'}
                        </td>
                        <td style={{ padding: '4px 8px', display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            aria-label={u.is_active ? `Suspend ${u.username}` : `Unsuspend ${u.username}`}
                            style={{ fontSize: 12, padding: '2px 8px' }}
                            onClick={() => void toggleSuspend(u.id, u.is_active)}
                          >{u.is_active ? 'Suspend' : 'Unsuspend'}</button>
                          <button
                            type="button"
                            aria-label={`Reset password for ${u.username}`}
                            style={{ fontSize: 12, padding: '2px 8px' }}
                            onClick={() => void adminResetPassword(u.id)}
                          >Reset pw</button>
                          <button
                            type="button"
                            aria-label={`Delete ${u.username}`}
                            style={{ fontSize: 12, padding: '2px 8px', color: 'var(--color-danger)', borderColor: 'var(--color-danger)' }}
                            onClick={() => void deleteUser(u.id, u.username)}
                          >Delete</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 12 }}>
              <strong style={{ fontSize: 13 }}>Create user</strong>
              <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
                  Username
                  <input
                    value={newUsername}
                    onChange={(e) => setNewUsername(e.target.value)}
                    aria-label="New user username"
                    style={{ fontSize: 13, padding: '4px 8px' }}
                    placeholder="username"
                  />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
                  Password
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    aria-label="New user password"
                    style={{ fontSize: 13, padding: '4px 8px' }}
                    placeholder="min 8 characters"
                  />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
                  Role
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value)}
                    aria-label="New user role"
                    style={{ fontSize: 13, background: 'var(--surface-l1, #1a1a1a)', color: 'inherit', border: '1px solid var(--border-default)', borderRadius: 4, padding: '4px 8px' }}
                  >
                    <option value="viewer">viewer</option>
                    <option value="operator">operator</option>
                    <option value="admin">admin</option>
                  </select>
                </label>
                <button
                  type="button"
                  disabled={createBusy}
                  onClick={() => void createUser()}
                  aria-label="Create new user"
                  style={{ padding: '4px 14px', fontSize: 13 }}
                >{createBusy ? 'Creating…' : 'Create'}</button>
              </div>
              {createMsg && (
                <div style={{ marginTop: 8, fontSize: 13, color: createMsg === 'User created' ? 'var(--color-success)' : 'var(--color-danger)' }}>
                  {createMsg}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'sso' && (
          <div>
            {ssoLoading && <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>Loading…</div>}
            {ssoErr && <div style={{ color: 'var(--color-danger)', marginBottom: 8, fontSize: 13 }}>{ssoErr}</div>}
            {sso && (
              <div className="admin-branding-form" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <strong style={{ fontSize: 13 }}>OIDC</strong>
                <label>Issuer
                  <input value={sso.oidcIssuer} onChange={(e) => updSso({ oidcIssuer: e.target.value })} placeholder="https://idp.example.com" />
                  {!sso.oidcIssuer && sso.envDefaults.oidc_issuer_set && (
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Using MEMAR_OIDC_ISSUER from environment</span>
                  )}
                </label>
                <label>Client ID
                  <input value={sso.oidcClientId} onChange={(e) => updSso({ oidcClientId: e.target.value })} />
                  {!sso.oidcClientId && sso.envDefaults.oidc_client_id_set && (
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Using MEMAR_OIDC_CLIENT_ID from environment</span>
                  )}
                </label>
                <label>Client secret{sso.oidcClientSecretSet ? ' (configured)' : ''}
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={sso.oidcClientSecret}
                    disabled={sso.oidcClientSecretClear}
                    onChange={(e) => updSso({ oidcClientSecret: e.target.value, oidcClientSecretDirty: true })}
                    placeholder={sso.oidcClientSecretClear ? 'Will be removed on save' : sso.oidcClientSecretSet ? 'Leave blank to keep current' : 'OIDC client secret'}
                  />
                  {!sso.oidcClientSecretSet && sso.envDefaults.oidc_client_secret_set && (
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Using MEMAR_OIDC_CLIENT_SECRET from environment</span>
                  )}
                </label>
                {sso.oidcClientSecretSet && (
                  <label className="checkbox-line">
                    <input type="checkbox" checked={sso.oidcClientSecretClear} onChange={(e) => updSso({ oidcClientSecretClear: e.target.checked })} /> Clear client secret
                  </label>
                )}
                <label>Redirect URI
                  <input value={sso.oidcRedirectUri} onChange={(e) => updSso({ oidcRedirectUri: e.target.value })} placeholder="https://…/api/auth/sso/oidc/callback" />
                </label>

                <strong style={{ fontSize: 13, marginTop: 8 }}>SAML 2.0</strong>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  Give your identity provider these values. Assertion consumer URL: <code>{typeof window !== 'undefined' ? `${window.location.origin}/api/auth/saml/acs` : '/api/auth/saml/acs'}</code>
                </span>
                <label>IdP entity ID
                  <input value={sso.samlIdpEntityId} onChange={(e) => updSso({ samlIdpEntityId: e.target.value })} placeholder="https://idp.example.com/metadata" />
                </label>
                <label>IdP sign-on URL
                  <input value={sso.samlIdpSsoUrl} onChange={(e) => updSso({ samlIdpSsoUrl: e.target.value })} placeholder="https://idp.example.com/sso" />
                </label>
                <label>IdP signing certificate (PEM)
                  <textarea
                    rows={5}
                    value={sso.samlIdpCertPem}
                    onChange={(e) => updSso({ samlIdpCertPem: e.target.value })}
                    placeholder={'-----BEGIN CERTIFICATE-----\n…\n-----END CERTIFICATE-----'}
                    style={{ fontFamily: 'monospace', fontSize: 12 }}
                  />
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Pinned here. Metadata is not fetched at login, so a changed key on the network cannot be accepted.</span>
                </label>
                <label>Service provider entity ID (optional)
                  <input value={sso.samlSpEntityId} onChange={(e) => updSso({ samlSpEntityId: e.target.value })} placeholder="Leave blank to use the metadata URL" />
                </label>

                <strong style={{ fontSize: 13, marginTop: 8 }}>LDAP</strong>
                <label>Server URL
                  <input value={sso.ldapServer} onChange={(e) => updSso({ ldapServer: e.target.value })} placeholder="ldap://ldap.example.com" />
                  {!sso.ldapServer && sso.envDefaults.ldap_server_set && (
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Using MEMAR_LDAP_SERVER from environment</span>
                  )}
                </label>
                <label>User DN template
                  <input value={sso.ldapUserDnTemplate} onChange={(e) => updSso({ ldapUserDnTemplate: e.target.value })} placeholder="uid={username},ou=people,dc=example,dc=com" />
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{'{username}'} is substituted with the login username at bind time.</span>
                  {!sso.ldapUserDnTemplate && sso.envDefaults.ldap_user_dn_template_set && (
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Using MEMAR_LDAP_USER_DN_TEMPLATE from environment</span>
                  )}
                </label>
                <label>LDAP default role
                  <select
                    value={sso.ldapDefaultRole}
                    onChange={(e) => updSso({ ldapDefaultRole: e.target.value })}
                    style={{ fontSize: 13, background: 'var(--surface-l1, #1a1a1a)', color: 'inherit', border: '1px solid var(--border-default)', borderRadius: 4, padding: '4px 8px' }}
                  >
                    {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </label>

                <strong style={{ fontSize: 13, marginTop: 8 }}>Defaults</strong>
                <label>Default SSO role
                  <select
                    value={sso.ssoDefaultRole}
                    onChange={(e) => updSso({ ssoDefaultRole: e.target.value })}
                    style={{ fontSize: 13, background: 'var(--surface-l1, #1a1a1a)', color: 'inherit', border: '1px solid var(--border-default)', borderRadius: 4, padding: '4px 8px' }}
                  >
                    {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Applied to OIDC logins (and LDAP logins with no LDAP-specific role set above).</span>
                </label>

                <button type="button" disabled={ssoBusy} onClick={() => void saveSso()}>{ssoBusy ? 'Saving…' : 'Save SSO settings'}</button>
                {ssoMsg && <div style={{ color: 'var(--color-success)' }}>{ssoMsg}</div>}
              </div>
            )}
          </div>
        )}

        {tab === 'notifications' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <strong>Adapter status</strong>
              <button type="button" onClick={sendTestAlert} style={{ fontSize: 12 }}>Send test alert</button>
              {msgTestStatus && <span style={{ fontSize: 12, color: 'var(--color-success)' }}>{msgTestStatus}</span>}
            </div>
            {msgAdapters.length === 0 ? (
              <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>No messaging adapters configured.</p>
            ) : (
              <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse', marginBottom: 20 }}>
                <thead>
                  <tr>
                    {['Adapter', 'Bidirectional', 'Last delivery', 'Status'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '4px 8px' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {msgAdapters.map((a) => (
                    <tr key={a.name} style={{ borderTop: '1px solid var(--border-default)' }}>
                      <td style={{ padding: '4px 8px' }}>{a.name}</td>
                      <td style={{ padding: '4px 8px' }}>{a.bidirectional ? '✓' : '—'}</td>
                      <td style={{ padding: '4px 8px' }}>{a.ts?.replace('T', ' ').slice(0, 19) || '—'}</td>
                      <td style={{ padding: '4px 8px' }}>
                        {a.ok === null ? '—' : a.ok ? '✅ ok' : `❌ ${a.error || 'failed'}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <strong>Linked identities</strong>
            <div style={{ maxHeight: 240, overflow: 'auto', marginTop: 8 }}>
              <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['Platform', 'Platform user ID', 'MEMAR user', 'Role'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '4px 8px' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {msgIdentities.length === 0 && (
                    <tr><td colSpan={4} style={{ color: 'var(--text-secondary)', padding: 8 }}>No identities linked yet. Use POST /api/admin/messaging/identities.</td></tr>
                  )}
                  {msgIdentities.map((i) => (
                    <tr key={i.id} style={{ borderTop: '1px solid var(--border-default)' }}>
                      <td style={{ padding: '4px 8px' }}>{i.platform}</td>
                      <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{i.platform_user_id}</td>
                      <td style={{ padding: '4px 8px' }}>{i.username || '—'}</td>
                      <td style={{ padding: '4px 8px' }}>{i.memar_role || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === 'audit' && (
          <div style={{ maxHeight: 420, overflow: 'auto' }}>
            <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Time', 'User', 'Action', 'Resource', 'IP'].map((h) => (
                    <th key={h} style={{ textAlign: 'left', padding: '4px 8px' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {audit.length === 0 && (
                  <tr><td colSpan={5} style={{ color: 'var(--text-secondary)', padding: 8 }}>No events (audit log requires an active license).</td></tr>
                )}
                {audit.map((r) => (
                  <tr key={r.id} style={{ borderTop: '1px solid var(--border-default)' }}>
                    <td style={{ padding: '4px 8px' }}>{r.created_at?.replace('T', ' ').slice(0, 19) || '—'}</td>
                    <td style={{ padding: '4px 8px' }}>{r.username || '—'}</td>
                    <td style={{ padding: '4px 8px' }}>{r.action}</td>
                    <td style={{ padding: '4px 8px' }}>{r.resource || '—'}</td>
                    <td style={{ padding: '4px 8px' }}>{r.ip_address || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

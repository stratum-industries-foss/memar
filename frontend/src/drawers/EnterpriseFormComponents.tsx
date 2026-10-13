/**
 * EnterpriseFormComponents — Reusable form components for enterprise settings
 *
 * Provides:
 * - SSO/LDAP configuration form
 * - Messaging platform configuration
 * - RBAC role editor
 * - Branding customization
 * - Webhook manager
 * - Analytics settings
 */

import React, { useState } from 'react'
import type {
  SsoConfig,
  MessagingPlatform,
  UserRole,
  BrandingConfig,
  Webhook,
  AnalyticsConfig,
} from './useEnterpriseSettings'

/* ========== SSO/LDAP Configuration ========== */

interface SsoFormProps {
  config: SsoConfig
  onUpdate: (config: Partial<SsoConfig>) => void
  onTest: () => Promise<boolean>
  loading: boolean
}

export const SsoForm: React.FC<SsoFormProps> = ({ config, onUpdate, onTest, loading }) => {
  const [testing, setTesting] = useState(false)

  const handleTest = async () => {
    setTesting(true)
    try {
      await onTest()
    } finally {
      setTesting(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Enable SSO toggle */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          checked={config.enabled}
          onChange={(e) => onUpdate({ enabled: e.target.checked })}
          disabled={loading}
        />
        <span>Enable SSO/LDAP Authentication</span>
      </label>

      {config.enabled && (
        <>
          {/* Provider selection */}
          <div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontWeight: 500 }}>Authentication Provider</span>
              <select
                value={config.provider}
                onChange={(e) => onUpdate({ provider: e.target.value as any })}
                disabled={loading}
              >
                <option value="oidc">OpenID Connect (OIDC)</option>
                <option value="ldap">LDAP</option>
                <option value="saml">SAML 2.0</option>
              </select>
              <span className="subtle small">Choose your authentication provider type</span>
            </label>
          </div>

          {/* OIDC configuration */}
          {config.provider === 'oidc' && (
            <>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Discovery URL</span>
                  <input
                    type="url"
                    value={config.discoveryUrl || ''}
                    onChange={(e) => onUpdate({ discoveryUrl: e.target.value })}
                    placeholder="https://provider.example.com/.well-known/openid-configuration"
                    disabled={loading}
                  />
                  <span className="subtle small">The OIDC provider's discovery endpoint</span>
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Client ID</span>
                  <input
                    type="text"
                    value={config.clientId || ''}
                    onChange={(e) => onUpdate({ clientId: e.target.value })}
                    placeholder="your-client-id"
                    disabled={loading}
                  />
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Client Secret</span>
                  <input
                    type="password"
                    value={config.clientSecret || ''}
                    onChange={(e) => onUpdate({ clientSecret: e.target.value })}
                    placeholder="••••••••••••"
                    disabled={loading}
                  />
                  <span className="subtle small">Keep this secure; never share publicly</span>
                </label>
              </div>
            </>
          )}

          {/* LDAP configuration */}
          {config.provider === 'ldap' && (
            <>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>LDAP Server Host</span>
                  <input
                    type="text"
                    value={config.ldapHost || ''}
                    onChange={(e) => onUpdate({ ldapHost: e.target.value })}
                    placeholder="ldap.example.com"
                    disabled={loading}
                  />
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>LDAP Server Port</span>
                  <input
                    type="number"
                    value={config.ldapPort || 389}
                    onChange={(e) => onUpdate({ ldapPort: Number(e.target.value) })}
                    placeholder="389"
                    disabled={loading}
                  />
                  <span className="subtle small">Default: 389 (LDAP) or 636 (LDAPS)</span>
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Base DN</span>
                  <input
                    type="text"
                    value={config.ldapBaseDn || ''}
                    onChange={(e) => onUpdate({ ldapBaseDn: e.target.value })}
                    placeholder="dc=example,dc=com"
                    disabled={loading}
                  />
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Search Filter</span>
                  <input
                    type="text"
                    value={config.ldapSearchFilter || ''}
                    onChange={(e) => onUpdate({ ldapSearchFilter: e.target.value })}
                    placeholder="(&(objectClass=person)(uid=*))"
                    disabled={loading}
                  />
                  <span className="subtle small">LDAP filter for user search</span>
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Bind DN</span>
                  <input
                    type="text"
                    value={config.ldapBindDn || ''}
                    onChange={(e) => onUpdate({ ldapBindDn: e.target.value })}
                    placeholder="cn=admin,dc=example,dc=com"
                    disabled={loading}
                  />
                  <span className="subtle small">DN for LDAP bind user (leave empty for anonymous)</span>
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Bind Password</span>
                  <input
                    type="password"
                    value={config.ldapBindPassword || ''}
                    onChange={(e) => onUpdate({ ldapBindPassword: e.target.value })}
                    placeholder="••••••••••••"
                    disabled={loading}
                  />
                </label>
              </div>
            </>
          )}

          {/* Role sync option */}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="checkbox"
              checked={config.autoSyncRoles}
              onChange={(e) => onUpdate({ autoSyncRoles: e.target.checked })}
              disabled={loading}
            />
            <span>Auto-sync user roles from LDAP groups</span>
          </label>

          {/* Test connection button */}
          <button
            onClick={handleTest}
            disabled={testing || loading}
            style={{ padding: '8px 16px', minWidth: '200px' }}
          >
            {testing ? '⏳ Testing...' : '🔌 Test Connection'}
          </button>
        </>
      )}
    </div>
  )
}

/* ========== Messaging Platform Configuration ========== */

interface MessagingFormProps {
  platforms: MessagingPlatform[]
  onUpdate: (index: number, platform: Partial<MessagingPlatform>) => void
  onAdd: (type: MessagingPlatform['type']) => void
  onRemove: (index: number) => void
  onTest: (index: number) => Promise<boolean>
  loading: boolean
}

export const MessagingForm: React.FC<MessagingFormProps> = ({
  platforms,
  onUpdate,
  onAdd,
  onRemove,
  onTest,
  loading,
}) => {
  const [testing, setTesting] = useState<number | null>(null)

  const messagingTypes: MessagingPlatform['type'][] = [
    'telegram',
    'slack',
    'discord',
    'mattermost',
    'matrix',
    'ntfy',
    'webhook',
  ]

  const handleTest = async (index: number) => {
    setTesting(index)
    try {
      await onTest(index)
    } finally {
      setTesting(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Add new platform button */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {messagingTypes.map((type) => (
          <button
            key={type}
            onClick={() => onAdd(type)}
            disabled={loading || platforms.some((p) => p.type === type)}
            style={{ padding: '6px 12px', fontSize: '0.9rem' }}
          >
            + {type.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Platform configs */}
      {platforms.map((platform, index) => (
        <div
          key={platform.id}
          style={{
            border: '1px solid var(--border-color)',
            borderRadius: 4,
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 500 }}>
              {platform.type.toUpperCase()}
            </span>
            <button
              onClick={() => onRemove(index)}
              disabled={loading}
              style={{
                padding: '4px 8px',
                fontSize: '0.85rem',
                background: 'var(--color-danger)',
                color: 'white',
                border: 'none',
                borderRadius: 2,
                cursor: 'pointer',
              }}
            >
              Remove
            </button>
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="checkbox"
              checked={platform.enabled}
              onChange={(e) => onUpdate(index, { enabled: e.target.checked })}
              disabled={loading}
            />
            <span>Enable {platform.type}</span>
          </label>

          {/* Platform-specific config */}
          {platform.type === 'telegram' && (
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500 }}>Bot Token</span>
                <input
                  type="password"
                  value={platform.config.botToken || ''}
                  onChange={(e) =>
                    onUpdate(index, {
                      config: { ...platform.config, botToken: e.target.value },
                    })
                  }
                  placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                  disabled={loading}
                />
                <span className="subtle small">Telegram bot token from @BotFather</span>
              </label>
            </div>
          )}

          {platform.type === 'telegram' && (
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500 }}>Chat ID</span>
                <input
                  type="text"
                  value={platform.config.chatId || ''}
                  onChange={(e) =>
                    onUpdate(index, {
                      config: { ...platform.config, chatId: e.target.value },
                    })
                  }
                  placeholder="123456789"
                  disabled={loading}
                />
                <span className="subtle small">Telegram chat ID to send messages to</span>
              </label>
            </div>
          )}

          {(platform.type === 'slack' || platform.type === 'discord') && (
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500 }}>Webhook URL</span>
                <input
                  type="url"
                  value={platform.config.webhookUrl || ''}
                  onChange={(e) =>
                    onUpdate(index, {
                      config: { ...platform.config, webhookUrl: e.target.value },
                    })
                  }
                  placeholder="https://hooks.slack.com/services/T00000000/B00000000/XXXXXXX"
                  disabled={loading}
                />
                <span className="subtle small">{platform.type} incoming webhook URL</span>
              </label>
            </div>
          )}

          {platform.type === 'mattermost' && (
            <>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Server URL</span>
                  <input
                    type="url"
                    value={platform.config.serverUrl || ''}
                    onChange={(e) =>
                      onUpdate(index, {
                        config: { ...platform.config, serverUrl: e.target.value },
                      })
                    }
                    placeholder="https://mattermost.example.com"
                    disabled={loading}
                  />
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Token</span>
                  <input
                    type="password"
                    value={platform.config.token || ''}
                    onChange={(e) =>
                      onUpdate(index, {
                        config: { ...platform.config, token: e.target.value },
                      })
                    }
                    placeholder="••••••••••••"
                    disabled={loading}
                  />
                </label>
              </div>
            </>
          )}

          {platform.type === 'matrix' && (
            <>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Homeserver</span>
                  <input
                    type="url"
                    value={platform.config.homeserver || ''}
                    onChange={(e) =>
                      onUpdate(index, {
                        config: { ...platform.config, homeserver: e.target.value },
                      })
                    }
                    placeholder="https://matrix.org"
                    disabled={loading}
                  />
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Room ID</span>
                  <input
                    type="text"
                    value={platform.config.roomId || ''}
                    onChange={(e) =>
                      onUpdate(index, {
                        config: { ...platform.config, roomId: e.target.value },
                      })
                    }
                    placeholder="!OGEhHVWSdvArJzumhm:example.com"
                    disabled={loading}
                  />
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Access Token</span>
                  <input
                    type="password"
                    value={platform.config.accessToken || ''}
                    onChange={(e) =>
                      onUpdate(index, {
                        config: { ...platform.config, accessToken: e.target.value },
                      })
                    }
                    placeholder="••••••••••••"
                    disabled={loading}
                  />
                </label>
              </div>
            </>
          )}

          {platform.type === 'ntfy' && (
            <>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Topic</span>
                  <input
                    type="text"
                    value={platform.config.topic || ''}
                    onChange={(e) =>
                      onUpdate(index, {
                        config: { ...platform.config, topic: e.target.value },
                      })
                    }
                    placeholder="memar-alerts"
                    disabled={loading}
                  />
                  <span className="subtle small">ntfy.sh topic for notifications</span>
                </label>
              </div>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Server (optional)</span>
                  <input
                    type="url"
                    value={platform.config.server || 'https://ntfy.sh'}
                    onChange={(e) =>
                      onUpdate(index, {
                        config: { ...platform.config, server: e.target.value },
                      })
                    }
                    placeholder="https://ntfy.sh"
                    disabled={loading}
                  />
                  <span className="subtle small">Leave blank for ntfy.sh</span>
                </label>
              </div>
            </>
          )}

          {platform.type === 'webhook' && (
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500 }}>Webhook URL</span>
                <input
                  type="url"
                  value={platform.config.url || ''}
                  onChange={(e) =>
                    onUpdate(index, {
                      config: { ...platform.config, url: e.target.value },
                    })
                  }
                  placeholder="https://your-server.com/webhook"
                  disabled={loading}
                />
              </label>
            </div>
          )}

          {/* Test button */}
          <button
            onClick={() => handleTest(index)}
            disabled={testing === index || loading || !platform.enabled}
            style={{
              padding: '8px 12px',
              fontSize: '0.9rem',
              alignSelf: 'flex-start',
            }}
          >
            {testing === index ? '⏳ Testing...' : '📤 Test Platform'}
          </button>
        </div>
      ))}
    </div>
  )
}

/* ========== RBAC Role Editor ========== */

interface RbacFormProps {
  roles: UserRole[]
  onAdd: (role: UserRole) => void
  onUpdate: (id: string, role: Partial<UserRole>) => void
  onDelete: (id: string) => void
}

const defaultPermissions = {
  'view:dashboard': true,
  'view:printers': true,
  'view:files': true,
  'edit:settings': false,
  'execute:print': false,
  'execute:jog': false,
  'admin:users': false,
  'admin:webhooks': false,
  'admin:roles': false,
}

export const RbacForm: React.FC<RbacFormProps> = ({ roles, onAdd, onUpdate, onDelete }) => {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [newRoleName, setNewRoleName] = useState('')

  const handleAddRole = () => {
    if (!newRoleName.trim()) return
    const newRole: UserRole = {
      id: `role-${Date.now()}`,
      name: newRoleName,
      description: '',
      permissions: defaultPermissions,
      isCustom: true,
    }
    onAdd(newRole)
    setNewRoleName('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Add new role */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontWeight: 500 }}>New Role Name</span>
            <input
              type="text"
              value={newRoleName}
              onChange={(e) => setNewRoleName(e.target.value)}
              placeholder="e.g., Supervisor, Technician"
            />
          </label>
        </div>
        <button
          onClick={handleAddRole}
          disabled={!newRoleName.trim()}
          style={{ padding: '8px 16px' }}
        >
          ➕ Add Role
        </button>
      </div>

      {/* Role list */}
      {roles.map((role) => (
        <div
          key={role.id}
          style={{
            border: '1px solid var(--border-color)',
            borderRadius: 4,
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 500 }}>{role.name}</span>
              {!role.isCustom && <span className="subtle" style={{ marginLeft: 8 }}>System Role</span>}
            </div>
            {role.isCustom && (
              <button
                onClick={() => onDelete(role.id)}
                style={{
                  padding: '4px 8px',
                  fontSize: '0.85rem',
                  background: 'var(--color-danger)',
                  color: 'white',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                Delete
              </button>
            )}
          </div>

          {/* Description */}
          <div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: '0.9rem' }}>Description</span>
              <input
                type="text"
                value={role.description}
                onChange={(e) => onUpdate(role.id, { description: e.target.value })}
                placeholder="Describe this role"
                disabled={!role.isCustom}
              />
            </label>
          </div>

          {/* Permissions matrix */}
          <div>
            <span style={{ fontWeight: 500, fontSize: '0.9rem', display: 'block', marginBottom: 8 }}>
              Permissions
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8 }}>
              {Object.entries(role.permissions).map(([permission, granted]) => (
                <label key={permission} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.9rem' }}>
                  <input
                    type="checkbox"
                    checked={granted}
                    onChange={(e) =>
                      onUpdate(role.id, {
                        permissions: { ...role.permissions, [permission]: e.target.checked },
                      })
                    }
                    disabled={!role.isCustom}
                  />
                  <span>{permission}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ========== Branding Configuration ========== */

interface BrandingFormProps {
  config: BrandingConfig
  onUpdate: (config: Partial<BrandingConfig>) => void
  onUploadLogo: (file: File) => Promise<string>
  licenseTier?: string
}

export const BrandingForm: React.FC<BrandingFormProps> = ({
  config,
  onUpdate,
  onUploadLogo,
  licenseTier,
}) => {
  const [uploading, setUploading] = useState(false)
  const isEnterprise = licenseTier === 'enterprise'

  if (!isEnterprise) {
    return (
      <div
        style={{
          padding: 16,
          background: 'var(--bg-warning, #fff3cd)',
          borderRadius: 4,
          color: 'var(--color-warning)',
        }}
      >
        ⚠️ White-label branding is available on the Enterprise plan only.
      </div>
    )
  }

  const handleLogoUpload = async (file: File) => {
    setUploading(true)
    try {
      const url = await onUploadLogo(file)
      onUpdate({ logoUrl: url })
    } finally {
      setUploading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Logo upload */}
      <div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontWeight: 500 }}>Dashboard Logo</span>
          <div
            style={{
              border: '2px dashed var(--border-color)',
              borderRadius: 4,
              padding: 24,
              textAlign: 'center',
              cursor: 'pointer',
            }}
          >
            <input
              type="file"
              accept="image/*"
              onChange={(e) => e.target.files?.[0] && handleLogoUpload(e.target.files[0])}
              disabled={uploading}
              style={{ display: 'none' }}
              id="logo-upload"
            />
            <label
              htmlFor="logo-upload"
              style={{ cursor: 'pointer', display: 'block' }}
            >
              {config.logoUrl ? (
                <>
                  <img src={config.logoUrl} alt="Logo preview" style={{ maxHeight: 100, marginBottom: 8 }} />
                  <span className="subtle small">Click to replace</span>
                </>
              ) : (
                <>
                  <span style={{ display: 'block', marginBottom: 8 }}>📤 Click to upload logo</span>
                  <span className="subtle small">PNG or JPG, max 5MB</span>
                </>
              )}
            </label>
          </div>
        </label>
      </div>

      {/* Company name */}
      <div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontWeight: 500 }}>Company Name</span>
          <input
            type="text"
            value={config.companyName || ''}
            onChange={(e) => onUpdate({ companyName: e.target.value })}
            placeholder="Your Company Name"
          />
        </label>
      </div>

      {/* Colors */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontWeight: 500 }}>Primary Color</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type="color"
                value={config.primaryColor || '#0066cc'}
                onChange={(e) => onUpdate({ primaryColor: e.target.value })}
              />
              <input
                type="text"
                value={config.primaryColor || '#0066cc'}
                onChange={(e) => onUpdate({ primaryColor: e.target.value })}
                placeholder="#0066cc"
                style={{ flex: 1 }}
              />
            </div>
          </label>
        </div>
        <div>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontWeight: 500 }}>Secondary Color</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type="color"
                value={config.secondaryColor || '#00b386'}
                onChange={(e) => onUpdate({ secondaryColor: e.target.value })}
              />
              <input
                type="text"
                value={config.secondaryColor || '#00b386'}
                onChange={(e) => onUpdate({ secondaryColor: e.target.value })}
                placeholder="#00b386"
                style={{ flex: 1 }}
              />
            </div>
          </label>
        </div>
      </div>

      {/* Custom domain */}
      <div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontWeight: 500 }}>Custom Domain (CNAME)</span>
          <input
            type="text"
            value={config.customDomain || ''}
            onChange={(e) => onUpdate({ customDomain: e.target.value })}
            placeholder="memar.yourcompany.com"
          />
          <span className="subtle small">Point your CNAME to your MEMAR instance</span>
        </label>
      </div>

      {/* Hide branding */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          checked={config.hideNoweredByMemar || false}
          onChange={(e) => onUpdate({ hideNoweredByMemar: e.target.checked })}
        />
        <span>Hide "Powered by MEMAR" branding</span>
      </label>
    </div>
  )
}

/* ========== Webhook Manager ========== */

interface WebhookFormProps {
  webhooks: Webhook[]
  onAdd: (webhook: Webhook) => void
  onUpdate: (id: string, webhook: Partial<Webhook>) => void
  onDelete: (id: string) => void
  onTest: (id: string) => Promise<boolean>
}

const eventTypes = [
  'print.start',
  'print.end',
  'print.pause',
  'print.resume',
  'print.cancel',
  'print.error',
  'alert.triggered',
  'maintenance.due',
  'device.offline',
]

export const WebhookForm: React.FC<WebhookFormProps> = ({
  webhooks,
  onAdd,
  onUpdate,
  onDelete,
  onTest,
}) => {
  const [testing, setTesting] = useState<string | null>(null)

  const handleAddWebhook = () => {
    const newWebhook: Webhook = {
      id: `webhook-${Date.now()}`,
      url: '',
      events: [],
      enabled: true,
      retryPolicy: {
        maxRetries: 3,
        backoffMs: 1000,
      },
    }
    onAdd(newWebhook)
  }

  const handleTest = async (id: string) => {
    setTesting(id)
    try {
      await onTest(id)
    } finally {
      setTesting(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <button onClick={handleAddWebhook} style={{ alignSelf: 'flex-start', padding: '8px 16px' }}>
        ➕ Add Webhook
      </button>

      {webhooks.map((webhook) => (
        <div
          key={webhook.id}
          style={{
            border: '1px solid var(--border-color)',
            borderRadius: 4,
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          {/* URL and enable */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500 }}>Webhook URL</span>
                <input
                  type="url"
                  value={webhook.url}
                  onChange={(e) => onUpdate(webhook.id, { url: e.target.value })}
                  placeholder="https://your-server.com/webhook"
                />
              </label>
            </div>
            <div style={{ display: 'flex', gap: 8, paddingTop: 24 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <input
                  type="checkbox"
                  checked={webhook.enabled}
                  onChange={(e) => onUpdate(webhook.id, { enabled: e.target.checked })}
                />
                <span style={{ fontSize: '0.9rem' }}>Enabled</span>
              </label>
              <button
                onClick={() => onDelete(webhook.id)}
                style={{
                  padding: '4px 8px',
                  fontSize: '0.85rem',
                  background: 'var(--color-danger)',
                  color: 'white',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                Delete
              </button>
            </div>
          </div>

          {/* Events */}
          <div>
            <span style={{ fontWeight: 500, fontSize: '0.9rem', display: 'block', marginBottom: 8 }}>
              Subscribe to Events
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
              {eventTypes.map((event) => (
                <label key={event} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.9rem' }}>
                  <input
                    type="checkbox"
                    checked={webhook.events.includes(event)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        onUpdate(webhook.id, { events: [...webhook.events, event] })
                      } else {
                        onUpdate(webhook.id, { events: webhook.events.filter((ev) => ev !== event) })
                      }
                    }}
                  />
                  <span>{event}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Retry policy */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500, fontSize: '0.9rem' }}>Max Retries</span>
                <input
                  type="number"
                  min="0"
                  max="10"
                  value={webhook.retryPolicy.maxRetries}
                  onChange={(e) =>
                    onUpdate(webhook.id, {
                      retryPolicy: {
                        ...webhook.retryPolicy,
                        maxRetries: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </div>
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500, fontSize: '0.9rem' }}>Backoff (ms)</span>
                <input
                  type="number"
                  min="100"
                  step="100"
                  value={webhook.retryPolicy.backoffMs}
                  onChange={(e) =>
                    onUpdate(webhook.id, {
                      retryPolicy: {
                        ...webhook.retryPolicy,
                        backoffMs: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </div>
          </div>

          {/* Test button */}
          <button
            onClick={() => handleTest(webhook.id)}
            disabled={testing === webhook.id || !webhook.enabled}
            style={{ alignSelf: 'flex-start', padding: '6px 12px', fontSize: '0.9rem' }}
          >
            {testing === webhook.id ? '⏳ Testing...' : '📤 Test Webhook'}
          </button>
        </div>
      ))}
    </div>
  )
}

/* ========== Analytics Configuration ========== */

interface AnalyticsFormProps {
  config: AnalyticsConfig
  onUpdate: (config: Partial<AnalyticsConfig>) => void
  onExport: (format: 'csv' | 'pdf') => Promise<Blob>
}

export const AnalyticsForm: React.FC<AnalyticsFormProps> = ({ config, onUpdate, onExport }) => {
  const [exporting, setExporting] = useState<'csv' | 'pdf' | null>(null)

  const handleExport = async (format: 'csv' | 'pdf') => {
    setExporting(format)
    try {
      const blob = await onExport(format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `analytics.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setExporting(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Enable analytics */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          checked={config.enabled}
          onChange={(e) => onUpdate({ enabled: e.target.checked })}
        />
        <span>Enable Analytics Collection</span>
      </label>

      {config.enabled && (
        <>
          {/* OEE Categories */}
          <div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontWeight: 500 }}>OEE Downtime Categories (one per line)</span>
              <textarea
                value={config.oeeCategories.join('\n')}
                onChange={(e) => onUpdate({ oeeCategories: e.target.value.split('\n').filter((x) => x.trim()) })}
                rows={4}
                placeholder="Planned Maintenance&#10;Unplanned Downtime&#10;Material Change&#10;Setup Time"
                style={{ fontFamily: 'monospace', fontSize: '0.9rem' }}
              />
            </label>
          </div>

          {/* Cost tracking */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500 }}>Material Cost per kg</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={config.materialCostPerKg}
                  onChange={(e) => onUpdate({ materialCostPerKg: Number(e.target.value) })}
                  placeholder="15.50"
                />
              </label>
            </div>
            <div>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontWeight: 500 }}>Energy Cost per kWh</span>
                <input
                  type="number"
                  min="0"
                  step="0.001"
                  value={config.energyCostPerKwh}
                  onChange={(e) => onUpdate({ energyCostPerKwh: Number(e.target.value) })}
                  placeholder="0.14"
                />
              </label>
            </div>
          </div>

          {/* Data retention */}
          <div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontWeight: 500 }}>Data Retention (days)</span>
              <input
                type="number"
                min="1"
                value={config.dataRetentionDays}
                onChange={(e) => onUpdate({ dataRetentionDays: Number(e.target.value) })}
                placeholder="365"
              />
              <span className="subtle small">How long to keep analytics data before archiving</span>
            </label>
          </div>

          {/* Telemetry */}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="checkbox"
              checked={config.collectTelemetry}
              onChange={(e) => onUpdate({ collectTelemetry: e.target.checked })}
            />
            <span>Collect usage telemetry for product improvement</span>
          </label>

          {/* Export buttons */}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => handleExport('csv')}
              disabled={exporting !== null}
              style={{ padding: '8px 16px' }}
            >
              {exporting === 'csv' ? '⏳' : '📥'} Export CSV
            </button>
            <button
              onClick={() => handleExport('pdf')}
              disabled={exporting !== null}
              style={{ padding: '8px 16px' }}
            >
              {exporting === 'pdf' ? '⏳' : '📥'} Export PDF
            </button>
          </div>
        </>
      )}
    </div>
  )
}

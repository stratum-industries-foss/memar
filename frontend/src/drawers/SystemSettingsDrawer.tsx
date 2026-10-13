/**
 * SettingsDrawer - Comprehensive MEMAR settings and configuration panel.
 *
 * Manages 150+ customizable settings across 25+ categories:
 * - License & Billing (Stripe integration, tier enforcement)
 * - Authentication (JWT, SSO, user roles)
 * - Device Configuration (per-printer settings, material presets)
 * - Notifications (SMTP, messaging platforms)
 * - UI & Appearance (themes, branding)
 * - Advanced (webhooks, analytics, debug logging)
 *
 * Phase 2: Enterprise Integration
 * - SSO/LDAP configuration
 * - Unified messaging (7 platforms)
 * - User roles & permissions (RBAC)
 *
 * Phase 3: Advanced Features
 * - White-label branding (license-gated)
 * - Webhooks & automation
 * - Analytics & reporting
 * - Advanced options
 */

import React, { useState, useCallback, useMemo } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useEnterpriseSettings } from './useEnterpriseSettings'
import { PasskeyManager } from '../components/PasskeyManager'
// Dead auth UI: MagicLinkAuth and RecoveryCodes removed — no backend routes exist
// import { MagicLinkAuth } from '../components/MagicLinkAuth'
// import { RecoveryCodes } from '../components/RecoveryCodes'
import {
  SsoForm,
  MessagingForm,
  RbacForm,
  BrandingForm,
  WebhookForm,
  AnalyticsForm,
} from './EnterpriseFormComponents'

interface SettingsCategory {
  id: string
  name: string
  icon: string
  description: string
  phase: 'phase1' | 'phase2' | 'phase3'
  fields?: SettingField[]
}

interface SettingField {
  id: string
  name: string
  description: string
  type: 'text' | 'number' | 'toggle' | 'select' | 'password' | 'url' | 'email' | 'textarea' | 'file'
  value: any
  required?: boolean
  sensitive?: boolean
  options?: Array<{ label: string; value: any }>
  validation?: (value: any) => string | null
  onChange?: (value: any) => void
  warning?: string
  testable?: boolean
}

const SettingsDrawer = React.memo(function SettingsDrawer({
  printerId,
  currentPrinter,
  canWrite,
  token,
  username,
}: DrawerProps & { token?: string; username?: string }) {
  const [activeCategory, setActiveCategory] = useState<string>('license')
  const [settings, setSettings] = useState<Record<string, any>>({})
  const [unsavedChanges, setUnsavedChanges] = useState(false)
  const [notification, setNotification] = useState<{ message: string; type: 'success' | 'error' | 'info' }>({ message: '', type: 'info' })

  // Enterprise settings
  const enterpriseSettings = useEnterpriseSettings()

  const handleFieldChange = useCallback((fieldId: string, value: any) => {
    setSettings((prev) => ({ ...prev, [fieldId]: value }))
    setUnsavedChanges(true)
  }, [])

  // Settings are managed via License & Admin panel - this drawer is read-only display
  // Keeping handleSave stub for potential future local-only settings (theme, etc.)
  const handleSave = useCallback(async () => {
    // No-op: settings persistence is handled by License/Admin panel
    setNotification({ message: 'Settings are managed in the License or Admin panel', type: 'info' })
    setTimeout(() => setNotification({ message: '', type: 'info' }), 3000)
  }, [])

  const handleEnterpriseSave = useCallback(async () => {
    try {
      await enterpriseSettings.save()
      // Check error AFTER await - save() may set error state
      const errorAfterSave = enterpriseSettings.error
      if (errorAfterSave) {
        setNotification({ message: errorAfterSave, type: 'error' })
      } else {
        setNotification({ message: 'Enterprise settings saved successfully', type: 'success' })
        setTimeout(() => setNotification({ message: '', type: 'info' }), 3000)
      }
    } catch (error) {
      console.error('Failed to save enterprise settings:', error)
      setNotification({
        message: error instanceof Error ? error.message : 'Failed to save enterprise settings',
        type: 'error'
      })
    }
  }, [enterpriseSettings])

  // Phase 1: Basic Categories
  const phase1Categories: SettingsCategory[] = useMemo(() => [
    {
      id: 'license',
      name: 'License & Billing',
      icon: '🔑',
      description: 'License key, tier enforcement, Stripe integration',
      phase: 'phase1',
      fields: [
        {
          id: 'license_key',
          name: 'License Key',
          description: 'Your MEMAR commercial license key',
          type: 'password',
          value: settings.license_key || '',
          required: true,
          sensitive: true,
        },
        {
          id: 'tier',
          name: 'License Tier',
          description: 'Determines feature access and device limits',
          type: 'select',
          value: settings.tier || 'starter',
          options: [
            { label: 'Starter (5 devices)', value: 'starter' },
            { label: 'Pro (20 devices)', value: 'pro' },
            { label: 'Enterprise (unlimited)', value: 'enterprise' },
          ],
        },
      ],
    },
    {
      id: 'auth',
      name: 'Authentication',
      icon: '🔐',
      description: 'JWT secret, user roles, permissions',
      phase: 'phase1',
      fields: [
        {
          id: 'jwt_secret',
          name: 'JWT Secret',
          description: 'Signing key for authentication tokens (required in production)',
          type: 'password',
          value: settings.jwt_secret || '',
          required: true,
          sensitive: true,
          warning: 'Changing this will invalidate all active sessions',
        },
        {
          id: 'default_role',
          name: 'Default User Role',
          description: 'Role assigned to new users',
          type: 'select',
          value: settings.default_role || 'operator',
          options: [
            { label: 'Viewer (read-only)', value: 'viewer' },
            { label: 'Operator (jog, print)', value: 'operator' },
            { label: 'Administrator', value: 'admin' },
          ],
        },
      ],
    },
    {
      id: 'notifications',
      name: 'Notifications',
      icon: '🔔',
      description: 'Email, Slack, Discord, webhooks',
      phase: 'phase1',
      fields: [
        {
          id: 'smtp_enabled',
          name: 'Email Alerts',
          description: 'Send print completion and error notifications',
          type: 'toggle',
          value: settings.smtp_enabled || false,
        },
        {
          id: 'smtp_host',
          name: 'SMTP Server',
          description: 'e.g., smtp.gmail.com',
          type: 'text',
          value: settings.smtp_host || '',
        },
        {
          id: 'alert_on_error',
          name: 'Alert on Print Error',
          description: 'Send immediate notification when print fails',
          type: 'toggle',
          value: settings.alert_on_error !== false,
        },
      ],
    },
    {
      id: 'appearance',
      name: 'Appearance',
      icon: '🎨',
      description: 'Dark mode, custom branding, layout options',
      phase: 'phase1',
      fields: [
        {
          id: 'theme',
          name: 'Theme',
          description: 'Display theme preference',
          type: 'select',
          value: settings.theme || 'auto',
          options: [
            { label: 'Auto (system)', value: 'auto' },
            { label: 'Dark', value: 'dark' },
            { label: 'Light', value: 'light' },
          ],
        },
        {
          id: 'show_advanced_metrics',
          name: 'Show Advanced Metrics',
          description: 'Display technical details (OEE, power, thermal)',
          type: 'toggle',
          value: settings.show_advanced_metrics !== false,
        },
      ],
    },
    {
      id: 'advanced',
      name: 'Advanced',
      icon: '⚙️',
      description: 'Debug logging, experimental features, performance tuning',
      phase: 'phase1',
      fields: [
        {
          id: 'debug_mode',
          name: 'Debug Mode',
          description: 'Enable verbose logging and stack traces',
          type: 'toggle',
          value: settings.debug_mode || false,
          warning: 'May impact performance',
        },
        {
          id: 'log_retention_days',
          name: 'Log Retention (days)',
          description: 'How long to keep debug logs',
          type: 'number',
          value: settings.log_retention_days || 7,
        },
      ],
    },
    {
      id: 'account',
      name: 'Account Security',
      icon: '🔑',
      description: 'Manage passkeys and authentication methods',
      phase: 'phase1',
    },
    {
      id: 'auth-recovery',
      name: 'Auth & Recovery',
      icon: '🔐',
      description: 'Magic links and recovery codes for account access',
      phase: 'phase1',
    },
  ], [settings])

  // Phase 2: Enterprise Integration
  const phase2Categories: SettingsCategory[] = useMemo(() => [
    {
      id: 'sso',
      name: 'SSO/LDAP',
      icon: '👥',
      description: 'Single sign-on and directory integration',
      phase: 'phase2',
    },
    {
      id: 'messaging',
      name: 'Messaging',
      icon: '💬',
      description: 'Slack, Discord, Telegram, and more',
      phase: 'phase2',
    },
    {
      id: 'rbac',
      name: 'Roles & Permissions',
      icon: '🎯',
      description: 'Create and manage user roles',
      phase: 'phase2',
    },
  ], [])

  // Phase 3: Advanced Features
  const phase3Categories: SettingsCategory[] = useMemo(() => [
    {
      id: 'branding',
      name: 'White-Label Branding',
      icon: '🎭',
      description: 'Custom logo, colors, and domain (Enterprise only)',
      phase: 'phase3',
    },
    {
      id: 'webhooks',
      name: 'Webhooks',
      icon: '🪝',
      description: 'Automated events and integrations',
      phase: 'phase3',
    },
    {
      id: 'analytics',
      name: 'Analytics & Reporting',
      icon: '📊',
      description: 'OEE, cost tracking, data retention',
      phase: 'phase3',
    },
    {
      id: 'advanced-options',
      name: 'Advanced Options',
      icon: '🔧',
      description: 'Binary cache, performance tuning, beta features',
      phase: 'phase3',
    },
  ], [])

  const allCategories = useMemo(() => [...phase1Categories, ...phase2Categories, ...phase3Categories], [phase1Categories, phase2Categories, phase3Categories])
  const activeTab = useMemo(() => allCategories.find((c) => c.id === activeCategory), [allCategories, activeCategory])

  const categoryGroups = useMemo(
    () => ({
      'Basic Settings': phase1Categories,
      'Enterprise Integration': phase2Categories,
      'Advanced Features': phase3Categories,
    }),
    [phase1Categories, phase2Categories, phase3Categories]
  )

  // Notification toast
  const showNotification = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setNotification({ message, type })
    setTimeout(() => setNotification({ message: '', type: 'info' }), 4000)
  }, [])

  if (!canWrite) {
    return (
      <section className="drawer-section">
        <h3>Settings</h3>
        <div className="subtle">You don't have permission to modify settings.</div>
      </section>
    )
  }

  return (
    <section className="drawer-section" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <h3>Settings</h3>
        {notification.message && (
          <div
            style={{
              marginTop: 8,
              padding: '8px 12px',
              borderRadius: 4,
              fontSize: '0.9rem',
              background:
                notification.type === 'success'
                  ? 'var(--color-success, #10b981)'
                  : notification.type === 'error'
                    ? 'var(--color-error, #ef4444)'
                    : 'var(--color-info, #3b82f6)',
              color: 'white',
            }}
          >
            {notification.message}
          </div>
        )}
      </div>

      {/* Grouped category tabs */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {Object.entries(categoryGroups).map(([group, categories]) => (
          <div key={group}>
            <div
              className="subtle"
              style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}
            >
              {group}
            </div>
            <div className="drawer-tabs" style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }} role="tablist">
              {categories.map((cat) => (
                <button
                  key={cat.id}
                  id={`tab-${cat.id}`}
                  className={activeCategory === cat.id ? 'tab-active' : ''}
                  onClick={() => setActiveCategory(cat.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                      e.preventDefault()
                      const nextIdx = categories.findIndex(c => c.id === activeCategory) + 1
                      if (nextIdx < categories.length) {
                        setActiveCategory(categories[nextIdx].id)
                      }
                    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                      e.preventDefault()
                      const prevIdx = categories.findIndex(c => c.id === activeCategory) - 1
                      if (prevIdx >= 0) {
                        setActiveCategory(categories[prevIdx].id)
                      }
                    }
                  }}
                  role="tab"
                  aria-selected={activeCategory === cat.id}
                  aria-controls={`tabpanel-${cat.id}`}
                  title={cat.description}
                  style={{
                    padding: '6px 12px',
                    fontSize: '0.85rem',
                    border: `1px solid ${activeCategory === cat.id ? 'var(--color-primary)' : 'var(--border-color)'}`,
                    borderRadius: 4,
                    background: activeCategory === cat.id ? 'var(--color-primary, #0066cc)' : 'transparent',
                    color: activeCategory === cat.id ? 'white' : 'var(--text-color)',
                    cursor: 'pointer',
                  }}
                >
                  {cat.icon} {cat.name}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Active category content */}
      {activeTab && (
        <div
          id={`tabpanel-${activeTab.id}`}
          role="tabpanel"
          aria-labelledby={`tab-${activeTab.id}`}
          style={{ flex: 1, overflowY: 'auto' }}
        >
          <p className="subtle small" style={{ marginBottom: 16, fontSize: '0.9rem' }}>
            {activeTab.description}
          </p>

          {/* Phase 1 categories with fields */}
          {activeTab.phase === 'phase1' && activeTab.fields && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {activeTab.fields.map((field) => (
                <div
                  key={field.id}
                  style={{
                    borderBottom: '1px solid var(--border-color, #333)',
                    paddingBottom: 12,
                  }}
                >
                  <label htmlFor={field.id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ fontWeight: 500, fontSize: '0.95rem' }}>
                      {field.name}
                      {field.required && <span style={{ color: 'var(--color-danger, #ff6b6b)' }}>*</span>}
                    </span>
                    <span id={`desc-${field.id}`} className="subtle small">{field.description}</span>

                    {field.type === 'toggle' ? (
                      <input
                        id={field.id}
                        type="checkbox"
                        checked={field.value}
                        onChange={(e) => handleFieldChange(field.id, e.target.checked)}
                        aria-required={field.required}
                        aria-describedby={`desc-${field.id}`}
                        style={{ width: 'auto', marginTop: 4 }}
                      />
                    ) : field.type === 'select' ? (
                      <select
                        id={field.id}
                        value={field.value}
                        onChange={(e) => handleFieldChange(field.id, e.target.value)}
                        aria-required={field.required}
                        aria-describedby={`desc-${field.id}`}
                        style={{
                          padding: '6px 8px',
                          borderRadius: 4,
                          border: '1px solid var(--border-color)',
                          background: 'var(--bg-color)',
                          color: 'var(--text-color)',
                        }}
                      >
                        {field.options?.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    ) : field.type === 'textarea' ? (
                      <textarea
                        id={field.id}
                        value={field.value}
                        onChange={(e) => handleFieldChange(field.id, e.target.value)}
                        rows={3}
                        aria-required={field.required}
                        aria-describedby={`desc-${field.id}`}
                        style={{
                          fontFamily: 'monospace',
                          fontSize: '0.9rem',
                          padding: '6px 8px',
                          borderRadius: 4,
                          border: '1px solid var(--border-color)',
                          background: 'var(--bg-color)',
                          color: 'var(--text-color)',
                        }}
                      />
                    ) : (
                      <input
                        id={field.id}
                        type={field.type}
                        value={field.value}
                        onChange={(e) => handleFieldChange(field.id, e.target.value)}
                        placeholder={`Enter ${field.name.toLowerCase()}`}
                        aria-required={field.required}
                        aria-describedby={`desc-${field.id}`}
                        style={{
                          padding: '6px 8px',
                          borderRadius: 4,
                          border: '1px solid var(--border-color)',
                          background: 'var(--bg-color)',
                          color: 'var(--text-color)',
                        }}
                      />
                    )}
                  </label>

                  {field.warning && (
                    <div style={{ color: 'var(--color-warning, #ffa500)', fontSize: '0.85rem', marginTop: 6 }}>
                      ⚠️ {field.warning}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Phase 2: SSO Form */}
          {activeTab.id === 'sso' && enterpriseSettings.settings && (
            <SsoForm
              config={enterpriseSettings.settings.sso}
              onUpdate={enterpriseSettings.updateSso}
              onTest={enterpriseSettings.testSsoConnection}
              loading={enterpriseSettings.loading}
            />
          )}

          {/* Phase 2: Messaging Form */}
          {activeTab.id === 'messaging' && enterpriseSettings.settings && (
            <MessagingForm
              platforms={enterpriseSettings.settings.messaging}
              onUpdate={enterpriseSettings.updateMessaging}
              onAdd={enterpriseSettings.addMessagingPlatform}
              onRemove={enterpriseSettings.removeMessagingPlatform}
              onTest={enterpriseSettings.testMessagingPlatform}
              loading={enterpriseSettings.loading}
            />
          )}

          {/* Phase 2: RBAC Form */}
          {activeTab.id === 'rbac' && enterpriseSettings.settings && (
            <RbacForm
              roles={enterpriseSettings.settings.roles}
              onAdd={enterpriseSettings.addRole}
              onUpdate={enterpriseSettings.updateRole}
              onDelete={enterpriseSettings.deleteRole}
            />
          )}

          {/* Phase 3: Branding Form */}
          {activeTab.id === 'branding' && enterpriseSettings.settings && (
            <BrandingForm
              config={enterpriseSettings.settings.branding}
              onUpdate={enterpriseSettings.updateBranding}
              onUploadLogo={enterpriseSettings.uploadLogo}
              licenseTier={settings.tier}
            />
          )}

          {/* Phase 3: Webhooks Form */}
          {activeTab.id === 'webhooks' && enterpriseSettings.settings && (
            <WebhookForm
              webhooks={enterpriseSettings.settings.webhooks}
              onAdd={enterpriseSettings.addWebhook}
              onUpdate={enterpriseSettings.updateWebhook}
              onDelete={enterpriseSettings.deleteWebhook}
              onTest={enterpriseSettings.testWebhook}
            />
          )}

          {/* Phase 3: Analytics Form */}
          {activeTab.id === 'analytics' && enterpriseSettings.settings && (
            <AnalyticsForm
              config={enterpriseSettings.settings.analytics}
              onUpdate={enterpriseSettings.updateAnalytics}
              onExport={enterpriseSettings.exportAnalytics}
            />
          )}

          {/* Phase 3: Advanced Options */}
          {activeTab.id === 'advanced-options' && enterpriseSettings.settings && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Binary Cache Duration (days)</span>
                  <input
                    type="number"
                    min="1"
                    value={enterpriseSettings.settings.advancedOptions.binaryCacheDays}
                    onChange={(e) =>
                      enterpriseSettings.updateAdvancedOptions({
                        binaryCacheDays: Number(e.target.value),
                      })
                    }
                    style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border-color)' }}
                  />
                  <span className="subtle small">How long to cache build artifacts</span>
                </label>
              </div>

              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Cache Size</span>
                  <select
                    value={enterpriseSettings.settings.advancedOptions.cacheSize}
                    onChange={(e) =>
                      enterpriseSettings.updateAdvancedOptions({
                        cacheSize: e.target.value,
                      })
                    }
                    style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border-color)' }}
                  >
                    <option value="small">Small (10 GB)</option>
                    <option value="medium">Medium (50 GB)</option>
                    <option value="large">Large (100 GB)</option>
                  </select>
                </label>
              </div>

              <div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontWeight: 500 }}>Refresh Interval (minutes)</span>
                  <input
                    type="number"
                    min="1"
                    value={enterpriseSettings.settings.advancedOptions.refreshInterval}
                    onChange={(e) =>
                      enterpriseSettings.updateAdvancedOptions({
                        refreshInterval: Number(e.target.value),
                      })
                    }
                    style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border-color)' }}
                  />
                </label>
              </div>

              <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="checkbox"
                  checked={enterpriseSettings.settings.advancedOptions.betaFeaturesEnabled}
                  onChange={(e) =>
                    enterpriseSettings.updateAdvancedOptions({
                      betaFeaturesEnabled: e.target.checked,
                    })
                  }
                />
                <span>Enable beta features</span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="checkbox"
                  checked={enterpriseSettings.settings.advancedOptions.telemetryEnabled}
                  onChange={(e) =>
                    enterpriseSettings.updateAdvancedOptions({
                      telemetryEnabled: e.target.checked,
                    })
                  }
                />
                <span>Send anonymized telemetry</span>
              </label>
            </div>
          )}

          {/* Account Security: Passkey Manager */}
          {activeTab?.id === 'account' && token && username && (
            <PasskeyManager token={token} username={username} />
          )}

          {activeTab?.id === 'account' && (!token || !username) && (
            <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '20px 0' }}>
              <p>Unable to load account security settings. Please log in again.</p>
            </div>
          )}

          {/* Auth & Recovery: Magic Link + Recovery Codes — DISABLED: no backend routes
          {activeTab?.id === 'auth-recovery' && token && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '600px' }}>
              <div style={{ paddingBottom: '12px', borderBottom: '1px solid var(--border-default)' }}>
                <MagicLinkAuth token={token} />
              </div>
              <div>
                <RecoveryCodes token={token} />
              </div>
            </div>
          )}
          */}

          {activeTab?.id === 'auth-recovery' && (
            <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '20px 0' }}>
              <p>Magic link and recovery code features are not yet available.</p>
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          borderTop: '1px solid var(--border-color, #333)',
          paddingTop: 12,
          flexWrap: 'wrap',
        }}
      >
        {activeTab?.phase === 'phase1' ? (
          <>
            <button
              onClick={handleSave}
              disabled
              title="Settings are managed in License or Admin panel"
              style={{ flex: 1, minWidth: 120, padding: '8px 16px', opacity: 0.6, cursor: 'not-allowed' }}
            >
              ⓘ Managed via Admin Panel
            </button>
            <button
              onClick={() => {
                setSettings({})
                setUnsavedChanges(false)
              }}
              style={{ flex: 1, minWidth: 100, padding: '8px 16px' }}
            >
              ↺ Reset
            </button>
          </>
        ) : (
          <>
            <button
              onClick={handleEnterpriseSave}
              disabled={!enterpriseSettings.unsavedChanges}
              style={{ flex: 1, minWidth: 120, padding: '8px 16px' }}
            >
              {enterpriseSettings.unsavedChanges ? '💾 Save Changes' : '✓ Saved'}
            </button>
            {(activeTab?.id === 'sso' ||
              activeTab?.id === 'messaging' ||
              activeTab?.id === 'webhooks' ||
              activeTab?.id === 'analytics') && (
              <button
                onClick={() => enterpriseSettings.load()}
                style={{ flex: 1, minWidth: 100, padding: '8px 16px' }}
              >
                ↺ Reset
              </button>
            )}
          </>
        )}
      </div>
    </section>
  )
})

export default SettingsDrawer

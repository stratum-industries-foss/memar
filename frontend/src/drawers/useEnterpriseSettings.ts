/**
 * useEnterpriseSettings — State management for Phase 2-3 enterprise features
 *
 * Manages:
 * - SSO/LDAP configuration
 * - Messaging platform integrations
 * - User roles and permissions (RBAC)
 * - White-label branding
 * - Webhooks and automation
 * - Analytics and reporting settings
 */

import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

export interface SsoConfig {
  enabled: boolean
  provider: 'oidc' | 'ldap' | 'saml'
  discoveryUrl?: string
  clientId?: string
  clientSecret?: string
  ldapHost?: string
  ldapPort?: number
  ldapBaseDn?: string
  ldapSearchFilter?: string
  ldapBindDn?: string
  ldapBindPassword?: string
  autoSyncRoles: boolean
}

export interface MessagingPlatform {
  id: string
  type: 'telegram' | 'slack' | 'discord' | 'mattermost' | 'matrix' | 'ntfy' | 'webhook'
  enabled: boolean
  config: Record<string, string>
  testable?: boolean
}

export interface UserRole {
  id: string
  name: string
  description: string
  permissions: Record<string, boolean>
  isCustom: boolean
}

export interface BrandingConfig {
  logoUrl?: string
  companyName?: string
  primaryColor?: string
  secondaryColor?: string
  hideNoweredByMemar?: boolean
  customDomain?: string
  emailTemplate?: string
  smsTemplate?: string
}

export interface Webhook {
  id: string
  url: string
  events: string[]
  enabled: boolean
  retryPolicy: {
    maxRetries: number
    backoffMs: number
  }
}

export interface AnalyticsConfig {
  enabled: boolean
  oeeCategories: string[]
  materialCostPerKg: number
  energyCostPerKwh: number
  dataRetentionDays: number
  collectTelemetry: boolean
}

export interface EnterpriseSettings {
  sso: SsoConfig
  messaging: MessagingPlatform[]
  roles: UserRole[]
  branding: BrandingConfig
  webhooks: Webhook[]
  analytics: AnalyticsConfig
  advancedOptions: {
    binaryCacheDays: number
    cacheSize: string
    refreshInterval: number
    betaFeaturesEnabled: boolean
    telemetryEnabled: boolean
  }
}

export interface EnterpriseSettingsState {
  settings: EnterpriseSettings | null
  loading: boolean
  error: string | null
  unsavedChanges: boolean
  message: string

  // SSO methods
  updateSso: (config: Partial<SsoConfig>) => void
  testSsoConnection: () => Promise<boolean>

  // Messaging methods
  updateMessaging: (index: number, platform: Partial<MessagingPlatform>) => void
  addMessagingPlatform: (type: MessagingPlatform['type']) => void
  removeMessagingPlatform: (index: number) => void
  testMessagingPlatform: (index: number) => Promise<boolean>

  // Role methods
  addRole: (role: UserRole) => void
  updateRole: (id: string, role: Partial<UserRole>) => void
  deleteRole: (id: string) => void

  // Branding methods
  updateBranding: (config: Partial<BrandingConfig>) => void
  uploadLogo: (file: File) => Promise<string>

  // Webhook methods
  addWebhook: (webhook: Webhook) => void
  updateWebhook: (id: string, webhook: Partial<Webhook>) => void
  deleteWebhook: (id: string) => void
  testWebhook: (id: string) => Promise<boolean>

  // Analytics methods
  updateAnalytics: (config: Partial<AnalyticsConfig>) => void
  exportAnalytics: (format: 'csv' | 'pdf') => Promise<Blob>

  // Advanced options
  updateAdvancedOptions: (options: Partial<EnterpriseSettings['advancedOptions']>) => void

  // Save/load
  save: () => Promise<void>
  load: () => Promise<void>
}

export function useEnterpriseSettings(fetcher: typeof apiFetch = apiFetch): EnterpriseSettingsState {
  const [settings, setSettings] = useState<EnterpriseSettings | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unsavedChanges, setUnsavedChanges] = useState(false)
  const [message, setMessage] = useState('')

  // Load settings on mount
  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    try {
      const resp = await fetcher('/api/settings/enterprise')
      if (resp.ok) {
        const data = await resp.json()
        setSettings(data)
        setError(null)
      } else {
        setError('Failed to load enterprise settings')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }

  async function save() {
    if (!settings) return
    try {
      const resp = await fetcher('/api/settings/enterprise', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      if (resp.ok) {
        setMessage('Settings saved successfully')
        setUnsavedChanges(false)
      } else {
        setError('Failed to save settings')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings')
    }
  }

  const updateSso = (config: Partial<SsoConfig>) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, sso: { ...prev.sso, ...config } } : null)
    setUnsavedChanges(true)
  }

  const testSsoConnection = async () => {
    if (!settings) return false
    try {
      const resp = await fetcher('/api/settings/sso/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings.sso),
      })
      const result = await resp.json()
      setMessage(result.connected ? 'SSO connection successful' : `Failed: ${result.error}`)
      return result.connected
    } catch {
      setMessage('Failed to test SSO connection')
      return false
    }
  }

  const updateMessaging = (index: number, platform: Partial<MessagingPlatform>) => {
    if (!settings) return
    const updated = [...settings.messaging]
    updated[index] = { ...updated[index], ...platform }
    setSettings(prev => prev ? { ...prev, messaging: updated } : null)
    setUnsavedChanges(true)
  }

  const addMessagingPlatform = (type: MessagingPlatform['type']) => {
    if (!settings) return
    const newPlatform: MessagingPlatform = {
      id: `${type}-${Date.now()}`,
      type,
      enabled: false,
      config: {},
    }
    setSettings(prev => prev ? { ...prev, messaging: [...prev.messaging, newPlatform] } : null)
    setUnsavedChanges(true)
  }

  const removeMessagingPlatform = (index: number) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, messaging: prev.messaging.filter((_, i) => i !== index) } : null)
    setUnsavedChanges(true)
  }

  const testMessagingPlatform = async (index: number) => {
    if (!settings) return false
    try {
      const resp = await fetcher('/api/settings/messaging/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings.messaging[index]),
      })
      const result = await resp.json()
      setMessage(result.success ? `${settings.messaging[index].type} test successful` : `Failed: ${result.error}`)
      return result.success
    } catch {
      setMessage('Failed to test messaging platform')
      return false
    }
  }

  const addRole = (role: UserRole) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, roles: [...prev.roles, role] } : null)
    setUnsavedChanges(true)
  }

  const updateRole = (id: string, role: Partial<UserRole>) => {
    if (!settings) return
    const updated = settings.roles.map(r => r.id === id ? { ...r, ...role } : r)
    setSettings(prev => prev ? { ...prev, roles: updated } : null)
    setUnsavedChanges(true)
  }

  const deleteRole = (id: string) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, roles: prev.roles.filter(r => r.id !== id) } : null)
    setUnsavedChanges(true)
  }

  const updateBranding = (config: Partial<BrandingConfig>) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, branding: { ...prev.branding, ...config } } : null)
    setUnsavedChanges(true)
  }

  const uploadLogo = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const resp = await fetcher('/api/settings/branding/upload-logo', {
        method: 'POST',
        body: formData,
      })
      if (resp.ok) {
        const { url } = await resp.json()
        updateBranding({ logoUrl: url })
        setMessage('Logo uploaded successfully')
        return url
      }
    } catch {
      setMessage('Failed to upload logo')
    }
    return ''
  }

  const addWebhook = (webhook: Webhook) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, webhooks: [...prev.webhooks, webhook] } : null)
    setUnsavedChanges(true)
  }

  const updateWebhook = (id: string, webhook: Partial<Webhook>) => {
    if (!settings) return
    const updated = settings.webhooks.map(w => w.id === id ? { ...w, ...webhook } : w)
    setSettings(prev => prev ? { ...prev, webhooks: updated } : null)
    setUnsavedChanges(true)
  }

  const deleteWebhook = (id: string) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, webhooks: prev.webhooks.filter(w => w.id !== id) } : null)
    setUnsavedChanges(true)
  }

  const testWebhook = async (id: string) => {
    try {
      const webhook = settings?.webhooks.find(w => w.id === id)
      if (!webhook) return false
      const resp = await fetcher(`/api/settings/webhooks/${id}/test`, { method: 'POST' })
      const result = await resp.json()
      setMessage(result.success ? 'Webhook test successful' : `Failed: ${result.error}`)
      return result.success
    } catch {
      setMessage('Failed to test webhook')
      return false
    }
  }

  const updateAnalytics = (config: Partial<AnalyticsConfig>) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, analytics: { ...prev.analytics, ...config } } : null)
    setUnsavedChanges(true)
  }

  const exportAnalytics = async (format: 'csv' | 'pdf') => {
    try {
      const resp = await fetcher(`/api/settings/analytics/export?format=${format}`)
      return await resp.blob()
    } catch {
      setMessage('Failed to export analytics')
      throw new Error('Export failed')
    }
  }

  const updateAdvancedOptions = (options: Partial<EnterpriseSettings['advancedOptions']>) => {
    if (!settings) return
    setSettings(prev => prev ? { ...prev, advancedOptions: { ...prev.advancedOptions, ...options } } : null)
    setUnsavedChanges(true)
  }

  return {
    settings,
    loading,
    error,
    unsavedChanges,
    message,
    updateSso,
    testSsoConnection,
    updateMessaging,
    addMessagingPlatform,
    removeMessagingPlatform,
    testMessagingPlatform,
    addRole,
    updateRole,
    deleteRole,
    updateBranding,
    uploadLogo,
    addWebhook,
    updateWebhook,
    deleteWebhook,
    testWebhook,
    updateAnalytics,
    exportAnalytics,
    updateAdvancedOptions,
    save,
    load,
  }
}

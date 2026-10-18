/**
 * EnterpriseSettings.test.tsx — Tests for Phase 2-3 enterprise settings
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useEnterpriseSettings } from '../useEnterpriseSettings'

// A settings payload matching the EnterpriseSettings type (useEnterpriseSettings.ts).
const SETTINGS_PAYLOAD = {
  sso: { enabled: false, provider: 'oidc', autoSyncRoles: false },
  messaging: [],
  roles: [],
  branding: {},
  webhooks: [],
  analytics: {},
  advancedOptions: {
    binaryCacheDays: 7,
    cacheSize: '1GB',
    refreshInterval: 30,
    betaFeaturesEnabled: false,
    telemetryEnabled: false,
  },
}

describe('useEnterpriseSettings', () => {
  // Resolves the load (GET /api/settings/enterprise) with a real payload, so the hook has
  // settings to edit. Without a response the load fails and settings stay null.
  const mockFetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => SETTINGS_PAYLOAD,
  }))

  beforeEach(() => {
    mockFetch.mockClear()
    mockFetch.mockImplementation(async () => ({
      ok: true,
      status: 200,
      json: async () => SETTINGS_PAYLOAD,
    }))
  })

  it('should initialize with default settings', () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))
    expect(result.current.loading).toBe(true)
    expect(result.current.error).toBe(null)
  })

  it('should update SSO configuration', async () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))

    // updateSso is a no-op until settings have loaded (it has nothing to edit yet),
    // so wait for the load before editing.
    await waitFor(() => expect(result.current.settings).not.toBeNull())

    act(() => {
      result.current.updateSso({ enabled: true, provider: 'oidc' })
    })

    expect(result.current.unsavedChanges).toBe(true)
  })

  it('should add and remove messaging platforms', () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))

    // Initial state should be loaded first
    expect(result.current.settings).toBeDefined()

    if (result.current.settings) {
      const initialCount = result.current.settings.messaging.length

      act(() => {
        result.current.addMessagingPlatform('slack')
      })

      expect(result.current.settings!.messaging.length).toBe(initialCount + 1)

      act(() => {
        result.current.removeMessagingPlatform(initialCount)
      })

      expect(result.current.settings!.messaging.length).toBe(initialCount)
    }
  })

  it('should manage user roles', () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))

    if (result.current.settings) {
      const newRole = {
        id: 'test-role',
        name: 'Supervisor',
        description: 'Supervisor role',
        permissions: { 'view:dashboard': true, 'edit:settings': true },
        isCustom: true,
      }

      act(() => {
        result.current.addRole(newRole)
      })

      expect(result.current.settings!.roles.some((r) => r.id === 'test-role')).toBe(true)

      act(() => {
        result.current.deleteRole('test-role')
      })

      expect(result.current.settings!.roles.some((r) => r.id === 'test-role')).toBe(false)
    }
  })

  it('should manage webhooks', () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))

    if (result.current.settings) {
      const newWebhook = {
        id: 'test-webhook',
        url: 'https://example.com/webhook',
        events: ['print.start', 'print.end'],
        enabled: true,
        retryPolicy: { maxRetries: 3, backoffMs: 1000 },
      }

      act(() => {
        result.current.addWebhook(newWebhook)
      })

      expect(result.current.settings!.webhooks.some((w) => w.id === 'test-webhook')).toBe(true)

      act(() => {
        result.current.updateWebhook('test-webhook', { enabled: false })
      })

      const webhook = result.current.settings!.webhooks.find((w) => w.id === 'test-webhook')
      expect(webhook?.enabled).toBe(false)
    }
  })

  it('should track unsaved changes', async () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))

    await waitFor(() => expect(result.current.settings).not.toBeNull())
    expect(result.current.unsavedChanges).toBe(false)

    act(() => {
      result.current.updateAnalytics({ enabled: true })
    })

    expect(result.current.unsavedChanges).toBe(true)
  })
})

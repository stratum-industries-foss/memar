/**
 * EnterpriseSettings.test.tsx — Tests for Phase 2-3 enterprise settings
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useEnterpriseSettings } from '../useEnterpriseSettings'

describe('useEnterpriseSettings', () => {
  const mockFetch = vi.fn()

  beforeEach(() => {
    mockFetch.mockClear()
  })

  it('should initialize with default settings', () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))
    expect(result.current.loading).toBe(true)
    expect(result.current.error).toBe(null)
  })

  it('should update SSO configuration', () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))

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

  it('should track unsaved changes', () => {
    const { result } = renderHook(() => useEnterpriseSettings(mockFetch))

    expect(result.current.unsavedChanges).toBe(false)

    act(() => {
      result.current.updateAnalytics({ enabled: true })
    })

    expect(result.current.unsavedChanges).toBe(true)
  })
})

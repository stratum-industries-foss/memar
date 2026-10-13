/**
 * useCoolantMetrics — Real-time coolant metrics polling
 *
 * Polls the coolant metrics endpoint at a configurable interval and manages
 * loading/error state. Supports one-shot reload and real-time updates via
 * WebSocket messages.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../api'

export interface CoolantMetrics {
  psi: number | null
  temperature_c: number | null
  status: 'active' | 'inactive' | 'error' | 'low' | 'unknown'
  flow_rate_lpm?: number | null
  chip_load_pct?: number | null
  pressure_bar?: number | null
  humidity_pct?: number | null
  last_updated?: string
}

export interface UseCoolantMetricsOptions {
  pollIntervalMs?: number
  onError?: (error: string) => void
}

export interface UseCoolantMetricsResult {
  /** Latest coolant metrics, or null if not yet loaded. */
  metrics: CoolantMetrics | null
  /** True while initial fetch is in progress. */
  loading: boolean
  /** Error message if last fetch failed. */
  error: string | undefined
  /** True if the endpoint responded with 404 (machine type doesn't support coolant). */
  unavailable: boolean
  /** Force a refresh from the server. */
  reload: () => Promise<void>
  /** Apply a real-time update from WebSocket without re-fetching. */
  applyRealtimeUpdate: (data: Partial<CoolantMetrics>) => void
}

/**
 * Hook for fetching and managing coolant metrics.
 *
 * Polls the `/api/printers/{printerId}/coolant/metrics` endpoint at a
 * configurable interval (default 5s). Tracks loading/error state and supports
 * real-time updates from WebSocket.
 *
 * @param printerId - Unique printer identifier
 * @param options - Configuration (poll interval, error callback)
 * @returns Metrics interface
 */
export function useCoolantMetrics(
  printerId: string | undefined,
  options: UseCoolantMetricsOptions = {},
): UseCoolantMetricsResult {
  const { pollIntervalMs = 5000, onError } = options

  const [metrics, setMetrics] = useState<CoolantMetrics | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [unavailable, setUnavailable] = useState(false)
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const reload = useCallback(async () => {
    if (!printerId) return

    setLoading(true)
    setError(undefined)

    try {
      const res = await apiFetch(`/api/printers/${printerId}/coolant/metrics`)

      if (res.status === 404) {
        // Machine type doesn't support coolant
        setUnavailable(true)
        setMetrics(null)
        return
      }

      if (!res.ok) {
        const msg = `Failed to load coolant metrics: ${res.statusText}`
        setError(msg)
        onError?.(msg)
        return
      }

      const data = (await res.json()) as CoolantMetrics
      setMetrics(data)
      setUnavailable(false)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(msg)
      onError?.(msg)
    } finally {
      setLoading(false)
    }
  }, [printerId, onError])

  const applyRealtimeUpdate = useCallback((data: Partial<CoolantMetrics>) => {
    setMetrics((prev) => (prev ? { ...prev, ...data } : data as CoolantMetrics))
  }, [])

  // Set up polling loop
  useEffect(() => {
    clearPollTimer()

    if (!printerId || unavailable) return

    // Initial load
    void reload()

    // Schedule periodic polls
    pollTimerRef.current = setInterval(() => {
      void reload()
    }, pollIntervalMs)

    return () => clearPollTimer()
  }, [printerId, unavailable, pollIntervalMs, reload, clearPollTimer])

  return {
    metrics,
    loading,
    error,
    unavailable,
    reload,
    applyRealtimeUpdate,
  }
}

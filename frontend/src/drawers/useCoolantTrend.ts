/**
 * useCoolantTrend — Time-series coolant metrics for trend analysis
 *
 * Fetches historical coolant data over a configurable window (default: last hour)
 * and calculates aggregate statistics (moving average, min, max).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../api'

export interface TrendPoint {
  timestamp: number
  psi?: number | null
  temperature_c?: number | null
  status?: string
  flow_rate_lpm?: number | null
  chip_load_pct?: number | null
}

export interface UseCoolantTrendOptions {
  /** Time window in minutes; defaults to 60 (last hour). */
  windowMinutes?: number
  /** Refresh interval in milliseconds; defaults to 30000 (30s). */
  refreshIntervalMs?: number
  onError?: (error: string) => void
}

export interface UseCoolantTrendResult {
  /** Array of time-series data points. */
  data: TrendPoint[]
  /** True while fetching trend data. */
  loading: boolean
  /** Error message if last fetch failed. */
  error: string | undefined
  /** Average pressure (PSI) across the window, or null if no data. */
  average: number | null
  /** Minimum pressure recorded in the window. */
  min: number | null
  /** Maximum pressure recorded in the window. */
  max: number | null
}

/**
 * Hook for fetching and analyzing coolant trend data.
 *
 * Fetches time-series data from `/api/printers/{printerId}/coolant/trend` and
 * calculates min/max/average statistics. Data is refreshed at configurable
 * intervals.
 *
 * @param printerId - Unique printer identifier
 * @param options - Configuration (window, interval, error callback)
 * @returns Trend data and statistics
 */
export function useCoolantTrend(
  printerId: string | undefined,
  options: UseCoolantTrendOptions = {},
): UseCoolantTrendResult {
  const { windowMinutes = 60, refreshIntervalMs = 30000, onError } = options

  const [data, setData] = useState<TrendPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const calculateStats = useCallback(
    (points: TrendPoint[]): { average: number | null; min: number | null; max: number | null } => {
      const pressures = points
        .map((p) => p.psi)
        .filter((p): p is number => p !== null && p !== undefined)

      if (pressures.length === 0) {
        return { average: null, min: null, max: null }
      }

      const sum = pressures.reduce((a, b) => a + b, 0)
      const avg = sum / pressures.length
      const minVal = Math.min(...pressures)
      const maxVal = Math.max(...pressures)

      return {
        average: Math.round(avg * 10) / 10,
        min: Math.round(minVal * 10) / 10,
        max: Math.round(maxVal * 10) / 10,
      }
    },
    [],
  )

  const fetch = useCallback(async () => {
    if (!printerId) return

    setLoading(true)
    setError(undefined)

    try {
      const params = new URLSearchParams({
        window_minutes: windowMinutes.toString(),
      })

      const res = await apiFetch(`/api/printers/${printerId}/coolant/trend?${params.toString()}`)

      if (!res.ok) {
        const msg = `Failed to load trend data: ${res.statusText}`
        setError(msg)
        onError?.(msg)
        return
      }

      const responseData = (await res.json()) as { points?: TrendPoint[] } | TrendPoint[]
      const points = Array.isArray(responseData) ? responseData : responseData.points || []
      setData(points)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(msg)
      onError?.(msg)
    } finally {
      setLoading(false)
    }
  }, [printerId, windowMinutes, onError])

  // Set up polling loop
  useEffect(() => {
    clearPollTimer()

    if (!printerId) return

    // Initial fetch
    void fetch()

    // Schedule periodic refreshes
    pollTimerRef.current = setInterval(() => {
      void fetch()
    }, refreshIntervalMs)

    return () => clearPollTimer()
  }, [printerId, refreshIntervalMs, fetch, clearPollTimer])

  const stats = calculateStats(data)

  return {
    data,
    loading,
    error,
    average: stats.average,
    min: stats.min,
    max: stats.max,
  }
}

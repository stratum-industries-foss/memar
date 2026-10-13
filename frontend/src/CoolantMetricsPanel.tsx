/**
 * CoolantMetricsPanel - Composite dashboard for coolant pressure monitoring
 *
 * Composition:
 * - CoolantAlertBanner (top)
 * - CoolantPSIGauge (left) + CoolantMetricsGrid (right)
 * - CoolantTrendChart (bottom)
 *
 * Real-time updates via polling (5s) + WebSocket anomaly alerts
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, authState } from './api'
import { CoolantPSIGauge } from './CoolantPSIGauge'
import { CoolantTrendChart } from './CoolantTrendChart'
import { CoolantAlertBanner } from './CoolantAlertBanner'
import { CoolantMetricsGrid } from './CoolantMetricsGrid'
import styles from './CoolantMetricsPanel.module.css'

interface CoolantMetrics {
  device_id: string
  device_name: string
  coolant_psi: number | null
  avg_psi: number | null
  min_psi: number | null
  max_psi: number | null
  uptime_percent: number
  sensor_status: 'online' | 'offline'
  last_update: string
  alert_active: boolean
  alert_duration_minutes: number
}

interface TrendDataPoint {
  timestamp: string
  value: number
}

interface CoolantMetricsPanelProps {
  deviceId?: string
  onError?: (error: string) => void
}

export function CoolantMetricsPanel({
  deviceId,
  onError,
}: CoolantMetricsPanelProps) {
  const [metrics, setMetrics] = useState<CoolantMetrics | null>(null)
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [trendLoading, setTrendLoading] = useState(false)
  const [error, setError] = useState('')
  const [showTrendChart, setShowTrendChart] = useState(true)
  // WS + reconnect bookkeeping (refs so the effect closure stays stable across renders).
  const wsRef = useRef<WebSocket | null>(null)
  const wsReconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wsAttemptRef = useRef(0)

  // Fetch current metrics
  const loadMetrics = useCallback(async () => {
    if (!deviceId) return

    setLoading(true)
    setError('')

    try {
      const res = await apiFetch(`/api/devices/${deviceId}/metrics/cnc`)
      if (!res.ok) {
        // 400 = this printer has no CNC/coolant (e.g. FDM/Moonraker). Neutral
        // message, not an alarming "failed to load" — it's simply not applicable.
        if (res.status === 400) {
          setError('Coolant/CNC metrics are not available for this printer.')
          return
        }
        throw new Error(`Failed to load metrics: ${res.status}`)
      }

      const data = await res.json()
      setMetrics({
        device_id: data.device_id,
        device_name: data.device_name,
        coolant_psi: data.coolant_psi ?? null,
        avg_psi: data.avg_coolant_psi ?? null,
        min_psi: data.min_coolant_psi ?? null,
        max_psi: data.max_coolant_psi ?? null,
        uptime_percent: data.uptime_percent ?? 99.5,
        sensor_status: data.sensor_status ?? 'online',
        last_update: data.timestamp ?? new Date().toISOString(),
        alert_active: data.coolant_psi != null && data.coolant_psi < 20,
        alert_duration_minutes: data.alert_duration_minutes ?? 0,
      })
    } catch (err) {
      const errorMsg = String(err)
      setError(errorMsg)
      onError?.(errorMsg)
    } finally {
      setLoading(false)
    }
  }, [deviceId, onError])

  // Fetch 24h trend data
  const loadTrend = useCallback(async () => {
    if (!deviceId) return

    setTrendLoading(true)

    try {
      const res = await apiFetch(
        `/api/devices/${deviceId}/metrics/cnc/aggregated?minutes=1440`
      )
      if (!res.ok) {
        console.warn(`Failed to load trend data: ${res.status}`)
        setTrendData([])
        return
      }

      const data = await res.json()
      // Transform aggregated data to trend points. Handle field name variations:
      // - avg_coolant_psi (canonical)
      // - coolant_psi (fallback)
      // - psi (fallback)
      if (data.history && Array.isArray(data.history)) {
        const points = data.history
          .map((point: any) => ({
            timestamp: point.timestamp,
            // Try multiple field names to account for backend variations
            value: point.avg_coolant_psi ?? point.coolant_psi ?? point.psi ?? 0,
          }))
          .filter((p: any) => p.timestamp != null)
        setTrendData(points.length > 0 ? points : [])
      } else {
        console.warn('Trend data response missing history array', data)
        setTrendData([])
      }
    } catch (err) {
      console.error('Failed to load trend data:', err)
      setTrendData([])
    } finally {
      setTrendLoading(false)
    }
  }, [deviceId])

  // Initial load
  useEffect(() => {
    loadMetrics()
    loadTrend()
  }, [loadMetrics, loadTrend])

  // Poll metrics every 5 seconds
  useEffect(() => {
    const interval = setInterval(loadMetrics, 5000)
    return () => clearInterval(interval)
  }, [loadMetrics])

  // Poll trend every 60 seconds
  useEffect(() => {
    const interval = setInterval(loadTrend, 60000)
    return () => clearInterval(interval)
  }, [loadTrend])

  // WebSocket for real-time anomalies.
  // Authed the same way as the fleet WS in App.tsx (token in query string — a minor
  // P2 in itself, tracked separately) and self-healing: reconnects with capped
  // exponential backoff on unexpected close, and tears down both the socket and any
  // pending timer on unmount. Does not touch `error` state on WS events so a genuine
  // metrics-fetch error banner isn't clobbered by socket churn.
  useEffect(() => {
    if (!deviceId) return
    let stopped = false

    const buildWsUrl = (ticket: string) => {
      const envBase = import.meta.env.VITE_API_BASE_URL
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const host = envBase ? new URL(envBase).host : window.location.host
      return `${protocol}://${host}/ws/metrics/${deviceId}?ticket=${ticket}`
    }

    const scheduleReconnect = () => {
      if (stopped) return
      const delay = Math.min(1000 * Math.pow(2, wsAttemptRef.current), 30000)
      wsAttemptRef.current += 1
      wsReconnectRef.current = setTimeout(() => { void connect() }, delay)
    }

    const connect = async () => {
      if (stopped) return
      // Don't open an unauthenticated socket; polling (apiFetch) still carries the
      // Authorization header, so metrics keep flowing until a token exists.
      if (!authState.accessToken) return
      // Fetch a fresh single-use ticket (Bearer via apiFetch — keeps the JWT out of
      // the WS URL). A ticket can't be reused, so every (re)connect fetches its own.
      let ticket: string
      try {
        const res = await apiFetch('/api/ws/ticket', { method: 'POST' })
        if (!res.ok) throw new Error(`ticket ${res.status}`)
        ticket = (await res.json()).ticket
      } catch {
        // No ticket → stay on the 5s polling path; retry the socket with backoff.
        scheduleReconnect()
        return
      }
      if (stopped || !ticket) return
      let socket: WebSocket
      try {
        socket = new WebSocket(buildWsUrl(ticket))
      } catch (err) {
        console.error('WebSocket error:', err)
        return
      }
      wsRef.current = socket

      socket.onopen = () => {
        wsAttemptRef.current = 0
      }

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'anomaly') {
            console.warn('CNC Anomaly:', msg.data)
          } else if (msg.type === 'metrics_update') {
            setMetrics((prev) => {
              if (!prev) return null
              // Normalize WebSocket metrics using the same field mapping as the HTTP response
              const update = msg.data
              return {
                ...prev,
                coolant_psi: update.coolant_psi ?? prev.coolant_psi,
                avg_psi: update.avg_coolant_psi ?? update.avg_psi ?? prev.avg_psi,
                min_psi: update.min_coolant_psi ?? update.min_psi ?? prev.min_psi,
                max_psi: update.max_coolant_psi ?? update.max_psi ?? prev.max_psi,
                sensor_status: update.sensor_status ?? prev.sensor_status,
                alert_active: update.coolant_psi != null && update.coolant_psi < 20,
                last_update: update.timestamp ?? new Date().toISOString(),
              }
            })
          }
        } catch (err) {
          console.warn('Failed to parse WebSocket message:', err)
        }
      }

      socket.onerror = () => {
        console.error('WebSocket connection error')
      }

      socket.onclose = () => {
        if (stopped) return
        scheduleReconnect()
      }
    }

    void connect()

    return () => {
      stopped = true
      if (wsReconnectRef.current !== null) {
        clearTimeout(wsReconnectRef.current)
        wsReconnectRef.current = null
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [deviceId])

  if (!deviceId) {
    return (
      <div className={styles['coolant-panel-empty']}>
        <p>Select a device to view coolant pressure metrics</p>
      </div>
    )
  }

  if (error && !metrics) {
    return (
      <div className={styles['coolant-panel-error']}>
        <p>{error}</p>
        <button onClick={loadMetrics} disabled={loading}>
          Retry
        </button>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className={styles['coolant-panel-loading']}>
        <p>{loading ? 'Loading metrics...' : 'No data available'}</p>
      </div>
    )
  }

  return (
    <div className={styles['coolant-metrics-panel']}>

      {/* Alert Banner — must stay mounted. The banner owns its full dismiss /
          5-minute re-show / auto-recovery lifecycle internally; gating it behind a
          parent-level dismiss flag (and unmounting it) permanently suppresses every
          future critical alert for this view. */}
      <CoolantAlertBanner
        coolant_psi={metrics.coolant_psi}
        alert_active={metrics.alert_active}
        duration_minutes={metrics.alert_duration_minutes}
        onViewHistory={() => setShowTrendChart(true)}
      />

      {/* Header */}
      <div className={styles['coolant-panel-header']}>
        <h2>Coolant Pressure Monitoring</h2>
        <div className={styles['coolant-panel-subheader']}>
          {metrics.device_name}
          {metrics.sensor_status === 'offline' && (
            <span> • ⚠️ Sensor Offline</span>
          )}
        </div>
      </div>

      {/* Main Content: Gauge + Metrics Grid */}
      <div className={styles['coolant-panel-content']}>
        <div className={styles['coolant-panel-gauge']}>
          <CoolantPSIGauge
            coolant_psi={metrics.coolant_psi}
            last_update={metrics.last_update}
            sensor_status={metrics.sensor_status}
          />
        </div>

        <div className={styles['coolant-panel-stats']}>
          <CoolantMetricsGrid
            avg_psi={metrics.avg_psi}
            min_psi={metrics.min_psi}
            max_psi={metrics.max_psi}
            uptime_percent={metrics.uptime_percent}
            last_update={metrics.last_update}
          />
        </div>
      </div>

      {/* Trend Chart */}
      {showTrendChart && (
        <div className={styles['coolant-panel-trend']}>
          <div className={styles['coolant-panel-trend-toggle']}>
            <button className={styles['active']} onClick={() => setShowTrendChart(false)}>24-Hour Trend</button>
            <span style={{ color: 'var(--text-disabled)', fontSize: '0.85rem' }}>
              {trendLoading ? 'Loading...' : `${trendData.length} data points`}
            </span>
          </div>
          <CoolantTrendChart
            data={trendData}
            loading={trendLoading}
            error={error}
          />
        </div>
      )}
      {!showTrendChart && (
        <div className={styles['coolant-panel-trend-toggle']}>
          <button onClick={() => setShowTrendChart(true)}>Show 24-Hour Trend</button>
        </div>
      )}
    </div>
  )
}

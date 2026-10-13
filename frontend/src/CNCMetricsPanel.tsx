/**
 * CNCMetricsPanel — Aggregated CNC fleet metrics dashboard.
 *
 * Displays:
 * - Spindle utilization (% time RPM > 1000)
 * - Production time (hours in cutting state)
 * - Idle/downtime hours
 * - Tool changes (count)
 * - Coolant flow duration (hours active)
 * - Feed rate statistics (avg, max)
 *
 * Real-time updates via WebSocket; historical export.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, authState } from './api'
import styles from './CNCMetricsPanel.module.css'

type MetricsData = {
  device_id: string
  device_name: string
  spindle_utilization_pct: number
  production_time_hours: number
  idle_time_hours: number
  downtime_hours: number
  tool_changes: number
  coolant_flow_hours: number
  avg_feed_rate_mm_min: number
  max_feed_rate_mm_min: number
  max_spindle_rpm: number
  window_minutes: number
  timestamp: string
}

// Coerce the raw API/WS payload into a fully-populated, numeric MetricsData so the
// render path can never crash on undefined.toFixed() or produce NaN gauges. Also
// tolerates the backend's canonical key aliases (tool_changes_count,
// sample_period_minutes) in case a future response drifts.
function normalizeMetrics(d: any): MetricsData {
  const n = (v: any): number => (typeof v === 'number' && isFinite(v) ? v : 0)
  return {
    device_id: d?.device_id ?? '',
    device_name: d?.device_name ?? d?.device_id ?? '',
    spindle_utilization_pct: n(d?.spindle_utilization_pct),
    production_time_hours: n(d?.production_time_hours),
    idle_time_hours: n(d?.idle_time_hours),
    downtime_hours: n(d?.downtime_hours),
    tool_changes: n(d?.tool_changes ?? d?.tool_changes_count),
    coolant_flow_hours: n(d?.coolant_flow_hours),
    avg_feed_rate_mm_min: n(d?.avg_feed_rate_mm_min),
    max_feed_rate_mm_min: n(d?.max_feed_rate_mm_min),
    max_spindle_rpm: n(d?.max_spindle_rpm),
    window_minutes: n(d?.window_minutes ?? d?.sample_period_minutes) || 60,
    timestamp: d?.timestamp ?? new Date().toISOString(),
  }
}

export function CNCMetricsPanel({ deviceId }: { deviceId?: string }) {
  const [metrics, setMetrics] = useState<MetricsData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [window, setWindow] = useState(60) // minutes
  // WS + reconnect bookkeeping (refs so the effect closure stays stable across renders).
  const wsRef = useRef<WebSocket | null>(null)
  const wsReconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wsAttemptRef = useRef(0)

  // Poll metrics endpoint
  const loadMetrics = useCallback(async () => {
    if (!deviceId) return
    setLoading(true)
    setError('')
    try {
      const res = await apiFetch(`/api/devices/${deviceId}/metrics/cnc/aggregated?minutes=${window}`)
      if (!res.ok) {
        setError(`Failed to load metrics: ${res.status}`)
        setMetrics(null)
        return
      }
      const data = await res.json()
      setMetrics(normalizeMetrics(data))
    } catch (err) {
      setError(String(err))
      setMetrics(null)
    } finally {
      setLoading(false)
    }
  }, [deviceId, window])

  // Initial load
  useEffect(() => {
    loadMetrics()
  }, [loadMetrics])

  // Poll every 5 seconds
  useEffect(() => {
    const interval = setInterval(loadMetrics, 5000)
    return () => clearInterval(interval)
  }, [loadMetrics])

  // WebSocket for real-time metrics + anomaly alerts.
  // Authed the same way as the fleet WS in App.tsx (token in query string — a minor
  // P2 in itself, tracked separately) and self-healing: reconnects with capped
  // exponential backoff on unexpected close, clears the "connection lost" error on
  // reconnect, and tears down both the socket and any pending timer on unmount.
  // NOTE: `window` is shadowed by state above, so use bare timers (not window.setTimeout).
  useEffect(() => {
    if (!deviceId) return
    let stopped = false

    const buildWsUrl = (ticket: string) => {
      const loc = typeof globalThis !== 'undefined' ? globalThis.location : undefined
      const envBase = import.meta.env.VITE_API_BASE_URL
      const proto = loc && String(loc.protocol) === 'https:' ? 'wss' : 'ws'
      const host = envBase ? new URL(envBase).host : (loc && loc.host ? String(loc.host) : 'localhost')
      return `${proto}://${host}/ws/metrics/${deviceId}?ticket=${ticket}`
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
        setError('')
      }

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'anomaly') {
            console.warn('CNC Anomaly:', msg.data)
          } else if (msg.type === 'metrics_update') {
            // normalizeMetrics handles field name variations and ensures all
            // values are valid numbers or 0, preventing NaN in gauges
            setMetrics(normalizeMetrics(msg.data))
          }
        } catch (err) {
          console.warn('Failed to parse WebSocket message:', err)
        }
      }

      socket.onerror = () => setError('WebSocket connection lost')

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
    return <div className="subtle small">Select a device to view metrics</div>
  }

  const m = metrics
  if (!m) {
    return (
      <section className="drawer-section">
        <h3>CNC Metrics</h3>
        {error && <div className="subtle">{error}</div>}
        {loading && <div className="subtle">Loading metrics...</div>}
        <button onClick={loadMetrics} disabled={loading}>
          Reload
        </button>
      </section>
    )
  }

  // Gauge visualization helper
  const Gauge = ({
    value,
    max = 100,
    label,
    unit = '',
  }: {
    value: number
    max?: number
    label: string
    unit?: string
  }) => {
    const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
    return (
      <div className={styles['metric-gauge']}>
        <label>{label}</label>
        <div className={styles['gauge-bar']}>
          <div className={styles['gauge-fill']} style={{ width: `${pct}%` }} />
        </div>
        <div className={styles['gauge-value']}>
          {value.toFixed(1)}
          {unit}
        </div>
      </div>
    )
  }

  return (
    <section className="drawer-section" role="region" aria-label={`CNC Metrics — ${m.device_name}`}>
      <h3>
        CNC Metrics — <span className="subtle small">{m.device_name}</span>
      </h3>

      {/* 40/60 asymmetric split: left (gauges + stats) | right (future 3D viewer slot) */}
      <div className={styles['cnc-metrics-container']}>
        {/* Left panel: controls + 2×2 gauges + stat cards + alerts */}
        <div className={styles['cnc-left-panel']}>
          <div className={styles['metrics-controls']}>
            <label>
              Window:
              <select value={window} onChange={(e) => setWindow(Number(e.target.value))}>
                <option value={15}>15 min</option>
                <option value={30}>30 min</option>
                <option value={60}>1 hour</option>
                <option value={120}>2 hours</option>
              </select>
            </label>
            <span className="subtle small">Updated {new Date(m.timestamp).toLocaleTimeString()}</span>
          </div>

          {/* 2×2 gauge grid */}
          <div className={styles['metrics-grid']}>
            <Gauge value={m.spindle_utilization_pct} max={100} label="Spindle Utilization" unit="%" />
            <Gauge value={m.production_time_hours} max={m.window_minutes / 60} label="Production Time" unit=" h" />
            <Gauge value={m.idle_time_hours} max={m.window_minutes / 60} label="Idle Time" unit=" h" />
            <Gauge value={m.downtime_hours} max={m.window_minutes / 60} label="Downtime" unit=" h" />
          </div>

          {/* Stat cards — stagger-animated via CSS nth-child */}
          <div className={styles['metrics-stats']}>
            <div className={styles['stat-card']}>
              <h4>Tool Changes</h4>
              <div className={styles['stat-value']}>{m.tool_changes}</div>
            </div>
            <div className={styles['stat-card']}>
              <h4>Coolant Flow</h4>
              <div className={styles['stat-value']}>{m.coolant_flow_hours.toFixed(2)} h</div>
            </div>
            <div className={styles['stat-card']}>
              <h4>Avg Feed Rate</h4>
              <div className={styles['stat-value']}>{m.avg_feed_rate_mm_min.toFixed(1)} mm/min</div>
            </div>
            <div className={styles['stat-card']}>
              <h4>Max Feed Rate</h4>
              <div className={styles['stat-value']}>{m.max_feed_rate_mm_min.toFixed(1)} mm/min</div>
            </div>
            <div className={styles['stat-card']}>
              <h4>Max Spindle RPM</h4>
              <div className={styles['stat-value']}>{m.max_spindle_rpm}</div>
            </div>
          </div>

          <div className={styles['metrics-alerts']}>
            {m.spindle_utilization_pct < 20 && (
              <div className={styles['alert-low']}>Low spindle utilization (&lt;20%)</div>
            )}
            {m.downtime_hours > (m.window_minutes / 60) * 0.3 && (
              <div className={styles['alert-high']}>High downtime (&gt;30%)</div>
            )}
          </div>
        </div>

        {/* Right panel: 3D viewer placeholder (full height via CSS grid row span) */}
        {/* When a real 3D viewer component exists, replace this div */}
        <div className={styles['cnc-3d-viewer']} aria-label="3D model viewer (coming soon)">
          <div className={styles['cnc-3d-viewer-placeholder']}>
            <span className="subtle small">3D Viewer</span>
          </div>
        </div>
      </div>
    </section>
  )
}

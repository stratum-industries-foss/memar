/**
 * useCoolantState — extracts all state and side effects from CoolantMetricsPanel.
 *
 * Manages:
 *   - Chart visibility toggle (showTrendChart)
 *   - Real-time metrics via useCoolantMetrics + useCoolantTrend
 *   - WebSocket connection via useTicketedMetricsWS
 *   - Message handling and dispatch
 */

import { useCallback, useState } from 'react'
import { useCoolantMetrics, CoolantMetrics } from './useCoolantMetrics'
import { useCoolantTrend, TrendPoint } from './useCoolantTrend'
import { useTicketedMetricsWS, CoolantMetricsMessage, CoolantRealtimeUpdate } from './useTicketedMetricsWS'

export interface CoolantState {
  // Render toggles
  showTrendChart: boolean
  setShowTrendChart: (value: boolean | ((prev: boolean) => boolean)) => void

  // Metrics data and state
  metrics: CoolantMetrics | null
  loading: boolean
  error: string | undefined
  unavailable: boolean
  reload: () => void
  applyRealtimeUpdate: (data: CoolantRealtimeUpdate) => void

  // Trend data and state
  trendData: TrendPoint[]
  trendLoading: boolean
  trendError: string | undefined
}

export function useCoolantState(
  printerId: string | undefined,
  onError?: (error: string) => void
): CoolantState {
  const [showTrendChart, setShowTrendChart] = useState(true)

  const { metrics, loading, error, unavailable, reload, applyRealtimeUpdate } =
    useCoolantMetrics(printerId, { onError })

  const {
    data: trendData,
    loading: trendLoading,
    error: trendError,
  } = useCoolantTrend(printerId)

  // Inline identity is fine: useTicketedMetricsWS reads its handler through a
  // latest-ref, so this never rebuilds the socket.
  const handleWsMessage = useCallback(
    (message: CoolantMetricsMessage) => {
      if (message?.type === 'anomaly') {
        console.warn('CNC anomaly:', message.data)
      } else if (message?.type === 'metrics_update') {
        applyRealtimeUpdate(message.data)
      }
    },
    [applyRealtimeUpdate]
  )

  // TODO: Connect to WebSocket metrics stream
  // useTicketedMetricsWS expects a ticketId, which should be obtained from the backend
  // when requesting real-time metrics for this printer.

  return {
    showTrendChart,
    setShowTrendChart,
    metrics,
    loading,
    error,
    unavailable,
    reload,
    applyRealtimeUpdate,
    trendData,
    trendLoading,
    trendError,
  }
}

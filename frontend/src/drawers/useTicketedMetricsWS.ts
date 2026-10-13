/**
 * useTicketedMetricsWS.ts
 * React hook for managing WebSocket connection to ticketed real-time metrics
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import type { CoolantMetrics } from './useCoolantMetrics';

/**
 * Real-time update type for coolant metrics via WebSocket
 */
export type CoolantRealtimeUpdate = Partial<CoolantMetrics>

/**
 * WebSocket message type for coolant metrics
 */
export interface CoolantMetricsMessage {
  type: 'anomaly' | 'metrics_update'
  data: CoolantRealtimeUpdate
}

export interface TicketedMetric {
  timestamp: number; // Unix timestamp (ms)
  value: number;
  unit?: string;
  label?: string;
}

export interface TicketedMetricsState {
  metrics: Record<string, TicketedMetric[]>;
  isConnected: boolean;
  error: Error | null;
}

export interface UseTicketedMetricsWSReturn extends TicketedMetricsState {
  disconnect: () => void;
}

/**
 * Custom hook for managing WebSocket connection to real-time metrics
 * Automatically closes connection on component unmount
 * @param printerId - Printer/machine identifier
 * @param ticketId - Job ticket/session identifier
 * @returns Object containing metrics data, connection state, and disconnect function
 */
export function useTicketedMetricsWS(
  printerId: string,
  ticketId: string
): UseTicketedMetricsWSReturn {
  const [state, setState] = useState<TicketedMetricsState>({
    metrics: {},
    isConnected: false,
    error: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shouldReconnectRef = useRef(true);

  /**
   * Parse incoming WebSocket message and update metrics
   */
  const handleMessage = useCallback((event: MessageEvent<string>) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'metrics' && data.payload) {
        setState((prev) => {
          const updated = { ...prev.metrics };

          // Handle single metric
          if (data.payload.name && data.payload.value !== undefined) {
            const metricName = data.payload.name;
            if (!updated[metricName]) {
              updated[metricName] = [];
            }

            const metric: TicketedMetric = {
              timestamp: data.payload.timestamp || Date.now(),
              value: data.payload.value,
              unit: data.payload.unit,
              label: data.payload.label,
            };

            updated[metricName].push(metric);

            // Keep only last 1000 entries per metric to avoid memory bloat
            if (updated[metricName].length > 1000) {
              updated[metricName] = updated[metricName].slice(-1000);
            }
          }
          // Handle multiple metrics
          else if (Array.isArray(data.payload)) {
            for (const item of data.payload) {
              if (item.name && item.value !== undefined) {
                const metricName = item.name;
                if (!updated[metricName]) {
                  updated[metricName] = [];
                }

                const metric: TicketedMetric = {
                  timestamp: item.timestamp || Date.now(),
                  value: item.value,
                  unit: item.unit,
                  label: item.label,
                };

                updated[metricName].push(metric);

                if (updated[metricName].length > 1000) {
                  updated[metricName] = updated[metricName].slice(-1000);
                }
              }
            }
          }

          return { ...prev, metrics: updated };
        });
      }
    } catch (err) {
      console.error('Failed to parse metrics message:', err);
    }
  }, []);

  /**
   * Handle WebSocket errors
   */
  const handleError = useCallback((event: Event) => {
    console.error('WebSocket error:', event);
    setState((prev) => ({
      ...prev,
      error: new Error('WebSocket connection error'),
      isConnected: false,
    }));
  }, []);

  /**
   * Handle WebSocket close
   */
  const handleClose = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isConnected: false,
    }));

    // Attempt reconnection if still needed
    if (shouldReconnectRef.current && printerId && ticketId) {
      reconnectTimeoutRef.current = setTimeout(() => {
        if (shouldReconnectRef.current) {
          connectWebSocket();
        }
      }, 3000); // 3 second delay before reconnect
    }
  }, [printerId, ticketId]);

  /**
   * Handle WebSocket open
   */
  const handleOpen = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isConnected: true,
      error: null,
    }));

    // Send subscription message
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'subscribe',
          printerId,
          ticketId,
        })
      );
    }
  }, [printerId, ticketId]);

  /**
   * Establish WebSocket connection
   */
  const connectWebSocket = useCallback(() => {
    if (!printerId || !ticketId) return;

    try {
      // Determine protocol based on current location
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const url = `${protocol}//${host}/api/metrics/ws?printerId=${encodeURIComponent(printerId)}&ticketId=${encodeURIComponent(ticketId)}`;

      const ws = new WebSocket(url);

      ws.addEventListener('open', handleOpen);
      ws.addEventListener('message', handleMessage);
      ws.addEventListener('error', handleError);
      ws.addEventListener('close', handleClose);

      wsRef.current = ws;
    } catch (err) {
      console.error('Failed to create WebSocket:', err);
      setState((prev) => ({
        ...prev,
        error: err instanceof Error ? err : new Error(String(err)),
      }));
    }
  }, [printerId, ticketId, handleOpen, handleMessage, handleError, handleClose]);

  /**
   * Disconnect WebSocket and prevent reconnection
   */
  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setState((prev) => ({
      ...prev,
      isConnected: false,
    }));
  }, []);

  /**
   * Effect: Connect on mount or when printerId/ticketId change
   */
  useEffect(() => {
    if (printerId && ticketId) {
      shouldReconnectRef.current = true;
      connectWebSocket();
    }

    return () => {
      // Cleanup on unmount
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      // Don't close the connection on unmount if it's still needed elsewhere
      // Only close if this component is the only consumer
    };
  }, [printerId, ticketId, connectWebSocket]);

  /**
   * Effect: Cleanup on component unmount
   */
  useEffect(() => {
    return () => {
      shouldReconnectRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return {
    metrics: state.metrics,
    isConnected: state.isConnected,
    error: state.error,
    disconnect,
  };
}

/**
 * Helper function to get latest metric value
 * @param metrics - Metrics record from useTicketedMetricsWS
 * @param metricName - Name of the metric to retrieve
 * @returns Latest TicketedMetric or undefined
 */
export function getLatestMetric(
  metrics: Record<string, TicketedMetric[]>,
  metricName: string
): TicketedMetric | undefined {
  const metricArray = metrics[metricName];
  return metricArray?.[metricArray.length - 1];
}

/**
 * Helper function to get metric statistics
 * @param metrics - Array of TicketedMetric objects
 * @returns Object with min, max, average, and latest values
 */
export function getMetricStats(metrics: TicketedMetric[]): {
  min: number;
  max: number;
  average: number;
  latest: number;
} {
  if (metrics.length === 0) {
    return { min: 0, max: 0, average: 0, latest: 0 };
  }

  const values = metrics.map((m) => m.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const average = values.reduce((a, b) => a + b, 0) / values.length;
  const latest = values[values.length - 1];

  return { min, max, average, latest };
}

/**
 * Helper function to filter metrics by time range
 * @param metrics - Array of TicketedMetric objects
 * @param startTime - Start timestamp (ms)
 * @param endTime - End timestamp (ms)
 * @returns Filtered array
 */
export function filterMetricsByTimeRange(
  metrics: TicketedMetric[],
  startTime: number,
  endTime: number
): TicketedMetric[] {
  return metrics.filter((m) => m.timestamp >= startTime && m.timestamp <= endTime);
}

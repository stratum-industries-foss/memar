/**
 * useGcodeConsole — G-code console API integration
 *
 * Manages console log display and G-code command execution via REST API.
 * Handles error messages, loading state, and automatic scrolling.
 */

import { useCallback, useRef, useEffect, useState } from 'react'
import { apiFetch } from '../api'
import type { MachineTypeValue } from './types.printer'

export interface LogEntry {
  type: 'request' | 'response' | 'error'
  text: string
  timestamp?: number
}

export interface UseGcodeConsoleOptions {
  printerId: string
  machineType?: MachineTypeValue
  onDispatch?: (command: string) => void
}

export interface UseGcodeConsoleResult {
  /** Console log entries (scrollable history). */
  log: LogEntry[]
  /** True if a send() call is pending. */
  sending: boolean
  /** Error message if last operation failed. */
  error: string | undefined
  /** Ref to console output div for auto-scroll. */
  scrollRef: React.RefObject<HTMLDivElement | null>
  /** Send a G-code command and append response to log. */
  send: (script: string) => Promise<void>
  /** Clear the console log. */
  clear: () => void
  /** Fetch and populate the console log from the server. */
  loadHistory: () => Promise<void>
}

/**
 * Hook for G-code console interaction.
 *
 * Fetches console history on demand (loadHistory) and can send individual
 * commands. Errors are captured in the `error` state; responses are appended
 * to the log. Maintains a ref to the scroll container for auto-scroll on new
 * entries.
 *
 * @param options - Configuration including printerId and optional machine type
 * @returns Console interface
 */
export function useGcodeConsole({
  printerId,
  machineType,
  onDispatch,
}: UseGcodeConsoleOptions): UseGcodeConsoleResult {
  const [log, setLog] = useState<LogEntry[]>([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll log to bottom whenever it updates
  useEffect(() => {
    if (scrollRef.current) {
      setTimeout(() => {
        scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight)
      }, 0)
    }
  }, [log])

  const clear = useCallback(() => {
    setLog([])
    setError(undefined)
  }, [])

  const loadHistory = useCallback(async () => {
    if (!printerId) return
    try {
      setError(undefined)
      const endpoint = machineType?.startsWith('cnc_') || machineType?.includes('laser')
        ? `/api/printers/${printerId}/gcode/log`
        : `/api/printers/${printerId}/console/log`

      const res = await apiFetch(endpoint)
      if (!res.ok) {
        setError(`Failed to load history: ${res.statusText}`)
        return
      }

      const data = (await res.json()) as { entries?: Array<{ type: string; text: string }> } | null
      if (data?.entries && Array.isArray(data.entries)) {
        setLog(
          data.entries.map((e) => ({
            type: (e.type as LogEntry['type']) || 'response',
            text: e.text || '',
            timestamp: Date.now(),
          })),
        )
      } else {
        setLog([])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error loading history')
    }
  }, [printerId, machineType])

  const send = useCallback(
    async (script: string) => {
      if (!printerId || !script.trim()) return

      setSending(true)
      setError(undefined)

      try {
        // Add request to log immediately
        setLog((prev) => [
          ...prev,
          {
            type: 'request',
            text: script.trim(),
            timestamp: Date.now(),
          },
        ])

        // Call onDispatch callback if provided (for recording to history, etc.)
        onDispatch?.(script)

        // Route endpoint based on machine type
        const endpoint = machineType?.startsWith('cnc_') || machineType?.includes('laser')
          ? `/api/printers/${printerId}/gcode`
          : `/api/printers/${printerId}/console/send`

        const res = await apiFetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            script: script.trim(),
            machine_type: machineType,
          }),
        })

        if (!res.ok) {
          const errText = await res.text()
          const msg = `Error (${res.status}): ${errText || res.statusText}`
          setLog((prev) => [...prev, { type: 'error', text: msg, timestamp: Date.now() }])
          setError(msg)
          return
        }

        const data = (await res.json()) as { result?: string; output?: string }
        const resultText = data.result || data.output || ''
        if (resultText) {
          setLog((prev) => [...prev, { type: 'response', text: resultText, timestamp: Date.now() }])
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error'
        setLog((prev) => [...prev, { type: 'error', text: msg, timestamp: Date.now() }])
        setError(msg)
      } finally {
        setSending(false)
      }
    },
    [printerId, machineType, onDispatch],
  )

  return {
    log,
    sending,
    error,
    scrollRef,
    send,
    clear,
    loadHistory,
  }
}

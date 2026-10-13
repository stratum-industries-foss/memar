/**
 * useSpoolManagement — Spool state and API management hook
 *
 * Fetches spool logs from the printer, records filament adjustments,
 * and calculates remaining filament estimates.
 *
 * Manages:
 *   - log: SpoolLogEntry[] from /api/printers/{printerId}/spool/log
 *   - isLoading: boolean indicating fetch in progress
 *   - recordAdjustment: Function to POST a new spool adjustment
 *   - calculateRemaining: Function to compute estimated remaining filament
 */

import { useState, useCallback, useEffect, useMemo } from 'react'
import type { SpoolLogEntry, SpoolLogResponse } from './spoolUtils'
import type { Diagnostics } from '../types/printer'

/**
 * Toast notification function type
 */
export type ToastFn = (message: string, level?: string) => void

/**
 * Hook return type for spool management
 */
export interface UseSpoolManagementReturn {
  log: SpoolLogEntry[]
  isLoading: boolean
  error: string | null
  recordAdjustment: (adjustment: Partial<SpoolLogEntry>) => Promise<void>
  calculateRemaining: () => number
  totalUsed: number
  currentRemaining: number
}

/**
 * Custom hook for managing spool state and API interactions.
 *
 * @param printerId - The printer ID for API calls
 * @param spoolLogState - Initial spool log state (optional, allows DI pattern)
 * @param pushToast - Optional toast notification callback
 * @returns Object with log, loading state, adjustment recording, and remaining calc
 */
export function useSpoolManagement(
  printerId: string,
  spoolLogState?: SpoolLogEntry[] | Diagnostics,
  pushToast?: ToastFn
): UseSpoolManagementReturn {
  // If spoolLogState is Diagnostics (object with numeric keys), treat as no initial state
  const isArrayState = Array.isArray(spoolLogState)
  const initialLog = isArrayState ? (spoolLogState as SpoolLogEntry[]) : []
  const [log, setLog] = useState<SpoolLogEntry[]>(initialLog)
  const [isLoading, setIsLoading] = useState(!isArrayState)
  const [error, setError] = useState<string | null>(null)
  const [totalUsed, setTotalUsed] = useState(0)
  const [currentRemaining, setCurrentRemaining] = useState(0)

  /**
   * Fetch the spool log from the API
   */
  const fetchSpoolLog = useCallback(async () => {
    if (!printerId) {
      setLog([])
      setIsLoading(false)
      return
    }

    try {
      setIsLoading(true)
      setError(null)

      const response = await fetch(
        `/api/printers/${encodeURIComponent(printerId)}/spool/log`,
        {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
        }
      )

      if (!response.ok) {
        throw new Error(`Failed to fetch spool log: ${response.statusText}`)
      }

      const data: SpoolLogResponse = await response.json()
      setLog(data.entries || [])
      setTotalUsed(data.totalUsed || 0)
      setCurrentRemaining(data.currentRemaining || 0)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      console.error('Spool log fetch error:', message)
    } finally {
      setIsLoading(false)
    }
  }, [printerId])

  /**
   * Fetch on mount or when printerId changes
   */
  useEffect(() => {
    fetchSpoolLog()
  }, [fetchSpoolLog])

  /**
   * Record a new filament adjustment (manual, refill, measurement, or print usage)
   *
   * @param adjustment - Partial SpoolLogEntry with material, lengthMm, weight, reason
   */
  const recordAdjustment = useCallback(
    async (adjustment: Partial<SpoolLogEntry>) => {
      if (!printerId) {
        setError('No printer selected')
        return
      }

      try {
        setError(null)

        const payload = {
          material: adjustment.material || 'UNKNOWN',
          lengthMm: adjustment.lengthMm || 0,
          weight: adjustment.weight || 0,
          reason: adjustment.reason || 'adjustment',
          timestamp: new Date().toISOString(),
        }

        const response = await fetch(
          `/api/printers/${encodeURIComponent(printerId)}/spool/log`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }
        )

        if (!response.ok) {
          throw new Error(`Failed to record adjustment: ${response.statusText}`)
        }

        // Refresh the log after successful adjustment
        await fetchSpoolLog()
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setError(message)
        console.error('Record adjustment error:', message)
        throw err
      }
    },
    [printerId, fetchSpoolLog]
  )

  /**
   * Calculate remaining filament from the log entries.
   *
   * Sums all weight entries: positive for refills, negative for usage.
   * Returns the estimated remaining weight in grams.
   *
   * @returns Remaining filament weight in grams
   */
  const calculateRemaining = useCallback((): number => {
    return log.reduce((sum, entry) => sum + entry.weight, currentRemaining)
  }, [log, currentRemaining])

  return {
    log,
    isLoading,
    error,
    recordAdjustment,
    calculateRemaining,
    totalUsed,
    currentRemaining,
  }
}

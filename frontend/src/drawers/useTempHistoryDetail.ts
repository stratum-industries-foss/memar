/**
 * useTempHistoryDetail — Custom hook for fetching and caching detailed temperature history.
 *
 * Fetches temperature history from /api/printers/{printerId}/temp/history and caches results
 * to avoid redundant requests. Designed for use in the Temperature drawer.
 *
 * Single responsibility: data fetching and caching only. All business logic stays in
 * useTemperatureState.ts.
 */

import { useEffect, useRef, useState } from 'react'

/**
 * A single point in temperature history.
 * timestamp is Unix epoch milliseconds; temperature is in °C.
 */
export type TempHistoryPoint = {
  timestamp: number
  temperature: number
}

/**
 * Full temperature history response: two time series, one for each heater.
 */
export type TempHistoryDetail = {
  extruder: TempHistoryPoint[]
  bed: TempHistoryPoint[]
}

/**
 * Fetcher signature — allows injection of apiFetch or test doubles.
 * Matches the signature of the module-level apiFetch from api.ts.
 */
export type Fetcher = (
  path: string,
  options?: RequestInit
) => Promise<Response>

interface UseTempHistoryDetailState {
  data: TempHistoryDetail | null
  isLoading: boolean
  error: Error | null
}

/**
 * Custom hook: useTempHistoryDetail
 *
 * Fetches detailed temperature history from the backend and memoizes the result.
 * If the fetch fails, error is logged and an empty history is returned.
 *
 * @param printerId - Printer ID to fetch history for
 * @param fetcher - Optional injected fetcher (defaults to apiFetch for production)
 * @returns { data, isLoading, error }
 *   - data: null initially and during loading, then { extruder: [], bed: [] } or populated arrays
 *   - isLoading: true while fetching
 *   - error: null if successful or not yet attempted, Error if fetch failed
 */
export function useTempHistoryDetail(
  printerId: string,
  fetcher?: Fetcher
): UseTempHistoryDetailState {
  const [state, setState] = useState<UseTempHistoryDetailState>({
    data: null,
    isLoading: false,
    error: null,
  })

  // Use a ref to track the last fetched ID — prevents redundant refetches
  // if the component re-renders with the same printerId.
  const lastFetchedId = useRef<string | null>(null)

  useEffect(() => {
    // Guard: don't fetch if already fetched for this ID or if fetcher is missing
    if (printerId === lastFetchedId.current || !fetcher || !printerId) return

    const abortController = new AbortController()

    async function fetch_() {
      setState({ data: null, isLoading: true, error: null })
      try {
        const res = await (fetcher as Fetcher)(`/api/printers/${printerId}/temp/history`, {
          signal: abortController.signal,
        })
        if (!res.ok) {
          setState({
            data: { extruder: [], bed: [] },
            isLoading: false,
            error: new Error(`Failed to fetch temperature history: ${res.status}`),
          })
          return
        }
        const json = (await res.json()) as TempHistoryDetail
        lastFetchedId.current = printerId
        setState({ data: json, isLoading: false, error: null })
      } catch (e) {
        // Ignore abort errors (cleanup from unmount or dependency change)
        if ((e as Error).name === 'AbortError') return
        const err = e instanceof Error ? e : new Error(String(e))
        setState({
          data: { extruder: [], bed: [] },
          isLoading: false,
          error: err,
        })
      }
    }

    fetch_()

    return () => {
      abortController.abort()
    }
  }, [printerId, fetcher])

  return state
}

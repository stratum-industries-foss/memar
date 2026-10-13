/**
 * useTimelapseState — extracts all state management for the TimelapseDrawer.
 *
 * Manages timelapse list, playback state, and download/delete operations.
 */

import { useState, useCallback, useEffect } from 'react'
import { apiFetch } from '../api'

export interface TimelapseEntry {
  id: string
  name: string
  kind: 'video' | 'image'
  size: number
  modified: number
}

export interface TimelapseResponse {
  configured: boolean
  source_dir: string | null
  entries: TimelapseEntry[]
}

export interface TimelapseState {
  /** Timelapse list and configuration. */
  data: TimelapseResponse | null
  /** Human-readable failure from the last load; '' when healthy. */
  error: string
  /** A GET /timelapse is in flight. */
  loading: boolean
  /** Playback speed multiplier (client-side). */
  playbackSpeed: number
  /** Re-read the timelapse list. */
  reload: () => Promise<void>
  /** Set playback speed. */
  setPlaybackSpeed: (speed: number) => void
}

/**
 * Manage timelapse state and operations.
 */
export function useTimelapseState(printerId: string): TimelapseState {
  const [data, setData] = useState<TimelapseResponse | null>(null)
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(false)
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1)

  /**
   * Load timelapse data from API
   */
  const reload = useCallback(async () => {
    if (!printerId) {
      setData(null)
      return
    }

    setLoading(true)
    setError('')

    try {
      const response = await apiFetch(`/api/printers/${printerId}/timelapse?limit=12`)
      if (!response.ok) {
        throw new Error(`Failed to load timelapse: ${response.statusText}`)
      }

      const timelapseData = (await response.json()) as TimelapseResponse
      setData(timelapseData)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [printerId])

  /**
   * Load timelapse data on mount or when printerId changes
   */
  useEffect(() => {
    reload()
  }, [printerId, reload])

  return {
    data,
    error,
    loading,
    playbackSpeed,
    reload,
    setPlaybackSpeed,
  }
}

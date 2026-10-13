/**
 * useWebcamsState — Encapsulates all Webcams drawer state and logic.
 *
 * Responsibilities:
 *  - Fetch webcam list from /api/printers/{id}/webcams
 *  - Track camera selection and layout mode (1, 2, 4 camera grid)
 *  - Track stream quality preference (local state only, no backend API)
 *  - Track per-camera errors and connection status
 *  - Manage fullscreen view state
 *  - All state/callbacks fully typed, no `any` casts
 */

import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

/**
 * WebcamEntry matches the structure from /api/printers/{id}/webcams
 */
export interface WebcamEntry {
  uid: string
  name: string
  enabled: boolean
  stream_url: string | null
  snapshot_url: string | null
  location: string | null
  service: string | null
  aspect_ratio: string | null
}

export type StreamQuality = 'low' | 'medium' | 'high'
export type LayoutMode = 1 | 2 | 4

export interface WebcamsState {
  // Camera list
  cameraList: WebcamEntry[]
  isLoading: boolean
  error: string | null

  // Selection & layout
  selectedCameraUid: string | null
  setSelectedCameraUid: (uid: string | null) => void
  layoutMode: LayoutMode
  setLayoutMode: (mode: LayoutMode) => void

  // Stream quality (local state only, no API)
  streamQuality: StreamQuality
  setStreamQuality: (quality: StreamQuality) => void

  // Fullscreen
  isFullscreen: boolean
  setIsFullscreen: (fullscreen: boolean) => void

  // Per-camera error tracking
  cameraErrors: Record<string, string>
  setCameraError: (uid: string, error: string | null) => void

  // Camera transforms (local state only: rotate, flip)
  cameraTransforms: Record<string, { rotate: number; flipH: boolean; flipV: boolean }>
  updateCameraTransform: (uid: string, transform: { rotate?: number; flipH?: boolean; flipV?: boolean }) => void
}

export type Fetcher = (url: string, opts?: RequestInit) => Promise<Response>

export function useWebcamsState(
  printerId: string | undefined,
  fetcher: Fetcher = apiFetch,
): WebcamsState {
  const [cameraList, setCameraList] = useState<WebcamEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [selectedCameraUid, setSelectedCameraUid] = useState<string | null>(null)
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(2)
  const [streamQuality, setStreamQuality] = useState<StreamQuality>('medium')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [cameraErrors, setCameraErrors] = useState<Record<string, string>>({})
  const [cameraTransforms, setCameraTransforms] = useState<
    Record<string, { rotate: number; flipH: boolean; flipV: boolean }>
  >({})

  // Fetch webcam list on mount or printerId change
  useEffect(() => {
    if (!printerId) {
      setCameraList([])
      setError(null)
      return
    }

    setIsLoading(true)
    setError(null)

    fetcher(`/api/printers/${printerId}/webcams`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
        const data = await res.json() as WebcamEntry[]
        setCameraList(Array.isArray(data) ? data : [])
        // Auto-select first enabled camera
        const first = data.find((c) => c.enabled)
        if (first) setSelectedCameraUid(first.uid)
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : String(err)
        setError(`Failed to load webcams: ${message}`)
        setCameraList([])
      })
      .finally(() => setIsLoading(false))
  }, [printerId, fetcher])

  function setCameraError(uid: string, errorMsg: string | null) {
    setCameraErrors((prev) => {
      if (errorMsg === null) {
        const { [uid]: _, ...rest } = prev
        return rest
      }
      return { ...prev, [uid]: errorMsg }
    })
  }

  function updateCameraTransform(
    uid: string,
    update: { rotate?: number; flipH?: boolean; flipV?: boolean },
  ) {
    setCameraTransforms((prev) => {
      const current = prev[uid] ?? { rotate: 0, flipH: false, flipV: false }
      return {
        ...prev,
        [uid]: {
          rotate: update.rotate !== undefined ? update.rotate : current.rotate,
          flipH: update.flipH !== undefined ? update.flipH : current.flipH,
          flipV: update.flipV !== undefined ? update.flipV : current.flipV,
        },
      }
    })
  }

  return {
    cameraList,
    isLoading,
    error,
    selectedCameraUid,
    setSelectedCameraUid,
    layoutMode,
    setLayoutMode,
    streamQuality,
    setStreamQuality,
    isFullscreen,
    setIsFullscreen,
    cameraErrors,
    setCameraError,
    cameraTransforms,
    updateCameraTransform,
  }
}

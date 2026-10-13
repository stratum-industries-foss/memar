/**
 * Hook for managing bed mesh data and calibration
 * Provides APIs for fetching mesh data, calibrating, and reloading
 */

import { useState, useCallback, useEffect } from 'react'
import { apiFetch } from './api'

/**
 * Bed mesh data structure returned from API
 */
export interface BedMeshData {
  supported: boolean
  active_profile?: string
  active_is_probed?: boolean
  profiles?: Array<{
    name: string
    points?: Array<[number, number]>
    mesh_params?: Record<string, any>
    probed_points?: number
    min_z?: number | null
    max_z?: number | null
  }>
  mesh_matrix?: number[][]
  x_count?: number
  y_count?: number
  global_min_z?: number | null
  global_max_z?: number | null
  mesh_extent?: {
    x_min: number | null
    x_max: number | null
    y_min: number | null
    y_max: number | null
  }
}

/**
 * Delay after calibrate before reloading mesh (ms)
 */
const CALIBRATE_RELOAD_DELAY_MS = 5000

/**
 * Hook for managing bed mesh state
 * Handles fetching, calibrating, and reloading bed mesh data
 *
 * @param printerId - Printer ID to fetch mesh for
 * @returns Object with mesh data, loading state, and control functions
 */
export function useBedMesh(printerId: string) {
  const [data, setData] = useState<BedMeshData | null>(null)
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(false)
  const [calibrating, setCalibrating] = useState<boolean>(false)

  /**
   * Load bed mesh data from API
   */
  const reload = useCallback(async () => {
    if (!printerId) {
      setData(null)
      return
    }

    setLoading(true)
    setError('')

    try {
      const response = await apiFetch(`/api/printers/${printerId}/bed-mesh`)
      if (!response.ok) {
        throw new Error(`Failed to load bed mesh: ${response.statusText}`)
      }

      const meshData = (await response.json()) as BedMeshData
      setData(meshData)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [printerId])

  /**
   * Calibrate bed mesh
   */
  const calibrate = useCallback(async () => {
    if (!printerId) {
      setError('No printer selected')
      return
    }

    setCalibrating(true)
    setError('')

    try {
      const response = await apiFetch(
        `/api/printers/${printerId}/macros/BED_MESH_CALIBRATE`,
        { method: 'POST' },
      )

      if (!response.ok) {
        throw new Error(`Calibration failed: ${response.statusText}`)
      }

      // Reload mesh after calibration completes
      // Use timeout instead of immediate reload to allow calibration to settle
      setTimeout(() => {
        reload()
      }, CALIBRATE_RELOAD_DELAY_MS)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
    } finally {
      setCalibrating(false)
    }
  }, [printerId, reload])

  /**
   * Load mesh data on mount or when printerId changes
   */
  useEffect(() => {
    reload()
  }, [printerId, reload])

  return {
    data,
    error,
    loading,
    calibrating,
    reload,
    calibrate,
  }
}

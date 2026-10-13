/**
 * useBedmeshState — extracts all state management for the BedMeshDrawer.
 *
 * Consolidates state from useBedMesh and returns the complete state object
 * needed by BedMeshDrawer component.
 */
import { useState, useCallback, useMemo } from 'react'
import { useBedMesh, type BedMeshData } from '../useBedMesh'

export interface BedmeshProbePoint {
  x: number
  y: number
  z: number | null
}

export interface BedmeshState {
  /** Mesh payload, or null while a load is in flight / before the first load. */
  data: BedMeshData | null
  /** Human-readable failure from the last load or calibrate; '' when healthy. */
  error: string
  /** A GET /bed-mesh is in flight. */
  loading: boolean
  /** A calibrate is in flight, or its settle window has not elapsed yet. */
  calibrating: boolean
  /** Selected probe point for hover detail display. */
  selectedPoint: BedmeshProbePoint | null
  /** Historical mesh profiles. */
  meshHistory: Array<{ name: string; timestamp?: string }>
  /** Re-read the mesh. Safe to call at any time; supersedes any earlier read. */
  reload: () => Promise<void>
  /** Fire BED_MESH_CALIBRATE, then reload after CALIBRATE_RELOAD_DELAY_MS. */
  calibrate: () => Promise<void>
  /** Select a probe point for hover detail. */
  onSelectPoint: (point: BedmeshProbePoint | null) => void
}

/**
 * Extract bedmesh state from the useBedMesh hook.
 * This hook encapsulates all non-printer/printerId state needed by BedMeshDrawer.
 */
export function useBedmeshState(printerId: string): BedmeshState {
  const { data, error, loading, calibrating, reload, calibrate } = useBedMesh(printerId)
  const [selectedPoint, setSelectedPoint] = useState<BedmeshProbePoint | null>(null)

  // Derive mesh history from available profiles
  const meshHistory = useMemo(() => {
    if (!data?.profiles) return []
    return data.profiles.map((profile) => ({
      name: profile.name,
      timestamp: undefined,
    }))
  }, [data?.profiles])

  const onSelectPoint = useCallback((point: BedmeshProbePoint | null) => {
    setSelectedPoint(point)
  }, [])

  return {
    data,
    error,
    loading,
    calibrating,
    selectedPoint,
    meshHistory,
    reload,
    calibrate,
    onSelectPoint,
  }
}

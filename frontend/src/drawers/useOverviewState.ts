/**
 * useOverviewState — extracts all state management for the OverviewDrawer component.
 *
 * This hook encapsulates:
 * - Diagnostics and fleet metrics (provided via context)
 * - Spool management and exclude-objects state (via sub-hooks)
 * - Confirmation dialog dispatch
 * - OEE and anomaly data (from context)
 *
 * By centralizing this, the OverviewDrawer becomes a pure presentation layer
 * that only knows about printer and printerId (DrawerProps), while this hook
 * handles all data coordination.
 */

import { useCallback, useContext } from 'react'
import type {
  CurrentFileResponse,
  CvAnomaly,
  Diagnostics,
  FleetMetricCard,
  OeeDevice,
  Printer,
} from '../types/printer'
import type { ToastFn } from './useSpoolManagement'
import { useSpoolManagement } from './useSpoolManagement'
import { useExcludeObjects } from './useExcludeObjects'
import { AppDrawerContext } from '../context/AppContext'

export type OverviewState = {
  diagnostics: Diagnostics | null
  currentFileDetail: CurrentFileResponse | null
  metric: FleetMetricCard | null
  oee: OeeDevice | null | undefined
  cvAnomalies: CvAnomaly[]
  canWrite: boolean
  showOee: boolean
  showEmptyCapabilityTiles: boolean
  pushToast: ToastFn
  onConfirm: (state: { message: string; onConfirm: () => void }) => void
  spool: ReturnType<typeof useSpoolManagement>
  excludeObjects: ReturnType<typeof useExcludeObjects>
  confirmExclude: (name: string) => void
}

export function useOverviewState(
  printer: Printer | null,
  printerId: string,
): OverviewState {
  const drawerCtx = useContext(AppDrawerContext)
  if (!drawerCtx) throw new Error('useOverviewState must be used inside DrawerProvider')

  // Extract overview-specific state from context
  const {
    diagnostics,
    currentFileDetail,
    metric,
    oee,
    cvAnomalies,
    canWrite,
    showOee,
    showEmptyCapabilityTiles,
    pushToast,
    onConfirm,
  } = drawerCtx as unknown as {
    diagnostics: Diagnostics | null
    currentFileDetail: CurrentFileResponse | null
    metric: FleetMetricCard | null
    oee: OeeDevice | null | undefined
    cvAnomalies: CvAnomaly[]
    canWrite: boolean
    showOee: boolean
    showEmptyCapabilityTiles: boolean
    pushToast: ToastFn
    onConfirm: (state: { message: string; onConfirm: () => void }) => void
  }

  // Sub-hooks for spool and exclude-objects management
  const spool = useSpoolManagement(printerId, diagnostics || undefined, pushToast)
  const excludeObjects = useExcludeObjects(printerId)

  // Confirmation callback for exclude-objects operations
  const confirmExclude = useCallback(
    (name: string) => {
      onConfirm({
        message: `Exclude "${name}" from print?`,
        onConfirm: () => void excludeObjects.exclude(name),
      })
    },
    [onConfirm, excludeObjects],
  )

  return {
    diagnostics,
    currentFileDetail,
    metric,
    oee,
    cvAnomalies,
    canWrite,
    showOee,
    showEmptyCapabilityTiles,
    pushToast,
    onConfirm,
    spool,
    excludeObjects,
    confirmExclude,
  }
}

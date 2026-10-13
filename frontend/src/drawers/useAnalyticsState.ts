import { useMemo } from 'react'
import type { DrawerProps } from '../types/drawer-props'

type MetricsData = {
  completed_jobs: number
  failed_jobs: number
  cancelled_jobs: number
  success_rate: number | null
  total_print_time: number
  total_filament_used: number
  avg_print_time: number
}

/**
 * Custom hook to extract analytics state from DrawerProps
 * Manages currentMetric and oeeByDevice data for the AnalyticsDrawer
 */
export function useAnalyticsState(props: DrawerProps & { currentMetric?: MetricsData | null; oeeByDevice?: Map<string, unknown> }) {
  const { currentMetric, oeeByDevice } = props

  // Memoize to prevent unnecessary recalculations
  return useMemo(() => ({
    currentMetric: (currentMetric || null) as MetricsData | null,
    oeeByDevice: oeeByDevice || new Map(),
  }), [currentMetric, oeeByDevice])
}

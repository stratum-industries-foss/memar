import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useAnalyticsState } from './useAnalyticsState'

// Type definitions for metrics data
type MetricsData = {
  completed_jobs: number
  failed_jobs: number
  cancelled_jobs: number
  success_rate: number | null
  total_print_time: number
  total_filament_used: number
  avg_print_time: number
}

type OeeDeviceData = {
  device_id: string
  oee: number | null
  availability: number | null
  performance: number | null
  quality: number | null
  sample_jobs: number
}

const AnalyticsDrawer = React.memo(function AnalyticsDrawer({ printerId = '' }: DrawerProps) {
  const { currentMetric, oeeByDevice } = useAnalyticsState({ printerId })

  if (!currentMetric) {
    return (
      <section className="drawer-section">
        <h3>Device Analytics</h3>
        <div className="empty-state">
          <div className="empty-state-icon">📭</div>
          <h4>No analytics data yet</h4>
          <p>Run some prints to see analytics and OEE metrics.</p>
        </div>
      </section>
    )
  }

  const totalJobs = (currentMetric.completed_jobs ?? 0) + (currentMetric.failed_jobs ?? 0) + (currentMetric.cancelled_jobs ?? 0)
  const successRate = currentMetric.success_rate
  const oeeData = oeeByDevice?.get(printerId ?? '')

  return (
    <section className="drawer-section">
      <h3>Device Analytics</h3>
      <div className="kv-grid" style={{marginBottom: 20}}>
        <div><span>Total Jobs</span><strong>{totalJobs}</strong></div>
        <div><span>Success Rate</span><strong>{successRate != null ? `${successRate.toFixed(1)}%` : '—'}</strong></div>
        <div><span>Completed</span><strong>{currentMetric.completed_jobs ?? 0}</strong></div>
        <div><span>Failed</span><strong>{currentMetric.failed_jobs ?? 0}</strong></div>
        <div><span>Cancelled</span><strong>{currentMetric.cancelled_jobs ?? 0}</strong></div>
        <div><span>OEE</span><strong>{oeeData?.oee != null ? `${(oeeData.oee * 100).toFixed(1)}%` : '—'}</strong></div>
      </div>
      <div className="subtle" style={{fontSize: '0.85rem'}}>Data from last 24 hours</div>
    </section>
  )
})

export default AnalyticsDrawer

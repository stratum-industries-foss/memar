/**
 * OverviewGraphs — comprehensive charts for printer metrics and job history
 *
 * Includes:
 * - Success Rate (donut chart) — from currentMetric props
 * - Job History Timeline (line chart) — would fetch from /api/printers/{id}/metrics/history
 * - Print Time Distribution (bar chart) — would derive from history payload
 * - Filament Usage Trend (area chart) — would derive from history payload
 *
 * Since history endpoints don't yet exist, timeline/duration/filament gracefully
 * degrade to empty states.
 */

import React from 'react'
import {
  PieChart, Pie, Cell,
  Tooltip, ResponsiveContainer
} from 'recharts'
import styles from './OverviewGraphs.module.css'

interface OverviewGraphsProps {
  currentMetric?: {
    completed_jobs?: number | null
    failed_jobs?: number | null
    cancelled_jobs?: number | null
  } | null
  printerId?: string
}

/**
 * Success Rate Donut Chart — rendered from currentMetric props (completed/failed/cancelled)
 */
const SuccessRateChart: React.FC<{ metric?: OverviewGraphsProps['currentMetric'] }> = ({ metric }) => {
  const chartHeight = typeof window !== 'undefined' && window.innerWidth < 480 ? 200 : 250

  if (!metric) {
    return (
      <div className={styles['chart-container']}>
        <div className={styles['chart-empty']}>No metrics available</div>
      </div>
    )
  }

  const completed = metric.completed_jobs ?? 0
  const failed = metric.failed_jobs ?? 0
  const cancelled = metric.cancelled_jobs ?? 0
  const total = completed + failed + cancelled

  if (total === 0) {
    return (
      <div className={styles['chart-container']}>
        <div className={styles['chart-empty']}>No jobs yet</div>
      </div>
    )
  }

  const data = [
    { name: 'Completed', value: completed, fill: 'var(--color-success)' },
    { name: 'Failed', value: failed, fill: 'var(--color-danger)' },
    { name: 'Cancelled', value: cancelled, fill: 'var(--color-warning)' },
  ].filter(d => d.value > 0)

  const successPct = ((completed / total) * 100).toFixed(1)

  return (
    <div className={styles['chart-section']}>
      <h4>Success Rate</h4>
      <div className={styles['chart-container']} role="img" aria-label={`Success Rate Pie Chart showing ${completed} completed, ${failed} failed, and ${cancelled} cancelled jobs`}>
        <ResponsiveContainer width="100%" height={chartHeight}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={90}
              paddingAngle={2}
              dataKey="value"
            >
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.fill} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value) => [Number(value), 'Jobs']}
              contentStyle={{ background: 'var(--surface-base)', border: '1px solid var(--border-default)' }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className={styles['chart-stats']}>
        <div><strong>{successPct}%</strong> success rate</div>
        <div className={styles['stat-secondary']}>
          {completed} completed · {failed} failed · {cancelled} cancelled
        </div>
      </div>
    </div>
  )
}

/**
 * Job History Timeline — line chart over 30 days
 * Currently shows unavailable state (endpoint doesn't exist yet)
 */
const JobHistoryTimeline: React.FC<{ printerId?: string }> = ({ printerId }) => {
  // History endpoint doesn't exist yet — show unavailable state
  return (
    <div className={styles['chart-section']}>
      <h4>Job History <span className={styles['chart-label-sub']}>last 30 days</span></h4>
      <div className={styles['chart-container']}>
        <div className={styles['chart-empty']}>
          Charts unavailable — history endpoint not yet implemented
        </div>
      </div>
    </div>
  )
}

/**
 * Print Time Distribution — bar chart showing job duration buckets
 * Currently unavailable (derived from history endpoint)
 */
const PrintTimeDistribution: React.FC<{ printerId?: string }> = ({ printerId }) => {
  // History endpoint doesn't exist yet — show unavailable state
  return (
    <div className={styles['chart-section']}>
      <h4>Print Time Distribution</h4>
      <div className={styles['chart-container']}>
        <div className={styles['chart-empty']}>
          Charts unavailable — history endpoint not yet implemented
        </div>
      </div>
    </div>
  )
}

/**
 * Filament Usage Trend — area chart showing cumulative consumption over time
 * Currently unavailable (derived from history endpoint)
 */
const FilamentUsageTrend: React.FC<{ printerId?: string }> = ({ printerId }) => {
  // History endpoint doesn't exist yet — show unavailable state
  return (
    <div className={styles['chart-section']}>
      <h4>Filament Usage Trend</h4>
      <div className={styles['chart-container']}>
        <div className={styles['chart-empty']}>
          Charts unavailable — history endpoint not yet implemented
        </div>
      </div>
    </div>
  )
}

/**
 * Main OverviewGraphs component — renders all charts
 */
export const OverviewGraphs: React.FC<OverviewGraphsProps> = ({
  currentMetric,
  printerId,
}) => {
  return (
    <div className={styles['graphs-container']}>
      <SuccessRateChart metric={currentMetric} />
      <JobHistoryTimeline printerId={printerId} />
      <PrintTimeDistribution printerId={printerId} />
      <FilamentUsageTrend printerId={printerId} />
    </div>
  )
}

export default OverviewGraphs

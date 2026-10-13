import React, { useState } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useHistoryState } from './useHistoryState'
import { formatDuration, getStatusLabel, type HistorySortKey } from './useHistoryUtils'
import { formatTimestamp } from './formatUtils'

const HistoryDrawer: React.FC<DrawerProps> = ({ printerId = '' }) => {
  const { history, canWrite, onReprint, statusFilter, setStatusFilter, sortKey, setSortKey, jobs } =
    useHistoryState()
  const [selectedJob, setSelectedJob] = useState<string | null>(null)

  if (!history) {
    return (
      <section className="drawer-section">
        <h3>History</h3>
        <div className="empty-state">
          <div className="empty-state-icon">📊</div>
          <h4>No history available</h4>
          <p>Start a print to begin tracking jobs.</p>
        </div>
      </section>
    )
  }

  if (history.jobs.length === 0) {
    return (
      <section className="drawer-section">
        <h3>History</h3>
        <div className="empty-state">
          <div className="empty-state-icon">📭</div>
          <h4>No print history yet</h4>
          <p>Your completed prints will appear here.</p>
        </div>
      </section>
    )
  }

  const totalJobs = history.jobs.length
  const completedCount = history.jobs.filter((j) => j.status === 'completed').length
  const failedCount = history.jobs.filter((j) => j.status === 'failed').length
  const successRate = totalJobs > 0 ? ((completedCount / totalJobs) * 100).toFixed(1) : '0'

  const totalPrintTime = history.jobs.reduce((sum, job) => {
    if (job.duration) return sum + job.duration
    if (job.endTime && job.startTime) return sum + (job.endTime - job.startTime)
    return sum
  }, 0)

  const avgPrintTime = completedCount > 0 ? totalPrintTime / completedCount : 0

  return (
    <>
      <section className="drawer-section">
        <h3>History totals</h3>
        <div className="kv-grid">
          <div>
            <span>Total jobs</span>
            <strong>{totalJobs}</strong>
          </div>
          <div>
            <span>Completed</span>
            <strong>{completedCount}</strong>
          </div>
          <div>
            <span>Failed</span>
            <strong>{failedCount}</strong>
          </div>
          <div>
            <span>Success rate</span>
            <strong>{successRate}%</strong>
          </div>
          <div>
            <span>Total print time</span>
            <strong>{formatDuration(totalPrintTime)}</strong>
          </div>
          <div>
            <span>Avg print time</span>
            <strong>{formatDuration(avgPrintTime)}</strong>
          </div>
        </div>
      </section>

      <section className="drawer-section">
        <h3>Recent jobs</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{ flex: 1 }}
            aria-label="Filter jobs by status"
          >
            <option value="all">All statuses</option>
            <option value="completed">Completed only</option>
            <option value="failed">Failed only</option>
            <option value="cancelled">Cancelled only</option>
            <option value="in_progress">In Progress</option>
          </select>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as HistorySortKey)}
            style={{ flex: 1 }}
            aria-label="Sort jobs by"
          >
            <option value="date">Sort: Date (newest)</option>
            <option value="name">Sort: Filename</option>
            <option value="duration">Sort: Duration</option>
            <option value="status">Sort: Status</option>
          </select>
        </div>
        <div className="history-list">
          {jobs.length === 0 && <div className="subtle">No jobs match the current filter.</div>}
          {jobs.map((job, idx) => (
            <div
              key={`${job.filename ?? idx}-${job.startTime}`}
              className="history-row"
              style={{
                padding: '8px',
                borderBottom: '1px solid var(--border, #333)',
                cursor: 'pointer',
                background: selectedJob === job.filename ? 'var(--bg-2, #222)' : undefined,
              }}
              onClick={() => setSelectedJob(selectedJob === job.filename ? null : job.filename)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  setSelectedJob(selectedJob === job.filename ? null : job.filename)
                }
              }}
              aria-label={`Job: ${job.filename}`}
            >
              <div>
                <strong>{job.filename || 'Unknown file'}</strong>
                <div className="subtle small">
                  {getStatusLabel(job.status)} • print{' '}
                  {job.duration ? formatDuration(job.duration) : '—'} •{' '}
                  {formatTimestamp(job.endTime || job.startTime)}
                </div>
                {job.result && (
                  <div className="subtle small" style={{ marginTop: 4, color: 'var(--text-secondary, #888)' }}>
                    {job.result}
                  </div>
                )}
              </div>
              {canWrite && job.filename && (
                <div className="inline-actions" style={{ display: 'flex', gap: 6, alignItems: 'center', marginLeft: 'auto' }}>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      void onReprint(job.filename)
                    }}
                    style={{ whiteSpace: 'nowrap' }}
                    aria-label={`Reprint ${job.filename}`}
                  >
                    Reprint
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </>
  )
}

const MemoizedHistoryDrawer = React.memo(HistoryDrawer)

export default MemoizedHistoryDrawer

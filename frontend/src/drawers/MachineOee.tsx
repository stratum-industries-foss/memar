/**
 * MachineOee — displays OEE (Overall Equipment Effectiveness) metric
 * Supports both compact (single line) and full (dashboard card) variants
 */

import React from 'react'
import type { OeeDevice } from '../types/printer'

interface MachineOeeProps {
  oee: OeeDevice | null | undefined
  variant?: 'compact' | 'full'
}

/**
 * RAG (red-amber-green) banding per ISO/OEE convention.
 * `value` is a 0-100 number.
 */
function ragColor(
  value: number | null | undefined,
  opts: { green: number; amber: number; inverse?: boolean },
): string {
  if (value == null) return 'var(--text-secondary)'
  const ok = opts.inverse ? value <= opts.green : value >= opts.green
  const mid = opts.inverse ? value <= opts.amber : value >= opts.amber
  return ok ? 'var(--color-success)' : mid ? 'var(--color-warning)' : 'var(--color-danger)'
}

export const MachineOee: React.FC<MachineOeeProps> = ({ oee, variant = 'compact' }) => {
  if (!oee) return null

  const pct = (v: number | null, d = 0): string =>
    v == null ? '—' : `${(v * 100).toFixed(d)}%`

  const oeeC = ragColor(oee.oee == null ? null : oee.oee * 100, { green: 85, amber: 60 })

  if (variant === 'compact') {
    return (
      <div className="machine-oee machine-oee-compact">
        <span className="machine-oee-val" style={{ color: oeeC }}>
          OEE {pct(oee.oee)}
        </span>
        <span className="machine-oee-apq">
          A {pct(oee.availability)} · P {pct(oee.performance)} · Q {pct(oee.quality)}
        </span>
      </div>
    )
  }

  return (
    <div className="machine-oee machine-oee-full" style={{ borderLeftColor: oeeC }}>
      <div className="metric-label">Overall Equipment Effectiveness</div>
      <div className="machine-oee-big" style={{ color: oeeC }}>
        {pct(oee.oee, 1)}
      </div>
      <div className="machine-oee-grid">
        <div>
          <span className="moe-k">Availability</span>
          <span
            className="moe-v"
            style={{
              color: ragColor(oee.availability == null ? null : oee.availability * 100, {
                green: 90,
                amber: 75,
              }),
            }}
          >
            {pct(oee.availability)}
          </span>
        </div>
        <div>
          <span className="moe-k">Performance</span>
          <span
            className="moe-v"
            style={{
              color: ragColor(oee.performance == null ? null : oee.performance * 100, {
                green: 90,
                amber: 75,
              }),
            }}
          >
            {pct(oee.performance)}
          </span>
        </div>
        <div>
          <span className="moe-k">Quality</span>
          <span
            className="moe-v"
            style={{
              color: ragColor(oee.quality == null ? null : oee.quality * 100, {
                green: 95,
                amber: 85,
              }),
            }}
          >
            {pct(oee.quality)}
          </span>
        </div>
      </div>
      <div className="metric-note">
        {oee.sample_jobs} jobs sampled
        {oee.performance == null ? ' · performance n/a (no slicer estimate)' : ''}
      </div>
    </div>
  )
}

/**
 * CoolantMetricsGrid - Stats aggregation for coolant pressure
 *
 * Displays:
 * - Average PSI (24h)
 * - Minimum PSI (24h)
 * - Maximum PSI (24h)
 * - Sensor uptime % (last 7d)
 * - Color-coded status indicators
 */

import React from 'react'
import styles from './CoolantMetricsGrid.module.css'

interface CoolantMetricsGridProps {
  avg_psi: number | null
  min_psi: number | null
  max_psi: number | null
  uptime_percent: number
  last_update?: string
}

export function CoolantMetricsGrid({
  avg_psi,
  min_psi,
  max_psi,
  uptime_percent,
  last_update,
}: CoolantMetricsGridProps) {
  // Status helper - determine color zone
  const getStatusColor = (value: number | null) => {
    if (value === null) return 'gray'
    if (value < 20) return 'critical'
    if (value < 35) return 'warning'
    return 'nominal'
  }

  const getStatusLabel = (value: number | null) => {
    if (value === null) return 'No Data'
    if (value < 20) return 'Critical'
    if (value < 35) return 'Caution'
    return 'Nominal'
  }

  const getUptimeColor = (uptime: number) => {
    if (uptime >= 99) return 'excellent'
    if (uptime >= 95) return 'good'
    if (uptime >= 90) return 'fair'
    return 'poor'
  }

  return (
    <div className={styles['coolant-metrics-grid']}>
      <div className={styles['metric-grid-container']}>
        <h4 className={styles['metric-grid-title']}>Coolant Pressure Metrics</h4>

        {/* 33/33/67 asymmetric grid — card 3 (max PSI) spans 2 rows */}
        <div className={styles['metric-grid-inner']}>
          {/* Card 1: Average PSI */}
          <div className={`${styles['metric-card']} ${styles[getStatusColor(avg_psi)]}`}>
            <div className={styles['metric-label']}>24h Average</div>
            <div className={styles['metric-value']}>
              {avg_psi !== null ? avg_psi.toFixed(1) : '—'}
              {avg_psi !== null && <span className={styles['metric-unit']}>PSI</span>}
            </div>
            {avg_psi !== null && (
              <div className={styles['metric-status']}>{getStatusLabel(avg_psi)}</div>
            )}
            {last_update && (
              <div className={styles['metric-timestamp']}>
                Last update: {new Date(last_update).toLocaleTimeString()}
              </div>
            )}
          </div>

          {/* Card 2: Minimum PSI */}
          <div className={`${styles['metric-card']} ${styles[getStatusColor(min_psi)]}`}>
            <div className={styles['metric-label']}>24h Minimum</div>
            <div className={styles['metric-value']}>
              {min_psi !== null ? min_psi.toFixed(1) : '—'}
              {min_psi !== null && <span className={styles['metric-unit']}>PSI</span>}
            </div>
            {min_psi !== null && (
              <div className={styles['metric-status']}>{getStatusLabel(min_psi)}</div>
            )}
            <div className={styles['metric-timestamp']}>
              Lowest pressure recorded
            </div>
          </div>

          {/* Card 3: Maximum PSI — spans 2 rows (the 67 column, full height) */}
          <div className={`${styles['metric-card']} ${styles[getStatusColor(max_psi)]}`}>
            <div className={styles['metric-label']}>24h Maximum</div>
            <div className={styles['metric-value']}>
              {max_psi !== null ? max_psi.toFixed(1) : '—'}
              {max_psi !== null && <span className={styles['metric-unit']}>PSI</span>}
            </div>
            {max_psi !== null && (
              <div className={styles['metric-status']}>{getStatusLabel(max_psi)}</div>
            )}
            <div className={styles['metric-timestamp']}>
              Highest pressure recorded
            </div>
          </div>

          {/* Card 4: Uptime — sits in row 2, col 1 */}
          <div className={`${styles['metric-card']} ${styles[getUptimeColor(uptime_percent)]}`}>
            <div className={styles['metric-label']}>7d Sensor Uptime</div>
            <div className={styles['metric-value']}>
              {uptime_percent.toFixed(1)}
              <span className={styles['metric-unit']}>%</span>
            </div>
            <div className={styles['metric-status']}>
              {uptime_percent >= 99
                ? 'Excellent'
                : uptime_percent >= 95
                  ? 'Good'
                  : uptime_percent >= 90
                    ? 'Fair'
                    : 'Poor'}
            </div>
            <div className={styles['metric-timestamp']}>
              {uptime_percent < 100 && (
                <>
                  ~
                  {(10080 * (1 - uptime_percent / 100)).toFixed(0)}
                  {' '}
                  min downtime
                </>
              )}
            </div>
          </div>

          {/* Card 5: Whitespace block (negative space) — desktop only */}
          <div
            className={`${styles['metric-card']} ${styles['metric-card-whitespace']}`}
            aria-hidden="true"
          />
        </div>
      </div>
    </div>
  )
}

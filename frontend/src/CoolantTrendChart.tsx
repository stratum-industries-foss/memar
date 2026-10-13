/**
 * CoolantTrendChart - 24-hour PSI trend visualization
 *
 * Displays:
 * - Line chart of coolant PSI over 24 hours
 * - Red zone background for critical pressure (<20 PSI)
 * - Hover tooltip with exact timestamp + value
 * - X-axis: Time (00:00 → 24:00)
 * - Y-axis: PSI (0-100)
 */

import React, { useEffect, useState } from 'react'
import styles from './CoolantTrendChart.module.css'

interface TrendDataPoint {
  timestamp: string
  value: number
}

interface CoolantTrendChartProps {
  data: TrendDataPoint[]
  loading?: boolean
  error?: string
}

export function CoolantTrendChart({
  data,
  loading = false,
  error = '',
}: CoolantTrendChartProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  if (error) {
    return (
      <div className={styles['coolant-trend-error']}>
        <p>{error}</p>
      </div>
    )
  }

  if (loading || !data || data.length === 0) {
    return (
      <div className={styles['coolant-trend-container']}>
        <h3>24-Hour Trend</h3>
        <div className={styles['coolant-trend-empty']}>
          {loading ? 'Loading chart data...' : 'No data available'}
        </div>
      </div>
    )
  }

  // Calculate min/max for Y-axis scaling
  const values = data.map((d) => d.value).filter((v) => v !== null)
  const minValue = Math.min(...values, 0)
  const maxValue = Math.max(...values, 100)
  const yMin = Math.max(0, minValue - 5)
  const yMax = Math.min(100, maxValue + 5)

  const chartWidth = 600
  const chartHeight = 300
  const padding = { top: 20, right: 20, bottom: 40, left: 50 }
  const innerWidth = chartWidth - padding.left - padding.right
  const innerHeight = chartHeight - padding.top - padding.bottom

  // Scale functions
  const xScale = (index: number) =>
    padding.left + (index / (data.length - 1 || 1)) * innerWidth
  const yScale = (value: number) =>
    padding.top + innerHeight - ((value - yMin) / (yMax - yMin)) * innerHeight

  // Generate path for line chart
  let pathData = ''
  data.forEach((point, index) => {
    const x = xScale(index)
    const y = yScale(point.value)
    pathData += `${index === 0 ? 'M' : 'L'} ${x} ${y} `
  })

  // Generate time labels (every 4 hours)
  const timeLabels: { index: number; label: string }[] = []
  for (let i = 0; i < data.length; i += Math.max(1, Math.floor(data.length / 6))) {
    const date = new Date(data[i].timestamp)
    timeLabels.push({
      index: i,
      label: date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }),
    })
  }

  // Last data point for tooltip. `hoveredIndex` is state that can outlive a background
  // refresh to a SHORTER `data` array — clamp it to the current bounds so we never
  // index past the end (which would crash the render below).
  const safeHoveredIndex =
    hoveredIndex !== null ? Math.min(hoveredIndex, data.length - 1) : null
  const lastDataPoint =
    safeHoveredIndex !== null ? data[safeHoveredIndex] : data[data.length - 1]

  return (
    <div className={styles['coolant-trend-container']}>
      <h3>24-Hour Trend</h3>

      <div className={styles['coolant-trend-chart-wrapper']}>
        <svg
          className={styles['coolant-trend-svg']}
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          preserveAspectRatio="xMidYMid meet"
        >
          {/* Critical zone background (< 20 PSI) */}
          <rect
            x={padding.left}
            y={yScale(20)}
            width={innerWidth}
            height={yScale(0) - yScale(20)}
            className={styles['trend-critical-zone']}
          />

          {/* Grid lines */}
          {[0, 20, 40, 60, 80, 100].map((value) => {
            if (value < yMin || value > yMax) return null
            return (
              <line
                key={`grid-${value}`}
                x1={padding.left}
                y1={yScale(value)}
                x2={padding.left + innerWidth}
                y2={yScale(value)}
                className={styles['trend-grid-line']}
              />
            )
          })}

          {/* Axes */}
          <line
            x1={padding.left}
            y1={padding.top}
            x2={padding.left}
            y2={padding.top + innerHeight}
            className={styles['trend-axis-line']}
          />
          <line
            x1={padding.left}
            y1={padding.top + innerHeight}
            x2={padding.left + innerWidth}
            y2={padding.top + innerHeight}
            className={styles['trend-axis-line']}
          />

          {/* Y-axis labels */}
          {[0, 20, 40, 60, 80, 100].map((value) => {
            if (value < yMin || value > yMax) return null
            return (
              <text
                key={`y-label-${value}`}
                x={padding.left - 10}
                y={yScale(value)}
                className={styles['trend-axis-y-label']}
              >
                {value}
              </text>
            )
          })}

          {/* Line chart */}
          <path d={pathData} className={styles['trend-line']} />

          {/* Data points */}
          {data.map((point, index) => (
            <circle
              key={`point-${index}`}
              cx={xScale(index)}
              cy={yScale(point.value)}
              className={
                hoveredIndex === index ? styles['trend-point-hover'] : styles['trend-point']
              }
            />
          ))}

          {/* X-axis labels */}
          {timeLabels.map(({ index, label }) => (
            <text
              key={`x-label-${index}`}
              x={xScale(index)}
              y={padding.top + innerHeight + 20}
              className={styles['trend-axis-label']}
            >
              {label}
            </text>
          ))}
        </svg>

        {/* Interaction overlay for hover */}
        <svg
          className={styles['trend-interaction-layer']}
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          preserveAspectRatio="xMidYMid meet"
          onMouseMove={(e) => {
            const svg = e.currentTarget
            const rect = svg.getBoundingClientRect()
            const x = e.clientX - rect.left
            const relX = (x / rect.width) * chartWidth

            if (
              relX >= padding.left &&
              relX <= padding.left + innerWidth
            ) {
              const index = Math.round(
                ((relX - padding.left) / innerWidth) * (data.length - 1)
              )
              setHoveredIndex(Math.max(0, Math.min(index, data.length - 1)))
            }
          }}
          onMouseLeave={() => setHoveredIndex(null)}
        />
      </div>

      {/* Tooltip */}
      {hoveredIndex !== null && lastDataPoint && (
        <div className={styles['trend-tooltip']}>
          <div>
            {new Date(lastDataPoint.timestamp).toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              hour12: false,
            })}
          </div>
          <div className={styles['trend-tooltip-value']}>
            {lastDataPoint.value.toFixed(1)} PSI
          </div>
        </div>
      )}

      <div className={styles['trend-legend']}>
        <div className={styles['trend-legend-item']}>
          <div
            className={styles['trend-legend-color']}
            style={{ background: 'var(--accent-solid)' }}
          />
          <span>Pressure (PSI)</span>
        </div>
        <div className={styles['trend-legend-item']}>
          <div
            className={styles['trend-legend-color']}
            style={{ background: 'color-mix(in srgb, var(--color-danger) 30%, transparent)' }}
          />
          <span>Critical Zone (&lt;20 PSI)</span>
        </div>
      </div>
    </div>
  )
}

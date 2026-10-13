/**
 * CoolantPSIGauge - SVG-based pressure gauge with animated needle
 *
 * Displays:
 * - Animated needle showing current PSI (0-100 range)
 * - Color zones: Red (<20), Yellow (20-35), Green (>35)
 * - Digital readout of current PSI value
 * - Last update timestamp
 * - Sensor status indicator (online/offline)
 */

import React, { useEffect, useState } from 'react'
import styles from './CoolantPSIGauge.module.css'

interface CoolantPSIGaugeProps {
  coolant_psi: number | null
  last_update: string
  sensor_status?: 'online' | 'offline'
}

export function CoolantPSIGauge({
  coolant_psi,
  last_update,
  sensor_status = 'online',
}: CoolantPSIGaugeProps) {
  const [animatedValue, setAnimatedValue] = useState(0)

  // Animate needle to current PSI value
  useEffect(() => {
    if (coolant_psi === null) {
      setAnimatedValue(0)
      return
    }

    // Animate from current to target value over 300ms
    let startValue = animatedValue
    let startTime = Date.now()
    const duration = 300

    const animate = () => {
      const now = Date.now()
      const progress = Math.min((now - startTime) / duration, 1)
      const newValue = startValue + (coolant_psi - startValue) * progress

      setAnimatedValue(newValue)

      if (progress < 1) {
        requestAnimationFrame(animate)
      }
    }

    requestAnimationFrame(animate)
  }, [coolant_psi])

  // Determine color zone
  const getColorZone = (value: number | null) => {
    if (value === null) return 'gray'
    if (value < 20) return 'red'
    if (value < 35) return 'yellow'
    return 'green'
  }

  // Convert PSI to angle (0-270 degrees, starting from bottom-left)
  const psiToAngle = (value: number) => {
    const maxPSI = 100
    const maxAngle = 270
    const minAngle = -90
    return minAngle + (Math.min(value, maxPSI) / maxPSI) * maxAngle
  }

  const needleAngle = psiToAngle(animatedValue)
  const colorZone = getColorZone(coolant_psi)

  // Determine value display color class
  let valueColorClass = styles['value-null']
  if (coolant_psi !== null) {
    if (coolant_psi < 20) {
      valueColorClass = styles['value-danger']
    } else if (coolant_psi < 35) {
      valueColorClass = styles['value-warning']
    } else {
      valueColorClass = styles['value-success']
    }
  }

  return (
    <div className={styles['coolant-psi-gauge']}>
      <div className={styles['gauge-header']}>
        <h3>Coolant Pressure</h3>
      </div>

      <div
        className={`${styles['gauge-container']} ${coolant_psi === null ? styles['gauge-offline'] : ''}`}
      >
        <svg className={styles['gauge-svg']} viewBox="0 0 240 240">
          {/* Gauge background circle */}
          <circle cx="120" cy="120" r="110" className={styles['gauge-background']} />

          {/* Color zones */}
          <path
            d="M 120 10 A 110 110 0 0 1 205.78 25.53 L 120 120 Z"
            className={styles['gauge-zone-red']}
          />
          <path
            d="M 205.78 25.53 A 110 110 0 0 1 230 120 L 120 120 Z"
            className={styles['gauge-zone-yellow']}
          />
          <path
            d="M 230 120 A 110 110 0 0 1 10 120 L 120 120 Z"
            className={styles['gauge-zone-green']}
          />

          {/* Tick marks and labels */}
          {[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map((tick) => {
            const angle = psiToAngle(tick)
            const rad = (angle * Math.PI) / 180
            const x1 = 120 + 100 * Math.cos(rad)
            const y1 = 120 + 100 * Math.sin(rad)
            const x2 = 120 + 110 * Math.cos(rad)
            const y2 = 120 + 110 * Math.sin(rad)
            const labelX = 120 + 85 * Math.cos(rad)
            const labelY = 120 + 85 * Math.sin(rad)

            return (
              <g key={`tick-${tick}`}>
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  className={styles['gauge-tick']}
                />
                {tick % 20 === 0 && (
                  <text
                    x={labelX}
                    y={labelY}
                    className={styles['gauge-tick-label']}
                  >
                    {tick}
                  </text>
                )}
              </g>
            )
          })}

          {/* Needle */}
          <g
            className={styles['gauge-needle']}
            style={{
              transform: `rotate(${needleAngle}deg)`,
            }}
          >
            <line x1="120" y1="120" x2="120" y2="30" strokeWidth="3" />
          </g>

          {/* Center circle */}
          <circle cx="120" cy="120" r="8" className={styles['gauge-center']} />
        </svg>
      </div>

      <div className={styles['gauge-readout']}>
        <div className={`${styles['gauge-value-display']} ${valueColorClass}`}>
          {coolant_psi === null ? '—' : coolant_psi.toFixed(1)}
          <span className={styles['gauge-unit']}>PSI</span>
        </div>
      </div>

      <div className={styles['gauge-status']}>
        <div className={`${styles['status-indicator']} ${sensor_status === 'online' ? styles['online'] : styles['offline']}`} />
        <span>{sensor_status === 'online' ? 'Sensor Online' : 'Sensor Offline'}</span>
      </div>

      {last_update && (
        <div className={styles['gauge-timestamp']}>
          Updated: {new Date(last_update).toLocaleTimeString()}
        </div>
      )}
    </div>
  )
}

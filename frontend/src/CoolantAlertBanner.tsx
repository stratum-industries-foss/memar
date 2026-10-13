/**
 * CoolantAlertBanner - Critical pressure alert notification
 *
 * Displays:
 * - Dismissible banner when coolant PSI < 20 for ≥5 min
 * - Alert message with current PSI and threshold
 * - Dismiss button (auto-re-shows if still critical)
 * - Optional "View history" link to trend chart
 */

import React, { useEffect, useState } from 'react'
import styles from './CoolantAlertBanner.module.css'

interface CoolantAlertBannerProps {
  coolant_psi: number | null
  alert_active: boolean
  duration_minutes?: number
  onDismiss?: () => void
  onViewHistory?: () => void
}

export function CoolantAlertBanner({
  coolant_psi,
  alert_active,
  duration_minutes = 0,
  onDismiss,
  onViewHistory,
}: CoolantAlertBannerProps) {
  const [dismissed, setDismissed] = useState(false)
  const [dismissCountdown, setDismissCountdown] = useState(0)

  // Reset dismissal when alert becomes inactive
  useEffect(() => {
    if (!alert_active) {
      setDismissed(false)
      setDismissCountdown(0)
    }
  }, [alert_active])

  // Countdown timer for auto-re-show after 5 minutes
  useEffect(() => {
    if (!dismissed || dismissCountdown <= 0) return

    const interval = setInterval(() => {
      setDismissCountdown((prev) => {
        if (prev <= 1) {
          setDismissed(false)
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(interval)
  }, [dismissed, dismissCountdown])

  const handleDismiss = () => {
    setDismissed(true)
    setDismissCountdown(5 * 60) // 5 minutes
    onDismiss?.()
  }

  // Don't show if not critical or dismissed
  if (!alert_active || dismissed || coolant_psi === null || coolant_psi >= 20) {
    return null
  }

  return (
    <div className={styles['coolant-alert-banner']}>
      <div className={styles['alert-content']}>
        <div className={styles['alert-icon']}>⚠️</div>
        <div className={styles['alert-message']}>
          <div className={styles['alert-title']}>Coolant Pressure Critical!</div>
          <div className={styles['alert-description']}>
            Current pressure: <strong>{coolant_psi.toFixed(1)} PSI</strong> (threshold: 20 PSI)
            {duration_minutes > 0 && <span> • Critical for {duration_minutes} min</span>}
          </div>
        </div>
      </div>

      <div className={styles['alert-actions']}>
        {onViewHistory && (
          <button
            className={`${styles['alert-button']} ${styles['alert-button-history']}`}
            onClick={onViewHistory}
            title="View 24-hour pressure history"
          >
            View History
          </button>
        )}
        <button
          className={`${styles['alert-button']} ${styles['alert-button-dismiss']}`}
          onClick={handleDismiss}
          title="Dismiss for 5 minutes (will re-appear if still critical)"
        >
          Dismiss
        </button>
      </div>

      {dismissed && dismissCountdown > 0 && (
        <div className={styles['alert-countdown']}>
          Re-show in {Math.ceil(dismissCountdown / 60)} min
        </div>
      )}
    </div>
  )
}

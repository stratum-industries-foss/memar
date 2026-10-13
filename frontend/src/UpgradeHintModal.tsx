import React, { useEffect, useState } from 'react'
import { apiFetch } from './api'
import { Modal } from './Modal'

interface UpgradeHintData {
  show: boolean
  current?: number
  limit?: number
  next_tier?: string
  next_limit?: number
  next_price_monthly?: number
}

export const UpgradeHintModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [data, setData] = useState<UpgradeHintData | null>(null)
  const [loading, setLoading] = useState(true)
  const [checkoutLoading, setCheckoutLoading] = useState(false)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)

  // Escape key handled by Modal component

  useEffect(() => {
    const fetchHint = async () => {
      try {
        const response = await apiFetch('/api/license/upgrade-hint')
        if (response.ok) {
          const data = await response.json() as UpgradeHintData
          setData(data)
        }
      } catch (err) {
        console.error('Failed to fetch upgrade hint:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchHint()
  }, [])

  if (loading || !data?.show) {
    return null
  }

  const tierNames: Record<string, string> = {
    maker: 'Maker',
    pro: 'Pro',
    farm: 'Farm',
    scale: 'Scale',
  }

  const nextTierName = tierNames[data.next_tier || ''] || data.next_tier

  const isOpen = data?.show ?? false

  const handleUpgrade = async () => {
    if (checkoutLoading) return
    setCheckoutError(null)
    setCheckoutLoading(true)
    try {
      const res = await apiFetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tier: data.next_tier,
          billing_period: 'monthly',
        }),
      })
      if (!res.ok) {
        let detail = 'Unable to start checkout. Please try again.'
        try {
          const body = (await res.json()) as { detail?: string }
          if (body?.detail) detail = body.detail
        } catch {
          // Non-JSON error body (e.g. 503) — keep the generic message
        }
        setCheckoutError(detail)
        return
      }
      const body = (await res.json()) as { checkout_url: string }
      window.location.href = body.checkout_url
    } catch (err) {
      console.error('Checkout failed:', err)
      setCheckoutError('Unable to start checkout. Please try again.')
    } finally {
      setCheckoutLoading(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Device limit reached">
      <div className="upgrade-hint-header">
        <p className="upgrade-hint-usage">
          You're using {data.current} of {data.limit} devices
        </p>
      </div>

      <div className="upgrade-hint-comparison">
        <div className="comparison-box">
          <span className="comparison-label">Current</span>
          <span className="comparison-value">{data.limit}</span>
          <span className="comparison-unit">devices</span>
        </div>
        <div className="comparison-arrow">→</div>
        <div className="comparison-box highlight">
          <span className="comparison-label">{nextTierName}</span>
          <span className="comparison-value">{data.next_limit}</span>
          <span className="comparison-unit">devices</span>
        </div>
      </div>

      <div className="upgrade-hint-price">
        <span className="price-amount">${data.next_price_monthly}</span>
        <span className="price-period">/mo</span>
      </div>

      <div className="upgrade-hint-features">
        <p className="upgrade-hint-text">
          Upgrade to the {nextTierName} tier to add {data.next_limit! - data.limit!} more devices.
        </p>
      </div>

      {checkoutError && (
        <div className="upgrade-hint-error" role="alert">
          {checkoutError}
        </div>
      )}

      <div className="modal-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleUpgrade}
          disabled={checkoutLoading}
        >
          {checkoutLoading ? 'Starting checkout…' : 'Upgrade now →'}
        </button>
        <button className="btn btn-ghost" onClick={onClose} disabled={checkoutLoading}>
          Dismiss
        </button>
      </div>

    </Modal>
  )
}

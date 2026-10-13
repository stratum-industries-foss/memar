import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { describe, it, expect } from 'vitest'
import { CoolantAlertBanner } from '../CoolantAlertBanner'

// Lets the test flip alert_active — proving the banner's OWN dismiss/recovery
// lifecycle works. This is the exact capability CoolantMetricsPanel must NOT
// destroy by unmounting the banner behind a parent-level dismiss flag.
function BannerHarness() {
  const [psi, setPsi] = useState(10)
  const [active, setActive] = useState(true)
  return (
    <div>
      <button data-testid="recover" onClick={() => { setPsi(50); setActive(false) }}>
        recover
      </button>
      <button data-testid="breach" onClick={() => { setPsi(10); setActive(true) }}>
        breach
      </button>
      <CoolantAlertBanner coolant_psi={psi} alert_active={active} />
    </div>
  )
}

describe('Coolant alert banner lifecycle', () => {
  it('re-shows a fresh critical alert after dismiss + recovery + re-breach', () => {
    render(<BannerHarness />)
    expect(screen.getByText(/Coolant Pressure Critical/)).toBeInTheDocument()

    fireEvent.click(screen.getByText('Dismiss'))
    expect(screen.queryByText(/Coolant Pressure Critical/)).toBeNull()

    // Pressure recovers, then breaches again — the banner must reappear.
    fireEvent.click(screen.getByTestId('recover'))
    fireEvent.click(screen.getByTestId('breach'))
    expect(screen.getByText(/Coolant Pressure Critical/)).toBeInTheDocument()
  })
})

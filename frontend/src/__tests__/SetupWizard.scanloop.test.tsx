import { render } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Preserve real exports; only stub apiFetch so a zero-result scan is deterministic.
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    apiFetch: vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ results: [] }),
    })),
  }
})

import { SetupWizard } from '../SetupWizard'
import { apiFetch } from '../api'

const mockedFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

describe('SetupWizard network scan', () => {
  beforeEach(() => mockedFetch.mockClear())

  it('scans exactly once when the network returns zero devices (no infinite loop)', async () => {
    render(<SetupWizard isOpen onClose={() => {}} />)

    // Let the initial scan settle, plus extra ticks. A looping effect keeps
    // re-firing /api/onboarding/scan after every zero-result return.
    await new Promise((r) => setTimeout(r, 100))

    const scanCalls = mockedFetch.mock.calls.filter((c) =>
      String(c[0]).includes('/api/onboarding/scan')
    )
    expect(scanCalls.length).toBe(1)
  })
})

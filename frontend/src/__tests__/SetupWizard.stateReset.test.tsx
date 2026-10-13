import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    apiFetch: vi.fn(async () => ({
      ok: true, status: 200, statusText: 'OK', json: async () => ({ results: [] }),
    })),
  }
})

import { SetupWizard } from '../SetupWizard'

describe('SetupWizard state reset on close/reopen', () => {
  it('discards a half-filled draft when closed and reopened', async () => {
    const { rerender } = render(<SetupWizard isOpen onClose={() => {}} />)

    // Reach the review step and type a device name.
    fireEvent.click(await screen.findByText('Add device manually'))
    fireEvent.change(screen.getByPlaceholderText('My Printer'), {
      target: { value: 'Draft Printer' },
    })
    expect(screen.queryByDisplayValue('Draft Printer')).toBeInTheDocument()

    // Close, then reopen (same mounted component instance — state persists in the bug).
    rerender(<SetupWizard isOpen={false} onClose={() => {}} />)
    rerender(<SetupWizard isOpen onClose={() => {}} />)

    // Should reopen fresh on the scan step, with no stale draft.
    await waitFor(() => {
      expect(screen.getByText('Add device manually')).toBeInTheDocument()
    })
    expect(screen.queryByDisplayValue('Draft Printer')).toBeNull()
  })
})

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, apiFetch: vi.fn() }
})

import { SetupWizard } from '../SetupWizard'
import { apiFetch } from '../api'

const mockedFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

describe('SetupWizard handleAddDevice error handling', () => {
  it('shows an error (not a stuck spinner) when the add request throws', async () => {
    mockedFetch.mockImplementation(async (url: string) => {
      if (String(url).includes('/api/onboarding/scan')) {
        return { ok: true, status: 200, statusText: 'OK', json: async () => ({ results: [] }) }
      }
      if (String(url).includes('/api/printers/add')) {
        throw new Error('Network down')
      }
      return { ok: true, status: 200, statusText: 'OK', json: async () => ({}) }
    })

    render(<SetupWizard isOpen onClose={() => {}} />)

    // Go to the manual "Device details" step.
    fireEvent.click(await screen.findByText('Add device manually'))

    // Fill the three required fields (matched by their placeholders).
    fireEvent.change(screen.getByPlaceholderText('http://192.168.1.100:7125'), {
      target: { value: 'http://x:1' },
    })
    fireEvent.change(screen.getByPlaceholderText('My Printer'), {
      target: { value: 'My Printer' },
    })
    fireEvent.change(screen.getByPlaceholderText('printer_1'), {
      target: { value: 'printer_1' },
    })

    // Click the modal primary action "Add device".
    fireEvent.click(screen.getByText('Add device'))

    await waitFor(() => {
      expect(screen.getByText(/Add failed:/)).toBeInTheDocument()
    })
    // Must not remain stuck on the in-flight message.
    expect(screen.queryByText('Adding device…')).toBeNull()
  })
})

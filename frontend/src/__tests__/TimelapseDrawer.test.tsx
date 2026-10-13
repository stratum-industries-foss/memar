/**
 * TimelapseDrawer.test.tsx
 * Tests for timelapse file browser and playback
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import React from 'react'
import TimelapseDrawer from '../drawers/TimelapseDrawer'
import * as api from '../api'

// Mock apiFetch
vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof api>('../api')
  return {
    ...actual,
    apiFetch: vi.fn(),
  }
})

// Stub URL.createObjectURL and URL.revokeObjectURL for jsdom
// In test environment, these may not be available; we mock them
beforeEach(() => {
  if (typeof URL.createObjectURL === 'undefined') {
    Object.defineProperty(URL, 'createObjectURL', {
      value: vi.fn(() => 'blob:mock-url'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: vi.fn(),
    })
  }
})

const mockTimelapseResponse = {
  configured: true,
  source_dir: '/home/pi/timelapse',
  entries: [
    {
      id: 'timelapse-1',
      name: 'print_001.mp4',
      kind: 'video' as const,
      size: 15728640,
      modified: Math.floor(Date.now() / 1000) - 3600,
    },
    {
      id: 'timelapse-2',
      name: 'print_002.jpg',
      kind: 'image' as const,
      size: 2097152,
      modified: Math.floor(Date.now() / 1000) - 7200,
    },
  ],
}

describe('TimelapseDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering and State', () => {
    it('renders without crashing when printerId is provided', () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockTimelapseResponse,
      } as any)

      const { container } = render(
        <TimelapseDrawer printerId="test-printer" />
      )
      expect(container).toBeInTheDocument()
    })

    it('returns null when printerId is not provided', () => {
      const { container } = render(<TimelapseDrawer />)
      expect(container.firstChild).toBeNull()
    })

    it('displays loading state initially', async () => {
      vi.mocked(api.apiFetch).mockImplementationOnce(() =>
        new Promise(() => {}) // never resolves
      )

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        expect(screen.getByText('Loading…')).toBeInTheDocument()
      })
    })

    it('displays timelapse list when data loads', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockTimelapseResponse,
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        expect(screen.getByText('print_001.mp4')).toBeInTheDocument()
        expect(screen.getByText('print_002.jpg')).toBeInTheDocument()
      })
    })

    it('displays not configured message when timelapse disabled', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          configured: false,
          source_dir: null,
          entries: [],
        }),
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        expect(screen.getByText(/No timelapse directory is configured/)).toBeInTheDocument()
      })
    })

    it('displays feature availability notes', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockTimelapseResponse,
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        expect(screen.getByText(/Frame rate, resolution, and enable\/disable/)).toBeInTheDocument()
      })
    })
  })

  describe('User Interactions', () => {
    it('calls reload when Refresh button is clicked', async () => {
      vi.mocked(api.apiFetch).mockResolvedValue({
        ok: true,
        json: async () => mockTimelapseResponse,
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      const refreshButton = await screen.findByLabelText('Refresh timelapse list')
      fireEvent.click(refreshButton)

      await waitFor(() => {
        expect(vi.mocked(api.apiFetch)).toHaveBeenCalledWith(
          '/api/printers/test-printer/timelapse?limit=12'
        )
      })
    })

    it('allows playback speed adjustment', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockTimelapseResponse,
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      // Wait for entries to load, which shows the playback speed control
      await waitFor(() => {
        expect(screen.getByText('print_001.mp4')).toBeInTheDocument()
      })

      const speedSelect = screen.getByLabelText('Playback speed') as HTMLSelectElement
      expect(speedSelect.value).toBe('1')

      fireEvent.change(speedSelect, { target: { value: '2' } })
      expect(speedSelect.value).toBe('2')
    })

    it('displays video load button for video entries', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockTimelapseResponse,
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        const loadButtons = screen.getAllByText(/Load video/)
        expect(loadButtons.length).toBeGreaterThan(0)
      })
    })

    it('displays download button for all entries', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockTimelapseResponse,
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        const downloadButtons = screen.getAllByText(/Download/)
        expect(downloadButtons.length).toBeGreaterThanOrEqual(2)
      })
    })
  })

  describe('Error Handling', () => {
    it('displays error message when API call fails', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: false,
        statusText: 'Server error',
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        expect(screen.getByText(/Failed to load timelapse/)).toBeInTheDocument()
      })
    })

    it('displays error when fetch throws', async () => {
      vi.mocked(api.apiFetch).mockRejectedValueOnce(new Error('Network timeout'))

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        expect(screen.getByText(/Network timeout/)).toBeInTheDocument()
      })
    })

    it('displays empty state when no timelapse entries', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          configured: true,
          source_dir: '/home/pi/timelapse',
          entries: [],
        }),
      } as any)

      render(<TimelapseDrawer printerId="test-printer" />)

      await waitFor(() => {
        expect(screen.getByText(/No recent timelapse artifacts found/)).toBeInTheDocument()
      })
    })
  })
})

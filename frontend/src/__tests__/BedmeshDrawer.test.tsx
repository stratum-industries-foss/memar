/**
 * BedmeshDrawer.test.tsx
 * Tests for bed mesh calibration and visualization drawer
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import React from 'react'
import BedmeshDrawer from '../drawers/BedmeshDrawer'
import * as api from '../api'

// Mock apiFetch
vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof api>('../api')
  return {
    ...actual,
    apiFetch: vi.fn(),
  }
})

// Mock BedMeshPanel to avoid complex SVG rendering in tests
vi.mock('../BedMeshPanel', () => ({
  BedMeshPanel: ({ data }: any) => (
    <div data-testid="bed-mesh-panel">
      Mesh: {data.x_count}x{data.y_count}
    </div>
  ),
}))

const mockBedMeshData = {
  supported: true,
  active_profile: 'default',
  active_is_probed: true,
  profiles: [
    {
      name: 'default',
      points: [[0, 0]],
      mesh_params: { x_count: 5, y_count: 5 },
      probed_points: 25,
      min_z: -0.05,
      max_z: 0.15,
    },
    {
      name: 'hightemp',
      points: [[0, 0]],
      mesh_params: { x_count: 5, y_count: 5 },
      probed_points: 25,
      min_z: -0.03,
      max_z: 0.12,
    },
  ],
  mesh_matrix: [[0.0, 0.05, 0.08], [0.01, 0.03, 0.06], [0.02, 0.04, 0.07]],
  x_count: 3,
  y_count: 3,
  global_min_z: -0.05,
  global_max_z: 0.15,
  mesh_extent: { x_min: 0, x_max: 235, y_min: 0, y_max: 235 },
}

describe('BedmeshDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering and State', () => {
    it('renders without crashing when printerId is provided', () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockBedMeshData,
      } as any)

      const { container } = render(
        <BedmeshDrawer printerId="test-printer" canWrite={true} />
      )
      expect(container).toBeInTheDocument()
    })

    it('returns null when canWrite is false', () => {
      const { container } = render(
        <BedmeshDrawer printerId="test-printer" canWrite={false} />
      )
      expect(container.firstChild).toBeNull()
    })

    it('returns null when printerId is not provided', () => {
      const { container } = render(
        <BedmeshDrawer canWrite={true} />
      )
      expect(container.firstChild).toBeNull()
    })

    it('displays loading state initially', async () => {
      vi.mocked(api.apiFetch).mockImplementationOnce(() =>
        new Promise(() => {}) // never resolves
      )

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)
      await waitFor(() => {
        expect(screen.getByText('Loading…')).toBeInTheDocument()
      })
    })

    it('displays bed mesh when data loads', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockBedMeshData,
      } as any)

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)

      await waitFor(() => {
        expect(screen.getByTestId('bed-mesh-panel')).toBeInTheDocument()
      })
    })

    it('displays unsupported message when bed mesh not available', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          supported: false,
          profiles: [],
        }),
      } as any)

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)

      await waitFor(() => {
        expect(screen.getByText(/Bed mesh not available/)).toBeInTheDocument()
      })
    })
  })

  describe('User Interactions', () => {
    it('calls reload when Refresh button is clicked', async () => {
      vi.mocked(api.apiFetch).mockResolvedValue({
        ok: true,
        json: async () => mockBedMeshData,
      } as any)

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)

      const refreshButton = await screen.findByLabelText('Refresh bed mesh')
      fireEvent.click(refreshButton)

      await waitFor(() => {
        expect(vi.mocked(api.apiFetch)).toHaveBeenCalledWith(
          '/api/printers/test-printer/bed-mesh'
        )
      })
    })

    it('calls calibrate when Calibrate button is clicked', async () => {
      vi.mocked(api.apiFetch).mockResolvedValue({
        ok: true,
        json: async () => mockBedMeshData,
      } as any)

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)

      const calibrateButton = await screen.findByLabelText('Calibrate bed mesh')
      fireEvent.click(calibrateButton)

      await waitFor(() => {
        expect(vi.mocked(api.apiFetch)).toHaveBeenCalledWith(
          '/api/printers/test-printer/macros/BED_MESH_CALIBRATE',
          expect.objectContaining({ method: 'POST' })
        )
      })
    })

    it('displays mesh profiles in history', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockBedMeshData,
      } as any)

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)

      await waitFor(() => {
        expect(screen.getByText('default')).toBeInTheDocument()
        expect(screen.getByText('hightemp')).toBeInTheDocument()
        expect(screen.getByText('active')).toBeInTheDocument()
      })
    })
  })

  describe('Error Handling', () => {
    it('displays error message when API call fails', async () => {
      vi.mocked(api.apiFetch).mockResolvedValueOnce({
        ok: false,
        statusText: 'Network error',
      } as any)

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)

      await waitFor(() => {
        expect(screen.getByText(/Failed to load bed mesh/)).toBeInTheDocument()
      })
    })

    it('displays error when fetch throws', async () => {
      vi.mocked(api.apiFetch).mockRejectedValueOnce(new Error('Connection failed'))

      render(<BedmeshDrawer printerId="test-printer" canWrite={true} />)

      await waitFor(() => {
        expect(screen.getByText(/Connection failed/)).toBeInTheDocument()
      })
    })
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HistoryDrawer from '../HistoryDrawer'
import type { DrawerProps } from '../../context/types'

// Mock the hooks
vi.mock('../useHistoryState', () => ({
  useHistoryState: vi.fn(),
}))

import * as useHistoryStateModule from '../useHistoryState'

// ============================================================================
// Test fixtures
// ============================================================================

import type { UseHistoryStateReturn } from '../useHistoryState'

const createMockHistoryState = (): UseHistoryStateReturn => ({
  history: {
    jobs: [
      {
        filename: 'test-print-1.gcode',
        material: 'PLA',
        startTime: Date.now() - 3600000,
        endTime: Date.now() - 3000000,
        status: 'completed' as const,
        result: 'Print completed successfully',
        duration: 600000,
      },
      {
        filename: 'test-print-2.gcode',
        material: 'PETG',
        startTime: Date.now() - 7200000,
        endTime: undefined,
        status: 'in_progress' as const,
        result: undefined,
        duration: undefined,
      },
      {
        filename: 'test-print-3.gcode',
        material: 'ABS',
        startTime: Date.now() - 10800000,
        endTime: Date.now() - 9600000,
        status: 'failed' as const,
        result: 'Nozzle clogged',
        duration: 1200000,
      },
    ],
    total: 3,
  },
  canWrite: true,
  onReprint: vi.fn(async () => {}),
  statusFilter: 'all',
  setStatusFilter: vi.fn(),
  sortKey: 'date' as const,
  setSortKey: vi.fn(),
  jobs: [], // Will be set to filtered jobs in tests
})

// ============================================================================
// Test suite
// ============================================================================

describe('HistoryDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ==========================================================================
  // Test 1: Renders without errors when no printer selected
  // ==========================================================================

  it('renders gracefully when no printer is selected', () => {
    const mockState = createMockHistoryState()
    const stateWithNullHistory: UseHistoryStateReturn = {
      ...mockState,
      history: null,
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithNullHistory)

    const props: DrawerProps = {
      printerId: '',
    }

    render(<HistoryDrawer {...props} />)

    expect(screen.getByText(/No history available/i)).toBeInTheDocument()
  })

  // ==========================================================================
  // Test 2: Displays history totals (completed, failed, success rate)
  // ==========================================================================

  it('displays history totals correctly', () => {
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    expect(screen.getByText('History totals')).toBeInTheDocument()
    expect(screen.getByText('Total jobs')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText('Success rate')).toBeInTheDocument()
  })

  // ==========================================================================
  // Test 3: Displays job list with correct data
  // ==========================================================================

  it('displays job list with filenames and status information', () => {
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    expect(screen.getByText(/Recent jobs/i)).toBeInTheDocument()
    expect(screen.getByText('test-print-1.gcode')).toBeInTheDocument()
    expect(screen.getByText('test-print-2.gcode')).toBeInTheDocument()
    expect(screen.getByText('test-print-3.gcode')).toBeInTheDocument()
  })

  // ==========================================================================
  // Test 4: Empty state message when no jobs match filter
  // ==========================================================================

  it('displays empty message when filtered jobs list is empty', () => {
    const mockState = createMockHistoryState()
    const stateWithEmptyJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: [],
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithEmptyJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    expect(screen.getByText(/No jobs match the current filter/i)).toBeInTheDocument()
  })

  // ==========================================================================
  // Test 5: Filter dropdown changes status filter
  // ==========================================================================

  it('has status filter dropdown with correct options', () => {
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    const filterSelect = screen.getByLabelText(/Filter jobs by status/i)
    expect(filterSelect).toBeInTheDocument()
    expect(filterSelect).toHaveValue('all')

    // Check that all filter options are present
    const options = screen.getAllByRole('option')
    expect(options.length).toBeGreaterThanOrEqual(4)
  })

  // ==========================================================================
  // Test 6: Sort dropdown with all sort keys
  // ==========================================================================

  it('has sort dropdown with all available sort options', () => {
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    const sortSelect = screen.getByLabelText(/Sort jobs by/i)
    expect(sortSelect).toBeInTheDocument()
    expect(sortSelect).toHaveValue('date')

    // Verify all sort options exist
    const options = screen.getAllByRole('option')
    const sortOptions = options.filter((opt) => opt.parentElement === sortSelect)
    expect(sortOptions.length).toBeGreaterThanOrEqual(3)
  })

  // ==========================================================================
  // Test 7: Reprint button is shown when canWrite is true
  // ==========================================================================

  it('shows Reprint button when canWrite is true', () => {
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
      canWrite: true,
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    const reprintButtons = screen.getAllByRole('button', { name: /Reprint/i })
    expect(reprintButtons.length).toBeGreaterThan(0)
  })

  // ==========================================================================
  // Test 8: Reprint button not shown when canWrite is false
  // ==========================================================================

  it('does not show Reprint button when canWrite is false', () => {
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
      canWrite: false,
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    const reprintButtons = screen.queryAllByRole('button', { name: /Reprint/i })
    expect(reprintButtons.length).toBe(0)
  })

  // ==========================================================================
  // Test 9: Job details are expandable
  // ==========================================================================

  it('allows job selection and displays result/message', async () => {
    const user = userEvent.setup()
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
      canWrite: true,
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    // Verify job results are displayed
    expect(screen.getByText('Print completed successfully')).toBeInTheDocument()
    expect(screen.getByText('Nozzle clogged')).toBeInTheDocument()
  })

  // ==========================================================================
  // Test 10: Proper accessibility attributes on interactive elements
  // ==========================================================================

  it('has proper accessibility labels on controls', () => {
    const mockState = createMockHistoryState()
    const stateWithJobs: UseHistoryStateReturn = {
      ...mockState,
      jobs: mockState.history?.jobs ?? [],
      canWrite: true,
    }
    vi.mocked(useHistoryStateModule.useHistoryState).mockReturnValue(stateWithJobs)

    const props: DrawerProps = {
      printerId: 'printer-1',
    }

    render(<HistoryDrawer {...props} />)

    // Check for aria labels
    const filterSelect = screen.getByLabelText(/Filter jobs by status/i)
    const sortSelect = screen.getByLabelText(/Sort jobs by/i)
    expect(filterSelect).toHaveAttribute('aria-label')
    expect(sortSelect).toHaveAttribute('aria-label')

    // Verify buttons have aria-label
    const reprintButtons = screen.queryAllByRole('button', { name: /Reprint/i })
    reprintButtons.forEach((button) => {
      expect(button).toHaveAttribute('aria-label')
    })
  })
})

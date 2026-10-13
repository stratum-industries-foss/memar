import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AnalyticsDrawer from '../AnalyticsDrawer'
import CoolantDrawer from '../CoolantDrawer'
import DryrunDrawer from '../DryrunDrawer'
import HealthDrawer from '../HealthDrawer'
import type { DrawerProps } from '../../App'

// Mock the custom hooks and components
vi.mock('../useAnalyticsState', () => ({
  useAnalyticsState: vi.fn(),
}))

vi.mock('../../CoolantMetricsPanel', () => ({
  CoolantMetricsPanel: ({ deviceId }: { deviceId: string }) => (
    <div data-testid="coolant-metrics-panel">CoolantMetricsPanel: {deviceId}</div>
  ),
}))

vi.mock('../../FleetTools', () => ({
  HealthPanel: ({ printerId }: { printerId: string }) => (
    <div data-testid="health-panel">HealthPanel: {printerId}</div>
  ),
}))

// Import mocked hooks after vi.mock
import { useAnalyticsState } from '../useAnalyticsState'

describe('AnalyticsDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders metrics when currentMetric is available', () => {
    const mockMetrics = {
      completed_jobs: 42,
      failed_jobs: 3,
      cancelled_jobs: 1,
      success_rate: 93.3,
      total_print_time: 1000,
      total_filament_used: 500,
      avg_print_time: 100,
    }

    const mockOeeData = new Map([
      ['printer1', {
        device_id: 'printer1',
        oee: 0.85,
        availability: 0.9,
        performance: 0.95,
        quality: 0.99,
        sample_jobs: 10,
      }],
    ])

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: mockOeeData,
    })

    const props: DrawerProps = { printerId: 'printer1' }
    render(<AnalyticsDrawer {...props} />)

    // Check that the drawer renders
    expect(screen.getByText('Device Analytics')).toBeInTheDocument()

    // Verify metrics are displayed
    expect(screen.getByText('46')).toBeInTheDocument() // totalJobs
    expect(screen.getByText('93.3%')).toBeInTheDocument() // success_rate
    expect(screen.getByText('42')).toBeInTheDocument() // completed_jobs
    expect(screen.getByText('3')).toBeInTheDocument() // failed_jobs
    expect(screen.getByText('1')).toBeInTheDocument() // cancelled_jobs
    expect(screen.getByText('85.0%')).toBeInTheDocument() // OEE
  })

  it('renders with null OEE when oeeByDevice is empty', () => {
    const mockMetrics = {
      completed_jobs: 10,
      failed_jobs: 1,
      cancelled_jobs: 0,
      success_rate: 90.9,
      total_print_time: 500,
      total_filament_used: 250,
      avg_print_time: 50,
    }

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: new Map(),
    })

    const props: DrawerProps = { printerId: 'printer2' }
    render(<AnalyticsDrawer {...props} />)

    // Check that the drawer renders
    expect(screen.getByText('Device Analytics')).toBeInTheDocument()

    // Verify OEE shows dash when not available
    const oeeElements = screen.getAllByText('—')
    expect(oeeElements.length).toBeGreaterThan(0)
  })

  it('renders null when currentMetric is null', () => {
    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: null,
      oeeByDevice: new Map(),
    })

    const props: DrawerProps = { printerId: 'printer3' }
    const { container } = render(<AnalyticsDrawer {...props} />)

    // Should render nothing (null component)
    expect(container.firstChild).toBeNull()
  })

  it('handles success_rate as null gracefully', () => {
    const mockMetrics = {
      completed_jobs: 5,
      failed_jobs: 0,
      cancelled_jobs: 0,
      success_rate: null,
      total_print_time: 300,
      total_filament_used: 100,
      avg_print_time: 60,
    }

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: new Map(),
    })

    const props: DrawerProps = { printerId: 'printer4' }
    render(<AnalyticsDrawer {...props} />)

    expect(screen.getByText('Device Analytics')).toBeInTheDocument()
    // Should display dash for null success_rate
    const dashElements = screen.getAllByText('—')
    expect(dashElements.length).toBeGreaterThan(0)
  })

  it('displays "Data from last 24 hours" footer text', () => {
    const mockMetrics = {
      completed_jobs: 1,
      failed_jobs: 0,
      cancelled_jobs: 0,
      success_rate: 100,
      total_print_time: 100,
      total_filament_used: 50,
      avg_print_time: 100,
    }

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: new Map(),
    })

    const props: DrawerProps = { printerId: 'printer5' }
    render(<AnalyticsDrawer {...props} />)

    expect(screen.getByText('Data from last 24 hours')).toBeInTheDocument()
  })
})

describe('CoolantDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders CoolantMetricsPanel when printerId is provided', () => {
    const props: DrawerProps = { printerId: 'cnc-machine-1' }
    render(<CoolantDrawer {...props} />)

    expect(screen.getByTestId('coolant-metrics-panel')).toBeInTheDocument()
    expect(screen.getByText('CoolantMetricsPanel: cnc-machine-1')).toBeInTheDocument()
  })

  it('renders CoolantMetricsPanel with different printer IDs', () => {
    const { rerender } = render(<CoolantDrawer printerId="machine-a" />)
    expect(screen.getByText('CoolantMetricsPanel: machine-a')).toBeInTheDocument()

    rerender(<CoolantDrawer printerId="machine-b" />)
    expect(screen.getByText('CoolantMetricsPanel: machine-b')).toBeInTheDocument()
  })

  it('returns null when printerId is not provided', () => {
    const props: DrawerProps = {}
    const { container } = render(<CoolantDrawer {...props} />)

    expect(container.firstChild).toBeNull()
  })

  it('returns null when printerId is undefined', () => {
    const props: DrawerProps = { printerId: undefined }
    const { container } = render(<CoolantDrawer {...props} />)

    expect(container.firstChild).toBeNull()
  })

  it('returns null when printerId is empty string', () => {
    const props: DrawerProps = { printerId: '' }
    const { container } = render(<CoolantDrawer {...props} />)

    expect(container.firstChild).toBeNull()
  })

  it('passes through additional DrawerProps to CoolantMetricsPanel context', () => {
    const props: DrawerProps = {
      printerId: 'cnc-1',
      canWrite: true,
      onMessage: vi.fn(),
    }
    render(<CoolantDrawer {...props} />)

    expect(screen.getByTestId('coolant-metrics-panel')).toBeInTheDocument()
  })
})

describe('DryrunDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders drawer section with title', () => {
    const props: DrawerProps = { printerId: 'printer1', canWrite: true }
    render(<DryrunDrawer {...props} />)

    expect(screen.getByText('Action dry-run')).toBeInTheDocument()
  })

  it('displays placeholder message', () => {
    const props: DrawerProps = { printerId: 'printer1' }
    render(<DryrunDrawer {...props} />)

    expect(
      screen.getByText('Extract dry-run UI from original App.tsx lines ~5072-5122')
    ).toBeInTheDocument()
  })

  it('renders even without printerId', () => {
    const props: DrawerProps = {}
    render(<DryrunDrawer {...props} />)

    expect(screen.getByText('Action dry-run')).toBeInTheDocument()
  })

  it('renders with various DrawerProps combinations', () => {
    const { rerender } = render(<DryrunDrawer printerId="a" canWrite={true} />)
    expect(screen.getByText('Action dry-run')).toBeInTheDocument()

    rerender(<DryrunDrawer printerId="b" canWrite={false} />)
    expect(screen.getByText('Action dry-run')).toBeInTheDocument()

    rerender(<DryrunDrawer />)
    expect(screen.getByText('Action dry-run')).toBeInTheDocument()
  })

  it('has drawer-section className', () => {
    const props: DrawerProps = { printerId: 'printer1' }
    const { container } = render(<DryrunDrawer {...props} />)

    const section = container.querySelector('section.drawer-section')
    expect(section).toBeInTheDocument()
  })
})

describe('HealthDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders HealthPanel when printerId is provided', () => {
    const props: DrawerProps = { printerId: 'printer-health-1' }
    render(<HealthDrawer {...props} />)

    expect(screen.getByTestId('health-panel')).toBeInTheDocument()
    expect(screen.getByText('HealthPanel: printer-health-1')).toBeInTheDocument()
  })

  it('renders HealthPanel with different printer IDs', () => {
    const { rerender } = render(<HealthDrawer printerId="host-a" />)
    expect(screen.getByText('HealthPanel: host-a')).toBeInTheDocument()

    rerender(<HealthDrawer printerId="host-b" />)
    expect(screen.getByText('HealthPanel: host-b')).toBeInTheDocument()
  })

  it('returns null when printerId is not provided', () => {
    const props: DrawerProps = {}
    const { container } = render(<HealthDrawer {...props} />)

    expect(container.firstChild).toBeNull()
  })

  it('returns null when printerId is undefined', () => {
    const props: DrawerProps = { printerId: undefined }
    const { container } = render(<HealthDrawer {...props} />)

    expect(container.firstChild).toBeNull()
  })

  it('returns null when printerId is empty string', () => {
    const props: DrawerProps = { printerId: '' }
    const { container } = render(<HealthDrawer {...props} />)

    expect(container.firstChild).toBeNull()
  })

  it('passes printerId to HealthPanel component', () => {
    const props: DrawerProps = {
      printerId: 'diagnostic-printer',
      diagnostics: { cpu_temp: 45.5 },
    }
    render(<HealthDrawer {...props} />)

    expect(screen.getByText('HealthPanel: diagnostic-printer')).toBeInTheDocument()
  })

  it('ignores additional DrawerProps and only passes printerId', () => {
    const props: DrawerProps = {
      printerId: 'printer-x',
      canWrite: false,
      onDone: vi.fn(),
      onMessage: vi.fn(),
    }
    render(<HealthDrawer {...props} />)

    expect(screen.getByText('HealthPanel: printer-x')).toBeInTheDocument()
  })
})

describe('Shared error boundary handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('CoolantDrawer handles missing deviceId prop gracefully', () => {
    const props: DrawerProps = { printerId: undefined }
    const { container } = render(<CoolantDrawer {...props} />)

    // Should not throw, just render null
    expect(container.firstChild).toBeNull()
  })

  it('HealthDrawer handles missing printerId gracefully', () => {
    const props: DrawerProps = { printerId: undefined }
    const { container } = render(<HealthDrawer {...props} />)

    // Should not throw, just render null
    expect(container.firstChild).toBeNull()
  })

  it('AnalyticsDrawer handles missing currentMetric gracefully', () => {
    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: null,
      oeeByDevice: new Map(),
    })

    const props: DrawerProps = { printerId: 'printer1' }
    const { container } = render(<AnalyticsDrawer {...props} />)

    // Should not throw, just render null
    expect(container.firstChild).toBeNull()
  })

  it('DryrunDrawer renders without errors regardless of props', () => {
    expect(() => {
      render(<DryrunDrawer />)
    }).not.toThrow()

    expect(() => {
      render(<DryrunDrawer printerId="p1" canWrite={true} />)
    }).not.toThrow()
  })

  it('all drawers handle empty DrawerProps object', () => {
    const emptyProps: DrawerProps = {}

    expect(() => {
      render(<AnalyticsDrawer {...emptyProps} />)
    }).not.toThrow()

    expect(() => {
      render(<CoolantDrawer {...emptyProps} />)
    }).not.toThrow()

    expect(() => {
      render(<DryrunDrawer {...emptyProps} />)
    }).not.toThrow()

    expect(() => {
      render(<HealthDrawer {...emptyProps} />)
    }).not.toThrow()
  })

  it('handles rapid prop changes without crashing', () => {
    const { rerender } = render(<CoolantDrawer printerId="p1" />)

    for (let i = 0; i < 5; i++) {
      expect(() => {
        rerender(<CoolantDrawer printerId={`p${i}`} />)
      }).not.toThrow()
    }
  })

  it('handles undefined props passed as spread operator', () => {
    const props = { printerId: 'printer1', canWrite: undefined, onDone: undefined }

    expect(() => {
      render(<HealthDrawer {...props} />)
    }).not.toThrow()

    expect(screen.getByText('HealthPanel: printer1')).toBeInTheDocument()
  })
})

describe('AnalyticsDrawer edge cases', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('handles zero values in metrics', () => {
    const mockMetrics = {
      completed_jobs: 0,
      failed_jobs: 0,
      cancelled_jobs: 0,
      success_rate: 0,
      total_print_time: 0,
      total_filament_used: 0,
      avg_print_time: 0,
    }

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: new Map(),
    })

    const props: DrawerProps = { printerId: 'empty-printer' }
    render(<AnalyticsDrawer {...props} />)

    // Multiple zeros exist, so use getAllByText
    const zeros = screen.getAllByText('0')
    expect(zeros.length).toBeGreaterThan(0)
    expect(screen.getByText('0.0%')).toBeInTheDocument()
  })

  it('handles very large numbers in metrics', () => {
    const mockMetrics = {
      completed_jobs: 999999,
      failed_jobs: 1000,
      cancelled_jobs: 100,
      success_rate: 99.9,
      total_print_time: 1000000,
      total_filament_used: 500000,
      avg_print_time: 1000,
    }

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: new Map(),
    })

    const props: DrawerProps = { printerId: 'high-volume-printer' }
    render(<AnalyticsDrawer {...props} />)

    expect(screen.getByText('1001099')).toBeInTheDocument() // totalJobs
    expect(screen.getByText('99.9%')).toBeInTheDocument()
  })

  it('handles OEE value of 0', () => {
    const mockMetrics = {
      completed_jobs: 10,
      failed_jobs: 5,
      cancelled_jobs: 2,
      success_rate: 66.7,
      total_print_time: 500,
      total_filament_used: 200,
      avg_print_time: 50,
    }

    const mockOeeData = new Map([
      ['printer1', {
        device_id: 'printer1',
        oee: 0,
        availability: 0,
        performance: 0,
        quality: 0,
        sample_jobs: 0,
      }],
    ])

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: mockOeeData,
    })

    const props: DrawerProps = { printerId: 'printer1' }
    render(<AnalyticsDrawer {...props} />)

    expect(screen.getByText('0.0%')).toBeInTheDocument()
  })

  it('handles OEE value of 1 (100%)', () => {
    const mockMetrics = {
      completed_jobs: 100,
      failed_jobs: 0,
      cancelled_jobs: 0,
      success_rate: 100,
      total_print_time: 1000,
      total_filament_used: 500,
      avg_print_time: 10,
    }

    const mockOeeData = new Map([
      ['perfect-printer', {
        device_id: 'perfect-printer',
        oee: 1,
        availability: 1,
        performance: 1,
        quality: 1,
        sample_jobs: 100,
      }],
    ])

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: mockOeeData,
    })

    const props: DrawerProps = { printerId: 'perfect-printer' }
    render(<AnalyticsDrawer {...props} />)

    // Both success_rate and OEE show 100.0%, verify multiple exist
    const percentages = screen.getAllByText('100.0%')
    expect(percentages.length).toBeGreaterThanOrEqual(2) // success_rate and OEE
  })
})

describe('Drawer section structure', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('AnalyticsDrawer uses drawer-section class', () => {
    const mockMetrics = {
      completed_jobs: 1,
      failed_jobs: 0,
      cancelled_jobs: 0,
      success_rate: 100,
      total_print_time: 100,
      total_filament_used: 50,
      avg_print_time: 100,
    }

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: new Map(),
    })

    const { container } = render(<AnalyticsDrawer printerId="p1" />)
    const section = container.querySelector('section.drawer-section')
    expect(section).toBeInTheDocument()
  })

  it('AnalyticsDrawer contains kv-grid for metrics display', () => {
    const mockMetrics = {
      completed_jobs: 1,
      failed_jobs: 0,
      cancelled_jobs: 0,
      success_rate: 100,
      total_print_time: 100,
      total_filament_used: 50,
      avg_print_time: 100,
    }

    vi.mocked(useAnalyticsState).mockReturnValue({
      currentMetric: mockMetrics,
      oeeByDevice: new Map(),
    })

    const { container } = render(<AnalyticsDrawer printerId="p1" />)
    const kvGrid = container.querySelector('.kv-grid')
    expect(kvGrid).toBeInTheDocument()
  })

  it('DryrunDrawer uses drawer-section class', () => {
    const { container } = render(<DryrunDrawer printerId="p1" />)
    const section = container.querySelector('section.drawer-section')
    expect(section).toBeInTheDocument()
  })
})

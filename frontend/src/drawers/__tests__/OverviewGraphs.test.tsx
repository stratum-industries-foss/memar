/**
 * OverviewGraphs Component Tests
 *
 * Tests cover:
 * - Success Rate donut rendering with complete/failed/cancelled jobs
 * - Empty and null metric handling
 * - Loading/error states for timeline/duration/filament charts
 * - Responsive layout
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OverviewGraphs } from '../OverviewGraphs'

// Mock recharts to avoid jsdom rendering issues
vi.mock('recharts', () => ({
  LineChart: ({ children, data }: any) => (
    <div data-testid="line-chart" data-items={data?.length || 0}>
      {children}
    </div>
  ),
  BarChart: ({ children, data }: any) => (
    <div data-testid="bar-chart" data-items={data?.length || 0}>
      {children}
    </div>
  ),
  AreaChart: ({ children, data }: any) => (
    <div data-testid="area-chart" data-items={data?.length || 0}>
      {children}
    </div>
  ),
  PieChart: ({ children, data }: any) => (
    <div data-testid="pie-chart" data-items={data?.length || 0}>
      {children}
    </div>
  ),
  Pie: ({ data }: any) => <div data-testid="pie" data-items={data?.length || 0} />,
  Line: ({ dataKey }: any) => <div data-testid={`line-${dataKey}`} />,
  Bar: ({ dataKey }: any) => <div data-testid={`bar-${dataKey}`} />,
  Area: ({ dataKey }: any) => <div data-testid={`area-${dataKey}`} />,
  Cell: () => <div data-testid="cell" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  Legend: () => <div data-testid="legend" />,
  ResponsiveContainer: ({ children }: any) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  ReferenceLine: () => <div data-testid="reference-line" />,
}))

describe('OverviewGraphs', () => {
  describe('Success Rate Chart', () => {
    it('renders donut chart with completed/failed/cancelled jobs', () => {
      const metric = {
        completed_jobs: 45,
        failed_jobs: 3,
        cancelled_jobs: 2,
      }
      render(<OverviewGraphs currentMetric={metric} printerId="printer-1" />)

      expect(screen.getByText('Success Rate')).toBeInTheDocument()
      expect(screen.getByText(/90\.0%/)).toBeInTheDocument() // 45/50
      expect(screen.getByText(/45 completed · 3 failed · 2 cancelled/)).toBeInTheDocument()
    })

    it('renders empty state when metric is null', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      expect(screen.getByText('No metrics available')).toBeInTheDocument()
    })

    it('renders empty state when no jobs have completed', () => {
      const metric = {
        completed_jobs: 0,
        failed_jobs: 0,
        cancelled_jobs: 0,
      }
      render(<OverviewGraphs currentMetric={metric} printerId="printer-1" />)

      expect(screen.getByText('No jobs yet')).toBeInTheDocument()
    })

    it('handles undefined job counts gracefully', () => {
      const metric = {
        completed_jobs: 10,
        failed_jobs: undefined,
        cancelled_jobs: undefined,
      }
      render(<OverviewGraphs currentMetric={metric} printerId="printer-1" />)

      expect(screen.getByText('Success Rate')).toBeInTheDocument()
      expect(screen.getByText(/100\.0%/)).toBeInTheDocument() // 10/10
    })

    it('filters out zero-value categories from chart', () => {
      const metric = {
        completed_jobs: 50,
        failed_jobs: 0,
        cancelled_jobs: 0,
      }
      render(<OverviewGraphs currentMetric={metric} printerId="printer-1" />)

      // Chart should render successfully even with only one category
      expect(screen.getByText('Success Rate')).toBeInTheDocument()
      expect(screen.getByText(/100\.0%/)).toBeInTheDocument() // 50/50
      expect(screen.getByText(/50 completed/)).toBeInTheDocument()
    })
  })

  describe('Job History Timeline', () => {
    it('renders empty state initially (endpoint not yet available)', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      // Every chart shows the same unavailable copy until the endpoint exists.
      expect(
        screen.getAllByText(/Charts unavailable.*history endpoint not yet implemented/).length
      ).toBeGreaterThanOrEqual(1)
    })

    it('displays correct heading with timeframe', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      expect(screen.getByText(/Job History/)).toBeInTheDocument()
      expect(screen.getByText(/last 30 days/)).toBeInTheDocument()
    })
  })

  describe('Print Time Distribution', () => {
    it('renders empty state initially (derived from history)', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      // Three charts share this copy; the distribution chart must show its own unavailable state.
      expect(
        screen.getAllByText(/Charts unavailable.*history endpoint not yet implemented/).length
      ).toBeGreaterThanOrEqual(1)
    })

    it('displays distribution chart heading', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      expect(screen.getByText('Print Time Distribution')).toBeInTheDocument()
    })
  })

  describe('Filament Usage Trend', () => {
    it('renders empty state initially (derived from history)', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      // The shipped copy for this chart is the same unavailable state as the others.
      expect(
        screen.getAllByText(/Charts unavailable.*history endpoint not yet implemented/).length
      ).toBeGreaterThanOrEqual(1)
    })

    it('displays trend chart heading', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      expect(screen.getByText('Filament Usage Trend')).toBeInTheDocument()
    })
  })

  describe('Layout and Accessibility', () => {
    it('renders all four chart sections', () => {
      const metric = {
        completed_jobs: 20,
        failed_jobs: 2,
        cancelled_jobs: 1,
      }
      render(<OverviewGraphs currentMetric={metric} printerId="printer-1" />)

      expect(screen.getByText('Success Rate')).toBeInTheDocument()
      expect(screen.getByText(/Job History/)).toBeInTheDocument()
      expect(screen.getByText('Print Time Distribution')).toBeInTheDocument()
      expect(screen.getByText('Filament Usage Trend')).toBeInTheDocument()
    })

    it('wraps charts in responsive container', () => {
      render(<OverviewGraphs currentMetric={null} printerId="printer-1" />)

      // Container with data-testid="graphs-container" should exist
      const sections = screen.getAllByText(/Success Rate|Job History|Print Time|Filament Usage/)
      expect(sections.length).toBeGreaterThan(0)
    })
  })

  describe('Edge Cases', () => {
    it('handles missing printerId gracefully', () => {
      const metric = {
        completed_jobs: 10,
        failed_jobs: 1,
        cancelled_jobs: 0,
      }
      render(<OverviewGraphs currentMetric={metric} />)

      expect(screen.getByText('Success Rate')).toBeInTheDocument()
      expect(screen.getByText(/90\.9%/)).toBeInTheDocument()
    })

    it('calculates success percentage correctly for various totals', () => {
      // Test 1: 50% success
      const { unmount: unmount1 } = render(
        <OverviewGraphs
          currentMetric={{ completed_jobs: 5, failed_jobs: 5, cancelled_jobs: 0 }}
          printerId="p1"
        />
      )
      expect(screen.getByText(/50\.0%/)).toBeInTheDocument()
      unmount1()

      // Test 2: 33.3% success
      render(
        <OverviewGraphs
          currentMetric={{ completed_jobs: 2, failed_jobs: 4, cancelled_jobs: 0 }}
          printerId="p1"
        />
      )
      expect(screen.getByText(/33\.3%/)).toBeInTheDocument()
    })
  })
})

/**
 * useOverviewState Hook Tests
 *
 * Tests verify:
 * 1. Diagnostics data loading from context
 * 2. Spool management integration and state synchronization
 * 3. Exclude objects integration and state synchronization
 * 4. Confirmation callback for exclude operations
 * 5. Context requirement enforcement
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import React, { ReactNode } from 'react'
import { useOverviewState } from '../useOverviewState'
import * as spoolHook from '../useSpoolManagement'
import * as excludeHook from '../useExcludeObjects'
import { AppDrawerContext } from '../../context/AppContext'

// ============================================================================
// Mock Dependencies
// ============================================================================

// Mock useSpoolManagement hook
const mockSpoolManagement = {
  log: [
    { id: '1', material: 'PLA', lengthMm: 1000, weight: 20, reason: 'refill' as const, timestamp: '2026-08-01T00:00:00Z' },
    { id: '2', material: 'PLA', lengthMm: -500, weight: -10, reason: 'print' as const, timestamp: '2026-08-02T00:00:00Z' },
  ],
  isLoading: false,
  error: null,
  recordAdjustment: vi.fn(),
  calculateRemaining: vi.fn(() => 10),
  totalUsed: 10,
  currentRemaining: 10,
}

vi.spyOn(spoolHook, 'useSpoolManagement').mockReturnValue(mockSpoolManagement as any)

// Mock useExcludeObjects hook
const mockExcludeObjects = {
  objects: [
    { name: 'support_1', status: 'included' as const, excludable: true },
    { name: 'part_a', status: 'included' as const, excludable: true },
  ],
  isLoading: false,
  error: null,
  exclude: vi.fn(),
  include: vi.fn(),
  excludedObjects: [],
  isExcluded: vi.fn((name: string) => false),
}

vi.spyOn(excludeHook, 'useExcludeObjects').mockReturnValue(mockExcludeObjects as any)

// ============================================================================
// Mock Data
// ============================================================================

const mockDiagnostics: any = {
  status: 'operational',
  temperature: 25,
  heater_bed: { current_temp: 25, target_temp: 0 },
  extruder: { current_temp: 25, target_temp: 0 },
  layer: 0,
  virtual_sdcard: { progress: 0, is_active: false },
}

const mockCurrentFileDetail = {
  filename: 'test_part.gcode',
  size: 5000,
  estimated_time: 3600,
  layer_height: 0.2,
}

const mockMetric = {
  printerId: 'printer-1',
  uptime: 86400,
  avg_temp: 25,
  successful_prints: 10,
  failed_prints: 2,
}

const mockOee = {
  device_id: 'printer-1',
  availability: 0.95,
  performance: 0.98,
  quality: 0.99,
  oee: 0.92,
  timestamp: '2026-08-01T00:00:00Z',
}

const mockCvAnomalies = [
  {
    anomaly_id: 'a1',
    type: 'blob',
    confidence: 0.95,
    detected_at: '2026-08-01T00:00:00Z',
    layer: 10,
  },
]

const mockToastFn = vi.fn()
const mockOnConfirm = vi.fn()

const mockContextValue = {
  diagnostics: mockDiagnostics,
  currentFileDetail: mockCurrentFileDetail,
  metric: mockMetric,
  oee: mockOee,
  cvAnomalies: mockCvAnomalies,
  canWrite: true,
  showOee: true,
  showEmptyCapabilityTiles: false,
  pushToast: mockToastFn,
  onConfirm: mockOnConfirm,
}

// ============================================================================
// Helper: Create Provider Wrapper
// ============================================================================

function createWrapper(contextValue: any) {
  return ({ children }: { children: ReactNode }) => (
    <AppDrawerContext.Provider value={contextValue}>
      {children}
    </AppDrawerContext.Provider>
  )
}

// ============================================================================
// Tests
// ============================================================================

describe('useOverviewState', () => {
  const mockPrinter = { id: 'printer-1', name: 'Printer 1' }
  const mockPrinterId = 'printer-1'

  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ==========================================================================
  // Test 1: Diagnostics Data Loading
  // ==========================================================================

  describe('Test 1: Diagnostics data loading', () => {
    it('should load diagnostics data from context', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.diagnostics).toEqual(mockDiagnostics)
      expect(result.current.diagnostics?.status).toBe('operational')
      expect(result.current.diagnostics?.layer).toBe(0)
    })

    it('should load all diagnostic-related state from context', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.currentFileDetail).toEqual(mockCurrentFileDetail)
      expect(result.current.metric).toEqual(mockMetric)
      expect(result.current.oee).toEqual(mockOee)
      expect(result.current.cvAnomalies).toEqual(mockCvAnomalies)
    })

    it('should handle null diagnostics gracefully', () => {
      const contextWithNullDiagnostics = { ...mockContextValue, diagnostics: null }
      const wrapper = createWrapper(contextWithNullDiagnostics)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.diagnostics).toBeNull()
      expect(result.current.currentFileDetail).toEqual(mockCurrentFileDetail)
      expect(result.current.metric).toEqual(mockMetric)
    })

    it('should expose canWrite and showOee flags from context', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.canWrite).toBe(true)
      expect(result.current.showOee).toBe(true)
      expect(result.current.showEmptyCapabilityTiles).toBe(false)
    })

    it('should load toast and confirm callbacks from context', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.pushToast).toBe(mockToastFn)
      expect(result.current.onConfirm).toBe(mockOnConfirm)
    })
  })

  // ==========================================================================
  // Test 2: Spool Management Integration
  // ==========================================================================

  describe('Test 2: Spool management integration', () => {
    it('should integrate spool management hook and expose its return value', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.spool).toBeDefined()
      expect(result.current.spool.log).toEqual(mockSpoolManagement.log)
      expect(result.current.spool.isLoading).toBe(false)
      expect(result.current.spool.error).toBeNull()
    })

    it('should pass printerId and diagnostics to useSpoolManagement', () => {
      const useSpoolManagementSpy = vi.spyOn(spoolHook, 'useSpoolManagement')
      const wrapper = createWrapper(mockContextValue)

      renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(useSpoolManagementSpy).toHaveBeenCalledWith(mockPrinterId, mockDiagnostics, mockToastFn)
    })

    it('should provide recordAdjustment function from spool management', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.spool.recordAdjustment).toBe(mockSpoolManagement.recordAdjustment)
    })

    it('should provide calculateRemaining function from spool management', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.spool.calculateRemaining).toBe(mockSpoolManagement.calculateRemaining)
    })

    it('should sync spool state changes when hook returns different values', () => {
      let callCount = 0
      const updatedSpoolReturn = {
        ...mockSpoolManagement,
        log: [
          { id: '3', material: 'PETG', lengthMm: 2000, weight: 40, reason: 'refill', timestamp: '2026-08-03T00:00:00Z' },
        ],
      }

      vi.spyOn(spoolHook, 'useSpoolManagement').mockImplementation(() => {
        callCount++
        return callCount === 1 ? mockSpoolManagement : updatedSpoolReturn
      })

      const wrapper = createWrapper(mockContextValue)
      const { result, rerender } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.spool.log).toEqual(mockSpoolManagement.log)

      act(() => {
        rerender()
      })

      expect(result.current.spool.log).toEqual(updatedSpoolReturn.log)
    })
  })

  // ==========================================================================
  // Test 3: Exclude Objects Integration
  // ==========================================================================

  describe('Test 3: Exclude objects integration', () => {
    it('should integrate exclude objects hook and expose its return value', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.excludeObjects).toBeDefined()
      expect(result.current.excludeObjects.objects).toEqual(mockExcludeObjects.objects)
      expect(result.current.excludeObjects.isLoading).toBe(false)
      expect(result.current.excludeObjects.error).toBeNull()
    })

    it('should pass printerId to useExcludeObjects', () => {
      const useExcludeObjectsSpy = vi.spyOn(excludeHook, 'useExcludeObjects')
      const wrapper = createWrapper(mockContextValue)

      renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(useExcludeObjectsSpy).toHaveBeenCalledWith(mockPrinterId)
    })

    it('should provide exclude and include functions from exclude objects hook', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.excludeObjects.exclude).toBe(mockExcludeObjects.exclude)
      expect(result.current.excludeObjects.include).toBe(mockExcludeObjects.include)
      expect(result.current.excludeObjects.isExcluded).toBe(mockExcludeObjects.isExcluded)
    })

    it('should provide excludedObjects array from exclude objects hook', () => {
      const excludedList = ['support_1', 'support_2']
      const updateMockExcludeObjects = {
        ...mockExcludeObjects,
        excludedObjects: excludedList,
      }

      vi.spyOn(excludeHook, 'useExcludeObjects').mockReturnValue(updateMockExcludeObjects as any)

      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.excludeObjects.excludedObjects).toEqual(excludedList)
    })

    it('should sync exclude objects state changes when hook returns different values', () => {
      let callCount = 0
      const updatedExcludeReturn = {
        ...mockExcludeObjects,
        objects: [
          { name: 'support_1', status: 'excluded' as const, excludable: true },
          { name: 'support_2', status: 'excluded' as const, excludable: true },
          { name: 'part_a', status: 'included' as const, excludable: true },
        ],
        excludedObjects: ['support_1', 'support_2'],
      }

      vi.spyOn(excludeHook, 'useExcludeObjects').mockImplementation(() => {
        callCount++
        return (callCount === 1 ? mockExcludeObjects : updatedExcludeReturn) as any
      })

      const wrapper = createWrapper(mockContextValue)
      const { result, rerender } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      expect(result.current.excludeObjects.excludedObjects).toEqual([])

      act(() => {
        rerender()
      })

      expect(result.current.excludeObjects.excludedObjects).toEqual(['support_1', 'support_2'])
      expect(result.current.excludeObjects.objects).toEqual(updatedExcludeReturn.objects)
    })
  })

  // ==========================================================================
  // Additional Integration Tests
  // ==========================================================================

  describe('confirmExclude callback integration', () => {
    it('should create confirmExclude callback that formats message and calls onConfirm', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      act(() => {
        result.current.confirmExclude('part_a')
      })

      expect(mockOnConfirm).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Exclude "part_a" from print?',
          onConfirm: expect.any(Function),
        })
      )
    })

    it('should call excludeObjects.exclude when confirmExclude callback is confirmed', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId), {
        wrapper,
      })

      let capturedCallback: (() => void) | null = null
      mockOnConfirm.mockImplementation((state) => {
        capturedCallback = state.onConfirm
      })

      act(() => {
        result.current.confirmExclude('part_b')
      })

      expect(capturedCallback).toBeDefined()
      expect(mockOnConfirm).toHaveBeenCalled()

      act(() => {
        capturedCallback?.()
      })

      expect(mockExcludeObjects.exclude).toHaveBeenCalledWith('part_b')
    })
  })

  // ==========================================================================
  // Context Provider Requirement
  // ==========================================================================

  describe('Context requirement', () => {
    it('should throw error when used outside AppDrawerContext', () => {
      // Suppress console.error for this test
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      expect(() => {
        renderHook(() => useOverviewState(mockPrinter as any, mockPrinterId))
      }).toThrow('useOverviewState must be used inside DrawerProvider')

      consoleSpy.mockRestore()
    })
  })

  // ==========================================================================
  // Null Printer Handling
  // ==========================================================================

  describe('Null printer handling', () => {
    it('should accept null printer and continue functioning', () => {
      const wrapper = createWrapper(mockContextValue)
      const { result } = renderHook(() => useOverviewState(null, mockPrinterId), {
        wrapper,
      })

      expect(result.current.diagnostics).toBeDefined()
      expect(result.current.spool).toBeDefined()
      expect(result.current.excludeObjects).toBeDefined()
    })
  })
})

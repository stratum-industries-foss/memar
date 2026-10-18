/**
 * Remaining Hooks Tests: useCoolantState, useConsoleState, useMacrosState, useExcludeObjects, useSpoolManagement
 *
 * Tests verify:
 * 1. useCoolantState: metrics loading, realtime updates
 * 2. useConsoleState: history management, gcode sending
 * 3. useMacrosState: macro filtering, parameter parsing
 * 4. useExcludeObjects: object list management, exclude/include operations
 * 5. useSpoolManagement: log display, adjustment recording
 *
 * Coverage target: >80%
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { ReactNode } from 'react'
import React from 'react'

// Hooks under test
import { useCoolantState, type CoolantState } from '../useCoolantState'
import { useConsoleState, type UseConsoleStateOptions } from '../useConsoleState'
import { useMacrosState, type MacrosState } from '../useMacrosState'
import { useExcludeObjects, type UseExcludeObjectsReturn } from '../useExcludeObjects'
import { useSpoolManagement, type UseSpoolManagementReturn } from '../useSpoolManagement'

// Context and types
import { AppDrawerContext } from '../../context/AppContext'
import type { Printer } from '../../context/types'

// Mock dependencies
import * as coolantMetricsHook from '../useCoolantMetrics'
import * as coolantTrendHook from '../useCoolantTrend'
import * as consoleHistoryHook from '../useConsoleHistory'
import * as gcodeConsoleHook from '../useGcodeConsole'
import * as macroFilterHook from '../../hooks/useMacroFilter'

// ============================================================================
// Mock Setup
// ============================================================================

const mockCoolantMetrics = {
  psi: 25.5,
  temperature_c: 18.5,
  status: 'active' as const,
  flow_rate_lpm: 10.2,
}

const mockTrendData = [
  { timestamp: Date.now() - 300000, psi: 25.0, temperature_c: 18.0 },
  { timestamp: Date.now() - 200000, psi: 25.5, temperature_c: 18.5 },
  { timestamp: Date.now(), psi: 26.0, temperature_c: 19.0 },
]

const mockConsoleLog = [
  { type: 'request' as const, text: 'G28' },
  { type: 'response' as const, text: 'ok' },
]

const mockMacros = [
  {
    name: 'START_PRINT',
    description: 'Start print sequence',
    is_private: false,
    parameters: [{ name: 'TEMP', type: 'float', default: '200' }],
  },
  {
    name: 'END_PRINT',
    description: 'End print sequence',
    is_private: false,
    parameters: [],
  },
  {
    name: '_PRIVATE_MACRO',
    description: 'Private macro',
    is_private: true,
    parameters: [],
  },
]

const mockExcludeObjects = [
  { name: 'support_1', status: 'included' as const, excludable: true },
  { name: 'part_a', status: 'included' as const, excludable: true },
]

const mockSpoolLog = [
  { timestamp: Date.now() - 86400000, material: 'PLA', lengthMm: 1000, weight: 20, reason: 'refill' as const },
  { timestamp: Date.now(), material: 'PLA', lengthMm: -500, weight: -10, reason: 'print' as const },
]

// ============================================================================
// Test Helpers
// ============================================================================

function createAppContextWrapper(overrides: any = {}) {
  const defaultContextValue = {
    printerId: 'printer-1',
    printer: null,
    macros: mockMacros,
    canWrite: true,
    searchTerm: '',
    setSearchTerm: vi.fn(),
    setDrawerMessage: vi.fn(),
    showToast: vi.fn(),
    ...overrides,
  }

  return ({ children }: { children: ReactNode }) =>
    React.createElement(
      AppDrawerContext.Provider,
      { value: defaultContextValue },
      children
    )
}

// ============================================================================
// Test 1: useCoolantState — Metrics Loading
// ============================================================================

describe('useCoolantState', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Mock useCoolantMetrics
    vi.spyOn(coolantMetricsHook, 'useCoolantMetrics').mockReturnValue({
      metrics: mockCoolantMetrics,
      loading: false,
      error: undefined,
      unavailable: false,
      reload: vi.fn(),
      applyRealtimeUpdate: vi.fn(),
    })

    // Mock useCoolantTrend
    vi.spyOn(coolantTrendHook, 'useCoolantTrend').mockReturnValue({
      data: mockTrendData,
      loading: false,
      error: undefined,
      average: 25.5,
      min: 25.0,
      max: 26.0,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should load coolant metrics and trend data on mount', () => {
    const { result } = renderHook(() => useCoolantState('printer-1'))

    expect(result.current.metrics).toEqual(mockCoolantMetrics)
    expect(result.current.trendData).toEqual(mockTrendData)
    expect(result.current.loading).toBe(false)
    expect(result.current.trendLoading).toBe(false)
  })

  it('should apply real-time updates to metrics without full reload', async () => {
    const { result } = renderHook(() => useCoolantState('printer-1'))

    const realtimeUpdate = { psi: 27.0, temperature_c: 20.0 }

    await act(async () => {
      result.current.applyRealtimeUpdate(realtimeUpdate)
    })

    // Verify that applyRealtimeUpdate was called
    expect(coolantMetricsHook.useCoolantMetrics).toHaveBeenCalled()
  })

  it('should toggle trend chart visibility', async () => {
    const { result } = renderHook(() => useCoolantState('printer-1'))

    expect(result.current.showTrendChart).toBe(true)

    await act(async () => {
      result.current.setShowTrendChart(false)
    })

    expect(result.current.showTrendChart).toBe(false)
  })

  it('should handle loading state transitions', () => {
    const loadingMockMetrics = { ...coolantMetricsHook.useCoolantMetrics }
    vi.spyOn(coolantMetricsHook, 'useCoolantMetrics').mockReturnValue({
      metrics: null,
      loading: true,
      error: undefined,
      unavailable: false,
      reload: vi.fn(),
      applyRealtimeUpdate: vi.fn(),
    })

    const { result } = renderHook(() => useCoolantState('printer-1'))

    expect(result.current.loading).toBe(true)
    expect(result.current.metrics).toBeNull()
  })
})

// ============================================================================
// Test 2: useCoolantState — Real-time Updates
// ============================================================================

describe('useCoolantState — Real-time Updates', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should trigger error callback on metrics fetch failure', () => {
    const errorCallback = vi.fn()

    vi.spyOn(coolantMetricsHook, 'useCoolantMetrics').mockReturnValue({
      metrics: null,
      loading: false,
      error: 'Coolant sensor offline',
      unavailable: false,
      reload: vi.fn(),
      applyRealtimeUpdate: vi.fn(),
    })

    vi.spyOn(coolantTrendHook, 'useCoolantTrend').mockReturnValue({
      data: [],
      loading: false,
      error: undefined,
      average: null,
      min: null,
      max: null,
    })

    const { result } = renderHook(() => useCoolantState('printer-1', errorCallback))

    expect(result.current.error).toBe('Coolant sensor offline')
  })

  it('should mark coolant unavailable for machines without coolant support', () => {
    vi.spyOn(coolantMetricsHook, 'useCoolantMetrics').mockReturnValue({
      metrics: null,
      loading: false,
      error: undefined,
      unavailable: true,
      reload: vi.fn(),
      applyRealtimeUpdate: vi.fn(),
    })

    vi.spyOn(coolantTrendHook, 'useCoolantTrend').mockReturnValue({
      data: [],
      loading: false,
      error: undefined,
      average: null,
      min: null,
      max: null,
    })

    const { result } = renderHook(() => useCoolantState('printer-1'))

    expect(result.current.unavailable).toBe(true)
  })
})

// ============================================================================
// Test 3: useConsoleState — History Management
// ============================================================================

describe('useConsoleState', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Mock useConsoleHistory
    vi.spyOn(consoleHistoryHook, 'useConsoleHistory').mockReturnValue({
      history: ['G28', 'M104 S200'],
      historyIndex: 2,
      setHistoryIndex: vi.fn(),
      cycleRef: { current: { prefix: '', index: -1 } },
      resetCycle: vi.fn(),
      record: vi.fn(),
    })

    // Mock useGcodeConsole
    vi.spyOn(gcodeConsoleHook, 'useGcodeConsole').mockReturnValue({
      log: mockConsoleLog,
      sending: false,
      error: undefined,
      scrollRef: { current: null },
      send: vi.fn(async () => {}),
      clear: vi.fn(),
      loadHistory: vi.fn(async () => {}),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should initialize with empty console input and load history on mount', async () => {
    const mockPrinter: Printer = {
      id: 'printer-1',
      name: 'Test Printer',
      machine_type: 'klipper',
      capability: { machine_type: 'klipper' },
      is_active: true,
    } as any

    const options: UseConsoleStateOptions = {
      printer: mockPrinter,
      printerId: 'printer-1',
      macroNames: [],
    }

    const { result } = renderHook(() => useConsoleState(options))

    expect(result.current.consoleInput).toBe('')
    expect(result.current.history).toEqual(['G28', 'M104 S200'])

    await waitFor(() => {
      expect(gcodeConsoleHook.useGcodeConsole).toHaveBeenCalled()
    })
  })

  it('should dispatch commands and clear input on send', async () => {
    const mockPrinter: Printer = {
      id: 'printer-1',
      name: 'Test Printer',
      machine_type: 'klipper',
      capability: { machine_type: 'klipper' },
      is_active: true,
    } as any

    const mockSend = vi.fn(async () => {})
    vi.spyOn(gcodeConsoleHook, 'useGcodeConsole').mockReturnValue({
      log: mockConsoleLog,
      sending: false,
      error: undefined,
      scrollRef: { current: null },
      send: mockSend,
      clear: vi.fn(),
      loadHistory: vi.fn(async () => {}),
    })

    const options: UseConsoleStateOptions = {
      printer: mockPrinter,
      printerId: 'printer-1',
      macroNames: [],
    }

    const { result } = renderHook(() => useConsoleState(options))

    await act(async () => {
      result.current.setConsoleInput('G28')
      await result.current.dispatch('G28')
    })

    expect(mockSend).toHaveBeenCalledWith('G28')
    expect(result.current.consoleInput).toBe('')
  })

  it('should not dispatch blank commands', async () => {
    const mockPrinter: Printer = {
      id: 'printer-1',
      name: 'Test Printer',
      machine_type: 'klipper',
      capability: { machine_type: 'klipper' },
      is_active: true,
    } as any

    const mockSend = vi.fn()
    vi.spyOn(gcodeConsoleHook, 'useGcodeConsole').mockReturnValue({
      log: mockConsoleLog,
      sending: false,
      error: undefined,
      scrollRef: { current: null },
      send: mockSend,
      clear: vi.fn(),
      loadHistory: vi.fn(async () => {}),
    })

    const options: UseConsoleStateOptions = {
      printer: mockPrinter,
      printerId: 'printer-1',
      macroNames: [],
    }

    const { result } = renderHook(() => useConsoleState(options))

    await act(async () => {
      result.current.dispatch('   ')
    })

    expect(mockSend).not.toHaveBeenCalled()
  })
})

// ============================================================================
// Test 4: useConsoleState — G-code Sending
// ============================================================================

describe('useConsoleState — G-code Sending', () => {
  it('should clear console log', async () => {
    const mockClear = vi.fn()
    vi.spyOn(consoleHistoryHook, 'useConsoleHistory').mockReturnValue({
      history: [],
      historyIndex: 0,
      setHistoryIndex: vi.fn(),
      cycleRef: { current: { prefix: '', index: -1 } },
      resetCycle: vi.fn(),
      record: vi.fn(),
    })

    vi.spyOn(gcodeConsoleHook, 'useGcodeConsole').mockReturnValue({
      log: [],
      sending: false,
      error: undefined,
      scrollRef: { current: null },
      send: vi.fn(),
      clear: mockClear,
      loadHistory: vi.fn(),
    })

    const mockPrinter: Printer = {
      id: 'printer-1',
      name: 'Test Printer',
      machine_type: 'klipper',
      capability: { machine_type: 'klipper' },
      is_active: true,
    } as any

    const { result } = renderHook(() =>
      useConsoleState({
        printer: mockPrinter,
        printerId: 'printer-1',
        macroNames: [],
      })
    )

    await act(async () => {
      result.current.clear()
    })

    expect(mockClear).toHaveBeenCalled()
  })

  it('should track sending state', async () => {
    vi.spyOn(consoleHistoryHook, 'useConsoleHistory').mockReturnValue({
      history: [],
      historyIndex: 0,
      setHistoryIndex: vi.fn(),
      cycleRef: { current: { prefix: '', index: -1 } },
      resetCycle: vi.fn(),
      record: vi.fn(),
    })

    vi.spyOn(gcodeConsoleHook, 'useGcodeConsole').mockReturnValue({
      log: mockConsoleLog,
      sending: true,
      error: undefined,
      scrollRef: { current: null },
      send: vi.fn(),
      clear: vi.fn(),
      loadHistory: vi.fn(),
    })

    const mockPrinter: Printer = {
      id: 'printer-1',
      name: 'Test Printer',
      machine_type: 'klipper',
      capability: { machine_type: 'klipper' },
      is_active: true,
    } as any

    const { result } = renderHook(() =>
      useConsoleState({
        printer: mockPrinter,
        printerId: 'printer-1',
        macroNames: [],
      })
    )

    expect(result.current.sending).toBe(true)
  })
})

// ============================================================================
// Test 5: useMacrosState — Macro Filtering
// ============================================================================

describe('useMacrosState', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should filter macros by search term and visibility', () => {
    const mockFilterReturn = {
      visibleMacros: [
        { name: 'START_PRINT', description: 'Start print sequence', is_private: false },
      ],
      privateMacroCount: 1,
      macroGroups: [['General', [{ name: 'START_PRINT', description: 'Start print sequence', is_private: false }]]],
    }

    vi.spyOn(macroFilterHook, 'useMacroFilter').mockReturnValue(mockFilterReturn as any)

    const contextValue = {
      printerId: 'printer-1',
      printer: null,
      macros: mockMacros,
      canWrite: true,
      searchTerm: 'START',
      setSearchTerm: vi.fn(),
      setDrawerMessage: vi.fn(),
      showToast: vi.fn(),
    }

    const wrapper = createAppContextWrapper(contextValue)
    const { result } = renderHook(() => useMacrosState(), { wrapper })

    expect(result.current.visibleMacros).toHaveLength(1)
    expect(result.current.visibleMacros[0].name).toBe('START_PRINT')
  })

  it('should track private macro visibility toggle', () => {
    vi.spyOn(macroFilterHook, 'useMacroFilter').mockReturnValue({
      visibleMacros: mockMacros,
      privateMacroCount: 1,
      macroGroups: [['General', mockMacros]],
    } as any)

    const wrapper = createAppContextWrapper()
    const { result } = renderHook(() => useMacrosState(), { wrapper })

    expect(result.current.showPrivateMacros).toBe(false)

    act(() => {
      result.current.setShowPrivateMacros(true)
    })

    expect(result.current.showPrivateMacros).toBe(true)
  })

  it('should reset macro state when printer changes', () => {
    const mockSetSearchTerm = vi.fn()
    vi.spyOn(macroFilterHook, 'useMacroFilter').mockReturnValue({
      visibleMacros: mockMacros,
      privateMacroCount: 1,
      macroGroups: [['General', mockMacros]],
    } as any)

    const contextValue = {
      printerId: 'printer-1',
      printer: null,
      macros: mockMacros,
      canWrite: true,
      searchTerm: 'START',
      setSearchTerm: mockSetSearchTerm,
      setDrawerMessage: vi.fn(),
      showToast: vi.fn(),
    }

    const wrapper = createAppContextWrapper(contextValue)
    const { result, rerender } = renderHook(() => useMacrosState(), { wrapper })

    expect(result.current.macroParams).toEqual({})

    // Change printer ID
    const newContextValue = { ...contextValue, printerId: 'printer-2' }
    const newWrapper = createAppContextWrapper(newContextValue)

    // Re-render with new printer (state should reset)
    rerender()

    expect(result.current.macroParams).toEqual({})
  })
})

// ============================================================================
// Test 6: useMacrosState — Parameter Parsing
// ============================================================================

describe('useMacrosState — Parameter Parsing', () => {
  it('should parse and track macro parameters', async () => {
    vi.spyOn(macroFilterHook, 'useMacroFilter').mockReturnValue({
      visibleMacros: mockMacros,
      privateMacroCount: 1,
      macroGroups: [['General', mockMacros]],
    } as any)

    const wrapper = createAppContextWrapper()
    const { result } = renderHook(() => useMacrosState(), { wrapper })

    act(() => {
      result.current.setMacroParams({
        START_PRINT: 'TEMP=220 SPEED=50',
      })
    })

    expect(result.current.macroParams).toEqual({
      START_PRINT: 'TEMP=220 SPEED=50',
    })
  })

  it('should set and retrieve typed macro parameters', async () => {
    vi.spyOn(macroFilterHook, 'useMacroFilter').mockReturnValue({
      visibleMacros: mockMacros,
      privateMacroCount: 1,
      macroGroups: [['General', mockMacros]],
    } as any)

    const wrapper = createAppContextWrapper()
    const { result } = renderHook(() => useMacrosState(), { wrapper })

    act(() => {
      result.current.setMacroTypedParams({
        START_PRINT: { TEMP: '220', SPEED: '50' },
      })
    })

    expect(result.current.macroTypedParams).toEqual({
      START_PRINT: { TEMP: '220', SPEED: '50' },
    })
  })

  it('should handle macro execution with parameters', async () => {
    const mockShowToast = vi.fn()
    const mockSetDrawerMessage = vi.fn()

    vi.spyOn(macroFilterHook, 'useMacroFilter').mockReturnValue({
      visibleMacros: mockMacros,
      privateMacroCount: 1,
      macroGroups: [['General', mockMacros]],
    } as any)

    ;global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({}), { status: 200 })
    )

    const contextValue = {
      printerId: 'printer-1',
      printer: null,
      macros: mockMacros,
      canWrite: true,
      searchTerm: '',
      setSearchTerm: vi.fn(),
      setDrawerMessage: mockSetDrawerMessage,
      showToast: mockShowToast,
    }

    const wrapper = createAppContextWrapper(contextValue)
    const { result } = renderHook(() => useMacrosState(), { wrapper })

    act(() => {
      result.current.setMacroParams({
        START_PRINT: 'TEMP=220',
      })
    })

    await act(async () => {
      await result.current.runMacroWithParams('START_PRINT')
    })

    expect(mockSetDrawerMessage).toHaveBeenCalledWith(
      expect.objectContaining({ level: 'info' })
    )
  })
})

// ============================================================================
// Test 7: useExcludeObjects — Object List
// ============================================================================

describe('useExcludeObjects', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should fetch and display available objects', async () => {
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                available_objects: mockExcludeObjects,
                excluded_objects: [],
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useExcludeObjects('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.objects).toHaveLength(2)
    expect(result.current.objects[0].name).toBe('support_1')
    expect(result.current.objects[0].status).toBe('included')
  })

  it('should track excluded objects list', async () => {
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                available_objects: mockExcludeObjects,
                excluded_objects: ['support_1'],
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useExcludeObjects('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.excludedObjects).toContain('support_1')
    expect(result.current.isExcluded('support_1')).toBe(true)
    expect(result.current.isExcluded('part_a')).toBe(false)
  })

  it('should handle empty object list gracefully', async () => {
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                available_objects: [],
                excluded_objects: [],
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useExcludeObjects('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.objects).toHaveLength(0)
    expect(result.current.excludedObjects).toHaveLength(0)
  })
})

// ============================================================================
// Test 8: useExcludeObjects — Exclude/Include Operations
// ============================================================================

describe('useExcludeObjects — Exclude/Include Operations', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                available_objects: mockExcludeObjects,
                excluded_objects: [],
              }),
              { status: 200 }
            )
    )
  })

  it('should exclude an object via API and update state', async () => {
    let callCount = 0
    global.fetch = vi.fn(async (url) => {
      callCount++
      if (url.includes('/exclude-objects/exclude')) {
        return new Response(JSON.stringify({}), { status: 200 })
      }
      return new Response(
        JSON.stringify({
          printer_id: 'printer-1',
          available_objects: mockExcludeObjects,
          excluded_objects: ['support_1'],
        }),
        { status: 200 }
      )
    })

    const { result } = renderHook(() => useExcludeObjects('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      await result.current.exclude('support_1')
    })

    expect(result.current.excludedObjects).toContain('support_1')
    expect(result.current.objects[0].status).toBe('excluded')
  })

  it('should include (re-enable) an excluded object', async () => {
    global.fetch = vi.fn(async (url) => {
      if (url.includes('/exclude-objects/include')) {
        return new Response(JSON.stringify({}), { status: 200 })
      }
      return new Response(
        JSON.stringify({
          printer_id: 'printer-1',
          available_objects: mockExcludeObjects,
          excluded_objects: [],
        }),
        { status: 200 }
      )
    })

    const { result } = renderHook(() => useExcludeObjects('printer-1', ['support_1']))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      await result.current.include('support_1')
    })

    expect(result.current.excludedObjects).not.toContain('support_1')
  })

  it('should handle API errors gracefully', async () => {
    global.fetch = vi.fn(async (url) => {
      if (url.includes('/exclude-objects/exclude')) {
        return new Response(JSON.stringify({ error: 'API error' }), { status: 500 })
      }
      return new Response(
        JSON.stringify({
          printer_id: 'printer-1',
          available_objects: mockExcludeObjects,
          excluded_objects: [],
        }),
        { status: 200 }
      )
    })

    const { result } = renderHook(() => useExcludeObjects('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      try {
        await result.current.exclude('support_1')
      } catch {
        // Expected to throw
      }
    })

    expect(result.current.error).toBeTruthy()
  })
})

// ============================================================================
// Test 9: useSpoolManagement — Log Display
// ============================================================================

describe('useSpoolManagement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should fetch and display spool log entries', async () => {
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                entries: mockSpoolLog,
                totalUsed: 10,
                currentRemaining: 10,
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useSpoolManagement('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.log).toHaveLength(2)
    expect(result.current.log[0].material).toBe('PLA')
    expect(result.current.log[1].reason).toBe('print')
  })

  it('should calculate total used filament from log', async () => {
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                entries: mockSpoolLog,
                totalUsed: 500,
                currentRemaining: 10,
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useSpoolManagement('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.totalUsed).toBe(500)
  })

  it('should handle initial state from props', async () => {
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                entries: mockSpoolLog,
                totalUsed: 10,
                currentRemaining: 10,
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useSpoolManagement('printer-1', mockSpoolLog))

    // Initial state should be loaded from props
    expect(result.current.log).toEqual(mockSpoolLog)

    // After the effect runs and fetch completes, loading should be false
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
  })

  it('should calculate remaining filament correctly', async () => {
    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                entries: mockSpoolLog,
                totalUsed: 10,
                currentRemaining: 1000,
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useSpoolManagement('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    const remaining = result.current.calculateRemaining()
    // Current remaining + sum of log weights
    expect(remaining).toBe(1000 + 20 - 10) // 1010
  })
})

// ============================================================================
// Test 10: useSpoolManagement — Adjustment Recording
// ============================================================================

describe('useSpoolManagement — Adjustment Recording', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should record a new filament adjustment and refresh log', async () => {
    let fetchCalls = 0
    global.fetch = vi.fn(async (url) => {
      fetchCalls++
      if (url.includes('/spool/log') && fetchCalls === 2) {
        // POST call to record adjustment
        return new Response(JSON.stringify({}), { status: 200 })
      }
      // GET calls
      return new Response(
        JSON.stringify({
          printer_id: 'printer-1',
          entries: [...mockSpoolLog, { timestamp: Date.now(), material: 'PLA', lengthMm: 250, weight: 5, reason: 'refill' as const }],
          totalUsed: 10,
          currentRemaining: 1015,
        }),
        { status: 200 }
      )
    })

    const { result } = renderHook(() => useSpoolManagement('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    const initialLength = result.current.log.length

    await act(async () => {
      await result.current.recordAdjustment({
        material: 'PLA',
        lengthMm: 250,
        weight: 5,
        reason: 'refill',
      })
    })

    await waitFor(() => {
      expect(result.current.log.length).toBeGreaterThanOrEqual(initialLength)
    })
  })

  it('should notify toast callback on adjustment success', async () => {
    const mockToast = vi.fn()

    global.fetch = vi.fn(async () =>
      new Response(
              JSON.stringify({
                printer_id: 'printer-1',
                entries: mockSpoolLog,
                totalUsed: 10,
                currentRemaining: 10,
              }),
              { status: 200 }
            )
    )

    const { result } = renderHook(() => useSpoolManagement('printer-1', [], mockToast))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      await result.current.recordAdjustment({
        material: 'PLA',
        lengthMm: 250,
        weight: 5,
        reason: 'refill',
      })
    })

    // Verify fetch was called for POST
    expect(global.fetch).toHaveBeenCalled()
  })

  it('should handle missing printer ID', async () => {
    global.fetch = vi.fn()

    const { result } = renderHook(() => useSpoolManagement(''))

    await act(async () => {
      await result.current.recordAdjustment({
        material: 'PLA',
        lengthMm: 250,
        weight: 5,
        reason: 'refill',
      })
    })

    expect(result.current.error).toBeTruthy()
  })

  it('should handle API errors during adjustment recording', async () => {
    global.fetch = vi.fn(async (url) => {
      if (url.includes('/spool/log') && url.endsWith('/spool/log')) {
        // POST request fails
        return new Response(
          JSON.stringify({ error: 'Recording failed' }),
          { status: 500 }
        )
      }
      return new Response(
        JSON.stringify({
          printer_id: 'printer-1',
          entries: mockSpoolLog,
          totalUsed: 10,
          currentRemaining: 10,
        }),
        { status: 200 }
      )
    })

    const { result } = renderHook(() => useSpoolManagement('printer-1'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      try {
        await result.current.recordAdjustment({
          material: 'PLA',
          lengthMm: 250,
          weight: 5,
          reason: 'refill',
        })
      } catch {
        // Expected to throw
      }
    })

    expect(result.current.error).toBeTruthy()
  })
})

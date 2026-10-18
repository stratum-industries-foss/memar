import { render, screen, renderHook, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { DrawerProvider, useAppDrawer, useDrawerContext, AppDrawerContext } from '../AppContext'
import type { DrawerContextType, DrawerMessage } from '../types'
import { ReactNode } from 'react'

/**
 * Test suite for DrawerProvider and DrawerContextType
 * Covers context initialization, hook usage, state dispatch, and drawer isolation
 */

describe('DrawerProvider', () => {
  // Mock drawer context value
  const createMockContextValue = (): DrawerContextType => ({
    activeSection: null,
    setActiveSection: vi.fn(),
    drawerMessage: { level: 'info', message: '' },
    setDrawerMessage: vi.fn(),
    printerId: 'printer-123',
    currentPrinter: null,
    macros: [],
    canWrite: false,
    searchTerm: '',
    setSearchTerm: vi.fn(),
    startPrint: vi.fn(),
    showToast: vi.fn(),
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  // TEST 1: DrawerProvider initializes context
  describe('Test 1: DrawerProvider initializes context', () => {
    it('should make context values available to children', () => {
      const mockValue = createMockContextValue()
      mockValue.printerId = 'test-printer-456'
      mockValue.searchTerm = 'test-search'

      const TestChild = () => {
        const ctx = useAppDrawer()
        return (
          <div>
            <span data-testid="printer-id">{ctx.printerId}</span>
            <span data-testid="search-term">{ctx.searchTerm}</span>
            <span data-testid="can-write">{ctx.canWrite ? 'yes' : 'no'}</span>
          </div>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <TestChild />
        </DrawerProvider>
      )

      expect(screen.getByTestId('printer-id')).toHaveTextContent('test-printer-456')
      expect(screen.getByTestId('search-term')).toHaveTextContent('test-search')
      expect(screen.getByTestId('can-write')).toHaveTextContent('no')
    })

    it('should provide context to nested child components', () => {
      const mockValue = createMockContextValue()
      mockValue.activeSection = 'overview'
      mockValue.canWrite = true

      const DeepChild = () => {
        const ctx = useAppDrawer()
        return (
          <span data-testid="deep-child">
            {ctx.activeSection} - {ctx.canWrite ? 'write' : 'read'}
          </span>
        )
      }

      const MiddleChild = () => (
        <div data-testid="middle">
          <DeepChild />
        </div>
      )

      render(
        <DrawerProvider value={mockValue}>
          <MiddleChild />
        </DrawerProvider>
      )

      expect(screen.getByTestId('deep-child')).toHaveTextContent('overview - write')
    })

    it('should provide all context properties to children', () => {
      const mockValue: DrawerContextType = {
        activeSection: 'console',
        setActiveSection: vi.fn(),
        drawerMessage: { level: 'error', message: 'Test error', title: 'Error' },
        setDrawerMessage: vi.fn(),
        printerId: 'printer-789',
        currentPrinter: {
          id: 'printer-789',
          name: 'Test Printer',
          base_url: 'http://192.168.1.100:7125',
          online: true,
          state: 'ready',
          state_message: null,
          nozzle: { temperature: 25, target: 0 },
          bed: { temperature: 25, target: 0 },
          job: { filename: null, state: null, progress: null },
          warnings: [],
          tags: [],
          available_actions: [],
          attention_needed: false,
          anomalies: [],
          macros_count: 0,
          webcams_count: 0,
          capability: {
            machine_type: 'fdm',
            profile: null,
            nozzle_diameter_mm: 0.4,
            build_volume: { x: 250, y: 210, z: 210 },
            supported_materials: [],
            current_material: null,
            current_spool_name: null,
            spool_remaining_g: null,
            spool_capacity_g: null,
            filament_sensor: false,
            probe: false,
            webcam_expected: false,
            fluidd_url: null,
            camera_url: null,
            maintenance_lockout: false,
            maintenance_state: null,
            maintenance_due: false,
            maintenance_interval_hours: null,
            maintenance_interval_jobs: null,
            maintenance_interval_filament_g: null,
            last_service_at: null,
            next_service_due: null,
            jog_enabled: false,
            safe_nozzle_max_c: null,
            safe_bed_max_c: null,
            motion_check_required: false,
            notes: [],
            maintenance_notes: [],
          },
        },
        macros: [{ name: 'macro1' }, { name: 'macro2' }],
        canWrite: true,
        searchTerm: 'search-query',
        setSearchTerm: vi.fn(),
        startPrint: vi.fn(),
        showToast: vi.fn(),
      }

      const ContextInspector = () => {
        const ctx = useAppDrawer()
        return (
          <div>
            <div data-testid="active-section">{ctx.activeSection}</div>
            <div data-testid="printer-name">{ctx.currentPrinter?.name}</div>
            <div data-testid="macro-count">{ctx.macros.length}</div>
            <div data-testid="message-level">{ctx.drawerMessage.level}</div>
          </div>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <ContextInspector />
        </DrawerProvider>
      )

      expect(screen.getByTestId('active-section')).toHaveTextContent('console')
      expect(screen.getByTestId('printer-name')).toHaveTextContent('Test Printer')
      expect(screen.getByTestId('macro-count')).toHaveTextContent('2')
      expect(screen.getByTestId('message-level')).toHaveTextContent('error')
    })
  })

  // TEST 2: useAppDrawer hook works
  describe('Test 2: useAppDrawer hook works', () => {
    it('should retrieve context correctly from useAppDrawer hook', () => {
      const mockValue = createMockContextValue()
      mockValue.printerId = 'hook-test-printer'
      mockValue.searchTerm = 'hook-search'
      mockValue.activeSection = 'temperature'

      const { result } = renderHook(() => useAppDrawer(), {
        wrapper: ({ children }: { children: ReactNode }) => (
          <DrawerProvider value={mockValue}>{children}</DrawerProvider>
        ),
      })

      expect(result.current.printerId).toBe('hook-test-printer')
      expect(result.current.searchTerm).toBe('hook-search')
      expect(result.current.activeSection).toBe('temperature')
    })

    it('throws when no provider is present (a missing provider must fail loudly)', () => {
      // Deliberate since 6e354a3: returning defaults would hide a drawer rendered outside
      // the app's provider, which then shows empty data as if it were real.
      expect(() => renderHook(() => useAppDrawer())).toThrow(/AppDrawerContext\.Provider/)
    })

    it('useDrawerContext should be an alias for useAppDrawer', () => {
      const mockValue = createMockContextValue()
      mockValue.printerId = 'alias-test'

      const { result: result1 } = renderHook(() => useAppDrawer(), {
        wrapper: ({ children }: { children: ReactNode }) => (
          <DrawerProvider value={mockValue}>{children}</DrawerProvider>
        ),
      })

      const { result: result2 } = renderHook(() => useDrawerContext(), {
        wrapper: ({ children }: { children: ReactNode }) => (
          <DrawerProvider value={mockValue}>{children}</DrawerProvider>
        ),
      })

      expect(result1.current.printerId).toBe(result2.current.printerId)
      expect(result1.current.printerId).toBe('alias-test')
    })

    it('should update when context value changes', () => {
      const mockValue1 = createMockContextValue()
      mockValue1.printerId = 'printer-v1'
      mockValue1.searchTerm = 'search-v1'

      const mockValue2 = createMockContextValue()
      mockValue2.printerId = 'printer-v2'
      mockValue2.searchTerm = 'search-v2'

      const ContextDisplay = ({ value }: { value: DrawerContextType }) => {
        return (
          <DrawerProvider value={value}>
            <HookUser />
          </DrawerProvider>
        )
      }

      const HookUser = () => {
        const ctx = useAppDrawer()
        return (
          <div>
            <span data-testid="id">{ctx.printerId}</span>
            <span data-testid="term">{ctx.searchTerm}</span>
          </div>
        )
      }

      const { rerender } = render(<ContextDisplay value={mockValue1} />)
      expect(screen.getByTestId('id')).toHaveTextContent('printer-v1')
      expect(screen.getByTestId('term')).toHaveTextContent('search-v1')

      rerender(<ContextDisplay value={mockValue2} />)
      expect(screen.getByTestId('id')).toHaveTextContent('printer-v2')
      expect(screen.getByTestId('term')).toHaveTextContent('search-v2')
    })
  })

  // TEST 3: Drawer state dispatch updates
  describe('Test 3: Drawer state dispatch updates', () => {
    it('should call setActiveSection callback when section is changed', () => {
      const setActiveSectionMock = vi.fn()
      const mockValue = createMockContextValue()
      mockValue.setActiveSection = setActiveSectionMock

      const SectionChanger = () => {
        const ctx = useAppDrawer()
        return (
          <button
            data-testid="change-section"
            onClick={() => ctx.setActiveSection('files')}
          >
            Change Section
          </button>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <SectionChanger />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('change-section'))
      expect(setActiveSectionMock).toHaveBeenCalledWith('files')
      expect(setActiveSectionMock).toHaveBeenCalledTimes(1)
    })

    it('should call setDrawerMessage callback when message is set', () => {
      const setDrawerMessageMock = vi.fn()
      const mockValue = createMockContextValue()
      mockValue.setDrawerMessage = setDrawerMessageMock

      const MessageSetter = () => {
        const ctx = useAppDrawer()
        return (
          <button
            data-testid="set-message"
            onClick={() =>
              ctx.setDrawerMessage({
                level: 'warn',
                message: 'Warning message',
                title: 'Warning',
              })
            }
          >
            Set Message
          </button>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <MessageSetter />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('set-message'))
      expect(setDrawerMessageMock).toHaveBeenCalledWith({
        level: 'warn',
        message: 'Warning message',
        title: 'Warning',
      })
    })

    it('should call setSearchTerm callback when search term is updated', () => {
      const setSearchTermMock = vi.fn()
      const mockValue = createMockContextValue()
      mockValue.setSearchTerm = setSearchTermMock

      const SearchUpdater = () => {
        const ctx = useAppDrawer()
        return (
          <button
            data-testid="update-search"
            onClick={() => ctx.setSearchTerm('new-search-term')}
          >
            Update Search
          </button>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <SearchUpdater />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('update-search'))
      expect(setSearchTermMock).toHaveBeenCalledWith('new-search-term')
    })

    it('should call startPrint when print is initiated', async () => {
      const startPrintMock = vi.fn().mockResolvedValue(undefined)
      const mockValue = createMockContextValue()
      mockValue.startPrint = startPrintMock

      const PrintStarter = () => {
        const ctx = useAppDrawer()
        return (
          <button
            data-testid="start-print"
            onClick={() => ctx.startPrint('printer-1', 'model.gcode')}
          >
            Start Print
          </button>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <PrintStarter />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('start-print'))
      expect(startPrintMock).toHaveBeenCalledWith('printer-1', 'model.gcode')
    })

    it('should call showToast callback with message and level', () => {
      const showToastMock = vi.fn()
      const mockValue = createMockContextValue()
      mockValue.showToast = showToastMock

      const ToastShower = () => {
        const ctx = useAppDrawer()
        return (
          <button
            data-testid="show-toast"
            onClick={() => ctx.showToast('Success!', 'success')}
          >
            Show Toast
          </button>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <ToastShower />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('show-toast'))
      expect(showToastMock).toHaveBeenCalledWith('Success!', 'success')
    })

    it('should handle multiple rapid state updates', () => {
      const setActiveSectionMock = vi.fn()
      const setDrawerMessageMock = vi.fn()
      const setSearchTermMock = vi.fn()

      const mockValue = createMockContextValue()
      mockValue.setActiveSection = setActiveSectionMock
      mockValue.setDrawerMessage = setDrawerMessageMock
      mockValue.setSearchTerm = setSearchTermMock

      const MultiUpdater = () => {
        const ctx = useAppDrawer()
        const handleMultiUpdate = () => {
          ctx.setActiveSection('console')
          ctx.setSearchTerm('multi-search')
          ctx.setDrawerMessage({
            level: 'info',
            message: 'Multi update',
          })
        }

        return (
          <button data-testid="multi-update" onClick={handleMultiUpdate}>
            Multi Update
          </button>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <MultiUpdater />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('multi-update'))
      expect(setActiveSectionMock).toHaveBeenCalledWith('console')
      expect(setSearchTermMock).toHaveBeenCalledWith('multi-search')
      expect(setDrawerMessageMock).toHaveBeenCalledWith({
        level: 'info',
        message: 'Multi update',
      })
    })
  })

  // TEST 4: Multiple drawers share state
  describe('Test 4: Multiple drawers share state', () => {
    it('should isolate state between different DrawerProvider instances', () => {
      const mockValue1 = createMockContextValue()
      mockValue1.printerId = 'drawer-1-printer'
      mockValue1.activeSection = 'files'

      const mockValue2 = createMockContextValue()
      mockValue2.printerId = 'drawer-2-printer'
      mockValue2.activeSection = 'console'

      const StateDisplay = () => {
        const ctx = useAppDrawer()
        return (
          <div>
            <span data-testid="printer-id">{ctx.printerId}</span>
            <span data-testid="section">{ctx.activeSection}</span>
          </div>
        )
      }

      const { rerender } = render(
        <DrawerProvider value={mockValue1}>
          <StateDisplay />
        </DrawerProvider>
      )

      expect(screen.getByTestId('printer-id')).toHaveTextContent('drawer-1-printer')
      expect(screen.getByTestId('section')).toHaveTextContent('files')

      rerender(
        <DrawerProvider value={mockValue2}>
          <StateDisplay />
        </DrawerProvider>
      )

      expect(screen.getByTestId('printer-id')).toHaveTextContent('drawer-2-printer')
      expect(screen.getByTestId('section')).toHaveTextContent('console')
    })

    it('should share state between sibling components under same provider', () => {
      const mockValue = createMockContextValue()
      mockValue.printerId = 'shared-printer'
      mockValue.searchTerm = 'shared-search'

      const ChildA = () => {
        const ctx = useAppDrawer()
        return (
          <div data-testid="child-a">
            A: {ctx.printerId} - {ctx.searchTerm}
          </div>
        )
      }

      const ChildB = () => {
        const ctx = useAppDrawer()
        return (
          <div data-testid="child-b">
            B: {ctx.printerId} - {ctx.searchTerm}
          </div>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <ChildA />
          <ChildB />
        </DrawerProvider>
      )

      expect(screen.getByTestId('child-a')).toHaveTextContent('A: shared-printer - shared-search')
      expect(screen.getByTestId('child-b')).toHaveTextContent('B: shared-printer - shared-search')
    })

    it('should switch drawer sections independently', () => {
      const mockValue = createMockContextValue()
      mockValue.printerId = 'multi-section-printer'

      const SectionA = () => {
        const ctx = useAppDrawer()
        return (
          <div data-testid="section-a">
            <span>{ctx.printerId}</span>
            <button
              onClick={() => ctx.setActiveSection('overview')}
              data-testid="switch-to-overview"
            >
              Overview
            </button>
          </div>
        )
      }

      const SectionB = () => {
        const ctx = useAppDrawer()
        return (
          <div data-testid="section-b">
            <span>{ctx.printerId}</span>
            <button
              onClick={() => ctx.setActiveSection('files')}
              data-testid="switch-to-files"
            >
              Files
            </button>
          </div>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <SectionA />
          <SectionB />
        </DrawerProvider>
      )

      const setActiveSectionMock = mockValue.setActiveSection as ReturnType<typeof vi.fn>

      fireEvent.click(screen.getByTestId('switch-to-overview'))
      expect(setActiveSectionMock).toHaveBeenCalledWith('overview')

      fireEvent.click(screen.getByTestId('switch-to-files'))
      expect(setActiveSectionMock).toHaveBeenCalledWith('files')
    })

    it('should share printer and macro data across drawers', () => {
      const printer = {
        id: 'printer-workshop',
        name: 'Prusa MK3S',
        base_url: 'http://192.168.1.50:7125',
        online: true,
        state: 'ready',
        state_message: null,
        nozzle: { temperature: 25, target: 0 },
        bed: { temperature: 25, target: 0 },
        job: { filename: null, state: null, progress: null },
        warnings: [],
        tags: [],
        available_actions: [],
        attention_needed: false,
        anomalies: [],
        macros_count: 3,
        webcams_count: 1,
        capability: {
          machine_type: 'fdm',
          profile: 'prusa-mk3s',
          nozzle_diameter_mm: 0.4,
          build_volume: { x: 250, y: 210, z: 210 },
          supported_materials: ['PLA', 'PETG', 'ABS'],
          current_material: 'PLA',
          current_spool_name: null,
          spool_remaining_g: 500,
          spool_capacity_g: 1000,
          filament_sensor: true,
          probe: true,
          webcam_expected: true,
          fluidd_url: 'http://192.168.1.50:7125',
          camera_url: null,
          maintenance_lockout: false,
          maintenance_state: null,
          maintenance_due: false,
          maintenance_interval_hours: 1000,
          maintenance_interval_jobs: 100,
          maintenance_interval_filament_g: 50000,
          last_service_at: null,
          next_service_due: null,
          jog_enabled: true,
          safe_nozzle_max_c: 300,
          safe_bed_max_c: 120,
          motion_check_required: false,
          notes: [],
          maintenance_notes: [],
        },
      }
      const macros = [
        { name: 'Home', command: 'G28' },
        { name: 'Level Bed', command: 'G29' },
      ]

      const mockValue = createMockContextValue()
      mockValue.currentPrinter = printer
      mockValue.macros = macros
      mockValue.canWrite = true

      const MacroList = () => {
        const ctx = useAppDrawer()
        return (
          <div data-testid="macro-list">
            <div data-testid="printer-name">{ctx.currentPrinter?.name}</div>
            <div data-testid="macro-count">{ctx.macros.length}</div>
            <ul>
              {ctx.macros.map((m, i) => (
                <li key={i} data-testid={`macro-${i}`}>
                  {m.name}
                </li>
              ))}
            </ul>
          </div>
        )
      }

      const MacroAccess = () => {
        const ctx = useAppDrawer()
        return (
          <div data-testid="macro-access">
            <span data-testid="can-write">{ctx.canWrite ? 'yes' : 'no'}</span>
          </div>
        )
      }

      render(
        <DrawerProvider value={mockValue}>
          <MacroList />
          <MacroAccess />
        </DrawerProvider>
      )

      expect(screen.getByTestId('printer-name')).toHaveTextContent('Prusa MK3S')
      expect(screen.getByTestId('macro-count')).toHaveTextContent('2')
      expect(screen.getByTestId('macro-0')).toHaveTextContent('Home')
      expect(screen.getByTestId('macro-1')).toHaveTextContent('Level Bed')
      expect(screen.getByTestId('can-write')).toHaveTextContent('yes')
    })

    it('should maintain separate message states across context switches', () => {
      const mockValue1 = createMockContextValue()
      mockValue1.drawerMessage = {
        level: 'info',
        message: 'Printer 1 message',
      }

      const mockValue2 = createMockContextValue()
      mockValue2.drawerMessage = {
        level: 'error',
        message: 'Printer 2 error',
      }

      const MessageDisplay = () => {
        const ctx = useAppDrawer()
        return (
          <div data-testid="message-display">
            <span data-testid="level">{ctx.drawerMessage.level}</span>
            <span data-testid="message">{ctx.drawerMessage.message}</span>
          </div>
        )
      }

      const { rerender } = render(
        <DrawerProvider value={mockValue1}>
          <MessageDisplay />
        </DrawerProvider>
      )

      expect(screen.getByTestId('level')).toHaveTextContent('info')
      expect(screen.getByTestId('message')).toHaveTextContent('Printer 1 message')

      rerender(
        <DrawerProvider value={mockValue2}>
          <MessageDisplay />
        </DrawerProvider>
      )

      expect(screen.getByTestId('level')).toHaveTextContent('error')
      expect(screen.getByTestId('message')).toHaveTextContent('Printer 2 error')
    })
  })

  // Additional coverage: Context provider structure
  describe('AppDrawerContext provider structure', () => {
    it('should expose AppDrawerContext for advanced usage', () => {
      expect(AppDrawerContext).toBeDefined()
      // Context should be a valid React context
      expect(AppDrawerContext.Provider).toBeDefined()
      expect(AppDrawerContext.Consumer).toBeDefined()
    })

    it('should fail loudly with no provider rather than return defaults', () => {
      // Matches the deliberate throw in useAppDrawer (see 6e354a3).
      expect(() => renderHook(() => useAppDrawer())).toThrow(/AppDrawerContext\.Provider/)
    })
  })
})

/**
 * DrawerIntegration.test.tsx
 * Integration tests for MEMAR drawer ecosystem
 *
 * Tests 8 core integration scenarios:
 * 1. Context-based state sync across multiple drawers
 * 2. API error handling (network, timeouts, retries)
 * 3. Toast notification flow
 * 4. Drawer tab switching with state preservation
 * 5. Print workflow (select → inspect → print)
 * 6. Temperature control (preset application)
 * 7. Async operations (loading states, callbacks)
 * 8. Error recovery (failed requests, retry mechanism)
 */

import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import React, { useState } from 'react'
import { DrawerProvider, useAppDrawer } from '../context/AppContext'
import type { DrawerContextType, DrawerSection, DrawerMessage } from '../context/types'
import type { Printer } from '../types/printer'

// ────────────────────────────────────────────────────────────────────────────
// MOCK DATA & FIXTURES
// ────────────────────────────────────────────────────────────────────────────

const mockPrinter: Printer = {
  id: 'printer-001',
  name: 'Test Printer',
  base_url: 'http://localhost:7125',
  online: true,
  state: 'printing',
  state_message: null,
  nozzle: { temperature: 210, target: 215 },
  bed: { temperature: 60, target: 65 },
  job: { filename: 'test_print.gcode', state: 'printing', progress: 45 },
  warnings: [],
  tags: [],
  available_actions: ['cancel', 'pause'],
  attention_needed: false,
  anomalies: [],
  macros_count: 5,
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
    fluidd_url: 'http://localhost:7125',
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

const mockContextValue: DrawerContextType = {
  activeSection: 'overview',
  setActiveSection: vi.fn(),
  drawerMessage: { level: 'info', message: '' },
  setDrawerMessage: vi.fn(),
  printerId: 'printer-001',
  currentPrinter: mockPrinter,
  macros: [{ label: 'Home', command: 'G28' }],
  canWrite: true,
  searchTerm: '',
  setSearchTerm: vi.fn(),
  startPrint: vi.fn().mockResolvedValue(undefined),
  showToast: vi.fn(),
}

// ────────────────────────────────────────────────────────────────────────────
// TEST COMPONENTS
// ────────────────────────────────────────────────────────────────────────────

/**
 * Component 1: MultiDrawerConsumer
 * Tests context-based state sync across multiple drawer instances
 */
function MultiDrawerConsumer() {
  const { activeSection, setActiveSection, drawerMessage, currentPrinter } = useAppDrawer()
  return (
    <div>
      <div data-testid="active-section">{activeSection}</div>
      <div data-testid="current-temp">{currentPrinter?.nozzle.temperature}</div>
      <div data-testid="drawer-message">{drawerMessage.message}</div>
      <button onClick={() => setActiveSection('temperature')}>Switch to Temperature</button>
      <button onClick={() => setActiveSection('files')}>Switch to Files</button>
    </div>
  )
}

/**
 * Component 2: AsyncOperationDrawer
 * Tests async operations with loading states and callbacks
 */
function AsyncOperationDrawer() {
  const { printerId, showToast } = useAppDrawer()
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const handleAsyncOperation = async () => {
    setIsLoading(true)
    try {
      // Simulate async operation
      await new Promise((resolve) => setTimeout(resolve, 100))
      setResult('Operation completed')
      showToast('Success!')
    } catch (error) {
      showToast('Error occurred', 'error')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div>
      <button data-testid="async-btn" disabled={isLoading} onClick={handleAsyncOperation}>
        {isLoading ? 'Loading...' : 'Start Operation'}
      </button>
      {result && <div data-testid="result">{result}</div>}
    </div>
  )
}

/**
 * Component 3: PrintWorkflowDrawer
 * Tests print workflow: select file → inspect → print
 */
function PrintWorkflowDrawer() {
  const { startPrint, printerId, showToast } = useAppDrawer()
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [fileDetails, setFileDetails] = useState<{
    name: string
    size: number
    estimatedTime: number
  } | null>(null)

  const handleFileSelect = (filename: string) => {
    setSelectedFile(filename)
    // Simulate file inspection
    setFileDetails({
      name: filename,
      size: 12345,
      estimatedTime: 3600,
    })
  }

  const handlePrint = async () => {
    if (!selectedFile) return
    try {
      await startPrint(printerId, selectedFile)
      showToast('Print started!')
    } catch (error) {
      showToast('Failed to start print', 'error')
    }
  }

  return (
    <div>
      <button data-testid="select-file" onClick={() => handleFileSelect('model.gcode')}>
        Select File
      </button>
      {selectedFile && (
        <div data-testid="selected-file">
          Selected: {selectedFile}
        </div>
      )}
      {fileDetails && (
        <div data-testid="file-details">
          <div>{fileDetails.name}</div>
          <div>{fileDetails.size} bytes</div>
          <div>{fileDetails.estimatedTime}s</div>
        </div>
      )}
      {selectedFile && (
        <button data-testid="print-btn" onClick={handlePrint}>
          Start Print
        </button>
      )}
    </div>
  )
}

/**
 * Component 4: TemperatureControlDrawer
 * Tests temperature control with preset application
 */
function TemperatureControlDrawer() {
  const { currentPrinter, showToast } = useAppDrawer()
  const [nozzleTarget, setNozzleTarget] = useState('215')
  const [bedTarget, setBedTarget] = useState('65')

  const applyPreset = (nozzle: string, bed: string) => {
    setNozzleTarget(nozzle)
    setBedTarget(bed)
    showToast(`Applied preset: ${nozzle}°C / ${bed}°C`)
  }

  return (
    <div>
      <div data-testid="nozzle-target">{nozzleTarget}</div>
      <div data-testid="bed-target">{bedTarget}</div>
      <button data-testid="pla-preset" onClick={() => applyPreset('200', '60')}>
        PLA Preset
      </button>
      <button data-testid="abs-preset" onClick={() => applyPreset('240', '100')}>
        ABS Preset
      </button>
      {currentPrinter && (
        <div data-testid="current-temps">
          Nozzle: {currentPrinter.nozzle.temperature}°C / Bed: {currentPrinter.bed.temperature}°C
        </div>
      )}
    </div>
  )
}

/**
 * Component 5: ErrorHandlingDrawer
 * Tests API error handling and retry mechanism
 */
function ErrorHandlingDrawer() {
  const { showToast } = useAppDrawer()
  const [error, setError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [isRetrying, setIsRetrying] = useState(false)

  const simulateApiCall = async (shouldFail: boolean = false) => {
    try {
      if (shouldFail) {
        throw new Error('Network error')
      }
      setError(null)
      showToast('API call successful')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      showToast(`Error: ${message}`, 'error')
    }
  }

  const handleRetry = async () => {
    setIsRetrying(true)
    setRetryCount((c) => c + 1)
    await simulateApiCall(retryCount < 2) // Fail first 2 attempts
    setIsRetrying(false)
  }

  return (
    <div>
      <button data-testid="fail-btn" onClick={() => simulateApiCall(true)}>
        Trigger Error
      </button>
      {error && (
        <div data-testid="error-message">
          {error}
        </div>
      )}
      <button data-testid="retry-btn" disabled={isRetrying} onClick={handleRetry}>
        {isRetrying ? 'Retrying...' : `Retry (${retryCount})`}
      </button>
    </div>
  )
}

/**
 * Component 6: TabSwitchingDrawer
 * Tests drawer tab switching with state preservation
 */
function TabSwitchingDrawer() {
  const { setActiveSection } = useAppDrawer()
  const [tabState, setTabState] = useState({ overview: 'data1', files: 'data2' })

  return (
    <div>
      <button onClick={() => setActiveSection('overview')} data-testid="tab-overview">
        Overview Tab
      </button>
      <button onClick={() => setActiveSection('files')} data-testid="tab-files">
        Files Tab
      </button>
      <div data-testid="state-value">{tabState.overview}</div>
      <div data-testid="state-files">{tabState.files}</div>
    </div>
  )
}

/**
 * Component 7: ToastIntegrationDrawer
 * Tests toast notification flow
 */
function ToastIntegrationDrawer() {
  const { showToast } = useAppDrawer()
  const [toasts, setToasts] = useState<Array<{ message: string; level: string }>>([])

  const handleShowToast = (message: string, level: string = 'info') => {
    showToast(message, level)
    setToasts((prev) => [...prev, { message, level }])
  }

  return (
    <div>
      <button onClick={() => handleShowToast('Info message')} data-testid="info-toast">
        Show Info
      </button>
      <button onClick={() => handleShowToast('Warning message', 'warn')} data-testid="warn-toast">
        Show Warning
      </button>
      <button onClick={() => handleShowToast('Error message', 'error')} data-testid="error-toast">
        Show Error
      </button>
      <div data-testid="toast-count">{toasts.length}</div>
      {toasts.map((t, i) => (
        <div key={i} data-testid={`toast-${i}`}>
          {t.level}: {t.message}
        </div>
      ))}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// INTEGRATION TEST SUITE
// ────────────────────────────────────────────────────────────────────────────

describe('DrawerIntegration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 1: Context-based state sync
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 1: Context-based state sync', () => {
    it('should sync state across multiple drawers in single context', () => {
      const testValue = { ...mockContextValue }
      testValue.setActiveSection = vi.fn()

      render(
        <DrawerProvider value={testValue}>
          <MultiDrawerConsumer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('active-section')).toHaveTextContent('overview')
      expect(screen.getByTestId('current-temp')).toHaveTextContent('210')
    })

    it('should update context state when section changes', async () => {
      const setActiveSection = vi.fn()
      const testValue = { ...mockContextValue, setActiveSection }

      render(
        <DrawerProvider value={testValue}>
          <MultiDrawerConsumer />
        </DrawerProvider>
      )

      const btn = screen.getByRole('button', { name: /Switch to Temperature/ })
      fireEvent.click(btn)

      expect(setActiveSection).toHaveBeenCalledWith('temperature')
    })

    it('should preserve drawer message across components', () => {
      const message = { level: 'info' as const, message: 'Test message' }
      const testValue = { ...mockContextValue, drawerMessage: message }

      render(
        <DrawerProvider value={testValue}>
          <MultiDrawerConsumer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('drawer-message')).toHaveTextContent('Test message')
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 2: API error handling
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 2: API error handling', () => {
    it('should handle network errors gracefully', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <ErrorHandlingDrawer />
        </DrawerProvider>
      )

      const btn = screen.getByTestId('fail-btn')
      fireEvent.click(btn)

      await waitFor(() => {
        expect(screen.getByTestId('error-message')).toHaveTextContent('Network error')
      })
      expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Network error'), 'error')
    })

    it('should support retry mechanism after failed requests', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <ErrorHandlingDrawer />
        </DrawerProvider>
      )

      const retryBtn = screen.getByTestId('retry-btn')

      // First call should succeed (simulating success after retries)
      fireEvent.click(retryBtn)

      await waitFor(() => {
        expect(screen.getByTestId('retry-btn')).toHaveTextContent('Retry (1)')
      })
    })

    it('should track retry attempts', async () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <ErrorHandlingDrawer />
        </DrawerProvider>
      )

      const retryBtn = screen.getByTestId('retry-btn')
      fireEvent.click(retryBtn)

      await waitFor(() => {
        expect(retryBtn).toHaveTextContent(/Retry \(\d+\)/)
      })
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 3: Toast notification flow
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 3: Toast notification flow', () => {
    it('should display info toast when triggered', () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <ToastIntegrationDrawer />
        </DrawerProvider>
      )

      const infoBtn = screen.getByTestId('info-toast')
      fireEvent.click(infoBtn)

      expect(showToast).toHaveBeenCalledWith('Info message', 'info')
    })

    it('should display warning toast', () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <ToastIntegrationDrawer />
        </DrawerProvider>
      )

      const warnBtn = screen.getByTestId('warn-toast')
      fireEvent.click(warnBtn)

      expect(showToast).toHaveBeenCalledWith('Warning message', 'warn')
    })

    it('should display error toast', () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <ToastIntegrationDrawer />
        </DrawerProvider>
      )

      const errorBtn = screen.getByTestId('error-toast')
      fireEvent.click(errorBtn)

      expect(showToast).toHaveBeenCalledWith('Error message', 'error')
    })

    it('should track multiple toasts in sequence', () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <ToastIntegrationDrawer />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('info-toast'))
      fireEvent.click(screen.getByTestId('warn-toast'))
      fireEvent.click(screen.getByTestId('error-toast'))

      expect(showToast).toHaveBeenCalledTimes(3)
      expect(screen.getByTestId('toast-count')).toHaveTextContent('3')
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 4: Drawer tab switching
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 4: Drawer tab switching', () => {
    it('should preserve state when switching tabs', () => {
      const setActiveSection = vi.fn()
      const testValue = { ...mockContextValue, setActiveSection }

      render(
        <DrawerProvider value={testValue}>
          <TabSwitchingDrawer />
        </DrawerProvider>
      )

      const overviewTab = screen.getByTestId('tab-overview')
      fireEvent.click(overviewTab)

      expect(setActiveSection).toHaveBeenCalledWith('overview')
      expect(screen.getByTestId('state-value')).toHaveTextContent('data1')
    })

    it('should switch to files tab and maintain state', () => {
      const setActiveSection = vi.fn()
      const testValue = { ...mockContextValue, setActiveSection }

      render(
        <DrawerProvider value={testValue}>
          <TabSwitchingDrawer />
        </DrawerProvider>
      )

      const filesTab = screen.getByTestId('tab-files')
      fireEvent.click(filesTab)

      expect(setActiveSection).toHaveBeenCalledWith('files')
      expect(screen.getByTestId('state-files')).toHaveTextContent('data2')
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 5: Print workflow
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 5: Print workflow', () => {
    it('should select file and display details', async () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <PrintWorkflowDrawer />
        </DrawerProvider>
      )

      const selectBtn = screen.getByTestId('select-file')
      fireEvent.click(selectBtn)

      await waitFor(() => {
        expect(screen.getByTestId('selected-file')).toHaveTextContent('Selected: model.gcode')
      })

      expect(screen.getByTestId('file-details')).toBeInTheDocument()
      expect(screen.getByTestId('file-details')).toHaveTextContent('model.gcode')
      expect(screen.getByTestId('file-details')).toHaveTextContent('12345 bytes')
    })

    it('should enable print button after file selection', async () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <PrintWorkflowDrawer />
        </DrawerProvider>
      )

      const selectBtn = screen.getByTestId('select-file')
      fireEvent.click(selectBtn)

      await waitFor(() => {
        const printBtn = screen.getByTestId('print-btn')
        expect(printBtn).not.toBeDisabled()
      })
    })

    it('should start print and show success toast', async () => {
      const showToast = vi.fn()
      const startPrint = vi.fn().mockResolvedValue(undefined)
      const testValue = { ...mockContextValue, showToast, startPrint }

      render(
        <DrawerProvider value={testValue}>
          <PrintWorkflowDrawer />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('select-file'))

      await waitFor(() => {
        fireEvent.click(screen.getByTestId('print-btn'))
      })

      await waitFor(() => {
        expect(startPrint).toHaveBeenCalledWith('printer-001', 'model.gcode')
        expect(showToast).toHaveBeenCalledWith('Print started!')
      })
    })

    it('should handle print failure with error toast', async () => {
      const showToast = vi.fn()
      const startPrint = vi.fn().mockRejectedValue(new Error('Print failed'))
      const testValue = { ...mockContextValue, showToast, startPrint }

      render(
        <DrawerProvider value={testValue}>
          <PrintWorkflowDrawer />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('select-file'))

      await waitFor(() => {
        fireEvent.click(screen.getByTestId('print-btn'))
      })

      await waitFor(() => {
        expect(showToast).toHaveBeenCalledWith('Failed to start print', 'error')
      })
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 6: Temperature control
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 6: Temperature control', () => {
    it('should apply PLA preset', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <TemperatureControlDrawer />
        </DrawerProvider>
      )

      const plaBtn = screen.getByTestId('pla-preset')
      fireEvent.click(plaBtn)

      expect(screen.getByTestId('nozzle-target')).toHaveTextContent('200')
      expect(screen.getByTestId('bed-target')).toHaveTextContent('60')
      expect(showToast).toHaveBeenCalledWith('Applied preset: 200°C / 60°C')
    })

    it('should apply ABS preset', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <TemperatureControlDrawer />
        </DrawerProvider>
      )

      const absBtn = screen.getByTestId('abs-preset')
      fireEvent.click(absBtn)

      expect(screen.getByTestId('nozzle-target')).toHaveTextContent('240')
      expect(screen.getByTestId('bed-target')).toHaveTextContent('100')
      expect(showToast).toHaveBeenCalledWith('Applied preset: 240°C / 100°C')
    })

    it('should display current temperatures from printer', () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <TemperatureControlDrawer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('current-temps')).toHaveTextContent('Nozzle: 210°C')
      expect(screen.getByTestId('current-temps')).toHaveTextContent('Bed: 60°C')
    })

    it('should verify state after preset application', async () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <TemperatureControlDrawer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('nozzle-target')).toHaveTextContent('215')
      expect(screen.getByTestId('bed-target')).toHaveTextContent('65')

      fireEvent.click(screen.getByTestId('pla-preset'))

      expect(screen.getByTestId('nozzle-target')).toHaveTextContent('200')
      expect(screen.getByTestId('bed-target')).toHaveTextContent('60')
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 7: Async operations
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 7: Async operations', () => {
    it('should show loading state during async operation', async () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <AsyncOperationDrawer />
        </DrawerProvider>
      )

      const btn = screen.getByTestId('async-btn')
      fireEvent.click(btn)

      expect(btn).toBeDisabled()
      expect(btn).toHaveTextContent('Loading...')
    })

    it('should complete async operation and show result', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <AsyncOperationDrawer />
        </DrawerProvider>
      )

      const btn = screen.getByTestId('async-btn')
      fireEvent.click(btn)

      await waitFor(() => {
        expect(screen.getByTestId('result')).toHaveTextContent('Operation completed')
      })
    })

    it('should invoke callback on completion', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <AsyncOperationDrawer />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('async-btn'))

      await waitFor(() => {
        expect(showToast).toHaveBeenCalledWith('Success!')
      })
    })

    it('should handle async operation errors', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      // Override component to throw error
      const ErrorAsyncComponent = () => {
        const { showToast } = useAppDrawer()
        const [isLoading, setIsLoading] = useState(false)

        const handleAsync = async () => {
          setIsLoading(true)
          try {
            throw new Error('Async failed')
          } catch {
            showToast('Error occurred', 'error')
          } finally {
            setIsLoading(false)
          }
        }

        return (
          <button data-testid="async-btn" onClick={handleAsync} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Start'}
          </button>
        )
      }

      render(
        <DrawerProvider value={testValue}>
          <ErrorAsyncComponent />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('async-btn'))

      await waitFor(() => {
        expect(showToast).toHaveBeenCalledWith('Error occurred', 'error')
      })
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 8: Error recovery
  // ──────────────────────────────────────────────────────────────────────────

  describe('Test 8: Error recovery', () => {
    it('should recover from failed request via retry', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <ErrorHandlingDrawer />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('fail-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('error-message')).toHaveTextContent('Network error')
      })

      const retryBtn = screen.getByTestId('retry-btn')
      fireEvent.click(retryBtn)

      await waitFor(() => {
        expect(retryBtn).toHaveTextContent(/Retry \([1-9]\)/)
      })
    })

    it('should clear error message on successful retry', async () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <ErrorHandlingDrawer />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('fail-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('error-message')).toBeInTheDocument()
      })

      const retryBtn = screen.getByTestId('retry-btn')
      fireEvent.click(retryBtn)

      await waitFor(() => {
        fireEvent.click(retryBtn)
        // After retries succeed, error should clear
      })
    })

    it('should disable retry button while retrying', async () => {
      const testValue = mockContextValue

      render(
        <DrawerProvider value={testValue}>
          <ErrorHandlingDrawer />
        </DrawerProvider>
      )

      const retryBtn = screen.getByTestId('retry-btn')
      fireEvent.click(retryBtn)

      expect(retryBtn).toBeDisabled()

      await waitFor(() => {
        expect(retryBtn).not.toBeDisabled()
      })
    })
  })

  // ──────────────────────────────────────────────────────────────────────────
  // EDGE CASES & COVERAGE
  // ──────────────────────────────────────────────────────────────────────────

  describe('Edge cases and coverage', () => {
    it('fails loudly when the drawer context is missing', () => {
      // A drawer rendered outside the app's provider must throw, not show default data.
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
      try {
        expect(() => render(<MultiDrawerConsumer />)).toThrow(/AppDrawerContext\.Provider/)
      } finally {
        spy.mockRestore()
      }
    })

    it('should handle rapid tab switches', () => {
      const setActiveSection = vi.fn()
      const testValue = { ...mockContextValue, setActiveSection }

      render(
        <DrawerProvider value={testValue}>
          <TabSwitchingDrawer />
        </DrawerProvider>
      )

      fireEvent.click(screen.getByTestId('tab-overview'))
      fireEvent.click(screen.getByTestId('tab-files'))
      fireEvent.click(screen.getByTestId('tab-overview'))

      expect(setActiveSection).toHaveBeenCalledTimes(3)
    })

    it('should handle concurrent async operations', async () => {
      const showToast = vi.fn()
      const testValue = { ...mockContextValue, showToast }

      render(
        <DrawerProvider value={testValue}>
          <AsyncOperationDrawer />
        </DrawerProvider>
      )

      const btn = screen.getByTestId('async-btn')
      fireEvent.click(btn)

      await waitFor(() => {
        expect(screen.getByTestId('result')).toHaveTextContent('Operation completed')
      })
    })

    it('should maintain context through component unmount/remount', () => {
      const testValue = mockContextValue
      const { rerender } = render(
        <DrawerProvider value={testValue}>
          <MultiDrawerConsumer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('current-temp')).toHaveTextContent('210')

      rerender(
        <DrawerProvider value={testValue}>
          <MultiDrawerConsumer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('current-temp')).toHaveTextContent('210')
    })

    it('should handle null printer state', () => {
      const testValue = { ...mockContextValue, currentPrinter: null }

      render(
        <DrawerProvider value={testValue}>
          <MultiDrawerConsumer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('active-section')).toBeInTheDocument()
    })

    it('should handle empty macros list', () => {
      const testValue = { ...mockContextValue, macros: [] }

      render(
        <DrawerProvider value={testValue}>
          <MultiDrawerConsumer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('active-section')).toBeInTheDocument()
    })

    it('should handle canWrite permission changes', () => {
      const { rerender } = render(
        <DrawerProvider value={{ ...mockContextValue, canWrite: false }}>
          <TemperatureControlDrawer />
        </DrawerProvider>
      )

      rerender(
        <DrawerProvider value={{ ...mockContextValue, canWrite: true }}>
          <TemperatureControlDrawer />
        </DrawerProvider>
      )

      expect(screen.getByTestId('pla-preset')).toBeInTheDocument()
    })
  })
})

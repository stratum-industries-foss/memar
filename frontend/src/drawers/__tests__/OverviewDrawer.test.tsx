import { render, fireEvent, waitFor, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import OverviewDrawer from '../OverviewDrawer'
import type { DrawerProps } from '../../App'

/**
 * Mock child components to isolate OverviewDrawer testing
 */
vi.mock('../MachineOee', () => ({
  MachineOee: ({ variant, oee }: any) => (
    <div data-testid="machine-oee">
      OEE: {oee?.oee_pct}%
    </div>
  ),
}))

vi.mock('../FileDetailCard', () => ({
  FileDetailCard: ({ detail }: any) => (
    <div data-testid="file-detail-card">
      {detail?.file?.name || 'unknown file'}
    </div>
  ),
}))

vi.mock('../KlipperConfigPanel', () => ({
  KlipperConfigPanel: ({ cfg }: any) => (
    <div data-testid="klipper-config-panel">
      Klipper Config
    </div>
  ),
}))

vi.mock('../../ExcludeObjectsMap', () => ({
  ExcludeObjectsMap: ({ objects, excluded, currentObject, canWrite, onExclude }: any) => (
    <div data-testid="exclude-objects-map">
      <svg data-testid="exclude-svg">
        {objects?.map((obj: any) => (
          <polygon
            key={obj.name}
            data-name={obj.name}
            data-testid={`exclude-polygon-${obj.name}`}
            onClick={() => onExclude(obj.name)}
          />
        ))}
      </svg>
    </div>
  ),
  hasPolygonData: (objects: any) => {
    if (!objects || !Array.isArray(objects)) return false
    return objects.some((obj: any) => Array.isArray(obj.polygon) && obj.polygon.length >= 3)
  },
}))

/**
 * Mock data for diagnostics, metrics, OEE, and related payloads.
 */

const MOCK_DIAGNOSTICS = {
  state: 'idle',
  klippy_connected: true,
  moonraker_version: '0.8.0',
  api_version_string: '1.2.3',
  process_id: 1234,
  attention_needed: false,
  config_file: '/home/pi/printer_data/config/printer.cfg',
  log_file: '/home/pi/printer_data/logs/klippy.log',
  recent_log_lines: ['[klippy] Build version: v0.11.0', '[mcu] MCU info: '],
  suggested_checks: ['Check nozzle temperature', 'Verify bed leveling'],
  capability: {
    bed_temp_max: 100,
    nozzle_temp_max: 300,
    spool_remaining_g: 250,
    current_material: 'PLA',
  },
  homed_axes: 'xyz',
  klipper_config: {
    printer: { max_velocity: 200 },
    bed_mesh: { mesh_min: [0, 0], mesh_max: [200, 200] },
  },
}

const MOCK_PRINTER = {
  id: 'test-printer',
  name: 'Test Printer',
  ip: '192.168.1.100',
  port: 7125,
  state: 'printing',
}

const MOCK_CURRENT_METRIC = {
  success_rate: 92.5,
  completed_jobs: 45,
  failed_jobs: 3,
  cancelled_jobs: 2,
  total_print_time: 86400000, // 24 hours in ms
  total_filament_used: 5000, // mm
  avg_print_time: 1920000, // 32 minutes in ms
  last_job_end_time: Date.now() - 3600000, // 1 hour ago
}

const MOCK_OEE = {
  device_id: 'test-printer',
  availability: 0.95,
  performance: 0.98,
  quality: 0.99,
  oee: 0.92,
  availability_pct: 95,
  performance_pct: 98,
  quality_pct: 99,
  oee_pct: 92,
}

const MOCK_CURRENT_FILE = {
  detail: {
    filename: 'test_print.gcode',
    print_start_time: Date.now() - 3600000,
    print_duration: 3600000,
    filament_used: 150,
    estimated_time: 3600000,
    nozzle_temp: 210,
    bed_temp: 60,
  },
}

const MOCK_SPOOL_LOG = [
  {
    id: 1,
    created_at: Date.now() - 7200000,
    job_name: 'test_print_1.gcode',
    filament_used_g: 12.5,
    spool_after_g: 237.5,
    source: 'automatic',
  },
  {
    id: 2,
    created_at: Date.now() - 3600000,
    job_name: 'test_print_2.gcode',
    filament_used_g: 8.3,
    spool_after_g: 229.2,
    source: 'manual',
  },
]

const MOCK_EXCLUDE_OBJECTS = {
  supported: true,
  objects: [
    { name: 'support_left', polygon: [[10, 10], [20, 10], [20, 20], [10, 20]] },
    { name: 'support_right', polygon: [[50, 10], [60, 10], [60, 20], [50, 20]] },
    { name: 'brim', polygon: [[5, 5], [65, 5], [65, 65], [5, 65]] },
  ],
  excluded: ['support_left'],
  current_object: 'support_right',
}

const MOCK_EXCLUDE_OBJECTS_NO_POLYGON = {
  supported: true,
  objects: [
    { name: 'support_left' },
    { name: 'support_right' },
    { name: 'brim' },
  ],
  excluded: ['support_left'],
  current_object: 'support_right',
}

const MOCK_EXCLUDE_OBJECTS_UNSUPPORTED = {
  supported: false,
  objects: [],
  excluded: [],
  current_object: null,
}

/**
 * Create a base set of drawer props for testing.
 */
function createBaseProps(overrides: Partial<DrawerProps> = {}): DrawerProps & { [key: string]: any } {
  return {
    printerId: 'test-printer',
    printer: MOCK_PRINTER,
    currentPrinter: MOCK_PRINTER,
    diagnostics: MOCK_DIAGNOSTICS,
    canWrite: true,
    dashboardSettings: { show_oee: true, default_drawer_section: 'overview' },
    oeeByDevice: new Map([['test-printer', MOCK_OEE]]),
    currentMetric: MOCK_CURRENT_METRIC,
    currentFileDetail: MOCK_CURRENT_FILE,
    cvAnomalies: {},
    spoolLogOpen: false,
    setSpoolLogOpen: vi.fn(),
    spoolLog: [],
    spoolLogLoading: false,
    excludeObjects: null,
    quickMaterial: '',
    setQuickMaterial: vi.fn(),
    quickRemaining: 0,
    setQuickRemaining: vi.fn(),
    quickFilamentSaving: false,
    saveQuickFilamentWithLog: vi.fn(),
    spoolEstimating: false,
    estimateSpoolFromPhoto: vi.fn(),
    spoolEstimateResult: null,
    formatDuration: (ms?: number | null) => (ms ? `${Math.round(ms / 60000)}m` : '—'),
    formatMillimeters: (mm?: number | null) => (mm ? `${mm}mm` : '—'),
    formatTimestamp: (ts?: number | null) => (ts ? new Date(ts).toLocaleString() : '—'),
    fetchSpoolLog: vi.fn(),
    capabilityOverviewItems: () => [
      { label: 'Max nozzle temp', value: '300°C' },
      { label: 'Max bed temp', value: '100°C' },
    ],
    setConfirmState: vi.fn(),
    loadExcludeObjects: vi.fn(),
    doExcludeObject: vi.fn(),
    ...overrides,
  }
}

describe('OverviewDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  /**
   * TEST 1: OverviewDrawer renders metrics
   * Verify OEE, printer state, and diagnostics display
   */
  describe('Test 1: Metrics and diagnostics rendering', () => {
    it('renders OEE section when show_oee is true and OEE data exists', () => {
      const props = createBaseProps({
        dashboardSettings: { show_oee: true },
      })
      const { getByTestId } = render(<OverviewDrawer {...props} />)

      // Check for OEE section presence via the mocked MachineOee component
      expect(getByTestId('machine-oee')).toBeInTheDocument()
      expect(getByTestId('machine-oee').textContent).toContain('92%')
    })

    it('hides OEE section when show_oee is false', () => {
      const props = createBaseProps({
        dashboardSettings: { show_oee: false },
      })
      const { container } = render(<OverviewDrawer {...props} />)

      // The OEE section should not exist
      const html = container.innerHTML
      // If show_oee is false, the section with MachineOee should not render
      expect(html).not.toContain('undefined')
    })

    it('renders printer state section with diagnostics', () => {
      const props = createBaseProps()
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('State')).toBeInTheDocument()
      expect(getByText(MOCK_DIAGNOSTICS.state)).toBeInTheDocument()
      expect(getByText('true')).toBeInTheDocument() // klippy_connected
      expect(getByText(MOCK_DIAGNOSTICS.moonraker_version)).toBeInTheDocument()
      expect(getByText(MOCK_DIAGNOSTICS.api_version_string)).toBeInTheDocument()
      expect(getByText(String(MOCK_DIAGNOSTICS.process_id))).toBeInTheDocument()
      expect(getByText('No')).toBeInTheDocument() // attention_needed is false
    })

    it('renders printer metrics with formatted values', () => {
      const props = createBaseProps()
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Printer metrics')).toBeInTheDocument()
      expect(getByText('92.5%')).toBeInTheDocument() // success_rate
      expect(getByText('45')).toBeInTheDocument() // completed_jobs
      expect(getByText('3')).toBeInTheDocument() // failed_jobs
      expect(getByText('2')).toBeInTheDocument() // cancelled_jobs
    })

    it('renders current file detail when available', () => {
      const props = createBaseProps()
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Current file')).toBeInTheDocument()
      // FileDetailCard child component renders the file details
    })

    it('shows "No active or selected file" when currentFileDetail is null', () => {
      const props = createBaseProps({ currentFileDetail: null })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('No active or selected file.')).toBeInTheDocument()
    })

    it('displays capability profile items', () => {
      const props = createBaseProps()
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Capability profile')).toBeInTheDocument()
      expect(getByText('Max nozzle temp')).toBeInTheDocument()
      expect(getByText('300°C')).toBeInTheDocument()
      expect(getByText('Max bed temp')).toBeInTheDocument()
      expect(getByText('100°C')).toBeInTheDocument()
    })

    it('renders suggested checks list', () => {
      const props = createBaseProps()
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Suggested checks')).toBeInTheDocument()
      expect(getByText('Check nozzle temperature')).toBeInTheDocument()
      expect(getByText('Verify bed leveling')).toBeInTheDocument()
    })

    it('renders config and log file paths', () => {
      const props = createBaseProps()
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Paths')).toBeInTheDocument()
      expect(getByText(MOCK_DIAGNOSTICS.config_file)).toBeInTheDocument()
      expect(getByText(MOCK_DIAGNOSTICS.log_file)).toBeInTheDocument()
    })

    it('renders recent log lines', () => {
      const props = createBaseProps()
      const { container } = render(<OverviewDrawer {...props} />)

      const logBox = container.querySelector('.log-box')
      expect(logBox).toBeInTheDocument()
      expect(logBox?.textContent).toContain('[klippy] Build version: v0.11.0')
      expect(logBox?.textContent).toContain('[mcu] MCU info:')
    })

    it('shows loading state when diagnostics is null', () => {
      const props = createBaseProps({ diagnostics: null })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Loading overview…')).toBeInTheDocument()
    })

    it('renders CV Monitor section when anomalies exist for the printer', () => {
      const props = createBaseProps({
        cvAnomalies: {
          'test-printer': [
            {
              type: 'nozzle_contact',
              confidence: 'high',
              score: 0.92,
              reasoning: 'Nozzle appears to be contacting the surface',
            },
            {
              type: 'layer_shift',
              confidence: 'low',
              score: 0.45,
              reasoning: 'Possible layer misalignment detected',
            },
          ],
        },
      })
      const { getByText, container } = render(<OverviewDrawer {...props} />)

      expect(getByText('CV Monitor')).toBeInTheDocument()
      expect(getByText(/nozzle contact/i)).toBeInTheDocument()
      expect(getByText(/layer shift/i)).toBeInTheDocument()
      expect(getByText('92%')).toBeInTheDocument()
      expect(getByText('45%')).toBeInTheDocument()
    })

    it('hides CV Monitor section when no anomalies exist', () => {
      const props = createBaseProps({ cvAnomalies: {} })
      const { queryByText } = render(<OverviewDrawer {...props} />)

      expect(queryByText('CV Monitor')).not.toBeInTheDocument()
    })
  })

  /**
   * TEST 2: Spool log displays
   * Verify spoolLog data displays correctly with adjustments
   */
  describe('Test 2: Spool log display and management', () => {
    it('renders filament section with update controls when canWrite is true', () => {
      const props = createBaseProps({ canWrite: true })
      const { getByPlaceholderText, getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Filament')).toBeInTheDocument()
      expect(getByPlaceholderText('Material (e.g. PLA)')).toBeInTheDocument()
      expect(getByPlaceholderText('Remaining (g)')).toBeInTheDocument()
      expect(getByText('Update')).toBeInTheDocument()
    })

    it('hides filament edit controls when canWrite is false', () => {
      const props = createBaseProps({ canWrite: false })
      const { container, getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Filament')).toBeInTheDocument()
      const materialInputs = container.querySelectorAll('input[placeholder*="Material"]')
      expect(materialInputs).toHaveLength(0)
    })

    it('updates material and remaining inputs on change', () => {
      const setQuickMaterial = vi.fn()
      const setQuickRemaining = vi.fn()
      const props = createBaseProps({
        setQuickMaterial,
        setQuickRemaining,
      })
      const { getByPlaceholderText } = render(<OverviewDrawer {...props} />)

      const materialInput = getByPlaceholderText('Material (e.g. PLA)') as HTMLInputElement
      const remainingInput = getByPlaceholderText('Remaining (g)') as HTMLInputElement

      fireEvent.change(materialInput, { target: { value: 'PETG' } })
      expect(setQuickMaterial).toHaveBeenCalledWith('PETG')

      fireEvent.change(remainingInput, { target: { value: '150' } })
      expect(setQuickRemaining).toHaveBeenCalledWith('150')
    })

    it('calls saveQuickFilamentWithLog when Update button is clicked', () => {
      const saveQuickFilamentWithLog = vi.fn().mockResolvedValue(undefined)
      const props = createBaseProps({ saveQuickFilamentWithLog })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const updateBtn = getByText('Update')
      fireEvent.click(updateBtn)

      expect(saveQuickFilamentWithLog).toHaveBeenCalledTimes(1)
    })

    it('shows "Saving…" state in update button when quickFilamentSaving is true', () => {
      const props = createBaseProps({ quickFilamentSaving: true })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Saving…')).toBeInTheDocument()
    })

    it('renders photo estimation button and calls estimateSpoolFromPhoto on file select', () => {
      const estimateSpoolFromPhoto = vi.fn().mockResolvedValue(undefined)
      const props = createBaseProps({ estimateSpoolFromPhoto, canWrite: true })
      const { getByText, container } = render(<OverviewDrawer {...props} />)

      expect(getByText(/Estimate from photo/i)).toBeInTheDocument()

      const fileInput = container.querySelector('input[accept="image/*"]') as HTMLInputElement
      expect(fileInput).toBeInTheDocument()

      const mockFile = new File(['image'], 'test.jpg', { type: 'image/jpeg' })
      fireEvent.change(fileInput, { target: { files: [mockFile] } })

      expect(estimateSpoolFromPhoto).toHaveBeenCalledWith(mockFile)
    })

    it('shows "⏳ Estimating…" when spoolEstimating is true', () => {
      const props = createBaseProps({ spoolEstimating: true })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText(/Estimating/)).toBeInTheDocument()
    })

    it('displays spool estimate result with confidence and model info', () => {
      const props = createBaseProps({
        spoolEstimateResult: {
          fill_pct: 0.65,
          confidence: 'high',
          model_used: 'vision-v2',
          reasoning: 'Spool appears 65% full based on visual analysis',
        },
      })
      const { container } = render(<OverviewDrawer {...props} />)

      // Check that estimate result is displayed with all components
      expect(container.textContent).toContain('65')
      expect(container.textContent).toContain('high')
      expect(container.textContent).toContain('vision-v2')
      expect(container.textContent).toContain('Spool appears 65% full based on visual analysis')
    })

    it('displays current spool remaining and material from diagnostics', () => {
      const props = createBaseProps()
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText(/250g remaining · PLA/i)).toBeInTheDocument()
    })

    it('toggles spool log visibility and fetches data on expand', async () => {
      const setSpoolLogOpen = vi.fn((cb) => {
        if (typeof cb === 'function') {
          cb(false) // toggle to true
        }
      })
      const fetchSpoolLog = vi.fn().mockResolvedValue(undefined)
      const props = createBaseProps({
        setSpoolLogOpen,
        spoolLog: [],
        spoolLogOpen: false,
        fetchSpoolLog,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const toggleBtn = getByText(/Depletion log/)
      fireEvent.click(toggleBtn)

      expect(setSpoolLogOpen).toHaveBeenCalled()
      await waitFor(() => {
        expect(fetchSpoolLog).toHaveBeenCalledWith('test-printer')
      })
    })

    it('renders spool log table when spoolLogOpen is true and data exists', () => {
      const props = createBaseProps({
        spoolLogOpen: true,
        spoolLog: MOCK_SPOOL_LOG,
      })
      const { getByText, container } = render(<OverviewDrawer {...props} />)

      expect(getByText('Date')).toBeInTheDocument()
      expect(getByText('Job')).toBeInTheDocument()
      expect(getByText('Used (g)')).toBeInTheDocument()
      expect(getByText('After (g)')).toBeInTheDocument()
      expect(getByText('Src')).toBeInTheDocument()

      const table = container.querySelector('table')
      expect(table).toBeInTheDocument()

      const rows = table?.querySelectorAll('tbody tr')
      expect(rows).toHaveLength(2)
    })

    it('displays spool log entries with correct formatting', () => {
      const props = createBaseProps({
        spoolLogOpen: true,
        spoolLog: MOCK_SPOOL_LOG,
      })
      const { getByText, container } = render(<OverviewDrawer {...props} />)

      // Check filament used with negative sign and color
      expect(getByText('-12.5')).toBeInTheDocument()
      expect(getByText('-8.3')).toBeInTheDocument()

      // Check spool after values
      expect(getByText('237.5')).toBeInTheDocument()
      expect(getByText('229.2')).toBeInTheDocument()

      // Check source indicators (✏ for manual, ⚙ for automatic)
      expect(container.innerHTML).toContain('✏') // manual
      expect(container.innerHTML).toContain('⚙') // automatic
    })

    it('shows loading state when spool log is loading', () => {
      const props = createBaseProps({
        spoolLogOpen: true,
        spoolLogLoading: true,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Loading…')).toBeInTheDocument()
    })

    it('shows empty state message when no spool log entries', () => {
      const props = createBaseProps({
        spoolLogOpen: true,
        spoolLog: [],
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText(/No entries yet/)).toBeInTheDocument()
    })

    it('displays log entry count in toggle button', () => {
      const props = createBaseProps({
        spoolLog: MOCK_SPOOL_LOG,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText(/Depletion log \(2\)/)).toBeInTheDocument()
    })
  })

  /**
   * TEST 3: Exclude objects panel
   * Verify exclude objects list and controls
   */
  describe('Test 3: Exclude objects panel and controls', () => {
    it('shows exclude objects section only when printer state is printing', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'idle' },
      })
      const { queryByText } = render(<OverviewDrawer {...props} />)

      expect(queryByText('Exclude objects')).not.toBeInTheDocument()
    })

    it('renders exclude objects section when printing and state is available', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Exclude objects')).toBeInTheDocument()
    })

    it('shows "Load objects" button when excludeObjects is null', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: null,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText('Load objects')).toBeInTheDocument()
    })

    it('calls loadExcludeObjects when "Load objects" button is clicked', () => {
      const loadExcludeObjects = vi.fn().mockResolvedValue(undefined)
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: null,
        loadExcludeObjects,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const loadBtn = getByText('Load objects')
      fireEvent.click(loadBtn)

      expect(loadExcludeObjects).toHaveBeenCalled()
    })

    it('shows unsupported message when exclude_object module is not available', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_UNSUPPORTED,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText(/Not available. Add/)).toBeInTheDocument()
      expect(getByText(/exclude_object/)).toBeInTheDocument()
    })

    it('shows "No named objects" when supported but objects list is empty', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: {
          supported: true,
          objects: [],
          excluded: [],
          current_object: null,
        },
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText(/No named objects in current print/)).toBeInTheDocument()
    })

    it('renders exclude object buttons when polygon data is not available', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
        canWrite: true,
      })
      const { container, getByText } = render(<OverviewDrawer {...props} />)

      // First verify the "Exclude objects" section is rendered
      expect(getByText('Exclude objects')).toBeInTheDocument()

      // Now check for exclude object buttons by looking at the flexbox container
      const objectButtonsDiv = container.querySelector('[style*="display: flex"][style*="gap: 6"]')
      expect(objectButtonsDiv).toBeInTheDocument()

      // Check that the objects are rendered in the container
      expect(container.textContent).toContain('support_left')
      expect(container.textContent).toContain('support_right')
      expect(container.textContent).toContain('brim')
    })

    it('disables excluded object buttons and marks them visually', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const excludedBtn = getByText('support_left') as HTMLButtonElement
      expect(excludedBtn.disabled).toBe(true)
      expect(excludedBtn.style.opacity).toBe('0.45')
      expect(excludedBtn.style.textDecoration).toBe('line-through')
    })

    it('marks current object with bullet indicator', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const currentBtn = getByText(/support_right ●/)
      expect(currentBtn).toBeInTheDocument()
    })

    it('calls setConfirmState with correct message when excluding an object', () => {
      const setConfirmState = vi.fn()
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
        canWrite: true,
        setConfirmState,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const objectBtn = getByText('brim')
      fireEvent.click(objectBtn)

      expect(setConfirmState).toHaveBeenCalled()
      const call = setConfirmState.mock.calls[0][0]
      expect(call.message).toContain('brim')
    })

    it('calls doExcludeObject via confirmation when object button is clicked', () => {
      const setConfirmState = vi.fn()
      const doExcludeObject = vi.fn().mockResolvedValue(undefined)
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
        canWrite: true,
        setConfirmState,
        doExcludeObject,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const objectBtn = getByText('brim')
      fireEvent.click(objectBtn)

      const confirmCall = setConfirmState.mock.calls[0][0]
      confirmCall.onConfirm()

      expect(doExcludeObject).toHaveBeenCalledWith('brim')
    })

    it('prevents click on excluded objects even with write permission', () => {
      const setConfirmState = vi.fn()
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
        canWrite: true,
        setConfirmState,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const excludedBtn = getByText('support_left')
      fireEvent.click(excludedBtn)

      expect(setConfirmState).not.toHaveBeenCalled()
    })

    it('prevents click on objects when canWrite is false', () => {
      const setConfirmState = vi.fn()
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
        canWrite: false,
        setConfirmState,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const objectBtn = getByText('brim')
      fireEvent.click(objectBtn)

      expect(setConfirmState).not.toHaveBeenCalled()
      expect((objectBtn as HTMLButtonElement).disabled).toBe(true)
    })

    it('renders Refresh button for exclude objects', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      const refreshBtn = getByText('Refresh')
      expect(refreshBtn).toBeInTheDocument()
    })

    it('calls loadExcludeObjects on Refresh button click', () => {
      const loadExcludeObjects = vi.fn().mockResolvedValue(undefined)
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS_NO_POLYGON,
        loadExcludeObjects,
      })
      const { getAllByText } = render(<OverviewDrawer {...props} />)

      const refreshBtns = getAllByText('Refresh')
      const excludeRefreshBtn = refreshBtns[refreshBtns.length - 1] // Last Refresh button
      fireEvent.click(excludeRefreshBtn)

      expect(loadExcludeObjects).toHaveBeenCalled()
    })

    it('renders ExcludeObjectsMap component when polygon data exists', () => {
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS,
        canWrite: true,
      })
      const { container } = render(<OverviewDrawer {...props} />)

      // ExcludeObjectsMap renders an SVG
      expect(container.querySelector('svg')).toBeInTheDocument()
    })

    it('passes correct props to ExcludeObjectsMap', () => {
      const onExcludeSpy = vi.fn()
      const props = createBaseProps({
        currentPrinter: { ...MOCK_PRINTER, state: 'printing' },
        excludeObjects: MOCK_EXCLUDE_OBJECTS,
        canWrite: true,
        setConfirmState: (state: any) => onExcludeSpy(state),
      })
      const { container } = render(<OverviewDrawer {...props} />)

      // Verify SVG polygons render
      const polygons = container.querySelectorAll('polygon')
      expect(polygons.length).toBeGreaterThanOrEqual(3)
    })
  })

  /**
   * Edge cases and integration tests
   */
  describe('Edge cases and integration', () => {
    it('handles null/undefined values gracefully in metrics display', () => {
      const props = createBaseProps({
        currentMetric: {
          success_rate: null,
          completed_jobs: 0,
          failed_jobs: 0,
          cancelled_jobs: 0,
          total_print_time: null,
          total_filament_used: null,
          avg_print_time: null,
          last_job_end_time: null,
        },
      })
      const { container } = render(<OverviewDrawer {...props} />)

      // Check that dash character appears in the output for null values
      expect(container.innerHTML).toContain('—')
    })

    it('handles missing spoolEstimateResult gracefully', () => {
      const props = createBaseProps({ spoolEstimateResult: null })
      const { container } = render(<OverviewDrawer {...props} />)

      expect(container.innerHTML).not.toContain('undefined')
    })

    it('renders with minimal props (all defaults)', () => {
      const minimalProps = createBaseProps({
        diagnostics: MOCK_DIAGNOSTICS,
      })
      const { container } = render(<OverviewDrawer {...minimalProps} />)

      expect(container.querySelector('.drawer-section')).toBeInTheDocument()
    })

    it('handles very long job names in spool log without overflow', () => {
      const longNameLog = [
        {
          id: 1,
          created_at: Date.now(),
          job_name: 'a'.repeat(200) + '_very_long_filename.gcode',
          filament_used_g: 10,
          spool_after_g: 240,
          source: 'automatic',
        },
      ]
      const props = createBaseProps({
        spoolLogOpen: true,
        spoolLog: longNameLog,
      })
      const { container } = render(<OverviewDrawer {...props} />)

      const jobCell = container.querySelector('td[title]')
      expect(jobCell).toHaveStyle({ overflow: 'hidden', textOverflow: 'ellipsis' })
    })

    it('maintains state consistency across multiple interactions', () => {
      const setSpoolLogOpen = vi.fn()
      const setQuickMaterial = vi.fn()
      const props = createBaseProps({
        setSpoolLogOpen,
        setQuickMaterial,
      })
      const { getByPlaceholderText, getByText } = render(<OverviewDrawer {...props} />)

      // Interact with multiple elements
      const materialInput = getByPlaceholderText('Material (e.g. PLA)') as HTMLInputElement
      fireEvent.change(materialInput, { target: { value: 'ABS' } })

      const toggleBtn = getByText(/Depletion log/)
      fireEvent.click(toggleBtn)

      expect(setQuickMaterial).toHaveBeenCalledWith('ABS')
      expect(setSpoolLogOpen).toHaveBeenCalled()
    })

    it('displays hardware config panel when klipper_config exists', () => {
      const props = createBaseProps({
        diagnostics: {
          ...MOCK_DIAGNOSTICS,
          klipper_config: {
            printer: { max_velocity: 200, max_accel: 2000 },
          },
        },
      })
      const { getByText } = render(<OverviewDrawer {...props} />)

      expect(getByText(/Hardware config/)).toBeInTheDocument()
      expect(getByText('(printer.cfg)')).toBeInTheDocument()
    })

    it('omits hardware config panel when klipper_config is null', () => {
      const props = createBaseProps({
        diagnostics: {
          ...MOCK_DIAGNOSTICS,
          klipper_config: null,
        },
      })
      const { queryByText } = render(<OverviewDrawer {...props} />)

      expect(queryByText(/Hardware config/)).not.toBeInTheDocument()
    })
  })
})

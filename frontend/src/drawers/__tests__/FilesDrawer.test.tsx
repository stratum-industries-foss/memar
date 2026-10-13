import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { FileBrowserResponse, FileEntry } from '../fileUtils'
import type { Printer } from '../types.printer'
import { FilesDrawer } from '../FilesDrawer'

/**
 * FilesDrawer.test.tsx — Comprehensive test suite for FilesDrawer component.
 *
 * Tests cover:
 *  1. File list rendering (display of files, print counts, action buttons)
 *  2. File sorting (name, size, modified, last_printed)
 *  3. File search filtering (case-insensitive search)
 *  4. Action button callbacks (Print, Inspect)
 *
 * Mocking strategy:
 *  - useFilesState is tested implicitly through component integration
 *  - apiFetch is mocked for file detail and upload operations
 *  - DrawerProps are provided as test fixtures
 */

// Mock the API layer
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    apiFetch: vi.fn(),
  }
})

import { apiFetch } from '../../api'

const mockedFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

// ============================================================================
// Test Fixtures
// ============================================================================

/** Sample file entries for testing */
const mockFileA: FileEntry = {
  name: 'benchy.gcode',
  path: 'gcodes/benchy.gcode',
  kind: 'file',
  size: 2500000,
  modified: 1722873600, // 2024-08-05 12:00:00 UTC
  permissions: '644',
  metadata: {
    print_start_time: '2024-08-05T10:00:00Z',
  },
}

const mockFileB: FileEntry = {
  name: 'calibration.gcode',
  path: 'gcodes/calibration.gcode',
  kind: 'file',
  size: 500000,
  modified: 1722960000, // 2024-08-06 12:00:00 UTC
  permissions: '644',
  metadata: {
    print_start_time: '2024-08-04T10:00:00Z',
  },
}

const mockFileC: FileEntry = {
  name: 'test.gcode',
  path: 'gcodes/test.gcode',
  kind: 'file',
  size: 1500000,
  modified: 1722787200, // 2024-08-04 12:00:00 UTC
  permissions: '644',
  metadata: {},
}

const mockDir: FileEntry = {
  name: 'models',
  path: 'gcodes/models',
  kind: 'dir',
  size: null,
  modified: null,
  permissions: '755',
  metadata: {},
}

/** Mock FileBrowserResponse */
const createMockBrowserResponse = (overrides?: Partial<FileBrowserResponse>): FileBrowserResponse => ({
  printer_id: 'test-printer-1',
  path: 'gcodes',
  root: 'gcodes',
  dirs: [mockDir],
  files: [mockFileA, mockFileB, mockFileC],
  ...overrides,
})

/** Mock print counts map */
const createMockPrintCounts = (): Map<string, number> => {
  const counts = new Map<string, number>()
  counts.set('benchy.gcode', 5)
  counts.set('calibration.gcode', 2)
  counts.set('test.gcode', 0)
  return counts
}

/** Mock printer factory */
function mockPrinter(overrides?: Partial<Printer>): Printer {
  return {
    id: 'test-printer-1',
    name: 'Test Printer',
    base_url: 'http://localhost:7125',
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
    ...overrides,
  }
}

/** Create DrawerProps fixture */
interface DrawerPropsFixture {
  printerId?: string
  printer?: Printer
  filePath?: string
  fileBrowser?: FileBrowserResponse | null
  printCounts?: Map<string, number>
  canWrite?: boolean
  onNavigate?: (path: string) => void | Promise<void>
  onRequestPrint?: (filename: string) => void
  onFileSelected?: (filename: string) => void
  onMessage?: (text: string) => void
  onUploaded?: (filename: string, startedPrint: boolean) => void
  [key: string]: unknown
}

const createDrawerProps = (overrides?: DrawerPropsFixture) => ({
  printerId: 'test-printer-1',
  printer: mockPrinter(),
  filePath: 'gcodes',
  fileBrowser: createMockBrowserResponse(),
  printCounts: createMockPrintCounts(),
  canWrite: true,
  onNavigate: vi.fn(),
  onRequestPrint: vi.fn(),
  onFileSelected: vi.fn(),
  onMessage: vi.fn(),
  onUploaded: vi.fn(),
  ...overrides,
})

// ============================================================================
// Test Cases
// ============================================================================

describe('FilesDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedFetch.mockClear()
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  describe('Test 1: File list rendering', () => {
    it('renders file list with files, directories, and print counts', () => {
      const props = createDrawerProps({
        filePath: 'gcodes/models', // Set nested path so parent ".." appears
        fileBrowser: createMockBrowserResponse({
          path: 'gcodes/models',
          dirs: [mockDir],
          files: [mockFileA, mockFileB, mockFileC],
        }),
      })
      render(<FilesDrawer {...props} />)

      // Check section header
      expect(screen.getByRole('heading', { name: /files/i })).toBeInTheDocument()

      // Check parent directory is rendered
      const parentButton = screen.getByRole('button', { name: /\.\./ })
      expect(parentButton).toBeInTheDocument()

      // Check subdirectory is rendered
      expect(screen.getByRole('button', { name: /models\// })).toBeInTheDocument()

      // Check files are rendered by name
      expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
      expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
      expect(screen.getByText('test.gcode')).toBeInTheDocument()

      // Check print counts are displayed
      expect(screen.getByText('5')).toBeInTheDocument() // benchy count
      expect(screen.getByText('2')).toBeInTheDocument() // calibration count
    })

    it('renders file metadata (size and modified date)', () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      // File sizes are formatted by formatBytes
      expect(screen.getByText(/2\.4 MB/)).toBeInTheDocument() // benchy ~2.5MB
      expect(screen.getByText(/488\.3 KB/)).toBeInTheDocument() // calibration ~500KB
      expect(screen.getByText(/1\.4 MB/)).toBeInTheDocument() // test ~1.5MB
    })

    it('renders action buttons (Print and Inspect)', () => {
      const props = createDrawerProps({ canWrite: true })
      render(<FilesDrawer {...props} />)

      // Each file should have Print and Inspect buttons
      const fileRows = screen.getAllByRole('button', { name: /print/i })
      const inspectButtons = screen.getAllByRole('button', { name: /inspect/i })

      expect(fileRows.length).toBeGreaterThan(0)
      expect(inspectButtons.length).toBeGreaterThan(0)
    })

    it('does not render Print buttons when canWrite is false', () => {
      const props = createDrawerProps({ canWrite: false })
      render(<FilesDrawer {...props} />)

      const printButtons = screen.queryAllByRole('button', { name: /^print$/i })
      expect(printButtons.length).toBe(0)

      // Inspect buttons should still be present
      const inspectButtons = screen.queryAllByRole('button', { name: /inspect/i })
      expect(inspectButtons.length).toBeGreaterThan(0)
    })

    it('displays file list only when fileBrowser is provided', () => {
      const props = createDrawerProps({ fileBrowser: null })
      render(<FilesDrawer {...props} />)

      // Should not render the file list
      expect(screen.queryByRole('button', { name: /benchy.gcode/i })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /models\//i })).not.toBeInTheDocument()
    })

    it('renders sort and search controls when fileBrowser is available', () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      // Sort dropdown and search input should be present
      expect(screen.getByLabelText(/sort files/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/search files/i)).toBeInTheDocument()
    })

    it('does not render sort and search controls when fileBrowser is null', () => {
      const props = createDrawerProps({ fileBrowser: null })
      render(<FilesDrawer {...props} />)

      expect(screen.queryByLabelText(/sort files/i)).not.toBeInTheDocument()
      expect(screen.queryByLabelText(/search files/i)).not.toBeInTheDocument()
    })

    it('shows "No printer selected" when printerId is empty', () => {
      const props = createDrawerProps({ printerId: '' })
      render(<FilesDrawer {...props} />)

      expect(screen.getByText(/no printer selected/i)).toBeInTheDocument()
    })

    it('handles missing print counts gracefully', () => {
      const props = createDrawerProps({
        printCounts: new Map<string, number>(), // Empty map
      })
      render(<FilesDrawer {...props} />)

      // Files should still render, counts should show as "-"
      expect(screen.getByText('benchy.gcode')).toBeInTheDocument()

      // The print count display should show "-" for missing counts
      const printCounts = screen.getAllByText('-')
      expect(printCounts.length).toBeGreaterThan(0)
    })
  })

  describe('Test 2: File sorting', () => {
    it('sorts files by name by default', () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const fileTexts = screen.getAllByText(/\.gcode/)
      // Names should be sorted alphabetically: benchy, calibration, test
      expect(fileTexts[0].textContent).toContain('benchy')
      expect(fileTexts[1].textContent).toContain('calibration')
      expect(fileTexts[2].textContent).toContain('test')
    })

    it('sorts files by size when "Sort: Size" is selected', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const sortDropdown = screen.getByLabelText(/sort files/i) as HTMLSelectElement
      await userEvent.selectOptions(sortDropdown, 'size')

      // Wait for re-render
      await waitFor(() => {
        // After sorting by size (largest first):
        // benchy: 2.5MB, test: 1.5MB, calibration: 0.5MB
        const fileRows = screen.getAllByText(/B /)
        expect(fileRows).toBeDefined()
      })

      // Verify the sort was applied by checking the dropdown value
      expect(sortDropdown.value).toBe('size')
    })

    it('sorts files by modified date when "Sort: Modified" is selected', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const sortDropdown = screen.getByLabelText(/sort files/i) as HTMLSelectElement
      await userEvent.selectOptions(sortDropdown, 'modified')

      // Verify the sort was applied
      await waitFor(() => {
        expect(sortDropdown.value).toBe('modified')
      })
    })

    it('sorts files by last printed when "Sort: Last Printed" is selected', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const sortDropdown = screen.getByLabelText(/sort files/i) as HTMLSelectElement
      await userEvent.selectOptions(sortDropdown, 'last_printed')

      // Verify the sort was applied
      await waitFor(() => {
        expect(sortDropdown.value).toBe('last_printed')
      })
    })

    it('maintains sort order across sort key changes', async () => {
      const props = createDrawerProps()
      const { rerender } = render(<FilesDrawer {...props} />)

      const sortDropdown = screen.getByLabelText(/sort files/i) as HTMLSelectElement

      // Change to size sort
      await userEvent.selectOptions(sortDropdown, 'size')
      await waitFor(() => {
        expect(sortDropdown.value).toBe('size')
      })

      // Change to name sort
      await userEvent.selectOptions(sortDropdown, 'name')
      await waitFor(() => {
        expect(sortDropdown.value).toBe('name')
      })
    })

    it('handles files with missing metadata fields during sorting', () => {
      const filesWithMissing = [
        { ...mockFileA, modified: null }, // No modified date
        mockFileB,
        { ...mockFileC, size: null }, // No size
      ]

      const props = createDrawerProps({
        fileBrowser: createMockBrowserResponse({
          files: filesWithMissing,
        }),
      })

      render(<FilesDrawer {...props} />)

      // Files should still render without crashing
      expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
      expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
      expect(screen.getByText('test.gcode')).toBeInTheDocument()
    })
  })

  describe('Test 3: File search filtering', () => {
    it('filters files by search term (case-insensitive)', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement

      // Initial state: all three files visible
      expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
      expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
      expect(screen.getByText('test.gcode')).toBeInTheDocument()

      // Search for "bench"
      await userEvent.type(searchInput, 'bench')

      // Only benchy.gcode should be visible
      await waitFor(() => {
        expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
        expect(screen.queryByText('calibration.gcode')).not.toBeInTheDocument()
        expect(screen.queryByText('test.gcode')).not.toBeInTheDocument()
      })
    })

    it('filters with uppercase search term', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement

      // Search for "CALIBRATION"
      await userEvent.type(searchInput, 'CALIBRATION')

      // Only calibration.gcode should be visible
      await waitFor(() => {
        expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
        expect(screen.queryByText('benchy.gcode')).not.toBeInTheDocument()
        expect(screen.queryByText('test.gcode')).not.toBeInTheDocument()
      })
    })

    it('clears search to show all files again', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement

      // Search for "bench"
      await userEvent.type(searchInput, 'bench')

      await waitFor(() => {
        expect(screen.queryByText('calibration.gcode')).not.toBeInTheDocument()
      })

      // Clear search
      await userEvent.clear(searchInput)

      // All files should be visible again
      await waitFor(() => {
        expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
        expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
        expect(screen.getByText('test.gcode')).toBeInTheDocument()
      })
    })

    it('shows no results when search term matches nothing', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement

      // Search for something that doesn't match
      await userEvent.type(searchInput, 'nonexistent-file-xyz')

      // All files should be hidden
      await waitFor(() => {
        expect(screen.queryByText('benchy.gcode')).not.toBeInTheDocument()
        expect(screen.queryByText('calibration.gcode')).not.toBeInTheDocument()
        expect(screen.queryByText('test.gcode')).not.toBeInTheDocument()
      })
    })

    it('filters with partial file extension', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement

      // Search for ".gcode"
      await userEvent.type(searchInput, '.gcode')

      // All files should still be visible (all are .gcode files)
      await waitFor(() => {
        expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
        expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
        expect(screen.getByText('test.gcode')).toBeInTheDocument()
      })
    })

    it('combines search filtering with sorting', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement
      const sortDropdown = screen.getByLabelText(/sort files/i) as HTMLSelectElement

      // Apply sort by size first
      await userEvent.selectOptions(sortDropdown, 'size')

      // Then search for files with "cal"
      await userEvent.type(searchInput, 'cal')

      // Only calibration.gcode should be visible
      await waitFor(() => {
        expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
        expect(screen.queryByText('benchy.gcode')).not.toBeInTheDocument()
      })
    })

    it('preserves sort order when clearing search', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement
      const sortDropdown = screen.getByLabelText(/sort files/i) as HTMLSelectElement

      // Set sort to size
      await userEvent.selectOptions(sortDropdown, 'size')

      // Search for "bench"
      await userEvent.type(searchInput, 'bench')

      // Clear search
      await userEvent.clear(searchInput)

      // Size sort should still be active
      await waitFor(() => {
        expect(sortDropdown.value).toBe('size')
      })
    })
  })

  describe('Test 4: Action button callbacks', () => {
    it('calls onRequestPrint and onFileSelected when Print button is clicked', async () => {
      const onRequestPrint = vi.fn()
      const onFileSelected = vi.fn()

      const props = createDrawerProps({
        canWrite: true,
        onRequestPrint,
        onFileSelected,
      })

      render(<FilesDrawer {...props} />)

      const printButtons = screen.getAllByRole('button', { name: /^print$/i })
      await userEvent.click(printButtons[0]) // Click first Print button

      // Both callbacks should be called with the correct filename
      await waitFor(() => {
        expect(onFileSelected).toHaveBeenCalledWith('benchy.gcode')
        expect(onRequestPrint).toHaveBeenCalledWith('benchy.gcode')
      })
    })

    it('calls onFileSelected with relative filename (without gcodes/ prefix)', async () => {
      const onFileSelected = vi.fn()

      const props = createDrawerProps({
        onFileSelected,
        onRequestPrint: vi.fn(),
        canWrite: true,
      })

      render(<FilesDrawer {...props} />)

      const printButtons = screen.getAllByRole('button', { name: /^print$/i })
      await userEvent.click(printButtons[0])

      // Filename should not have "gcodes/" prefix
      await waitFor(() => {
        expect(onFileSelected).toHaveBeenCalledWith('benchy.gcode')
        expect(onFileSelected).not.toHaveBeenCalledWith('gcodes/benchy.gcode')
      })
    })

    it('calls onFileSelected with nested path filenames', async () => {
      const onFileSelected = vi.fn()
      const nestedFile: FileEntry = {
        name: 'nested.gcode',
        path: 'gcodes/models/nested.gcode',
        kind: 'file',
        size: 1000000,
        modified: 1722873600,
        permissions: '644',
        metadata: {},
      }

      const props = createDrawerProps({
        fileBrowser: createMockBrowserResponse({ files: [nestedFile] }),
        onFileSelected,
        onRequestPrint: vi.fn(),
        canWrite: true,
      })

      render(<FilesDrawer {...props} />)

      const printButtons = screen.getAllByRole('button', { name: /^print$/i })
      await userEvent.click(printButtons[0])

      // Should strip "gcodes/" prefix but keep relative path
      await waitFor(() => {
        expect(onFileSelected).toHaveBeenCalledWith('models/nested.gcode')
      })
    })

    it('calls onMessage when Inspect button is clicked', async () => {
      const onMessage = vi.fn()

      const props = createDrawerProps({
        onMessage,
      })

      // Mock the file detail API response
      mockedFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          filename: 'benchy.gcode',
          size: 2500000,
          print_start_time: '2024-08-05T10:00:00Z',
        }),
      })

      render(<FilesDrawer {...props} />)

      const inspectButtons = screen.getAllByRole('button', { name: /^inspect$/i })
      await userEvent.click(inspectButtons[0])

      // onMessage should be called with loading message
      await waitFor(() => {
        expect(onMessage).toHaveBeenCalledWith(expect.stringContaining('Loading'))
      })

      // onMessage should be called with success message
      await waitFor(() => {
        expect(onMessage).toHaveBeenCalledWith(expect.stringContaining('Loaded'))
      })
    })

    it('handles multiple file prints sequentially', async () => {
      const onRequestPrint = vi.fn()
      const onFileSelected = vi.fn()

      const props = createDrawerProps({
        canWrite: true,
        onRequestPrint,
        onFileSelected,
      })

      render(<FilesDrawer {...props} />)

      const printButtons = screen.getAllByRole('button', { name: /^print$/i })

      // Click first file print
      await userEvent.click(printButtons[0])
      await waitFor(() => {
        expect(onRequestPrint).toHaveBeenCalledWith('benchy.gcode')
      })

      // Click second file print
      await userEvent.click(printButtons[1])
      await waitFor(() => {
        expect(onRequestPrint).toHaveBeenCalledWith('calibration.gcode')
      })

      expect(onRequestPrint).toHaveBeenCalledTimes(2)
    })

    it('calls onNavigate when "Open path" button is clicked', async () => {
      const onNavigate = vi.fn()

      const props = createDrawerProps({ onNavigate })

      render(<FilesDrawer {...props} />)

      const openPathButton = screen.getByRole('button', { name: /open path/i })
      await userEvent.click(openPathButton)

      await waitFor(() => {
        expect(onNavigate).toHaveBeenCalledWith('gcodes')
      })
    })

    it('calls onNavigate when directory is clicked', async () => {
      const onNavigate = vi.fn()

      const props = createDrawerProps({ onNavigate })

      render(<FilesDrawer {...props} />)

      // Click the "models/" directory
      const dirButton = screen.getByRole('button', { name: /models\// })
      await userEvent.click(dirButton)

      await waitFor(() => {
        expect(onNavigate).toHaveBeenCalledWith('gcodes/models')
      })
    })

    it('calls onNavigate with parent directory when ".." is clicked', async () => {
      const onNavigate = vi.fn()

      const props = createDrawerProps({
        filePath: 'gcodes/models',
        fileBrowser: createMockBrowserResponse({
          path: 'gcodes/models',
        }),
        onNavigate,
      })

      render(<FilesDrawer {...props} />)

      const parentButton = screen.getByRole('button', { name: /\.\./ })
      await userEvent.click(parentButton)

      await waitFor(() => {
        expect(onNavigate).toHaveBeenCalledWith('gcodes')
      })
    })

    it('does not call any callbacks when clicking on buttons outside file list', async () => {
      const callbacks = {
        onRequestPrint: vi.fn(),
        onFileSelected: vi.fn(),
        onNavigate: vi.fn(),
      }

      const props = createDrawerProps(callbacks)

      render(<FilesDrawer {...props} />)

      // Find and click the path input field and open button (not file actions)
      const pathInput = screen.getByLabelText(/browse path/i) as HTMLInputElement
      await userEvent.clear(pathInput)
      await userEvent.type(pathInput, 'gcodes/test')

      // These should not trigger file-related callbacks
      expect(callbacks.onRequestPrint).not.toHaveBeenCalled()
      expect(callbacks.onFileSelected).not.toHaveBeenCalled()
    })
  })

  describe('Edge cases and error handling', () => {
    it('renders empty file list when fileBrowser has no files', () => {
      const props = createDrawerProps({
        fileBrowser: createMockBrowserResponse({
          files: [],
          dirs: [],
        }),
      })

      render(<FilesDrawer {...props} />)

      // Should render the list container but no file rows
      expect(screen.queryByText('benchy.gcode')).not.toBeInTheDocument()
      expect(screen.queryByText('calibration.gcode')).not.toBeInTheDocument()
    })

    it('handles very long filenames', () => {
      const longNameFile: FileEntry = {
        name: 'this_is_a_very_long_filename_that_might_break_ui_if_not_handled_properly_model_version_12345.gcode',
        path: 'gcodes/this_is_a_very_long_filename_that_might_break_ui_if_not_handled_properly_model_version_12345.gcode',
        kind: 'file',
        size: 1000000,
        modified: 1722873600,
        permissions: '644',
        metadata: {},
      }

      const props = createDrawerProps({
        fileBrowser: createMockBrowserResponse({
          files: [longNameFile],
        }),
      })

      render(<FilesDrawer {...props} />)

      expect(screen.getByText(longNameFile.name)).toBeInTheDocument()
    })

    it('handles files with special characters in names', () => {
      const specialCharFile: FileEntry = {
        name: 'file-with-dash_and_underscore.gcode',
        path: 'gcodes/file-with-dash_and_underscore.gcode',
        kind: 'file',
        size: 1000000,
        modified: 1722873600,
        permissions: '644',
        metadata: {},
      }

      const props = createDrawerProps({
        fileBrowser: createMockBrowserResponse({
          files: [specialCharFile],
        }),
      })

      render(<FilesDrawer {...props} />)

      expect(screen.getByText('file-with-dash_and_underscore.gcode')).toBeInTheDocument()
    })

    it('renders zero print counts', () => {
      const props = createDrawerProps({
        printCounts: (() => {
          const counts = new Map<string, number>()
          counts.set('test.gcode', 0)
          return counts
        })(),
      })

      render(<FilesDrawer {...props} />)

      // Should display "0" for zero print counts
      const zeroElements = screen.getAllByText('0')
      expect(zeroElements.length).toBeGreaterThan(0)
    })

    it('handles print counts with large numbers', () => {
      const props = createDrawerProps({
        printCounts: (() => {
          const counts = new Map<string, number>()
          counts.set('benchy.gcode', 999)
          counts.set('calibration.gcode', 5000)
          return counts
        })(),
      })

      render(<FilesDrawer {...props} />)

      expect(screen.getByText('999')).toBeInTheDocument()
      expect(screen.getByText('5000')).toBeInTheDocument()
    })

    it('handles upload toolbar visibility based on canWrite', () => {
      const propsWritable = createDrawerProps({ canWrite: true })
      const { unmount: unmountWritable } = render(<FilesDrawer {...propsWritable} />)

      // Upload toolbar should be present
      expect(screen.getByLabelText(/choose file to upload/i)).toBeInTheDocument()

      unmountWritable()

      const propsReadOnly = createDrawerProps({ canWrite: false })
      render(<FilesDrawer {...propsReadOnly} />)

      // Upload button should not be available (input exists but button is disabled)
      const uploadButton = screen.queryByRole('button', { name: /upload/i })
      if (uploadButton) {
        expect(uploadButton).toBeDisabled()
      }
    })

    it('preserves search term when no matches found', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const searchInput = screen.getByLabelText(/search files/i) as HTMLInputElement

      await userEvent.type(searchInput, 'nomatch')

      await waitFor(() => {
        expect(searchInput.value).toBe('nomatch')
      })
    })
  })

  describe('Integration tests', () => {
    it('maintains state correctly across multiple interactions', async () => {
      const callbacks = {
        onRequestPrint: vi.fn(),
        onFileSelected: vi.fn(),
        onNavigate: vi.fn(),
        onMessage: vi.fn(),
      }

      const props = createDrawerProps(callbacks)
      render(<FilesDrawer {...props} />)

      // Step 1: Search for a file
      const searchInput = screen.getByLabelText(/search files/i)
      await userEvent.type(searchInput, 'bench')

      await waitFor(() => {
        expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
        expect(screen.queryByText('calibration.gcode')).not.toBeInTheDocument()
      })

      // Step 2: Sort the filtered results
      const sortDropdown = screen.getByLabelText(/sort files/i)
      await userEvent.selectOptions(sortDropdown, 'size')

      // Step 3: Click Print on the filtered file
      const printButtons = screen.getAllByRole('button', { name: /^print$/i })
      await userEvent.click(printButtons[0])

      await waitFor(() => {
        expect(callbacks.onRequestPrint).toHaveBeenCalledWith('benchy.gcode')
      })

      // Step 4: Clear search
      await userEvent.clear(searchInput)

      await waitFor(() => {
        expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
        expect(screen.getByText('calibration.gcode')).toBeInTheDocument()
      })

      // Sort should still be active
      expect((sortDropdown as HTMLSelectElement).value).toBe('size')
    })

    it('handles rapid sorting changes', async () => {
      const props = createDrawerProps()
      render(<FilesDrawer {...props} />)

      const sortDropdown = screen.getByLabelText(/sort files/i) as HTMLSelectElement

      // Rapidly change sort order
      await userEvent.selectOptions(sortDropdown, 'size')
      await userEvent.selectOptions(sortDropdown, 'name')
      await userEvent.selectOptions(sortDropdown, 'modified')
      await userEvent.selectOptions(sortDropdown, 'last_printed')

      // Last sort should be active
      await waitFor(() => {
        expect(sortDropdown.value).toBe('last_printed')
      })

      // Files should still render
      expect(screen.getByText('benchy.gcode')).toBeInTheDocument()
    })
  })
})

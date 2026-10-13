import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFilesState } from '../useFilesState'
import type { FileBrowserResponse, FileEntry, FileSortKey } from '../fileUtils'

// ============================================================================
// Mock dependencies
// ============================================================================

vi.mock('../useFilesDrawer', () => ({
  useFileUpload: vi.fn(),
  useFilteredFiles: vi.fn(),
  useFileDetail: vi.fn(),
}))

import * as useFilesDrawerModule from '../useFilesDrawer'

// ============================================================================
// Test fixtures
// ============================================================================

const mockFileEntries: FileEntry[] = [
  {
    name: 'test-print-1.gcode',
    path: 'gcodes/test-print-1.gcode',
    kind: 'file',
    size: 5242880, // 5MB
    modified: 1690000000,
    permissions: 'rw-r--r--',
    metadata: { print_start_time: '2024-01-01T10:00:00Z' },
  },
  {
    name: 'test-print-2.gcode',
    path: 'gcodes/test-print-2.gcode',
    kind: 'file',
    size: 2097152, // 2MB
    modified: 1690100000,
    permissions: 'rw-r--r--',
    metadata: { print_start_time: '2024-01-02T14:30:00Z' },
  },
  {
    name: 'advanced-print.gcode',
    path: 'gcodes/advanced-print.gcode',
    kind: 'file',
    size: 8388608, // 8MB
    modified: 1690200000,
    permissions: 'rw-r--r--',
    metadata: {},
  },
]

const mockFileBrowser: FileBrowserResponse = {
  printer_id: 'printer-123',
  path: 'gcodes',
  root: 'gcodes',
  dirs: [],
  files: mockFileEntries,
}

// ============================================================================
// Test suite
// ============================================================================

describe('useFilesState', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ==========================================================================
  // Test 1: Manages file list state (sort, search, upload state)
  // ==========================================================================

  it('manages file list state with sort, search, and upload state', () => {
    // Setup: mock the dependencies
    const mockUploadFile = new File(['test'], 'upload.gcode', { type: 'text/plain' })
    const mockFilteredFiles = [mockFileEntries[0], mockFileEntries[1]]

    vi.mocked(useFilesDrawerModule.useFileUpload).mockReturnValue({
      uploadFile: null,
      setUploadFile: vi.fn(),
      uploadBusy: false,
      upload: vi.fn(),
    })

    vi.mocked(useFilesDrawerModule.useFilteredFiles).mockReturnValue(mockFilteredFiles)

    vi.mocked(useFilesDrawerModule.useFileDetail).mockReturnValue({
      detail: null,
      inspect: vi.fn(),
    })

    // Render the hook
    const { result } = renderHook(() =>
      useFilesState({
        printerId: 'printer-123',
        filePath: 'gcodes',
        fileBrowser: mockFileBrowser,
        printCounts: new Map([['test-print-1.gcode', 2]]),
        canWrite: true,
        onNavigate: vi.fn(),
        onRequestPrint: vi.fn(),
        onFileSelected: vi.fn(),
        onMessage: vi.fn(),
        onUploaded: vi.fn(),
      }),
    )

    // Verify initial state
    expect(result.current.fileSort).toBe('name')
    expect(result.current.fileSearchTerm).toBe('')
    expect(result.current.uploadAutoPrint).toBe(false)
    expect(result.current.uploadBusy).toBe(false)
    expect(result.current.uploadFile).toBeNull()
    expect(result.current.sortedFiles).toEqual(mockFilteredFiles)

    // Update sort
    act(() => {
      result.current.setFileSort('size')
    })
    expect(result.current.fileSort).toBe('size')

    // Update search term
    act(() => {
      result.current.setFileSearchTerm('test')
    })
    expect(result.current.fileSearchTerm).toBe('test')

    // Update upload auto-print toggle
    act(() => {
      result.current.setUploadAutoPrint(true)
    })
    expect(result.current.uploadAutoPrint).toBe(true)

    // Verify that useFilteredFiles was called with correct params
    expect(useFilesDrawerModule.useFilteredFiles).toHaveBeenCalledWith(
      mockFileBrowser.files,
      'test',
      'size',
    )
  })

  // ==========================================================================
  // Test 2: File upload triggers callbacks
  // ==========================================================================

  it('triggers onUploaded callback when file upload completes', () => {
    // Setup: mock upload behavior
    const mockOnUploaded = vi.fn()
    const mockOnMessage = vi.fn()
    const mockUpload = vi.fn()
    const mockSetUploadFile = vi.fn()

    vi.mocked(useFilesDrawerModule.useFileUpload).mockReturnValue({
      uploadFile: new File(['test'], 'newfile.gcode', { type: 'text/plain' }),
      setUploadFile: mockSetUploadFile,
      uploadBusy: false,
      upload: mockUpload,
    })

    vi.mocked(useFilesDrawerModule.useFilteredFiles).mockReturnValue(mockFileEntries)

    vi.mocked(useFilesDrawerModule.useFileDetail).mockReturnValue({
      detail: null,
      inspect: vi.fn(),
    })

    // Render the hook
    const { result } = renderHook(() =>
      useFilesState({
        printerId: 'printer-123',
        filePath: 'gcodes',
        fileBrowser: mockFileBrowser,
        printCounts: new Map(),
        canWrite: true,
        onNavigate: vi.fn(),
        onRequestPrint: vi.fn(),
        onFileSelected: vi.fn(),
        onMessage: mockOnMessage,
        onUploaded: mockOnUploaded,
      }),
    )

    // Verify upload function was received
    expect(result.current.upload).toBeDefined()

    // Call upload
    act(() => {
      result.current.upload()
    })

    // Verify upload was called
    expect(mockUpload).toHaveBeenCalled()

    // Simulate the onDone callback from useFileUpload
    // In the real hook, this is wired through useFileUpload's onDone parameter
    const useFileUploadCall = vi.mocked(useFilesDrawerModule.useFileUpload).mock.calls[0][0]
    expect(useFileUploadCall.onDone).toBeDefined()

    // Trigger the callback as if upload succeeded
    act(() => {
      useFileUploadCall.onDone('newfile.gcode', true)
    })

    // Verify that onUploaded was called with correct params
    expect(mockOnUploaded).toHaveBeenCalledWith('newfile.gcode', true)
  })

  // ==========================================================================
  // Test 3: File search filters correctly
  // ==========================================================================

  it('filters file list when search term changes', () => {
    // Setup: create files with different names to test search
    const testFiles: FileEntry[] = [
      {
        name: 'nozzle-calibration.gcode',
        path: 'gcodes/nozzle-calibration.gcode',
        kind: 'file',
        size: 1048576,
        modified: 1690000000,
        permissions: 'rw-r--r--',
        metadata: {},
      },
      {
        name: 'bed-leveling.gcode',
        path: 'gcodes/bed-leveling.gcode',
        kind: 'file',
        size: 2097152,
        modified: 1690100000,
        permissions: 'rw-r--r--',
        metadata: {},
      },
      {
        name: 'test-pattern.gcode',
        path: 'gcodes/test-pattern.gcode',
        kind: 'file',
        size: 3145728,
        modified: 1690200000,
        permissions: 'rw-r--r--',
        metadata: {},
      },
    ]

    const fileBrowserWithTestFiles: FileBrowserResponse = {
      printer_id: 'printer-123',
      path: 'gcodes',
      root: 'gcodes',
      dirs: [],
      files: testFiles,
    }

    // Track calls to useFilteredFiles to verify search term is passed
    const mockFilteredFilesCall = vi.fn(() => [testFiles[0]])
    vi.mocked(useFilesDrawerModule.useFilteredFiles).mockImplementation(mockFilteredFilesCall)

    vi.mocked(useFilesDrawerModule.useFileUpload).mockReturnValue({
      uploadFile: null,
      setUploadFile: vi.fn(),
      uploadBusy: false,
      upload: vi.fn(),
    })

    vi.mocked(useFilesDrawerModule.useFileDetail).mockReturnValue({
      detail: null,
      inspect: vi.fn(),
    })

    // Render the hook
    const { result, rerender } = renderHook(
      ({ searchTerm }: { searchTerm: string }) =>
        useFilesState({
          printerId: 'printer-123',
          filePath: 'gcodes',
          fileBrowser: fileBrowserWithTestFiles,
          printCounts: new Map(),
          canWrite: true,
          onNavigate: vi.fn(),
          onRequestPrint: vi.fn(),
          onFileSelected: vi.fn(),
          onMessage: vi.fn(),
          onUploaded: vi.fn(),
        }),
      {
        initialProps: { searchTerm: '' },
      },
    )

    // Initial state: no search term, all files should be considered
    expect(result.current.fileSearchTerm).toBe('')
    expect(mockFilteredFilesCall).toHaveBeenCalledWith(
      fileBrowserWithTestFiles.files,
      '',
      'name',
    )

    // Update search term to 'nozzle'
    act(() => {
      result.current.setFileSearchTerm('nozzle')
    })

    // Verify the search term is updated
    expect(result.current.fileSearchTerm).toBe('nozzle')

    // Verify useFilteredFiles is called with the new search term
    expect(mockFilteredFilesCall).toHaveBeenCalledWith(
      fileBrowserWithTestFiles.files,
      'nozzle',
      'name',
    )

    // Update search term to 'test'
    act(() => {
      result.current.setFileSearchTerm('test')
    })

    expect(result.current.fileSearchTerm).toBe('test')
    expect(mockFilteredFilesCall).toHaveBeenCalledWith(
      fileBrowserWithTestFiles.files,
      'test',
      'name',
    )

    // Update search term to empty string
    act(() => {
      result.current.setFileSearchTerm('')
    })

    expect(result.current.fileSearchTerm).toBe('')
    expect(mockFilteredFilesCall).toHaveBeenCalledWith(
      fileBrowserWithTestFiles.files,
      '',
      'name',
    )
  })

  // ==========================================================================
  // Additional coverage: Callbacks and derived data
  // ==========================================================================

  it('provides navigate, handlePrint, and handleInspect callbacks', () => {
    const mockNavigate = vi.fn()
    const mockOnFileSelected = vi.fn()
    const mockOnRequestPrint = vi.fn()
    const mockInspect = vi.fn()

    vi.mocked(useFilesDrawerModule.useFileUpload).mockReturnValue({
      uploadFile: null,
      setUploadFile: vi.fn(),
      uploadBusy: false,
      upload: vi.fn(),
    })

    vi.mocked(useFilesDrawerModule.useFilteredFiles).mockReturnValue(mockFileEntries)

    vi.mocked(useFilesDrawerModule.useFileDetail).mockReturnValue({
      detail: null,
      inspect: mockInspect,
    })

    const { result } = renderHook(() =>
      useFilesState({
        printerId: 'printer-123',
        filePath: 'gcodes',
        fileBrowser: mockFileBrowser,
        printCounts: new Map(),
        canWrite: true,
        onNavigate: mockNavigate,
        onRequestPrint: mockOnRequestPrint,
        onFileSelected: mockOnFileSelected,
        onMessage: vi.fn(),
        onUploaded: vi.fn(),
      }),
    )

    // Test navigate callback
    act(() => {
      result.current.navigate('gcodes/subfolder')
    })
    expect(mockNavigate).toHaveBeenCalledWith('gcodes/subfolder')

    // Test handlePrint callback
    act(() => {
      result.current.handlePrint(mockFileEntries[0])
    })
    expect(mockOnFileSelected).toHaveBeenCalledWith('test-print-1.gcode')
    expect(mockOnRequestPrint).toHaveBeenCalledWith('test-print-1.gcode')

    // Test handleInspect callback
    act(() => {
      result.current.handleInspect(mockFileEntries[1])
    })
    expect(mockInspect).toHaveBeenCalledWith('test-print-2.gcode')
  })

  it('computes parent path from file browser', () => {
    vi.mocked(useFilesDrawerModule.useFileUpload).mockReturnValue({
      uploadFile: null,
      setUploadFile: vi.fn(),
      uploadBusy: false,
      upload: vi.fn(),
    })

    vi.mocked(useFilesDrawerModule.useFilteredFiles).mockReturnValue(mockFileEntries)

    vi.mocked(useFilesDrawerModule.useFileDetail).mockReturnValue({
      detail: null,
      inspect: vi.fn(),
    })

    const { result: resultWithPath } = renderHook(() =>
      useFilesState({
        printerId: 'printer-123',
        filePath: 'gcodes/subfolder',
        fileBrowser: {
          ...mockFileBrowser,
          path: 'gcodes/subfolder',
        },
        printCounts: new Map(),
        canWrite: true,
        onNavigate: vi.fn(),
        onRequestPrint: vi.fn(),
        onFileSelected: vi.fn(),
        onMessage: vi.fn(),
        onUploaded: vi.fn(),
      }),
    )

    // Parent of 'gcodes/subfolder' should be 'gcodes'
    expect(resultWithPath.current.parent).toBe('gcodes')

    // Test root path
    const { result: resultAtRoot } = renderHook(() =>
      useFilesState({
        printerId: 'printer-123',
        filePath: 'gcodes',
        fileBrowser: {
          ...mockFileBrowser,
          path: 'gcodes',
        },
        printCounts: new Map(),
        canWrite: true,
        onNavigate: vi.fn(),
        onRequestPrint: vi.fn(),
        onFileSelected: vi.fn(),
        onMessage: vi.fn(),
        onUploaded: vi.fn(),
      }),
    )

    // Parent of root 'gcodes' should be null (no parent row rendered)
    expect(resultAtRoot.current.parent).toBeNull()
  })

  it('provides printCounts from props', () => {
    const printCounts = new Map([
      ['test-print-1.gcode', 5],
      ['test-print-2.gcode', 2],
    ])

    vi.mocked(useFilesDrawerModule.useFileUpload).mockReturnValue({
      uploadFile: null,
      setUploadFile: vi.fn(),
      uploadBusy: false,
      upload: vi.fn(),
    })

    vi.mocked(useFilesDrawerModule.useFilteredFiles).mockReturnValue(mockFileEntries)

    vi.mocked(useFilesDrawerModule.useFileDetail).mockReturnValue({
      detail: null,
      inspect: vi.fn(),
    })

    const { result } = renderHook(() =>
      useFilesState({
        printerId: 'printer-123',
        filePath: 'gcodes',
        fileBrowser: mockFileBrowser,
        printCounts,
        canWrite: true,
        onNavigate: vi.fn(),
        onRequestPrint: vi.fn(),
        onFileSelected: vi.fn(),
        onMessage: vi.fn(),
        onUploaded: vi.fn(),
      }),
    )

    expect(result.current.printCounts).toBe(printCounts)
    expect(result.current.printCounts.get('test-print-1.gcode')).toBe(5)
  })
})

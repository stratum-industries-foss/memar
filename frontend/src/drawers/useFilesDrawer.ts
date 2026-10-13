/**
 * useFilesDrawer — Three modular hooks for file browser state management.
 *
 * Extracted from FilesDrawer to separate concerns:
 *  - useFileDetail: manages file metadata fetching and display state
 *  - useFileUpload: handles file selection, upload progress, and post-upload actions
 *  - useFilteredFiles: filters and sorts the file list based on search term and sort key
 *
 * Based on patterns from useTemperatureState and useJogState.
 */

import { useCallback, useMemo, useState } from 'react'
import { apiFetch } from '../api'
import type { FileEntry, FileSortKey } from './fileUtils'
import type { FileDetailResponse } from './types.printer'

// ============================================================================
// useFileDetail — File metadata fetching and display
// ============================================================================

interface UseFileDetailReturn {
  /** Currently inspected file detail, or null if none selected. */
  detail: FileDetailResponse | null
  /** Fetch and display metadata for a file. */
  inspect: (filename: string) => Promise<void>
}

/**
 * useFileDetail — Manages file detail card state (inspect metadata).
 *
 * Fetches file metadata from `/api/printers/{printerId}/files/detail?filename=...`
 * on demand. Provides the detail object to render FileDetailCard, and an inspect
 * callback for the UI to trigger the fetch.
 *
 * @param printerId - Device ID for the API endpoint
 * @param onMessage - Status line writer (for errors, success messages)
 */
export function useFileDetail(printerId: string, onMessage: (msg: string) => void): UseFileDetailReturn {
  const [detail, setDetail] = useState<FileDetailResponse | null>(null)

  const inspect = useCallback(
    async (filename: string) => {
      if (!printerId || !filename) return

      try {
        onMessage(`Loading ${filename}...`)
        const response = await apiFetch(`/api/printers/${printerId}/files/detail?filename=${encodeURIComponent(filename)}`)
        if (!response.ok) {
          onMessage(`Failed to load file details: ${response.statusText}`)
          return
        }
        const payload = (await response.json()) as FileDetailResponse
        setDetail(payload)
        onMessage(`Loaded ${filename}`)
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        onMessage(`Failed to load file details: ${msg}`)
      }
    },
    [printerId, onMessage],
  )

  return { detail, inspect }
}

// ============================================================================
// useFileUpload — File upload state and progress
// ============================================================================

interface UseFileUploadOptions {
  /** Device ID for the upload endpoint. */
  printerId: string
  /** Current directory path (for upload destination). */
  filePath: string
  /** Auto-start print after upload. */
  autoPrint: boolean
  /** Status line writer. */
  onMessage: (msg: string) => void
  /** Callback after successful upload: (filename, startedPrint) => void */
  onDone: (filename: string, startedPrint: boolean) => void
}

interface UseFileUploadReturn {
  /** Currently selected file, or null if none. */
  uploadFile: File | null
  /** Update the selected file. */
  setUploadFile: (file: File | null) => void
  /** True if upload is in progress. */
  uploadBusy: boolean
  /** Perform the upload. */
  upload: () => Promise<void>
}

/**
 * useFileUpload — Manages file selection and upload state.
 *
 * Handles FormData construction, progress tracking, and post-upload callbacks.
 * Integrates with autoPrint to optionally start a print immediately after upload.
 *
 * Uploads to `/api/printers/{printerId}/files/upload` with multipart/form-data.
 * Expected POST body: { file: File, path?: string, start_print?: boolean }
 */
export function useFileUpload(options: UseFileUploadOptions): UseFileUploadReturn {
  const { printerId, filePath, autoPrint, onMessage, onDone } = options
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadBusy, setUploadBusy] = useState(false)

  const upload = useCallback(async () => {
    if (!printerId || !uploadFile) return

    setUploadBusy(true)
    try {
      const form = new FormData()
      form.append('file', uploadFile)
      if (filePath && filePath !== 'gcodes') {
        form.append('path', filePath)
      }
      if (autoPrint) {
        form.append('start_print', 'true')
      }

      onMessage(`Uploading ${uploadFile.name}...`)
      const response = await apiFetch(`/api/printers/${printerId}/files/upload`, {
        method: 'POST',
        body: form,
      })

      if (!response.ok) {
        onMessage(`Upload failed: ${response.statusText}`)
        return
      }

      const uploaded = uploadFile.name
      setUploadFile(null)
      onMessage(`Uploaded ${uploaded}`)
      onDone(uploaded, autoPrint)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      onMessage(`Upload failed: ${msg}`)
    } finally {
      setUploadBusy(false)
    }
  }, [printerId, uploadFile, filePath, autoPrint, onMessage, onDone])

  return {
    uploadFile,
    setUploadFile,
    uploadBusy,
    upload,
  }
}

// ============================================================================
// useFilteredFiles — File list filtering and sorting
// ============================================================================

interface UseFilteredFilesReturn extends Array<FileEntry> {
  // Typed as an array so it can be spread or mapped directly
}

/**
 * useFilteredFiles — Filters and sorts file list based on search term and sort key.
 *
 * Applies text search (case-insensitive name match) followed by sorting
 * (by name, size, modified date, or last printed timestamp).
 *
 * Returns a stable sorted array; changes to search term or sort key trigger
 * recalculation via useMemo.
 *
 * Sort keys:
 *  - 'name': alphabetical by filename
 *  - 'size': largest first (null sizes treated as 0)
 *  - 'modified': newest first (null timestamps treated as epoch 0)
 *  - 'last_printed': newest print_start_time first (from file metadata)
 *
 * @param files - File list from FileBrowserResponse.files, or undefined if not loaded
 * @param searchTerm - Text to search for in file names (case-insensitive)
 * @param sortKey - Which field to sort by
 */
export function useFilteredFiles(
  files: FileEntry[] | undefined,
  searchTerm: string,
  sortKey: FileSortKey,
): FileEntry[] {
  return useMemo(() => {
    if (!files || files.length === 0) return []

    // Filter by search term (case-insensitive name match)
    const filtered = files.filter((f) =>
      f.name.toLowerCase().includes(searchTerm.toLowerCase()),
    )

    // Sort by the selected key
    const sorted = [...filtered].sort((a, b) => {
      switch (sortKey) {
        case 'name':
          return a.name.localeCompare(b.name)

        case 'size':
          return (b.size ?? 0) - (a.size ?? 0)

        case 'modified':
          // Treat null timestamps as epoch 0
          const aTime = a.modified ? a.modified * 1000 : 0
          const bTime = b.modified ? b.modified * 1000 : 0
          return bTime - aTime

        case 'last_printed': {
          // Extract print_start_time from metadata; newest first
          const aMetadata = a.metadata as Record<string, unknown> | undefined
          const bMetadata = b.metadata as Record<string, unknown> | undefined
          const aStart = aMetadata?.print_start_time ? new Date(aMetadata.print_start_time as string).getTime() : 0
          const bStart = bMetadata?.print_start_time ? new Date(bMetadata.print_start_time as string).getTime() : 0
          return bStart - aStart
        }

        default:
          return 0
      }
    })

    return sorted
  }, [files, searchTerm, sortKey])
}

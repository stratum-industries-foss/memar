import { useCallback, useMemo, useState } from 'react'
import { useFileDetail, useFileUpload, useFilteredFiles } from './useFilesDrawer'
import {
  normalizeJobKey,
  parentPath,
  relativeFilename,
  type FileBrowserResponse,
  type FileEntry,
  type FileSortKey,
} from './fileUtils'

/**
 * useFilesState — encapsulates all view-local state and callbacks for FilesDrawer.
 *
 * Extracted from FilesDrawer to conform to DrawerProps interface, which accepts
 * only { printer, printerId }. All state management now lives here.
 */
export function useFilesState({
  printerId,
  filePath,
  fileBrowser,
  printCounts,
  canWrite,
  onNavigate,
  onRequestPrint,
  onFileSelected,
  onMessage,
  onUploaded,
}: {
  printerId: string
  filePath: string
  fileBrowser: FileBrowserResponse | null
  printCounts: Map<string, number>
  canWrite: boolean
  onNavigate: (path: string) => Promise<void> | void
  onRequestPrint: (filename: string) => void
  onFileSelected: (filename: string) => void
  onMessage: (text: string) => void
  onUploaded: (filename: string, startedPrint: boolean) => void
}) {
  const [fileSort, setFileSort] = useState<FileSortKey>('name')
  const [fileSearchTerm, setFileSearchTerm] = useState('')
  const [uploadAutoPrint, setUploadAutoPrint] = useState(false)

  const { uploadFile, setUploadFile, uploadBusy, upload } = useFileUpload({
    printerId,
    filePath,
    autoPrint: uploadAutoPrint,
    onMessage,
    onDone: onUploaded,
  })
  const { detail: selectedFileDetail, inspect } = useFileDetail(printerId, onMessage)

  const sortedFiles = useFilteredFiles(fileBrowser?.files, fileSearchTerm, fileSort)

  const navigate = useCallback((path: string) => { void onNavigate(path) }, [onNavigate])

  const handlePrint = useCallback((entry: FileEntry) => {
    const filename = relativeFilename(entry.path)
    // Order matters: the dryrun tab reads dispatchFilename, and the confirm
    // dialog opened by onRequestPrint can be dismissed — the dryrun tab should
    // still be pre-populated either way, exactly as before extraction.
    onFileSelected(filename)
    onRequestPrint(filename)
  }, [onFileSelected, onRequestPrint])

  const handleInspect = useCallback((entry: FileEntry) => {
    void inspect(relativeFilename(entry.path))
  }, [inspect])

  // `..` target, or null at the root (where no parent row is rendered).
  const parent = useMemo(
    () => (fileBrowser ? parentPath(fileBrowser.path) : null),
    [fileBrowser],
  )

  return {
    // Sort and search state
    fileSort,
    setFileSort,
    fileSearchTerm,
    setFileSearchTerm,
    // Upload state
    uploadFile,
    setUploadFile,
    uploadAutoPrint,
    setUploadAutoPrint,
    uploadBusy,
    upload,
    // Inspection state
    selectedFileDetail,
    // Derived data
    sortedFiles,
    parent,
    printCounts,
    // Callbacks
    navigate,
    handlePrint,
    handleInspect,
  }
}

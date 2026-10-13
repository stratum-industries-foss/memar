/**
 * FilesDrawer - the `files` section of the per-printer workspace drawer.
 *
 * Browse the machine's G-code directory, upload, print, and inspect metadata.
 *
 * ── State ownership ────────────────────────────────────────────────────────
 * `fileBrowser` and `filePath` are App-owned and arrive via a dependency-injection
 * pattern passed to useFilesState. That is not an oversight, it is forced by two
 * call sites:
 *
 *   (a) `uploadFromDashboard` (App.tsx) calls `reloadFiles(filePath)` to refresh
 *       an already-open drawer after a multi-printer dashboard upload. If the
 *       browser state lived here, that refresh would silently stop working.
 *   (b) `openPrinterWorkspace` seeds `fileBrowser` from a shared
 *       `Promise.allSettled` batch under one AbortController, and resets
 *       `filePath` on every printer switch.
 *
 * Only view-local state (sort, search, upload selection, inspected detail) moved
 * down into useFilesState. See AGENT_APP_GUIDE §6 decision matrix: "local controlled
 * input, toggle" → `useState`; server-fetched data keeps its existing single owner.
 *
 * ── Styling ────────────────────────────────────────────────────────────────
 * No stylesheet of its own, by repo convention: `styles.css` is a single global
 * sheet and every other component (FleetTools, AdminPanel) consumes drawer
 * classes straight from it. A scoped CSS module here would in fact BREAK the
 * timelapse list, which reuses `.file-list` / `.file-row` / `.file-row-flex`
 * (App.tsx ~5132). Those classes are shared, not files-drawer-private.
 */
import React, { useEffect, useState } from 'react'
import { FileDetailCard } from './FileDetailCard'
import { useFilesState } from './useFilesState'
import type { DrawerProps } from '../types/drawer-props'
import {
  formatBytes,
  formatTimestamp,
  normalizeJobKey,
  type FileBrowserResponse,
  type FileEntry,
  type FileSortKey,
} from './fileUtils'
import type { FileDetailResponse } from './types.printer'

/** Explains what the count does and does not include. Kept verbatim from the
 * original markup - support has leaned on this wording to head off "why is this
 * lower than my printer's own job history?" tickets. */
const PRINT_COUNT_TITLE =
  "Times MEMAR has run this file on this machine - completed, failed and cancelled runs all count. " +
  "Covers only what MEMAR has observed, plus a 30-day import of the printer's own history, " +
  "so it reads lower than the printer's native job history."

/**
 * FilesDrawerInternalProps - full state contract passed to useFilesState.
 * Mirrors the old FilesDrawerProps but kept internal; App passes these
 * to the hook, not directly to the component.
 */
export interface FilesDrawerInternalProps {
  printerId: string
  fileBrowser: FileBrowserResponse | null
  filePath: string
  printCounts: Map<string, number>
  canWrite: boolean
  onNavigate: (path: string) => Promise<void> | void
  onRequestPrint: (filename: string) => void
  onFileSelected: (filename: string) => void
  onMessage: (text: string) => void
  onUploaded: (filename: string, startedPrint: boolean) => void
}

// ---------- private children ----------

function FileBrowserToolbar({
  filePath, showSortRow, sort, onSortChange, searchTerm, onSearchChange, onNavigate,
}: {
  filePath: string
  showSortRow: boolean
  sort: FileSortKey
  onSortChange: (value: FileSortKey) => void
  searchTerm: string
  onSearchChange: (value: string) => void
  onNavigate: (path: string) => void
}) {
  // Local echo so typing a path does not push a state update into App on every
  // keystroke. Re-synced whenever App changes filePath - a directory click, a
  // parent-row click, or a printer switch resetting it to 'gcodes'. Without
  // this effect the box would go stale the moment the user clicks a folder.
  const [pathInput, setPathInput] = useState(filePath)
  useEffect(() => { setPathInput(filePath) }, [filePath])

  return (
    <>
      <div className="file-toolbar">
        <input
          aria-label="Browse path"
          value={pathInput}
          onChange={(event) => setPathInput(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') onNavigate(pathInput) }}
        />
        <button type="button" onClick={() => onNavigate(pathInput)}>Open path</button>
      </div>
      {showSortRow && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
          <select
            aria-label="Sort files"
            value={sort}
            onChange={(e) => onSortChange(e.target.value as FileSortKey)}
            style={{ flex: 1 }}
          >
            <option value="name">Sort: Name</option>
            <option value="size">Sort: Size</option>
            <option value="modified">Sort: Modified</option>
            <option value="last_printed">Sort: Last Printed</option>
          </select>
          <input
            type="text"
            aria-label="Search files"
            placeholder="Search files..."
            value={searchTerm}
            onChange={(e) => onSearchChange(e.target.value)}
            style={{ flex: 1 }}
          />
        </div>
      )}
    </>
  )
}

function FileUploadToolbar({
  canWrite, uploadFile, onPick, autoPrint, onAutoPrintChange, busy, onUpload,
}: {
  canWrite: boolean
  uploadFile: File | null
  onPick: (file: File | null) => void
  autoPrint: boolean
  onAutoPrintChange: (value: boolean) => void
  busy: boolean
  onUpload: () => void
}) {
  return (
    <div className="upload-toolbar">
      <input type="file" aria-label="Choose file to upload" onChange={(event) => onPick(event.target.files?.[0] || null)} />
      <label className="checkbox-line">
        <input type="checkbox" checked={autoPrint} onChange={(event) => onAutoPrintChange(event.target.checked)} /> Auto print
      </label>
      {canWrite && (
        <button type="button" onClick={onUpload} disabled={!uploadFile || busy}>
          {busy ? 'Uploading…' : 'Upload'}
        </button>
      )}
    </div>
  )
}

const FileRow = React.memo(function FileRow({
  entry, printCount, canWrite, onPrint, onInspect,
}: {
  entry: FileEntry
  printCount: number | undefined
  canWrite: boolean
  onPrint: (entry: FileEntry) => void
  onInspect: (entry: FileEntry) => void
}) {
  return (
    <div className="file-row file-row-flex">
      <div>
        <strong>{entry.name}</strong>
        <div className="subtle small">{formatBytes(entry.size)} • {formatTimestamp(entry.modified)}</div>
      </div>
      <div className="file-print-count" title={PRINT_COUNT_TITLE}>
        <span className="subtle small">Times printed</span>
        <strong>{printCount ?? '-'}</strong>
      </div>
      <div className="inline-actions">
        {canWrite && <button type="button" onClick={() => onPrint(entry)}>Print</button>}
        <button type="button" onClick={() => onInspect(entry)}>Inspect</button>
      </div>
    </div>
  )
})

// ---------- wrapper for external state injection ----------

/**
 * FilesDrawerShell - wraps the refactored component to accept the old prop interface.
 * This shell is used by App and integrates with useFilesState to provide all state
 * management. Eventually, App can be refactored to pass DrawerProps + inject state
 * via a context or provider.
 */
export function FilesDrawerShell(props: FilesDrawerInternalProps): React.ReactElement {
  const state = useFilesState(props)
  return <FilesDrawerInner {...state} fileBrowser={props.fileBrowser} filePath={props.filePath} canWrite={props.canWrite} />
}

// ---------- main ----------

interface FilesDrawerInnerProps {
  // View-local state from useFilesState
  fileSort: import('./fileUtils').FileSortKey
  setFileSort: (value: import('./fileUtils').FileSortKey) => void
  fileSearchTerm: string
  setFileSearchTerm: (value: string) => void
  uploadFile: File | null
  setUploadFile: (file: File | null) => void
  uploadAutoPrint: boolean
  setUploadAutoPrint: (value: boolean) => void
  uploadBusy: boolean
  upload: () => Promise<void>
  selectedFileDetail: FileDetailResponse | null
  sortedFiles: FileEntry[]
  parent: string | null
  printCounts: Map<string, number>
  navigate: (path: string) => void
  handlePrint: (entry: FileEntry) => void
  handleInspect: (entry: FileEntry) => void
  // Props from outer scope needed for rendering
  fileBrowser: FileBrowserResponse | null
  filePath: string
  canWrite: boolean
}

function FilesDrawerInner({
  fileSort,
  setFileSort,
  fileSearchTerm,
  setFileSearchTerm,
  uploadFile,
  setUploadFile,
  uploadAutoPrint,
  setUploadAutoPrint,
  uploadBusy,
  upload,
  selectedFileDetail,
  sortedFiles,
  parent,
  printCounts,
  navigate,
  handlePrint,
  handleInspect,
  fileBrowser,
  filePath,
  canWrite,
}: FilesDrawerInnerProps) {
  return (
    <section className="drawer-section">
      <h3>Files</h3>

      <FileBrowserToolbar
        filePath={filePath}
        showSortRow={!!fileBrowser}
        sort={fileSort}
        onSortChange={setFileSort}
        searchTerm={fileSearchTerm}
        onSearchChange={setFileSearchTerm}
        onNavigate={navigate}
      />

      <FileUploadToolbar
        canWrite={canWrite}
        uploadFile={uploadFile}
        onPick={setUploadFile}
        autoPrint={uploadAutoPrint}
        onAutoPrintChange={setUploadAutoPrint}
        busy={uploadBusy}
        onUpload={() => void upload()}
      />

      {fileBrowser && (
        <div className="file-list">
          {fileBrowser.dirs.length === 0 && sortedFiles.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">📁</div>
              <h4>No files in this directory</h4>
              <p>Upload G-code files to get started.</p>
            </div>
          ) : (
            <>
              {parent && (
                <button type="button" className="file-row dir-row" onClick={() => navigate(parent)}>..</button>
              )}
              {fileBrowser.dirs.map((entry) => (
                <button type="button" key={entry.path} className="file-row dir-row" onClick={() => navigate(entry.path)}>
                  {entry.name}/
                </button>
              ))}
              {sortedFiles.map((entry) => (
                <FileRow
                  key={entry.path}
                  entry={entry}
                  // Keyed on entry.path, never entry.name - see normalizeJobKey.
                  printCount={printCounts.get(normalizeJobKey(entry.path))}
                  canWrite={canWrite}
                  onPrint={handlePrint}
                  onInspect={handleInspect}
                />
              ))}
            </>
          )}
        </div>
      )}

      {selectedFileDetail && (
        <div className="file-detail-wrapper">
          <h3>Selected file detail</h3>
          <FileDetailCard detail={selectedFileDetail} />
        </div>
      )}
    </section>
  )
}

// For backward compatibility: export the primary component accepting DrawerProps only.
// Extracts state from props via the dependency-injection pattern and passes to useFilesState.
const FilesDrawer: React.FC<DrawerProps> = ({
  printerId,
  printer,
  filePath,
  fileBrowser,
  printCounts,
  canWrite,
  onNavigate,
  onRequestPrint,
  onFileSelected,
  onMessage,
  onUploaded,
  ...rest
}) => {
  // Provide sensible defaults for missing internal props (handles null printer case)
  const internalProps = {
    printerId: printerId || '',
    filePath: (filePath as string) || 'gcodes',
    fileBrowser: (fileBrowser as FileBrowserResponse | null) || null,
    printCounts: (printCounts as Map<string, number>) || new Map(),
    canWrite: (canWrite as boolean) ?? false,
    onNavigate: (onNavigate as ((path: string) => Promise<void> | void)) || (() => {}),
    onRequestPrint: (onRequestPrint as ((filename: string) => void)) || (() => {}),
    onFileSelected: (onFileSelected as ((filename: string) => void)) || (() => {}),
    onMessage: (onMessage as ((text: string) => void)) || (() => {}),
    onUploaded: (onUploaded as ((filename: string, startedPrint: boolean) => void)) || (() => {}),
  }

  // Validate that we have the minimum required props to render
  if (!internalProps.printerId) {
    return (
      <section className="drawer-section">
        <div className="subtle">No printer selected</div>
      </section>
    )
  }

  const state = useFilesState(internalProps)
  return (
    <FilesDrawerInner
      {...state}
      fileBrowser={internalProps.fileBrowser}
      filePath={internalProps.filePath}
      canWrite={internalProps.canWrite}
    />
  )
}

const MemoizedFilesDrawer = React.memo(FilesDrawer)

export { MemoizedFilesDrawer as FilesDrawer }

// Export the component as default (used by drawer registry)
export default MemoizedFilesDrawer

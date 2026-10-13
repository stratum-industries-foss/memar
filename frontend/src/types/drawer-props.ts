import type { ReactNode } from 'react'
import type {
  Printer,
  Diagnostics,
  OeeDevice,
  CvAnomaly,
  ExcludeObjectsPayload,
  SpoolLogEntry,
  FileDetailResponse,
} from './printer'
import type { Material } from './material'

/**
 * Canonical DrawerProps interface for all 18 drawer components.
 *
 * Previously fragmented across:
 * - src/App.tsx line 884-900 (optional printerId, catch-all [key: string]: any)
 * - src/App.new.tsx line 84-95 (required printerId, catch-all)
 * - src/context/types.ts line 17-38 (required printerId, no catch-all)
 *
 * Consolidated here to enable strict TypeScript type checking.
 * Includes core props and optional callbacks/handlers used by various drawers.
 * Removed catch-all [key: string]: any in favor of explicit optional properties.
 */
export interface DrawerProps {
  // Core printer and capability props
  printerId?: string
  printer?: Printer | null
  currentPrinter?: Printer | null
  canWrite?: boolean

  // Diagnostics and metrics
  diagnostics?: Diagnostics | null
  currentMetric?: {
    success_rate?: number | null
    completed_jobs?: number | null
    failed_jobs?: number | null
    cancelled_jobs?: number | null
    total_print_time?: number | null
    total_filament_used?: number | null
    avg_print_time?: number | null
    last_job_end_time?: number | null
  } | null
  oeeByDevice?: Map<string, OeeDevice | null>
  cvAnomalies?: Record<string, CvAnomaly[]> | null

  // File and data props
  currentFileDetail?: { detail: FileDetailResponse } | null
  excludeObjects?: ExcludeObjectsPayload | null
  spoolLog?: SpoolLogEntry[]
  spoolLogLoading?: boolean
  spoolLogOpen?: boolean

  // UI state and settings
  dashboardSettings?: {
    show_oee?: boolean
    show_empty_capability_tiles?: boolean
    [key: string]: unknown
  }
  capabilityOverviewItems?: (capability: unknown, homedAxes: string, showEmpty?: boolean) => Array<{ label: string; value: string | number | ReactNode }>

  // Spool/filament management
  quickMaterial?: string
  quickRemaining?: number
  quickFilamentSaving?: boolean
  spoolEstimating?: boolean
  spoolEstimateResult?: {
    fill_pct: number
    confidence: 'high' | 'low' | string
    model_used: string
    reasoning?: string
  } | null

  // Optional callbacks used by various drawer components
  onMessage?: (message: string) => void
  onRequestConfirm?: (message: string, onConfirm: () => void) => void
  onRequestPrint?: (file: unknown) => void
  onFileSelected?: (file: unknown) => void
  onUploaded?: (filename?: string, startedPrint?: boolean) => void
  onDone?: () => void

  // State setters for drawer-managed state
  setSpoolLogOpen?: (open: boolean) => void
  setQuickMaterial?: (material: string) => void
  setQuickRemaining?: (remaining: number) => void
  setConfirmState?: (state: unknown) => void

  // Async operations
  fetchSpoolLog?: (printerId?: string) => Promise<void>
  saveQuickFilamentWithLog?: (amount: number) => Promise<void>
  estimateSpoolFromPhoto?: (file: File) => Promise<void>
  loadExcludeObjects?: () => Promise<void>
  doExcludeObject?: (objectName: string) => Promise<void>

  // Formatting functions
  formatDuration?: (ms?: number | null) => string
  formatMillimeters?: (mm?: number | null) => string
  formatTimestamp?: (ts?: number | null) => string

  // File browser props (FilesDrawer)
  filePath?: string
  fileBrowser?: unknown
  printCounts?: Map<string, number> | Record<string, number>
  onNavigate?: (path: string) => void

  // Material props (MaterialSelector integration)
  onMaterialApply?: (materialName: string) => void
  onMaterialSelected?: (material: Material) => void

  // Additional callbacks
  onOpen?: () => void
  onClose?: () => void
  onPrint?: (filename: string) => void
  onDelete?: (filename: string) => Promise<void>
  onUpload?: (file: File, startPrint: boolean) => Promise<void>
  onPhotoAnalysis?: (result: { fill_pct: number; confidence: string; model_used: string }) => void

  // Generic props for flexible drawer extensions
  [key: string]: unknown
}

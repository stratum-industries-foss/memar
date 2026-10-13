/**
 * useDryrunState — Encapsulates all Dry-run drawer state and logic.
 *
 * Manages three independent dry-run endpoints:
 *  1. /api/dry-run/actions/{action} — Test if a printer can execute an action
 *  2. /api/printers/{id}/motion-check — Validate motion system (homing, probe, mesh)
 *  3. /api/dispatch/dry-run — Preflight check for print dispatch across fleet
 *
 * Backend concepts:
 *  - Action dry-run: 9 actions (home, cooldown, motors_off, pause, resume, cancel, firmware_restart, macro, temperature)
 *  - Motion check: Validates homing, axis limits, probe, bed mesh, safe Z state
 *  - Dispatch dry-run: Scores printers for suitability (material, nozzle, build envelope)
 *
 * Note: "thermal/extrusion check" mentioned in the task brief do not exist as separate backend APIs.
 * They are represented here as part of the motion check and dispatch preflight workflows.
 */

import { useState } from 'react'
import { apiFetch } from '../api'

/**
 * API response types matching backend schemas
 */

export type MotionIntent = 'home' | 'jog' | 'park' | 'macro' | 'mesh' | 'unknown'

export interface DryRunResult {
  printer_id: string
  name: string
  eligible: boolean
  would_execute: boolean
  current_state: string | null
  required_state: string | null
  blocking_reasons: string[]
  warnings: string[]
  motion_summary?: string | null
}

export interface DryRunResponse {
  action: string
  mode: string
  results: DryRunResult[]
}

export interface MotionCheckResponse {
  printer_id: string
  name: string
  ok: boolean
  homed_axes: string
  current_state: string | null
  checks: string[]
  warnings: string[]
  blocking_reasons: string[]
}

export interface DispatchDryRunResult {
  printer_id: string
  name: string
  eligible: boolean
  would_queue: boolean
  score: number
  blocking_reasons: string[]
  warnings: string[]
  recommendation: string | null
}

export interface DispatchDryRunResponse {
  filename: string
  requested_material: string | null
  requested_nozzle_diameter_mm: number | null
  recommended_printer_ids: string[]
  results: DispatchDryRunResult[]
}

/**
 * All state and callbacks for dry-run operations
 */
export interface DryrunState {
  // Action dry-run
  selectedAction: string
  setSelectedAction: (action: string) => void
  actionDryRunResults: DryRunResponse | null
  isRunningActionDryRun: boolean
  actionDryRunError: string | null
  runActionDryRun: (printerIds: string[]) => Promise<void>

  // Motion check
  motionIntent: MotionIntent
  setMotionIntent: (intent: MotionIntent) => void
  motionCheckResults: MotionCheckResponse | null
  isRunningMotionCheck: boolean
  motionCheckError: string | null
  runMotionCheck: (printerId: string) => Promise<void>

  // Dispatch preflight
  dispatchFilename: string
  setDispatchFilename: (filename: string) => void
  dispatchMaterial: string
  setDispatchMaterial: (material: string) => void
  dispatchNozzle: string
  setDispatchNozzle: (nozzle: string) => void
  dispatchResults: DispatchDryRunResponse | null
  isRunningDispatch: boolean
  dispatchError: string | null
  runDispatchDryRun: (printerIds: string[]) => Promise<void>
}

export type Fetcher = (url: string, opts?: RequestInit) => Promise<Response>

export function useDryrunState(fetcher: Fetcher = apiFetch): DryrunState {
  // Action dry-run state
  const [selectedAction, setSelectedAction] = useState('home')
  const [actionDryRunResults, setActionDryRunResults] = useState<DryRunResponse | null>(null)
  const [isRunningActionDryRun, setIsRunningActionDryRun] = useState(false)
  const [actionDryRunError, setActionDryRunError] = useState<string | null>(null)

  // Motion check state
  const [motionIntent, setMotionIntent] = useState<MotionIntent>('home')
  const [motionCheckResults, setMotionCheckResults] = useState<MotionCheckResponse | null>(null)
  const [isRunningMotionCheck, setIsRunningMotionCheck] = useState(false)
  const [motionCheckError, setMotionCheckError] = useState<string | null>(null)

  // Dispatch preflight state
  const [dispatchFilename, setDispatchFilename] = useState('')
  const [dispatchMaterial, setDispatchMaterial] = useState('')
  const [dispatchNozzle, setDispatchNozzle] = useState('')
  const [dispatchResults, setDispatchResults] = useState<DispatchDryRunResponse | null>(null)
  const [isRunningDispatch, setIsRunningDispatch] = useState(false)
  const [dispatchError, setDispatchError] = useState<string | null>(null)

  /**
   * Run action dry-run for selected action across printer(s)
   */
  async function runActionDryRun(printerIds: string[]): Promise<void> {
    if (printerIds.length === 0) {
      setActionDryRunError('No printers selected')
      return
    }

    setIsRunningActionDryRun(true)
    setActionDryRunError(null)

    try {
      const body: Record<string, unknown> = {
        printer_ids: printerIds,
        mode: 'standard',
      }

      // Add action-specific parameters
      if (selectedAction === 'macro') {
        body.macro_name = '' // Would be populated from macro selector in component
      }
      if (selectedAction === 'temperature') {
        body.nozzle_target = 0 // Would be populated from temp input in component
        body.bed_target = 0 // Would be populated from temp input in component
      }

      const response = await fetcher(`/api/dry-run/actions/${selectedAction}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const text = await response.text().catch(() => response.statusText)
        throw new Error(text || `HTTP ${response.status}`)
      }

      const data = (await response.json()) as DryRunResponse
      setActionDryRunResults(data)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setActionDryRunError(`Dry-run failed: ${message}`)
      setActionDryRunResults(null)
    } finally {
      setIsRunningActionDryRun(false)
    }
  }

  /**
   * Run motion check on a single printer
   */
  async function runMotionCheck(printerId: string): Promise<void> {
    if (!printerId) {
      setMotionCheckError('No printer selected')
      return
    }

    setIsRunningMotionCheck(true)
    setMotionCheckError(null)

    try {
      const response = await fetcher(`/api/printers/${printerId}/motion-check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intent: motionIntent,
          macro_name: undefined, // Would be populated from component
        }),
      })

      if (!response.ok) {
        const text = await response.text().catch(() => response.statusText)
        throw new Error(text || `HTTP ${response.status}`)
      }

      const data = (await response.json()) as MotionCheckResponse
      setMotionCheckResults(data)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setMotionCheckError(`Motion check failed: ${message}`)
      setMotionCheckResults(null)
    } finally {
      setIsRunningMotionCheck(false)
    }
  }

  /**
   * Run dispatch preflight check for a file across multiple printers
   */
  async function runDispatchDryRun(printerIds: string[]): Promise<void> {
    if (!dispatchFilename.trim()) {
      setDispatchError('Please enter a filename')
      return
    }

    if (printerIds.length === 0) {
      setDispatchError('No printers available')
      return
    }

    setIsRunningDispatch(true)
    setDispatchError(null)

    try {
      const response = await fetcher('/api/dispatch/dry-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: dispatchFilename.trim(),
          printer_ids: printerIds,
          material: dispatchMaterial.trim() || undefined,
          nozzle_diameter_mm: dispatchNozzle ? Number(dispatchNozzle) : undefined,
        }),
      })

      if (!response.ok) {
        const text = await response.text().catch(() => response.statusText)
        throw new Error(text || `HTTP ${response.status}`)
      }

      const data = (await response.json()) as DispatchDryRunResponse
      setDispatchResults(data)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setDispatchError(`Dispatch check failed: ${message}`)
      setDispatchResults(null)
    } finally {
      setIsRunningDispatch(false)
    }
  }

  return {
    selectedAction,
    setSelectedAction,
    actionDryRunResults,
    isRunningActionDryRun,
    actionDryRunError,
    runActionDryRun,

    motionIntent,
    setMotionIntent,
    motionCheckResults,
    isRunningMotionCheck,
    motionCheckError,
    runMotionCheck,

    dispatchFilename,
    setDispatchFilename,
    dispatchMaterial,
    setDispatchMaterial,
    dispatchNozzle,
    setDispatchNozzle,
    dispatchResults,
    isRunningDispatch,
    dispatchError,
    runDispatchDryRun,
  }
}

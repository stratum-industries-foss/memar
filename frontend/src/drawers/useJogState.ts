/**
 * useJogState — state and logic for JogDrawer.
 *
 * Extracted from JogDrawer to conform to DrawerProps interface.
 * This hook manages internal state (distance, feedrate, busy flag) and
 * encapsulates all jog-related logic (motion check, jog commands).
 */

import { useCallback, useState } from 'react'
import { apiFetch } from '../api'
import {
  isCncMachine,
  type JogAxis,
  type MachineTypeValue,
  type MotionCheckResponse,
  type MotionIntent,
} from './machineTypes'

interface UseJogStateOptions {
  /** Device id used to build the jog / motion-check endpoints. */
  printerId: string
  /** From `printer.capability.machine_type`. Drives CNC vs FDM endpoint routing. */
  machineType?: MachineTypeValue
  /** Latest motion-check result. Parent-owned: the dry-run drawer section renders
   * the same payload, so this state must stay lifted. */
  motionCheckPayload: MotionCheckResponse | null
  /** Publishes a new motion-check result up to the parent. */
  onMotionCheckResult: (payload: MotionCheckResponse) => void
  /** Status line writer (the drawer's shared message area). */
  onMessage: (message: string) => void
  /** Optional override for the standalone "Motion check" button. */
  onRunMotionCheck?: () => void
}

interface UseJogStateReturn {
  jogDistance: string
  setJogDistance: (distance: string) => void
  jogFeedrate: string
  setJogFeedrate: (feedrate: string) => void
  busy: boolean
  runJog: (axis: JogAxis, distance: number) => Promise<void>
  runHome: (axes: string) => Promise<void>
  handleMotionCheckClick: () => void
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/**
 * Pull a human-readable reason out of an error response.
 *
 * FastAPI returns `{"detail": "..."}`. The old code showed a bare "Jog failed"
 * with no cause, which is actively misleading for the CNC path: that endpoint
 * requires admin + alpha-ack while this drawer only gates on canWrite, so an
 * operator jogging a CNC machine got a 403 rendered as "Jog failed". Falls back
 * to the raw body, then to the status text, so non-JSON errors read the same as
 * they did before.
 */
async function errorDetail(res: Response): Promise<string> {
  const raw = await res.text().catch(() => '')
  if (!raw) return res.statusText || `HTTP ${res.status}`
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    if (typeof parsed.detail === 'string' && parsed.detail) return parsed.detail
  } catch {
    // Non-JSON body — fall through and show it verbatim.
  }
  return raw
}

function describeError(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function useJogState(options: UseJogStateOptions): UseJogStateReturn {
  const { printerId, machineType, motionCheckPayload, onMotionCheckResult, onMessage, onRunMotionCheck } = options

  const [jogDistance, setJogDistance] = useState<string>('1')
  const [jogFeedrate, setJogFeedrate] = useState<string>('3000')
  // Guards against a second jog being queued while one is in flight. Without it,
  // impatient double-clicks stack duplicate physical moves.
  const [busy, setBusy] = useState(false)

  const isCnc = machineType ? isCncMachine(machineType) : false

  const runJog = useCallback(
    async (axis: JogAxis, distance: number) => {
      if (!Number.isFinite(distance) || distance === 0) {
        onMessage('Enter a non-zero jog distance.')
        return
      }
      setBusy(true)
      try {
        onMessage(`Running motion check for ${axis}${distance}...`)
        // Extruder moves on an FDM machine are macro-shaped, not axis-shaped.
        const intent: MotionIntent = !isCnc && axis === 'E' ? 'macro' : 'jog'
        const checkResponse = await apiFetch(`/api/printers/${printerId}/motion-check`, {
          method: 'POST',
          headers: JSON_HEADERS,
          body: JSON.stringify({ intent }),
        })
        if (!checkResponse.ok) {
          onMessage(`Motion check failed: ${await errorDetail(checkResponse)}`)
          return
        }
        const checkPayload = (await checkResponse.json()) as MotionCheckResponse
        onMotionCheckResult(checkPayload)
        if (!checkPayload.ok) {
          const reasons = checkPayload.blocking_reasons?.join('; ') || 'Unknown reason'
          onMessage(`Jog blocked: ${reasons}`)
          return
        }

        onMessage(`Jogging ${axis}${distance}...`)
        const endpoint = isCnc ? `/api/devices/${printerId}/cnc/jog` : `/api/printers/${printerId}/jog`
        const jogRes = await apiFetch(endpoint, {
          method: 'POST',
          headers: JSON_HEADERS,
          body: JSON.stringify({
            axis,
            distance,
            feedrate: Number(jogFeedrate) || undefined,
            relative: true,
          }),
        })
        onMessage(jogRes.ok ? `Jogged ${axis}${distance}` : `Jog failed: ${await errorDetail(jogRes)}`)
      } catch (err) {
        onMessage(`Jog failed: ${describeError(err)}`)
      } finally {
        setBusy(false)
      }
    },
    [printerId, isCnc, jogFeedrate, onMessage, onMotionCheckResult],
  )

  const runOwnMotionCheck = useCallback(async () => {
    setBusy(true)
    try {
      onMessage('Running motion check...')
      const response = await apiFetch(`/api/printers/${printerId}/motion-check`, {
        method: 'POST',
        headers: JSON_HEADERS,
        body: JSON.stringify({ intent: 'jog' satisfies MotionIntent }),
      })
      if (!response.ok) {
        onMessage(`Motion check failed: ${await errorDetail(response)}`)
        return
      }
      const payload = (await response.json()) as MotionCheckResponse
      onMotionCheckResult(payload)
      const status = payload.ok ? 'passed' : `blocked: ${(payload.blocking_reasons?.join('; ') || 'unknown reason')}`
      onMessage(`Motion check ${status}`)
    } catch (err) {
      onMessage(`Motion check failed: ${describeError(err)}`)
    } finally {
      setBusy(false)
    }
  }, [printerId, onMessage, onMotionCheckResult])

  const handleMotionCheckClick = useCallback(() => {
    if (onRunMotionCheck) {
      onRunMotionCheck()
      return
    }
    void runOwnMotionCheck()
  }, [onRunMotionCheck, runOwnMotionCheck])

  const runHome = useCallback(
    async (axes: string) => {
      setBusy(true)
      try {
        onMessage(`Homing ${axes}...`)
        const endpoint = isCnc ? `/api/devices/${printerId}/cnc/home` : `/api/printers/${printerId}/home`
        const homeRes = await apiFetch(endpoint, {
          method: 'POST',
          headers: JSON_HEADERS,
          body: JSON.stringify({ axes }),
        })
        onMessage(homeRes.ok ? `Homed ${axes}` : `Home failed: ${await errorDetail(homeRes)}`)
      } catch (err) {
        onMessage(`Home failed: ${describeError(err)}`)
      } finally {
        setBusy(false)
      }
    },
    [printerId, isCnc, onMessage],
  )

  return {
    jogDistance,
    setJogDistance,
    jogFeedrate,
    setJogFeedrate,
    busy,
    runJog,
    runHome,
    handleMotionCheckClick,
  }
}

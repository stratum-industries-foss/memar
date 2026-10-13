/**
 * Hook for confirming and handling interactive-mode macros.
 * PROBE_CALIBRATE and SCREWS_TILT_ADJUST require manual user commands (TESTZ, ACCEPT, etc.)
 * and should not be fire-and-forget. This hook gates execution with a confirmation dialog.
 *
 * TODO(post-launch): Implement full interactive mode support including:
 * - Bidirectional gcode feed (capture printer responses, not just fire commands)
 * - Follow-up command routing (TESTZ, ACCEPT, ABORT, etc.)
 * - State machine for probe calibration workflow
 * See: https://github.com/stratum-industries/memar/issues/XXXX
 */

import { useCallback } from 'react'

const INTERACTIVE_MACROS = {
  PROBE_CALIBRATE: {
    title: 'Z-Offset Probe Calibration',
    message:
      'This enters manual probe mode. You must issue TESTZ commands to move the nozzle, then ACCEPT or ABORT to finish. Do not use as fire-and-forget.',
    steps: [
      'Run the macro to start probing.',
      'Issue TESTZ commands (e.g., TESTZ=-0.5) to adjust nozzle height.',
      'When satisfied, issue ACCEPT to save the offset or ABORT to cancel.',
    ],
  },
  SCREWS_TILT_ADJUST: {
    title: 'Manual Bed Leveling (Screw Adjustment)',
    message:
      'This probes bed screws and reports how many turns each screw needs. You must manually adjust screws and may need to re-run to verify.',
    steps: [
      'Run the macro to probe all bed screw positions.',
      'Read the console output for turn counts (e.g., CW 1.5 for clockwise 1.5 turns).',
      'Adjust each screw by the reported amount.',
      'Optionally re-run to verify leveling is within tolerance.',
    ],
  },
}

export type InteractiveMacroName = keyof typeof INTERACTIVE_MACROS

/**
 * Check if a macro name is interactive-mode-requiring.
 */
export function isInteractiveMacro(name: string): name is InteractiveMacroName {
  return name in INTERACTIVE_MACROS
}

/**
 * Get confirmation details for an interactive macro.
 */
export function getInteractiveMacroInfo(
  name: InteractiveMacroName,
): (typeof INTERACTIVE_MACROS)[InteractiveMacroName] {
  return INTERACTIVE_MACROS[name]
}

/**
 * Hook for managing interactive macro confirmations.
 * Returns a function to confirm before executing, or pass if not interactive.
 */
export function useInteractiveMacroConfirm() {
  /**
   * Request confirmation for an interactive macro, or return true immediately if not interactive.
   * In a real implementation, this would show a modal dialog with the steps.
   * For now, we use window.confirm as a placeholder (poor UX but functional).
   *
   * @param macroName - The name of the macro to confirm
   * @returns true if the user confirmed or the macro is not interactive, false if cancelled
   */
  const confirmIfNeeded = useCallback((macroName: string): boolean => {
    if (!isInteractiveMacro(macroName)) {
      return true // Not interactive, proceed
    }

    const info = getInteractiveMacroInfo(macroName)
    const stepsText = info.steps.map((step, i) => `${i + 1}. ${step}`).join('\n')
    const confirmText = `${info.title}\n\n${info.message}\n\nSteps:\n${stepsText}\n\nProceed?`

    return window.confirm(confirmText)
  }, [])

  return { confirmIfNeeded }
}

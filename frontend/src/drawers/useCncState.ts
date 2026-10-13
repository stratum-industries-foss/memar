/**
 * useCncState — CNC drawer state management hook.
 *
 * Encapsulates drawer-level state for the CNC metrics display.
 * Currently maintains no additional state beyond the metrics hook,
 * but provides a seam for future state additions (e.g., filters,
 * alert preferences, view modes).
 */

import { useCallback } from 'react'

export interface CncStateHook {
  // Currently no state to manage; this hook is a seam for future expansion
  // State like socketError, windowMinutes, etc. lives in useCncMetrics
}

/**
 * Hook for CNC drawer state management.
 *
 * @returns CncStateHook object with state management methods
 */
export function useCncState(): CncStateHook {
  // Placeholder: state management methods can be added here
  // without changing the drawer component interface

  return {
    // Future state would go here
  }
}

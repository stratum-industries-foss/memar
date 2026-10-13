/**
 * useConsoleHistory — localStorage-backed command history with arrow navigation
 *
 * Manages a per-printer history array, persists to localStorage, and provides
 * up/down navigation cursor. Dedupes adjacent entries.
 */

import { useCallback, useRef, useState, useEffect } from 'react'
import {
  consoleHistoryKey,
  CONSOLE_HISTORY_LIMIT,
  loadConsoleHistory,
  saveConsoleHistory,
  appendConsoleHistory,
  NO_COMPLETION_CYCLE,
  type CompletionCycle,
} from '../consoleInput'

export interface UseConsoleHistoryResult {
  /** All commands in the history. */
  history: string[]
  /** Current cursor (0..history.length; .length means "not browsing"). */
  historyIndex: number
  /** Set cursor position (for arrow key navigation). */
  setHistoryIndex: (index: number) => void
  /** Ref to track TAB-cycle state across renders. */
  cycleRef: React.MutableRefObject<CompletionCycle>
  /** Reset TAB-cycle state. */
  resetCycle: () => void
  /** Record a command in history and persist to localStorage. */
  record: (command: string) => void
}

/**
 * Hook for managing per-printer console command history.
 *
 * @param printerId - Unique printer identifier (used as localStorage key)
 * @returns History management interface
 */
export function useConsoleHistory(printerId: string): UseConsoleHistoryResult {
  const [history, setHistory] = useState<string[]>(() => loadConsoleHistory(printerId))
  const [historyIndex, setHistoryIndex] = useState(history.length)
  const cycleRef = useRef<CompletionCycle>(NO_COMPLETION_CYCLE)

  // Re-sync history when printerId changes
  useEffect(() => {
    const loaded = loadConsoleHistory(printerId)
    setHistory(loaded)
    setHistoryIndex(loaded.length)
    cycleRef.current = NO_COMPLETION_CYCLE
  }, [printerId])

  const resetCycle = useCallback(() => {
    cycleRef.current = NO_COMPLETION_CYCLE
  }, [])

  const record = useCallback(
    (command: string) => {
      setHistory((prev) => {
        const updated = appendConsoleHistory(prev, command)
        saveConsoleHistory(printerId, updated)
        // Move cursor past the newest entry (ready for up-arrow browsing)
        setHistoryIndex(updated.length)
        resetCycle()
        return updated
      })
    },
    [printerId, resetCycle],
  )

  return {
    history,
    historyIndex,
    setHistoryIndex,
    cycleRef,
    resetCycle,
    record,
  }
}

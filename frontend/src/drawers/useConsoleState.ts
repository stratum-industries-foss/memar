import React, { useCallback, useEffect, useState } from 'react'
import { handleConsoleKey, type CompletionCycle } from '../consoleInput'
import { useConsoleHistory } from './useConsoleHistory'
import { useGcodeConsole } from './useGcodeConsole'
import type { Printer } from '../types/printer'
import type { MachineTypeValue } from './machineTypes'

export interface UseConsoleStateOptions {
  printer: Printer | null
  printerId: string
  macroNames?: readonly string[]
  onEnsureMacrosLoaded?: (printerId: string) => void
}

export interface UseConsoleStateResult {
  consoleInput: string
  setConsoleInput: (value: string) => void
  history: string[]
  historyIndex: number
  setHistoryIndex: (index: number) => void
  cycleRef: React.MutableRefObject<CompletionCycle>
  resetCycle: () => void
  log: Array<{ type: string; text: string }>
  sending: boolean
  scrollRef: React.RefObject<HTMLDivElement>
  send: (script: string) => Promise<void>
  clear: () => void
  loadHistory: () => Promise<void>
  dispatch: (script: string) => void
}

/**
 * Encapsulates all console state and effects, extracted from ConsoleDrawer.
 *
 * Receives printer and printerId; extracts machineType from printer.capability.
 * macroNames and onEnsureMacrosLoaded are optional — defaults to empty array
 * and no-op function respectively if not provided.
 */
export function useConsoleState({
  printer,
  printerId,
  macroNames = [],
  onEnsureMacrosLoaded = () => {},
}: UseConsoleStateOptions): UseConsoleStateResult {
  const [consoleInput, setConsoleInput] = useState<string>('')

  // Extract machineType from printer if available
  const machineType: MachineTypeValue | undefined = printer?.capability?.machine_type

  const { history, historyIndex, setHistoryIndex, cycleRef, resetCycle, record } = useConsoleHistory(printerId)
  const { log, sending, scrollRef, send, clear, loadHistory } = useGcodeConsole({
    printerId,
    machineType,
    onDispatch: record,
  })

  // Lazy-load on mount. The parent renders this section conditionally, so it
  // unmounts on leaving the tab and this fires at the same times the old
  // `activeSection === 'console'` branch did.
  useEffect(() => {
    if (!printerId) return
    void loadHistory()
    // Macros normally arrive with the rest of the workspace payload
    // (openPrinterWorkspace), but that fetch can reject — GRBL has no macro
    // endpoint — leaving TAB with nothing but the static vocabulary. Refetch
    // once if we came up empty. `macroNames` is deliberately NOT in the dep
    // array: this must not re-run when the fetch below lands.
    if (macroNames.length === 0) onEnsureMacrosLoaded(printerId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [printerId])

  // Single dispatch path for both the Enter key and the Send button. Mirrors the
  // original guard order: a blank script never clears the field.
  const dispatch = useCallback(
    (script: string) => {
      if (!printerId || !script.trim()) return
      setConsoleInput('')
      void send(script)
    },
    [printerId, send],
  )

  return {
    consoleInput,
    setConsoleInput,
    history,
    historyIndex,
    setHistoryIndex,
    cycleRef,
    resetCycle,
    log,
    sending,
    scrollRef,
    send,
    clear,
    loadHistory,
    dispatch,
  }
}

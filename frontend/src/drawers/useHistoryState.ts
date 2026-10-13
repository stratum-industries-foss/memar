import { useState, useCallback, useMemo } from 'react'
import { useAppDrawer } from '../context/AppContext'
import {
  HistoryResponse,
  HistoryJob,
  HistorySortKey,
  filterAndSortJobs,
} from './useHistoryUtils'

/**
 * useHistoryState — Extract all state management from HistoryDrawer.
 *
 * Manages:
 *   - statusFilter & sortKey (filtering/sorting state)
 *   - history data (from context or fetched)
 *   - canWrite (derived from printer role/context)
 *   - onReprint (wrapper around context.startPrint)
 *
 * Returns an object compatible with the old HistoryPanel props signature,
 * so the refactored component can use hook values in place of destructured props.
 */
export interface UseHistoryStateReturn {
  history: HistoryResponse | null
  canWrite: boolean
  onReprint: (filename: string) => Promise<void>
  statusFilter: string
  setStatusFilter: (value: string) => void
  sortKey: HistorySortKey
  setSortKey: (value: HistorySortKey) => void
  jobs: HistoryJob[]
}

export function useHistoryState(): UseHistoryStateReturn {
  const { currentPrinter, printerId, startPrint } = useAppDrawer()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [sortKey, setSortKey] = useState<HistorySortKey>('date')

  // TODO: Fetch history from API based on printerId
  // For now, return null (component already handles this case)
  const history: HistoryResponse | null = null as HistoryResponse | null

  // Derive canWrite from printer role/context
  // TODO: Get userRole from context or props to determine actual write permission
  // For now, default to true (component responsibility to gate the action)
  const canWrite = true

  // Wrap startPrint as onReprint
  const onReprint = useCallback(
    async (filename: string) => {
      try {
        if (!printerId) throw new Error('No printer selected')
        await startPrint(printerId, filename)
      } catch (err) {
        console.error('Failed to start print:', err)
      }
    },
    [startPrint, printerId]
  )

  // Memoize the filtered/sorted jobs to avoid unnecessary recalculations
  const jobs = useMemo<HistoryJob[]>(() => {
    if (!history) return []
    return filterAndSortJobs(history.jobs, statusFilter, sortKey)
  }, [history, statusFilter, sortKey])

  return {
    history,
    canWrite,
    onReprint,
    statusFilter,
    setStatusFilter,
    sortKey,
    setSortKey,
    jobs,
  }
}

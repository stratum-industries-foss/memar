/**
 * useExcludeObjects — Exclude objects state and API management hook
 *
 * Fetches available objects from the printer, tracks exclusion state,
 * and provides methods to include/exclude objects during a print.
 *
 * Manages:
 *   - objects: ObjectEntry[] available objects with exclusion state
 *   - isLoading: boolean indicating fetch in progress
 *   - exclude: Function to exclude an object by name
 *   - include: Function to re-include an excluded object
 */

import { useState, useCallback, useEffect } from 'react'
import type { ObjectEntry, ExcludeObjectsResponse } from './spoolUtils'

/**
 * Hook return type for exclude objects management
 */
export interface UseExcludeObjectsReturn {
  objects: ObjectEntry[]
  isLoading: boolean
  error: string | null
  exclude: (objectName: string) => Promise<void>
  include: (objectName: string) => Promise<void>
  excludedObjects: string[]
  isExcluded: (objectName: string) => boolean
}

/**
 * Custom hook for managing exclude-objects state and API interactions.
 *
 * Allows inclusion/exclusion of specific objects from a print job in progress.
 * Useful for Klipper's exclude_objects module.
 *
 * @param printerId - The printer ID for API calls
 * @param excludeState - Initial excluded objects list (optional, allows DI pattern)
 * @returns Object with objects, exclusion helpers, and loading state
 */
export function useExcludeObjects(
  printerId: string,
  excludeState?: string[]
): UseExcludeObjectsReturn {
  const [objects, setObjects] = useState<ObjectEntry[]>([])
  const [excludedObjects, setExcludedObjects] = useState<string[]>(excludeState || [])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  /**
   * Fetch available objects from the printer
   */
  const fetchObjects = useCallback(async () => {
    if (!printerId) {
      setObjects([])
      setIsLoading(false)
      return
    }

    try {
      setIsLoading(true)
      setError(null)

      const response = await fetch(
        `/api/printers/${encodeURIComponent(printerId)}/exclude-objects/list`,
        {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
        }
      )

      if (!response.ok) {
        throw new Error(
          `Failed to fetch exclude objects: ${response.statusText}`
        )
      }

      const data: ExcludeObjectsResponse = await response.json()
      const objList = (data.available_objects || []).map((obj): ObjectEntry => ({
        ...obj,
        status:
          (data.excluded_objects || []).includes(obj.name) ? 'excluded' : 'included',
      }))

      setObjects(objList)
      setExcludedObjects(data.excluded_objects || [])
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      console.error('Exclude objects fetch error:', message)
    } finally {
      setIsLoading(false)
    }
  }, [printerId])

  /**
   * Fetch on mount or when printerId changes
   */
  useEffect(() => {
    fetchObjects()
  }, [fetchObjects])

  /**
   * Exclude a single object by name (prevents it from being printed)
   *
   * @param objectName - Name of the object to exclude
   */
  const exclude = useCallback(
    async (objectName: string) => {
      if (!printerId) {
        setError('No printer selected')
        return
      }

      try {
        setError(null)

        const response = await fetch(
          `/api/printers/${encodeURIComponent(printerId)}/exclude-objects/exclude`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ object_name: objectName }),
          }
        )

        if (!response.ok) {
          throw new Error(`Failed to exclude object: ${response.statusText}`)
        }

        // Update local state
        setExcludedObjects((prev) =>
          [...new Set([...prev, objectName])].sort()
        )
        setObjects((prev) =>
          prev.map((obj) =>
            obj.name === objectName ? { ...obj, status: 'excluded' } : obj
          )
        )
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setError(message)
        console.error('Exclude object error:', message)
        throw err
      }
    },
    [printerId]
  )

  /**
   * Include (re-enable) a previously excluded object
   *
   * @param objectName - Name of the object to re-include
   */
  const include = useCallback(
    async (objectName: string) => {
      if (!printerId) {
        setError('No printer selected')
        return
      }

      try {
        setError(null)

        const response = await fetch(
          `/api/printers/${encodeURIComponent(printerId)}/exclude-objects/include`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ object_name: objectName }),
          }
        )

        if (!response.ok) {
          throw new Error(`Failed to include object: ${response.statusText}`)
        }

        // Update local state
        setExcludedObjects((prev) =>
          prev.filter((name) => name !== objectName).sort()
        )
        setObjects((prev) =>
          prev.map((obj) =>
            obj.name === objectName ? { ...obj, status: 'included' } : obj
          )
        )
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setError(message)
        console.error('Include object error:', message)
        throw err
      }
    },
    [printerId]
  )

  /**
   * Check if an object is currently excluded
   *
   * @param objectName - Name of the object to check
   * @returns true if the object is excluded, false if included
   */
  const isExcluded = useCallback(
    (objectName: string): boolean => {
      return excludedObjects.includes(objectName)
    },
    [excludedObjects]
  )

  return {
    objects,
    isLoading,
    error,
    exclude,
    include,
    excludedObjects,
    isExcluded,
  }
}

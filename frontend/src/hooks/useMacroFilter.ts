/**
 * Macro filtering and parameter handling hook
 * Provides utilities for filtering, searching, and managing macro parameters
 */

import { useMemo, useState, useCallback } from 'react'

/**
 * Represents a macro parameter definition
 */
export type MacroParameter = {
  name: string
  description?: string
  default?: string
  type?: string
}

/**
 * Represents a macro entry
 */
export type MacroEntry = {
  name: string
  description?: string
  parameters?: MacroParameter[]
  is_private?: boolean
  // Additional properties from Klipper macros
  params?: Record<string, { type?: string; default?: string | number | null }>
  color?: string
  category?: string | null  // Explicit category (overrides description-based grouping)
  is_builtin?: boolean      // true for Klipper built-in commands, false for user [gcode_macro]
}

/**
 * Return type for useMacroFilter hook
 */
export type UseMacroFilterReturn = {
  visibleMacros: MacroEntry[]
  privateMacroCount: number
  macroGroups: Array<[string, MacroEntry[]]>
}

/**
 * Hook for filtering and searching macros
 * Handles macro search, filtering by name, visibility, and grouping
 *
 * @param macros - List of macros to filter
 * @param searchTerm - Search term to filter macros
 * @param showPrivateMacros - Whether to show private macros
 * @returns Object with visibleMacros, privateMacroCount, and macroGroups
 */
export function useMacroFilter(
  macros: MacroEntry[] = [],
  searchTerm: string = '',
  showPrivateMacros: boolean = false,
): UseMacroFilterReturn {
  return useMemo(() => {
    if (!macros || macros.length === 0) {
      return { visibleMacros: [], privateMacroCount: 0, macroGroups: [] }
    }

    // First, filter by search term
    let filtered = macros
    if (searchTerm && searchTerm.trim() !== '') {
      const lowerSearchTerm = searchTerm.toLowerCase()
      filtered = macros.filter((macro) => {
        const nameMatch = macro.name.toLowerCase().includes(lowerSearchTerm)
        const descMatch = macro.description?.toLowerCase().includes(lowerSearchTerm)
        return nameMatch || descMatch
      })
    }

    // Separate private and public macros
    const publicMacros = filtered.filter((m) => !m.is_private)
    const privateMacros = filtered.filter((m) => m.is_private)
    const privateMacroCount = privateMacros.length

    // Determine visible macros based on showPrivateMacros flag
    const visibleMacros = showPrivateMacros ? filtered : publicMacros

    // Group visible macros by category (explicit category takes precedence over description-derived)
    const groups = new Map<string, MacroEntry[]>()
    for (const macro of visibleMacros) {
      // Use explicit category if provided, otherwise derive from description or default to 'General'
      const category = macro.category ?? macro.description?.split('\n')[0] ?? 'General'
      if (!groups.has(category)) {
        groups.set(category, [])
      }
      groups.get(category)!.push(macro)
    }

    const macroGroups = Array.from(groups.entries())

    return { visibleMacros, privateMacroCount, macroGroups }
  }, [macros, searchTerm, showPrivateMacros])
}

/**
 * Hook for managing macro parameters
 * Tracks parameter values separately for free-text and typed parameters
 */
export function useMacroParams() {
  // Free-text fallback, per macro
  const [macroParams, setMacroParams] = useState<Record<string, string>>({})
  // Per-macro, per-param values for macros with typed parameters
  const [macroTypedParams, setMacroTypedParams] = useState<
    Record<string, Record<string, string>>
  >({})

  const setMacroParam = useCallback(
    (macroName: string, paramName: string, value: string, isTyped = false) => {
      if (isTyped) {
        setMacroTypedParams((prev) => ({
          ...prev,
          [macroName]: {
            ...(prev[macroName] || {}),
            [paramName]: value,
          },
        }))
      } else {
        setMacroParams((prev) => ({
          ...prev,
          [macroName]: value,
        }))
      }
    },
    [],
  )

  const getMacroParam = useCallback(
    (macroName: string, paramName?: string, isTyped = false) => {
      if (isTyped && paramName) {
        return macroTypedParams[macroName]?.[paramName] ?? ''
      }
      return macroParams[macroName] ?? ''
    },
    [macroParams, macroTypedParams],
  )

  return {
    macroParams,
    setMacroParams,
    macroTypedParams,
    setMacroTypedParams,
    setMacroParam,
    getMacroParam,
  }
}

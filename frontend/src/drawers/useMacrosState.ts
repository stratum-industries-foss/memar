import { useCallback, useEffect, useRef, useMemo, useState } from 'react'
import { apiFetch } from '../api'
import { useMacroFilter } from '../hooks/useMacroFilter'
import type { MacroEntry } from '../hooks/useMacroFilter'
import { parseStringMacroParams } from './useMacroUtils'
import { useAppDrawer } from '../context/AppContext'
import { getAvailableBuiltins } from './macroDescriptions'
import { useInteractiveMacroConfirm } from './useInteractiveMacroConfirm'

export interface MacrosState {
  showPrivateMacros: boolean
  setShowPrivateMacros: (value: boolean) => void
  macroExpanded: string | null
  setMacroExpanded: (value: string | null) => void
  macroParams: Record<string, string>
  setMacroParams: (value: Record<string, string> | ((p: Record<string, string>) => Record<string, string>)) => void
  macroTypedParams: Record<string, Record<string, string>>
  setMacroTypedParams: (value: Record<string, Record<string, string>> | ((p: Record<string, Record<string, string>>) => Record<string, Record<string, string>>)) => void
  visibleMacros: MacroEntry[]
  privateMacroCount: number
  macroGroups: Array<[string, MacroEntry[]]>
  runMacroWithParams: (name: string) => Promise<void>
}

/**
 * Encapsulates all state and effects for the MacrosDrawer component.
 * Handles macro expansion, parameter tracking, filtering, and macro execution.
 * All required context is obtained from useAppDrawer hook.
 */
export function useMacrosState(): MacrosState {
  const {
    printerId,
    macros,
    canWrite,
    searchTerm,
    setSearchTerm,
    setDrawerMessage,
    showToast,
  } = useAppDrawer()
  const [showPrivateMacros, setShowPrivateMacros] = useState<boolean>(false)
  const [macroExpanded, setMacroExpanded] = useState<string | null>(null)
  // Free-text fallback, per macro.
  const [macroParams, setMacroParams] = useState<Record<string, string>>({})
  // Per-macro, per-param values for macros whose parameters the backend could
  // type. Kept separate from macroParams (the free-text fallback) so an untyped
  // macro keeps working exactly as before.
  const [macroTypedParams, setMacroTypedParams] = useState<Record<string, Record<string, string>>>({})

  // Klipper config for capability-gating of built-in functions
  const [klipperConfig, setKlipperConfig] = useState<Record<string, unknown>>({})

  // Context callbacks are stable via the provider, so no need for refs here.
  // The context handles their lifecycle management.

  // Param values are per-machine — carrying a TEMP typed for one printer over
  // to the next machine's macro of the same name would be a real hazard. App
  // used to do this inside openPrinterWorkspace (:2202-2204); owning the state
  // means owning the reset.
  //
  // Guarded against firing on mount: this section is conditionally rendered, so
  // every drawer-tab switch remounts it, and an unguarded effect would do a
  // pointless reset pass on each one. The search term is not touched here — it
  // is the parent's, and App already clears it at :2199.
  const prevPrinterId = useRef(printerId)
  useEffect(() => {
    if (prevPrinterId.current === printerId) return
    prevPrinterId.current = printerId
    setMacroTypedParams({})
    setMacroParams({})
    setMacroExpanded(null)
    setKlipperConfig({}) // Reset config on printer switch
  }, [printerId])

  // Fetch Klipper config to determine available built-in functions
  useEffect(() => {
    if (!printerId) return
    const ctrl = new AbortController()
    apiFetch(`/api/printers/${printerId}/klipper-config`, { signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) return
        const data = await res.json() as { klipper_config?: Record<string, unknown> }
        if (data.klipper_config) {
          setKlipperConfig(data.klipper_config)
        }
      })
      .catch(() => {
        // Silent fail: config fetch errors don't break macro list
      })
    return () => ctrl.abort()
  }, [printerId])

  // Synthesize built-in Klipper functions from config capabilities
  const builtinMacros = useMemo(() => {
    const builtins = getAvailableBuiltins(klipperConfig)
    return builtins.map((def): MacroEntry => ({
      name: def.name,
      description: def.description,
      category: def.category,
      is_builtin: true,
      is_private: false,
      params: def.params
        ? Object.entries(def.params).reduce((acc, [key, spec]) => {
            acc[key] = {
              type: spec.type === 'int' ? 'int' : spec.type === 'float' ? 'float' : 'string',
              default: spec.default ?? null,
            }
            return acc
          }, {} as Record<string, { type?: string; default?: string | number | null }>)
        : {},
      color: undefined,
    }))
  }, [klipperConfig])

  // Merge user-defined macros with built-in functions
  const allMacros = useMemo(
    () => [...macros, ...builtinMacros].sort((a, b) => a.name.localeCompare(b.name)),
    [macros, builtinMacros],
  )

  const { visibleMacros, privateMacroCount, macroGroups } = useMacroFilter(
    allMacros,
    searchTerm,
    showPrivateMacros,
  )

  const { confirmIfNeeded } = useInteractiveMacroConfirm()

  const runMacroWithParams = useCallback(async (name: string) => {
    // Single-point permission gate. The original gated only the Run BUTTON, so
    // a read-only user could still fire a run by pressing Enter in a param
    // field (App.tsx:4590/:4613 vs :4620). Gating here covers every entry path.
    if (!canWrite) return

    // Gate interactive-mode macros with confirmation
    if (!confirmIfNeeded(name)) return

    const macro = allMacros.find((item) => item.name === name)
    const isBuiltin = macro?.is_builtin ?? false
    const typed = macro?.params && Object.keys(macro.params).length > 0

    // Typed macros read their per-field state; untyped ones keep the free-text
    // box. Either way params travel in the request BODY as a KEY=VALUE map —
    // appending them to the macro name in the URL is what the backend rejects
    // with a 400, since a macro name may not contain a space.
    let params: Record<string, string>
    if (typed) {
      params = Object.fromEntries(
        Object.entries(macroTypedParams[name] || {})
          .map(([key, value]): [string, string] => [key, value.trim()])
          .filter(([, value]) => value !== ''),
      )
    } else {
      const parsed = parseStringMacroParams(macroParams[name] || '')
      if (parsed === null) {
        showToast('Parameters must be KEY=VALUE, space separated', 'error')
        return
      }
      params = parsed
    }

    const summary = Object.entries(params).map(([key, value]) => `${key}=${value}`).join(' ')
    const cmd = summary ? `${name} ${summary}` : name
    setDrawerMessage({ message: `Running ${cmd}...`, level: 'info' })

    try {
      // Use /gcode endpoint for built-in Klipper commands, /macros for user-defined
      const endpoint = isBuiltin
        ? `/api/printers/${printerId}/gcode`
        : `/api/printers/${printerId}/macros/${encodeURIComponent(name)}`

      const res = await apiFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(isBuiltin ? { script: cmd } : { params }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({} as { detail?: string }))
        showToast((data as { detail?: string }).detail || 'Execution failed', 'error')
        setDrawerMessage({ message: '', level: 'info' })
        return
      }
      setDrawerMessage({ message: `Ran ${cmd}`, level: 'info' })
      setMacroExpanded(null)
    } catch {
      showToast('Execution failed', 'error')
      setDrawerMessage({ message: '', level: 'info' })
    }
  }, [canWrite, allMacros, macroParams, macroTypedParams, printerId, setDrawerMessage, showToast, confirmIfNeeded])

  return {
    showPrivateMacros,
    setShowPrivateMacros,
    macroExpanded,
    setMacroExpanded,
    macroParams,
    setMacroParams,
    macroTypedParams,
    setMacroTypedParams,
    visibleMacros,
    privateMacroCount,
    macroGroups,
    runMacroWithParams,
  }
}

/**
 * MacroList — Reusable macro grid component.
 * Renders filtered macro groups with parameter fields and execution controls.
 */
import React from 'react'
import type { MacroEntry } from '../hooks/useMacroFilter'

export interface MacroListProps {
  macroGroups: Array<[string, MacroEntry[]]>
  macroExpanded: string | null
  setMacroExpanded: (name: string | null) => void
  macroParams: Record<string, string>
  setMacroParams: (fn: (p: Record<string, string>) => Record<string, string>) => void
  macroTypedParams: Record<string, Record<string, string>>
  setMacroTypedParams: (fn: (p: Record<string, Record<string, string>>) => Record<string, Record<string, string>>) => void
  canWrite: boolean
  onRunMacro: (name: string) => Promise<void>
}

const MacroList: React.FC<MacroListProps> = ({
  macroGroups,
  macroExpanded,
  setMacroExpanded,
  macroParams,
  setMacroParams,
  macroTypedParams,
  setMacroTypedParams,
  canWrite,
  onRunMacro,
}) => {
  return (
    <>
      {macroGroups.map(([category, groupMacros]) => (
        <div
          key={category || '__uncategorised'}
          className="macro-group"
          role="region"
          aria-label={category ? `${category} macros` : 'Uncategorized macros'}
        >
          {/* Only label a group when the config actually named one —
              a lone "Uncategorised" header on a stock printer.cfg is noise. */}
          {category && macroGroups.length > 1 && (
            <div className="macro-group-title subtle small">{category}</div>
          )}
          <div className="macro-grid">
            {groupMacros.map((macro) => {
              const paramSpecs = Object.entries(macro.params || {})
              const expanded = macroExpanded === macro.name

              return (
                <div className="macro-row" key={macro.name}>
                  <button
                    className="macro-button"
                    aria-expanded={expanded}
                    aria-label={`${macro.name}${expanded ? ' (expanded)' : ''}`}
                    style={
                      macro.color
                        ? { borderLeft: `3px solid ${macro.color}` }
                        : undefined
                    }
                    onClick={() =>
                      setMacroExpanded(expanded ? null : macro.name)
                    }
                  >
                    {macro.name}
                  </button>

                  {expanded && (
                    <div className="macro-params">
                      {paramSpecs.length === 0 ? (
                        <input
                          placeholder="params (optional, e.g. TEMP=230)"
                          value={macroParams[macro.name] || ''}
                          onChange={(e) =>
                            setMacroParams((p) => ({
                              ...p,
                              [macro.name]: e.target.value,
                            }))
                          }
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              void onRunMacro(macro.name)
                              e.preventDefault()
                            }
                          }}
                          autoFocus
                          aria-label={`Parameters for ${macro.name}`}
                        />
                      ) : (
                        paramSpecs.map(([paramName, spec], index) => {
                          const inputId = `macro-${macro.name}-${paramName}`
                          const specObj = spec as { type?: string; default?: string | number | null }
                          const numeric =
                            specObj.type === 'int' || specObj.type === 'float'

                          return (
                            <span
                              className="macro-param-field"
                              key={paramName}
                            >
                              <label
                                htmlFor={inputId}
                                className="subtle small"
                              >
                                {paramName}
                              </label>
                              <input
                                id={inputId}
                                type={numeric ? 'number' : 'text'}
                                step={
                                  specObj.type === 'int'
                                    ? 1
                                    : specObj.type === 'float'
                                      ? 0.1
                                      : undefined
                                }
                                placeholder={
                                  specObj.default === null ||
                                  specObj.default === undefined
                                    ? specObj.type
                                    : String(specObj.default)
                                }
                                value={
                                  macroTypedParams[macro.name]?.[paramName] ??
                                  ''
                                }
                                onChange={(e) =>
                                  setMacroTypedParams((p) => ({
                                    ...p,
                                    [macro.name]: {
                                      ...(p[macro.name] || {}),
                                      [paramName]: e.target.value,
                                    },
                                  }))
                                }
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    void onRunMacro(macro.name)
                                    e.preventDefault()
                                  }
                                }}
                                autoFocus={index === 0}
                                aria-label={`${paramName} for ${macro.name}`}
                              />
                            </span>
                          )
                        })
                      )}
                      {canWrite && (
                        <button
                          onClick={() => void onRunMacro(macro.name)}
                          aria-label={`Run ${macro.name}`}
                        >
                          &#9654; Run
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </>
  )
}

export default MacroList

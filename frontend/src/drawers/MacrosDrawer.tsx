import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useMacrosState } from './useMacrosState'
import { useAppDrawer } from '../context/AppContext'

const MacrosDrawer: React.FC<DrawerProps> = ({
  printerId,
  currentPrinter,
  canWrite,
}) => {
  const { searchTerm, setSearchTerm } = useAppDrawer()

  const {
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
  } = useMacrosState()

  if (!currentPrinter) {
    return (
      <section className="drawer-section">
        <h3>Macros</h3>
        <div className="subtle">No printer selected</div>
      </section>
    )
  }

  return (
    <section className="drawer-section">
      <h3>Macros</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 12 }}>
        <div className="file-toolbar">
          <input
            placeholder="Filter macros"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label="Filter macros"
          />
        </div>

        {privateMacroCount > 0 && (
          <label className="subtle small macro-private-toggle">
            <input
              type="checkbox"
              checked={showPrivateMacros}
              onChange={(event) => setShowPrivateMacros(event.target.checked)}
              aria-label={`Toggle private macros (${privateMacroCount})`}
            />
            Show {privateMacroCount} private macro{privateMacroCount === 1 ? '' : 's'} (_ prefix)
          </label>
        )}
      </div>

      {visibleMacros.length === 0 && (
        <div className="subtle">No macros detected.</div>
      )}

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
                              void runMacroWithParams(macro.name)
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
                                    void runMacroWithParams(macro.name)
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
                          onClick={() => void runMacroWithParams(macro.name)}
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
    </section>
  )
}

const MemoizedMacrosDrawer = React.memo(MacrosDrawer)

export default MemoizedMacrosDrawer

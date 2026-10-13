import React, { useEffect } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useConsoleState } from './useConsoleState'
import { handleConsoleKey, NO_COMPLETION_CYCLE } from '../consoleInput'

const ConsoleDrawer = React.memo(function ConsoleDrawer({ printerId = '', currentPrinter = null, canWrite = false }: DrawerProps) {
  const isCnc = currentPrinter?.capability?.machine_type && ['cnc_mill', 'cnc_router', 'cnc_lathe', 'cnc_laser', 'cnc_plasma', 'cnc_waterjet', 'cnc_wire_edm'].includes(currentPrinter.capability.machine_type)
  const headingLabel = isCnc ? 'MDI' : 'G-code console'
  if (!canWrite || !printerId) {
    return (
      <section className="drawer-section">
        <h3>{headingLabel}</h3>
        <div className="subtle">Console unavailable (no write permission or printer not selected)</div>
      </section>
    )
  }

  const {
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
  } = useConsoleState({
    printer: currentPrinter,
    printerId,
    macroNames: [], // Could be passed as prop if available
  })

  // Auto-scroll to bottom when new log entries appear
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [log, scrollRef])

  // Load history on mount
  useEffect(() => {
    void loadHistory()
  }, [printerId])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const next = handleConsoleKey(
      e,
      { input: consoleInput, history, historyIndex, cycle: cycleRef.current },
      [],
    )

    if (next) {
      setConsoleInput(next.input)
      setHistoryIndex(next.historyIndex)
      cycleRef.current = next.cycle
      return
    }

    if (e.key === 'Enter' && consoleInput.trim()) {
      dispatch(consoleInput)
      resetCycle()
    }
  }

  const handleSend = () => {
    if (consoleInput.trim()) {
      dispatch(consoleInput)
      resetCycle()
    }
  }

  const handleClear = () => {
    clear()
  }

  return (
    <section className="drawer-section">
      <h3>{headingLabel}</h3>
      <div
        className="console-log"
        style={{
          height: 260,
          overflowY: 'auto',
          background: 'var(--bg-2, #1a1a1a)',
          borderRadius: 4,
          padding: '8px 10px',
          fontFamily: 'monospace',
          fontSize: 12,
          marginBottom: 8,
        }}
        ref={scrollRef}
      >
        {log.length === 0 && <div className="subtle">No history. Type a command below.</div>}
        {log.map((entry, i) => (
          <div
            key={i}
            style={{
              color:
                entry.type === 'request'
                  ? 'var(--text-secondary, #888)'
                  : entry.type === 'error'
                    ? 'var(--color-danger, #ff6b6b)'
                    : 'var(--text-primary, #fff)',
              marginBottom: 2,
              wordBreak: 'break-word',
            }}
          >
            {entry.type === 'request' ? '> ' : entry.type === 'error' ? '! ' : ''}
            {entry.text}
          </div>
        ))}
      </div>
      <div className="file-toolbar">
        <input
          style={{ flex: 1, fontFamily: 'monospace' }}
          value={consoleInput}
          onChange={(e) => {
            setConsoleInput(e.target.value)
            resetCycle()
          }}
          onKeyDown={handleKeyDown}
          placeholder={isCnc ? 'G0 X0 F200' : 'G28 / M104 S200 / BED_MESH_CALIBRATE…'}
          disabled={sending}
          aria-label="G-code command input"
        />
        <button onClick={handleSend} disabled={sending || !consoleInput.trim()}>
          Send
        </button>
        <button onClick={handleClear} title="Clear log">
          Clear
        </button>
      </div>
      <div className="subtle small" style={{ marginTop: 4 }}>
        Enter to send • ↑/↓ for previous commands • Tab to complete
      </div>
    </section>
  )
})

export default ConsoleDrawer

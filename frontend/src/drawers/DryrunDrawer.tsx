import React, { useState } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useDryrunState, type DryRunResponse, type MotionCheckResponse, type DispatchDryRunResponse, type MotionIntent } from './useDryrunState'
import { Modal } from '../Modal'

/**
 * Matrix display components — render results from dry-run operations
 *
 * Declared here since they're imported from App.tsx:6120/6124
 * In a real implementation, these would be extracted to a shared utility.
 */

const DryRunMatrix = React.memo(function DryRunMatrix({ results }: { results: any[] }) {
  return (
    <div className="matrix-list">
      {results.map((result) => (
        <div key={result.printer_id} className={`matrix-row ${result.eligible ? 'matrix-ok' : 'matrix-blocked'}`}>
          <div>
            <strong>{result.name}</strong>
            <div className="subtle small">{result.motion_summary || result.current_state || '—'}</div>
          </div>
          <div>{result.eligible ? 'Eligible' : 'Blocked'}</div>
          <div className="subtle small">{[...result.blocking_reasons, ...result.warnings].join(' • ') || 'No issues'}</div>
        </div>
      ))}
    </div>
  )
})

const DispatchMatrix = React.memo(function DispatchMatrix({ payload }: { payload: any }) {
  return (
    <div className="matrix-list">
      {payload.results.map((result: any) => (
        <div key={result.printer_id} className={`matrix-row ${result.eligible ? 'matrix-ok' : 'matrix-blocked'}`}>
          <div>
            <strong>{result.name}</strong>
            <div className="subtle small">score {result.score != null ? result.score.toFixed(1) : '—'}</div>
          </div>
          <div>{result.recommendation || (result.eligible ? 'Eligible' : 'Blocked')}</div>
          <div className="subtle small">{[...result.blocking_reasons, ...result.warnings].join(' • ') || 'No issues'}</div>
        </div>
      ))}
    </div>
  )
})

function labelForAction(action: string): string {
  const overrides: Record<string, string> = { motors_off: 'Motors Off', firmware_restart: 'FW Restart' }
  return overrides[action] ?? action.split('_').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
}

function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1)
}

interface DryrunDrawerProps extends DrawerProps {
  printerId?: string
  canWrite?: boolean
}

const DryrunDrawer = React.memo(function DryrunDrawer({ printerId, canWrite = false }: DryrunDrawerProps) {
  const {
    selectedAction,
    setSelectedAction,
    actionDryRunResults,
    isRunningActionDryRun,
    actionDryRunError,
    runActionDryRun,

    motionIntent,
    setMotionIntent,
    motionCheckResults,
    isRunningMotionCheck,
    motionCheckError,
    runMotionCheck,

    dispatchFilename,
    setDispatchFilename,
    dispatchMaterial,
    setDispatchMaterial,
    dispatchNozzle,
    setDispatchNozzle,
    dispatchResults,
    isRunningDispatch,
    dispatchError,
    runDispatchDryRun,
  } = useDryrunState()

  const [showDispatchConfirm, setShowDispatchConfirm] = useState(false)

  if (!printerId) {
    return (
      <section className="drawer-section">
        <h3>Action dry-run</h3>
        <div className="subtle">No printer selected</div>
      </section>
    )
  }

  return (
    <>
      {/* Action Dry-Run Section */}
      <section className="drawer-section">
        <h3>Action dry-run</h3>
        <div className="file-toolbar">
          <select value={selectedAction} onChange={(e) => setSelectedAction(e.target.value)}>
            {['home', 'cooldown', 'motors_off', 'pause', 'resume', 'cancel', 'firmware_restart', 'macro', 'temperature'].map(
              (action) => (
                <option key={action} value={action}>
                  {labelForAction(action)}
                </option>
              ),
            )}
          </select>
          <button
            onClick={() => void runActionDryRun([printerId])}
            disabled={isRunningActionDryRun}
          >
            {isRunningActionDryRun ? 'Running...' : 'Run dry-run'}
          </button>
        </div>
        {actionDryRunError && (
          <div style={{ color: 'var(--color-error)', fontSize: '0.9rem', marginTop: 8 }}>
            {actionDryRunError}
          </div>
        )}
        {actionDryRunResults && <DryRunMatrix results={actionDryRunResults.results} />}
      </section>

      {/* Motion Check Section */}
      {canWrite && (
        <section className="drawer-section">
          <h3>Motion check</h3>
          <div className="file-toolbar">
            <select value={motionIntent} onChange={(e) => setMotionIntent(e.target.value as MotionIntent)}>
              {['home', 'jog', 'park', 'macro', 'mesh', 'unknown'].map((intent) => (
                <option key={intent} value={intent}>
                  {capitalize(intent)}
                </option>
              ))}
            </select>
            <button
              onClick={() => void runMotionCheck(printerId)}
              disabled={isRunningMotionCheck}
            >
              {isRunningMotionCheck ? 'Checking...' : 'Run motion check'}
            </button>
          </div>
          {motionCheckError && (
            <div style={{ color: 'var(--color-error)', fontSize: '0.9rem', marginTop: 8 }}>
              {motionCheckError}
            </div>
          )}
          {motionCheckResults && (
            <div style={{ marginTop: 12 }}>
              <div
                style={{
                  padding: 8,
                  backgroundColor: motionCheckResults.ok ? 'var(--bg-success)' : 'var(--bg-error)',
                  borderRadius: 4,
                  marginBottom: 8,
                }}
              >
                <strong>{motionCheckResults.ok ? '✓ Motion check passed' : '✗ Motion check blocked'}</strong>
                <div className="subtle small" style={{ marginTop: 4 }}>
                  Homed axes: {motionCheckResults.homed_axes || '—'}
                </div>
              </div>

              {motionCheckResults.checks.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <strong style={{ fontSize: '0.9rem' }}>Checks performed:</strong>
                  <ul style={{ margin: '4px 0 0 16px', fontSize: '0.9rem' }}>
                    {motionCheckResults.checks.map((check, idx) => (
                      <li key={idx}>{check}</li>
                    ))}
                  </ul>
                </div>
              )}

              {motionCheckResults.blocking_reasons.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <strong style={{ fontSize: '0.9rem', color: 'var(--color-error)' }}>Blocking reasons:</strong>
                  <ul style={{ margin: '4px 0 0 16px', fontSize: '0.9rem', color: 'var(--color-error)' }}>
                    {motionCheckResults.blocking_reasons.map((reason, idx) => (
                      <li key={idx}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              {motionCheckResults.warnings.length > 0 && (
                <div>
                  <strong style={{ fontSize: '0.9rem', color: 'var(--color-warning)' }}>Warnings:</strong>
                  <ul style={{ margin: '4px 0 0 16px', fontSize: '0.9rem', color: 'var(--color-warning)' }}>
                    {motionCheckResults.warnings.map((warning, idx) => (
                      <li key={idx}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* Dispatch Preflight Section */}
      <section className="drawer-section">
        <h3>Dispatch preflight</h3>
        <div className="temp-grid">
          <label>
            <span>Filename</span>
            <input
              value={dispatchFilename}
              onChange={(e) => setDispatchFilename(e.target.value)}
              placeholder="gcodes/example.gcode"
            />
          </label>
          <label>
            <span>Material</span>
            <input
              value={dispatchMaterial}
              onChange={(e) => setDispatchMaterial(e.target.value)}
              placeholder="PLA"
            />
          </label>
          <label>
            <span>Nozzle mm</span>
            <input
              type="number"
              step="0.05"
              value={dispatchNozzle}
              onChange={(e) => setDispatchNozzle(e.target.value)}
            />
          </label>
        </div>
        <button
          onClick={() => setShowDispatchConfirm(true)}
          disabled={isRunningDispatch || !dispatchFilename.trim()}
        >
          {isRunningDispatch ? 'Checking...' : 'Run dispatch dry-run'}
        </button>
        {dispatchError && (
          <div style={{ color: 'var(--color-error)', fontSize: '0.9rem', marginTop: 8 }}>
            {dispatchError}
          </div>
        )}
        {dispatchResults && <DispatchMatrix payload={dispatchResults} />}
      </section>

      {/* Confirmation Modal for Dispatch */}
      <Modal
        isOpen={showDispatchConfirm}
        onClose={() => setShowDispatchConfirm(false)}
        title="Run Dispatch Dry-Run"
        primaryAction={{
          label: 'Run',
          onClick: () => {
            setShowDispatchConfirm(false)
            const onlinePrinterIds: string[] = [] // Would be passed from App context
            void runDispatchDryRun(onlinePrinterIds.length > 0 ? onlinePrinterIds : [printerId])
          },
        }}
        secondaryAction={{
          label: 'Cancel',
          onClick: () => setShowDispatchConfirm(false),
        }}
      >
        <div>
          <p>
            This will check if the file <strong>{dispatchFilename}</strong> is suitable for printing
            on available printers.
          </p>
          {dispatchMaterial && <p>Material: {dispatchMaterial}</p>}
          {dispatchNozzle && <p>Nozzle diameter: {dispatchNozzle}mm</p>}
          <p style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            The preflight check will validate file compatibility, material availability, and
            machine capabilities.
          </p>
        </div>
      </Modal>
    </>
  )
})

export default DryrunDrawer


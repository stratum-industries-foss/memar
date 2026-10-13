import React, { useCallback, useState } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useJogState } from './useJogState'
import { isCncMachine, type MotionCheckResponse } from './machineTypes'

const JogDrawer: React.FC<DrawerProps> = ({
  printerId,
  currentPrinter,
  canWrite,
  onRequestConfirm,
}) => {
  // Parent-owned motion check payload (shared with dry-run drawer)
  const [motionCheckPayload, setMotionCheckPayload] =
    useState<MotionCheckResponse | null>(null)
  const [drawerMessage, setDrawerMessage] = useState('')

  const handleMessage = useCallback((msg: string) => {
    setDrawerMessage(msg)
  }, [])

  const handleMotionCheckResult = useCallback((payload: MotionCheckResponse) => {
    setMotionCheckPayload(payload)
  }, [])

  const { jogDistance, setJogDistance, jogFeedrate, setJogFeedrate, busy, runJog, runHome, handleMotionCheckClick } =
    useJogState({
      printerId: printerId || '',
      machineType: currentPrinter?.capability.machine_type,
      motionCheckPayload,
      onMotionCheckResult: handleMotionCheckResult,
      onMessage: handleMessage,
    })

  if (!canWrite) {
    return null
  }

  if (!currentPrinter) {
    return (
      <section className="drawer-section">
        <h3>Jog controls</h3>
        <div className="subtle">No printer selected</div>
      </section>
    )
  }

  return (
    <section className="drawer-section">
      <h3>Jog controls</h3>

      {/* Distance and feedrate inputs */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginBottom: 12,
          flexWrap: 'wrap',
          alignItems: 'flex-end',
        }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 80 }}>
          <span style={{ fontSize: '0.75rem', marginBottom: 4, color: 'var(--text-secondary)', fontWeight: 500 }}>
            Distance (mm)
          </span>
          <input
            type="number"
            step="0.1"
            value={jogDistance}
            onChange={(event) => setJogDistance(event.target.value)}
            placeholder="1.0"
            style={{ flex: 1 }}
            aria-label="Jog distance in millimeters"
            disabled={busy}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 100 }}>
          <span style={{ fontSize: '0.75rem', marginBottom: 4, color: 'var(--text-secondary)', fontWeight: 500 }}>
            Feedrate (mm/min)
          </span>
          <input
            type="number"
            step="10"
            value={jogFeedrate}
            onChange={(event) => setJogFeedrate(event.target.value)}
            placeholder="3000"
            style={{ flex: 1 }}
            aria-label="Jog feedrate in millimeters per minute"
            disabled={busy}
          />
        </label>
        <button
          onClick={() => handleMotionCheckClick()}
          style={{ minWidth: 100, height: 32 }}
          disabled={busy}
          aria-label="Run motion check"
        >
          Motion check
        </button>
      </div>

      {/* D-pad and axis controls */}
      <div
        style={{
          display: 'flex',
          gap: 12,
          marginBottom: 12,
        }}
      >
        {/* X/Y D-pad */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            alignItems: 'center',
          }}
          role="group"
          aria-label="X/Y axis control (D-pad)"
        >
          <div
            style={{
              fontSize: '0.75rem',
              marginBottom: 4,
              textAlign: 'center',
              color: 'var(--text-secondary)',
            }}
          >
            X / Y
          </div>
          <button
            onClick={() => void runJog('Y', Number(jogDistance))}
            style={{ width: 50, height: 50, fontSize: '1.5rem' }}
            disabled={busy}
            aria-label="Jog Y+ (forward)"
            title="Jog Y+ (forward)"
          >
            ↑
          </button>
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              onClick={() => void runJog('X', -Number(jogDistance))}
              style={{ width: 50, height: 50, fontSize: '1.5rem' }}
              disabled={busy}
              aria-label="Jog X- (left)"
              title="Jog X- (left)"
            >
              ←
            </button>
            <button
              onClick={() => {
                if (onRequestConfirm) {
                  onRequestConfirm('Home XY axes?', () => void runHome('xy'))
                } else {
                  void runHome('xy')
                }
              }}
              style={{
                width: 50,
                height: 50,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.7rem',
                fontWeight: 600,
                lineHeight: 1.1,
                padding: 2,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
              }}
              disabled={busy}
              aria-label="Home XY"
              title="Home XY"
            >
              HOME
            </button>
            <button
              onClick={() => void runJog('X', Number(jogDistance))}
              style={{ width: 50, height: 50, fontSize: '1.5rem' }}
              disabled={busy}
              aria-label="Jog X+ (right)"
              title="Jog X+ (right)"
            >
              →
            </button>
          </div>
          <button
            onClick={() => void runJog('Y', -Number(jogDistance))}
            style={{ width: 50, height: 50, fontSize: '1.5rem' }}
            disabled={busy}
            aria-label="Jog Y- (back)"
            title="Jog Y- (back)"
          >
            ↓
          </button>
        </div>

        {/* Z axis buttons */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            alignItems: 'center',
          }}
          role="group"
          aria-label="Z axis control"
        >
          <div
            style={{
              fontSize: '0.75rem',
              marginBottom: 4,
              textAlign: 'center',
              color: 'var(--text-secondary)',
            }}
          >
            Z
          </div>
          <button
            onClick={() => void runJog('Z', Number(jogDistance))}
            style={{ width: 50, height: 50, fontSize: '1.5rem' }}
            disabled={busy}
            aria-label="Jog Z+ (up)"
            title="Jog Z+ (up)"
          >
            ↑
          </button>
          <button
            onClick={() => void runHome('z')}
            style={{
              width: 50,
              height: 50,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.75rem',
              fontWeight: 500,
            }}
            disabled={busy}
            aria-label="Home Z"
            title="Home Z"
          >
            HOME
          </button>
          <button
            onClick={() => void runJog('Z', -Number(jogDistance))}
            style={{ width: 50, height: 50, fontSize: '1.5rem' }}
            disabled={busy}
            aria-label="Jog Z- (down)"
            title="Jog Z- (down)"
          >
            ↓
          </button>
        </div>

        {/* HOME ALL button */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            alignItems: 'center',
          }}
          role="group"
          aria-label="Home all axes"
        >
          <div
            style={{
              fontSize: '0.75rem',
              marginBottom: 4,
              textAlign: 'center',
              color: 'var(--text-secondary)',
              width: 50,
            }}
          >
            All
          </div>
          <button
            onClick={() => {
              if (onRequestConfirm) {
                onRequestConfirm('Home all axes (XYZ)?', () => void runHome('xyz'))
              } else {
                void runHome('xyz')
              }
            }}
            style={{
              width: 50,
              height: 90,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.65rem',
              fontWeight: 600,
              textAlign: 'center',
              padding: 4,
              lineHeight: 1.2,
            }}
            disabled={busy}
            aria-label="Home all axes XYZ"
            title="Home all axes"
          >
            HOME<br />ALL
          </button>
        </div>

        {/* Extruder controls (FDM only) */}
        {currentPrinter && currentPrinter.capability?.machine_type && !isCncMachine(currentPrinter.capability.machine_type) && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              alignItems: 'center',
            }}
            role="group"
            aria-label="Extruder control"
          >
            <div
              style={{
                fontSize: '0.75rem',
                marginBottom: 4,
                textAlign: 'center',
                color: 'var(--text-secondary)',
              }}
            >
              E
            </div>
            <button
              onClick={() => void runJog('E', Number(jogDistance))}
              style={{
                width: 50,
                height: 50,
                fontSize: '1rem',
                fontWeight: 500,
              }}
              disabled={busy}
              aria-label="Extrude (E+)"
              title="Extrude"
            >
              +E
            </button>
            <div
              style={{
                width: 50,
                height: 50,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-secondary)',
                fontSize: '0.75rem',
              }}
            >
              Extrude
            </div>
            <button
              onClick={() => void runJog('E', -Number(jogDistance))}
              style={{
                width: 50,
                height: 50,
                fontSize: '1rem',
                fontWeight: 500,
              }}
              disabled={busy}
              aria-label="Retract (E-)"
              title="Retract"
            >
              -E
            </button>
          </div>
        )}
      </div>

      {/* Quick distance buttons */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        <div
          style={{
            fontSize: '0.75rem',
            color: 'var(--text-secondary)',
          }}
        >
          Quick distances:
        </div>
        {[0.1, 1, 10].map((dist) => (
          <button
            key={dist}
            onClick={() => {
              setJogDistance(String(dist))
              void runJog('X', dist)
            }}
            style={{ fontSize: '0.8rem', padding: '4px 8px', minWidth: 'auto' }}
            disabled={busy}
            aria-label={`Jog ${dist}mm`}
            title={`Quick set to ${dist}mm`}
          >
            {dist}mm
          </button>
        ))}
      </div>

      {/* Message/status display */}
      {drawerMessage && (
        <div className="subtle small" style={{ marginBottom: 12 }}>
          {drawerMessage}
        </div>
      )}

      {/* Help text */}
      <div className="subtle small">
        Jogging runs a motion check first. Extruder jog should only be used
        when hot.
      </div>

      {/* Motion check result display */}
      {motionCheckPayload && (
        <div
          style={{
            background: 'var(--bg-2, #1a1a1a)',
            border: `1px solid ${motionCheckPayload.ok ? 'var(--color-success, #51cf66)' : 'var(--color-danger, #ff6b6b)'}`,
            borderRadius: 4,
            padding: 8,
            marginTop: 12,
          }}
        >
          <div
            style={{
              fontSize: '0.85rem',
              fontWeight: 500,
              marginBottom: 6,
              color: motionCheckPayload.ok ? 'var(--color-success, #51cf66)' : 'var(--color-danger, #ff6b6b)',
            }}
          >
            Motion Check: {motionCheckPayload.ok ? 'PASSED ✓' : 'BLOCKED ✗'}
          </div>
          {motionCheckPayload.message && (
            <div style={{ fontSize: '0.8rem', marginBottom: 4, color: 'var(--text-primary)' }}>
              {motionCheckPayload.message}
            </div>
          )}
          {motionCheckPayload.blocking_reasons && motionCheckPayload.blocking_reasons.length > 0 && (
            <div style={{ fontSize: '0.8rem', color: 'var(--color-danger, #ff6b6b)', gap: 4, display: 'flex', flexDirection: 'column' }}>
              {motionCheckPayload.blocking_reasons.map((reason, i) => (
                <div key={i} style={{ wordBreak: 'break-word' }}>• {reason}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

const MemoizedJogDrawer = React.memo(JogDrawer)

export default MemoizedJogDrawer

import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useBedmeshState } from './useBedmeshState'
import { BedMeshPanel } from '../BedMeshPanel'

/**
 * BedmeshDrawer — Bed mesh calibration and visualization panel
 *
 * Requires canWrite permission (operator or admin role).
 * Displays current mesh state, probe grid, and calibration controls.
 */
const BedmeshDrawer = React.memo(function BedmeshDrawer({ printerId, canWrite, ...props }: DrawerProps) {
  if (!canWrite) return null
  if (!printerId) return null

  const { data, error, loading, calibrating, reload, calibrate } = useBedmeshState(printerId)

  return (
    <section className="drawer-section">
      <h3>Bed mesh</h3>

      {/* Toolbar: Refresh and Calibrate buttons */}
      <div className="file-toolbar" style={{ marginBottom: 8 }}>
        <button
          onClick={() => {
            void reload()
          }}
          disabled={loading}
          aria-label="Refresh bed mesh"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
        <button
          onClick={() => {
            void calibrate()
          }}
          disabled={calibrating}
          aria-label="Calibrate bed mesh"
        >
          {calibrating ? 'Calibrating…' : 'Calibrate'}
        </button>
      </div>

      {/* Error state */}
      {error && <div style={{ color: 'var(--color-danger)', marginBottom: 8 }} aria-live="polite">{error}</div>}

      {/* Loading state */}
      {loading && data === null && <div className="subtle">Loading…</div>}

      {/* Not supported state */}
      {data !== null && !data.supported && (
        <div className="subtle">
          Bed mesh not available. Ensure <code>[bed_mesh]</code> is in printer.cfg and a mesh has been calibrated.
        </div>
      )}

      {/* Mesh visualization (via BedMeshPanel) */}
      {data?.supported && <BedMeshPanel data={data} />}

      {/* Mesh history */}
      {data?.profiles && data.profiles.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="subtle small" style={{ marginBottom: 8 }}>
            Saved profiles ({data.profiles.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.profiles.map((profile) => (
              <div
                key={profile.name}
                style={{
                  padding: '6px 8px',
                  background: profile.name === data.active_profile ? 'var(--bg-3, #2a2a2a)' : 'transparent',
                  borderRadius: 3,
                  fontSize: '0.9rem',
                }}
              >
                <span>{profile.name}</span>
                {profile.name === data.active_profile && <span style={{ marginLeft: 8, color: 'var(--color-success)' }}>active</span>}
                {profile.probed_points !== undefined && <span className="subtle small" style={{ marginLeft: 8 }}>({profile.probed_points} points)</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
})

export default BedmeshDrawer


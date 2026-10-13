/**
 * Mesh visualization controls: view modes, profile selection, rendering options
 */

import React from 'react'

type ViewMode = '2d' | '3d'
type RenderMode = 'solid' | 'wireframe' | 'transparent'

interface MeshControlsProps {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  renderMode: RenderMode
  onRenderModeChange: (mode: RenderMode) => void
  selectedProfile: string
  profiles: Array<{ name: string; isActive?: boolean }>
  onProfileChange: (profileName: string) => void
  onRefresh?: () => void
  onCalibrate?: () => void
  isCalibrating?: boolean
  canCalibrate?: boolean
}

export const MeshControls: React.FC<MeshControlsProps> = ({
  viewMode,
  onViewModeChange,
  renderMode,
  onRenderModeChange,
  selectedProfile,
  profiles,
  onProfileChange,
  onRefresh,
  onCalibrate,
  isCalibrating = false,
  canCalibrate = true,
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* View mode toggle */}
      <div>
        <label style={{ display: 'block', marginBottom: 8 }}>
          <span className="subtle small">View</span>
        </label>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['2d', '3d'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => onViewModeChange(mode)}
              style={{
                flex: 1,
                padding: '8px 12px',
                borderRadius: 'var(--radius-sm)',
                border: viewMode === mode ? '1px solid var(--accent-border)' : '1px solid var(--border-default)',
                backgroundColor: viewMode === mode ? 'var(--accent-bg)' : 'transparent',
                color: viewMode === mode ? 'var(--text-primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '0.875rem',
                fontWeight: viewMode === mode ? 500 : 400,
                transition: 'all 150ms var(--ease-snappy)',
              }}
            >
              {mode === '2d' ? 'Heatmap' : '3D Mesh'}
            </button>
          ))}
        </div>
      </div>

      {/* Render mode toggle (3D only) */}
      {viewMode === '3d' && (
        <div>
          <label style={{ display: 'block', marginBottom: 8 }}>
            <span className="subtle small">Render mode</span>
          </label>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(['solid', 'wireframe', 'transparent'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => onRenderModeChange(mode)}
                style={{
                  padding: '6px 10px',
                  borderRadius: 'var(--radius-sm)',
                  border: renderMode === mode ? '1px solid var(--accent-border)' : '1px solid var(--border-default)',
                  backgroundColor: renderMode === mode ? 'var(--accent-bg)' : 'transparent',
                  color: renderMode === mode ? 'var(--text-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                  fontWeight: renderMode === mode ? 500 : 400,
                  transition: 'all 150ms var(--ease-snappy)',
                  whiteSpace: 'nowrap',
                }}
              >
                {mode === 'solid' ? 'Solid' : mode === 'wireframe' ? 'Wire' : 'Transparent'}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Profile selector */}
      {profiles.length > 0 && (
        <div>
          <label htmlFor="mesh-profile-select" style={{ display: 'block', marginBottom: 8 }}>
            <span className="subtle small">Profile</span>
          </label>
          <select
            id="mesh-profile-select"
            value={selectedProfile}
            onChange={(e) => onProfileChange(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 10px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-default)',
              backgroundColor: 'var(--bg-input)',
              color: 'var(--text-primary)',
              cursor: 'pointer',
              fontSize: '0.9rem',
            }}
          >
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name} {p.isActive ? '(active)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8, flexDirection: 'column' }}>
        <button
          onClick={() => onRefresh?.()}
          style={{
            width: '100%',
            padding: '8px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-default)',
            backgroundColor: 'transparent',
            color: 'var(--text-primary)',
            cursor: 'pointer',
            fontSize: '0.9rem',
            transition: 'all 150ms var(--ease-snappy)',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--surface-overlay)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent';
          }}
        >
          ↻ Refresh
        </button>

        {onCalibrate && (
          <button
            onClick={onCalibrate}
            disabled={!canCalibrate || isCalibrating}
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--accent-border)',
              backgroundColor: canCalibrate && !isCalibrating ? 'var(--accent-bg)' : 'var(--surface-l2)',
              color: canCalibrate && !isCalibrating ? 'var(--text-primary)' : 'var(--text-secondary)',
              cursor: canCalibrate && !isCalibrating ? 'pointer' : 'not-allowed',
              fontSize: '0.9rem',
              fontWeight: 500,
              transition: 'all 150ms var(--ease-snappy)',
              opacity: canCalibrate && !isCalibrating ? 1 : 0.6,
            }}
          >
            {isCalibrating ? 'Calibrating...' : 'Calibrate Mesh'}
          </button>
        )}
      </div>

      {/* Legend */}
      <div
        style={{
          padding: '10px',
          backgroundColor: 'var(--surface-overlay)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.8rem',
          color: 'var(--text-secondary)',
          lineHeight: 1.5,
        }}
      >
        <div style={{ marginBottom: 6 }}>
          <strong>Controls:</strong>
        </div>
        <div>
          {viewMode === '3d' ? (
            <>
              <div>• <strong>Rotate:</strong> Left-click + drag</div>
              <div>• <strong>Pan:</strong> Right-click + drag</div>
              <div>• <strong>Zoom:</strong> Scroll wheel</div>
            </>
          ) : (
            <div>• Darker blue = lower height, Darker red = higher height</div>
          )}
        </div>
      </div>
    </div>
  )
}
